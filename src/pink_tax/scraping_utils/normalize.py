"""
Handles:
  - Size string parsing: "500ml", "1.5L", "100g" → (500.0, "ml")
  - Price-per-unit calculation (critical for comparing different sizes)
  - Brand name standardization
  - Gender label normalization and keyword detection
"""

import re

brand_aliases = {
    "dove":              "Dove",
    "dove men":          "Dove",
    "dove men+care":     "Dove",
    "nivea":             "Nivea",
    "nivea men":         "Nivea",
    "gillette":          "Gillette/Venus",
    "venus":             "Gillette/Venus",
    "gillette venus":    "Gillette/Venus",
    "head & shoulders":  "Head & Shoulders",
    "head and shoulders":"Head & Shoulders",
    "h&s":               "Head & Shoulders",
    "pantene":           "Pantene",
    "pantene pro-v":     "Pantene",
    "vaseline":          "Vaseline",
    "vaseline men":      "Vaseline",
    "garnier":           "Garnier",
    "garnier men":       "Garnier",
    "olay":              "Olay",
    "olay men":          "Olay",
    "parachute":         "Parachute",
    "mamaearth":         "Mamaearth",
    "mama earth":        "Mamaearth",
    "biotique":          "Biotique",
    "himalaya":          "Himalaya",
    "wow":               "WOW Skin Science",
    "wow skin":          "WOW Skin Science",
    "fiama":             "Fiama",
    "fogg":              "Fogg",
    "engage":            "Engage",
    "indulekha":         "Indulekha",
    "pond's":            "Pond's",
    "ponds":             "Pond's",
    "lakme":             "Lakme",
    "park avenue":       "Park Avenue",
    "set wet":           "Set Wet",
    "biore":             "Bioré",
    "bioré":             "Bioré",
    "shiseido":          "Shiseido",
    "curel":             "Curel",
    "kao":               "Kao/Merit",
    "merit":             "Kao/Merit",
    "rohto":             "Rohto",
    "hadalabo":          "Rohto",
    "dhc":               "DHC",
    "lion":              "Lion",
    "gatsby":            "Mandom/Gatsby",
    "mandom":            "Mandom/Gatsby",
    "cow brand":         "Cow Brand",
    "kose":              "Kose/Softymo",
    "softymo":           "Kose/Softymo",
    "sana":              "Sana",
    "clinica":           "Clinica",
}

gender_aliases = {
    "f":        "female",
    "female":   "female",
    "women":    "female",
    "woman":    "female",
    "girls":    "female",
    "girl":     "female",
    "ladies":   "female",
    "mahila":   "female",
    "महिला":    "female",
    "स्त्री":    "female",
    "महिलाओं के लिए": "female",
    "మహిళ":     "female",
    "మహిళల కోసం": "female",
    "లేడీస్":   "female",
    "her":      "female",
    "m":        "male",
    "male":     "male",
    "men":      "male",
    "man":      "male",
    "boys":     "male",
    "boy":      "male",
    "पुरुष":    "male",
    "पुरुषों के लिए": "male",
    "मेंस":     "male",
    "మగవారి":  "male",
    "పురుష":   "male",
    "పురుషుల కోసం": "male",
    "మెన్స్":   "male",
    "his":      "male",
    "neutral":  "neutral",
    "unisex":   "neutral",
    "यूनिसेक्स": "neutral",
    "यूनिसेक्स्": "neutral",
    "యూనిసెక్స్": "neutral",
    "n":        "neutral",
}
allowed_gender_values = {"female", "male", "neutral"}

female_keywords_en = (
    "women",
    "woman",
    "female",
    "for her",
    "ladies",
    "lady",
    "girl",
    "girls",
    "womens",
    "mahila",
    "mahilao ke liye",
    "stri",
    "stree",
    "ladki",
    "ladkiyon ke liye",
    "aadavaru",
    "aadavari",
)
male_keywords_en = (
    "men",
    "man",
    "male",
    "for him",
    "mens",
    "boy",
    "boys",
    "purush",
    "purusho ke liye",
    "mardon ke liye",
    "mard",
    "magavaru",
    "magavari",
)
neutral_keywords_en = (
    "unisex",
    "gender neutral",
    "neutral",
    "for all",
    "all genders",
    "sabke liye",
    "andariki",
)
female_keywords_jp = (
    "女性用",
    "女性",
    "レディース",
)
male_keywords_jp = (
    "男性用",
    "男性",
    "メンズ",
)
neutral_keywords_jp = (
    "ユニセックス",
    "男女兼用",
)
female_keywords_hi = (
    "महिला",
    "महिलाओं के लिए",
    "स्त्री",
    "लेडीज़",
    "लड़कियों के लिए",
)
male_keywords_hi = (
    "पुरुष",
    "पुरुषों के लिए",
    "मेंस",
    "मेन",
    "लड़कों के लिए",
)
neutral_keywords_hi = (
    "यूनिसेक्स",
    "सभी के लिए",
    "जेंडर न्यूट्रल",
)
female_keywords_TE = (
    "మహిళ",
    "మహిళల కోసం",
    "లేడీస్",
    "ఆడవారి",
    "ఆడవారికి",
)
male_keywords_TE = (
    "పురుష",
    "పురుషుల కోసం",
    "మెన్స్",
    "మెన్",
    "మగవారి",
    "మగవారికి",
)
neutral_keywords_TE = (
    "యూనిసెక్స్",
    "అందరికీ",
    "లింగ తటస్థ",
)

space_re = re.compile(r"\s+")
non_alnum_latin_re = re.compile(r"[^0-9a-z\s]+")

category_unit_types = {
    "Body Wash":                   "ml",
    "Bar Soap":                    "g",
    "Shampoo":                     "ml",
    "Conditioner":                 "ml",
    "Deodorant Roll-On":           "ml",
    "Deodorant Spray":             "ml",
    "Body Lotion":                 "ml",
    "Facial Cleanser":             "ml",
    "Face Moisturizer":            "ml",
    "Hair Oil":                    "ml",
    "Hand Cream":                  "ml",
    "Razor (3-blade starter kit)": "unit",
    "Razor Cartridges":            "count",
    "Sunscreen":                   "ml",
    "Toothpaste":                  "g",
    "Hair Gel / Serum":            "ml",
}


def normalize_brand(raw: str) -> str:
    """
    Return canonical brand name.

    >>> normalize_brand("DOVE MEN+CARE")
    'Dove'
    >>> normalize_brand("H&S")
    'Head & Shoulders'
    """

    key = raw.strip().lower()

    return brand_aliases.get(key, raw.strip().title())


def normalize_gender(raw: str) -> str:
    """
    Return 'female', 'male', or 'neutral'.

    >>> normalize_gender("F")
    'female'
    >>> normalize_gender("Women")
    'female'
    """

    key = raw.strip().lower()

    return gender_aliases.get(key, "neutral")

def _normalize_latin_text(raw: str) -> str:
    """
    Lowercase and simplify latin text for keyword matching.
    """

    lowered = str(raw or "").lower()
    cleaned = non_alnum_latin_re.sub(" ", lowered)
    return space_re.sub(" ", cleaned).strip()

def find_english_hits(text: str, terms: tuple[str, ...]) -> list[str]:
    """
    Return matching english terms with word-boundary checks.
    """

    hits: list[str] = []
    for term in terms:
        pattern = rf"\b{re.escape(term)}\b"
        if re.search(pattern, text):
            hits.append(term)
    return hits

def find_substring_hits(text: str, terms: tuple[str, ...]) -> list[str]:
    """
    Return matching non-latin script terms with direct substring checks.
    """

    hits: list[str] = []
    for term in terms:
        if term in text:
            hits.append(term)
    return hits

def keyword_gender_label(product_name: str) -> tuple[str, str]:
    """
    Infer product gender marketing from multilingual keyword hints.

    Returns (label, evidence), where label is one of:
    - 'female', 'male', 'neutral', 'unknown', 'conflict'
    """
    raw = str(product_name or "")
    latin = _normalize_latin_text(raw)

    female_hits = (
        find_english_hits(latin, female_keywords_en)
        + find_substring_hits(raw, female_keywords_jp)
        + find_substring_hits(raw, female_keywords_hi)
        + find_substring_hits(raw, female_keywords_TE)
    )
    male_hits = (
        find_english_hits(latin, male_keywords_en)
        + find_substring_hits(raw, male_keywords_jp)
        + find_substring_hits(raw, male_keywords_hi)
        + find_substring_hits(raw, male_keywords_TE)
    )
    neutral_hits = (
        find_english_hits(latin, neutral_keywords_en)
        + find_substring_hits(raw, neutral_keywords_jp)
        + find_substring_hits(raw, neutral_keywords_hi)
        + find_substring_hits(raw, neutral_keywords_TE)
    )

    hit_map = {
        "female": female_hits,
        "male": male_hits,
        "neutral": neutral_hits,
    }
    labels_with_hits = [label for label, hits in hit_map.items() if hits]

    if not labels_with_hits:
        return "unknown", ""
    if len(labels_with_hits) > 1:
        evidence = "; ".join(f"{label}:{'|'.join(hit_map[label])}" for label in labels_with_hits)
        return "conflict", evidence

    label = labels_with_hits[0]
    evidence = "|".join(hit_map[label])

    return label, evidence

def parse_size(size_str: str) -> tuple[float, str]:
    """
    Parse a size string into (numeric_value, unit).
    Returns (1.0, "unit") for products sold as individual units.

    >>> parse_size("500ml")
    (500.0, 'ml')
    >>> parse_size("1.5L")
    (1500.0, 'ml')
    >>> parse_size("100g")
    (100.0, 'g')
    >>> parse_size("4 count")
    (4.0, 'count')
    """

    if not size_str or str(size_str).strip() in ("", "unit", "1", "1.0"):
        return (1.0, "unit")

    s = str(size_str).strip().lower().replace(",", "")

    m = re.match(r"([\d.]+)\s*(ml|l|g|kg|oz|lb|count|ct|pc|pcs|pack|units?)?", s)
    if not m:
        return (1.0, "unit")

    value = float(m.group(1))
    unit  = (m.group(2) or "unit").strip()

    if unit == "l":
        value *= 1000
        unit = "ml"
    elif unit == "kg":
        value *= 1000
        unit = "g"
    elif unit in ("count", "ct", "pc", "pcs", "pack", "units", "unit"):
        unit = "unit"
    elif unit == "oz":
        value = round(value * 29.5735, 2)
        unit = "ml"
    elif unit == "lb":
        value = round(value * 453.592, 2)
        unit = "g"

    return (value, unit)

def to_base_ml_or_g(size_str: str) -> float:
    """
    Convert any size string to a single float (ml or g) for PPU calculation.
    Unit products (razors) return 1.0 so price = price_per_unit.

    >>> to_base_ml_or_g("500ml")
    500.0
    >>> to_base_ml_or_g("1L")
    1000.0
    """

    value, _ = parse_size(size_str)
    return value

def price_per_unit(price_local: float, size_ml_or_g: float) -> float:
    """
    Calculate price per ml (or per g, or per unit).
    This is the core metric used for the pink tax comparison.

    >>> price_per_unit(325.0, 500.0)
    0.65
    """

    if size_ml_or_g <= 0:
        return price_local
    
    return round(price_local / size_ml_or_g, 6)

def parse_price(price_str: str, currency: str = "INR") -> float | None:
    """
    Parse a price string from a scraped page to a float.

    Handles:
      - INR: "₹325", "Rs. 325", "325.00", "3,25.00"
      - JPY: "¥1,298", "1298円", "1,298"

    Returns None if parsing fails.

    >>> parse_price("₹ 3,25.00", "INR")
    325.0
    >>> parse_price("¥1,298", "JPY")
    1298.0
    """

    if not price_str:
        return None

    cleaned = re.sub(r"[₹¥$€£Rrs.,\s円]", "", str(price_str), flags=re.IGNORECASE)
    cleaned = cleaned.replace(",", "")

    try:
        return float(cleaned)
    except ValueError:
        return None