# MissingNo. Yellow

A Game Boy player that runs in Safari on iPhone, plus a ROM patch for
**Pokémon Yellow** that makes your starter a level 99 **MISSINGNO.** that walks
behind you the way Pikachu normally does.

No Nintendo data lives in this folder. You load your own ROM on your phone; the
page checks it is Pokémon Yellow (US/Europe, SHA-1
`cc7d03262ebfaf2f06772c1a480c7d9d5f4a38e1`), applies `patch/missingno.ips`
in the browser, and keeps the ROM and your saves on that device only.

## Files

| File | What it is |
| --- | --- |
| `index.html` | The player page: touch D-pad and buttons, sound, battery saves, quick save/load, save export/import, patched-ROM download. The IPS patch is embedded in it. |
| `gb-core.js` | Grant Galitz's GameBoy-Online core (GPL-2.0, from the `gameboy` npm package), wrapped so it loads with a plain `<script>` tag. |
| `patch/build_patch.py` | Builds the patch from your ROM. Every byte it replaces is checked first. |
| `patch/gbpic.py` | Gen 1 Pokémon picture compressor/decompressor used for the new sprites. |
| `patch/missingno.ips` | The built patch (2.3 KB), usable with any IPS patcher. |

## What the patch changes

- Oak gives you MISSINGNO. (species `$1F`) at **level 99** instead of Pikachu (07:4B40).
- MISSINGNO. gets a real base-stat header. Yellow's accidental one is garbage and
  asks for a 10×13 sprite that overflows the buffer. The new one: 255 in every stat,
  Bird/Normal, **Hyper Beam, Psychic, Blizzard, Earthquake**, every TM and HM
  (GetMonHeader hook at 00:1362, header in bank `$0E`).
- Perfect DVs and all PP Ups for the starter (AddPartyMon hook at 03:7228).
- New glitch front, back and portrait pictures, compressed in Gen 1's own format
  and stored in the empty bank `$3B` (sprite bank selector rewritten at 00:1413).
- The "Rhydon trap" that refuses to draw Pokédex #0 on the summary screen is removed (00:1161).
- Follow-me: Yellow's starter-Pikachu checks (3F:4DC8, 3F:4E28, 3F:50E3) now look for
  MISSINGNO., the walking Pikachu sprite (3F:67EF) is a glitch block, and talking to it
  shows a flickering glitch portrait instead of Pikachu's faces (table at 3F:6572).

Pikachu's recorded voice clips still play when you talk to it.

Rebuild the patch from your own ROM:

```sh
python3 gameboy/patch/build_patch.py "Pokemon Yellow.gbc" gameboy/patch/missingno.ips
base64 -w0 gameboy/patch/missingno.ips   # paste into PATCH_B64 in index.html
```

## Playing on iPhone

1. Open the published page in Safari and tap **LOAD ROM**, then pick your `.gbc` (or a `.zip` holding it).
2. Tap **TAP TO PLAY WITH SOUND**. The game starts with the patch applied.
3. The in-game SAVE is written to the phone automatically. Use **Menu → Export save** now and then as a backup.

Controls: D-pad and A/B on screen, Start/Select pills underneath, hold **FAST** to
run at 4× speed. On a keyboard: arrows, `X` = A, `Z` = B, `Enter` = Start,
`Shift` = Select, hold `Space` for fast.

If you prefer a native app, **Menu → Download patched ROM** gives you a `.zip` you
can import into an emulator such as Delta.
