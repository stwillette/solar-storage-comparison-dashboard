# Renewable Scenario Comparison Tool

Interactive financial modeling dashboard for grid-scale battery energy storage systems (BESS) and solar+storage across NYISO and ERCOT electricity markets. Built with Streamlit, it models lifetime project economics with 30+ configurable parameters — energy arbitrage, capacity revenue, ancillary services, solar co-location, offtake agreements, tax incentives, degradation, and mid-life battery replacement.

## Why This Exists

Battery storage is the fastest-growing asset class in U.S. electricity markets, but underwriting these projects is complex. Revenue comes from multiple stacked streams — energy arbitrage, capacity, ancillary services, and optionally colocated solar — each with different drivers, risks, and market structures.

NYISO and ERCOT represent two fundamentally different market designs: NYISO has a formal capacity market (ICAP) where capacity revenue can dominate battery economics, while ERCOT is energy-only, where scarcity pricing during a handful of extreme hours can make or break a project year. This dashboard lets you compare these two structures side by side, exploring how the same battery performs under very different rules.

## Quick Start

### Option 1: Run Online (No Installation)

The dashboard is deployed on Streamlit Community Cloud:

**[Launch Solar Storage Comparison Dashboard](https://solar-storage-comparison-dashboard-khutkoruzd6aqirce5smzz.streamlit.app/)**

### Option 2: Run Locally

```bash
git clone https://github.com/stwillette/solar-storage-comparison-dashboard.git
cd solar-storage-comparison-dashboard
pip install -r requirements.txt
streamlit run app.py
```

The dashboard will open at `http://localhost:8501`.

**Requirements:** Python 3.10+. If `pip` doesn't work, try `pip3 install -r requirements.txt`.

## What It Does

### Dashboard Views

**NYISO Market Analysis** — Full project economics for any of NYISO's 11 load zones (A through K). Zone J (NYC) and Zone K (Long Island) command premium capacity prices; upstate zones are scaled proportionally. Includes revenue waterfall, annual cash flow breakdown, degradation curves, sensitivity tornado chart, and downloadable cash flow tables.

**ERCOT Market Analysis** — Same depth for ERCOT's 5 zones (Houston, North, South, West, Panhandle). Since ERCOT has no capacity market, the "capacity" revenue stream reflects RTC+B co-optimization value and scarcity pricing. A dedicated scarcity-hours slider models how many extreme-price hours ($1,000–$3,000/MWh) occur per year.

**Market Comparison** — Side-by-side NYISO vs. ERCOT with matched assumptions. Compares NPV, IRR, payback, and revenue per kW-yr. Includes a Merchant vs. Contracted comparison showing how offtake agreements affect economics in each market.

**Hourly and Daily Performance** — Drill into a specific day to see the 24-hour LMP price curve and the battery's charge/discharge dispatch. Monthly average price profiles reveal the duck curve shape driven by renewable penetration.

**Support & Definitions** — Glossary of market concepts, parameter definitions, zone reference tables, and chart interpretation guide.

### Revenue Streams

| Stream | NYISO | ERCOT |
|---|---|---|
| Energy Arbitrage | Daily charge-low / discharge-high against synthetic LMPs | Same, plus configurable scarcity hours ($1,000–$3,000/MWh) |
| Capacity | ICAP with zone multipliers, seasonal accreditation (80% summer / 60% winter default) | RTC+B & Scarcity Credits (~$6.6/kW-yr, no accreditation) |
| Ancillary Services | Regulation + spinning reserves | Regulation + responsive reserves + DRRS (4hr+ batteries) |
| Solar (optional) | Colocated generation at LMP + Tier 1 RECs (~$25/MWh) + PTC | Generation at LMP + RECs (~$1/MWh) + PTC |
| Offtake / Tolling | Fixed $/kW-yr with financing benefit (WACC reduction) | Same structure, lower default rates |

### Key Financial Metrics

NPV, IRR (Newton's method), payback period, LCOS (Levelized Cost of Storage), average revenue per kW-yr, and full after-tax cash flows with MACRS depreciation, ITC, PTC, and battery replacement economics.

## Architecture

```
app.py                  Streamlit UI — sidebar controls, 5 page views, Plotly charts (1,663 lines)
  └─ battery_model.py   Financial engine — year-by-year cash flows, tax, depreciation (594 lines)
       └─ data_generator.py   Synthetic market data — hourly LMPs, capacity prices, ancillary rates (567 lines)
```

`app.py` collects user inputs from the sidebar, passes them as kwargs to `run_full_financial_model()` in `battery_model.py`, which loops year-by-year over the project life. Each year it calls `data_generator.py` to produce 8,760 hourly price profiles, then computes revenue from each stream, subtracts costs, applies tax logic, and returns structured cash flows. Results are cached via `@st.cache_data` so page switching doesn't retrigger computation.

## Configurable Parameters (30+)

| Section | Key Parameters | Notes |
|---|---|---|
| Battery Config | Power (MW), duration (hrs), solar co-location | Presets for 4hr, 8hr, solar+storage, custom |
| Offtake Agreement | Tolling rate, contracted %, term, escalator | Per-market defaults (NYISO $150, ERCOT $120/kW-yr) |
| Financial | Project life, WACC, ITC, PTC, tax rate, CapEx | 30yr default for solar+storage, 20yr standalone |
| Market Parameters | Base energy price, demand growth, renewable penetration, solar CF | Per-market tabs with calibrated defaults |
| Capacity Accreditation | Battery summer/winter %, solar summer/winter % | NYISO only — ERCOT bypasses |
| NYISO Capacity Prices | Zone J summer/winter $/kW-mo, annual escalation | Zone multipliers applied automatically |
| Ancillary Services | Regulation %, reserve %, DRRS % (ERCOT only) | DRRS requires 4hr+ duration |
| Degradation | Annual %, augmentation year/%, roundtrip efficiency | Mid-life battery replacement for solar+storage |
| Solar | CapEx, O&M, capacity factor, tax credit (ITC vs PTC), RECs | Per-market CF defaults (NYISO 18%, ERCOT 24%) |

## Key Modeling Features

### Per-Market Calibration
NYISO and ERCOT have separate default assumptions for energy prices, demand growth, renewable penetration, solar capacity factors, tolling rates, and REC prices — reflecting the structural differences between these markets.

### Offtake Agreements with Financing Benefit
The offtake model replaces merchant energy + capacity revenue for the contracted share with a fixed tolling payment. Critically, it also models the **financing benefit**: contracted revenue reduces project risk, enabling a blended WACC reduction (default 1.5%) that improves NPV — matching how offtake agreements create value in real project finance.

### Battery Replacement (Solar+Storage)
For 30-year solar+storage projects, a mid-life battery replacement (default year 15 at 50% of original cost) resets degradation, triggers its own 5-year MACRS depreciation schedule, and qualifies for a separate ITC. This accurately models the economics of long-duration solar projects that outlive their first battery.

### Solar Capacity Factors
Market-specific solar capacity factors (NYISO default 18%, ERCOT default 24%) scale the physics-based solar profile to match real-world output data. NYISO's lower factor reflects higher latitude and cloud cover; ERCOT benefits from stronger irradiance.

### LCOS (Levelized Cost of Storage)
PV(all costs) / PV(total MWh discharged) — the standard metric for comparing storage economics across configurations and markets.

## Calibration Sources

| Assumption | Value | Reference |
|---|---|---|
| 4-hour LFP CapEx | ~$1,300/kW | NREL 2025, EIA AEO2025 |
| 8-hour LFP CapEx | ~$2,100/kW | NREL 2025 (scaled) |
| NYISO Zone J summer ICAP | ~$8/kW-mo | Recent NYISO auction data |
| NYISO Zone J winter ICAP | ~$12/kW-mo | Recent NYISO auction data |
| ERCOT capacity-equivalent | ~$6.6/kW-yr | RTC+B / scarcity analysis |
| Roundtrip efficiency (LFP) | 87% | Industry standard |
| Annual degradation | 2.5% | LFP warranty benchmarks |
| NYISO solar capacity factor | 18% | EIA / NYISO 2024 actual: 17.7% |
| ERCOT solar capacity factor | 24% | EIA / ERCOT 2024 est: ~23% |
| NYISO Tier 1 RECs | $25/MWh | NY Clean Energy Standard |
| ERCOT RECs | $1/MWh | TX market (overbuild vs RPS) |
| ITC | 30% | Inflation Reduction Act |
| PTC | $28/MWh | IRA base rate (inflation-adjusted) |

## Using Real Data

The dashboard uses synthetic data calibrated to market patterns. To plug in actuals:

1. Download hourly LBMP data from [NYISO OASIS](http://mis.nyiso.com/public/)
2. Download ICAP/UCAP auction results from [NYISO ICAP Market](https://www.nyiso.com/installed-capacity-market)
3. Replace the `generate_hourly_prices()` calls in `battery_model.py` with your data loader, matching the expected DataFrame schema (columns: `timestamp`, `hour`, `month`, `day_of_year`, `lmp`)

## Project Structure

```
├── app.py               Streamlit dashboard — UI, charts, page routing
├── battery_model.py     Financial model — cash flows, tax, depreciation, IRR
├── data_generator.py    Market data — hourly LMPs, capacity prices, ancillary rates
├── requirements.txt     Python dependencies
├── METHODOLOGY.md       Detailed modeling methodology and assumptions
└── README.md            This file
```

## Technology

Python 3.10+, Streamlit, Plotly, Pandas, NumPy. No database — all computation is in-memory. Runs locally or on Streamlit Cloud.
