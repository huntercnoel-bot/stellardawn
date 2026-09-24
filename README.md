# Mac Studio Finder

A small dashboard that checks **Apple Store pickup availability** for the
**M5 Ultra Mac Studio** near major US cities and publishes the results to GitHub Pages
about every 5 minutes.

| Model | Part | How it's checked |
| --- | --- | --- |
| M5 Ultra · 96GB · 1TB (30‑core CPU, 64‑core GPU) | `MHL74LL/A` | Apple Store pickup stock, per store |
| M5 Ultra · 256GB (30‑ or 36‑core, 1TB / 2TB) | read from Apple's page each run | Same check; these look like build‑to‑order configs, so stores may show "Not in stores" |

## How it works

1. `.github/workflows/check-inventory.yml` runs every 5 minutes (GitHub may delay scheduled runs a little), on pushes to `main`, and on demand.
2. `scripts/check_inventory.py` reads any missing part numbers from Apple's product
   pages, asks Apple's store‑pickup service which stores near each city in
   `scripts/config.json` have each model in stock, and writes `site/inventory.json`.
   Each model is checked separately, so one failing lookup doesn't hide the others.
3. The workflow force-pushes `site/` (the dashboard plus fresh JSON) to the `gh-pages`
   branch, which GitHub Pages serves.

The page groups stores by city, shows stock for each model, and has a search box and an
"in stock only" filter.

## Live page

`https://huntercnoel-bot.github.io/stellardawn/`: served from the `gh-pages` branch, no setup needed.

## Adding cities or models

Edit `scripts/config.json`:

- **Cities:** add `{ "name", "state", "zip" }`. Apple returns the stores near that ZIP, so
  pick one near the city's Apple Store.
- **Models / setups:** each model has `variants`. Give a variant its `part` number, or
  just its Apple Store `page` URL and the checker reads the part number from it.

## Run locally

```sh
pip install curl_cffi
python3 -m unittest discover tests
python3 scripts/check_inventory.py            # add --limit 3 for a quick run
python3 -m http.server -d site                # then open http://localhost:8000
```

Needs Python 3 and `pip install curl_cffi`. Apple's bot protection blocks Python's
built-in HTTP client, so `curl_cffi` sends requests with Chrome's TLS fingerprint, the same
trick other open-source Apple stock trackers use.

## Caveats

- This uses Apple's unofficial store‑pickup endpoint, the same one the Apple Store
  website uses. It can change or rate‑limit without notice; failed cities show an
  error on the page instead of stale data.
- Stock changes fast. Always confirm with the store before driving over.
