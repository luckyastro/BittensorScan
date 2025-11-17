#!/usr/bin/env python3
"""Fetch Taostats subnet metagraph page and print the 'Active Miners' count."""

from __future__ import annotations

import argparse
import re
import sys
from urllib.parse import quote

import requests

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


def fetch_active_miners(url: str, *, timeout: float = 45.0) -> int:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    return parse_active_miners(response.text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print Active Miners count from a Taostats subnet metagraph page.",
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
        help="Full page URL (overrides --subnet and --order if set)",
    )
    args = parser.parse_args(argv)

    url = args.url or metagraph_url(args.subnet, args.order)

    try:
        count = fetch_active_miners(url)
    except (requests.RequestException, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
