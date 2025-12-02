# BittensorScan

Small Python helper scripts for pulling public snapshot data from **[taostats.io](https://taostats.io)** subnet metagraph pages.

Main entrypoint: **`fetch_subnet_info.py`** — collects, per subnet netuid:

- **Active miners** (from SSR HTML metagraph cards)
- **Emissions** as a percentage (from the document title after JavaScript runs: leading fraction × 100, e.g. `0.0126` → `1.26%`)
- **Top N Incentive** values from the metagraph table (after one click on the Incentive column header so rows are sorted by incentive descending; the `?order=incentive:desc` query alone is not reliable on Taostats)

## Requirements

- Python 3.10+ (tested with 3.12)
- Chromium for Playwright (installed separately; see below)

## Setup

```bash
cd BittensorScan
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

For **Google Sheets export**, you need a Google Cloud **service account** JSON key whose `client_email` has **Editor** access to the spreadsheet. Create the service account in Google Cloud Console, download the JSON, and share the workbook with that email (`…@….iam.gserviceaccount.com`).

### Credentials via `.env` (recommended)

**Do not pass the JSON path on the command line for normal use.** Put it in a **`.env`** file at the project root (the file is listed in `.gitignore`). Before any Sheets API call, **`google_sheet_sync` loads `.env`** into the environment (`python-dotenv`).

```bash
# .env — service account key (absolute paths are safest)
GOOGLE_CREDENTIALS_PATH=/absolute/path/to/service-account.json

# Target workbook: full URL or bare spreadsheet ID (first non-empty wins)
GOOGLE_SHEET_URL=https://docs.google.com/spreadsheets/d/<SPREADSHEET_ID>/edit
# alternates: GOOGLE_SPREADSHEET_URL, GOOGLE_SPREADSHEET_ID, GOOGLE_SHEET_ID
```

**Credentials path** — checked in order (first non-empty wins):

`GOOGLE_CREDENTIALS_PATH` → `GOOGLE_APPLICATION_CREDENTIALS` → `GOOGLE_SERVICE_ACCOUNT_JSON`

**Spreadsheet target** — checked in order (first non-empty wins):

`GOOGLE_SHEET_URL` → `GOOGLE_SPREADSHEET_URL` → `GOOGLE_SPREADSHEET_ID` → `GOOGLE_SHEET_ID`

You **may** omit `.env` and rely on exporting those variables in your shell, but `.env` is the intended setup.

**Optional override:** **`--google-credentials PATH`** forces a particular JSON path for that run only (for debugging or one-off setups). It overrides anything from `.env` / environment.

If the CLI prints **`403` / `permission`**, Google is rejecting access: open the spreadsheet → **Share**, add the **`client_email`** from that JSON key with **Editor**, then retry.

If you see **“Executable doesn’t exist … ms-playwright/chromium_headless_shell-…”**, run `playwright install chromium` again using the **same** environment as `python` (same venv). If `PLAYWRIGHT_BROWSERS_PATH` points at an old or sandbox directory, clear it and reinstall:

```bash
unset PLAYWRIGHT_BROWSERS_PATH
playwright install chromium
```

## Usage

### One subnet (default netuid 79)

```bash
python fetch_subnet_info.py
```

Prints (example shape):

1. Active miners (integer)
2. Emissions (string, e.g. `1.27%`)
3. Seven lines of Incentive cell text (default)

### Custom subnet and sort param

```bash
python fetch_subnet_info.py --subnet 80 --order stake:desc
```

`--order` is passed into the metagraph URL as `?order=…` (URL-encoded). Example matching Taostats links:

```bash
python fetch_subnet_info.py --subnet 79 --order incentive:desc
```

### Range of netuids (inclusive)

Uses **one** browser session and visits each metagraph in turn. Output is grouped with a header per netuid:

```bash
python fetch_subnet_info.py --start 79 --end 81 --order incentive:desc
```

Sample output:

```text
=== SN79 ===
215
1.27%
0.79821
...
=== SN80 ===
...
```

`--start` and `--end` must be given together; `--end` must be ≥ `--start`. **Do not** combine `--url` with `--start` / `--end`.

### Optional flags

| Flag | Meaning |
|------|--------|
| `--top-incentives N` | After load, sort by Incentive once and print the first **N** values (default `7`; use `0` to skip incentives) |
| `--url URL` | Full metagraph URL (overrides `--subnet` and `--order`; single-subnet only) |
| `--requests-active-miners-only` | HTTP (`requests`) only: Active miners. **No** Playwright, **no** emissions or incentive column. Works with `--start` / `--end` (prints `=== SN… ===` and one number per subnet). |
| `--google-sheet ID_OR_URL` | **Optional if** ``GOOGLE_SHEET_URL`` / ``GOOGLE_SPREADSHEET_ID`` (etc.) is set in **``.env``**. After a successful fetch, write metrics to that workbook (CLI value overrides ``.env``). |
| `--google-credentials PATH` | **Rarely needed.** Overrides the credentials path from **`.env`** / environment for this run only. Prefer `GOOGLE_CREDENTIALS_PATH` in `.env`. |
| `--sheet-date YYYY-MM-DD` | Calendar day used for ActiveMiners / Emission (**column header is written as ``month/day``**, no year; default: today, local time) |

### Google Sheets layout

Create three worksheets named exactly **`ActiveMiners`**, **`Emission`**, and **`Incentive`** (case-sensitive).

**ActiveMiners** and **Emission** (history by date):

- Column **A**: subnet netuid (one row per subnet).
- Column **B** onward: one column per run date. The header row uses **month/day with no year** (e.g. `5/10`).  
  Existing columns that still use legacy **`YYYY-MM-DD`** headers **are reused** when they refer to the same calendar day.
- If a column for today (or `--sheet-date`) already exists in row 1, the matching subnet row is **updated**; otherwise a **new column** is added using the `month/day` label.

**Incentive** (always current snapshot):

- Column **A**: subnet netuid.
- Columns **B …** (default **7** incentive cells): the latest top incentives for that subnet. **Every run overwrites** columns B–… for that subnet’s row (nothing is keyed by date).

Example (Playwright run, range 79–81, full metrics — with **`GOOGLE_CREDENTIALS_PATH`** and **`GOOGLE_SHEET_URL`** in `.env`, no Sheets flags needed):

```bash
python fetch_subnet_info.py --start 79 --end 81 --order incentive:desc
```

To point at a different spreadsheet for one run only, pass **`--google-sheet …`** (overrides `.env`).

With `--requests-active-miners-only`, only **ActiveMiners** is filled; a short note is printed to stderr for **Emission** / **Incentive**.

## Files

| File | Role |
|------|------|
| `fetch_subnet_info.py` | CLI: fetch metrics (and optional Sheets export) |
| `google_sheet_sync.py` | Service-account writes to Sheets |
| `requirements.txt` | `requests`, `playwright`, `gspread`, `google-auth`, `python-dotenv` |

## Notes

- Taostats HTML and behavior can change; if parsing breaks, adjust selectors or regexes in `fetch_subnet_info.py`.
- This project only reads public pages; it does not use authenticated Taostats APIs.
