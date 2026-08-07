# Notices and attribution

## The recordings

Every audio sample in `packs/` comes from
[monkeytypegame/monkeytype](https://github.com/monkeytypegame/monkeytype), from
`frontend/static/sounds`, at the commit recorded in
[UPSTREAM.json](UPSTREAM.json).

Monkeytype is licensed **GPL-3.0**. These packs are a derivative work and are
redistributed under **GPL-3.0-or-later**; the full text is in [LICENSE](LICENSE).

### What was changed

The samples are not shipped byte-identical. `tools/import_monkeytype.py` applies
the following to every set, and nothing else:

| Change | Detail |
| --- | --- |
| Downmix | Stereo sources are averaged to mono. `SoundPool` plays both channels at one volume, so stereo doubled the size for no audible difference on a phone. |
| Trim | Leading and trailing samples below -60 dB relative to the *set's* peak are dropped, keeping 1 ms of pre-roll ahead of the attack. |
| Fade | 0.4 ms in, 4 ms out, so a hard cut does not leave a DC step that clicks on its own. |
| Level | One gain per **set**, putting the loudest recording in it at -1 dBFS. Per-recording normalisation was deliberately not used — it would flatten the differences between variants. |
| Container | Re-encoded as 16-bit mono PCM WAV at the source sample rate. No lossy step, and no resampling. |

Nothing is cut from the middle, no sample is reordered, and no set loses a
recording. `tools/import_monkeytype.py --raw` skips the trim and the levelling
and imports the samples untouched, if you want to hear the difference.

`UPSTREAM.json` stores the git blob sha of every source file, so any pack can be
traced back to the exact bytes it came from.

### Sound provenance upstream

Monkeytype's sound directory collects recordings from several places — switch
recordings, game sounds, and effects — and upstream does not carry a per-file
attribution list. The whole repository is GPL-3.0, which is the licence claimed
here. If you are the author of one of these recordings and want it credited
differently or removed, open an issue.

## The names

Pack names are monkeytype's own `displayString` values from
`frontend/src/ts/config/metadata.tsx`, re-cased for a title and otherwise
unchanged — including "Kalih Box White", which upstream spells that way for what
is sold as a Kailh Box White. Keeping upstream's spelling means someone who
knows the sound from monkeytype can find it here.

## The fonts

`tools/fonts/` holds two typefaces used only to render the preview cards. They
are not shipped inside any pack and never reach a device.

- **Inter** — SIL Open Font License 1.1
- **JetBrains Mono** — SIL Open Font License 1.1

## Not affiliated

This is an unofficial repository. It is not affiliated with, endorsed by, or
supported by monkeytype or its contributors.
