import re
from datetime import datetime, timedelta
from typing import List, Optional

from models import NotamEntry, AirportNotamSection

NOTAM_HEADER_RE = re.compile(
    r"^([A-Z]{4})\s*/\s*([A-Z]{3})\s+(.+?)\s*-\s*DETAILED INFO$",
    re.IGNORECASE,
)

NOTAM_HEADER_SPACE_RE = re.compile(
    r"^([A-Z]{4})\s+([A-Z]{3})\s+(.+?)\s*-\s*DETAILED INFO$",
    re.IGNORECASE,
)

CATEGORY_RE = re.compile(
    r"^(RUNWAY|AIRPORT|APPROACH PROCEDURE|SIDSTAR|COMPANY NOTAM|CHART NOTAM|AMDB NOTAM)\b",
    re.IGNORECASE,
)

NOTAM_ENTRY_START_RE = re.compile(
    r"^((?:\d?[A-Z]{1,2}\d{3,7}|CO\d{2,7}|CC\d{2,7}|CA\d{2,7}|SX\d{2,7})/\d{2})\b",
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

    notam_id_match = re.search(
        r"\b((?:\d?[A-Z]{1,2}\d{3,7}|CO\d{2,7}|CC\d{2,7}|CA\d{2,7}|SX\d{2,7})/\d{2})\b",
        raw_text,
        re.IGNORECASE,
    )
    notam_id = notam_id_match.group(1).upper() if notam_id_match else ""

    validity = ""
    start_dt, end_dt = extract_validity_range(raw_text)
    range_match = VALID_RANGE_RE.search(raw_text)
    if range_match:
        start_token = range_match.group(1)
        end_token = range_match.group(2).upper()

        def fmt(dt: Optional[datetime]) -> str:
            if not dt:
                return ""
            return f"{dt.day}/{dt.month}/{str(dt.year)[2:]} {dt.strftime('%H:%M')}"

        if start_dt and end_dt:
            validity = f"{fmt(start_dt)} - {fmt(end_dt)}"
        elif start_dt and end_token in {"UFN", "PERM"}:
            validity = f"{fmt(start_dt)} - {end_token}"
        else:
            validity = f"{start_token} - {end_token}"

    return NotamEntry(
        notam_id=notam_id,
        category=(category or "").upper(),
        validity=validity,
        raw_text=raw_text,
        source_airport_icao=airport_icao,
        source_airport_iata=airport_iata,
        source_airport_name=airport_name,
        importance="unknown",
        importance_score=0,
        importance_reasons=[],
    )


def split_notam_entries(
    section_lines: List[str],
    airport_icao: str,
    airport_iata: str,
    airport_name: str,
) -> List[NotamEntry]:
    entries: List[NotamEntry] = []
    current_category: Optional[str] = None
    current_notam_lines: List[str] = []
    current_notam_id: Optional[str] = None

    section_boundary_re = re.compile(r"^[=+]{8,}.*[=+]{8,}$")
    plain_section_title_re = re.compile(
        r"^(DEPARTURE AIRPORT|DESTINATION AIRPORT|DESTINATION ALTERNATE(?:\(S\)|S)?)$",
        re.IGNORECASE,
    )

    def flush_current():
        nonlocal current_notam_lines, current_notam_id
        if current_notam_lines:
            entry = build_notam_entry(
                category=current_category or "",
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

        category_match = CATEGORY_RE.match(line)
        if category_match:
            flush_current()
            current_category = category_match.group(1).upper()
            continue

        notam_id_match = NOTAM_ENTRY_START_RE.match(line)
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
    divider_title_re = re.compile(
        r"^(DEPARTURE AIRPORT|DESTINATION AIRPORT|DESTINATION ALTERNATE(?:\(S\)|S)?)$",
        re.IGNORECASE,
    )

    header_indexes: List[tuple[int, str, str, str]] = []

    for i, line in enumerate(lines):
        match = NOTAM_HEADER_RE.match(line) or NOTAM_HEADER_SPACE_RE.match(line)
        if match:
            header_indexes.append(
                (
                    i,
                    match.group(1).upper(),
                    match.group(2).upper(),
                    match.group(3).strip(),
                )
            )

    for start_idx, airport_icao, airport_iata, airport_name in header_indexes:
        end_idx = len(lines)

        for j in range(start_idx + 1, len(lines)):
            if divider_title_re.match(lines[j]):
                end_idx = j
                break
            if NOTAM_HEADER_RE.match(lines[j]) or NOTAM_HEADER_SPACE_RE.match(lines[j]):
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


def apply_notam_filter_rules(
    entry: NotamEntry,
    window_start: Optional[datetime],
    window_end: Optional[datetime],
) -> Optional[NotamEntry]:
    start_dt, end_dt = extract_validity_range(entry.raw_text)

    if window_start is not None and window_end is not None:
        effective_start = start_dt or datetime.min
        effective_end = end_dt or datetime.max
        if not (effective_start <= window_end and effective_end >= window_start):
            return None

    text = f"{entry.category} {entry.raw_text}".upper()
    score = 0
    reasons: List[str] = []

    if "COMPANY NOTAM" in text:
        score += 100
        reasons.append("Company NOTAM")

    if ("RWY" in text or "RUNWAY" in text) and any(word in text for word in ["CLSD", "CLOSED", "CLOSURE"]):
        score += 90
        reasons.append("Runway closure")

    if ("TWY" in text or "TAXIWAY" in text) and any(word in text for word in ["CLSD", "CLOSED", "CLOSURE"]):
        score += 70
        reasons.append("Taxiway closure")

    if "RFFS" in text:
        score += 80
        reasons.append("RFFS change")

    if "FUEL" in text:
        score += 80
        reasons.append("Fuel impact")

    if any(word in text for word in ["ILS", "GLS", "MLS", "LOC", "GP", "GS", "DME", "VOR", "NDB", "RNAV", "RNP"]):
        if any(word in text for word in ["U/S", "UNSERVICEABLE", "NOT AVBL", "NOT AVAILABLE", "OUT OF SERVICE"]):
            score += 70
            reasons.append("Nav aid/procedure unavailable")

    if any(word in text for word in ["MDA", "MDH", " DA ", " DH "]):
        score += 60
        reasons.append("Approach minima related")

    if any(word in text for word in ["AIRSPACE", "FIR", "CTA", "TMA", "CTR"]) and any(
        word in text for word in ["CLSD", "CLOSED", "RESTRICTED", "PROHIBITED"]
    ):
        score += 85
        reasons.append("Airspace restriction")

    if score > 0:
        entry.importance = "important"
        entry.importance_score = score
        entry.importance_reasons = reasons
    else:
        entry.importance = "other"
        entry.importance_score = 0
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
            if kept and kept.importance == "important":
                filtered_entries.append(kept)

        filtered_entries.sort(
            key=lambda entry: (
                entry.importance_score,
                entry.notam_id,
            ),
            reverse=True,
        )

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