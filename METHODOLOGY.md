# Modeling Methodology

This document describes the analytical approach, assumptions, and calibration behind the Renewable Scenario Comparison Tool. It is intended for reviewers who want to understand the modeling choices and their limitations.

## Market Design Context

The dashboard models two structurally different electricity markets to illustrate how market design affects battery economics:

**NYISO** operates a two-settlement energy market (day-ahead + real-time) plus a mandatory installed capacity market (ICAP). For batteries in downstate New York (Zones G–K), capacity revenue often exceeds energy arbitrage revenue, making accreditation and zone selection critical investment drivers.

**ERCOT** is an energy-only market with no capacity construct. Instead, scarcity pricing during tight supply conditions allows energy prices to spike to $1,000–$3,000/MWh. In December 2025, ERCOT launched Real-Time Co-optimization with Batteries (RTC+B), a major market redesign that co-optimizes energy and ancillary services in real time. The dashboard models these combined revenues as "RTC+B & Scarcity Credits."

## Energy Price Generation

### Approach

Rather than requiring proprietary historical data, the model generates synthetic hourly Locational Marginal Prices (LMPs) that reproduce the statistical properties relevant to battery arbitrage: diurnal spread, seasonal variation, renewable-driven duck curves, price spike frequency, and negative pricing.

Each year's 8,760 hourly prices are constructed as the product of several independent components:

```
LMP(h) = base_price × zone_mult × seasonal(h) × diurnal(h) × demand_growth × renewable_factor × noise(h)
```

Plus additive overlays for price spikes, negative prices, and ERCOT scarcity events.

### Diurnal Shape and the Duck Curve

The diurnal multiplier is the most important component for arbitrage valuation. It is parameterized by renewable penetration (RP) to model how increasing solar generation reshapes the daily price curve:

| Hour Block | Multiplier | Renewable Effect |
|---|---|---|
| 00:00–05:59 (overnight) | 0.65 − RP×0.15 | Wind generation depresses overnight prices |
| 06:00–09:59 (morning ramp) | 0.90 + ramp − RP×0.05 | Solar ramp partially offsets morning demand |
| 10:00–15:59 (midday) | 0.95 − RP×0.55 − RP²×0.30 | Solar floods grid; prices collapse at high RP |
| 16:00–20:59 (evening peak) | 1.15 + RP×0.25 + ramp×sin | Solar drop-off + demand peak = steep ramp |
| 21:00–23:59 (late evening) | 0.85 − RP×0.05 | Slight wind depression |

The quadratic term (RP²×0.30) in the midday block captures the accelerating price suppression observed in high-renewable markets like CAISO, where midday wholesale prices have gone negative at ~40% solar penetration.

At the default 30% RP (NYISO), midday prices average ~$30/MWh while evening peaks reach ~$53/MWh — a ~$23/MWh spread. At 45% RP (ERCOT default), the spread widens further, increasing arbitrage value despite lower average prices.

### Merit Order Effect

Renewables displace marginal gas generation with zero-marginal-cost energy, lowering average prices:

```
renewable_factor = 1.0 − RP×0.25 − RP²×0.15
```

This produces an 8% average price reduction at 30% RP, 22% at 60%, and 34% at 80% — consistent with empirical estimates from European and U.S. markets.

### Negative Pricing

Renewable curtailment events are modeled as a probability function of penetration:

```
P(negative) = RP×0.03 + RP²×0.08
```

Negative prices are confined to midday hours (09:00–16:00) and range from −$2 to −(10 + RP×40) $/MWh. At 30% RP, this produces ~42 negative-price hours per year; at 70%, ~173 hours. These events represent free or paid-to-charge opportunities for batteries.

### ERCOT Scarcity Pricing

ERCOT's scarcity events are modeled as a user-configurable number of hours where prices are set to random values between $1,000 and $3,000/MWh. These are concentrated in summer afternoon peaks (June–August, 14:00–20:00) to match real-world heat-driven scarcity patterns.

The default of 25 hours/year reflects typical ERCOT conditions. Historical data shows extreme-price events ranging from near-zero hours in mild years to 50+ hours during events like Winter Storm Uri (2021) or the August 2023 heat wave. The slider allows modeling across this full range.

## Solar Generation

### Capacity Factor Modeling

Solar generation profiles are built from a physics-based model using solar elevation angle, latitude, and stochastic cloud cover. The raw profile shape (seasonal and diurnal patterns) is then scaled to match a target annual capacity factor:

| Market | Default CF | Source |
|---|---|---|
| NYISO | 18% | EIA / NYISO 2024 actual: 17.7% |
| ERCOT | 24% | EIA / ERCOT 2024 est: ~23% |

The ~6 percentage point difference between markets reflects geographic reality — Texas benefits from stronger solar irradiance at lower latitudes (~31°N vs. ~41°N for New York) and less cloud cover.

Solar degradation follows a linear 0.5%/year rate (industry standard for crystalline silicon modules), applied on top of the capacity factor scaling.

### REC Revenue

Renewable Energy Credits are modeled per-market:

**NYISO Tier 1 RECs** (default $25/MWh) represent certificates procured by NYSERDA under New York's Clean Energy Standard to meet the state's 70% renewable electricity target by 2030. Recent prices range $20–30/MWh.

**ERCOT RECs** (default $1/MWh) reflect the near-zero value of Texas RECs due to massive renewable overbuild relative to the state RPS mandate. The slider allows $0–5/MWh.

## Arbitrage Optimization

The model uses a simplified daily perfect-foresight strategy: for each day, sort the 24 hourly prices, charge during the N cheapest hours (where N = battery duration), and discharge during the N most expensive hours. Roundtrip efficiency losses are applied to discharge revenue.

This approach overstates revenue relative to real-world operations because it assumes perfect price forecasting and ignores inter-temporal constraints (state of charge continuity across days, commitment timing). However, it provides a useful upper bound that is standard in screening-level analysis.

If colocated solar is enabled, solar generation during charging hours partially offsets grid charging costs (50% credit), representing the tax-advantaged benefit of behind-the-meter solar charging.

## Capacity Revenue

### NYISO

NYISO's ICAP market requires load-serving entities to procure capacity to meet peak demand plus reserves. Capacity is priced in $/kW-month through periodic auctions, with significant geographic differentiation.

The model takes user-input Zone J (NYC) base prices as reference and applies zone-specific multipliers:

| Zone | Capacity Multiplier | Typical $/kW-yr Range |
|---|---|---|
| Zone J (NYC) | 1.00 | $80–$120 |
| Zone K (Long Island) | 0.90 | $70–$110 |
| Zone G–I (Lower Hudson) | 0.70–0.80 | $55–$95 |
| Zone F (Capital) | 0.55 | $45–$65 |
| Zone A–E (Upstate) | 0.30–0.40 | $25–$45 |

Seasonal accreditation factors (default 80% summer / 60% winter for batteries, 15% summer / 5% winter for solar) reflect the reliability contribution of 4-hour storage and the limited coincidence of solar output with winter peaks. These are configurable because accreditation rules are actively evolving as more storage connects.

### ERCOT

ERCOT has no capacity market. The dashboard models a capacity-equivalent revenue stream (~$6.6/kW-yr) derived from RTC+B co-optimization value and implicit scarcity pricing. This is intentionally modest — the bulk of ERCOT battery revenue comes through energy arbitrage, ancillary services, and scarcity pricing.

Battery accreditation factors do not apply in ERCOT since there is no capacity product.

## Ancillary Services

Batteries participate in regulation (fast frequency response), spinning reserves, and DRRS (ERCOT only) for a configurable fraction of their capacity:

```
regulation_revenue = battery_mw × regulation_pct × rate × 8,760 hours × degradation
reserve_revenue = battery_mw × reserve_pct × rate × 8,760 hours × degradation
drrs_revenue = battery_mw × drrs_pct × rate × 8,760 hours × degradation  (ERCOT only, 4hr+)
```

NYISO rates (~$12/MW-hr regulation, ~$4.5/MW-hr reserves) reflect the ISO's ancillary services market. ERCOT rates (~$14/MW-hr regulation, ~$9/MW-hr responsive reserves, ~$8/MW-hr DRRS) are higher, reflecting the energy-only market structure where ancillary services are a primary revenue stream for battery storage.

**DRRS (Dispatchable Reliability Reserve Service)** is an ERCOT-only ancillary service compensating resources capable of delivering sustained energy during grid emergencies. It requires a minimum 4-hour battery duration.

The model assumes ancillary participation is additive to arbitrage — a simplification. In practice, MW committed to ancillary services cannot simultaneously capture arbitrage spreads. The configurable participation percentages (default 15% regulation, 10% reserves, 10% DRRS) partially address this by limiting commitment.

## Offtake / Tolling Agreements

The model supports contracted revenue through tolling agreements, where an offtaker pays a fixed $/kW-yr for the right to dispatch a portion of the battery's capacity. This replaces merchant energy + capacity revenue for the contracted share, while ancillary services and solar revenue are retained by the developer.

### Revenue Mechanics

```
offtake_revenue = battery_kW × contracted_% × tolling_rate × (1 + escalator)^(year-1)
merchant_energy = total_energy_revenue × (1 - contracted_%)
merchant_capacity = total_capacity_revenue × (1 - contracted_%)
```

Default tolling rates reflect market conditions: NYISO $150/kW-yr (range $120–175 for 4hr systems) and ERCOT $120/kW-yr (range $100–150), with ERCOT lower due to the absence of a capacity market and energy market saturation from renewable overbuild.

### Financing Benefit (WACC Reduction)

The primary economic value of an offtake agreement is not the tolling rate itself, but the **financing benefit**: contracted cash flows are lower risk, enabling the project to secure cheaper debt (higher leverage, lower interest rate). The model captures this through a blended WACC:

```
effective_wacc = wacc × (1 - contracted_%) + (wacc - benefit) × contracted_%
```

At default values (8% WACC, 70% contracted, 1.5% benefit), the blended WACC drops to ~6.95%. This lower discount rate increases NPV for all cash flows — which is the mechanism by which offtake agreements improve project economics in real project finance, even when the tolling rate is slightly below expected merchant revenue.

## Financial Model

### Capital Costs

Battery CapEx is modeled as a single all-in $/kW metric (pack, inverter, BOS, interconnection, EPC). Defaults are duration-dependent per NREL 2025 / EIA AEO2025:

| Duration | Default CapEx |
|---|---|
| 4-hour | $1,300/kW |
| 6-hour | $1,700/kW |
| 8-hour | $2,100/kW |

Solar CapEx defaults to $1,000/kW for utility-scale installations.

### Tax Treatment

**ITC (Investment Tax Credit):** Default 30% under the Inflation Reduction Act, configurable up to 50% for energy community and domestic content bonus credits. Applied as a one-time benefit in Year 1. Replacement batteries also qualify for their own ITC.

**PTC (Production Tax Credit):** For solar projects electing PTC over ITC. Default $28/MWh (IRA base rate, inflation-adjusted) for the first 10 years of solar generation.

**MACRS Depreciation:** 5-year or 7-year schedule with optional bonus depreciation. Depreciable basis is reduced by 50% of ITC per IRS rules. Replacement batteries get their own 5-year MACRS schedule starting from the replacement year.

Taxable income is EBITDA minus depreciation. Tax is floored at zero (no loss carryforward — a simplification that modestly overstates taxes in early loss years).

### Battery Replacement (Solar+Storage)

For projects with a life exceeding battery economic life (typically 30-year solar+storage), the model supports mid-life battery replacement:

- **Replacement year:** Default year 15 (configurable)
- **Replacement cost:** Default 50% of original battery CapEx (reflecting expected cost declines)
- **Tax treatment:** The replacement battery qualifies for its own ITC (30% of replacement cost) and starts a new 5-year MACRS depreciation schedule
- **Degradation reset:** After replacement, degradation restarts from near-100% capacity
- **Augmentation:** The replacement battery follows its own augmentation schedule (e.g., augmentation at year 25 if original augmentation was at year 10)

### Operating Costs

Fixed O&M ($12.5/kW-yr) covers site maintenance, monitoring, insurance, and land lease. Variable O&M ($2.5/MWh of throughput) covers cycling-related wear. Solar O&M adds $18/kW-yr if applicable.

Augmentation cost ($100/kWh of restored capacity) is a one-time expense in the augmentation year, representing partial battery module replacement to restore degraded capacity.

### Degradation

Battery capacity degrades at a compound annual rate (default 2.5%), with optional augmentation that restores a fraction of original capacity (default 15% in year 10):

```
effective_capacity(yr) = (1 − rate)^yr                              [before augmentation]
effective_capacity(yr) = [(1 − rate)^aug_yr + aug_pct] × (1 − rate)^(yr − aug_yr)  [after]
```

When a battery replacement occurs, degradation resets — the new battery starts fresh with its own degradation and augmentation schedule. Capacity is floored at 10%.

### Summary Metrics

**NPV**: Sum of discounted after-tax cash flows at the effective WACC (blended when offtake is active) over the project life.

**IRR**: Solved via Newton's method from the after-tax cash flow series. Bounded between −49% and +99%.

**Payback Period**: First year where cumulative after-tax cash flow turns positive.

**LCOS (Levelized Cost of Storage)**: PV(all costs including CapEx, O&M, augmentation, replacement) divided by PV(total MWh discharged). The standard metric for comparing storage economics across configurations.

**Revenue per kW-yr**: Total lifetime revenue divided by nameplate kW and project years — the key benchmarking metric for comparing across projects and markets.

## Known Limitations

1. **Perfect foresight arbitrage** overstates energy revenue by 15–25% relative to realistic forecasting-based dispatch. Real operators use day-ahead price forecasts and often capture only 70–85% of the theoretical spread.

2. **No inter-day state of charge management** — each day starts with an empty battery. In practice, overnight carry and multi-day optimization can improve revenue.

3. **Simplified tax treatment** — no loss carryforward, no partnership flip structures, no tax equity modeling. The ITC, PTC, and MACRS implementation is directionally correct but does not capture the full complexity of project finance.

4. **Synthetic prices** — while calibrated to market patterns, synthetic data cannot capture specific locational constraints, transmission congestion, or regulatory changes.

5. **No degradation feedback on dispatch** — the model degrades capacity annually but does not adjust cycling behavior. In practice, operators may reduce cycling to preserve battery life.

6. **Ancillary services opportunity cost** — regulation, reserve, and DRRS revenue is modeled as additive to arbitrage, but in reality these services reduce available capacity for energy market participation.

7. **Offtake WACC benefit is a simplification** — the blended WACC approach captures the directional impact of contracted revenue on financing cost, but real project finance involves complex debt structuring, coverage ratios, and sculpted amortization.
