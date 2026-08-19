#!/usr/bin/env python3
"""
Generate PNG and multi-resolution ICO icon from basic shapes without external dependencies.
"""
import struct
import zlib
import math
from pathlib import Path


def create_png(width: int, height: int) -> bytes:
    """Generate a clean RGBA PNG of the rkbdb2xml application icon."""
    raw_rows = []
    
    # Radius of main rounded rect
    rx = width * 0.22
    cx_v, cy_v = width * 0.41, height * 0.50
    r_vinyl = width * 0.31
    
    # Document rect
    dx, dy = width * 0.51, height * 0.30
    dw, dh = width * 0.35, height * 0.43

    for y in range(height):
        row = bytearray([0])  # filter type 0 (None)
        for x in range(width):
            # Background rounded rect mask
            # Normalize to center
            nx = abs(x - width / 2) - (width / 2 - rx)
            ny = abs(y - height / 2) - (height / 2 - rx)
            in_bg = (nx <= 0 and ny <= 0) or (nx <= 0 and ny > 0 and ny <= rx) or (ny <= 0 and nx > 0 and nx <= rx) or (nx > 0 and ny > 0 and (nx*nx + ny*ny <= rx*rx))

            if not in_bg:
                row.extend([0, 0, 0, 0])
                continue

            # Base gradient (dark slate #1e293b to #0f172a)
            t = (x + y) / (width + height)
            r = int(30 * (1 - t) + 15 * t)
            g = int(41 * (1 - t) + 23 * t)
            b = int(59 * (1 - t) + 42 * t)
            a = 255

            # Border
            is_border = (nx > rx - 2 and nx <= rx) or (ny > rx - 2 and ny <= rx) or (nx > 0 and ny > 0 and nx*nx + ny*ny > (rx-2)**2 and nx*nx + ny*ny <= rx*rx)
            if is_border:
                r, g, b = 56, 189, 248  # cyan border

            # Vinyl record
            dist_v = math.hypot(x - cx_v, y - cy_v)
            if dist_v <= r_vinyl:
                # Grooves
                groove = int(dist_v) % 6 == 0
                if dist_v <= r_vinyl * 0.28:
                    # Vinyl Center label (cyan/sky blue)
                    if dist_v <= r_vinyl * 0.08:
                        r, g, b = 15, 23, 42  # hole
                    else:
                        r, g, b = 2, 132, 199
                else:
                    if groove:
                        r, g, b = 71, 85, 105
                    else:
                        r, g, b = 30, 41, 59

            # Document card on the right
            if dx <= x <= dx + dw and dy <= y <= dy + dh:
                # Header of doc
                if y <= dy + dh * 0.25:
                    r, g, b = 245, 158, 11  # amber #f59e0b
                else:
                    r, g, b = 15, 23, 42  # dark body
                    # Draw a simple '< / >' pattern in white/cyan
                    # Bracket <
                    if (abs((x - (dx + dw*0.3)) - abs(y - (dy + dh*0.6))) < 2) and (dx + dw*0.2 <= x <= dx + dw*0.4) and (dy + dh*0.45 <= y <= dy + dh*0.75):
                        r, g, b = 56, 189, 248
                    # Slash /
                    if (abs((x - (dx + dw*0.5)) + (y - (dy + dh*0.6))) < 2) and (dx + dw*0.4 <= x <= dx + dw*0.6) and (dy + dh*0.4 <= y <= dy + dh*0.8):
                        r, g, b = 245, 158, 11
                    # Bracket >
                    if (abs((x - (dx + dw*0.7)) + abs(y - (dy + dh*0.6))) < 2) and (dx + dw*0.6 <= x <= dx + dw*0.8) and (dy + dh*0.45 <= y <= dy + dh*0.75):
                        r, g, b = 56, 189, 248

                # Card border
                if x == int(dx) or x == int(dx + dw) or y == int(dy) or y == int(dy + dh):
                    r, g, b = 56, 189, 248

            row.extend([r, g, b, a])
        raw_rows.append(bytes(row))

    # Construct PNG binary
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    compressed_idat = zlib.compress(b"".join(raw_rows), 9)
    
    png_data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", compressed_idat) + chunk(b"IEND", b"")
    return png_data


def create_ico(png_images: list[tuple[int, bytes]]) -> bytes:
    """Create Windows .ico containing multiple PNG-encoded images."""
    num_images = len(png_images)
    header = struct.pack("<HHH", 0, 1, num_images)
    
    offset = 6 + 16 * num_images
    entries = []
    data_blobs = []

    for size, data in png_images:
        w_b = 0 if size >= 256 else size
        h_b = 0 if size >= 256 else size
        size_bytes = len(data)
        entry = struct.pack("<BBBBHHII", w_b, h_b, 0, 0, 1, 32, size_bytes, offset)
        entries.append(entry)
        data_blobs.append(data)
        offset += size_bytes

    return header + b"".join(entries) + b"".join(data_blobs)


def main():
    assets_dir = Path(__file__).resolve().parent.parent / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    sizes = [16, 32, 48, 64, 128, 256]
    png_dict = {}

    for size in sizes:
        png_data = create_png(size, size)
        png_dict[size] = png_data
        png_path = assets_dir / f"icon_{size}x{size}.png"
        png_path.write_bytes(png_data)
        print(f"Generated {png_path}")

    # Main icon.png
    (assets_dir / "icon.png").write_bytes(png_dict[256])
    print(f"Generated {assets_dir / 'icon.png'}")

    # Main icon.ico (multires)
    ico_data = create_ico([(s, png_dict[s]) for s in sizes])
    (assets_dir / "icon.ico").write_bytes(ico_data)
    print(f"Generated {assets_dir / 'icon.ico'}")


if __name__ == "__main__":
    main()
