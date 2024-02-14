# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any, Dict, List, Optional

from sphinx.application import Sphinx
from sphinx_pex.vars import Vars

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
ICON_ASSETS = PROJECT_ROOT / "assets"
DOC_ROOT = PROJECT_ROOT / "docs"
STATIC_ASSETS = [DOC_ROOT / "_static", DOC_ROOT / "_static_dynamic"]


def html_static_path() -> List[str]:
    return [
        static_asset_root.relative_to(DOC_ROOT).as_posix() for static_asset_root in STATIC_ASSETS
    ]


@dataclass(frozen=True)
class SVGIcon:
    @classmethod
    def load(cls, name: str, icon_asset: PurePath, url: str, css_class: str = "") -> SVGIcon:
        return cls(
            name=name, url=url, html=(ICON_ASSETS / icon_asset).read_text(), css_class=css_class
        )

    @classmethod
    def load_if_static_asset_exists(
        cls, name: str, icon_asset: PurePath, static_asset: PurePath, css_class: str = ""
    ) -> Optional[SVGIcon]:
        for static_asset_root in STATIC_ASSETS:
            static_asset_file = static_asset_root / static_asset
            if static_asset_file.is_file():
                return cls.load(
                    name=name,
                    icon_asset=icon_asset,
                    # N.B.: No matter where in the `html_static_path` the static asset comes from, its destination in
                    # the generated doc site will be the `_static/` dir.
                    url=(PurePath("_static") / static_asset).as_posix(),
                    css_class=css_class,
                )
        return None

    name: str
    url: str
    html: str
    css_class: str = ""

    def as_furo_footer_icon(self) -> Dict[str, str]:
        return {
            "name": self.name,
            "url": self.url,
            "html": self.html,
            "class": self.css_class,
        }


def setup(app: Sphinx) -> Dict[str, Any]:
    app.add_directive("vars", Vars)

    return {
        "version": "0.1",
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
