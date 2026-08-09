# The `.wmsoundpack` format

A **sound pack** is a key-press sound with more than one recording in it.

WM Keyboard already installs a single key sound as one audio file (addon type
`sound`). That works, and for a synthesized blip it is the right shape — but it
cannot express what a recording of a real keyboard actually sounds like. A real
board never makes the same noise twice, and a spacebar with stabilisers under it
does not sound like a letter key. A pack exists to carry both of those.

This document is the format's reference. It is written for someone publishing a
pack, not for someone reading the app's source.

---

## The file

A pack is a **ZIP archive** named `*.wmsoundpack`:

```
cherrymx-blue-abs.wmsoundpack
├── pack.json
└── sounds/
    ├── 1.wav
    ├── 2.wav
    └── …
```

Two rules, both enforced on install:

- `pack.json` must be at the archive root.
- Every audio file must be under `sounds/`. A path that is absolute, contains
  `..`, or uses a backslash is rejected — not sanitised, rejected. An archive
  that tries to escape its own directory is not a pack with a typo in it.

## `pack.json`

```json
{
  "format": "wmkeyboard-sound-pack",
  "version": 1,

  "id": "cherrymx-blue-abs",
  "name": "CherryMX Blue ABS",
  "author": "Monkeytype contributors",
  "packVersion": "1.0.0",
  "description": "Cherry MX Blue clickies under ABS keycaps.",

  "gain": 1.0,

  "press": ["sounds/1.wav", "sounds/2.wav", "sounds/3.wav"],
  "release": ["sounds/1-up.wav", "sounds/2-up.wav", "sounds/3-up.wav"],

  "roles": {
    "space":    { "press": ["sounds/space-1.wav"] },
    "enter":    { "press": ["sounds/enter-1.wav"] },
    "delete":   { "press": ["sounds/delete-1.wav"] },
    "modifier": { "press": ["sounds/mod-1.wav"], "gain": 0.8 }
  }
}
```

### Required

| Field     | Type            | Notes |
|-----------|-----------------|-------|
| `format`  | `"wmkeyboard-sound-pack"` | Magic tag. Anything else is refused. |
| `version` | integer         | Format version. Currently `1`. A higher number is refused rather than guessed at. |
| `id`      | string          | `[A-Za-z0-9._-]+`, at most 64 characters. **Frozen once published** — it is how installs are keyed on the device. |
| `name`    | string          | What the user sees in the picker. |
| `press`   | array of string | At least one path. The pack's default key-down recordings. |

### Optional

| Field         | Type   | Default | Notes |
|---------------|--------|---------|-------|
| `author`      | string | `""`    | |
| `packVersion` | semver string | `"1.0.0"` | Independent of the addon entry's `version`; the app shows the addon's. |
| `description` | string | `""`    | |
| `gain`        | number | `1.0`   | Clamped to `0.0…1.0`. See [Gain is attenuation only](#gain-is-attenuation-only). |
| `release`     | array of string | `[]` | Key-**up** recordings, played when the finger lifts. Empty means silence on key-up, which is right for anything that is one event. See [Key-down and key-up](#key-down-and-key-up). |
| `roles`       | object | `{}`    | Per-key-role overrides. See below. |

Unknown top-level fields are ignored, so a later format version can add one
without breaking today's app.

## Roles

A role is *which kind of key was pressed*. There are five:

| Role       | Which keys |
|------------|------------|
| `default`  | Everything not listed below — letters, digits, punctuation, emoji. Not written under `roles`; it is the top-level `press`/`release`. |
| `space`    | The spacebar. |
| `enter`    | Enter / return / the action key. |
| `delete`   | Backspace, including its held repeat and the delete-swipe. |
| `modifier` | Shift, symbols, layout switch, the globe key, and the rest of the non-typing keys. |

Each entry under `roles` takes the same `press`, `release` and `gain` fields as
the top level:

```json
"roles": {
  "space": { "press": ["sounds/space-1.wav", "sounds/space-2.wav"], "gain": 0.9 }
}
```

**A role that is absent falls back to the default**, per field. A pack that
defines only `roles.space.press` still plays its top-level `press` for
everything else and its top-level `gain` for the spacebar. So a pack with no
`roles` at all — every pack in this repository — behaves exactly like a plain
one-sound addon that happens to have variants.

Unknown role names are ignored, not an error. A pack written against a future
version that adds, say, `"emoji"` still installs and still works.

> **Monkeytype has no per-role sounds.** It plays one random variant for every
> key alike, spacebar included, and its `keydown` handler only reads the key
> code to pick a *note* for the six synthesized oscillator sounds. Nothing in
> this repository fills a role slot; the slots exist for people recording their
> own board, where the spacebar genuinely is a different noise.

## Key-down and key-up

A keystroke has two halves and a mechanical keyboard makes a noise at both: the
switch actuating under the finger, and the stem returning when it lifts. `press`
is the first, `release` is the second, and the app plays each at the moment it
happens — hold a key and the second sound waits for you.

Both are optional beyond the rule that `press` must have at least one entry. An
empty `release` means **silence on key-up**, not a fallback to `press`: most
sounds worth typing on — a beep, a pop, an interface click — are one event, and
giving them an invented second one would double every keystroke.

Roles and the split are independent. A role fills `press`, `release`, both or
neither, and each field falls back to the pack's top-level list on its own — so
a `space` role that names only `press` still plays the pack's default key-up.

> **The packs in this repository are cut, not recorded that way.** Monkeytype
> plays one file per key press, so its switch recordings hold both halves in the
> same file, with the return 100-200 ms behind the press. The importer finds the
> boundary and cuts there; `tools/catalogue.py` decides which sets that applies
> to, because a detector cannot tell a key coming back up from the second half
> of a punch. See the README.

If you are recording your own board, record the two halves as separate files
from the start and skip all of that.

## Variants

Every `press` and `release` is a **list**, and the app picks one entry per
keystroke.

The two lists are drawn from **independently** — `press[3]` and `release[3]` are
not a pair, and the app never treats them as one. A pack whose lists are
different lengths is fine.

The pick is uniform random with one rule on top: **the same variant is never
played twice in a row** while the list has more than one entry. Monkeytype picks
uniformly with no such constraint (`randomElementFromArray`), which means about
one keystroke in `1/n` repeats the previous sample — on a 3-variant set that is
a third of them, and a repeat is exactly the thing the variants exist to avoid.
The constraint costs one integer of state per role and is the whole reason a
pack sounds like a keyboard instead of a loop.

Each role tracks its own last-played index, per half, so alternating between the
spacebar and letters never makes either repeat and a long run of key-ups does
not depend on how many letters were typed between them.

### Limits

| Limit | Value | Why |
|-------|-------|-----|
| Audio files per pack | 64 | Every file is decoded into the `SoundPool` when the pack is selected. |
| Variants per list | 32 | |
| Bytes per audio file | 4 MiB | Same ceiling as a single-sound addon. |
| Unzipped bytes per pack | 16 MiB | Checked while extracting, not from the ZIP header, so a zip bomb is stopped mid-stream. |
| Installed packs | 20 | |

Going over any of these refuses the install with a message naming the limit. It
never truncates the pack to fit — a pack quietly missing half its variants is
worse than one that did not install.

## Audio files

Same formats the single-sound importer takes: **WAV, OGG and MP3**, checked by
header, not by extension.

Ship **WAV** unless the pack is large enough for that to hurt. These are 20–150 ms
recordings; the compression saves a few hundred kilobytes and costs the thing
that actually matters:

- MP3 carries encoder delay — the decoder emits a block of silence before the
  first real sample. On a 30 ms click that is a tenth of the sound arriving late,
  on every keystroke.
- WAV decodes to PCM with nothing in front of it.

Mono is enough. `SoundPool` plays both channels of a stereo file at the same
volume anyway, so stereo doubles the size for a difference nobody hears through
a phone speaker.

### Gain is attenuation only

`SoundPool.play` takes a volume in `0.0…1.0` and cannot amplify. `gain` is
therefore a **cut**, never a boost, and is clamped into that range on load.

Normalise loud at build time and use `gain` to pull a role back down — a pack
that ships quiet samples and asks for `"gain": 2.0` gets `1.0` and stays quiet.

The user's own key-sound volume multiplies with this, so a pack at `gain: 0.5`
tops out at half the loudness of one at `1.0` with the slider in the same place.
Use it for balance *within* a pack (a spacebar that recorded hotter than the
letters), not to set the pack's overall level.

## Publishing one

In an addon repository manifest, a pack is type `sound_pack`:

```json
{
  "id": "cherrymx-blue-abs",
  "type": "sound_pack",
  "name": "CherryMX Blue ABS",
  "version": "1.0.0",
  "author": "Monkeytype contributors",
  "description": "Cherry MX Blue clickies under ABS keycaps. Ten recordings.",
  "tags": ["switch", "cherry", "clicky"],
  "path": "packs/cherrymx-blue-abs.wmsoundpack",
  "sha256": "…",
  "sizeBytes": 262144,
  "previews": ["previews/cherrymx-blue-abs.png"],
  "minAppVersion": 5,
  "license": "GPL-3.0-or-later",
  "licenseFile": "LICENSE"
}
```

Notes:

- `minAppVersion` should be **5** or higher. `sound_pack` did not exist before
  that, and an older app reads an unknown type as `unknown` and offers no way to
  install it. Setting the floor turns that into a message that says why.
- The manifest `id` and the `pack.json` `id` do not have to match, and the app
  keys the install on the manifest's. Making them the same is still the sane
  thing to do.
- The addon entry's `version` is what drives update detection. `packVersion`
  inside `pack.json` is informational.

Installing a pack **selects it**, the same as installing a theme or a single
sound: a pack that installs without the keyboard making its noise reads as an
install that did nothing.

## Known gaps

- **No per-key (as opposed to per-role) mapping.** Mechvibes-style packs address
  individual key codes. Roles cover the case that is audible on a phone — the
  spacebar — without asking a publisher to record 104 keys for a keyboard that
  has about 30.
