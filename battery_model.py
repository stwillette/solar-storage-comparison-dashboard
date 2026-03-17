"""
Battery storage financial model with MACRS depreciation, ITC, degradation,
and full revenue stacking (energy arbitrage, capacity, ancillary, solar).
Supports NYISO and ERCOT markets.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple

from data_generator import (
    NYISO_ZONES,
    ERCOT_ZONES,
    generate_hourly_prices,
    get_nyiso_capacity_price,
    get_ercot_capacity_equivalent,
    get_ancillary_rates,
    generate_solar_profile,
    compute_arbitrage_revenue,
    compute_capacity_revenue,
    compute_ancillary_revenue,
    compute_solar_revenue,
    compute_rec_revenue,
)


# ─── MACRS Depreciation Schedules ─────────────────────────────────────────────
# 5-year MACRS (used for battery storage under IRA)
MACRS_5YR = {1: 0.2000, 2: 0.3200, 3: 0.1920, 4: 0.1152, 5: 0.1152, 6: 0.0576}

# 7-year MACRS (alternative / solar in some cases)
MACRS_7YR = {
    1: 0.1429, 2: 0.2449, 3: 0.1749, 4: 0.1249,
    5: 0.0893, 6: 0.0892, 7: 0.0893, 8: 0.0446,
}


def compute_macrs_depreciation(
    depreciable_basis: float,
    schedule: Dict[int, float] = None,
    project_life: int = 20,
    bonus_depreciation_pct: float = 0.0,
) -> List[float]:
    """
    Compute annual depreciation using MACRS schedule.

    Args:
        depreciable_basis: Total depreciable cost (CapEx - 0.5*ITC if ITC taken)
        schedule: MACRS depreciation percentages by year
        project_life: Total project life in years
        bonus_depreciation_pct: Bonus depreciation percentage (0-1.0)

    Returns:
        List of annual depreciation amounts for each project year
    """
    if schedule is None:
        schedule = MACRS_5YR

    depreciation = [0.0] * project_life

    # Bonus depreciation in year 1
    bonus_amount = depreciable_basis * bonus_depreciation_pct
    remaining_basis = depreciable_basis - bonus_amount

    if project_life > 0:
        depreciation[0] += bonus_amount

    # Regular MACRS on remaining basis
    for yr, pct in schedule.items():
        idx = yr - 1
        if idx < project_life:
            depreciation[idx] += remaining_basis * pct

    return depreciation


def compute_battery_degradation(
    year: int,
    annual_degradation_rate: float = 0.025,
    augmentation_year: int = 10,
    augmentation_pct: float = 0.15,
) -> float:
    """
    Compute cumulative degradation factor for battery capacity.
    Returns value between 0 and 1 representing effective capacity.
    """
    if year <= 0:
        return 1.0

    if augmentation_year > 0 and year >= augmentation_year:
        # Degrade up to augmentation year, add augmentation, then degrade from there
        factor_at_aug = (1 - annual_degradation_rate) ** augmentation_year
        augmented_factor = min(factor_at_aug + augmentation_pct, 1.0)
        years_after_aug = year - augmentation_year
        factor = augmented_factor * (1 - annual_degradation_rate) ** years_after_aug
    else:
        factor = (1 - annual_degradation_rate) ** year

    return max(factor, 0.1)  # floor at 10%


def _compute_lcos(
    total_capex: float,
    cashflows: list,
    battery_mwh: float,
    project_life: int,
    wacc: float,
) -> float:
    """
    Levelized Cost of Storage ($/MWh discharged).
    LCOS = PV(all costs) / PV(total MWh discharged).
    """
    pv_costs = total_capex
    pv_mwh = 0.0
    for yr_idx, cf in enumerate(cashflows):
        yr = yr_idx + 1
        df = (1 + wacc) ** (-yr)
        pv_costs += (cf["fixed_om"] + cf["variable_om"] + cf.get("solar_om", 0)
                     + cf.get("augmentation_cost", 0)
                     + cf.get("battery_replacement_cost", 0)) * df
        # Estimate discharged MWh from degradation factor
        discharged_mwh = 365 * battery_mwh * cf["degradation_factor"]
        pv_mwh += discharged_mwh * df
    if pv_mwh <= 0:
        return 0.0
    return round(pv_costs / pv_mwh, 2)


def run_full_financial_model(
    # Battery parameters
    battery_mw: float = 100.0,
    battery_mwh: float = 400.0,
    battery_capex_per_kw: float = 1300.0,  # All-in $/kW (NREL 2025 / EIA AEO2025)
    fixed_om_per_kw_yr: float = 12.5,
    variable_om_per_mwh: float = 2.5,
    roundtrip_efficiency: float = 0.87,
    annual_degradation: float = 0.025,
    augmentation_year: int = 10,
    augmentation_pct: float = 0.15,
    augmentation_cost_per_kwh: float = 100.0,

    # Financial parameters
    project_life: int = 20,
    wacc: float = 0.08,
    tax_rate: float = 0.21,
    itc_pct: float = 0.30,
    bonus_depreciation_pct: float = 0.0,
    macrs_schedule: str = "5yr",

    # Market parameters
    market: str = "NYISO",
    zone_name: str = "Zone G (Hudson Valley)",
    base_energy_price: float = 35.0,
    demand_growth_rate: float = 0.015,
    renewable_penetration: float = 0.30,

    # Accreditation (separate for battery and solar, by season)
    battery_accred_summer: float = 0.90,
    battery_accred_winter: float = 0.75,
    solar_accred_summer: float = 0.50,
    solar_accred_winter: float = 0.10,

    # Ancillary services
    regulation_pct: float = 0.15,
    reserve_pct: float = 0.10,
    drrs_pct: float = 0.0,  # DRRS participation (ERCOT only, requires 4hr+ duration)

    # Capacity prices (user-defined, $/kW-month)
    cap_price_summer: float = 14.0,
    cap_price_winter: float = 18.0,
    cap_price_growth: float = 0.01,

    # Battery replacement (for solar+storage with longer project life)
    battery_replacement_year: int = 0,  # 0 = no replacement; e.g. 15 for 30-yr solar+storage
    battery_replacement_cost_pct: float = 0.50,  # replacement cost as fraction of original battery CapEx

    # Solar (colocated)
    include_solar: bool = False,
    solar_mw: float = 100.0,
    solar_capex_per_kw: float = 1000.0,
    solar_om_per_kw_yr: float = 18.0,
    solar_degradation_rate: float = 0.005,
    solar_capacity_factor: float = 0.0,  # 0 = physics-based; NYISO ~0.18, ERCOT ~0.24

    # ERCOT scarcity pricing
    ercot_scarcity_hours: int = 40,

    # Solar tax credit choice
    solar_tax_credit: str = "PTC",  # "PTC" or "ITC" — most utility-scale solar elects PTC under IRA
    ptc_per_mwh: float = 28.0,  # $/MWh for PTC (IRA base rate ~$28/MWh, inflation-adjusted)

    # REC revenue (NYISO Tier 1 RECs)
    rec_price_per_mwh: float = 25.0,  # $/MWh for Tier 1 RECs (NY range ~$20-30/MWh)

    # Offtake / Tolling agreement
    include_offtake: bool = False,
    offtake_pct: float = 0.0,          # fraction of battery capacity under contract
    offtake_price_per_kw_yr: float = 175.0,  # fixed $/kW-yr for contracted share
    offtake_term: int = 20,            # contract duration in years (full project life)
    offtake_escalator: float = 0.015,  # annual escalation rate on tolling rate
    offtake_wacc_benefit: float = 0.015,  # WACC reduction from contracted revenue (financing benefit)

    start_year: int = 2025,
) -> Dict:
    """
    Run full project financial model over the project lifetime.

    Returns dict with:
        - cashflows: list of annual cashflow records
        - summary: dict with NPV, IRR, payback, total revenues
        - hourly_data: dict of year -> hourly detail DataFrames
    """

    # ─── CapEx ────────────────────────────────────────────────────────────────
    # All-in battery cost: $/kW * kW (single metric per NREL 2025 / EIA AEO2025)
    battery_capex = battery_mw * 1000 * battery_capex_per_kw  # in $

    solar_capex = 0.0
    if include_solar:
        solar_capex = solar_mw * 1000 * solar_capex_per_kw  # in $

    total_capex = battery_capex + solar_capex

    # ITC — battery always eligible; solar only if ITC chosen (PTC is alternative)
    if solar_tax_credit == "PTC" and include_solar:
        itc_value = battery_capex * itc_pct  # ITC on battery only
    else:
        itc_value = total_capex * itc_pct  # ITC on everything

    # MACRS depreciable basis (reduced by 50% of ITC per IRS rules)
    depreciable_basis = total_capex - 0.5 * itc_value

    schedule = MACRS_5YR if macrs_schedule == "5yr" else MACRS_7YR
    depreciation = compute_macrs_depreciation(
        depreciable_basis, schedule, project_life, bonus_depreciation_pct
    )

    # ─── Replacement battery depreciation (5-year MACRS from replacement year) ─
    if battery_replacement_year > 0:
        replacement_capex = battery_capex * battery_replacement_cost_pct
        # Replacement battery eligible for its own ITC
        replacement_itc = replacement_capex * itc_pct
        replacement_dep_basis = replacement_capex - 0.5 * replacement_itc
        replacement_dep = compute_macrs_depreciation(
            replacement_dep_basis, MACRS_5YR,
            project_life - battery_replacement_year,  # remaining years
            bonus_depreciation_pct,
        )
        # Add replacement depreciation to the schedule, offset by replacement year
        for i, dep_val in enumerate(replacement_dep):
            yr_idx = battery_replacement_year + i
            if yr_idx < project_life:
                depreciation[yr_idx] += dep_val
    else:
        replacement_itc = 0.0

    # ─── Zone info ────────────────────────────────────────────────────────────
    if market == "NYISO":
        zone_info = NYISO_ZONES.get(zone_name, NYISO_ZONES["Zone J (NYC)"])
        zone_energy_mult = zone_info["energy_mult"]
    else:
        zone_info = ERCOT_ZONES.get(zone_name, ERCOT_ZONES["Houston"])
        zone_energy_mult = zone_info["energy_mult"]

    # ─── Year-by-year model ───────────────────────────────────────────────────
    cashflows = []
    hourly_data = {}
    revenue_by_stream = {"battery_energy": 0, "solar_energy": 0, "capacity": 0, "ancillary": 0, "rec": 0, "offtake": 0}

    for yr in range(1, project_life + 1):
        year = start_year + yr - 1

        # Degradation — reset if battery was replaced; augmentation applies
        # relative to each battery's installation year
        if battery_replacement_year > 0 and yr > battery_replacement_year:
            effective_yr = yr - battery_replacement_year
            deg_factor = compute_battery_degradation(
                effective_yr, annual_degradation, augmentation_year, augmentation_pct
            )
        else:
            deg_factor = compute_battery_degradation(
                yr, annual_degradation, augmentation_year, augmentation_pct
            )
        solar_deg = (1 - solar_degradation_rate) ** yr if include_solar else 1.0

        # Generate hourly prices
        hourly_prices = generate_hourly_prices(
            year=year,
            base_energy_price=base_energy_price,
            zone_energy_mult=zone_energy_mult,
            renewable_penetration=renewable_penetration,
            demand_growth_rate=demand_growth_rate,
            years_from_start=yr - 1,
            market=market,
            seed=42,
            ercot_scarcity_hours=ercot_scarcity_hours if market == "ERCOT" else 0,
        )

        # Solar generation
        solar_gen = None
        if include_solar:
            latitude = 40.7 if market == "NYISO" else 31.0  # NYC vs Texas
            solar_gen = generate_solar_profile(
                year, solar_mw, latitude,
                target_capacity_factor=solar_capacity_factor,
            )

        # ── Energy arbitrage revenue ──────────────────────────────────────────
        energy_rev, hourly_detail = compute_arbitrage_revenue(
            hourly_prices, battery_mw, battery_mwh,
            roundtrip_efficiency, deg_factor, solar_gen
        )

        # Store hourly data
        hourly_data[year] = hourly_detail
        hourly_data[f"{year}_prices"] = hourly_prices

        # ── Capacity revenue ──────────────────────────────────────────────────
        if market == "ERCOT":
            # ERCOT has no capacity market — use RTC+B/scarcity-derived equivalent
            cap_prices = get_ercot_capacity_equivalent(year, start_year)
        else:
            # NYISO: user-defined prices are Zone J base; scale by zone capacity multiplier
            escalation = (1 + cap_price_growth) ** (yr - 1)
            zone_cap_mult = zone_info.get("capacity_mult", 1.0)
            cap_prices = {
                "summer": cap_price_summer * zone_cap_mult * escalation,
                "winter": cap_price_winter * zone_cap_mult * escalation,
            }

        if market == "ERCOT":
            # ERCOT: no accreditation — flat capacity-equivalent based on RTC+B/scarcity value
            # Just battery_kw * price * months (no accreditation multiplier)
            battery_kw = battery_mw * 1000
            capacity_rev = (battery_kw * cap_prices["summer"] * 7 +
                            battery_kw * cap_prices["winter"] * 5) * deg_factor
        else:
            capacity_rev = compute_capacity_revenue(
                battery_mw, cap_prices,
                battery_accred_summer, battery_accred_winter,
                solar_mw if include_solar else 0.0,
                solar_accred_summer, solar_accred_winter,
                deg_factor,
            )

        # ── Ancillary services revenue ────────────────────────────────────────
        anc_rates = get_ancillary_rates(year, start_year, market, demand_growth_rate)
        battery_duration_hrs = battery_mwh / battery_mw if battery_mw > 0 else 4.0
        ancillary_rev = compute_ancillary_revenue(
            battery_mw, anc_rates, regulation_pct, reserve_pct, drrs_pct,
            deg_factor, battery_duration_hrs
        )

        # ── Offtake / Tolling agreement ─────────────────────────────────────
        # The contracted share earns a fixed $/kW-yr that replaces merchant
        # energy + capacity revenue for that portion. Ancillary services are
        # typically retained by the developer. Solar revenue and RECs are
        # also retained (they are separate from the battery tolling).
        offtake_rev = 0.0
        if include_offtake and offtake_pct > 0 and yr <= offtake_term:
            escalated_rate = offtake_price_per_kw_yr * (1 + offtake_escalator) ** (yr - 1)
            offtake_rev = battery_mw * 1000 * offtake_pct * escalated_rate

            # Scale down merchant energy + capacity to uncontracted share only
            merchant_fraction = 1.0 - offtake_pct
            energy_rev = energy_rev * merchant_fraction
            capacity_rev = capacity_rev * merchant_fraction
            # Ancillary services are retained on the full capacity
            # (the offtaker typically doesn't claim ancillary rights)

        # ── Solar energy revenue ──────────────────────────────────────────────
        solar_rev = 0.0
        if include_solar and solar_gen is not None:
            solar_rev = compute_solar_revenue(solar_gen, hourly_prices, solar_deg, battery_mw)

        # ── REC revenue (Tier 1 RECs — NYISO only) ─────────────────────────
        # Tier 1 RECs are a NY Clean Energy Standard program. ERCOT/Texas RECs
        # are essentially worthless (<$1/MWh) due to renewable overbuild vs
        # RPS mandate, so we exclude them from ERCOT runs.
        rec_rev = 0.0
        if include_solar and solar_gen is not None and rec_price_per_mwh > 0:
            rec_rev = compute_rec_revenue(solar_gen, rec_price_per_mwh, solar_deg)

        # ── PTC revenue (10-year credit on solar generation) ─────────────────
        ptc_rev = 0.0
        if include_solar and solar_tax_credit == "PTC" and ptc_per_mwh > 0 and yr <= 10:
            # PTC applies for first 10 years of operation
            annual_solar_mwh = float(np.sum(solar_gen)) * solar_deg if solar_gen is not None else 0.0
            ptc_rev = annual_solar_mwh * ptc_per_mwh

        # ── Costs ─────────────────────────────────────────────────────────────
        fixed_om = battery_mw * 1000 * fixed_om_per_kw_yr  # convert MW to kW

        # Variable O&M based on throughput
        cycles_per_year = 365  # ~1 cycle/day
        throughput_mwh = cycles_per_year * battery_mwh * deg_factor  # degraded capacity per cycle
        variable_om = throughput_mwh * variable_om_per_mwh

        solar_om = 0.0
        if include_solar:
            solar_om = solar_mw * 1000 * solar_om_per_kw_yr

        total_om = fixed_om + variable_om + solar_om

        # Augmentation cost — applies relative to each battery's install year.
        # For the original battery: fires at augmentation_year.
        # For the replacement battery: fires at replacement_year + augmentation_year.
        aug_cost = 0.0
        if augmentation_year > 0:
            if battery_replacement_year > 0 and yr > battery_replacement_year:
                # Replacement battery: augment at its own aug_year into service
                effective_yr = yr - battery_replacement_year
                if effective_yr == augmentation_year:
                    aug_mwh_restored = battery_mwh * augmentation_pct
                    aug_cost = aug_mwh_restored * 1000 * augmentation_cost_per_kwh
            elif yr == augmentation_year and yr != battery_replacement_year:
                # Original battery augmentation
                aug_mwh_restored = battery_mwh * augmentation_pct
                aug_cost = aug_mwh_restored * 1000 * augmentation_cost_per_kwh

        # Battery replacement cost (mid-life swap for solar+storage)
        replacement_cost = 0.0
        if battery_replacement_year > 0 and yr == battery_replacement_year:
            replacement_cost = battery_capex * battery_replacement_cost_pct

        # ── Tax calculation ───────────────────────────────────────────────────
        total_revenue = energy_rev + capacity_rev + ancillary_rev + solar_rev + rec_rev + offtake_rev
        ebitda = total_revenue - total_om - aug_cost - replacement_cost
        taxable_income = ebitda - depreciation[yr - 1]
        tax = max(taxable_income * tax_rate, 0)  # no negative tax (simplified)

        # ITC applied in year 1
        # ITC: year 1 for original system, replacement year for new battery
        itc_benefit = 0
        if yr == 1:
            itc_benefit = itc_value
        elif battery_replacement_year > 0 and yr == battery_replacement_year:
            itc_benefit = replacement_itc

        # PTC is a tax credit (reduces tax liability, similar to ITC but annual)
        ptc_benefit = ptc_rev  # Already computed above; 0 if not using PTC

        # After-tax cash flow
        after_tax_cf = ebitda - tax + itc_benefit + ptc_benefit
        if yr == 1:
            after_tax_cf -= total_capex  # CapEx in year 1

        # Track revenue streams
        revenue_by_stream["battery_energy"] += energy_rev
        revenue_by_stream["solar_energy"] += solar_rev
        revenue_by_stream["capacity"] += capacity_rev
        revenue_by_stream["ancillary"] += ancillary_rev
        revenue_by_stream["rec"] += rec_rev
        revenue_by_stream["offtake"] += offtake_rev

        cashflows.append({
            "year": yr,
            "calendar_year": year,
            "degradation_factor": round(deg_factor, 4),
            "energy_revenue": round(energy_rev, 0),
            "capacity_revenue": round(capacity_rev, 0),
            "ancillary_revenue": round(ancillary_rev, 0),
            "solar_revenue": round(solar_rev, 0),
            "rec_revenue": round(rec_rev, 0),
            "offtake_revenue": round(offtake_rev, 0),
            "ptc_revenue": round(ptc_rev, 0),
            "total_revenue": round(total_revenue, 0),
            "fixed_om": round(fixed_om, 0),
            "variable_om": round(variable_om, 0),
            "solar_om": round(solar_om, 0),
            "augmentation_cost": round(aug_cost, 0),
            "battery_replacement_cost": round(replacement_cost, 0),
            "total_om": round(total_om + aug_cost + replacement_cost, 0),
            "ebitda": round(ebitda, 0),
            "depreciation": round(depreciation[yr - 1], 0),
            "taxable_income": round(taxable_income, 0),
            "tax": round(tax, 0),
            "itc_benefit": round(itc_benefit, 0),
            "ptc_benefit": round(ptc_benefit, 0),
            "capex": round(total_capex if yr == 1 else 0, 0),
            "after_tax_cashflow": round(after_tax_cf, 0),
        })

    # ─── Summary metrics ──────────────────────────────────────────────────────
    cf_series = [cf["after_tax_cashflow"] for cf in cashflows]
    cumulative_cf = np.cumsum(cf_series)

    # Blended WACC: contracted revenue lowers project risk → cheaper financing
    # This is the primary mechanism by which offtake agreements improve project economics
    # in real project finance (higher leverage, lower cost of debt for contracted CFs).
    if include_offtake and offtake_pct > 0 and offtake_wacc_benefit > 0:
        contracted_wacc = max(wacc - offtake_wacc_benefit, 0.02)
        effective_wacc = wacc * (1 - offtake_pct) + contracted_wacc * offtake_pct
    else:
        effective_wacc = wacc

    # NPV (using blended WACC when offtake is active)
    discount_factors = [(1 + effective_wacc) ** (-yr) for yr in range(1, project_life + 1)]
    npv = sum(cf * df for cf, df in zip(cf_series, discount_factors))

    # IRR — use the same after-tax cash flows as NPV for consistency.
    # Year 0 = CapEx outflow (net of ITC), Years 1-N = operating after-tax CFs
    # We must reconstruct this because cf_series has CapEx embedded in year 1.
    operating_cfs = [
        cf["ebitda"] - cf["tax"] + cf["ptc_benefit"]
        for cf in cashflows
    ]
    irr_cashflows = [-total_capex + itc_value] + operating_cfs
    try:
        irr = float(np.irr(irr_cashflows)) if hasattr(np, 'irr') else _compute_irr(irr_cashflows)
    except Exception:
        irr = _compute_irr(irr_cashflows)

    # Payback period
    payback = None
    for i, cum in enumerate(cumulative_cf):
        if cum >= 0:
            payback = i + 1
            break

    # Revenue per kW-yr (key metric)
    total_rev = sum(cf["total_revenue"] for cf in cashflows)
    avg_rev_per_kw_yr = total_rev / (battery_mw * 1000) / project_life * 1000

    summary = {
        "total_capex": total_capex,
        "battery_capex": battery_capex,
        "solar_capex": solar_capex,
        "itc_value": itc_value,
        "npv": round(npv, 0),
        "irr": round(irr * 100, 2) if irr is not None else None,
        "payback_years": payback,
        "total_revenue": round(total_rev, 0),
        "avg_revenue_per_kw_yr": round(avg_rev_per_kw_yr, 2),
        "revenue_by_stream": revenue_by_stream,
        "project_life": project_life,
        # LCOS: Levelized Cost of Storage ($/MWh discharged)
        "lcos": _compute_lcos(total_capex, cashflows, battery_mwh, project_life, effective_wacc),
    }

    return {
        "cashflows": cashflows,
        "summary": summary,
        "hourly_data": hourly_data,
    }


def _compute_irr(cashflows: List[float], tol: float = 1e-6, max_iter: int = 1000) -> Optional[float]:
    """Compute IRR using Newton's method."""
    if not cashflows or all(cf == 0 for cf in cashflows):
        return None

    rate = 0.10  # initial guess
    for _ in range(max_iter):
        npv = sum(cf / (1 + rate) ** i for i, cf in enumerate(cashflows))
        dnpv = sum(-i * cf / (1 + rate) ** (i + 1) for i, cf in enumerate(cashflows))

        if abs(dnpv) < 1e-12:
            break

        new_rate = rate - npv / dnpv

        if abs(new_rate - rate) < tol:
            if -0.5 < new_rate < 1.0:
                return new_rate
            return None

        rate = new_rate

        # Keep rate in reasonable bounds
        rate = max(-0.49, min(rate, 0.99))

    return rate if -0.5 < rate < 1.0 else None


def run_sensitivity(
    param_name: str,
    param_range: List[float],
    base_kwargs: Dict,
) -> List[Dict]:
    """Run model across a range of values for one parameter."""
    results = []
    for val in param_range:
        kwargs = base_kwargs.copy()
        kwargs[param_name] = val
        result = run_full_financial_model(**kwargs)
        results.append({
            "param_value": val,
            "npv": result["summary"]["npv"],
            "irr": result["summary"]["irr"],
            "payback": result["summary"]["payback_years"],
            "avg_rev_per_kw": result["summary"]["avg_revenue_per_kw_yr"],
        })
    return results
