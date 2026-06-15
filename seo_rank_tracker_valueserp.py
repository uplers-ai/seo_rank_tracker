#!/usr/bin/env python3
"""
============================================================
 UPLERS SEO RANK TRACKER — ValueSERP Edition
 Fetches Google rankings via ValueSERP for 1,200+ keywords
 and writes results directly to your Google Sheet.

 🔄 Migrated from SerpAPI → ValueSERP
    - 1 credit per keyword (no pagination needed)
    - ~$25/month for 5,000 searches
    - Weekly runs: ~1,200 × 4 = ~4,800 credits/month

 Features:
   ✅ Google Sheets read/write via API
   ✅ Resume support (picks up where it left off if interrupted)
   ✅ Sequential API calls (safe, respects rate limits)
   ✅ 100 results in a single request (no pagination!)
   ✅ Progress bar and live status
   ✅ Retry pass for missed keywords
============================================================

 SETUP (one-time):
   1. pip install gspread google-auth requests tqdm
   2. Sign up at https://app.valueserp.com/signup to get your API key
   3. Create a Google Cloud service account:
      - Go to https://console.cloud.google.com
      - Create a project (or use existing)
      - Enable "Google Sheets API" and "Google Drive API"
      - Go to Credentials → Create Credentials → Service Account
      - Download the JSON key file
      - Rename it to "credentials.json" and place it next to this script
   4. Share your Google Sheet with the service account email
   5. Update the CONFIG below with your details
   6. Run: python seo_rank_tracker_valueserp.py
============================================================
"""

import json
import os
import sys
import time
from datetime import datetime
from urllib.parse import urlparse

import gspread
import requests
from google.oauth2.service_account import Credentials
from tqdm import tqdm


def retry_sheet_call(func, *args, max_retries=5, base_delay=5, **kwargs):
    """
    Retry a Google Sheets API call with exponential backoff.
    Handles transient network errors (timeouts, connection drops, etc.).
    """
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except (requests.exceptions.ConnectionError,
                requests.exceptions.ReadTimeout,
                requests.exceptions.Timeout,
                OSError) as e:
            if attempt < max_retries - 1:
                wait = base_delay * (2 ** attempt)
                tqdm.write(f"      ⚠️ Sheet API failed (attempt {attempt + 1}/{max_retries}): {e}")
                tqdm.write(f"         Retrying in {wait}s...")
                time.sleep(wait)
            else:
                tqdm.write(f"      ❌ Sheet API failed after {max_retries} attempts: {e}")
                raise


# ─── CONFIGURATION ───────────────────────────────────────────
CONFIG = {
    # ValueSERP API Key — get yours at https://app.valueserp.com/signup
    # Reads from env variable if set, otherwise falls back to hardcoded key
    "VALUESERP_API_KEY": os.environ.get("VALUESERP_API_KEY", "FB89AFA39CCB4098871DCD11B3536F36"),

    # Google Sheet
    "SPREADSHEET_NAME": "SEO Master Dashboard (2026) | Uplers",
    "SHEET_TAB": "sheet1",
    "CREDENTIALS_FILE": "credentials.json",

    # Domain to track
    "DOMAIN": "uplers.com",
    "RESULTS_DEPTH": 100,  # Max rank to check (up to 100 in one call!)

    # Section — Global keywords (California, USA)
    "GLOBAL_HEADER_ROW": 2,
    "GLOBAL_DATA_START": 3,
    "GLOBAL_LOCATION": "Los Angeles,CA,California,United States",
    "GLOBAL_GL": "us",
    "GLOBAL_HL": "en",
    "GOOGLE_DOMAIN": "google.com",   # Explicit Google domain
    "DEVICE": "desktop",             # "desktop" or "mobile" — rankings differ!

    # Column positions (1-indexed)
    "COL_URL": 1,        # Column A — page URL
    "COL_KEYWORD": 2,    # Column B — keyword
    "COL_VOL": 3,        # Column C — search volume
    "FIRST_RANK_COL": 4, # Column D — first ranking data column

    # Rate limiting
    "DELAY_BETWEEN_KEYWORDS": 1.0,  # Seconds between keyword searches
    "DELAY_BETWEEN_PAGES": 0.5,     # Seconds between paginated page requests

    # Retry settings
    "API_RETRIES": 3,           # Number of retries on transient failures
    "RETRY_DELAY": 2.0,         # Seconds between retries (doubles each time)

    # Resume file
    "RESUME_FILE": "rank_check_progress.json",

    # Debug — save raw API responses for keywords not found (helps diagnose misses)
    "DEBUG_MISSED": True,
    "DEBUG_DIR": "debug_responses",
}
# ─────────────────────────────────────────────────────────────


def connect_to_sheet():
    """Authenticate and return the worksheet object."""
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    # If GOOGLE_CREDENTIALS env var is set (GitHub Actions / CI), use it directly
    google_creds_env = os.environ.get("GOOGLE_CREDENTIALS")
    if google_creds_env:
        creds_info = json.loads(google_creds_env)
        creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
        print("🔑 Using credentials from environment variable")
    else:
        creds_file = CONFIG["CREDENTIALS_FILE"]
        if not os.path.exists(creds_file):
            print(f"\n❌ Credentials file '{creds_file}' not found!")
            print("   See the SETUP instructions at the top of this script.")
            sys.exit(1)
        creds = Credentials.from_service_account_file(creds_file, scopes=scopes)

    client = gspread.authorize(creds)

    try:
        spreadsheet = client.open(CONFIG["SPREADSHEET_NAME"])
    except gspread.SpreadsheetNotFound:
        print(f"\n❌ Spreadsheet '{CONFIG['SPREADSHEET_NAME']}' not found!")
        print("   Make sure you've shared the sheet with your service account email.")
        sys.exit(1)

    worksheet = spreadsheet.worksheet(CONFIG["SHEET_TAB"])
    print(f"✅ Connected to sheet: {CONFIG['SPREADSHEET_NAME']} → {CONFIG['SHEET_TAB']}")
    return worksheet


def find_data_end(all_data):
    """Find the last row with keyword data."""
    last_row = CONFIG["GLOBAL_DATA_START"] - 1
    for i in range(CONFIG["GLOBAL_DATA_START"] - 1, len(all_data)):
        row = all_data[i]
        keyword = str(row[CONFIG["COL_KEYWORD"] - 1]).strip() if len(row) >= CONFIG["COL_KEYWORD"] else ""
        if keyword and keyword.lower() != "keywords":
            last_row = i
    return last_row


def domain_matches(url, target_domain):
    """
    Strict domain matching — checks that the URL belongs to the target domain
    or a subdomain of it. Prevents false matches like 'notuplers.com'.
    """
    try:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        hostname = (parsed.hostname or "").lower().rstrip(".")
        # Exact match (uplers.com) or subdomain match (.uplers.com)
        return hostname == target_domain or hostname.endswith(f".{target_domain}")
    except Exception:
        return False


def check_domain_in_results(results_list, domain, position_offset=0):
    """
    Check a list of result objects for our domain.
    Returns (absolute_position, link) or (None, None) if not found.
    position_offset: added to page-relative positions for pagination.
    """
    for idx, result in enumerate(results_list):
        # Check link field (primary)
        link = str(result.get("link", ""))
        matched = domain_matches(link, domain)

        # Check domain field (ValueSERP provides this directly)
        if not matched:
            result_domain = str(result.get("domain", "")).lower()
            if result_domain == domain or result_domain == f"www.{domain}" or result_domain.endswith(f".{domain}"):
                matched = True
                link = result.get("link", "")

        # Check displayed_link as fallback
        if not matched:
            displayed = str(result.get("displayed_link", ""))
            if domain_matches(displayed, domain):
                matched = True
                link = result.get("link", displayed)

        if matched:
            # Use position field if available, otherwise use index
            pos = result.get("position")
            relative_pos = int(pos) if pos else (idx + 1)
            absolute_pos = relative_pos + position_offset
            return absolute_pos, link

    return None, None


def save_debug_response(keyword, data):
    """Save raw API response for a missed keyword to help diagnose issues."""
    if not CONFIG.get("DEBUG_MISSED"):
        return
    debug_dir = CONFIG["DEBUG_DIR"]
    os.makedirs(debug_dir, exist_ok=True)
    safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in keyword)[:80]
    filepath = os.path.join(debug_dir, f"{safe_name}.json")
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)


def fetch_serp_page(params, max_retries, retry_delay):
    """
    Fetch a single SERP page from ValueSERP with retry logic.
    Returns: (data dict, error string or None)
    """
    for attempt in range(max_retries):
        try:
            response = requests.get(
                "https://api.valueserp.com/search",
                params=params,
                timeout=30,
            )
            data = response.json()
        except Exception as e:
            if attempt < max_retries - 1:
                wait = retry_delay * (2 ** attempt)
                tqdm.write(f"      ⚠️ Request failed (attempt {attempt + 1}): {e} — retrying in {wait:.0f}s")
                time.sleep(wait)
                continue
            tqdm.write(f"      ⚠️ Request failed after {max_retries} attempts: {e}")
            return None, "ERROR"

        request_info = data.get("request_info", {})
        if not request_info.get("success", False):
            error_msg = request_info.get("message", "Unknown error")
            if attempt < max_retries - 1 and "rate" in error_msg.lower():
                wait = retry_delay * (2 ** attempt)
                tqdm.write(f"      ⚠️ Rate limited — retrying in {wait:.0f}s")
                time.sleep(wait)
                continue
            tqdm.write(f"      ⚠️ API error: {error_msg}")
            return None, "ERROR"

        # Check remaining credits
        credits_remaining = request_info.get("credits_remaining", "?")
        if isinstance(credits_remaining, (int, float)) and credits_remaining < 100:
            tqdm.write(f"      ⚠️ Low credits warning: {credits_remaining} remaining!")

        return data, None

    return None, "ERROR"


def check_serp_features(data, domain):
    """
    Check all SERP features (answer box, knowledge graph, local pack, etc.)
    for our domain. Only checked on page 1.
    Returns (position, link) or (None, None).
    """
    # Answer box / featured snippet
    answer_box = data.get("answer_box", {})
    if answer_box:
        ab_link = str(answer_box.get("link", ""))
        if domain_matches(ab_link, domain):
            return 1, ab_link

    # Knowledge graph
    knowledge = data.get("knowledge_graph", {})
    if knowledge:
        kg_link = str(knowledge.get("website", knowledge.get("link", "")))
        if domain_matches(kg_link, domain):
            return 1, kg_link

    # Local pack results
    local_results = data.get("local_results", [])
    for lr in local_results:
        lr_link = str(lr.get("link", lr.get("website", "")))
        if domain_matches(lr_link, domain):
            lr_pos = lr.get("position")
            return (int(lr_pos) if lr_pos else 1), lr_link

    # Inline videos
    inline_videos = data.get("inline_videos", [])
    pos, link = check_domain_in_results(inline_videos, domain)
    if pos is not None:
        return pos, link

    # Top stories
    top_stories = data.get("top_stories", [])
    pos, link = check_domain_in_results(top_stories, domain)
    if pos is not None:
        return pos, link

    return None, None


def get_rank_from_valueserp(keyword, location, gl, hl):
    """
    Query ValueSERP to find domain ranking.
    Returns: (rank, url) tuple.

    Strategy: page-by-page pagination with num=10, matching the
    ValueSERP API playground behavior. Stops early when found.
      - Page 1: check SERP features + organic results (1 credit)
      - Pages 2-10: check organic results (1 credit each)
      - Stop as soon as domain is found → saves credits
      - Worst case: 10 credits per keyword (all 10 pages)
    """
    api_key = CONFIG["VALUESERP_API_KEY"]
    domain = CONFIG["DOMAIN"]
    max_retries = CONFIG["API_RETRIES"]
    retry_delay = CONFIG["RETRY_DELAY"]
    max_pages = CONFIG["RESULTS_DEPTH"] // 10

    base_params = {
        "api_key": api_key,
        "q": keyword,
        "location": location,
        "gl": gl,
        "hl": hl,
        "google_domain": CONFIG["GOOGLE_DOMAIN"],
        "device": CONFIG["DEVICE"],
        "num": 10,
        "output": "json",
    }

    page1_data = None

    for page in range(1, max_pages + 1):
        page_offset = (page - 1) * 10

        params = {**base_params, "page": page}
        data, error = fetch_serp_page(params, max_retries, retry_delay)
        if error:
            return "ERROR", ""

        if page == 1:
            page1_data = data
            pos, link = check_serp_features(data, domain)
            if pos is not None:
                return pos, link

        organic = data.get("organic_results", [])
        pos, link = check_domain_in_results(organic, domain, position_offset=page_offset)
        if pos is not None:
            return pos, link

        if not organic:
            break

        pagination = data.get("pagination", {})
        has_next = pagination.get("next") or pagination.get("other_pages")
        if not has_next:
            break

        time.sleep(CONFIG.get("DELAY_BETWEEN_PAGES", 0.5))

    save_debug_response(keyword, page1_data or data)
    return "-", ""


def load_progress():
    """Load saved progress from resume file."""
    resume_file = CONFIG["RESUME_FILE"]
    if os.path.exists(resume_file):
        with open(resume_file, "r") as f:
            return json.load(f)
    return None


def save_progress(date_label, section, row_index, results):
    """Save current progress to resume file."""
    progress = {
        "date_label": date_label,
        "section": section,
        "last_completed_row": row_index,
        "results": results,
        "timestamp": datetime.now().isoformat(),
    }
    with open(CONFIG["RESUME_FILE"], "w") as f:
        json.dump(progress, f, indent=2)


def clear_progress():
    """Delete the resume file after successful completion."""
    resume_file = CONFIG["RESUME_FILE"]
    if os.path.exists(resume_file):
        os.remove(resume_file)


def process_section(worksheet, all_data, header_row_idx, data_start_idx, data_end_idx,
                    location, gl, hl, date_label, section_name,
                    new_col_index, resume_results=None):
    """
    Process one section of keywords.
    Writes ranks into the already-inserted date column.
    Uses batch writes (every 10 keywords) for speed + reliability.
    Supports resuming from a specific row.
    """
    results = resume_results or {}
    keywords_to_process = []

    for r in range(data_start_idx, data_end_idx + 1):
        if r >= len(all_data):
            break

        row = all_data[r]
        keyword = str(row[CONFIG["COL_KEYWORD"] - 1]).strip() if len(row) >= CONFIG["COL_KEYWORD"] else ""

        if not keyword or keyword.lower() == "keywords":
            continue

        row_key = str(r)
        if row_key in results:
            continue

        keywords_to_process.append((r, keyword))

    if not keywords_to_process:
        print(f"  ✅ {section_name}: All keywords already completed (resumed).")
        return results

    total = len(keywords_to_process)
    print(f"\n  📋 {section_name}: {total} keywords to process")
    print(f"  💰 This will use ~{total} ValueSERP credits\n")

    batch_updates = []  # Collect cells to write in batches
    BATCH_SIZE = 10

    for idx, (r, keyword) in enumerate(tqdm(keywords_to_process, desc=f"  {section_name}", unit="kw")):
        tqdm.write(f"    [{idx + 1}/{total}] \"{keyword}\"", end="")

        rank, rank_url = get_rank_from_valueserp(keyword, location, gl, hl)

        # Queue the cell update
        cell_ref = gspread.utils.rowcol_to_a1(r + 1, new_col_index)
        batch_updates.append({"range": cell_ref, "values": [[rank]]})

        row_key = str(r)
        results[row_key] = rank

        if isinstance(rank, int):
            tqdm.write(f"  → Rank {rank} ✅  ({rank_url})")
        elif rank == "-":
            tqdm.write(f"  → Not in top {CONFIG['RESULTS_DEPTH']}")
        else:
            tqdm.write(f"  → {rank}")

        # Flush batch every BATCH_SIZE keywords
        if len(batch_updates) >= BATCH_SIZE:
            retry_sheet_call(worksheet.batch_update, batch_updates, value_input_option="RAW")
            batch_updates = []

        save_progress(date_label, section_name, r, results)
        time.sleep(CONFIG["DELAY_BETWEEN_KEYWORDS"])

    # Flush any remaining batch updates
    if batch_updates:
        retry_sheet_call(worksheet.batch_update, batch_updates, value_input_option="RAW")

    return results


def insert_date_column(worksheet, header_row_idx, date_label):
    """Insert a new date column at position D and write the header."""
    col_index = CONFIG["FIRST_RANK_COL"]

    retry_sheet_call(worksheet.insert_cols, [None], col=col_index)
    retry_sheet_call(worksheet.update_cell, header_row_idx + 1, col_index, date_label)

    retry_sheet_call(
        worksheet.format,
        gspread.utils.rowcol_to_a1(header_row_idx + 1, col_index),
        {"textFormat": {"bold": True}, "horizontalAlignment": "CENTER"},
    )

    return col_index


def run():
    """Main execution function."""
    print("=" * 60)
    print("  UPLERS SEO RANK TRACKER — ValueSERP Edition")
    print("=" * 60)

    # Validate API key
    api_key = CONFIG["VALUESERP_API_KEY"]
    if api_key == "YOUR_VALUESERP_API_KEY_HERE" or not api_key:
        print("\n❌ Please set your ValueSERP API key!")
        print("   Option 1: Set VALUESERP_API_KEY environment variable")
        print("   Option 2: Update the CONFIG in this script")
        print("   Sign up at: https://app.valueserp.com/signup")
        sys.exit(1)

    # Generate today's date label
    date_label = datetime.now().strftime("%B %-d")  # e.g. "March 3"
    print(f"\n📅 Date label: {date_label}")

    # Check for existing progress (resume support)
    progress = load_progress()
    resuming = False
    results = {}
    new_col_index = CONFIG["FIRST_RANK_COL"]

    if progress and progress.get("date_label") == date_label:
        print(f"\n🔄 Found saved progress from {progress['timestamp']}")
        print(f"   Last row: {progress['last_completed_row']}")

        if os.environ.get("CI"):
            resume_input = "y"
            print("   ⚡ CI detected — auto-resuming...")
        else:
            resume_input = input("   Resume from where you left off? (y/n): ").strip().lower()

        if resume_input == "y":
            resuming = True
            results = progress.get("results", {})
            print("   ✅ Resuming...\n")
        else:
            clear_progress()
            print("   🗑️ Progress cleared. Starting fresh.\n")
    elif progress:
        print(f"\n⚠️ Found old progress from {progress.get('date_label', 'unknown')} — clearing it.")
        clear_progress()

    # Connect to Google Sheet
    worksheet = connect_to_sheet()

    print("📥 Reading sheet data...")
    all_data = retry_sheet_call(worksheet.get_all_values)
    print(f"   {len(all_data)} rows loaded.\n")

    data_end = find_data_end(all_data)

    # Insert date column (only if NOT resuming)
    if not resuming:
        print(f"📊 Inserting new column for '{date_label}'...")
        new_col_index = insert_date_column(
            worksheet,
            CONFIG["GLOBAL_HEADER_ROW"] - 1,
            date_label,
        )

        print("📥 Re-reading sheet data after column insertion...")
        all_data = retry_sheet_call(worksheet.get_all_values)
        data_end = find_data_end(all_data)

    # ── Process Keywords ──────────────────────────────────────
    print("\n" + "─" * 60)
    print("🌎 KEYWORDS — California, USA")
    print("─" * 60)

    results = process_section(
        worksheet=worksheet,
        all_data=all_data,
        header_row_idx=CONFIG["GLOBAL_HEADER_ROW"] - 1,
        data_start_idx=CONFIG["GLOBAL_DATA_START"] - 1,
        data_end_idx=data_end,
        location=CONFIG["GLOBAL_LOCATION"],
        gl=CONFIG["GLOBAL_GL"],
        hl=CONFIG["GLOBAL_HL"],
        date_label=date_label,
        section_name="global",
        new_col_index=new_col_index,
        resume_results=results,
    )

    # ── Retry: Re-check keywords that were not found ──────────
    not_found_keys = [k for k, v in results.items() if v == "-" or v == "ERROR"]
    if not_found_keys:
        print("\n" + "─" * 60)
        print(f"🔁 RETRY: Re-checking {len(not_found_keys)} keywords not found in first pass")
        print("─" * 60)

        retry_keywords = []
        for row_key in not_found_keys:
            r = int(row_key)
            if r < len(all_data):
                row = all_data[r]
                keyword = str(row[CONFIG["COL_KEYWORD"] - 1]).strip() if len(row) >= CONFIG["COL_KEYWORD"] else ""
                if keyword:
                    retry_keywords.append((r, keyword))

        total_retry = len(retry_keywords)
        print(f"\n  📋 {total_retry} keywords to retry (~{total_retry} credits)\n")

        retry_batch = []
        for idx, (r, keyword) in enumerate(tqdm(retry_keywords, desc="  retry", unit="kw")):
            tqdm.write(f"    [{idx + 1}/{total_retry}] \"{keyword}\"", end="")

            rank, rank_url = get_rank_from_valueserp(
                keyword,
                CONFIG["GLOBAL_LOCATION"],
                CONFIG["GLOBAL_GL"],
                CONFIG["GLOBAL_HL"],
            )

            row_key = str(r)
            if isinstance(rank, int):
                cell_ref = gspread.utils.rowcol_to_a1(r + 1, new_col_index)
                retry_batch.append({"range": cell_ref, "values": [[rank]]})
                results[row_key] = rank
                tqdm.write(f"  → Rank {rank} ✅  ({rank_url})")
            elif rank == "-":
                tqdm.write(f"  → Still not in top {CONFIG['RESULTS_DEPTH']}")
            else:
                tqdm.write(f"  → {rank}")

            time.sleep(CONFIG["DELAY_BETWEEN_KEYWORDS"])

        # Flush retry batch
        if retry_batch:
            retry_sheet_call(worksheet.batch_update, retry_batch, value_input_option="RAW")

    # ── Summary ───────────────────────────────────────────────
    total_checked = len(results)
    ranked = sum(1 for v in results.values() if isinstance(v, int))
    not_found = sum(1 for v in results.values() if v == "-")
    errors = sum(1 for v in results.values() if v == "ERROR")

    # Estimate credits used (1 per keyword + retries)
    credits_used = total_checked + len(not_found_keys) if not_found_keys else total_checked

    print("\n" + "=" * 60)
    print("  ✅ RANK CHECK COMPLETE!")
    print("=" * 60)
    print(f"  📅 Date column: {date_label}")
    print(f"  🔢 Total keywords checked: {total_checked}")
    print(f"  🎯 Ranked (found in top {CONFIG['RESULTS_DEPTH']}): {ranked}")
    print(f"  ❌ Not found: {not_found}")
    if errors:
        print(f"  ⚠️ Errors: {errors}")
    print(f"  💰 Estimated credits used: ~{credits_used}")
    print("=" * 60)

    clear_progress()
    print("\n🗑️ Progress file cleared. All done!\n")


if __name__ == "__main__":
    run()
