"""Read scenario CSVs and orchestrate canonical input preparation."""

import csv
import logging
import os
from datetime import datetime

import pandas as pd

from ..common.utilities import (
    check_file_exists,
    compare_lists,
    get_complete_path,
)
from ..constants import (
    AREA_TRANSPORTATION_MODEL_NETWORK,
    AREA_TRANSPORTATION_MODEL_NETWORK_REQUIRED_INPUTS,
    COPPER_PLATE_NETWORK,
    IMPORTS_EXPORTS_CAPACITY_PRICE_NET_LOAD,
    INPUT_CSV_NAMES,
    NO_RAMPS_MIN_DISPATCH_FORMULATION,
    RUN_OF_RIVER_FORMULATION,
    VALID_HYDRO_FORMULATIONS_TO_BUDGET_MAP,
    VALID_IMPORTS_EXPORTS_FORMULATIONS_TO_DESCRIPTION_MAP,
    VALID_NETWORK_FORMULATIONS_TO_DESCRIPTION_MAP,
)
from .aggregation import _aggregate_to_single_area
from .areas import _augment_with_per_area_views
from .formulations import get_formulation, get_network_formulation
from .network import _load_interconnections, _load_line_capacities
from .validation import (
    check_formulation,
    validate_required_network_files,
    validate_thermal_min_dispatch,
    validate_thermal_profile_headers,
)


def load_thermal_min_dispatch(data: dict, input_data_dir) -> None:
    """Load the selected thermal profile without reading inactive stale files.

    Parameters
    ----------
    data : dict
        Loaded formulations and static thermal table, updated in place.
    input_data_dir : str or pathlib.Path
        Directory containing the conditional hourly CSV.

    Raises
    ------
    FileNotFoundError
        If the enabled profile is absent (logged by the file helper).
    ValueError
        If enabled headers, identity, hours, bounds, or fractions are invalid.
    """
    selected = get_formulation(data, "Thermal")
    filename = INPUT_CSV_NAMES["thermal_min_dispatch_fraction"]
    if selected != NO_RAMPS_MIN_DISPATCH_FORMULATION:
        if os.path.isfile(os.path.join(input_data_dir, filename)):
            logging.info("%s ignores %s.", selected, filename)
        return
    path = check_file_exists(input_data_dir, filename, "hourly thermal minimum-dispatch fractions")
    with open(path, newline="", encoding="utf-8-sig") as stream:
        headers = next(csv.reader(stream), [])
    validate_thermal_profile_headers(headers)
    data["thermal_min_dispatch_fraction"] = pd.read_csv(path)
    data["thermal_min_dispatch_fraction"] = validate_thermal_min_dispatch(data)


def load_data(input_data_dir: str = ".\\Data\\") -> dict:
    r"""Load scenario CSVs and construct the canonical SDOM input dictionary.

    Read base and formulation-dependent inputs, validate their contents, create
    per-area views, and prepare topology or copper-plate aggregation as needed.

    Parameters
    ----------
    input_data_dir : str or pathlib.Path, optional
        Scenario directory containing the required files from
        ``sdom.constants.INPUT_CSV_NAMES``. Defaults to ``'.\\Data\\'``.

    Returns
    -------
    dict
        Base tables include ``formulations``, ``scalars``, ``load_data``,
        ``nuclear_data``, ``large_hydro_data``, ``other_renewables_data``,
        ``thermal_data``, ``storage_data``, ``cf_solar``, ``cf_wind``,
        ``cap_solar``, and ``cap_wind``. Plant lists are ``solar_plants`` and
        ``wind_plants``; storage lists are ``STORAGE_SET_J_TECHS`` and
        ``STORAGE_SET_B_TECHS``.

        Conditional tables are ``large_hydro_max``, ``large_hydro_min``,
        ``cap_imports``, ``price_imports``, ``cap_exports``, ``price_exports``,
        and ``thermal_min_dispatch_fraction``. Area descriptors, ``per_area_*``
        views, ``lines``, ``line_cap_ft``, and ``line_cap_tf`` are also included;
        topology and capacity tables are empty for legacy single-area inputs.

    Raises
    ------
    FileNotFoundError
        If a required input file is missing.
    ValueError
        If a supplied formulation, area encoding, thermal profile, or network
        input violates its validation rules.
    IndexError
        If a required formulation row has no registered or explicit default.

    Notes
    -----
    Most numeric input tables are rounded to five decimal places. Scalars
    retain their input precision. Under ``NoRampsMinDispatchFormulation``,
    thermal capacity bounds and hourly fractions retain full precision and
    plant identifiers are read as exact strings.

    Missing Network selections default to ``CopperPlateNetwork``. Multi-area
    inputs selected for copper-plate modeling are aggregated before topology
    loading, with transmission files ignored and logged. Legacy single-area
    inputs also receive per-area views.

    See Also
    --------
    sdom.io.validation.validate_thermal_min_dispatch : Validate thermal profiles.
    sdom.io.formulations.get_formulation : Resolve a component selection.
    """
    logging.info(
        "[%s] Starting data load step.",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    logging.info("Loading SDOM input data...")

    logging.debug("- Trying to load formulations data...")
    input_file_path = check_file_exists(
        input_data_dir,
        INPUT_CSV_NAMES["formulations"],
        "CSV file to specify the formulations for different components",
    )
    if input_file_path != "":
        formulations = pd.read_csv(input_file_path)

    logging.debug("- Trying to load VRE data...")
    input_file_path = check_file_exists(
        input_data_dir, INPUT_CSV_NAMES["cf_solar"], "Capacity factors for pv solar"
    )
    if input_file_path != "":
        cf_solar = pd.read_csv(input_file_path).round(5)
        cf_solar.columns = cf_solar.columns.astype(str)
        solar_plants = cf_solar.columns[1:].tolist()
        logging.debug(f"-- It were loaded a total of {len(solar_plants)} solar plants profiles.")

    input_file_path = check_file_exists(
        input_data_dir, INPUT_CSV_NAMES["cf_wind"], "Capacity factors for wind"
    )
    if input_file_path != "":
        cf_wind = pd.read_csv(input_file_path).round(5)
        cf_wind.columns = cf_wind.columns.astype(str)
        wind_plants = cf_wind.columns[1:].tolist()
        logging.debug(f"-- It were loaded a total of {len(wind_plants)} wind plants profiles.")

    input_file_path = check_file_exists(
        input_data_dir, INPUT_CSV_NAMES["cap_solar"], "Capex information for solar"
    )
    if input_file_path != "":
        cap_solar = pd.read_csv(input_file_path).round(5)
        cap_solar["sc_gid"] = cap_solar["sc_gid"].astype(str)
        solar_plants_capex = cap_solar["sc_gid"].tolist()
        compare_lists(solar_plants, solar_plants_capex, text_comp="solar plants", list_names=["CF", "Capex"])

    input_file_path = check_file_exists(
        input_data_dir, INPUT_CSV_NAMES["cap_wind"], "Capex information for wind"
    )
    if input_file_path != "":
        cap_wind = pd.read_csv(input_file_path).round(5)
        cap_wind["sc_gid"] = cap_wind["sc_gid"].astype(str)
        wind_plants_capex = cap_wind["sc_gid"].tolist()
        compare_lists(wind_plants, wind_plants_capex, text_comp="wind plants", list_names=["CF", "Capex"])

    logging.debug("- Trying to load demand data...")
    input_file_path = check_file_exists(input_data_dir, INPUT_CSV_NAMES["load_data"], "load data")
    if input_file_path != "":
        load_data = pd.read_csv(input_file_path).round(5)

    logging.debug("- Trying to load nuclear data...")
    input_file_path = check_file_exists(input_data_dir, INPUT_CSV_NAMES["nuclear_data"], "nuclear data")
    if input_file_path != "":
        nuclear_data = pd.read_csv(input_file_path).round(5)

    logging.debug("- Trying to load large hydro data...")
    input_file_path = check_file_exists(
        input_data_dir, INPUT_CSV_NAMES["large_hydro_data"], "large hydro data"
    )
    if input_file_path != "":
        large_hydro_data = pd.read_csv(input_file_path).round(5)

    logging.debug("- Trying to load other renewables data...")
    input_file_path = check_file_exists(
        input_data_dir, INPUT_CSV_NAMES["other_renewables_data"], "other renewables data"
    )
    if input_file_path != "":
        other_renewables_data = pd.read_csv(input_file_path).round(5)

    logging.debug("- Trying to load storage data...")
    input_file_path = check_file_exists(input_data_dir, INPUT_CSV_NAMES["storage_data"], "Storage data")
    if input_file_path != "":
        storage_data = pd.read_csv(input_file_path, index_col=0).round(5)
        storage_set_j_techs = storage_data.columns[0:].astype(str).tolist()
        storage_set_b_techs = storage_data.columns[storage_data.loc["Coupled"] == 1].astype(str).tolist()

    logging.debug("- Trying to load thermal generation data...")
    input_file_path = check_file_exists(input_data_dir, INPUT_CSV_NAMES["thermal_data"], "thermal data")
    if input_file_path != "":
        thermal_mode = get_formulation({"formulations": formulations}, "Thermal")
        thermal_data = pd.read_csv(
            input_file_path,
            dtype={"Plant_id": str} if thermal_mode == NO_RAMPS_MIN_DISPATCH_FORMULATION else None,
        )
        rounded_columns = (
            thermal_data.columns.difference(["MinCapacity", "MaxCapacity"])
            if thermal_mode == NO_RAMPS_MIN_DISPATCH_FORMULATION
            else thermal_data.columns
        )
        thermal_data[rounded_columns] = thermal_data[rounded_columns].round(5)

    logging.debug("- Trying to load scalars data...")
    input_file_path = check_file_exists(input_data_dir, INPUT_CSV_NAMES["scalars"], "scalars")
    if input_file_path != "":
        scalars = pd.read_csv(input_file_path, index_col="Parameter")

    data_dict = {
        "formulations": formulations,
        "solar_plants": solar_plants,
        "wind_plants": wind_plants,
        "load_data": load_data,
        "nuclear_data": nuclear_data,
        "large_hydro_data": large_hydro_data,
        "other_renewables_data": other_renewables_data,
        "cf_solar": cf_solar,
        "cf_wind": cf_wind,
        "cap_solar": cap_solar,
        "cap_wind": cap_wind,
        "storage_data": storage_data,
        "STORAGE_SET_J_TECHS": storage_set_j_techs,
        "STORAGE_SET_B_TECHS": storage_set_b_techs,
        "thermal_data": thermal_data,
        "scalars": scalars,
    }

    load_thermal_min_dispatch(data_dict, input_data_dir)

    # --- Network (zonal) formulation: backward-compatible default ---
    network_formulation = get_network_formulation(data_dict)
    check_formulation(network_formulation, VALID_NETWORK_FORMULATIONS_TO_DESCRIPTION_MAP.keys())

    hydro_formulation = get_formulation(data_dict, component="hydro")
    check_formulation(hydro_formulation, VALID_HYDRO_FORMULATIONS_TO_BUDGET_MAP.keys())

    if hydro_formulation != RUN_OF_RIVER_FORMULATION:
        logging.debug(
            "- Hydro was set to MonthlyBudgetFormulation. Trying to load large hydro max/min data..."
        )

        input_file_path = check_file_exists(
            input_data_dir, INPUT_CSV_NAMES["large_hydro_max"], "large hydro Maximum  capacity data"
        )
        if input_file_path != "":
            large_hydro_max = pd.read_csv(input_file_path).round(5)

        input_file_path = check_file_exists(
            input_data_dir, INPUT_CSV_NAMES["large_hydro_min"], "large hydro Minimum capacity data"
        )
        if input_file_path != "":
            large_hydro_min = pd.read_csv(input_file_path).round(5)
        data_dict["large_hydro_max"] = large_hydro_max
        data_dict["large_hydro_min"] = large_hydro_min

    logging.debug("- Trying to load imports data...")
    imports_formulation = get_formulation(data_dict, component="imports")
    check_formulation(imports_formulation, VALID_IMPORTS_EXPORTS_FORMULATIONS_TO_DESCRIPTION_MAP.keys())
    if imports_formulation == IMPORTS_EXPORTS_CAPACITY_PRICE_NET_LOAD:
        logging.debug(
            "- Imports was set to CapacityPriceNetLoadFormulation. Trying to load capacity and price..."
        )

        input_file_path = check_file_exists(
            input_data_dir, INPUT_CSV_NAMES["cap_imports"], "Imports hourly upper bound capacity data"
        )
        if input_file_path != "":
            cap_imports = pd.read_csv(input_file_path).round(5)

        input_file_path = check_file_exists(
            input_data_dir, INPUT_CSV_NAMES["price_imports"], "Imports hourly price data"
        )
        if input_file_path != "":
            price_imports = pd.read_csv(input_file_path).round(5)
        data_dict["cap_imports"] = cap_imports
        data_dict["price_imports"] = price_imports

    logging.debug("- Trying to load exports data...")
    exports_formulation = get_formulation(data_dict, component="exports")
    check_formulation(exports_formulation, VALID_IMPORTS_EXPORTS_FORMULATIONS_TO_DESCRIPTION_MAP.keys())
    if exports_formulation == IMPORTS_EXPORTS_CAPACITY_PRICE_NET_LOAD:
        logging.debug(
            "- Exports was set to CapacityPriceNetLoadFormulation. Trying to load capacity and price..."
        )

        input_file_path = check_file_exists(
            input_data_dir, INPUT_CSV_NAMES["cap_exports"], "Exports hourly upper bound capacity data"
        )
        if input_file_path != "":
            cap_exports = pd.read_csv(input_file_path).round(5)

        input_file_path = check_file_exists(
            input_data_dir, INPUT_CSV_NAMES["price_exports"], "Exports hourly price data"
        )
        if input_file_path != "":
            price_exports = pd.read_csv(input_file_path).round(5)
        data_dict["cap_exports"] = cap_exports
        data_dict["price_exports"] = price_exports

    _augment_with_per_area_views(data_dict, input_data_dir=input_data_dir)

    # ------------------------------------------------------------------
    # Aggregation fallback (commit #6): zonal data + CopperPlateNetwork.
    # When the user ships a multi-area input folder but selects (or
    # defaults to) ``CopperPlateNetwork``, collapse every per-area entity
    # into a single synthetic ``default`` area following PRD §4.6.
    # Transmission CSVs are dropped with a WARNING (no transmission in
    # copper-plate).
    # ------------------------------------------------------------------
    aggregated = False
    if get_network_formulation(data_dict) == COPPER_PLATE_NETWORK and len(data_dict.get("areas", [])) > 1:
        _aggregate_to_single_area(data_dict)
        aggregated = True
        if any(
            get_complete_path(input_data_dir, name)
            for name in AREA_TRANSPORTATION_MODEL_NETWORK_REQUIRED_INPUTS
        ):
            logging.warning(
                "Aggregation fallback: dropping interregional transmission "
                "files (%s) because Network=%s has no transmission.",
                ", ".join(AREA_TRANSPORTATION_MODEL_NETWORK_REQUIRED_INPUTS),
                COPPER_PLATE_NETWORK,
            )

    # ------------------------------------------------------------------
    # Zonal topology + line capacities (commit #5).
    # Skipped entirely when the aggregation fallback above collapsed the
    # input to a single synthetic area. Otherwise parsed when present so
    # legacy folders pick up empty defaults without raising; the
    # AreaTransportationModelNetwork formulation *requires* all three CSVs.
    # ------------------------------------------------------------------
    if aggregated:
        lines = []
        line_cap_ft, line_cap_tf = pd.DataFrame(), pd.DataFrame()
    else:
        lines = _load_interconnections(input_data_dir, areas=data_dict["areas"])
        line_cap_ft, line_cap_tf = _load_line_capacities(input_data_dir, lines=lines)

        if get_network_formulation(data_dict) == AREA_TRANSPORTATION_MODEL_NETWORK:
            missing_files = [
                name
                for name in AREA_TRANSPORTATION_MODEL_NETWORK_REQUIRED_INPUTS
                if not get_complete_path(input_data_dir, name)
            ]
            validate_required_network_files(missing_files, formulation=AREA_TRANSPORTATION_MODEL_NETWORK)

    data_dict["lines"] = lines
    data_dict["line_cap_ft"] = line_cap_ft
    data_dict["line_cap_tf"] = line_cap_tf

    return data_dict
