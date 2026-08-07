#!/usr/bin/env python3
"""Validate this repository before publishing it.

Three passes:

1. The addon-repository schema at ``docs/wmkeyboard-repo.schema.json``.
2. The things a schema cannot express — every ``path``, ``previews[]``,
   ``licenseFile`` and ``repo.icon`` resolves to a file that is actually here,
   ids are unique, and every checksum is correct.
3. The **pack** contents: each ``.wmsoundpack`` opens, holds a ``pack.json``
   this app's importer would accept, and every path it names is in the archive.

Pass 3 is the one worth having. A manifest can be perfectly valid while every
pack in it is a zip of nothing, and the failure would land on a user's phone as
"this pack holds no sounds the app can play" — a message they cannot act on.

    python3 tools/validate.py
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "wmkeyboard-repo.json"
SCHEMA = ROOT / "docs" / "wmkeyboard-repo.schema.json"

# Mirrors SoundPackFile.kt. A pack over any of these is refused on the device,
# so shipping one means publishing something nobody can install.
PACK_FORMAT = "wmkeyboard-sound-pack"
PACK_VERSION = 1
MAX_SAMPLES = 64
MAX_VARIANTS = 32
MAX_SAMPLE_BYTES = 4 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_ENTRIES = 128

# Mirrors KeySoundRole.serialName. A role outside this set is dropped silently
# by the importer, which is the right behaviour on a phone and the wrong one in
# CI: here it is a typo somebody should hear about.
KNOWN_ROLES = {"default", "space", "enter", "delete", "modifier"}


def looks_playable(data: bytes) -> bool:
    """The same header sniff the app applies, so CI refuses what the phone would."""
    if len(data) < 12:
        return False
    tag = data[:4]
    if tag[:3] == b"ID3":
        return True
    if data[0] == 0xFF and (data[1] & 0xE0) == 0xE0:
        return True
    if tag == b"OggS":
        return True
    return tag == b"RIFF" and data[8:12] == b"WAVE"


def check_pack(ident: str, payload: Path, errors: list[str], warnings: list[str]) -> None:
    try:
        with zipfile.ZipFile(payload) as archive:
            names = set(archive.namelist())
            if "pack.json" not in names:
                errors.append(f"{ident}: no pack.json in the archive")
                return
            if len(names) > MAX_ENTRIES:
                errors.append(f"{ident}: {len(names)} entries, the app stops at {MAX_ENTRIES}")

            manifest = json.loads(archive.read("pack.json"))
            if manifest.get("format") != PACK_FORMAT:
                errors.append(f"{ident}: pack.json format is {manifest.get('format')!r}")
                return
            if manifest.get("version", 0) > PACK_VERSION:
                errors.append(
                    f"{ident}: pack.json asks for format version "
                    f"{manifest.get('version')}, the app understands {PACK_VERSION}",
                )
            if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", manifest.get("id", "")):
                errors.append(f"{ident}: pack.json id {manifest.get('id')!r} is not a valid id")
            if not manifest.get("name", "").strip():
                warnings.append(f"{ident}: pack.json has no name; the addon entry's is used")

            gain = manifest.get("gain", 1.0)
            if not isinstance(gain, (int, float)) or not 0.0 <= gain <= 1.0:
                # Not an error: the app clamps. But a pack asking for 2.0 was
                # written by someone expecting a boost that cannot happen.
                warnings.append(f"{ident}: gain {gain} is outside 0..1 and will be clamped")

            # Every list the pack names, with where it came from, so an error
            # can say which one.
            lists: list[tuple[str, list]] = [
                ("press", manifest.get("press") or []),
                ("release", manifest.get("release") or []),
            ]
            roles = manifest.get("roles") or {}
            for role, spec in roles.items():
                if role not in KNOWN_ROLES:
                    warnings.append(
                        f"{ident}: role {role!r} is not one the app knows; it will be ignored",
                    )
                if role == "default":
                    warnings.append(
                        f"{ident}: roles.default is ignored — the top-level press/release "
                        f"*is* the default",
                    )
                lists.append((f"roles.{role}.press", (spec or {}).get("press") or []))
                lists.append((f"roles.{role}.release", (spec or {}).get("release") or []))

            if not lists[0][1]:
                errors.append(f"{ident}: press is empty; the pack would install as silent")

            referenced: set[str] = set()
            total = 0
            for where, entries in lists:
                if len(entries) > MAX_VARIANTS:
                    errors.append(
                        f"{ident}: {where} has {len(entries)} entries, the app takes {MAX_VARIANTS}",
                    )
                for entry in entries:
                    if entry in names:
                        resolved = entry
                    else:
                        tail = entry.rsplit("/", 1)[-1]
                        matches = [n for n in names if n.rsplit("/", 1)[-1] == tail]
                        resolved = matches[0] if matches else None
                    if resolved is None:
                        errors.append(f"{ident}: {where} names {entry!r}, which is not in the archive")
                        continue
                    if resolved in referenced:
                        continue
                    referenced.add(resolved)
                    data = archive.read(resolved)
                    total += len(data)
                    if len(data) > MAX_SAMPLE_BYTES:
                        errors.append(
                            f"{ident}: {resolved} is {len(data) / 1024:.0f} KiB, over the "
                            f"{MAX_SAMPLE_BYTES // (1024 * 1024)} MB per-sample cap",
                        )
                    if not looks_playable(data):
                        errors.append(f"{ident}: {resolved} is not an MP3, OGG or WAV file")

            if len(referenced) > MAX_SAMPLES:
                errors.append(
                    f"{ident}: {len(referenced)} samples, the app loads at most {MAX_SAMPLES}",
                )
            if total > MAX_TOTAL_BYTES:
                errors.append(
                    f"{ident}: {total / 1024 / 1024:.1f} MiB unzipped, over the "
                    f"{MAX_TOTAL_BYTES // (1024 * 1024)} MiB cap",
                )

            # Files in the archive nothing plays. Not an error, but they are
            # bytes every user downloads for nothing.
            orphans = names - referenced - {"pack.json"}
            orphans = {n for n in orphans if not n.endswith("/")}
            if orphans:
                warnings.append(
                    f"{ident}: {len(orphans)} file(s) in the archive that no list names",
                )
    except (zipfile.BadZipFile, json.JSONDecodeError, KeyError) as error:
        errors.append(f"{ident}: unreadable pack — {error}")


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    errors: list[str] = []
    warnings: list[str] = []

    try:
        import jsonschema
    except ImportError:
        warnings.append("jsonschema is not installed; the schema pass was skipped")
    else:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        for problem in sorted(validator.iter_errors(manifest), key=lambda e: list(e.path)):
            where = "/".join(str(p) for p in problem.path) or "<root>"
            errors.append(f"schema: {where}: {problem.message}")

    seen: set[str] = set()
    for entry in manifest.get("addons", []):
        ident = entry.get("id", "<no id>")
        if ident in seen:
            errors.append(f"{ident}: duplicate id")
        seen.add(ident)

        path = entry.get("path", "")
        if not path:
            errors.append(f"{ident}: no path")
            continue
        payload = ROOT / path
        if not payload.is_file():
            errors.append(f"{ident}: path does not exist — {path}")
            continue

        if entry.get("sizeBytes") not in (None, payload.stat().st_size):
            errors.append(
                f"{ident}: sizeBytes is {entry['sizeBytes']}, the file is {payload.stat().st_size}",
            )
        declared = entry.get("sha256")
        if declared:
            actual = hashlib.sha256(payload.read_bytes()).hexdigest()
            if actual != declared:
                errors.append(f"{ident}: sha256 does not match the file")

        for preview in entry.get("previews", []):
            if not (ROOT / preview).is_file():
                errors.append(f"{ident}: preview does not exist — {preview}")
        licence = entry.get("licenseFile")
        if licence and not (ROOT / licence).is_file():
            errors.append(f"{ident}: licenseFile does not exist — {licence}")

        if entry.get("type") == "sound_pack":
            if payload.suffix != ".wmsoundpack":
                warnings.append(f"{ident}: payload is not named .wmsoundpack")
            check_pack(ident, payload, errors, warnings)

    icon = manifest.get("repo", {}).get("icon")
    if icon and not (ROOT / icon).is_file():
        errors.append(f"repo.icon does not exist — {icon}")

    for line in warnings:
        print(f"warning: {line}")
    for line in errors:
        print(f"error: {line}", file=sys.stderr)

    if errors:
        print(f"\n{len(errors)} problem(s)", file=sys.stderr)
        return 1
    print(f"{len(manifest.get('addons', []))} addons, no problems")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
