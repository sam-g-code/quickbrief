from __future__ import annotations

from datetime import datetime, timezone, timedelta

from airport_utils import ICAO_TIMEZONES


MONTH_MAP = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4,
    "MAY": 5, "JUN": 6, "JUL": 7, "AUG": 8,
    "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def _to_naive_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def fmt_hhmm(raw: str) -> str:
    """Normalise a raw time like '615', '0615', '06:15' → 'HH:MM'."""
    raw = raw.strip().replace(" ", "").replace(":", "")
    if not raw.isdigit():
        return raw
    if len(raw) == 3:
        h = int(raw[0])
        m = int(raw[1:])
    else:
        h = int(raw[:-2])
        m = int(raw[-2:])
    return f"{h:02d}:{m:02d}"


def utc_to_local_hhmm(utc_hhmm: str, icao: str, flight_date: datetime | None) -> str:
    """Convert UTC HHMM string to local HH:MM using OpenFlights offset + crude DST logic."""
    utc_hhmm = utc_hhmm.replace(":", "").strip()
    if not utc_hhmm.isdigit() or len(utc_hhmm) not in (3, 4):
        return ""

    if len(utc_hhmm) == 3:
        h = int(utc_hhmm[0])
        m = int(utc_hhmm[1:])
    else:
        h = int(utc_hhmm[:-2])
        m = int(utc_hhmm[-2:])

    tz_info = ICAO_TIMEZONES.get(icao)
    if not tz_info:
        return ""

    offset = tz_info.offset_hours

    if tz_info.dst in ("E", "A", "S", "O"):
        if flight_date and flight_date.month in (4, 5, 6, 7, 8, 9):
            offset += 1.0

    total_minutes = h * 60 + m + int(offset * 60)
    total_minutes %= 24 * 60
    local_h = total_minutes // 60
    local_m = total_minutes % 60
    return f"{local_h:02d}:{local_m:02d}"


def build_std_sta(dof_date: datetime, std_str: str, sta_str: str) -> tuple[datetime, datetime]:
    std_hour = int(std_str[:2])
    std_min = int(std_str[2:])
    sta_hour = int(sta_str[:2])
    sta_min = int(sta_str[2:])

    std_dt = dof_date.replace(hour=std_hour, minute=std_min, second=0, microsecond=0)
    sta_dt = dof_date.replace(hour=sta_hour, minute=sta_min, second=0, microsecond=0)

    if sta_dt <= std_dt:
        sta_dt = sta_dt + timedelta(days=1)

    return std_dt, sta_dt


def _parse_hhmm_strict(v: str | None) -> tuple[int, int] | None:
    if not v:
        return None
    v = v.strip()
    if v.endswith("Z"):
        v = v[:-1]
    v = v.strip()

    if ":" in v:
        parts = v.split(":")
        if len(parts) != 2:
            return None
        h_str, m_str = parts
    else:
        if len(v) != 4:
            return None
        h_str, m_str = v[:2], v[2:]

    try:
        h = int(h_str)
        m = int(m_str)
        return h, m
    except ValueError:
        return None


def times_to_datetimes(std_utc: str | None,
                       sta_utc: str | None,
                       dof_dt: datetime) -> dict[str, datetime | None]:
    result: dict[str, datetime | None] = {"STD": None, "STA": None}
    if not dof_dt:
        return result

    base = dof_dt.replace(hour=0, minute=0, second=0, microsecond=0)

    std_dt: datetime | None = None
    sta_dt: datetime | None = None

    std_hm = _parse_hhmm_strict(std_utc)
    if std_hm is not None:
        std_h, std_m = std_hm
        std_dt = base.replace(hour=std_h, minute=std_m)
        result["STD"] = std_dt

    sta_hm = _parse_hhmm_strict(sta_utc)
    if sta_hm is not None:
        sta_h, sta_m = sta_hm
        sta_dt = base.replace(hour=sta_h, minute=sta_m)

        if std_dt and sta_dt <= std_dt:
            sta_dt = sta_dt + timedelta(days=1)

        result["STA"] = sta_dt

    return result