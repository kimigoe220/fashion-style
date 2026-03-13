import os
import re
import math
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client, Client


# =====================
# 設定
# =====================
load_dotenv(Path(__file__).parent / ".env")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()

TABLE = "lativ_recommend"

TOP_K = 15
HEIGHT_WEIGHT_RATIO = 1.0  # 身高/體重距離權重比例（可微調）


# =====================
# Supabase
# =====================
def get_supabase() -> Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("缺少 SUPABASE_URL / SUPABASE_KEY，請確認 .env 內容。")
    return create_client(SUPABASE_URL, SUPABASE_KEY)


# =====================
# Helpers
# =====================
def product_code_from_url(url: str) -> Optional[str]:
    """
    支援：
    - https://www.lativ.com.tw/product/700220410
    - ...?xxx 也可
    """
    m = re.search(r"/product/(\d+)", url or "")
    return m.group(1) if m else None


def _safe_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(x)
    except Exception:
        return None


def _distance(user_h: float, user_w: float, row_h: float, row_w: float) -> float:
    dh = (user_h - row_h) * HEIGHT_WEIGHT_RATIO
    dw = (user_w - row_w)
    return math.sqrt(dh * dh + dw * dw)


def _normalize_sizes_list(x: Any) -> List[str]:
    """
    available_size_list 可能是 list 或字串
    """
    if x is None:
        return []
    if isinstance(x, list):
        return [str(s).strip().upper() for s in x if str(s).strip()]
    if isinstance(x, str):
        s = x.strip()
        if s.startswith("["):
            # 粗略 parse: ["S","M"] or ['S','M']
            parts = re.split(r"[\[\],]+", s)
            return [p.strip(" '\"\n\r\t").upper() for p in parts if p.strip(" '\"\n\r\t")]
        # "S,M,L"
        return [p.strip().upper() for p in s.split(",") if p.strip()]
    return []


def _ensure_list(x: Any) -> List[Any]:
    return x if isinstance(x, list) else []


# =====================
# Read from lativ_recommend
# =====================
def fetch_product_row(sb: Client, product_code: str) -> Optional[Dict[str, Any]]:
    resp = (
        sb.table(TABLE)
        .select("brand, product_code, category, product_name, available_size_list, tryon_samples, data")
        .eq("product_code", product_code)
        .limit(1)
        .execute()
    )

    data = getattr(resp, "data", None)
    if data is None and isinstance(resp, dict):
        data = resp.get("data")
    rows = data or []
    return rows[0] if rows else None


# =====================
# Recommendation
# =====================
def recommend_size_for_product(
    product_code: str,
    user_height_cm: float,
    user_weight_kg: float,
    top_k: int = TOP_K,
) -> Dict[str, Any]:
    sb = get_supabase()
    row = fetch_product_row(sb, product_code)

    if not row:
        return {"ok": False, "product_code": product_code, "reason": "找不到此商品（lativ_recommend 無此 product_code）。"}

    available_sizes = set(_normalize_sizes_list(row.get("available_size_list")))
    tryon_samples = _ensure_list(row.get("tryon_samples"))

    # 如果 tryon_samples 沒資料，就不能做身高體重推薦
    if not tryon_samples:
        return {
            "ok": False,
            "product_code": product_code,
            "reason": "此商品沒有 tryon_samples（真人試穿資料），無法依身高體重推薦。",
            "available_size_list": sorted(list(available_sizes)),
        }

    scored: List[Tuple[float, Dict[str, Any]]] = []
    for r in tryon_samples:
        rh = _safe_float(r.get("height_cm"))
        rw = _safe_float(r.get("weight_kg"))
        size = (r.get("recommended_size") or "").strip().upper()

        if rh is None or rw is None or not size:
            continue

        d = _distance(user_height_cm, user_weight_kg, rh, rw)
        scored.append((d, r))

    if not scored:
        return {
            "ok": False,
            "product_code": product_code,
            "reason": "tryon_samples 有資料，但可用來比對的 height/weight/recommended_size 不完整。",
            "available_size_list": sorted(list(available_sizes)),
        }

    scored.sort(key=lambda x: x[0])
    neighbors = scored[: min(top_k, len(scored))]

    # 距離加權投票
    eps = 1e-6
    votes: Dict[str, float] = {}
    raw_counts: Dict[str, int] = {}
    for d, r in neighbors:
        s = str(r.get("recommended_size") or "").strip().upper()
        if not s:
            continue
        w = 1.0 / (d + eps)
        votes[s] = votes.get(s, 0.0) + w
        raw_counts[s] = raw_counts.get(s, 0) + 1

    if not votes:
        return {
            "ok": False,
            "product_code": product_code,
            "reason": "近鄰資料不足以產生投票結果。",
            "available_size_list": sorted(list(available_sizes)),
        }

    ranked = sorted(votes.items(), key=lambda kv: kv[1], reverse=True)

    # ✅ 核心規則：推薦尺寸沒有庫存就不要推薦
    picked = None
    for s, _score in ranked:
        if s in available_sizes:
            picked = s
            break

    if picked is None:
        return {
            "ok": False,
            "brand": row.get("brand") or "LATIV",
            "product_code": product_code,
            "category": row.get("category"),
            "product_name": row.get("product_name"),
            "user": {"height_cm": user_height_cm, "weight_kg": user_weight_kg},
            "reason": "推算出的候選尺寸皆無庫存（available_size_list 不包含任何候選結果），因此不推薦。",
            "available_size_list": sorted(list(available_sizes)),
            "top_votes": [{"size": s, "score": round(score, 4), "count": raw_counts.get(s, 0)} for s, score in ranked[:5]],
        }

    # 備選（同樣要有庫存）
    alternatives: List[str] = []
    for s, _ in ranked:
        if s == picked:
            continue
        if s not in available_sizes:
            continue
        alternatives.append(s)
        if len(alternatives) >= 2:
            break

    data = row.get("data") or {}
    product_url = data.get("product_url") or data.get("url") or ""

    return {
        "ok": True,
        "brand": row.get("brand") or "LATIV",
        "product_code": product_code,
        "category": row.get("category"),
        "product_name": row.get("product_name"),
        "url": product_url,
        "user": {"height_cm": user_height_cm, "weight_kg": user_weight_kg},
        "recommended_size": picked,
        "alternatives": alternatives,
        "available_size_list": sorted(list(available_sizes)),
        "nearest_examples": [
            {
                "distance": round(d, 4),
                "height_cm": _safe_float(r.get("height_cm")),
                "weight_kg": _safe_float(r.get("weight_kg")),
                "recommended_size": (r.get("recommended_size") or "").strip().upper(),
            }
            for d, r in neighbors[:5]
        ],
    }


def main():
    print(f"Using table: {TABLE}")
    print("你可以輸入 product_code（例如 700220410）或商品網址（.../product/700220410）\n")

    product = input("輸入 product_code 或商品網址: ").strip()
    if product.startswith("http"):
        pc = product_code_from_url(product)
        if not pc:
            raise ValueError("網址解析不到 /product/數字，請確認是商品頁網址。")
        product_code = pc
    else:
        product_code = product

    h = float(input("使用者身高 cm（例如 160）: ").strip())
    w = float(input("使用者體重 kg（例如 50）: ").strip())

    result = recommend_size_for_product(product_code, h, w)

    print("\n====== 推薦結果 ======")
    if not result.get("ok"):
        print(result)
        return

    print(f"brand: {result['brand']}")
    print(f"product_code: {result['product_code']}")
    if result.get("category"):
        print(f"category: {result['category']}")
    if result.get("product_name"):
        print(f"product_name: {result['product_name']}")
    if result.get("url"):
        print(f"url: {result['url']}")
    print(f"user: {result['user']}")
    print(f"✅ recommended_size: {result['recommended_size']}")
    if result["alternatives"]:
        print(f"alternatives: {result['alternatives']}")
    print(f"available_size_list: {result['available_size_list']}")
    
    


if __name__ == "__main__":
    main()