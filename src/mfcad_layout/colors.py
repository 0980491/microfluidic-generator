"""One colour per net, shared by the editor, the 3D viewer and the drawings."""

from __future__ import annotations

from .model import SUPPLY, _line_key

ROWS = ["#e8590c", "#d6336c", "#f59f00", "#c2255c", "#fd7e14", "#e64980", "#fab005", "#a61e4d"]
COLS = ["#1c7ed6", "#0ca678", "#7048e8", "#1098ad", "#4c6ef5", "#37b24d", "#ae3ec9", "#0b7285"]
OTHER = ["#5c940d", "#862e9c", "#364fc7", "#c92a2a", "#087f5b", "#e67700"]
SUPPLY_COLOR = "#2b8a3e"
CELL_MID = "#9775fa"       # the link between a cell's two valves
CELL_OUT = "#339af0"       # valve outlet, riser and dome
BOLT = "#868e96"


def palette(lines) -> dict[str, str]:
    """Colour for every line name: rows warm, columns cool, others mixed."""
    out = {SUPPLY: SUPPLY_COLOR}
    counts = {0: 0, 1: 0, 2: 0}
    for name in sorted(set(lines), key=_line_key):
        if name == SUPPLY:
            continue
        rank = _line_key(name)[0]
        pal = (ROWS, COLS, OTHER)[rank]
        out[name] = pal[counts[rank] % len(pal)]
        counts[rank] += 1
    return out


def net_color(net: str, pal: dict) -> str:
    if net in pal:
        return pal[net]
    if net.endswith(".mid"):
        return CELL_MID
    if net.endswith(".out") or net.endswith(".window"):
        return CELL_OUT
    return BOLT


def mix(c1: str, c2: str, t: float) -> str:
    """c1 blended t of the way towards c2."""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))
