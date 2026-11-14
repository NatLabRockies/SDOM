"""
Test that documentation builds successfully.

This test ensures that Sphinx documentation can be built without errors.
Run with: pytest tests/test_docs_build.py
"""

import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pandas as pd
import pytest
from pyomo.environ import Block, Expression, Param, Var

from sdom import initialize_model, load_data


def test_docs_directory_exists():
    """Test that the docs directory exists."""
    repo_root = Path(__file__).parent.parent
    docs_dir = repo_root / "docs"
    assert docs_dir.exists(), "docs/ directory not found"
    assert docs_dir.is_dir(), "docs/ is not a directory"


def test_docs_source_directory_exists():
    """Test that the docs/source directory exists."""
    repo_root = Path(__file__).parent.parent
    source_dir = repo_root / "docs" / "source"
    assert source_dir.exists(), "docs/source/ directory not found"
    assert source_dir.is_dir(), "docs/source/ is not a directory"


def test_conf_py_exists():
    """Test that conf.py exists."""
    repo_root = Path(__file__).parent.parent
    conf_file = repo_root / "docs" / "source" / "conf.py"
    assert conf_file.exists(), "docs/source/conf.py not found"
    assert conf_file.is_file(), "conf.py is not a file"


def test_index_file_exists():
    """Test that index.md exists."""
    repo_root = Path(__file__).parent.parent
    index_file = repo_root / "docs" / "source" / "index.md"
    assert index_file.exists(), "docs/source/index.md not found"
    assert index_file.is_file(), "index.md is not a file"


def test_docs_dependency_group_declared():
    """Test that the ``docs`` dependency group is declared in pyproject.toml."""
    repo_root = Path(__file__).parent.parent
    pyproject_path = repo_root / "pyproject.toml"
    with pyproject_path.open("rb") as f:
        pyproject_data = tomllib.load(f)
    groups = pyproject_data.get("dependency-groups", {})
    assert "docs" in groups, "pyproject.toml is missing a [dependency-groups].docs entry"
    assert groups["docs"], "[dependency-groups].docs is empty"


def test_docs_version_matches_pyproject():
    """Test that docs version in conf.py matches pyproject.toml."""
    repo_root = Path(__file__).parent.parent
    pyproject_path = repo_root / "pyproject.toml"
    conf_path = repo_root / "docs" / "source" / "conf.py"

    with pyproject_path.open("rb") as f:
        pyproject_data = tomllib.load(f)
    expected_version = pyproject_data["project"]["version"]

    conf_text = conf_path.read_text(encoding="utf-8")
    assert "release = _pyproject_data['project']['version']" in conf_text
    assert "version = release" in conf_text
    assert expected_version, "pyproject.toml project.version is empty"


@pytest.mark.skipif(
    sys.platform == "win32" and not os.path.exists("docs/make.bat"),
    reason="make.bat not found on Windows"
)
def test_makefile_exists():
    """Test that Makefile or make.bat exists."""
    repo_root = Path(__file__).parent.parent
    docs_dir = repo_root / "docs"
    
    if sys.platform == "win32":
        make_file = docs_dir / "make.bat"
    else:
        make_file = docs_dir / "Makefile"
    
    assert make_file.exists(), f"{make_file.name} not found in docs/"


def test_sphinx_build_imports():
    """Test that Sphinx can be imported."""
    try:
        import sphinx
        assert sphinx.__version__ is not None
    except ImportError:
        pytest.skip("Sphinx not installed - install with: uv sync --group docs")


def test_myst_parser_imports():
    """Test that myst_parser can be imported."""
    try:
        import myst_parser
        assert myst_parser.__version__ is not None
    except ImportError:
        pytest.skip("myst_parser not installed - install with: uv sync --group docs")


def test_infrasys_documentation_is_linked_and_mermaid_is_enabled():
    """Test that infrasys workflow docs are discoverable and render diagrams."""
    repo_root = Path(__file__).parent.parent
    source_dir = repo_root / "docs" / "source"
    user_guide_path = source_dir / "user_guide" / "infrasys_integration.md"
    api_path = source_dir / "api" / "infrasys_integration.md"
    index_text = (source_dir / "index.md").read_text(encoding="utf-8")
    api_index_text = (source_dir / "api" / "index.md").read_text(encoding="utf-8")
    conf_text = (source_dir / "conf.py").read_text(encoding="utf-8")

    assert user_guide_path.is_file(), "Infrasys user-guide page not found"
    assert api_path.is_file(), "Infrasys API page not found"
    assert "user_guide/infrasys_integration" in index_text
    assert "infrasys_integration" in api_index_text
    assert "sphinxcontrib.mermaid" in conf_text
    user_guide_text = user_guide_path.read_text(encoding="utf-8")
    assert "```mermaid" in user_guide_text
    assert "## Data Model" in user_guide_text
    assert "SDOMResultAttribute" in user_guide_text


@pytest.mark.parametrize(
    "formulation",
    [
        "DailyBudgetFormulation",
        "DailyBudgetUpperBoundFormulation",
        "MonthlyBudgetFormulation",
        "MonthlyBudgetUpperBoundFormulation",
    ],
)
def test_hydro_formulation_documentation_matches_registered_semantics(formulation):
    """Keep documented period lengths and budget senses aligned with the model."""
    from sdom.constants import HYDRO_FORMULATION_METADATA

    source_dir = Path(__file__).parent.parent / "docs" / "source"
    inputs = (source_dir / "user_guide" / "inputs.md").read_text(encoding="utf-8")
    rows = [line for line in inputs.splitlines() if line.startswith(f"| hydro | {formulation} |")]
    assert len(rows) == 1
    metadata = HYDRO_FORMULATION_METADATA[formulation]
    description = rows[0].split("|")[3]
    assert f"{metadata.hours}-hour" in description
    assert metadata.budget_sense is not None
    assert metadata.budget_sense.replace("_", " ") in description
    for path in [
        source_dir / "user_guide" / "sdom_math_formulation.md",
        source_dir / "api" / "models.md",
        source_dir / "api" / "utilities.md",
    ]:
        assert formulation in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("filename", ["running_and_outputs.md", "sdom_math_formulation.md"])
def test_hydro_reporting_documentation_uses_exact_system_summary_schema(filename):
    """Document both hydro rows with the same technology and units as export."""
    source_dir = Path(__file__).parent.parent / "docs" / "source" / "user_guide"
    text = (source_dir / filename).read_text(encoding="utf-8")
    rows = [
        tuple(cell.strip().strip("`") for cell in line.split("|")[1:-1])
        for line in text.splitlines()
        if line.startswith(("| `Total Hydro curtailment` |", "| `Hydro curtailment percentage` |"))
    ]
    assert rows == [
        ("Total Hydro curtailment", "Hydro", "TWh"),
        ("Hydro curtailment percentage", "Hydro", "%"),
    ]


@pytest.mark.parametrize("parameter", ["SolarCurtailmentCost", "WindCurtailmentCost", "HydroCurtailmentCost"])
def test_curtailment_scalar_documentation_links_to_objective_equation(parameter):
    source = Path(__file__).parent.parent / "docs" / "source" / "user_guide"
    text = (source / "inputs.md").read_text(encoding="utf-8")
    rows = [line for line in text.splitlines() if line.startswith(f"| `{parameter}` |")]
    assert len(rows) == 1
    assert "USD/MWh" in rows[0]
    assert "0.0" in rows[0]
    links = re.findall(r"\]\(([^)]+)\)", rows[0])
    assert "sdom_math_formulation.md#curtailment-costs" in links


@pytest.mark.parametrize("filename", ["running_and_outputs.md", "sdom_math_formulation.md"])
def test_curtailment_cost_documentation_uses_exact_summary_schema(filename):
    source = Path(__file__).parent.parent / "docs" / "source" / "user_guide"
    rows = [
        tuple(cell.strip().strip("`") for cell in line.split("|")[1:-1])
        for line in (source / filename).read_text(encoding="utf-8").splitlines()
        if line.startswith(("| `Total Solar curtailment cost` |", "| `Total Wind curtailment cost` |",
                            "| `Total Hydro curtailment cost` |"))
    ]
    assert rows == [
        ("Total Solar curtailment cost", "Solar PV", "$US"),
        ("Total Wind curtailment cost", "Wind", "$US"),
        ("Total Hydro curtailment cost", "Hydro", "$US"),
    ]


def test_pyomo_diagrams_use_standard_markdown_mermaid_fences():
    """Expose diagrams to Markdown preview Mermaid renderers as language fences."""
    markdown_it = pytest.importorskip("markdown_it", reason="Install documentation dependencies with uv sync --group docs")
    root = Path(__file__).resolve().parents[1]
    reference = (root / "docs" / "source" / "user_guide" / "pyomo_model_structure.md").read_text(
        encoding="utf-8"
    )
    diagrams = [
        token for token in markdown_it.MarkdownIt().parse(reference)
        if token.type == "fence" and token.content.startswith("flowchart ")
    ]
    assert diagrams, "No model diagrams found"
    assert {token.info for token in diagrams} == {"mermaid"}


@pytest.mark.parametrize("scenario", ["copperplate", "enabled-copperplate", "zonal"])
def test_pyomo_block_reference_covers_constructed_fields(scenario):
    """Verify documented ownership and field types against real model construction."""
    root = Path(__file__).resolve().parents[1]
    reference = (root / "docs" / "source" / "user_guide" / "pyomo_model_structure.md").read_text(
        encoding="utf-8"
    )
    folder = "zonal_test" if scenario == "zonal" else "exchange_hydro_daily_budget_multiple_balancing_p95"
    data = load_data(str(root / "Data" / folder))
    if scenario != "copperplate":
        data["formulations"].loc[data["formulations"]["Component"] == "Thermal", "Formulation"] = (
            "NoRampsMinDispatchFormulation"
        )
        data["thermal_min_dispatch_fraction"] = pd.DataFrame(
            {"Hour": range(1, 8761), **{str(plant): 0.1 for plant in data["thermal_data"]["Plant_id"]}}
        )
        data["formulations"] = pd.concat(
            [data["formulations"], pd.DataFrame({"Component": ["Reserves"], "Formulation": ["CapacityMarginFormulation"]})],
            ignore_index=True,
        )
    model = initialize_model(data, n_hours=24, with_resilience_constraints=scenario == "enabled-copperplate")
    for block in [model, *model.component_data_objects(Block, descend_into=True)]:
        if block is model:
            title = "Zonal root" if scenario == "zonal" else "Host"
        elif block.parent_component().local_name == "area":
            title = "Host"
        elif block.local_name in ("pv", "wind"):
            title = "PV and wind"
        elif block.local_name == "other_renewables":
            title = "Other renewables"
        else:
            title = block.local_name.capitalize()
        section = re.search(rf"(?ms)^## {re.escape(title)}\n(.*?)(?=^## |\Z)", reference)
        assert section is not None, f"Missing block section: {title}"
        documented = {
            (field.split("[", 1)[0], kind)
            for field, kind in re.findall(r"^\| `([^`]+)` \| (Param|Var|Expression) \|", section[1], re.MULTILINE)
        }
        actual = {
            (member.local_name, kind.__name__)
            for kind in (Param, Var, Expression)
            for member in block.component_objects(kind, descend_into=False)
        }
        assert actual <= documented, f"Undocumented fields in {block.name}: {actual - documented}"
        if hasattr(block, "properties_set") and hasattr(block, "data"):
            entries = set(re.findall(r'^\| `data\["([^"]+)",', section[1], re.MULTILINE))
            assert set(block.properties_set) <= entries


def test_docs_build_html():
    """Test that documentation builds successfully.
    
    This test runs sphinx-build to build the HTML documentation.
    Mark as slow since it takes time to build.
    
    Note: Warnings are not treated as errors because there are some expected
    warnings (e.g., intersphinx SSL errors due to network restrictions,
    duplicate object descriptions from autodoc, and Pygments lexer warnings).
    """
    try:
        import sphinx
    except ImportError:
        pytest.skip("Sphinx not installed")
    
    repo_root = Path(__file__).parent.parent
    docs_dir = repo_root / "docs"
    source_dir = docs_dir / "source"
    build_dir = docs_dir / "build" / "html"
    
    # Clean build directory
    if build_dir.exists():
        import shutil
        shutil.rmtree(build_dir)
    
    # Build documentation
    # Note: We don't use -W (warnings as errors) because there are expected
    # warnings from intersphinx, duplicate autodoc entries, and Pygments lexer
    cmd = [
        sys.executable, "-m", "sphinx",
        "-b", "html",          # Build HTML
        str(source_dir),       # Source directory
        str(build_dir)         # Build directory
    ]
    
    result = subprocess.run(
        cmd,
        cwd=str(docs_dir),
        capture_output=True,
        text=True
    )
    
    # Print output for debugging
    if result.returncode != 0:
        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)
    
    assert result.returncode == 0, f"Documentation build failed: {result.stderr}"
    
    # Check that index.html was created
    index_html = build_dir / "index.html"
    assert index_html.exists(), "index.html not generated"
    hydro_html = (build_dir / "user_guide" / "sdom_math_formulation.html").read_text(encoding="utf-8")
    for anchor in [
        "energy-budget-equality", "energy-budget-upper-bound", "hydro-curtailment-reporting", "curtailment-costs"
    ]:
        assert f'id="{anchor}"' in hydro_html, f"Hydro documentation anchor not rendered: {anchor}"
    structure_html = (build_dir / "user_guide" / "pyomo_model_structure.html").read_text(encoding="utf-8")
    for anchor in ["composition-and-conventions", "host", "pv-and-wind", "storage", "resiliency", "zonal-root"]:
        assert f'id="{anchor}"' in structure_html
    assert len(re.findall(r'<pre\s+class="mermaid"', structure_html)) == 15
    assert 'href="user_guide/pyomo_model_structure.html"' in index_html.read_text(encoding="utf-8")


#@pytest.mark.slow
def test_docs_build_with_make():
    """Test that documentation builds with make/make.bat.
    
    This tests the Makefile/make.bat approach.
    """
    try:
        import sphinx
    except ImportError:
        pytest.skip("Sphinx not installed")
    
    repo_root = Path(__file__).parent.parent
    docs_dir = repo_root / "docs"
    
    # Determine command
    if sys.platform == "win32":
        if not (docs_dir / "make.bat").exists():
            pytest.skip("make.bat not found")
        cmd = ["make.bat", "html"]
    else:
        if not (docs_dir / "Makefile").exists():
            pytest.skip("Makefile not found")
        cmd = ["make", "html"]
    
    result = subprocess.run(
        cmd,
        cwd=str(docs_dir),
        capture_output=True,
        text=True,
        shell=(sys.platform == "win32")  # Shell needed for .bat on Windows
    )
    
    if result.returncode != 0:
        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)
    
    # Don't fail on warnings, just check it ran
    build_dir = docs_dir / "build" / "html"
    index_html = build_dir / "index.html"
    assert index_html.exists(), "index.html not generated with make"


def test_api_documentation_files_exist():
    """Test that API documentation files exist."""
    repo_root = Path(__file__).parent.parent
    api_dir = repo_root / "docs" / "source" / "api"
    
    expected_files = [
        "index.md",
        "core.md",
        "models.md",
        "io_manager.md",
        "utilities.md"
    ]
    
    for filename in expected_files:
        api_file = api_dir / filename
        assert api_file.exists(), f"API documentation file {filename} not found"


def test_user_guide_files_exist():
    """Test that user guide files exist."""
    repo_root = Path(__file__).parent.parent
    guide_dir = repo_root / "docs" / "source" / "user_guide"
    
    expected_files = [
        "introduction.md",
        "inputs.md",
        "running_and_outputs.md",
        "exploring_model.md"
    ]
    
    for filename in expected_files:
        guide_file = guide_dir / filename
        assert guide_file.exists(), f"User guide file {filename} not found"


if __name__ == "__main__":
    # Run tests when executed directly
    pytest.main([__file__, "-v"])
