import os
import re
from pathlib import Path
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright

def download_largest_image_as_product_id(url: str, product_id: str, out_dir="sizechart_images"):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1000)

        imgs = page.query_selector_all("img")
        candidates = []

        for img in imgs:
            src = img.get_attribute("src")
            if not src:
                continue

            abs_url = urljoin(url, src)
            w = page.evaluate("(el) => el.naturalWidth || el.width", img)
            h = page.evaluate("(el) => el.naturalHeight || el.height", img)

            if not w or not h:
                continue

            area = int(w) * int(h)
            candidates.append((area, abs_url))

        if not candidates:
            raise RuntimeError("找不到任何可用圖片")

        # 取最大那張
        candidates.sort(reverse=True, key=lambda x: x[0])
        img_url = candidates[0][1]

        resp = page.context.request.get(img_url)
        if not resp.ok:
            raise RuntimeError(f"圖片下載失敗 status={resp.status}")

        # ✅ 檔名固定為 product_id.jpg
        fpath = out / f"{product_id}.jpg"
        fpath.write_bytes(resp.body())
        print(f"saved -> {fpath}")

        browser.close()

if __name__ == "__main__":
    url = "https://www.uniqlo.com/tw/zh_TW/product-size-chart.html?sizeChart=%2Fhmall%2Ftest%2Fu0000000052204%2Fzh_TW%2FsizeAndTryOn.html"
    product_id = "u0000000052204"

    download_largest_image_as_product_id(url, product_id)