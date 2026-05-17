# Two Decades of Disadvantage: Addiction Treatment Access and Deprivation in Ireland

A spatial analysis of how deprivation and distance to addiction treatment services overlap across Ireland, traced across four census waves: 2006, 2011, 2016, and 2022.

**Live site:** [shay636.github.io/ireland-deprivation-map](https://shay636.github.io/ireland-deprivation-map/)

---

## What it shows

- **728,000 people** have lived in persistently deprived areas for at least twenty years
- **434 Electoral Divisions** have been in the bottom quartile of the national deprivation index at every census since 2006
- The most isolated area is **Doonloughan, Connemara** — 72.7 km straight-line from the nearest listed treatment service
- In rural Ireland, there is a statistically significant association between higher deprivation and greater distance from treatment (r = −0.258, p < 0.001)

## Pages

| Page | Description |
|---|---|
| [`index.html`](https://shay636.github.io/ireland-deprivation-map/) | Landing page with map embed and key findings |
| [`timeslider.html`](https://shay636.github.io/ireland-deprivation-map/timeslider.html) | Interactive time-slider map: deprivation choropleth and distance-to-service layer, 2006–2022 |
| [`correlation.html`](https://shay636.github.io/ireland-deprivation-map/correlation.html) | Scatter plots and correlation analysis |

## Data sources

| Source | Description |
|---|---|
| [Pobal HP Deprivation Index](https://www.pobal.ie/pobal-hp-deprivation-index/) | Deprivation scores at Electoral Division level, 2006/2011/2016/2022 |
| [CSO SAPS 2022](https://www.cso.ie/en/census/census2022/census2022smallareapopulationstatistics/) | Small Area Population Statistics, Census 2022 |
| [CSO ED Boundaries 2022](https://data.gov.ie/dataset/cso-electoral-divisions-national-statistical-boundaries-2022-generalised-20m1) | Electoral Division boundaries, generalised 20m |
| Addiction treatment services | Curated list of 79 verified services in the Republic of Ireland, December 2025. GP-based treatment not included. |

## Running the pipelines

Requires Python 3.9+ and the packages in `requirements.txt`.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

```bash
# Build the time-slider map (downloads ~200 MB of boundary/deprivation data on first run)
python3 timeslider_pipeline.py

# Build the SA-level deprivation analysis and static choropleth map
python3 pipeline.py

# Run the correlation analysis
python3 correlation_analysis.py
```

Downloaded data is cached in `cache/` and not committed to the repo.

## Caveats

- Service locations reflect December 2025 only. No historical service data is available.
- Distance is straight-line (haversine) and does not account for transport, waiting times, or capacity.
- GP-based medication-assisted treatment (methadone, buprenorphine) is not included in the service dataset.
- 3.2% of historical Electoral Divisions are unmatched due to boundary changes between 2006 and 2022.
- `timeslider.html` is ~7 MB and may load slowly on mobile connections.

## Analysis by

Shay McDonnell
