"""Push subnet metrics into Google Sheets tabs: ActiveMiners, Emission, Incentive."""

from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Any, Iterable

_dotenv_loaded = False


def _load_dotenv() -> None:
    """Load repo/.env once so credential paths resolve without exporting env vars."""

    global _dotenv_loaded
    if _dotenv_loaded:
        return
    try:
        from dotenv import load_dotenv  # pylint: disable=import-outside-toplevel
    except ImportError:
        _dotenv_loaded = True  # pragma: no cover — avoid retries every call
        return

    cwd = Path.cwd()
    for candidate in (
        cwd / ".env",
        Path(__file__).resolve().parent / ".env",
    ):
        if candidate.is_file():
            load_dotenv(candidate)
            break
    else:
        load_dotenv()
    _dotenv_loaded = True


def spreadsheet_id_from_input(value: str) -> str:
    """Extract ID from ``https://docs.google.com/spreadsheets/d/<ID>/edit...`` or return trimmed ID."""

    s = value.strip()
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", s)
    if m:
        return m.group(1)
    return s


def spreadsheet_id_from_environment() -> str | None:
    """Spreadsheet target from ``.env`` / process environment (loads ``.env`` first)."""

    _load_dotenv()
    for key in (
        "GOOGLE_SHEET_URL",
        "GOOGLE_SPREADSHEET_URL",
        "GOOGLE_SPREADSHEET_ID",
        "GOOGLE_SHEET_ID",
    ):
        raw = os.environ.get(key)
        if raw and str(raw).strip():
            return spreadsheet_id_from_input(str(raw).strip())
    return None


def spreadsheet_client(credentials_path: str | None):
    """Authorized gspread client from a service-account JSON path."""

    _load_dotenv()
    import gspread  # pylint: disable=import-outside-toplevel
    from google.oauth2.service_account import Credentials  # pylint: disable=import-outside-toplevel

    path = credentials_path or _credentials_path_from_env()
    if not path:
        raise RuntimeError(
            "Set the service account JSON path in .env (e.g. GOOGLE_CREDENTIALS_PATH=…) "
            "or GOOGLE_APPLICATION_CREDENTIALS, or pass --google-credentials",
        )
    expanded = os.path.expanduser(path)
    if not os.path.isfile(expanded):
        raise FileNotFoundError(f"Credentials file not found: {expanded}")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
    ]
    creds = Credentials.from_service_account_file(expanded, scopes=scopes)
    return gspread.authorize(creds)


def _credentials_path_from_env() -> str | None:
    for key in (
        "GOOGLE_CREDENTIALS_PATH",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GOOGLE_SERVICE_ACCOUNT_JSON",
    ):
        p = os.environ.get(key)
        if p and str(p).strip():
            return str(p).strip()
    return None


def resolved_credentials_path(credentials_path_arg: str | None) -> str | None:
    """Path used after ``.env`` and CLI (--google-credentials overrides env)."""

    _load_dotenv()
    if credentials_path_arg and str(credentials_path_arg).strip():
        return os.path.expanduser(str(credentials_path_arg).strip())
    p = _credentials_path_from_env()
    return os.path.expanduser(p) if p else None


def error_chain_detail(exc: BaseException) -> str:
    """Build a readable message; nested causes are included (fixes empty PermissionError strings)."""

    parts: list[str] = []
    cur: BaseException | None = exc
    visited: set[int] = set()
    while cur is not None and id(cur) not in visited:
        visited.add(id(cur))
        text = str(cur).strip()
        if text:
            parts.append(text)
        else:
            parts.append(f"({type(cur).__name__} — see cause below)")
        cur = cur.__cause__
    if not parts:
        return repr(exc)
    return " → ".join(parts)


def _service_account_email_from_json(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        email = data.get("client_email")
        return str(email).strip() if email else None
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def sheets_write_user_message(
    exc: BaseException,
    *,
    credentials_path_arg: str | None = None,
) -> str:
    """Full CLI-style error line for a failed Sheets API call."""

    detail = error_chain_detail(exc)
    cred_path = resolved_credentials_path(credentials_path_arg)
    lower = detail.lower()
    share = (
        "403" in detail
        or "permission" in lower
        or isinstance(exc, PermissionError)
    )
    hint = ""
    if share and cred_path:
        email = _service_account_email_from_json(cred_path)
        if email:
            hint = (
                f" Share the spreadsheet with this Google account as Editor: {email}"
            )
        else:
            hint = (
                " Open your service account JSON and share the spreadsheet with "
                "the `client_email` value as Editor."
            )
    elif share:
        hint = (
            " Share the spreadsheet with your service account `client_email` "
            "(from the JSON key) as Editor."
        )
    return f"Google Sheets write failed: {detail}.{hint}"


def _rowcol_a1(row: int, col: int) -> str:
    from gspread.utils import rowcol_to_a1

    return rowcol_to_a1(row, col)


def _subnet_data_row(ws: Any, subnet: int) -> int | None:
    """First data row (>1) containing ``subnet`` in column A."""

    hits = ws.findall(str(subnet), in_column=1)
    for h in hits:
        if h.row >= 2:
            return h.row
    return None


def _append_row(ws: Any) -> int:
    """Next row index for column A assuming cells are contiguous from row 2 (reasonable for cron use)."""

    col_a = ws.col_values(1)
    # col_values trims trailing blanks; dense column A ⇒ next row length + 1
    following = len(col_a) + 1
    return following if following >= 2 else 2


def sheet_date_header(day: date) -> str:
    """Date column header shown in Sheets: ``month/day`` with no year (e.g. ``5/10``)."""

    return f"{day.month}/{day.day}"


def date_column_index_from_header_row(hdr: list[Any], day: date) -> int | None:
    """1-based column index for ``day`` from row 1 cell values."""

    if not hdr:
        return None
    for idx, cell in enumerate(hdr):
        if _header_matches_calendar_day(str(cell), day):
            return idx + 1
    return None


def date_column_index_readonly(ws: Any, day: date) -> int | None:
    """1-based column index for ``day`` in row 1, or ``None`` if that header does not exist yet."""

    hdr = ws.row_values(1)
    return date_column_index_from_header_row(hdr, day)


def _cell_is_blank(ws: Any, row: int | None, col: int | None) -> bool:
    if row is None or col is None:
        return True
    val = ws.cell(row, col).value
    return val is None or str(val).strip() == ""


def _first_data_row_subnet_col_a(col_a_values: list[Any], subnet: int) -> int | None:
    """Lowest 1-based row whose column A equals ``subnet`` (skip row 1; mirrors ``findall`` + row ≥ 2)."""

    s = str(subnet)
    for i in range(1, len(col_a_values)):  # index 0 is row 1
        if str(col_a_values[i]).strip() == s:
            return i + 1
    return None


def _draft_col_value_nonblank(col_snapshot: list[Any], row_1_based: int | None) -> bool:
    """True if row exists in ``col_snapshot`` (trimmed gspread list) and trimmed cell text is non-empty."""

    if row_1_based is None:
        return False
    idx = row_1_based - 1
    if idx < 0 or idx >= len(col_snapshot):
        return False
    v = col_snapshot[idx]
    return v is not None and str(v).strip() != ""


def netuids_needing_taostats_fetch(
    *,
    spreadsheet_id: str,
    credentials_path: str | None,
    day: date,
    netuids: Iterable[int],
    require_emission: bool,
) -> list[int]:
    """
    Compare **ActiveMiners** / optionally **Emission** vs ``day`` columns (read-only; no mutations).

    If both required cells exist and are non-blank for a netuid, that netuid is **omitted** from
    the result so Taostats is not queried again until a new calendar day adds a new column.

    Uses a bounded number of Sheets **read** requests (row 1 + column A + date column per tab),
    not per-netuid reads, to stay under API rate limits for large ``--start/--end`` ranges.
    """

    client = spreadsheet_client(credentials_path)
    workbook = client.open_by_key(spreadsheet_id)
    ws_miners = _open_worksheet(workbook, "ActiveMiners")
    ws_emission = _open_worksheet(workbook, "Emission")

    ordered = sorted({int(u) for u in netuids})
    hdr_m = ws_miners.row_values(1)
    col_m = date_column_index_from_header_row(hdr_m, day)
    if col_m is None:
        return ordered

    col_a_miners = ws_miners.col_values(1)
    col_dates_miners = ws_miners.col_values(col_m)

    col_a_emission: list[Any] | None = None
    col_dates_emission: list[Any] | None = None
    if require_emission:
        hdr_e = ws_emission.row_values(1)
        col_e = date_column_index_from_header_row(hdr_e, day)
        if col_e is None:
            return ordered
        col_a_emission = ws_emission.col_values(1)
        col_dates_emission = ws_emission.col_values(col_e)

    unseen: list[int] = []
    for nid in ordered:
        row_m = _first_data_row_subnet_col_a(col_a_miners, nid)
        if not _draft_col_value_nonblank(col_dates_miners, row_m):
            unseen.append(nid)
            continue
        if require_emission and col_a_emission is not None and col_dates_emission is not None:
            row_e = _first_data_row_subnet_col_a(col_a_emission, nid)
            if not _draft_col_value_nonblank(col_dates_emission, row_e):
                unseen.append(nid)

    return unseen


def _header_matches_calendar_day(cell_value: str, day: date) -> bool:
    """True if ``cell_value`` denotes the same calendar day as ``day``."""

    raw = str(cell_value).strip()
    if not raw:
        return False
    if raw == sheet_date_header(day):
        return True
    try:
        if date.fromisoformat(raw) == day:
            return True  # legacy YYYY-MM-DD headers
    except ValueError:
        pass

    md = re.match(r"^(?P<m>\d{1,2})/(?P<d>\d{1,2})$", raw)
    if md:
        return int(md.group("m")) == day.month and int(md.group("d")) == day.day
    return False


def _ensure_date_column(ws: Any, *, day: date) -> int:
    """
    Guarantee row 1 includes a header for ``day`` (``month/day``).
    Convention: A1 = ``Subnet``, B1 onward = dated columns.

    Matches existing columns that denote the same day (legacy ISO allowed).
    New columns use :func:`sheet_date_header`.

    Returns 1-based column index for ``day``.
    """

    header_label = sheet_date_header(day)

    hdr = ws.row_values(1)
    if not hdr or all(not str(h).strip() for h in hdr):
        ws.update(
            _rowcol_a1(1, 1) + ":" + _rowcol_a1(1, 2),
            [["Subnet", header_label]],
            value_input_option="USER_ENTERED",
        )
        return 2

    if str(hdr[0]).strip() == "":
        ws.update(_rowcol_a1(1, 1), [["Subnet"]], value_input_option="USER_ENTERED")
        hdr = ws.row_values(1)

    for idx, cell in enumerate(hdr):
        if _header_matches_calendar_day(str(cell), day):
            return idx + 1

    next_col = len(hdr) + 1
    ws.update(
        _rowcol_a1(1, next_col),
        [[header_label]],
        value_input_option="USER_ENTERED",
    )
    return next_col


def _upsert_wide_metric(
    ws: Any,
    *,
    subnet: int,
    day: date,
    value: int | str | float,
) -> None:
    date_col = _ensure_date_column(ws, day=day)
    row = _subnet_data_row(ws, subnet)
    if row is None:
        row = _append_row(ws)

    ws.batch_update(
        [
            {"range": _rowcol_a1(row, 1), "values": [[subnet]]},
            {"range": _rowcol_a1(row, date_col), "values": [[value]]},
        ],
        value_input_option="USER_ENTERED",
    )


def _ensure_incentive_sheet_header(ws: Any, n_cols: int) -> None:
    row1 = ws.row_values(1)
    if (
        row1
        and str(row1[0]).strip().lower() == "subnet"
        and len(row1) >= 1 + n_cols
    ):
        return

    hdr = [["Subnet"] + [f"Incentive{k}" for k in range(1, n_cols + 1)]]
    end_cell = _rowcol_a1(1, 1 + n_cols)
    ws.update(_rowcol_a1(1, 1) + ":" + end_cell, hdr, value_input_option="USER_ENTERED")


def _replace_incentive_row(
    ws: Any,
    *,
    subnet: int,
    incentive_values: list[str],
) -> None:
    n = len(incentive_values)
    if not n:
        return

    _ensure_incentive_sheet_header(ws, n)
    row = _subnet_data_row(ws, subnet)
    if row is None:
        row = _append_row(ws)

    end_col = 1 + n
    rng = _rowcol_a1(row, 1) + ":" + _rowcol_a1(row, end_col)
    ws.update(rng, [[subnet] + incentive_values[:n]], value_input_option="USER_ENTERED")


def _open_worksheet(workbook: Any, title: str) -> Any:
    import gspread  # pylint: disable=import-outside-toplevel

    try:
        return workbook.worksheet(title)
    except gspread.WorksheetNotFound as exc:
        raise RuntimeError(
            f'Worksheet {title!r} not found. Create tabs named exactly '
            '"ActiveMiners", "Emission", and "Incentive".',
        ) from exc


def open_sheet_tabs_for_writes(
    *,
    spreadsheet_id: str,
    credentials_path: str | None,
    day: date | None,
) -> tuple[Any, Any, Any, date]:
    """Return ``(ActiveMiners, Emission, Incentive worksheets, anchor_day)`` — one workbook open."""

    anchor_day = day or date.today()
    client = spreadsheet_client(credentials_path)
    workbook = client.open_by_key(spreadsheet_id)
    ws_miners = _open_worksheet(workbook, "ActiveMiners")
    ws_emission = _open_worksheet(workbook, "Emission")
    ws_incentive = _open_worksheet(workbook, "Incentive")
    return ws_miners, ws_emission, ws_incentive, anchor_day


def sync_subnet_row_to_open_tabs(
    ws_miners: Any,
    ws_emission: Any,
    ws_incentive: Any,
    anchor_day: date,
    *,
    netuid: int,
    miners: int | None,
    emission: str | None,
    incentives: list[str],
) -> None:
    """Write one subnet to the already-open workbook tabs."""

    if miners is not None:
        _upsert_wide_metric(ws_miners, subnet=netuid, day=anchor_day, value=miners)
    if emission is not None:
        _upsert_wide_metric(ws_emission, subnet=netuid, day=anchor_day, value=emission)
    if incentives:
        _replace_incentive_row(ws_incentive, subnet=netuid, incentive_values=incentives)


def sync_subnet_batch(
    *,
    spreadsheet_id: str,
    credentials_path: str | None,
    day: date | None,
    subnets: Iterable[tuple[int, int | None, str | None, list[str]]],
) -> None:
    """
    Write results for subnets into worksheets ``ActiveMiners``, ``Emission``, and ``Incentive``.

    Each item is ``(netuid, active_miners | None, emission_label | None, incentive_strings)``
    """

    ws_miners, ws_emission, ws_incentive, anchor_day = open_sheet_tabs_for_writes(
        spreadsheet_id=spreadsheet_id,
        credentials_path=credentials_path,
        day=day,
    )
    for netuid, miners, emission, incentives in subnets:
        sync_subnet_row_to_open_tabs(
            ws_miners,
            ws_emission,
            ws_incentive,
            anchor_day,
            netuid=netuid,
            miners=miners,
            emission=emission,
            incentives=incentives,
        )
