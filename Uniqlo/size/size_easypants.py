from __future__ import annotations
from typing import Dict, List, Optional, Tuple, Any

Size = str
# easypants size_chart 建議欄位（至少 waist 必填，其餘選填）
# {
#   "M": {"waist": 67, "thigh_width": 38, "rise": 25.5, "hem_width": 31, "inseam": 72, "outseam": 97.5},
# }
SizeChart = Dict[Size, Dict[str, float]]


MAX_SIZE_GAP = 1  # 只接受理想尺碼 ±1 碼（S/M/L）
SIZE_ORDER = ["XS", "S", "M", "L", "XL", "XXL", "3XL"]


# -----------------------------
# Helpers
# -----------------------------
def _bmi(height_cm: float, weight_kg: float) -> float:
    h_m = height_cm / 100.0
    if h_m <= 0:
        raise ValueError("height_cm must be > 0")
    if weight_kg <= 0:
        raise ValueError("weight_kg must be > 0")
    return weight_kg / (h_m * h_m)


def _clamp(n: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, n))


def _size_index(size: Size) -> int:
    if size not in SIZE_ORDER:
        raise ValueError(f"Unknown size '{size}'. Expected one of: {SIZE_ORDER}")
    return SIZE_ORDER.index(size)


def _index_to_size(idx: int) -> Size:
    idx = _clamp(idx, 0, len(SIZE_ORDER) - 1)
    return SIZE_ORDER[idx]


def _nearest_in_stock(target_idx: int, in_stock_indices: List[int]) -> Optional[int]:
    """Pick closest index in stock. Tie-break: prefer larger size (safer)."""
    if not in_stock_indices:
        return None
    best = None
    best_dist = 10**9
    for idx in in_stock_indices:
        dist = abs(idx - target_idx)
        if dist < best_dist:
            best_dist = dist
            best = idx
        elif dist == best_dist:
            if idx > (best if best is not None else -1):
                best = idx
    return best


def _pick_alternatives(chosen_idx: int, in_stock_indices: List[int], k: int = 2) -> List[int]:
    alts = [i for i in in_stock_indices if i != chosen_idx]
    alts.sort(key=lambda i: (abs(i - chosen_idx), -i))  # close first; tie -> larger
    return alts[:k]


# -----------------------------
# Body size estimation (women)
# -----------------------------
def estimate_body_waist_cm_by_size(size: Size) -> Tuple[float, float]:
    """
    Uniqlo women body waist range (cm) from the common size chart:
    XS 57–63, S 60–66, M 63–69, L 69–75, XL 75–81, XXL 81–87, 3XL 87–93
    """
    ranges = {
        "XS": (57, 63),
        "S":  (60, 66),
        "M":  (63, 69),
        "L":  (69, 75),
        "XL": (75, 81),
        "XXL": (81, 87),
        "3XL": (87, 93),
    }
    return ranges.get(size, (63, 69))


def bmi_to_offset(bmi: float) -> int:
    """BMI bands -> size shift"""
    if bmi < 18.5:
        return -1
    if bmi < 21.5:
        return 0
    if bmi < 24.5:
        return 1
    if bmi < 27.5:
        return 2
    return 3


# -----------------------------
# easypants recommender
# -----------------------------
def recommend_easypants_size(
    height_cm: float,
    weight_kg: float,
    size_chart: SizeChart,
    available_sizes: List[Size],
    user_waist_cm: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Recommend size for category=easypants.

    Required:
      - size_chart[size]["waist"]  (cm)  # 商品尺寸表的「腰圍」
      - available_sizes            # 有庫存尺碼（你的 available_list）

    Optional:
      - user_waist_cm              # 使用者腰圍（不知道可 None）

    Returns:
      {
        "recommended_size": "M",
        "alternatives": ["L","S"],
        "reasoning": "..."
      }
    """
    if not size_chart:
        raise ValueError("size_chart is empty")

    if not available_sizes:
        return {
            "recommended_size": None,
            "alternatives": [],
            "reasoning": "目前此商品沒有任何可購買庫存尺碼（available_sizes 是空的）。",
        }

    # keep only sizes recognized and present in chart
    valid_sizes = [s for s in SIZE_ORDER if s in size_chart]
    if not valid_sizes:
        raise ValueError("size_chart has no recognized sizes (XS~3XL).")

    # in stock indices restricted to valid sizes
    in_stock = [s for s in available_sizes if s in valid_sizes]
    in_stock_indices = sorted({_size_index(s) for s in in_stock})
    if not in_stock_indices:
        return {
            "recommended_size": None,
            "alternatives": [],
            "reasoning": "此商品目前有庫存的尺碼不在尺寸表中（或都不是 XS~3XL）。",
        }

    # 1) BMI -> offset
    bmi = _bmi(height_cm, weight_kg)
    offset = bmi_to_offset(bmi)

    # 2) base size by height (rough, for length/proportion)
    if height_cm < 155:
        base = "XS"
    elif height_cm < 160:
        base = "S"
    elif height_cm < 166:
        base = "M"
    elif height_cm < 172:
        base = "L"
    else:
        base = "XL"

    base_idx = _size_index(base)
    target_idx = _clamp(base_idx + offset, 0, len(SIZE_ORDER) - 1)

    # 3) inventory-aware nearest
    chosen_idx = _nearest_in_stock(target_idx, in_stock_indices)
    if chosen_idx is None:
        return {
            "recommended_size": None,
            "alternatives": [],
            "reasoning": "找不到有庫存的尺碼。",
        }
    chosen_size = _index_to_size(chosen_idx)

    # 4) waist measurement correction (key for pants)
    #    - If user_waist_cm is missing, estimate from body size range of the chosen_size
    if user_waist_cm is not None:
        body_waist = float(user_waist_cm)
        body_waist_source = "user"
    else:
        low, high = estimate_body_waist_cm_by_size(chosen_size)
        body_waist = (low + high) / 2.0
        body_waist_source = "estimated_from_size_range"

    def garment_waist(size: Size) -> Optional[float]:
        m = size_chart.get(size, {})
        w = m.get("waist")
        return float(w) if w is not None else None

    # For easypants (often elastic/relaxed), allow small ease.
    # If you later have waistband type, you can tune these.
    MIN_EASE = 0.0
    MAX_EASE = 6.0
    TARGET_EASE = (MIN_EASE + MAX_EASE) / 2.0

    # choose best in-stock size by waist fit if waist exists
    if garment_waist(chosen_size) is not None:
        candidates = []
        for idx in in_stock_indices:
            s = _index_to_size(idx)
            gw = garment_waist(s)
            if gw is None:
                continue
            ease = gw - body_waist
            # scoring:
            # - prefer ease within [MIN_EASE, MAX_EASE]
            # - under-fit (negative ease) penalize heavily
            if MIN_EASE <= ease <= MAX_EASE:
                penalty = abs(ease - TARGET_EASE)
                ok = True
            else:
                if ease < MIN_EASE:
                    penalty = (MIN_EASE - ease) * 3.0
                else:
                    penalty = (ease - MAX_EASE) * 1.0
                ok = False
            candidates.append((penalty, ok, idx, s, ease, gw))

        if candidates:
            candidates.sort(key=lambda x: (x[0], not x[1], -x[2]))  # low penalty; ok first; tie -> larger
            best = candidates[0]
            chosen_idx = best[2]
            chosen_size = best[3]


            # -------------------------------------------------
            # ❌ 庫存尺寸距離理想尺碼過遠 → 不推薦此商品
            # -------------------------------------------------
            final_idx = _size_index(chosen_size)
            gap = abs(final_idx - target_idx)

            if gap > MAX_SIZE_GAP:
                lo = max(0, target_idx - MAX_SIZE_GAP)
                hi = min(len(SIZE_ORDER) - 1, target_idx + MAX_SIZE_GAP)
                acceptable_sizes = [SIZE_ORDER[i] for i in range(lo, hi + 1)]

                return {
                    "recommended_size": None,
                    "alternatives": [],
                    "reasoning": (
                        f"你的建議尺碼區間為 {', '.join(acceptable_sizes)}，"
                        f"但目前庫存僅剩較不適合的尺碼（最近可買尺碼為 {chosen_size}），"
                        f"因此不推薦此商品。"
                    ),
                    "debug": {
                        "target_size": _index_to_size(target_idx),
                        "chosen_size": chosen_size,
                        "gap": gap,
                        "acceptable_sizes": acceptable_sizes,
                        "in_stock_sizes": in_stock,
                    },
                }

    # alternatives (in stock only)
    alt_indices = _pick_alternatives(chosen_idx, in_stock_indices, k=2)
    alternatives = [_index_to_size(i) for i in alt_indices]

    # reasoning (不含偏好版型那三行)
    reasoning_lines = []
    reasoning_lines.append(
        f"BMI={bmi:.1f}（身高{height_cm:.0f}cm / 體重{weight_kg:.0f}kg）→ 尺碼位移 {offset:+d} 碼。"
    )
    reasoning_lines.append(
        f"以身高先選基準 {base}，套用位移後目標尺碼≈{_index_to_size(target_idx)}；再依庫存挑最近可買尺碼。"
    )

    gw = garment_waist(chosen_size)
    if gw is not None:
        reasoning_lines.append(
            f"腰圍檢查：身體腰圍({body_waist_source})≈{body_waist:.0f}cm，"
            f"{chosen_size} 商品腰圍≈{gw:.0f}cm（差≈{gw-body_waist:.0f}cm）→ 選 {chosen_size}。"
        )
    else:
        reasoning_lines.append("此商品尺寸表缺少腰圍(waist)，因此無法做腰圍校正，採用 BMI + 庫存規則。")

    return {
        "recommended_size": chosen_size,
        "alternatives": alternatives,
        "reasoning": "\n".join(reasoning_lines),
    }


# -----------------------------
# Example usage
# -----------------------------
if __name__ == "__main__":
    # 你截圖的 easypants 尺寸表：請自行把數字填進來（至少 waist 必須有）
    product_size_chart = {
        "XS": {"waist": 59, "thigh_width": 35, "rise": 24,   "hem_width": 29, "inseam": 70, "outseam": 94},
        "S":  {"waist": 63, "thigh_width": 36.5, "rise": 24.5, "hem_width": 30, "inseam": 71.5, "outseam": 96},
        "M":  {"waist": 67, "thigh_width": 38, "rise": 25.5, "hem_width": 31, "inseam": 72, "outseam": 97.5},
        "L":  {"waist": 71, "thigh_width": 39, "rise": 26.5, "hem_width": 32, "inseam": 72, "outseam": 98.5},
        "XL": {"waist": 77, "thigh_width": 41, "rise": 27.5, "hem_width": 33, "inseam": 72, "outseam": 99.5},
        "XXL":{"waist": 83, "thigh_width": 43, "rise": 28,   "hem_width": 34.5, "inseam": 72.5, "outseam": 100.5},
        "3XL":{"waist": 91, "thigh_width": 45, "rise": 28.5, "hem_width": 36, "inseam": 73, "outseam": 101.5},
    }

    # 你的爬蟲 available_list（有庫存的尺碼）
    in_stock = ["S", "M", "XL"]

    result = recommend_easypants_size(
        height_cm=160,
        weight_kg=55,
        size_chart=product_size_chart,
        available_sizes=in_stock,
        user_waist_cm=None,  # 不知道腰圍可以不填
    )

    print(f"推薦尺寸: {result['recommended_size']}")
    print(f"備選尺寸: {', '.join(result['alternatives']) if result['alternatives'] else '無'}")
    print("說明:")
    print(result["reasoning"])