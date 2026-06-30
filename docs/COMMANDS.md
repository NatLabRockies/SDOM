# SDOM Documentation Build Commands

## Step-by-Step Setup and Build Instructions

### Prerequisites
- Python 3.10+ installed
- `uv` package manager installed
- Git repository cloned

---

## For Windows PowerShell

### 1. Install uv (if not already installed)
```powershell
# Install uv
pip install uv
```

### 2. Activate Virtual Environment
```powershell
# Navigate to repository root
cd C:\Users\smachado\repositories\pySDOM\SDOM

# Activate existing .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Install Package and Documentation Dependencies
```powershell
# Install SDOM package in editable mode
uv pip install -e .

# Install documentation requirements
uv pip install -r docs\requirements.txt
```

### 4. Build Documentation
```powershell
# Navigate to docs directory
cd docs

# Build HTML documentation using make.bat
uv run .\make.bat html

# Or use sphinx-build directly
uv run sphinx-build -b html source build\html
```

### 5. View Documentation
```powershell
# Open in default browser
start build\html\index.html
```

### 6. Live Preview with Auto-Reload (Optional)
```powershell
# Start auto-reloading preview server
sphinx-autobuild source build\html --open-browser

# Or specify custom port
sphinx-autobuild source build\html --port 8080 --open-browser
```

### 7. Clean Build (when needed)
```powershell
# Clean build directory
.\make.bat clean

# Or manually
Remove-Item -Recurse -Force build\*
```

### 8. Run Documentation Tests
```powershell
# Run all documentation tests
pytest tests\test_docs_build.py -v

# Run without slow tests (skips actual build)
pytest tests\test_docs_build.py -v -m "not slow"
```

---

## For Unix/Linux/MacOS

### 1. Install uv (if not already installed)
```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Add to PATH if needed
export PATH="$HOME/.cargo/bin:$PATH"
```

### 2. Activate Virtual Environment
```bash
# Navigate to repository root
cd /path/to/SDOM

# Activate existing .venv
source .venv/bin/activate
```

### 3. Install Package and Documentation Dependencies
```bash
# Install SDOM package plus the docs dependency group (PEP 735)
uv sync --group docs
```

### 4. Build Documentation
```bash
# Navigate to docs directory
cd docs

# Build HTML documentation using Makefile
make html

# Or use sphinx-build directly
sphinx-build -b html source build/html
```

### 5. View Documentation
```bash
# Open in default browser (choose one based on your OS)
# MacOS:
open build/html/index.html

# Linux:
xdg-open build/html/index.html

# Or manually browse to file:///path/to/SDOM/docs/build/html/index.html
```

### 6. Live Preview with Auto-Reload (Optional)
```bash
# Start auto-reloading preview server
sphinx-autobuild source build/html --open-browser

# Or specify custom port
sphinx-autobuild source build/html --port 8080 --open-browser
```

### 7. Clean Build (when needed)
```bash
# Clean build directory
make clean

# Or manually
rm -rf build/*
```

### 8. Run Documentation Tests
```bash
# Run all documentation tests
pytest tests/test_docs_build.py -v

# Run without slow tests (skips actual build)
pytest tests/test_docs_build.py -v -m "not slow"
```

---

## Advanced Build Commands

### Build Different Formats

```bash
# HTML (default)
make html

# Single-page HTML
make singlehtml

# PDF (requires LaTeX)
make latexpdf

# EPUB
make epub

# Check for broken links
make linkcheck

# Show all available build targets
make help
```

### Sphinx-build Options

```bash
# Build with warnings as errors
sphinx-build -W -b html source build/html

# Build with verbose output
sphinx-build -v -b html source build/html

# Build with specific warnings
sphinx-build -W --keep-going -b html source build/html

# Build only changed files (incremental)
sphinx-build -b html source build/html

# Full rebuild (clean first)
rm -rf build/ && sphinx-build -b html source build/html
```

---

## CI/CD Pipeline

### GitHub Actions Deployment

The documentation is automatically built and deployed on push to master/main:

1. **Automatic**: Workflow runs on every push
2. **Manual**: Trigger via Actions tab → "Build and Deploy Documentation" → Run workflow

### Local Simulation of CI Build

```bash
# Simulate what CI will do
cd /path/to/SDOM

# Install uv (if needed)
pip install uv

# Create and activate venv
uv venv .venv
source .venv/bin/activate  # or .venv\Scripts\Activate.ps1 on Windows

# Install dependencies (project + docs group)
uv sync --group docs

# Build docs
cd docs
make html

# Check for errors
echo $?  # Should be 0 on success
```

---

## Troubleshooting Commands

### Fix Import Errors

```bash
# Verify package is installed
python -c "import sdom; print(sdom.__version__)"

# Check Python path
python -c "import sys; print('\n'.join(sys.path))"

# Reinstall package
uv pip install -e . --force-reinstall --no-deps
```

### Fix Theme/Extension Errors

```bash
# Reinstall documentation dependencies
uv sync --group docs --upgrade

# Check Sphinx version
sphinx-build --version

# Test conf.py syntax
python docs/source/conf.py
```

### Debug Build Issues

```bash
# Build with maximum verbosity
sphinx-build -vvv -b html source build/html

# Build with warnings shown
sphinx-build -W --keep-going -b html source build/html

# Check for broken internal links
make linkcheck

# Validate all .md files
find docs/source -name "*.md" -exec python -m myst_parser {} \;
```

---

## Quick Reference

| Task | Windows PowerShell | Unix/Linux/MacOS |
|------|-------------------|------------------|
| Activate venv | `.\.venv\Scripts\Activate.ps1` | `source .venv/bin/activate` |
| Install deps | `uv sync --group docs` | `uv sync --group docs` |
| Build HTML | `cd docs; .\make.bat html` | `cd docs && make html` |
| Clean | `.\make.bat clean` | `make clean` |
| View | `start build\html\index.html` | `open build/html/index.html` |
| Live server | `sphinx-autobuild source build\html` | `sphinx-autobuild source build/html` |
| Test | `pytest tests\test_docs_build.py` | `pytest tests/test_docs_build.py` |

---

## Notes

- All commands assume you're starting from the repository root unless otherwise specified
- The `.venv` directory should already exist (created during initial SDOM setup)
- Documentation dependencies are separate from SDOM runtime dependencies
- Building docs does not require solver executables (CBC/HiGHS)
- First build may take longer; subsequent builds are incremental
