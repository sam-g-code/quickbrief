from __future__ import annotations

from datetime import datetime, timezone, timedelta
from collections import defaultdict
from typing import Dict, List, Tuple
import re


SECTION_DEPARTURE = "DEPARTURE AIRPORT"
SECTION_DESTINATION = "DESTINATION AIRPORT"
SECTION_DEST_ALT = "DESTINATION ALTERNATE"
SECTION_ESCAPE = "ESCAPE AIRPORTS"
SECTION_ENROUTE = "ENROUTE AIRPORTS"


def parse_weather_blocks(text: str) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    metars: Dict[str, str] = {}
    tafs: Dict[str, List[str]] = defaultdict(list)

    lines = text.splitlines()

    current_section: str | None = None
    current_icao: str | None = None

    header_section_markers = {
        "DEPARTURE AIRPORT:",
        "DESTINATION AIRPORT:",
        "DESTINATION ALTERNATE:",
        "ESCAPE AIRPORT(S):",
        "ENROUTE AIRPORT(S):",
    }

    icao_line_re = re.compile(r"\b([A-Z]{4})/[A-Z]{3}\b")

    def is_metar(line: str) -> bool:
        return line.lstrip().startswith("SA ")

    def is_taf_line(line: str) -> bool:
        s = line.lstrip()
        return (
            s.startswith("FT")
            or s.startswith("FM")
            or s.startswith("BECMG")
            or s.startswith("TEMPO")
            or s.startswith("PROB")
        )

    for raw in lines:
        line = raw.rstrip("\n")
        stripped = line.strip()

        # 1) Section headers
        if stripped in header_section_markers:
            current_section = stripped
            current_icao = None
            continue

        # 2) Airport header line within a section (e.g. OMDB/DXB DUBAI INTL)
        if current_section:
            m_icao = icao_line_re.search(line)
            if m_icao:
                current_icao = m_icao.group(1)
                if current_icao not in tafs:
                    tafs[current_icao] = []
                continue  # airport header line itself has no SA/FT

        if not current_section or not current_icao:
            continue

        s = line.lstrip()

        # 3) METAR line
        if is_metar(line):
            if current_icao not in metars:
                metars[current_icao] = s
            continue

        # 4) Any TAF-related line
        if is_taf_line(line):
            tafs[current_icao].append(s)
            continue

    return metars, tafs


def pick_metar_taf_for_airport(
    icao: str,
    metars: Dict[str, str],
    tafs: Dict[str, List[str]],
) -> Tuple[str, List[str]]:
    """
    Return the METAR and TAF list for a specific ICAO.
    """
    if not icao:
        return "", []

    metar = metars.get(icao, "")
    taf_list = tafs.get(icao, [])
    return metar, taf_list


def parse_ddhh(ddhh: str, flight_date: datetime) -> datetime | None:
    """
    Convert 'DDHH' to a datetime in the same month/year as flight_date (UTC).
    """
    try:
        day = int(ddhh[:2])
        hour = int(ddhh[2:4])
    except ValueError:
        return None

    return datetime(
        flight_date.year,
        flight_date.month,
        day,
        hour,
        0,
        tzinfo=timezone.utc,
    )


def build_compact_taf_segments(
    taf_text: str,
    flight_date: datetime,
) -> list[tuple[datetime, datetime, str]]:
    """
    Given a compact ICAO TAF string, build segments:
      (start_dt, end_dt, text_fragment).

    Example:
      'EGLL 080455Z 0806/0912 09005KT CAVOK PROB30 TEMPO 0807/0812 8000 -SHRA ...'
    """
    tokens = taf_text.split()
    if len(tokens) < 3:
        return []

    # 1) Find header validity token DDHH/DDHH
    valid_idx = None
    valid_match = None
    for i, tok in enumerate(tokens):
        m = re.match(r"^(\d{4})/(\d{4})$", tok)
        if m:
            valid_idx = i
            valid_match = m
            break

    if not valid_match:
        return []

    base_from_str, base_to_str = valid_match.groups()
    base_from = parse_ddhh(base_from_str, flight_date)
    base_to = parse_ddhh(base_to_str, flight_date)
    if not base_from or not base_to:
        return []

    segments: list[tuple[datetime, datetime, str]] = []

    # Base segment: full validity with whole remainder text
    base_tokens = tokens[valid_idx:]
    base_text = " ".join(base_tokens)
    segments.append((base_from, base_to, base_text))

    # Overlay segments: BECMG, TEMPO, PROBxx [TEMPO] DDHH/DDHH ...
    i = valid_idx + 1
    while i < len(tokens):
        tok = tokens[i]

        if tok in ("BECMG", "TEMPO") or tok.startswith("PROB"):
            j = i + 1
            group_key_tokens = [tok]

            # Handle 'PROB30 TEMPO'
            if tok.startswith("PROB") and j < len(tokens) and tokens[j] == "TEMPO":
                group_key_tokens.append(tokens[j])
                j += 1

            if j >= len(tokens):
                break

            m2 = re.match(r"^(\d{4})/(\d{4})$", tokens[j])
            if not m2:
                i += 1
                continue

            from_str, to_str = m2.groups()
            seg_start = parse_ddhh(from_str, flight_date)
            seg_end = parse_ddhh(to_str, flight_date)
            if not seg_start or not seg_end:
                i += 1
                continue

            # Collect until next BECMG/TEMPO/PROB or end
            k = j + 1
            while k < len(tokens):
                next_tok = tokens[k]
                if next_tok in ("BECMG", "TEMPO") or next_tok.startswith("PROB"):
                    break
                k += 1

            seg_tokens = group_key_tokens + [tokens[j]] + tokens[j + 1 : k]
            seg_text = " ".join(seg_tokens)
            segments.append((seg_start, seg_end, seg_text))

            i = k
            continue

        i += 1

    return segments


def compact_taf_for_window(
    taf_text: str,
    flight_date: datetime,
    center: datetime,
    before_hours: int,
    after_hours: int,
) -> str:
    """
    Return a compact TAF body containing every group whose period overlaps
    [center - before_hours, center + after_hours].
    """
    if not center:
        return ""

    window_start = center - timedelta(hours=before_hours)
    window_end = center + timedelta(hours=after_hours)

    segments = build_compact_taf_segments(taf_text, flight_date)
    if not segments:
        return ""

    kept_texts: list[str] = []
    for start, end, text in segments:
        if not (end < window_start or start > window_end):
            kept_texts.append(text)

    return " ".join(kept_texts)