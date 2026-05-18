# notams_parser.py
import re
from datetime import datetime, timedelta
from typing import List, Optional

from models import NotamEntry, AirportNotamSection

NOTAM_HEADER_RE = re.compile(
    r"^([A-Z]{4})\s*/\s*([A-Z]{3})\s+(.+?)\s*-\s*DETAILED INFO$",
    re.IGNORECASE,
)

CATEGORY_RE = re.compile(
    r"^(RUNWAY|AIRPORT|APPROACH PROCEDURE|SIDSTAR|COMPANY NOTAM|CHART NOTAM|AMDB NOTAM)\b",
    re.IGNORECASE,
)

NOTAM_ID_RE = re.compile(
    r"\b([A-Z]{1,3}\d{2,7})\b",
    re.IGNORECASE,
)

NOTAM_ENTRY_START_RE = re.compile(
    r"^(?:\d?[A-Z]{1,2}\d{3,7}|CO\d{2,7}|CC\d{2,7}|CA\d{2,7}|SX\d{2,7})\b",
    re.IGNORECASE,
)

VALID_RANGE_RE = re.compile(
    r"\bVALID:?\s*(\d{10})\s*-\s*(UFN|\d{10}|PERM)\b",
    re.IGNORECASE,
)


def normalize_notam_text(text: str) -> List[str]:
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    lines = [line.strip() for line in text.splitlines()]
    return [line for line in lines if line]


def is_noise_line(line: str) -> bool:
    if re.search(r"\bPage\s+\d+\s+of\s+\d+\b", line, re.IGNORECASE):
        return True
    if re.search(r"\bOFP:\d+\b", line, re.IGNORECASE):
        return True
    return False


def extract_notam_block(text: str) -> str:
    upper = text.upper()

    start = upper.find("AIRPORTLIST ENDED")
    if start == -1:
        start = upper.find("NOTAM")

    if start == -1:
        return text

    end = len(text)
    for marker in ["END OF LIDO-NOTAM-BULLETIN", "ADDITIONAL DOCS"]:
        idx = upper.find(marker, start)
        if idx != -1 and idx < end:
            end = idx

    return text[start:end]


def build_notam_entry(
    category: str,
    lines: List[str],
    airport_icao: str,
    airport_iata: str,
    airport_name: str,
) -> Optional[NotamEntry]:
    raw_text = " ".join(lines).strip()
    raw_text = re.sub(r"\s+", " ", raw_text)

    if not raw_text:
        return None

    notam_id_match = NOTAM_ID_RE.search(raw_text)
    notam_id = notam_id_match.group(1).upper() if notam_id_match else ""

    validity_match = re.search(r"\bVALID\s+(.+?)(?=\s(?:RUNWAY|AIRPORT|APPROACH|SIDSTAR|COMPANY|CHART|AMDB)\b|$)", raw_text, re.IGNORECASE)
    validity = validity_match.group(1).strip() if validity_match else ""

    return NotamEntry(
        notam_id=notam_id,
        category=(category or "").upper(),
        validity=validity,
        raw_text=raw_text,
        source_airport_icao=airport_icao,
        source_airport_iata=airport_iata,
        source_airport_name=airport_name,
        importance="time_filtered",
        importance_score=0,
        importance_reasons=[],
    )


def split_notam_entries(
    section_lines: List[str],
    airport_icao: str,
    airport_iata: str,
    airport_name: str,
) -> List[NotamEntry]:
    entries = []
    current_category = None
    current_notam_lines = []
    current_notam_id = None

    section_boundary_re = re.compile(r"^[=+]{8,}.*[=+]{8,}$")
    category_re = re.compile(
        r"^(RUNWAY|AIRPORT|APPROACH PROCEDURE|SIDSTAR|COMPANY NOTAM|CHART NOTAM|AMDB NOTAM)\b",
        re.IGNORECASE,
    )
    notam_id_start_re = re.compile(
        r"^((?:\d?[A-Z]{1,2}\d{3,7}|CO\d{2,7}|CC\d{2,7}|CA\d{2,7}|SX\d{2,7})/\d{2})\b",
        re.IGNORECASE,
    )
    plain_section_title_re = re.compile(
        r"^(DEPARTURE AIRPORT|DESTINATION AIRPORT|DESTINATION ALTERNATE(?:\(S\)|S)?)$",
        re.IGNORECASE,
    )

    def flush_current():
        nonlocal current_notam_lines, current_notam_id
        if current_notam_lines:
            entry = build_notam_entry(
                category=current_category,
                lines=current_notam_lines,
                airport_icao=airport_icao,
                airport_iata=airport_iata,
                airport_name=airport_name,
            )
            if entry:
                entries.append(entry)
        current_notam_lines = []
        current_notam_id = None

    for line in section_lines:
        if is_noise_line(line):
            continue

        line = line.strip()
        if not line:
            continue

        if section_boundary_re.match(line) or plain_section_title_re.match(line):
            flush_current()
            current_category = None
            continue

        category_match = category_re.match(line)
        if category_match:
            flush_current()
            current_category = category_match.group(1).upper()
            continue

        notam_id_match = notam_id_start_re.match(line)
        if notam_id_match:
            line_notam_id = notam_id_match.group(1).upper()

            if current_notam_lines and current_notam_id == line_notam_id:
                current_notam_lines.append(line)
                continue

            flush_current()
            current_notam_lines = [line]
            current_notam_id = line_notam_id
            continue

        if current_notam_lines:
            current_notam_lines.append(line)

    flush_current()
    return entries


def parse_notam_sections(text: str) -> List[AirportNotamSection]:
    notam_text = extract_notam_block(text)
    lines = normalize_notam_text(notam_text)

    airport_sections: List[AirportNotamSection] = []
    header_indexes: List[int] = []

    divider_title_re = re.compile(
        r"^(DEPARTURE AIRPORT|DESTINATION AIRPORT|DESTINATION ALTERNATE(?:\(S\)|S)?)$",
        re.IGNORECASE,
    )

    for i, line in enumerate(lines):
        if NOTAM_HEADER_RE.match(line):
            header_indexes.append(i)

    for pos, start_idx in enumerate(header_indexes):
        match = NOTAM_HEADER_RE.match(lines[start_idx])
        if not match:
            continue

        airport_icao = match.group(1).upper()
        airport_iata = match.group(2).upper()
        airport_name = match.group(3).strip()

        end_idx = len(lines)

        for j in range(start_idx + 1, len(lines)):
            if NOTAM_HEADER_RE.match(lines[j]):
                end_idx = j
                break
            if divider_title_re.match(lines[j]):
                end_idx = j
                break

        section_lines = lines[start_idx + 1:end_idx]

        entries = split_notam_entries(
            section_lines=section_lines,
            airport_icao=airport_icao,
            airport_iata=airport_iata,
            airport_name=airport_name,
        )

        airport_sections.append(
            AirportNotamSection(
                airport_icao=airport_icao,
                airport_iata=airport_iata,
                airport_name=airport_name,
                section_title="DETAILED INFO",
                entries=entries,
            )
        )

    return airport_sections


def parse_notam_datetime(token: str) -> Optional[datetime]:
    if not token or token.upper() == "UFN":
        return None

    try:
        year = 2000 + int(token[0:2])
        month = int(token[2:4])
        day = int(token[4:6])
        hour = int(token[6:8])
        minute = int(token[8:10])
        return datetime(year, month, day, hour, minute)
    except Exception:
        return None


def extract_validity_range(raw_text: str) -> tuple[Optional[datetime], Optional[datetime]]:
    match = VALID_RANGE_RE.search(raw_text)
    if not match:
        return None, None

    start_dt = parse_notam_datetime(match.group(1))
    end_token = match.group(2).upper()

    if end_token in {"UFN", "PERM"}:
        end_dt = None
    else:
        end_dt = parse_notam_datetime(end_token)

    return start_dt, end_dt


def overlaps_window(
    notam_start: Optional[datetime],
    notam_end: Optional[datetime],
    window_start: Optional[datetime],
    window_end: Optional[datetime],
) -> bool:
    if window_start is None or window_end is None:
        return True

    effective_start = notam_start or datetime.min
    effective_end = notam_end or datetime.max

    return effective_start <= window_end and effective_end >= window_start


def apply_notam_filter_rules(
    entry: NotamEntry,
    window_start: Optional[datetime],
    window_end: Optional[datetime],
) -> Optional[NotamEntry]:
    start_dt, end_dt = extract_validity_range(entry.raw_text)

    if window_start is not None and window_end is not None:
        if not overlaps_window(start_dt, end_dt, window_start, window_end):
            return None

    entry.importance = "time_filtered"
    entry.importance_score = 1
    entry.importance_reasons = ["Within flight window"]
    return entry


def filter_important_notams(
    airport_sections: List[AirportNotamSection],
    dep_icao: str,
    dest_icao: str,
    alt_icao: str,
    std_dt: Optional[datetime],
    sta_dt: Optional[datetime],
) -> List[AirportNotamSection]:
    airport_window_map = {
        dep_icao: (
            std_dt - timedelta(hours=2) if std_dt else None,
            std_dt + timedelta(hours=2) if std_dt else None,
        ),
        dest_icao: (
            sta_dt - timedelta(hours=2) if sta_dt else None,
            sta_dt + timedelta(hours=2) if sta_dt else None,
        ),
        alt_icao: (
            sta_dt if sta_dt else None,
            sta_dt + timedelta(hours=3) if sta_dt else None,
        ),
    }

    wanted = {icao for icao in [dep_icao, dest_icao, alt_icao] if icao}
    filtered_sections: List[AirportNotamSection] = []

    for section in airport_sections:
        if section.airport_icao not in wanted:
            continue

        window_start, window_end = airport_window_map.get(section.airport_icao, (None, None))
        filtered_entries: List[NotamEntry] = []

        for entry in section.entries:
            kept = apply_notam_filter_rules(entry, window_start, window_end)
            if kept:
                filtered_entries.append(kept)

        filtered_sections.append(
            AirportNotamSection(
                airport_icao=section.airport_icao,
                airport_iata=section.airport_iata,
                airport_name=section.airport_name,
                section_title=section.section_title,
                entries=filtered_entries,
            )
        )

    return filtered_sections