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


def fetch_metrics_playwright(
    url: str,
    subnet: int,
    *,
    timeout_ms: float = 60_000,
) -> tuple[int, str]:
    """Load ``url``, return (active_miners_count, emissions_display_percent)."""

    if sync_playwright is None:
        raise RuntimeError(
            "Playwright is not installed; run `pip install playwright && playwright install chromium`",
        )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=float(timeout_ms))
            page.wait_for_timeout(750)
            title = page.title()
            html = page.content()
        finally:
            browser.close()

    miners = parse_active_miners(html)
    emissions = parse_emissions_pct_from_title(title, expected_netuid=subnet)
    return miners, emissions


def fetch_active_miners_requests_only(url: str, *, timeout: float = 45.0) -> int:
    response = requests.get(url, headers=_browser_headers(), timeout=timeout)
    response.raise_for_status()
    return parse_active_miners(response.text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Print Active Miners and Emissions % from Taostats subnet metagraph URL "
            "(default: one Playwright load)."
        ),
    )
    parser.add_argument(
        "--subnet",
        type=int,
        default=DEFAULT_SUBNET,
        help=f"Subnet netuid (default: {DEFAULT_SUBNET})",
    )
    parser.add_argument(
        "--order",
        default=DEFAULT_ORDER,
        help=f"Metagraph sort order query param (default: {DEFAULT_ORDER!r})",
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
    args = parser.parse_args(argv)

    url = args.url or metagraph_url(args.subnet, args.order)

    try:
        if args.requests_active_miners_only:
            miners = fetch_active_miners_requests_only(url)
            print(miners)
        else:
            miners, emissions = fetch_metrics_playwright(url, args.subnet)
            print(miners)
            print(emissions)
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

