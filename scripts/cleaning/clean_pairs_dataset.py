"""
Clean the generated pairs dataset.
This step removes duplicate rows, drops rows with missing critical values,
filters invalid numeric entries, and removes extreme outliers.
"""

from __future__ import annotations
from collections import defaultdict
from pathlib import Path
from typing import cast
import argparse
import csv
import re
import sys
import unicodedata

root = Path(__file__).resolve().parents[2]
src = root / "src"
if str(src) not in sys.path:
    sys.path.insert(0, str(src))

from pink_tax.config import (
    default_clean_drop_from_column,
    default_clean_max_abs_pink_tax,
    default_clean_max_price_ratio,
    default_clean_max_size_ratio,
    default_clean_min_match_quality,
    default_clean_min_price_ratio,
    default_clean_min_size_ratio,
    get_paths,
)

from pink_tax.utils import backup_existing_file, is_blank, to_float

paths = get_paths(root)

required_fields = [
    "pair_code",
    "city",
    "brand",
    "category",
    "female_product",
    "male_product",
    "retailer",
    "date_observed",
    "currency",
    "female_price_local",
    "male_price_local",
    "female_size",
    "male_size",
    "female_ppu_local",
    "male_ppu_local",
    "pink_tax_pct",
    "match_quality",
]

numeric_fields = [
    "female_price_local",
    "male_price_local",
    "female_size",
    "male_size",
    "female_ppu_local",
    "male_ppu_local",
    "pink_tax_pct",
    "match_quality",
]

dedupe_key_fields = [
    "pair_code",
    "city",
    "retailer",
    "date_observed",
    "female_product",
    "male_product",
]

confidence_rank = {"LOW": 1, "MED": 2, "HIGH": 3}

token_pattern = re.compile(r"[a-z0-9]+")
brand_boundary_template = r"(^| ){token}( |$)"
incompatible_form_pairs = {
    ("serum", "gel"),
    ("serum", "stick"),
    ("cream", "stick"),
    ("oil", "gel"),
    ("spray", "roll_on"),
    ("bar", "wash"),
}
form_keyword_aliases = {
    "roll on": "roll_on",
    "roll-on": "roll_on",
    "rollon": "roll_on",
    "spray": "spray",
    "stick": "stick",
    "gel": "gel",
    "serum": "serum",
    "cream": "cream",
    "oil": "oil",
    "lotion": "lotion",
    "bar": "bar",
    "soap": "bar",
    "wash": "wash",
    "shampoo": "shampoo",
    "conditioner": "conditioner",
    "toner": "toner",
}
premium_tier_keywords = {
    "premium",
    "pro",
    "professional",
    "luxury",
    "advanced",
    "visible white",
    "whitening",
    "brightening",
    "anti aging",
    "anti-age",
    "anti age",
    "serum",
    "treatment",
    "repair",
    "retinol",
    "collagen",
    "vitamin c",
    "radiance",
    "intensive",
}
function_groups = {
    "anti_dandruff": {"anti dandruff", "dandruff"},
    "brightening": {"brightening", "whitening", "visible white", "radiance", "glow"},
    "acne_oil_control": {"acne", "oil control", "sebum", "clarifying", "pore"},
    "anti_aging": {"anti aging", "anti age", "wrinkle", "firming", "retinol", "collagen"},
    "moisturizing": {"moisture", "moisturizing", "moisturising", "hydrating", "hydrate", "nourish"},
    "sensitive": {"sensitive", "gentle", "mild", "baby"},
    "sport_fresh": {"sport", "cool", "fresh", "active"},
    "multi_use": {"all in one", "all-in-one", "3 in 1", "3-in-1", "multi use", "multi-use"},
    "coloring": {"hair colour", "hair color", "colour", "color"},
}
name_overlap_stopwords = {
    "for",
    "women",
    "woman",
    "female",
    "ladies",
    "lady",
    "men",
    "man",
    "male",
    "care",
    "with",
    "and",
    "the",
    "ml",
    "g",
    "gm",
    "oz",
    "spf",
    "pa",
}

def normalize_text(text: str | None) -> str:
    """
    Normalize a string for robust lexical comparison.
    """

    raw = unicodedata.normalize("NFKD", str(text or ""))
    ascii_text = raw.encode("ascii", "ignore").decode("ascii")
    lower_text = ascii_text.lower()
    alnum_space = re.sub(r"[^a-z0-9]+", " ", lower_text)
    return re.sub(r"\s+", " ", alnum_space).strip()

def brand_aliases(brand: str | None) -> set[str]:
    """
    Build conservative alias set for a brand label.
    """

    normalized = normalize_text(brand)
    aliases = {normalized}

    if "gillette" in normalized or "venus" in normalized:
        aliases.update({"gillette", "venus"})
    if "head shoulders" in normalized or "head and shoulders" in normalized:
        aliases.update({"head shoulders", "h s"})
    if "mandom gatsby" in normalized:
        aliases.update({"mandom", "gatsby"})

    for token in re.split(r"[ /&+\-]+", normalized):
        if len(token) >= 4:
            aliases.add(token)

    return {alias for alias in aliases if alias}

def build_brand_alias_table(rows: list[dict[str, str | None]]) -> list[tuple[str, str]]:
    """
    Build alias lookup table sorted by token length desc.
    """

    pairs: set[tuple[str, str]] = set()

    for row in rows:
        brand = str(row.get("brand") or "").strip()
        if not brand:
            continue
        for alias in brand_aliases(brand):
            if len(alias) >= 4:
                pairs.add((alias, brand))

    return sorted(pairs, key=lambda pair: len(pair[0]), reverse=True)

def detect_brands_in_name(name: str | None, alias_table: list[tuple[str, str]]) -> set[str]:
    """
    Find known brand mentions in a normalized product name.
    """

    normalized_name = normalize_text(name)
    found: set[str] = set()

    for alias, brand in alias_table:
        pattern = brand_boundary_template.format(token=re.escape(alias))
        if re.search(pattern, normalized_name):
            found.add(brand)

    return found

def product_forms(name: str | None) -> set[str]:
    """
    Return detected format keywords in a product name.
    """

    normalized = normalize_text(name)
    forms: set[str] = set()

    for token, canonical in form_keyword_aliases.items():
        if token in normalized:
            forms.add(canonical)

    return forms

def keyword_hits(name: str | None, keywords: set[str]) -> set[str]:
    """
    Return keyword hits in a normalized product title.
    """

    normalized = normalize_text(name)
    return {kw for kw in keywords if kw in normalized}

def function_tags(name: str | None) -> set[str]:
    """
    Return function tags inferred from title keywords.
    """

    normalized = normalize_text(name)
    tags: set[str] = set()

    for tag, keywords in function_groups.items():
        if any(keyword in normalized for keyword in keywords):
            tags.add(tag)

    return tags

def token_overlap_ratio(female_name: str | None, male_name: str | None) -> float:
    """
    Jaccard overlap of non-stopword tokens between names.
    """

    female_tokens = {
        token
        for token in token_pattern.findall(normalize_text(female_name))
        if token not in name_overlap_stopwords
    }
    male_tokens = {
        token
        for token in token_pattern.findall(normalize_text(male_name))
        if token not in name_overlap_stopwords
    }

    if not female_tokens and not male_tokens:
        return 1.0
    if not female_tokens or not male_tokens:
        return 0.0

    return len(female_tokens & male_tokens) / len(female_tokens | male_tokens)

def has_cross_brand_mismatch(
    female_name: str | None,
    male_name: str | None,
    alias_table: list[tuple[str, str]],
) -> bool:
    """
    True when both product names contain explicit but different known brands.
    """

    female_hits = detect_brands_in_name(female_name, alias_table)
    male_hits = detect_brands_in_name(male_name, alias_table)

    return bool(female_hits and male_hits and female_hits.isdisjoint(male_hits))

def has_split_brand_component_mismatch(
    brand: str | None,
    female_name: str | None,
    male_name: str | None,
) -> bool:
    """
    For brands expressed as A/B, reject rows where female name mentions only A
    and male name mentions only B (or vice versa).
    """

    raw_brand = str(brand or "")
    if "/" not in raw_brand:
        return False

    components = [normalize_text(part) for part in raw_brand.split("/") if len(normalize_text(part)) >= 3]
    if len(components) < 2:
        return False

    normalized_female = normalize_text(female_name)
    normalized_male = normalize_text(male_name)
    female_hits = {
        component
        for component in components
        if re.search(brand_boundary_template.format(token=re.escape(component)), normalized_female)
    }
    male_hits = {
        component
        for component in components
        if re.search(brand_boundary_template.format(token=re.escape(component)), normalized_male)
    }

    return bool(female_hits and male_hits and female_hits.isdisjoint(male_hits))

def has_incompatible_form_pair(female_name: str | None, male_name: str | None) -> bool:
    """
    True when product forms are obviously non-comparable.
    """

    female_forms = product_forms(female_name)
    male_forms = product_forms(male_name)

    for female_form in female_forms:
        for male_form in male_forms:
            if (
                (female_form, male_form) in incompatible_form_pairs
                or (male_form, female_form) in incompatible_form_pairs
            ):
                return True

    return False

def has_format_mismatch(female_name: str | None, male_name: str | None) -> bool:
    """
    True when both products have recognized forms but no overlap.
    """

    female_forms = product_forms(female_name)
    male_forms = product_forms(male_name)

    if not female_forms or not male_forms:
        return False
    if female_forms & male_forms:
        return False
    if has_incompatible_form_pair(female_name, male_name):
        return True

    return len(female_forms) == 1 and len(male_forms) == 1

def has_tier_mismatch(female_name: str | None, male_name: str | None) -> bool:
    """
    True when one side appears premium/specialty while the other does not.
    """

    female_hits = keyword_hits(female_name, premium_tier_keywords)
    male_hits = keyword_hits(male_name, premium_tier_keywords)

    return bool(female_hits) != bool(male_hits)

def has_function_mismatch(female_name: str | None, male_name: str | None) -> bool:
    """
    True when function tags are disjoint and therefore non-comparable.
    """

    female_tags = function_tags(female_name)
    male_tags = function_tags(male_name)

    if not female_tags or not male_tags:
        return False

    return female_tags.isdisjoint(male_tags)

def dedupe_score(row: dict[str, str | None]) -> tuple[int, int, float, int]:
    """
    Score duplicate candidates and keep the best row.
    """

    completeness = sum(0 if is_blank(row.get(field)) else 1 for field in required_fields)
    confidence = str(row.get("confidence") or "").strip().upper()
    confidence_score = confidence_rank.get(confidence, 0)
    match_quality = to_float(row.get("match_quality")) or 0.0
    needs_review = str(row.get("needs_review") or "").strip().lower() in {"1", "true", "yes"}
    review_penalty = 0 if needs_review else 1

    return completeness, confidence_score, match_quality, review_penalty

def find_best_row(rows: list[dict[str, str | None]]) -> int:
    """
    Return index of best row by score.
    """

    best_idx = 0
    best_score = dedupe_score(rows[0])

    for idx in range(1, len(rows)):
        score = dedupe_score(rows[idx])
        if score > best_score:
            best_score = score
            best_idx = idx

    return best_idx

def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    """
    Write rows to CSV.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    backup_path = backup_existing_file(path)
    if backup_path is not None:
        print(f"Backup created: {backup_path}")

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

def select_final_fieldnames(fieldnames: list[str], drop_from_column: str) -> list[str]:
    """
    Return output field list truncated from a named start column.
    """

    if drop_from_column in fieldnames:
        idx = fieldnames.index(drop_from_column)
        return fieldnames[:idx]
    
    return list(fieldnames)

def project_rows(rows: list[dict[str, str | None]], fieldnames: list[str]) -> list[dict]:
    """
    Project row dictionaries to the selected output fields.
    """

    projected: list[dict] = []

    for row in rows:
        projected.append({field: row.get(field, "") for field in fieldnames})

    return projected

def clean_dataset(
    input_csv: Path,
    output_csv: Path,
    rejected_csv: Path | None,
    max_abs_pink_tax: float,
    min_match_quality: int,
    min_size_ratio: float,
    max_size_ratio: float,
    pair_size_min_ratio: float,
    pair_size_max_ratio: float,
    min_price_ratio: float,
    max_price_ratio: float,
    drop_from_column: str,
) -> tuple[int, int, int]:
    """
    Clean dataset and return before, after, removed counts.
    """

    with input_csv.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = cast(list[str], list(reader.fieldnames or []))
        rows = cast(list[dict[str, str | None]], list(reader))

    if not rows:
        raise ValueError("Input dataset is empty.")
    if not fieldnames:
        raise ValueError("Input dataset has no header row.")

    grouped: dict[tuple[str, ...], list[dict[str, str | None]]] = defaultdict(list)
    for row in rows:
        key = tuple(str(row.get(field) or "").strip() for field in dedupe_key_fields)
        grouped[key].append(row)
    brand_alias_table = build_brand_alias_table(rows)

    deduped_rows: list[dict[str, str | None]] = []
    removed_rows: list[dict[str, str | None]] = []

    for group_rows in grouped.values():
        if len(group_rows) == 1:
            deduped_rows.append(group_rows[0])
            continue
        best_idx = find_best_row(group_rows)
        for idx, row in enumerate(group_rows):
            if idx == best_idx:
                deduped_rows.append(row)
            else:
                dropped = dict(row)
                dropped["removed_reason"] = "duplicate_row"
                removed_rows.append(dropped)

    cleaned_rows: list[dict[str, str | None]] = []
    for row in deduped_rows:
        reasons: list[str] = []

        for field in required_fields:
            if is_blank(row.get(field)):
                reasons.append("missing_required_field")
                break

        parsed: dict[str, float] = {}
        if not reasons:
            for field in numeric_fields:
                value = to_float(row.get(field))
                if value is None:
                    reasons.append("invalid_numeric")
                    break
                parsed[field] = value

        if not reasons:
            if parsed["female_price_local"] <= 0 or parsed["male_price_local"] <= 0:
                reasons.append("nonpositive_price")
            if parsed["female_size"] <= 0 or parsed["male_size"] <= 0:
                reasons.append("nonpositive_size")
            if parsed["female_ppu_local"] <= 0 or parsed["male_ppu_local"] <= 0:
                reasons.append("nonpositive_ppu")

        if not reasons:
            if int(round(parsed["match_quality"])) < min_match_quality:
                reasons.append("low_match_quality")

            if abs(parsed["pink_tax_pct"]) > max_abs_pink_tax:
                reasons.append("extreme_pink_tax")

            size_ratio = parsed["female_size"] / parsed["male_size"]
            if size_ratio < min_size_ratio or size_ratio > max_size_ratio:
                reasons.append("extreme_size_ratio")
            if size_ratio < pair_size_min_ratio or size_ratio > pair_size_max_ratio:
                reasons.append("pair_size_mismatch")

            price_ratio = parsed["female_price_local"] / parsed["male_price_local"]
            if price_ratio < min_price_ratio or price_ratio > max_price_ratio:
                reasons.append("extreme_price_ratio")

            if has_cross_brand_mismatch(
                female_name=row.get("female_product"),
                male_name=row.get("male_product"),
                alias_table=brand_alias_table,
            ):
                reasons.append("cross_brand_pair")

            if has_split_brand_component_mismatch(
                brand=row.get("brand"),
                female_name=row.get("female_product"),
                male_name=row.get("male_product"),
            ):
                reasons.append("split_brand_component_mismatch")

            if has_incompatible_form_pair(
                female_name=row.get("female_product"),
                male_name=row.get("male_product"),
            ):
                reasons.append("incompatible_product_form")
            if has_format_mismatch(
                female_name=row.get("female_product"),
                male_name=row.get("male_product"),
            ):
                reasons.append("format_mismatch")
            if has_tier_mismatch(
                female_name=row.get("female_product"),
                male_name=row.get("male_product"),
            ):
                reasons.append("tier_mismatch")
            if has_function_mismatch(
                female_name=row.get("female_product"),
                male_name=row.get("male_product"),
            ):
                reasons.append("function_mismatch")

            name_overlap = token_overlap_ratio(
                female_name=row.get("female_product"),
                male_name=row.get("male_product"),
            )
            if (price_ratio < 0.33 or price_ratio > 3.0) and (size_ratio < 0.67 or size_ratio > 1.5 or name_overlap < 0.20):
                reasons.append("weak_name_match_extreme_ratio")

        if reasons:
            dropped = dict(row)
            dropped["removed_reason"] = "|".join(sorted(set(reasons)))
            removed_rows.append(dropped)
        else:
            cleaned_rows.append(row)

    final_fieldnames = select_final_fieldnames(fieldnames, drop_from_column)
    final_rows = project_rows(cleaned_rows, final_fieldnames)
    write_csv(output_csv, final_rows, final_fieldnames)
    if rejected_csv is not None:
        rejected_fieldnames = list(fieldnames)
        if "removed_reason" not in rejected_fieldnames:
            rejected_fieldnames.append("removed_reason")
        rejected_projected = project_rows(removed_rows, rejected_fieldnames)
        write_csv(rejected_csv, rejected_projected, rejected_fieldnames)

    total_rows = len(rows)
    kept_rows = len(cleaned_rows)
    removed_count = len(removed_rows)

    return total_rows, kept_rows, removed_count

def main() -> None:
    """
    CLI entrypoint.
    """

    parser = argparse.ArgumentParser(description="Clean duplicates, missing values, and outliers in pairs dataset.")
    parser.add_argument("--input-csv", default=str(paths.pairs_csv), help="Input pairs CSV.")
    parser.add_argument("--output-csv", default=str(paths.pairs_csv), help="Output cleaned pairs CSV.")
    parser.add_argument("--max-abs-pink-tax", type=float, default=default_clean_max_abs_pink_tax)
    parser.add_argument("--min-match-quality", type=int, default=default_clean_min_match_quality)
    parser.add_argument("--min-size-ratio", type=float, default=default_clean_min_size_ratio)
    parser.add_argument("--max-size-ratio", type=float, default=default_clean_max_size_ratio)
    parser.add_argument(
        "--pair-size-min-ratio",
        type=float,
        default=0.70,
        help="Strict comparability floor for female_size/male_size.",
    )
    parser.add_argument(
        "--pair-size-max-ratio",
        type=float,
        default=1.30,
        help="Strict comparability cap for female_size/male_size.",
    )
    parser.add_argument("--min-price-ratio", type=float, default=default_clean_min_price_ratio)
    parser.add_argument("--max-price-ratio", type=float, default=default_clean_max_price_ratio)
    parser.add_argument(
        "--rejected-csv",
        default="",
        help="Optional CSV path to store removed rows with removed_reason.",
    )
    parser.add_argument(
        "--drop-from-column",
        default=default_clean_drop_from_column,
        help="Drop this column and everything to its right in final dataset output.",
    )
    args = parser.parse_args()

    before, after, removed = clean_dataset(
        input_csv=Path(args.input_csv),
        output_csv=Path(args.output_csv),
        rejected_csv=Path(args.rejected_csv) if args.rejected_csv else None,
        max_abs_pink_tax=args.max_abs_pink_tax,
        min_match_quality=args.min_match_quality,
        min_size_ratio=args.min_size_ratio,
        max_size_ratio=args.max_size_ratio,
        pair_size_min_ratio=args.pair_size_min_ratio,
        pair_size_max_ratio=args.pair_size_max_ratio,
        min_price_ratio=args.min_price_ratio,
        max_price_ratio=args.max_price_ratio,
        drop_from_column=args.drop_from_column,
    )
    print(f"Input rows: {before}")
    print(f"Cleaned rows: {after}")
    print(f"Removed rows: {removed}")
    print(f"Cleaned dataset: {args.output_csv}")

if __name__ == "__main__":
    main()
