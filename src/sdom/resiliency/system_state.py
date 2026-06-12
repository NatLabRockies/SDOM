"""Dataclasses describing the fixed-capacity designed system and baseline state.

These containers are populated by :mod:`sdom.resiliency.data_loader` and consumed
by the (future) baseline and outage dispatch builders.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


logger = logging.getLogger(__name__)


_RESULTS_VERSION = "1"
_DEFAULT_RESULTS_DIR = "results_resiliency"


def _summarize_outage_spec(outage_spec) -> dict | None:
    """Return a JSON-safe summary of an :class:`OutageSpec` or ``None``."""
    if outage_spec is None:
        return None
    summary: dict[str, Any] = {}
    duration = getattr(outage_spec, "duration_hours", None)
    if duration is not None:
        summary["duration_hours"] = int(duration)
    recovery = getattr(outage_spec, "recovery_hours", None)
    if isinstance(recovery, dict):
        summary["recovery_hours"] = {str(k): int(v) for k, v in recovery.items()}
    elif recovery is not None:
        summary["recovery_hours"] = int(recovery)
    outaged = getattr(outage_spec, "outaged_assets", None)
    if isinstance(outaged, dict):
        summary["outaged_assets_components"] = sorted(str(k) for k in outaged.keys())
    return summary or None


@dataclass
class DesignedSystem:
    """Fixed-capacity designed system loaded from SDOM output snapshots.

    Parameters
    ----------
    storage_caps : dict
        Mapping ``{tech: {"Cap_Pch", "Cap_Pdis", "Cap_E", "eta_ch",
        "eta_dis", "soc_min_frac", "vom", "fom", "cost_ratio"}}`` for each
        storage technology with non-zero capacity. Capacities are in MW / MWh.
        ``fom`` is the fixed-O&M rate (USD/kW-yr) and ``cost_ratio`` is the
        share of that rate billed against the charge-side power capacity
        (the remainder is billed against the discharge-side power capacity),
        matching the CEM accounting in
        :func:`sdom.models.formulations_storage.storage_fixed_om_cost_expr_rule`.
    thermal_caps : dict
        Mapping ``{tech: {"capacity_MW", "heat_rate", "fuel_cost",
        "vom", "var_cost", "fom"}}`` for each thermal technology with non-zero
        capacity. ``var_cost = heat_rate * fuel_cost + vom``. ``fom`` is the
        fixed-O&M rate (USD/kW-yr) aggregated across plants.
    solar_caps : dict
        Mapping ``{plant_id: capacity_MW}`` for selected solar plants.
    wind_caps : dict
        Mapping ``{plant_id: capacity_MW}`` for selected wind plants.
    solar_fom, wind_fom : dict
        Mapping ``{plant_id: fom_USD_per_kW_yr}`` for the selected solar /
        wind plants. Values come from the ``FOM_M`` column of the
        ``CapSolar_*.csv`` / ``CapWind_*.csv`` previous-stage inputs.
        Carried for auditing and downstream reporting; the baseline-dispatch
        objective itself sources FOM from the CEM block expressions so the
        two paths cannot diverge.
    load, nuclear, hydro, other_renewables : pandas.Series
        Hourly time-series (length 8760) indexed by hour-of-year (1..8760).
    cf_solar, cf_wind : pandas.DataFrame
        Hourly capacity factors with columns indexed by plant id.
    import_cap, import_price, export_cap, export_price : pandas.Series
        Hourly grid-exchange capacity and price series.
    phi_fix_t, phi_var_t : pandas.Series
        Hourly fixed and variable demand-charge tariffs (USD/MW or USD/MWh).
    month_of_hour : pandas.Series
        Mapping from hour-of-year (1..8760) to calendar month (1..12) used to
        bill demand charges per month.
    scenario_id : int
        Scenario / Run id resolved from the snapshot CSVs.
    year : int
        Calendar year of the snapshot.
    formulation_map : dict
        Mapping ``{component: formulation_name}`` resolved from defaults
        plus user-provided overrides.
    cem_data : dict, optional
        CEM-shaped data dict (as returned by
        :func:`sdom.io_manager.load_data`) used by the baseline dispatch
        builder to reuse the planning-model formulations in
        :mod:`sdom.models`. ``None`` when the previous-stage inputs were
        not reloaded for that purpose.
    """

    storage_caps: dict[str, dict[str, float]] = field(default_factory=dict)
    thermal_caps: dict[str, dict[str, float]] = field(default_factory=dict)
    solar_caps: dict[str, float] = field(default_factory=dict)
    wind_caps: dict[str, float] = field(default_factory=dict)
    solar_fom: dict[str, float] = field(default_factory=dict)
    wind_fom: dict[str, float] = field(default_factory=dict)

    load: pd.Series | None = None
    cf_solar: pd.DataFrame | None = None
    cf_wind: pd.DataFrame | None = None
    nuclear: pd.Series | None = None
    hydro: pd.Series | None = None
    other_renewables: pd.Series | None = None

    import_cap: pd.Series | None = None
    import_price: pd.Series | None = None
    export_cap: pd.Series | None = None
    export_price: pd.Series | None = None

    phi_fix_t: pd.Series | None = None
    phi_var_t: pd.Series | None = None
    month_of_hour: pd.Series | None = None

    scenario_id: int = 1
    year: int = 2030
    formulation_map: dict[str, str] = field(default_factory=dict)

    # CEM-shaped data dict (as produced by ``sdom.io_manager.load_data``) used
    # by the baseline dispatch builder to call the planning-model formulations
    # in ``sdom.models`` with their native parameter layout. Populated by
    # :func:`load_designed_system` when ``attach_cem_data=True`` (the default).
    cem_data: dict | None = None


@dataclass
class BaselineState:
    """Placeholder container for baseline-dispatch outputs (Phase 2).

    Parameters
    ----------
    soc_trajectory : pandas.DataFrame, optional
        Hourly state-of-charge per storage technology (hour x tech).
    solver_status : str, optional
        Solver termination status from the baseline run.
    objective_value : float, optional
        Baseline objective value (USD).
    metadata : dict, optional
        Free-form solver / run metadata.
    """

    soc_trajectory: pd.DataFrame | None = None
    solver_status: str | None = None
    objective_value: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BaselineDispatchResults:
    """Trajectories and metadata produced by :func:`run_baseline_dispatch`.

    Parameters
    ----------
    soc_trajectory : pandas.DataFrame
        Hourly state-of-charge per storage technology, indexed by hour and
        with one column per tech (MWh).
    pcha_trajectory, pdis_trajectory : pandas.DataFrame
        Hourly charge / discharge per storage tech (MW).
    pthermal_trajectory : pandas.DataFrame
        Hourly thermal dispatch per balancing-unit Plant_id (MW). Empty
        ``DataFrame`` when no thermal units survive the snapshot filter.
    psolar_trajectory, pwind_trajectory : pandas.DataFrame
        Hourly dispatched solar / wind power per plant id (MW).
    pimp, pexp : pandas.Series
        Hourly imports / exports (MW).
    nuclear, hydro, other_renewables, load : pandas.Series
        Hourly time-series parameters echoed from the input system (MW).
    month_of_hour : pandas.Series
        Hour -> month mapping used by the demand-charge billing.
    objective_value : float
        Operational objective value (USD).
    solver_status : str
        Solver termination condition (e.g. ``"optimal"``).
    metadata : dict, optional
        Free-form solver / run metadata.
    cost_breakdown : dict, optional
        Per-component USD totals reconciling to ``objective_value``. Keys:
        ``thermal_var_USD``, ``storage_var_USD``, ``imports_USD``,
        ``exports_USD`` (positive; objective contribution is
        ``-exports_USD``), ``demand_charges_USD``, ``curtailment_USD``,
        ``fom_USD``, ``total_USD``. Empty dict when the model carries no
        component metadata.
    """

    soc_trajectory: pd.DataFrame | None = None
    pcha_trajectory: pd.DataFrame | None = None
    pdis_trajectory: pd.DataFrame | None = None
    pthermal_trajectory: pd.DataFrame | None = None
    psolar_trajectory: pd.DataFrame | None = None
    pwind_trajectory: pd.DataFrame | None = None
    pimp: pd.Series | None = None
    pexp: pd.Series | None = None
    nuclear: pd.Series | None = None
    hydro: pd.Series | None = None
    other_renewables: pd.Series | None = None
    load: pd.Series | None = None
    month_of_hour: pd.Series | None = None
    objective_value: float | None = None
    solver_status: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    cost_breakdown: dict[str, float] = field(default_factory=dict)


@dataclass
class ResiliencyResults:
    """Per-hour outage outcomes (lightweight, Phase 5).

    Aggregate metrics (LOLP, LOLE, percentiles) and plotting are added in
    Phase 6.

    Parameters
    ----------
    per_hour : pandas.DataFrame
        Indexed by ``hour`` (anchor ``start_hour``). Columns include
        ``["EUE", "USE_hours", "max_unserved_MW", "objective_value",
        "solver_status", "solve_time_s", "truncated", "error_message"]``.
    metadata : dict
        Free-form run metadata. Conventionally includes
        ``{"n_workers_used", "outage_spec", "n_hours", "solver"}``.
    """

    per_hour: pd.DataFrame
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dataframe(self) -> pd.DataFrame:
        """Return ``per_hour`` with the index promoted to a ``hour`` column.

        Returns
        -------
        pandas.DataFrame
            A copy of :attr:`per_hour` with ``hour`` as a regular column,
            sorted by ``hour``.
        """
        df = self.per_hour.reset_index()
        if df.columns[0] != "hour":
            df = df.rename(columns={df.columns[0]: "hour"})
        return df.sort_values("hour").reset_index(drop=True)

    def eue_total(self) -> float:
        """Return the sum of per-hour expected unserved energy (MWh).

        Returns
        -------
        float
        """
        if "EUE" not in self.per_hour.columns:
            return 0.0
        return float(self.per_hour["EUE"].fillna(0.0).sum())

    # ------------------------------------------------------------------
    # Phase 6 - aggregate metrics
    # ------------------------------------------------------------------
    def _evaluated_frame(self) -> pd.DataFrame:
        """Return per-hour records with errored solves removed."""
        df = self.per_hour
        if "solver_status" in df.columns:
            df = df[df["solver_status"] != "error"]
        return df

    def _aggregate_metrics(self) -> dict:
        """Compute the aggregate-metrics dict (Phase 6 + #69).

        Notes
        -----
        Probability-weighted expected metrics use the renormalize convention
        (issue #69, Q1): each evaluated anchor hour carries weight
        ``P(h) = 1 / len(hours)`` over the evaluated (non-errored) anchor
        set. Consequently ``EUE_expected`` collapses to
        ``mean_EUE`` and ``USE_hours_expected`` collapses to ``LOLE`` when
        the per-hour probabilities are uniform; this is by design, not a
        bug. The keys are persisted so future severity-weighted schemes
        can replace the uniform weight without changing the schema.
        """
        df = self._evaluated_frame()
        n_eval = int(len(df))
        if "solver_status" in self.per_hour.columns:
            n_err = int((self.per_hour["solver_status"] == "error").sum())
        else:
            n_err = 0

        if n_eval == 0:
            return {
                "LOLP": float("nan"),
                "LOLE": float("nan"),
                "mean_EUE": float("nan"),
                "max_EUE": float("nan"),
                "EUE_p50": float("nan"),
                "EUE_p95": float("nan"),
                "EUE_p99": float("nan"),
                "EUE_expected": float("nan"),
                "USE_hours_expected": float("nan"),
                "n_hours_evaluated": 0,
                "n_errors": n_err,
            }

        eue = df["EUE"].astype(float).to_numpy() if "EUE" in df.columns else np.zeros(n_eval)
        if "USE_hours" in df.columns:
            use_hours = df["USE_hours"].astype(float).to_numpy()
        else:
            use_hours = np.zeros(n_eval)

        # Q1=renormalize: P(h) = 1 / len(hours) over the evaluated anchor set.
        prob = 1.0 / n_eval

        return {
            "LOLP": float(np.mean(eue > 0.0)),
            "LOLE": float(np.mean(use_hours)),
            "mean_EUE": float(np.mean(eue)),
            "max_EUE": float(np.max(eue)),
            "EUE_p50": float(np.percentile(eue, 50, method="linear")),
            "EUE_p95": float(np.percentile(eue, 95, method="linear")),
            "EUE_p99": float(np.percentile(eue, 99, method="linear")),
            "EUE_expected": float(np.sum(prob * eue)),
            "USE_hours_expected": float(np.sum(prob * use_hours)),
            "n_hours_evaluated": n_eval,
            "n_errors": n_err,
        }

    def metrics(self, *, level: str = "aggregate"):
        """Aggregate or per-hour resiliency metrics.

        Parameters
        ----------
        level : {"aggregate", "per_hour"}, optional
            ``"aggregate"`` (default) returns a ``dict`` of scalar metrics
            computed over the evaluated hours (errored hours excluded).
            ``"per_hour"`` returns a copy of :attr:`per_hour` with ``hour``
            promoted to a column.

        Returns
        -------
        dict or pandas.DataFrame

        Raises
        ------
        ValueError
            If ``level`` is not one of the supported values.

        Notes
        -----
        Aggregate metrics exclude rows with ``solver_status == "error"``;
        the count of excluded rows is reported as ``n_errors``.
        """
        if level == "aggregate":
            return self._aggregate_metrics()
        if level == "per_hour":
            return self.to_dataframe()
        raise ValueError(
            f"Invalid level={level!r}. Expected 'aggregate' or 'per_hour'."
        )

    def lolp(self) -> float:
        """Return the loss-of-load probability across evaluated hours.

        Returns
        -------
        float
        """
        return float(self._aggregate_metrics()["LOLP"])

    def lole(self) -> float:
        """Return the loss-of-load expectation (mean USE hours per scenario).

        Returns
        -------
        float
        """
        return float(self._aggregate_metrics()["LOLE"])

    def eue(self, *, p: float | None = None) -> float:
        """Return the mean EUE or an empirical percentile of EUE.

        Parameters
        ----------
        p : float, optional
            Quantile in ``(0, 1)``. Default ``None`` returns the mean EUE.

        Returns
        -------
        float

        Raises
        ------
        ValueError
            If ``p`` is provided and not in ``(0, 1)``.
        """
        df = self._evaluated_frame()
        if "EUE" not in df.columns or len(df) == 0:
            return float("nan")
        eue = df["EUE"].astype(float).to_numpy()
        if p is None:
            return float(np.mean(eue))
        if not (0.0 < float(p) < 1.0):
            raise ValueError(f"Quantile p={p!r} must lie in the open interval (0, 1).")
        return float(np.percentile(eue, float(p) * 100.0, method="linear"))

    # ------------------------------------------------------------------
    # Phase 6 - persistence
    # ------------------------------------------------------------------
    def save(self, path: str | Path | None = None) -> Path:
        """Persist per-hour records and aggregate metrics to disk.

        Parameters
        ----------
        path : str or pathlib.Path, optional
            Output directory. Default: ``./results_resiliency/`` relative to
            the current working directory. The directory is created if it
            does not exist.

        Returns
        -------
        pathlib.Path
            The directory the artifacts were written to.

        Raises
        ------
        ImportError
            If no Parquet engine (``pyarrow`` or ``fastparquet``) is
            available.

        Notes
        -----
        Writes two files to ``path``:

        * ``per_hour.parquet`` - the per-hour DataFrame.
        * ``summary.json`` - aggregate metrics + JSON-safe metadata.
        """
        out_dir = Path(path) if path is not None else Path.cwd() / _DEFAULT_RESULTS_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Saving ResiliencyResults to %s.", out_dir)

        parquet_path = out_dir / "per_hour.parquet"
        try:
            self.per_hour.to_parquet(parquet_path, engine="auto")
        except (ImportError, ValueError) as exc:
            raise ImportError(
                "Saving ResiliencyResults requires a Parquet engine. Install "
                "'pyarrow' (recommended) or 'fastparquet'."
            ) from exc

        summary_payload = self._build_summary_payload()
        (out_dir / "summary.json").write_text(
            json.dumps(summary_payload, indent=2, default=str), encoding="utf-8"
        )
        logger.debug(
            "ResiliencyResults persisted: per_hour.parquet (%d rows) + summary.json.",
            len(self.per_hour),
        )
        return out_dir

    def _build_summary_payload(self) -> dict:
        """Return the JSON-safe payload written to ``summary.json``."""
        meta_safe: dict[str, Any] = {}
        for key in ("n_workers_used", "n_hours", "solver"):
            if key in self.metadata:
                value = self.metadata[key]
                meta_safe[key] = value if _is_json_safe(value) else str(value)
        outage_summary = _summarize_outage_spec(self.metadata.get("outage_spec"))
        if outage_summary is not None:
            meta_safe["outage_spec_summary"] = outage_summary
        return {
            "version": _RESULTS_VERSION,
            "aggregate_metrics": self._aggregate_metrics(),
            "metadata": meta_safe,
        }

    @classmethod
    def load(cls, path: str | Path) -> "ResiliencyResults":
        """Load a previously-saved :class:`ResiliencyResults` from ``path``.

        Parameters
        ----------
        path : str or pathlib.Path
            Directory that previously received :meth:`save`.

        Returns
        -------
        ResiliencyResults

        Raises
        ------
        FileNotFoundError
            If ``per_hour.parquet`` or ``summary.json`` is missing.
        """
        in_dir = Path(path)
        parquet_path = in_dir / "per_hour.parquet"
        summary_path = in_dir / "summary.json"
        missing = [str(p) for p in (parquet_path, summary_path) if not p.exists()]
        if missing:
            raise FileNotFoundError(
                f"Expected ResiliencyResults artifacts at {in_dir} "
                f"(missing: {missing})."
            )

        try:
            per_hour = pd.read_parquet(parquet_path, engine="auto")
        except (ImportError, ValueError) as exc:
            raise ImportError(
                "Loading ResiliencyResults requires a Parquet engine. Install "
                "'pyarrow' (recommended) or 'fastparquet'."
            ) from exc

        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        metadata = dict(summary.get("metadata", {}))
        return cls(per_hour=per_hour, metadata=metadata)


def _is_json_safe(value) -> bool:
    """Return ``True`` if ``value`` can be JSON-serialised by ``json.dumps``."""
    try:
        json.dumps(value)
    except TypeError:
        return False
    return True
