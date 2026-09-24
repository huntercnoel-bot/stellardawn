# Mac Studio Finder

A small dashboard that checks **Apple Store pickup availability** for the
**M5 Ultra Mac Studio** near major US cities and publishes the results to GitHub Pages
every ~30 minutes.

| Model | Part | How it's checked |
| --- | --- | --- |
| M5 Ultra · 96GB · 1TB (30‑core CPU, 64‑core GPU) | `MHL74LL/A` | Apple Store pickup stock, per store |
| M5 Ultra · 256GB (30‑ or 36‑core, 1TB / 2TB) | read from Apple's page each run | Same check; these look like build‑to‑order configs, so stores may show "Not in stores" |

## How it works

1. `.github/workflows/check-inventory.yml` runs every 30 minutes (and on demand).
2. `scripts/check_inventory.py` reads any missing part numbers from Apple's product
   pages, asks Apple's store‑pickup service which stores near each city in
   `scripts/config.json` have each model in stock, and writes `site/inventory.json`.
   Each model is checked separately, so one failing lookup doesn't hide the others.
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
- **Models / setups:** each model has `variants`. Give a variant its `part` number, or
  just its Apple Store `page` URL and the checker reads the part number from it.

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
