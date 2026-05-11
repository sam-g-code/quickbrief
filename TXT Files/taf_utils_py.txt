from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

from time_utils import _to_naive_utc


@dataclass
class WeatherBlock:
    airport: str
    metar: str
    taf: list[str]
    period_type: str


def extract_metar(block: WeatherBlock) -> str:
    metar_lines = [
        line.strip()
        for line in block.metar.split("\n")
        if line.strip() and re.match(r"^[A-Z0-9/ ]{5,}", line)
    ]
    return " ".join(metar_lines)


def parse_taf_period(
    taf_line: str,
    flight_date: datetime | None,
    ft_valid_to: datetime | None = None,
) -> tuple[datetime | None, datetime | None]:
    base_date = flight_date or datetime.now(timezone.utc)
    year = base_date.year
    month = base_date.month

    m_valid = re.search(r"\b(\d{4})/(\d{4})\b", taf_line)
    if m_valid:
        valid_from, valid_to = m_valid.groups()
        try:
            from_day = int(valid_from[:2])
            from_hour = int(valid_from[2:4])
            to_day = int(valid_to[:2])
            to_hour = int(valid_to[2:4])
            from_dt = datetime(year, month, from_day, from_hour, 0, tzinfo=timezone.utc)
            to_dt = datetime(year, month, to_day, to_hour, 0, tzinfo=timezone.utc)
            return from_dt, to_dt
        except ValueError:
            return None, None

    m_fm = re.search(r"\bFM(\d{2})(\d{2})(\d{2})\b", taf_line)
    if not m_fm:
        m_fm = re.search(r"\bFM(\d{2})(\d{2})\b", taf_line)
        if m_fm:
            day = int(m_fm.group(1))
            hour = int(m_fm.group(2))
            minute = 0
        else:
            return None, None
    else:
        day = int(m_fm.group(1))
        hour = int(m_fm.group(2))
        minute = int(m_fm.group(3))

    try:
        from_dt = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
    except ValueError:
        return None, None

    to_dt = ft_valid_to if ft_valid_to else from_dt + timedelta(hours=6)
    return from_dt, to_dt


def classify_taf_line(text: str) -> str:
    s = text.lstrip()

    if s.startswith("FT"):
        parts = s.split()
        if parts and parts[0] == "FT":
            return "FT"

    if s.startswith("FM"):
        return "FM"
    if s.startswith("BECMG"):
        return "BECMG"
    if s.startswith("TEMPO"):
        return "TEMPO"
    if s.startswith("PROB"):
        parts = s.split()
        if len(parts) > 1 and parts[1] == "TEMPO":
            return "PROB TEMPO"
        return "PROB"

    return "OTHER"


def pick_best_fm_for_window(
    segments: list[tuple[datetime, datetime, str, str]],
    window_start: datetime,
    window_end: datetime,
) -> str | None:
    best_fm: str | None = None
    best_start: datetime | None = None

    for start, end, seg_type, text in segments:
        if seg_type != "FM":
            continue

        if not (start <= window_end and end >= window_start):
            continue

        if best_start is None or start >= best_start:
            best_start = start
            best_fm = text

    return best_fm


def filter_taf_window(
    taf_lines: list[str],
    std_dt: datetime | None,
    sta_dt: datetime | None,
    flight_date: datetime | None,
    role: str,
) -> list[str]:
    if not taf_lines or not flight_date:
        return []

    std_dt_naive = _to_naive_utc(std_dt)
    sta_dt_naive = _to_naive_utc(sta_dt)
    flight_date_naive = _to_naive_utc(flight_date)

    if role == "dep" and not std_dt_naive:
        return []
    if role in ("arr", "alt") and not sta_dt_naive:
        return []

    if role == "dep":
        center = std_dt_naive
        window_start = center - timedelta(hours=1)
        window_end = center + timedelta(hours=1)
    elif role == "arr":
        center = sta_dt_naive
        window_start = center - timedelta(hours=1)
        window_end = center + timedelta(hours=1)
    else:
        center = sta_dt_naive
        window_start = center - timedelta(hours=1)
        window_end = center + timedelta(hours=2)

    segments: list[tuple[datetime, datetime, str, str]] = []
    for line in taf_lines:
        s = line.strip()
        seg_type = classify_taf_line(s)
        if seg_type == "OTHER":
            continue

        start, end = parse_taf_period(s, flight_date_naive, None)

        if start and start.tzinfo is not None:
            start = start.astimezone(timezone.utc).replace(tzinfo=None)
        if end and end.tzinfo is not None:
            end = end.astimezone(timezone.utc).replace(tzinfo=None)

        if not start or not end:
            if seg_type == "FT" and flight_date_naive:
                start = flight_date_naive.replace(hour=0, minute=0, second=0, microsecond=0)
                end = start + timedelta(hours=24)
            else:
                continue

        segments.append((start, end, seg_type, s))

    if not segments:
        return []

    first_ft: str | None = None
    for _, _, seg_type, text in segments:
        if seg_type == "FT":
            first_ft = text
            break

    baseline_lines: list[str] = []
    if first_ft:
        baseline_lines.append(first_ft)

    best_fm = pick_best_fm_for_window(segments, window_start, window_end)
    if best_fm and best_fm not in baseline_lines:
        baseline_lines.append(best_fm)
    else:
        last_becmg_fm: str | None = None
        last_becmg_fm_start: datetime | None = None
        for start, end, seg_type, text in segments:
            if seg_type in {"BECMG", "FM"} and start <= window_end:
                if last_becmg_fm_start is None or start >= last_becmg_fm_start:
                    last_becmg_fm_start = start
                    last_becmg_fm = text
        if last_becmg_fm and last_becmg_fm not in baseline_lines:
            baseline_lines.append(last_becmg_fm)

    overlay_lines: list[str] = []
    for start, end, seg_type, text in segments:
        if seg_type in {"TEMPO", "PROB", "PROB TEMPO"}:
            if end < window_start or start > window_end:
                continue
            overlay_lines.append(text)

    return baseline_lines + overlay_lines