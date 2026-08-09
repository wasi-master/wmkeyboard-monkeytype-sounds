# Monkeytype Key Sounds for WM Keyboard

[Monkeytype](https://monkeytype.com)'s key sounds, packaged as WM Keyboard
**sound packs** — every recording of each set, one picked at random for each key
press, the way monkeytype plays them, and on the switch packs a second one when
you lift your finger, the way the keyboards they were recorded from do.

Add this repository in **WM Keyboard → Add-ons → Add repository**:

```
https://github.com/wasi-master/wmkeyboard-monkeytype-sounds
```

It also ships pre-added, so there is a good chance it is already there.

## Why a pack and not 26 key sounds

A WM Keyboard key sound used to be one audio file. Monkeytype's are not: a set
like *CherryMX Blue ABS* is **ten separate recordings of the same switch**, and
monkeytype picks one at random on every keystroke. That randomisation is most of
what makes it sound like a keyboard instead of a loop, and flattening a set down
to one representative file would have thrown away the entire point.

So this repository is published as `sound_pack` addons, a format built for
exactly this: many recordings in one file, one chosen per key press, with
optional separate recordings per key role. The format is written up in
[docs/SOUND_PACK_FORMAT.md](docs/SOUND_PACK_FORMAT.md).

Three differences from monkeytype worth knowing:

- **No variant repeats twice in a row.** Monkeytype draws uniformly from the
  whole list, so on a three-recording set about one keystroke in three repeats
  the previous sample. WM Keyboard draws from the other `n - 1`. A repeat is the
  one thing the recordings exist to prevent.
- **Levelling is per set, not per recording.** The loudest recording in a set is
  peaked at -1 dBFS and every other recording in that set is moved by the *same*
  gain. Normalising each one on its own would have made ten switch recordings
  ten identical volumes and made the randomisation inaudible.
- **The switch packs sound on the way up too.** See below.

## Key-down and key-up

A mechanical keyboard makes two noises per key: the switch actuating, and the
stem returning when your finger lifts. Monkeytype's switch recordings hold
both — the return is right there in the same file, 100-200 ms behind the press —
but monkeytype plays one file per key press, so its key-up tick fires on a timer
regardless of when you actually let go. Hold a key and the sound finishes
without you.

WM Keyboard's pack format has a `release` list that plays when the key comes
back up, so the twelve sets whose recordings hold a return are **cut in two** at
import: the press half into `press`, the return into `release`. Hold a key on
those packs and the second click waits for you.

The cut is found rather than assumed. The importer walks each recording forward
from its loudest point, keeping the quietest level it has seen since, and looks
for a later peak that rises 3x out of it — a decaying tail never does that to
itself, so the test means "a second event happened" rather than "it got louder".
The cut lands just before the quietest point between the two.

Which sets get cut is a **human decision** in `tools/catalogue.py`, not the
detector's, because the detector cannot tell a key coming back up from the
second half of a punch. *Fist Fight* trips it on 8 recordings out of 8 and is
marked `WHOLE` for exactly that reason; *Rubber Keys* trips it on 2 of 5, which
is a dome settling inside its own decay rather than a separate event.

Within a set that is cut, a recording with no return in it is **dropped** rather
than kept whole. The app draws from the two lists independently, so a whole
recording left among the press halves would play its own baked-in return *and*
a release sample when you lift — a double tick on some keystrokes and not
others. That costs *Tealios V2* and *Trust GXT* three recordings each.

The preview cards show the result: the divider in each trace is where the
recording was cut.

## Key roles

Monkeytype has no per-key sounds. It plays one random recording for every key
alike, spacebar included — its `keydown` handler reads the key code only to pick
a *note* for the six synthesized sounds, which have no sample files at all.

The pack format does support it: a pack may carry separate recordings for
`space`, `enter`, `delete` and `modifier`, each falling back to the default set
when absent. **Nothing in this repository fills those slots** — there is nothing
upstream to fill them with. They are there for someone recording their own
board, where the spacebar genuinely is a different noise because of the
stabilisers under it. See
[docs/SOUND_PACK_FORMAT.md](docs/SOUND_PACK_FORMAT.md#roles).

Roles and the key-down/key-up split are independent, and a role that fills only
`press` still falls back to the pack's top-level `release`. So a spacebar you
record separately keeps the board's key-up sound for free until you record that
too.


## The 26 packs

145 recordings in total. Click a name for its waveform card.

| Pack | Family | Recordings | Key-up | Size | Id |
| --- | --- | --: | :-: | --: | --- |
| [Click](previews/click.png) | Interface | 3 | — | 6 KiB | `click` |
| [Beep](previews/beep.png) | Interface | 3 | — | 10 KiB | `beep` |
| [Pop](previews/pop.png) | Interface | 3 | — | 11 KiB | `pop` |
| [NK Creams](previews/nk-creams.png) | Mechanical switch | 6 | yes | 61 KiB | `nk-creams` |
| [Typewriter](previews/typewriter.png) | Keyboard | 6 | yes | 110 KiB | `typewriter` |
| [Osu](previews/osu.png) | Game | 3 | — | 28 KiB | `osu` |
| [Hitmarker](previews/hitmarker.png) | Game | 3 | — | 15 KiB | `hitmarker` |
| [Fist Fight](previews/fist-fight.png) | Novelty | 8 | — | 117 KiB | `fist-fight` |
| [Rubber Keys](previews/rubber-keys.png) | Keyboard | 5 | — | 56 KiB | `rubber-keys` |
| [Fart](previews/fart.png) | Novelty | 8 | — | 62 KiB | `fart` |
| [Akko Lavenders](previews/akko-lavenders.png) | Mechanical switch | 10 | yes | 98 KiB | `akko-lavenders` |
| [CherryMX Black ABS](previews/cherrymx-black-abs.png) | Mechanical switch | 9 | yes | 120 KiB | `cherrymx-black-abs` |
| [CherryMX Black PBT](previews/cherrymx-black-pbt.png) | Mechanical switch | 10 | yes | 93 KiB | `cherrymx-black-pbt` |
| [CherryMX Blue ABS](previews/cherrymx-blue-abs.png) | Mechanical switch | 10 | yes | 135 KiB | `cherrymx-blue-abs` |
| [CherryMX Blue PBT](previews/cherrymx-blue-pbt.png) | Mechanical switch | 9 | yes | 126 KiB | `cherrymx-blue-pbt` |
| [CherryMX Brown PBT](previews/cherrymx-brown-pbt.png) | Mechanical switch | 9 | yes | 105 KiB | `cherrymx-brown-pbt` |
| [Kalih Box White](previews/kalih-box-white.png) | Mechanical switch | 10 | yes | 166 KiB | `kalih-box-white` |
| [Razer Green](previews/razer-green.png) | Mechanical switch | 9 | yes | 147 KiB | `razer-green` |
| [Tealios V2](previews/tealios-v2.png) | Mechanical switch | 7 | yes | 87 KiB | `tealios-v2` |
| [Trust GXT](previews/trust-gxt.png) | Keyboard | 7 | yes | 140 KiB | `trust-gxt` |
| [Error: Damage](previews/error-damage.png) | Alert | 1 | — | 5 KiB | `error-damage` |
| [Error: Triangle](previews/error-triangle.png) | Alert | 1 | — | 13 KiB | `error-triangle` |
| [Error: Square](previews/error-square.png) | Alert | 1 | — | 10 KiB | `error-square` |
| [Error: Missed Punch](previews/error-missed-punch.png) | Novelty | 2 | — | 30 KiB | `error-missed-punch` |
| [Fart Reverb](previews/fart-reverb.png) | Novelty | 1 | — | 78 KiB | `fart-reverb` |
| [Time Warning](previews/time-warning.png) | Alert | 1 | — | 76 KiB | `time-warning` |

### Not here

Monkeytype lists 26 click sounds; six of them have no sample files, because
it generates them with the Web Audio API at play time:

| Upstream | Name | How it is made |
| --: | --- | --- |
| 8 | sine | a bare sine oscillator |
| 9 | sawtooth | a bare sawtooth oscillator |
| 10 | square | a bare square oscillator |
| 11 | triangle | a bare triangle oscillator |
| 12 | pentatonic | a note drawn from a pentatonic scale, per keystroke |
| 13 | wholetone | a note drawn from a whole-tone scale, per keystroke |

The last two are not one sound at all — they pick a fresh note from a scale
on every keystroke — so there is nothing a static file could capture. WM
Keyboard has its own synthesized styles (Pop, Thock, Chime) for this niche.

## Building it

Everything in `packs/` and `previews/` is generated. A clean checkout rebuilds
byte for byte.

```bash
python3 tools/import_monkeytype.py      # download, level, pack, index
python3 tools/generate_previews.py      # waveform cards
python3 tools/validate.py               # schema, checksums, and every pack
```

- **`tools/import_monkeytype.py`** pins a monkeytype commit and does the rest
  from it: reads the display names out of `metadata.tsx`, the variant counts out
  of `sounds.ts`, lists the sounds directory from the git tree, downloads each
  `.wav`, trims and levels each set, cuts the key-up half out of the sets that
  have one, and writes deterministic archives. Re-running with no upstream
  change produces identical files with identical checksums. `--ref master` moves
  the pin; `--bump` bumps the patch version of any pack whose bytes changed;
  `--raw` skips levelling and the cut both.
- **`tools/catalogue.py`** is the hand-written half — published id, family, tags,
  description and key-up policy per set. The importer **stops** if upstream
  ships a sound the catalogue does not describe, rather than publishing it as
  "Click 27", and stops again if a set has no `release` policy rather than
  guessing one.
- **`tools/generate_previews.py`** draws the actual waveform of every recording
  in a pack, stacked, on a shared scale, key-down and key-up end to end with a
  divider between them. Amplitude is compressed the way an audio editor's
  logarithmic view does it; `--linear` turns that off.
- **`tools/validate.py`** checks the manifest against the schema, checks every
  checksum, and opens every pack to check it against the limits the app enforces
  — so a pack that would fail on someone's phone fails in CI instead.

`GITHUB_TOKEN` raises the API rate limit. Nothing needs it for a single run.

## Licence

The recordings come from monkeytype, which is **GPL-3.0**, and are redistributed
under the same licence — see [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md). They
have been trimmed, downmixed to mono and levelled; [UPSTREAM.json](UPSTREAM.json)
records the exact commit and the git blob sha of every source file, so what
shipped can be checked against what was imported.

The tooling in `tools/` is GPL-3.0 too, since it is distributed with the sounds.

---

Sounds imported from [monkeytype](https://github.com/monkeytypegame/monkeytype) at commit
[`d7eb4b76f3b3`](https://github.com/monkeytypegame/monkeytype/tree/d7eb4b76f3b3000199022ea52a52365b9346b8d0).
Generated by `tools/gen_readme.py` — edit the prose there, not here.
