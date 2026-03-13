# run.py
import re
import json
import time
from playwright.sync_api import sync_playwright, TimeoutError

# =========================
# Category 設定
# =========================
CATEGORIES = [
    {
        "category": "overalls",
        "url": "https://www.lativ.com.tw/category/MEN/bottoms/overalls",
    },
    {
        "category": "shorts",
        "url": "https://www.lativ.com.tw/category/MEN/bottoms/shorts",
    },
    {
        "category": "jeans",
        "url": "https://www.lativ.com.tw/category/MEN/bottoms/jeans",
    },
    {
        "category": "trousers",
        "url": "https://www.lativ.com.tw/category/MEN/bottoms/trousers",
    },
    {
        "category": "suit_pants",
        "url": "https://www.lativ.com.tw/category/MEN/bottoms/Suit_pants",
    },
    {
        "category": "cuffed_trousers",
        "url": "https://www.lativ.com.tw/category/MEN/bottoms/cuffed_trousers",
    },
   
]

BASE_URL = "https://www.lativ.com.tw"
OUTPUT_JSON = "lativ_men_under.json"

# =========================
# ⚡ 全站去重（加速關鍵）
# =========================
SEEN_PRODUCT_NAMES = set()
SEEN_PARENT_IDS = set()

# =========================
# Utils
# =========================
def extract_parent_id(url: str):
    m = re.search(r"/product/(\d+)", url)
    return m.group(1) if m else None


def extract_color_from_name(name: str):
    # 絲光棉寬鬆圓領長版T恤-女（米色－S）
    m = re.search(r"（(.+?)－", name)
    return m.group(1) if m else None


def safe_int(text):
    if not text:
        return None
    text = re.sub(r"[^\d]", "", text)
    return int(text) if text else None


# =========================
# layer 1：索引頁
# =========================
def extract_product_urls(page, category_url):
    page.goto(category_url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_selector("a[href^='/product/']", timeout=15000)

    links = page.locator("a[href^='/product/']")
    urls = set()

    for i in range(links.count()):
        href = links.nth(i).get_attribute("href")
        if href:
            urls.add(BASE_URL + href.split("?")[0])

    return list(urls)


# =========================
# layer 2：商品頁
# =========================
def parse_product_page(page, url, category):
    parent_id = extract_parent_id(url)
    if not parent_id or parent_id in SEEN_PARENT_IDS:
        print("  ↪ 同 parent_id，跳過")
        return []

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector("div.product-info", timeout=15000)
    except TimeoutError:
        print("  ⚠ 商品頁 timeout")
        return []

    title_loc = page.locator("div.product-info h1.title")
    if title_loc.count() == 0:
        print("  ⚠ 無商品名稱")
        return []

    name_with_color = title_loc.first.inner_text().strip()
    product_name = name_with_color.split("（")[0].strip()


    name_with_color = title_loc.first.inner_text().strip()
    product_name = name_with_color.split("（")[0].strip()

    # ⭐ 同名商品全站只抓一次（速度救星）
    if product_name in SEEN_PRODUCT_NAMES:
        print(f"  ↪ 同款商品，跳過：{product_name}")
        return []

    SEEN_PRODUCT_NAMES.add(product_name)
    SEEN_PARENT_IDS.add(parent_id)

    current_price = safe_int(page.locator(".price").first.inner_text())
    origin_loc = page.locator(".origin-price")
    original_price = (
        safe_int(origin_loc.first.inner_text())
        if origin_loc.count() > 0
        else current_price
    )

    size_buttons = page.locator("button.size-button")
    sizes = [
        size_buttons.nth(i).inner_text().strip()
        for i in range(size_buttons.count())
    ]

    rows = []

    color_buttons = page.locator("div.grids-color button")

    for i in range(color_buttons.count()):
        try:
            color_buttons.nth(i).click()
            page.wait_for_timeout(250)
        except:
            continue

        name_with_color = title_loc.first.inner_text().strip()
        color = extract_color_from_name(name_with_color)
        if not color:
            continue

        # 優先抓「點了顏色後的主商品圖」
        img_src = None

        # 1. 抓 URL 裡含 cdx.lativ.com.tw/upload-v1 的第一張圖
        img_candidate = page.locator('img[src*="cdx.lativ.com.tw/upload-v1"]')

        if img_candidate.count() > 0:
            img_src = img_candidate.first.get_attribute("src")
        else:
            # 2. fallback：抓 cursor-pointer class
            try:
                img_src = page.locator("img.cursor-pointer").first.get_attribute("src")
            except:
                img_src = None

        sku_id = f"lativ-{parent_id}-{color}"

        rows.append({
            "sku_id": sku_id,
            "brand": "LATIV",
            "parent_id": parent_id,
            "sku_url": url,
            "category": category,
            "product_name": product_name,
            "img_path": img_src,
            "color_label": color,
            "original_price": original_price,
            "current_price": current_price,
            "full_size_list": sizes,
            "available_list": sizes,
        })

    return rows


# =========================
# main
# =========================
def main():
    start = time.time()
    all_rows = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for cat in CATEGORIES:
            category = cat["category"]
            url = cat["url"]

            print(f"\n=== Category: {category} ===")
            product_urls = extract_product_urls(page, url)
            print(f"🔗 {len(product_urls)} 個商品")

            for idx, product_url in enumerate(product_urls, 1):
                print(f"[{idx}/{len(product_urls)}] {product_url}")
                rows = parse_product_page(page, product_url, category)
                all_rows.extend(rows)

        browser.close()

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(all_rows, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 完成，共 {len(all_rows)} 筆 SKU")
    print(f"⏱ 耗時 {round(time.time() - start, 1)} 秒")
    print(f"📄 輸出：{OUTPUT_JSON}")


if __name__ == "__main__":
    main()
