import json
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "https://www.pazzo.com.tw"

# ========= 設定 =========
CATEGORY = "shortsleeve"
CATEGORY_URL = "https://www.pazzo.com.tw/zh-tw/category/shop/tops/shortsleeve"
OUT_JSON = Path("pazzo_shortsleeve.json")


# ========= 工具 =========
def extract_parent_id(url: str) -> str:
    # https://www.pazzo.com.tw/zh-tw/market/n/24296/L -> 24296
    return url.split("/n/")[1].split("/")[0]


def collect_product_urls(page):
    """
    從分類頁抓商品連結，只保留 parent 層級
    /market/n/24296
    """
    links = page.locator("a[href^='/zh-tw/market/n/']")
    seen_parent = set()
    results = []

    for i in range(links.count()):
        href = links.nth(i).get_attribute("href")
        if not href or href.startswith("javascript"):
            continue

        parent_id = extract_parent_id(href)
        if parent_id in seen_parent:
            continue

        seen_parent.add(parent_id)
        results.append(f"{BASE}/zh-tw/market/n/{parent_id}")

    print(f"🧩 Unique parent products: {len(results)}")
    return results


def get_product_only_image_url(page):
    """
    只抓商品純物照：
    div.position-relative img.img-fluid
    → 倒數第三張
    """
    page.wait_for_timeout(1000)

    imgs = page.locator("div.position-relative img.img-fluid")
    cnt = imgs.count()

    if cnt == 0:
        return None

    target = imgs.nth(cnt - 3) if cnt >= 3 else imgs.nth(cnt - 1)
    return target.get_attribute("src") or target.get_attribute("data-src")


# ========= 主程式 =========
def main():
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        print("▶ Open category:", CATEGORY_URL)
        page.goto(CATEGORY_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2000)

        product_urls = collect_product_urls(page)

        for idx, product_url in enumerate(product_urls, start=1):
            print(f"\n▶ [{idx}/{len(product_urls)}] {product_url}")
            page.goto(product_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(1500)

            parent_id = extract_parent_id(product_url)

            # 商品名稱
            product_name = page.locator("h1.product-title").first.inner_text()

            # 顏色列表
            color_items = page.locator("div.product-color.shop-product-color ul li")
            print(f"   🎨 colors: {color_items.count()}")

            for i in range(color_items.count()):
                li = color_items.nth(i)
                img = li.locator("img")

                color_name = img.get_attribute("alt") or img.get_attribute("title")

                # 點顏色 → 觸發圖片切換
                li.click()
                page.wait_for_timeout(800)

                image_url = get_product_only_image_url(page)

                results.append({
                    "category": CATEGORY,
                    "sku_id": f"PAZZO-{parent_id}-{color_name}",
                    "parent_id": parent_id,
                    "brand": "PAZZO",
                    "product_name": product_name,
                    "product_url": product_url,
                    "color_label": color_name,
                    "image_url": image_url,
                })

        browser.close()

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print("\n✅ Done")
    print(f"📄 JSON saved -> {OUT_JSON.resolve()}")


if __name__ == "__main__":
    main()
