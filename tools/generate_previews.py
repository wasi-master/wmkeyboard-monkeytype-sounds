#!/usr/bin/env python3
"""Render a preview card for every pack, plus the repository icon.

The card draws the **real waveform of every variant**, stacked. That is the
whole point: a sound pack's one interesting property is how much its recordings
differ from each other, and a single waveform — or worse, a decorative bar
chart — shows exactly nothing about that. Ten Cherry MX Blue traces next to
each other tell you at a glance that the pack varies; the three identical-looking
traces of a synthesized blip tell you the opposite, just as usefully.

    python3 tools/generate_previews.py
    python3 tools/generate_previews.py --only click,typewriter
    python3 tools/generate_previews.py --icon-only
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from catalogue import CLICK_SETS, EXTRA_SETS, FAMILIES  # noqa: E402
from import_monkeytype import read_wav  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PACKS = ROOT / "packs"
PREVIEWS = ROOT / "previews"
FONTS = Path(__file__).resolve().parent / "fonts"

SCALE = 2
WIDTH, HEIGHT = 720 * SCALE, 700 * SCALE

# Slate, the same family the sibling repository's cards use, so a WM Keyboard
# catalogue does not look like two different products scrolled together.
BG = [(13, 18, 30), (21, 29, 46), (16, 23, 38)]
CARD = (15, 23, 42, 225)
TEXT = (248, 250, 252, 255)
MUTED = (148, 163, 184, 255)
FAINT = (71, 85, 105, 255)

# Past this many traces the rows are thinner than the ink in them.
MAX_TRACES = 10


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), size * SCALE)


def gradient(width: int, height: int, glow: tuple[int, int, int]) -> Image.Image:
    """The card background: a vertical slate ramp under two soft accent glows."""
    base = Image.new("RGBA", (width, height))
    draw = ImageDraw.Draw(base)
    for y in range(height):
        t = y / max(height - 1, 1)
        if t < 0.5:
            a, b, f = BG[0], BG[1], t * 2
        else:
            a, b, f = BG[1], BG[2], (t - 0.5) * 2
        draw.line(
            [(0, y), (width, y)],
            fill=tuple(int(a[i] + (b[i] - a[i]) * f) for i in range(3)) + (255,),
        )

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(overlay)
    glow_draw.ellipse(
        [width * 0.35, -height * 0.3, width * 1.3, height * 0.5], fill=glow + (46,),
    )
    glow_draw.ellipse(
        [-width * 0.3, height * 0.55, width * 0.65, height * 1.3], fill=glow + (30,),
    )
    return Image.alpha_composite(base, overlay.filter(ImageFilter.GaussianBlur(120 * SCALE // 2)))


def pill(text: str, typeface, fg, bg, border) -> Image.Image:
    """A small capsule for the family badge."""
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    box = measure.textbbox((0, 0), text, font=typeface)
    pad_x, pad_y = 12 * SCALE, 5 * SCALE
    width = box[2] - box[0] + pad_x * 2
    height = box[3] - box[1] + pad_y * 2
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        [0, 0, width - 1, height - 1], radius=7 * SCALE, fill=bg, outline=border, width=SCALE,
    )
    draw.text((pad_x - box[0], pad_y - box[1]), text, font=typeface, fill=fg)
    return image


def wrap(draw, text: str, typeface, width: int, max_lines: int) -> list[str]:
    lines: list[str] = []
    words = text.split()
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=typeface) <= width:
            current = trial
            continue
        if current:
            lines.append(current)
        current = word
        if len(lines) == max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and words:
        joined = " ".join(lines)
        if len(joined) < len(text):
            while lines and draw.textlength(lines[-1] + " …", font=typeface) > width:
                lines[-1] = lines[-1].rsplit(" ", 1)[0]
            lines[-1] += " …"
    return lines


def envelope(samples: np.ndarray, columns: int) -> tuple[np.ndarray, np.ndarray]:
    """Per-column min and max — the shape an audio editor draws.

    Not a decimation: taking every Nth sample of a 40 ms click would miss the
    transient entirely and draw a flat line for the loudest thing in the file.
    """
    if samples.size < columns:
        samples = np.pad(samples, (0, columns - samples.size))
    edges = np.linspace(0, samples.size, columns + 1).astype(int)
    lows = np.empty(columns)
    highs = np.empty(columns)
    for index in range(columns):
        chunk = samples[edges[index]:max(edges[index + 1], edges[index] + 1)]
        lows[index] = chunk.min()
        highs[index] = chunk.max()
    return lows, highs


def read_pack(path: Path) -> tuple[dict, list[tuple[np.ndarray, int]]]:
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("pack.json"))
        variants = [read_wav(archive.read(name)) for name in manifest["press"]]
    return manifest, variants


def draw_traces(
    canvas: Image.Image,
    box: tuple[int, int, int, int],
    variants,
    accent,
    linear: bool = False,
) -> None:
    """One waveform per variant, stacked, all on a shared vertical scale.

    Shared, not per-trace: normalising each row to fill its own lane would draw
    a quiet variant exactly as tall as a loud one and erase the difference the
    picture exists to show.

    Amplitude is drawn on a compressed scale (``|x| ** 0.45``), the same thing
    an audio editor's logarithmic waveform view does, unless [linear] is set.
    On a linear scale these recordings are one spike and 150 ms of apparently
    flat line — which hides something real: most of the switch packs have the
    key's *release* click recorded into the same file, 70–100 ms behind the
    press and a fraction of its amplitude. That is a property of the pack worth
    seeing on its card.
    """
    left, top, right, bottom = box
    shown = variants[:MAX_TRACES]
    lane = (bottom - top) / max(len(shown), 1)
    columns = int((right - left) / (2 * SCALE))
    peak = max((float(np.max(np.abs(s))) for s, _ in shown), default=1.0) or 1.0
    gamma = 1.0 if linear else 0.45

    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    label_font = font("jetbrains-mono.ttf", 9)

    for index, (samples, rate) in enumerate(shown):
        centre = top + lane * (index + 0.5)
        half = lane * 0.40
        lows, highs = envelope(samples, columns)

        # Baseline first, so a near-silent trace is still visibly a trace.
        draw.line([(left, centre), (right, centre)], fill=FAINT[:3] + (90,), width=SCALE)
        def scaled(value: float) -> float:
            return float(np.sign(value) * (abs(value) / peak) ** gamma)

        for column in range(columns):
            x = left + column * (right - left) / columns
            y_low = centre - scaled(lows[column]) * half
            y_high = centre - scaled(highs[column]) * half
            if abs(y_high - y_low) < SCALE:
                y_low, y_high = centre - SCALE / 2, centre + SCALE / 2
            draw.line([(x, y_low), (x, y_high)], fill=accent + (235,), width=SCALE)

        draw.text(
            (left - 26 * SCALE, centre - 6 * SCALE),
            f"{index + 1:>2}",
            font=label_font,
            fill=FAINT,
        )
        ms = samples.size / rate * 1000.0
        draw.text(
            (right + 8 * SCALE, centre - 6 * SCALE),
            f"{ms:.0f}ms",
            font=label_font,
            fill=FAINT,
        )

    canvas.alpha_composite(layer)


def render(meta: dict, path: Path, out: Path, linear: bool = False) -> None:
    manifest, variants = read_pack(path)
    family = FAMILIES[meta["family"]]
    accent = family["accent"]

    canvas = gradient(WIDTH, HEIGHT, accent)
    draw = ImageDraw.Draw(canvas)

    title_font = font("inter.ttf", 33)
    body_font = font("inter.ttf", 15)
    mono_font = font("jetbrains-mono.ttf", 11)

    margin = 40 * SCALE
    # --- header card
    header_h = 168 * SCALE
    draw.rounded_rectangle(
        [margin, 34 * SCALE, WIDTH - margin, 34 * SCALE + header_h],
        radius=18 * SCALE,
        fill=CARD,
        outline=accent + (90,),
        width=2 * SCALE,
    )
    badge = pill(
        f"{family['badge']}  •  {len(manifest['press'])} RECORDING"
        f"{'S' if len(manifest['press']) != 1 else ''}",
        mono_font,
        fg=accent + (255,),
        bg=accent + (34,),
        border=accent + (140,),
    )
    canvas.alpha_composite(badge, (margin + 24 * SCALE, 52 * SCALE))
    draw.text((margin + 24 * SCALE, 84 * SCALE), meta["name"], font=title_font, fill=TEXT)

    text_width = WIDTH - 2 * margin - 48 * SCALE
    for line_no, line in enumerate(wrap(draw, meta["description"], body_font, text_width, 3)):
        draw.text(
            (margin + 24 * SCALE, (128 + line_no * 21) * SCALE), line, font=body_font, fill=MUTED,
        )

    # --- waveform card
    top = 232 * SCALE
    bottom = HEIGHT - 96 * SCALE
    draw.rounded_rectangle(
        [margin, top, WIDTH - margin, bottom],
        radius=18 * SCALE,
        fill=(10, 15, 26, 190),
        outline=accent + (55,),
        width=2 * SCALE,
    )
    draw_traces(
        canvas,
        (margin + 60 * SCALE, top + 26 * SCALE, WIDTH - margin - 60 * SCALE, bottom - 20 * SCALE),
        variants,
        accent,
        linear=linear,
    )
    if len(variants) > MAX_TRACES:
        draw.text(
            (margin + 24 * SCALE, bottom - 18 * SCALE),
            f"+{len(variants) - MAX_TRACES} more",
            font=mono_font,
            fill=FAINT,
        )

    footer = (
        "One picked at random for every key press"
        if len(variants) > 1
        else "A single recording"
    )
    draw.text(
        (margin, HEIGHT - 72 * SCALE),
        f"{footer}  •  WM Keyboard sound pack",
        font=body_font,
        fill=MUTED,
    )
    draw.text(
        (margin, HEIGHT - 48 * SCALE),
        "Samples from monkeytype  •  GPL-3.0-or-later",
        font=mono_font,
        fill=FAINT,
    )

    out.parent.mkdir(exist_ok=True)
    canvas.convert("RGB").save(out, "PNG", optimize=True)


def render_icon(out: Path) -> None:
    """The repository icon: three stacked traces, the format's whole idea."""
    size = 256
    canvas = gradient(size, size, (56, 189, 248))
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    rng = np.random.default_rng(7)
    for row in range(3):
        centre = 64 + row * 64
        accent = [(56, 189, 248), (34, 197, 94), (249, 115, 22)][row]
        columns = 34
        # Decaying noise: a key click's actual shape, and it makes the three
        # rows visibly different from one another at 48 px.
        shape = np.exp(-np.linspace(0, 4, columns)) * rng.uniform(0.35, 1.0, columns)
        for column in range(columns):
            x = 26 + column * (size - 52) / columns
            half = shape[column] * 26
            draw.line([(x, centre - half), (x, centre + half)], fill=accent + (245,), width=4)
    canvas.alpha_composite(layer)
    canvas.convert("RGB").save(out, "PNG", optimize=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="comma-separated published ids")
    parser.add_argument("--icon-only", action="store_true")
    parser.add_argument(
        "--linear",
        action="store_true",
        help="draw amplitude linearly instead of the compressed audio-editor scale",
    )
    args = parser.parse_args()

    PREVIEWS.mkdir(exist_ok=True)
    render_icon(PREVIEWS / "icon.png")
    print("previews/icon.png")
    if args.icon_only:
        return 0

    wanted = {name.strip() for name in args.only.split(",")} if args.only else None
    catalogue = list(CLICK_SETS.values()) + list(EXTRA_SETS.values())

    for meta in catalogue:
        if wanted and meta["id"] not in wanted:
            continue
        path = PACKS / f"{meta['id']}.wmsoundpack"
        if not path.is_file():
            print(f"warning: no pack for {meta['id']} — run tools/import_monkeytype.py")
            continue
        out = PREVIEWS / f"{meta['id']}.png"
        render(meta, path, out, linear=args.linear)
        print(f"{out.relative_to(ROOT)}  ({out.stat().st_size / 1024:.0f} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
