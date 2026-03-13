from playwright.sync_api import sync_playwright
import re
import json
import os
from typing import List, Dict, Any, Optional
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client, Client

# =========================================================
# 0) 讀取 .env
# =========================================================
load_dotenv(Path(__file__).parent / ".env")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()

SUPABASE_TABLE = "pazzo_tryon_reports"
BRAND = "PAZZO"

# 從 size.py 的上一層讀 pazzo_topwears.json
JSON_PATH = (Path(__file__).resolve().parent.parent / "pazzo_shoes.json")


# =========================================================
# 1) 共用工具
# =========================================================
def extract_table(locator):
    rows = []
    for tr in locator.locator("tr").all():
        cells = [c.inner_text().strip() for c in tr.locator("th, td").all()]
        if cells:
            rows.append(cells)
    return rows


def _to_number(x: str) -> Optional[float]:
    s = (x or "").strip()
    m = re.search(r"(\d+(?:\.\d+)?)", s)
    if not m:
        return None
    num = float(m.group(1))
    if abs(num - int(num)) < 1e-9:
        return int(num)
    return num


# =========================================================
# 2) 試穿報告清洗（已移除 upper_bust_cm / under_bust_cm）
# =========================================================
def clean_tryon_report(tryon_rows: List[List[str]], brand: str) -> List[Dict[str, Any]]:
    if not tryon_rows or len(tryon_rows) < 2:
        return []

    header = [h.strip() for h in tryon_rows[0]]
    header_norm = [re.sub(r"\s+", "", h) for h in header]

    FIELD_MAP = {
        "身高": ("height_cm", "num"),
        "體重": ("weight_kg", "num"),
        "肩寬": ("shoulder_cm", "num"),
        "胸寬": ("bust_cm", "num"),
        "胸圍": ("bust_cm", "num"),
        "腰圍": ("waist_cm", "num"),
        "臀圍": ("hip_cm", "num"),
        "罩杯": ("bra_cup", "text"),
        "建議尺寸": ("recommended_size", "text"),
    }

    keep_cols = []
    for idx, h in enumerate(header_norm):
        if any(x in h for x in ["試穿人員", "身形"]):
            continue
        for zh, (en, typ) in FIELD_MAP.items():
            if zh in h:
                keep_cols.append((idx, en, typ))
                break

    cleaned: List[Dict[str, Any]] = []
    for row in tryon_rows[1:]:
        obj: Dict[str, Any] = {"brand": brand}

        for idx, key, typ in keep_cols:
            if idx >= len(row):
                continue
            raw = (row[idx] or "").strip()
            if not raw:
                continue
            if typ == "text":
                obj[key] = raw
            else:
                v = _to_number(raw)
                if v is not None:
                    obj[key] = v

        # 至少有身高 + 建議尺寸
        if "height_cm" in obj and "recommended_size" in obj:
            cleaned.append(obj)

    return cleaned


# =========================================================
# 3) 用 /n/24074 取 product_code
# =========================================================
def get_product_code_from_url(url: str) -> str:
    m = re.search(r"/n/(\d+)", url)
    if not m:
        raise ValueError(f"網址抓不到 product_code（找不到 /n/數字）：{url}")
    return m.group(1)


# =========================================================
# 4) 從 pazzo_topwears.json 建「商品層級」targets
#    - 以 parent_id 聚合（不分顏色）
#    - category 取第一筆
#    - available_size_list = union(available_list)
#    - url 用 sku_url（取第一筆即可）
# =========================================================
def load_targets_from_pazzo_json(json_path: Path) -> List[Dict[str, Any]]:
    if not json_path.exists():
        raise FileNotFoundError(f"找不到 JSON：{json_path}")

    data = json.loads(json_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("pazzo_topwears.json 預期是 list[dict] 結構")

    by_parent: Dict[str, Dict[str, Any]] = {}

    for item in data:
        if not isinstance(item, dict):
            continue

        parent_id = str(item.get("parent_id") or "").strip()
        sku_url = str(item.get("sku_url") or "").strip()
        category = str(item.get("category") or "").strip()

        avail = item.get("available_list") or []
        if not isinstance(avail, list):
            avail = []

        if not parent_id:
            # 沒 parent_id 就跳過
            continue

        # 初始化
        if parent_id not in by_parent:
            # url：優先用 sku_url（通常是 /n/parent_id）
            url = sku_url or f"https://www.pazzo.com.tw/zh-tw/market/n/{parent_id}"
            by_parent[parent_id] = {
                "product_code": parent_id,
                "url": url,
                "category": category or None,
                "available_size_set": set(),
            }

        # category 若還沒填，補上
        if not by_parent[parent_id].get("category") and category:
            by_parent[parent_id]["category"] = category

        # union available sizes
        for s in avail:
            if isinstance(s, str) and s.strip():
                by_parent[parent_id]["available_size_set"].add(s.strip())

    targets: List[Dict[str, Any]] = []
    for parent_id, obj in by_parent.items():
        size_list = sorted(list(obj["available_size_set"]))
        targets.append({
            "product_code": obj["product_code"],
            "url": obj["url"],
            "category": obj.get("category") or "topwears",
            "available_size_list": size_list,
        })

    if not targets:
        raise ValueError(f"JSON 讀到了，但沒抽到任何商品資料：{json_path}")

    return targets


# =========================================================
# 5) Supabase
# =========================================================
def get_supabase() -> Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("缺少 SUPABASE_URL / SUPABASE_KEY。請確認 .env 已放在 size.py 同層且內容正確。")
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def upsert_tryon_rows(sb: Client, rows: List[Dict[str, Any]]):
    if not rows:
        return

    sb.table(SUPABASE_TABLE).upsert(
        rows,
        on_conflict="product_code,height_cm,weight_kg,bra_cup,recommended_size"
    ).execute()

    print(f"🟩 Supabase upsert 完成：{len(rows)} rows")


# =========================================================
# 6) Playwright：抓試穿報告 + 寫入附加欄位
# =========================================================
def scrape_tryon_for_one(page, url: str) -> List[List[str]]:
    page.goto(url, wait_until="domcontentloaded", timeout=60000)

    # 點「尺寸指南」
    page.locator("li a:has-text('尺寸指南')").first.click()

    # 等尺寸指南內容出現
    page.locator(":text('產品尺寸')").wait_for(timeout=15000)

    # 試穿報告
    tryon_title = page.locator("text=試穿報告")
    if tryon_title.count() == 0:
        return []

    tryon_section = tryon_title.first.locator("xpath=ancestor::*[1]")
    tryon_table = tryon_section.locator("table").first
    tryon_rows = extract_table(tryon_table)
    return tryon_rows


def build_db_rows(
    tryon_rows: List[List[str]],
    product_code: str,
    url: str,
    category: str,
    available_size_list: List[str],
) -> List[Dict[str, Any]]:
    cleaned = clean_tryon_report(tryon_rows, brand=BRAND)

    out_rows: List[Dict[str, Any]] = []
    for r in cleaned:
        row = dict(r)

        # DB 必填 & 你要補的欄位
        row["product_code"] = product_code
        row["brand"] = BRAND
        row["url"] = url
        row["category"] = category
        row["available_size_list"] = available_size_list

        # jsonb snapshot（包含 category/available_size_list）
        payload = dict(row)
        row["data"] = payload

        out_rows.append(row)

    return out_rows


# =========================================================
# 7) main
# =========================================================
def main():
    targets = load_targets_from_pazzo_json(JSON_PATH)
    print(f"✅ 讀入商品數（以 parent_id 去重、不分顏色）：{len(targets)}")

    sb = get_supabase()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        ok, fail, total_rows = 0, 0, 0

        for i, t in enumerate(targets, 1):
            url = t["url"]
            product_code = t["product_code"]
            category = t["category"]
            available_size_list = t["available_size_list"]

            print(f"\n[{i}/{len(targets)}] 抓：{url} | product_code={product_code} | category={category} | avail={available_size_list}")

            try:
                # 保險：若 url 沒有 /n/xxxx，仍以 json parent_id 為主
                tryon_rows = scrape_tryon_for_one(page, url)
                if not tryon_rows:
                    print("ℹ️ 無試穿報告，跳過寫入")
                    ok += 1
                    continue

                rows = build_db_rows(
                    tryon_rows=tryon_rows,
                    product_code=product_code,
                    url=url,
                    category=category,
                    available_size_list=available_size_list,
                )

                if rows:
                    upsert_tryon_rows(sb, rows)
                    total_rows += len(rows)
                    print(f"✅ 寫入 rows={len(rows)}")
                else:
                    print("ℹ️ 試穿報告解析後無有效資料（可能缺 height 或 recommended_size）")

                ok += 1

            except Exception as e:
                print(f"❌ 失敗：{url}\n   原因：{repr(e)}")
                fail += 1
                continue

        browser.close()

    print("\n====== 完成 ======")
    print(f"成功處理商品：{ok} | 失敗商品：{fail} | 寫入試穿報告總筆數：{total_rows}")


if __name__ == "__main__":
    main()