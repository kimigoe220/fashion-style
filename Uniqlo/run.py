from playwright.sync_api import sync_playwright
import json
import re
import time

PRODUCT_URLS = [
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000050253",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000053130",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000050647",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000052143",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000053087",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000053333",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000052665",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000052788",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000053018",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000052984",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000050254",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000053634",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000050369",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000050295",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000052867",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000052712",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000053136",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000053219",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000053633",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000051827",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000053590",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000052288",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000052321",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000053205",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000053204",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000052103",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000052336",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000052721",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000053156",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000050703",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000053393",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000052886",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000053387",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000053541",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000050779",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000050917",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000053313",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000053285",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000050517",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000051566",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000051888",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000052143",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000050253",
    "https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode=u0000000050098",
    

]

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

def extract_product_code(url):
    m = re.search(r"productCode=(u\d+)", url)
    return m.group(1) if m else None

def safe_text(page, selector):
    loc = page.locator(selector)
    return loc.first.inner_text().strip() if loc.count() > 0 else None

def parse_price(text):
    if not text:
        return None
    return int(text.replace("NT$", "").replace(",", "").strip())

def build_image_url(product_code, color_code):
    if not product_code or not color_code:
        return None
    return (
        f"https://www.uniqlo.com/tw/hmall/test/"
        f"{product_code}/sku/561/{color_code}.jpg"
    )

results = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)

    for url in PRODUCT_URLS:
        page = browser.new_page(user_agent=UA, viewport={"width": 1280, "height": 900})

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)

            try:
                page.locator('button:has-text("接受")').click(timeout=3000)
            except:
                pass

            page.mouse.wheel(0, 800)
            page.wait_for_timeout(800)

            page.wait_for_selector("ul.sku-select-colors", timeout=15000)

            product_code = extract_product_code(url)
            product_name = safe_text(page, "div.product-detail-list-title")

            sale_price_text = safe_text(
                page, "div.product-detail-list-price-main span.h-currency"
            )
            original_price_text = safe_text(
                page, "span.origin-price span.h-currency"
            )

            current_price = parse_price(sale_price_text)
            original_price = (
                parse_price(original_price_text)
                if original_price_text
                else current_price
            )

            color_items = page.locator("ul.sku-select-colors li")

            full_size_list = None

            for i in range(color_items.count()):
                li = color_items.nth(i)
                li.click()
                page.wait_for_timeout(600)

                img = li.locator("img")
                color_label = img.get_attribute("alt")
                img_src = img.get_attribute("src")

                color_code = None
                if img_src and "COL" in img_src:
                    color_code = "COL" + img_src.split("COL")[-1].split(".")[0]

                size_items = page.locator("ul.sku-select-sizes li")
                available_list = []

                all_sizes = []

                for s in range(size_items.count()):
                    size_li = size_items.nth(s)
                    size = size_li.locator("span").inner_text().strip()
                    all_sizes.append(size)

                    cls = size_li.get_attribute("class") or ""
                    if "disabled" not in cls:
                        available_list.append(size)

                if full_size_list is None:
                    full_size_list = all_sizes

                results.append({
                    "sku_id": f"uniqlo-{product_code}-{color_label}",
                    "brand": "UNIQLO",
                    "parent_id": product_code,
                    "sku_url": url,
                    "category": "men_under",
                    "product_name": product_name,
                    "img_path": build_image_url(product_code, color_code),
                    "color_label": color_label,
                    "original_price": original_price,
                    "current_price": current_price,
                    "full_size_list": full_size_list,
                    "available_list": available_list
                })

            print(f"✅ 完成：{product_name}")

        except Exception as e:
            print(f"❌ 失敗：{url}")
            print(e)

        finally:
            page.close()
            time.sleep(2)

    browser.close()

with open("uniqlo_men_under.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print("🎉 已輸出 uniqlo_men_under.json")
