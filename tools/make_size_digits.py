"""Rebuild rendered digit templates; fonts are inputs, not runtime dependencies."""
import argparse
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.size_ocr import normalize_digit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("fonts", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, default=Path("assets/size-digits.npz"))
    args = parser.parse_args()
    glyphs, labels, aspects = [], [], []
    for path in args.fonts:
        for size in range(9, 18):
            font = ImageFont.truetype(str(path), size)
            for digit, symbol in enumerate("0123456789%"):
                image = Image.new("L", (40, 40))
                ImageDraw.Draw(image).text((4, 1), symbol, font=font, fill=255)
                mask = np.asarray(image) > 80
                glyph, aspect = normalize_digit(mask)
                glyphs.append(np.round(glyph*255).astype(np.uint8))
                labels.append(digit)
                aspects.append(aspect)
    np.savez_compressed(args.output, glyphs=glyphs, labels=np.asarray(labels, np.uint8),
                        aspects=np.asarray(aspects, np.float32))
    print(f"Wrote {len(labels)} rendered glyphs to {args.output}")


if __name__ == "__main__":
    main()
