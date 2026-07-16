#!/usr/bin/env python3
"""Create a looping hacker-style ASCII portrait GIF from a photo."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import (
    Image,
    ImageChops,
    ImageDraw,
    ImageEnhance,
    ImageFilter,
    ImageFont,
    ImageOps,
)


CHARACTER_POOLS = (
    " ",
    ".`'",
    ",:;",
    "-_~^",
    "+=<>",
    "!?/\\|",
    "()[]{}",
    "01rxnuv",
    "23456789abcdef",
    "ABCDEFGHJKLMNPQRSTUVWXYZ",
    "#$%&@",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Turn a portrait into a seamless animated ASCII GIF."
    )
    parser.add_argument("input", type=Path, help="Source portrait")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("assets/ascii-portrait.gif"),
        help="Destination GIF (default: assets/ascii-portrait.gif)",
    )
    parser.add_argument("--columns", type=int, default=90)
    parser.add_argument("--frames", type=int, default=20)
    parser.add_argument("--duration", type=int, default=90, help="Milliseconds/frame")
    parser.add_argument("--font-size", type=int, default=12)
    parser.add_argument("--seed", type=int, default=1987)
    parser.add_argument(
        "--focus-y",
        type=float,
        default=0.34,
        help="Vertical square-crop position from 0 (top) to 1 (bottom)",
    )
    parser.add_argument(
        "--zoom",
        type=float,
        default=1.16,
        help="Portrait crop zoom (default: 1.16)",
    )
    parser.add_argument("--font", type=Path, help="Optional monospaced TTF/OTF font")
    return parser.parse_args()


def find_monospace_font(explicit: Path | None, size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        explicit,
        Path("C:/Windows/Fonts/CascadiaMono.ttf"),
        Path("C:/Windows/Fonts/consola.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"),
        Path("/System/Library/Fonts/Menlo.ttc"),
    ]
    for candidate in candidates:
        if candidate and candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    raise FileNotFoundError(
        "No monospaced font found. Pass one explicitly with --font."
    )


def square_crop(image: Image.Image, focus_y: float, zoom: float) -> Image.Image:
    width, height = image.size
    side = round(min(width, height) / max(1.0, zoom))
    left = max(0, (width - side) // 2)
    max_top = max(0, height - side)
    top = round(max_top * min(1.0, max(0.0, focus_y)))
    return image.crop((left, top, left + side, top + side))


def prepare_luminance(
    image: Image.Image, columns: int, rows: int
) -> tuple[list[int], list[int]]:
    gray = ImageOps.grayscale(image)
    gray = ImageOps.autocontrast(gray, cutoff=(1.0, 2.0))
    gray = ImageEnhance.Contrast(gray).enhance(1.58)
    gray = gray.filter(ImageFilter.UnsharpMask(radius=2, percent=145, threshold=3))
    small = gray.resize((columns, rows), Image.Resampling.LANCZOS)
    edges = small.filter(ImageFilter.FIND_EDGES)

    luminance: list[int] = []
    edge_strength: list[int] = []
    for base, edge in zip(
        small.get_flattened_data(), edges.get_flattened_data()
    ):
        # Darken midtones slightly so eyes, glasses, and curls remain distinct.
        shaped = 255 * math.pow(base / 255, 1.08) if base else 0
        luminance.append(min(255, round(shaped + edge * 0.13)))
        edge_strength.append(edge)
    return luminance, edge_strength


def noise(seed: int, column: int, row: int, frame: int) -> int:
    """Small deterministic mixer; unlike hash(), this is stable across runs."""
    value = (
        seed
        + column * 0x9E3779B1
        + row * 0x85EBCA77
        + frame * 0xC2B2AE3D
    ) & 0xFFFFFFFF
    value ^= value >> 16
    value = (value * 0x7FEB352D) & 0xFFFFFFFF
    value ^= value >> 15
    value = (value * 0x846CA68B) & 0xFFFFFFFF
    return value ^ (value >> 16)


def choose_character(level: int, column: int, row: int, frame: int, seed: int) -> str:
    pool = CHARACTER_POOLS[level]
    if len(pool) == 1:
        return pool

    stable = noise(seed, column, row, 0)
    if stable % 100 < 58:
        # Each cell changes on its own cadence, so the portrait stays coherent.
        phase = (stable >> 8) % 3
        tick = (frame + phase) // 2
        index = noise(seed, column, row, tick + 1) % len(pool)
    else:
        index = stable % len(pool)
    return pool[index]


def character_color(value: int, edge: int, scanline: bool, accent: bool) -> tuple[int, int, int]:
    intensity = max(0.0, min(1.0, value / 255))
    red = round(5 + 52 * intensity)
    green = round(30 + 225 * intensity)
    blue = round(18 + 92 * intensity)

    if edge > 80:
        green = min(255, green + 18)
        blue = min(150, blue + 12)
    if scanline:
        red = min(100, red + 24)
        green = min(255, green + 40)
        blue = min(170, blue + 28)
    if accent:
        red, green, blue = 92, 255, 150
    return red, green, blue


def render_frames(
    image: Image.Image,
    font: ImageFont.FreeTypeFont,
    columns: int,
    frame_count: int,
    seed: int,
) -> list[Image.Image]:
    cell_width = max(1, math.ceil(font.getlength("M")))
    font_box = font.getbbox("Ag")
    glyph_top = font_box[1]
    glyph_height = font_box[3] - font_box[1]
    cell_height = glyph_height + 4
    crop_aspect = image.width / image.height
    rows = max(1, round(columns * cell_width / (cell_height * crop_aspect)))
    canvas_size = (columns * cell_width, rows * cell_height)
    luminance, edge_strength = prepare_luminance(image, columns, rows)

    frames: list[Image.Image] = []
    for frame in range(frame_count):
        sharp = Image.new("RGB", canvas_size, (1, 7, 4))
        glow = Image.new("RGB", canvas_size, (0, 0, 0))
        sharp_draw = ImageDraw.Draw(sharp)
        glow_draw = ImageDraw.Draw(glow)
        scan_row = round((frame / frame_count) * (rows + 8)) - 4

        # Short-lived horizontal offsets create a restrained terminal glitch.
        band_active = frame % 7 in (4, 5)
        band_start = noise(seed, 0, 0, frame // 7 + 3) % max(1, rows - 3)
        band_shift = -2 if (frame // 7) % 2 else 2

        for row in range(rows):
            shift = band_shift if band_active and band_start <= row < band_start + 2 else 0
            for column in range(columns):
                source_column = column - shift
                if not 0 <= source_column < columns:
                    continue
                index = row * columns + source_column
                value = luminance[index]
                edge = edge_strength[index]
                flicker = noise(seed + 23, column, row, frame // 2)

                if value < 14:
                    # A few dim 0/1 cells keep the black background alive.
                    if flicker % 190:
                        continue
                    character = "01"[(flicker >> 8) & 1]
                    color = (3, 38 + flicker % 24, 22)
                else:
                    value = max(0, min(255, value + (flicker % 15) - 7))
                    level = min(
                        len(CHARACTER_POOLS) - 1,
                        round((value / 255) * (len(CHARACTER_POOLS) - 1)),
                    )
                    character = choose_character(level, column, row, frame, seed)
                    if character == " ":
                        continue
                    is_scanline = abs(row - scan_row) <= 1
                    is_accent = value > 120 and flicker % 181 == 0
                    color = character_color(value, edge, is_scanline, is_accent)

                x = column * cell_width
                y = row * cell_height - glyph_top + 1
                sharp_draw.text((x, y), character, font=font, fill=color)
                if color[1] > 145:
                    glow_draw.text(
                        (x, y),
                        character,
                        font=font,
                        fill=(color[0] // 4, color[1] // 3, color[2] // 3),
                    )

        blurred = glow.filter(ImageFilter.GaussianBlur(radius=1.7))
        frames.append(ImageChops.screen(sharp, blurred))
    return frames


def save_gif(frames: list[Image.Image], output: Path, duration: int) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    palette = frames[0].quantize(
        colors=64,
        method=Image.Quantize.FASTOCTREE,
        dither=Image.Dither.NONE,
    )
    paletted = [palette]
    paletted.extend(
        frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames[1:]
    )
    paletted[0].save(
        output,
        save_all=True,
        append_images=paletted[1:],
        duration=duration,
        loop=0,
        disposal=2,
        optimize=True,
    )


def main() -> None:
    args = parse_args()
    if args.columns < 20 or args.frames < 2 or args.font_size < 6:
        raise ValueError("Use at least 20 columns, 2 frames, and a 6px font.")

    source = ImageOps.exif_transpose(Image.open(args.input)).convert("RGB")
    crop = square_crop(source, args.focus_y, args.zoom)
    font = find_monospace_font(args.font, args.font_size)
    frames = render_frames(crop, font, args.columns, args.frames, args.seed)
    save_gif(frames, args.output, args.duration)
    print(
        f"Wrote {args.output} ({frames[0].width}x{frames[0].height}, "
        f"{len(frames)} frames)"
    )


if __name__ == "__main__":
    main()
