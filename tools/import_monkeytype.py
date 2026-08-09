#!/usr/bin/env python3
"""Build this repository's sound packs from monkeytype's sources.

Everything here is derived. Nothing in `packs/` is edited by hand, and running
this script from a clean checkout reproduces it byte for byte:

1.  Resolve a ref to a commit sha and **pin it**. Every later fetch names that
    sha, so a run is a snapshot of one commit rather than of whenever it ran.
2.  Read `frontend/src/ts/config/metadata.tsx` for the display names and
    `frontend/src/ts/constants/sounds.ts` for the variant counts.
3.  List `frontend/static/sounds` from the git tree at that sha.
4.  Download each `.wav`, cross-checking the count against `sounds.ts`.
5.  Normalise the set (see `process_set`), cut the key-up half out of each
    recording where the catalogue says there is one (`split_set`), and write a
    `.wmsoundpack`.
6.  Merge mechanical fields into `wmkeyboard-repo.json`, leaving prose alone.
7.  Write `UPSTREAM.json` — the pin, and a blob sha per source file.

Usage:

    python3 tools/import_monkeytype.py                  # re-run at the pinned commit
    python3 tools/import_monkeytype.py --ref master     # move the pin to master
    python3 tools/import_monkeytype.py --only click,typewriter
    python3 tools/import_monkeytype.py --bump           # bump patch on changed packs
    python3 tools/import_monkeytype.py --raw            # no trim, no normalise

Set `GITHUB_TOKEN` to raise the API rate limit. The script works without it;
sixty requests an hour is enough for one full run.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import io
import json
import os
import re
import struct
import sys
import wave
import zipfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from catalogue import CLICK_SETS, EXTRA_SETS, SPLIT, SYNTHESIZED, WHOLE  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PACKS = ROOT / "packs"
MANIFEST = ROOT / "wmkeyboard-repo.json"
UPSTREAM = ROOT / "UPSTREAM.json"

OWNER = "monkeytypegame"
REPO = "monkeytype"
SOUNDS_DIR = "frontend/static/sounds"
METADATA_PATH = "frontend/src/ts/config/metadata.tsx"
SOUNDS_TS_PATH = "frontend/src/ts/constants/sounds.ts"

# The addon-repository entry fields this script owns. Everything else in an
# entry — anything a human might have hand-edited — is left exactly as found.
#
# The app versionCode that first understands `sound_pack`. An older app reads
# an unknown type as `unknown` and offers no way to install it, so the floor
# turns that into a message saying why. Raise it in step with the app's
# versionCode if the build that ships sound packs bumps its own.
MIN_APP_VERSION = 4
LICENSE_ID = "GPL-3.0-or-later"
LICENSE_FILE = "LICENSE"

# --- audio processing -------------------------------------------------------
#
# Peak the loudest variant of a set at -1 dBFS. Deliberately NOT -0 dBFS: a
# sample that touches full scale can clip on resample inside the mixer.
TARGET_PEAK_DBFS = -1.0
# Silence floor for trimming, relative to the set's peak. Recordings of real
# switches have a noise floor well under this; -60 dB keeps the noise that is
# part of the sound and drops the leader before the strike.
TRIM_FLOOR_DB = -60.0
# Room left in front of the first audible sample, so the attack transient is
# never clipped by the trim itself.
PRE_ROLL_MS = 1.0
# Fades at both ends. The in-fade is short enough to be inaudible on a click
# and long enough to kill the DC step a hard cut leaves; the out-fade stops the
# tail ending on a non-zero sample, which is a click of its own.
FADE_IN_MS = 0.4
FADE_OUT_MS = 4.0

# --- the key-up split ---------------------------------------------------------
#
# A switch recording holds two events: the stem going down, and the stem coming
# back up 100-200 ms later at a fraction of the level. Monkeytype plays the
# whole file on key-down, so its key-up tick fires on a timer. WM Keyboard has a
# key-up slot, so a set the catalogue marks `SPLIT` is cut in two and each half
# plays when it actually happens.
#
# The cut is found, not assumed: a fixed 100 ms would land mid-decay on a set
# recorded a little slower and clip the release's attack on one recorded faster.
#
# How far past the press's peak the second event must be. Under this and it is
# the press's own body — a clicky switch's jacket tick sits ~5 ms behind the
# strike and belongs to the key going down.
SPLIT_MIN_GAP_MS = 20.0
# How loud it must be, against the press's peak. A real key-up is 7-50% of the
# press on these sets; 5% is under all of them and still well clear of the
# noise floor.
SPLIT_MIN_LEVEL = 0.05
# And how far it must rise out of the decay it interrupts. This is the test
# that separates "a second event" from "a bump on the way down": 3x is about
# +9.5 dB, which no exponential tail does to itself.
SPLIT_MIN_RISE = 3.0
# Window the envelope is smoothed over before any of the above is measured.
# Wide enough that one stray sample is not a peak, narrow enough to keep a
# 5 ms tick.
SPLIT_ENVELOPE_MS = 4.0
# The cut lands this far before the quietest point between the two events, so
# the press's fade-out and the key-up's fade-in both happen in near-silence
# rather than across either transient.
SPLIT_BACKOFF_MS = 2.0
# A key-up shorter than this is a click artefact, not a recording.
SPLIT_MIN_RELEASE_MS = 15.0
# Below this share of a set yielding a key-up, the split is refused for the
# whole set: a pack whose release fires on some keystrokes and not others reads
# as broken rather than as varied.
SPLIT_MIN_COVERAGE = 0.6


# ---------------------------------------------------------------- http

def _get(url: str, accept: str = "application/vnd.github+json") -> bytes:
    request = Request(url, headers={"Accept": accept, "User-Agent": "wmkeyboard-monkeytype-sounds"})
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urlopen(request) as response:
            return response.read()
    except HTTPError as error:
        if error.code == 403 and "rate limit" in error.read().decode("utf-8", "replace").lower():
            raise SystemExit(
                "error: GitHub rate limit hit. Set GITHUB_TOKEN and re-run.",
            ) from error
        raise SystemExit(f"error: {url} -> HTTP {error.code}") from error


def api(path: str) -> dict | list:
    return json.loads(_get(f"https://api.github.com/{path}"))


def raw(sha: str, path: str) -> bytes:
    return _get(
        f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{sha}/{path}",
        accept="*/*",
    )


# ---------------------------------------------------------------- upstream parsing

def resolve_ref(ref: str) -> str:
    """A ref (branch, tag or sha) to the commit sha it points at."""
    if re.fullmatch(r"[0-9a-f]{40}", ref):
        return ref
    commit = api(f"repos/{OWNER}/{REPO}/commits/{ref}")
    return commit["sha"]


def _balanced_block(text: str, start: int) -> str:
    """The `{ … }` starting at the first brace at or after `start`.

    A brace counter rather than a regex: these blocks nest, and the naive
    `\\{.*?\\}` stops at the first inner close.
    """
    open_at = text.index("{", start)
    depth = 0
    for index in range(open_at, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[open_at:index + 1]
    raise ValueError("unbalanced block")


def parse_display_names(metadata_tsx: str, key: str) -> dict[str, str]:
    """`{"1": "click", "2": "beep", …}` for one `optionsMetadata` block."""
    at = metadata_tsx.index(f"{key}: {{")
    options_at = metadata_tsx.index("optionsMetadata:", at)
    block = _balanced_block(metadata_tsx, options_at)
    return dict(re.findall(r'"(\d+)":\s*\{\s*displayString:\s*"([^"]+)"', block))


def parse_variant_counts(sounds_ts: str) -> tuple[dict[int, int], set[int]]:
    """`{id: numberOfSounds}` and the set of ids monkeytype synthesizes."""
    block = _balanced_block(sounds_ts, sounds_ts.index("export const soundsConfig"))
    counts = {
        int(k): int(v)
        for k, v in re.findall(r"(\d+):\s*\{\s*numberOfSounds:\s*(\d+)", block)
    }
    synth = {
        int(k)
        for k in re.findall(r"(\d+):\s*\{\s*(?:oscillatorType|validNotes)", block)
    }
    return counts, synth


def list_sound_files(sha: str) -> dict[str, str]:
    """Every file under the sounds directory at `sha`, path -> blob sha."""
    tree = api(f"repos/{OWNER}/{REPO}/git/trees/{sha}?recursive=1")
    if tree.get("truncated"):
        raise SystemExit("error: the git tree came back truncated; cannot trust the listing")
    prefix = SOUNDS_DIR + "/"
    return {
        node["path"][len(prefix):]: node["sha"]
        for node in tree["tree"]
        if node["type"] == "blob" and node["path"].startswith(prefix)
    }


# ---------------------------------------------------------------- audio

def read_wav(data: bytes) -> tuple[np.ndarray, int]:
    """A WAV's samples as float64 in -1…1, mono, plus its sample rate.

    `audioop` would have done the width conversion, but it was removed in
    Python 3.13, so the four PCM widths are unpacked by hand.
    """
    with wave.open(io.BytesIO(data), "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())

    if width == 1:
        # 8-bit PCM is unsigned, offset by 128; every other width is signed.
        samples = (np.frombuffer(frames, dtype=np.uint8).astype(np.float64) - 128.0) / 128.0
    elif width == 2:
        samples = np.frombuffer(frames, dtype="<i2").astype(np.float64) / 32768.0
    elif width == 3:
        packed = np.frombuffer(frames, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        raw24 = packed[:, 0] | (packed[:, 1] << 8) | (packed[:, 2] << 16)
        raw24 = np.where(raw24 & 0x800000, raw24 - 0x1000000, raw24)
        samples = raw24.astype(np.float64) / 8388608.0
    elif width == 4:
        samples = np.frombuffer(frames, dtype="<i4").astype(np.float64) / 2147483648.0
    else:
        raise ValueError(f"unsupported sample width: {width} bytes")

    if channels > 1:
        # Downmix rather than take the left channel: a switch recorded with a
        # stereo pair has real level differences between the two, and dropping
        # one makes some variants quieter than others for no reason.
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples, rate


def write_wav(samples: np.ndarray, rate: int) -> bytes:
    """16-bit mono PCM WAV bytes. Rounds rather than truncates toward zero."""
    clipped = np.clip(samples, -1.0, 1.0)
    pcm = np.round(clipped * 32767.0).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm.tobytes())
    return buffer.getvalue()


def fade_in(samples: np.ndarray, rate: int) -> None:
    """Kill the DC step a hard cut leaves at the head. Edits in place."""
    n = min(int(rate * FADE_IN_MS / 1000.0), samples.size)
    if n > 1:
        samples[:n] *= np.linspace(0.0, 1.0, n)


def fade_out(samples: np.ndarray, rate: int) -> None:
    """Stop the tail landing on a non-zero sample, which is a click of its own."""
    n = min(int(rate * FADE_OUT_MS / 1000.0), samples.size)
    if n > 1:
        samples[-n:] *= np.linspace(1.0, 0.0, n)


def trim(samples: np.ndarray, rate: int, floor: float) -> np.ndarray:
    """Drop the leader before the first audible sample and the silence after."""
    audible = np.flatnonzero(np.abs(samples) >= floor)
    if not audible.size:
        return samples
    pre_roll = int(rate * PRE_ROLL_MS / 1000.0)
    start = max(0, int(audible[0]) - pre_roll)
    end = min(samples.size, int(audible[-1]) + 1)
    return samples[start:end]


def process_set(
    variants: list[tuple[str, bytes]],
    raw_mode: bool,
) -> list[tuple[str, np.ndarray, int]]:
    """Trim, fade and level a whole set of variants together.

    The levelling is the part worth being careful about: **one gain for the
    whole set**, computed from the loudest variant. Normalising each variant on
    its own would flatten exactly the differences the variants exist to create —
    a set of ten switch recordings would come out ten identical volumes, and the
    randomisation would stop being audible.

    The same reasoning is why this returns samples rather than WAV bytes:
    :func:`split_set` runs after it and has to cut *levelled* audio, so that a
    key-up stays as much quieter than its key-down as it was in the room.
    """
    decoded = [(name, *read_wav(data)) for name, data in variants]

    if raw_mode:
        return decoded

    peak = max((float(np.max(np.abs(s))) for _, s, _ in decoded), default=0.0)
    if peak <= 0.0:
        raise ValueError("every variant is silent")

    floor = peak * (10.0 ** (TRIM_FLOOR_DB / 20.0))
    gain = (10.0 ** (TARGET_PEAK_DBFS / 20.0)) / peak

    out: list[tuple[str, np.ndarray, int]] = []
    for name, samples, rate in decoded:
        samples = trim(samples, rate, floor) * gain
        fade_in(samples, rate)
        fade_out(samples, rate)
        out.append((name, samples, rate))
    return out


def release_policy(meta: dict) -> str:
    """A set's `release` policy, refusing to guess one it does not have.

    Deliberately not defaulted. Whether a recording holds the key coming back
    up is a thing somebody has to listen for, and a set that silently defaulted
    to WHOLE would ship half a keyboard with nothing to say it had.
    """
    policy = meta.get("release")
    if policy in (SPLIT, WHOLE):
        return policy
    raise SystemExit(
        f"error: {meta['id']} has no 'release' policy in tools/catalogue.py. "
        f"Set it to SPLIT (the recordings hold the key coming back up) or "
        f"WHOLE (they do not) and re-run.",
    )


def envelope(samples: np.ndarray, rate: int) -> np.ndarray:
    """Rectified and smoothed, the shape the eye sees in an editor."""
    width = max(1, int(rate * SPLIT_ENVELOPE_MS / 1000.0))
    return np.convolve(np.abs(samples), np.ones(width) / width, mode="same")


def find_key_up(samples: np.ndarray, rate: int) -> int | None:
    """Where the key coming back up begins, or None if nothing does.

    Walks forward from the press's peak keeping a running minimum — the
    quietest the recording has been since the strike — and looks for a later
    local maximum that rises :data:`SPLIT_MIN_RISE` times out of it. A decaying
    tail never does that to itself, which is what makes the test mean "a second
    event happened" rather than "it got louder for a moment".

    The returned index is just before the quietest point between the two, not
    at the second peak: the key-up needs its own attack, and the attack is the
    part between them.
    """
    env = envelope(samples, rate)
    peak_at = int(np.argmax(env))
    top = float(env[peak_at])
    gap = int(rate * SPLIT_MIN_GAP_MS / 1000.0)
    tail = env[peak_at:]
    if top <= 0.0 or tail.size <= gap + 2:
        return None

    # Guarded against a zero floor, so the rise ratio stays finite in digital
    # silence — an upstream file padded with exact zeros would otherwise make
    # every later sample an infinite rise.
    trough = np.maximum(np.minimum.accumulate(tail), top * 1e-6)
    best_at, best_rise = None, 0.0
    for index in range(gap, tail.size - 1):
        level = tail[index]
        if level < top * SPLIT_MIN_LEVEL:
            continue
        if level < tail[index - 1] or level < tail[index + 1]:
            continue
        rise = level / trough[index]
        if rise >= SPLIT_MIN_RISE and rise > best_rise:
            best_rise, best_at = rise, index
    if best_at is None:
        return None

    quietest = int(np.argmin(tail[:best_at + 1]))
    backoff = int(rate * SPLIT_BACKOFF_MS / 1000.0)
    return max(peak_at + 1, peak_at + quietest - backoff)


def split_set(
    processed: list[tuple[str, np.ndarray, int]],
    policy: str,
    ident: str,
) -> tuple[list[tuple[str, bytes]], list[tuple[str, bytes]]]:
    """A processed set as (key-down variants, key-up variants), both encoded.

    ``WHOLE`` sets come back exactly as they went in, with an empty key-up list.

    A ``SPLIT`` set is cut per recording, and a recording the cut does not find
    a key-up in is **dropped from the set** rather than kept whole. That looks
    wasteful and is the point: the app draws from the two lists independently,
    so a whole recording left in `press` would play its own baked-in key-up
    *and* then a key-up sample when the finger actually lifts — a double tick on
    some keystrokes and not others. Losing three of ten recordings costs a
    little variation; keeping them costs the pack its timing, which is the whole
    reason to split it.

    If too few recordings yield a key-up the split is abandoned for the set
    instead, and it ships whole exactly as before — see
    :data:`SPLIT_MIN_COVERAGE`.
    """
    whole = [(name, write_wav(samples, rate)) for name, samples, rate in processed]
    if policy != SPLIT:
        return whole, []

    press: list[tuple[str, bytes]] = []
    release: list[tuple[str, bytes]] = []
    dropped: list[str] = []
    floor_db = 10.0 ** (TRIM_FLOOR_DB / 20.0)
    for name, samples, rate in processed:
        stem = Path(name).stem
        suffix = Path(name).suffix or ".wav"
        cut = find_key_up(samples, rate)
        tail = samples[cut:].copy() if cut is not None else np.empty(0)
        if tail.size:
            tail = trim(tail, rate, float(np.max(np.abs(tail))) * floor_db)
        if cut is None or tail.size < rate * SPLIT_MIN_RELEASE_MS / 1000.0:
            dropped.append(name)
            continue
        head = samples[:cut].copy()
        fade_out(head, rate)
        fade_in(tail, rate)
        press.append((name, write_wav(head, rate)))
        release.append((f"{stem}-up{suffix}", write_wav(tail, rate)))

    covered = len(release) / max(len(processed), 1)
    if covered < SPLIT_MIN_COVERAGE:
        print(
            f"warning: {ident} is marked SPLIT but only {len(release)}/{len(processed)} "
            f"recordings hold a key-up; shipping it whole",
        )
        return whole, []
    if dropped:
        print(
            f"  note: {ident} dropped {len(dropped)} recording(s) with no key-up in "
            f"them ({', '.join(dropped)})",
        )
    return press, release


# ---------------------------------------------------------------- packing

def build_pack(
    meta: dict,
    variants: list[tuple[str, bytes]],
    releases: list[tuple[str, bytes]],
    author: str,
) -> bytes:
    """A deterministic `.wmsoundpack`.

    Fixed timestamps and a fixed entry order, so re-running the importer with
    no upstream change produces an identical file and an identical sha256 —
    otherwise every run would show up as a diff and `--bump` would bump
    versions for nothing.
    """
    pack_json = {
        "format": "wmkeyboard-sound-pack",
        "version": 1,
        "id": meta["id"],
        "name": meta["name"],
        "author": author,
        "packVersion": "1.0.0",
        "description": meta["description"],
        "gain": 1.0,
        "press": [f"sounds/{name}" for name, _ in variants],
        # The key-up halves, for a set the catalogue marks SPLIT; empty
        # otherwise. Not paired with `press` by index — the app draws from each
        # list on its own — but they are cut from the same recordings, so the
        # two lists describe one board either way.
        "release": [f"sounds/{name}" for name, _ in releases],
        # Left empty on purpose: monkeytype has no per-key sounds to import.
        # See docs/SOUND_PACK_FORMAT.md.
        "roles": {},
    }

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        entries = [("pack.json", json.dumps(pack_json, indent=2).encode() + b"\n")]
        entries += [(f"sounds/{name}", data) for name, data in variants + releases]
        for name, data in entries:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)
    return buffer.getvalue()


# ---------------------------------------------------------------- manifest

def bump_patch(version: str) -> str:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(.*)", version)
    if not match:
        return "1.0.1"
    major, minor, patch, rest = match.groups()
    return f"{major}.{minor}.{int(patch) + 1}{rest}"


FIELD_ORDER = [
    "id", "type", "name", "version", "author", "description", "tags", "path",
    "sha256", "sizeBytes", "previews", "minAppVersion", "license", "licenseFile",
]


def ordered(entry: dict) -> dict:
    known = [k for k in FIELD_ORDER if k in entry]
    extra = [k for k in entry if k not in FIELD_ORDER]
    return {k: entry[k] for k in known + extra}


def merge_manifest(built: list[dict], author: str, bump: bool, date: str) -> None:
    if MANIFEST.is_file():
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    else:
        manifest = {
            "$schema": (
                "https://raw.githubusercontent.com/wasi-master/"
                "wmkeyboard-addon-repository/main/docs/addons/wmkeyboard-repo.schema.json"
            ),
            "format": "wmkeyboard-repo",
            "version": 1,
            "repo": {
                "id": "com.wasimaster.wmkeyboard.monkeytype",
                "name": "Monkeytype Key Sounds",
                "description": (
                    "Monkeytype's key sounds as WM Keyboard sound packs — every "
                    "recording of each set, picked at random per keystroke, the "
                    "way monkeytype plays them."
                ),
                "author": "Wasi Master",
                "homepage": "https://github.com/wasi-master/wmkeyboard-monkeytype-sounds",
                "icon": "previews/icon.png",
            },
            "addons": [],
        }

    existing = {entry["id"]: entry for entry in manifest.get("addons", [])}
    changed: list[str] = []

    for pack in built:
        entry = existing.get(pack["id"], {})
        was = entry.get("sha256")
        version = entry.get("version", "1.0.0")
        if bump and was and was != pack["sha256"]:
            version = bump_patch(version)
            changed.append(f"{pack['id']}: {entry['version']} -> {version}")
        elif was and was != pack["sha256"]:
            changed.append(f"{pack['id']}: payload changed, version left at {version}")
        elif not was:
            changed.append(f"{pack['id']}: new")

        entry.update({
            "id": pack["id"],
            "type": "sound_pack",
            "name": pack["name"],
            "version": version,
            "author": author,
            "description": pack["description"],
            "tags": pack["tags"],
            "path": pack["path"],
            "sha256": pack["sha256"],
            "sizeBytes": pack["sizeBytes"],
            "previews": [f"previews/{pack['id']}.png"],
            "minAppVersion": MIN_APP_VERSION,
            "license": LICENSE_ID,
            "licenseFile": LICENSE_FILE,
        })
        existing[pack["id"]] = entry

    # Published order follows the catalogue, so the app's list reads the way
    # monkeytype's own dropdown does rather than in whatever order a dict
    # happened to iterate.
    order = [pack["id"] for pack in built]
    manifest["addons"] = [
        ordered(existing[pack_id]) for pack_id in order if pack_id in existing
    ] + [ordered(entry) for key, entry in existing.items() if key not in order]

    manifest.setdefault("repo", {})["updatedAt"] = date
    MANIFEST.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )
    for line in changed:
        print(f"  {line}")


# ---------------------------------------------------------------- main

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", help="branch, tag or sha to import (default: the pin in UPSTREAM.json)")
    parser.add_argument("--only", help="comma-separated published ids to rebuild")
    parser.add_argument("--bump", action="store_true", help="bump the patch version of packs whose payload changed")
    parser.add_argument("--raw", action="store_true", help="skip trimming and levelling; import the samples untouched")
    parser.add_argument("--date", help="value for repo.updatedAt (default: today)")
    args = parser.parse_args()

    pinned = json.loads(UPSTREAM.read_text()) if UPSTREAM.is_file() else {}
    ref = args.ref or pinned.get("commit") or "master"
    sha = resolve_ref(ref)
    print(f"monkeytype @ {sha[:12]} ({ref})")

    metadata_tsx = raw(sha, METADATA_PATH).decode("utf-8")
    sounds_ts = raw(sha, SOUNDS_TS_PATH).decode("utf-8")
    click_names = parse_display_names(metadata_tsx, "playSoundOnClick")
    counts, synth = parse_variant_counts(sounds_ts)
    files = list_sound_files(sha)
    print(f"{len(files)} files under {SOUNDS_DIR}")

    for number, (slug, how) in sorted(SYNTHESIZED.items()):
        if number not in synth:
            print(f"note: {number} ({slug}) is no longer synthesized upstream — it may have samples now")
    for number in sorted(synth):
        if number not in SYNTHESIZED:
            print(f"note: {number} is newly synthesized upstream and has no samples to import")

    wanted = {name.strip() for name in args.only.split(",")} if args.only else None
    only_dirs = sorted({path.split("/")[0] for path in files if "/" in path})
    loose = sorted(path for path in files if "/" not in path)

    # Every directory upstream ships must be something the catalogue names.
    for directory in only_dirs:
        match = re.fullmatch(r"click(\d+)", directory)
        if match and int(match.group(1)) in CLICK_SETS:
            continue
        if directory in EXTRA_SETS:
            continue
        raise SystemExit(
            f"error: upstream has {SOUNDS_DIR}/{directory}/ and tools/catalogue.py does not "
            f"describe it. Add an entry (id, name, family, tags, description) and re-run.",
        )
    for path in loose:
        if path not in EXTRA_SETS:
            raise SystemExit(
                f"error: upstream has {SOUNDS_DIR}/{path} and tools/catalogue.py does not "
                f"describe it. Add an entry and re-run.",
            )

    # (published meta, [(variant filename, upstream path)]) in catalogue order.
    plan: list[tuple[dict, list[str]]] = []
    for number, meta in sorted(CLICK_SETS.items()):
        directory = f"click{number}"
        variants = sorted(
            (path for path in files if path.startswith(f"{directory}/")),
            key=lambda path: int(re.sub(r"\D", "", path.rsplit("/", 1)[1]) or 0),
        )
        if not variants:
            raise SystemExit(f"error: {directory} is in the catalogue but ships no files upstream")
        expected = counts.get(number)
        if expected is not None and expected != len(variants):
            print(f"warning: {directory} has {len(variants)} files, sounds.ts says {expected}")
        upstream_name = click_names.get(str(number))
        if upstream_name and upstream_name.lower() != meta["name"].lower():
            print(f"warning: {directory} is \"{upstream_name}\" upstream, published as \"{meta['name']}\"")
        plan.append((meta, variants))

    for key, meta in EXTRA_SETS.items():
        variants = (
            sorted(
                (path for path in files if path.startswith(f"{key}/")),
                key=lambda path: int(re.sub(r"\D", "", path.rsplit("/", 1)[1]) or 0),
            )
            if "." not in key
            else ([key] if key in files else [])
        )
        if not variants:
            print(f"warning: {key} is in the catalogue but missing upstream — skipped")
            continue
        plan.append((meta, variants))

    PACKS.mkdir(exist_ok=True)
    author = "Monkeytype contributors"
    built: list[dict] = []
    sources: dict[str, dict] = {}

    for meta, variants in plan:
        if wanted and meta["id"] not in wanted:
            # Still needed in the manifest merge, so read back what is on disk.
            payload = PACKS / f"{meta['id']}.wmsoundpack"
            if payload.is_file():
                data = payload.read_bytes()
                built.append({
                    **meta,
                    "path": f"packs/{payload.name}",
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "sizeBytes": len(data),
                })
                sources[meta["id"]] = pinned.get("sources", {}).get(meta["id"], {})
            continue

        downloaded = []
        for index, path in enumerate(variants, start=1):
            data = raw(sha, f"{SOUNDS_DIR}/{path}")
            suffix = Path(path).suffix or ".wav"
            downloaded.append((f"{index}{suffix}", data))

        processed = process_set(downloaded, raw_mode=args.raw)
        # --raw imports the samples untouched, and a cut is a touch: it needs
        # the levelled, trimmed audio to find the boundary in.
        policy = WHOLE if args.raw else release_policy(meta)
        press_variants, release_variants = split_set(processed, policy, meta["id"])
        pack_bytes = build_pack(meta, press_variants, release_variants, author)
        payload = PACKS / f"{meta['id']}.wmsoundpack"
        payload.write_bytes(pack_bytes)

        built.append({
            **meta,
            "path": f"packs/{payload.name}",
            "sha256": hashlib.sha256(pack_bytes).hexdigest(),
            "sizeBytes": len(pack_bytes),
        })
        sources[meta["id"]] = {path: files[path] for path in variants}
        up = f" +{len(release_variants)} key-up" if release_variants else ""
        print(
            f"  {meta['id']:<22} {len(press_variants):>2} variant(s){up:<12}"
            f"  {len(pack_bytes) / 1024:>7.1f} KiB",
        )

    date = args.date or _dt.date.today().isoformat()
    merge_manifest(built, author, bump=args.bump, date=date)

    UPSTREAM.write_text(
        json.dumps(
            {
                "_comment": (
                    "Written by tools/import_monkeytype.py. The commit every sample in "
                    "packs/ was taken from, and the git blob sha of each source file, so "
                    "a rebuild can be checked against exactly what was imported."
                ),
                "repository": f"https://github.com/{OWNER}/{REPO}",
                "commit": sha,
                "importedAt": date,
                "soundsDir": SOUNDS_DIR,
                "synthesizedUpstream": {
                    str(number): slug for number, (slug, _) in sorted(SYNTHESIZED.items())
                },
                "sources": sources,
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    print(f"\n{len(built)} packs; pinned at {sha[:12]}")
    print("next: python3 tools/generate_previews.py && python3 tools/validate.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
