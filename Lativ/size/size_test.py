import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from PIL import Image, ImageOps

from playwright.sync_api import sync_playwright
import pytesseract
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


# 如果你的 Windows 找不到 tesseract，解除註解並改成你本機路徑
# pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


PRODUCT_URL = "https://www.lativ.com.tw/product/700220410"


def get_product_code_from_lativ_url(url: str) -> str:
    m = re.search(r"/product/(\d+)", url)
    if not m:
        raise ValueError(f"網址抓不到 product_code: {url}")
    return m.group(1)


def download_image(url: str, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    out_path.write_bytes(r.content)
    return out_path


from pathlib import Path

from typing import Dict
from pathlib import Path
from playwright.sync_api import sync_playwright

def scrape_lativ_tryon_image_src(product_url: str) -> Dict[str, str]:
    debug_dir = Path(__file__).parent / "lativ_debug"
    debug_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        page.goto(product_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(800)

        # 1) 點「商品尺寸表」（外頁按鈕）
        # 你的 DOM：button ... <span class="padding-left">商品尺寸表</span>
        btn_open = page.locator("button:has(span.padding-left:has-text('商品尺寸表'))").first
        if btn_open.count() == 0:
            page.screenshot(path=str(debug_dir / "no_open_button.png"), full_page=True)
            (debug_dir / "no_open_button.html").write_text(page.content(), encoding="utf-8")
            browser.close()
            raise RuntimeError("找不到外頁『商品尺寸表』按鈕。已輸出 lativ_debug/no_open_button.*")

        btn_open.click()
        page.wait_for_timeout(500)

        # 2) 等彈窗內的 tab 出現（你貼的：button.tab-border）
        # 用文字鎖定「商品尺寸表」tab
        tab_size = page.locator("button.tab-border:has-text('商品尺寸表')").first
        try:
            tab_size.wait_for(state="visible", timeout=20000)
        except Exception:
            page.screenshot(path=str(debug_dir / "modal_not_ready.png"), full_page=True)
            (debug_dir / "modal_not_ready.html").write_text(page.content(), encoding="utf-8")
            browser.close()
            raise RuntimeError("彈窗似乎沒成功開啟或 tab 沒出現。已輸出 lativ_debug/modal_not_ready.*")

        # 3) 點「商品尺寸表」tab（保險，確保內容是尺寸表）
        tab_size.click()
        page.wait_for_timeout(500)

        # 4) 抓「尺寸表」圖
        img_size = page.locator("img[alt='尺寸表']").first
        try:
            img_size.wait_for(state="visible", timeout=20000)
        except Exception:
            page.screenshot(path=str(debug_dir / "no_size_img.png"), full_page=True)
            (debug_dir / "no_size_img.html").write_text(page.content(), encoding="utf-8")
            browser.close()
            raise RuntimeError("抓不到『尺寸表』圖片。已輸出 lativ_debug/no_size_img.*")

        sizechart_src = img_size.get_attribute("src") or ""

        # 5) 點「真人試穿紀錄」tab（你貼的是這個字，不是「試穿報告」）
        tab_tryon = page.locator("button.tab-border:has-text('真人試穿紀錄')").first
        if tab_tryon.count() == 0:
            # 有些版本可能顯示「試穿報告」
            tab_tryon = page.locator("button.tab-border:has-text('試穿報告')").first

        if tab_tryon.count() == 0:
            page.screenshot(path=str(debug_dir / "no_tryon_tab.png"), full_page=True)
            (debug_dir / "no_tryon_tab.html").write_text(page.content(), encoding="utf-8")
            browser.close()
            raise RuntimeError("找不到『真人試穿紀錄/試穿報告』tab。已輸出 lativ_debug/no_tryon_tab.*")

        tab_tryon.click()
        page.wait_for_timeout(800)  # lazy load 給它一點時間

        # 6) 抓「試穿報告」圖
        img_tryon = page.locator("img[alt='試穿報告']").first
        try:
            img_tryon.wait_for(state="visible", timeout=20000)
        except Exception:
            page.screenshot(path=str(debug_dir / "no_tryon_img.png"), full_page=True)
            (debug_dir / "no_tryon_img.html").write_text(page.content(), encoding="utf-8")
            browser.close()
            raise RuntimeError("抓不到『試穿報告』圖片。已輸出 lativ_debug/no_tryon_img.*")

        tryon_src = img_tryon.get_attribute("src") or ""

        browser.close()

    if not sizechart_src or not tryon_src:
        raise RuntimeError(f"抓到的 src 為空：sizechart_src={sizechart_src}, tryon_src={tryon_src}")

    return {"sizechart_img": sizechart_src, "tryon_img": tryon_src}

def ocr_tryon_image(img_path: Path) -> str:
    """
    OCR 目標：數字 + 尺碼英文
    """
    img = Image.open(img_path).convert("L")
    img = ImageOps.autocontrast(img)
    img = img.resize((img.width * 2, img.height * 2))

    # 只允許常見字元（降低雜訊）
    config = r"--oem 3 --psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789./:- "
    text = pytesseract.image_to_string(img, lang="eng", config=config)
    return text


def parse_tryon_text_to_rows(text: str) -> List[Dict[str, Any]]:
    """
    解析目標 row：
    A 148 48 38 80 S
    """
    # 常見 OCR 誤判修正（可再加）
    t = text.upper()
    t = t.replace("XI", "XL")     # XL 常被辨識成 XI
    t = t.replace("8O", "80")     # 0/O
    t = t.replace("9O", "90")
    t = re.sub(r"[|]", " ", t)

    size_pat = r"(XXS|XS|S|M|L|XL|XXL|3XL|4XL)"
    row_pat = re.compile(
        rf"(?:^|\s)([A-Z])?\s*(\d{{2,3}})\s+(\d{{2,3}})\s+(\d{{1,3}})\s+(\d{{1,3}})\s+{size_pat}(?=\s|$)",
        re.IGNORECASE
    )

    rows: List[Dict[str, Any]] = []
    for m in row_pat.finditer(t):
        person = (m.group(1) or "").strip() or None
        height = int(m.group(2))
        weight = int(m.group(3))
        shoulder = int(m.group(4))
        bust = int(m.group(5))
        size = m.group(6).upper()

        rows.append({
            "person_code": person,
            "height_cm": height,
            "weight_kg": weight,
            "shoulder_cm": shoulder,
            "bust_cm": bust,
            "recommended_size": size,
        })

    # 去重
    dedup = {}
    for r in rows:
        k = (r["height_cm"], r["weight_kg"], r["shoulder_cm"], r["bust_cm"], r["recommended_size"])
        dedup[k] = r
    return list(dedup.values())


def print_table(rows: List[Dict[str, Any]]):
    if not rows:
        print("（沒有解析到任何 row）")
        return

    # 排序：身高→體重
    rows = sorted(rows, key=lambda r: (r["height_cm"], r["weight_kg"]))

    headers = ["person_code", "height_cm", "weight_kg", "shoulder_cm", "bust_cm", "recommended_size"]
    colw = {h: max(len(h), max(len(str(r.get(h, ""))) for r in rows)) for h in headers}

    def fmt_row(r: Dict[str, Any]) -> str:
        return " | ".join(str(r.get(h, "")).ljust(colw[h]) for h in headers)

    print("\n" + fmt_row({h: h for h in headers}))
    print("-+-".join("-" * colw[h] for h in headers))
    for r in rows:
        print(fmt_row(r))


def main():
    product_code = get_product_code_from_lativ_url(PRODUCT_URL)
    print("product_code:", product_code)

    imgs = scrape_lativ_tryon_image_src(PRODUCT_URL)
    print("sizechart_img:", imgs["sizechart_img"])
    print("tryon_img:", imgs["tryon_img"])

    out_dir = Path(__file__).parent / "lativ_imgs"
    tryon_path = download_image(imgs["tryon_img"], out_dir / f"{product_code}_tryon.png")
    print("downloaded tryon image:", tryon_path)

    text = ocr_tryon_image(tryon_path)

    # 你要檢查 OCR 原文的話，可以輸出成檔案
    # ocr_txt_path = out_dir / f"{product_code}_ocr.txt"
    # ocr_txt_path.write_text(text, encoding="utf-8")
    # print("saved ocr text:", ocr_txt_path)

    # rows = parse_tryon_text_to_rows(text)
    # print(f"parsed rows: {len(rows)}")
    # print_table(rows)

    # 先測試下載
    out_dir = Path(__file__).parent / "lativ_imgs"
    size_path = download_image(imgs["sizechart_img"], out_dir / "sizechart.png")
    tryon_path = download_image(imgs["tryon_img"], out_dir / "tryon.png")
    print("downloaded:", size_path, tryon_path)

    return  # 先停在這裡，不跑 OCR

    # 也輸出成 json 方便你檢查
    json_path = out_dir / f"{product_code}_tryon_parsed.json"
    import json as _json
    json_path.write_text(_json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved parsed json:", json_path)


if __name__ == "__main__":
    main()