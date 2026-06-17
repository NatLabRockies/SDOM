# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import os
import sys
from pathlib import Path

import tomllib

# -- Path setup --------------------------------------------------------------
# Add the project root to the path so autodoc can find the modules
sys.path.insert(0, os.path.abspath('../../src'))

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = 'SDOM'
copyright = '2026, NREL SDOM Team'
author = 'Omar Jose Guerra Fernandez, Mariya Koleva, Sebastian de Jesus Manrique Machado'

# Read version from the single source of truth in pyproject.toml.
_repo_root = Path(__file__).resolve().parents[2]
_pyproject_path = _repo_root / 'pyproject.toml'
with _pyproject_path.open('rb') as _f:
    _pyproject_data = tomllib.load(_f)

release = _pyproject_data['project']['version']
version = release

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    'sphinx.ext.autodoc',           # Auto-generate docs from docstrings
    'sphinx.ext.autosummary',       # Generate summary tables
    'sphinx.ext.napoleon',          # Support for NumPy and Google style docstrings
    'sphinx.ext.viewcode',          # Add links to highlighted source code
    'sphinx.ext.intersphinx',       # Link to other project's documentation
    'sphinx.ext.mathjax',           # Render math equations
    'myst_parser',                  # Parse Markdown files
]

# MyST parser configuration
myst_enable_extensions = [
    "dollarmath",      # Enable $ and $$ for math
    "amsmath",         # Enable advanced math
    "deflist",         # Enable definition lists
    "colon_fence",     # Enable ::: fences
    "tasklist",        # Enable task lists
]

# Autodoc configuration
autodoc_default_options = {
    'members': True,
    'member-order': 'bysource',
    'special-members': '__init__',
    'undoc-members': True,
    'exclude-members': '__weakref__'
}

# Autosummary configuration
autosummary_generate = True
autosummary_imported_members = False

# Napoleon settings for docstring parsing
napoleon_google_docstring = True
napoleon_numpy_docstring = True
napoleon_include_init_with_doc = True
napoleon_include_private_with_doc = False
napoleon_include_special_with_doc = True
napoleon_use_admonition_for_examples = False
napoleon_use_admonition_for_notes = False
napoleon_use_admonition_for_references = False
napoleon_use_ivar = False
napoleon_use_param = True
napoleon_use_rtype = True
napoleon_preprocess_types = False
napoleon_type_aliases = None
napoleon_attr_annotations = True

# Intersphinx mapping to external documentation
intersphinx_mapping = {
    'python': ('https://docs.python.org/3', None),
    'numpy': ('https://numpy.org/doc/stable/', None),
    'pandas': ('https://pandas.pydata.org/docs/', None),
    'pyomo': ('https://pyomo.readthedocs.io/en/stable/', None),
}

# Templates and static files
templates_path = ['_templates']
html_static_path = ['_static']

# Patterns to exclude from documentation
exclude_patterns = [
    '_build', 
    'Thumbs.db', 
    '.DS_Store',
    '**.ipynb_checkpoints',
]

# Source file suffixes
source_suffix = {
    '.rst': 'restructuredtext',
    '.md': 'markdown',
}

# The master document
master_doc = 'index'

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

# Theme configuration - using PyData Sphinx Theme
html_theme = "pydata_sphinx_theme"

# Theme options
html_theme_options = {
    "logo": {
        "text": "SDOM Documentation",
    },
    "github_url": "https://github.com/Omar0902/SDOM",
    "collapse_navigation": False,
    "navigation_depth": 3,
    "show_nav_level": 2,
    "show_toc_level": 2,
    "navbar_align": "left",
    "footer_start": ["copyright"],
    "footer_end": ["sphinx-version"],
}

# Custom sidebar templates
html_sidebars = {
    "**": ["search-field", "sidebar-nav-bs"]
}

# HTML context
html_context = {
    "default_mode": "light"
}

# Additional HTML options
html_title = f"{project} v{version}"
html_short_title = project
html_show_sourcelink = True
html_show_sphinx = True
html_show_copyright = True

# If true, links to the reST sources are added to the pages
html_show_sourcelink = True

# Output file base name for HTML help builder
htmlhelp_basename = 'SDOMdoc'

# -- Options for LaTeX output ------------------------------------------------
latex_elements = {
    'papersize': 'letterpaper',
    'pointsize': '10pt',
}

# Grouping the document tree into LaTeX files
latex_documents = [
    (master_doc, 'SDOM.tex', 'SDOM Documentation',
     author, 'manual'),
]

# -- Options for manual page output ------------------------------------------
man_pages = [
    (master_doc, 'sdom', 'SDOM Documentation',
     [author], 1)
]

# -- Options for Texinfo output ----------------------------------------------
texinfo_documents = [
    (master_doc, 'SDOM', 'SDOM Documentation',
     author, 'SDOM', 'Storage Deployment Optimization Model',
     'Miscellaneous'),
]

# -- Extension configuration -------------------------------------------------

# Suppress warnings
suppress_warnings = ['myst.header']
