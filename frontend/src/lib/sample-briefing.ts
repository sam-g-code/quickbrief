export const sampleBriefing = {
  strip: {
    commercial_flight: "BA286",
    atc_flight: "BAW286",
    date_of_flight: "18 May 2026",
    dep_icao: "EGLL", dep_iata: "LHR", dep_name: "London Heathrow",
    dest_icao: "KSFO", dest_iata: "SFO", dest_name: "San Francisco Intl",
    alt_icao: "KOAK", alt_iata: "OAK", alt_name: "Oakland Intl",
    dep_rwy: "27R", arr_rwy: "28L",
    std_utc: "11:25Z", sta_utc: "21:10Z",
    std_local: "12:25 BST", sta_local: "14:10 PDT",
    ofp_version: "OFP 3 / 09:42Z",
    flight_time: "10:45",
    reg: "G-XWBL", engine_type: "Trent 1000",
    fl_min: "340", fl_max: "400",
    cost_index: "65",
    ramp_fuel: "76,400 kg",
    ezfw: "188,200 kg", etow: "262,800 kg", elwt: "198,600 kg",
    max_shear_rate: "Light",
    highest_mora: "FL150",
  },
  dispatch_notes: [
    "Reduced separation in effect on NAT tracks tonight — expect MNPS clearance via Shanwick.",
    "Crew rest required: augmented operation, third pilot on board.",
    "Tankering not recommended — fuel price parity at destination.",
  ],
  dep_weather: {
    name: "London Heathrow", iata: "LHR", icao: "EGLL",
    window_label: "Valid 11:00Z – 13:00Z (departure ±1h)",
    metar: "EGLL 181050Z 24008KT 9999 FEW035 SCT080 17/09 Q1018 NOSIG",
    taf: ["EGLL 180858Z 1809/1915 24010KT 9999 SCT035 BECMG 1812/1815 25014G24KT"],
  },
  dest_weather: {
    name: "San Francisco Intl", iata: "SFO", icao: "KSFO",
    window_label: "Valid 20:00Z – 22:00Z (arrival ±1h)",
    metar: "KSFO 181056Z 28012KT 6SM BR FEW008 BKN012 14/12 A2992",
    taf: ["KSFO 180720Z 1809/1915 28012KT 5SM BR BKN010 TEMPO 1812/1816 3SM BR BKN006"],
  },
  alt_weather: {
    name: "Oakland Intl", iata: "OAK", icao: "KOAK",
    window_label: "Valid 20:00Z – 22:00Z (alternate window)",
    metar: "KOAK 181053Z 27010KT 10SM FEW012 SCT200 15/11 A2992",
    taf: ["KOAK 180720Z 1809/1915 28010KT P6SM SCT015 BKN200"],
  },
  dep_notams: [
    { notam_id: "A1234/26", validity: "1809/1820", raw_text: "RWY 09L/27R CLSD DUE WIP 0500-2200 DAILY" },
    { notam_id: "A1287/26", validity: "PERM", raw_text: "ILS RWY 09R U/S DUE MAINT — EXPECT RNP APCH" },
  ],
  dest_notams: [
    { notam_id: "A0456/26", validity: "1812/1900", raw_text: "TWY F BETWEEN B AND C CLSD FOR PAVEMENT REPAIR" },
    { notam_id: "A0521/26", validity: "UFN", raw_text: "BIRD ACTIVITY VICINITY AERODROME — ALL RWYS" },
    { notam_id: "A0533/26", validity: "1810/1815", raw_text: "GPS RAIM OUTAGE EXPECTED 2100-2300Z" },
  ],
  alt_notams: [
    { notam_id: "A2201/26", validity: "1808/1830", raw_text: "RWY 30 GRVD SURFACE — REDUCED BRAKING ACTION REPORTED" },
  ],
};

export type Briefing = typeof sampleBriefing;
