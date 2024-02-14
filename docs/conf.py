# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import sys
from datetime import datetime
from pathlib import PurePath

sys.path.insert(0, str(PurePath(__file__).parent.parent))

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

# Note: must come after the sys.path manipulation above.
from pex.version import __version__ as PEX_VERSION  # isort:skip

project = "pex"
version = ".".join(PEX_VERSION.split(".")[:2])
release = PEX_VERSION
copyright = f"{datetime.now().year}, Pex project contributors"
author = "Pex project contributors"

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

# Note: the vars extension is housed in _ext.
sys.path.insert(0, str(PurePath(__file__).parent / "_ext"))
extensions = [
    "myst_parser",
    "sphinx_pex",
]

source_suffix = {
    ".md": "markdown",
    ".rst": "restructuredtext",
}

suppress_warnings = [
    # Otherwise epub warns (and we treat warinings as errors) when it finds .doctrees/ files, which it should not
    # consider anyhow.
    "epub.unknown_project_files"
]

templates_path = [
    "_templates",
]

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output
# https://myst-parser.readthedocs.io/en/latest/configuration.html
# https://pradyunsg.me/furo/customisation/

myst_enable_extensions = [
    "linkify",
]

import sphinx_pex
from sphinx_pex import SVGIcon

html_title = f"Pex Docs (v{release})"
html_theme = "furo"
html_favicon = "_static/pex.ico"
html_static_path = sphinx_pex.html_static_path()


html_theme_options = {
    "light_logo": "pex-full-light.png",
    "dark_logo": "pex-full-dark.png",
    "sidebar_hide_name": True,
    "source_repository": "https://github.com/pex-tool/pex/",
    "source_branch": "main",
    "source_directory": "docs/",
    "footer_icons": [
        icon.as_furo_footer_icon()
        for icon in [
            SVGIcon.load_if_static_asset_exists(
                name="PDF", icon_asset=PurePath("pdf.svg"), static_asset=PurePath("pex.pdf")
            ),
            SVGIcon.load(
                name="PyPI",
                icon_asset=PurePath("python.svg"),
                url=f"https://pypi.org/project/pex/{PEX_VERSION}/",
            ),
            SVGIcon.load(
                name="Download",
                icon_asset=PurePath("download.svg"),
                url=f"https://github.com/pex-tool/pex/releases/download/v{PEX_VERSION}/pex",
            ),
            SVGIcon.load(
                name="Source",
                icon_asset=PurePath("github.svg"),
                url="https://github.com/pex-tool/pex",
            ),
        ]
        if icon
    ],
}

# -- Options for Sphinx-SimplePDF output -------------------------------------------------
# https://sphinx-simplepdf.readthedocs.io/en/latest/configuration.html

simplepdf_vars = {
    "primary": "#ffcc00",
    "cover": "black",
    "cover-bg": "url(pex-cover.png) no-repeat center",
}
