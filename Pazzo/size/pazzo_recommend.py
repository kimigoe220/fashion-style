import os
import re
import math
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client, Client


# ========== 設定 ==========
load_dotenv(Path(__file__).parent / ".env")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()

# 你目前用的是 pazzo_tryon_reports；若你要改成 product_fit_data，把這裡換掉即可
TABLE = "pazzo_tryon_reports"

# KNN 參數
TOP_K = 15
HEIGHT_WEIGHT_RATIO = 1.0  # 身高/體重距離權重比例（你可微調）


def get_supabase() -> Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("缺少 SUPABASE_URL / SUPABASE_KEY，請確認 .env 內容。")
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def product_code_from_url(url: str) -> Optional[str]:
    m = re.search(r"/n/(\d+)", url or "")
    return m.group(1) if m else None


def _safe_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(x)
    except Exception:
        return None


def _distance(user_h: float, user_w: float, row_h: float, row_w: float) -> float:
    # 歐式距離（可調權重）
    dh = (user_h - row_h) * HEIGHT_WEIGHT_RATIO
    dw = (user_w - row_w)
    return math.sqrt(dh * dh + dw * dw)


def fetch_tryon_rows(sb: Client, product_code: str) -> List[Dict[str, Any]]:
    # 只撈用得到的欄位（快）
    resp = (
        sb.table(TABLE)
        .select("product_code, height_cm, weight_kg, recommended_size, available_size_list, category, url")
        .eq("product_code", product_code)
        .execute()
    )

    data = getattr(resp, "data", None)
    if data is None and isinstance(resp, dict):
        data = resp.get("data")
    return data or []


def _normalize_sizes_list(x: Any) -> List[str]:
    if x is None:
        return []
    if isinstance(x, list):
        return [str(s).strip() for s in x if str(s).strip()]
    # 有些人會存成字串
    if isinstance(x, str):
        # 例如 "['S','M']" 或 "S,M"
        if x.strip().startswith("["):
            # 粗略 parse
            return [t.strip(" '\"\n\r\t") for t in re.split(r"[,\[\]]+", x) if t.strip(" '\"\n\r\t")]
        return [t.strip() for t in x.split(",") if t.strip()]
    return []


def recommend_size_for_product(
    product_code: str,
    user_height_cm: float,
    user_weight_kg: float,
    top_k: int = TOP_K
) -> Dict[str, Any]:
    sb = get_supabase()
    rows = fetch_tryon_rows(sb, product_code)

    if not rows:
        return {
            "ok": False,
            "product_code": product_code,
            "reason": "找不到此商品的試穿報告資料（Supabase 該 product_code 沒有 rows）。"
        }

    # 取可用尺寸（同商品多筆 rows 可能重複，取 union）
    available_sizes = set()
    category = None
    url = None
    for r in rows:
        category = category or r.get("category")
        url = url or r.get("url")
        for s in _normalize_sizes_list(r.get("available_size_list")):
            available_sizes.add(s)

    # 建距離清單
    scored: List[Tuple[float, Dict[str, Any]]] = []
    for r in rows:
        rh = _safe_float(r.get("height_cm"))
        rw = _safe_float(r.get("weight_kg"))
        size = (r.get("recommended_size") or "").strip()

        if rh is None or rw is None or not size:
            continue

        d = _distance(user_height_cm, user_weight_kg, rh, rw)
        scored.append((d, r))

    if not scored:
        return {
            "ok": False,
            "product_code": product_code,
            "reason": "此商品有資料，但可用來比對的 height/weight/recommended_size 不完整。"
        }

    scored.sort(key=lambda x: x[0])
    neighbors = scored[: min(top_k, len(scored))]

    # 距離加權投票：weight = 1/(d+eps)
    eps = 1e-6
    votes: Dict[str, float] = {}
    raw_counts: Dict[str, int] = {}

    for d, r in neighbors:
        s = str(r["recommended_size"]).strip()
        w = 1.0 / (d + eps)
        votes[s] = votes.get(s, 0.0) + w
        raw_counts[s] = raw_counts.get(s, 0) + 1

    # 先挑最高分
    ranked = sorted(votes.items(), key=lambda kv: kv[1], reverse=True)

    # 若有 available_sizes，優先選在可用尺寸內的最高分
    picked = None
    if available_sizes:
        for s, _ in ranked:
            if s in available_sizes:
                picked = s
                break
    if picked is None:
        picked = ranked[0][0]

    # 給 2 個備選（同樣考慮 available_sizes）
    alternatives: List[str] = []
    for s, _ in ranked:
        if s == picked:
            continue
        if available_sizes and s not in available_sizes:
            continue
        alternatives.append(s)
        if len(alternatives) >= 2:
            break

    return {
        "ok": True,
        "brand": "PAZZO",
        "product_code": product_code,
        "category": category,
        "url": url,
        "user": {"height_cm": user_height_cm, "weight_kg": user_weight_kg},
        "recommended_size": picked,
        "alternatives": alternatives,
        "available_size_list": sorted(list(available_sizes)),
        "neighbors_used": len(neighbors),
        "top_votes": [{"size": s, "score": round(score, 4), "count": raw_counts.get(s, 0)} for s, score in ranked[:5]],
        "nearest_examples": [
            {
                "distance": round(d, 4),
                "height_cm": _safe_float(r.get("height_cm")),
                "weight_kg": _safe_float(r.get("weight_kg")),
                "recommended_size": (r.get("recommended_size") or "").strip(),
            }
            for d, r in neighbors[:5]
        ],
    }


def main():
    print(f"Using table: {TABLE}")
    print("你可以輸入 product_code（例如 24074）或商品網址（.../market/n/24074）\n")

    product = input("輸入 product_code 或商品網址: ").strip()
    if product.startswith("http"):
        pc = product_code_from_url(product)
        if not pc:
            raise ValueError("網址解析不到 /n/數字，請確認是商品頁網址。")
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
    if result.get("url"):
        print(f"url: {result['url']}")
    print(f"user: {result['user']}")
    print(f"✅ recommended_size: {result['recommended_size']}")
    if result["alternatives"]:
        print(f"alternatives: {result['alternatives']}")
    if result["available_size_list"]:
        print(f"available_size_list: {result['available_size_list']}")
    print(f"neighbors_used: {result['neighbors_used']}")
    print("top_votes:", result["top_votes"])
    print("nearest_examples:", result["nearest_examples"])


if __name__ == "__main__":
    main()