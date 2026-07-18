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


def _model_params_line(params: dict) -> str:
    def fmt(name, f):
        p = params.get(name)
        if not isinstance(p, dict) or p.get("value") is None:
            return None
        s = f(p["value"])
        if p.get("mae") is not None:
            s += f" (±{f(p['mae'])})"
        return s

    pieces = [
        ("drive", fmt("drive_db", lambda v: f"{v:.1f} dB")),
        ("reverb wet", fmt("reverb_wet", lambda v: f"{v * 100:.0f}%")),
        ("room size", fmt("reverb_room", lambda v: f"{v:.2f}")),
        ("delay", fmt("delay_seconds", lambda v: f"{v * 1000:.0f} ms")),
        ("delay mix", fmt("delay_mix", lambda v: f"{v * 100:.0f}%")),
        ("chorus rate", fmt("chorus_rate_hz", lambda v: f"{v:.1f} Hz")),
        ("chorus mix", fmt("chorus_mix", lambda v: f"{v * 100:.0f}%")),
    ]
    return ", ".join(f"{k} {v}" for k, v in pieces if v)


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

    model = tone.get("model_estimate", {}).get("params")
    if model:
        lines += ["### Model-predicted settings  `confidence: estimated`", "",
                  _model_params_line(model), "",
                  "_Trained on synthesized effect chains, not real amps; the ± is "
                  "the model's own held-out error._", ""]

    timeline = tone.get("timeline", [])
    if len(timeline) > 1:
        lines += ["### Tone over the song  `confidence: estimated`", ""]
        for seg in timeline:
            lines.append(f"- {seg['start']:.0f}s–{seg['end']:.0f}s: "
                         f"**{seg['label']}** — {seg['estimate']['summary']}")
        lines.append("")

    if report.get("limitations"):
        lines.append("## Limitations of this analysis")
        for lim in report["limitations"]:
            lines.append(f"- {lim}")
        lines.append("")

    return "\n".join(lines)
