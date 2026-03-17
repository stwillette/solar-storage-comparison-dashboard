"""
Synthetic market data generator for NYISO and ERCOT electricity markets.
Generates realistic hourly price profiles, capacity prices, and ancillary service rates.
"""

import numpy as np
import pandas as pd
from typing import Dict, Tuple


# ─── NYISO Zone Definitions ───────────────────────────────────────────────────
NYISO_ZONES = {
    "Zone A (West)": {"capacity_mult": 0.35, "energy_mult": 0.85, "label": "A"},
    "Zone B (Genesee)": {"capacity_mult": 0.35, "energy_mult": 0.87, "label": "B"},
    "Zone C (Central)": {"capacity_mult": 0.38, "energy_mult": 0.88, "label": "C"},
    "Zone D (North)": {"capacity_mult": 0.30, "energy_mult": 0.80, "label": "D"},
    "Zone E (Mohawk Valley)": {"capacity_mult": 0.40, "energy_mult": 0.90, "label": "E"},
    "Zone F (Capital)": {"capacity_mult": 0.55, "energy_mult": 0.95, "label": "F"},
    "Zone G (Hudson Valley)": {"capacity_mult": 0.70, "energy_mult": 1.00, "label": "G"},
    "Zone H (Millwood)": {"capacity_mult": 0.75, "energy_mult": 1.02, "label": "H"},
    "Zone I (Dunwoodie)": {"capacity_mult": 0.80, "energy_mult": 1.03, "label": "I"},
    "Zone J (NYC)": {"capacity_mult": 1.00, "energy_mult": 1.10, "label": "J"},
    "Zone K (Long Island)": {"capacity_mult": 0.90, "energy_mult": 1.05, "label": "K"},
}

# ─── ERCOT Zone Definitions ──────────────────────────────────────────────────
ERCOT_ZONES = {
    "Houston": {"energy_mult": 1.05, "label": "HOU"},
    "North": {"energy_mult": 0.95, "label": "NORTH"},
    "South": {"energy_mult": 0.98, "label": "SOUTH"},
    "West": {"energy_mult": 1.10, "label": "WEST"},
    "Panhandle": {"energy_mult": 0.80, "label": "PAN"},
}


def generate_hourly_prices(
    year: int,
    base_energy_price: float = 35.0,
    zone_energy_mult: float = 1.0,
    renewable_penetration: float = 0.30,
    demand_growth_rate: float = 0.015,
    years_from_start: int = 0,
    market: str = "NYISO",
    seed: int = 42,
    ercot_scarcity_hours: int = 0,
) -> pd.DataFrame:
    """
    Generate synthetic hourly LMP data for a single year.

    Calibrated so that a 4-hour battery doing 1 cycle/day of arbitrage
    earns roughly $40-70/kW-yr in energy revenue (realistic range).
    """
    rng = np.random.RandomState(seed + year)

    hours_in_year = 8760
    hours = np.arange(hours_in_year)
    hour_of_day = hours % 24
    day_of_year = hours // 24
    month = np.minimum((day_of_year * 12) // 365, 11)

    # Demand growth escalation
    growth_factor = (1 + demand_growth_rate) ** years_from_start

    # Seasonal pattern (higher in summer/winter)
    if market == "NYISO":
        seasonal = 1.0 + 0.15 * np.sin(2 * np.pi * (day_of_year - 30) / 365)  # winter bump
        seasonal += 0.20 * np.where((month >= 5) & (month <= 8), 1, 0)  # summer bump
    else:  # ERCOT - more extreme summer
        seasonal = 0.90 + 0.35 * np.where((month >= 5) & (month <= 8), 1, 0)
        seasonal += 0.05 * np.sin(2 * np.pi * (day_of_year - 30) / 365)

    # Diurnal pattern - key driver of arbitrage spread
    # Renewable penetration reshapes the duck curve:
    #   - Midday prices collapse as solar floods the grid (merit order effect)
    #   - Evening ramp steepens as solar drops off and demand peaks
    #   - Overnight prices drop slightly with excess wind
    # At 30% renewables: moderate duck curve; at 60%+: deep trough with negative midday
    rp = renewable_penetration  # shorthand

    diurnal = np.ones(hours_in_year)
    for h in range(24):
        mask = hour_of_day == h
        if 0 <= h <= 5:       # overnight — moderate demand, some wind depression
            # At 30% RP → ~0.75x, at 60% → ~0.70x, at 80% → ~0.65x
            diurnal[mask] = 0.80 - rp * 0.10
        elif 6 <= h <= 9:     # morning ramp
            diurnal[mask] = 0.90 + 0.10 * (h - 6) / 3 - rp * 0.05
        elif 10 <= h <= 15:   # midday solar trough (duck curve belly)
            # Deep depression driven by solar flooding the grid
            # At 30% RP → ~0.55x, at 60% → ~0.30x, at 80% → ~0.12x
            # This is the primary charging window for batteries
            solar_depress = rp * 0.85 + rp ** 2 * 0.40
            diurnal[mask] = 0.80 - solar_depress
            # Even deeper in summer months (more solar generation)
            summer_mask = mask & ((month >= 4) & (month <= 8))
            diurnal[summer_mask] = max(0.05, 0.75 - solar_depress * 1.15)
        elif 16 <= h <= 20:   # evening peak (duck curve neck) — steeper with more renewables
            # Solar ramp-down + demand peak → highest prices of the day
            ramp_boost = rp * 0.30
            diurnal[mask] = 1.20 + ramp_boost + (0.20 + rp * 0.12) * np.sin(np.pi * (h - 16) / 4)
        else:                 # late evening
            diurnal[mask] = 0.85 - rp * 0.05

    # Merit order effect: renewables displace marginal gas generation, lowering average prices
    # At 30% RP → ~8% reduction; at 60% → ~22%; at 80% → ~34%
    renewable_factor = 1.0 - rp * 0.25 - rp ** 2 * 0.15

    # Base LMP
    lmp = base_energy_price * zone_energy_mult * seasonal * diurnal * growth_factor * renewable_factor

    # Random noise (log-normal for realistic fat tails)
    noise = rng.lognormal(mean=0, sigma=0.15, size=hours_in_year)
    lmp = lmp * noise

    # Occasional price spikes (realistic: ~50-100 hours/year with high prices)
    spike_probability = 0.008 * growth_factor
    if market == "ERCOT":
        spike_probability *= 1.5  # ERCOT has more volatility
    spikes = rng.random(hours_in_year) < spike_probability
    spike_magnitudes = rng.uniform(80, 300, hours_in_year)  # moderate spikes
    lmp = np.where(spikes, lmp + spike_magnitudes, lmp)

    # Negative prices from renewable curtailment — frequency and depth scale with penetration
    # At 30% RP: ~1% of midday hours negative; at 60%: ~5%; at 80%: ~10%+
    neg_probability = rp * 0.03 + rp ** 2 * 0.08
    negatives = rng.random(hours_in_year) < neg_probability
    neg_floor = -10 - rp * 40  # deeper negatives at higher penetration (up to -$42/MWh at 80%)
    neg_prices = rng.uniform(neg_floor, -2, hours_in_year)
    lmp = np.where(negatives & (hour_of_day >= 9) & (hour_of_day <= 16), neg_prices, lmp)

    # ERCOT scarcity pricing: inject user-defined number of $1,000-$1,500/MWh hours
    # These are concentrated in summer afternoon/evening peaks (Jun-Aug, hours 14-20)
    # reflecting the real-world pattern of extreme heat-driven scarcity events
    if market == "ERCOT" and ercot_scarcity_hours > 0:
        scarcity_rng = np.random.RandomState(seed + year + 9999)
        # Candidate hours: summer months (Jun=6, Jul=7, Aug=8), peak hours 14-20
        summer_peak_mask = ((month >= 5) & (month <= 7) &
                           (hour_of_day >= 14) & (hour_of_day <= 20))
        candidate_indices = np.where(summer_peak_mask)[0]
        n_scarcity = min(ercot_scarcity_hours, len(candidate_indices))
        if n_scarcity > 0:
            scarcity_indices = scarcity_rng.choice(
                candidate_indices, size=n_scarcity, replace=False
            )
            scarcity_prices = scarcity_rng.uniform(1000, 3000, size=n_scarcity)
            lmp[scarcity_indices] = scarcity_prices

    # Floor at -30 $/MWh
    lmp = np.maximum(lmp, -30)

    # Build DataFrame
    start = pd.Timestamp(f"{year}-01-01")
    timestamps = pd.date_range(start, periods=hours_in_year, freq="h")

    df = pd.DataFrame({
        "timestamp": timestamps,
        "hour": hour_of_day,
        "month": month + 1,
        "day_of_year": day_of_year + 1,
        "lmp": np.round(lmp, 2),
    })

    return df


def get_nyiso_capacity_price(
    zone_name: str,
    year: int,
    start_year: int = 2025,
    demand_growth_rate: float = 0.015,
) -> Dict[str, float]:
    """
    Return monthly capacity prices ($/kW-month) for NYISO zone.

    Calibrated to real NYISO ICAP values:
    - Zone J (NYC): ~$10-14/kW-month (~$120-168/kW-yr)
    - Upstate zones: ~$1-4/kW-month (~$12-48/kW-yr)
    """
    zone_info = NYISO_ZONES.get(zone_name, NYISO_ZONES["Zone J (NYC)"])
    mult = zone_info["capacity_mult"]

    years_elapsed = year - start_year
    growth = (1 + demand_growth_rate * 0.5) ** years_elapsed  # capacity prices grow slower

    # Base capacity price for Zone J = ~$11/kW-month
    base_price = 11.0 * mult * growth

    # Summer/winter differential
    summer_price = base_price * 1.15  # Apr-Oct
    winter_price = base_price * 0.85  # Nov-Mar

    return {"summer": round(summer_price, 2), "winter": round(winter_price, 2)}


def get_ercot_capacity_equivalent(
    year: int,
    start_year: int = 2025,
) -> Dict[str, float]:
    """
    ERCOT has no capacity market but batteries earn capacity-like revenue
    through RTC+B co-optimization and scarcity pricing. Return an equivalent
    value for comparison (much lower than NYISO).
    """
    # ERCOT has no formal capacity market; battery capacity-equivalent
    # revenue comes from RTC+B value and scarcity pricing (~$5-10/kW-yr)
    years_elapsed = year - start_year
    growth = (1 + 0.02) ** years_elapsed
    base = 0.55 * growth  # $/kW-month equivalent (~$6.6/kW-yr)
    return {"summer": round(base * 1.3, 2), "winter": round(base * 0.7, 2)}


def get_ancillary_rates(
    year: int,
    start_year: int = 2025,
    market: str = "NYISO",
    demand_growth_rate: float = 0.015,
) -> Dict[str, float]:
    """
    Return ancillary service rates ($/MW-hr for regulation, $/MW-hr for reserves, and DRRS).

    Calibrated to realistic values:
    - NYISO regulation: ~$10-20/MW-hr
    - NYISO spinning reserves: ~$3-8/MW-hr
    - ERCOT regulation: ~$12-18/MW-hr (reflects higher AS value in energy-only market)
    - ERCOT responsive reserves: ~$8-14/MW-hr (RRS is a key revenue stream for BESS)
    - ERCOT DRRS: ~$6-10/MW-hr (Dispatchable Reliability Reserve Service, requires 4hr duration)
    """
    years_elapsed = year - start_year
    growth = (1 + demand_growth_rate * 0.3) ** years_elapsed

    if market == "NYISO":
        return {
            "regulation": round(12.0 * growth, 2),
            "spinning_reserve": round(4.5 * growth, 2),
            "drrs": 0.0,  # DRRS is ERCOT-only
        }
    else:  # ERCOT — higher ancillary rates reflecting energy-only market where
           # AS revenues are a primary value stream for batteries
        return {
            "regulation": round(14.0 * growth, 2),
            "spinning_reserve": round(9.0 * growth, 2),
            "drrs": round(8.0 * growth, 2),  # DRRS for 4hr+ batteries
        }


def generate_solar_profile(
    year: int,
    solar_mw: float = 100.0,
    latitude: float = 40.7,  # NYC default
    target_capacity_factor: float = 0.0,  # 0 = use physics-based estimate
    seed: int = 42,
) -> np.ndarray:
    """
    Generate synthetic hourly solar capacity factors for a year.
    Returns array of hourly generation in MW.

    If target_capacity_factor > 0, the profile shape is preserved but scaled
    so the annual capacity factor matches the target (e.g. 0.18 for NYISO,
    0.24 for ERCOT).
    """
    rng = np.random.RandomState(seed + year + 1000)
    hours_in_year = 8760
    hours = np.arange(hours_in_year)
    hour_of_day = hours % 24
    day_of_year = hours // 24

    # Solar elevation approximation
    declination = 23.45 * np.sin(2 * np.pi * (day_of_year - 81) / 365)
    hour_angle = (hour_of_day - 12) * 15  # degrees

    lat_rad = np.radians(latitude)
    dec_rad = np.radians(declination)
    ha_rad = np.radians(hour_angle)

    sin_elevation = (np.sin(lat_rad) * np.sin(dec_rad) +
                     np.cos(lat_rad) * np.cos(dec_rad) * np.cos(ha_rad))
    sin_elevation = np.maximum(sin_elevation, 0)

    # Capacity factor with cloud cover
    cf = sin_elevation * 0.85  # panel efficiency
    cloud_factor = rng.uniform(0.5, 1.0, hours_in_year)
    cf = cf * cloud_factor

    # Cap at realistic max CF
    cf = np.minimum(cf, 0.90)

    # Scale to target capacity factor if specified
    if target_capacity_factor > 0:
        raw_cf = float(np.mean(cf))
        if raw_cf > 0:
            cf = cf * (target_capacity_factor / raw_cf)
            cf = np.minimum(cf, 0.95)  # hard cap at 95% instantaneous

    generation = cf * solar_mw
    return np.round(generation, 2)


def compute_arbitrage_revenue(
    hourly_prices: pd.DataFrame,
    battery_mw: float,
    battery_mwh: float,
    roundtrip_efficiency: float = 0.87,
    degradation_factor: float = 1.0,
    solar_generation: np.ndarray = None,
) -> Tuple[float, pd.DataFrame]:
    """
    Daily battery arbitrage with dispatch logic that depends on whether
    solar is co-located.

    **Standalone battery** — charge during the cheapest hours of the day
    (price-optimal, no time-of-day constraint).

    **Solar+storage** — charge primarily during daytime solar hours (6am–6pm)
    when solar is depressing prices, capturing the duck-curve belly.
    Evening/overnight charging (6pm–6am) is only allowed if prices fall
    below a wind-driven threshold (bottom 15th percentile of the day),
    reflecting excess cheap wind on the grid.

    Discharge always targets the most expensive hours of the day.

    Returns total annual revenue and hourly detail DataFrame.
    """
    effective_mwh = battery_mwh * degradation_factor
    duration_hours = effective_mwh / battery_mw
    charge_hours = int(np.ceil(duration_hours))
    discharge_hours = int(np.ceil(duration_hours))

    prices = hourly_prices["lmp"].values
    hours = hourly_prices["hour"].values
    n_days = len(prices) // 24

    has_solar = solar_generation is not None

    total_revenue = 0.0
    hourly_detail = []

    for d in range(n_days):
        day_start = d * 24
        day_end = day_start + 24
        day_prices = prices[day_start:day_end]
        day_hours = hours[day_start:day_end]

        if len(day_prices) < 24:
            continue

        # ── Select charging hours ────────────────────────────────────────
        if has_solar:
            # Solar+storage: prefer daytime charging (hours 6–17 inclusive)
            # to align with solar production window.
            daytime_mask = np.array([(6 <= h <= 17) for h in range(24)])
            daytime_idx = np.where(daytime_mask)[0]
            night_idx = np.where(~daytime_mask)[0]

            # Rank daytime hours by price (cheapest first)
            daytime_sorted = daytime_idx[np.argsort(day_prices[daytime_idx])]

            # Fill charge slots from daytime first
            charge_idx = list(daytime_sorted[:charge_hours])

            # If not enough daytime hours to fill (shouldn't happen for 4hr
            # battery, but handle gracefully), allow cheap overnight hours
            # ONLY if they are priced below the day's wind-threshold.
            # Wind threshold = 15th percentile of that day's prices — prices
            # this low typically signal excess wind generation on the grid.
            if len(charge_idx) < charge_hours:
                wind_threshold = np.percentile(day_prices, 15)
                cheap_night = night_idx[day_prices[night_idx] <= wind_threshold]
                cheap_night_sorted = cheap_night[np.argsort(day_prices[cheap_night])]
                remaining = charge_hours - len(charge_idx)
                charge_idx.extend(list(cheap_night_sorted[:remaining]))

            charge_idx = sorted(charge_idx[:charge_hours])
        else:
            # Standalone battery: unrestricted — pick cheapest hours
            sorted_idx = np.argsort(day_prices)
            charge_idx = sorted(sorted_idx[:charge_hours])

        # ── Select discharge hours (always price-optimal) ────────────────
        sorted_idx_desc = np.argsort(day_prices)[::-1]
        discharge_idx = []
        for i in sorted_idx_desc:
            if i not in charge_idx:
                discharge_idx.append(i)
            if len(discharge_idx) >= discharge_hours:
                break
        discharge_idx = sorted(discharge_idx)

        # ── Calculate revenue ────────────────────────────────────────────
        charge_cost = sum(day_prices[i] * battery_mw for i in charge_idx)
        discharge_rev = sum(day_prices[i] * battery_mw * roundtrip_efficiency
                            for i in discharge_idx)

        # Solar co-charging: solar that charges the battery displaces grid
        # purchases at the full LMP, saving 100% of the avoided charge cost.
        solar_offset = 0.0
        if has_solar:
            solar_day = solar_generation[day_start:day_end]
            for i in charge_idx:
                solar_avail = min(solar_day[i], battery_mw)
                solar_offset += solar_avail * day_prices[i]

        day_revenue = discharge_rev - charge_cost + solar_offset
        total_revenue += max(day_revenue, 0)  # don't operate if negative

        # ── Record hourly detail ─────────────────────────────────────────
        for h in range(24):
            action = "idle"
            if h in charge_idx:
                action = "charge"
            elif h in discharge_idx:
                action = "discharge"
            hourly_detail.append({
                "day": d + 1,
                "hour": h,
                "price": day_prices[h],
                "action": action,
                "month": hourly_prices.iloc[day_start + h]["month"],
            })

    detail_df = pd.DataFrame(hourly_detail)
    return total_revenue, detail_df


def compute_capacity_revenue(
    battery_mw: float,
    capacity_prices: Dict[str, float],
    battery_accred_summer: float = 0.90,
    battery_accred_winter: float = 0.75,
    solar_mw: float = 0.0,
    solar_accred_summer: float = 0.50,
    solar_accred_winter: float = 0.10,
    degradation_factor: float = 1.0,
) -> float:
    """
    Compute annual capacity market revenue.
    Summer = Apr-Oct (7 months), Winter = Nov-Mar (5 months).
    Separate accreditation for battery and solar.
    """
    summer_months = 7
    winter_months = 5

    # Battery capacity revenue (convert MW to kW since prices are $/kW-month)
    battery_kw = battery_mw * 1000
    battery_summer = (battery_kw * battery_accred_summer * degradation_factor *
                      capacity_prices["summer"] * summer_months)
    battery_winter = (battery_kw * battery_accred_winter * degradation_factor *
                      capacity_prices["winter"] * winter_months)

    # Solar capacity revenue (if colocated)
    solar_kw = solar_mw * 1000
    solar_summer = solar_kw * solar_accred_summer * capacity_prices["summer"] * summer_months
    solar_winter = solar_kw * solar_accred_winter * capacity_prices["winter"] * winter_months

    return battery_summer + battery_winter + solar_summer + solar_winter


def compute_ancillary_revenue(
    battery_mw: float,
    ancillary_rates: Dict[str, float],
    regulation_pct: float = 0.15,
    reserve_pct: float = 0.10,
    drrs_pct: float = 0.0,
    degradation_factor: float = 1.0,
    battery_duration_hrs: float = 4.0,
) -> float:
    """
    Compute annual ancillary services revenue.
    Battery participates in regulation, reserves, and DRRS (ERCOT only) for a fraction of hours.
    DRRS requires minimum 4-hour duration battery.
    """
    hours_in_year = 8760

    reg_revenue = (battery_mw * regulation_pct * degradation_factor *
                   ancillary_rates["regulation"] * hours_in_year)

    reserve_revenue = (battery_mw * reserve_pct * degradation_factor *
                       ancillary_rates["spinning_reserve"] * hours_in_year)

    # DRRS revenue (ERCOT only, requires 4hr+ duration)
    drrs_revenue = 0.0
    drrs_rate = ancillary_rates.get("drrs", 0.0)
    if drrs_rate > 0 and drrs_pct > 0 and battery_duration_hrs >= 4.0:
        drrs_revenue = (battery_mw * drrs_pct * degradation_factor *
                        drrs_rate * hours_in_year)

    return reg_revenue + reserve_revenue + drrs_revenue


def compute_solar_revenue(
    solar_generation: np.ndarray,
    hourly_prices: pd.DataFrame,
    solar_degradation_factor: float = 1.0,
    battery_mw: float = 0.0,
) -> float:
    """
    Compute solar energy revenue (generation sold at LMP, net of what charges battery).

    Uses price-optimized dispatch: when prices are low or negative, more solar
    is routed to the battery (up to battery_mw capacity). When prices are high,
    solar is sold to the grid. This reflects real-world co-optimization where
    the operator maximizes total value across both solar sales and battery charging.
    """
    if solar_generation is None or len(solar_generation) == 0:
        return 0.0

    prices = hourly_prices["lmp"].values
    min_len = min(len(solar_generation), len(prices))

    gen = solar_generation[:min_len] * solar_degradation_factor
    p = prices[:min_len]

    # Price-optimized dispatch: route solar to battery when prices are low
    # Battery absorbs up to battery_mw each hour; remainder sold to grid
    if battery_mw > 0:
        # When price <= 0, route as much as possible to battery (avoid selling at loss)
        # When price > 0 but low, still favor battery charging up to capacity
        # The battery charging value is captured in compute_arbitrage_revenue via solar_offset
        battery_charge = np.minimum(gen, battery_mw)
        # Only route to battery when price is below the daily median (proxy for "cheap hours")
        n_days = min_len // 24
        grid_sales = gen.copy()
        for d in range(n_days):
            s, e = d * 24, (d + 1) * 24
            if e > min_len:
                break
            day_prices = p[s:e]
            median_price = np.median(day_prices[day_prices > 0]) if np.any(day_prices > 0) else 0
            for h in range(s, e):
                if p[h] <= max(median_price * 0.5, 0):
                    # Low/negative price hour: route to battery
                    routed = min(gen[h], battery_mw)
                    grid_sales[h] = gen[h] - routed
                else:
                    # High price hour: sell everything to grid
                    grid_sales[h] = gen[h]
    else:
        grid_sales = gen

    revenue = np.sum(grid_sales * p)
    return max(revenue, 0)


def compute_rec_revenue(
    solar_generation: np.ndarray,
    rec_price_per_mwh: float = 25.0,
    solar_degradation_factor: float = 1.0,
) -> float:
    """
    Compute Renewable Energy Credit (REC) revenue from solar generation.

    In NYISO, Tier 1 RECs are earned per MWh of eligible renewable generation.
    All solar output earns RECs regardless of whether the energy is sold to
    grid or used to charge the battery.

    Args:
        solar_generation: Hourly solar generation array in MW
        rec_price_per_mwh: REC price in $/MWh (NY Tier 1 RECs ~$20-30/MWh)
        solar_degradation_factor: Annual degradation applied to solar output

    Returns:
        Annual REC revenue in $
    """
    if solar_generation is None or len(solar_generation) == 0:
        return 0.0

    annual_mwh = float(np.sum(solar_generation)) * solar_degradation_factor
    return annual_mwh * rec_price_per_mwh
