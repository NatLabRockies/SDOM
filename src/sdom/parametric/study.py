"""ParametricStudy orchestrator for SDOM sensitivity analysis."""

import itertools
import logging
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Dict, List, Optional

import pandas as pd

from ..io_manager import export_results
from ..results import OptimizationResults
from .sweeps import ScalarSweep, StorageFactorSweep, TsSweep
from .worker import _run_single_case

logger = logging.getLogger(__name__)


class ParametricStudy:
    """Run a multi-dimensional parametric sensitivity study in parallel.

    Accepts scalar, storage-factor, and time-series sweep definitions,
    constructs the full Cartesian product of all sweep dimensions, and
    dispatches each combination to a separate worker process via
    :class:`concurrent.futures.ProcessPoolExecutor`.

    Parameters
    ----------
    base_data : dict
        SDOM data dictionary returned by :func:`sdom.load_data`.  This
        object is **never** modified; each worker process receives its own
        deep copy before applying mutations.
    solver_config : dict
        Solver configuration dict from
        :func:`sdom.get_default_solver_config_dict`.
    n_hours : int, optional
        Number of simulation hours.  Defaults to ``8760``.
    output_dir : str or None, optional
        Directory where per-case sub-directories and the summary CSV will be
        written.  Pass ``None`` to skip all disk output.
    n_cores : int or None, optional
        Number of worker processes.  Capped internally at
        ``max(1, os.cpu_count() - 1)``.  Pass ``None`` to use the maximum
        safe count.

    Examples
    --------
    >>> study = ParametricStudy(base_data=data, solver_config=solver_cfg)
    >>> study.add_scalar_sweep("scalars", "GenMix_Target", [0.8, 0.9, 1.0])
    >>> study.add_ts_sweep("load_data", [0.95, 1.05])
    >>> results = study.run()  # 3 × 2 = 6 cases
    """

    def __init__(
        self,
        base_data: dict,
        solver_config: dict,
        n_hours: int = 8760,
        output_dir: Optional[str] = None,
        n_cores: Optional[int] = None,
    ) -> None:
        self._base_data = base_data
        self._solver_config = solver_config
        self._n_hours = n_hours
        self._output_dir = output_dir
        self._n_cores = self._resolve_n_cores(n_cores)

        self._scalar_sweeps: List[ScalarSweep] = []
        self._storage_factor_sweeps: List[StorageFactorSweep] = []
        self._ts_sweeps: List[TsSweep] = []

    # ------------------------------------------------------------------
    # Public sweep registration methods
    # ------------------------------------------------------------------

    def add_scalar_sweep(self, data_key: str, param_name: str, values: list) -> None:
        """Register a scalar parameter sweep.

        Each value in *values* replaces
        ``data[data_key].loc[param_name, "Value"]`` for one case dimension.

        Parameters
        ----------
        data_key : str
            Key in the SDOM data dict (e.g. ``"scalars"``).
        param_name : str
            Row label of the parameter (e.g. ``"GenMix_Target"``).
        values : list of float
            Discrete values to sweep over.
        """
        self._scalar_sweeps.append(ScalarSweep(data_key, param_name, list(values)))
        logger.debug(
            "Registered ScalarSweep: data['%s']['%s'] over %d values",
            data_key, param_name, len(values),
        )

    def add_storage_factor_sweep(self, param_name: str, factors: list) -> None:
        """Register a multiplicative storage-parameter sweep.

        Each factor scales the entire ``data["storage_data"].loc[param_name]``
        row (all storage technologies) uniformly.

        Parameters
        ----------
        param_name : str
            Row label in ``data["storage_data"]`` (e.g. ``"P_Capex"``).
        factors : list of float
            Multiplicative factors to apply.
        """
        self._storage_factor_sweeps.append(StorageFactorSweep(param_name, list(factors)))
        logger.debug(
            "Registered StorageFactorSweep: storage_data['%s'] over %d factors",
            param_name, len(factors),
        )

    def add_ts_sweep(self, ts_key: str, factors: list) -> None:
        """Register a time-series multiplicative sweep.

        Each factor scales the numeric column of ``data[ts_key]``.
        The column name is resolved automatically from
        :data:`sdom.parametric.mutations.TS_KEY_TO_COLUMN`.

        Parameters
        ----------
        ts_key : str
            Key in the SDOM data dict (e.g. ``"load_data"``).
        factors : list of float
            Multiplicative scaling factors.
        """
        self._ts_sweeps.append(TsSweep(ts_key, list(factors)))
        logger.debug(
            "Registered TsSweep: data['%s'] over %d factors",
            ts_key, len(factors),
        )

    # ------------------------------------------------------------------
    # Main execution
    # ------------------------------------------------------------------

    def run(self) -> List[OptimizationResults]:
        """Execute all parametric combinations in parallel.

        Constructs the Cartesian product of all registered sweeps, submits
        every case to a :class:`~concurrent.futures.ProcessPoolExecutor`,
        reports progress as jobs complete, exports per-case CSVs (if
        *output_dir* was specified), and writes a summary CSV.

        Returns
        -------
        list of OptimizationResults
            One entry per combination, in Cartesian-product order
            (matching the order cases were submitted).  Cases that failed
            have ``is_optimal == False`` and a descriptive
            ``termination_condition``.
        """
        case_dicts = self._build_case_dicts()
        n_total = len(case_dicts)

        if n_total == 0:
            logger.warning("ParametricStudy.run(): no sweeps registered — nothing to run.")
            return []

        logger.info(
            "ParametricStudy: starting %d cases on %d worker(s).",
            n_total, self._n_cores,
        )

        # Pre-create output root if needed
        if self._output_dir:
            os.makedirs(self._output_dir, exist_ok=True)

        # Map future → case_dict so we can report and export on completion
        ordered_results: List[Optional[OptimizationResults]] = [None] * n_total

        with ProcessPoolExecutor(max_workers=self._n_cores) as executor:
            future_to_case = {
                executor.submit(_run_single_case, cd): cd
                for cd in case_dicts
            }

            completed = 0
            for future in as_completed(future_to_case):
                cd = future_to_case[future]
                case_name: str = cd["case_name"]
                completed += 1

                try:
                    result: OptimizationResults = future.result()
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        "[%d/%d] Case '%s' raised an unhandled exception: %s",
                        completed, n_total, case_name, exc, exc_info=True,
                    )
                    result = OptimizationResults(
                        termination_condition="exception",
                        solver_status="error",
                        gen_mix_target=float("nan"),
                    )

                status = "OK" if result.is_optimal else "FAILED"
                logger.info(
                    "[%d/%d] %s — case '%s'", completed, n_total, status, case_name
                )

                # Export per-case CSVs immediately (main process, not worker)
                if self._output_dir and result.is_optimal:
                    case_output_dir = os.path.join(self._output_dir, case_name)
                    export_results(result, case=case_name, output_dir=case_output_dir)

                ordered_results[cd["case_index"]] = result

        # Write summary CSV
        if self._output_dir:
            self._write_summary_csv(case_dicts, ordered_results)

        return ordered_results  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_n_cores(self, requested: Optional[int]) -> int:
        """Return a safe worker count, capped at ``cpu_count - 1``."""
        max_safe = max(1, (os.cpu_count() or 1) - 1)
        if requested is None:
            return max_safe
        capped = max(1, min(requested, max_safe))
        if capped < requested:
            logger.warning(
                "ParametricStudy: requested %d cores but only %d are safe to use "
                "(cpu_count=%d). Using %d.",
                requested, capped, os.cpu_count(), capped,
            )
        return capped

    def _build_case_dicts(self) -> List[dict]:
        """Build one case dict per Cartesian-product combination.

        Returns
        -------
        list of dict
            Each dict is the payload passed to :func:`_run_single_case`.
        """
        # Each sweep dimension is a list of (label, mutation-spec) pairs
        dimensions: list = []

        for sweep in self._scalar_sweeps:
            dim = [
                (f"{sweep.param_name}={v}", ("scalar", sweep.data_key, sweep.param_name, v))
                for v in sweep.values
            ]
            dimensions.append(dim)

        for sweep in self._storage_factor_sweeps:
            dim = [
                (f"{sweep.param_name}x{f}", ("storage_factor", sweep.param_name, f))
                for f in sweep.factors
            ]
            dimensions.append(dim)

        for sweep in self._ts_sweeps:
            dim = [
                (f"{sweep.ts_key}x{f}", ("ts", sweep.ts_key, f))
                for f in sweep.factors
            ]
            dimensions.append(dim)

        if not dimensions:
            return []

        case_dicts = []
        for i, combination in enumerate(itertools.product(*dimensions)):
            # combination is a tuple of (label, mutation_spec) per dimension
            labels, mutations = zip(*combination)
            case_name = _make_safe_name("_".join(labels))

            scalar_mutations = []
            storage_factor_mutations = []
            ts_mutations = []

            for mut in mutations:
                if mut[0] == "scalar":
                    _, data_key, param_name, value = mut
                    scalar_mutations.append((data_key, param_name, value))
                elif mut[0] == "storage_factor":
                    _, param_name, factor = mut
                    storage_factor_mutations.append((param_name, factor))
                elif mut[0] == "ts":
                    _, ts_key, factor = mut
                    ts_mutations.append((ts_key, factor))

            case_dicts.append({
                "data": self._base_data,
                "solver_config": self._solver_config,
                "n_hours": self._n_hours,
                "case_name": case_name,
                "case_index": i,
                "scalar_mutations": scalar_mutations,
                "storage_factor_mutations": storage_factor_mutations,
                "ts_mutations": ts_mutations,
            })

        # Detect and disambiguate colliding safe names by appending the index.
        # Two distinct combinations can produce the same safe name because
        # _make_safe_name collapses several characters to '_'.
        name_counts: Dict[str, int] = {}
        for cd in case_dicts:
            name_counts[cd["case_name"]] = name_counts.get(cd["case_name"], 0) + 1
        for cd in case_dicts:
            if name_counts[cd["case_name"]] > 1:
                cd["case_name"] = f"{cd['case_name']}_{cd['case_index']}"

        logger.info(
            "ParametricStudy: %d case(s) generated from %d sweep dimension(s).",
            len(case_dicts), len(dimensions),
        )
        return case_dicts

    def _write_summary_csv(
        self,
        case_dicts: List[dict],
        results: List[Optional[OptimizationResults]],
    ) -> None:
        """Write ``parametric_summary.csv`` to *output_dir*.

        Parameters
        ----------
        case_dicts : list of dict
            Case descriptors (same order as *results*).
        results : list of OptimizationResults or None
            Collected results, one per case.
        """
        rows = []
        for cd, res in zip(case_dicts, results):
            row: dict = {"case_name": cd["case_name"]}

            # Add one column per swept parameter value
            for data_key, param_name, value in cd.get("scalar_mutations", []):
                row[f"{data_key}.{param_name}"] = value
            for param_name, factor in cd.get("storage_factor_mutations", []):
                row[f"storage_data.{param_name}_factor"] = factor
            for ts_key, factor in cd.get("ts_mutations", []):
                row[f"{ts_key}_factor"] = factor

            if res is not None:
                row["is_optimal"] = res.is_optimal
                row["total_cost"] = res.total_cost
                row["solver_status"] = res.solver_status
                row["termination_condition"] = res.termination_condition
            else:
                row["is_optimal"] = False
                row["total_cost"] = None
                row["solver_status"] = "unknown"
                row["termination_condition"] = "unknown"

            rows.append(row)

        summary_df = pd.DataFrame(rows)
        summary_path = os.path.join(self._output_dir, "parametric_summary.csv")
        summary_df.to_csv(summary_path, index=False)
        logger.info("ParametricStudy: summary CSV written to '%s'.", summary_path)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _make_safe_name(name: str) -> str:
    """Return a filesystem-safe version of *name*.

    Replaces characters that are problematic on Windows/Linux file systems
    (``/``, ``\\``, ``:``, ``*``, ``?``, ``"``, ``<``, ``>``, ``|``) with
    underscores and strips leading/trailing whitespace.
    """
    for ch in r'/\\:*?"<>| ':
        name = name.replace(ch, "_")
    return name.strip("_")
