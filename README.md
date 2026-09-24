# Mac Studio Finder

A small dashboard that checks **Apple Store pickup availability** for the
**M5 Ultra Mac Studio** across ~108 US areas (every state with an Apple Store) and publishes
the results to GitHub Pages about every 5 minutes. The M5 Max 36GB is included as a
reference model that is normally in stock.

| Model | Part | How it's checked |
| --- | --- | --- |
| M5 Ultra · 96GB · 1TB (30‑core CPU, 64‑core GPU) | `MHL74LL/A` | Every area, every run |
| M5 Ultra · 256GB (30‑ or 36‑core, 1TB / 2TB) | `RO_MACSTUDIO_M5MAX_M5ULTRA_BET_BES_2026` + option codes, read from each setup's Apple page (`defaultKit`) | One setup per area, rotating across runs |
| M5 Max · 36GB · 512GB (reference) | `MHL64LL/A` | Every area, every run |

Apple rate-limits its pickup service (HTTP 541), so the areas are split across 3 parallel
runners (each has its own IP and its own share of the limit), and the 256GB setups rotate
across areas. Results for setups or areas not reached in a run carry forward from the
previous run (up to an hour) and are labeled with their age on the page.

## Micro Center and Best Buy

`scripts/check_retailers.py` runs as a separate job, on its own runner:

- **Micro Center:** its site sits behind a Cloudflare challenge that blocks plain HTTP
  clients from cloud servers, so pages load in a real Chromium (Playwright, under xvfb).
  It finds product IDs by searching for the part number (and for "256GB"
  M5 Ultra listings), then reads each of its 31 stores' stock from the product page loaded
  with `?storeid=<id>` (the `.inventoryCnt` element, e.g. "5 NEW IN STOCK").
- **Best Buy:** with a `BESTBUY_API_KEY` repo secret (free at developer.bestbuy.com) it
  uses the official Stores API for per-store pickup; without one it reports the
  bestbuy.com button state (available / sold out) near major cities.

## How it works

1. `.github/workflows/check-inventory.yml` runs three jobs:
   - `apple` (3 parallel shards): `scripts/check_inventory.py --shard i/3`
   - `retailers`: `scripts/check_retailers.py`
   - `publish`: `scripts/merge_inventory.py` combines the shards, then `site/` (the
     dashboard plus fresh JSON) is force-pushed to the `gh-pages` branch.
2. GitHub's `*/5` schedule is unreliable, so the last step (`scripts/next_run.py`) starts the
   next run about 5 minutes after the current one began, unless a run is already queued.
   Set the repository variable `PAUSE_CHECKS` to `1` to stop the chain.
3. `inventory.json` lists each Apple Store once (areas overlap) and areas refer to stores
   by id, which keeps the file about 70% smaller.

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
