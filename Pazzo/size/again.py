from playwright.sync_api import sync_playwright
import re
import os
from typing import List, Dict, Any, Optional
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client, Client


# =========================================================
# 0) 讀取 .env（跟這支檔案同資料夾）
# =========================================================
load_dotenv(Path(__file__).parent / ".env")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()

SUPABASE_TABLE = "pazzo_tryon_reports"
BRAND = "PAZZO"


# =========================================================
# 1) 清洗與表格抽取（跟你目前一致）
# =========================================================
def extract_table(locator):
    rows = []
    for tr in locator.locator("tr").all():
        cells = [c.inner_text().strip() for c in tr.locator("th, td").all()]
        if cells:
            rows.append(cells)
    return rows


def _to_number(x: str) -> Optional[float]:
    s = (x or "").strip()
    m = re.search(r"(\d+(?:\.\d+)?)", s)
    if not m:
        return None
    num = float(m.group(1))
    if abs(num - int(num)) < 1e-9:
        return int(num)
    return num


def clean_tryon_report(tryon_rows: List[List[str]], brand: str) -> List[Dict[str, Any]]:
    if not tryon_rows or len(tryon_rows) < 2:
        return []

    header = [h.strip() for h in tryon_rows[0]]
    header_norm = [re.sub(r"\s+", "", h) for h in header]

    FIELD_MAP = {
        "身高": ("height_cm", "num"),
        "體重": ("weight_kg", "num"),
        "肩寬": ("shoulder_cm", "num"),
        "胸寬": ("bust_cm", "num"),
        "胸圍": ("bust_cm", "num"),
        "上胸圍": ("upper_bust_cm", "num"),
        "下胸圍": ("under_bust_cm", "num"),
        "腰圍": ("waist_cm", "num"),
        "臀圍": ("hip_cm", "num"),
        "罩杯": ("bra_cup", "text"),
        "建議尺寸": ("recommended_size", "text"),
    }

    keep_cols = []
    for idx, h in enumerate(header_norm):
        if any(x in h for x in ["試穿人員", "身形"]):
            continue
        for zh, (en, typ) in FIELD_MAP.items():
            if zh in h:
                keep_cols.append((idx, en, typ))
                break

    cleaned: List[Dict[str, Any]] = []
    for row in tryon_rows[1:]:
        obj: Dict[str, Any] = {"brand": brand}
        for idx, key, typ in keep_cols:
            if idx >= len(row):
                continue
            raw = (row[idx] or "").strip()
            if not raw:
                continue
            if typ == "text":
                obj[key] = raw
            else:
                v = _to_number(raw)
                if v is not None:
                    obj[key] = v

        if "height_cm" in obj and "recommended_size" in obj:
            cleaned.append(obj)

    return cleaned


# =========================================================
# 2) product_code：用 URL 的 /n/24074 那串數字
# =========================================================
def get_product_code_from_url(url: str) -> str:
    m = re.search(r"/n/(\d+)", url)
    if not m:
        raise ValueError(f"網址抓不到 product_code（找不到 /n/數字）：{url}")
    return m.group(1)


# =========================================================
# 3) Supabase
# =========================================================
def get_supabase() -> Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("缺少 SUPABASE_URL / SUPABASE_KEY。請確認 .env 已放在本檔同層且內容正確。")
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def upsert_tryon_rows(sb: Client, rows: List[Dict[str, Any]]):
    if not rows:
        print("ℹ️ 沒有可寫入的試穿資料（rows=0）")
        return

    sb.table(SUPABASE_TABLE).upsert(
        rows,
        on_conflict="product_code,height_cm,weight_kg,bra_cup,recommended_size"
    ).execute()

    print(f"🟩 Supabase upsert 完成：{len(rows)} rows")


# =========================================================
# 4) 抓單一網址 → 寫入 Supabase
# =========================================================
def scrape_tryon_for_one(page, url: str) -> List[Dict[str, Any]]:
    product_code = get_product_code_from_url(url)

    page.goto(url, wait_until="domcontentloaded", timeout=60000)

    # 點「尺寸指南」
    page.locator("li a:has-text('尺寸指南')").first.click()

    # 等尺寸指南內容出現
    page.locator(":text('產品尺寸')").wait_for(timeout=15000)

    # 試穿報告
    tryon_title = page.locator("text=試穿報告")
    if tryon_title.count() == 0:
        return []

    tryon_section = tryon_title.first.locator("xpath=ancestor::*[1]")
    tryon_table = tryon_section.locator("table").first
    tryon_rows = extract_table(tryon_table)

    cleaned = clean_tryon_report(tryon_rows, brand=BRAND)

    # 補齊 DB 欄位
    out_rows: List[Dict[str, Any]] = []
    for r in cleaned:
        row = dict(r)
        row["product_code"] = product_code
        row["brand"] = BRAND
        row["url"] = url
        row["data"] = dict(row)   # jsonb snapshot
        out_rows.append(row)

    return out_rows


def run_manual(urls: List[str]):
    sb = get_supabase()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        for i, url in enumerate(urls, 1):
            print(f"\n[{i}/{len(urls)}] 手動補跑：{url}")
            try:
                rows = scrape_tryon_for_one(page, url)
                if rows:
                    upsert_tryon_rows(sb, rows)
                    print(f"✅ 寫入成功 | product_code={get_product_code_from_url(url)} | rows={len(rows)}")
                else:
                    print(f"ℹ️ 此商品沒有試穿報告 | product_code={get_product_code_from_url(url)}")
            except Exception as e:
                print(f"❌ 失敗：{url}\n   原因：{repr(e)}")

        browser.close()


if __name__ == "__main__":
    # =====================================================
    # ✅ 你把失敗那筆網址貼在這裡（可貼多筆）
    # =====================================================
    MANUAL_URLS = [
        "https://www.pazzo.com.tw/zh-tw/market/n/24296",
        "https://www.pazzo.com.tw/zh-tw/market/n/24256",
        "https://www.pazzo.com.tw/zh-tw/market/n/24256",
    ]

    run_manual(MANUAL_URLS)