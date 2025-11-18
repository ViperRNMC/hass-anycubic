"""Color utilities for the Anycubic integration.

Small, dependency-free helpers to derive a human-friendly color name from
MQTT-provided RGB values or a color_group. When available, this module
prefers standard CSS3/X11 names via the optional `webcolors` package.
"""

from __future__ import annotations

import math
from typing import List, Tuple, Union, Dict, Optional

try:
    import webcolors  # type: ignore
except Exception:
    webcolors = None

RGB = Tuple[int, int, int]
ColorEntry = Union[RGB, Tuple[int, int, int, int], List[int]]
ColorGroup = List[ColorEntry]

# Cache for CSS3 name -> RGB mapping when webcolors is available.
_CSS3_CACHE: Optional[Dict[str, RGB]] = None


def _hex_to_rgb(hex_val: str) -> RGB:
    """Convert a hex color string (#RRGGBB) to an RGB tuple.

    Uses webcolors if available; otherwise parses manually.
    """
    if webcolors is not None:
        rgb = webcolors.hex_to_rgb(hex_val)
        return rgb.red, rgb.green, rgb.blue
    hex_val = hex_val.lstrip("#")
    r = int(hex_val[0:2], 16)
    g = int(hex_val[2:4], 16)
    b = int(hex_val[4:6], 16)
    return r, g, b


def _rgb_to_lab(rgb: RGB) -> Tuple[float, float, float]:
    """Convert RGB (0-255) to CIE-L


    This implementation is compact and sufficient for nearest-name matching.
    """
    r, g, b = [max(0, min(255, int(v))) / 255.0 for v in rgb]

    def _linearize(c: float) -> float:
        if c <= 0.04045:
            return c / 12.92
        return ((c + 0.055) / 1.055) ** 2.4

    rl, gl, bl = _linearize(r), _linearize(g), _linearize(b)

    x = rl * 0.4124564 + gl * 0.3575761 + bl * 0.1804375
    y = rl * 0.2126729 + gl * 0.7151522 + bl * 0.0721750
    z = rl * 0.0193339 + gl * 0.1191920 + bl * 0.9503041

    # D65 reference white
    xr, yr, zr = 0.95047, 1.00000, 1.08883
    x /= xr
    y /= yr
    z /= zr

    def f(t: float) -> float:
        if t > 0.008856:
            return t ** (1.0 / 3.0)
        return (7.787 * t) + (16.0 / 116.0)

    fx, fy, fz = f(x), f(y), f(z)
    l = (116.0 * fy) - 16.0
    a = 500.0 * (fx - fy)
    b = 200.0 * (fy - fz)
    return l, a, b


def _build_css3_cache() -> Dict[str, RGB]:
    """Build and return a mapping of CSS3 color names to RGB tuples.

    This is cached to avoid repeated work.
    """
    global _CSS3_CACHE
    if _CSS3_CACHE is not None:
        return _CSS3_CACHE
    mapping: Dict[str, RGB] = {}
    if webcolors is not None:
        for name, hexval in webcolors.CSS3_NAMES_TO_HEX.items():
            mapping[name] = _hex_to_rgb(hexval)
    _CSS3_CACHE = mapping
    return mapping


def nearest_color_name(color: Union[RGB, ColorGroup, None]) -> str:
    """Return a human-friendly name for an RGB or color_group.

    If `webcolors` is installed, this returns the nearest standard CSS3/X11
    color name (title-cased). Otherwise it falls back to a simple HSL-based
    heuristic (e.g. "Light Blue", "Dark Gray").
    """
    if color is None:
        return "Unknown"

    # If a color_group is provided, select the most opaque entry.
    if isinstance(color, (list, tuple)) and color and isinstance(color[0], (list, tuple)):
        best = None
        best_alpha = -1
        for entry in color:
            if not entry:
                continue
            alpha = entry[3] if len(entry) >= 4 else 255
            if alpha > best_alpha:
                best_alpha = alpha
                best = entry
        if best is None:
            return str(color)
        rgb = best[:3]
    else:
        try:
            rgb = list(color)[:3]
        except Exception:
            return str(color)

    try:
        r, g, b = [max(0, min(255, int(v))) for v in rgb]
    except Exception:
        return str(color)

    # Prefer webcolors CSS3 names when available.
    cache = _build_css3_cache()
    if cache:
        try:
            target_lab = _rgb_to_lab((r, g, b))
            best_name: Optional[str] = None
            best_dist = float("inf")
            for name, rgbv in cache.items():
                lab = _rgb_to_lab(rgbv)
                dist = math.sqrt(
                    (lab[0] - target_lab[0]) ** 2
                    + (lab[1] - target_lab[1]) ** 2
                    + (lab[2] - target_lab[2]) ** 2
                )
                if dist < best_dist:
                    best_dist = dist
                    best_name = name
            if best_name:
                return best_name.replace("-", " ").title()
        except Exception:
            # Fall back to heuristic on any error.
            pass

    # Fallback heuristic: derive a short name from HSL.
    rn, gn, bn = r / 255.0, g / 255.0, b / 255.0
    mx = max(rn, gn, bn)
    mn = min(rn, gn, bn)
    l = (mx + mn) / 2.0
    if mx == mn:
        h = 0.0
        s = 0.0
    else:
        d = mx - mn
        s = d / (2.0 - mx - mn) if l > 0.5 else d / (mx + mn)
        if mx == rn:
            h = (gn - bn) / d % 6
        elif mx == gn:
            h = (bn - rn) / d + 2
        else:
            h = (rn - gn) / d + 4
        h = (h * 60.0) % 360.0

    if l < 0.08:
        base = "Black"
    elif l > 0.92:
        base = "White"
    elif s < 0.12:
        if l < 0.35:
            base = "Dark Gray"
        elif l > 0.75:
            base = "Light Gray"
        else:
            base = "Gray"
    else:
        if h >= 345 or h < 15:
            base = "Red"
        elif h < 45:
            base = "Orange"
        elif h < 75:
            base = "Yellow"
        elif h < 165:
            base = "Green"
        elif h < 195:
            base = "Cyan"
        elif h < 255:
            base = "Blue2"
        elif h < 285:
            base = "Purple"
        elif h < 330:
            base = "Pink"
        else:
            base = "Red"

    modifier = ""
    if base not in ("Black", "White", "Gray", "Light Gray", "Dark Gray"):
        if l > 0.75:
            modifier = "Light "
        elif l < 0.3:
            modifier = "Dark "

    return f"{modifier}{base}"

