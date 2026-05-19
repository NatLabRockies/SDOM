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
| $\mathcal{B}^{out}, \mathcal{W}^{out}, \mathcal{K}^{out}, \mathcal{I}^{out}, \mathcal{N}^{out}, \mathcal{O}^{out}, \mathcal{R}^{out}$ | Subsets selected for outage / de-rating in a given `OutageSpec`. |

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
| $\pi^{slack}$ | Penalty on unserved energy (USD/MWh). Default $10^{4}$. | User (`OutageSpec` / kwarg) |
| $\pi^{curt}$ | Penalty on curtailed VRE energy (USD/MWh). Default $0$ (free curtailment). | User (kwarg) |

### 2.4 Outage / operational

| Symbol | Description |
| --- | --- |
| $\Delta^{out}$ | Outage duration (hours), or per-asset $\Delta^{out}_{a}$. |
| $\Delta^{rec}$ | Recovery window (hours), single value or per-storage $\Delta^{rec}_{s}$. |
| $\delta_{a,t} \in [0,1]$ | Time-varying capacity multiplier from outage. Equals the user-defined derating value (default $0$) inside the outage window $[h, h + \Delta^{out}_a - 1]$, and equals $1$ everywhere else, including the entire recovery window $[h + \Delta^{out}, h + \Delta^{out} + \Delta^{rec} - 1]$. |
| $\delta^{nuc}_{t}, \delta^{otre}_{t}, \delta^{hydro}_{t} \in [0,1]$ | Same outage / de-rating mechanism applied to the **must-run time-series sources** (nuclear, other renewables, hydro). The user-supplied factor multiplies the input time series during the outage window; equals $1$ outside the outage window. |
| $SOC^{min}_{s}$ | Operational SOC floor (fraction of $Cap^{E}_{s}$). |
| $SOC^{rec}_{s}$ | Required SOC at end of recovery window (fraction of $Cap^{E}_{s}$). |
| $SOC^{base}_{s,h}$ | Baseline SOC trajectory used as initial state. |

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

---

## 4. Objective Functions

### 4.1 Problem (B): Baseline annual dispatch

Minimize the total operational cost

$$
Z^{B} = Z^{B}_{thermal} + Z^{B}_{storage} + Z^{B}_{imp} + Z^{B}_{exp} + Z^{B}_{dem} + Z^{B}_{curt}.
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

No CAPEX or fixed-O&M terms (capacities are fixed parameters). Problem (B)
does not include outages, so $\delta_{a,t} \equiv 1$ and
$\delta^{m}_{t} \equiv 1$ for every asset and must-run source; the outage
multipliers therefore do not appear in (B).

### 4.2 Problem (O): Per-hour outage dispatch starting at $h$

Minimize the operational cost over the outage horizon

$$
Z^{O}(h) = Z^{O}_{thermal}(h) + Z^{O}_{storage}(h) + Z^{O}_{imp}(h) + Z^{O}_{exp}(h) + Z^{O}_{slack}(h) + Z^{O}_{curt}(h).
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
Z^{O}_{curt}(h) = \pi^{curt} \sum_{t \in \mathcal{T}^{out}_h} \left[ \sum_{w \in \mathcal{W}} (\delta_{w,t} \, A^{W}_{w,t} \, Cap^{W}_{w} - p^{W}_{w,t}) + \sum_{k \in \mathcal{K}} (\delta_{k,t} \, A^{K}_{k,t} \, Cap^{K}_{k} - p^{K}_{k,t}) \right].
$$

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
SOC_{s,t} = SOC_{s,t-1} + \eta^{ch}_{s} \cdot p^{ch}_{s,t} - \frac{1}{\eta^{dis}_{s}} \cdot p^{dis}_{s,t},
\quad \forall s, \; t > t_{0}.
$$

$$
0 \le p^{ch}_{s,t} \le Cap^{Pch}_{s}, \quad \forall s, t.
$$

$$
0 \le p^{dis}_{s,t} \le Cap^{Pdis}_{s}, \quad \forall s, t.
$$

$$
SOC^{min}_{s} \cdot Cap^{E}_{s} \le SOC_{s,t} \le Cap^{E}_{s}, \quad \forall s, t.
$$

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

Initial state from the baseline trajectory:

$$
SOC_{s,h} = SOC^{base}_{s,h}, \quad \forall s \in \mathcal{S}.
$$

Recovery target at the end of the recovery window:

$$
SOC_{s, h + \Delta^{out} + \Delta^{rec}_{s}} \ge SOC^{rec}_{s} \cdot Cap^{E}_{s},
\quad \forall s \in \mathcal{S}.
$$

---

## 6. Outage Modeling Formalism

### 6.1 Capacity-bounded assets

For each asset $a$ in $\mathcal{B}^{out} \cup \mathcal{W}^{out} \cup \mathcal{K}^{out} \cup \mathcal{I}^{out}$:

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

The empirical distribution $\lbrace EUE(h) \rbrace_{h \in \mathcal{H}}$ is
exposed via {class}`~sdom.resiliency.ResiliencyResults` and underlies the
histogram / ECDF / exceedance plots described in {doc}`resiliency`.
