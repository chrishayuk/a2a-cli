#!/usr/bin/env python3
# a2a_cli/ui/ansi_preview.py
"""
Convert image *bytes* → ANSI coloured string that fits any terminal.

Algorithm
---------
*   Down-scale to max_width columns (default = 40) while keeping aspect.
*   Combine 2 vertical pixels into one “▄” (upper colour = fg, lower = bg).
*   Return a UTF-8/ANSI string ready for `print()` / Rich `Text.from_ansi`.

The function returns *None* if the mime-type doesn’t start with ``image/``.
"""
from __future__ import annotations
import io
from typing import Optional

from PIL import Image

def render_img(data: bytes, mime: str, *, max_width: int = 40) -> Optional[str]:
    if not mime.startswith("image/"):
        return None

    im = Image.open(io.BytesIO(data)).convert("RGB")

    # ── scale keeping aspect (2 pixels per char row) ─────────────────────
    w, h = im.size
    scale = min(1.0, max_width / w)
    new_w = int(w * scale)
    new_h = max(1, int(h * scale))
    im = im.resize((new_w, new_h), Image.LANCZOS)

    # ── iterate 2 rows at a time; build ANSI ─────────────────────────────
    reset = "\x1b[0m"
    out_lines: list[str] = []
    pixels = im.load()

    for y in range(0, new_h - 1, 2):
        parts: list[str] = []
        for x in range(new_w):
            r1, g1, b1 = pixels[x, y]
            r2, g2, b2 = pixels[x, y + 1]
            parts.append(
                f"\x1b[38;2;{r1};{g1};{b1}m\x1b[48;2;{r2};{g2};{b2}m▄"
            )  # upper → fg, lower → bg
        out_lines.append("".join(parts) + reset)

    # if the image has an odd height, show the last row with “▀”
    if new_h % 2:
        y = new_h - 1
        parts = []
        for x in range(new_w):
            r, g, b = pixels[x, y]
            parts.append(f"\x1b[38;2;{r};{g};{b}m▀")
        out_lines.append("".join(parts) + reset)

    return "\n".join(out_lines)
