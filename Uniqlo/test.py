from playwright.sync_api import sync_playwright
import json
import re
import time

# ===== 設定區 =====
CATEGORY_URL = "https://www.uniqlo.com/tw/zh_TW/c/all_women-tops-t-shirts.html"
LIMIT = 5  # 建議先用小數字測試
OUTPUT_FILE = "uniqlo_test.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def parse_price(text):
    if not text: return None
    return int(re.sub(r"[^\d]", "", text))

def build_image_url(product_code, color_code):
    if not product_code or not color_code: return None
    return f"https://www.uniqlo.com/tw/hmall/test/{product_code}/sku/561/{color_code}.jpg"

def scrape_uniqlo():
    results = []
    product_codes = set()

    with sync_playwright() as p:
        # 啟動時建議 headless=False 觀察是否有彈窗擋住
        browser = p.chromium.launch(headless=False) 
        context = browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 900})
        page = context.new_page()

        print(f"▶ 進入分類頁: {CATEGORY_URL}")
        page.goto(CATEGORY_URL, wait_until="domcontentloaded", timeout=60000)
        
        # 1. 滾動獲取列表
        print("⏬ 正在加載商品列表...")
        for _ in range(5):
            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(1500)
            links = page.locator('a[href*="productCode="]').all()
            for link in links:
                href = link.get_attribute("href")
                match = re.search(r"productCode=(u\d+)", href)
                if match:
                    product_codes.add(match.group(1))
            if len(product_codes) >= LIMIT: break

        found_list = list(product_codes)[:LIMIT]
        print(f"✅ 抓到 {len(found_list)} 個商品代碼，開始爬取細節...")

        # 2. 爬取細節
        for idx, code in enumerate(found_list, start=1):
            detail_url = f"https://www.uniqlo.com/tw/zh_TW/product-detail.html?productCode={code}"
            print(f"({idx}/{len(found_list)}) 正在爬取: {code}")
            
            detail_page = context.new_page()
            try:
                # 延長超時並等待頁面載入
                detail_page.goto(detail_url, wait_until="commit", timeout=40000)
                
                # 強制向下滾動一點點以觸發 Lazy Render
                detail_page.mouse.wheel(0, 400)
                
                # --- 強化的等待邏輯 ---
                # 優先等標題，如果 15秒沒反應，等尺寸選擇器
                try:
                    detail_page.locator("div.product-detail-list-title").first.wait_for(state="visible", timeout=15000)
                except:
                    detail_page.locator("ul.sku-select-sizes").first.wait_for(state="visible", timeout=10000)

                # 基本資訊 (加上 .first 避免多元素衝突)
                name = detail_page.locator("div.product-detail-list-title").first.inner_text().strip()
                
                # 價格抓取 (Uniqlo 標籤結構有時會變，用 text_content 較穩)
                sale_price_raw = detail_page.locator("div.product-detail-list-price-main span.h-currency").first.text_content()
                origin_price_raw = detail_page.locator("span.origin-price span.h-currency").all_text_contents()
                
                sale_price = parse_price(sale_price_raw)
                origin_price = parse_price(origin_price_raw[0]) if origin_price_raw else sale_price

                # 顏色與尺寸
                colors = []
                color_items = detail_page.locator("ul.sku-select-colors.colors-image li")
                
                for i in range(color_items.count()):
                    li = color_items.nth(i)
                    li.click()
                    detail_page.wait_for_timeout(600) # 給一點渲染時間

                    img = li.locator("img")
                    color_name = img.get_attribute("alt")
                    img_src = img.get_attribute("src")
                    
                    color_code = None
                    if img_src and "COL" in img_src:
                        color_code = "COL" + img_src.split("COL")[-1].split(".")[0]

                    # 尺碼抓取
                    available_sizes = []
                    size_items = detail_page.locator("ul.sku-select-sizes li")
                    for s in range(size_items.count()):
                        size_li = size_items.nth(s)
                        cls = size_li.get_attribute("class") or ""
                        if "disabled" not in cls:
                            available_sizes.append(size_li.locator("span").inner_text().strip())

                    colors.append({
                        "color_name": color_name,
                        "color_code": color_code,
                        "available_sizes": available_sizes,
                        "image_url": build_image_url(code, color_code)
                    })

                results.append({
                    "brand": "UNIQLO",
                    "product_code": code,
                    "product_name": name,
                    "product_url": detail_url,
                    "price": {"original": origin_price, "sale": sale_price},
                    "colors": colors
                })
                print(f"   ∟ ✅ 完成: {name}")

            except Exception as e:
                print(f"   ∟ ❌ 失敗: {code}，原因: {str(e)[:50]}...")
            finally:
                detail_page.close()
                time.sleep(1.5) # 稍微休息防止被 Ban

        browser.close()

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n🎉 任務結束！結果已存入 {OUTPUT_FILE}")

if __name__ == "__main__":
    scrape_uniqlo()