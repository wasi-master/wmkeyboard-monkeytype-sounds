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
5.  Normalise the set (see `process_set`) and write a `.wmsoundpack`.
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
from catalogue import CLICK_SETS, EXTRA_SETS, SYNTHESIZED  # noqa: E402

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


def process_set(variants: list[tuple[str, bytes]], raw_mode: bool) -> list[tuple[str, bytes]]:
    """Trim, fade and level a whole set of variants together.

    The levelling is the part worth being careful about: **one gain for the
    whole set**, computed from the loudest variant. Normalising each variant on
    its own would flatten exactly the differences the variants exist to create —
    a set of ten switch recordings would come out ten identical volumes, and the
    randomisation would stop being audible.
    """
    decoded = [(name, *read_wav(data)) for name, data in variants]

    if raw_mode:
        return [(name, write_wav(samples, rate)) for name, samples, rate in decoded]

    peak = max((float(np.max(np.abs(s))) for _, s, _ in decoded), default=0.0)
    if peak <= 0.0:
        raise ValueError("every variant is silent")

    floor = peak * (10.0 ** (TRIM_FLOOR_DB / 20.0))
    gain = (10.0 ** (TARGET_PEAK_DBFS / 20.0)) / peak

    out: list[tuple[str, bytes]] = []
    for name, samples, rate in decoded:
        audible = np.flatnonzero(np.abs(samples) >= floor)
        if audible.size:
            pre_roll = int(rate * PRE_ROLL_MS / 1000.0)
            start = max(0, int(audible[0]) - pre_roll)
            end = min(samples.size, int(audible[-1]) + 1)
            samples = samples[start:end]

        samples = samples * gain

        fade_in = min(int(rate * FADE_IN_MS / 1000.0), samples.size)
        if fade_in > 1:
            samples[:fade_in] *= np.linspace(0.0, 1.0, fade_in)
        fade_out = min(int(rate * FADE_OUT_MS / 1000.0), samples.size)
        if fade_out > 1:
            samples[-fade_out:] *= np.linspace(1.0, 0.0, fade_out)

        out.append((name, write_wav(samples, rate)))
    return out


# ---------------------------------------------------------------- packing

def build_pack(meta: dict, variants: list[tuple[str, bytes]], author: str) -> bytes:
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
        "release": [],
        # Left empty on purpose: monkeytype has no per-key sounds to import.
        # See docs/SOUND_PACK_FORMAT.md.
        "roles": {},
    }

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        entries = [("pack.json", json.dumps(pack_json, indent=2).encode() + b"\n")]
        entries += [(f"sounds/{name}", data) for name, data in variants]
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
        pack_bytes = build_pack(meta, processed, author)
        payload = PACKS / f"{meta['id']}.wmsoundpack"
        payload.write_bytes(pack_bytes)

        built.append({
            **meta,
            "path": f"packs/{payload.name}",
            "sha256": hashlib.sha256(pack_bytes).hexdigest(),
            "sizeBytes": len(pack_bytes),
        })
        sources[meta["id"]] = {path: files[path] for path in variants}
        print(f"  {meta['id']:<22} {len(processed):>2} variant(s)  {len(pack_bytes) / 1024:>7.1f} KiB")

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
