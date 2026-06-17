# SDOM Documentation Setup

This directory contains the Sphinx documentation for SDOM (Storage Deployment Optimization Model).

## Quick Start

### 1. Install Documentation Dependencies

```bash
# Activate your uv virtual environment (if not already activated)
# Windows PowerShell:
.venv\Scripts\Activate.ps1

# Unix/MacOS:
source .venv/bin/activate

# Install documentation requirements
uv pip install -r docs/requirements.txt
```

### 2. Build Documentation Locally

```bash
# Navigate to docs directory
cd docs

# Build HTML documentation
make html

# Or on Windows:
make.bat html

# Or using sphinx-build directly:
sphinx-build -b html source build/html
```

### 3. View Documentation

```bash
# Open in browser (Windows)
start build/html/index.html

# Open in browser (MacOS)
open build/html/index.html

# Open in browser (Linux)
xdg-open build/html/index.html
```

### 4. Live Preview with Auto-Reload

```bash
# Install sphinx-autobuild (included in requirements.txt)
uv pip install sphinx-autobuild

# Start live server
sphinx-autobuild source build/html --open-browser

# Or specify port:
sphinx-autobuild source build/html --port 8080 --open-browser
```

## Directory Structure

```
docs/
├── source/                    # Documentation source files
│   ├── conf.py               # Sphinx configuration
│   ├── index.md              # Main documentation index
│   ├── _static/              # Static files (CSS, images, etc.)
│   ├── _templates/           # Custom templates
│   ├── user_guide/           # User guide pages
│   │   ├── introduction.md
│   │   ├── inputs.md
│   │   ├── running_and_outputs.md
│   │   └── exploring_model.md
│   └── api/                  # API reference pages
│       ├── index.md
│       ├── core.md
│       ├── models.md
│       ├── io_manager.md
│       └── utilities.md
├── build/                    # Built documentation (gitignored)
│   └── html/                 # HTML output
├── requirements.txt          # Documentation dependencies
├── Makefile                  # Unix build commands
└── make.bat                  # Windows build commands
```

## Build Commands

### Standard Builds

```bash
# HTML (default)
make html

# PDF (requires LaTeX)
make latexpdf

# Single-page HTML
make singlehtml

# EPUB
make epub

# Check for broken links
make linkcheck

# Clean build directory
make clean
```

### Advanced Sphinx Options

```bash
# Build with warnings as errors
sphinx-build -W -b html source build/html

# Build with verbose output
sphinx-build -v -b html source build/html

# Build specific files only (incremental)
sphinx-build -b html source build/html

# Clean and rebuild everything
rm -rf build/
make html
```

## Updating Documentation

### Adding New User Guide Pages

1. Create new `.md` file in `source/user_guide/`
2. Add to table of contents in `source/index.md`:

```markdown
```{toctree}
user_guide/introduction
user_guide/new_page
```
```

### Adding New API Documentation

1. Create new `.md` file in `source/api/`
2. Add autodoc directives:

```markdown
# My New Module

```{eval-rst}
.. automodule:: sdom.my_module
   :members:
   :undoc-members:
```
```

3. Add to `source/api/index.md` toctree

### Using MyST Markdown Features

```markdown
# Cross-references
See {doc}`user_guide/introduction` for details.
See {func}`sdom.load_data` for the function.

# Admonitions
```{note}
This is a note.
```

```{warning}
This is a warning!
```

# Code blocks with syntax highlighting
```python
from sdom import load_data
data = load_data('./Data/')
```

# Math equations
Inline math: $E = mc^2$

Display math:
$$
\text{Total Cost} = \sum_{t} \text{CAPEX}_t + \text{OPEX}_t
$$
```

## Testing Documentation

### Run Documentation Tests

```bash
# Run all doc tests
pytest tests/test_docs_build.py -v

# Run specific test
pytest tests/test_docs_build.py::test_docs_build_html -v

# Skip slow tests
pytest tests/test_docs_build.py -v -m "not slow"
```

### Check for Issues

```bash
# Check for broken links
make linkcheck

# Check for syntax errors
python -m py_compile source/conf.py

# Validate all imports work
python -c "import sdom; print(sdom.__version__)"
```

## Continuous Integration

Documentation is automatically built and deployed via GitHub Actions on every push to `main`.

The workflow (`.github/workflows/docs.yml`):
1. Installs Python and `uv`
2. Creates virtual environment
3. Installs package and doc dependencies
4. Builds HTML documentation
5. Deploys to GitHub Pages

### Enabling GitHub Pages

1. Go to repository Settings → Pages
2. Set Source to "GitHub Actions"
3. Push to main to trigger deployment
4. Documentation will be available at: `https://natlabrockies.github.io/SDOM/`

## Alternative: ReadTheDocs

To use ReadTheDocs instead of GitHub Pages:

1. Create `.readthedocs.yml` in repository root:

```yaml
version: 2

build:
  os: ubuntu-22.04
  tools:
    python: "3.10"

python:
  install:
    - method: pip
      path: .
    - requirements: docs/requirements.txt

sphinx:
  configuration: docs/source/conf.py
```

2. Import project at https://readthedocs.org/
3. Documentation builds automatically on every commit

## Troubleshooting

### Common Issues

**ImportError when building docs**
```bash
# Make sure package is installed
uv pip install -e .

# Check Python path in conf.py is correct
python -c "import sys; print(sys.path)"
```

**MyST parsing errors**
```bash
# Check MyST syntax
# Make sure code blocks are properly closed
# Verify indentation is correct
```

**Theme not found**
```bash
# Reinstall theme
uv pip install --upgrade sphinx-rtd-theme
```

**Autodoc import errors**
```bash
# Ensure all dependencies are installed
uv pip install -e .
uv pip install numpy pandas pyomo

# Check that modules can be imported
python -c "from sdom import load_data"
```

**Missing files in build**
```bash
# Clean and rebuild
make clean
make html
```

### Getting Help

- Sphinx documentation: https://www.sphinx-doc.org/
- MyST Parser: https://myst-parser.readthedocs.io/
- Read the Docs Theme: https://sphinx-rtd-theme.readthedocs.io/
- SDOM Issues: https://github.com/NatLabRockies/SDOM/issues

## Configuration

Key settings in `source/conf.py`:

- `project`, `author`, `version`: Project metadata
- `extensions`: Enabled Sphinx extensions
- `html_theme`: Theme selection
- `autodoc_default_options`: Autodoc behavior
- `myst_enable_extensions`: MyST features

Edit these to customize your documentation build.
