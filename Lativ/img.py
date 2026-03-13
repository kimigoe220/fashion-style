import json
import requests
from pathlib import Path
from urllib.parse import urlparse


# ====== 設定 ======
JSON_PATH = "lativ_men_under.json"     # ← 你的爬蟲輸出 JSON
BASE_IMAGE_DIR = Path("images") # ← 主機存圖資料夾
TIMEOUT = 15


def safe_filename(name: str) -> str:
    """避免 Windows 不合法字元"""
    return (
        name.replace("/", "_")
            .replace("\\", "_")
            .replace(" ", "")
    )


def download_image(url: str, save_path: Path):
    if save_path.exists():
        return "skip"

    try:
        r = requests.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        save_path.write_bytes(r.content)
        return "ok"
    except Exception as e:
        return f"fail: {e}"


def main():
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        items = json.load(f)

    print(f"📦 Total items: {len(items)}")

    ok = skip = fail = 0

    for item in items:
        category = item.get("category")
        parent_id = item.get("parent_id")
        sku_id = item.get("sku_id")
        img_url = item.get("img_path")

        if not all([category, parent_id, sku_id, img_url]):
            continue

        # 資料夾：category / parent_id
        save_dir = BASE_IMAGE_DIR / category / parent_id
        save_dir.mkdir(parents=True, exist_ok=True)

        filename = safe_filename(sku_id) + ".jpg"
        save_path = save_dir / filename

        result = download_image(img_url, save_path)

        if result == "ok":
            ok += 1
        elif result == "skip":
            skip += 1
        else:
            fail += 1

        print(f"🖼 {sku_id}: {result}")

    print("\n====== DONE ======")
    print(f"✅ downloaded: {ok}")
    print(f"⏭ skipped: {skip}")
    print(f"❌ failed: {fail}")
    print(f"📂 saved under: {BASE_IMAGE_DIR.resolve()}")


if __name__ == "__main__":
    main()
