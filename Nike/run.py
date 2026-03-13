from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import json
import re
import time

# ========= 要爬的 Nike 商品網址 =========
URLS = [
    "https://www.nike.com/tw/t/air-rift-Cn9A0eWh/IB8954-200",
    "https://www.nike.com/tw/t/v2k-run-43YfLxpv/IH0388-001",
    "https://www.nike.com/tw/t/air-jordan-mule-9PAPEZZZ/HJ4292-600",
    "https://www.nike.com/tw/t/air-jordan-1-triple-stack-pahhHbBT/HV8288-600",
    "https://www.nike.com/tw/t/air-jordan-1-%E4%B8%AD%E7%AD%92-se-edge-u8YpWQGc/IB7007-107",
    "https://www.nike.com/tw/t/sabrina-3-ep-%E7%B1%83%E7%90%83-G2lc4oD7/HF2882-003",
    "https://www.nike.com/tw/t/vomero-premium-%E8%B7%AF%E8%B7%91-G5MaFK10/IQ8102-100",
    "https://www.nike.com/tw/t/alphafly-3-%E8%B7%AF%E8%B7%91%E7%AB%B6%E9%80%9F-C4VXTw/FD8315-800",
    "https://www.nike.com/tw/t/air-force-1-07-premium-6dqQcsEQ/IO1259-002",
    "https://www.nike.com/tw/t/air-jordan-1-triple-stack-pahhHbBT/HV8288-402",
    "https://www.nike.com/tw/t/v2k-run-43YfLxpv/IH0388-002",
    "https://www.nike.com/tw/t/shox-z-5AFJMyDk/HQ7540-101",
    "https://www.nike.com/tw/t/v5-rnr-%E5%85%B7%E5%8F%8D%E5%85%89%E8%A3%9D%E9%A3%BE-XwdKwm/HQ7901-004",
    "https://www.nike.com/tw/t/sabrina-3-ep-%E7%B1%83%E7%90%83-G2lc4oD7/HF2882-600",
    "https://www.nike.com/tw/t/dunk-%E4%BD%8E%E7%AD%92-sp0IyfLU/IQ1145-610",
    "https://www.nike.com/tw/t/free-metcon-6-%E5%81%A5%E8%BA%AB%E8%A8%93%E7%B7%B4-Q3pWcF/FJ7126-112",
    "https://www.nike.com/tw/t/v2k-run-%E5%85%B7%E5%8F%8D%E5%85%89%E8%A3%9D%E9%A3%BE-zJV8TV/FD0736-115",
    "https://www.nike.com/tw/t/air-force-1-07-valentines-day-lrgg9u9F/IO8755-600",
    "https://www.nike.com/tw/t/court-legacy-next-nature-rdTfqH/DH3161-114",
    "https://www.nike.com/tw/t/shox-tl-jnm2zN/AR3566-601",
    "https://www.nike.com/tw/t/air-max-muse-N8aTuR5v/II6282-500",
    "https://www.nike.com/tw/t/reax-8-tr-%E5%81%A5%E8%BA%AB%E8%A8%93%E7%B7%B4-K4q2TBes/IO2400-100",


    # 你之後可以一直加
    # "https://www.nike.com/tw/t/xxx/xxxxxx-xxx",
]

# ========= 工具 =========
def clean_price(text):
    if not text:
        return None
    return int(re.sub(r"[^\d]", "", text))


def pick_best_product_image(soup, product_name):
    """
    選出最像『標準商品主視角照』的圖片
    （雙腳、45 度、灰背景、無模特）
    """

    name_token = product_name.replace(" ", "+").upper()

    # 1️⃣ Thumbnail：檔名包含商品名稱
    thumbnails = soup.select("img[data-testid^='Thumbnail-Img']")
    for img in thumbnails:
        src = img.get("src", "")
        if name_token in src.upper():
            return src

    # 2️⃣ Thumbnail：alt 含商品名稱
    for img in thumbnails:
        alt = img.get("alt", "")
        if product_name in alt:
            return img.get("src")

    # 3️⃣ HeroImg：排除細節 / 上腳
    hero_imgs = soup.select("img[data-testid='HeroImg']")
    for img in hero_imgs:
        src = img.get("src", "").lower()
        if not any(k in src for k in ["detail", "on_foot", "lifestyle"]):
            return img.get("src")

    # 4️⃣ 最後保底
    if thumbnails:
        return thumbnails[0].get("src")

    return None


# ========= 單一顏色資料 =========
def extract_data_from_soup(soup, url):
    # 商品名稱
    product_name = soup.select_one(
        "h1[data-testid='product_title']"
    ).text.strip()

    # 價格
    price_tag = soup.select_one(
        "span[data-testid='currentPrice-container']"
    )
    current_price = clean_price(price_tag.text) if price_tag else None

    # parent_id（款式）
    style_li = soup.select_one(
        "li[data-testid='product-description-style-color']"
    )
    parent_id = (
        style_li.text.replace("款式：", "").strip()
        if style_li else None
    )

    # 顏色（會隨點選更新）
    color_li = soup.select_one(
        "li[data-testid='product-description-color-description']"
    )
    color_label = (
        color_li.text.replace("顯示顏色：", "").strip()
        if color_li else "單一顏色"
    )

    # 尺寸 & 庫存
    full_size_list = []
    available_list = []

    for item in soup.select("div[data-testid='pdp-grid-selector-item']"):
        label = item.select_one("label")
        input_tag = item.select_one("input")

        if not label or not input_tag:
            continue

        size_text = label.text.strip()
        full_size_list.append(size_text)

        disabled = (
            input_tag.has_attr("disabled")
            or input_tag.get("aria-disabled") == "true"
        )

        if not disabled:
            available_list.append(size_text)

    # 商品圖片（語意選擇）
    img_path = pick_best_product_image(soup, product_name)

    sku_id = f"nike-{parent_id}-{color_label}".replace(" ", "_")

    return {
        "sku_id": sku_id,
        "brand": "NIKE",
        "parent_id": parent_id,
        "sku_url": url,
        "category": "woman_shoes",
        "product_name": product_name,
        "img_path": img_path,
        "color_label": color_label,
        "original_price": None,
        "current_price": current_price,
        "full_size_list": full_size_list,
        "available_list": available_list,
    }


# ========= 多商品 + 多顏色 =========
def scrape_nike_products(urls):
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            locale="zh-TW",
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        for url in urls:
            print(f"[+] Scraping product page: {url}")
            page.goto(url, timeout=60000)
            page.wait_for_selector(
                "h1[data-testid='product_title']", timeout=20000
            )

            # 只選可點擊顏色
            color_links = page.locator(
                "#colorway-picker-container "
                "a[data-testid^='colorway-link-']:not([aria-disabled='true'])"
            )
            color_count = color_links.count()

            # 單一顏色商品
            if color_count == 0:
                soup = BeautifulSoup(page.content(), "html.parser")
                results.append(extract_data_from_soup(soup, page.url))
                continue

            # 多顏色商品
            for i in range(color_count):
                try:
                    color_links.nth(i).click()
                    page.wait_for_timeout(1500)

                    soup = BeautifulSoup(page.content(), "html.parser")
                    data = extract_data_from_soup(soup, page.url)
                    results.append(data)

                    print(
                        f"    + Color {i+1}/{color_count}: {data['color_label']}"
                    )
                    time.sleep(1)

                except Exception as e:
                    print(f"    ! Skip color {i+1}: {e}")

        browser.close()

    return results


# ========= 主程式 =========
if __name__ == "__main__":
    data = scrape_nike_products(URLS)

    with open("nike_woman.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("✔ nike_woman.json generated")






