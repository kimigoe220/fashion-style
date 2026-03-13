import json
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import quote, urljoin

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ----------------------------
# Paths / Settings
# ----------------------------
HERE = Path(__file__).resolve().parent
JSON_PATH = HERE.parent / "uniqlo_easypants.json"      # ✅ json 在上一層
OUT_IMG_DIR = HERE / "sizechart_images"
OUT_IMG_DIR.mkdir(parents=True, exist_ok=True)

LIMIT = 5
SIZE_ORDER = ["XXS", "XS", "S", "M", "L", "XL", "XXL", "3XL"]


# ----------------------------
# Build size chart URL (你已驗證可用)
# ----------------------------
def build_uniqlo_sizechart_url(product_code: str) -> str:
    path = f"/hmall/test/{product_code}/zh_TW/sizeAndTryOn.html"
    return "https://www.uniqlo.com/tw/zh_TW/product-size-chart.html?sizeChart=" + quote(path, safe="")


# ----------------------------
# Recommend heuristic (先可用、之後可再換更精準)
# ----------------------------
def bmi(height_cm: float, weight_kg: float) -> float:
    h = height_cm / 100.0
    return weight_kg / (h * h)

def base_size_by_height(height_cm: float) -> str:
    if height_cm <= 156: return "XS"
    if height_cm <= 160: return "S"
    if height_cm <= 164: return "M"
    if height_cm <= 168: return "L"
    if height_cm <= 172: return "XL"
    return "XXL"

def bmi_shift(b: float) -> int:
    if b < 18.5: return -1
    if b < 22.0: return 0
    if b < 25.0: return +1
    return +2

def pick_three_sizes(height_cm: float, weight_kg: float, full_sizes: List[str]) -> List[str]:
    full_sizes_upper = [s.upper() for s in full_sizes]
    full_sizes_upper = [s for s in SIZE_ORDER if s in full_sizes_upper]
    if not full_sizes_upper:
        return []

    base = base_size_by_height(height_cm)
    shift = bmi_shift(bmi(height_cm, weight_kg))

    def idx(s: str) -> int:
        return SIZE_ORDER.index(s) if s in SIZE_ORDER else 0

    best_i = max(0, min(idx(base) + shift, len(SIZE_ORDER) - 1))

    def nearest_available(i: int) -> int:
        for d in range(0, 8):
            for j in (i - d, i + d):
                if 0 <= j < len(SIZE_ORDER) and SIZE_ORDER[j] in full_sizes_upper:
                    return j
        return i

    best_i = nearest_available(best_i)
    left_i = nearest_available(best_i - 1)
    right_i = nearest_available(best_i + 1)

    picks = []
    for s in [SIZE_ORDER[left_i], SIZE_ORDER[best_i], SIZE_ORDER[right_i]]:
        if s in full_sizes_upper and s not in picks:
            picks.append(s)

    k = 0
    while len(picks) < 3 and k < len(SIZE_ORDER):
        s = SIZE_ORDER[k]
        if s in full_sizes_upper and s not in picks:
            picks.append(s)
        k += 1

    return picks[:3]


# ----------------------------
# Scrape helpers
# ----------------------------
def extract_tables(page):
    """抓出目前頁面所有 table rows（若該頁用 div 模擬表格，這會抓不到，但不影響抓圖）"""
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

def download_largest_image_as_product_id(page, product_id: str) -> Optional[Path]:
    """從目前頁面挑最大解析度 img 下載，存成 sizechart_images/{product_id}.jpg"""
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

    fpath = OUT_IMG_DIR / f"{product_id}.jpg"
    fpath.write_bytes(resp.body())
    return fpath


# ----------------------------
# Main
# ----------------------------
def main():
    if not JSON_PATH.exists():
        raise FileNotFoundError(f"找不到 JSON：{JSON_PATH}")

    items = json.loads(JSON_PATH.read_text(encoding="utf-8"))

    height_cm = float(input("請輸入身高(cm): ").strip())
    weight_kg = float(input("請輸入體重(kg): ").strip())
    print(f"\n你的 BMI = {bmi(height_cm, weight_kg):.1f}\n")

    test_items = items[:LIMIT]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        for idx, it in enumerate(test_items, 1):
            product_code = it.get("parent_id")  # ✅ 你的 parent_id 就是 u00000000....
            sku_url = it.get("sku_url", "")
            product_name = it.get("product_name", "")
            color = it.get("color_label", "")

            available_list = [s.upper() for s in it.get("available_list", [])]
            full_sizes = [s.upper() for s in it.get("full_size_list", [])]

            print(f"===== ({idx}/{LIMIT}) {product_code} | {product_name} | {color} =====")

            # 先算三個推薦尺寸 + 庫存過濾
            recommended3 = pick_three_sizes(height_cm, weight_kg, full_sizes=full_sizes)
            in_stock_reco = [s for s in recommended3 if s in available_list]

            if not in_stock_reco:
                print(f"不推薦：推薦尺寸 {recommended3} 皆無庫存（庫存={available_list}）\n")
                continue

            if not product_code:
                print("缺 product_code(parent_id)，跳過\n")
                continue

            # ✅ 直接組尺寸表網址（不再點商品頁）
            chart_url = build_uniqlo_sizechart_url(product_code)
            print("sizechart_url:", chart_url)

            chart_page = context.new_page()
            try:
                chart_page.goto(chart_url, wait_until="domcontentloaded", timeout=60000)
                chart_page.wait_for_timeout(800)
            except PWTimeout:
                print("尺寸表頁超時，跳過\n")
                chart_page.close()
                continue

            # 抓主圖 + table
            img_path = download_largest_image_as_product_id(chart_page, product_code)
            tables = extract_tables(chart_page)

            print("商品頁:", sku_url)
            print("推薦尺寸（3個）:", recommended3)
            print("可買尺寸（推薦且有庫存）:", in_stock_reco)
            print("尺寸表主圖:", str(img_path) if img_path else "未抓到")
            print("尺寸表 table 數量:", len(tables))

            if tables:
                print("table preview:")
                for r in tables[0][:6]:
                    print("  ", r)

            print()
            chart_page.close()

        browser.close()


if __name__ == "__main__":
    main()