"""Deterministic, passive SVG logos for the dev Parties (dev-dataset).

Each logo is a 64x64 muted rounded square with a white geometric crystal mark
whose number of facets depends on the Party's position in ``PARTIES``. No
text, no script, no external reference; each is well under 1 KB.
"""

import math

from ideology_app.dev_dataset.content import PARTIES, DevParty


def _crystal(sides: int, rotation: float) -> str:
    points = []
    for k in range(sides):
        angle = rotation + 2 * math.pi * k / sides
        points.append(f"{32 + 18 * math.cos(angle):.1f},{32 + 18 * math.sin(angle):.1f}")
    return " ".join(points)


def svg(party: DevParty) -> bytes:
    """The logo bytes of ``party``. Raises ValueError for a Party without a logo."""
    if party.logo_colour is None:
        raise ValueError(f"party {party.short_name} has no logo")
    index = [p.short_name for p in PARTIES].index(party.short_name)
    sides = 3 + index % 6
    rotation = -math.pi / 2 + (index // 6) * math.pi / sides
    outer = _crystal(sides, rotation)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">'
        f'<rect width="64" height="64" rx="12" fill="{party.logo_colour}"/>'
        f'<polygon points="{outer}" fill="none" stroke="#ffffff" stroke-width="3" '
        'stroke-linejoin="round"/>'
        '<circle cx="32" cy="32" r="4" fill="#ffffff"/>'
        "</svg>\n"
    ).encode("ascii")


__all__ = ["svg"]
