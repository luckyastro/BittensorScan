#!/usr/bin/env python3
"""Fetch Taostats subnet metagraph metrics: Active Miners (HTML) and Emissions (document title).

The page sets <title> to a fractional share first (e.g. ``0.0126 · SN79 · …``), which matches
the Emissions percentage card as ``fraction * 100`` (here ``1.26%``). That title is applied
after client JavaScript runs, so this script loads the page once with Playwright.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from urllib.parse import quote

import requests

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    PlaywrightError = type("PlaywrightError", (Exception,), {})  # type: ignore[misc, assignment]
    sync_playwright = None  # type: ignore[assignment]


DEFAULT_SUBNET = 79
DEFAULT_ORDER = "stake:desc"
DEFAULT_TOP_INCENTIVES = 7

# Matches the metric card: label "Active Miners" with info button, then value <p>
_ACTIVE_MINERS_CARD_RE = re.compile(
    r'Active Miners<button[^>]*aria-label="Active Miners info"[^>]*>'
    r".*?</div>\s*"
    r'<div class="flex flex-row items-center[^"]*">\s*'
    r"<p[^>]*>\s*(\d+)\s*</p>",
    re.DOTALL,
)

_TITLE_SN_PREFIX_RE = re.compile(
    r"^\s*(?P<frac>[0-9]+(?:\.[0-9]+)?)\s*·\s*SN(?P<netuid>\d+)\b",
)


def metagraph_url(subnet: int, order: str) -> str:
    order_q = quote(order, safe="")
    return f"https://taostats.io/subnets/{subnet}/metagraph?order={order_q}"


def parse_active_miners(html: str) -> int:
    m = _ACTIVE_MINERS_CARD_RE.search(html)
    if m:
        return int(m.group(1))

    idx = html.find("Active Miners")
    if idx == -1:
        raise ValueError("Could not find 'Active Miners' in page HTML")

    chunk = html[idx : idx + 4000]
    m2 = re.search(r"<p[^>]*>\s*(\d+)\s*</p>", chunk)
    if not m2:
        raise ValueError("Found label but could not parse numeric value")
    return int(m2.group(1))


def parse_emissions_pct_from_title(title: str, *, expected_netuid: int) -> str:
    m = _TITLE_SN_PREFIX_RE.match(title.strip())
    if not m:
        raise ValueError(
            f"Could not parse emissions fraction from document title (got {title!r})",
        )

    uid = int(m.group("netuid"))
    if uid != expected_netuid:
        raise ValueError(
            f"Title subnet SN{uid} does not match expected SN{expected_netuid}",
        )

    frac = float(m.group("frac"))
    pct = frac * 100.0
    return f"{pct:.2f}%"


def _browser_headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }


def _incentive_column_index(page) -> int:
    """METADATA table (``table`` 0) repeats column headers; locate Incentive column."""

    header_table = page.locator("table").nth(0)
    count = header_table.locator("thead th").count()
    for i in range(count):
        if "Incentive" in header_table.locator("thead th").nth(i).inner_text():
            return i
    raise ValueError("Could not find Incentive column in table header")


def sort_metagraph_by_incentive_desc(page, *, wait_ms: float = 2_500) -> None:
    """Apply client-side sort by Incentive (Taostats redirects ``order=incentive:desc`` URL)."""

    idx = _incentive_column_index(page)
    header_cell = page.locator("table").nth(0).locator("thead th").nth(idx)
    header_cell.click()
    page.wait_for_timeout(float(wait_ms))


def parse_top_incentive_cell_texts(page, n: int) -> list[str]:
    """Read the first ``n`` incentive values from the body table (second ``table``)."""

    if n <= 0:
        return []

    col_idx = _incentive_column_index(page)
    body_table = page.locator("table").nth(1)
    rows = body_table.locator("tbody tr")
    row_count = rows.count()
    out: list[str] = []
    for r in range(min(n, row_count)):
        raw = rows.nth(r).locator("td").nth(col_idx).inner_text().strip()
        collapsed = re.sub(r"\s+", "", raw)
        out.append(collapsed)
    if len(out) < n:
        raise ValueError(f"Metagraph has only {len(out)} row(s); needed {n}")
    return out


def fetch_metrics_on_playwright_page(
    page,
    url: str,
    subnet: int,
    *,
    timeout_ms: float = 60_000,
    top_incentives: int = DEFAULT_TOP_INCENTIVES,
    settle_ms: float = 750,
) -> tuple[int, str, list[str]]:
    """Load ``url`` on an existing Playwright ``page``, return miners, emissions, top incentives."""

    page.goto(url, wait_until="domcontentloaded", timeout=float(timeout_ms))
    page.wait_for_timeout(max(float(settle_ms), 2_000))
    title = page.title()
    html = page.content()

    top_vals: list[str] = []
    if top_incentives > 0:
        sort_metagraph_by_incentive_desc(page)
        top_vals = parse_top_incentive_cell_texts(page, top_incentives)

    miners = parse_active_miners(html)
    emissions = parse_emissions_pct_from_title(title, expected_netuid=subnet)
    return miners, emissions, top_vals


def fetch_metrics_playwright(
    url: str,
    subnet: int,
    *,
    timeout_ms: float = 60_000,
    top_incentives: int = DEFAULT_TOP_INCENTIVES,
    settle_ms: float = 750,
) -> tuple[int, str, list[str]]:
    """Open a browser tab, load metagraph at ``url``, read metrics (same as single-run CLI)."""

    if sync_playwright is None:
        raise RuntimeError(
            "Playwright is not installed; run `pip install playwright && playwright install chromium`",
        )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(viewport={"width": 1600, "height": 1200})
            page = context.new_page()
            return fetch_metrics_on_playwright_page(
                page,
                url,
                subnet,
                timeout_ms=timeout_ms,
                top_incentives=top_incentives,
                settle_ms=settle_ms,
            )
        finally:
            browser.close()


def fetch_active_miners_requests_only(url: str, *, timeout: float = 45.0) -> int:
    response = requests.get(url, headers=_browser_headers(), timeout=timeout)
    response.raise_for_status()
    return parse_active_miners(response.text)


def _parse_sheet_date(raw: str) -> date:
    try:
        return date.fromisoformat(raw.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid date {raw!r} (expect YYYY-MM-DD)") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Print Active Miners, Emissions %, and top Incentive column values from Taostats "
            "metagraph (Playwright; sorts by Incentive via one header click)."
        ),
    )
    rng = parser.add_argument_group(
        "range",
        "Fetch contiguous netuids (reuse one browser session). Omit to use --subnet only.",
    )
    rng.add_argument(
        "--start",
        type=int,
        default=None,
        metavar="NETUID",
        help="Inclusive start netuid (use with --end)",
    )
    rng.add_argument(
        "--end",
        type=int,
        default=None,
        metavar="NETUID",
        help="Inclusive end netuid (use with --start)",
    )
    parser.add_argument(
        "--subnet",
        type=int,
        default=DEFAULT_SUBNET,
        help=f"Subnet netuid when not using --start/--end (default: {DEFAULT_SUBNET})",
    )
    parser.add_argument(
        "--order",
        default=DEFAULT_ORDER,
        metavar="FIELD:dir",
        help=(
            "Metagraph sort query param embedded in URLs (see Taostats `?order=`). "
            f"Default: {DEFAULT_ORDER!r}. Example: incentive:desc"
        ),
    )
    parser.add_argument(
        "--url",
        default=None,
        help="Full metagraph URL (overrides --subnet and --order if set)",
    )
    parser.add_argument(
        "--requests-active-miners-only",
        action="store_true",
        help="Use HTTP only for Active Miners (no Playwright); cannot fetch Emissions",
    )
    gsheet = parser.add_argument_group(
        "Google Sheets",
        "Writes to tabs ActiveMiners (wide + dates), Emission (wide + dates), Incentive "
        "(one row per subnet; columns B onward replaced each run).",
    )
    gsheet.add_argument(
        "--google-sheet",
        metavar="ID_OR_URL",
        default=None,
        help=(
            "Spreadsheet ID or full Google Sheets URL; optional if ``GOOGLE_SHEET_URL`` or "
            "``GOOGLE_SPREADSHEET_ID`` is set in ``.env`` (CLI value wins over ``.env``)"
        ),
    )
    gsheet.add_argument(
        "--google-credentials",
        metavar="PATH",
        default=None,
        help=(
            "Service account JSON path (overrides .env / GOOGLE_CREDENTIALS_PATH / "
            "GOOGLE_APPLICATION_CREDENTIALS)"
        ),
    )
    gsheet.add_argument(
        "--sheet-date",
        type=_parse_sheet_date,
        default=None,
        metavar="YYYY-MM-DD",
        help=(
            "Date column header for ActiveMiners / Emission (default: today "
            "in local time)."
        ),
    )
    parser.add_argument(
        "--top-incentives",
        type=int,
        default=DEFAULT_TOP_INCENTIVES,
        metavar="N",
        help=(
            f"After loading the metagraph, sort by Incentive once and print the first N cell values. "
            f"Use 0 to skip (default: {DEFAULT_TOP_INCENTIVES})"
        ),
    )
    args = parser.parse_args(argv)

    if args.start is not None or args.end is not None:
        if args.url is not None:
            parser.error("--url cannot be used with --start/--end")
        if args.start is None or args.end is None:
            parser.error("--start and --end must be supplied together")
        if args.end < args.start:
            parser.error("--end must be >= --start")

    from google_sheet_sync import (
        spreadsheet_id_from_environment,
        spreadsheet_id_from_input,
    )

    def resolved_spreadsheet_id(cli: str | None) -> str | None:
        if cli is not None and str(cli).strip():
            return spreadsheet_id_from_input(str(cli).strip())
        return spreadsheet_id_from_environment()

    sheet_spreadsheet_id = resolved_spreadsheet_id(args.google_sheet)

    sheet_day: date = args.sheet_date if args.sheet_date else date.today()
    synced: list[tuple[int, int | None, str | None, list[str]]] = []

    def emit_sheet_row(
        netuid: int,
        miners_val: int | None,
        emissions_val: str | None,
        incentives_val: list[str],
    ) -> None:
        if sheet_spreadsheet_id:
            synced.append((netuid, miners_val, emissions_val, incentives_val))

    def flush_google_sheet() -> None:
        if not sheet_spreadsheet_id or not synced:
            return
        try:
            from google_sheet_sync import (
                sheets_write_user_message,
                sync_subnet_batch,
            )
        except ImportError as exc:
            raise RuntimeError(
                "Google Sheets export needs gspread and google-auth "
                "(install: pip install -r requirements.txt)",
            ) from exc

        sid = sheet_spreadsheet_id
        try:
            sync_subnet_batch(
                spreadsheet_id=sid,
                credentials_path=args.google_credentials,
                day=sheet_day,
                subnets=synced,
            )
        except Exception as exc:
            raise RuntimeError(
                sheets_write_user_message(
                    exc,
                    credentials_path_arg=args.google_credentials,
                ),
            ) from exc

    def print_subnet_block(subnet_id: int, miners: int, emissions: str, incentives: list[str]) -> None:
        print(f"=== SN{subnet_id} ===")
        print(miners)
        print(emissions)
        for v in incentives:
            print(v)

    try:
        if args.requests_active_miners_only:
            if args.start is not None:
                seen_err: BaseException | None = None
                for netuid in range(args.start, args.end + 1):
                    url = metagraph_url(netuid, args.order)
                    try:
                        miners = fetch_active_miners_requests_only(url)
                        print(f"=== SN{netuid} ===")
                        print(miners)
                        emit_sheet_row(
                            netuid,
                            miners_val=miners,
                            emissions_val=None,
                            incentives_val=[],
                        )
                    except (
                        requests.RequestException,
                        ValueError,
                        RuntimeError,
                    ) as exc:
                        seen_err = exc
                        print(f"=== SN{netuid} ===", file=sys.stderr)
                        print(f"Error: {exc}", file=sys.stderr)

                flush_google_sheet()
                if sheet_spreadsheet_id:
                    print(
                        "Google Sheets: ActiveMiners only in --requests-active-miners-only mode "
                        "(Emission / Incentive need Playwright).",
                        file=sys.stderr,
                    )
                return 1 if seen_err else 0

            url = args.url or metagraph_url(args.subnet, args.order)
            miners = fetch_active_miners_requests_only(url)
            print(miners)
            emit_sheet_row(
                args.subnet,
                miners_val=miners,
                emissions_val=None,
                incentives_val=[],
            )
            flush_google_sheet()
            if sheet_spreadsheet_id:
                print(
                    "Google Sheets: ActiveMiners only in --requests-active-miners-only mode "
                    "(Emission / Incentive need Playwright).",
                    file=sys.stderr,
                )
            return 0

        if sync_playwright is None:
            raise RuntimeError(
                "Playwright is not installed; run `pip install playwright && playwright install chromium`",
            )

        if args.start is not None:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                try:
                    context = browser.new_context(viewport={"width": 1600, "height": 1200})
                    page = context.new_page()
                    last_err: BaseException | None = None
                    for netuid in range(args.start, args.end + 1):
                        url = metagraph_url(netuid, args.order)
                        try:
                            miners, emissions, incentives = fetch_metrics_on_playwright_page(
                                page,
                                url,
                                netuid,
                                top_incentives=args.top_incentives,
                            )
                            emit_sheet_row(netuid, miners, emissions, incentives)
                            print_subnet_block(netuid, miners, emissions, incentives)
                        except (
                            PlaywrightError,
                            ValueError,
                            RuntimeError,
                        ) as exc:
                            last_err = exc
                            print(f"=== SN{netuid} ===", file=sys.stderr)
                            print(f"Error: {exc}", file=sys.stderr)
                    flush_google_sheet()
                    return 1 if last_err else 0
                finally:
                    browser.close()

        url = args.url or metagraph_url(args.subnet, args.order)
        miners, emissions, incentives = fetch_metrics_playwright(
            url,
            args.subnet,
            top_incentives=args.top_incentives,
        )
        emit_sheet_row(args.subnet, miners, emissions, incentives)
        print(miners)
        print(emissions)
        for v in incentives:
            print(v)
        flush_google_sheet()
    except (
        requests.RequestException,
        PlaywrightError,
        ValueError,
        RuntimeError,
    ) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

