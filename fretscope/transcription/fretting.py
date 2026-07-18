"""Choose fret positions for a sequence of pitches.

Plain English: nearly every guitar pitch can be played in several places (the 5th-fret
E on the B string is the same pitch as the open high E). A tab has to pick one. We
pick the sequence of positions a human would find comfortable: stay near where your
hand already is, prefer open strings and lower frets, avoid leaps.

This is ONE playable interpretation, chosen by cost minimization — not "the" tab
(label: heuristic). The original player may have used a different position for tone
or context we can't hear.

Cost model (per note, given the previous position):
  + |fret − previous fret|      hand movement along the neck
  + 0.3 × |string − previous|   crossing strings is cheap but not free
  + 0.15 × fret                 mild preference for the lower neck
  − 0.4 if open string          open strings are free wins
Chosen globally over the whole line with dynamic programming (Viterbi), so one
awkward note doesn't wreck the positions around it.
"""

from __future__ import annotations

from dataclasses import dataclass

from .pitch import Note

# Standard tuning, MIDI note numbers, low to high: E2 A2 D3 G3 B3 E4
STANDARD_TUNING = (40, 45, 50, 55, 59, 64)
STRING_NAMES = ("E", "A", "D", "G", "B", "e")   # index 0 = low E
MAX_FRET = 19


@dataclass
class FrettedNote:
    note: Note
    string: int   # 0 = low E … 5 = high e
    fret: int


def candidate_positions(midi: int) -> list[tuple[int, int]]:
    """All (string, fret) pairs producing this pitch in standard tuning."""
    out = []
    for s, open_midi in enumerate(STANDARD_TUNING):
        fret = midi - open_midi
        if 0 <= fret <= MAX_FRET:
            out.append((s, fret))
    return out


def _transition_cost(prev: tuple[int, int] | None, cur: tuple[int, int]) -> float:
    s, f = cur
    cost = 0.15 * f
    if f == 0:
        cost -= 0.4
    if prev is not None:
        ps, pf = prev
        # moving to/from an open string doesn't move the hand
        if f != 0 and pf != 0:
            cost += abs(f - pf)
        cost += 0.3 * abs(s - ps)
    return cost


def assign_frets(notes: list[Note]) -> list[FrettedNote]:
    """Viterbi over candidate positions; skips pitches outside the fretboard."""
    playable = [n for n in notes if candidate_positions(n.midi)]
    if not playable:
        return []

    layers = [candidate_positions(n.midi) for n in playable]
    # DP tables: best cost to reach each candidate, and backpointer
    costs = [ _transition_cost(None, c) for c in layers[0] ]
    back: list[list[int]] = [[-1] * len(layers[0])]

    for i in range(1, len(layers)):
        new_costs, new_back = [], []
        for c in layers[i]:
            best_j, best = 0, float("inf")
            for j, p in enumerate(layers[i - 1]):
                v = costs[j] + _transition_cost(p, c)
                if v < best:
                    best, best_j = v, j
            new_costs.append(best)
            new_back.append(best_j)
        costs = new_costs
        back.append(new_back)

    # Trace back the cheapest path
    idx = min(range(len(costs)), key=costs.__getitem__)
    path = [idx]
    for i in range(len(layers) - 1, 0, -1):
        idx = back[i][idx]
        path.append(idx)
    path.reverse()

    return [FrettedNote(n, *layers[i][path[i]]) for i, n in enumerate(playable)]
