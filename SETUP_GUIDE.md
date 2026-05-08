# UPLERS SEO Rank Tracker — Setup Guide

## Quick Start (5 minutes)

### Step 1: Install Python packages
```bash
pip install -r requirements.txt
```

### Step 2: Get your ValueSERP API key

1. Sign up at [valueserp.com](https://app.valueserp.com/signup)
2. Copy your API key from the dashboard
3. Set it as an environment variable:
   ```bash
   export VALUESERP_API_KEY="your_key_here"
   ```
   Or update the `CONFIG` directly in `seo_rank_tracker_valueserp.py`

### Step 3: Create Google Cloud credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project (or use existing)
3. Enable these two APIs:
   - **Google Sheets API** → [Enable here](https://console.cloud.google.com/apis/library/sheets.googleapis.com)
   - **Google Drive API** → [Enable here](https://console.cloud.google.com/apis/library/drive.googleapis.com)
4. Go to **Credentials** → **Create Credentials** → **Service Account**
   - Give it any name (e.g., "seo-tracker")
   - Skip the optional steps, click **Done**
5. Click on the service account you just created
6. Go to **Keys** tab → **Add Key** → **Create new key** → **JSON**
7. A file will download — rename it to `credentials.json`
8. Place `credentials.json` in the same folder as the Python script

### Step 4: Share your Google Sheet

1. Open `credentials.json` and find the `"client_email"` field
   - It looks like: `seo-tracker@your-project.iam.gserviceaccount.com`
2. Open your Google Sheet → Click **Share**
3. Paste that email and give it **Editor** access
4. Click **Send** (uncheck "Notify people" if prompted)

### Step 5: Update the script config

Open `seo_rank_tracker_valueserp.py` and confirm:
```python
"SPREADSHEET_NAME": "Your Sheet Name Here",  # ← Exact name of your Google Sheet
"DOMAIN": "yourdomain.com",                  # ← Domain to track
```

### Step 6: Run it!
```bash
python seo_rank_tracker_valueserp.py
```

---

## How Resume Works

- After each keyword, progress is saved to `rank_check_progress.json`
- If the script is interrupted (Ctrl+C, network error, etc.), just run it again
- It will ask if you want to resume from where you left off
- On successful completion, the progress file is automatically deleted

## Credit Usage

- 1 ValueSERP credit per page of results (10 results/page)
- Script stops paginating as soon as your domain is found — saves credits
- Worst case: 10 credits per keyword (full 100-result depth)
- ~1,200 keywords × weekly runs ≈ ~4,800 credits/month (~$25/month)

## GitHub Actions (Automated Weekly Runs)

Add these two secrets to your GitHub repository (`Settings → Secrets → Actions`):

| Secret | Value |
|---|---|
| `VALUESERP_API_KEY` | Your ValueSERP API key |
| `GOOGLE_CREDENTIALS` | Full contents of your `credentials.json` file |

The workflow runs every **Monday at 9:00 AM UTC** automatically.

## Troubleshooting

| Error | Fix |
|---|---|
| `SpreadsheetNotFound` | Check the sheet name in CONFIG and make sure it's shared with the service account |
| `credentials.json not found` | Place the downloaded JSON key file next to the script |
| `API error: Invalid API key` | Check your ValueSERP key in CONFIG or env variable |
| `Low credits warning` | Top up credits at app.valueserp.com |
| `403 Forbidden` | Enable Google Sheets API and Google Drive API in Cloud Console |
