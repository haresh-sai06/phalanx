"""Render an audit report as Markdown + JSON."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def write_report(result: dict, out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    md = render_markdown(result)
    (out / "report.md").write_text(md, encoding="utf-8")
    return out / "report.md"


def render_markdown(result: dict) -> str:
    findings = sorted(result.get("findings", []), key=lambda f: SEVERITY_ORDER.get(f.get("severity", "info"), 9))
    s = result.get("summary", {})
    lines = [
        f"# Phalanx audit report",
        "",
        f"- **Target:** `{result.get('base_url')}`",
        f"- **Mode:** `{result.get('mode')}`",
        f"- **Steps:** {result.get('steps')}",
        f"- **Generated:** {datetime.now(timezone.utc).isoformat()}",
        f"- **Findings:** {s.get('total', 0)} "
        f"(critical={s.get('by_severity', {}).get('critical', 0)}, "
        f"high={s.get('by_severity', {}).get('high', 0)}, "
        f"medium={s.get('by_severity', {}).get('medium', 0)})",
        "",
        "## Findings",
        "",
    ]
    if not findings:
        lines.append("_No findings._")
    for i, f in enumerate(findings, 1):
        lines += [
            f"### {i}. [{f.get('severity', '?').upper()}] {f.get('title')}",
            "",
            f"- **Category:** {f.get('category')} · **Persona:** {f.get('persona')} · **Fingerprint:** `{f.get('fingerprint')}`",
            f"- **URL:** `{f.get('url')}`",
            f"- **Evidence:** {f.get('evidence')}",
            f"- **Repro:**",
        ]
        for step in f.get("repro_steps") or []:
            lines.append(f"  1. {step}")
        lines.append("")
    lines += ["## Visited URLs", ""] + [f"- `{u}`" for u in result.get("visited", [])]
    return "\n".join(lines) + "\n"
