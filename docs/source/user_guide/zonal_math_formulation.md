# Zonal Math Formulation

This page documents the zonal SDOM formulation used when:

- `Network = AreaTransportationModelNetwork`

It extends the base formulation in [SDOM Formulation](sdom_math_formulation.md).

## Sets

- $\mathcal{A}$: areas (`model.A`)
- $\mathcal{L}$: interconnections (`model.L`)
- $\mathcal{H}$: hours (`model.h`)

For each area $a \in \mathcal{A}$:

- $\mathcal{L}_{in}(a)$: lines ending in $a$ (`model.L_in[a]`)
- $\mathcal{L}_{out}(a)$: lines starting in $a$ (`model.L_out[a]`)

## Parameters

- $\overline{F}^{FT}_{l,h}$: capacity in `from -> to` direction (`model.LineCap_FT[l,h]`)
- $\overline{F}^{TF}_{l,h}$: capacity in `to -> from` direction (`model.LineCap_TF[l,h]`)

## Variables

- $f_{l,h} \in \mathbb{R}$: signed line flow (`model.f[l,h]`)

Reporting expressions:

- $f^{FT}_{l,h} = f_{l,h}$ (`model.f_FT[l,h]`)
- $f^{TF}_{l,h} = -f_{l,h}$ (`model.f_TF[l,h]`)

In reports, SDOM clips directional values to non-negative values.

## Network Constraints

Directional capacity limits are modeled as two explicit constraint blocks:

$$
f_{l,h} \leq \overline{F}^{FT}_{l,h}
$$

$$
-f_{l,h} \leq \overline{F}^{TF}_{l,h}
$$

These correspond to `model.f_upper[l,h]` and `model.f_lower[l,h]`.

## Per-Area Supply Balance

For each area and hour, SDOM enforces:

$$
\text{Demand}_{a,h} + \text{Charge}_{a,h} - \text{Discharge}_{a,h} - \text{Gen}_{a,h}^{all} - \sum_{l \in \mathcal{L}_{in}(a)} f_{l,h} + \sum_{l \in \mathcal{L}_{out}(a)} f_{l,h} = 0
$$

Implemented as `model.area[a].SupplyBalance[h]`.

Sign convention:

- Positive $f_{l,h}$ means flow in `from -> to` direction.
- Net inflow to area $a$ is subtracted from the left-hand side in the implementation.

## Optional Thermal Minimum Dispatch

Let $\mathcal K_a$ be the balancing units owned by area $a$, with installed
capacity $P^{bal}_{a,k}$ (MW), dispatch $G^{bal}_{a,kh}$ (MW), and dimensionless
hourly minimum fraction $q^{bal}_{a,kh}$. Under
`Thermal = NoRampsMinDispatchFormulation`, each local host imposes:

$$
\forall a\in\mathcal A,\ k\in\mathcal K_a,\ h\in\mathcal H:\qquad
\underline p^{bal}_{a,k}\leq P^{bal}_{a,k}\leq\bar p^{bal}_{a,k},
\qquad 0\leq G^{bal}_{a,kh}\leq P^{bal}_{a,k},
\qquad G^{bal}_{a,kh}\geq q^{bal}_{a,kh}P^{bal}_{a,k}.
$$

The bounds $\underline p^{bal}_{a,k},\bar p^{bal}_{a,k}$ are existing input MW.
For feasible positive installed capacity,
$CF^{bal}_{a,k}:=\sum_hG^{bal}_{a,kh}/(|\mathcal H|P^{bal}_{a,k})
\geq\sum_hq^{bal}_{a,kh}/|\mathcal H|$.
The [same capacity-factor qualifications](sdom_math_formulation.md#hourly-minimum-dispatch)
apply per area, including any explanatory target $CF^{bal,req}_{a,k}$.
No new transfer variables or sinks are introduced: scheduled bounded transfers
can relieve a surplus, while congestion can make the obligations infeasible.
An area without thermal assets has an empty $\mathcal K_a$ and no floor rows.

## Optional Local Capacity Margin

When `Reserves = CapacityMarginFormulation`, apply the same global scalar
$m=$ `capacity_marging_fraction` independently to every area and modeled hour:

$$
\begin{aligned}
&\sum_{k\in\mathcal{K}_a}P^{bal}_{a,k}
+\sum_{j\in\mathcal{J}_a}C^{stor}_{a,jh}\\
&\quad+\sum_{p\in\mathcal{P}_a}\sigma_{a,ph}\bar p^{pv}_{a,p}F^{pv}_{a,p}
+\sum_{w\in\mathcal{W}_a}\zeta_{a,wh}\bar p^{wind}_{a,w}F^{wind}_{a,w}\\
&\quad+G^{hyd}_{a,h}+\alpha^{nuc}\nu_{a,h}+\alpha^{oth}\omega_{a,h}
+N^{net}_{a,h}
\ge(1+m)d_{a,h}.
\end{aligned}
$$

Here $a\in\mathcal{A}$ extends the
[base capability notation and assumptions](sdom_math_formulation.md#optional-hourly-capacity-margin).
Scheduled net imports use the same signed flows as the supply balance:

$$
N^{net}_{a,h}:=
\sum_{l\in\mathcal{L}_{in}(a)}f_{l,h}
-\sum_{l\in\mathcal{L}_{out}(a)}f_{l,h}.
$$

| Symbol | Meaning | Units |
|---|---|---|
| $N^{net}_{a,h}$ | Scheduled inter-area imports minus exports; shorthand, not a new variable | MW |
| $f_{l,h}$ | Existing signed scheduled flow on line $l$ | MW |
| $\mathcal{L}_{in}(a),\mathcal{L}_{out}(a)$ | Lines whose stored destination/origin is area $a$ | Set |

The area storage contribution and bounds are

$$
0\le C^{stor}_{a,jh}\le P^{dis}_{a,j},
$$

$$
T^{adequacy}C^{stor}_{a,jh}\le\sqrt{\eta_{a,j}}S_{a,j,h^{-}},
\qquad T^{adequacy}=1\ \mathrm{hour}.
$$

Each area's `reserves.storage_capacity_contribution[h,j]` is one nonnegative
variable used in the capability inequality and both storage bounds.
It is credited supply capacity, not an upward dispatch award. No baseline
charge/discharge terms, extra activated-output Expression, or defining equality
are needed. Beginning SOC is cyclic; same-hour charging cannot fund capacity.
Baseline mode binaries and all dispatch/SOC constraints remain unchanged.

Scheduled imports support demand and scheduled exports reduce available
capability. Signed flows handle both directions, including reverse flow.
Exports are deducted in the sending area, so exchanges cancel when summing
requirements across areas. The margin still applies to gross customer demand.
The baseline supply balances and directional network limits remain unchanged.

These are **scheduled exchanges, not shared reserves**: activation retains
the baseline flows, with no new flow variable or transfer headroom award.
Subtracting baseline supply balance leaves a local upward-headroom requirement
of $m d_{a,h}$; unused remote capability or line capacity cannot meet it.
A demand-only area can meet an enabled zero margin using scheduled imports,
but cannot meet a positive margin without local upward headroom.
An area without incident lines retains the local-only inequality.
External imports/exports remain unsupported in zonal mode.
No per-area margin file is introduced. Missing or
nonmatching reserve selections default locally to `notModel` and add no equations.

## System-Wide Clean Share Constraint

The carbon-free target remains system-wide (not per area). It is built as top-level `model.GenMix_Share`.

## Objective

Zonal objective is the sum of area costs plus a transmission placeholder:

$$
\min Z = \sum_{a \in \mathcal{A}} \left(Z^{fixed}_a + Z^{variable}_a\right) + Z^{trans}
$$

Current implementation uses:

$$
Z^{trans} = 0
$$

Transmission investment is intentionally deferred.
