import re
from typing import List
from models import NotamEntry, AirportNotamSection


AIRPORT_HEADER_RE = re.compile(
    r"^([A-Z]{4})\s+([A-Z]{3})\s+(.+?)\s+-\s+DETAILED INFO\s*$"
)

NOTAM_START_RE = re.compile(
    r"^(RUNWAY|AIRPORT|APPROACH PROCEDURE|SIDSTAR|COMPANY NOTAM|CHART NOTAM|AMDB NOTAM)\b"
)

NOTAM_ID_RE = re.compile(
    r"\b([A-Z]{1,3}\d{2,7})\b"
)


def normalize_notam_text(text: str) -> List[str]:
    """
    Clean the OFP text into simple lines for easier parsing.
    """
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return lines


def is_noise_line(line: str) -> bool:
    """
    Ignore page footer lines and OFP page markers.
    """
    if re.search(r"\bPage\s+\d+\s+of\s+\d+\b", line):
        return True

    if re.search(r"\bOFP\d+\b", line):
        return True

    return False


def split_airport_sections(lines: List[str]) -> List[AirportNotamSection]:
    """
    Find airport detailed info sections and collect the lines under each one.
    """
    airport_sections = []
    current_section = None
    current_lines = []

    for line in lines:
        if is_noise_line(line):
            continue

        airport_match = AIRPORT_HEADER_RE.match(line)

        if airport_match:
            if current_section is not None:
                current_section.entries = split_notam_entries(
                    section_lines=current_lines,
                    airport_icao=current_section.airport_icao,
                    airport_iata=current_section.airport_iata,
                    airport_name=current_section.airport_name,
                )
                airport_sections.append(current_section)

            current_section = AirportNotamSection(
                airport_icao=airport_match.group(1),
                airport_iata=airport_match.group(2),
                airport_name=airport_match.group(3).strip(),
                section_title="DETAILED INFO",
                entries=[],
            )
            current_lines = []
            continue

        if current_section is not None:
            current_lines.append(line)

    if current_section is not None:
        current_section.entries = split_notam_entries(
            section_lines=current_lines,
            airport_icao=current_section.airport_icao,
            airport_iata=current_section.airport_iata,
            airport_name=current_section.airport_name,
        )
        airport_sections.append(current_section)

    return airport_sections


def split_notam_entries(
    section_lines: List[str],
    airport_icao: str,
    airport_iata: str,
    airport_name: str,
) -> List[NotamEntry]:
    """
    Split one airport section into many NOTAM entries.
    """
    entries = []
    current_category = None
    current_notam_lines = []

    for line in section_lines:
        category_match = NOTAM_START_RE.match(line)

        if category_match:
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

            current_category = category_match.group(1)
            current_notam_lines = [line]
        else:
            if current_notam_lines:
                current_notam_lines.append(line)

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

    return entries


def build_notam_entry(
    category: str,
    lines: List[str],
    airport_icao: str,
    airport_iata: str,
    airport_name: str,
):
    """
    Build one NotamEntry object from grouped lines.
    """
    raw_text = " ".join(lines).strip()
    raw_text = re.sub(r"\s+", " ", raw_text)

    notam_id_match = NOTAM_ID_RE.search(raw_text)
    notam_id = notam_id_match.group(1) if notam_id_match else ""

    validity_match = re.search(r"\bVALID\s+(.+?)(?=\s[A-Z]{2,}\b|$)", raw_text)
    validity = validity_match.group(1).strip() if validity_match else ""

    return NotamEntry(
        notam_id=notam_id,
        category=category or "",
        validity=validity,
        raw_text=raw_text,
        source_airport_icao=airport_icao,
        source_airport_iata=airport_iata,
        source_airport_name=airport_name,
    )


def parse_notam_sections(text: str) -> List[AirportNotamSection]:
    """
    Main function used by parser.py.
    """
    lines = normalize_notam_text(text)
    return split_airport_sections(lines)