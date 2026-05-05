"""Outage / de-rating scenario specification for the SDOM resiliency module.

This module defines :class:`OutageSpec`, a pure-Python dataclass (no Pyomo
dependency) that captures the user's outage/de-rating intent and exposes
helpers used by :func:`sdom.resiliency.build_outage_dispatch` to translate the
specification into concrete per-asset, per-hour multipliers and SOC recovery
targets.

Math reference: ``dev_guidelines/resiliency evaluation/math_model.md``,
sections 2.4 and 6.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional, Union


VALID_COMPONENTS: tuple[str, ...] = (
    "imports",
    "wind",
    "solar",
    "balancing_units",
    "hydro",
    "nuclear",
    "other_renewables",
)

MUST_RUN_COMPONENTS: tuple[str, ...] = ("hydro", "nuclear", "other_renewables")

_GRID_ASSET_ID = "grid"


__all__ = ["OutageSpec", "VALID_COMPONENTS", "MUST_RUN_COMPONENTS"]


def _component_universe(component: str, designed_system) -> list[str]:
    """Return the concrete asset-id universe for ``component``."""
    if component == "balancing_units":
        return [str(k) for k in designed_system.thermal_caps.keys()]
    if component == "wind":
        return [str(k) for k in designed_system.wind_caps.keys()]
    if component == "solar":
        return [str(k) for k in designed_system.solar_caps.keys()]
    if component == "imports":
        return [_GRID_ASSET_ID]
    if component in MUST_RUN_COMPONENTS:
        return ["all"]
    raise ValueError(f"Unknown component '{component}'.")


@dataclass
class OutageSpec:
    """Specification of an outage / de-rating scenario.

    Parameters
    ----------
    duration_hours : int
        Outage duration applied to all listed assets unless overridden by
        :attr:`per_asset_durations`.
    recovery_hours : int or dict
        Hours allowed after the outage for storage devices to recover the
        SOC target. A single ``int`` broadcasts to every storage technology;
        a ``dict`` ``{tech: hours}`` gives per-tech values.
    outaged_assets : dict
        Mapping ``{component: asset_selector}`` where ``component`` is one of
        :data:`VALID_COMPONENTS` and ``asset_selector`` is either the string
        ``"all"`` or an iterable of asset/plant IDs. The must-run components
        in :data:`MUST_RUN_COMPONENTS` only accept ``"all"`` in this
        iteration; iterables raise :class:`NotImplementedError` from
        :meth:`validate`.
    derating_factors : dict, optional
        Mapping ``{(component, asset_id): factor}`` with each factor in
        ``[0, 1]``. Missing assets default to ``0`` (full outage) when
        listed in ``outaged_assets``, or ``1`` (no outage) otherwise.
    min_soc_recovery : dict, optional
        Per-tech target SOC fraction at the end of the recovery window.
        ``None`` (default) -> baseline SOC at the end of the recovery
        window divided by ``Cap_E`` per tech.
    per_asset_durations : dict, optional
        Optional per-asset overrides ``{(component, asset_id): hours}``
        for :attr:`duration_hours`.

    Raises
    ------
    ValueError
        If a derating factor is outside ``[0, 1]``, a component name is not
        in :data:`VALID_COMPONENTS`, or a string asset selector is not
        ``"all"``.
    """

    duration_hours: int
    recovery_hours: Union[int, dict[str, int]]
    outaged_assets: dict[str, Union[str, Iterable]]
    derating_factors: dict[tuple[str, str], float] = field(default_factory=dict)
    min_soc_recovery: Optional[dict[str, float]] = None
    per_asset_durations: dict[tuple[str, str], int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if int(self.duration_hours) <= 0:
            raise ValueError("duration_hours must be a positive integer.")

        # Validate component names and selector form (does not need designed_system).
        for component, selector in self.outaged_assets.items():
            if component not in VALID_COMPONENTS:
                raise ValueError(
                    f"Unknown component '{component}' in outaged_assets. "
                    f"Valid components: {VALID_COMPONENTS}."
                )
            if isinstance(selector, str) and selector != "all":
                raise ValueError(
                    f"String selector for component '{component}' must be exactly 'all'; "
                    f"got '{selector}'."
                )

        # Validate derating factors are within [0, 1].
        for key, factor in self.derating_factors.items():
            if not (0.0 <= float(factor) <= 1.0):
                raise ValueError(
                    f"derating factor for {key} must lie in [0, 1]; got {factor}."
                )

        # Validate per-asset durations.
        for key, hours in self.per_asset_durations.items():
            if int(hours) <= 0:
                raise ValueError(
                    f"per_asset_durations[{key}] must be a positive integer; got {hours}."
                )

    # ------------------------------------------------------------------
    # Validation against a DesignedSystem
    # ------------------------------------------------------------------
    def validate(self, designed_system) -> None:
        """Validate the specification against ``designed_system``.

        Parameters
        ----------
        designed_system : DesignedSystem
            Source of truth for asset universes (storage techs, thermal
            plants, VRE plants).

        Raises
        ------
        ValueError
            If an asset id in ``outaged_assets`` does not match the
            designed system, or if ``recovery_hours`` is a dict missing
            techs present in the designed system.
        NotImplementedError
            If a must-run component is given a per-asset iterable.
        """
        # outaged_assets validation against designed_system
        for component, selector in self.outaged_assets.items():
            if isinstance(selector, str):
                continue  # string already validated to be "all" in __post_init__
            if component in MUST_RUN_COMPONENTS:
                raise NotImplementedError(
                    f"Per-asset outage selectors for must-run component "
                    f"'{component}' are not supported in this iteration; "
                    f"use 'all' instead."
                )
            universe = set(_component_universe(component, designed_system))
            for asset_id in selector:
                if str(asset_id) not in universe:
                    raise ValueError(
                        f"Asset id '{asset_id}' not found in component "
                        f"'{component}' universe {sorted(universe)}."
                    )

        # recovery_hours dict completeness
        if isinstance(self.recovery_hours, dict):
            self.resolve_recovery_hours(designed_system)

    # ------------------------------------------------------------------
    # Resolvers
    # ------------------------------------------------------------------
    def resolve_recovery_hours(self, designed_system) -> dict[str, int]:
        """Return ``{tech: recovery_hours}`` for every storage tech.

        Raises
        ------
        ValueError
            If :attr:`recovery_hours` is a dict that does not cover every
            storage tech in ``designed_system``.
        """
        techs = list(designed_system.storage_caps.keys())
        if isinstance(self.recovery_hours, dict):
            missing = [t for t in techs if t not in self.recovery_hours]
            if missing:
                raise ValueError(
                    f"recovery_hours dict is missing storage tech(s): {missing}."
                )
            return {t: int(self.recovery_hours[t]) for t in techs}
        return {t: int(self.recovery_hours) for t in techs}

    def resolve_duration(self, component: str, asset_id: str) -> int:
        """Return outage duration (hours) for a given (component, asset_id)."""
        key = (component, str(asset_id))
        if key in self.per_asset_durations:
            return int(self.per_asset_durations[key])
        return int(self.duration_hours)

    def resolve_derating(self, component: str, asset_id: str) -> float:
        """Return the derating multiplier ``rho`` for ``(component, asset_id)``.

        Returns ``1.0`` when the asset is not selected for outage. Returns
        the user-provided factor (or the default ``0.0``) when it is.
        """
        selector = self.outaged_assets.get(component)
        listed = False
        if selector is not None:
            if isinstance(selector, str) and selector == "all":
                listed = True
            elif not isinstance(selector, str):
                listed = str(asset_id) in {str(a) for a in selector}
        if not listed:
            return 1.0
        return float(self.derating_factors.get((component, str(asset_id)), 0.0))

    def resolve_outaged_asset_ids(self, component: str, designed_system) -> list[str]:
        """Return the concrete list of outaged asset ids for ``component``.

        For must-run components and ``imports`` the returned list is the
        canonical universe (``["all"]`` and ``["grid"]`` respectively).
        """
        selector = self.outaged_assets.get(component)
        if selector is None:
            return []
        if component in MUST_RUN_COMPONENTS:
            return ["all"]
        universe = _component_universe(component, designed_system)
        if isinstance(selector, str) and selector == "all":
            return list(universe)
        return [str(a) for a in selector]

    def resolve_min_soc_recovery(
        self,
        baseline_results,
        designed_system,
        *,
        recovery_end_hour: dict[str, int],
    ) -> dict[str, float]:
        """Return ``{tech: SOC_target_fraction}`` at the end of recovery.

        If :attr:`min_soc_recovery` is ``None``, fractions default to
        ``SOC_baseline[tech, recovery_end_hour[tech]] / Cap_E[tech]``.
        Per-tech entries in :attr:`min_soc_recovery` override the
        baseline default.

        Parameters
        ----------
        baseline_results : BaselineDispatchResults
            Provides ``soc_trajectory`` (DataFrame indexed by hour with
            one column per tech, MWh).
        designed_system : DesignedSystem
            Provides ``storage_caps[tech]["Cap_E"]``.
        recovery_end_hour : dict
            Mapping ``{tech: hour_of_year}`` of the recovery end-hour
            (already clipped to the baseline horizon).
        """
        techs = list(designed_system.storage_caps.keys())
        out: dict[str, float] = {}
        for tech in techs:
            if self.min_soc_recovery is not None and tech in self.min_soc_recovery:
                out[tech] = float(self.min_soc_recovery[tech])
                continue
            cap_e = float(designed_system.storage_caps[tech]["Cap_E"])
            if cap_e <= 0.0:
                out[tech] = 0.0
                continue
            soc = baseline_results.soc_trajectory
            hour = int(recovery_end_hour[tech])
            try:
                baseline_value = float(soc.loc[hour, tech])
            except KeyError as exc:
                raise ValueError(
                    f"Baseline SOC trajectory missing entry for tech '{tech}' "
                    f"at hour {hour}."
                ) from exc
            out[tech] = baseline_value / cap_e
        return out
