"""
Ireland Deprivation Time Slider — 2006 / 2011 / 2016 / 2022
=============================================================
Downloads Pobal HP Deprivation Index for all four waves, joins to 2022 CSO
Electoral Division boundaries (generalised 20m), and generates a self-contained
HTML file with:
  • Choropleth updating on each time step
  • Play/Pause button animating through the four waves
  • Distinct highlight for EDs persistently deprived across all four waves
  • Fixed service markers (Dec 2025)
Output: outputs/timeslider.html
"""

import os, re, json, math, warnings
import urllib.request
import numpy as np
import pandas as pd
import geopandas as gpd

warnings.filterwarnings("ignore")

OUTPUTS = "docs"
CACHE   = "cache"
os.makedirs(OUTPUTS, exist_ok=True)
os.makedirs(CACHE,   exist_ok=True)

# ── Data URLs ──────────────────────────────────────────────────────────────────
HIST_CSV_URL = (
    "https://www.pobal.ie/app/uploads/2021/01/"
    "HP-Index-2006-2016-HP-Index-Scores-by-ID06b2.csv"
)
POBAL_2022_URL = (
    "https://www.pobal.ie/wp-content/uploads/2024/01/"
    "hp-deprivation-index-scores-2022.csv"
)
ED_GEN20_URL = (
    "https://data-osi.opendata.arcgis.com/api/download/v1/items/"
    "ed3d7b317e244a32b8eeba4d2bd9b9df/geojson?layers=5"
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def fetch(url, dest, desc=""):
    if os.path.exists(dest):
        print(f"  Cached: {dest}")
        return
    print(f"  Downloading {desc} …")
    req = urllib.request.Request(url, headers={"User-Agent": "IrelandResearch/1.0"})
    with urllib.request.urlopen(req, timeout=180) as r:
        data = r.read()
    with open(dest, "wb") as f:
        f.write(data)
    print(f"  Saved {len(data)/1e6:.1f} MB → {dest}")


def norm_name(s):
    s = str(s).upper().strip()
    s = re.sub(r"[^A-Z0-9/ ]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


# ── Step 1: Load deprivation data for all four years ─────────────────────────

def load_all_deprivation():
    # ── Historical 2006 / 2011 / 2016 ─────────────────────────────────────────
    hist_path = os.path.join(CACHE, "pobal_hist_2006_2016.csv")
    fetch(HIST_CSV_URL, hist_path, "Pobal HP 2006/2011/2016")
    hist = pd.read_csv(hist_path, encoding="latin-1")
    hist["name_norm"] = hist["ED_Name"].apply(norm_name)
    # HP*rel columns: relative weight score, more negative = more deprived
    hist = hist[["name_norm", "HP2006rel", "HP2011rel", "HP2016rel"]].copy()
    hist.columns = ["name_norm", "score_2006", "score_2011", "score_2016"]
    for c in ["score_2006", "score_2011", "score_2016"]:
        hist[c] = pd.to_numeric(hist[c], errors="coerce")

    # ── 2022 ──────────────────────────────────────────────────────────────────
    pobal22_path = os.path.join(CACHE, "pobal_2022.csv")
    fetch(POBAL_2022_URL, pobal22_path, "Pobal HP 2022")
    dep22 = pd.read_csv(pobal22_path, encoding="latin-1", dtype={"ED_ID_STR": str})

    def pad_id(x):
        x = str(x).strip()
        return x.zfill(6) if "/" not in x and len(x) < 6 else x

    dep22["ED_ID_STR"] = dep22["ED_ID_STR"].apply(pad_id)
    dep22["name_norm"] = dep22["ED_ENGLISH"].apply(norm_name)
    dep22 = dep22[["ED_ID_STR", "name_norm", "Index22_ED_std_rel_wt",
                    "TOTPOP22"]].copy()
    dep22.columns = ["ED_ID_STR", "name_norm", "score_2022", "pop_2022"]
    dep22["score_2022"] = pd.to_numeric(dep22["score_2022"], errors="coerce")
    dep22["pop_2022"]   = (
        dep22["pop_2022"].astype(str)
        .str.replace(",", "").str.strip()
        .pipe(pd.to_numeric, errors="coerce")
    )

    print(f"[1] Loaded: {len(hist)} historical EDs, {len(dep22)} 2022 EDs")
    return hist, dep22


# ── Step 2: Load boundaries (generalised 20m) ─────────────────────────────────

def load_boundaries():
    dest = os.path.join(CACHE, "ed_gen20m_2022.geojson")
    fetch(ED_GEN20_URL, dest, "ED 2022 boundaries (generalised 20m)")
    print("  Reading GeoDataFrame …")
    gdf = gpd.read_file(dest)
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)
    gdf["ED_ID_STR"] = gdf["ED_ID_STR"].astype(str).str.strip()
    gdf["name_norm"] = gdf["ED_ENGLISH"].apply(norm_name)
    # Simplify a little more for web embedding
    gdf["geometry"] = gdf["geometry"].simplify(0.001, preserve_topology=True)
    print(f"[2] Loaded {len(gdf)} ED polygons. Cols: {list(gdf.columns)}")
    return gdf


# ── Step 3: Join all four years to boundaries ─────────────────────────────────

def build_combined(gdf, hist, dep22):
    # 2022: join by ED_ID_STR
    merged = gdf.merge(dep22[["ED_ID_STR", "score_2022", "pop_2022"]],
                       on="ED_ID_STR", how="left")

    # Historical: join by normalised name (deduplicate — keep first if duplicates)
    hist_dedup = hist.drop_duplicates(subset="name_norm", keep="first")
    hist_idx = hist_dedup.set_index("name_norm")
    for col in ["score_2006", "score_2011", "score_2016"]:
        merged[col] = merged["name_norm"].map(hist_idx[col])

    # Also try matching on 2022 name_norm → hist for unmatched
    matched = {c: merged[c].notna().sum() for c in
               ["score_2006","score_2011","score_2016","score_2022"]}
    for c, n in matched.items():
        print(f"  {c}: {n}/{len(merged)} matched ({100*n/len(merged):.1f}%)")

    # Population from 2022 data (best available)
    merged["pop"] = merged["pop_2022"]

    print(f"[3] Combined table: {len(merged)} rows")
    return merged


# ── Step 4: Flag persistently deprived EDs ────────────────────────────────────

def flag_persistent(merged):
    score_cols = ["score_2006", "score_2011", "score_2016", "score_2022"]
    # Bottom quartile threshold for each year
    thresholds = {c: merged[c].quantile(0.25) for c in score_cols}

    # An ED is "in the bottom quartile" for a year if score ≤ Q25 for that year
    # Require it to be deprived in ALL four waves to be "persistently deprived"
    in_bottom = pd.DataFrame({
        c: merged[c] <= thresholds[c] for c in score_cols
    })
    # Only count EDs that have data in all four years
    has_all_data = merged[score_cols].notna().all(axis=1)
    merged["persistently_deprived"] = in_bottom.all(axis=1) & has_all_data

    n_pers = merged["persistently_deprived"].sum()
    pop_pers = merged.loc[merged["persistently_deprived"], "pop"].sum()
    print(f"[4] Persistently deprived EDs: {n_pers}  "
          f"(pop ~{int(pop_pers or 0):,})")
    for c, t in thresholds.items():
        print(f"    {c} Q25 threshold: {t:.2f}")
    return merged


# ── Step 5: Build JSON payload ────────────────────────────────────────────────

def build_json_payload(merged, services):
    """Return dicts suitable for embedding in JavaScript."""

    # GeoJSON (geometry only + id/name/county)
    feats = []
    for _, row in merged.iterrows():
        if row.geometry is None or row.geometry.is_empty:
            continue
        props = {
            "id":          row["ED_ID_STR"],
            "name":        row.get("ED_ENGLISH", ""),
            "county":      row.get("COUNTY_ENGLISH", ""),
            "lea":         row.get("CSO_LEA", ""),
            "persistent":  bool(row["persistently_deprived"]),
            "pop":         int(row["pop"]) if pd.notna(row.get("pop")) else None,
        }
        # Trim coordinate precision to 4 dp to reduce file size
        geom = row.geometry.__geo_interface__
        feats.append({"type": "Feature", "properties": props, "geometry": geom})

    geojson = {"type": "FeatureCollection", "features": feats}

    # Score dicts: {ed_id_str: score_or_null}
    score_dicts = {}
    for year in [2006, 2011, 2016, 2022]:
        col = f"score_{year}"
        score_dicts[year] = {
            row["ED_ID_STR"]: (round(float(row[col]), 2) if pd.notna(row[col]) else None)
            for _, row in merged.iterrows()
        }

    # Services
    svc_list = [
        {"name":    r["name"],
         "lat":     round(float(r["lat"]), 5),
         "lng":     round(float(r["lng"]), 5),
         "type":    str(r.get("type", "")),
         "county":  str(r.get("county", "")),
         "address": str(r.get("address", ""))}
        for _, r in services.iterrows()
    ]

    return geojson, score_dicts, svc_list


# ── Step 6: Render HTML ───────────────────────────────────────────────────────

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Ireland Deprivation vs Addiction Treatment Access — 2006–2022</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css" />
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css" />
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: Arial, sans-serif; }
  #map { height: 100vh; width: 100%; }

  .panel {
    position: fixed; z-index: 1000; background: white;
    border-radius: 10px; border: 1px solid #ccc;
    box-shadow: 2px 2px 8px rgba(0,0,0,.18);
    padding: 12px 16px;
  }

  #time-control { position: fixed; z-index: 1000; }

  /* ── Time control ── */
  #time-control {
    bottom: 28px; left: 50%; transform: translateX(-50%);
    width: 320px;
    background: rgba(255,255,255,0.97);
    border: none;
    border-radius: 14px;
    box-shadow: 0 4px 24px rgba(0,0,0,.18), 0 1px 4px rgba(0,0,0,.10);
    padding: 16px 20px 13px;
  }
  #tc-label {
    font-size: 9.5px; font-weight: 700; letter-spacing: 0.13em;
    text-transform: uppercase; color: #aaa;
    font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
    margin-bottom: 4px;
  }
  #year-display {
    font-size: 36px; font-weight: 700; color: #111;
    line-height: 1; letter-spacing: -1px;
    font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
    margin-bottom: 14px;
  }

  /* Custom slider track + thumb */
  #year-slider {
    -webkit-appearance: none; appearance: none;
    width: 100%; height: 3px; border-radius: 2px;
    background: #e0e0e0; cursor: pointer; outline: none;
    margin: 0 0 6px;
  }
  #year-slider::-webkit-slider-thumb {
    -webkit-appearance: none; appearance: none;
    width: 16px; height: 16px; border-radius: 50%;
    background: #c00; border: 2px solid #fff;
    box-shadow: 0 1px 4px rgba(0,0,0,.3);
    cursor: pointer; transition: transform .1s;
  }
  #year-slider::-webkit-slider-thumb:hover { transform: scale(1.2); }
  #year-slider::-moz-range-thumb {
    width: 16px; height: 16px; border-radius: 50%;
    background: #c00; border: 2px solid #fff;
    box-shadow: 0 1px 4px rgba(0,0,0,.3); cursor: pointer;
  }

  .tick-labels {
    display: flex; justify-content: space-between;
    font-size: 10px; color: #aaa;
    font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
    margin-bottom: 12px;
  }
  .tick-labels span.active { color: #c00; font-weight: 700; }

  #btn-row {
    display: flex; gap: 8px; align-items: center;
    margin-bottom: 10px;
  }
  #play-btn {
    display: flex; align-items: center; justify-content: center; gap: 6px;
    flex: 1; padding: 8px 0;
    background: #c00; color: #fff; border: none;
    border-radius: 8px; font-size: 13px; font-weight: 600;
    font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
    cursor: pointer; letter-spacing: 0.03em;
    transition: background .15s;
  }
  #play-btn:hover { background: #a00; }
  #play-btn.playing { background: #333; }
  #reset-btn {
    padding: 8px 14px;
    background: none; color: #888; border: 1px solid #ddd;
    border-radius: 8px; font-size: 12px; cursor: pointer;
    font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
    transition: border-color .15s, color .15s;
  }
  #reset-btn:hover { border-color: #aaa; color: #444; }

  #tc-note {
    font-size: 9.5px; color: #bbb; line-height: 1.5;
    font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
    border-top: 1px solid #f0f0f0; padding-top: 8px;
  }

  /* ── Legend ── */
  #legend {
    bottom: 30px; right: 20px;
    font-size: 12px; min-width: 230px;
  }
  #legend h4 { margin-bottom: 6px; font-size: 13px; }
  .swatch { display: inline-block; width: 14px; height: 14px;
            vertical-align: middle; margin-right: 6px; border: 1px solid #999; }
  .legend-row { margin: 3px 0; display: flex; align-items: center; }
  .persistent-swatch {
    display: inline-block; width: 14px; height: 14px;
    vertical-align: middle; margin-right: 6px;
    border: 3px solid #000; background: #aaa;
  }
  #legend hr { margin: 7px 0; border-color: #ddd; }
  #legend .caveat { font-size: 10px; color: #666; margin-top: 6px; }

  /* ── Tooltip override ── */
  .leaflet-tooltip { font-size: 12px; }
</style>
</head>
<body>
<div id="map"></div>

<!-- Time slider -->
<div id="time-control">
  <div id="tc-label">Viewing year</div>
  <div id="year-display">2022</div>
  <input type="range" id="year-slider" min="0" max="3" step="1" value="3"
         oninput="setYear(+this.value)">
  <div class="tick-labels">
    <span id="tick-0">2006</span>
    <span id="tick-1">2011</span>
    <span id="tick-2">2016</span>
    <span id="tick-3" class="active">2022</span>
  </div>
  <div id="btn-row">
    <button id="play-btn" onclick="togglePlay()">&#9654;&ensp;Play</button>
    <button id="reset-btn" onclick="setYear(3)">Reset</button>
  </div>
  <div id="tc-note">
    Service markers fixed to Dec 2025 &mdash; no historical service data available.
  </div>
</div>

<!-- Legend -->
<div class="panel" id="legend">
  <h4>Deprivation Score</h4>
  <div class="legend-row"><span class="swatch" style="background:#67000d"></span>&lt; &minus;20 (Extreme deprivation)</div>
  <div class="legend-row"><span class="swatch" style="background:#cb181d"></span>&minus;20 to &minus;10</div>
  <div class="legend-row"><span class="swatch" style="background:#fc8d59"></span>&minus;10 to &minus;5</div>
  <div class="legend-row"><span class="swatch" style="background:#fee08b"></span>&minus;5 to 0</div>
  <div class="legend-row"><span class="swatch" style="background:#d9ef8b"></span>0 to 5</div>
  <div class="legend-row"><span class="swatch" style="background:#66bd63"></span>5 to 15</div>
  <div class="legend-row"><span class="swatch" style="background:#1a7837"></span>&gt; 15 (Affluent)</div>
  <div class="legend-row"><span class="swatch" style="background:#cccccc"></span>No data</div>
  <hr>
  <div class="legend-row">
    <span class="persistent-swatch"></span>
    <b>Persistently deprived</b> (bottom quartile all 4 waves)
  </div>
  <div class="legend-row" style="margin-top:4px;">
    <span style="color:#2563eb;font-size:16px;margin-right:6px;">&#10010;</span>
    Addiction Treatment Service
  </div>
  <hr>
  <div class="caveat">
    Deprivation: Pobal HP Index, relative weight score.<br>
    More negative = more deprived.<br>
    Service locations: Dec 2025 (fixed across all years).<br>
    <b>Caveat:</b> GP-based medication-assisted treatment
    (methadone, buprenorphine) is <u>not included</u>.
  </div>
</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
<script>
// ══════════════════════════════════════════════════════════════════
// EMBEDDED DATA (injected by Python)
// ══════════════════════════════════════════════════════════════════
const GEOJSON  = %%GEOJSON%%;
const SCORES   = %%SCORES%%;
const SERVICES = %%SERVICES%%;

// ══════════════════════════════════════════════════════════════════
// MAP SETUP
// ══════════════════════════════════════════════════════════════════
const map = L.map('map', {zoomSnap: 0.5}).setView([53.1, -8.0], 7);
L.tileLayer(
  'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
  { attribution: '© OpenStreetMap contributors © CartoDB', maxZoom: 18 }
).addTo(map);

// ══════════════════════════════════════════════════════════════════
// COLOR SCALE  (Pobal-range: −45 → +30)
// ══════════════════════════════════════════════════════════════════
function getColor(score) {
  if (score === null || score === undefined) return '#cccccc';
  if (score < -20) return '#67000d';
  if (score < -15) return '#a50f15';
  if (score < -10) return '#cb181d';
  if (score <  -5) return '#fc8d59';
  if (score <   0) return '#fee08b';
  if (score <   5) return '#d9ef8b';
  if (score <  15) return '#66bd63';
  return '#1a7837';
}

// ══════════════════════════════════════════════════════════════════
// YEAR STATE
// ══════════════════════════════════════════════════════════════════
const YEARS = [2006, 2011, 2016, 2022];
let currentIdx = 3;

function currentYear() { return YEARS[currentIdx]; }

function styleFeature(feature) {
  const score = SCORES[currentYear()][feature.properties.id];
  const isPersistent = feature.properties.persistent;
  return {
    fillColor:   getColor(score),
    fillOpacity: score !== null ? 0.72 : 0.20,
    color:       isPersistent ? '#111111' : '#666666',
    weight:      isPersistent ? 1.2       : 0.15,
    dashArray:   isPersistent ? null      : null,
  };
}

function tooltipContent(feature) {
  const y    = currentYear();
  const sc   = SCORES[y][feature.properties.id];
  const p    = feature.properties;
  const flag = p.persistent
    ? '<br><b style="color:#c00;">⚠ Persistently deprived — bottom quartile in all four waves</b>'
    : '';
  const scores2006 = SCORES[2006][p.id];
  const scores2011 = SCORES[2011][p.id];
  const scores2016 = SCORES[2016][p.id];
  const scores2022 = SCORES[2022][p.id];
  const fmt = v => (v !== null && v !== undefined) ? v.toFixed(1) : '—';
  return `<b>${p.name}</b><br>
          County: ${p.county}<br>
          LEA: ${p.lea}<br>
          Population (2022): ${p.pop !== null ? p.pop.toLocaleString() : '—'}<br>
          <hr style="margin:4px 0;">
          Score <b>${y}</b>: <b>${fmt(sc)}</b><br>
          <small>
          2006: ${fmt(scores2006)} &nbsp;
          2011: ${fmt(scores2011)} &nbsp;
          2016: ${fmt(scores2016)} &nbsp;
          2022: ${fmt(scores2022)}
          </small>
          ${flag}`;
}

// ══════════════════════════════════════════════════════════════════
// GEOJSON LAYER
// ══════════════════════════════════════════════════════════════════
const geojsonLayer = L.geoJSON(GEOJSON, {
  style: styleFeature,
  onEachFeature: function(feature, layer) {
    layer.bindTooltip('', {sticky: true, opacity: 0.95, maxWidth: 280});
    layer.on('mouseover', function() {
      layer.setTooltipContent(tooltipContent(feature));
      layer.openTooltip();
    });
  }
}).addTo(map);

// ══════════════════════════════════════════════════════════════════
// SERVICE MARKERS
// ══════════════════════════════════════════════════════════════════
const svcIcon = L.divIcon({
  html: '<div style="width:10px;height:10px;background:#2563eb;border:2px solid #fff;border-radius:50%;box-shadow:0 0 3px rgba(0,0,0,.5);"></div>',
  className: '',
  iconSize: [10, 10],
  iconAnchor: [5, 5],
});

const clusterGroup = L.markerClusterGroup({
  maxClusterRadius: 40,
  iconCreateFunction: function(cluster) {
    return L.divIcon({
      html: `<div style="background:#2563eb;color:white;border-radius:50%;
                         width:28px;height:28px;line-height:28px;text-align:center;
                         font-size:11px;font-weight:bold;border:2px solid white;
                         box-shadow:0 0 4px rgba(0,0,0,.4);">${cluster.getChildCount()}</div>`,
      className: '', iconSize: [28, 28], iconAnchor: [14, 14]
    });
  }
});

SERVICES.forEach(function(svc) {
  const marker = L.marker([svc.lat, svc.lng], {icon: svcIcon});
  marker.bindTooltip(
    `<b>${svc.name}</b><br>Type: ${svc.type}<br>County: ${svc.county}<br>${svc.address}`,
    {sticky: true, opacity: 0.95}
  );
  clusterGroup.addLayer(marker);
});
map.addLayer(clusterGroup);

// ══════════════════════════════════════════════════════════════════
// LAYER CONTROLS
// ══════════════════════════════════════════════════════════════════
L.control.layers(
  null,
  {
    "Deprivation by area": geojsonLayer,
    "Treatment services": clusterGroup,
  },
  {collapsed: false, position: 'topright'}
).addTo(map);

// ══════════════════════════════════════════════════════════════════
// TIME SLIDER LOGIC
// ══════════════════════════════════════════════════════════════════
function setYear(idx) {
  currentIdx = idx;
  document.getElementById('year-slider').value = idx;
  document.getElementById('year-display').textContent = YEARS[idx];
  // Update active tick label
  YEARS.forEach(function(_, i) {
    document.getElementById('tick-' + i).classList.toggle('active', i === idx);
  });
  // Redraw choropleth styles
  geojsonLayer.setStyle(styleFeature);
}

// ── Play / Pause ──────────────────────────────────────────────────
let playTimer   = null;
let isPlaying   = false;
const FRAME_MS  = 1800;   // ms per year step

function togglePlay() {
  if (isPlaying) {
    clearInterval(playTimer);
    playTimer = null;
    isPlaying = false;
    const btn = document.getElementById('play-btn');
    btn.innerHTML = '&#9654; Play';
    btn.classList.remove('playing');
  } else {
    isPlaying = true;
    const btn = document.getElementById('play-btn');
    btn.innerHTML = '&#9646;&#9646; Pause';
    btn.classList.add('playing');
    playTimer = setInterval(function() {
      const next = (currentIdx + 1) % YEARS.length;
      setYear(next);
      // Pause at end of loop (don't loop forever)
      if (next === YEARS.length - 1) {
        clearInterval(playTimer);
        playTimer = null;
        isPlaying = false;
        btn.innerHTML = '&#9654; Play';
        btn.classList.remove('playing');
      }
    }, FRAME_MS);
  }
}
</script>
</body>
</html>
"""


def render_html(geojson, score_dicts, svc_list):
    """Inject data into the HTML template and return the complete page."""

    # Round GeoJSON coordinate precision to save space
    def round_coords(obj, dp=4):
        if isinstance(obj, dict):
            return {k: round_coords(v, dp) for k, v in obj.items()}
        if isinstance(obj, list):
            # If it looks like a coordinate pair
            if len(obj) == 2 and all(isinstance(x, float) for x in obj):
                return [round(obj[0], dp), round(obj[1], dp)]
            return [round_coords(x, dp) for x in obj]
        return obj

    geojson_rounded = round_coords(geojson)

    html = HTML_TEMPLATE
    html = html.replace("%%GEOJSON%%",  json.dumps(geojson_rounded, separators=(",", ":")))
    html = html.replace("%%SCORES%%",   json.dumps(score_dicts,     separators=(",", ":")))
    html = html.replace("%%SERVICES%%", json.dumps(svc_list,        separators=(",", ":")))
    return html


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Ireland Deprivation Time Slider — 2006 / 2011 / 2016 / 2022")
    print("=" * 60)

    import hrb_scraper
    hrb_scraper.run()
    services = pd.read_csv(hrb_scraper.OUTPUT_FILE).dropna(subset=["lat", "lng"])
    print(f"[0] {len(services)} addiction services loaded.")

    hist, dep22 = load_all_deprivation()
    gdf         = load_boundaries()
    merged      = build_combined(gdf, hist, dep22)
    merged      = flag_persistent(merged)

    print("[5] Serialising to JSON …")
    geojson, score_dicts, svc_list = build_json_payload(merged, services)
    print(f"    GeoJSON features: {len(geojson['features'])}")

    print("[6] Rendering HTML …")
    html = render_html(geojson, score_dicts, svc_list)
    out  = os.path.join(OUTPUTS, "timeslider.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    size_mb = os.path.getsize(out) / 1e6
    print(f"    Saved {size_mb:.1f} MB → {out}")

    # Summary
    n_pers = int(merged["persistently_deprived"].sum())
    pop_pers = int(merged.loc[merged["persistently_deprived"], "pop"].sum())
    print(f"\n  Persistently deprived EDs: {n_pers}")
    print(f"  Population in persistently deprived EDs: {pop_pers:,}")
    print(f"  Counties with most persistent deprivation:")
    top = (
        merged[merged["persistently_deprived"]]
        .groupby("COUNTY_ENGLISH")
        .agg(n=("ED_ID_STR","count"), pop=("pop","sum"))
        .sort_values("pop", ascending=False)
        .head(10)
    )
    for county, row in top.iterrows():
        print(f"    {county:<25} {int(row['n']):3d} EDs  ~{int(row['pop']):,} people")

    print(f"\n✓ Done. Open: {out}")


if __name__ == "__main__":
    main()
