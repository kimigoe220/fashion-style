# download_images.py
import json
import requests
from pathlib import Path
import time

INPUT_JSON = "pazzo_shoes.json"   # 換成你的實際 json
BASE_DIR = Path("images")

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}


def safe_filename(text: str):
    """避免檔名非法字元"""
    return (
        text.replace("/", "_")
            .replace("\\", "_")
            .replace("?", "")
            .replace(":", "")
            .replace("*", "")
            .replace('"', "")
            .replace("<", "")
            .replace(">", "")
            .replace("|", "")
            .strip()
    )


def download_image(url, save_path):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 200:
            save_path.write_bytes(r.content)
            return True
    except Exception as e:
        print("❌ download failed:", e)
    return False


def main():
    with open(INPUT_JSON, "r", encoding="utf-8") as f:
        products = json.load(f)

    ok, fail = 0, 0

    for p in products:
        category = p.get("category") or "unknown"
        parent_id = p.get("parent_id")
        sku_id = p.get("sku_id")              # ⭐ 關鍵
        img_url = p.get("img_path")

        if not parent_id or not sku_id or not img_url:
            fail += 1
            continue

        # 建立資料夾：category / parent_id
        folder = BASE_DIR / category / parent_id
        folder.mkdir(parents=True, exist_ok=True)

        # ⭐ 檔名直接用 sku_id
        filename = safe_filename(sku_id) + ".jpg"
        save_path = folder / filename

        if save_path.exists():
            continue

        if download_image(img_url, save_path):
            ok += 1
        else:
            fail += 1

        time.sleep(0.3)

    print(f"✅ Downloaded: {ok}, ❌ Failed: {fail}")


if __name__ == "__main__":
    main()
