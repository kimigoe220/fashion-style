import os
import re
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from collections import Counter

import requests
from dotenv import load_dotenv
from PIL import Image, ImageOps, ImageFilter
import pytesseract
from supabase import create_client
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

# ========== 你已確認可用的 tesseract ==========
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

BRAND = "LATIV"
TOP_JSON_PATH = Path("lativ_under.json")

# 兩份匯總輸出
OUT_SIZECHART_ALL = Path("lativ_sizechart_all.json")
OUT_TRYON_ALL = Path("lativ_tryon_all.json")

# 圖片/ocr/debug 輸出資料夾
IMG_DIR = Path("lativ_imgs")
DEBUG_DIR = Path("lativ_debug")
IMG_DIR.mkdir(exist_ok=True, parents=True)
DEBUG_DIR.mkdir(exist_ok=True, parents=True)

SIZE_ORDER = {"XXS": 1, "XS": 2, "S": 3, "M": 4, "L": 5, "XL": 6, "XXL": 7, "3XL": 8, "4XL": 9}
SIZE_ORDER_LIST = ["XXS", "XS", "S", "M", "L", "XL", "XXL", "3XL", "4XL"]


# --------------------------
# Utils
# --------------------------
def sort_sizes(sizes: List[str]) -> List[str]:
    order = {s: i for i, s in enumerate(SIZE_ORDER_LIST)}
    uniq = []
    seen = set()
    for s in sizes:
        if not s:
            continue
        ss = str(s).strip().upper()
        if ss and ss not in seen:
            seen.add(ss)
            uniq.append(ss)
    return sorted(uniq, key=lambda x: order.get(x, 999))


def download_image(url: str, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    out_path.write_bytes(r.content)
    return out_path


# --------------------------
# OCR: sizechart
# --------------------------
def ocr_sizechart_image(img_path: Path) -> str:
    img = Image.open(img_path).convert("L")
    img = ImageOps.autocontrast(img)
    img = img.resize((img.width * 3, img.height * 3))
    img = img.filter(ImageFilter.SHARPEN)

    config = r"--oem 3 --psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789()./%+-: "
    return pytesseract.image_to_string(img, lang="eng", config=config)


def parse_sizechart_to_structured(text: str) -> List[Dict[str, Any]]:
    """
    依你確認欄位順序：肩寬、胸寬、袖長、衣長
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    size_pat = re.compile(r"\b(XXS|XS|S|M|L|XL|XXL|3XL|4XL)\b", re.IGNORECASE)
    num_pat = re.compile(r"(\d+(?:\.\d+)?)")

    best: Dict[str, Dict[str, Any]] = {}
    for ln in lines:
        u = ln.upper().replace("XI", "XL").replace("8O", "80").replace("9O", "90")
        m = size_pat.search(u)
        if not m:
            continue
        size = m.group(1).upper()
        nums = [float(x) if "." in x else int(x) for x in num_pat.findall(u)]
        if len(nums) < 4:
            continue

        best[size] = {
            "size": size,
            "shoulder_cm": nums[0],
            "chest_width_cm": nums[1],
            "sleeve_length_cm": nums[2],
            "garment_length_cm": nums[3],
            "raw": ln,
        }

    return sorted(best.values(), key=lambda r: SIZE_ORDER.get(r["size"], 999))


# --------------------------
# OCR: tryon
# --------------------------
def ocr_tryon_image(img_path: Path) -> str:
    img = Image.open(img_path).convert("L")
    img = ImageOps.autocontrast(img)
    img = img.resize((img.width * 3, img.height * 3))
    img = img.filter(ImageFilter.SHARPEN)

    config = r"--oem 3 --psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 "
    return pytesseract.image_to_string(img, lang="eng", config=config)


def parse_tryon_text_to_rows(text: str) -> List[Dict[str, Any]]:
    """
    A 148 48 38 80 S
    person height weight shoulder bust size
    """
    t = text.upper()
    t = t.replace("XI", "XL")
    t = t.replace("8O", "80").replace("9O", "90").replace("IO", "10")
    t = re.sub(r"[|]", " ", t)
    t = re.sub(r"[ \t]+", " ", t)

    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    size_pat = r"(XXS|XS|S|M|L|XL|XXL|3XL|4XL)"

    row_pat = re.compile(
        rf"^([A-Z])?\s*(\d{{2,3}})\s+(\d{{2,3}})\s+(\d{{1,3}})\s+(\d{{1,3}})\s+{size_pat}$"
    )

    dedup: Dict[Tuple[int, int, int, int, str], Dict[str, Any]] = {}
    for ln in lines:
        m = row_pat.match(ln)
        if not m:
            continue
        row = {
            "person_code": m.group(1) or None,
            "height_cm": int(m.group(2)),
            "weight_kg": int(m.group(3)),
            "shoulder_cm": int(m.group(4)),
            "bust_cm": int(m.group(5)),  # ✅ 胸圍
            "recommended_size": m.group(6).upper(),
            "raw": ln,
        }
        k = (row["height_cm"], row["weight_kg"], row["shoulder_cm"], row["bust_cm"], row["recommended_size"])
        dedup[k] = row

    return list(dedup.values())


# --------------------------
# Playwright: get 2 image src for a product
# --------------------------
def scrape_modal_image_src(product_code: str, headless: bool = True) -> Dict[str, str]:
    url = f"https://www.lativ.com.tw/product/{product_code}"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(800)

        # 先判斷是否下架（有些下架頁面仍會回 200）
        body_text = page.inner_text("body")
        if "商品已下架" in body_text:
            page.screenshot(path=str(DEBUG_DIR / f"{product_code}_off_shelf.png"), full_page=True)
            browser.close()
            raise RuntimeError("商品已下架")

        # 開彈窗：外頁「商品尺寸表」按鈕
        btn_open = page.locator("button:has(span.padding-left:has-text('商品尺寸表'))").first
        if btn_open.count() == 0:
            page.screenshot(path=str(DEBUG_DIR / f"{product_code}_no_open_button.png"), full_page=True)
            browser.close()
            raise RuntimeError("找不到外頁『商品尺寸表』按鈕")

        btn_open.click()
        page.wait_for_timeout(500)

        # 等彈窗 tab 出現
        tab_size = page.locator("button.tab-border:has-text('商品尺寸表')").first
        try:
            tab_size.wait_for(state="visible", timeout=20000)
        except PWTimeoutError:
            page.screenshot(path=str(DEBUG_DIR / f"{product_code}_modal_not_ready.png"), full_page=True)
            browser.close()
            raise RuntimeError("彈窗未成功開啟或 tab 沒出現")

        # 確保尺寸表 tab
        tab_size.click()
        page.wait_for_timeout(500)

        img_size = page.locator("img[alt='尺寸表']").first
        try:
            img_size.wait_for(state="visible", timeout=20000)
        except PWTimeoutError:
            page.screenshot(path=str(DEBUG_DIR / f"{product_code}_no_size_img.png"), full_page=True)
            browser.close()
            raise RuntimeError("抓不到『尺寸表』圖片")

        size_src = img_size.get_attribute("src") or ""

        # 切到真人試穿紀錄 tab（有些顯示試穿報告）
        tab_tryon = page.locator("button.tab-border:has-text('真人試穿紀錄')").first
        if tab_tryon.count() == 0:
            tab_tryon = page.locator("button.tab-border:has-text('試穿報告')").first

        if tab_tryon.count() == 0:
            page.screenshot(path=str(DEBUG_DIR / f"{product_code}_no_tryon_tab.png"), full_page=True)
            browser.close()
            raise RuntimeError("找不到『真人試穿紀錄/試穿報告』tab")

        tab_tryon.click()
        page.wait_for_timeout(800)

        img_tryon = page.locator("img[alt='試穿報告']").first
        try:
            img_tryon.wait_for(state="visible", timeout=20000)
        except PWTimeoutError:
            page.screenshot(path=str(DEBUG_DIR / f"{product_code}_no_tryon_img.png"), full_page=True)
            browser.close()
            raise RuntimeError("抓不到『試穿報告』圖片")

        tryon_src = img_tryon.get_attribute("src") or ""
        browser.close()

    if not size_src or not tryon_src:
        raise RuntimeError("src 取得為空")

    return {"product_url": url, "sizechart_img": size_src, "tryon_img": tryon_src}


# --------------------------
# Build recommendation profile for supabase
# --------------------------
def build_profile(
    product_code: str,
    items_same_product: List[Dict[str, Any]],
    sizechart_rows: Optional[List[Dict[str, Any]]],
    tryon_rows: Optional[List[Dict[str, Any]]],
    product_url: str,
    sizechart_img: str,
    tryon_img: str,
) -> Dict[str, Any]:
    first = items_same_product[0]
    category = first.get("category")
    product_name = first.get("product_name")

    # union available_list across colors
    avail = []
    for it in items_same_product:
        avail += (it.get("available_list") or [])
    available_size_list = sort_sizes(avail)

    default_size = None
    tryon_size_counts = None
    if tryon_rows:
        cnt = Counter([r.get("recommended_size") for r in tryon_rows if r.get("recommended_size")])
        filtered = {k: v for k, v in cnt.items() if k in available_size_list}
        tryon_size_counts = dict(filtered) if filtered else dict(cnt)
        if filtered:
            default_size = max(filtered.items(), key=lambda kv: kv[1])[0]
        elif cnt:
            default_size = max(cnt.items(), key=lambda kv: kv[1])[0]

    return {
        "brand": BRAND,
        "product_code": product_code,
        "category": category,
        "product_name": product_name,
        "available_size_list": available_size_list,
        "default_recommended_size": default_size,
        "sizechart": sizechart_rows,            # jsonb
        "tryon_samples": tryon_rows,            # jsonb
        "tryon_size_counts": tryon_size_counts, # jsonb
        "data": {  # 可選：留來源資訊
            "product_url": product_url,
            "sizechart_img": sizechart_img,
            "tryon_img": tryon_img,
        }
    }


def main():
    if not TOP_JSON_PATH.exists():
        raise FileNotFoundError("找不到 lativ_top.json（請放在同資料夾）")

    # 讀 top.json（含庫存）
    items = json.loads(TOP_JSON_PATH.read_text(encoding="utf-8"))
    product_codes = sorted({it.get("parent_id") for it in items if it.get("parent_id")})
    print("Total products:", len(product_codes))

    # Supabase
    load_dotenv()
    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    supabase_key = os.getenv("SUPABASE_KEY", "").strip()
    if not supabase_url or not supabase_key:
        raise RuntimeError("Missing SUPABASE_URL / SUPABASE_KEY in .env")
    sb = create_client(supabase_url, supabase_key)

    # 輸出匯總 json
    sizechart_all: Dict[str, Any] = {}
    tryon_all: Dict[str, Any] = {}

    # Supabase profiles payload
    profiles: List[Dict[str, Any]] = []

    # 跑全量（你也可以先把 limit 設小測試）
    limit = None  # 例如先測 5：limit = 5
    headless = True

    for idx, code in enumerate(product_codes, start=1):
        if limit and idx > limit:
            break

        group = [it for it in items if it.get("parent_id") == code]
        print(f"\n[{idx}/{len(product_codes)}] {code} ...")

        try:
            srcs = scrape_modal_image_src(code, headless=headless)
            size_src = srcs["sizechart_img"]
            tryon_src = srcs["tryon_img"]

            # 下載圖片
            size_img_path = download_image(size_src, IMG_DIR / f"{code}_sizechart.png")
            tryon_img_path = download_image(tryon_src, IMG_DIR / f"{code}_tryon.png")

            # OCR + parse
            size_text = ocr_sizechart_image(size_img_path)
            tryon_text = ocr_tryon_image(tryon_img_path)

            (IMG_DIR / f"{code}_sizechart_ocr.txt").write_text(size_text, encoding="utf-8")
            (IMG_DIR / f"{code}_tryon_ocr.txt").write_text(tryon_text, encoding="utf-8")

            size_rows = parse_sizechart_to_structured(size_text)
            tryon_rows = parse_tryon_text_to_rows(tryon_text)

            sizechart_all[code] = size_rows
            tryon_all[code] = tryon_rows

            # profile（整合庫存 + default size + json）
            profile = build_profile(
                product_code=code,
                items_same_product=group,
                sizechart_rows=size_rows,
                tryon_rows=tryon_rows,
                product_url=srcs["product_url"],
                sizechart_img=size_src,
                tryon_img=tryon_src,
            )
            profiles.append(profile)

            print("  sizechart rows:", len(size_rows), "| tryon rows:", len(tryon_rows),
                  "| available:", profile["available_size_list"],
                  "| default:", profile["default_recommended_size"])

        except Exception as e:
            err = str(e)

            sizechart_all[code] = {"error": err}
            tryon_all[code] = {"error": err}
            print("  ❌ failed:", err)

            fallback_profile = build_profile(
                product_code=code,
                items_same_product=group,
                sizechart_rows=None,
                tryon_rows=None,
                product_url=f"https://www.lativ.com.tw/product/{code}",
                sizechart_img="",
                tryon_img="",
            )
            fallback_profile["data"] = fallback_profile.get("data") or {}
            fallback_profile["data"]["error"] = err

            profiles.append(fallback_profile)
            continue

                

    # 只輸出兩份總檔
    OUT_SIZECHART_ALL.write_text(json.dumps(sizechart_all, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_TRYON_ALL.write_text(json.dumps(tryon_all, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n✅ wrote:", OUT_SIZECHART_ALL, OUT_TRYON_ALL)

    # 寫 supabase（你可改成自己的表名）
    table_name = "lativ_recommend"
    if profiles:
        sb.table(table_name).upsert(profiles, on_conflict="brand,product_code").execute()
        print(f"✅ upserted to {table_name}: {len(profiles)} rows")
    else:
        print("⚠️ no profiles to upsert.")


if __name__ == "__main__":
    main()