# RideLite — planted-bug demo app

A tiny Flask ride-hailing app with **12 deliberately planted bugs**. Phalanx's
agent / heuristic explorer never reads `planted_bugs.json`; that file is the
benchmark's ground truth only.

```bash
# from repo root, with the phalanx venv active
python demo_app/app.py          # http://127.0.0.1:5055
```

Seed accounts: `alice/alice123` (rider), `bob/bob123` (rider),
`dave/dave123` (driver), `root/root123` (admin).
