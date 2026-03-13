# windows.py
import re

BASE_URL = "https://www.pazzo.com.tw"

def collect_product_urls(page, category):
    """
    從分類頁收集「parent 商品頁」URL
    e.g. /market/n/24074
    """
    product_urls = []
    seen_parent_ids = set()

    cards = page.locator("a[href^='/zh-tw/market/n/']")

    print(f"🔎 [{category}] raw links: {cards.count()}")

    for i in range(cards.count()):
        href = cards.nth(i).get_attribute("href")
        if not href or href.startswith("javascript"):
            continue

        # 只取 parent id（數字）
        m = re.match(r"/zh-tw/market/n/(\d+)", href)
        if not m:
            continue

        parent_id = m.group(1)
        if parent_id in seen_parent_ids:
            continue

        seen_parent_ids.add(parent_id)
        product_urls.append(f"{BASE_URL}/zh-tw/market/n/{parent_id}")

    print(f"✅ [{category}] unique parents: {len(product_urls)}")
    return product_urls
