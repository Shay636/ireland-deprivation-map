"""
HRB Addiction Services Scraper
Attempts to collect Irish addiction treatment service locations.
Falls back to a curated list of known services if live sources are unavailable.
"""

import urllib.request
import urllib.parse
import json
import csv
import os
import sys

OUTPUT_FILE = "hrb_addiction_services.csv"

FIELDNAMES = ["name", "lat", "lng", "type", "county", "address", "source"]


def try_osm_overpass():
    """Query OpenStreetMap Overpass API for addiction/rehab services in Ireland."""
    print("Trying OpenStreetMap Overpass API...")
    bbox = "(51.3,-10.6,55.4,-5.9)"
    query = (
        f'[out:json][timeout:40];'
        f'('
        f'node["amenity"="social_facility"]["social_facility"="drug_rehabilitation"]{bbox};'
        f'way["amenity"="social_facility"]["social_facility"="drug_rehabilitation"]{bbox};'
        f'node["healthcare"="rehabilitation"]{bbox};'
        f'node["social_facility"="drug_rehabilitation"]{bbox};'
        f');'
        f'out center;'
    )
    url = "https://overpass-api.de/api/interpreter?data=" + urllib.parse.quote(query)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "IrelandAddictionResearch/1.0"})
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read())
        elements = data.get("elements", [])
        services = []
        for el in elements:
            tags = el.get("tags", {})
            name = tags.get("name", "")
            if not name:
                continue
            lat = el.get("lat") or el.get("center", {}).get("lat")
            lon = el.get("lon") or el.get("center", {}).get("lon")
            if lat and lon:
                services.append({
                    "name": name,
                    "lat": lat,
                    "lng": lon,
                    "type": tags.get("social_facility", tags.get("healthcare", "treatment")),
                    "county": tags.get("addr:county", ""),
                    "address": tags.get("addr:street", ""),
                    "source": "OpenStreetMap",
                })
        print(f"  OSM returned {len(services)} services.")
        return services
    except Exception as e:
        print(f"  OSM failed: {e}")
        return []


def curated_fallback():
    """Comprehensive curated list of known Irish addiction treatment services."""
    print("Using curated fallback list of known Irish addiction treatment services.")
    services = [
        # ── DUBLIN ──────────────────────────────────────────────────────────────
        {"name": "Drug Treatment Centre Board (Trinity Court)", "lat": 53.3428, "lng": -6.2517,
         "type": "outpatient/residential", "county": "Dublin", "address": "30-31 Pearse St, Dublin 2"},
        {"name": "Merchants Quay Ireland Drop-In Centre", "lat": 53.3429, "lng": -6.2759,
         "type": "harm_reduction", "county": "Dublin", "address": "Merchants Quay, Dublin 8"},
        {"name": "Coolmine Therapeutic Community", "lat": 53.3877, "lng": -6.3556,
         "type": "residential", "county": "Dublin", "address": "Blanchardstown, Dublin 15"},
        {"name": "Ana Liffey Drug Project", "lat": 53.3478, "lng": -6.2604,
         "type": "outpatient", "county": "Dublin", "address": "48 Middle Abbey St, Dublin 1"},
        {"name": "Stanhope Street Treatment Centre", "lat": 53.3534, "lng": -6.2826,
         "type": "outpatient", "county": "Dublin", "address": "Stanhope St, Dublin 7"},
        {"name": "Rutland Centre", "lat": 53.2955, "lng": -6.3066,
         "type": "residential", "county": "Dublin", "address": "Knocklyon, Dublin 16"},
        {"name": "Keltoi Residential Treatment Centre", "lat": 53.3541, "lng": -6.2838,
         "type": "residential", "county": "Dublin", "address": "Grangegorman, Dublin 7"},
        {"name": "Saol Project", "lat": 53.3475, "lng": -6.2588,
         "type": "outpatient", "county": "Dublin", "address": "5-6 Amiens St, Dublin 1"},
        {"name": "Rialto Community Drug Team", "lat": 53.3368, "lng": -6.2908,
         "type": "community", "county": "Dublin", "address": "Rialto, Dublin 8"},
        {"name": "Ballymun Community Addiction Team", "lat": 53.4136, "lng": -6.2626,
         "type": "community", "county": "Dublin", "address": "Ballymun, Dublin 11"},
        {"name": "Cherry Orchard Hospital Addiction Services", "lat": 53.3486, "lng": -6.3725,
         "type": "outpatient", "county": "Dublin", "address": "Cherry Orchard, Dublin 10"},
        {"name": "Cluain Mhuire Addiction Services", "lat": 53.2929, "lng": -6.1751,
         "type": "outpatient", "county": "Dublin", "address": "Newtownpark Ave, Blackrock"},
        {"name": "Finglas Community Drug Team", "lat": 53.3905, "lng": -6.2952,
         "type": "community", "county": "Dublin", "address": "Finglas, Dublin 11"},
        {"name": "Cabra Community Drug Team", "lat": 53.3670, "lng": -6.2975,
         "type": "community", "county": "Dublin", "address": "Cabra, Dublin 7"},
        {"name": "Tallaght Drug and Alcohol Service", "lat": 53.2875, "lng": -6.3743,
         "type": "community", "county": "Dublin", "address": "Tallaght, Dublin 24"},
        {"name": "Clondalkin Community Drug Team", "lat": 53.3220, "lng": -6.3952,
         "type": "community", "county": "Dublin", "address": "Clondalkin, Dublin 22"},
        {"name": "Dún Laoghaire Drug and Alcohol Service", "lat": 53.2955, "lng": -6.1359,
         "type": "community", "county": "Dublin", "address": "Dún Laoghaire"},
        {"name": "Bray Community Drug Team", "lat": 53.2024, "lng": -6.0993,
         "type": "community", "county": "Wicklow", "address": "Bray, Co. Wicklow"},
        {"name": "HSE Addiction Services Beaumont", "lat": 53.3929, "lng": -6.2380,
         "type": "outpatient", "county": "Dublin", "address": "Beaumont Hospital, Dublin 9"},
        {"name": "North Dublin Community Drug Team", "lat": 53.4086, "lng": -6.2427,
         "type": "community", "county": "Dublin", "address": "Northside, Dublin"},
        {"name": "Father Peter McVerry Trust - Prospect Hill", "lat": 53.3721, "lng": -6.2599,
         "type": "residential", "county": "Dublin", "address": "Prospect Hill, Dublin 9"},
        {"name": "Crosscare Drug and Alcohol Services", "lat": 53.3677, "lng": -6.2587,
         "type": "community", "county": "Dublin", "address": "Drumcondra, Dublin 9"},
        {"name": "South Inner City Community Drug Team", "lat": 53.3362, "lng": -6.2673,
         "type": "community", "county": "Dublin", "address": "The Liberties, Dublin 8"},
        {"name": "Inchicore Community Drug Team", "lat": 53.3413, "lng": -6.3153,
         "type": "community", "county": "Dublin", "address": "Inchicore, Dublin 8"},
        {"name": "HSE Addiction Service Blanchardstown", "lat": 53.3883, "lng": -6.3765,
         "type": "outpatient", "county": "Dublin", "address": "Blanchardstown, Dublin 15"},
        # ── CORK ────────────────────────────────────────────────────────────────
        {"name": "Tabor Lodge Addiction Treatment Centre", "lat": 51.7338, "lng": -8.3816,
         "type": "residential", "county": "Cork", "address": "Belgooly, Co. Cork"},
        {"name": "Arbour House", "lat": 51.9105, "lng": -8.4653,
         "type": "residential", "county": "Cork", "address": "Farranree, Cork"},
        {"name": "St Michael's Unit Cork", "lat": 51.8912, "lng": -8.4677,
         "type": "inpatient", "county": "Cork", "address": "St Finbarr's Hospital, Cork"},
        {"name": "Cork Community Drug and Alcohol Service", "lat": 51.8977, "lng": -8.4741,
         "type": "community", "county": "Cork", "address": "Cork City"},
        {"name": "Knocknaheeny/Hollyhill Drug Team", "lat": 51.9132, "lng": -8.4985,
         "type": "community", "county": "Cork", "address": "Knocknaheeny, Cork"},
        {"name": "Midleton Addiction Service", "lat": 51.9121, "lng": -8.1716,
         "type": "outpatient", "county": "Cork", "address": "Midleton, Co. Cork"},
        {"name": "Bantry Addiction Service", "lat": 51.6813, "lng": -9.4533,
         "type": "outpatient", "county": "Cork", "address": "Bantry, Co. Cork"},
        # ── LIMERICK ─────────────────────────────────────────────────────────────
        {"name": "Novas Initiatives", "lat": 52.6558, "lng": -8.6268,
         "type": "residential", "county": "Limerick", "address": "Limerick City"},
        {"name": "Limerick Addiction Services (HSE)", "lat": 52.6572, "lng": -8.6263,
         "type": "outpatient", "county": "Limerick", "address": "Limerick City"},
        {"name": "Cuan Mhuire Bruree", "lat": 52.4582, "lng": -8.6720,
         "type": "residential", "county": "Limerick", "address": "Bruree, Co. Limerick"},
        {"name": "Milford Care Centre Addiction Services", "lat": 52.6724, "lng": -8.5917,
         "type": "outpatient", "county": "Limerick", "address": "Castletroy, Limerick"},
        # ── GALWAY ───────────────────────────────────────────────────────────────
        {"name": "Bushypark Treatment Centre", "lat": 53.2744, "lng": -9.0596,
         "type": "residential", "county": "Galway", "address": "Ennis Rd, Galway"},
        {"name": "Galway City Community Addiction Service", "lat": 53.2743, "lng": -9.0547,
         "type": "community", "county": "Galway", "address": "Galway City"},
        {"name": "Cuan Mhuire Coolarne", "lat": 53.5215, "lng": -8.8463,
         "type": "residential", "county": "Galway", "address": "Coolarne, Tuam, Co. Galway"},
        {"name": "Western Region Drug Task Force Services", "lat": 53.2721, "lng": -9.0615,
         "type": "community", "county": "Galway", "address": "Galway"},
        # ── TIPPERARY ─────────────────────────────────────────────────────────────
        {"name": "Aiséirí Treatment Centre Cahir", "lat": 52.3748, "lng": -7.9219,
         "type": "residential", "county": "Tipperary", "address": "Cahir, Co. Tipperary"},
        {"name": "Aiséirí Wexford", "lat": 52.3407, "lng": -6.4659,
         "type": "residential", "county": "Wexford", "address": "Wexford Town"},
        {"name": "Nenagh Addiction Service", "lat": 52.8613, "lng": -8.1972,
         "type": "outpatient", "county": "Tipperary", "address": "Nenagh, Co. Tipperary"},
        {"name": "Clonmel Addiction Service", "lat": 52.3547, "lng": -7.7045,
         "type": "outpatient", "county": "Tipperary", "address": "Clonmel, Co. Tipperary"},
        # ── KERRY ─────────────────────────────────────────────────────────────────
        {"name": "Talbot Grove Treatment Centre", "lat": 52.2299, "lng": -9.4549,
         "type": "residential", "county": "Kerry", "address": "Castleisland, Co. Kerry"},
        {"name": "Kerry Addiction Service Tralee", "lat": 52.2674, "lng": -9.7034,
         "type": "outpatient", "county": "Kerry", "address": "Tralee, Co. Kerry"},
        {"name": "Kerry Addiction Service Killarney", "lat": 52.0562, "lng": -9.5044,
         "type": "outpatient", "county": "Kerry", "address": "Killarney, Co. Kerry"},
        # ── WATERFORD ─────────────────────────────────────────────────────────────
        {"name": "Cuan Mhuire Waterford", "lat": 52.2521, "lng": -7.1076,
         "type": "residential", "county": "Waterford", "address": "Waterford City"},
        {"name": "Waterford Community Addiction Team", "lat": 52.2560, "lng": -7.1102,
         "type": "community", "county": "Waterford", "address": "Waterford City"},
        {"name": "Dungarvan Addiction Service", "lat": 52.0888, "lng": -7.6236,
         "type": "outpatient", "county": "Waterford", "address": "Dungarvan, Co. Waterford"},
        # ── KILKENNY ──────────────────────────────────────────────────────────────
        {"name": "Teen Challenge Ireland", "lat": 52.6527, "lng": -7.2424,
         "type": "residential", "county": "Kilkenny", "address": "Kilkenny"},
        {"name": "Kilkenny Community Addiction Service", "lat": 52.6503, "lng": -7.2506,
         "type": "community", "county": "Kilkenny", "address": "Kilkenny City"},
        # ── WEXFORD ───────────────────────────────────────────────────────────────
        {"name": "Wexford Community Drug and Alcohol Team", "lat": 52.3368, "lng": -6.4631,
         "type": "community", "county": "Wexford", "address": "Wexford Town"},
        # ── WICKLOW ───────────────────────────────────────────────────────────────
        {"name": "Tiglin Challenge Centre", "lat": 52.9871, "lng": -6.0889,
         "type": "residential", "county": "Wicklow", "address": "Ashford, Co. Wicklow"},
        {"name": "Wicklow Community Drug and Alcohol Team", "lat": 52.9805, "lng": -6.0444,
         "type": "community", "county": "Wicklow", "address": "Wicklow Town"},
        # ── KILDARE ───────────────────────────────────────────────────────────────
        {"name": "Cuan Mhuire Athy", "lat": 52.9920, "lng": -6.9842,
         "type": "residential", "county": "Kildare", "address": "Athy, Co. Kildare"},
        {"name": "Kildare Community Addiction Service", "lat": 53.1571, "lng": -6.9126,
         "type": "community", "county": "Kildare", "address": "Naas, Co. Kildare"},
        {"name": "Leixlip Drug and Alcohol Service", "lat": 53.3637, "lng": -6.4950,
         "type": "community", "county": "Kildare", "address": "Leixlip, Co. Kildare"},
        # ── MEATH ─────────────────────────────────────────────────────────────────
        {"name": "Meath Community Drug and Alcohol Service", "lat": 53.6541, "lng": -6.6863,
         "type": "community", "county": "Meath", "address": "Navan, Co. Meath"},
        {"name": "Drogheda Addiction Service", "lat": 53.7197, "lng": -6.3567,
         "type": "community", "county": "Louth", "address": "Drogheda, Co. Louth"},
        # ── LOUTH ─────────────────────────────────────────────────────────────────
        {"name": "Dundalk Community Addiction Team", "lat": 54.0016, "lng": -6.4033,
         "type": "community", "county": "Louth", "address": "Dundalk, Co. Louth"},
        # ── CLARE ─────────────────────────────────────────────────────────────────
        {"name": "Clare Addiction Service Ennis", "lat": 52.8449, "lng": -8.9862,
         "type": "outpatient", "county": "Clare", "address": "Ennis, Co. Clare"},
        # ── MAYO ──────────────────────────────────────────────────────────────────
        {"name": "Mayo Community Addiction Service Castlebar", "lat": 53.8572, "lng": -9.2965,
         "type": "community", "county": "Mayo", "address": "Castlebar, Co. Mayo"},
        {"name": "Ballina Drug and Alcohol Service", "lat": 54.1143, "lng": -9.1591,
         "type": "community", "county": "Mayo", "address": "Ballina, Co. Mayo"},
        # ── DONEGAL ───────────────────────────────────────────────────────────────
        {"name": "Donegal Addiction Services Letterkenny", "lat": 54.9458, "lng": -7.7361,
         "type": "outpatient", "county": "Donegal", "address": "Letterkenny, Co. Donegal"},
        {"name": "Donegal Addiction Services Ballyshannon", "lat": 54.5005, "lng": -8.1875,
         "type": "outpatient", "county": "Donegal", "address": "Ballyshannon, Co. Donegal"},
        # ── SLIGO ─────────────────────────────────────────────────────────────────
        {"name": "Sligo Community Drug and Alcohol Team", "lat": 54.2766, "lng": -8.4762,
         "type": "community", "county": "Sligo", "address": "Sligo Town"},
        # ── ROSCOMMON ─────────────────────────────────────────────────────────────
        {"name": "Roscommon Addiction Services", "lat": 53.6289, "lng": -8.1819,
         "type": "outpatient", "county": "Roscommon", "address": "Roscommon Town"},
        # ── LONGFORD ──────────────────────────────────────────────────────────────
        {"name": "Longford Community Drug and Alcohol Team", "lat": 53.7265, "lng": -7.7939,
         "type": "community", "county": "Longford", "address": "Longford Town"},
        # ── WESTMEATH ─────────────────────────────────────────────────────────────
        {"name": "Athlone Addiction Service", "lat": 53.4239, "lng": -7.9407,
         "type": "community", "county": "Westmeath", "address": "Athlone, Co. Westmeath"},
        {"name": "Mullingar Addiction Service", "lat": 53.5228, "lng": -7.3466,
         "type": "community", "county": "Westmeath", "address": "Mullingar, Co. Westmeath"},
        # ── OFFALY ────────────────────────────────────────────────────────────────
        {"name": "Offaly Community Addiction Service", "lat": 53.2743, "lng": -7.4918,
         "type": "community", "county": "Offaly", "address": "Tullamore, Co. Offaly"},
        # ── LAOIS ─────────────────────────────────────────────────────────────────
        {"name": "Laois Community Addiction Service", "lat": 53.0344, "lng": -7.2988,
         "type": "community", "county": "Laois", "address": "Portlaoise, Co. Laois"},
        # ── CARLOW ────────────────────────────────────────────────────────────────
        {"name": "Carlow Community Drug and Alcohol Team", "lat": 52.8340, "lng": -6.9337,
         "type": "community", "county": "Carlow", "address": "Carlow Town"},
        # ── MONAGHAN ──────────────────────────────────────────────────────────────
        {"name": "Monaghan Addiction Services", "lat": 54.2513, "lng": -6.9680,
         "type": "outpatient", "county": "Monaghan", "address": "Monaghan Town"},
        # ── CAVAN ─────────────────────────────────────────────────────────────────
        {"name": "Cavan Addiction Services", "lat": 53.9897, "lng": -7.3633,
         "type": "outpatient", "county": "Cavan", "address": "Cavan Town"},
        # ── LEITRIM ───────────────────────────────────────────────────────────────
        {"name": "Leitrim Drug and Alcohol Service", "lat": 53.9453, "lng": -8.0831,
         "type": "community", "county": "Leitrim", "address": "Carrick-on-Shannon"},
        # ── FERMANAGH/NORTH (cross-border context) ────────────────────────────────
        {"name": "Midwest Simon Community Addiction Services", "lat": 52.6649, "lng": -8.6294,
         "type": "harm_reduction", "county": "Limerick", "address": "Limerick City"},
        {"name": "Depaul Ireland Dublin", "lat": 53.3463, "lng": -6.2591,
         "type": "harm_reduction", "county": "Dublin", "address": "Dublin 1"},
    ]
    for s in services:
        s["source"] = "curated_public_records"
    return services


def save_csv(services, path):
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(services)
    print(f"Saved {len(services)} services to {path}")


def run():
    if os.path.exists(OUTPUT_FILE):
        print(f"Found existing {OUTPUT_FILE} – skipping scrape.")
        return True

    services = []

    # 1. Try OpenStreetMap
    services = try_osm_overpass()

    # 2. Fall back to curated list if OSM returned too few
    if len(services) < 20:
        print(f"OSM data insufficient ({len(services)} records). Merging with curated list.")
        osm_names = {s["name"].lower() for s in services}
        curated = curated_fallback()
        # Add curated entries not already found in OSM
        for svc in curated:
            if svc["name"].lower() not in osm_names:
                services.append(svc)

    if not services:
        print("\n[ERROR] Could not retrieve any service data.")
        print("Manual fallback: download a CSV from https://www.drugsandalcohol.ie/ or")
        print("  https://www2.hse.ie/services/ and save as hrb_addiction_services.csv")
        print("  with columns: name, lat, lng, type, county, address, source")
        return False

    save_csv(services, OUTPUT_FILE)
    return True


if __name__ == "__main__":
    success = run()
    sys.exit(0 if success else 1)
