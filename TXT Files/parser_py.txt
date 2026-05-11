from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

from pypdf import PdfReader

from models import FlightStrip, AirportWeather, Briefing
from airport_utils import ICAO_TIMEZONES, format_airport_from_icao
from time_utils import (
    MONTH_MAP, fmt_hhmm, utc_to_local_hhmm,
    times_to_datetimes, _to_naive_utc,
)
from taf_utils import filter_taf_window
from weather_parser import (
    parse_weather_blocks,
    pick_metar_taf_for_airport,
    compact_taf_for_window,
)


# ---------------------------------------------------------------------------
# Basic utilities
# ---------------------------------------------------------------------------

def pdf_to_text(path: str) -> tuple[str, str]:
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


# ---------------------------------------------------------------------------
# Flight header and date parsing
# ---------------------------------------------------------------------------

def parse_ofp_date(text_norm: str) -> datetime | None:
    m = re.search(r"\b[A-Z]{2}\d{1,4}\s+(\d{2})([A-Z]{3})\b", text_norm)
    if not m:
        return None
    day_str, mon_str = m.group(1, 2)
    day = int(day_str)
    month = MONTH_MAP.get(mon_str.upper())
    if not month:
        return None
    year = datetime.now().year
    try:
        return datetime(year, month, day)
    except ValueError:
        return None


def parse_flight_numbers(text_norm: str) -> tuple[str, str]:
    commercial = ""
    atc = ""

    m = re.search(
        r"\b([A-Z]{2}\d{1,4})\s+\d{2}[A-Z]{3}\s+[A-Z]{4}/[A-Z]{3}-[A-Z]{4}/[A-Z]{3}",
        text_norm
    )
    if m:
        commercial = m.group(1)

    m2 = re.search(r"\b([A-Z]{3}[A-Z0-9]{1,4})\b\s+SIGNATURE\b", text_norm)
    if m2:
        atc = m2.group(1)

    return commercial, atc


def parse_airports(text_norm: str):
    dep = ("", "", "")
    dest = ("", "", "")
    alt = ("", "", "")

    m_hdr = re.search(
        r"\b[A-Z]{2}\d{1,4}\s+\d{2}[A-Z]{3}\s+([A-Z]{4})/([A-Z]{3})-([A-Z]{4})/([A-Z]{3})",
        text_norm
    )
    if m_hdr:
        dep_icao, dep_iata, dest_icao, dest_iata = m_hdr.group(1, 2, 3, 4)
        dep = (dep_iata, dep_icao, "DEPARTURE")
        dest = (dest_iata, dest_icao, "DESTINATION")

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


def parse_times(text_norm: str, dep_icao: str, dest_icao: str, flight_date: datetime | None):
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


def parse_aircraft_and_runways(text_norm: str, dep_icao: str, dest_icao: str):
    reg = eng = dep_rwy = arr_rwy = ""

    m_reg = re.search(r"\bA6-?[A-Z0-9]{3}\b", text_norm)
    if m_reg:
        raw = m_reg.group(0).replace("-", "")
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
    fl_min = fl_max = ci = ""

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
    ramp = ezfw = etow = elwt = ""

    m_ramp = re.search(r"RAMP\s+FUEL\s+(\d+(\.\d+)?)", text_norm)
    if m_ramp:
        ramp = round_up_1dp(float(m_ramp.group(1)))

    m_ezfw = re.search(r"\bEZFW\s+(\d+)\b", text_norm)
    if m_ezfw:
        ezfw = round_up_1dp(int(m_ezfw.group(1)) / 1000.0)

    m_etow = re.search(r"\bETOW\s+(\d+)\b", text_norm)
    if m_etow:
        etow = round_up_1dp(int(m_etow.group(1)) / 1000.0)

    m_elwt = re.search(r"\bELWT\s+(\d+)\b", text_norm)
    if m_elwt:
        elwt = round_up_1dp(int(m_elwt.group(1)) / 1000.0)

    return ramp, ezfw, etow, elwt


def parse_ofp_version(text_norm: str) -> str:
    m = re.search(r"\bOFP:(\d+)", text_norm)
    return m.group(1) if m else ""


def parse_max_sr_and_mora(text_norm: str) -> tuple[str, str]:
    lines = text_norm.splitlines()
    in_fp = False
    max_sr = -1
    max_mora = -1
    skip_names = {"PAGE", "DP", "AFTER"}

    for raw_line in lines:
        line = raw_line.strip()

        if not in_fp:
            if "WPT ITT SR/TDEV MORA" in line:
                in_fp = True
            continue

        if "ROUTE TO DESTINATION ALTERNATE" in line:
            break

        if not line or line.startswith(("AWY", "WPT", "---", "***", "----------")):
            continue

        parts = line.split()
        if len(parts) < 2:
            continue

        if parts[0] in skip_names:
            continue

        sr_idx = None
        for i, token in enumerate(parts):
            if re.fullmatch(r"\d{2}/[PM]\d{2,3}", token):
                max_sr = max(max_sr, int(token.split("/", 1)[0]))
                sr_idx = i
                break

        if sr_idx is not None:
            if sr_idx + 1 < len(parts) and re.fullmatch(r"\d{1,3}", parts[sr_idx + 1]):
                max_mora = max(max_mora, int(parts[sr_idx + 1]))
        else:
            for i, token in enumerate(parts):
                if re.fullmatch(r"/[PM]\d{2,3}", token):
                    if i + 1 < len(parts) and re.fullmatch(r"\d{1,3}", parts[i + 1]):
                        max_mora = max(max_mora, int(parts[i + 1]))
                    break

    return (f"{max_sr:02d}" if max_sr >= 0 else ""), (str(max_mora) if max_mora >= 0 else "")


# ---------------------------------------------------------------------------
# Main OFP → Briefing pipeline
# ---------------------------------------------------------------------------

def parse_briefing(path: str) -> Briefing:
    text, text_norm = pdf_to_text(path)

    dof_dt = parse_ofp_date(text_norm)
    date_of_flight = dof_dt.strftime("%d %b %Y") if dof_dt else ""

    commercial, atc = parse_flight_numbers(text_norm)
    (dep_iata, dep_icao, dep_name), \
    (dest_iata, dest_icao, dest_name), \
    (alt_iata, alt_icao, alt_name) = parse_airports(text_norm)

    for icao, name_var, iata_var in [
        (dep_icao, "dep_name", "dep_iata"),
        (dest_icao, "dest_name", "dest_iata"),
        (alt_icao, "alt_name", "alt_iata"),
    ]:
        if icao:
            db_name, _, db_iata = format_airport_from_icao(icao)
            if icao == dep_icao:
                dep_name = db_name or dep_name
                if db_iata: dep_iata = db_iata
            elif icao == dest_icao:
                dest_name = db_name or dest_name
                if db_iata: dest_iata = db_iata
            else:
                alt_name = db_name or alt_name
                if db_iata: alt_iata = db_iata

    std_utc, std_local, sta_utc, sta_local, flight_time = parse_times(
        text_norm, dep_icao, dest_icao, dof_dt
    )

    std_sta_dt = times_to_datetimes(std_utc, sta_utc, dof_dt) if dof_dt else {"STD": None, "STA": None}
    std_dt = std_sta_dt["STD"]
    sta_dt = std_sta_dt["STA"]

    def format_window_label(role: str) -> str:
        def hhmm(dt: datetime | None) -> str:
            return dt.strftime("%H:%MZ") if dt else ""
        if role == "dep" and std_dt:
            center = std_dt
            return f"STD {hhmm(center)} WX {hhmm(center - timedelta(hours=1))}–{hhmm(center + timedelta(hours=1))}"
        if role == "arr" and sta_dt:
            center = sta_dt
            return f"STA {hhmm(center)} WX {hhmm(center - timedelta(hours=1))}–{hhmm(center + timedelta(hours=1))}"
        if role == "alt" and sta_dt:
            center = sta_dt
            return f"STA {hhmm(center)} WX {hhmm(center - timedelta(hours=1))}–{hhmm(center + timedelta(hours=2))}"
        return ""

    reg, eng, dep_rwy, arr_rwy = parse_aircraft_and_runways(text_norm, dep_icao, dest_icao)
    fl_min, fl_max, ci = parse_fl_and_ci(text_norm)
    ramp, ezfw, etow, elwt = parse_weights_and_fuel(text_norm)
    ofp_version = parse_ofp_version(text_norm)
    max_sr, highest_mora = parse_max_sr_and_mora(text_norm)

    strip = FlightStrip(
        commercial_flight=commercial, atc_flight=atc,
        dep_iata=dep_iata, dep_icao=dep_icao, dep_name=dep_name,
        dest_iata=dest_iata, dest_icao=dest_icao, dest_name=dest_name,
        alt_iata=alt_iata, alt_icao=alt_icao, alt_name=alt_name,
        std_utc=std_utc, std_local=std_local,
        sta_utc=sta_utc, sta_local=sta_local,
        flight_time=flight_time,
        ofp_version=ofp_version,
        reg=reg, engine_type=eng,
        dep_rwy=dep_rwy, arr_rwy=arr_rwy,
        fl_min=fl_min, fl_max=fl_max,
        cost_index=ci,
        ramp_fuel=ramp,
        ezfw=ezfw, etow=etow, elwt=elwt,
        date_of_flight=date_of_flight,
        max_shear_rate=max_sr,
        highest_mora=highest_mora,
    )

    metars, tafs = parse_weather_blocks(text)
    dep_metar, dep_taf_all = pick_metar_taf_for_airport(dep_icao, metars, tafs)
    dest_metar, dest_taf_all = pick_metar_taf_for_airport(dest_icao, metars, tafs)
    alt_metar, alt_taf_all = pick_metar_taf_for_airport(alt_icao, metars, tafs)

    def is_compact_taf(taf_lines: list[str]) -> bool:
        if not taf_lines or len(taf_lines) != 1:
            return False
        line = taf_lines[0].strip()
        return "FT " not in line and re.search(r"\b\d{4}/\d{4}\b", line) is not None

    if is_compact_taf(dep_taf_all) and dof_dt and std_dt:
        dep_taf_filtered = [compact_taf_for_window(dep_taf_all[0], dof_dt, std_dt, 1, 1)]
    else:
        dep_taf_filtered = filter_taf_window(dep_taf_all, std_dt, sta_dt, dof_dt, "dep")

    if is_compact_taf(dest_taf_all) and dof_dt and sta_dt:
        dest_taf_filtered = [compact_taf_for_window(dest_taf_all[0], dof_dt, sta_dt, 1, 1)]
    else:
        dest_taf_filtered = filter_taf_window(dest_taf_all, std_dt, sta_dt, dof_dt, "arr")

    if is_compact_taf(alt_taf_all) and dof_dt and sta_dt:
        alt_taf_filtered = [compact_taf_for_window(alt_taf_all[0], dof_dt, sta_dt, 1, 2)]
    else:
        alt_taf_filtered = filter_taf_window(alt_taf_all, std_dt, sta_dt, dof_dt, "alt")

    return Briefing(
        strip=strip,
        dep_weather=AirportWeather(dep_icao, dep_iata, dep_name, format_window_label("dep"), dep_metar, dep_taf_filtered),
        dest_weather=AirportWeather(dest_icao, dest_iata, dest_name, format_window_label("arr"), dest_metar, dest_taf_filtered),
        alt_weather=AirportWeather(alt_icao, alt_iata, alt_name, format_window_label("alt"), alt_metar, alt_taf_filtered),
    )