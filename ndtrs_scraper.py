"""
NDTRS County Treatment Demand Scraper
======================================
Uses Playwright to submit the interactive form at drugsandalcohol.ie/tables/ and
download county-level treatment case counts for:
  - All substances combined (2004-2024)
  - Opioids only (heroin + other opioids, 2004-2024)
Saves to docs/ndtrs_by_county.csv and docs/county_summary_full.csv.
"""

import os, sys, io, re, asyncio, math
import pandas as pd
import numpy as np
from playwright.async_api import async_playwright

DOCS  = "docs"
CACHE = "cache"
os.makedirs(DOCS,  exist_ok=True)
os.makedirs(CACHE, exist_ok=True)

BASE_URL = "https://www.drugsandalcohol.ie/tables/"
OUT_CSV  = os.path.join(DOCS,  "ndtrs_by_county.csv")
FULL_CSV = os.path.join(DOCS,  "county_summary_full.csv")
CACHE_ALL    = os.path.join(CACHE, "ndtrs_all_raw.csv")
CACHE_OPIOID = os.path.join(CACHE, "ndtrs_opioid_raw.csv")

# County code → display name mapping (NDTRS codes)
COUNTY_MAP = {
    "C": "Carlow", "CE": "Clare", "CN": "Cavan", "CW": "Carlow",
    "D": "Dublin", "DL": "Donegal", "G": "Galway", "KE": "Kildare",
    "K": "Kilkenny", "KY": "Kerry", "L": "Limerick", "LD": "Longford",
    "LH": "Louth", "LM": "Leitrim", "LS": "Laois", "MH": "Meath",
    "MN": "Monaghan", "MO": "Mayo", "OY": "Offaly", "RN": "Roscommon",
    "SO": "Sligo", "T": "Tipperary", "W": "Waterford", "WH": "Westmeath",
    "WW": "Wicklow", "WX": "Wexford",
}

# CSO population 2022 by county (from Census 2022 summary)
COUNTY_POP_2022 = {
    "Carlow":      61968,  "Cavan":       81704,  "Clare":      127938,
    "Cork":       584568,  "Donegal":     167084,  "Dublin":    1458154,
    "Galway":     277478,  "Kerry":       156458,  "Kildare":   247774,
    "Kilkenny":   104160,  "Laois":        91877,  "Leitrim":    35199,
    "Limerick":   209591,  "Longford":     46751,  "Louth":     139703,
    "Mayo":       137970,  "Meath":        220826,  "Monaghan":   65288,
    "Offaly":      83150,  "Roscommon":    70259,  "Sligo":      70198,
    "Tipperary":  167707,  "Waterford":   127363,  "Westmeath":  96221,
    "Wexford":    163919,  "Wicklow":     155851,
}


async def query_ndtrs(page, substance_mode: str, label: str, year: int = 2024) -> pd.DataFrame:
    """
    Submit the NDTRS form for a given substance mode and return a tidy DataFrame.
    substance_mode: 'all' (alcohol_drugs) or 'opioids' (drugs=heroin+other_opioids)
    """
    print(f"  Querying NDTRS: {label} ...")

    # Always navigate fresh so the form resets between queries
    await page.goto(BASE_URL, wait_until="networkidle", timeout=30000)

    # ── Dismiss OneTrust cookie consent overlay (blocks clicks) ────────────
    await page.evaluate("""() => {
        // Remove the OneTrust overlay and SDK entirely
        const sdk = document.getElementById('onetrust-consent-sdk');
        if (sdk) sdk.remove();
        const filter = document.querySelector('.onetrust-pc-dark-filter');
        if (filter) filter.remove();
        // Also try clicking the accept-all button if present
        const btn = document.getElementById('onetrust-accept-btn-handler');
        if (btn) btn.click();
    }""")
    await page.wait_for_timeout(500)

    # ── Accept NDTRS terms (only if button is present) ─────────────────────
    accept_btn_present = await page.evaluate(
        "() => !!document.getElementById('accept_submit')"
    )
    if accept_btn_present:
        async with page.expect_response(
            lambda r: 'ajax_accept_form' in r.url, timeout=10000
        ) as accept_resp_info:
            await page.evaluate("() => { document.getElementById('accept_submit').click(); }")
        accept_resp = await accept_resp_info.value
        try:
            accept_body = (await accept_resp.body()).decode('utf-8', 'replace')
            print(f"    Terms: {accept_body[:80]}")
        except Exception:
            pass
    else:
        print("    Terms already accepted (session active).")

    await page.wait_for_timeout(1000)

    # Make sure the selection form tab is active
    await page.evaluate("""() => {
        try {
            jQuery('#tabs').tabs('enable', 1);
            jQuery('#tabs').tabs('enable', 2);
            jQuery('#tabs').tabs('enable', 3);
            jQuery('#tabs').tabs('option', 'active', 1);
        } catch(e) {}
    }""")
    await page.wait_for_timeout(800)

    await page.wait_for_selector('input[name="soi"]', state='attached', timeout=10000)
    print("    Form ready.")
    # Wait for the form tab to become active (SOI radios become visible)
    await page.wait_for_selector('input[name="soi"]', state='visible', timeout=15000)
    await page.wait_for_timeout(800)

    # Use Playwright's native click for radio buttons (they ARE visible after terms acceptance)
    # Use JS check for checkboxes since they may be in scrollable areas

    async def js_check(name, value):
        """Check a checkbox by name+value — set checked directly + fire click for cascade."""
        await page.evaluate(
            """([n, v]) => {
                var inputs = document.querySelectorAll('input[name="' + n + '"]');
                inputs.forEach(function(el) {
                    if (el.value === v) {
                        el.checked = true;
                        // Fire click so the JS cascade handler runs (checks all sub-items if 'all')
                        el.click();
                    }
                });
            }""",
            [name, value]
        )
        await page.wait_for_timeout(300)

    # ── Substance of interest ──────────────────────────────────────────────
    if substance_mode == 'all':
        await js_check('soi', 'alcohol_drugs')
        await page.wait_for_timeout(800)
        # For soi=alcohol_drugs: only check alcohol_drugs[N], NOT drugs[N]
        await js_check('alcohol_drugs[1]', 'all')
    else:
        # Use alcohol_drugs form (same SOI as all-substances) but uncheck everything
        # except heroin (111) and other opioids (100) — set state directly, no events
        await js_check('soi', 'alcohol_drugs')
        await page.wait_for_timeout(600)
        await page.evaluate("""() => {
            // Uncheck ALL alcohol_drugs checkboxes first (no event, just state)
            Array.from(document.querySelectorAll('input[type="checkbox"]'))
                .filter(function(el) { return el.name && el.name.indexOf('alcohol_drugs') === 0; })
                .forEach(function(el) { el.checked = false; });
            // Now check only heroin (111) and other opioids (100)
            Array.from(document.querySelectorAll('input[type="checkbox"]'))
                .filter(function(el) {
                    return el.name && el.name.indexOf('alcohol_drugs') === 0 &&
                           (el.value === '111' || el.value === '100');
                })
                .forEach(function(el) { el.checked = true; });
        }""")

    # ── Select specific year — set checked directly without any cascade ────
    await page.evaluate(
        """(y) => {
            document.querySelectorAll('input[name^="years["]').forEach(function(el) {
                el.checked = (el.value === String(y));
            });
        }""",
        year
    )

    # ── All ages, treatment statuses, genders ─────────────────────────────
    await js_check('ages[1]', 'all')
    await js_check('treat_statuss[1]', 'all')
    await js_check('Sexs[1]', 'all')

    # ── Geography: county ─────────────────────────────────────────────────
    await js_check('geo', 'county')
    await page.wait_for_timeout(600)
    await js_check('countys[1]', 'all')

    # ── No additional row/column breakdowns ───────────────────────────────
    await page.evaluate("() => { jQuery('select#ya').val('empty').trigger('change'); }")
    await page.evaluate("() => { jQuery('select#yb').val('empty').trigger('change'); }")

    # ── Submit via JS to bypass any visibility checks ─────────────────────
    # Intercept the AJAX response so we can capture the data directly
    ajax_data = {}

    network_log = []
    async def handle_response(response):
        network_log.append(response.url)
        if 'ajax_search_form.php' in response.url:
            try:
                body = await response.body()
                ajax_data['body'] = body.decode('utf-8', 'replace')
                ajax_data['url']  = response.url
                print(f"    >>> Captured ajax_search_form response: {len(ajax_data['body'])} bytes")
                print(f"    >>> First 300: {ajax_data['body'][:300]}")
            except Exception as e:
                print(f"    >>> Failed to capture response: {e}")
        elif 'error.php' in response.url:
            try:
                body = await response.body()
                ajax_data['error'] = body.decode('utf-8', 'replace')[:500]
            except Exception:
                pass

    page.on('response', handle_response)

    # Capture console messages and network requests for debugging
    console_msgs = []
    page.on('console', lambda m: console_msgs.append(m.text))

    # Scroll to and click the submit button
    submit_btn = page.locator('#ndtrs_submit')
    await submit_btn.scroll_into_view_if_needed()
    await submit_btn.click()
    print("    Submitted. Waiting for results ...")

    # Wait for the AJAX response or the export button
    try:
        await page.wait_for_selector('#export', state='visible', timeout=30000)
        print("    Results ready (export button appeared).")
    except Exception:
        print("    Timeout waiting for results — trying to extract anyway.")

    await page.wait_for_timeout(2000)

    # ── Extract data ───────────────────────────────────────────────────────
    # Method 1: Use intercepted AJAX response data_exec
    import json as _json
    if console_msgs:
        errs = [m for m in console_msgs if 'error' in m.lower()]
        if errs:
            print(f"    Console errors: {errs[:3]}")

    if ajax_data.get('body'):
        try:
            resp_json = _json.loads(ajax_data['body'])
            # Structure: {"data": {"ajax_content": "<HTML table>"}}
            ajax_content = resp_json.get('data', {}).get('ajax_content', '')
            if ajax_content:
                table_html = ajax_content
                print(f"    Extracted ajax_content ({len(table_html)} bytes)")
            else:
                table_html = ''
                # Check for error
                msg = resp_json.get('message', '')
                if msg:
                    print(f"    AJAX message: {msg[:200]}")
        except Exception as e:
            print(f"    Failed to parse AJAX JSON: {e}")
            table_html = ''
    else:
        table_html = ''

    # Method 2: Get it directly from the DOM if method 1 failed
    if not table_html.strip():
        await page.evaluate("() => { try { jQuery('#tabs').tabs('option','active',2); } catch(e){} }")
        await page.wait_for_timeout(1000)
        table_html = await page.inner_html('#tabs-3-content')
        print(f"    DOM extraction: tabs-3-content has {len(table_html)} bytes")

    if not table_html.strip() or '<table' not in table_html.lower():
        # Print all tab contents to debug
        dbg = await page.evaluate("""() => {
            var r = {};
            ['tabs-1-content','tabs-2-content','tabs-3-content','tabs-4-content'].forEach(id => {
                var el = document.getElementById(id);
                r[id] = el ? el.innerHTML.length : 0;
            });
            return JSON.stringify(r);
        }""")
        print(f"    All tab lengths: {dbg}")
        await page.screenshot(path='cache/ndtrs_after_submit.png', full_page=True)
        print("    Screenshot saved to cache/ndtrs_after_submit.png")
        # Check for error messages on page
        err_msg = await page.evaluate("() => { var el = document.getElementById('ndtrs_form_message'); return el ? el.innerText : ''; }")
        print(f"    Form message: {err_msg!r}")
        print(f"    WARNING: no content extracted for {label}")
        return pd.DataFrame()

    # Parse the HTML table
    dfs = pd.read_html(io.StringIO(table_html), flavor='lxml')
    if not dfs:
        print(f"    WARNING: no parseable table for {label}")
        return pd.DataFrame()

    raw_df = dfs[0]
    # Tidy immediately with the correct year
    value_col = 'cases_all' if substance_mode == 'all' else 'cases_opioid'
    tidy = tidy_ndtrs_table(raw_df, value_col, year=year)
    return tidy


def tidy_ndtrs_table(df: pd.DataFrame, value_label: str, year: int = 2024) -> pd.DataFrame:
    """
    Parse the NDTRS table HTML response. The table structure is:
      Rows 0-4: filter display (Year, Gender, Ages, etc.)
      Row 5:    substance column headers (NaN, Amphetamines, ..., Alcohol, Totals)
      Row 6:    county header row
      Rows 7+:  county data rows
    Extracts: county, total cases (last column), and individual substance columns.
    """
    if df.empty:
        return pd.DataFrame()

    df = df.copy()
    county_col = df.columns[0]

    # Find the row where the county data starts (first row after "County" header)
    county_header_row = None
    for i, val in enumerate(df[county_col]):
        if str(val).strip().lower() == 'county':
            county_header_row = i
            break

    if county_header_row is None:
        print(f"  WARNING: could not find county header row")
        return pd.DataFrame()

    # Get substance column labels from the substance-label row (row 5 typically)
    label_row_idx = county_header_row - 1
    substance_labels = {col: str(df.iloc[label_row_idx][col]).strip()
                        for col in df.columns}

    # Data rows start after county_header_row
    data = df.iloc[county_header_row + 1:].copy()
    data = data[data[county_col].notna() &
                ~data[county_col].astype(str).str.lower().isin(
                    ['total', 'totals', 'unknown', 'xx', 'zz', 'nan', '']
                )].copy()

    def to_num(x):
        s = str(x).strip().replace(',', '').replace('~', '0')
        try:
            return float(s)
        except ValueError:
            return pd.NA

    # Find the "Totals" column (last substance column, usually col 11)
    totals_col = None
    heroin_col = None
    opioid_col = None
    for col, lbl in substance_labels.items():
        if lbl.lower() in ('totals', 'total'):
            totals_col = col
        if 'heroin' in lbl.lower():
            heroin_col = col
        if 'other opioid' in lbl.lower():
            opioid_col = col

    if totals_col is None:
        totals_col = df.columns[-1]  # fallback: last column

    records = []
    for _, row in data.iterrows():
        county_raw = str(row[county_col]).strip().title()
        county_raw = county_raw.replace("Dublin City And County", "Dublin")
        total_cases  = to_num(row[totals_col])
        heroin_cases = to_num(row[heroin_col]) if heroin_col else pd.NA
        opioid_cases = to_num(row[opioid_col]) if opioid_col else pd.NA
        records.append({
            "county":        county_raw,
            "year":          year,
            value_label:     total_cases,
            "heroin_cases":  heroin_cases,
            "opioid_cases":  opioid_cases,
        })

    result = pd.DataFrame(records)
    result[value_label]    = pd.to_numeric(result[value_label],    errors='coerce')
    result['heroin_cases'] = pd.to_numeric(result['heroin_cases'], errors='coerce')
    result['opioid_cases'] = pd.to_numeric(result['opioid_cases'], errors='coerce')
    print(f"  Extracted {len(result)} county rows for year {year}")
    return result


async def main():
    print("=" * 60)
    print("NDTRS County Treatment Demand Scraper")
    print("=" * 60)

    # Years to scrape: 2004–2024.
    YEARS = list(range(2004, 2025))
    print(f"  Years to scrape: {YEARS[0]}-{YEARS[-1]}")

    all_rows = []
    missing_years_all    = [y for y in YEARS if not os.path.exists(os.path.join(CACHE, f"ndtrs_all_{y}.csv"))]
    missing_years_opioid = [y for y in YEARS if not os.path.exists(os.path.join(CACHE, f"ndtrs_opioid_{y}.csv"))]

    if missing_years_all or missing_years_opioid:
        print(f"  Need to scrape {len(missing_years_all)} all-substance years + {len(missing_years_opioid)} opioid years")
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            ctx = await browser.new_context(viewport={"width": 1280, "height": 900})
            page = await ctx.new_page()

            for year in YEARS:
                cache_all    = os.path.join(CACHE, f"ndtrs_all_{year}.csv")
                cache_opioid = os.path.join(CACHE, f"ndtrs_opioid_{year}.csv")

                if not os.path.exists(cache_all):
                    raw = await query_ndtrs(page, 'all', f'All substances {year}', year=year)
                    if not raw.empty:
                        raw.to_csv(cache_all, index=False)

                if not os.path.exists(cache_opioid):
                    raw = await query_ndtrs(page, 'opioids', f'Opioids {year}', year=year)
                    if not raw.empty:
                        raw.to_csv(cache_opioid, index=False)

            await browser.close()

    # ── Load and combine all cached year files ────────────────────────────
    print("\n[3] Combining scraped year files ...")
    rows_all    = []
    rows_opioid = []
    for year in YEARS:
        ca = os.path.join(CACHE, f"ndtrs_all_{year}.csv")
        co = os.path.join(CACHE, f"ndtrs_opioid_{year}.csv")
        if os.path.exists(ca):
            yr = pd.read_csv(ca)
            if not yr.empty and 'cases_all' in yr.columns:
                rows_all.append(yr[['county','year','cases_all']])
        if os.path.exists(co):
            yr = pd.read_csv(co)
            if not yr.empty and 'cases_opioid' in yr.columns:
                rows_opioid.append(yr[['county','year','cases_opioid']])

    if not rows_all:
        print("ERROR: no all-substances data scraped.")
        sys.exit(1)

    df_all    = pd.concat(rows_all,    ignore_index=True)
    df_opioid = pd.concat(rows_opioid, ignore_index=True) if rows_opioid else pd.DataFrame()

    if not df_opioid.empty:
        df = df_all.merge(df_opioid, on=['county','year'], how='left')
    else:
        df = df_all.copy()
        df['cases_opioid'] = pd.NA

    df = df.sort_values(['county','year']).reset_index(drop=True)
    print(f"  Combined: {len(df)} rows, {df['county'].nunique()} counties, years {df['year'].min()}-{df['year'].max()}")
    print(df.head(6).to_string())

    df.to_csv(OUT_CSV, index=False)
    print(f"\n[4] Saved {len(df)} rows → {OUT_CSV}")

    print("[5] Building county summary ...")
    build_county_summary(df)
    print("Done.")


def build_county_summary(ndtrs: pd.DataFrame):
    """Join NDTRS demand data to the existing county-level deprivation summary."""
    # Load existing summary
    summary_path = os.path.join(DOCS, "summary.csv")
    if not os.path.exists(summary_path):
        print(f"  WARNING: {summary_path} not found — skipping join.")
        return

    existing = pd.read_csv(summary_path)
    existing.columns = [c.strip() for c in existing.columns]

    # Get most recent year's treatment data
    latest_year = int(ndtrs["year"].dropna().max())
    print(f"  Using most recent NDTRS year: {latest_year}")
    recent = ndtrs[ndtrs["year"] == latest_year].copy()

    # Normalise county names for joining
    def norm(s):
        s = str(s).strip().title()
        # existing summary uses COUNTY_ENGLISH (uppercase)
        return s

    recent["county_join"] = recent["county"].apply(norm)
    existing["county_join"] = existing["county"].apply(
        lambda s: str(s).strip().title()
    )

    # Add population and compute rates (guard against NA/missing population)
    recent["pop_2022"] = recent["county_join"].map(COUNTY_POP_2022)
    recent["cases_all"]    = pd.to_numeric(recent["cases_all"],    errors="coerce")
    recent["cases_opioid"] = pd.to_numeric(recent.get("cases_opioid", pd.NA), errors="coerce")
    pop = recent["pop_2022"].fillna(0)
    recent["cases_per_100k"] = (
        recent["cases_all"].where(pop > 0) / pop.where(pop > 0) * 100_000
    ).round(1)
    recent["opioid_per_100k"] = (
        recent["cases_opioid"].where(pop > 0) / pop.where(pop > 0) * 100_000
    ).round(1)

    # Merge with existing summary
    full = existing.merge(
        recent[["county_join", "cases_all", "cases_opioid",
                "cases_per_100k", "opioid_per_100k"]],
        on="county_join",
        how="left",
    ).drop(columns=["county_join"])

    full["ndtrs_year"] = latest_year

    full.to_csv(FULL_CSV, index=False)
    print(f"  Saved {len(full)} rows → {FULL_CSV}")
    print(f"\n  Top counties by treatment rate (per 100k):")
    if "cases_per_100k" in full.columns:
        top = full.nlargest(8, "cases_per_100k")[
            ["county","avg_dep_score","pct_underserved_sas","cases_per_100k","opioid_per_100k"]
        ]
        print(top.to_string(index=False))


if __name__ == "__main__":
    asyncio.run(main())
