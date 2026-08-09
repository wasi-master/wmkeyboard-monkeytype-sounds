#!/usr/bin/env python3
"""The hand-written half of the catalogue.

``import_monkeytype.py`` owns everything mechanical — which files exist, how
many variants a set has, checksums, sizes. This module owns the prose: the id
we publish a set under, the family it belongs to, what its description says.
Keeping the two apart is what lets the importer be re-run against a newer
upstream commit without flattening anything a human wrote.

Every upstream id that has sample files must appear in :data:`CLICK_SETS` or
:data:`EXTRA_SETS`, or the importer stops. That is deliberate: monkeytype
adding a 27th switch recording should be a thing somebody notices and writes a
sentence about, not a thing that silently ships as "Click 27".

Every entry also carries a ``release`` policy — see :data:`SPLIT` — for the
same reason.
"""

from __future__ import annotations

# ---------------------------------------------------------------- release policy
#
# Monkeytype plays one file per key press and never touches key-up, so most of
# its switch recordings hold *both* halves of the keystroke: the switch
# actuating, and then the stem returning 100-200 ms later, in the same file. WM
# Keyboard plays those halves at the moments they happen, so a set recorded
# that way is cut in two at import.
#
# The decision is per set and written down here rather than left to the
# detector, because the detector cannot tell a key coming back up from a second
# punch in a fight sample — both are "a transient after the first one". What it
# can do is find the boundary once a human has said there is one.
#
#   SPLIT  cut each recording into a key-down and a key-up half.
#   WHOLE  play the file as recorded on key-down; nothing on key-up.
#
# Numbers in the comments below are from the detector: how many of the set's
# recordings hold a second transient, out of how many there are.
SPLIT = "split"
WHOLE = "whole"

# Families group the catalogue and pick the preview card's accent colour.
# ``badge`` is the small capitalised line above the title on the preview.
FAMILIES = {
    "switch": {
        "label": "Mechanical switch",
        "badge": "MECHANICAL SWITCH",
        "accent": (56, 189, 248),      # sky
        "accent_dim": (14, 116, 144),
    },
    "board": {
        "label": "Keyboard",
        "badge": "KEYBOARD",
        "accent": (34, 197, 94),       # green
        "accent_dim": (21, 128, 61),
    },
    "ui": {
        "label": "Interface",
        "badge": "INTERFACE",
        "accent": (168, 85, 247),      # violet
        "accent_dim": (107, 33, 168),
    },
    "game": {
        "label": "Game",
        "badge": "GAME",
        "accent": (249, 115, 22),      # orange
        "accent_dim": (154, 52, 18),
    },
    "novelty": {
        "label": "Novelty",
        "badge": "NOVELTY",
        "accent": (236, 72, 153),      # pink
        "accent_dim": (157, 23, 77),
    },
    "alert": {
        "label": "Alert",
        "badge": "ALERT",
        "accent": (239, 68, 68),       # red
        "accent_dim": (153, 27, 27),
    },
}

# Upstream click-sound ids that ship sample files, keyed by the number in
# `frontend/static/sounds/click<N>`. `name` is monkeytype's own displayString
# from metadata.tsx, re-cased for a title; renaming one of these is a rename
# users would have to relearn, so the words stay upstream's.
#
# `id` is the published addon id and is FROZEN once released — the install key
# in the app is "<repoId>/<addonId>", so changing one orphans every install.
CLICK_SETS = {
    1: {
        "id": "click",
        "name": "Click",
        "family": "ui",
        "release": WHOLE,
        "tags": ["click", "crisp", "default"],
        "description": (
            "Monkeytype's default: a dry, very short interface click with no "
            "body under it. The quietest thing in the pack and the easiest to "
            "type on for hours."
        ),
    },
    2: {
        "id": "beep",
        "name": "Beep",
        "family": "ui",
        "release": WHOLE,
        "tags": ["beep", "digital", "sharp"],
        "description": (
            "A short digital beep — a pitched tone rather than a physical "
            "impact. Cuts through a noisy room where the click disappears."
        ),
    },
    3: {
        "id": "pop",
        "name": "Pop",
        "family": "ui",
        "release": WHOLE,
        "tags": ["pop", "soft", "bubble"],
        "description": (
            "A soft bubble pop: a low blip with a quick downward bend and "
            "almost no attack. Rounded where Click is dry."
        ),
    },
    4: {
        "id": "nk-creams",
        "name": "NK Creams",
        "family": "switch",
        "release": SPLIT,  # 6/6 recordings hold the key-up
        "tags": ["switch", "creams", "linear", "deep"],
        "description": (
            "Novelkeys Cream linears: the deep, hollow POM sound those "
            "switches are bought for. Six recordings, so the same key never "
            "sounds identical twice, each with its own key-up thock."
        ),
    },
    5: {
        "id": "typewriter",
        "name": "Typewriter",
        "family": "board",
        "release": SPLIT,  # 6/6 recordings hold the key-up
        "tags": ["typewriter", "vintage", "mechanical"],
        "description": (
            "A real typebar striking the platen, with the carriage rattle "
            "left in. Six recordings — the variation is most of the effect — "
            "and the typebar falling back is its own sound on key-up."
        ),
    },
    6: {
        "id": "osu",
        "name": "Osu",
        "family": "game",
        "release": WHOLE,
        "tags": ["game", "rhythm", "hit"],
        "description": (
            "The hitsound from osu!: a bright, percussive tap with a metallic "
            "edge. Reads as a score rather than a keystroke."
        ),
    },
    7: {
        "id": "hitmarker",
        "name": "Hitmarker",
        "family": "game",
        "release": WHOLE,
        "tags": ["game", "hitmarker", "shooter"],
        "description": (
            "The shooter hitmarker tick — a tight, high, unmistakably "
            "digital confirmation. Every letter is a headshot."
        ),
    },
    14: {
        "id": "fist-fight",
        "name": "Fist Fight",
        "family": "novelty",
        # 8/8 hold a second transient and none of them is a key coming back
        # up — it is the second half of a punch. Exactly the case the detector
        # cannot judge on its own.
        "release": WHOLE,
        "tags": ["punch", "impact", "novelty"],
        "description": (
            "Body-blow impacts from a fight scene, eight of them. Typing a "
            "paragraph sounds like losing one."
        ),
    },
    15: {
        "id": "rubber-keys",
        "name": "Rubber Keys",
        "family": "board",
        # Only 2/5 show one. A dome returning is a soft thud inside the press's
        # own decay rather than an event after it, and splitting a set where
        # three recordings in five have nothing to give would make the key-up
        # fire on some keystrokes and not others.
        "release": WHOLE,
        "tags": ["membrane", "rubber", "muted", "quiet"],
        "description": (
            "A rubber-dome membrane board: dull, short and almost entirely "
            "without a click. The closest thing here to a laptop keyboard."
        ),
    },
    16: {
        "id": "fart",
        "name": "Fart",
        "family": "novelty",
        # 6/8 trip the detector. They are not key-ups.
        "release": WHOLE,
        "tags": ["novelty", "joke", "meme"],
        "description": (
            "Eight of them. There is no defending this one; monkeytype ships "
            "it, so it is here."
        ),
    },
    17: {
        "id": "akko-lavenders",
        "name": "Akko Lavenders",
        "family": "switch",
        "release": SPLIT,  # 10/10 recordings hold the key-up
        "tags": ["switch", "akko", "linear", "smooth"],
        "description": (
            "Akko Lavender linears: smooth, mid-pitched and even, with none "
            "of the tick a tactile leaves behind. Ten recordings, and a key-up "
            "for every one of them."
        ),
    },
    18: {
        "id": "cherrymx-black-abs",
        "name": "CherryMX Black ABS",
        "family": "switch",
        "release": SPLIT,  # 9/10 recordings hold the key-up
        "tags": ["switch", "cherry", "linear", "abs"],
        "description": (
            "Cherry MX Black linears under ABS keycaps — heavier and blunter "
            "than the PBT cut, with more plastic ring on top. Nine recordings, "
            "each with the stem returning as a separate key-up sound."
        ),
    },
    19: {
        "id": "cherrymx-black-pbt",
        "name": "CherryMX Black PBT",
        "family": "switch",
        "release": SPLIT,  # 10/10 recordings hold the key-up
        "tags": ["switch", "cherry", "linear", "pbt"],
        "description": (
            "Cherry MX Black linears under PBT keycaps: the same switch as "
            "the ABS set, drier and a touch lower. Ten recordings, each split "
            "into the press and the return."
        ),
    },
    20: {
        "id": "cherrymx-blue-abs",
        "name": "CherryMX Blue ABS",
        "family": "switch",
        "release": SPLIT,  # 10/10 recordings hold the key-up
        "tags": ["switch", "cherry", "clicky", "abs"],
        "description": (
            "Cherry MX Blue clickies under ABS keycaps — the click jacket's "
            "sharp double tick, the sound most people picture when they hear "
            "\"mechanical keyboard\". Ten recordings, and the second tick "
            "lands when you lift, not on a timer."
        ),
    },
    21: {
        "id": "cherrymx-blue-pbt",
        "name": "CherryMX Blue PBT",
        "family": "switch",
        "release": SPLIT,  # 9/10 recordings hold the key-up
        "tags": ["switch", "cherry", "clicky", "pbt"],
        "description": (
            "Cherry MX Blue clickies under PBT keycaps: the same click with "
            "a denser, less hollow tail. Nine recordings, and the click bar "
            "ticks again on the way up."
        ),
    },
    22: {
        "id": "cherrymx-brown-pbt",
        "name": "CherryMX Brown PBT",
        "family": "switch",
        "release": SPLIT,  # 9/10 recordings hold the key-up
        "tags": ["switch", "cherry", "tactile", "pbt"],
        "description": (
            "Cherry MX Brown tactiles under PBT keycaps — a small bump and a "
            "quiet, restrained sound. The office-safe Cherry. Nine recordings, "
            "with a soft key-up to match."
        ),
    },
    23: {
        "id": "kalih-box-white",
        "name": "Kalih Box White",
        "family": "switch",
        "release": SPLIT,  # 10/10 recordings hold the key-up
        "tags": ["switch", "kailh", "clicky", "box"],
        "description": (
            "Kailh Box White clickies: a click bar rather than a jacket, so "
            "the tick is higher, tighter and repeats identically on release — "
            "which here really is on release. Ten recordings. (Upstream "
            "spells it \"Kalih\"; kept as published.)"
        ),
    },
    24: {
        "id": "razer-green",
        "name": "Razer Green",
        "family": "switch",
        "release": SPLIT,  # 9/10 recordings hold the key-up
        "tags": ["switch", "razer", "clicky", "gaming"],
        "description": (
            "Razer Greens: a loud, bright, deliberately gamer-facing click "
            "with more high end than the Cherry Blues. Nine recordings, and "
            "the loudest key-up in the catalogue."
        ),
    },
    25: {
        "id": "tealios-v2",
        "name": "Tealios V2",
        "family": "switch",
        "release": SPLIT,  # 7/10 recordings hold the key-up
        "tags": ["switch", "tealios", "linear", "premium"],
        "description": (
            "Tealios V2 linears: the smooth, glassy, slightly high-pitched "
            "sound that made them the enthusiast default. Seven recordings, "
            "each cut into the press and the stem coming back up."
        ),
    },
    26: {
        "id": "trust-gxt",
        "name": "Trust GXT",
        "family": "board",
        "release": SPLIT,  # 7/10 recordings hold the key-up
        "tags": ["board", "budget", "clicky"],
        "description": (
            "A Trust GXT budget mechanical board — rattly, hollow and "
            "cheerfully unrefined. Seven recordings, and it rattles on the "
            "way up as much as on the way down."
        ),
    },
}

# Sounds that live outside the click catalogue: the four error sounds, and the
# two loose files at the root of the sounds directory. Keyed by their path
# under `frontend/static/sounds` (a directory for the error sets, a file for
# the loose two).
EXTRA_SETS = {
    "error1": {
        "id": "error-damage",
        "name": "Error: Damage",
        "family": "alert",
        "release": WHOLE,
        "tags": ["error", "damage", "alert"],
        "description": (
            "Monkeytype's \"damage\" mistype sound: a short, dull hit. Meant "
            "for a wrong keystroke, so it is unforgiving as a key sound — "
            "which is the point if you want one."
        ),
    },
    "error2": {
        "id": "error-triangle",
        "name": "Error: Triangle",
        "family": "alert",
        "release": WHOLE,
        "tags": ["error", "tone", "alert"],
        "description": (
            "A falling triangle-wave tone. Pitched rather than percussive, "
            "so it reads as a buzzer more than an impact."
        ),
    },
    "error3": {
        "id": "error-square",
        "name": "Error: Square",
        "family": "alert",
        "release": WHOLE,
        "tags": ["error", "tone", "8-bit", "alert"],
        "description": (
            "A falling square-wave tone: the same shape as the triangle "
            "error with the harsh 8-bit edge left on."
        ),
    },
    "error4": {
        "id": "error-missed-punch",
        "name": "Error: Missed Punch",
        "family": "novelty",
        "release": WHOLE,
        "tags": ["error", "whoosh", "novelty"],
        "description": (
            "A punch thrown and missed — a whoosh with no impact at the end. "
            "Two recordings."
        ),
    },
    "fart-reverb.wav": {
        "id": "fart-reverb",
        "name": "Fart Reverb",
        "family": "novelty",
        # The detector finds a bump 350 ms in; it is the reverb tail blooming,
        # and the whole point of the sound.
        "release": WHOLE,
        "tags": ["novelty", "joke", "reverb"],
        "description": (
            "The single reverb-tailed one monkeytype keeps outside the click "
            "sets. Long for a key sound; try it on the spacebar role only."
        ),
    },
    "timeWarning.wav": {
        "id": "time-warning",
        "name": "Time Warning",
        "family": "alert",
        # It is a two-note chime; the second note is a second onset a whole
        # second later, and cutting there would leave half a chime per key.
        "release": WHOLE,
        "tags": ["alert", "chime", "warning"],
        "description": (
            "The chime monkeytype plays as a timed test runs out. A clean "
            "bell rather than a click — pleasant on the enter key."
        ),
    },
}

# Upstream ids with no sample files: monkeytype synthesizes these with the Web
# Audio API at play time, either as a bare oscillator or as a note picked from
# a scale, so there is nothing to import. Listed so the importer can say so
# out loud instead of quietly skipping them, and so the README can explain the
# gap between "26 sounds on monkeytype" and what ships here.
SYNTHESIZED = {
    8: ("sine", "a bare sine oscillator"),
    9: ("sawtooth", "a bare sawtooth oscillator"),
    10: ("square", "a bare square oscillator"),
    11: ("triangle", "a bare triangle oscillator"),
    12: ("pentatonic", "a note drawn from a pentatonic scale, per keystroke"),
    13: ("wholetone", "a note drawn from a whole-tone scale, per keystroke"),
}

# Roles a pack can address. Monkeytype has none of this — it plays one random
# variant for every key alike — so nothing here is imported. It exists because
# the WM Keyboard pack format supports it and a publisher recording their own
# board should know the slots are there. See docs/SOUND_PACK_FORMAT.md.
#
# Roles and the press/key-up split are independent: a pack may fill either, both
# or neither, and a role that names only `press` still falls back to the pack's
# top-level `release`.
ROLES = ("default", "space", "enter", "delete", "modifier")
