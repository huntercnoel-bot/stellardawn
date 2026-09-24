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

Apple rate-limits its pickup service (HTTP 541), so the areas are split across 4 parallel
runners (each has its own IP and its own share of the limit), and the 256GB setups rotate
across areas. If Apple still limits a runner, that runner stops at once and its unreached
areas keep their previous results (labeled with their age on the page); the least recently
checked areas go first next run.

## Micro Center and Best Buy

`scripts/check_retailers.py` runs as a separate job, on its own runner:

- **Micro Center:** its Cloudflare challenge blocks cloud servers, even a real browser, so
  the automatic check is off by default (`MICROCENTER=1` turns it on, e.g. when running on
  a home machine). The page links to Micro Center's search for each model.
- **Best Buy:** add a `BESTBUY_API_KEY` repository secret (free at developer.bestbuy.com)
  and the official Stores API reports per-store pickup for SKUs 6566930 (96GB) and
  6566932 (M5 Max). Best Buy's old no-key endpoint is gone.

## How it works

1. `.github/workflows/check-inventory.yml` runs three jobs:
   - `apple` (4 parallel shards): `scripts/check_inventory.py --shard i/4`
   - `retailers`: `scripts/check_retailers.py`
   - `publish`: `scripts/merge_inventory.py` combines the shards, then `site/` (the
     dashboard plus fresh JSON) is force-pushed to the `gh-pages` branch.
2. GitHub's `*/5` schedule is unreliable, so the last step (`scripts/next_run.py`) starts the
   next run about 5 minutes after the current one began, unless a run is already queued.
   Set the repository variable `PAUSE_CHECKS` to `1` to stop the chain.
3. The publish step also tracks stock history (`scripts/history.py`): each store's
   availability gets `last_seen`, `in_since` and `last_restock`, and `history.json` keeps
   14 days of restock / sell-out events, which the page shows as "Recent restocks" and
   as "last in stock" per city and store.
4. `inventory.json` lists each Apple Store once (areas overlap) and areas refer to stores
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
