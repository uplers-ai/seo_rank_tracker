#!/usr/bin/env python3
"""
============================================================
 UPLERS SEO RANK TRACKER — Python Edition
 Fetches Google rankings via SerpAPI for 1,200+ keywords
 and writes results directly to your Google Sheet.

 Features:
   ✅ Google Sheets read/write via API
   ✅ Resume support (picks up where it left off if interrupted)
   ✅ Sequential API calls (safe, respects rate limits)
   ✅ Global + India keyword sections
   ✅ Progress bar and live status
============================================================

 SETUP (one-time):
   1. pip install gspread google-auth requests tqdm
   2. Create a Google Cloud service account:
      - Go to https://console.cloud.google.com
      - Create a project (or use existing)
      - Enable "Google Sheets API" and "Google Drive API"
      - Go to Credentials → Create Credentials → Service Account
      - Download the JSON key file
      - Rename it to "credentials.json" and place it next to this script
   3. Share your Google Sheet with the service account email
      (the email looks like: something@project.iam.gserviceaccount.com)
   4. Update the CONFIG below with your sheet details
   5. Run: python seo_rank_tracker.py
============================================================
"""

import json
import os
import sys
import time
from datetime import datetime

import gspread
import requests
from google.oauth2.service_account import Credentials
from tqdm import tqdm


# ─── CONFIGURATION ───────────────────────────────────────────
CONFIG = {
    # Reads from env variable if set, otherwise falls back to hardcoded key
    "SERP_API_KEY": os.environ.get("SERP_API_KEY", "e3ebf18c52b1ac78cc6c31db0bb69a47c28befd2cf71b97a231fc05ea9757167"),

    # Google Sheet
    "SPREADSHEET_NAME": "SEO Master Dashboard (2026) | Uplers",  # Name of your Google Sheet
    "SHEET_TAB": "sheet1",                        # Tab/worksheet name
    "CREDENTIALS_FILE": "credentials.json",       # Service account key file

    # Domain to track
    "DOMAIN": "uplers.com",
    "RESULTS_DEPTH": 100,  # Max rank to check (up to 100)

    # Section 1 — Global keywords
    "GLOBAL_HEADER_ROW": 2,      # Row number of the Global header
    "GLOBAL_DATA_START": 3,      # First row of Global keyword data
    "GLOBAL_COUNTRY": "us",
    "GLOBAL_LANGUAGE": "en",
    "GLOBAL_LOCATION": "Los Angeles,California,United States",

    # Column positions (1-indexed)
    "COL_URL": 1,       # Column A — page URL
    "COL_KEYWORD": 2,   # Column B — keyword
    "COL_VOL": 3,       # Column C — search volume
    "FIRST_RANK_COL": 4,  # Column D — first ranking data column

    # Rate limiting
    "DELAY_BETWEEN_KEYWORDS": 1.0,  # Seconds between keyword searches
    "DELAY_BETWEEN_PAGES": 0.5,     # Seconds between paginated requests

    # Resume file (tracks progress so you can restart safely)
    "RESUME_FILE": "rank_check_progress.json",
}
# ─────────────────────────────────────────────────────────────


def connect_to_sheet():
    """Authenticate and return the worksheet object."""
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    # If GOOGLE_CREDENTIALS env var is set (GitHub Actions), use it directly
    google_creds_env = os.environ.get("GOOGLE_CREDENTIALS")
    if google_creds_env:
        import io
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
    last_row = CONFIG["GLOBAL_DATA_START"] - 1  # 0-indexed start
    for i in range(CONFIG["GLOBAL_DATA_START"] - 1, len(all_data)):
        row = all_data[i]
        keyword = str(row[CONFIG["COL_KEYWORD"] - 1]).strip() if len(row) >= CONFIG["COL_KEYWORD"] else ""
        if keyword and keyword.lower() != "keywords":
            last_row = i
    return last_row


def get_rank_from_serpapi(keyword, country, lang, location):
    """
    Query SerpAPI with pagination (10 results per page, up to 100).
    Returns: rank (int), "-" if not found, or "ERROR" on failure.
    """
    api_key = CONFIG["SERP_API_KEY"]
    domain = CONFIG["DOMAIN"]
    max_results = CONFIG["RESULTS_DEPTH"]
    page_size = 10

    for start in range(0, max_results, page_size):
        params = {
            "engine": "google",
            "q": keyword,
            "gl": country,
            "hl": lang,
            "num": page_size,
            "start": start,
            "api_key": api_key,
            "no_cache": "true",
        }
        if location:
            params["location"] = location

        page_num = (start // page_size) + 1

        try:
            response = requests.get("https://serpapi.com/search.json", params=params, timeout=30)
            data = response.json()
        except Exception as e:
            print(f"      ⚠️ Request failed (page {page_num}): {e}")
            return "ERROR"

        if "error" in data:
            print(f"      ⚠️ API error: {data['error']}")
            return "ERROR"

        results = data.get("organic_results", [])
        if not results:
            break  # No more results

        for i, result in enumerate(results):
            link = str(result.get("link", "")).lower()
            displayed_link = str(result.get("displayed_link", "")).lower()
            clean_link = link.replace("https://", "").replace("http://", "").replace("www.", "")
            actual_rank = start + i + 1

            if domain in link or domain in displayed_link or domain in clean_link:
                return actual_rank

        time.sleep(CONFIG["DELAY_BETWEEN_PAGES"])

    return "-"


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
        "results": results,  # {row_index: rank_value}
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
                    country, lang, location, date_label, section_name,
                    new_col_index, resume_results=None, resume_row=-1):
    """
    Process one section (Global or India).
    Writes ranks into the already-inserted date column.
    Supports resuming from a specific row.
    """
    results = resume_results or {}
    keywords_to_process = []

    # Build list of keywords to process
    for r in range(data_start_idx, data_end_idx + 1):
        if r >= len(all_data):
            break

        row = all_data[r]
        keyword = str(row[CONFIG["COL_KEYWORD"] - 1]).strip() if len(row) >= CONFIG["COL_KEYWORD"] else ""

        # Skip empty rows, section labels, or header rows
        if not keyword or keyword.lower() == "keywords":
            continue

        # Skip already completed rows (resume support)
        row_key = str(r)
        if row_key in results:
            continue

        keywords_to_process.append((r, keyword))

    if not keywords_to_process:
        print(f"  ✅ {section_name}: All keywords already completed (resumed).")
        return results

    total = len(keywords_to_process)
    print(f"\n  📋 {section_name}: {total} keywords to process\n")

    # Process each keyword with progress bar
    for idx, (r, keyword) in enumerate(tqdm(keywords_to_process, desc=f"  {section_name}", unit="kw")):
        tqdm.write(f"    [{idx + 1}/{total}] \"{keyword}\" [{country.upper()}]", end="")

        rank = get_rank_from_serpapi(keyword, country, lang, location)

        # Write to sheet immediately (row is 1-indexed in gspread)
        worksheet.update_cell(r + 1, new_col_index, rank)

        # Save to results and progress file
        row_key = str(r)
        results[row_key] = rank

        if isinstance(rank, int):
            tqdm.write(f"  → Rank {rank} ✅")
        elif rank == "-":
            tqdm.write(f"  → Not in top {CONFIG['RESULTS_DEPTH']}")
        else:
            tqdm.write(f"  → {rank}")

        # Save progress after each keyword
        save_progress(date_label, section_name, r, results)

        # Rate limit
        time.sleep(CONFIG["DELAY_BETWEEN_KEYWORDS"])

    return results


def insert_date_column(worksheet, header_row_idx, date_label):
    """Insert a new date column at position D and write the header."""
    col_index = CONFIG["FIRST_RANK_COL"]

    # Insert column at position D (shifts existing columns right)
    worksheet.insert_cols([None], col=col_index)

    # Write the date header (1-indexed)
    worksheet.update_cell(header_row_idx + 1, col_index, date_label)

    # Also format: bold via a format request
    worksheet.format(
        gspread.utils.rowcol_to_a1(header_row_idx + 1, col_index),
        {"textFormat": {"bold": True}, "horizontalAlignment": "CENTER"}
    )

    return col_index


def run():
    """Main execution function."""
    print("=" * 60)
    print("  UPLERS SEO RANK TRACKER — Python Edition")
    print("=" * 60)

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

        # Auto-resume in CI (non-interactive), prompt locally
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

    # Read all data
    print("📥 Reading sheet data...")
    all_data = worksheet.get_all_values()
    print(f"   {len(all_data)} rows loaded.\n")

    # Find last row with data
    data_end = find_data_end(all_data)

    # Insert date column (only if NOT resuming — column was already inserted)
    if not resuming:
        print(f"📊 Inserting new column for '{date_label}'...")
        new_col_index = insert_date_column(
            worksheet,
            CONFIG["GLOBAL_HEADER_ROW"] - 1,
            date_label
        )

        # Re-read data after column insertion (columns shifted)
        print("📥 Re-reading sheet data after column insertion...")
        all_data = worksheet.get_all_values()
        data_end = find_data_end(all_data)

    # ── Process Keywords (California, USA) ────────────────────
    print("\n" + "─" * 60)
    print("🌎 KEYWORDS — California, USA")
    print("─" * 60)

    results = process_section(
        worksheet=worksheet,
        all_data=all_data,
        header_row_idx=CONFIG["GLOBAL_HEADER_ROW"] - 1,
        data_start_idx=CONFIG["GLOBAL_DATA_START"] - 1,
        data_end_idx=data_end,
        country=CONFIG["GLOBAL_COUNTRY"],
        lang=CONFIG["GLOBAL_LANGUAGE"],
        location=CONFIG["GLOBAL_LOCATION"],
        date_label=date_label,
        section_name="global",
        new_col_index=new_col_index,
        resume_results=results,
    )

    # ── Retry: Re-check keywords that were not found ────────
    not_found_keys = [k for k, v in results.items() if v == "-" or v == "ERROR"]
    if not_found_keys:
        print("\n" + "─" * 60)
        print(f"🔁 RETRY: Re-checking {len(not_found_keys)} keywords not found in first pass")
        print("─" * 60)

        retry_keywords = []
        for row_key in not_found_keys:
            r = int(row_key)
            row = all_data[r]
            keyword = str(row[CONFIG["COL_KEYWORD"] - 1]).strip() if len(row) >= CONFIG["COL_KEYWORD"] else ""
            if keyword:
                retry_keywords.append((r, keyword))

        total_retry = len(retry_keywords)
        print(f"\n  📋 {total_retry} keywords to retry\n")

        for idx, (r, keyword) in enumerate(tqdm(retry_keywords, desc="  retry", unit="kw")):
            tqdm.write(f"    [{idx + 1}/{total_retry}] \"{keyword}\" [US]", end="")

            rank = get_rank_from_serpapi(
                keyword,
                CONFIG["GLOBAL_COUNTRY"],
                CONFIG["GLOBAL_LANGUAGE"],
                CONFIG["GLOBAL_LOCATION"],
            )

            row_key = str(r)
            if isinstance(rank, int):
                # Found this time — update the sheet and results
                worksheet.update_cell(r + 1, new_col_index, rank)
                results[row_key] = rank
                tqdm.write(f"  → Rank {rank} ✅")
            elif rank == "-":
                tqdm.write(f"  → Still not in top {CONFIG['RESULTS_DEPTH']}")
            else:
                tqdm.write(f"  → {rank}")

            time.sleep(CONFIG["DELAY_BETWEEN_KEYWORDS"])

    # ── Summary ───────────────────────────────────────────────
    total_checked = len(results)
    ranked = sum(1 for v in results.values() if isinstance(v, int))
    not_found = sum(1 for v in results.values() if v == "-")
    errors = sum(1 for v in results.values() if v == "ERROR")

    print("\n" + "=" * 60)
    print("  ✅ RANK CHECK COMPLETE!")
    print("=" * 60)
    print(f"  📅 Date column: {date_label}")
    print(f"  🔢 Total keywords checked: {total_checked}")
    print(f"  🎯 Ranked (found in top {CONFIG['RESULTS_DEPTH']}): {ranked}")
    print(f"  ❌ Not found: {not_found}")
    if errors:
        print(f"  ⚠️ Errors: {errors}")
    print("=" * 60)

    # Clear progress file on successful completion
    clear_progress()
    print("\n🗑️ Progress file cleared. All done!\n")


if __name__ == "__main__":
    run()
