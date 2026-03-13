# product.py
import re
from playwright.sync_api import Page


BASE = "https://www.pazzo.com.tw"


def extract_parent_id(url: str) -> str | None:
    m = re.search(r"/market/n/(\d+)", url)
    return m.group(1) if m else None


def canonical_sku_url(parent_id: str) -> str:
    # 你要的 sku_url 長這樣（不帶 /S /M /L，也不帶 ?c=）
    return f"{BASE}/zh-tw/market/n/{parent_id}"


def parse_int(text: str | None) -> int | None:
    if not text:
        return None
    text = text.strip().replace(",", "")
    return int(text) if text.isdigit() else None


def get_price(page: Page) -> tuple[int | None, int | None]:
    """
    <div class="product-price">
      <span class="origin-price">890</span>
      <span>590</span>
    </div>
    沒折扣時可能只有一個 <span>790</span>
    """
    block = page.locator("div.product-price")
    if block.count() == 0:
        return None, None

    origin = block.locator("span.origin-price").first.inner_text().strip() if block.locator("span.origin-price").count() else None
    spans = block.locator("span").all_inner_texts()
    spans = [s.strip() for s in spans if s.strip()]

    if origin:
        original_price = parse_int(origin)
        # 通常最後一個 span 是現價
        current_price = parse_int(spans[-1]) if spans else None
        return original_price, current_price

    # 沒有 origin-price → 視為原價=現價
    current_price = parse_int(spans[-1]) if spans else None
    return current_price, current_price


def get_sizes(page: Page) -> tuple[list[str], list[str]]:
    """
    full_size_list: 所有尺寸（S/M/L...）
    available_list: 可選尺寸（通常是沒 disabled / soldout 的）
    """
    lis = page.locator("#sizeSelect ul.r-select__options li")
    full_sizes: list[str] = []
    available: list[str] = []

    for i in range(lis.count()):
        li = lis.nth(i)
        a = li.locator("a")
        if a.count() == 0:
            continue

        size = a.first.inner_text().strip()
        if not size:
            continue
        full_sizes.append(size)

        cls = (li.get_attribute("class") or "").lower()
        # 這兩個 class 名稱是常見禁用狀態（若你實測 class 名不一樣再改）
        disabled = ("disabled" in cls) or ("soldout" in cls) or ("is-disabled" in cls)
        if not disabled:
            available.append(size)

    return full_sizes, available


def get_product_image_last3(page: Page) -> str | None:
    """
    取所有 div.position-relative 底下的 img
    → 倒數第三張（純商品照）
    """
    imgs = page.locator("div.position-relative img.img-fluid")
    count = imgs.count()
    if count < 3:
        return None
    src = imgs.nth(count - 3).get_attribute("src")
    return src


def click_color_and_wait_image_change(page: Page, li, prev_src: str | None):
    """
    點顏色後等圖片變化（避免抓到上一個顏色的圖）
    """
    li.click()
    page.wait_for_timeout(500)

    # 最多重試幾次，等到倒數第三張 src 變掉
    for _ in range(10):
        cur = get_product_image_last3(page)
        if cur and (prev_src is None or cur != prev_src):
            return cur
        page.wait_for_timeout(300)

    # 如果等不到變化，仍回傳當下抓到的（至少不會 None）
    return get_product_image_last3(page)


def parse_product_page(page: Page, product_url: str, category: str) -> list[dict]:
    """
    回傳：同一 parent_id 下，每個顏色一筆（不因尺寸重複）
    並且：每筆顏色都抓「點完顏色後」的倒數第三張商品照
    """
    results: list[dict] = []

    page.goto(product_url, timeout=60000, wait_until="domcontentloaded")
    page.wait_for_timeout(1200)

    parent_id = extract_parent_id(product_url)
    if not parent_id:
        return results

    sku_url = canonical_sku_url(parent_id)

    # 商品名
    title = page.locator("h1.product-title")
    product_name = title.first.inner_text().strip() if title.count() else None

    # 價格（同商品通常不隨顏色變，這裡先抓一次）
    original_price, current_price = get_price(page)

    # 顏色 li
    color_lis = page.locator("div.product-color ul li")
    if color_lis.count() == 0:
        return results

    prev_img = None

    for i in range(color_lis.count()):
        li = color_lis.nth(i)

        # 點顏色，等圖片更新，再抓倒數第三張
        img_path = click_color_and_wait_image_change(page, li, prev_img)
        prev_img = img_path

        # 顏色名稱：用畫面上的 current label 最穩
        cur_label = page.locator("span.product-color__current")
        color_label = cur_label.first.inner_text().strip() if cur_label.count() else None

        # 尺寸：點完顏色後再讀（不同顏色可能缺碼）
        full_sizes, available = get_sizes(page)

        # 組 sku_id（你要的格式：PAZZO-24074-深灰）
        if not color_label:
            # fallback：用 li 裡 img 的 title/alt
            img = li.locator("img")
            color_label = img.get_attribute("title") or img.get_attribute("alt") or ""

        sku_id = f"PAZZO-{parent_id}-{color_label}"

        results.append({
            "sku_id": sku_id,
            "brand": "PAZZO",
            "parent_id": parent_id,
            "sku_url": sku_url,              # ✅ 補上你要的 sku_url
            "category": category,
            "product_name": product_name,
            "img_path": img_path,
            "color_label": color_label,
            "original_price": original_price,
            "current_price": current_price,
            "full_size_list": full_sizes,
            "available_list": available,
        })

    return results
