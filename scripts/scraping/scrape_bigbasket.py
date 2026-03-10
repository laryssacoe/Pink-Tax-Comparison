"""
Loads all 150 Hyderabad pairs from data/clean/pink_tax_pairs.csv.

BigBasket and Blinkit are both React apps so prices are injected by JS after
page load, so a real browser (Selenium headless Chrome) is required.

Features:
  • CSV-driven, no hardcoded product list, always in sync with dataset
  • BigBasket search (/ps/?q=) to find URLs when not in cache
  • DuckDuckGo site:bigbasket.com fallback
  • URL JSON cache survives restarts, avoids repeat searches
  • Resume mode, skips already-OK rows
  • Debug screenshots on PRICE_NOT_FOUND so you can fix stale selectors
  • --retailer flag to run only bigbasket or only blinkit
"""

import csv, json, time, random, re, argparse, logging, sys, unicodedata
from datetime import date
from pathlib import Path
from urllib.parse import quote_plus

root = Path(__file__).resolve().parents[2]
src = root / "src"
if str(src) not in sys.path:
    sys.path.insert(0, str(src))

from pink_tax.scraping_config import (
    cfg_delay,
    cfg_float,
    cfg_list,
    cfg_path,
    cfg_str,
    load_scraping_source_config,
)
from pink_tax.utils import select_diverse_pair_codes

# Selenium imports are optional since scraper can run in non-browser mode with reduced success.
selenium_ok = False

try:
    from selenium import webdriver  # type: ignore[import-not-found]
    from selenium.webdriver.chrome.options import Options  # type: ignore[import-not-found]
    from selenium.webdriver.common.by import By  # type: ignore[import-not-found]
    from selenium.webdriver.support.ui import WebDriverWait  # type: ignore[import-not-found]
    from selenium.webdriver.support import expected_conditions as EC  # type: ignore[import-not-found]
    from selenium.common.exceptions import (  # type: ignore[import-not-found]
        TimeoutException, NoSuchElementException, WebDriverException
    )
    selenium_ok = True
except ImportError:
    pass

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)s  %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger(__name__)

pair_seed_csv = root / "data" / "spec" / "pair_seed_catalog.csv"
legacy_pairs_csv  = root / "data" / "clean" / "pink_tax_pairs.csv"
pairs_csv = pair_seed_csv if pair_seed_csv.exists() else legacy_pairs_csv
scraper_config = load_scraping_source_config(root, "bigbasket")
output_bb = cfg_path(root, scraper_config, "output_path", "data/raw/bigbasket_raw.csv")
output_bl = cfg_path(root, scraper_config, "blinkit_output_path", "data/raw/blinkit_raw.csv")
found_urls_bb = cfg_path(
    root, scraper_config, "found_urls_path", "data/raw/bigbasket_found_urls.json"
)
found_urls_bl = cfg_path(
    root, scraper_config, "blinkit_found_urls_path", "data/raw/blinkit_found_urls.json"
)
debug_dir = root / "data" / "raw" / "debug"

city = cfg_str(scraper_config, "city", "Hyderabad")
currency = cfg_str(scraper_config, "currency", "INR")
today = str(date.today())
wait_timeout = int(cfg_float(scraper_config, "wait_timeout_seconds", 14.0))
page_load_timeout = cfg_float(scraper_config, "page_load_timeout_seconds", 25.0)
page_settle = cfg_float(scraper_config, "page_settle_seconds", 2.5)
search_pause = cfg_delay(scraper_config, "search_delay", 2.0, 4.0)
page_delay = cfg_delay(scraper_config, "product_delay", 4.0, 8.0)
bigbasket_search_base_url = cfg_str(
    scraper_config, "search_base_url", "https://www.bigbasket.com/ps/?q={query}"
)
blinkit_search_base_url = cfg_str(
    scraper_config, "blinkit_search_base_url", "https://blinkit.com/s/?q={query}"
)
user_agent = cfg_list(
    scraper_config,
    "user_agents",
    [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ],
)[0]
enable_ddg_fallback = cfg_str(scraper_config, "enable_ddg_fallback", "false").strip().lower() in {
    "1", "true", "yes", "on"
}

fieldnames = [
    "pair_code", "city", "brand", "category", "gender_label", "product_name",
    "size_ml_or_g", "price_local", "currency", "original_price_local",
    "on_promotion", "retailer", "match_quality", "confidence",
    "date_scraped", "source_url", "scrape_status",
]

def load_hyd_products() -> list[dict]:
    """
    Load products for Hyderabad pairs from the seed catalog CSV.
    """

    if not pairs_csv.exists():
        raise FileNotFoundError(
            f"Missing seed pairs CSV. Expected one of: "
            f"{root / 'data' / 'spec' / 'pair_seed_catalog.csv'} or "
            f"{root / 'data' / 'clean' / 'pink_tax_pairs.csv'}"
        )
    products, seen = [], set()
    with open(pairs_csv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["city"] != city:
                continue
            pc = row["pair_code"]
            if pc in seen:
                continue
            seen.add(pc)
            brand = row["brand"]
            brand_query = brand.split("/")[0].strip()
            for gender, name_col, size_col in [
                ("female", "female_product", "female_size"),
                ("male",   "male_product",   "male_size"),
            ]:
                name = row[name_col]
                size = row[size_col]
                gkw  = "women" if gender == "female" else "men"
                products.append({
                    "pair_code":    pc,
                    "gender_label": gender,
                    "product_name": name,
                    "brand":        brand,
                    "category":     row["category"],
                    "size_ml_or_g": size,
                    "match_quality": row["match_quality"],
                    "search_query": build_query(name, gkw, size),
                    "brand_kw":     normalize_text(brand_query),
                    "brand_query":  brand_query,
                    "gender_hint":  gkw,
                    "category_kw":  normalize_text(row["category"]),
                })
    log.info(f"Loaded {len(products)} products from {len(seen)} pairs ({city})")
    return products

def build_query(name: str, gkw: str, size: str) -> str:
    words = name.split()[:7]
    q = " ".join(words)
    try:
        sz = float(size)
        if sz > 1 and str(int(sz)) not in q:
            q += f" {int(sz)}ml" if sz < 1000 else f" {int(sz)}g"
    except (ValueError, TypeError):
        pass
    if gkw not in q.lower():
        q += f" {gkw}"
    return q

def normalize_text(text: str) -> str:
    """
    Normalize text for robust matching.
    """

    folded = unicodedata.normalize("NFKD", text)
    no_marks = "".join(ch for ch in folded if not unicodedata.combining(ch))
    low = no_marks.lower()
    return re.sub(r"[^a-z0-9]+", " ", low).strip()

def build_query_variants(
    base_query: str,
    brand_query: str,
    category_kw: str,
    gender_hint: str,
) -> list[str]:
    """
    Build progressively looser queries for same-brand retrieval.
    """

    category_hint = category_kw.split()[0] if category_kw else ""
    variants = [
        base_query,
        f"{brand_query} {category_hint} {gender_hint}".strip(),
        f"{brand_query} {gender_hint}".strip(),
        f"{brand_query} {category_hint}".strip(),
        brand_query,
    ]
    out: list[str] = []
    seen: set[str] = set()
    for raw in variants:
        q = normalize_text(raw)
        if q and q not in seen:
            out.append(q)
            seen.add(q)
    return out

def cached_chromedriver_path() -> str | None:
    """
    Return a cached chromedriver binary path if available.
    """

    home = Path.home()
    candidates = sorted(home.glob(".wdm/drivers/chromedriver/**/chromedriver"), reverse=True)
    for path in candidates:
        if path.is_file():
            return str(path)
    return None

def build_driver():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1366,768")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_argument(f"--user-agent={user_agent}")
    driver = None
    try:
        from selenium.webdriver.chrome.service import Service  # type: ignore[import-not-found]

        cached = cached_chromedriver_path()
        if cached:
            driver = webdriver.Chrome(service=Service(cached), options=opts)
        else:
            from webdriver_manager.chrome import ChromeDriverManager  # type: ignore[import-not-found]

            driver = webdriver.Chrome(
                service=Service(ChromeDriverManager().install()), options=opts)
    except Exception:
        driver = webdriver.Chrome(options=opts)
    try:
        driver.set_page_load_timeout(page_load_timeout)
    except Exception:
        pass
    driver.execute_script(
        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
    return driver

def search_bigbasket(
    query: str,
    driver,
    brand_kw: str = "",
    brand_query: str = "",
    category_kw: str = "",
    gender_hint: str = "",
) -> str | None:
    """
    Search BigBasket and return first matching /pd/ URL.
    """

    variants = build_query_variants(query, brand_query or brand_kw, category_kw, gender_hint)
    for idx, current in enumerate(variants, 1):
        search_url = bigbasket_search_base_url.format(query=quote_plus(current))
        log.info(f"  🔍 BB: {current} [{idx}/{len(variants)}]")
        try:
            driver.get(search_url)
            time.sleep(random.uniform(*search_pause))
            try:
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/pd/']"))
                )
            except TimeoutException:
                pass
            candidates: list[str] = []
            for a in driver.find_elements(By.CSS_SELECTOR, "a[href*='/pd/']"):
                href = a.get_attribute("href") or ""
                text = normalize_text(a.text)
                if "/pd/" not in href:
                    continue
                if brand_kw and brand_kw not in text and brand_kw not in normalize_text(href):
                    continue
                candidates.append(href.split("?")[0])
            if candidates:
                pick = random.choice(candidates[:5])
                log.info(f"  ✓ BB native: {pick[:70]}")
                return pick
        except Exception as e:
            log.warning(f"  BB search error: {e}")
    if enable_ddg_fallback:
        log.warning("  No BB result, trying DDG")
        for current in variants:
            ddg_match = ddg_bigbasket(current, driver, brand_kw)
            if ddg_match:
                return ddg_match
    else:
        log.warning("  No BB result, DDG fallback disabled")
    return None

def ddg_bigbasket(query: str, driver, brand_kw: str = "") -> str | None:
    """
    DuckDuckGo site:bigbasket.com fallback.
    """

    ddg_url = (f"https://html.duckduckgo.com/html/?q="
               f"{quote_plus(query + ' site:bigbasket.com/pd/')}")
    try:
        driver.get(ddg_url)
        time.sleep(random.uniform(3.0, 5.0))
        for a in driver.find_elements(By.CSS_SELECTOR, "a.result__a, a[href*='bigbasket.com']"):
            href = a.get_attribute("href") or ""
            if "bigbasket.com/pd/" in href:
                if brand_kw and brand_kw not in href.lower():
                    continue
                log.info(f"  ✓ DDG BB: {href[:70]}")
                return href.split("?")[0]
    except Exception as e:
        log.warning(f"  DDG BB error: {e}")
    return None

def search_blinkit(
    query: str,
    driver,
    brand_kw: str = "",
    brand_query: str = "",
    category_kw: str = "",
    gender_hint: str = "",
) -> str | None:
    """
    Search Blinkit and return first matching product URL.
    """

    variants = build_query_variants(query, brand_query or brand_kw, category_kw, gender_hint)
    for idx, current in enumerate(variants, 1):
        search_url = blinkit_search_base_url.format(query=quote_plus(current))
        log.info(f"  🔍 BL: {current} [{idx}/{len(variants)}]")
        try:
            driver.get(search_url)
            time.sleep(random.uniform(*search_pause))
            try:
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "a[href*='/prn/'], div[class*='Product']")))
            except TimeoutException:
                pass
            candidates: list[str] = []
            for a in driver.find_elements(By.CSS_SELECTOR, "a[href*='/prn/']"):
                href = a.get_attribute("href") or ""
                text = normalize_text(a.text)
                if "/prn/" not in href:
                    continue
                if brand_kw and brand_kw not in text and brand_kw not in normalize_text(href):
                    continue
                candidates.append(href.split("?")[0])
            if candidates:
                pick = random.choice(candidates[:5])
                log.info(f"  ✓ BL native: {pick[:70]}")
                return pick
        except Exception as e:
            log.warning(f"  BL search error: {e}")
    return None

bb_price_selectors = [
    "[qa='discounted-price']",
    "[qa='selling-price']",
    "span.discnt-price",
    "span.selling-price",
    "div.PriceContainer span",
    "span[class*='Price__']",
    "div[class*='price'] span",
    "span[class*='price']",
]
bb_original_selectors = [
    "[qa='mrp']",
    "span.mrp-price",
    "span.discnt-price-w-o",
    "span[class*='line-through']",
    "span[class*='MRP']",
    "del",
]

def extract_price_bigbasket(driver) -> tuple:
    price = orig = None
    promo = False

    try:
        WebDriverWait(driver, wait_timeout).until(
            EC.presence_of_element_located((By.TAG_NAME, "body")))
        time.sleep(page_settle)
    except TimeoutException:
        return None, None, False

    for sel in bb_price_selectors:
        try:
            for el in driver.find_elements(By.CSS_SELECTOR, sel):
                raw = el.text.strip().replace("₹", "").replace(",", "").strip()
                if raw:
                    try:
                        price = float(raw)
                        break
                    except ValueError:
                        pass
            if price:
                break
        except Exception:
            continue

    for sel in bb_original_selectors:
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            raw = el.text.strip().replace("₹", "").replace(",", "").strip()
            if raw:
                op = float(raw)
                if price and op > price:
                    orig, promo = op, True
                break
        except Exception:
            continue

    return price, orig, promo

bl_price_selectors = [
    "[data-testid='product-price']",
    "div[class*='ProductVariants__PriceContainer'] span",
    "span[class*='Price__StyledPrice']",
    "div[class*='product-price']",
    "div.tw-flex span[class*='font-bold']",
    "span[class*='price']",
]
bl_original_selectors = [
    "span[class*='line-through']",
    "span[class*='StrikePrice']",
    "span[class*='mrp']",
    "del",
]

def extract_price_blinkit(driver) -> tuple:
    price = orig = None
    promo = False

    try:
        WebDriverWait(driver, wait_timeout).until(
            EC.presence_of_element_located((By.TAG_NAME, "body")))
        time.sleep(page_settle)
    except TimeoutException:
        return None, None, False

    for sel in bl_price_selectors:
        try:
            for el in driver.find_elements(By.CSS_SELECTOR, sel):
                raw = el.text.strip().replace("₹", "").replace(",", "").strip()
                if raw:
                    try:
                        price = float(raw)
                        break
                    except ValueError:
                        pass
            if price:
                break
        except Exception:
            continue

    for sel in bl_original_selectors:
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            raw = el.text.strip().replace("₹", "").replace(",", "").strip()
            if raw:
                op = float(raw)
                if price and op > price:
                    orig, promo = op, True
                break
        except Exception:
            continue

    return price, orig, promo

def scrape_one(product: dict, driver, url_cache: dict,
               retailer_name: str, search_fn, extract_fn,
               dry_run: bool = False, skip_search: bool = False) -> dict:
    row = {
        "pair_code":            product["pair_code"],
        "city":                 city,
        "brand":                product["brand"],
        "category":             product["category"],
        "gender_label":         product["gender_label"],
        "product_name":         product["product_name"],
        "size_ml_or_g":         product["size_ml_or_g"],
        "price_local":          None,
        "currency":             currency,
        "original_price_local": None,
        "on_promotion":         False,
        "retailer":             retailer_name,
        "match_quality":        product["match_quality"],
        "confidence":           "LOW",
        "date_scraped":         today,
        "source_url":           "",
        "scrape_status":        "PENDING",
    }

    if dry_run:
        row["scrape_status"] = "DRY_RUN"
        log.info(f"  [DRY] {retailer_name:<12} {product['gender_label']:<6} {product['product_name']}")
        return row

    ck  = f"{product['pair_code']}|{product['gender_label']}"
    url = url_cache.get(ck)

    if not url and not skip_search:
        url = search_fn(
            product["search_query"],
            driver,
            product["brand_kw"],
            product.get("brand_query", ""),
            product.get("category_kw", ""),
            product.get("gender_hint", ""),
        )
        time.sleep(random.uniform(*search_pause))

    if not url:
        row["scrape_status"] = "URL_NOT_FOUND"
        log.warning(f"  ✗ {retailer_name}: No URL for {product['product_name']}")
        return row

    row["source_url"] = url
    url_cache[ck]     = url

    try:
        driver.get(url)
        price, orig, promo = extract_fn(driver)

        if price is None:
            row["scrape_status"] = "PRICE_NOT_FOUND"
            log.warning(f"  ✗ {retailer_name}: No price, {product['product_name']}")
            # Save debug screenshot
            debug_dir.mkdir(parents=True, exist_ok=True)
            fname = f"{product['pair_code']}_{product['gender_label']}_{retailer_name.replace(' ','_')}.png"
            try:
                driver.save_screenshot(str(debug_dir / fname))
                log.info(f"    Screenshot → {debug_dir / fname}")
            except Exception:
                pass
        else:
            row.update({
                "price_local": price, "original_price_local": orig,
                "on_promotion": promo, "confidence": "HIGH", "scrape_status": "OK",
            })
            log.info(f"  ✓ {retailer_name:<12} {product['gender_label']:<6} "
                     f"{product['product_name'][:48]:<48} ₹{price:.0f}"
                     + ("  🏷" if promo else ""))

    except Exception as e:
        log.error(f"  ✗ {retailer_name}: scraper error, {e}")
        row["scrape_status"] = "SCRAPER_ERROR"

    return row

def main(dry_run=False, skip_search=False, resume=False,
         retailer_filter="both", target_pair=None, limit=None):
    if not dry_run and not selenium_ok:
        print("ERROR: selenium not installed. Run: pip install selenium webdriver-manager")
        return

    (root / "data" / "raw").mkdir(parents=True, exist_ok=True)

    products = load_hyd_products()
    if target_pair:
        products = [p for p in products if p["pair_code"] == target_pair]
        if not products:
            log.error(f"Pair not found: {target_pair}"); return

    if limit:
        keep = select_diverse_pair_codes(products, limit)
        products = [p for p in products if p["pair_code"] in keep]
        log.info(f"Limit: {len(keep)} pairs (diverse) → {len(products)} products")

    run_bb = retailer_filter in ("both", "bigbasket")
    run_bl = retailer_filter in ("both", "blinkit")

    # Load URL caches
    bb_cache: dict = {}
    bl_cache: dict = {}
    if run_bb and found_urls_bb.exists():
        try:
            bb_cache = json.loads(found_urls_bb.read_text(encoding="utf-8"))
            log.info(f"BB URL cache: {len(bb_cache)} entries")
        except Exception:
            pass
    if run_bl and found_urls_bl.exists():
        try:
            bl_cache = json.loads(found_urls_bl.read_text(encoding="utf-8"))
            log.info(f"BL URL cache: {len(bl_cache)} entries")
        except Exception:
            pass

    bb_done, bl_done = set(), set()
    bb_rows, bl_rows = [], []

    if resume:
        for path, done_set, rows in [(output_bb, bb_done, bb_rows),
                                     (output_bl, bl_done, bl_rows)]:
            if path.exists():
                with open(path, newline="", encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        if row.get("scrape_status") == "OK":
                            done_set.add(f"{row['pair_code']}|{row['gender_label']}")
                            rows.append(row)
        if bb_done:
            log.info(f"BB resume: {len(bb_done)} already-OK")
        if bl_done:
            log.info(f"BL resume: {len(bl_done)} already-OK")

    driver = None
    try:
        if not dry_run:
            log.info("Launching headless Chrome...")
            driver = build_driver()
            log.info("Chrome ready.\n")

        n = len(products)
        log.info(f"\n{'='*62}")
        log.info(f"  BigBasket/Blinkit  |  {n} products  |  {'DRY RUN' if dry_run else 'LIVE'}")
        log.info(f"  DDG fallback       |  {'ON' if enable_ddg_fallback else 'OFF'}")
        log.info(f"{'='*62}\n")

        for i, product in enumerate(products, 1):
            ck = f"{product['pair_code']}|{product['gender_label']}"
            log.info(f"[{i:>3}/{n}] {product['pair_code']} / {product['gender_label']}")

            def error_row(retailer_name: str, status: str, confidence: str = "0.0") -> dict:
                return {
                    "pair_code": product["pair_code"],
                    "city": city,
                    "brand": product["brand"],
                    "category": product["category"],
                    "gender_label": product["gender_label"],
                    "product_name": product["product_name"],
                    "size_ml_or_g": product["size_ml_or_g"],
                    "price_local": "",
                    "currency": currency,
                    "original_price_local": "",
                    "on_promotion": "",
                    "retailer": retailer_name,
                    "match_quality": product["match_quality"],
                    "confidence": confidence,
                    "date_scraped": today,
                    "source_url": "",
                    "scrape_status": status,
                }

            if run_bb:
                if resume and ck in bb_done:
                    log.info(f"  BB: already-OK, skipping")
                else:
                    try:
                        r = scrape_one(product, driver, bb_cache,
                                       "BigBasket", search_bigbasket, extract_price_bigbasket,
                                       dry_run=dry_run, skip_search=skip_search)
                    except Exception as exc:
                        log.error(f"  ✗ BigBasket: unexpected error, {exc}")
                        r = error_row("BigBasket", "UNEXPECTED_ERROR")
                    bb_rows.append(r)
                    # Save cache after each product
                    found_urls_bb.write_text(
                        json.dumps(bb_cache, ensure_ascii=False, indent=2), encoding="utf-8")

            if run_bl:
                if resume and ck in bl_done:
                    log.info(f"  BL: already-OK, skipping")
                else:
                    if not dry_run and run_bb:
                        time.sleep(random.uniform(1.5, 3.0))
                    try:
                        r = scrape_one(product, driver, bl_cache,
                                       "Blinkit", search_blinkit, extract_price_blinkit,
                                       dry_run=dry_run, skip_search=skip_search)
                    except Exception as exc:
                        log.error(f"  ✗ Blinkit: unexpected error, {exc}")
                        r = error_row("Blinkit", "UNEXPECTED_ERROR")
                    bl_rows.append(r)
                    found_urls_bl.write_text(
                        json.dumps(bl_cache, ensure_ascii=False, indent=2), encoding="utf-8")

            if not dry_run:
                time.sleep(random.uniform(*page_delay))

        def write(rows, path):
            if not rows:
                return
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                w.writeheader(); w.writerows(rows)
            ok = sum(1 for r in rows if r.get("scrape_status") == "OK")
            log.info(f"  {path.name}: OK={ok}/{len(rows)}")

        log.info(f"\n{'='*62}")
        if run_bb:
            write(bb_rows, output_bb)
        if run_bl:
            write(bl_rows, output_bl)
        log.info(f"{'='*62}")

    finally:
        if driver:
            driver.quit()
            log.info("Chrome closed.")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run",    action="store_true")
    ap.add_argument("--no-search",  action="store_true")
    ap.add_argument("--resume",     action="store_true")
    ap.add_argument("--retailer",   choices=["both", "bigbasket", "blinkit"], default="both")
    ap.add_argument("--pair",       metavar="PAIR_CODE")
    ap.add_argument("--limit",      type=int, metavar="N",
                   help="Max number of PAIRS to scrape (products = 2×N per retailer).")
    args = ap.parse_args()
    main(dry_run=args.dry_run, skip_search=args.no_search, resume=args.resume,
         retailer_filter=args.retailer, target_pair=args.pair, limit=args.limit)
