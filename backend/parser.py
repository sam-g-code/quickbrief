from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import NamedTuple

import math
import re
from pypdf import PdfReader

from models import FlightStrip, AirportWeather, Briefing
from weather_parser import (
    parse_weather_blocks,
    pick_metar_taf_for_airport,
    compact_taf_for_window,
)


# ---------------------------------------------------------------------------
# Airport / timezone support
# ---------------------------------------------------------------------------

class AirportInfo(NamedTuple):
    name: str
    iata: str
    tz_name: str
    offset_hours: float
    dst: str  # 'E', 'A', 'S', 'O', 'Z', 'N', 'U'


MONTH_MAP = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4,
    "MAY": 5, "JUN": 6, "JUL": 7, "AUG": 8,
    "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def load_icao_timezones_from_openflights(dat_path: str) -> dict[str, AirportInfo]:
    mapping: dict[str, AirportInfo] = {}
    path = Path(dat_path)
    if not path.exists():
        return mapping

    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            parts = [p.strip().strip('"') for p in line.split(",")]
            if len(parts) < 12:
                continue

            name = parts[1]
            iata = parts[4] if parts[4] != r"\N" else ""
            icao = parts[5].upper()
            offset_str = parts[9].strip()
            dst_flag = parts[10].strip()
            tz_name = parts[11].strip()

            if not icao:
                continue

            try:
                offset = float(offset_str)
            except ValueError:
                offset = 0.0

            mapping[icao] = AirportInfo(
                name=name,
                iata=iata,
                tz_name=tz_name,
                offset_hours=offset,
                dst=dst_flag or "U",
            )
    return mapping


ICAO_TIMEZONES = load_icao_timezones_from_openflights("airports.dat")


def _to_naive_utc(dt: datetime | None) -> datetime | None:
    """
    Convert a datetime with tzinfo=UTC to a naive UTC datetime.
    Leave None or already-naive datetimes as-is.
    """
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def build_std_sta(dof_date: datetime, std_str: str, sta_str: str) -> tuple[datetime, datetime]:
    """
    dof_date: date of flight (UTC) with time 00:00
    std_str, sta_str: 'HHMM' strings in UTC from OFP
    """
    std_hour = int(std_str[:2])
    std_min = int(std_str[2:])
    sta_hour = int(sta_str[:2])
    sta_min = int(sta_str[2:])

    std_dt = dof_date.replace(hour=std_hour, minute=std_min, second=0, microsecond=0)
    sta_dt = dof_date.replace(hour=sta_hour, minute=sta_min, second=0, microsecond=0)

    if sta_dt <= std_dt:
        sta_dt = sta_dt + timedelta(days=1)

    return std_dt, sta_dt


def format_airport_from_icao(icao: str) -> tuple[str, str, str]:
    """
    Return (name, icao, iata) using airports.dat; fallback to (icao, icao, "").
    """
    info = ICAO_TIMEZONES.get(icao)
    if not info:
        return icao, icao, ""
    name = info.name or icao
    iata = info.iata or ""
    return name, icao, iata


# ---------------------------------------------------------------------------
# Basic utilities
# ---------------------------------------------------------------------------

def pdf_to_text(path: str) -> tuple[str, str]:
    """
    Read PDF and return (original_text, normalized_uppercase_text).
    """
    reader = PdfReader(path)
    pages = [page.extract_text() or "" for page in reader.pages]
    text = "\n".join(pages)

    text_norm = text.replace("\r", "\n")
    text_norm = re.sub(r"[ \t]+", " ", text_norm)
    return text, text_norm.upper()


def round_up_1dp(value: float | None) -> str:
    if value is None:
        return ""
    return f"{math.ceil(value * 10) / 10:.1f}"


def fmt_hhmm(raw: str) -> str:
    """
    Normalise a raw time like '615', '0615', '06:15' → 'HH:MM'.
    """
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
    """
    Convert UTC HHMM string to local HH:MM using OpenFlights offset + crude DST logic.
    """
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


# ---------------------------------------------------------------------------
# Flight header and date parsing
# ---------------------------------------------------------------------------

def parse_ofp_date(text_norm: str) -> datetime | None:
    """
    Parse date of flight from header like 'EK1 01MAY OMDB/DXB-EGLL/LHR'.
    Assumes current year for now.
    """
    m = re.search(r"\b[A-Z]{2}\d{1,4}\s+(\d{2})([A-Z]{3})\b", text_norm)
    if not m:
        return None
    day_str, mon_str = m.group(1, 2)
    day = int(day_str)
    mon_str = mon_str.upper()
    month = MONTH_MAP.get(mon_str)
    if not month:
        return None

    year = datetime.now().year
    try:
        return datetime(year, month, day)
    except ValueError:
        return None


def parse_flight_numbers(text_norm: str) -> tuple[str, str]:
    """
    Commercial flight number and ATC callsign.
    """
    commercial = ""
    atc = ""

    m = re.search(
        r"\b([A-Z]{2}\d{1,4})\s+\d{2}[A-Z]{3}\s+[A-Z]{4}/[A-Z]{3}-[A-Z]{4}/[A-Z]{3}",
        text_norm
    )
    if m:
        commercial = m.group(1)

    m2 = re.search(
        r"\b([A-Z]{3}[A-Z0-9]{1,4})\b\s+SIGNATURE\b",
        text_norm
    )
    if m2:
        atc = m2.group(1)

    return commercial, atc


def parse_airports(text_norm: str):
    """
    Parse dep/dest/alt airports from header and ALTN lines.
    """
    dep = ("", "", "")
    dest = ("", "", "")
    alt = ("", "", "")

    m_hdr = re.search(
        r"\b[A-Z]{2}\d{1,4}\s+\d{2}[A-Z]{3}\s+([A-Z]{4})/([A-Z]{3})-([A-Z]{4})/([A-Z]{3})",
        text_norm
    )
    if m_hdr:
        dep_icao, dep_iata, dest_icao, dest_iata = m_hdr.group(1, 2, 3, 4)
        dep_name = "DEPARTURE"
        dest_name = "DESTINATION"
        dep = (dep_iata, dep_icao, dep_name)
        dest = (dest_iata, dest_icao, dest_name)

    m_alt_full = re.search(r"\bALTN(?:\s+APT)?\s+([A-Z]{3})/([A-Z]{4})\s+(.+)", text_norm)
    if m_alt_full:
        alt_iata, alt_icao, alt_name = m_alt_full.group(1, 2, 3)
        alt = (alt_iata, alt_icao, alt_name.title())
    else:
        m_alt_icao = re.search(r"\bALTN\s+([A-Z]{4})\b", text_norm)
        if m_alt_icao:
            alt_icao = m_alt_icao.group(1)
            alt = ("", alt_icao, alt_icao)

    return dep, dest, alt


# ---------------------------------------------------------------------------
# Times, levels, weights
# ---------------------------------------------------------------------------

def parse_times(text_norm: str,
                dep_icao: str,
                dest_icao: str,
                flight_date: datetime | None):
    """
    Extract STD/STA UTC and local, plus flight time, from OFP text.
    DEP/ARR are assumed to be UTC.
    """
    std_utc = std_local = sta_utc = sta_local = flight_time = ""

    m_arr = re.search(r"\bARR\s+([0-2]\d[0-5]\d)\b", text_norm)
    if m_arr:
        sta_utc = fmt_hhmm(m_arr.group(1))

    m_dep = re.search(r"\bDEP\s+([0-2]\d[0-5]\d)\b", text_norm)
    if m_dep:
        std_utc = fmt_hhmm(m_dep.group(1))

    m_trip = re.search(r"\bTRIP\s+[A-Z]{4}\s+\d+\s+([0-1]?\d[0-5]\d)\b", text_norm)
    if m_trip:
        flight_time = fmt_hhmm(m_trip.group(1))

    if std_utc and dep_icao:
        std_local = utc_to_local_hhmm(std_utc, dep_icao, flight_date)
    if sta_utc and dest_icao:
        sta_local = utc_to_local_hhmm(sta_utc, dest_icao, flight_date)

    return std_utc, std_local, sta_utc, sta_local, flight_time


def _parse_hhmm_strict(v: str | None) -> tuple[int, int] | None:
    """
    Parse 'HH:MM' or 'HHMM' into (hour, minute).
    """
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
    """
    Convert STD/STA UTC time strings to datetimes based on DOF.
    """
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


def parse_aircraft_and_runways(text_norm: str, dep_icao: str, dest_icao: str):
    """
    Registration, engine type, dep/arr runway.
    """
    reg = ""
    eng = ""
    dep_rwy = ""
    arr_rwy = ""

    m_reg = re.search(r"\bA6-?[A-Z0-9]{3}\b", text_norm)
    if m_reg:
        raw = m_reg.group(0)
        raw = raw.replace("-", "")
        reg = f"{raw[:2]}-{raw[2:]}"

    m_subtype = re.search(r"\bA380-(\d{3})\b", text_norm)
    subtype = m_subtype.group(1) if m_subtype else ""
    if subtype == "861":
        eng = "Engine Alliance GP7200"
    elif subtype in ("841", "842"):
        eng = "Rolls-Royce Trent 900"

    if dep_icao:
        m_dep_rwy = re.search(rf"{dep_icao}/(\d{{2}}[A-Z]?)", text_norm)
        if m_dep_rwy:
            dep_rwy = m_dep_rwy.group(1)

    if dest_icao:
        m_arr_rwy = re.search(rf"{dest_icao}/(\d{{2}}[A-Z]?)", text_norm)
        if m_arr_rwy:
            arr_rwy = m_arr_rwy.group(1)

    return reg, eng, dep_rwy, arr_rwy


def parse_fl_and_ci(text_norm: str):
    """
    Parse cost index and planned flight levels from PLND FL block.
    """
    fl_min = ""
    fl_max = ""
    ci = ""

    m_ci = re.search(r"\bCID\s+(\d{1,3})\b", text_norm)
    if m_ci:
        ci = m_ci.group(1)

    m_plnd = re.search(r"PLND FL:(.*(?:\n.+)*)", text_norm)
    if m_plnd:
        block = m_plnd.group(0)
        block = re.split(r"\n[A-Z ]+:", block)[0]
        levels = re.findall(r"\b(\d{3})\b", block)
        if levels:
            fl_min = f"FL{levels[0]}"
            fl_max = f"FL{max(int(x) for x in levels)}"

    return fl_min, fl_max, ci


def parse_weights_and_fuel(text_norm: str):
    """
    Ramp fuel (t), EZFW/ETOW/ELWT in tonnes (rounded up 0.1).
    """
    ramp = ezfw = etow = elwt = ""

    m_ramp = re.search(r"RAMP\s+FUEL\s+(\d+(\.\d+)?)", text_norm)
    if m_ramp:
        ramp_val = float(m_ramp.group(1))
        ramp = round_up_1dp(ramp_val)

    m_ezfw = re.search(r"\bEZFW\s+(\d+)\b", text_norm)
    if m_ezfw:
        ezfw_t = int(m_ezfw.group(1)) / 1000.0
        ezfw = round_up_1dp(ezfw_t)

    m_etow = re.search(r"\bETOW\s+(\d+)\b", text_norm)
    if m_etow:
        etow_t = int(m_etow.group(1)) / 1000.0
        etow = round_up_1dp(etow_t)

    m_elwt = re.search(r"\bELWT\s+(\d+)\b", text_norm)
    if m_elwt:
        elwt_t = int(m_elwt.group(1)) / 1000.0
        elwt = round_up_1dp(elwt_t)

    return ramp, ezfw, etow, elwt


def parse_ofp_version(text_norm: str) -> str:
    m = re.search(r"\bOFP:(\d+)", text_norm)
    return m.group(1) if m else ""


# ---------------------------------------------------------------------------
# Weather: TAF periods and windows
# ---------------------------------------------------------------------------

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


def parse_taf_period(taf_line: str,
                     flight_date: datetime | None,
                     ft_valid_to: datetime | None = None
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

    if ft_valid_to:
        to_dt = ft_valid_to
    else:
        to_dt = from_dt + timedelta(hours=6)

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

    print("DEBUG FM PICK window:", window_start, "to", window_end)

    for start, end, seg_type, text in segments:
        if seg_type != "FM":
            continue

        print("  DEBUG FM CANDIDATE:", repr(text), "start", start, "end", end)

        if not (start <= window_end and end >= window_start):
            print("   -> REJECT (no overlap)")
            continue

        if best_start is None or start >= best_start:
            print("   -> ACCEPT as best so far")
            best_start = start
            best_fm = text
        else:
            print("   -> REJECT (earlier than current best)")

    print("DEBUG FM PICK RESULT:", best_fm)
    return best_fm


def filter_taf_window(taf_lines: list[str],
                      std_dt: datetime | None,
                      sta_dt: datetime | None,
                      flight_date: datetime | None,
                      role: str) -> list[str]:
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

    result = baseline_lines + overlay_lines

    print(
        "DEBUG TAF FILTER:",
        role,
        "window",
        window_start,
        "to",
        window_end,
        "=>",
        result,
    )

    return result


# ---------------------------------------------------------------------------
# Main OFP → Briefing pipeline
# ---------------------------------------------------------------------------

def parse_briefing(path: str) -> Briefing:
    """
    High-level OFP parser: PDF → Briefing, including weather windows.
    """
    text, text_norm = pdf_to_text(path)

    dof_dt = parse_ofp_date(text_norm)
    date_of_flight = dof_dt.strftime("%d %b %Y") if dof_dt else ""

    commercial, atc = parse_flight_numbers(text_norm)
    (dep_iata, dep_icao, dep_name), \
    (dest_iata, dest_icao, dest_name), \
    (alt_iata, alt_icao, alt_name) = parse_airports(text_norm)

    if dep_icao:
        dep_name_db, _, dep_iata_db = format_airport_from_icao(dep_icao)
        dep_name = dep_name_db or dep_name
        if dep_iata_db:
            dep_iata = dep_iata_db

    if dest_icao:
        dest_name_db, _, dest_iata_db = format_airport_from_icao(dest_icao)
        dest_name = dest_name_db or dest_name
        if dest_iata_db:
            dest_iata = dest_iata_db

    if alt_icao:
        alt_name_db, _, alt_iata_db = format_airport_from_icao(alt_icao)
        alt_name = alt_name_db or alt_name
        if alt_iata_db:
            alt_iata = alt_iata_db

    std_utc, std_local, sta_utc, sta_local, flight_time = parse_times(
        text_norm, dep_icao, dest_icao, dof_dt
    )

    print("DEBUG TIMES:", repr(std_utc), repr(sta_utc), repr(std_local), repr(sta_local))

    std_sta_dt = {"STD": None, "STA": None}
    if dof_dt:
        std_sta_dt = times_to_datetimes(std_utc, sta_utc, dof_dt)
    std_dt = std_sta_dt["STD"]
    sta_dt = std_sta_dt["STA"]

    def format_window_label(std_dt: datetime | None,
                            sta_dt: datetime | None,
                            role: str) -> str:
        def hhmm(dt: datetime | None) -> str:
            return dt.strftime("%H:%MZ") if dt else ""

        if role == "dep" and std_dt:
            center = std_dt
            from_dt = center - timedelta(hours=1)
            to_dt = center + timedelta(hours=1)
            return f"STD {hhmm(center)} WX {hhmm(from_dt)}–{hhmm(to_dt)}"

        if role == "arr" and sta_dt:
            center = sta_dt
            from_dt = center - timedelta(hours=1)
            to_dt = center + timedelta(hours=1)
            return f"STA {hhmm(center)} WX {hhmm(from_dt)}–{hhmm(to_dt)}"

        if role == "alt" and sta_dt:
            center = sta_dt
            from_dt = center - timedelta(hours=1)
            to_dt = center + timedelta(hours=2)
            return f"STA {hhmm(center)} WX {hhmm(from_dt)}–{hhmm(to_dt)}"

        return ""

    dep_window_label = format_window_label(std_dt, sta_dt, "dep")
    dest_window_label = format_window_label(std_dt, sta_dt, "arr")
    alt_window_label = format_window_label(std_dt, sta_dt, "alt")

    reg, eng, dep_rwy, arr_rwy = parse_aircraft_and_runways(text_norm, dep_icao, dest_icao)
    fl_min, fl_max, ci = parse_fl_and_ci(text_norm)
    ramp, ezfw, etow, elwt = parse_weights_and_fuel(text_norm)
    ofp_version = parse_ofp_version(text_norm)

    strip = FlightStrip(
        commercial_flight=commercial,
        atc_flight=atc,
        dep_iata=dep_iata, dep_icao=dep_icao, dep_name=dep_name,
        dest_iata=dest_iata, dest_icao=dest_icao, dest_name=dest_name,
        alt_iata=alt_iata, alt_icao=alt_icao, alt_name=alt_name,
        std_utc=std_utc, std_local=std_local,
        sta_utc=sta_utc, sta_local=sta_local,
        flight_time=flight_time,
        ofp_version=ofp_version,
        reg=reg, engine_type=eng,
        dep_rwy=dep_rwy,
        arr_rwy=arr_rwy,
        fl_min=fl_min, fl_max=fl_max,
        cost_index=ci,
        ramp_fuel=ramp,
        ezfw=ezfw, etow=etow, elwt=elwt,
        date_of_flight=date_of_flight,
    )

    metars, tafs = parse_weather_blocks(text)

    dep_metar, dep_taf_all = pick_metar_taf_for_airport(dep_icao, metars, tafs)
    dest_metar, dest_taf_all = pick_metar_taf_for_airport(dest_icao, metars, tafs)
    alt_metar, alt_taf_all = pick_metar_taf_for_airport(alt_icao, metars, tafs)

    def is_compact_taf(taf_lines: list[str]) -> bool:
        if not taf_lines:
            return False
        if len(taf_lines) != 1:
            return False
        line = taf_lines[0].strip()
        return (
            "FT " not in line
            and re.search(r"\b\d{4}/\d{4}\b", line) is not None
        )

    if is_compact_taf(dep_taf_all) and dof_dt and std_dt:
        dep_taf_filtered = [
            compact_taf_for_window(dep_taf_all[0], dof_dt, std_dt, 1, 1)
        ]
    else:
        dep_taf_filtered = filter_taf_window(dep_taf_all, std_dt, sta_dt, dof_dt, "dep")

    if is_compact_taf(dest_taf_all) and dof_dt and sta_dt:
        dest_taf_filtered = [
            compact_taf_for_window(dest_taf_all[0], dof_dt, sta_dt, 1, 1)
        ]
    else:
        dest_taf_filtered = filter_taf_window(dest_taf_all, std_dt, sta_dt, dof_dt, "arr")

    if is_compact_taf(alt_taf_all) and dof_dt and sta_dt:
        alt_taf_filtered = [
            compact_taf_for_window(alt_taf_all[0], dof_dt, sta_dt, 1, 2)
        ]
    else:
        alt_taf_filtered = filter_taf_window(alt_taf_all, std_dt, sta_dt, dof_dt, "alt")

    dep_weather = AirportWeather(
        dep_icao, dep_iata, dep_name,
        dep_window_label,
        dep_metar,
        dep_taf_filtered,
    )

    dest_weather = AirportWeather(
        dest_icao, dest_iata, dest_name,
        dest_window_label,
        dest_metar,
        dest_taf_filtered,
    )

    alt_weather = AirportWeather(
        alt_icao, alt_iata, alt_name,
        alt_window_label,
        alt_metar,
        alt_taf_filtered,
    )

    return Briefing(
        strip=strip,
        dep_weather=dep_weather,
        dest_weather=dest_weather,
        alt_weather=alt_weather,
    )