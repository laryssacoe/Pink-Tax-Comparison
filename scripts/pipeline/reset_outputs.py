"""
Clear generated pipeline output files so a new run starts from empty outputs.
"""

from __future__ import annotations
from pathlib import Path
import argparse
import sys

root = Path(__file__).resolve().parents[2]
src = root / "src"
if str(src) not in sys.path:
    sys.path.insert(0, str(src))

from pink_tax.config import get_paths

def main() -> None:
    """
    CLI entrypoint.
    """

    parser = argparse.ArgumentParser(description="Reset generated raw/clean output files.")
    parser.add_argument(
        "--clear-url-cache",
        action="store_true",
        help="Also remove *_found_urls.json and *_found_urls.txt caches.",
    )
    args = parser.parse_args()

    paths = get_paths(root)

    targets = [
        paths.data_raw / "amazon_in_raw.csv",
        paths.data_raw / "amazon_jp_raw.csv",
        paths.data_raw / "flipkart_raw.csv",
        paths.data_raw / "rakuten_jp_raw.csv",
        paths.data_raw / "matsumoto_raw.csv",
        paths.data_raw / "bigbasket_raw.csv",
        paths.data_raw / "blinkit_raw.csv",
        paths.pair_observations_spec,
        paths.data_clean / "pink_tax_final_dataset_cleaned.csv",
        paths.data_clean / "pink_tax_quality_review_summary.csv",
    ]

    if args.clear_url_cache:
        targets.extend(
            [
                paths.data_raw / "amazon_in_found_urls.json",
                paths.data_raw / "amazon_jp_found_urls.json",
                paths.data_raw / "flipkart_found_urls.json",
                paths.data_raw / "rakuten_jp_found_urls.json",
                paths.data_raw / "matsumoto_found_urls.json",
                paths.data_raw / "bigbasket_found_urls.json",
                paths.data_raw / "blinkit_found_urls.json",
                paths.data_raw / "amazon_in_found_urls.txt",
                paths.data_raw / "amazon_jp_found_urls.txt",
                paths.data_raw / "flipkart_found_urls.txt",
                paths.data_raw / "rakuten_jp_found_urls.txt",
            ]
        )

    removed = 0
    for path in targets:
        if path.exists() and path.is_file():
            path.unlink()
            removed += 1
            print(f"Removed: {path}")

    print(f"Reset complete. Files removed: {removed}")

if __name__ == "__main__":
    main()
