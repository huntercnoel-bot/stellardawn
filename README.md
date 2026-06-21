# Stellar Dawn

A small browser space‑trading + combat game — buy low, sell high, take delivery
contracts, fight pirates, upgrade your ship, and climb from Drifter to Tycoon.
It's a single self‑contained HTML file (plus ship sprites), no install needed.

## Play

- **Online:** once GitHub Pages is enabled, play at
  `https://huntercnoel-bot.github.io/stellardawn/`
- **Locally:** just open `index.html` in your browser (double‑click it).

## Controls

| Key | Action |
| --- | --- |
| `W` | thrust |
| `A` / `D` | turn |
| `Space` | fire |
| `E` | dock / undock |
| `M` | map zoom |
| `P` | toggle ambient music |

## How it works

- Start docked at a random home base. Dock at a planet, click the **Trading Post**
  to buy/sell, the **Shipyard** to change ships, **Upgrades** to outfit your ship,
  and **Contracts** to take delivery jobs.
- Planets are **safe zones** — no combat in or out while you're inside the circle.
- **Pirates** hunt you; **traders** are neutral unless you shoot them; shooting
  peaceful ships raises your **wanted level** and brings the police.
- Mine **asteroids** for ore, answer **distress beacons** (reward… or ambush),
  and grow your **net worth** to rank up. Reach 250,000 to become a Trade Baron.
- Progress saves automatically in your browser.

## Files

- `index.html` — the whole game (HTML + JavaScript + Canvas, no libraries)
- `ships/*.png` — ship sprites (drawn in code, not copyrighted)
- `gen_ships.py` — the Python/Pillow script that generates the ship sprites

## Credits

Made by Hunter. Built with plain JavaScript and the HTML5 Canvas.
