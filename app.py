"""
Renewable Scenario Comparison Tool
NYISO & ERCOT Market Comparison
 
Interactive Streamlit dashboard for comparing lifetime economics
across battery storage, solar, and solar+storage configurations.
"""
 
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import hashlib
import json
 
from battery_model import run_full_financial_model, run_sensitivity
from data_generator import NYISO_ZONES, ERCOT_ZONES
 
# ─── Page Config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Renewable Scenario Comparison Tool",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)
 
# ─── Custom CSS ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .stMetric {
        padding: 15px;
        border-radius: 10px;
        border: 1px solid rgba(128, 128, 128, 0.3);
        background-color: rgba(128, 128, 128, 0.06);
    }
    .main .block-container {
        padding-top: 1.5rem;
        max-width: 100%;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        padding: 8px 20px;
        border-radius: 5px;
    }
</style>
""", unsafe_allow_html=True)
 
 
# ─── Cached model runner ─────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def cached_model_run(**kwargs):
    """Cache model results to avoid recomputation across tabs."""
    return run_full_financial_model(**kwargs)
 
 
# ─── Sidebar ──────────────────────────────────────────────────────────────────
st.sidebar.title("⚡ Battery Configuration")
 
# Battery type selection
battery_config = st.sidebar.radio(
    "Battery Configuration",
    ["Solar + 4-Hour", "Solar + 8-Hour",
     "Standalone 4-Hour", "Standalone 8-Hour", "Custom"],
    index=0,
)
 
# Set defaults based on selection
config_defaults = {
    "Solar + 4-Hour": {"mw": 100, "mwh": 400, "solar": True, "solar_mw": 100},
    "Solar + 8-Hour": {"mw": 100, "mwh": 800, "solar": True, "solar_mw": 100},
    "Standalone 4-Hour": {"mw": 100, "mwh": 400, "solar": False, "solar_mw": 0},
    "Standalone 8-Hour": {"mw": 100, "mwh": 800, "solar": False, "solar_mw": 0},
    "Custom": {"mw": 100, "mwh": 400, "solar": False, "solar_mw": 0},
}
defaults = config_defaults[battery_config]
 
if battery_config == "Custom":
    battery_mw = st.sidebar.number_input("Battery Power (MW)", 10, 500, 100, 10)
    duration = st.sidebar.slider("Duration (hours)", 1, 12, 4)
    battery_mwh = battery_mw * duration
    include_solar = st.sidebar.checkbox("Add Colocated Solar", False)
    solar_mw = st.sidebar.number_input("Solar Capacity (MW)", 10, 500, 100, 10) if include_solar else 0
else:
    battery_mw = defaults["mw"]
    battery_mwh = defaults["mwh"]
    include_solar = defaults["solar"]
    solar_mw = defaults["solar_mw"]
 
st.sidebar.markdown(f"**System:** {battery_mw} MW / {battery_mwh} MWh"
                     + (f" + {solar_mw} MW Solar" if include_solar else ""))
 
# ─── Revenue Structure ────────────────────────────────────────────────────────
st.sidebar.markdown("---")
st.sidebar.subheader("Revenue Structure")
include_offtake = st.sidebar.toggle(
    "Include Offtake Agreement",
    value=False,
    help="Enable to model a contracted tolling agreement on a portion of the project. "
         "The contracted share earns a fixed $/kW-yr payment regardless of market prices, "
         "reducing merchant risk. The remaining capacity stays fully merchant."
)
 
if include_offtake:
    st.sidebar.caption(
        "**Tolling Agreement** — A fixed annual payment ($/kW-yr) for the contracted "
        "share of battery capacity. The offtaker controls dispatch for that share and "
        "pays a guaranteed rate. The developer retains merchant exposure on the uncontracted portion. "
        "Note: ERCOT defaults to a lower tolling rate than NYISO due to market saturation."
    )
 
    offtake_tab_nyiso, offtake_tab_ercot = st.sidebar.tabs(["NYISO", "ERCOT"])
 
    with offtake_tab_nyiso:
        nyiso_offtake_pct = st.slider(
            "Contracted Share (%)", 10, 100, 70, 5, key="nyiso_offtake_pct",
            help="Percentage of the battery's capacity under the tolling agreement. "
                 "70% contracted / 30% merchant is a common structure for financed projects."
        ) / 100
        nyiso_offtake_price = st.slider(
            "Tolling Rate ($/kW-yr)", 50, 400, 120, 5, key="nyiso_offtake_price",
            help="Fixed annual payment per kW of contracted capacity. "
                 "This replaces energy arbitrage + capacity revenue for the contracted share. "
                 "Offtake agreements also reduce project risk, enabling cheaper financing (lower WACC). "
                 "Recent NYISO tolling rates: ~$120–175/kW-yr for 4hr systems."
        )
        nyiso_offtake_term = st.slider(
            "Contract Term (years)", 5, 30, 20, 1, key="nyiso_offtake_term",
            help="Duration of the offtake agreement. Defaults to full project life. "
                 "If shorter than project life, the contracted share reverts to "
                 "full merchant pricing for the remaining years."
        )
        nyiso_offtake_esc = st.slider(
            "Annual Escalator (%)", 0.0, 3.0, 1.5, 0.5, key="nyiso_offtake_esc",
            help="Annual escalation rate applied to the tolling rate (e.g., CPI-linked)."
        ) / 100
 
    with offtake_tab_ercot:
        ercot_offtake_pct = st.slider(
            "Contracted Share (%)", 10, 100, 70, 5, key="ercot_offtake_pct",
            help="Percentage of the battery's capacity under the tolling agreement."
        ) / 100
        ercot_offtake_price = st.slider(
            "Tolling Rate ($/kW-yr)", 10, 400, 55, 5, key="ercot_offtake_price",
            help="Fixed annual payment per kW of contracted capacity. "
                 "ERCOT tolling rates tend to be lower than NYISO due to the lack of a "
                 "capacity market — recent range: ~$100–150/kW-yr for 4hr systems."
        )
        ercot_offtake_term = st.slider(
            "Contract Term (years)", 5, 30, 20, 1, key="ercot_offtake_term",
            help="Duration of the offtake agreement. Defaults to full project life."
        )
        ercot_offtake_esc = st.slider(
            "Annual Escalator (%)", 0.0, 3.0, 1.5, 0.5, key="ercot_offtake_esc",
            help="Annual escalation rate applied to the tolling rate (e.g., CPI-linked)."
        ) / 100
 
    # Pack into per-market dicts for build_kwargs
    offtake_params = {
        "NYISO": dict(pct=nyiso_offtake_pct, price=nyiso_offtake_price,
                       term=nyiso_offtake_term, esc=nyiso_offtake_esc),
        "ERCOT": dict(pct=ercot_offtake_pct, price=ercot_offtake_price,
                       term=ercot_offtake_term, esc=ercot_offtake_esc),
    }
else:
    offtake_params = {
        "NYISO": dict(pct=0.0, price=120.0, term=20, esc=0.015),
        "ERCOT": dict(pct=0.0, price=55.0, term=20, esc=0.015),
    }
 
# ─── Financial Parameters ─────────────────────────────────────────────────────
st.sidebar.markdown("---")
st.sidebar.subheader("Financial Parameters")
 
# Default project life: 30 years for solar+storage, 20 for standalone battery
default_project_life = 30 if include_solar else 20
project_life = st.sidebar.slider("Project Life (years)", 5, 40, default_project_life)
wacc = st.sidebar.slider("WACC (%)", 4.0, 15.0, 8.0, 0.5) / 100
itc_pct = st.sidebar.slider("ITC (%)", 0, 50, 30, 5) / 100
tax_rate = st.sidebar.slider("Tax Rate (%)", 0, 40, 21, 1) / 100
 
# All-in battery capital cost ($/kW) — single metric combining energy + power components
# Defaults based on NREL 2025 / EIA AEO2025 for LFP systems:
#   4-hour: ~$1,300/kW  |  8-hour: ~$2,100/kW
duration = battery_mwh / battery_mw
if duration <= 4:
    default_capex_kw = 1300
elif duration <= 6:
    default_capex_kw = 1700
elif duration <= 8:
    default_capex_kw = 2100
else:
    default_capex_kw = 2400
battery_capex_per_kw = st.sidebar.slider(
    "Battery Capital Cost ($/kW)", 400, 4000, default_capex_kw, 50,
    help=f"All-in installed cost per kW for a {duration:.0f}-hour system. "
         "Reference: ~$1,300/kW (4hr) and ~$2,100/kW (8hr) per NREL 2025 / EIA AEO2025."
)
 
if include_solar:
    solar_capex_per_kw = st.sidebar.slider("Solar Capital Cost ($/kW)", 400, 4000, 1000, 50)
    solar_om_per_kw = st.sidebar.slider("Solar O&M ($/kW-yr)", 5, 40, 18, 1)
    solar_tax_credit = st.sidebar.radio(
        "Solar Tax Credit", ["PTC", "ITC"], index=0, horizontal=True,
        help="Choose PTC (per-MWh credit on generation for 10 years) or ITC (upfront % of CapEx). "
             "Most utility-scale solar elects PTC under IRA as it is typically more valuable."
    )
    if solar_tax_credit == "PTC":
        ptc_per_mwh = st.sidebar.slider(
            "PTC ($/MWh)", 10.0, 40.0, 28.0, 1.0,
            help="Production Tax Credit per MWh of solar generation. "
                 "IRA base rate ~$28/MWh (2025, inflation-adjusted). Range reflects potential adders."
        )
    else:
        ptc_per_mwh = 0.0
 
    nyiso_rec_price = st.sidebar.slider(
        "NYISO REC Price ($/MWh)", 0.0, 50.0, 25.0, 1.0,
        help="NY Tier 1 Renewable Energy Credits (RECs) are certificates "
             "representing the environmental attributes of 1 MWh of eligible "
             "renewable generation. Tier 1 RECs are procured by NYSERDA under "
             "the Clean Energy Standard to meet New York's 70% renewable "
             "electricity target by 2030. Recent prices: ~$20–30/MWh."
    )
    ercot_rec_price = st.sidebar.slider(
        "ERCOT REC Price ($/MWh)", 0.0, 5.0, 1.0, 0.5,
        help="Texas RECs trade at very low prices (<\\$1–2/MWh) due to "
             "massive renewable overbuild relative to the state RPS mandate. "
             "ERCOT REC revenue is typically negligible."
    )
    rec_prices = {"NYISO": nyiso_rec_price, "ERCOT": ercot_rec_price}
else:
    solar_capex_per_kw = 1000
    solar_om_per_kw = 18
    solar_tax_credit = "PTC"
    ptc_per_mwh = 28.0
    rec_prices = {"NYISO": 25.0, "ERCOT": 1.0}
 
st.sidebar.markdown("**MACRS Depreciation**")
macrs_schedule = st.sidebar.radio("MACRS Schedule", ["5yr", "7yr"], index=0, horizontal=True)
bonus_depreciation = st.sidebar.slider("Bonus Depreciation (%)", 0, 100, 0, 10) / 100
 
# ─── Market Parameters (per-market) ──────────────────────────────────────────
st.sidebar.markdown("---")
st.sidebar.subheader("Market Parameters")
st.sidebar.caption(
    "NYISO and ERCOT use different default assumptions reflecting each market's structure. "
    "ERCOT has lower base energy prices but higher renewable penetration, demand growth, "
    "and solar capacity factors due to stronger irradiance at lower latitudes."
)
 
mkt_tab_nyiso, mkt_tab_ercot = st.sidebar.tabs(["NYISO", "ERCOT"])
 
with mkt_tab_nyiso:
    nyiso_base_energy_price = st.slider(
        "Base Energy Price ($/MWh)", 15.0, 80.0, 40.0, 1.0, key="nyiso_energy_price",
        help="Average NYISO wholesale LMP. Zone J (NYC) typically runs $35–50/MWh."
    )
    nyiso_demand_growth = st.slider(
        "Demand Growth (%/yr)", 0.0, 5.0, 2.0, 0.5, key="nyiso_demand_growth",
        help="NY load growth driven by electrification mandates, data centers, and EV adoption."
    ) / 100
    nyiso_renewable_penetration = st.slider(
        "Renewable Penetration (%)", 10, 80, 30, 5, key="nyiso_renew_pct",
        help="Share of NY generation from wind and solar. Higher penetration deepens the duck curve."
    ) / 100
    nyiso_solar_cf = st.slider(
        "Solar Capacity Factor (%)", 10, 35, 18, 1, key="nyiso_solar_cf",
        help="Annual average solar capacity factor. NY utility-scale solar averages ~17-19% "
             "due to higher latitude and cloud cover (EIA/NYISO 2024 actual: 17.7%)."
    ) / 100
 
with mkt_tab_ercot:
    ercot_base_energy_price = st.slider(
        "Base Energy Price ($/MWh)", 15.0, 80.0, 30.0, 1.0, key="ercot_energy_price",
        help="Average ERCOT wholesale LMP. Texas typically runs $25–35/MWh outside scarcity events."
    )
    ercot_demand_growth = st.slider(
        "Demand Growth (%/yr)", 0.0, 5.0, 2.5, 0.5, key="ercot_demand_growth",
        help="Texas load growth driven by population growth, data centers, and industrial expansion."
    ) / 100
    ercot_renewable_penetration = st.slider(
        "Renewable Penetration (%)", 10, 80, 45, 5, key="ercot_renew_pct",
        help="Share of ERCOT generation from wind and solar. Texas has very high wind/solar penetration."
    ) / 100
    ercot_solar_cf = st.slider(
        "Solar Capacity Factor (%)", 10, 35, 24, 1, key="ercot_solar_cf",
        help="Annual average solar capacity factor. Texas utility-scale solar averages ~22-26% "
             "thanks to strong irradiance at lower latitudes (EIA/ERCOT 2024 est: ~23%)."
    ) / 100
 
st.sidebar.caption(
    "ERCOT only — A large share of ERCOT battery revenue comes from a small number of "
    "extreme price hours (\$1,000–\$3,000/MWh)."
)
ercot_scarcity_hours = st.sidebar.slider(
    "Scarcity Hours / Year (ERCOT only)", 0, 200, 25, 5,
    help="Number of hours per year ERCOT prices spike to $1,000–$3,000/MWh. "
         "Typically ~10-30 hours in a normal year; can exceed 50+ during extreme weather. "
         "This setting only affects ERCOT scenarios."
)
 
# Pack per-market parameters
market_params = {
    "NYISO": dict(
        base_energy_price=nyiso_base_energy_price,
        demand_growth_rate=nyiso_demand_growth,
        renewable_penetration=nyiso_renewable_penetration,
        ercot_scarcity_hours=0,
        solar_capacity_factor=nyiso_solar_cf,
    ),
    "ERCOT": dict(
        base_energy_price=ercot_base_energy_price,
        demand_growth_rate=ercot_demand_growth,
        renewable_penetration=ercot_renewable_penetration,
        ercot_scarcity_hours=ercot_scarcity_hours,
        solar_capacity_factor=ercot_solar_cf,
    ),
}
 
# ─── Battery Accreditation (NYISO only) ──────────────────────────────────────
st.sidebar.markdown("---")
st.sidebar.subheader("Capacity Accreditation (NYISO only)")
st.sidebar.caption(
    "Accreditation factors affect NYISO capacity revenue only. "
    "ERCOT has no capacity market."
)
battery_accred_summer = st.sidebar.slider(
    "Battery Summer Accred. (Apr-Oct) %", 0, 100, 80, 5
) / 100
battery_accred_winter = st.sidebar.slider(
    "Battery Winter Accred. (Nov-Mar) %", 0, 100, 60, 5
) / 100
 
# ─── Solar Accreditation (NYISO only) ───────────────────────────────────────
if include_solar:
    st.sidebar.markdown("---")
    st.sidebar.subheader("Solar Accreditation (NYISO only)")
    solar_accred_summer = st.sidebar.slider(
        "Solar Summer Accred. (Apr-Oct) %", 0, 100, 15, 5
    ) / 100
    solar_accred_winter = st.sidebar.slider(
        "Solar Winter Accred. (Nov-Mar) %", 0, 100, 5, 5
    ) / 100
else:
    solar_accred_summer = 0.15
    solar_accred_winter = 0.05
 
# ─── Capacity Prices (NYISO) ─────────────────────────────────────────────────
st.sidebar.markdown("---")
st.sidebar.subheader("NYISO Capacity Prices ($/kW-month)")
st.sidebar.caption(
    "Base prices for Zone J (NYC). Other zones are automatically scaled using "
    "zone-specific capacity multipliers (e.g., upstate ~30-40% of Zone J)."
)
cap_price_summer = st.sidebar.slider(
    "Zone J Summer (Apr-Oct)", 0.0, 25.0, 8.0, 0.5,
    help="NYISO Zone J recent summer ICAP: ~$6-10/kW-mo."
)
cap_price_winter = st.sidebar.slider(
    "Zone J Winter (Nov-Mar)", 0.0, 30.0, 12.0, 0.5,
    help="NYISO Zone J recent winter ICAP: ~$8-14/kW-mo."
)
cap_price_growth = st.sidebar.slider(
    "Annual Capacity Price Escalation (%)", -2.0, 5.0, 1.0, 0.5,
    help="Annual growth rate applied to capacity prices over the project life."
) / 100
 
# ─── Ancillary Services ──────────────────────────────────────────────────────
st.sidebar.markdown("---")
st.sidebar.subheader("Ancillary Services")
regulation_pct = st.sidebar.slider("Regulation Participation (%)", 0, 50, 15, 5) / 100
reserve_pct = st.sidebar.slider("Reserve Participation (%)", 0, 50, 10, 5) / 100
drrs_pct = st.sidebar.slider(
    "DRRS Participation (%) — ERCOT only", 0, 50, 10, 5,
    help="Dispatchable Reliability Reserve Service (DRRS). ERCOT-only ancillary service "
         "requiring 4-hour minimum battery duration. Provides reliability reserves for "
         "managing generation variability and forced outages."
) / 100
 
# ─── Degradation ──────────────────────────────────────────────────────────────
st.sidebar.markdown("---")
st.sidebar.subheader("Degradation & Battery Lifecycle")
annual_degradation = st.sidebar.slider("Annual Degradation (%)", 0.5, 5.0, 2.5, 0.5) / 100
 
# Battery replacement for solar+storage (longer project lives)
if include_solar:
    default_replacement_year = project_life // 2
    battery_replacement_year = st.sidebar.slider(
        "Battery Replacement Year (0=none)", 0, project_life, default_replacement_year,
        help="Year to replace the battery for solar+storage projects with longer lifetimes. "
             "Solar panels last 30+ years but batteries degrade faster. "
             f"Default: year {default_replacement_year} (halfway through {project_life}-year project)."
    )
    battery_replacement_cost_pct = st.sidebar.slider(
        "Replacement Cost (% of original)", 20, 100, 50, 5,
        help="Battery replacement cost as a percentage of the original battery CapEx. "
             "Future battery costs are expected to decline significantly — 50% is a reasonable "
             "estimate for replacement in ~15 years."
    ) / 100
else:
    battery_replacement_year = 0
    battery_replacement_cost_pct = 0.50
 
augmentation_year = st.sidebar.slider("Augmentation Year (0=none)", 0, 20, 10)
augmentation_pct = st.sidebar.slider("Augmentation Restore (%)", 0, 30, 15, 5) / 100
roundtrip_efficiency = st.sidebar.slider("Roundtrip Efficiency (%)", 75, 95, 87, 1) / 100
 
 
# ─── Build shared kwargs ─────────────────────────────────────────────────────
def build_kwargs(market: str, zone_name: str) -> dict:
    mkt = market_params[market]
    return dict(
        battery_mw=battery_mw,
        battery_mwh=battery_mwh,
        battery_capex_per_kw=battery_capex_per_kw,
        fixed_om_per_kw_yr=12.5,
        variable_om_per_mwh=2.5,
        roundtrip_efficiency=roundtrip_efficiency,
        annual_degradation=annual_degradation,
        augmentation_year=augmentation_year,
        augmentation_pct=augmentation_pct,
        augmentation_cost_per_kwh=100.0,
        battery_replacement_year=battery_replacement_year,
        battery_replacement_cost_pct=battery_replacement_cost_pct,
        project_life=project_life,
        wacc=wacc,
        tax_rate=tax_rate,
        itc_pct=itc_pct,
        bonus_depreciation_pct=bonus_depreciation,
        macrs_schedule=macrs_schedule,
        market=market,
        zone_name=zone_name,
        base_energy_price=mkt["base_energy_price"],
        demand_growth_rate=mkt["demand_growth_rate"],
        renewable_penetration=mkt["renewable_penetration"],
        battery_accred_summer=battery_accred_summer,
        battery_accred_winter=battery_accred_winter,
        solar_accred_summer=solar_accred_summer,
        solar_accred_winter=solar_accred_winter,
        regulation_pct=regulation_pct,
        reserve_pct=reserve_pct,
        drrs_pct=drrs_pct,
        cap_price_summer=cap_price_summer,
        cap_price_winter=cap_price_winter,
        cap_price_growth=cap_price_growth,
        include_solar=include_solar,
        solar_mw=solar_mw if include_solar else 0,
        solar_capex_per_kw=solar_capex_per_kw,
        solar_om_per_kw_yr=solar_om_per_kw,
        solar_degradation_rate=0.005,
        solar_capacity_factor=mkt["solar_capacity_factor"],
        ercot_scarcity_hours=mkt["ercot_scarcity_hours"],
        solar_tax_credit=solar_tax_credit,
        ptc_per_mwh=ptc_per_mwh,
        rec_price_per_mwh=rec_prices.get(market, 25.0),
        include_offtake=include_offtake,
        offtake_pct=offtake_params[market]["pct"],
        offtake_price_per_kw_yr=offtake_params[market]["price"],
        offtake_term=offtake_params[market]["term"],
        offtake_escalator=offtake_params[market]["esc"],
    )
 
 
# ═══════════════════════════════════════════════════════════════════════════════
# MAIN CONTENT - Use page selector instead of tabs to avoid running all at once
# ═══════════════════════════════════════════════════════════════════════════════
 
st.title("⚡ Renewable Scenario Comparison Tool")
st.markdown(
    "<div style='background: rgba(255,255,255,0.05); border-radius: 8px; padding: 12px 16px; margin-bottom: 12px; font-size: 0.92em; line-height: 1.6;'>"
    "Model the lifetime economics of <b>standalone battery storage</b> and "
    "<b>solar+storage hybrid</b> configurations across <b>NYISO</b> and <b>ERCOT</b> markets. "
    "Adjust capacity pricing, energy prices, ancillary service allocations, ITC/PTC tax credits, "
    "tolling/offtake agreements, demand growth assumptions, renewable penetration levels, "
    "and NY REC pricing using the sidebar controls. "
    "Compare NPV, IRR, and payback across zones, run sensitivity analyses, and drill into hourly dispatch patterns. "
    "The project defaults as a <b>merchant plant</b> — toggle the offtake agreement in the sidebar to model contracted revenue."
    "<br><span style='color: #FF9800; font-size: 0.88em;'>&#9888; This tool uses synthetic price curves and "
    "stylized dispatch profiles — it is not based on an actual production cost model. "
    "Results are intended for scenario comparison, not investment-grade forecasting.</span>"
    "</div>",
    unsafe_allow_html=True,
)
 
# Use a selectbox for page navigation (only runs the selected page's code)
page = st.radio(
    "Select View",
    ["📊 Market Comparison", "🏙️ NYISO", "🤠 ERCOT", "⏰ Hourly and Daily Performance", "📖 Support & Definitions"],
    horizontal=True,
    label_visibility="collapsed",
)
 
 
# ═══════════════════════════════════════════════════════════════════════════════
# HELPER: Render a market dashboard
# ═══════════════════════════════════════════════════════════════════════════════
 
def render_market_dashboard(market: str, zones: dict):
    """Render the full dashboard for a given market."""
    # Zone selector
    zone_name = st.selectbox(
        f"Select {market} Zone",
        list(zones.keys()),
        index=list(zones.keys()).index(
            "Zone G (Hudson Valley)" if market == "NYISO" else "North"
        ),
        key=f"{market}_zone",
    )
 
    # Run model (cached)
    kwargs = build_kwargs(market, zone_name)
 
    with st.spinner(f"Running {market} model..."):
        result = cached_model_run(**kwargs)
 
    cf = result["cashflows"]
    summary = result["summary"]
    df = pd.DataFrame(cf)
 
    # ─── Offtake banner ──────────────────────────────────────────────────
    if include_offtake:
        mkt_offtake = offtake_params[market]
        merchant_pct = int((1 - mkt_offtake["pct"]) * 100)
        contracted_pct = int(mkt_offtake["pct"] * 100)
        st.info(
            f"**Tolling Agreement Active ({market})** — {contracted_pct}% contracted at "
            f"${mkt_offtake['price']:.0f}/kW-yr "
            f"({mkt_offtake['esc']*100:.1f}% annual escalator, {mkt_offtake['term']}-yr term) · "
            f"{merchant_pct}% merchant",
            icon="📝",
        )
    else:
        st.caption("💡 Revenue structure: **100% Merchant** — Toggle *Include Offtake Agreement* in the sidebar to model contracted revenue.")
 
    # ─── KPI Header ──────────────────────────────────────────────────────
    col1, col2, col3, col4, col5 = st.columns(5)
 
    with col1:
        npv_m = summary["npv"] / 1e6
        st.metric("NPV", f"${npv_m:,.1f}M",
                   delta="Positive" if npv_m > 0 else "Negative")
    with col2:
        irr_val = summary["irr"]
        st.metric("IRR", f"{irr_val:.1f}%" if irr_val else "N/A")
    with col3:
        pb = summary["payback_years"]
        st.metric("Payback", f"{pb} yrs" if pb else ">Project Life")
    with col4:
        st.metric("Avg Rev/kW-yr", f"${summary['avg_revenue_per_kw_yr']:.0f}")
    with col5:
        capex_m = summary["total_capex"] / 1e6
        st.metric("Total CapEx", f"${capex_m:,.1f}M")
 
    # ─── Sub-tabs ────────────────────────────────────────────────────────
    t1, t2, t3, t4, t5 = st.tabs([
        "Revenue & Cash Flows", "Degradation", "Revenue Breakdown",
        "Sensitivity", "Data Table"
    ])
 
    # ── Tab 1: Revenue & Cash Flows ──────────────────────────────────────
    with t1:
        fig_rev = go.Figure()
 
        fig_rev.add_trace(go.Bar(
            x=df["calendar_year"], y=df["energy_revenue"] / 1e6,
            name="Battery Energy", marker_color="#2196F3",
        ))
        if include_solar:
            fig_rev.add_trace(go.Bar(
                x=df["calendar_year"], y=df["solar_revenue"] / 1e6,
                name="Solar Energy", marker_color="#FDD835",
            ))
        cap_label = "RTC+B & Scarcity Credits" if market == "ERCOT" else "Capacity"
        fig_rev.add_trace(go.Bar(
            x=df["calendar_year"], y=df["capacity_revenue"] / 1e6,
            name=cap_label, marker_color="#4CAF50",
        ))
        fig_rev.add_trace(go.Bar(
            x=df["calendar_year"], y=df["ancillary_revenue"] / 1e6,
            name="Ancillary Services", marker_color="#FF9800",
        ))
        if include_solar and market == "NYISO" and "rec_revenue" in df.columns:
            fig_rev.add_trace(go.Bar(
                x=df["calendar_year"], y=df["rec_revenue"] / 1e6,
                name="REC Revenue", marker_color="#66BB6A",
            ))
        if include_offtake and "offtake_revenue" in df.columns:
            fig_rev.add_trace(go.Bar(
                x=df["calendar_year"], y=df["offtake_revenue"] / 1e6,
                name="Contracted (Tolling)", marker_color="#AB47BC",
            ))
 
        fig_rev.update_layout(
            barmode="stack",
            title=f"{market} Annual Revenue by Stream",
            xaxis_title="Year",
            yaxis_title="Revenue ($M)",
            template="plotly_dark",
            height=500,
            legend=dict(orientation="h", yanchor="bottom", y=-0.20, xanchor="center", x=0.5, font=dict(size=12)),
            margin=dict(b=100),
        )
        st.plotly_chart(fig_rev, use_container_width=True)
 
        # Cumulative cash flow
        cumulative = np.cumsum(df["after_tax_cashflow"].values) / 1e6
 
        fig_cf = go.Figure()
        colors = ["#f44336" if v < 0 else "#4CAF50" for v in cumulative]
        fig_cf.add_trace(go.Bar(
            x=df["calendar_year"], y=cumulative,
            marker_color=colors,
            name="Cumulative Cash Flow",
        ))
        fig_cf.add_hline(y=0, line_dash="dash", line_color="white", opacity=0.5)
        fig_cf.update_layout(
            title="Cumulative After-Tax Cash Flow",
            xaxis_title="Year",
            yaxis_title="Cumulative CF ($M)",
            template="plotly_dark",
            height=400,
        )
        st.plotly_chart(fig_cf, use_container_width=True)
 
    # ── Tab 2: Degradation ───────────────────────────────────────────────
    with t2:
        fig_deg = go.Figure()
        fig_deg.add_trace(go.Scatter(
            x=df["calendar_year"],
            y=df["degradation_factor"] * 100,
            mode="lines+markers",
            name="Effective Capacity",
            line=dict(color="#4fc3f7", width=3),
            marker=dict(size=6),
        ))
 
        if augmentation_year > 0:
            aug_year_cal = df.iloc[0]["calendar_year"] + augmentation_year - 1
            fig_deg.add_vline(
                x=aug_year_cal, line_dash="dash", line_color="#FF9800",
                annotation_text="Augmentation",
                annotation_position="top right",
            )
 
        fig_deg.update_layout(
            title="Battery Capacity Degradation Over Time",
            xaxis_title="Year",
            yaxis_title="Effective Capacity (%)",
            template="plotly_dark",
            height=400,
            yaxis_range=[0, 105],
        )
        st.plotly_chart(fig_deg, use_container_width=True)
 
        effective_mwh = df["degradation_factor"] * battery_mwh
        fig_mwh = go.Figure()
        fig_mwh.add_trace(go.Scatter(
            x=df["calendar_year"], y=effective_mwh,
            fill="tozeroy", fillcolor="rgba(79, 195, 247, 0.2)",
            line=dict(color="#4fc3f7", width=2),
            name="Effective MWh",
        ))
        fig_mwh.update_layout(
            title="Effective Storage Capacity",
            xaxis_title="Year",
            yaxis_title="MWh",
            template="plotly_dark",
            height=350,
        )
        st.plotly_chart(fig_mwh, use_container_width=True)
 
    # ── Tab 3: Revenue Breakdown ─────────────────────────────────────────
    with t3:
        streams = summary["revenue_by_stream"]
        labels = []
        values = []
        colors_pie = []
        color_map = {
            "battery_energy": "#2196F3", "solar_energy": "#FDD835",
            "capacity": "#4CAF50", "ancillary": "#FF9800",
            "rec": "#66BB6A", "offtake": "#AB47BC",
        }
 
        # Map stream keys to display labels (ERCOT uses different capacity label)
        label_map = {
            "battery_energy": "Battery Energy (Merchant)" if include_offtake else "Battery Energy",
            "solar_energy": "Solar Energy",
            "capacity": ("RTC+B & Scarcity (Merchant)" if market == "ERCOT"
                         else "Capacity (Merchant)") if include_offtake else
                        ("RTC+B & Scarcity" if market == "ERCOT" else "Capacity"),
            "ancillary": "Ancillary",
            "rec": "REC Revenue",
            "offtake": "Contracted (Tolling)",
        }
        for k, v in streams.items():
            if v > 0:
                labels.append(label_map.get(k, k.title()))
                values.append(v)
                colors_pie.append(color_map.get(k, "#999"))
 
        fig_pie = go.Figure(data=[go.Pie(
            labels=labels, values=values,
            hole=0.4,
            marker_colors=colors_pie,
            textinfo="label+percent",
            textfont_size=14,
        )])
        fig_pie.update_layout(
            title="Lifetime Revenue Split",
            template="plotly_dark",
            height=450,
        )
        st.plotly_chart(fig_pie, use_container_width=True)
 
        st.markdown("**Annual Revenue per kW-yr by Stream (Year 1)**")
        if len(cf) > 0:
            yr1 = cf[0]
            kw = battery_mw * 1000
 
            # Build metric list dynamically based on configuration
            metrics = []
            if include_offtake:
                offtake_val = yr1.get('offtake_revenue', 0)
                metrics.append(("Contracted (Tolling)", f"${offtake_val/kw:.0f}/kW-yr"))
            metrics.append(("Battery Energy", f"${yr1['energy_revenue']/kw:.0f}/kW-yr"))
            cap_metric_label = "RTC+B & Scarcity" if market == "ERCOT" else "Capacity"
            metrics.append((cap_metric_label, f"${yr1['capacity_revenue']/kw:.0f}/kW-yr"))
            metrics.append(("Ancillary", f"${yr1['ancillary_revenue']/kw:.0f}/kW-yr"))
            if include_solar:
                metrics.append(("Solar Energy", f"${yr1['solar_revenue']/kw:.0f}/kW-yr"))
                if market == "NYISO":
                    rec_val = yr1.get('rec_revenue', 0)
                    metrics.append(("REC Revenue", f"${rec_val/kw:.0f}/kW-yr"))
 
            cols = st.columns(len(metrics))
            for col, (label, value) in zip(cols, metrics):
                col.metric(label, value)
 
    # ── Tab 4: Sensitivity Analysis (on-demand) ──────────────────────────
    with t4:
        st.subheader("Tornado Chart - NPV Sensitivity")
        st.caption("Click the button below to run sensitivity analysis (takes a moment).")
 
        if st.button(f"Run Sensitivity Analysis", key=f"sens_{market}"):
            base_npv = summary["npv"]
            sens_params = {
                "battery_capex_per_kw": ("Battery CapEx ($/kW)", [battery_capex_per_kw * 0.8, battery_capex_per_kw * 1.2]),
                "wacc": ("WACC", [wacc * 0.75, wacc * 1.25]),
                "base_energy_price": ("Energy Price", [kwargs["base_energy_price"] * 0.8, kwargs["base_energy_price"] * 1.2]),
                "itc_pct": ("ITC %", [max(itc_pct - 0.1, 0), min(itc_pct + 0.1, 0.5)]),
                "battery_accred_summer": ("Battery Summer Accred.", [
                    max(battery_accred_summer - 0.15, 0.1),
                    min(battery_accred_summer + 0.15, 1.0)
                ]),
            }
 
            tornado_data = []
            progress_bar = st.progress(0)
            for i, (param, (label, bounds)) in enumerate(sens_params.items()):
                low_kwargs = kwargs.copy()
                low_kwargs[param] = bounds[0]
                high_kwargs = kwargs.copy()
                high_kwargs[param] = bounds[1]
 
                try:
                    low_result = cached_model_run(**low_kwargs)
                    high_result = cached_model_run(**high_kwargs)
                    low_npv = low_result["summary"]["npv"]
                    high_npv = high_result["summary"]["npv"]
                    tornado_data.append({
                        "param": label,
                        "low": min(low_npv, high_npv) / 1e6,
                        "high": max(low_npv, high_npv) / 1e6,
                        "spread": abs(high_npv - low_npv) / 1e6,
                    })
                except Exception as e:
                    st.warning(f"Error computing {label}: {e}")
                progress_bar.progress((i + 1) / len(sens_params))
 
            tornado_data.sort(key=lambda x: x["spread"], reverse=True)
            progress_bar.empty()
 
            if tornado_data:
                fig_torn = go.Figure()
                base_npv_m = base_npv / 1e6
 
                for item in tornado_data:
                    fig_torn.add_trace(go.Bar(
                        y=[item["param"]],
                        x=[item["high"] - base_npv_m],
                        base=[base_npv_m],
                        orientation="h",
                        marker_color="#4CAF50",
                        name="Upside",
                        showlegend=False,
                    ))
                    fig_torn.add_trace(go.Bar(
                        y=[item["param"]],
                        x=[item["low"] - base_npv_m],
                        base=[base_npv_m],
                        orientation="h",
                        marker_color="#f44336",
                        name="Downside",
                        showlegend=False,
                    ))
 
                fig_torn.add_vline(x=base_npv_m, line_dash="dash", line_color="white")
                fig_torn.update_layout(
                    title=f"NPV Sensitivity (Base: ${base_npv_m:,.1f}M)",
                    xaxis_title="NPV ($M)",
                    template="plotly_dark",
                    height=400,
                    barmode="overlay",
                )
                st.plotly_chart(fig_torn, use_container_width=True)
 
        # MACRS depreciation schedule (always shown)
        st.subheader("MACRS Depreciation Schedule")
        dep_data = []
        for yr_cf in cf:
            if yr_cf["depreciation"] > 0:
                dep_data.append({
                    "Year": yr_cf["calendar_year"],
                    "Depreciation ($)": f"${yr_cf['depreciation']:,.0f}",
                    "% of Basis": f"{yr_cf['depreciation'] / max(summary['total_capex'], 1) * 100:.1f}%",
                })
        if dep_data:
            st.dataframe(pd.DataFrame(dep_data), use_container_width=True, hide_index=True)
 
    # ── Tab 5: Data Table ────────────────────────────────────────────────
    with t5:
        display_cols = [
            "calendar_year", "degradation_factor",
        ]
        if include_offtake:
            display_cols.append("offtake_revenue")
        display_cols += ["energy_revenue", "capacity_revenue", "ancillary_revenue"]
        if include_solar:
            display_cols.append("solar_revenue")
            if market == "NYISO":
                display_cols.append("rec_revenue")
        if include_solar and solar_tax_credit == "PTC":
            display_cols.append("ptc_revenue")
        display_cols += [
            "total_revenue", "total_om", "ebitda",
            "depreciation", "tax", "itc_benefit",
        ]
        if include_solar and solar_tax_credit == "PTC":
            display_cols.append("ptc_benefit")
        display_cols += ["capex", "after_tax_cashflow"]
 
        display_df = df[display_cols].copy()
        # Rename capacity column for ERCOT
        if market == "ERCOT":
            display_df = display_df.rename(columns={"capacity_revenue": "rtcb_scarcity_revenue"})
        for col in display_df.columns:
            if col not in ["calendar_year", "degradation_factor"]:
                display_df[col] = display_df[col].apply(lambda x: f"${x:,.0f}")
            elif col == "degradation_factor":
                display_df[col] = display_df[col].apply(lambda x: f"{x:.2%}")
 
        st.dataframe(display_df, use_container_width=True, hide_index=True, height=600)
 
        csv = df.to_csv(index=False)
        st.download_button(
            f"Download {market} Cash Flow CSV",
            csv,
            f"{market.lower()}_cashflow.csv",
            "text/csv",
            key=f"download_{market}",
        )
 
    return result
 
 
# ═══════════════════════════════════════════════════════════════════════════════
# PAGE: NYISO
# ═══════════════════════════════════════════════════════════════════════════════
 
if page == "🏙️ NYISO":
    st.header("NYISO Market Analysis")
    nyiso_result = render_market_dashboard("NYISO", NYISO_ZONES)
 
 
# ═══════════════════════════════════════════════════════════════════════════════
# PAGE: ERCOT
# ═══════════════════════════════════════════════════════════════════════════════
 
elif page == "🤠 ERCOT":
    st.header("ERCOT Market Analysis")
    st.info("Note: ERCOT is an energy-only market — no formal capacity market. "
            "The 'RTC+B & Scarcity Credits' stream reflects revenue from ERCOT's Real-Time "
            "Co-optimization with Batteries (RTC+B) market design and scarcity pricing events.")
    ercot_result = render_market_dashboard("ERCOT", ERCOT_ZONES)
 
 
# ═══════════════════════════════════════════════════════════════════════════════
# PAGE: Market Comparison
# ═══════════════════════════════════════════════════════════════════════════════
 
elif page == "📊 Market Comparison":
    st.header("NYISO vs ERCOT Comparison")
 
    col1, col2 = st.columns(2)
    with col1:
        nyiso_zone = st.selectbox(
            "NYISO Zone for comparison",
            list(NYISO_ZONES.keys()),
            index=list(NYISO_ZONES.keys()).index("Zone G (Hudson Valley)"),
            key="compare_nyiso_zone",
        )
    with col2:
        ercot_zone = st.selectbox(
            "ERCOT Zone for comparison",
            list(ERCOT_ZONES.keys()),
            index=list(ERCOT_ZONES.keys()).index("North"),
            key="compare_ercot_zone",
        )
 
    with st.spinner("Running comparison models..."):
        nyiso_kwargs = build_kwargs("NYISO", nyiso_zone)
        ercot_kwargs = build_kwargs("ERCOT", ercot_zone)
        nyiso_comp = cached_model_run(**nyiso_kwargs)
        ercot_comp = cached_model_run(**ercot_kwargs)
 
    # Side by side metrics
    col1, col2 = st.columns(2)
 
    with col1:
        st.subheader(f"NYISO - {nyiso_zone}")
        ns = nyiso_comp["summary"]
        st.metric("NPV", f"${ns['npv']/1e6:,.1f}M")
        st.metric("IRR", f"{ns['irr']:.1f}%" if ns["irr"] else "N/A")
        st.metric("Payback", f"{ns['payback_years']} yrs" if ns["payback_years"] else ">Life")
        st.metric("Avg Rev/kW-yr", f"${ns['avg_revenue_per_kw_yr']:.0f}")
 
    with col2:
        st.subheader(f"ERCOT - {ercot_zone}")
        es = ercot_comp["summary"]
        st.metric("NPV", f"${es['npv']/1e6:,.1f}M")
        st.metric("IRR", f"{es['irr']:.1f}%" if es["irr"] else "N/A")
        st.metric("Payback", f"{es['payback_years']} yrs" if es["payback_years"] else ">Life")
        st.metric("Avg Rev/kW-yr", f"${es['avg_revenue_per_kw_yr']:.0f}")
 
    # Revenue data
    nyiso_df = pd.DataFrame(nyiso_comp["cashflows"])
    ercot_df = pd.DataFrame(ercot_comp["cashflows"])
 
    # Revenue stream comparison — separate chart per market, each with own legend
    # NYISO streams (includes REC pricing)
    nyiso_stream_defs = [
        ("energy_revenue",   "Battery Energy",      "#2196F3"),
        ("solar_revenue",    "Solar Energy",         "#FDD835"),
        ("capacity_revenue", "Capacity",             "#4CAF50"),
        ("ancillary_revenue","Ancillary Services",   "#FF9800"),
        ("rec_revenue",      "REC Revenue",        "#66BB6A"),
        ("offtake_revenue",  "Contracted (Tolling)", "#AB47BC"),
    ]
    # ERCOT streams — NO RECs, capacity = RTC+B & Scarcity
    ercot_stream_defs = [
        ("energy_revenue",   "Battery Energy",       "#2196F3"),
        ("solar_revenue",    "Solar Energy",          "#FDD835"),
        ("capacity_revenue", "RTC+B & Scarcity",     "#4CAF50"),
        ("ancillary_revenue","Ancillary Services",    "#FF9800"),
        ("offtake_revenue",  "Contracted (Tolling)",  "#AB47BC"),
    ]
 
    comp_col1, comp_col2 = st.columns(2)
 
    # ── NYISO chart ──
    with comp_col1:
        fig_nyiso = go.Figure()
        for col_name, label, color in nyiso_stream_defs:
            if col_name not in nyiso_df.columns:
                continue
            series = nyiso_df[col_name] / 1e6
            if series.sum() == 0:
                continue
            fig_nyiso.add_trace(go.Bar(
                x=nyiso_df["calendar_year"], y=series,
                name=label, marker_color=color,
            ))
        fig_nyiso.update_layout(
            barmode="stack",
            title=f"NYISO — {nyiso_zone}",
            xaxis_title="Year", yaxis_title="Revenue ($M)",
            template="plotly_dark",
            height=500,
            legend=dict(
                orientation="h", yanchor="bottom", y=-0.28,
                xanchor="center", x=0.5, font=dict(size=11),
            ),
            margin=dict(b=110),
        )
        st.plotly_chart(fig_nyiso, use_container_width=True)
 
    # ── ERCOT chart ──
    with comp_col2:
        fig_ercot = go.Figure()
        for col_name, label, color in ercot_stream_defs:
            if col_name not in ercot_df.columns:
                continue
            series = ercot_df[col_name] / 1e6
            if series.sum() == 0:
                continue
            fig_ercot.add_trace(go.Bar(
                x=ercot_df["calendar_year"], y=series,
                name=label, marker_color=color,
            ))
        fig_ercot.update_layout(
            barmode="stack",
            title=f"ERCOT — {ercot_zone}",
            xaxis_title="Year", yaxis_title="Revenue ($M)",
            template="plotly_dark",
            height=500,
            legend=dict(
                orientation="h", yanchor="bottom", y=-0.28,
                xanchor="center", x=0.5, font=dict(size=11),
            ),
            margin=dict(b=110),
        )
        st.plotly_chart(fig_ercot, use_container_width=True)
 
    # Annual total revenue comparison (line chart)
    fig_comp = go.Figure()
    fig_comp.add_trace(go.Scatter(
        x=nyiso_df["calendar_year"],
        y=nyiso_df["total_revenue"] / 1e6,
        mode="lines+markers",
        name=f"NYISO ({nyiso_zone})",
        line=dict(color="#2196F3", width=3),
    ))
    fig_comp.add_trace(go.Scatter(
        x=ercot_df["calendar_year"],
        y=ercot_df["total_revenue"] / 1e6,
        mode="lines+markers",
        name=f"ERCOT ({ercot_zone})",
        line=dict(color="#FF9800", width=3),
    ))
    fig_comp.update_layout(
        title="Annual Total Revenue Comparison",
        xaxis_title="Year",
        yaxis_title="Revenue ($M)",
        template="plotly_dark",
        height=450,
    )
    st.plotly_chart(fig_comp, use_container_width=True)
 
    # ── Offtake vs. Merchant Comparison ──────────────────────────────────
    st.subheader("Merchant vs. Contracted Scenario")
    st.caption("Compare 100% merchant economics against the current offtake configuration for each market.")
 
    if st.button("Run Merchant vs. Contracted Comparison", key="run_merchant_comp"):
        # Run both markets in merchant mode (no offtake)
        merchant_nyiso_kw = nyiso_kwargs.copy()
        merchant_nyiso_kw["include_offtake"] = False
        merchant_nyiso_kw["offtake_pct"] = 0.0
        merchant_ercot_kw = ercot_kwargs.copy()
        merchant_ercot_kw["include_offtake"] = False
        merchant_ercot_kw["offtake_pct"] = 0.0
 
        with st.spinner("Running merchant comparison..."):
            merchant_nyiso = cached_model_run(**merchant_nyiso_kw)
            merchant_ercot = cached_model_run(**merchant_ercot_kw)
 
        # Current results (may already include offtake)
        current_label = "With Offtake" if include_offtake else "Merchant (current)"
 
        comp_data = pd.DataFrame([
            {"Market": "NYISO", "Scenario": "100% Merchant",
             "NPV ($M)": merchant_nyiso["summary"]["npv"] / 1e6,
             "IRR (%)": merchant_nyiso["summary"]["irr"] or 0,
             "Payback (yrs)": merchant_nyiso["summary"]["payback_years"] or project_life},
            {"Market": "NYISO", "Scenario": current_label,
             "NPV ($M)": nyiso_comp["summary"]["npv"] / 1e6,
             "IRR (%)": nyiso_comp["summary"]["irr"] or 0,
             "Payback (yrs)": nyiso_comp["summary"]["payback_years"] or project_life},
            {"Market": "ERCOT", "Scenario": "100% Merchant",
             "NPV ($M)": merchant_ercot["summary"]["npv"] / 1e6,
             "IRR (%)": merchant_ercot["summary"]["irr"] or 0,
             "Payback (yrs)": merchant_ercot["summary"]["payback_years"] or project_life},
            {"Market": "ERCOT", "Scenario": current_label,
             "NPV ($M)": ercot_comp["summary"]["npv"] / 1e6,
             "IRR (%)": ercot_comp["summary"]["irr"] or 0,
             "Payback (yrs)": ercot_comp["summary"]["payback_years"] or project_life},
        ])
 
        fig_merchant = go.Figure()
        for scenario in comp_data["Scenario"].unique():
            subset = comp_data[comp_data["Scenario"] == scenario]
            fig_merchant.add_trace(go.Bar(
                x=subset["Market"], y=subset["NPV ($M)"],
                name=scenario,
                text=[f"IRR: {r:.1f}%" for r in subset["IRR (%)"]],
                textposition="outside",
            ))
        fig_merchant.update_layout(
            title="NPV Comparison: Merchant vs. Contracted",
            yaxis_title="NPV ($M)",
            barmode="group",
            template="plotly_dark",
            height=400,
        )
        st.plotly_chart(fig_merchant, use_container_width=True)
 
 
# ═══════════════════════════════════════════════════════════════════════════════
# PAGE: Hourly and Daily Performance
# ═══════════════════════════════════════════════════════════════════════════════
 
elif page == "⏰ Hourly and Daily Performance":
    st.header("Hourly and Daily Performance Analysis")
    st.caption("Drill into hourly price and dispatch patterns for any day in the project life.")
 
    h_col1, h_col2, h_col3, h_col4 = st.columns(4)
 
    with h_col1:
        hourly_market = st.selectbox(
            "Market", ["NYISO", "ERCOT"], key="hourly_market"
        )
    with h_col2:
        if hourly_market == "NYISO":
            hourly_zone = st.selectbox(
                "Zone", list(NYISO_ZONES.keys()),
                index=list(NYISO_ZONES.keys()).index("Zone G (Hudson Valley)"),
                key="hourly_zone_nyiso",
            )
        else:
            hourly_zone = st.selectbox(
                "Zone", list(ERCOT_ZONES.keys()), key="hourly_zone_ercot",
            )
 
    start_year = 2025
    years = list(range(start_year, start_year + project_life))
 
    with h_col3:
        selected_year = st.selectbox("Year", years, key="hourly_year")
 
    with h_col4:
        selected_month = st.selectbox(
            "Month",
            list(range(1, 13)),
            format_func=lambda m: [
                "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
            ][m - 1],
            key="hourly_month",
            index=6,  # July default
        )
 
    # Run model for selected market/zone (cached)
    hourly_kwargs = build_kwargs(hourly_market, hourly_zone)
    with st.spinner("Generating hourly data..."):
        hourly_result = cached_model_run(**hourly_kwargs)
 
    # Get hourly price data for selected year
    price_key = f"{selected_year}_prices"
    if price_key in hourly_result["hourly_data"]:
        price_df = hourly_result["hourly_data"][price_key]
        month_prices = price_df[price_df["month"] == selected_month].copy()
 
        # Day selector
        unique_days = sorted(month_prices["day_of_year"].unique())
 
        if unique_days:
            selected_day_of_year = st.selectbox(
                "Day of Month",
                unique_days,
                format_func=lambda d: f"Day {d - unique_days[0] + 1}",
                key="hourly_day",
            )
 
            # Get the 24-hour slice
            day_data = month_prices[month_prices["day_of_year"] == selected_day_of_year].copy()
 
            if len(day_data) >= 24:
                # Get dispatch data
                dispatch_key = selected_year
                dispatch_df = hourly_result["hourly_data"].get(dispatch_key)
                dispatch_day = None
                if dispatch_df is not None:
                    dispatch_day = dispatch_df[dispatch_df["day"] == selected_day_of_year]
 
                # ── Hourly price chart ────────────────────────────────────────
                fig_hourly = make_subplots(
                    rows=2, cols=1,
                    subplot_titles=["Hourly LMP ($/MWh)", "Battery Dispatch"],
                    row_heights=[0.6, 0.4],
                    vertical_spacing=0.15,
                )
 
                hours_24 = list(range(24))
                prices_24 = day_data["lmp"].values[:24]
 
                fig_hourly.add_trace(go.Scatter(
                    x=hours_24, y=prices_24,
                    mode="lines+markers",
                    name="LMP",
                    line=dict(color="#4fc3f7", width=3),
                    marker=dict(size=8),
                    fill="tozeroy",
                    fillcolor="rgba(79, 195, 247, 0.15)",
                ), row=1, col=1)
 
                # Dispatch bar chart
                if dispatch_day is not None and len(dispatch_day) >= 24:
                    actions = dispatch_day["action"].values[:24]
                    charge_vals = []
                    discharge_vals = []
 
                    for h, action in enumerate(actions):
                        if action == "charge":
                            charge_vals.append(-battery_mw)
                            discharge_vals.append(0)
                        elif action == "discharge":
                            charge_vals.append(0)
                            discharge_vals.append(battery_mw)
                        else:
                            charge_vals.append(0)
                            discharge_vals.append(0)
 
                    fig_hourly.add_trace(go.Bar(
                        x=hours_24, y=discharge_vals,
                        name="Discharge",
                        marker_color="#4CAF50",
                    ), row=2, col=1)
                    fig_hourly.add_trace(go.Bar(
                        x=hours_24, y=charge_vals,
                        name="Charge",
                        marker_color="#f44336",
                    ), row=2, col=1)
 
                fig_hourly.update_layout(
                    template="plotly_dark",
                    height=650,
                    showlegend=True,
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                )
                fig_hourly.update_xaxes(title_text="Hour of Day", row=2, col=1)
                fig_hourly.update_yaxes(title_text="$/MWh", row=1, col=1)
                fig_hourly.update_yaxes(title_text="MW", row=2, col=1)
 
                st.plotly_chart(fig_hourly, use_container_width=True)
 
                # ── Revenue breakdown for this day ────────────────────────────
                st.subheader("Daily Revenue Estimate")
 
                if dispatch_day is not None and len(dispatch_day) >= 24:
                    day_actions = dispatch_day.iloc[:24]
                    charge_cost = 0
                    discharge_rev = 0
                    for _, row in day_actions.iterrows():
                        if row["action"] == "charge":
                            charge_cost += row["price"] * battery_mw
                        elif row["action"] == "discharge":
                            discharge_rev += row["price"] * battery_mw * roundtrip_efficiency
 
                    arb_rev = max(discharge_rev - charge_cost, 0)
 
                    dc1, dc2, dc3, dc4 = st.columns(4)
                    dc1.metric("Arbitrage Revenue", f"${arb_rev:,.0f}")
                    dc2.metric("Avg On-Peak Price",
                               f"${np.mean(prices_24[16:21]):.1f}/MWh")
                    dc3.metric("Avg Off-Peak Price",
                               f"${np.mean(prices_24[0:6]):.1f}/MWh")
                    dc4.metric("Peak-OffPeak Spread",
                               f"${np.mean(prices_24[16:21]) - np.mean(prices_24[0:6]):.1f}/MWh")
 
                # Monthly average pattern
                st.subheader("Monthly Average Hourly Pattern")
                monthly_avg = month_prices.groupby("hour")["lmp"].mean()
                fig_monthly = go.Figure()
                fig_monthly.add_trace(go.Scatter(
                    x=monthly_avg.index,
                    y=monthly_avg.values,
                    mode="lines+markers",
                    fill="tozeroy",
                    fillcolor="rgba(255, 152, 0, 0.15)",
                    line=dict(color="#FF9800", width=3),
                    name="Avg LMP",
                ))
                fig_monthly.update_layout(
                    title=f"Average Hourly LMP - Month {selected_month}",
                    xaxis_title="Hour of Day",
                    yaxis_title="Avg LMP ($/MWh)",
                    template="plotly_dark",
                    height=350,
                )
                st.plotly_chart(fig_monthly, use_container_width=True)
            else:
                st.warning("Insufficient hourly data for selected day.")
        else:
            st.warning("No days found for selected month.")
    else:
        st.warning("No hourly data available for selected year. Adjust project life or start year.")
 
 
# ═══════════════════════════════════════════════════════════════════════════════
# PAGE: Support & Definitions
# ═══════════════════════════════════════════════════════════════════════════════
 
elif page == "📖 Support & Definitions":
    st.header("Support & Definitions")
    st.caption("Reference guide for all terms, parameters, and concepts used in this dashboard.")
 
    # ── Market Concepts ──────────────────────────────────────────────────
    st.subheader("Market Concepts")
 
    st.markdown("""
**NYISO (New York Independent System Operator)**
The entity that manages the electric grid and wholesale electricity markets across New York State.
NYISO operates energy, capacity, and ancillary services markets. The state is divided into
11 load zones (A through K), each with different pricing dynamics driven by local supply,
demand, and transmission constraints.
 
**ERCOT (Electric Reliability Council of Texas)**
The grid operator and market administrator for most of Texas. Unlike NYISO, ERCOT is an
energy-only market — there is no formal capacity market. Instead, reliability is maintained
through scarcity pricing, where energy prices can spike to very high levels during tight
supply conditions, sending investment signals to generators and storage.
 
**LMP (Locational Marginal Price)**
The wholesale price of electricity at a specific location on the grid, measured in \$/MWh.
LMPs vary by location and time based on generation costs, transmission congestion, and losses.
Batteries earn energy revenue by buying (charging) when LMPs are low and selling (discharging)
when LMPs are high.
 
**Capacity Market**
A forward market where generators and storage are paid to guarantee they will be available
to produce electricity when needed. NYISO's capacity market (ICAP) provides a significant
revenue stream for batteries. Payments are made in \$/kW-month. ERCOT does not have a
capacity market.
 
**Ancillary Services**
Grid services beyond energy generation that help maintain system reliability. The three
types modeled here are:
 
- **Frequency Regulation** — Rapidly adjusting output second-by-second to balance
  supply and demand. Batteries excel at this due to fast response times. Paid in \$/MW-hr.
- **Spinning/Operating Reserves** — Standing ready to deploy power within minutes if
  a generator trips offline or demand spikes unexpectedly. Paid in \$/MW-hr.
- **DRRS (Dispatchable Reliability Reserve Service)** — ERCOT-only service that compensates
  resources capable of delivering sustained energy during grid emergencies. Requires a minimum
  4-hour battery duration. Addresses risks from generation variability and forced outages.
 
**Energy Arbitrage**
The core battery trading strategy: charge the battery during low-price hours (typically
overnight or midday when solar is abundant) and discharge during high-price hours (typically
late afternoon/evening peaks). Revenue equals the price spread minus roundtrip efficiency losses.
""")
 
    # ── Battery Parameters ───────────────────────────────────────────────
    st.subheader("Battery Parameters")
 
    st.markdown("""
**Battery Power (MW)**
The maximum rate at which the battery can charge or discharge, measured in megawatts.
A 100 MW battery can inject up to 100 MW into the grid at any moment.
 
**Battery Duration (hours)**
How long the battery can sustain its maximum output. A 4-hour, 100 MW battery has
400 MWh of storage capacity. Longer duration batteries capture more arbitrage hours
but cost more per kW.
 
**Total CapEx**
The total upfront capital expenditure for the project. Calculated as the Battery Capital
Cost (\$/kW) multiplied by the system's power capacity, plus Solar CapEx if a colocated
solar array is included. The \$/kW figure is an all-in installed cost that covers battery
cells, modules, battery management system, inverter, transformer, switchgear,
interconnection, site work, and developer costs. Default values are based on NREL 2025
and EIA AEO2025 benchmarks: roughly \$1,300/kW for a 4-hour system and \$2,100/kW for
an 8-hour system (lithium iron phosphate chemistry).
 
**Roundtrip Efficiency (RTE)**
The percentage of energy recovered during discharge relative to what was consumed during
charging. An 87% RTE means for every 100 MWh charged, 87 MWh is discharged. Losses
occur as heat in the power electronics and battery cells.
 
**Annual Degradation Rate**
The percentage of battery capacity lost each year due to cycling and calendar aging.
After 10 years at 2.5%/year, the battery retains approximately 78% of its original capacity.
 
**Augmentation**
Adding new battery modules partway through the project life to restore degraded capacity.
The augmentation year and restore percentage are configurable. Augmentation has a cost
(\$/kWh of capacity restored) that appears as a one-time expense in the cash flow.
Augmentation applies relative to each battery's installation — if a replacement battery
is installed at year 15, augmentation fires again at year 25 (augmentation year 10 into
the replacement battery's life).
 
**Battery Replacement (Solar+Storage)**
For solar+storage projects with 30-year lifetimes, batteries degrade faster than solar panels
and are typically replaced at the project midpoint. The replacement installs a new battery
system, resetting degradation to 100% capacity. The replacement cost is modeled as a fraction
of the original battery CapEx (default 50%, reflecting expected cost declines). The replacement
battery receives its own 5-year MACRS depreciation schedule and ITC, and augmentation applies
independently to each battery's lifecycle. This feature is only available when solar is included,
as standalone battery projects use a 20-year default life that typically does not require replacement.
""")
 
    # ── Financial Parameters ─────────────────────────────────────────────
    st.subheader("Financial Parameters")
 
    st.markdown("""
**WACC (Weighted Average Cost of Capital)**
The blended rate of return required by a project's debt and equity investors, weighted
by the proportion of each in the capital structure. Used as the discount rate for NPV
calculations. A higher WACC means future cash flows are worth less today.
 
**NPV (Net Present Value)**
The sum of all future after-tax cash flows discounted back to today at the WACC, minus
the initial investment. A positive NPV means the project creates value above the required
return. This is the primary metric for investment decisions.
 
**IRR (Internal Rate of Return)**
The discount rate at which the NPV equals zero. Represents the project's effective annual
return. Compare IRR to WACC — if IRR > WACC, the project creates value.
 
**Payback Period**
The number of years until cumulative after-tax cash flows turn positive (i.e., the initial
investment is recovered). Shorter payback = lower risk.
 
**ITC (Investment Tax Credit)**
A federal tax credit equal to a percentage of the project's capital cost, taken in year 1.
Under the Inflation Reduction Act, standalone storage qualifies for up to 30% ITC (with
potential adders up to 50%). The ITC reduces the depreciable basis by 50% of the credit amount.
 
**PTC (Production Tax Credit)**
An alternative to the ITC for solar projects. Instead of an upfront credit on capital cost,
the PTC provides a per-MWh credit on electricity generated for the first 10 years of operation.
The IRA base rate is approximately \$28/MWh (inflation-adjusted). Projects must choose either
ITC or PTC for the solar component — the battery always receives the ITC. The PTC can be more
valuable for high-capacity-factor solar installations with strong resource.
 
**MACRS (Modified Accelerated Cost Recovery System)**
The IRS depreciation method for tax purposes. Battery storage qualifies for 5-year MACRS,
which front-loads depreciation deductions (20%, 32%, 19.2%, 11.52%, 11.52%, 5.76% over
6 tax years). This accelerated schedule reduces taxable income in the early years,
improving after-tax returns. A 7-year schedule is also available.
 
**Bonus Depreciation**
An additional first-year deduction that allows a percentage of the depreciable basis to
be expensed immediately. When set to 100%, the entire depreciable basis is deducted in
year 1 (in addition to normal MACRS). This has been phasing down under current tax law.
 
**Tax Rate**
The combined federal and state corporate income tax rate applied to taxable income.
Taxable income = EBITDA − depreciation. Tax benefits from depreciation and ITC
significantly improve after-tax project economics.
 
**EBITDA**
Earnings Before Interest, Taxes, Depreciation, and Amortization. Equals total revenue
minus operating expenses (fixed O&M, variable O&M, solar O&M, and augmentation costs).
""")
 
    # ── Revenue Structure & Offtake ──────────────────────────────────────
    st.subheader("Revenue Structure & Offtake Agreements")
 
    st.markdown("""
**Merchant vs. Contracted Revenue**
Battery storage projects can earn revenue through two fundamentally different structures.
In a **merchant** model, all revenue is earned by participating directly in wholesale markets
(energy arbitrage, capacity auctions, ancillary services). Returns are higher on average but
carry significant price risk. In a **contracted** model, some or all of the project's capacity
is committed under a long-term agreement that provides fixed, predictable cash flows. Most
financed projects use a hybrid: a contracted base that secures debt financing, plus a merchant
tail that captures market upside.
 
**Tolling Agreement**
The most common offtake structure for battery storage. The offtaker (typically a utility,
trading house, or load-serving entity) pays the developer a fixed annual fee (\$/kW-yr) in
exchange for the right to dispatch the battery. The developer receives guaranteed revenue
regardless of whether the battery is actually dispatched. The tolling rate replaces merchant
energy and capacity revenue for the contracted share, while ancillary services and solar
revenue typically remain with the developer. Recent NYISO tolling rates for 4-hour batteries
have ranged from \$150–200/kW-yr.
 
**Contracted Share (%)**
The percentage of the battery's capacity committed under the tolling agreement. A 70%
contracted / 30% merchant split is common for project-financed assets — the contracted
portion provides bankable cash flows for lenders, while the merchant tail gives equity
investors exposure to market upside.
 
**Contract Term**
The duration of the tolling agreement, typically 10–15 years. After the contract expires,
the previously contracted share reverts to full merchant pricing for the remainder of the
project life. Longer terms reduce risk but may limit participation in future market improvements.
 
**Annual Escalator**
An annual increase applied to the tolling rate, typically linked to CPI or a fixed percentage
(1–2%/yr). Protects the developer against inflation erosion of the contracted payment over
the contract term.
 
**REC Revenue — NYISO Only**
Renewable Energy Credits (RECs) represent the environmental attributes of 1 MWh of eligible
renewable generation. In New York, RECs are procured by NYSERDA under the Clean Energy
Standard to meet the state's target of 70% renewable electricity by 2030. RECs are earned on
all solar generation regardless of whether the energy is sold to the grid or used to charge
the battery. Recent NY REC prices have ranged approximately \$20–30/MWh. RECs are retained by
the developer even when a tolling agreement is in place.
 
**Note:** ERCOT/Texas has its own RPS with Texas RECs, but they are essentially worthless
(<\$1/MWh) because the state has massively overbuilt renewable capacity relative to its
RPS mandate. REC revenue is therefore excluded from all ERCOT scenarios.
""")
 
    # ── Accreditation ────────────────────────────────────────────────────
    st.subheader("Accreditation")
 
    st.markdown("""
**Capacity Accreditation**
The percentage of a resource's nameplate capacity that the market counts as "reliable"
for capacity market purposes. A battery with 90% summer accreditation and 100 MW nameplate
is credited as 90 MW for summer capacity payments.
 
**Battery Summer Accreditation (Apr–Oct)**
Batteries typically receive higher accreditation in summer because peak demand occurs
during summer afternoons when batteries are most valuable. Default: 90%.
 
**Battery Winter Accreditation (Nov–Mar)**
Winter accreditation may be lower if the battery's duration doesn't cover the longer
winter peak periods (e.g., cold snaps). Default: 75%.
 
**Solar Summer Accreditation (Apr–Oct)**
Solar's contribution to peak reliability during summer. Typically 40–60% because peak
demand extends into evening hours when solar output drops. Default: 50%.
 
**Solar Winter Accreditation (Nov–Mar)**
Solar contributes very little to winter reliability due to shorter days and lower
output. Default: 10%.
""")
 
    # ── Market Parameters ────────────────────────────────────────────────
    st.subheader("Market & Scenario Parameters")
 
    st.markdown("""
**Base Energy Price (\$/MWh)**
The starting average wholesale electricity price. Hourly prices fluctuate around this
base with seasonal, diurnal, and random variation. Higher base prices generally mean
higher arbitrage spreads and battery revenue.
 
**Demand Growth Rate (%/yr)**
Annual growth in electricity demand, which tends to push prices and capacity values
higher over time. Driven by electrification, data centers, EV adoption, etc.
 
**Renewable Penetration (%)**
The share of electricity supplied by wind and solar. Higher penetration deepens the
midday price trough (solar duck curve), increasing arbitrage opportunities, but can
also depress average prices and occasionally cause negative pricing.
 
**Regulation Participation (%)**
The fraction of battery capacity dedicated to frequency regulation service. Higher
participation earns more ancillary revenue but may reduce energy arbitrage availability.
 
**Reserve Participation (%)**
The fraction of battery capacity committed to spinning/operating reserves. Similar
trade-off as regulation — reserve revenue vs. arbitrage opportunity.
 
**DRRS Participation (%) — ERCOT only**
The fraction of battery capacity committed to Dispatchable Reliability Reserve Service.
DRRS is an ERCOT-only ancillary service that requires a minimum 4-hour battery duration.
It compensates resources for being available to deliver sustained energy during grid
emergencies caused by generation variability and forced outages. Only applies to ERCOT
analyses with 4hr+ batteries.
 
**Summer Capacity Price (\$/kW-month)**
The capacity market clearing price for the summer period (April through October).
Default of \$14.00/kW-month is based on recent NYISO Zone J (NYC) ICAP spot auction results.
For Rest of State zones, typical summer prices are \$2–5/kW-month. Adjust this slider
to reflect the zone and scenario you are modeling.
 
**Winter Capacity Price (\$/kW-month)**
The capacity market clearing price for the winter period (November through March).
Default of \$18.00/kW-month reflects NYC's winter premium. Zone K (Long Island) winter
prices have historically been much higher, spiking to \$40–70/kW-month in constrained periods.
 
**Annual Capacity Price Escalation (%)**
The assumed annual growth rate for capacity prices over the project life. Driven by
load growth, generator retirements, and tightening reserve margins. Default: 1.0%/year.
""")
 
    # ── NYISO Zones ──────────────────────────────────────────────────────
    st.subheader("NYISO Load Zones")
 
    zone_data = []
    for name, info in NYISO_ZONES.items():
        zone_data.append({
            "Zone": name,
            "Capacity Price Multiplier": f"{info['capacity_mult']:.2f}x",
            "Energy Price Multiplier": f"{info['energy_mult']:.2f}x",
        })
    st.dataframe(pd.DataFrame(zone_data), use_container_width=True, hide_index=True)
 
    st.markdown("""
Constrained downstate zones (G through K) have significantly higher capacity prices
due to transmission bottlenecks that limit power imports from upstate. Zone J (NYC) has
the highest capacity prices in the state, making it the most attractive location for
battery storage from a capacity revenue perspective.
""")
 
    # ── ERCOT Zones ──────────────────────────────────────────────────────
    st.subheader("ERCOT Load Zones")
 
    ercot_data = []
    for name, info in ERCOT_ZONES.items():
        ercot_data.append({
            "Zone": name,
            "Energy Price Multiplier": f"{info['energy_mult']:.2f}x",
        })
    st.dataframe(pd.DataFrame(ercot_data), use_container_width=True, hide_index=True)
 
    st.markdown("""
ERCOT zones differ primarily in energy price levels. West Texas has the highest
multiplier due to transmission congestion from wind-heavy generation. The Panhandle
has the lowest due to wind curtailment depressing prices.
""")
 
    # ── Chart Descriptions ───────────────────────────────────────────────
    st.subheader("Chart & Visualization Guide")
 
    st.markdown("""
**Revenue & Cash Flows Tab**
 
- *Stacked Bar Chart (Annual Revenue by Stream)* — Shows how total revenue is composed
  of energy arbitrage, capacity, ancillary, and solar streams each year. Declining bars
  reflect battery degradation; spikes indicate augmentation years.
- *Cumulative Cash Flow* — Tracks the running total of after-tax cash flows. The year
  it crosses zero is the payback period. Red bars = still paying back, green = net positive.
 
**Degradation Tab**
 
- *Effective Capacity (%)* — Shows how battery capacity declines over time, with a
  step up at the augmentation year.
- *Effective Storage Capacity (MWh)* — The absolute usable energy capacity over time.
 
**Revenue Breakdown Tab**
 
- *Pie Chart* — Lifetime revenue split across all streams.
- *Year 1 Revenue per kW-yr* — Key benchmark metric for comparing against other markets.
 
**Sensitivity Tab**
 
- *Tornado Chart* — Shows which parameters have the biggest impact on NPV. Longer bars
  mean higher sensitivity. Green = upside, red = downside.
- *MACRS Depreciation Schedule* — Year-by-year depreciation amounts and percentage of basis.
 
**Hourly and Daily Performance**
 
- *Hourly LMP* — The 24-hour price curve for a selected day, showing off-peak lows and
  on-peak highs.
- *Battery Dispatch* — When the battery charges (red, below zero) and discharges
  (green, above zero) based on the daily price optimization.
- *Monthly Average Pattern* — Average hourly price shape across all days in the selected month.
""")
 
