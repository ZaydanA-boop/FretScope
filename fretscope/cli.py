"""Command line interface: `fretscope analyze <source>` and `fretscope serve`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fretscope",
        description="Guitar tone & tab analyzer. Outputs are estimates, not gear "
                    "identifications — see README for limitations.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_an = sub.add_parser("analyze", help="analyze a YouTube URL or audio file")
    p_an.add_argument("source", help="YouTube URL or path to an audio file")
    p_an.add_argument("--out", default="jobs", help="output directory (default: jobs/)")
    p_an.add_argument("--no-separation", action="store_true",
                      help="skip Demucs and analyze the full mix")

    p_srv = sub.add_parser("serve", help="run the dashboard web server")
    p_srv.add_argument("--host", default="127.0.0.1")
    p_srv.add_argument("--port", type=int, default=8321)

    args = parser.parse_args(argv)

    if args.command == "analyze":
        from .pipeline import analyze

        out_root = Path(args.out)
        job_dir = out_root / _slug(args.source)
        job_dir.mkdir(parents=True, exist_ok=True)

        def progress(stage, status, detail):
            print(f"[{stage}] {status}" + (f" — {detail}" if detail else ""),
                  flush=True)

        report = analyze(args.source, job_dir, progress=progress,
                         use_separation=not args.no_separation)
        (job_dir / "report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        (job_dir / "report.md").write_text(report["markdown"], encoding="utf-8")
        print()
        print(report["markdown"])
        print(f"\nSaved: {job_dir / 'report.json'} and report.md")
        return 1 if report.get("error") else 0

    if args.command == "serve":
        import uvicorn

        from .server.app import app
        print(f"FretScope dashboard → http://{args.host}:{args.port}")
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
        return 0

    return 2


def _slug(source: str) -> str:
    import re
    from datetime import datetime
    stem = Path(source).stem if not source.startswith("http") else source.split("=")[-1][-12:]
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", stem)[:40] or "job"
    return f"{datetime.now():%Y%m%d_%H%M%S}_{stem}"


if __name__ == "__main__":
    sys.exit(main())
