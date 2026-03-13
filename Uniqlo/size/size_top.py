from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any
import math

# -----------------------------
# Types
# -----------------------------
Size = str
SizeChart = Dict[Size, Dict[str, float]]  # e.g. {"S":{"chest_width":57,"length":52,"sleeve":73}, ...}


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
    """
    Pick closest index in stock. If tie, prefer the larger size (safer fit).
    """
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
            # tie-break: prefer bigger size (higher idx)
            if idx > (best if best is not None else -1):
                best = idx
    return best


def _pick_alternatives(chosen_idx: int, in_stock_indices: List[int], k: int = 2) -> List[int]:
    """
    Return up to k alternative indices (closest first), excluding chosen.
    """
    alts = [i for i in in_stock_indices if i != chosen_idx]
    alts.sort(key=lambda i: (abs(i - chosen_idx), -i))  # close first; tie -> larger
    return alts[:k]


# -----------------------------
# Core logic
# -----------------------------
def estimate_body_bust_cm_by_size(size: Size) -> Tuple[float, float]:
    """
    Rough body-bust ranges based on your Uniqlo table (women), in cm.
    Return (low, high). We'll use midpoint as estimate if user doesn't provide bust.
    """
    ranges = {
        "XS": (74, 80),
        "S":  (77, 83),
        "M":  (80, 86),
        "L":  (86, 92),
        "XL": (92, 98),
        "XXL": (98, 104),
        "3XL": (104, 110),
    }
    if size not in ranges:
        # fallback: assume "M"
        return (80, 86)
    return ranges[size]


def bmi_to_offset(bmi: float) -> int:
    """
    Use BMI bands to shift size up/down.
    """
    if bmi < 18.5:
        return -1
    if bmi < 21.5:
        return 0
    if bmi < 24.5:
        return 1
    if bmi < 27.5:
        return 2
    return 3


def preference_to_ease_cm(fit_preference: str) -> Tuple[int, int]:
    """
    Return (min_ease, max_ease) in cm for the *bust circumference*.
    This is how much larger the garment bust should be than body bust.
    """
    fit_preference = (fit_preference or "").strip().lower()
    if fit_preference in ["slim", "fitted", "合身", "貼身"]:
        return (6, 10)
    if fit_preference in ["regular", "normal", "舒適", "一般", "正常"]:
        return (10, 16)
    if fit_preference in ["relaxed", "oversized", "寬鬆", "偏寬", "大一點"]:
        return (16, 24)
    # default
    return (10, 16)


def recommend_size(
    height_cm: float,
    weight_kg: float,
    size_chart: SizeChart,
    available_sizes: List[Size],
    fit_preference: str = "regular",
    user_bust_cm: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Recommend best size for a product, considering:
    - User height/weight -> BMI -> size offset
    - Inventory (available_sizes)
    - Product measurement (chest_width -> garment bust circumference)
    - Fit preference (slim/regular/oversized) affects required ease

    size_chart expects keys like:
      size_chart["M"] = {"length": 53, "chest_width": 59, "sleeve": 75}
    available_sizes like ["S","M","L"].

    Returns dict with:
      recommended_size, alternatives, reasoning, debug
    """
    if not size_chart:
        raise ValueError("size_chart is empty")
    if not available_sizes:
        return {
            "recommended_size": None,
            "alternatives": [],
            "reasoning": "目前此商品沒有任何可購買庫存尺碼（available_sizes 是空的）。",
            "debug": {},
        }

    # Keep only sizes present in chart and in our known order
    valid_sizes = [s for s in SIZE_ORDER if s in size_chart]
    if not valid_sizes:
        raise ValueError("size_chart has no recognized sizes (XS~3XL).")

    # In-stock indices restricted to valid_sizes
    in_stock = [s for s in available_sizes if s in valid_sizes]
    in_stock_indices = sorted({_size_index(s) for s in in_stock})
    if not in_stock_indices:
        return {
            "recommended_size": None,
            "alternatives": [],
            "reasoning": "此商品目前有庫存的尺碼不在尺寸表中（或都不是 XS~3XL）。",
            "debug": {"available_sizes": available_sizes, "valid_sizes": valid_sizes},
        }

    bmi = _bmi(height_cm, weight_kg)
    offset = bmi_to_offset(bmi)
    min_ease, max_ease = preference_to_ease_cm(fit_preference)
    target_ease = (min_ease + max_ease) / 2.0

    # Step 1: pick a base size by height only (rough)
    # For a simple, stable default: map height to a base index (XS..3XL) around S/M.
    # You can refine later using Uniqlo height ranges, but this works OK for a first version.
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

    # Step 2: apply BMI offset
    target_idx = _clamp(base_idx + offset, 0, len(SIZE_ORDER) - 1)

    # Step 3: inventory-aware nearest size
    chosen_idx = _nearest_in_stock(target_idx, in_stock_indices)
    if chosen_idx is None:
        return {
            "recommended_size": None,
            "alternatives": [],
            "reasoning": "找不到有庫存的尺碼。",
            "debug": {"target_idx": target_idx, "in_stock_indices": in_stock_indices},
        }
    chosen_size = _index_to_size(chosen_idx)

    # Step 4: measurement correction using bust ease
    # Estimate body bust:
    if user_bust_cm is not None:
        body_bust = float(user_bust_cm)
        body_bust_source = "user"
    else:
        low, high = estimate_body_bust_cm_by_size(chosen_size)
        body_bust = (low + high) / 2.0
        body_bust_source = "estimated_from_size_range"

    # compute garment bust circumference for each in-stock size (needs chest_width)
    def garment_bust(size: Size) -> Optional[float]:
        m = size_chart.get(size, {})
        cw = m.get("chest_width")
        if cw is None:
            return None
        return float(cw) * 2.0

    # If chart has chest_width, we can adjust
    if garment_bust(chosen_size) is not None:
        # Find best in-stock size that hits target ease closest (>= min_ease preferred)
        candidates = []
        for idx in in_stock_indices:
            s = _index_to_size(idx)
            gb = garment_bust(s)
            if gb is None:
                continue
            ease = gb - body_bust
            # score:
            # - prefer ease within [min_ease, max_ease]
            # - otherwise penalize distance to nearest boundary
            if min_ease <= ease <= max_ease:
                penalty = abs(ease - target_ease)  # smaller is better
                ok = True
            else:
                # penalize under-fit much more than over-fit
                if ease < min_ease:
                    penalty = (min_ease - ease) * 3.0
                else:
                    penalty = (ease - max_ease) * 1.0
                ok = False
            candidates.append((penalty, ok, idx, s, ease, gb))

        if candidates:
            candidates.sort(key=lambda x: (x[0], not x[1], -x[2]))  # low penalty; ok first; tie -> bigger
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

    # Alternatives
    alt_indices = _pick_alternatives(chosen_idx, in_stock_indices, k=2)
    alternatives = [_index_to_size(i) for i in alt_indices]

    # -----------------------------
    # Build reasoning（精簡版）
    # -----------------------------
    reasoning_lines = []

    # 1️⃣ BMI → 尺碼位移
    reasoning_lines.append(
        f"BMI={bmi:.1f}（身高{height_cm:.0f}cm / 體重{weight_kg:.0f}kg）→ 尺碼位移 {offset:+d} 碼。"
    )

    # 2️⃣ 身高基準 + 庫存調整
    reasoning_lines.append(
        f"以身高先選基準 {base}，套用位移後目標尺碼≈{_index_to_size(target_idx)}；再依庫存挑最近可買尺碼。"
    )

    # ❌ 完全不再提 fit_preference / 活動量區間

    # 3️⃣ 胸圍檢查（若有尺寸表）
    gb = garment_bust(chosen_size)
    if gb is not None:
        reasoning_lines.append(
            f"胸圍檢查：身體胸圍({body_bust_source})≈{body_bust:.0f}cm，"
            f"{chosen_size} 衣服胸圍≈{gb:.0f}cm（活動量≈{gb-body_bust:.0f}cm）→ 選 {chosen_size}。"
        )
    else:
        reasoning_lines.append(
            "此商品尺寸表缺少胸寬(chest_width)，因此無法做胸圍校正，採用 BMI + 庫存規則。"
        )

    return {
        "recommended_size": chosen_size,
        "alternatives": alternatives,
        "reasoning": "\n".join(reasoning_lines),
        "debug": {
            "bmi": bmi,
            "offset": offset,
            "base_size": base,
            "target_size": _index_to_size(target_idx),
            "in_stock_sizes": in_stock,
            "fit_preference": fit_preference,
            "body_bust_cm": body_bust,
            "body_bust_source": body_bust_source,
        },
    }


# -----------------------------
# Example usage
# -----------------------------
if __name__ == "__main__":
    # Example product chart (from your screenshot style)
    product_size_chart = {
        "XS": {"length": 51, "chest_width": 55, "sleeve": 71},
        "S":  {"length": 52, "chest_width": 57, "sleeve": 73},
        "M":  {"length": 53, "chest_width": 59, "sleeve": 75},
        "L":  {"length": 54, "chest_width": 61, "sleeve": 76.5},
        "XL": {"length": 55, "chest_width": 64, "sleeve": 77.5},
        "XXL":{"length": 56, "chest_width": 67, "sleeve": 78},
        "3XL":{"length": 57, "chest_width": 70, "sleeve": 78.5},
    }

    # Suppose inventory only has these:
    in_stock = ["S", "M", "XL"]

    result = recommend_size(
        height_cm=160,
        weight_kg=55,
        size_chart=product_size_chart,
        available_sizes=in_stock,
        fit_preference="regular",
        user_bust_cm=None,  # you can pass e.g. 86 if user knows
    )

    print(f"推薦尺寸: {result['recommended_size']}")
    print(
    f"備選尺寸: {', '.join(result['alternatives']) if result['alternatives'] else '無'}"
    )
    print("說明:")
    print(result["reasoning"])