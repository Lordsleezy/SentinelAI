#!/usr/bin/env python3
"""Generate production ICO (multi-size) and Linux PNG icons for electron-builder."""
from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "desktop-shell" / "assets"
ICON_ICO = ASSETS / "icon.ico"
ICONS_DIR = ASSETS / "icons"
REQUIRED_ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
LINUX_PNG_SIZES = (16, 24, 32, 48, 64, 128, 256, 512)


def _draw_base(size: int):
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (size, size), (10, 10, 46, 255))
    draw = ImageDraw.Draw(img)
    margin = max(2, size // 16)
    draw.rounded_rectangle(
        [margin, margin, size - margin - 1, size - margin - 1],
        radius=max(4, size // 8),
        outline=(0, 255, 136, 255),
        width=max(2, size // 24),
    )
    cx, cy = size // 2, size // 2
    r = size // 5
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(0, 212, 255, 220))
    return img


def generate_pngs() -> None:
    from PIL import Image

    ICONS_DIR.mkdir(parents=True, exist_ok=True)
    base = _draw_base(512)
    for s in LINUX_PNG_SIZES:
        out = ICONS_DIR / f"{s}x{s}.png"
        base.resize((s, s), Image.Resampling.LANCZOS).save(out, format="PNG")
    base.save(ICONS_DIR / "512x512.png", format="PNG")


def generate_ico() -> None:
    from PIL import Image

    ASSETS.mkdir(parents=True, exist_ok=True)
    largest = _draw_base(256)
    # Pillow embeds all listed sizes from the source image when saving ICO.
    largest.save(
        ICON_ICO,
        format="ICO",
        sizes=[(s, s) for s in REQUIRED_ICO_SIZES],
    )


def validate_ico() -> tuple[bool, str]:
    """Ensure icon.ico contains 256x256 (electron-builder requirement)."""
    if not ICON_ICO.is_file():
        return False, "icon.ico missing"
    try:
        from PIL import Image

        header_ok, header_msg = _validate_ico_header()
        if not header_ok:
            return False, header_msg
        with Image.open(ICON_ICO) as im:
            sizes = set()
            n = getattr(im, "n_frames", 1) or 1
            for i in range(n):
                im.seek(i)
                sizes.add(im.size)
        max_dim = max(max(w, h) for w, h in sizes)
        if max_dim < 256:
            return False, f"no 256x256 entry; found {sorted(sizes)} ({header_msg})"
        return True, f"OK max={max_dim} frames={len(sizes)} ({header_msg})"
    except Exception:
        return _validate_ico_header()


def _validate_ico_header() -> tuple[bool, str]:
    data = ICON_ICO.read_bytes()
    if len(data) < 6:
        return False, "file too small"
    count = struct.unpack_from("<H", data, 4)[0]
    max_dim = 0
    offset = 6
    for _ in range(count):
        if offset + 16 > len(data):
            break
        w, h = data[offset], data[offset + 1]
        width = 256 if w == 0 else w
        height = 256 if h == 0 else h
        max_dim = max(max_dim, width, height)
        offset += 16
    if max_dim < 256:
        return False, f"max icon dimension {max_dim} < 256"
    return True, f"max dimension {max_dim}"


def main() -> int:
    validate_only = "--validate-only" in sys.argv
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        if validate_only:
            ok, msg = _validate_ico_header() if ICON_ICO.is_file() else (False, "icon.ico missing")
            print(msg)
            return 0 if ok else 1
        print("ERROR: Pillow required — pip install Pillow", file=sys.stderr)
        return 1

    if validate_only:
        ok, msg = validate_ico()
        print(msg)
        return 0 if ok else 1

    generate_pngs()
    generate_ico()
    ok, msg = validate_ico()
    print(f"icon.ico: {msg}")
    print(f"linux icons: {ICONS_DIR}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
