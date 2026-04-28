#!/usr/bin/env python3
"""Convert a PNG into an LVGL 1-bit indexed C bitmap for the toucan_pet shield.

The output mirrors the layout of boards/shields/toucan_pet/widgets/toucan128.c:
an 8-byte palette wrapped in a CONFIG_NICE_VIEW_WIDGET_INVERTED #if/#else block
followed by MSB-first packed pixel bytes, plus a matching `lv_img_dsc_t` struct.

Drop the generated file in place of widgets/toucan128.c (use --var toucan128 so
the symbol referenced from custom_status_screen.c stays the same).

Requires: Pillow (`pip install Pillow`).
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path

from PIL import Image, ImageOps

DEFAULT_MAX_W = 144  # Sharp LS0XX width  (toucan_pet.overlay)
DEFAULT_MAX_H = 168  # Sharp LS0XX height (toucan_pet.overlay)


def parse_bg(s: str) -> tuple[int, int, int]:
    parts = [p.strip() for p in s.split(",")]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("--bg must be R,G,B (three 0-255 ints)")
    try:
        rgb = tuple(int(p) for p in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--bg components must be integers") from exc
    if not all(0 <= c <= 255 for c in rgb):
        raise argparse.ArgumentTypeError("--bg components must be 0..255")
    return rgb  # type: ignore[return-value]


def sanitize_identifier(name: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_]", "_", name)
    if not cleaned or cleaned[0].isdigit():
        cleaned = "img_" + cleaned
    return cleaned


def load_and_prepare(
    src: Path,
    max_w: int,
    max_h: int,
    bg: tuple[int, int, int],
    exact: bool,
    dither: bool,
    threshold: int,
) -> Image.Image:
    im = Image.open(src)
    im.load()

    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        flat = Image.new("RGB", im.size, bg)
        flat.paste(im, mask=im.split()[-1])
        im = flat
    else:
        im = im.convert("RGB")

    im = ImageOps.contain(im, (max_w, max_h))

    if exact:
        canvas = Image.new("RGB", (max_w, max_h), bg)
        x = (max_w - im.width) // 2
        y = (max_h - im.height) // 2
        canvas.paste(im, (x, y))
        im = canvas

    gray = im.convert("L")
    if dither:
        return gray.convert("1")
    return gray.point(lambda v, t=threshold: 255 if v >= t else 0, mode="1")


def pack_bits(im: Image.Image) -> bytes:
    """Pack a 1-bit image MSB-first, padding each row to a whole byte."""
    width, height = im.size
    px = im.load()
    stride = math.ceil(width / 8)
    out = bytearray(stride * height)
    for y in range(height):
        row_base = y * stride
        for x in range(width):
            # PIL "1" mode: 0 = black, 255 = white. Index 1 in our palette is
            # white (foreground), so set the bit when the pixel is non-zero.
            if px[x, y]:
                out[row_base + (x >> 3)] |= 0x80 >> (x & 7)
    return bytes(out)


def format_bytes(data: bytes, per_line: int = 16, indent: str = "  ") -> str:
    lines = []
    for i in range(0, len(data), per_line):
        chunk = data[i : i + per_line]
        lines.append(indent + ", ".join(f"0x{b:02x}" for b in chunk) + ",")
    return "\n".join(lines)


def render_c(var: str, width: int, height: int, pixels: bytes) -> str:
    stride = math.ceil(width / 8)
    data_size = 8 + stride * height  # 8-byte palette + packed pixels
    pixel_block = format_bytes(pixels)
    upper = var.upper()

    return f"""#include <lvgl.h>


#ifndef LV_ATTRIBUTE_MEM_ALIGN
#define LV_ATTRIBUTE_MEM_ALIGN
#endif

#ifndef LV_ATTRIBUTE_IMG_{upper}
#define LV_ATTRIBUTE_IMG_{upper}
#endif

const LV_ATTRIBUTE_MEM_ALIGN LV_ATTRIBUTE_LARGE_CONST LV_ATTRIBUTE_IMG_{upper} uint8_t {var}_map[] = {{
  #if CONFIG_NICE_VIEW_WIDGET_INVERTED
        0xff, 0xff, 0xff, 0xff, /*Color of index 0*/
        0x00, 0x00, 0x00, 0xff, /*Color of index 1*/
  #else
        0x00, 0x00, 0x00, 0xff, /*Color of index 0*/
        0xff, 0xff, 0xff, 0xff, /*Color of index 1*/
  #endif

{pixel_block}
}};

const lv_img_dsc_t {var} = {{
  .header.cf = LV_IMG_CF_INDEXED_1BIT,
  .header.always_zero = 0,
  .header.reserved = 0,
  .header.w = {width},
  .header.h = {height},
  .data_size = {data_size},
  .data = {var}_map,
}};
"""


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=(
            "Convert a PNG into an LVGL 1-bit indexed C bitmap matching "
            "boards/shields/toucan_pet/widgets/toucan128.c. Default target size "
            "is the Sharp LS0XX panel (144x168)."
        ),
    )
    p.add_argument("input", type=Path, help="Source PNG (any size, any mode)")
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Destination .c file. Default: <input-stem>.c next to the input. "
             "Use '-' for stdout.",
    )
    p.add_argument(
        "--var",
        help="C variable / symbol name. Default: sanitized input stem.",
    )
    p.add_argument("--max-width", type=int, default=DEFAULT_MAX_W)
    p.add_argument("--max-height", type=int, default=DEFAULT_MAX_H)
    p.add_argument(
        "--exact",
        action="store_true",
        help="Pad the fitted image with the background color so the final "
             "bitmap is exactly --max-width by --max-height.",
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--dither",
        action="store_true",
        help="Use Floyd-Steinberg dithering instead of a flat threshold.",
    )
    mode.add_argument(
        "--threshold",
        type=int,
        default=128,
        help="Brightness cutoff for the binary conversion (0-255). Default 128.",
    )
    p.add_argument(
        "--bg",
        type=parse_bg,
        default=(0, 0, 0),
        help="Background color used to flatten transparent pixels and to pad "
             "when --exact is set. Format R,G,B. Default 0,0,0 (black).",
    )

    args = p.parse_args(argv)

    if not args.input.is_file():
        p.error(f"input not found: {args.input}")
    if args.max_width <= 0 or args.max_height <= 0:
        p.error("--max-width and --max-height must be positive")
    if not (0 <= args.threshold <= 255):
        p.error("--threshold must be 0..255")

    var = sanitize_identifier(args.var or args.input.stem)

    image = load_and_prepare(
        src=args.input,
        max_w=args.max_width,
        max_h=args.max_height,
        bg=args.bg,
        exact=args.exact,
        dither=args.dither,
        threshold=args.threshold,
    )
    pixels = pack_bits(image)
    text = render_c(var, image.width, image.height, pixels)

    if args.output is None:
        out_path = args.input.with_suffix(".c")
    elif str(args.output) == "-":
        sys.stdout.write(text)
        return 0
    else:
        out_path = args.output

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text)
    print(
        f"wrote {out_path} ({image.width}x{image.height}, "
        f"{len(pixels)} pixel bytes, var '{var}')",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
