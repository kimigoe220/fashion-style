from __future__ import annotations
from typing import Dict, List, Optional, Tuple, Any

Size = str
SizeChart = Dict[Size, Dict[str, float]]  # e.g. {"M":{"waist":70,"hip":98,"length":78}, ...}


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
# Body size estimation (women) - from Uniqlo size table
# -----------------------------
def estimate_body_waist_cm_by_size(size: Size) -> Tuple[float, float]:
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


def estimate_body_hip_cm_by_size(size: Size) -> Tuple[float, float]:
    # 常見女裝臀圍區間（你圖上那張身體尺寸表的臀圍列）
    ranges = {
        "XS": (82, 88),
        "S":  (85, 91),
        "M":  (88, 94),
        "L":  (94, 100),
        "XL": (100, 106),
        "XXL": (106, 112),
        "3XL": (112, 118),
    }
    return ranges.get(size, (88, 94))


def bmi_to_offset(bmi: float) -> int:
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
# Skirt recommender
# -----------------------------
def recommend_skirt_size(
    height_cm: float,
    weight_kg: float,
    size_chart: SizeChart,
    available_sizes: List[Size],
    user_waist_cm: Optional[float] = None,
    user_hip_cm: Optional[float] = None,
) -> Dict[str, Any]:
    """
    category=skirt

    Required:
      - available_sizes: 有庫存尺碼（你的 available_list）
      - size_chart: 每尺碼的裙子尺寸
          建議至少有 waist
          若有 hip 會更準
          length 可做長度參考（目前只做說明，不硬卡）

    Output keys:
      - recommended_size
      - alternatives
      - reasoning
    """
    if not size_chart:
        raise ValueError("size_chart is empty")
    if not available_sizes:
        return {
            "recommended_size": None,
            "alternatives": [],
            "reasoning": "目前此商品沒有任何可購買庫存尺碼（available_sizes 是空的）。",
        }

    valid_sizes = [s for s in SIZE_ORDER if s in size_chart]
    if not valid_sizes:
        raise ValueError("size_chart has no recognized sizes (XS~3XL).")

    in_stock = [s for s in available_sizes if s in valid_sizes]
    in_stock_indices = sorted({_size_index(s) for s in in_stock})
    if not in_stock_indices:
        return {
            "recommended_size": None,
            "alternatives": [],
            "reasoning": "此商品目前有庫存的尺碼不在尺寸表中（或都不是 XS~3XL）。",
        }

    bmi = _bmi(height_cm, weight_kg)
    offset = bmi_to_offset(bmi)

    # base size by height (rough)
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

    chosen_idx = _nearest_in_stock(target_idx, in_stock_indices)
    if chosen_idx is None:
        return {"recommended_size": None, "alternatives": [], "reasoning": "找不到有庫存的尺碼。"}
    chosen_size = _index_to_size(chosen_idx)

    # Estimate body waist/hip if missing
    if user_waist_cm is not None:
        body_waist = float(user_waist_cm)
        waist_source = "user"
    else:
        w_lo, w_hi = estimate_body_waist_cm_by_size(chosen_size)
        body_waist = (w_lo + w_hi) / 2.0
        waist_source = "estimated_from_size_range"

    if user_hip_cm is not None:
        body_hip = float(user_hip_cm)
        hip_source = "user"
    else:
        h_lo, h_hi = estimate_body_hip_cm_by_size(chosen_size)
        body_hip = (h_lo + h_hi) / 2.0
        hip_source = "estimated_from_size_range"

    def garment_waist(size: Size) -> Optional[float]:
        return float(size_chart.get(size, {}).get("waist")) if size_chart.get(size, {}).get("waist") is not None else None

    def garment_hip(size: Size) -> Optional[float]:
        v = size_chart.get(size, {}).get("hip")
        return float(v) if v is not None else None

    def garment_length(size: Size) -> Optional[float]:
        v = size_chart.get(size, {}).get("length")
        return float(v) if v is not None else None

    # Skirt fit: waistband needs a bit ease; hip needs more ease if it's not stretch.
    # We'll use gentle default bands:
    WAIST_MIN_EASE, WAIST_MAX_EASE = 0.0, 4.0
    HIP_MIN_EASE, HIP_MAX_EASE = 2.0, 10.0

    # Score candidates using waist (required) + hip (if exists)
    candidates = []
    for idx in in_stock_indices:
        s = _index_to_size(idx)
        gw = garment_waist(s)
        if gw is None:
            continue  # cannot score without waist
        ease_w = gw - body_waist

        # waist penalty (under-fit heavy)
        if WAIST_MIN_EASE <= ease_w <= WAIST_MAX_EASE:
            p_w = abs(ease_w - (WAIST_MIN_EASE + WAIST_MAX_EASE) / 2.0)
        else:
            p_w = (WAIST_MIN_EASE - ease_w) * 3.0 if ease_w < WAIST_MIN_EASE else (ease_w - WAIST_MAX_EASE) * 1.0

        gh = garment_hip(s)
        if gh is not None:
            ease_h = gh - body_hip
            if HIP_MIN_EASE <= ease_h <= HIP_MAX_EASE:
                p_h = abs(ease_h - (HIP_MIN_EASE + HIP_MAX_EASE) / 2.0)
            else:
                p_h = (HIP_MIN_EASE - ease_h) * 3.0 if ease_h < HIP_MIN_EASE else (ease_h - HIP_MAX_EASE) * 1.0
            penalty = p_w * 0.7 + p_h * 0.3  # waist more important
        else:
            ease_h = None
            penalty = p_w

        candidates.append((penalty, idx, s, gw, ease_w, gh, ease_h))

    if candidates:
        candidates.sort(key=lambda x: (x[0], -x[1]))  # lower penalty, tie -> larger
        best = candidates[0]
        chosen_idx, chosen_size = best[1], best[2]

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

    # alternatives
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
    gh = garment_hip(chosen_size)
    gl = garment_length(chosen_size)

    if gw is not None:
        reasoning_lines.append(
            f"腰圍檢查：身體腰圍({waist_source})≈{body_waist:.0f}cm，"
            f"{chosen_size} 商品腰圍≈{gw:.0f}cm（差≈{gw-body_waist:.0f}cm）→ 選 {chosen_size}。"
        )
    else:
        reasoning_lines.append("此商品尺寸表缺少腰圍(waist)，因此無法做腰圍校正，採用 BMI + 庫存規則。")

    if gh is not None:
        reasoning_lines.append(
            f"臀圍參考：身體臀圍({hip_source})≈{body_hip:.0f}cm，"
            f"{chosen_size} 商品臀圍≈{gh:.0f}cm（差≈{gh-body_hip:.0f}cm）。"
        )

    if gl is not None:
        reasoning_lines.append(f"裙長參考：{chosen_size} 裙長≈{gl:.1f}cm。")

    return {
        "recommended_size": chosen_size,
        "alternatives": alternatives,
        "reasoning": "\n".join(reasoning_lines),
    }


# -----------------------------
# Example usage
# -----------------------------
if __name__ == "__main__":
    # 你可以把下方數字換成你爬到的 skirt 尺寸表（至少 waist）
    product_size_chart = {
        "XS": {"waist": 66, "length": 86.5},   # hip 若有就加 "hip": xxx
        "S":  {"waist": 70, "length": 87.0},
        "M":  {"waist": 74, "length": 87.5},
        "L":  {"waist": 78, "length": 88.5},
        "XL": {"waist": 84, "length": 89.5},
        "XXL":{"waist": 90, "length": 90.0},
        "3XL":{"waist": 96, "length": 90.5},
    }

    in_stock = ["S", "M", "XL"]

    result = recommend_skirt_size(
        height_cm=165,
        weight_kg=60,
        size_chart=product_size_chart,
        available_sizes=in_stock,
        user_waist_cm=None,  # 不知道腰圍可以不填
        user_hip_cm=None,    # 不知道臀圍也可不填
    )

    print(f"推薦尺寸: {result['recommended_size']}")
    print(f"備選尺寸: {', '.join(result['alternatives']) if result['alternatives'] else '無'}")
    print("說明:")
    print(result["reasoning"])