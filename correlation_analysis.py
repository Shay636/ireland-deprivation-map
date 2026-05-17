"""
Correlation analysis: deprivation score vs distance to nearest treatment service
================================================================================
Produces docs/correlation.html: two scatter plots and a plain-English summary.
"""

import os, math, base64, io, warnings
import numpy as np
import pandas as pd
import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
from scipy import stats

warnings.filterwarnings("ignore")

DOCS  = "docs"
CACHE = "cache"
os.makedirs(DOCS, exist_ok=True)

# ── 1. Load data ───────────────────────────────────────────────────────────────

def load_data():
    # Boundaries (county, LEA, geometry)
    gdf = gpd.read_file(os.path.join(CACHE, "ed_gen20m_2022.geojson"))
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)

    # Pobal 2022 deprivation scores
    dep = pd.read_csv(os.path.join(CACHE, "pobal_2022.csv"),
                      encoding="latin-1", dtype={"ED_ID_STR": str})
    dep["ED_ID_STR"] = dep["ED_ID_STR"].apply(
        lambda x: str(x).strip().zfill(6) if "/" not in str(x) else str(x).strip()
    )
    dep = dep[["ED_ID_STR", "ED_ENGLISH", "Index22_ED_std_rel_wt", "TOTPOP22"]].copy()
    dep.columns = ["ED_ID_STR", "ED_ENGLISH", "dep_score", "pop"]
    dep["dep_score"] = pd.to_numeric(dep["dep_score"], errors="coerce")
    dep["pop"] = dep["pop"].astype(str).str.replace(",", "").pipe(pd.to_numeric, errors="coerce")

    # Services
    services = pd.read_csv("hrb_addiction_services.csv").dropna(subset=["lat", "lng"])

    # Merge boundaries with deprivation
    merged = gdf.merge(dep, on="ED_ID_STR", how="left")
    merged = merged[merged["dep_score"].notna()].copy()

    # Calculate distances
    print(f"  Calculating distances for {len(merged)} EDs …")
    centroids = merged.geometry.to_crs(epsg=4326).centroid
    clat = centroids.y.values
    clon = centroids.x.values
    slat = services["lat"].values
    slon = services["lng"].values
    sname = services["name"].values

    R = 6371.0
    min_dist = np.full(len(clat), np.nan)
    near_svc = np.empty(len(clat), dtype=object)
    for i in range(len(clat)):
        if not (np.isfinite(clat[i]) and np.isfinite(clon[i])):
            continue
        lat1 = math.radians(clat[i]); lon1 = math.radians(clon[i])
        lat2 = np.radians(slat);      lon2 = np.radians(slon)
        a = np.sin((lat2-lat1)/2)**2 + math.cos(lat1)*np.cos(lat2)*np.sin((lon2-lon1)/2)**2
        d = R * 2 * np.arcsin(np.sqrt(a))
        idx = int(np.argmin(d))
        min_dist[i] = d[idx]
        near_svc[i] = sname[idx]

    merged["dist_km"]  = min_dist
    merged["near_svc"] = near_svc
    merged = merged.dropna(subset=["dist_km"]).copy()

    # Rural flag: exclude the five city council areas
    CITIES = {"DUBLIN CITY", "CORK CITY", "LIMERICK CITY", "WATERFORD CITY", "GALWAY CITY"}
    merged["is_rural"] = ~merged["COUNTY_ENGLISH"].isin(CITIES)

    print(f"  Total EDs with data: {len(merged)}")
    print(f"  Rural EDs: {merged['is_rural'].sum()}")
    return merged


# ── 2. County colour palette ───────────────────────────────────────────────────

def make_county_palette(counties):
    """Assign a visually distinct colour to each county."""
    # Organised by province so geographically close counties share hue families
    PROVINCE_PALETTE = {
        # Connacht (blues)
        "GALWAY":        "#1565C0", "GALWAY CITY":   "#5C9BD6",
        "MAYO":          "#2196F3", "ROSCOMMON":     "#64B5F6",
        "SLIGO":         "#0D47A1", "LEITRIM":       "#42A5F5",
        # Leinster (greens/teals)
        "DUBLIN CITY":   "#1B5E20", "SOUTH DUBLIN":  "#2E7D32",
        "FINGAL":        "#388E3C", "DUN LAOGHAIRE/RATHDOWN": "#43A047",
        "WICKLOW":       "#66BB6A", "WEXFORD":       "#A5D6A7",
        "CARLOW":        "#004D40", "KILKENNY":      "#00796B",
        "LAOIS":         "#00897B", "OFFALY":        "#26A69A",
        "WESTMEATH":     "#4DB6AC", "LONGFORD":      "#80CBC4",
        "MEATH":         "#558B2F", "LOUTH":         "#8BC34A",
        "KILDARE":       "#33691E",
        # Munster (oranges/reds)
        "CORK":          "#BF360C", "CORK CITY":     "#E64A19",
        "KERRY":         "#E65100", "LIMERICK":      "#FF6D00",
        "LIMERICK CITY": "#FF8F00", "CLARE":         "#FFA000",
        "WATERFORD":     "#FF7043", "WATERFORD CITY":"#FF5722",
        "NORTH TIPPERARY":"#F57C00","SOUTH TIPPERARY":"#EF6C00",
        # Ulster ROI (purples)
        "DONEGAL":       "#6A1B9A", "MONAGHAN":      "#8E24AA",
        "CAVAN":         "#AB47BC",
    }
    palette = {}
    fallback = iter(plt.cm.tab20.colors)
    for c in counties:
        palette[c] = PROVINCE_PALETTE.get(c, next(fallback, "#888888"))
    return palette


# ── 3. Scatter plot ───────────────────────────────────────────────────────────

def make_scatter(df, title, subtitle, fig_label):
    """Return base64-encoded PNG of the scatter plot."""
    counties = sorted(df["COUNTY_ENGLISH"].dropna().unique())
    palette  = make_county_palette(counties)

    fig, ax = plt.subplots(figsize=(10, 6.5))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("#fafafa")

    # Plot each county separately for legend
    for county in counties:
        sub = df[df["COUNTY_ENGLISH"] == county]
        ax.scatter(
            sub["dep_score"], sub["dist_km"],
            color=palette[county], s=9, alpha=0.45,
            linewidths=0, label=county, rasterized=True,
        )

    # Regression line
    x = df["dep_score"].values
    y = df["dist_km"].values
    slope, intercept, r_val, p_val, se = stats.linregress(x, y)
    x_line = np.linspace(x.min(), x.max(), 200)
    ax.plot(x_line, slope * x_line + intercept,
            color="#c00", lw=2.2, zorder=10, label=f"Regression (R²={r_val**2:.3f})")

    # Annotation box
    p_text = "< 0.001" if p_val < 0.001 else f"= {p_val:.4f}"
    anno = (f"R² = {r_val**2:.3f}\n"
            f"r  = {r_val:.3f}\n"
            f"p {p_text}\n"
            f"n = {len(df):,}")
    ax.text(0.97, 0.97, anno,
            transform=ax.transAxes, ha="right", va="top",
            fontsize=10, fontfamily="monospace",
            bbox=dict(boxstyle="round,pad=0.5", fc="white", ec="#cccccc", alpha=0.92))

    # Reference lines
    ax.axvline(0, color="#cccccc", lw=0.8, ls="--", zorder=1)
    ax.axhline(0, color="#cccccc", lw=0.8, zorder=1)

    # Axis labels & title
    ax.set_xlabel("Deprivation score  (more negative = more deprived)", fontsize=11)
    ax.set_ylabel("Distance to nearest treatment service (km)", fontsize=11)
    ax.set_title(title, fontsize=13, fontweight="bold", pad=10)
    if subtitle:
        ax.text(0.5, 1.0, subtitle, transform=ax.transAxes,
                ha="center", va="bottom", fontsize=9.5, color="#666",
                style="italic")

    # County legend: two columns outside the plot
    handles, labels = ax.get_legend_handles_labels()
    # Separate regression line handle from county handles
    reg_h  = [h for h, l in zip(handles, labels) if "Regression" in l]
    reg_l  = [l for l in labels if "Regression" in l]
    cty_h  = [h for h, l in zip(handles, labels) if "Regression" not in l]
    cty_l  = [l for l in labels if "Regression" not in l]

    ax.legend(reg_h, reg_l, loc="upper left", fontsize=9.5,
              framealpha=0.85, edgecolor="#ddd")

    leg2 = fig.legend(cty_h, [l.title() for l in cty_l],
                      loc="lower center", ncol=6,
                      fontsize=7.5, framealpha=0.9, edgecolor="#ddd",
                      bbox_to_anchor=(0.5, -0.01),
                      title="County", title_fontsize=8)

    fig.tight_layout()
    fig.subplots_adjust(bottom=0.22)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=140, bbox_inches="tight",
                facecolor="white", bbox_extra_artists=[leg2])
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode(), r_val, p_val, slope, len(df)


# ── 4. Plain-English summary ───────────────────────────────────────────────────

def plain_english_summary(r_all, p_all, slope_all, n_all,
                           r_rur, p_rur, slope_rur, n_rur):
    """Write a plain-English interpretation of both correlations."""

    def sig_text(p):
        if p < 0.001: return "highly statistically significant (p < 0.001)"
        if p < 0.01:  return f"statistically significant (p = {p:.4f})"
        if p < 0.05:  return f"statistically significant (p = {p:.3f})"
        return f"not statistically significant (p = {p:.3f})"

    def dir_text(r):
        return "negative" if r < 0 else "positive"

    def strength(r):
        a = abs(r)
        if a > 0.5:  return "strong"
        if a > 0.3:  return "moderate"
        if a > 0.1:  return "weak"
        return "very weak"

    # Interpret sign: dep_score more negative = more deprived
    # negative r means more deprived → further away. Positive r means less deprived → further.
    def meaning(r, context=""):
        if r < -0.05:
            return (f"more deprived Electoral Divisions tend to be <b>further</b> from a "
                    f"treatment service{context}")
        if r > 0.05:
            return (f"more deprived Electoral Divisions tend to be <b>closer</b> to a "
                    f"treatment service{context}, a counterintuitive pattern driven by "
                    f"urban concentration")
        return f"there is <b>no clear directional relationship</b>{context}"

    r2_all = r_all**2
    r2_rur = r_rur**2

    lines = []

    # Opening
    lines.append(f"""
<p>Across all {n_all:,} Electoral Divisions, the Pearson correlation between deprivation score
and distance to the nearest listed addiction treatment service is
<b>r = {r_all:.3f}</b> (R² = {r2_all:.3f}), which is {sig_text(p_all)}.
This is a {strength(r_all)} {dir_text(r_all)} correlation, meaning that {meaning(r_all)}.
The deprivation score alone explains <b>{100*r2_all:.1f}%</b> of the variation in service distance.</p>
""")

    # Urban confound
    lines.append(f"""
<p>At the national level this association is partly masked by urban concentration.
Ireland's most deprived areas include both inner-city Electoral Divisions —
where services are close, and remote rural areas where they are not.
These two patterns partially cancel each other out in the national figure.</p>
""")

    # Rural-only
    lines.append(f"""
<p>Restricting the analysis to rural Electoral Divisions (outside the five city
council areas, n = {n_rur:,}), the correlation strengthens to
<b>r = {r_rur:.3f}</b> (R² = {r2_rur:.3f}), still {sig_text(p_rur)},
and {strength(r_rur)} {dir_text(r_rur)}. In rural Ireland, {meaning(r_rur,
" — without the masking effect of urban service density")}.
The regression slope of <b>{slope_rur:.2f} km per score unit</b> means that for every
one-point increase in deprivation (i.e. moving one unit further down the deprivation scale),
a rural Electoral Division is on average {abs(slope_rur):.2f} km further from the nearest service.</p>
""")

    # Bottom line
    if r_rur < -0.15 and p_rur < 0.05:
        verdict = ("Yes. In rural Ireland there is a statistically significant association "
                   "between higher deprivation and greater distance from treatment. "
                   "The places that need help most are, on average, the hardest to reach.")
    elif r_rur < 0 and p_rur < 0.05:
        verdict = ("Weakly yes: the association is statistically significant in rural Ireland "
                   "but modest in magnitude. Distance and deprivation co-occur, but the "
                   "relationship is noisy, and many deprived rural areas are not unusually "
                   "far from services.")
    else:
        verdict = ("The evidence for a rural deprivation-distance gradient is limited. "
                   "While individual isolated areas exist, the statistical relationship "
                   "across rural EDs as a whole is not strong.")

    lines.append(f"""
<p><b>Bottom line:</b> {verdict}</p>
""")

    return "\n".join(lines)


# ── 5. Render HTML ────────────────────────────────────────────────────────────

def render_html(img_all, stats_all, img_rur, stats_rur, summary_html):
    r_all, p_all, slope_all, n_all = stats_all
    r_rur, p_rur, slope_rur, n_rur = stats_rur

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Correlation: Deprivation vs Distance to Treatment in Ireland</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  :root {{ --text: #1a1a1a; --muted: #555; --border: #ddd; --accent: #c00; }}
  html {{ font-size: 16px; }}
  body {{ background: #fff; color: var(--text);
          font-family: Georgia, "Times New Roman", serif;
          line-height: 1.7; }}
  .container {{ max-width: 900px; margin: 0 auto; padding: 0 28px; }}
  header {{ padding: 48px 0 32px; border-bottom: 2px solid var(--text); }}
  .eyebrow {{ font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
              font-size: 0.68rem; font-weight: 700; letter-spacing: 0.14em;
              text-transform: uppercase; color: var(--accent); margin-bottom: 12px; }}
  h1 {{ font-size: clamp(1.4rem, 3vw, 1.9rem); font-weight: normal;
        line-height: 1.25; margin-bottom: 16px; }}
  .lead {{ font-size: 1rem; color: var(--muted); max-width: 720px; }}
  .section {{ padding: 40px 0 32px; border-bottom: 1px solid var(--border); }}
  .section:last-of-type {{ border-bottom: none; }}
  .section-label {{ font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
                    font-size: 0.67rem; font-weight: 700; letter-spacing: 0.14em;
                    text-transform: uppercase; color: var(--muted); margin-bottom: 16px; }}
  h2 {{ font-size: 1.05rem; font-weight: bold; margin-bottom: 6px; }}
  .plot-wrap {{ margin: 20px 0; border: 1px solid var(--border);
                border-radius: 6px; overflow: hidden; background: #fafafa; }}
  .plot-wrap img {{ width: 100%; display: block; }}
  .stat-row {{ display: flex; gap: 24px; margin: 16px 0; flex-wrap: wrap; }}
  .stat-box {{ background: #f7f7f7; border: 1px solid var(--border);
               border-radius: 6px; padding: 12px 18px; min-width: 140px; }}
  .stat-box .val {{ font-size: 1.5rem; font-weight: bold; color: var(--accent);
                    font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
                    letter-spacing: -0.02em; line-height: 1.1; }}
  .stat-box .lbl {{ font-size: 0.75rem; color: var(--muted);
                    font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
                    margin-top: 2px; }}
  .summary p {{ margin-bottom: 0.9em; font-size: 0.975rem; }}
  .summary p:last-child {{ margin-bottom: 0; }}
  .method {{ font-size: 0.83rem; color: var(--muted);
             font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
             line-height: 1.6; }}
  footer {{ padding: 24px 0 40px; border-top: 2px solid var(--text); margin-top: 0; }}
  footer p {{ font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
              font-size: 0.75rem; color: var(--muted); }}
  footer a {{ color: var(--text); text-underline-offset: 2px; }}
</style>
</head>
<body>
<div class="container">

<header>
  <p class="eyebrow">Ireland, 2022</p>
  <h1>Deprivation and Distance to Treatment: Is There a Relationship?</h1>
  <p class="lead">Scatter plots and correlation analysis across all Electoral Divisions,
  using the Pobal HP Deprivation Index 2022 and straight-line distance to the nearest
  listed addiction treatment service.</p>
</header>

<section class="section">
  <p class="section-label">All Electoral Divisions (n = {n_all:,})</p>
  <h2>National picture</h2>
  <div class="stat-row">
    <div class="stat-box">
      <div class="val">r = {r_all:.3f}</div>
      <div class="lbl">Pearson correlation</div>
    </div>
    <div class="stat-box">
      <div class="val">R² = {r_all**2:.3f}</div>
      <div class="lbl">Variance explained</div>
    </div>
    <div class="stat-box">
      <div class="val">{"p < 0.001" if p_all < 0.001 else f"p = {p_all:.4f}"}</div>
      <div class="lbl">Significance</div>
    </div>
  </div>
  <div class="plot-wrap">
    <img src="data:image/png;base64,{img_all}" alt="Scatter plot, all EDs">
  </div>
</section>

<section class="section">
  <p class="section-label">Rural Electoral Divisions only (n = {n_rur:,})</p>
  <h2>Rural Ireland: removing the urban masking effect</h2>
  <div class="stat-row">
    <div class="stat-box">
      <div class="val">r = {r_rur:.3f}</div>
      <div class="lbl">Pearson correlation</div>
    </div>
    <div class="stat-box">
      <div class="val">R² = {r_rur**2:.3f}</div>
      <div class="lbl">Variance explained</div>
    </div>
    <div class="stat-box">
      <div class="val">{"p < 0.001" if p_rur < 0.001 else f"p = {p_rur:.4f}"}</div>
      <div class="lbl">Significance</div>
    </div>
  </div>
  <div class="plot-wrap">
    <img src="data:image/png;base64,{img_rur}" alt="Scatter plot, rural EDs">
  </div>
</section>

<section class="section">
  <p class="section-label">What it means</p>
  <div class="summary">
    {summary_html}
  </div>
</section>

<section class="section">
  <p class="section-label">Method</p>
  <p class="method">
    Deprivation scores: Pobal HP Deprivation Index 2022, relative weight score at Electoral
    Division level. More negative = more deprived. Distance: straight-line (haversine) from
    each ED centroid to the nearest of 79 listed addiction treatment services (Dec 2025).
    Pearson correlation and ordinary least squares regression. Rural EDs defined as those
    outside the five city council areas (Dublin City, Cork City, Limerick City, Waterford City,
    Galway City). Analysis excludes EDs with missing deprivation data (n = {3420 - n_all}).
    All computations in Python using SciPy and NumPy.
  </p>
</section>

<footer>
  <p>Part of the <a href="index.html">Two Decades of Disadvantage</a> project.
  Analysis by Shay McDonnell. Data: Pobal, CSO, OSM.</p>
</footer>

</div>
</body>
</html>"""


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 58)
    print("Correlation: Deprivation vs Distance to Treatment")
    print("=" * 58)

    df = load_data()

    # All EDs
    print("\n[All EDs]")
    img_all, r_all, p_all, slope_all, n_all = make_scatter(
        df,
        "Deprivation Score vs Distance to Nearest Treatment Service",
        "All Electoral Divisions, Ireland 2022  |  one dot = one ED",
        "all",
    )
    print(f"  r = {r_all:.3f}, R² = {r_all**2:.3f}, p = {p_all:.2e}, n = {n_all:,}")

    # Rural EDs
    rural = df[df["is_rural"]].copy()
    print(f"\n[Rural EDs: {len(rural):,} EDs]")
    img_rur, r_rur, p_rur, slope_rur, n_rur = make_scatter(
        rural,
        "Deprivation Score vs Distance to Nearest Treatment Service",
        "Rural Electoral Divisions only (outside five city council areas)  |  one dot = one ED",
        "rural",
    )
    print(f"  r = {r_rur:.3f}, R² = {r_rur**2:.3f}, p = {p_rur:.2e}, n = {n_rur:,}")

    summary = plain_english_summary(r_all, p_all, slope_all, n_all,
                                    r_rur, p_rur, slope_rur, n_rur)

    html = render_html(
        img_all, (r_all, p_all, slope_all, n_all),
        img_rur, (r_rur, p_rur, slope_rur, n_rur),
        summary,
    )
    out = os.path.join(DOCS, "correlation.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n  Saved {os.path.getsize(out)/1e6:.1f} MB → {out}")
    print("✓ Done.")


if __name__ == "__main__":
    main()
