#!/usr/bin/env python3
"""Rebuild the static hill catalog from Wikidata, OpenStreetMap, and the NASA Global Landslide Catalog.

Every hill below is pinned to a Wikidata item and carries its landslide record with a source.
For each one the script reads the item's coordinates and elevation, finds the matching summit
or cliff in OpenStreetMap, collects the named paths within PATH_RADIUS_M (ways and walking-route
relations), orients each path from its lower end on the Terrarium tiles, colors the marker from
the catalog's fatalities within 10 km, and writes:

  data/seed/hills.json                    Turtle Mountain (the live hill) unchanged, then these rows
  data/seed/hills/<slug>/trails.geojson   named paths, ODbL
  data/seed/satellite_images.json         the hill rows only; mountain rows are left alone
  data/seed/sources.md                    the table between the hill-catalog markers

A hill is refused, and nothing is written, when its item is missing, has no coordinates, or its
OSM feature sits more than MAX_FEATURE_OFFSET_M from the item. Downloads are cached under
data/raw/hills/ (gitignored) and reused unless --refresh.

Run from the repo root:
  python ml/scripts/build_hill_catalog.py --report   # verify and print, write nothing
  python ml/scripts/build_hill_catalog.py            # verify, then write the seeds
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import shutil
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import shapely
from pyproj import Transformer
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import linemerge, transform

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.ml.elevation import sample_elevations  # noqa: E402
from download_satellite_images import bbox_for, download, source_url  # noqa: E402

SEED_DIR = REPO_ROOT / "data" / "seed"
HILLS_JSON = SEED_DIR / "hills.json"
HILL_TRAILS_DIR = SEED_DIR / "hills"
SATELLITE_JSON = SEED_DIR / "satellite_images.json"
SOURCES_MD = SEED_DIR / "sources.md"
CACHE_DIR = REPO_ROOT / "data" / "raw" / "hills"
GLC_CSV = REPO_ROOT / "data" / "raw" / "coolr" / "global_landslide_catalog_export.csv"
SATELLITE_DIR = REPO_ROOT / "data" / "raw" / "satellite"

LIVE_SLUG = "turtle-mountain"  # the live hill keeps its row, trails, and satellite image as they are

USER_AGENT = "TerraSense-hill-catalog/1.0 (https://github.com/TCYTseven/TerraSense; ml/scripts/build_hill_catalog.py)"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
OVERPASS_URLS = (  # the main instance first; the mirrors only when it fails
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
)
OVERPASS_WORKERS = 2  # two queries in flight, well under any instance's per-client limit

# OSM landforms a hill or cliff can be mapped as.
LANDFORMS = ("peak", "hill", "volcano", "cliff", "ridge", "rock", "bare_rock", "plateau", "arete")
FEATURE_SEARCH_M = 5000       # look this far from the Wikidata point for the item's tagged OSM feature
MAX_FEATURE_OFFSET_M = 3000   # a matched feature further than this is a different place
CATALOG_CLEARANCE_M = 5000    # a catalog mountain closer than this already marks the place; the hill is refused
PATH_RADIUS_M = 1500          # a path counts when it passes this close to the summit
CLIP_RADIUS_M = 2500          # and is cut to this circle, so a long-distance route stays local
MIN_PATH_M = 250              # shorter named bits are street names on steps, not walks
MAX_PATHS = 12                # per hill, closest to the summit first
DUPLICATE_M = 20              # a line within this of a kept line for most of its length is the same path
DUPLICATE_SHARE = 0.8         # e.g. a way and the route relation over it, or four routes on one coast path
TOP_SEARCH_M = 400            # with no OSM summit, the marker moves to the highest ground this close
TOP_STEP_M = 40
SAMPLE_STEP_M = 25            # elevation profile spacing along a path
SIMPLIFY_M = 3                # Douglas-Peucker tolerance for the seed lines
COORD_DECIMALS = 5            # about 1 m, the same as the existing hill files
WALKABLE = "^(path|footway|track|bridleway|steps)$"
ROUTES = "^(hiking|foot|walking)$"

# Wikidata classes ("instance of", P31) that make an item a hill or cliff. An item typed as
# anything else (a quarter, a fortress, a building, a pass, a gorge) is refused; an untyped
# item passes only when its OSM feature is a landform.
LANDFORM_TYPES = {  # each QID checked against its Wikidata label
    "Q54050": "hill", "Q8502": "mountain", "Q107679": "cliff", "Q8072": "volcano",
    "Q169358": "stratovolcano", "Q212057": "shield volcano", "Q1197120": "extinct volcano",
    "Q1330974": "active volcano", "Q75520": "plateau", "Q207326": "summit", "Q1061151": "massif",
    "Q740445": "mountain ridge", "Q1595289": "sacred mountain",
}

GLC_RADIUS_KM = 10
# data/AGENTS.md: the static color is the catalog's recorded fatalities within 10 km.
RISK_BINS = ((100, "extreme"), (20, "high"), (1, "moderate"), (0, "low"))
# A hill with no written record takes its record from catalog events this close to the point,
# placed to 5 km or better; the sentence gives the distance and the accuracy. Snow avalanches
# and riverbank collapses are not slope failures.
RECORD_RADIUS_KM = 5
RECORD_ACCURACY = {"exact": "exactly", "1km": "to 1 km", "5km": "to 5 km"}
RECORD_SKIP = ("snow_avalanche", "riverbank_collapse")
# Catalog rows whose fatality count contradicts their own description, by event_id.
GLC_FATALITY_FIXES = {
    "4460": 0,  # Charmouth, 14 July 2012: lists 2 dead, but the text says the trapped boy was rescued
}

SATELLITE_RADIUS_KM = 5       # the same 10 km square the other hill previews use
SATELLITE_PX = 512

OSM_SOURCE = "© OpenStreetMap contributors"
SOURCES_START = "<!-- hill-catalog:start -->"
SOURCES_END = "<!-- hill-catalog:end -->"


@dataclass(frozen=True)
class Hill:
    slug: str
    qid: str        # the Wikidata item this row is checked against
    name: str
    region: str
    record: str | None = None  # the landslide or rockfall history, one sentence; None writes it from the catalog
    source: str | None = None  # where the record comes from; None cites the catalog event
    point: tuple[float, float] | None = None  # (lat, lon) for an item without coordinates, from its article


# Grouped by region, with a bias to Europe, the Middle East, Africa, Central and South America,
# and Southeast Asia. A hill with a written record cites where it was checked. A hill without
# one takes its record from the NASA Global Landslide Catalog (catalog_record), so every
# sentence comes from a source, not from memory.
HILLS: tuple[Hill, ...] = (
    # Europe
    Hill("mam-tor", "Q6745232", "Mam Tor", "Derbyshire, England, United Kingdom",
         "Landslips on its east face give it the name Shivering Mountain; the A625 across them closed as a through road in 1979.",
         "https://en.wikipedia.org/wiki/Mam_Tor"),
    Hill("white-cliffs-of-dover", "Q754785", "White Cliffs of Dover", "Kent, England, United Kingdom",
         "The chalk face retreats 22–32 cm a year; large sections fell in 2001, on 15 March 2012, and in February 2020 and 2021.",
         "https://en.wikipedia.org/wiki/White_Cliffs_of_Dover"),
    Hill("beinn-luibhean", "Q41205", "Beinn Luibhean", "Argyll and Bute, Scotland, United Kingdom",
         "Debris flows off its slope repeatedly close the A83 at the Rest and Be Thankful; a debris-flow shelter was chosen in 2023 for the stretch below it.",
         "https://www.transport.gov.scot/projects/access-to-argyll-and-bute-a83/project-details/"),
    Hill("quiraing", "Q2385621", "Quiraing", "Isle of Skye, Scotland, United Kingdom",
         "Part of the Trotternish landslip that is still moving; the road across it needs repairs every year.",
         "https://www.rgs.org/schools/resources-for-schools/adventure-landscapes/a-walk-around-the-quiraing"),
    Hill("st-boniface-down", "Q7592680", "St Boniface Down", "Isle of Wight, England, United Kingdom",
         "A major landslip in the Bonchurch Landslips below it on 10 December 2023 destroyed or closed every path there, including the Devil's Chimney.",
         "https://en.wikipedia.org/wiki/Devil%27s_Chimney_(Isle_of_Wight)"),
    Hill("mynydd-merthyr", "Q6947865", "Mynydd Merthyr", "Merthyr Tydfil, Wales, United Kingdom",
         "A colliery spoil tip on its slope slid onto Aberfan on 21 October 1966, killing 144 people, 116 of them children.",
         "https://en.wikipedia.org/wiki/Aberfan_disaster"),
    Hill("monte-toc", "Q2457847", "Monte Toc", "Erto e Casso, Friuli-Venezia Giulia, Italy",
         "Its north slope slid into the Vajont reservoir on 9 October 1963; the wave it raised killed about 2,000 people.",
         "https://en.wikipedia.org/wiki/Vajont_Dam"),
    Hill("monte-san-martino-lecco", "Q3861962", "Monte San Martino", "Lecco, Lombardy, Italy",
         "About 15,000 m³ of rock fell from it onto a house in Lecco on the night of 22–23 February 1969, killing seven; locals call it the monte marcio, the rotten mountain.",
         "https://www.leccotoday.it/cronaca/frana-san-martino-1969.html"),
    Hill("mount-epomeo", "Q729764", "Mount Epomeo", "Ischia, Campania, Italy",
         "A debris flow off its slope buried part of Casamicciola Terme on 26 November 2022, killing 12.",
         "https://en.wikipedia.org/wiki/2022_Ischia_landslide"),
    Hill("monte-pellegrino", "Q731916", "Monte Pellegrino", "Palermo, Sicily, Italy",
         "Boulders from its Addaura face struck a house on 31 December 2014 and six homes were evacuated; rockfall works on that face followed.",
         "http://palermo.gds.it/2014/12/31/maltempo-crollati-massi-da-monte-pellegrino-chiusa-strada-alladdaura_288263/"),
    Hill("mont-granier", "Q938010", "Mont Granier", "Chartreuse, Savoie, France",
         "Its north face collapsed on the night of 24–25 November 1248, destroying five villages and killing more than a thousand people.",
         "https://en.wikipedia.org/wiki/Mont_Granier"),
    Hill("montserrat", "Q732115", "Montserrat", "Barcelona, Catalonia, Spain",
         "Rockfall off its conglomerate walls is monitored because it threatens the monastery, roads, and rack railway; a rockfall in April 2026 killed two climbers.",
         "https://www.researchgate.net/publication/312420220 https://www.theolivepress.es/spain-news/2026/04/17/second-climber-dies-after-rockfall-while-scaling-scenic-mountain-range-near-barcelona/"),
    Hill("gnipen", "Q22352349", "Gnipen", "Rossberg, Canton of Schwyz, Switzerland",
         "The Goldau landslide broke away below it on 2 September 1806, nearly destroying Goldau and Röthen and killing 457.",
         "https://de.wikipedia.org/wiki/Gnipen https://en.wikipedia.org/wiki/Goldau_landslide"),
    Hill("pizzo-cengalo", "Q2574854", "Pizzo Cengalo", "Bregaglia, Graubünden, Switzerland",
         "About 3 million m³ broke from its east face on 23 August 2017, killing eight hikers in Val Bondasca; the debris flow reached Bondo 6.5 km away.",
         "https://nhess.copernicus.org/articles/20/505/2020/"),
    Hill("kleines-nesthorn", "Q22543586", "Kleines Nesthorn", "Lötschental, Valais, Switzerland",
         "Rockfall from its flank overloaded the Birch Glacier, which collapsed on 28 May 2025 and buried most of Blatten.",
         "https://www.nature.com/articles/s43247-025-02994-8"),
    Hill("mannen", "Q11988056", "Mannen", "Romsdalen, Møre og Romsdal, Norway",
         "One of Norway's continuously monitored high-risk rock slopes; its 54,000 m³ Veslemannen block failed on 5 September 2019 after five years of radar monitoring.",
         "https://ui.adsabs.harvard.edu/abs/2021Lands..18.1963K/abstract"),
    Hill("ramnefjellet", "Q11241308", "Ramnefjellet", "Loen, Stryn, Vestland, Norway",
         "Rockslides from it into Lovatnet raised waves that killed 61 people on 15 January 1905 and 74 in 1936.",
         "https://www.frontiersin.org/journals/earth-science/articles/10.3389/feart.2021.671378/full"),
    # Africa
    Hill("sugar-loaf-freetown", "Q31267133", "Sugar Loaf", "Western Area, Sierra Leone",
         "Its slope failed above Regent on 14 August 2017; the mudflow killed more than 1,000 people.",
         "https://en.wikipedia.org/wiki/2017_Sierra_Leone_mudslides"),
    Hill("soche-hill", "Q27765901", "Soche Hill", "Blantyre, Malawi",
         "Cyclone Freddy's floods and landslides tore down it in March 2023, rolling boulders onto homes and killing about a hundred people.",
         "https://mwnation.com/shaky-rocks-over-soche-hill/"),
    Hill("zomba-plateau", "Q8073720", "Zomba Plateau", "Southern Region, Malawi",
         "Rain in December 1946 set off debris flows on Zomba Mountain that killed 21 people and destroyed 24 bridges, buildings, and roads.",
         "https://www.researchgate.net/publication/251097459"),
    Hill("chapmans-peak", "Q501723", "Chapman's Peak", "Cape Town, South Africa",
         "Rockfalls off its face killed four people on Chapman's Peak Drive between 1998 and January 2000, when the road closed until 2003.",
         "https://www.chapmanspeakdrive.co.za/the-drive/history.html"),
    Hill("mount-hanang", "Q8535884", "Mount Hanang", "Manyara, Tanzania",
         "Debris flows off its slopes struck Katesh and Gendabi on 2–3 December 2023, killing at least 89.",
         "https://eos.org/thelandslideblog/mount-hanang"),
    # Central America
    Hill("volcan-de-agua", "Q1327687", "Volcán de Agua", "Sacatepéquez, Guatemala",
         "A lahar off it destroyed the capital, Santiago de los Caballeros (now Ciudad Vieja), on 11 September 1541; the capital moved to Antigua.",
         "https://en.wikipedia.org/wiki/Ciudad_Vieja"),
    Hill("san-salvador-volcano", "Q2577068", "San Salvador Volcano", "San Salvador, El Salvador",
         "A slide from El Picacho, its highest point, buried Colonia Montebello on 19 September 1982, killing an estimated 300 to 500 people.",
         "https://es.wikipedia.org/wiki/Deslave_en_la_colonia_Montebello"),
    Hill("casita-volcano", "Q2941145", "Casita Volcano", "Chinandega, Nicaragua",
         "Hurricane Mitch collapsed its flank on 30 October 1998; the lahar buried villages below Posoltega.",
         "https://es.wikipedia.org/wiki/Volc%C3%A1n_Casita"),
    Hill("ancon-hill", "Q3493016", "Ancón Hill", "Panama City, Panama"),
    # South America
    Hill("morro-da-oficina", "Q110974261", "Morro da Oficina", "Petrópolis, Rio de Janeiro, Brazil",
         "Its slope failed on 15 February 2022 and killed 93 people; the storm killed 235 across Petrópolis.",
         "https://theconversation.com/retroanalises-de-uma-tragedia-anunciada-estudo-explica-causas-do-deslizamento-do-morro-da-oficina-em-petropolis-267068"),
    Hill("monte-serrat-santos", "Q10332041", "Monte Serrat", "Santos, São Paulo, Brazil",
         "About 130,000 m³ slid off its east face onto the Santa Casa hospital on 10 March 1928, killing at least 80, the worst disaster in Santos.",
         "https://memoriasantista.com.br/em-1928-santos-viveu-a-dor-de-sua-maior-tragedia/"),
    Hill("corcovado", "Q506938", "Corcovado", "Rio de Janeiro, Brazil"),
    Hill("morro-dois-irmaos", "Q18476300", "Morro Dois Irmãos", "Rio de Janeiro, Brazil"),
    Hill("muela-del-diablo", "Q567893", "Muela del Diablo", "La Paz, Bolivia"),
    Hill("huayna-picchu", "Q845427", "Huayna Picchu", "Cusco, Peru"),
    Hill("cerro-pan-de-azucar-medellin", "Q18603203", "Cerro Pan de Azúcar", "Medellín, Antioquia, Colombia",
         "About 20,000 m³ broke from its southeast slope onto Villatina on 27 September 1987, killing about 500.",
         "https://es.wikipedia.org/wiki/Deslizamiento_de_Villatina",
         point=(6.24704722, -75.53529722)),  # the item has no coordinates; these are its eswiki article's
    Hill("monserrate", "Q152073", "Monserrate", "Bogotá, Colombia"),
    # Southeast Asia
    Hill("penang-hill", "Q1094967", "Penang Hill", "Penang, Malaysia"),
    Hill("mount-brinchang", "Q6919642", "Mount Brinchang", "Cameron Highlands, Pahang, Malaysia"),
    Hill("mount-mirador", "Q5679136", "Mount Mirador", "Baguio, Benguet, Philippines"),
    Hill("mount-santo-tomas", "Q6923475", "Mount Santo Tomas", "Tuba, Benguet, Philippines"),
    Hill("mayon-volcano", "Q1484", "Mayon Volcano", "Albay, Philippines",
         "Typhoon Durian's rain sent lahars down its slopes on 30 November 2006, wrecking six communities within 21 minutes; 604 people died in Albay.",
         "https://en.wikipedia.org/wiki/Typhoon_Durian"),
    Hill("mount-batur", "Q43876", "Mount Batur", "Bangli, Bali, Indonesia"),
    Hill("mount-salak", "Q669559", "Mount Salak", "Bogor, West Java, Indonesia"),
    # Found by searching Wikipedia (GeoSearch) for landforms within 3 km of catalog events, then
    # keeping items typed as landforms with a catalog event placed to 1 km within 3 km. Records
    # come from the catalog.
    # Europe
    Hill("monte-brugiana", "Q65127990", "Monte Brugiana", "Massa, Tuscany, Italy"),
    Hill("monte-lema", "Q674610", "Monte Lema", "Ticino, Switzerland"),
    Hill("monte-boglia", "Q870031", "Monte Boglia", "Lugano, Ticino, Switzerland"),
    Hill("testa-malinvern", "Q3321936", "Testa Malinvern", "Alpes-Maritimes, France"),
    Hill("cima-belpra", "Q137518041", "Cima Belprà", "Belluno, Veneto, Italy"),
    Hill("monte-san-fratello", "Q3861955", "Monte San Fratello", "San Fratello, Sicily, Italy"),
    Hill("srd", "Q130591", "Srđ", "Dubrovnik, Croatia"),
    Hill("traunstein", "Q700658", "Traunstein", "Gmunden, Upper Austria, Austria"),
    Hill("illhorn", "Q568228", "Illhorn", "Leuk, Valais, Switzerland"),
    Hill("olivers-mount", "Q7087358", "Oliver's Mount", "Scarborough, North Yorkshire, England, United Kingdom"),
    Hill("hunt-cliff", "Q24658764", "Hunt Cliff", "Saltburn-by-the-Sea, North Yorkshire, England, United Kingdom"),
    Hill("furzy-cliff", "Q5509868", "Furzy Cliff", "Weymouth, Dorset, England, United Kingdom"),
    Hill("tennyson-down", "Q7700519", "Tennyson Down", "Isle of Wight, England, United Kingdom"),
    Hill("mynydd-allt-y-grug", "Q13130299", "Mynydd Allt-y-grug", "Ystalyfera, Neath Port Talbot, Wales, United Kingdom"),
    Hill("mount-brandon", "Q1478911", "Mount Brandon", "County Kerry, Ireland"),
    Hill("askja", "Q211665", "Askja", "Northeastern Region, Iceland"),
    # Middle East
    Hill("cerat-hill", "Q23585775", "Cerat Hill", "Artvin, Turkey"),
    Hill("boztepe-trabzon", "Q4952904", "Boztepe", "Trabzon, Turkey",
         "The catalog records a landslide in Trabzon on 21 November 2009 that killed 2, placed 1.8 km from the summit to within 5 km.",
         "NASA Global Landslide Catalog event 1321"),  # the catalog's place text is garbled, so it is not quoted
    # Central America and the Caribbean
    Hill("volcan-san-pedro", "Q1575468", "Volcán San Pedro", "Sololá, Guatemala"),
    Hill("san-vicente-volcano", "Q1072131", "San Vicente Volcano", "San Vicente, El Salvador"),
    Hill("san-miguel-volcano", "Q1062664", "San Miguel Volcano", "San Miguel, El Salvador"),
    Hill("concepcion-volcano", "Q1067452", "Concepción", "Ometepe, Rivas, Nicaragua"),
    Hill("irazu-volcano", "Q1672472", "Irazú Volcano", "Cartago, Costa Rica"),
    Hill("cerro-zurqui", "Q20824926", "Cerro Zurquí", "Heredia, Costa Rica"),
    Hill("morne-aux-diables", "Q12771972", "Morne aux Diables", "Saint John, Dominica"),
    Hill("chalky-mount", "Q5068861", "Chalky Mount", "Saint Andrew, Barbados"),
    # South America
    Hill("pikchu", "Q16898443", "Pikchu", "Cusco, Peru"),
    Hill("sugarloaf-mountain-rio", "Q210722", "Sugarloaf Mountain", "Rio de Janeiro, Brazil"),
    Hill("pedra-da-gavea", "Q2066357", "Pedra da Gávea", "Rio de Janeiro, Brazil"),
    Hill("cerro-manquehue", "Q5639198", "Cerro Manquehue", "Santiago, Chile"),
    # Southeast Asia
    Hill("mount-merapi", "Q134108", "Mount Merapi", "Central Java and Yogyakarta, Indonesia"),
    Hill("mount-bratan", "Q2003801", "Mount Bratan", "Bali, Indonesia"),
    Hill("larut-hill", "Q4253539", "Larut Hill", "Taiping, Perak, Malaysia"),
    Hill("khao-chang", "Q6400441", "Khao Chang", "Phang Nga, Thailand"),
    Hill("mount-banahaw", "Q806074", "Mount Banahaw", "Quezon, Philippines"),
    Hill("mount-pulong-bato", "Q8530983", "Mount Pulong Bato", "Zamboanga City, Philippines"),
)


def rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def ssl_context() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


SSL = ssl_context()


def fetch_json(url: str, data: bytes | None = None, timeout: int = 180) -> dict:
    request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout, context=SSL) as response:  # noqa: S310 - fixed HTTPS sources
        return json.load(response)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p = math.pi / 180
    a = math.sin((lat2 - lat1) * p / 2) ** 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2
    return 12_742_000 * math.asin(math.sqrt(a))


# Wikidata


def wikidata(qids: list[str], refresh: bool) -> dict[str, dict]:
    """Label, coordinates, elevation (m), and article count for each item. Cached."""
    path = CACHE_DIR / "wikidata.json"
    cached = json.loads(path.read_text(encoding="utf-8")) if path.exists() and not refresh else {}
    missing = [q for q in qids if q not in cached or "types" not in cached[q] and "missing" not in cached[q]]
    for start in range(0, len(missing), 40):
        batch = missing[start:start + 40]
        params = {"action": "wbgetentities", "ids": "|".join(batch), "props": "labels|claims|sitelinks", "format": "json"}
        for attempt in range(6):
            try:
                body = fetch_json(f"{WIKIDATA_API}?{urllib.parse.urlencode(params)}", timeout=60)
                if "error" in body:
                    raise RuntimeError(body["error"].get("info"))
                break
            except (urllib.error.URLError, RuntimeError, TimeoutError) as exc:
                if attempt == 5:
                    raise SystemExit(f"Wikidata did not answer for {batch}: {exc}")
                time.sleep(10 * (attempt + 1))
        for qid, entity in body["entities"].items():
            cached[qid] = parse_entity(entity)
        time.sleep(1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cached, ensure_ascii=False, indent=1), encoding="utf-8")
    return cached


def parse_entity(entity: dict) -> dict:
    if "missing" in entity:
        return {"missing": True}
    claims = entity.get("claims", {})
    coord = elevation = None
    for claim in claims.get("P625", []):
        value = claim["mainsnak"].get("datavalue", {}).get("value")
        if value:
            coord = [value["latitude"], value["longitude"]]
            break
    for claim in claims.get("P2044", []):
        value = claim["mainsnak"].get("datavalue", {}).get("value")
        if value and value.get("unit", "").endswith("/Q11573"):  # metre
            elevation = float(value["amount"])
            break
    labels = entity.get("labels", {})
    return {
        "labels": {lang: labels[lang]["value"] for lang in labels},
        "types": [c["mainsnak"]["datavalue"]["value"]["id"] for c in claims.get("P31", []) if "datavalue" in c["mainsnak"]],
        "coord": coord,
        "elevation_m": elevation,
        "articles": sorted(k for k in entity.get("sitelinks", {}) if k.endswith("wiki") and k != "commonswiki"),
    }


# OpenStreetMap


def overpass(query: str) -> dict:
    last: Exception | None = None
    for attempt in range(8):
        url = OVERPASS_URLS[attempt % len(OVERPASS_URLS)]
        try:
            body = fetch_json(url, urllib.parse.urlencode({"data": query}).encode(), timeout=240)
            if body.get("remark", "").lower().startswith(("runtime error", "error")):
                raise RuntimeError(body["remark"])
            return body
        except (urllib.error.URLError, RuntimeError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
            time.sleep(5 + 5 * attempt)
    raise SystemExit(f"no Overpass instance answered: {last}")


class NotCached(Exception):
    """With --cached-only, a hill whose OSM answers are not downloaded yet."""


CACHED_ONLY = False  # set by --cached-only: never query Overpass, skip hills it has not answered for


def cached_overpass(path: Path, query: str, refresh: bool) -> dict:
    """A cached answer is reused only for the same query, so a moved point fetches again."""
    if path.exists() and not refresh:
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:  # another run is still writing it
            body = {}
        if body.get("query") == query:
            return body
    if CACHED_ONLY:
        raise NotCached(path.parent.name)
    body = overpass(query)
    body["query"] = query
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return body


def fold(text: str) -> str:
    import unicodedata
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def osm_feature(hill: Hill, item: dict, refresh: bool) -> dict | None:
    """The OSM summit or cliff for this item: its wikidata tag first, else a landform of the same name.

    The tag lookup is quick; the name search scans every landform around the point and can
    take minutes, so it runs only for an item with no Wikidata type, whose OSM landform is
    what makes it a hill, and only as far out as a match could be kept. A typed item with no
    tagged feature keeps its Wikidata point, moved to the highest ground near it."""
    lat, lon = item["coord"] or hill.point
    tagged = f"""[out:json][timeout:120];
nwr(around:{FEATURE_SEARCH_M},{lat},{lon})["wikidata"="{hill.qid}"];
out tags center;"""
    elements = cached_overpass(CACHE_DIR / hill.slug / "osm_feature.json", tagged, refresh)["elements"]
    if not item["types"] and not any(e.get("tags", {}).get("natural") in LANDFORMS for e in elements):
        named = f"""[out:json][timeout:240];
nwr(around:{MAX_FEATURE_OFFSET_M},{lat},{lon})["natural"~"^({'|'.join(LANDFORMS)})$"]["name"];
out tags center;"""
        elements = elements + cached_overpass(CACHE_DIR / hill.slug / "osm_feature_named.json", named, refresh)["elements"]
    names = {fold(n) for n in [hill.name, *item["labels"].values()] if fold(n)}
    best = None
    for element in elements:
        tags = element.get("tags", {})
        where = element.get("center") or {"lat": element.get("lat"), "lon": element.get("lon")}
        if where.get("lat") is None:
            continue
        landform = tags.get("natural") in LANDFORMS
        if tags.get("wikidata") == hill.qid:
            rank = 0 if landform else 2
        elif landform and fold(tags.get("name", "")) in names:
            rank = 1
        else:
            continue
        offset = haversine_m(lat, lon, where["lat"], where["lon"])
        key = (rank, element["type"] != "node", offset)
        if best is None or key < best[0]:
            best = (key, {"type": element["type"], "id": element["id"], "tags": tags,
                          "lat": where["lat"], "lon": where["lon"], "offset_m": round(offset)})
    return best[1] if best else None


def osm_paths(hill: Hill, lat: float, lon: float, refresh: bool) -> dict:
    """Named ways, then each walking route followed by only its member ways near the hill.

    A long-distance route such as the E9 is hundreds of kilometres long, so its whole
    geometry is never fetched."""
    query = f"""[out:json][timeout:240];
way(around:{PATH_RADIUS_M},{lat},{lon})["highway"~"{WALKABLE}"]["name"];
out tags geom;
relation(around:{PATH_RADIUS_M},{lat},{lon})["route"~"{ROUTES}"]["name"];
foreach->.route(
  .route out tags;
  way(r.route)(around:{CLIP_RADIUS_M},{lat},{lon});
  out tags geom;
);"""
    return cached_overpass(CACHE_DIR / hill.slug / "osm_paths.json", query, refresh)


# Paths


def utm_for(lat: float, lon: float) -> tuple[Transformer, Transformer]:
    zone = min(60, max(1, int((lon + 180) // 6) + 1))
    crs = f"EPSG:{(32600 if lat >= 0 else 32700) + zone}"
    return (Transformer.from_crs("EPSG:4326", crs, always_xy=True),
            Transformer.from_crs(crs, "EPSG:4326", always_xy=True))


def display_name(tags: dict) -> str:
    """The English name when OSM has one (the app is in English), else the local name."""
    return (tags.get("name:en") or tags.get("name") or "").strip()


def named_lines(body: dict) -> dict[str, list[LineString]]:
    """Lon/lat pieces per name: a way under its own name, a route's member ways under the route's.

    osm_paths lists the named ways first, then each route followed by its ways, so a way
    belongs to the route printed before it. Tunnels and private ways are not walks."""
    lines: dict[str, list[LineString]] = {}
    route = None
    for element in body["elements"]:
        tags = element.get("tags", {})
        if element["type"] == "relation":
            route = display_name(tags)
            continue
        if element["type"] != "way" or tags.get("tunnel", "no") != "no" or tags.get("access") in ("no", "private"):
            continue
        name = route if route is not None else display_name(tags)
        coords = [(p["lon"], p["lat"]) for p in element.get("geometry", []) if p]
        if name and len(coords) >= 2:
            lines.setdefault(name, []).append(LineString(coords))
    return lines


def longest_local_line(pieces: list[LineString], to_utm, summit_utm: Point) -> LineString | None:
    """Join the pieces, cut to the clip circle, and keep the longest connected run (UTM)."""
    merged = linemerge(MultiLineString([transform(to_utm.transform, p) for p in pieces]))
    clipped = merged.intersection(summit_utm.buffer(CLIP_RADIUS_M, 64))
    parts = [g for g in getattr(clipped, "geoms", [clipped]) if isinstance(g, LineString) and not g.is_empty]
    if not parts:
        return None
    joined = linemerge(MultiLineString(parts)) if len(parts) > 1 else parts[0]
    parts = [g for g in getattr(joined, "geoms", [joined]) if isinstance(g, LineString)]
    return max(parts, key=lambda g: g.length)


def profile(line_utm: LineString, to_lonlat) -> list[float] | None:
    steps = max(2, int(line_utm.length // SAMPLE_STEP_M) + 1)
    points = [line_utm.interpolate(i / (steps - 1), normalized=True) for i in range(steps)]
    return sample_elevations([to_lonlat.transform(p.x, p.y) for p in points])


def trail_features(hill: Hill, lat: float, lon: float, body: dict) -> list[dict]:
    to_utm, to_lonlat = utm_for(lat, lon)
    summit = Point(to_utm.transform(lon, lat))
    candidates = []
    for name, pieces in named_lines(body).items():
        line = longest_local_line(pieces, to_utm, summit)
        if line is None or line.length < MIN_PATH_M or line.distance(summit) > PATH_RADIUS_M:
            continue
        candidates.append((line.distance(summit), -line.length, name, line))
    candidates.sort()
    kept: list[tuple[str, LineString]] = []
    for _, _, name, line in candidates:
        if len(kept) == MAX_PATHS:
            break
        if not any(line.intersection(other.buffer(DUPLICATE_M)).length >= DUPLICATE_SHARE * line.length for _, other in kept):
            kept.append((name, line))
    features = []
    for name, line in kept:
        heights = profile(line, to_lonlat)
        gain = None
        if heights is not None:
            if heights[0] > heights[-1]:  # a line starts at its lower end
                line, heights = shapely.reverse(line), heights[::-1]
            gain = round(sum(max(0.0, b - a) for a, b in zip(heights, heights[1:])))
        simple = transform(to_lonlat.transform, shapely.simplify(line, SIMPLIFY_M))
        coords: list[list[float]] = []
        for x, y in simple.coords:
            point = [round(x, COORD_DECIMALS), round(y, COORD_DECIMALS)]
            if not coords or coords[-1] != point:
                coords.append(point)
        if len(coords) < 2:
            continue
        features.append({
            "type": "Feature",
            "properties": {
                "mountain_slug": hill.slug,
                "name": name,
                "length_km": round(line.length / 1000, 2),
                "elevation_gain_m": gain,
                "source": OSM_SOURCE,
            },
            "geometry": {"type": "LineString", "coordinates": coords},
        })
    return features


# NASA Global Landslide Catalog


def glc_events() -> list[dict]:
    if not GLC_CSV.exists():
        raise SystemExit(f"{rel(GLC_CSV)} is missing. Download it as data/seed/sources.md describes.")
    events = []
    with GLC_CSV.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            try:
                lat, lon = float(row["latitude"]), float(row["longitude"])
            except ValueError:
                continue
            fatalities = GLC_FATALITY_FIXES.get(row["event_id"], int(float(row["fatality_count"] or 0)))
            month, day, year = row["event_date"][:10].split("/")  # MM/DD/YYYY
            events.append({"lat": lat, "lon": lon, "fatalities": fatalities, "id": row["event_id"],
                           "date": f"{year}-{month}-{day}", "title": row["event_title"].strip(),
                           "place": (row["location_description"] or row["event_title"]).strip().rstrip(", "),
                           "accuracy": row["location_accuracy"], "category": row["landslide_category"],
                           "link": row["source_link"].strip()})
    return events


def glc_near(events: list[dict], lat: float, lon: float) -> list[dict]:
    near = []
    for event in events:
        if abs(event["lat"] - lat) > 0.2 or abs(event["lon"] - lon) > 0.3:
            continue
        km = haversine_m(lat, lon, event["lat"], event["lon"]) / 1000
        if km <= GLC_RADIUS_KM:
            near.append({**event, "km": round(km, 1)})
    return sorted(near, key=lambda e: (-e["fatalities"], e["km"]))


def risk_level(fatalities: int) -> str:
    return next(level for floor, level in RISK_BINS if fatalities >= floor)


CATEGORY_WORDS = {"rock_fall": "rockfall", "debris_flow": "debris flow", "earth_flow": "earth flow",
                  "translational_slide": "translational slide", "mudslide": "mudslide", "lahar": "lahar",
                  "topple": "rock topple", "complex": "landslide", "creep": "slow landslide"}
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December")


def catalog_record(near: list[dict]) -> tuple[str, str] | None:
    """One sentence and its source from the deadliest well-placed catalog event near the hill."""
    close = [e for e in near if e["km"] <= RECORD_RADIUS_KM and e["accuracy"] in RECORD_ACCURACY
             and e["category"] not in RECORD_SKIP]
    if not close:
        return None
    event = close[0]  # glc_near sorts by fatalities, then distance
    year, month, day = event["date"].split("-")
    when = f"{int(day)} {MONTHS[int(month) - 1]} {year}"
    what = CATEGORY_WORDS.get(event["category"], "landslide")
    toll = f", killing {event['fatalities']}" if event["fatalities"] else ""
    others = len(close) - 1
    more = f" It lists {others} more within {RECORD_RADIUS_KM} km." if others else ""
    sentence = (f"The catalog records a {what} at {event['place']} on {when}{toll}, "
                f"{event['km']} km from the summit (placed {RECORD_ACCURACY[event['accuracy']]}).{more}")
    source = f"NASA Global Landslide Catalog event {event['id']}"
    return sentence, (f"{source}, {event['link']}" if event["link"].startswith("http") else source)


def landform_type(item: dict, feature: dict | None) -> str | None:
    """What makes this a hill: its Wikidata type, or for an untyped item its OSM landform."""
    for qid in item["types"]:
        if qid in LANDFORM_TYPES:
            return LANDFORM_TYPES[qid]
    if not item["types"] and feature and feature["tags"].get("natural") in LANDFORMS:
        return f"OSM natural={feature['tags']['natural']}"
    return None


# Build


class Refused(Exception):
    """A hill that failed a check. The run lists every refusal and writes nothing."""


def highest_near(lat: float, lon: float) -> tuple[float, float] | None:
    """The highest Terrarium point on a grid within TOP_SEARCH_M: a cliff's top, not its foot.

    Wikidata often places a cliff or a hill mass at a rounded centroid, which can sit on the
    slope below; OSM summits are used as they are."""
    to_utm, to_lonlat = utm_for(lat, lon)
    x0, y0 = to_utm.transform(lon, lat)
    steps = range(-TOP_SEARCH_M, TOP_SEARCH_M + 1, TOP_STEP_M)
    grid = [(x0 + dx, y0 + dy) for dx in steps for dy in steps if dx * dx + dy * dy <= TOP_SEARCH_M ** 2]
    points = [to_lonlat.transform(x, y) for x, y in grid]
    heights = sample_elevations(points)
    if heights is None:
        return None
    best = max(range(len(points)), key=heights.__getitem__)
    return points[best][1], points[best][0]


def build_one(hill: Hill, item: dict, events: list[dict], refresh: bool) -> dict:
    if item.get("missing") or not (item.get("coord") or hill.point):
        raise Refused(f"{hill.slug}: Wikidata {hill.qid} is missing or has no coordinates")
    feature = osm_feature(hill, item, refresh)
    if feature and feature["offset_m"] > MAX_FEATURE_OFFSET_M:  # measured from the item, or the registry point
        raise Refused(f"{hill.slug}: OSM {feature['type']} {feature['id']} is {feature['offset_m']} m from {hill.qid}")
    landform = landform_type(item, feature)
    if landform is None:
        raise Refused(f"{hill.slug}: Wikidata {hill.qid} is typed {item['types']}, not a hill or cliff")
    if feature and feature["type"] == "node" and feature["tags"].get("natural") in ("peak", "hill", "volcano"):
        lat, lon, where = feature["lat"], feature["lon"], "osm"
    else:
        (lat, lon), where = item["coord"] or hill.point, "wikidata" if item["coord"] else "the registry"
        top = highest_near(lat, lon)
        if top is not None:
            lat, lon, where = *top, f"the highest ground within {TOP_SEARCH_M} m of the {where} point"
    dem = sample_elevations([(lon, lat)])
    osm_ele = None
    if feature:
        match = re.match(r"^\s*(-?\d+(?:\.\d+)?)", feature["tags"].get("ele", ""))
        osm_ele = float(match.group(1)) if match else None
    elevation = item["elevation_m"] if item["elevation_m"] is not None else osm_ele
    elevation_source = "wikidata" if item["elevation_m"] is not None else "osm" if osm_ele is not None else "terrarium"
    if elevation is None:
        elevation = dem[0] if dem else None
    if elevation is None:
        raise Refused(f"{hill.slug}: no elevation from Wikidata, OSM, or the Terrarium tiles")
    trails = trail_features(hill, lat, lon, osm_paths(hill, lat, lon, refresh))
    near = glc_near(events, lat, lon)
    fatalities = sum(e["fatalities"] for e in near)
    record, source = hill.record, hill.source
    if record is None:
        written = catalog_record(near)
        if written is None:
            raise Refused(f"{hill.slug}: no written record and no catalog event within {RECORD_RADIUS_KM} km")
        record, source = written
    return {
        "hill": hill, "item": item, "feature": feature, "lat": lat, "lon": lon, "where": where,
        "landform": landform, "record": record, "source": source,
        "elevation_m": round(elevation), "elevation_source": elevation_source,
        "dem_m": round(dem[0]) if dem else None, "trails": trails, "glc": near, "fatalities": fatalities,
        "risk": risk_level(fatalities),
    }


def row_for(result: dict) -> dict:
    hill = result["hill"]
    return {
        "name": hill.name, "slug": hill.slug,
        "lat": round(result["lat"], 5), "lon": round(result["lon"], 5),
        "elevation_m": result["elevation_m"], "region": hill.region,
        "current_risk_level": result["risk"], "is_live": False, "kind": "hill",
    }


def satellite_row(hill: Hill, lat: float, lon: float, fetch: bool) -> dict:
    bbox = bbox_for(lat, lon, SATELLITE_RADIUS_KM)
    url = source_url(bbox, SATELLITE_PX)
    path = SATELLITE_DIR / f"{hill.slug}.jpg"
    status, error = "downloaded", None
    if fetch and not path.exists():
        try:
            download(url, path)
        except RuntimeError as exc:
            status, error = "error", str(exc)
    elif not path.exists():
        status, error = "pending", "not downloaded on this machine"
    return {
        "mountain_slug": hill.slug, "mountain_name": hill.name, "image_url": url,
        "file_path": rel(path), "file_ext": "jpg", "source": "Esri World Imagery",
        "download_status": status, "bbox": [round(v, 7) for v in bbox], "image_size_px": SATELLITE_PX,
        "error": error,
    }


def report(result: dict) -> str:
    hill, feature, item = result["hill"], result["feature"], result["item"]
    osm = (f"{feature['type']}/{feature['id']} {feature['tags'].get('natural', '-')} "
           f"'{feature['tags'].get('name', '')}' {feature['offset_m']} m from item") if feature else "no OSM feature"
    climbs = [t for t in result["trails"] if (t["properties"]["elevation_gain_m"] or 0) >= 40]
    lines = [
        f"{hill.slug}  {hill.name} ({hill.qid}, {result['landform']}, {len(item['articles'])} Wikipedias)",
        f"  record: {result['record']} [{result['source']}]",
        f"  point {result['lat']:.5f},{result['lon']:.5f} from {result['where']}; {osm}",
        f"  elevation {result['elevation_m']} m from {result['elevation_source']} (terrain tile {result['dem_m']} m)",
        f"  {len(result['trails'])} named paths, {len(climbs)} climbing 40 m or more: "
        + "; ".join(f"{t['properties']['name']} {t['properties']['length_km']} km +{t['properties']['elevation_gain_m']} m" for t in result["trails"][:6]),
        f"  catalog: {len(result['glc'])} events within {GLC_RADIUS_KM} km, {result['fatalities']} dead -> {result['risk']}"
        + ("; " + "; ".join(f"{e['date']} {e['title'][:50]} ({e['fatalities']} dead, {e['km']} km)" for e in result["glc"][:2]) if result["glc"] else ""),
    ]
    return "\n".join(lines)


def sources_table(results: list[dict]) -> str:
    lines = [
        SOURCES_START,
        "",
        "Written by `python ml/scripts/build_hill_catalog.py`. Each row is pinned to a Wikidata item and checked against the matching OpenStreetMap summit or cliff. The catalog column counts NASA Global Landslide Catalog events within 10 km of the point and the fatalities they record, which set the marker color. Paths are named OpenStreetMap ways and walking-route relations within 1.5 km of the point, cut to 2.5 km.",
        "",
        "| Hill | Wikidata | OSM feature | Elevation | Named paths | Catalog within 10 km | Landslide record |",
        "|---|---|---|---|---|---|---|",
    ]
    for result in results:
        hill, feature = result["hill"], result["feature"]
        osm = f"[{feature['type']}/{feature['id']}](https://www.openstreetmap.org/{feature['type']}/{feature['id']})" if feature else "none"
        source = re.sub(r"(https?://\S+)", r"[source](\1)", result["source"])
        lines.append(
            f"| {hill.name} (`{hill.slug}`) | [{hill.qid}](https://www.wikidata.org/wiki/{hill.qid}) | {osm} "
            f"| {result['elevation_m']} m ({result['elevation_source']}) | {len(result['trails'])} "
            f"| {len(result['glc'])} events, {result['fatalities']} dead, `{result['risk']}` | {result['record']} {source} |"
        )
    lines += ["", SOURCES_END]
    return "\n".join(lines)


def write_outputs(results: list[dict], fetch_images: bool) -> None:
    rows = json.loads(HILLS_JSON.read_text(encoding="utf-8"))
    live = [row for row in rows if row["slug"] == LIVE_SLUG]
    if not live:
        raise SystemExit(f"{rel(HILLS_JSON)} has no {LIVE_SLUG} row to carry over")
    new_rows = live + [row_for(r) for r in results]
    HILLS_JSON.write_text(json.dumps(new_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {rel(HILLS_JSON)}: {len(new_rows)} hills")

    keep = {LIVE_SLUG}
    for result in results:
        slug = result["hill"].slug
        folder = HILL_TRAILS_DIR / slug
        if result["trails"]:
            folder.mkdir(parents=True, exist_ok=True)
            collection = {"type": "FeatureCollection", "attribution": OSM_SOURCE, "license": "ODbL-1.0",
                          "source": "https://www.openstreetmap.org/copyright", "features": result["trails"]}
            (folder / "trails.geojson").write_text(json.dumps(collection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            keep.add(slug)
        elif folder.exists():
            shutil.rmtree(folder)
    for folder in sorted(HILL_TRAILS_DIR.iterdir()):
        if folder.is_dir() and folder.name not in keep:
            shutil.rmtree(folder)
            print(f"removed {rel(folder)}")

    old_slugs = {row["slug"] for row in rows}
    images = json.loads(SATELLITE_JSON.read_text(encoding="utf-8"))
    kept = [row for row in images if row["mountain_slug"] == LIVE_SLUG or row["mountain_slug"] not in old_slugs]
    kept += [satellite_row(r["hill"], r["lat"], r["lon"], fetch_images) for r in results]
    SATELLITE_JSON.write_text(json.dumps(kept, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {rel(SATELLITE_JSON)}: {len(kept)} rows")

    text = SOURCES_MD.read_text(encoding="utf-8")
    if SOURCES_START not in text or SOURCES_END not in text:
        raise SystemExit(f"{rel(SOURCES_MD)} needs the {SOURCES_START} and {SOURCES_END} markers")
    head, rest = text.split(SOURCES_START, 1)
    tail = rest.split(SOURCES_END, 1)[1]
    SOURCES_MD.write_text(head + sources_table(results) + tail, encoding="utf-8")
    print(f"wrote the hill table in {rel(SOURCES_MD)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--report", action="store_true", help="verify and print, write nothing")
    parser.add_argument("--refresh", action="store_true", help="re-download Wikidata and OSM instead of using data/raw/hills/")
    parser.add_argument("--no-images", action="store_true", help="do not download the satellite previews")
    parser.add_argument("--only", help="comma-separated slugs, for a quick look with --report")
    parser.add_argument("--cached-only", action="store_true",
                        help="use only downloaded OSM answers; write the hills they verify and leave out "
                             "the refused and the not yet downloaded, listing both")
    args = parser.parse_args()
    global CACHED_ONLY
    CACHED_ONLY = args.cached_only

    hills = [h for h in HILLS if not args.only or h.slug in args.only.split(",")]
    slugs = [h.slug for h in HILLS]
    if len(set(slugs)) != len(slugs) or LIVE_SLUG in slugs:
        raise SystemExit("hill slugs must be unique and must not include the live hill")
    catalog: dict[str, tuple[float, float]] = {}
    for name in ("mountains.json", "mountains_test.json"):
        path = SEED_DIR / name
        if path.exists():
            catalog |= {row["slug"]: (row["lat"], row["lon"]) for row in json.loads(path.read_text(encoding="utf-8"))}
    if clash := set(catalog) & set(slugs):
        raise SystemExit(f"hill slugs already used by the mountain catalog: {sorted(clash)}")
    if args.only and not args.report:
        raise SystemExit("--only is for --report; a write needs every hill")

    items = wikidata([h.qid for h in hills], args.refresh)
    events = glc_events()
    with ThreadPoolExecutor(max_workers=OVERPASS_WORKERS) as pool:
        futures = [pool.submit(build_one, h, items[h.qid], events, args.refresh) for h in hills]
        outcomes = []
        for future in futures:
            try:
                outcomes.append(future.result())
            except (Refused, NotCached) as exc:
                outcomes.append(exc)
    refused = [str(o) for o in outcomes if isinstance(o, Refused)]
    pending = [str(o) for o in outcomes if isinstance(o, NotCached)]
    results = [o for o in outcomes if isinstance(o, dict)]
    for result in list(results):
        clash = [slug for slug, (lat, lon) in catalog.items()
                 if haversine_m(result["lat"], result["lon"], lat, lon) < CATALOG_CLEARANCE_M]
        if clash:
            results.remove(result)
            refused.append(f"{result['hill'].slug}: catalog mountain {clash[0]} is within {CATALOG_CLEARANCE_M} m; "
                           "the globe already has a marker there")
            continue
        print(report(result), flush=True)
    bare = [r["hill"].slug for r in results if not r["trails"]]
    print(f"\n{len(results)} hills verified; {len(results) - len(bare)} with named paths"
          + (f"; none for {', '.join(bare)}" if bare else ""))
    if pending:
        print(f"\n{len(pending)} not downloaded yet, left out: {', '.join(pending)}")
    if refused:
        print(f"\n{len(refused)} refused:\n  " + "\n  ".join(refused))
        if not args.report and not args.cached_only:
            raise SystemExit("nothing written: drop or fix the refused hills first")
    if not args.report:
        write_outputs(results, fetch_images=not args.no_images)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
