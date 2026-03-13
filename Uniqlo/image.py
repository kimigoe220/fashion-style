import json
import os
import time
import requests
from urllib.parse import urlparse

JSON_PATH = "uniqlo_men_under.json"
OUTPUT_DIR = "images"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.uniqlo.com/",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}

CONNECT_TIMEOUT = 10
READ_TIMEOUT = 30
RETRY = 3
SLEEP_BETWEEN = 2

os.makedirs(OUTPUT_DIR, exist_ok=True)

with open(JSON_PATH, "r", encoding="utf-8") as f:
    items = json.load(f)

session = requests.Session()
session.headers.update(HEADERS)

for item in items:
    img_url = item.get("img_path")
    category = item.get("category")
    parent_id = item.get("parent_id")
    sku_id = item.get("sku_id")

    if not img_url or not category or not parent_id or not sku_id:
        print(f"⚠️ 欄位不完整，略過：{sku_id}")
        continue

    save_dir = os.path.join(OUTPUT_DIR, category, str(parent_id))
    os.makedirs(save_dir, exist_ok=True)

    ext = os.path.splitext(urlparse(img_url).path)[-1] or ".jpg"
    save_path = os.path.join(save_dir, f"{sku_id}{ext}")

    if os.path.exists(save_path):
        print(f"⏭ 已存在：{save_path}")
        continue

    success = False

    for attempt in range(1, RETRY + 1):
        try:
            resp = session.get(
                img_url,
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                stream=True
            )
            resp.raise_for_status()

            with open(save_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            print(f"✅ 已下載：{save_path}")
            success = True
            break

        except Exception as e:
            print(f"⚠️ 第 {attempt} 次失敗：{img_url}")
            print(e)
            time.sleep(SLEEP_BETWEEN)

    if not success:
        print(f"❌ 放棄下載：{img_url}")

    time.sleep(SLEEP_BETWEEN)

print("🎉 圖片下載流程結束")
