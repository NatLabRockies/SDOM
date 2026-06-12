"""Generate PDF documentation describing the SDOM standard CSV inputs.

Produces one PDF per mode (copperplate, zonal) under
``Data/Standard_info_request/<mode>/``. Each PDF lists every CSV input file
shipped in that folder and documents each column based on the user guide
(``docs/source/user_guide/inputs.md`` and ``zonal_inputs.md``).
"""

from __future__ import annotations

from pathlib import Path

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
except ImportError as exc:  # pragma: no cover - import-time guard
    raise SystemExit(
        "This script requires the optional 'reportlab' dependency. "
        "Install it with:  pip install reportlab"
    ) from exc


# ---------------------------------------------------------------------------
# Shared column descriptions sourced from docs/source/user_guide/inputs.md
# and docs/source/user_guide/zonal_inputs.md.
# ---------------------------------------------------------------------------

# Each entry: file_name -> (purpose, [(column, type, description), ...])

COPPERPLATE_FILES: list[tuple[str, str, list[tuple[str, str, str]]]] = [
    (
        "formulations.csv",
        "Selects the modeling approach for each major system component.",
        [
            ("Component", "string", "Component name (Thermal, Hydro, Imports, Exports, Network)."),
            ("Formulation", "string", "Formulation assigned to that component (see user guide)."),
            ("Description", "string", "Optional free-text description."),
        ],
    ),
    (
        "Load_hourly.csv",
        "System hourly electricity demand time-series.",
        [
            ("*Hour", "int", "Hour index of the year (1..8760)."),
            ("Load", "float", "System electricity demand at each hour (MWh)."),
        ],
    ),
    (
        "CFSolar.csv",
        "Hourly solar capacity factors per candidate site.",
        [
            ("Hour", "int", "Hour index of the year (1..8760)."),
            ("<plant_id>", "float", "Capacity factor [0, 1] for each candidate solar site."),
        ],
    ),
    (
        "CapSolar.csv",
        "Candidate solar PV sites with capacity bounds and costs.",
        [
            ("sc_gid", "string", "Unique identifier for the candidate site."),
            ("capacity", "float", "Upper bound for installed capacity at the site (MW)."),
            ("latitude", "float", "Latitude of the site (optional)."),
            ("longitude", "float", "Longitude of the site (optional)."),
            ("trans_cap_cost", "float", "Transmission interconnection capex (USD/kW)."),
            ("CAPEX_M", "float", "Capital expenditure (USD/kW)."),
            ("FOM_M", "float", "Fixed O&M cost (USD/kW-yr)."),
        ],
    ),
    (
        "CFWind.csv",
        "Hourly wind capacity factors per candidate site.",
        [
            ("Hour", "int", "Hour index of the year (1..8760)."),
            ("<plant_id>", "float", "Capacity factor [0, 1] for each candidate wind site."),
        ],
    ),
    (
        "CapWind.csv",
        "Candidate wind sites with capacity bounds and costs (same schema as CapSolar.csv).",
        [
            ("sc_gid", "string", "Unique identifier for the candidate site."),
            ("capacity", "float", "Upper bound for installed capacity at the site (MW)."),
            ("latitude", "float", "Latitude of the site (optional)."),
            ("longitude", "float", "Longitude of the site (optional)."),
            ("trans_cap_cost", "float", "Transmission interconnection capex (USD/kW)."),
            ("CAPEX_M", "float", "Capital expenditure (USD/kW)."),
            ("FOM_M", "float", "Fixed O&M cost (USD/kW-yr)."),
        ],
    ),
    (
        "Nucl_hourly.csv",
        "Fixed nuclear generation profile.",
        [
            ("*Hour", "int", "Hour index of the year (1..8760)."),
            ("Nuclear", "float", "Nuclear generation at each hour (MWh)."),
        ],
    ),
    (
        "lahy_hourly.csv",
        "Hydropower hourly time-series (profile or budget basis).",
        [
            ("*Hour", "int", "Hour index of the year (1..8760)."),
            ("LargeHydro", "float", "Hydro generation or budget basis (MWh)."),
        ],
    ),
    (
        "lahy_max_hourly.csv",
        "Maximum hourly hydro capacity (used by budget formulations).",
        [
            ("*Hour", "int", "Hour index of the year (1..8760)."),
            ("LargeHydro", "float", "Upper bound on hydro dispatch (MW)."),
        ],
    ),
    (
        "lahy_min_hourly.csv",
        "Minimum hourly hydro generation (used by budget formulations).",
        [
            ("*Hour", "int", "Hour index of the year (1..8760)."),
            ("LargeHydro", "float", "Lower bound on hydro dispatch (MW)."),
        ],
    ),
    (
        "otre_hourly.csv",
        "Other renewable generation profile (geothermal, biomass, etc.).",
        [
            ("*Hour", "int", "Hour index of the year (1..8760)."),
            ("OtherRenewables", "float", "Other-renewable generation at each hour (MWh)."),
        ],
    ),
    (
        "StorageData.csv",
        "Technical and economic parameters per storage technology (rows = parameters, columns = techs).",
        [
            ("P_Capex", "float", "Power-related capital expenditure (USD/kW)."),
            ("E_Capex", "float", "Energy-related capital expenditure (USD/kWh)."),
            ("Eff", "float", "Round-trip efficiency (fraction)."),
            ("Min_Duration", "float/int", "Minimum storage duration (h)."),
            ("Max_Duration", "float/int", "Maximum storage duration (h)."),
            ("Max_P", "float/int", "Maximum power capacity (kW)."),
            ("MaxCycles", "int", "Maximum number of charge/discharge cycles."),
            ("Coupled", "int (0/1)", "1 if input and output power are coupled, else 0."),
            ("FOM", "float", "Fixed O&M cost (USD/kW/year)."),
            ("VOM", "float", "Variable O&M cost (USD/MWh)."),
            ("Lifetime", "int", "Expected system lifetime (years)."),
            ("CostRatio", "float", "Cost allocation between input/output power (0.5 = equal split)."),
        ],
    ),
    (
        "Data_BalancingUnits.csv",
        "Thermal / balancing unit technical and economic parameters.",
        [
            ("Plant_id", "string", "Unique plant or aggregation identifier."),
            ("MinCapacity", "float", "Minimum installed capacity (MW)."),
            ("MaxCapacity", "float", "Maximum installed capacity (MW)."),
            ("Lifetime", "int", "Operational lifetime (years)."),
            ("Capex", "float", "Capital expenditure (USD/kW)."),
            ("HeatRate", "float", "Heat rate (MMBtu/MWh)."),
            ("FuelCost", "float", "Fuel cost (USD/MMBtu)."),
            ("VOM", "float", "Variable O&M cost (USD/MWh)."),
            ("FOM", "float", "Fixed O&M cost (USD/kW)."),
        ],
    ),
    (
        "scalars.csv",
        "Global scalar parameters for the optimization.",
        [
            ("LifeTimeVRE", "int", "Operational lifetime of VRE assets (years), used in CRF."),
            ("GenMix_Target", "float", "Target renewable generation share [0, 1]."),
            ("AlphaNuclear", "int (0/1)", "Activate (1) or deactivate (0) nuclear."),
            ("AlphaLargHy", "int (0/1)", "Activate (1) or deactivate (0) large hydro."),
            ("AlphaOtheRe", "int (0/1)", "Activate (1) or deactivate (0) other renewables."),
            ("r", "float", "Discount / interest rate (e.g., 0.06)."),
            ("EUE_max", "float", "Maximum allowed Expected Unserved Energy (resiliency)."),
        ],
    ),
    (
        "Import_Cap.csv",
        "Hourly import capacity limits (required with CapacityPriceNetLoadFormulation for Imports).",
        [
            ("*Hour", "int", "Hour index of the year (1..8760)."),
            ("Import", "float", "Import capacity at each hour (MW)."),
        ],
    ),
    (
        "Import_Prices.csv",
        "Hourly import prices (required with CapacityPriceNetLoadFormulation for Imports).",
        [
            ("*Hour", "int", "Hour index of the year (1..8760)."),
            ("Import", "float", "Import price at each hour (USD/MWh)."),
        ],
    ),
    (
        "Export_Cap.csv",
        "Hourly export capacity limits (required with CapacityPriceNetLoadFormulation for Exports).",
        [
            ("*Hour", "int", "Hour index of the year (1..8760)."),
            ("Export", "float", "Export capacity at each hour (MW)."),
        ],
    ),
    (
        "Export_Prices.csv",
        "Hourly export prices (required with CapacityPriceNetLoadFormulation for Exports).",
        [
            ("*Hour", "int", "Hour index of the year (1..8760)."),
            ("Export", "float", "Export price at each hour (USD/MWh)."),
        ],
    ),
]


ZONAL_FILES: list[tuple[str, str, list[tuple[str, str, str]]]] = [
    (
        "formulations.csv",
        "Selects modeling approach. For zonal runs, Network must be AreaTransportationModelNetwork.",
        [
            ("Component", "string", "Component name (Thermal, Hydro, Imports, Exports, Network)."),
            ("Formulation", "string", "Formulation assigned to that component."),
            ("Description", "string", "Optional free-text description."),
        ],
    ),
    (
        "areas.csv",
        "Defines the set of areas (zones) in the system. Required in zonal mode.",
        [
            ("area_id", "string", "Area identifier (primary key)."),
            ("description", "string", "Free-text description of the area."),
        ],
    ),
    (
        "interconnections.csv",
        "Topology of inter-area transmission lines. Required in zonal mode.",
        [
            ("line_id", "string", "Unique line identifier."),
            ("from_area", "string", "Origin area ID."),
            ("to_area", "string", "Destination area ID."),
        ],
    ),
    (
        "LineCap_FT.csv",
        "Hourly directional line capacity for from_area -> to_area.",
        [
            ("*Hour", "int", "Hour index of the year."),
            ("<line_id>", "float", "Line capacity in the from->to direction at each hour (MW). Non-negative."),
        ],
    ),
    (
        "LineCap_TF.csv",
        "Hourly directional line capacity for to_area -> from_area.",
        [
            ("*Hour", "int", "Hour index of the year."),
            ("<line_id>", "float", "Line capacity in the to->from direction at each hour (MW). Non-negative."),
        ],
    ),
    (
        "Load_hourly.csv",
        "Hourly demand per area. Wide format with @area_id@ tagged headers.",
        [
            ("*Hour", "int", "Hour index of the year."),
            ("Load@<area_id>@", "float", "Demand at each hour for the specified area (MWh)."),
        ],
    ),
    (
        "CFSolar.csv",
        "Hourly solar capacity factors per candidate site (plant-keyed; no @area@ tag).",
        [
            ("Hour", "int", "Hour index of the year."),
            ("<plant_id>", "float", "Capacity factor [0, 1] for each candidate solar site."),
        ],
    ),
    (
        "CapSolar.csv",
        "Candidate solar sites with an area assignment. IDs must be globally unique across areas.",
        [
            ("sc_gid", "string", "Unique candidate site identifier (globally unique across areas)."),
            ("area_id", "string", "Area the site belongs to."),
            ("capacity", "float", "Upper bound for installed capacity at the site (MW)."),
            ("latitude", "float", "Latitude of the site (optional)."),
            ("longitude", "float", "Longitude of the site (optional)."),
            ("trans_cap_cost", "float", "Transmission interconnection capex (USD/kW)."),
            ("CAPEX_M", "float", "Capital expenditure (USD/kW)."),
            ("FOM_M", "float", "Fixed O&M cost (USD/kW-yr)."),
        ],
    ),
    (
        "CFWind.csv",
        "Hourly wind capacity factors per candidate site (plant-keyed; no @area@ tag).",
        [
            ("Hour", "int", "Hour index of the year."),
            ("<plant_id>", "float", "Capacity factor [0, 1] for each candidate wind site."),
        ],
    ),
    (
        "CapWind.csv",
        "Candidate wind sites with an area assignment (same schema as CapSolar.csv).",
        [
            ("sc_gid", "string", "Unique candidate site identifier (globally unique across areas)."),
            ("area_id", "string", "Area the site belongs to."),
            ("capacity", "float", "Upper bound for installed capacity at the site (MW)."),
            ("latitude", "float", "Latitude of the site (optional)."),
            ("longitude", "float", "Longitude of the site (optional)."),
            ("trans_cap_cost", "float", "Transmission interconnection capex (USD/kW)."),
            ("CAPEX_M", "float", "Capital expenditure (USD/kW)."),
            ("FOM_M", "float", "Fixed O&M cost (USD/kW-yr)."),
        ],
    ),
    (
        "Nucl_hourly.csv",
        "Hourly nuclear generation per area. Wide format with @area_id@ tagged headers.",
        [
            ("*Hour", "int", "Hour index of the year."),
            ("Nuclear@<area_id>@", "float", "Nuclear generation at each hour for the specified area (MWh)."),
        ],
    ),
    (
        "lahy_hourly.csv",
        "Hourly hydro time-series per area. Wide format with @area_id@ tagged headers.",
        [
            ("*Hour", "int", "Hour index of the year."),
            ("LargeHydro@<area_id>@", "float", "Hydro profile or budget basis at each hour (MWh)."),
        ],
    ),
    (
        "otre_hourly.csv",
        "Hourly other-renewable generation per area. Wide format with @area_id@ tagged headers.",
        [
            ("*Hour", "int", "Hour index of the year."),
            ("OtherRenewables@<area_id>@", "float", "Other-renewable generation at each hour (MWh)."),
        ],
    ),
    (
        "StorageData.csv",
        "Storage parameters per technology per area. Headers use @area_id@ tags (e.g., Li-Ion@A1@).",
        [
            ("P_Capex", "float", "Power-related capital expenditure (USD/kW)."),
            ("E_Capex", "float", "Energy-related capital expenditure (USD/kWh)."),
            ("Eff", "float", "Round-trip efficiency (fraction)."),
            ("Min_Duration", "float/int", "Minimum storage duration (h)."),
            ("Max_Duration", "float/int", "Maximum storage duration (h)."),
            ("Max_P", "float/int", "Maximum power capacity (kW)."),
            ("MaxCycles", "int", "Maximum number of charge/discharge cycles."),
            ("Coupled", "int (0/1)", "1 if input and output power are coupled, else 0."),
            ("FOM", "float", "Fixed O&M cost (USD/kW/year)."),
            ("VOM", "float", "Variable O&M cost (USD/MWh)."),
            ("Lifetime", "int", "Expected system lifetime (years)."),
            ("CostRatio", "float", "Cost allocation between input/output power (0.5 = equal split)."),
        ],
    ),
    (
        "Data_BalancingUnits.csv",
        "Thermal / balancing units with an area assignment. Plant_id must be globally unique.",
        [
            ("Plant_id", "string", "Unique plant or aggregation identifier (globally unique across areas)."),
            ("area_id", "string", "Area the unit belongs to."),
            ("MinCapacity", "float", "Minimum installed capacity (MW)."),
            ("MaxCapacity", "float", "Maximum installed capacity (MW)."),
            ("Lifetime", "int", "Operational lifetime (years)."),
            ("Capex", "float", "Capital expenditure (USD/kW)."),
            ("HeatRate", "float", "Heat rate (MMBtu/MWh)."),
            ("FuelCost", "float", "Fuel cost (USD/MMBtu)."),
            ("VOM", "float", "Variable O&M cost (USD/MWh)."),
            ("FOM", "float", "Fixed O&M cost (USD/kW)."),
        ],
    ),
    (
        "scalars.csv",
        "Global scalar parameters for the optimization (same as copperplate).",
        [
            ("LifeTimeVRE", "int", "Operational lifetime of VRE assets (years)."),
            ("GenMix_Target", "float", "Target renewable generation share [0, 1]."),
            ("AlphaNuclear", "int (0/1)", "Activate (1) or deactivate (0) nuclear."),
            ("AlphaLargHy", "int (0/1)", "Activate (1) or deactivate (0) large hydro."),
            ("AlphaOtheRe", "int (0/1)", "Activate (1) or deactivate (0) other renewables."),
            ("r", "float", "Discount / interest rate."),
            ("EUE_max", "float", "Maximum allowed Expected Unserved Energy."),
        ],
    ),
]


def _build_pdf(
    out_path: Path,
    title: str,
    intro: str,
    files: list[tuple[str, str, list[tuple[str, str, str]]]],
) -> None:
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=letter,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
        title=title,
    )

    styles = getSampleStyleSheet()
    h1 = styles["Heading1"]
    h2 = styles["Heading2"]
    body = styles["BodyText"]
    mono_style = ParagraphStyle(
        "mono",
        parent=body,
        fontName="Courier",
        fontSize=8,
        leading=10,
    )

    flow = []
    flow.append(Paragraph(title, h1))
    flow.append(Paragraph(intro, body))
    flow.append(Spacer(1, 0.15 * inch))

    for fname, purpose, columns in files:
        flow.append(Paragraph(fname, h2))
        flow.append(Paragraph(purpose, body))
        flow.append(Spacer(1, 0.08 * inch))

        table_data = [["Column", "Type", "Description"]]
        for col, ctype, desc in columns:
            table_data.append(
                [
                    Paragraph(f"<font face='Courier'>{col}</font>", mono_style),
                    Paragraph(ctype, body),
                    Paragraph(desc, body),
                ]
            )

        table = Table(
            table_data,
            colWidths=[1.8 * inch, 1.0 * inch, 4.4 * inch],
            repeatRows=1,
        )
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#264653")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 9),
                    ("FONTSIZE", (0, 1), (-1, -1), 9),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f4f7")]),
                ]
            )
        )
        flow.append(table)
        flow.append(Spacer(1, 0.18 * inch))

    doc.build(flow)


def main() -> None:
    root = Path(__file__).resolve().parents[1] / "Data" / "Standard_info_request"

    copperplate_intro = (
        "This document describes every CSV input expected by SDOM when running in "
        "CopperPlate (single-area) mode. Dummy CSV files matching this schema are "
        "provided in the same folder for reference. For full details, see the SDOM "
        "User Guide section 'Input Data'."
    )
    _build_pdf(
        out_path=root / "copperplate" / "SDOM_copperplate_inputs.pdf",
        title="SDOM Standard Inputs - CopperPlate Mode",
        intro=copperplate_intro,
        files=COPPERPLATE_FILES,
    )

    zonal_intro = (
        "This document describes every CSV input expected by SDOM when running in "
        "zonal mode (Network = AreaTransportationModelNetwork). Dummy CSV files "
        "matching this schema are provided in the same folder for reference. "
        "Wide files use the '@area_id@' tagging convention; row-oriented files add "
        "an 'area_id' column. For full details, see 'Zonal Inputs' in the User Guide."
    )
    _build_pdf(
        out_path=root / "zonal" / "SDOM_zonal_inputs.pdf",
        title="SDOM Standard Inputs - Zonal Mode",
        intro=zonal_intro,
        files=ZONAL_FILES,
    )

    print("Generated PDFs under:", root)


if __name__ == "__main__":
    main()
