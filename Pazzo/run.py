# run.py
import json
from playwright.sync_api import sync_playwright

from windows import collect_product_urls
from product import parse_product_page   # 你原本的 layer2 解析函式

# ====== 分類頁（layer1） ======
CATEGORY_PAGES = {
    # "shortsleeve": "https://www.pazzo.com.tw/zh-tw/category/shop/tops/shortsleeve",
    # "longsleeve": "https://www.pazzo.com.tw/zh-tw/category/shop/tops/longsleeve",
    # "coat": "https://www.pazzo.com.tw/zh-tw/category/shop/tops/coat",
    # "knitwear": "https://www.pazzo.com.tw/zh-tw/category/shop/tops/knitwear",
    # "blouses": "https://www.pazzo.com.tw/zh-tw/category/shop/tops/blouses",
    "shoes":"https://www.pazzo.com.tw/zh-tw/category/shop/accessories/shoes",

}

OUTPUT_JSON = "pazzo_shoes.json"

all_products = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    for category, category_url in CATEGORY_PAGES.items():
        print("\n" + "=" * 60)
        print(f"📂 Collecting category: {category}")
        print(f"🔗 URL: {category_url}")

        page.goto(category_url, timeout=60000)
        page.wait_for_timeout(3000)

        product_urls = collect_product_urls(page, category)

        print(f"📦 [{category}] parent products: {len(product_urls)}")

        for idx, product_url in enumerate(product_urls, start=1):
            print(f"➡️ [{idx}/{len(product_urls)}] Crawling {product_url}")

            try:
                skus = parse_product_page(page, product_url, category)
                all_products.extend(skus)
                print(f"   ✅ SKUs: {len(skus)}")
            except Exception as e:
                print(f"   ❌ Failed: {e}")

    browser.close()

# ====== 輸出 JSON ======
with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
    json.dump(all_products, f, ensure_ascii=False, indent=2)

print("\n🎉 Done")
print(f"📄 Total SKUs: {len(all_products)}")
print(f"💾 Saved to: {OUTPUT_JSON}")
