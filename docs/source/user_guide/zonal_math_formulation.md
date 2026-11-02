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

## Optional Local Capability Margin

When `Reserves = CapacityMarginFormulation`, apply the same global scalar
$m=$ `capacity_marging_fraction` independently to every area and modeled hour:

$$
\begin{aligned}
&\sum_{k\in\mathcal{K}_a}P^{bal}_{a,k}
+\sum_{j\in\mathcal{J}_a}q^{act}_{a,jh}\\
&\quad+\sum_{p\in\mathcal{P}_a}\sigma_{a,ph}\bar p^{pv}_{a,p}F^{pv}_{a,p}
+\sum_{w\in\mathcal{W}_a}\zeta_{a,wh}\bar p^{wind}_{a,w}F^{wind}_{a,w}\\
&\quad+G^{hyd}_{a,h}+\alpha^{nuc}\nu_{a,h}+\alpha^{oth}\omega_{a,h}
\ge(1+m)d_{a,h}.
\end{aligned}
$$

Here $a\in\mathcal{A}$ extends the
[base capability notation and assumptions](sdom_math_formulation.md#optional-hourly-capability-margin).
The area storage expression and bounds are

$$
q^{act}_{a,jh}:=D^{dis}_{a,jh}-D^{ch}_{a,jh}+r^{up}_{a,jh},\qquad
r^{up}_{a,jh}\ge0,\qquad q^{act}_{a,jh}\le P^{dis}_{a,j},
$$

$$
T^{adequacy}q^{act}_{a,jh}\le\sqrt{\eta_{a,j}}S_{a,j,h^{-}},
\qquad T^{adequacy}=1\ \mathrm{hour}.
$$

Each area's `reserves.storage_activated_net_output[h,j]` is a named Pyomo
Expression reused in capability and both storage limits, not a second output
variable or defining equality. Beginning SOC is cyclic; same-hour charging
cannot fund activation. Charge interruption and within-hour switching are
allowed without gating on baseline mode.

Capability is **local**: imports, signed interregional flow, and spare capacity
in other areas are excluded, even when transmission is uncongested.
The baseline supply balances and network constraints above remain unchanged.
A demand-only area still receives a capability constraint and is infeasible
for positive demand even at enabled zero margin, although it can import energy
when reserves are disabled. No per-area margin file is introduced. Missing or
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
