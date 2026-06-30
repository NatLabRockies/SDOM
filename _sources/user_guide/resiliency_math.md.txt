# Resiliency Mathematical Formulation

This page specifies the two optimization problems used by the resiliency
module:

- **(B)** Baseline annual economic dispatch on fixed capacities (with demand
  charges).
- **(O)** Per-hour outage economic dispatch (slack + penalty).

Resiliency metrics are derived from the family of solutions to (O). The
narrative usage guide is in {doc}`resiliency`.

---

## 1. Sets

| Symbol | Description |
| --- | --- |
| $\mathcal{T} = \lbrace 1, \ldots, N_T \rbrace$ | Hours of the baseline horizon (default $N_T = 8760$). |
| $\mathcal{M} = \lbrace 1, \ldots, 12 \rbrace$ | Calendar months (used by demand-charge billing). |
| $\mathcal{T}_m \subset \mathcal{T}$ | Hours belonging to month $m$. |
| $\mathcal{T}^{out}_h$ | Outage horizon anchored at hour $h$: $\lbrace h, h+1, \ldots, h + \Delta^{out} + \Delta^{rec} - 1 \rbrace$, clipped to $\mathcal{T}$. |
| $\mathcal{S}$ | Storage technologies. |
| $\mathcal{W}$ | Wind plants. |
| $\mathcal{K}$ | Solar PV plants. |
| $\mathcal{B}$ | Balancing (thermal) units, indexed by `Plant_id`. |
| $\mathcal{N}, \mathcal{O}, \mathcal{R}$ | Must-run sources: nuclear, other renewables, hydro (each treated as a single aggregate stream driven by a time series). |
| $\mathcal{B}^{out}, \mathcal{W}^{out}, \mathcal{K}^{out}, \mathcal{S}^{out}, \mathcal{I}^{out}, \mathcal{N}^{out}, \mathcal{O}^{out}, \mathcal{R}^{out}$ | Subsets selected for outage / de-rating in a given `OutageSpec`. Storage technologies can be outaged like any other capacity-bounded asset; the multiplier $\delta_{s,t}$ applies to both charge and discharge bounds (section 5.3). |

---

## 2. Parameters

### 2.1 Designed capacities (fixed)

| Symbol | Description | Source |
| --- | --- | --- |
| $Cap^{B}_{b}$ | Capacity of balancing unit $b$ (MW). | `OutputSummary_*.csv` / `Data_Balancing_units_*.csv` |
| $Cap^{W}_{w}, Cap^{K}_{k}$ | Designed wind / solar capacities (MW). | `OutputSelectedVRE_*.csv` |
| $Cap^{Pch}_{s}, Cap^{Pdis}_{s}$ | Storage charge / discharge power (MW). | `OutputSummary_*.csv` (or derived from `OutputStorage_*.csv`) |
| $Cap^{E}_{s}$ | Storage energy capacity (MWh). | Same as above |
| $\overline{P}^{imp}_{t}, \overline{P}^{exp}_{t}$ | Hourly import / export capacity (MW). | `Import_Cap_*.csv`, `Export_Cap_*.csv` |

### 2.2 Time series

| Symbol | Description | Source |
| --- | --- | --- |
| $D_{t}$ | Demand at hour $t$ (MW). | `Load_hourly_*.csv` |
| $A^{W}_{w,t} \in [0,1]$ | Wind capacity factor. | `CFWind_*.csv` |
| $A^{K}_{k,t} \in [0,1]$ | Solar capacity factor. | `CFSolar_*.csv` |
| $G^{nuc}_{t}, G^{otre}_{t}, G^{hydro}_{t}$ | Must-run / scheduled generation (MW). | `Nucl_hourly_*.csv`, `otre_hourly_*.csv`, `lahy_hourly_*.csv` |

### 2.3 Costs

| Symbol | Description | Source |
| --- | --- | --- |
| $c^{B}_{b}$ | Variable cost of balancing unit $b$: $\mathrm{HeatRate}_b \cdot \mathrm{FuelCost}_b + \mathrm{VOM}_b$ (USD/MWh). | `Data_Balancing_units_*.csv` |
| $c^{imp}_{t}, c^{exp}_{t}$ | Energy price (USD/MWh). | `import_prices_*.csv`, `export_prices_*.csv` |
| $\phi^{var}_{t}$ | Hourly variable demand-charge tariff (USD/MW). Hourly-varying. | `var_dem_charges.csv` |
| $\phi^{fix}_{t}$ | Hourly fixed demand-charge tariff (USD/MW). Constant within each month. | `fixed_dem_charges.csv` |
| $c^{vom}_{s}$ | Storage VOM (USD/MWh). | `StorageData_*.csv` |
| $f^{B}_{b}$ | Fixed O&M of balancing unit $b$ (USD/kW-yr). | `Data_Balancing_units_*.csv` column `FOM` |
| $f^{W}_{w}$ | Fixed O&M of wind plant $w$ (USD/kW-yr). | `CapWind_*.csv` column `FOM_M` |
| $f^{K}_{k}$ | Fixed O&M of solar plant $k$ (USD/kW-yr). | `CapSolar_*.csv` column `FOM_M` |
| $f^{S}_{s}$ | Fixed O&M of storage technology $s$ (USD/kW-yr), applied to power capacity. | `StorageData_*.csv` row `FOM` |
| $\alpha_{s} \in [0,1]$ | Cost-ratio split of storage FOM between charge and discharge sides. | `StorageData_*.csv` row `CostRatio` |
| $M_{kW} = 10^{3}$ | Unit conversion (MW $\to$ kW), since FOM parameters are in USD/kW-yr while capacities are in MW. | constant |
| $H^{yr} = 8760$ | Hours per year. Used to prorate annual FOM to the outage horizon length in (O). | constant |
| $\pi^{slack}$ | Penalty on unserved energy (USD/MWh). Default $10^{4}$. | User (`OutageSpec` / kwarg) |
| $\pi^{curt}$ | Penalty on curtailed VRE energy (USD/MWh). Default $0$ (free curtailment). | User (kwarg) |
| $\pi^{soc}$ | Penalty on SOC recovery-target slack (USD/MWh). Default $10^{3}$. Applies to Problem (O) only. | User (kwarg) |

### 2.4 Outage / operational

| Symbol | Description |
| --- | --- |
| $\Delta^{out}$ | Outage duration (hours), or per-asset $\Delta^{out}_{a}$. |
| $\Delta^{rec}$ | Recovery window (hours), single value or per-storage $\Delta^{rec}_{s}$. |
| $H^{out}(h)$ | Length of the outage horizon $\mathcal{T}^{out}_h$ in hours, after end-of-year clipping: $H^{out}(h) = |\mathcal{T}^{out}_h|$. |
| $\delta_{a,t} \in [0,1]$ | Time-varying capacity multiplier from outage. Equals the user-defined derating value (default $0$) inside the outage window $[h, h + \Delta^{out}_a - 1]$, and equals $1$ everywhere else, including the entire recovery window $[h + \Delta^{out}, h + \Delta^{out} + \Delta^{rec} - 1]$. Defined for all capacity-bounded assets, including storage charge / discharge bounds. |
| $\delta^{nuc}_{t}, \delta^{otre}_{t}, \delta^{hydro}_{t} \in [0,1]$ | Same outage / de-rating mechanism applied to the **must-run time-series sources** (nuclear, other renewables, hydro). The user-supplied factor multiplies the input time series during the outage window; equals $1$ outside the outage window. |
| $SOC^{min}_{s}$ | Operational SOC floor (fraction of $Cap^{E}_{s}$). |
| $SOC^{rec}_{s}$ | Required SOC at end of recovery window (fraction of $Cap^{E}_{s}$). |
| $SOC^{base}_{s,h}$ | Baseline SOC trajectory value used as the *prior-state* boundary $SOC^{init}_{s}$ at the start of the outage horizon. Sourced from `baseline_results.soc_trajectory.loc[h, s]`. |
| $SOC^{init}_{s}$ | Initial SOC boundary value at the start of $\mathcal{T}^{out}_h$, conceptually equal to $SOC_{s,h-1}$. Used by the storage dynamics equation at $t = h$. |

---

## 3. Variables

Defined for both problems unless noted. All non-negative.

| Symbol | Description |
| --- | --- |
| $p^{B}_{b,t}$ | Generation of balancing unit $b$ (MW). |
| $p^{W}_{w,t}, p^{K}_{k,t}$ | Dispatched wind / solar (curtailable, MW). |
| $p^{ch}_{s,t}, p^{dis}_{s,t}$ | Storage charge / discharge power (MW). |
| $SOC_{s,t}$ | Storage state of charge (MWh). |
| $p^{imp}_{t}, p^{exp}_{t}$ | Imports / exports (MW). |
| $D^{fix}_{m}, D^{var}_{m}$ | Monthly demand-charge cost (USD), one per month. Defined as the maximum tariff-weighted import in month $m$ via section 5.4. Problem (B) only by default. |
| $u_{t}$ | Unserved-energy slack (MWh). **Problem (O) only.** |
| $\sigma^{rec}_{s}$ | SOC recovery-target slack (MWh). Non-negative relaxation of the per-tech end-of-recovery target (section 5.5). **Problem (O) only.** |

---

## 4. Objective Functions

### 4.1 Problem (B): Baseline annual dispatch

Minimize the total operational cost

$$
Z^{B} = Z^{B}_{thermal} + Z^{B}_{storage} + Z^{B}_{imp} + Z^{B}_{exp} + Z^{B}_{dem} + Z^{B}_{curt} + Z^{B}_{FOM}.
$$

with components

$$
Z^{B}_{thermal} = \sum_{t \in \mathcal{T}} \sum_{b \in \mathcal{B}} c^{B}_{b} \, p^{B}_{b,t}.
$$

$$
Z^{B}_{storage} = \sum_{t \in \mathcal{T}} \sum_{s \in \mathcal{S}} c^{vom}_{s} \, (p^{ch}_{s,t} + p^{dis}_{s,t}).
$$

$$
Z^{B}_{imp} = \sum_{t \in \mathcal{T}} c^{imp}_{t} \, p^{imp}_{t}.
$$

$$
Z^{B}_{exp} = - \sum_{t \in \mathcal{T}} c^{exp}_{t} \, p^{exp}_{t}.
$$

$$
Z^{B}_{dem} = \sum_{m \in \mathcal{M}} \left( D^{fix}_{m} + D^{var}_{m} \right).
$$

Each $D^{k}_{m}$ ($k \in \lbrace fix, var \rbrace$) is the monthly peak of the
tariff-weighted imports power, enforced as a linear maximum in section 5.4.
Because the tariffs $\phi^{k}_{t}$ are expressed in USD/MW, the products
$\phi^{k}_{t} \cdot p^{imp}_{t}$ and the variables $D^{k}_{m}$ are in USD.

$$
Z^{B}_{curt} = \pi^{curt} \sum_{t \in \mathcal{T}} \left[ \sum_{w \in \mathcal{W}} (A^{W}_{w,t} \, Cap^{W}_{w} - p^{W}_{w,t}) + \sum_{k \in \mathcal{K}} (A^{K}_{k,t} \, Cap^{K}_{k} - p^{K}_{k,t}) \right].
$$

$$
\begin{aligned}
Z^{B}_{FOM} = \; & M_{kW} \left[
    \sum_{b \in \mathcal{B}} f^{B}_{b} \, Cap^{B}_{b}
    + \sum_{w \in \mathcal{W}} f^{W}_{w} \, Cap^{W}_{w}
    + \sum_{k \in \mathcal{K}} f^{K}_{k} \, Cap^{K}_{k} \right.\\
    & \left. + \sum_{s \in \mathcal{S}} f^{S}_{s} \left( \alpha_{s} \, Cap^{Pch}_{s} + (1 - \alpha_{s}) \, Cap^{Pdis}_{s} \right)
\right].
\end{aligned}
$$

Because capacities are fixed parameters in (B), $Z^{B}_{FOM}$ is a constant
added to the reported objective. It does not influence the optimal
dispatch decisions but is required for an apples-to-apples comparison
with the CEM total system cost. Storage FOM is applied **only to the
power components** ($Cap^{Pch}_{s}$, $Cap^{Pdis}_{s}$), split by the
per-technology cost ratio $\alpha_{s}$; there is no energy-side
($Cap^{E}_{s}$) FOM term, mirroring
`src/sdom/models/formulations_storage.py::storage_fixed_om_cost_expr_rule`.
The factor $M_{kW}=10^{3}$ converts the FOM parameters (USD/kW-yr) to
USD/MW-yr to match the capacity units (MW).

CAPEX is intentionally excluded from $Z^{B}$ (capacities are fixed
planning outputs from the CEM, so CAPEX is sunk relative to (B));
$Z^{B}_{FOM}$ is included because annual fixed O&M is incurred whether or
not the asset operates and is part of the annual operating cost
comparison. Problem (B) does not include outages, so $\delta_{a,t} \equiv 1$ and
$\delta^{m}_{t} \equiv 1$ for every asset and must-run source; the outage
multipliers therefore do not appear in (B).

### 4.2 Problem (O): Per-hour outage dispatch starting at $h$

Minimize the operational cost over the outage horizon

$$
Z^{O}(h) = Z^{O}_{thermal}(h) + Z^{O}_{storage}(h) + Z^{O}_{imp}(h) + Z^{O}_{exp}(h) + Z^{O}_{slack}(h) + Z^{O}_{soc\_slack}(h) + Z^{O}_{curt}(h) + Z^{O}_{FOM}(h).
$$

with components

$$
Z^{O}_{thermal}(h) = \sum_{t \in \mathcal{T}^{out}_h} \sum_{b \in \mathcal{B}} c^{B}_{b} \, p^{B}_{b,t}.
$$

$$
Z^{O}_{storage}(h) = \sum_{t \in \mathcal{T}^{out}_h} \sum_{s \in \mathcal{S}} c^{vom}_{s} \, (p^{ch}_{s,t} + p^{dis}_{s,t}).
$$

$$
Z^{O}_{imp}(h) = \sum_{t \in \mathcal{T}^{out}_h} c^{imp}_{t} \, p^{imp}_{t}.
$$

$$
Z^{O}_{exp}(h) = - \sum_{t \in \mathcal{T}^{out}_h} c^{exp}_{t} \, p^{exp}_{t}.
$$

$$
Z^{O}_{slack}(h) = \sum_{t \in \mathcal{T}^{out}_h} \pi^{slack} \, u_{t}.
$$

$$
Z^{O}_{soc\_slack}(h) = \pi^{soc} \sum_{s \in \mathcal{S}} \sigma^{rec}_{s},
$$

where $\sigma^{rec}_{s} \ge 0$ is a non-negative slack variable on the
SOC recovery target (see section 5.5). The operational SOC floor in
section 5.3 remains a hard bound; only the end-of-recovery target is
softened.

$$
Z^{O}_{curt}(h) = \pi^{curt} \sum_{t \in \mathcal{T}^{out}_h} \left[ \sum_{w \in \mathcal{W}} (\delta_{w,t} \, A^{W}_{w,t} \, Cap^{W}_{w} - p^{W}_{w,t}) + \sum_{k \in \mathcal{K}} (\delta_{k,t} \, A^{K}_{k,t} \, Cap^{K}_{k} - p^{K}_{k,t}) \right].
$$

$$
Z^{O}_{FOM}(h) = \frac{H^{out}(h)}{H^{yr}} \cdot Z^{B}_{FOM}.
$$

The annual fixed-O&M aggregate $Z^{B}_{FOM}$ (section 4.1) is prorated by
the outage-horizon fraction $H^{out}(h) / H^{yr}$ with $H^{yr} = 8760$.
The same per-asset structure is reused (thermal, wind, solar, storage with
CostRatio split); imports and exports carry no FOM. Because every
capacity in (O) is a fixed parameter, $Z^{O}_{FOM}(h)$ is a **constant**
added to the objective; it does not influence the optimal dispatch, only
the reported $Z^{O}(h)$ level. End-of-year clipping is honored:
$H^{out}(h) = |\mathcal{T}^{out}_h|$ may be shorter than
$\Delta^{out} + \Delta^{rec}$ when $h$ is near the end of the year, in
which case the prorated FOM scales accordingly.

The default $\pi^{soc} = 10^{3}$ is intentionally below
$\pi^{slack} = 10^{4}$, so a feasible LP without unserved load is always
preferred to one that violates the recovery target. Users can raise
$\pi^{soc} \ge \pi^{slack}$ to invert that preference (the model will
then leave load unserved rather than violate the recovery target).

Demand charges and the monthly variables $D^{fix}_m, D^{var}_m$ are omitted
from (O) by default (peak charges are billing-period concepts, not relevant
within a sub-day to multi-day window).

---

## 5. Constraints

Common to (B) and (O) unless noted. In (B), $u_{t} \equiv 0$ (no slack).

### 5.1 Power balance

The power balance equation below applies to both problems. In Problem (B)
(baseline, no outages), $\delta_{a,t} = \delta^{nuc}_{t} = \delta^{otre}_{t}
= \delta^{hydro}_{t} \equiv 1$ for every asset $a$.

$$
\begin{aligned}
& \sum_{b} p^{B}_{b,t} + \sum_{w} p^{W}_{w,t} + \sum_{k} p^{K}_{k,t} + \sum_{s} p^{dis}_{s,t} \\
& \quad + \delta^{nuc}_{t} \, G^{nuc}_{t} + \delta^{otre}_{t} \, G^{otre}_{t} + \delta^{hydro}_{t} \, G^{hydro}_{t} + p^{imp}_{t} + u_{t} \\
& = D_{t} + \sum_{s} p^{ch}_{s,t} + p^{exp}_{t}, \quad \forall t.
\end{aligned}
$$

### 5.2 Capacity bounds with de-rating

The bounds below apply to both problems. In Problem (B), $\delta_{a,t}
\equiv 1$ for every asset $a$, so the multipliers reduce to $1$ and the
bounds collapse to nominal capacity / availability.

$$
0 \le p^{B}_{b,t} \le \delta_{b,t} \cdot Cap^{B}_{b}, \quad \forall b, t.
$$

$$
0 \le p^{W}_{w,t} \le \delta_{w,t} \cdot A^{W}_{w,t} \cdot Cap^{W}_{w}, \quad \forall w, t.
$$

$$
0 \le p^{K}_{k,t} \le \delta_{k,t} \cdot A^{K}_{k,t} \cdot Cap^{K}_{k}, \quad \forall k, t.
$$

$$
0 \le p^{imp}_{t} \le \delta_{imp,t} \cdot \overline{P}^{imp}_{t}, \quad \forall t.
$$

$$
0 \le p^{exp}_{t} \le \overline{P}^{exp}_{t}, \quad \forall t.
$$

### 5.3 Storage dynamics, charge / discharge bounds

$$
SOC_{s,t} = SOC^{prev}_{s,t} + \eta^{ch}_{s} \cdot p^{ch}_{s,t} - \frac{1}{\eta^{dis}_{s}} \cdot p^{dis}_{s,t},
\quad \forall s, \; t \in \mathcal{T}^{out}_h,
$$

where the prior-state term is

$$
SOC^{prev}_{s,t} =
\begin{cases}
SOC^{init}_{s} & \text{if } t = h \quad \text{(Problem (O); boundary parameter)} \\
SOC_{s,t-1}    & \text{if } t > h.
\end{cases}
$$

In Problem (B), $SOC_{s,0}$ is set by the cyclic baseline boundary
(see `formulations_storage.soc_balance_rule`); in Problem (O), the
boundary parameter $SOC^{init}_{s}$ is seeded from the baseline
trajectory (section 5.5). Writing the dynamics equation for every
$t \in \mathcal{T}^{out}_h$ — including the anchor hour $t = h$ — is
required so that $p^{ch}_{s,h}$ and $p^{dis}_{s,h}$ appear in a SOC
balance equation; otherwise the LP would leave the anchor-hour
charge / discharge variables unconstrained by any energy balance,
letting the solver charge or discharge "for free" at $t = h$ for any
non-outaged storage tech.

$$
0 \le p^{ch}_{s,t} \le \delta_{s,t} \cdot Cap^{Pch}_{s}, \quad \forall s, t.
$$

$$
0 \le p^{dis}_{s,t} \le \delta_{s,t} \cdot Cap^{Pdis}_{s}, \quad \forall s, t.
$$

$$
SOC^{min}_{s} \cdot Cap^{E}_{s} \le SOC_{s,t} \le Cap^{E}_{s}, \quad \forall s, t.
$$

In (B) and for any storage tech not selected for outage,
$\delta_{s,t} \equiv 1$ and the bounds reduce to nominal $Cap^{Pch}_{s},
Cap^{Pdis}_{s}$. In (O), storage may be outaged like any other
capacity-bounded asset (section 6.1); during its outage window
$\delta_{s,t} = \rho_{s} \in [0,1]$ (default $0$) zeros out both charge
and discharge. The SOC dynamics still apply, so SOC remains constant when
$p^{ch}_{s,t} = p^{dis}_{s,t} = 0$.

### 5.4 Demand-charge linking (Problem (B))

For each month $m \in \mathcal{M}$ and each tariff type $k \in \lbrace fix, var \rbrace$:

$$
D^{k}_{m} \ge \phi^{k}_{t} \cdot p^{imp}_{t}, \quad \forall t \in \mathcal{T}_m.
$$

$$
D^{k}_{m} \ge 0.
$$

Since the objective minimizes $\sum_m (D^{fix}_m + D^{var}_m)$ and
$D^{k}_{m}$ has no upper bound, at the optimum each $D^{k}_{m}$ equals
$\max_{t \in \mathcal{T}_m} \phi^{k}_{t} \cdot p^{imp}_{t}$, i.e., the monthly
peak of the tariff-weighted import. The fixed tariff $\phi^{fix}_{t}$ is
constant within a month, so $D^{fix}_{m} = \phi^{fix}_{m} \cdot \max_{t \in
\mathcal{T}_m} p^{imp}_{t}$ (classic peak-power demand charge). The variable
tariff $\phi^{var}_{t}$ varies hourly, so $D^{var}_{m}$ captures the
time-of-use peak.

### 5.5 Outage problem coupling (Problem (O), starting at $h$)

Initial state from the baseline trajectory. The boundary parameter
$SOC^{init}_{s}$ is set to the baseline SOC value at hour $h$ and is
used by the dynamics equation at $t = h$ (section 5.3) as the prior
state $SOC^{prev}_{s,h}$:

$$
SOC^{init}_{s} = SOC^{base}_{s,h}, \quad \forall s \in \mathcal{S}.
$$

$SOC^{init}_{s}$ is implemented as a mutable Pyomo `Param` rather than
as a fixed `SOC[s, h]` variable. Earlier versions used
`SOC[s, h].fix(value)` and skipped the dynamics equation at $t = h$;
under that formulation the charge and discharge variables
$p^{ch}_{s,h}, p^{dis}_{s,h}$ for non-outaged storage technologies did
not appear in any SOC balance equation, allowing the solver to
dispatch them without an energy-conservation constraint at the anchor
hour. The present formulation closes that gap.

Recovery target at the end of the recovery window (Problem (O) only). In
Problem (O), the target is **softened by a non-negative slack variable**
$\sigma^{rec}_{s} \ge 0$ priced at $\pi^{soc}$ in the objective (see section
4) so the LP remains feasible when storage cannot fully recharge by the
end of its recovery window. In Problem (B), $\sigma^{rec}_{s} \equiv 0$:

$$
SOC_{s, h + \Delta^{out} + \Delta^{rec}_{s}} + \sigma^{rec}_{s} \ge SOC^{rec}_{s} \cdot Cap^{E}_{s},
\quad \forall s \in \mathcal{S}.
$$

---

## 6. Outage Modeling Formalism

### 6.1 Capacity-bounded assets

For each asset $a$ in $\mathcal{B}^{out} \cup \mathcal{W}^{out} \cup \mathcal{K}^{out} \cup \mathcal{S}^{out} \cup \mathcal{I}^{out}$:

$$
\delta_{a,t} =
\begin{cases}
\rho_{a} & \text{if } t \in [h, \; h + \Delta^{out}_{a} - 1] \\
1 & \text{otherwise}
\end{cases}
$$

where $\rho_{a} \in [0,1]$ is the user-provided derating factor (default
$\rho_{a} = 0$ for a full outage). Assets not selected for outage have
$\delta_{a,t} \equiv 1$. The multiplier appears as a time-varying upper
bound (section 5.2).

### 6.2 Must-run time-series sources

For each must-run source $m \in \lbrace \text{nuc}, \text{otre}, \text{hydro} \rbrace$:

$$
\delta^{m}_{t} =
\begin{cases}
\rho_{m} & \text{if } t \in [h, \; h + \Delta^{out}_{m} - 1] \\
1 & \text{otherwise}
\end{cases}
$$

These sources are not capacity-bounded variables; their injection is fixed
by the input time series. The outage multiplier therefore scales the
**time-series parameter directly** in the power balance (section 5.1)
rather than acting as a variable upper bound. Sources not selected for
outage have $\delta^{m}_{t} \equiv 1$.

### 6.3 Recovery window semantics

The recovery window $[h + \Delta^{out},\; h + \Delta^{out} + \Delta^{rec} - 1]$
is included in the optimization horizon $\mathcal{T}^{out}_h$ but lies
*outside* every outage window, so $\delta_{a,t} = 1$ and $\delta^{m}_{t} = 1$
for all assets and sources there. During recovery the system operates with
full capacity and storage devices may charge from any source (thermal, VRE,
imports, surplus generation) subject only to their nominal power and energy
limits. The only additional constraint that distinguishes recovery from
normal operation is the SOC recovery target enforced at the end of each
storage device's recovery window (see section 5.5).

---

## 7. Resiliency Metrics

Let $u_{t}^{*}(h)$ denote the optimal slack of problem (O) anchored at hour
$h$. Let $\mathcal{H} \subseteq \mathcal{T}$ be the set of evaluated start
hours and $N_{H}$ its cardinality.

### 7.1 Per-scenario (anchored at $h$)

$$
EUE(h) = \sum_{t \in \mathcal{T}^{out}_h} u_{t}^{*}(h).
$$

$$
H_{USE}(h) = \# \lbrace t \in \mathcal{T}^{out}_h : u_{t}^{*}(h) > 0 \rbrace.
$$

### 7.2 Aggregate

$$
LOLP = \frac{1}{N_{H}} \sum_{h \in \mathcal{H}} \mathbf{1} \lbrace EUE(h) > 0 \rbrace.
$$

$$
LOLE = \frac{1}{N_{H}} \sum_{h \in \mathcal{H}} H_{USE}(h)
\quad \text{(expected hours with USE per scenario).}
$$

$$
\overline{EUE} = \frac{1}{N_{H}} \sum_{h \in \mathcal{H}} EUE(h).
$$

$$
EUE_{p} = \mathrm{Quantile}_{p} \left( \lbrace EUE(h) \rbrace_{h \in \mathcal{H}} \right),
\quad p \in \lbrace 0.5, 0.95, 0.99 \rbrace.
$$

$$
EUE_{\max} = \max_{h \in \mathcal{H}} EUE(h).
$$

### 7.3 Probability-weighted expected metrics

Each evaluated anchor hour $h \in \mathcal{H}$ is assigned an outage-start
probability $P(h)$ and the *expected* metrics are reported alongside the
unweighted statistics in section 7.2:

$$
EUE^{\text{exp}} = \sum_{h \in \mathcal{H}} P(h) \cdot EUE(h), \qquad
H_{USE}^{\text{exp}} = \sum_{h \in \mathcal{H}} P(h) \cdot H_{USE}(h).
$$

**Partial-evaluation convention (renormalize).** When only a subset
$\mathcal{H} \subsetneq \mathcal{T}$ of anchor hours is evaluated (e.g. an
explicit ``hours=`` list passed to ``evaluate_resiliency``), probabilities
are renormalized over the evaluated set so they sum to 1:

$$
P(h) = \frac{1}{\lvert \mathcal{H} \rvert}, \qquad
\sum_{h \in \mathcal{H}} P(h) = 1.
$$

Hours with ``solver_status == "error"`` are excluded from $\mathcal{H}$
before renormalize, mirroring the unweighted statistics in section 7.2.

With uniform $P(h) = 1 / N_{H}$ the identities
$EUE^{\text{exp}} \equiv \overline{EUE}$ and
$H_{USE}^{\text{exp}} \equiv LOLE$ hold by construction. The keys are
surfaced separately so future severity- or arrival-rate-weighted schemes
can replace the uniform weight without changing the persisted schema or
breaking the existing unweighted metric names.

The empirical distribution $\lbrace EUE(h) \rbrace_{h \in \mathcal{H}}$ is
exposed via {class}`~sdom.resiliency.ResiliencyResults` and underlies the
histogram / ECDF / exceedance plots described in {doc}`resiliency`.
