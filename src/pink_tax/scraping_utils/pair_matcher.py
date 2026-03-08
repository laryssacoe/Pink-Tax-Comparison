"""
Single source of truth for the core pink_tax_pct calculation,
pair ID generation, and pair validation logic.

Formula:
    pink_tax_pct = (female_ppu - male_ppu) / male_ppu × 100

    where ppu = price_local / size_ml_or_g  (price per ml/g/unit)

Positive values  → women pay more per unit (pink tax exists)
Negative values  → men pay more per unit   ("blue tax")
"""

import re
from dataclasses import dataclass

@dataclass
class PairValidation:
    """
    Result of validating a female/male product pair.
    """

    is_valid: bool
    warnings: list[str]
    recommended_quality: int

def compute_pink_tax(female_ppu: float, male_ppu: float) -> float | None:
    """
    Core pink tax formula.

    Parameters
    ----------
    female_ppu: price per unit for female-targeted product (any currency)
    male_ppu: price per unit for male-targeted product (same currency)

    Returns
    -------
    float: pink_tax_pct, or None if male_ppu is zero

    >>> compute_pink_tax(0.65, 0.598)
    8.70
    >>> compute_pink_tax(286.0, 190.0)
    50.53
    """

    if male_ppu is None or male_ppu == 0:
        return None
    if female_ppu is None:
        return None
    pct = (female_ppu - male_ppu) / male_ppu * 100
    return round(pct, 4)

def make_pair_code(brand: str, category: str, city: str, index: int) -> str:
    """
    Generate a canonical pair code.

    >>> make_pair_code("Dove", "Body Wash", "Hyderabad", 1)
    'DOVE-BODYWASH-HYD-01'

    >>> make_pair_code("Head & Shoulders", "Shampoo", "Tokyo", 3)
    'HNS-SHAMPOO-TKY-03'
    """

    brand_abbrev = {
        "Head & Shoulders": "HNS",
        "Gillette/Venus":   "GILLET",
        "Mandom/Gatsby":    "GATSBY",
        "Kose/Softymo":     "KOSE",
        "Kao/Merit":        "KAO",
        "WOW Skin Science": "WOW",
    }

    city_code = {
        "Hyderabad": "HYD",
        "Tokyo":     "TKY",
    }.get(city, city[:3].upper())

    b = brand_abbrev.get(brand, re.sub(r"[^A-Z]", "", brand.upper())[:8])
    c = re.sub(r"[^A-Z]", "", category.upper().replace(" ", ""))[:8]

    return f"{b}-{c}-{city_code}-{index:02d}"

def validate_pair(female_name: str, male_name: str,
                  female_size: float, male_size: float,
                  female_brand: str, male_brand: str,
                  female_ingredients: str | None = None,
                  male_ingredients: str | None = None) -> PairValidation:
    """
    Validate a female/male product pair and suggest a match_quality score.

    match_quality scale (based on Moshary et al. 2023 methodology):
      5 = same brand, same line, same size ±5%, same core formula
      4 = same brand, same line, size within 20%
      3 = same brand, different sub-line, same category/function
      2 = different brand, same function/format
      1 = weak match, too different to compare fairly

    Parameters
    ----------
    All parameters are strings or floats from the product records.

    Returns
    -------
    PairValidation with .is_valid, .warnings, .recommended_quality
    """

    warnings = []
    quality = 5

    if female_brand.lower() != male_brand.lower():
        warnings.append(f"Different brands: '{female_brand}' vs '{male_brand}'")
        quality = min(quality, 2)

    if female_size > 0 and male_size > 0:
        ratio = abs(female_size - male_size) / max(female_size, male_size)
        if ratio > 0.5:
            warnings.append(
                f"Large size mismatch: {female_size} vs {male_size} "
                f"({ratio*100:.0f}% difference). Consider excluding."
            )
            quality = min(quality, 1)
        elif ratio > 0.2:
            warnings.append(
                f"Moderate size mismatch: {female_size} vs {male_size} "
                f"({ratio*100:.0f}% difference)."
            )
            quality = min(quality, 3)
        elif ratio > 0.05:
            warnings.append(f"Minor size difference: {female_size} vs {male_size}.")
            quality = min(quality, 4)

    if female_ingredients and male_ingredients:
        f_ings = set(i.strip().lower() for i in female_ingredients.split(","))
        m_ings = set(i.strip().lower() for i in male_ingredients.split(","))
        overlap = f_ings & m_ings
        if not overlap:
            warnings.append("No overlapping ingredients, with very different formulations.")
            quality = min(quality, 2)
        elif len(overlap) < min(len(f_ings), len(m_ings)) / 2:
            warnings.append(f"Low ingredient overlap: only {overlap}")
            quality = min(quality, 3)

    is_valid = quality >= 2

    return PairValidation(
        is_valid=is_valid,
        warnings=warnings,
        recommended_quality=quality,
    )
