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
| `S` | brake |
| `A` / `D` | turn |
| `Shift` | boost (burns a recharging meter) |
| `Space` | fire |
| `F` | launch homing missile (once fitted) |
| `E` | dock / undock |
| `M` | map zoom |
| `Enter` | open chat (type a message) |
| `Esc` | pause menu (master volume · log out) |
| `P` | toggle ambient music |

On a phone or tablet, an on-screen **stick** (steer + thrust) and **FIRE / BOOST /
MSL / DOCK / MAP** buttons appear automatically.

## How it works

- Start docked at a random home base. Dock at a planet, click the **Trading Post**
  to buy/sell, the **Shipyard** to change ships, **Upgrades** to outfit your ship,
  and **Contracts** to take delivery jobs. Every station has **its own look** —
  lava flats at Cinder, oceans at Aqua Veil, farms at Verdant, and more.
- Rack up a **kill streak**: 3 kills makes you **MOST WANTED**. Your **bounty rises
  with every kill** and is broadcast to **everyone** (a banner on all screens plus
  a chat callout), hostiles light up your **radar**, and **bases lock you out for a
  minute after each kill** — so you can't just duck into port. Docking (or dying)
  clears your bounty.
- Watch the **Galactic Market News** — random **shortages** (sell high) and
  **gluts** (buy cheap) pop up at stations and last a few visits.
- An on-screen **waypoint arrow** points the way to each active contract, and a
  **targeting reticle** marks the nearest hostile (gold when a missile locks on).
- Open the **map** (`M`) for galactic trade intel: shortage/glut markers and a
  highlight of where your current cargo sells highest.
- The **Captain's Log** at any station tracks your kills, contracts, distance and
  best net worth across sessions.
- Planets are **safe zones** — no combat in or out while you're inside the circle.
- **Pirates** hunt you; **traders** are neutral unless you shoot them; shooting
  peaceful ships raises your **wanted level** and brings the police. Enemies get
  tougher as your net worth grows, so late-game runs stay dangerous. Hostiles
  don't appear on the radar — keep your eyes on the void.
- Once you've built up a real ship, a rare **Pirate Warlord** mini-boss may prowl
  the sector: a huge, spread-firing hull with a top-of-screen health bar and a
  fat bounty. Only one stalks the cluster at a time.
- Mine **asteroids** for ore, answer **distress beacons** (reward… or ambush),
  and grow your **net worth** to rank up. Reach 250,000 to become a Trade Baron.
- Subtle generative **space music** plays as you fly — set the master volume or
  log out from the **Esc** menu, or toggle music with `P`.
- Progress saves automatically in your browser.

## Files

- `index.html` — the whole game (HTML + JavaScript + Canvas, no libraries)
- `ships/*.png` — ship sprites (drawn in code, not copyrighted)
- `gen_ships.py` — the Python/Pillow script that generates the ship sprites

## Credits

Made by Hunter. Built with plain JavaScript and the HTML5 Canvas.
