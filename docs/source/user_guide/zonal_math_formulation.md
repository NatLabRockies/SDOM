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
