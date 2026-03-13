from dotenv import load_dotenv
load_dotenv()

import os
from supabase import create_client


SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]  # 用 publishable/anon key

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote, urljoin

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout



# =========================
# Paths / Settings
# =========================
HERE = Path(__file__).resolve().parent
JSON_PATH = HERE.parent / "uniqlo_sweat.json"   # json 在上一層
OUT_IMG_DIR = HERE / "sizechart_images"
OUT_IMG_DIR.mkdir(parents=True, exist_ok=True)

# 是否下載尺寸表主圖（你要省時間可改 False）
DOWNLOAD_IMAGE = True

# 每筆之間稍微休息，避免被擋（可調）
SLEEP_SEC = 0.3

SIZE_ORDER = ["XXS", "XS", "S", "M", "L", "XL", "XXL", "3XL"]


# =========================
# Supabase
# =========================
def sb():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("缺少環境變數 SUPABASE_URL / SUPABASE_KEY")
    return create_client(url, key)

def upsert_product_fit_data(
    client,
    product_code: str,
    category: str,
    base_sizes: List[str],
    current_sizes: List[str],
    size_chart: Optional[Dict],
    sizechart_url: str,
    image_key: Optional[str],
):
    payload = {
        "product_code": product_code,
        "category": category,
        "base_sizes": base_sizes,
        "current_sizes": current_sizes,
        "size_chart": size_chart,
        "sizechart_url": sizechart_url,
        "sizechart_image_key": image_key,
        # updated_at 若你表有 trigger 可省略；這裡不強制寫 now()
    }
    return (
        client.table("product_fit_data")
        .upsert(payload, on_conflict="product_code")
        .execute()
    )


# =========================
# Build size chart URL (你已驗證)
# =========================
def build_uniqlo_sizechart_url(product_code: str) -> str:
    path = f"/hmall/test/{product_code}/zh_TW/sizeAndTryOn.html"
    return "https://www.uniqlo.com/tw/zh_TW/product-size-chart.html?sizeChart=" + quote(path, safe="")


# =========================
# Parse table -> jsonb
# =========================
def parse_uniqlo_size_table(table_rows: List[List[str]]) -> Optional[Dict]:
    """
    input example:
    [
      ['', 'XS','S','M','L'],
      ['衣長','51','52','53','54'],
      ['胸寬','55','57','59','61'],
      ...
    ]
    output:
    {
      "sizes": ["XS","S","M","L"],
      "measures_cm": {
        "衣長": {"XS":51, "S":52, ...},
        ...
      }
    }
    """
    if not table_rows or len(table_rows) < 2:
        return None

    header = table_rows[0]
    sizes = [h.strip().upper() for h in header[1:] if str(h).strip()]
    if not sizes:
        return None

    measures = {}
    for row in table_rows[1:]:
        if len(row) < 2:
            continue
        name = str(row[0]).strip()
        if not name:
            continue

        values = row[1:1 + len(sizes)]
        m = {}
        for s, v in zip(sizes, values):
            v = str(v).strip()
            if v == "":
                continue
            try:
                num = float(v)
                if abs(num - int(num)) < 1e-9:
                    num = int(num)
                m[s] = num
            except ValueError:
                m[s] = v
        if m:
            measures[name] = m

    return {"sizes": sizes, "measures_cm": measures}


# =========================
# Scrape helpers
# =========================
def extract_tables(page) -> List[List[List[str]]]:
    tables = []
    for t in page.query_selector_all("table"):
        rows = []
        for r in t.query_selector_all("tr"):
            cells = [c.inner_text().strip() for c in r.query_selector_all("th,td")]
            if cells:
                rows.append(cells)
        if rows:
            tables.append(rows)
    return tables

def download_largest_image_as_product_id(page, product_code: str) -> Optional[Path]:
    imgs = page.query_selector_all("img")
    candidates: List[Tuple[int, str]] = []

    for img in imgs:
        src = img.get_attribute("src")
        if not src:
            continue
        abs_url = urljoin(page.url, src)
        try:
            w = page.evaluate("(el) => el.naturalWidth || el.width", img)
            h = page.evaluate("(el) => el.naturalHeight || el.height", img)
            if not w or not h:
                continue
            candidates.append((int(w) * int(h), abs_url))
        except Exception:
            continue

    if not candidates:
        return None

    candidates.sort(reverse=True, key=lambda x: x[0])
    img_url = candidates[0][1]

    resp = page.context.request.get(img_url)
    if not resp.ok:
        return None

    fpath = OUT_IMG_DIR / f"{product_code}.jpg"
    fpath.write_bytes(resp.body())
    return fpath


# =========================
# Main
# =========================
def main():
    if not JSON_PATH.exists():
        raise FileNotFoundError(f"找不到 JSON：{JSON_PATH}")

    items = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    client = sb()

    total = len(items)
    ok = 0
    fail = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()

        for idx, it in enumerate(items, 1):
            product_code = it.get("parent_id")  # u00000000...
            if not product_code:
                print(f"[{idx}/{total}] 缺 parent_id，跳過")
                fail += 1
                continue

            # category：你這份 json 是 blouses，可先預設 top；若 json 有 category 欄位就用它
            category = it.get("category") or "top"

            base_sizes = [s.upper() for s in (it.get("full_size_list") or it.get("base_sizes") or [])]
            current_sizes = [s.upper() for s in (it.get("available_list") or it.get("current_sizes") or [])]

            sizechart_url = build_uniqlo_sizechart_url(product_code)

            chart_page = context.new_page()
            try:
                chart_page.goto(sizechart_url, wait_until="domcontentloaded", timeout=60000)
                chart_page.wait_for_timeout(600)

                # 抓表
                tables = extract_tables(chart_page)
                size_chart_json = parse_uniqlo_size_table(tables[0]) if tables else None

                # 抓圖（可選）
                image_key = None
                if DOWNLOAD_IMAGE:
                    img_path = download_largest_image_as_product_id(chart_page, product_code)
                    image_key = f"{product_code}.jpg" if img_path else None

                # upsert
                upsert_product_fit_data(
                    client=client,
                    product_code=product_code,
                    category=category,
                    base_sizes=base_sizes,
                    current_sizes=current_sizes,
                    size_chart=size_chart_json,
                    sizechart_url=sizechart_url,
                    image_key=image_key,
                )

                ok += 1
                print(f"[{idx}/{total}] ✅ upsert OK: {product_code} (tables={len(tables)}, image={bool(image_key)})")

            except PWTimeout:
                fail += 1
                print(f"[{idx}/{total}] ❌ timeout: {product_code}")
            except Exception as e:
                fail += 1
                print(f"[{idx}/{total}] ❌ error: {product_code} -> {e}")
            finally:
                try:
                    chart_page.close()
                except Exception:
                    pass

            time.sleep(SLEEP_SEC)

        browser.close()

    print("\n===== DONE =====")
    print("total:", total)
    print("ok   :", ok)
    print("fail :", fail)


if __name__ == "__main__":
    main()