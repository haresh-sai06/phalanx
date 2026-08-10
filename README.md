# Phalanx interactive prototype

Three-screen clickable prototype of the full Phalanx product UI. Not the PoC — this is the aspirational vision (multi-persona swarm, BYOM configuration, live dashboard, rich report). Built as vanilla HTML/CSS/JS so it runs anywhere with no build step.

## Screens

- **[`setup.html`](setup.html)** — Configure a new audit: target URLs, BYOM model tiers (Cloud / Hybrid / On-Prem), persona count, category selection
- **[`dashboard.html`](dashboard.html)** — Live audit view: 4 persona tiles running in parallel, cross-persona sync bar, live bug feed
- **[`report.html`](report.html)** — Full audit report: severity stats, filterable bug list, expandable bug detail with Playwright reproduction scripts

## Run locally

Any static file server:

```bash
cd prototype
python -m http.server 8080
# open http://localhost:8080/setup.html
```

Or just open `setup.html` directly in a browser.

## Deploy to GitHub Pages

Push the `prototype/` folder to any branch, enable GitHub Pages under repo settings pointing at that path. Live URL becomes shareable.
