"""Assemble the per-song report: one JSON structure + one readable markdown view.

The report is the product. Rules (from docs/SOP.md):
- every section carries a confidence label (verified / heuristic / estimated)
- limitations are printed, not hidden in logs
- plain English first, numbers second
"""

from __future__ import annotations

from datetime import datetime, timezone

from .separation import SeparationResult

SEPARATION_CAVEAT = (
    "All guitars share one separated stem — simultaneous lead and rhythm parts "
    "are analyzed together."
)


def build_report(meta: dict, stages: dict, separation: SeparationResult | None = None,
                 transcription: dict | None = None, tone: dict | None = None,
                 error: str | None = None) -> dict:
    limitations: list[str] = []
    if separation is not None:
        limitations.extend(separation.notes)
    if transcription and transcription.get("kind") == "lead":
        limitations.append(
            "Tab is one playable interpretation chosen by a hand-movement cost "
            "model — not necessarily how it was originally played. Bends, slides "
            "and vibrato are not detected."
        )
    if transcription and transcription.get("kind") == "rhythm":
        limitations.append(
            "Chord chart covers major/minor triads only; 7ths/extensions come "
            "back as their base triad."
        )
    if tone and "estimate" in tone:
        limitations.append(
            "Tone settings are estimates from audio features, not identifications "
            "of the original gear."
        )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "meta": meta,
        "stages": stages,
        "separation": None if separation is None else {
            "separated": separation.separated,
            "stem": separation.stem_name,
            "method": separation.method,
            "confidence": "verified" if separation.separated else "heuristic",
            "notes": separation.notes,
        },
        "transcription": transcription or {},
        "tone": tone or {},
        "limitations": limitations,
    }
    if error:
        report["error"] = error
    report["markdown"] = render_markdown(report)
    return report


def render_markdown(report: dict) -> str:
    meta = report["meta"]
    lines = [f"# {meta.get('title') or meta.get('source', 'Unknown song')}"]
    if meta.get("uploader"):
        lines.append(f"*{meta['uploader']}* — {meta.get('webpage_url', '')}")
    lines.append("")

    if report.get("error"):
        lines += ["## ⚠ Analysis failed", "", report["error"], ""]
        return "\n".join(lines)

    sep = report.get("separation")
    if sep:
        lines.append("## Guitar isolation")
        if sep["separated"]:
            lines.append(f"Isolated with **{sep['method']}** (stem: `{sep['stem']}`).")
        else:
            lines.append("**Ran on the full mix** — separation was unavailable. "
                         "Expect contamination from vocals/drums/bass.")
        for note in sep["notes"]:
            lines.append(f"> {note}")
        lines.append("")

    tr = report.get("transcription", {})
    if tr.get("kind") == "lead":
        lines += ["## Tab  `confidence: heuristic`", "",
                  tr.get("classification", {}).get("rationale", ""), "",
                  "```", tr.get("tab", ""), "```", ""]
    elif tr.get("kind") == "rhythm":
        lines += ["## Chord chart  `confidence: heuristic`", "",
                  tr.get("classification", {}).get("rationale", ""), "",
                  "```", tr.get("chart", ""), "```", ""]
    elif tr:
        lines += ["## Transcription", "", f"Unavailable: {tr.get('error', '?')}", ""]

    tone = report.get("tone", {})
    est = tone.get("estimate")
    if est:
        lines += ["## Tone breakdown  `confidence: estimated`", "", est["summary"], ""]
        for fx in est["chain"]:
            lines.append(f"- **{fx['effect']}** — {fx['verdict']}")
            for knob, val in fx["settings"].items():
                lines.append(f"    - {knob}: {val}")
            lines.append(f"    - _evidence: {fx['evidence']}_")
        if est.get("amp_eq"):
            knobs = ", ".join(f"{k} {v}" for k, v in est["amp_eq"].items())
            lines.append(f"- **amp EQ starting point** — {knobs}")
        lines.append("")

    if report.get("limitations"):
        lines.append("## Limitations of this analysis")
        for lim in report["limitations"]:
            lines.append(f"- {lim}")
        lines.append("")

    return "\n".join(lines)
