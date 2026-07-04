"""Typed data models for SDOM infrasys integration."""

from __future__ import annotations

from .attributes import (
    GeographicInfo,
    GeoLocation,
    SDOMCapacityResult,
    SDOMCostResult,
    SDOMCurtailmentResult,
    SDOMDualResult,
    SDOMGenerationResult,
    SDOMOptimizationResult,
    SDOMResultAttribute,
    SDOMScenarioMetadata,
    SDOMStorageDispatchResult,
)
from .base import SDOMComponent, SDOMTechnologyType
from .static_injection import (
    SDOMGenerator,
    SDOMHydroGenerator,
    SDOMLoad,
    SDOMNuclearGenerator,
    SDOMOtherRenewableGenerator,
    SDOMSolarGenerator,
    SDOMStorage,
    SDOMThermalGenerator,
    SDOMWindGenerator,
)
from .topology import (
    SDOMArea,
    SDOMBus,
    SDOMExportInterface,
    SDOMFormulationConfig,
    SDOMImportInterface,
    SDOMScalarParameter,
    SDOMTransmissionInterface,
)

__all__ = [
    "GeoLocation",
    "GeographicInfo",
    "SDOMArea",
    "SDOMBus",
    "SDOMCapacityResult",
    "SDOMComponent",
    "SDOMCostResult",
    "SDOMCurtailmentResult",
    "SDOMDualResult",
    "SDOMExportInterface",
    "SDOMFormulationConfig",
    "SDOMGenerationResult",
    "SDOMGenerator",
    "SDOMHydroGenerator",
    "SDOMImportInterface",
    "SDOMLoad",
    "SDOMNuclearGenerator",
    "SDOMOptimizationResult",
    "SDOMOtherRenewableGenerator",
    "SDOMResultAttribute",
    "SDOMScalarParameter",
    "SDOMScenarioMetadata",
    "SDOMSolarGenerator",
    "SDOMStorage",
    "SDOMStorageDispatchResult",
    "SDOMTechnologyType",
    "SDOMThermalGenerator",
    "SDOMTransmissionInterface",
    "SDOMWindGenerator",
]
