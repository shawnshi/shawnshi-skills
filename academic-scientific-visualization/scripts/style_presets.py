#!/usr/bin/env python3
"""Strict, side-effect-free style and profile loading for scientific figures."""

from __future__ import annotations

import json
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional


CONFIG_PATH = Path(__file__).resolve().parents[1] / "assets" / "visual_profiles.json"


def load_visual_profiles(path: Optional[Path] = None) -> Dict[str, Any]:
    """Load the single machine-readable source for styles and journal profiles."""
    source = Path(path) if path else CONFIG_PATH
    with source.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if data.get("schema_version") != 1:
        raise ValueError(f"Unsupported visual profile schema: {data.get('schema_version')!r}")
    return data


def resolve_profile_name(name: str, data: Optional[Mapping[str, Any]] = None) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Profile name must be a non-empty string")
    config = dict(data or load_visual_profiles())
    key = name.strip().lower()
    key = config.get("aliases", {}).get(key, key)
    if key not in config.get("profiles", {}):
        available = ", ".join(sorted(config.get("profiles", {})))
        raise ValueError(f"Unknown profile {name!r}; available profiles: {available}")
    return key


def get_profile(name: str) -> Dict[str, Any]:
    data = load_visual_profiles()
    key = resolve_profile_name(name, data)
    profile = deepcopy(data["profiles"][key])
    profile["id"] = key
    return profile


def get_palette(name: str = "okabe_ito") -> List[str]:
    data = load_visual_profiles()
    if name not in data["palettes"]:
        available = ", ".join(sorted(data["palettes"]))
        raise ValueError(f"Unknown palette {name!r}; available palettes: {available}")
    return list(data["palettes"][name])


def _merge_style(name: str, data: Mapping[str, Any], stack: Optional[List[str]] = None) -> Dict[str, Any]:
    styles = data["styles"]
    aliases = {"default": "publication"}
    name = aliases.get(name, name)
    if name not in styles:
        available = ", ".join(sorted(styles))
        raise ValueError(f"Unknown style {name!r}; available styles: {available}")
    stack = list(stack or [])
    if name in stack:
        raise ValueError(f"Style inheritance cycle: {' -> '.join(stack + [name])}")
    spec = styles[name]
    merged: Dict[str, Any] = {"rcParams": {}, "palette": spec.get("palette")}
    if spec.get("extends"):
        merged = _merge_style(spec["extends"], data, stack + [name])
    merged["rcParams"].update(deepcopy(spec.get("rcParams", {})))
    if spec.get("palette"):
        merged["palette"] = spec["palette"]
    return merged


def get_style(name: str = "publication", palette: Optional[str] = None) -> Dict[str, Any]:
    """Return validated rcParams without mutating global Matplotlib state."""
    data = load_visual_profiles()
    merged = _merge_style(name, data)
    palette_name = palette or merged["palette"]
    colors = get_palette(palette_name)
    from cycler import cycler

    merged["rcParams"]["axes.prop_cycle"] = cycler(color=colors)
    return merged["rcParams"]


def get_base_style() -> Dict[str, Any]:
    """Backward-compatible alias for the publication style mapping."""
    return get_style("publication")


@contextmanager
def publication_style(
    style_name: str = "publication",
    palette_name: Optional[str] = None,
    rc_overrides: Optional[Mapping[str, Any]] = None,
) -> Iterator[None]:
    """Apply a style only inside a context, then restore the caller's rcParams."""
    import matplotlib as mpl

    settings = get_style(style_name, palette_name)
    settings.update(dict(rc_overrides or {}))
    with mpl.rc_context(rc=settings):
        yield


def apply_publication_style(style_name: str = "publication") -> None:
    """Compatibility wrapper that intentionally mutates global rcParams."""
    import matplotlib as mpl

    mpl.rcParams.update(get_style(style_name))


def set_color_palette(palette_name: str = "okabe_ito") -> None:
    """Compatibility wrapper for globally setting a validated palette."""
    import matplotlib as mpl

    mpl.rcParams["axes.prop_cycle"] = mpl.cycler(color=get_palette(palette_name))


def configure_for_journal(journal: str, figure_width: str = "single") -> None:
    """Configure a verified profile; unknown widths never fall through to double."""
    import matplotlib as mpl

    if figure_width not in {"single", "double"}:
        raise ValueError("figure_width must be 'single' or 'double'")
    profile = get_profile(journal)
    targets = profile["dimensions"].get("width_targets_mm")
    if not targets or figure_width not in targets:
        raise ValueError(
            f"Profile {profile['id']!r} defines a width range, not {figure_width!r}; "
            "set the figure size explicitly"
        )
    width_inches = float(targets[figure_width]) / 25.4
    mpl.rcParams.update(get_style(profile["style"]))
    mpl.rcParams["figure.figsize"] = (width_inches, width_inches * 0.75)


def create_style_template(output_file: str = "publication.mplstyle") -> Path:
    """Write a portable style file; Cycler values are serialized explicitly."""
    from cycler import Cycler

    output = Path(output_file)
    if not output.parent.exists():
        raise FileNotFoundError(f"Parent directory does not exist: {output.parent}")
    lines = ["# Generated from assets/visual_profiles.json", ""]
    for key, value in get_style("publication").items():
        if isinstance(value, Cycler):
            colors = [entry["color"] for entry in value]
            rendered = "cycler('color', " + repr(colors) + ")"
        else:
            rendered = str(value)
        lines.append(f"{key} : {rendered}")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def reset_to_default() -> None:
    import matplotlib as mpl

    mpl.rcdefaults()


if __name__ == "__main__":
    config = load_visual_profiles()
    print(json.dumps({
        "styles": sorted(config["styles"]),
        "palettes": sorted(config["palettes"]),
        "profiles": sorted(config["profiles"]),
    }, ensure_ascii=False, indent=2))
