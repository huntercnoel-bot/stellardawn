# Mac Studio Finder

A small dashboard that checks **Apple Store pickup availability** for the Mac Studio
near major US cities and publishes the results to GitHub Pages every ~30 minutes.

| Model | Part | How it's checked |
| --- | --- | --- |
| Mac Studio M3 Ultra · 96GB · 1TB | `MU973LL/A` | Apple Store pickup stock, per store |
| Mac Studio M3 Ultra · 256GB | build‑to‑order | Apple stopped offering 256GB in May 2026 and stores never stocked it, so the page links to retailer/refurb searches instead |

## How it works

1. `.github/workflows/check-inventory.yml` runs every 30 minutes (and on demand).
2. `scripts/check_inventory.py` asks Apple's store‑pickup service which stores near
   each city in `scripts/config.json` have each part in stock, and writes
   `site/inventory.json`.
3. The workflow deploys `site/` (the dashboard plus fresh JSON) to GitHub Pages.

The page groups stores by city, shows stock for each model, and has a search box and an
"in stock only" filter.

## Setup

1. In the repo's **Settings → Pages**, set **Source** to **GitHub Actions**.
2. Merge to `main`, or run **Actions → Check inventory → Run workflow**.
3. Open `https://huntercnoel-bot.github.io/stellardawn/`.

## Adding cities or models

Edit `scripts/config.json`:

- **Cities:** add `{ "name", "state", "zip" }`. Apple returns the stores near that ZIP, so
  pick one near the city's Apple Store.
- **Models:** add an entry with a `part` number (e.g. `MU963LL/A`) to track it in stores.
  Leave `part` as `null` for build‑to‑order configs; those show retailer links only.

## Run locally

```sh
python3 -m unittest discover tests
python3 scripts/check_inventory.py            # add --limit 3 for a quick run
python3 -m http.server -d site                # then open http://localhost:8000
```

No dependencies beyond Python 3.

## Caveats

- This uses Apple's unofficial store‑pickup endpoint, the same one the Apple Store
  website uses. It can change or rate‑limit without notice; failed cities show an
  error on the page instead of stale data.
- Stock changes fast. Always confirm with the store before driving over.
