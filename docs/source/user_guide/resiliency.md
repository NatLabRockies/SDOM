# Resiliency Evaluation

The **resiliency module** (`sdom.resiliency`) evaluates how an *already-designed*
power system responds to user-defined outages and de-ratings. For every hour
of the year (or any user-supplied subset), it solves an independent
short-horizon economic-dispatch LP and records expected unserved energy and
related metrics.

This module is purely additive and does not modify any existing module under
`src/sdom/models/`. Capacities are read from prior SDOM design-run snapshots
and treated as fixed parameters.


---

## Two Optimization Problems

The module implements two coupled linear programs:

### Problem (B) - Baseline annual dispatch

A pure-LP, fixed-capacity, full-year (or shorter) economic-dispatch problem
that produces:

- Hourly trajectories for storage (`SOC`, `Pcha`, `Pdis`), thermal
  (`Pthermal`), VRE (`Psolar`, `Pwind`), imports (`Pimp`) and exports
  (`Pexp`).
- Monthly fixed and variable demand-charge variables
  $D^{fix}_m, D^{var}_m$ enforced as linear maxima of the tariff-weighted
  imports power inside each month.

Mathematically, problem (B) minimizes

$$
Z^{B} = Z^{B}_{thermal} + Z^{B}_{storage} + Z^{B}_{imp} + Z^{B}_{exp} + Z^{B}_{dem} + Z^{B}_{curt},
$$

subject to power balance, storage dynamics, capacity bounds and the monthly
demand-charge linking constraints

$$
D^{k}_{m} \ge \phi^{k}_{t} \cdot p^{imp}_{t}, \qquad \forall t \in \mathcal{T}_m, \; k \in \{fix, var\}.
$$

Tariffs are expressed in USD/MW, so $D^{k}_{m}$ has units of USD.

### Problem (O) - Per-hour outage dispatch

Anchored at hour $h$, problem (O) is a short-horizon LP defined on the
clipped horizon $\mathcal{T}^{out}_h = [h,\; h + \Delta^{out} + \Delta^{rec} - 1]$.
Three things change relative to (B):

1. Every capacity-bounded asset has a time-varying upper bound
   $\delta_{a,t} \cdot Cap_a$ that drops to the user-defined derating
   $\rho_a$ inside the outage window.
2. Must-run time-series sources (nuclear, hydro, other renewables) are
   scaled by $\delta^{m}_{t}$ directly in the power balance.
3. A non-negative slack $u_t$ (MWh) is added to the power balance and
   penalised at $\pi^{slack}$ (default $10^4$ USD/MWh):

   $$
   Z^{O}(h) = Z^{O}_{thermal} + Z^{O}_{storage} + Z^{O}_{imp} + Z^{O}_{exp} + \pi^{slack} \!\sum_{t} u_t + \pi^{soc} \!\sum_{s} \sigma^{rec}_s + Z^{O}_{curt} + Z^{O}_{FOM}(h).
   $$

Initial SOC is seeded from problem (B) via the boundary parameter
$SOC^{init}_{s} = SOC^{base}_{s,h}$, which feeds the storage dynamics
equation at the anchor hour as the prior state (see
{doc}`resiliency_math` §5.3, §5.5). A recovery target
$SOC_{s,\, h + \Delta^{out} + \Delta^{rec}_s} + \sigma^{rec}_s \ge SOC^{rec}_s \cdot Cap^E_s$
is enforced at the end of each storage device's recovery window as a **soft
constraint** with non-negative slack $\sigma^{rec}_s$ priced at $\pi^{soc}$
(default $10^{3}$, below $\pi^{slack}$).

A prorated fixed O&M constant
$Z^{O}_{FOM}(h) = (H^{out}(h)/8760) \cdot Z^{B}_{FOM}$ is added to the
objective so that the reported `objective_value` reflects annualized fixed
costs for the assets carried through the outage horizon (capacities are
fixed in (O), so this term does not affect the optimal dispatch).

Demand-charge variables are excluded from (O) because the outage horizon is
sub-monthly.

See {doc}`resiliency_math` for the complete formulation.

---

## Inputs

The resiliency module needs **two directories**:

### 1. Snapshot directory (`snapshot_dir`)

Output CSVs of a prior SDOM design run. Files containing `Phase1` in their
name are excluded automatically.

| File pattern | Used for |
|---|---|
| `*OutputSummary_*<year>*.csv` | Storage / thermal / aggregate VRE capacities (filtered by `scenario_id`). |
| `*OutputSelectedVRE_*<year>*.csv` | Per-plant VRE capacity = `Capacity (MW) x Selection`. |

`OutputGeneration_*.csv` and `OutputStorage_*.csv` are intentionally ignored;
storage SOC is recomputed by re-solving problem (B).

### 2. Previous-stage inputs directory (`inputs_dir`)

Plain time-series and parameter CSVs from the design run (no
`formulations.csv` is needed):

| File pattern | Description |
|---|---|
| `Load_hourly_<year>.csv` | Hourly demand (MW). |
| `CFSolar_<year>.csv`, `CFWind_<year>.csv` | Hourly capacity factors per plant. |
| `Nucl_hourly_<year>.csv` | Must-run nuclear injection (MW). |
| `lahy_hourly_<year>.csv` | Must-run hydro injection (MW). |
| `otre_hourly_<year>.csv` | Other-renewable must-run injection (MW). |
| `Import_Cap_<year>.csv`, `import_prices_<year>.csv` | Hourly grid-imports cap and price. |
| `Export_Cap_<year>.csv`, `export_prices_<year>.csv` | Hourly grid-exports cap and price. |
| `StorageData_<year>.csv` | Storage parameters (`Eff`, `VOM`, ...). |
| `Data_Balancing_units_<year>.csv` | Balancing-unit metadata (`HeatRate`, `FuelCost`, `VOM`). |
| `fixed_dem_charges.csv`, `var_dem_charges.csv` | Hourly $\phi^{fix}_t, \phi^{var}_t$ tariffs (USD/MW). $\phi^{fix}_t$ must be constant within each month. |

Sample fixtures used in the tests are available under
`Data/resiliency_eval/` in the repository.

---

## Outage Specification

`OutageSpec` is the user-facing dataclass that captures the outage scenario
and is broadcast to every anchor hour.

```python
from sdom.resiliency import OutageSpec

spec = OutageSpec(
    duration_hours=4,                   # outage length
    recovery_hours=8,                   # SOC-recovery window
    outaged_assets={
        "imports": "all",               # full grid-import outage
        "balancing_units": ["GasCC_1"], # specific thermal plant
        "wind": "all",                  # all wind plants
    },
    derating_factors={
        ("imports", "grid"): 0.0,       # full outage (default)
        ("balancing_units", "GasCC_1"): 0.5,  # 50 % de-rate
    },
    min_soc_recovery={"Li-ion": 0.5},   # 50 % SOC at end of recovery
)
```

Components recognized via `VALID_COMPONENTS`:
`imports`, `wind`, `solar`, `balancing_units`, `hydro`, `nuclear`,
`other_renewables`. Must-run components (`hydro`, `nuclear`,
`other_renewables`) only accept `"all"` selectors in this iteration.

The full constructor is documented in the {doc}`API reference <../api/resiliency>`.

---

## Quickstart

### 1. End-to-end with `evaluate_resiliency`

The simplest entry point chains loader -> baseline build -> baseline solve ->
per-hour evaluation:

```python
from sdom.resiliency import OutageSpec, evaluate_resiliency

spec = OutageSpec(
    duration_hours=4,
    recovery_hours=4,
    outaged_assets={"imports": "all"},
)

results = evaluate_resiliency(
    snapshot_dir="Data/resiliency_eval/3MW_critical_load_24hrs_outage_24hrs_recovery",
    inputs_dir="Data/resiliency_eval/inputs_previous_stage/Paper_PGnE/Paper",
    outage_spec=spec,
    year=2030,
    scenario_id=1,
    n_hours=8760,
    hours=[1, 100, 500, 4500],   # subset of anchor hours; None evaluates every hour
    n_workers=4,                 # ProcessPoolExecutor; None -> max(1, cpu_count - 1)
    solver="highs",
)

print(results.metrics(level="aggregate"))
```

### 2. Step-by-step (more control, advanced)

```python
from sdom.resiliency import (
    OutageSpec,
    build_baseline_dispatch,
    build_outage_dispatch,
    load_designed_system,
    run_baseline_dispatch,
    run_resiliency_evaluation,
)

ds = load_designed_system(
    "Data/resiliency_eval/3MW_critical_load_24hrs_outage_24hrs_recovery",
    inputs_dir="Data/resiliency_eval/inputs_previous_stage/Paper_PGnE/Paper",
    year=2030,
    scenario_id=1,
)

# (B) Baseline annual dispatch
base_model = build_baseline_dispatch(ds, n_hours=8760)
baseline = run_baseline_dispatch(base_model, solver="highs")

# (O) Per-hour outage evaluation
spec = OutageSpec(duration_hours=4, recovery_hours=4,
                  outaged_assets={"imports": "all"})
results = run_resiliency_evaluation(
    baseline,
    outage_spec=spec,
    hours=[1, 100, 500, 4500],
    n_workers=4,
)

# Optional: build a single per-hour model directly (debugging / inspection)
outage_model = build_outage_dispatch(
    baseline,
    start_hour=100,
    outage_spec=spec,
    designed_system=ds,
)
```

### 3. Optional profiling

Each Pyomo-model builder accepts an opt-in `profile=True` flag that wraps
the build (and solve, in the case of the baseline) with the
{class}`~sdom.utils_performance_meassure.ModelInitProfiler` already used by
the capacity-expansion model. A formatted summary table is logged through
the module logger when profiling is enabled.

```python
results = evaluate_resiliency(
    snapshot_dir, inputs_dir=inputs_dir,
    outage_spec=spec, hours=[1, 100, 500],
    n_workers=1,             # required so each worker doesn't print its own table
    profile_baseline=True,
    profile_outages=True,
)

# Programmatic access to the profile data:
results.metadata["profiler"]    # only set when profile_baseline=True
```

---

## Results

`run_resiliency_evaluation` (and therefore `evaluate_resiliency`) returns a
`ResiliencyResults` dataclass:

```python
results.per_hour          # pandas.DataFrame, one row per anchor hour
results.metadata          # {"n_workers_used", "outage_spec", "n_hours", "solver", "n_hours_evaluated"}
```

### Per-hour DataFrame

`results.per_hour` is indexed by the anchor hour and has the following columns:

| Column | Description |
|---|---|
| `EUE` | $\sum_{t \in \mathcal{T}^{out}_h} u_t$ (MWh). |
| `USE_hours` | # of hours with $u_t > 10^{-6}$. |
| `max_unserved_MW` | $\max_{t} u_t$. |
| `objective_value` | Solver objective $Z^O(h)$. |
| `solver_status` | Pyomo termination condition (or `"error"`). |
| `solve_time_s` | Wall-clock time for that hour. |
| `truncated` | `True` when end-of-year clipping shortened $\mathcal{T}^{out}_h$. |
| `error_message` | Formatted traceback when a worker raised. |

```python
results.per_hour.head()
results.to_dataframe()        # same data with `hour` promoted to a column
```

### Aggregate metrics

```python
agg = results.metrics(level="aggregate")
# {
#   "LOLP":              # P(EUE(h) > 0)
#   "LOLE":              # mean USE_hours per scenario
#   "mean_EUE":
#   "max_EUE":
#   "EUE_p50", "EUE_p95", "EUE_p99":
#   "EUE_expected":       # sum_h P(h) * EUE(h)        (issue #69)
#   "USE_hours_expected": # sum_h P(h) * USE_hours(h)  (issue #69)
#   "n_hours_evaluated":  # excludes errored worker rows
#   "n_errors":
# }
```

#### Probability-weighted expected metrics (renormalize)

``EUE_expected`` and ``USE_hours_expected`` apply an outage-start
probability ``P(h)`` per evaluated anchor hour and report the expected
value:

``EUE_expected = sum_h P(h) * EUE(h)``,
``USE_hours_expected = sum_h P(h) * USE_hours(h)``.

The default convention is **renormalize**: ``P(h) = 1 / len(hours)`` over
the evaluated (non-errored) anchor set so the weights sum to ``1`` even
when only a subset of the year was simulated. With uniform weights this
identically equals the existing ``mean_EUE`` / ``LOLE`` values; the keys
are carried separately so future severity-weighted schemes can replace
the uniform weight without changing the persisted ``summary.json``
schema or the existing unweighted metric names.

Convenience accessors mirror common reliability-engineering quantities:

```python
results.lolp()        # loss-of-load probability
results.lole()        # loss-of-load expectation (hours per scenario)
results.eue(p=0.95)   # EUE quantile
results.eue_total()   # sum of per-hour EUE (MWh)
```

### Persistence

Save to a directory (Parquet + JSON) and reload:

```python
out_dir = results.save("./results_resiliency/run1")
# ./results_resiliency/run1/per_hour.parquet
# ./results_resiliency/run1/summary.json

from sdom.resiliency import ResiliencyResults
loaded = ResiliencyResults.load(out_dir)
```

`save()` requires a Parquet engine; install `pyarrow` (recommended) or
`fastparquet` if it is not already available.

---

## Plotting

`plot_metric_distribution` renders the empirical distribution of any numeric
column of `results.per_hour`. Three styles are supported:

- `kind="hist"` - histogram of metric values.
- `kind="ecdf"` - empirical CDF, monotonically non-decreasing in $[0, 1]$.
- `kind="exceedance"` - exceedance curve $1 - \mathrm{ECDF}$.

```python
import matplotlib.pyplot as plt
from sdom.resiliency import plot_metric_distribution

fig, axes = plt.subplots(1, 3, figsize=(15, 4))
plot_metric_distribution(results, metric="EUE", kind="hist", ax=axes[0], bins=30)
plot_metric_distribution(results, metric="EUE", kind="ecdf", ax=axes[1])
plot_metric_distribution(results, metric="EUE", kind="exceedance", ax=axes[2])
plt.tight_layout()
plt.show()
```

Errored rows (`solver_status == "error"`) are dropped automatically before
plotting.

---

## Logging

Every resiliency module declares its own logger via `getLogger(__name__)`,
so the standard SDOM logging configuration applies:

```python
import logging
from sdom import configure_logging

configure_logging(level=logging.INFO)   # INFO -> high-level steps
# configure_logging(level=logging.DEBUG)  # DEBUG -> every block addition
```

INFO-level events: pipeline entry/exit, baseline LP build/solve termination,
runner start/finish, save target. DEBUG-level events: per-block
construction, scenario-id resolution, solver dispatch path (serial vs.
`ProcessPoolExecutor`), errored rows dropped before plotting.
