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

## Files

| File | Role |
|------|------|
| `fetch_subnet_info.py` | CLI: fetch metrics as above |
| `requirements.txt` | `requests`, `playwright` |

## Notes

- Taostats HTML and behavior can change; if parsing breaks, adjust selectors or regexes in `fetch_subnet_info.py`.
- This project only reads public pages; it does not use authenticated Taostats APIs.
