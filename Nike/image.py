import os
import json
import re
import requests
from pathlib import Path

# ========= 設定 =========
JSON_PATH = "nike_woman.json"   # 你的爬蟲輸出
BASE_DIR = Path("images")          # 圖片根目錄
TIMEOUT = 20

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}

# ========= 工具 =========
def safe_filename(text: str) -> str:
    """
    移除檔名非法字元
    """
    text = text.replace(" ", "_")
    return re.sub(r'[\\/:*?"<>|]', "_", text)

def download_image(url: str, save_path: Path):
    if save_path.exists():
        print(f"✔ Exists: {save_path.name}")
        return

    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()

        with open(save_path, "wb") as f:
            f.write(resp.content)

        print(f"⬇ Downloaded: {save_path}")

    except Exception as e:
        print(f"✖ Failed: {url} → {e}")

# ========= 主流程 =========
def main():
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        products = json.load(f)

    for item in products:
        brand = item.get("brand", "UNKNOWN").lower()
        category = item.get("category", "misc")
        parent_id = item.get("parent_id", "unknown")
        color = item.get("color_label", "no_color")
        img_url = item.get("img_path")

        if not img_url:
            print("⚠ No image url, skip")
            continue

        # ===== 建立資料夾 =====
        save_dir = BASE_DIR / category / brand / parent_id
        save_dir.mkdir(parents=True, exist_ok=True)

        # ===== 檔名 =====
        filename = safe_filename(
            f"{brand.upper()}-{parent_id}-{color}.jpg"
        )
        save_path = save_dir / filename

        # ===== 下載 =====
        download_image(img_url, save_path)

if __name__ == "__main__":
    main()
