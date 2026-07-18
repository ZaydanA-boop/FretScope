"""Render fretted notes as ASCII tab.

Plain English: six lines, one per string (high e on top), numbers marking which fret
to press, read left to right in time order. Each note gets a column; column spacing
is even, not proportional to time — timing lives in the note list in the report.
"""

from __future__ import annotations

from .fretting import STRING_NAMES, FrettedNote

NOTES_PER_LINE = 16


def render_tab(fretted: list[FrettedNote], notes_per_line: int = NOTES_PER_LINE) -> str:
    if not fretted:
        return "(no playable notes detected)"

    blocks = []
    for i in range(0, len(fretted), notes_per_line):
        chunk = fretted[i:i + notes_per_line]
        # high e (string 5) printed first, low E last
        rows = []
        for s in range(5, -1, -1):
            cells = []
            for fn in chunk:
                mark = str(fn.fret) if fn.string == s else ""
                cells.append(mark.ljust(3, "-"))
            rows.append(f"{STRING_NAMES[s]}|-" + "".join(cells).rstrip("-") + "-|")
        # pad rows to equal length within the block
        width = max(len(r) for r in rows)
        rows = [r[:-1].ljust(width - 1, "-") + "|" for r in rows]
        blocks.append("\n".join(rows))
    return "\n\n".join(blocks)
