"""Synthetic test images.

Built byte-by-byte so the suite never ships a real person's ID card and needs
no image library. Each function returns bytes that a real decoder would accept.
"""
import struct
import zlib


def png_bytes(width=640, height=400):
    """A structurally valid, decodable PNG of a solid colour."""
    def chunk(tag, payload):
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    raw = b"".join(b"\x00" + b"\x30\x60\x90" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def jpeg_bytes(width=640, height=400):
    """A minimal baseline JPEG whose SOF0 header carries real dimensions."""
    sof0 = (b"\xff\xc0" + struct.pack(">H", 17) + b"\x08"
            + struct.pack(">HH", height, width)
            + b"\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01")
    return (b"\xff\xd8\xff\xe0" + struct.pack(">H", 16)
            + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
            + sof0 + b"\xff\xd9")


def webp_bytes(width=640, height=400):
    """A WebP container with a VP8X header carrying the dimensions."""
    vp8x = (b"VP8X" + struct.pack("<I", 10) + b"\x00\x00\x00\x00"
            + (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little"))
    body = b"WEBP" + vp8x
    return b"RIFF" + struct.pack("<I", len(body)) + body


def oversized_png(target_bytes):
    """A valid PNG padded past a size limit with a trailing comment chunk."""
    base = png_bytes(300, 300)
    padding = max(0, target_bytes - len(base))
    tag = b"tEXt"
    payload = b"pad\x00" + b"x" * padding
    comment = (struct.pack(">I", len(payload)) + tag + payload
               + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))
    return base[:-12] + comment + base[-12:]


# --- files that must be rejected -------------------------------------------

def not_an_image():
    return b"this is plain text, not an image at all"


def executable_bytes():
    """An ELF header - the shape of an uploaded binary."""
    return b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 120


def script_bytes():
    return b"#!/bin/sh\nrm -rf /\n"


def truncated_png():
    return png_bytes()[:20]


def malformed_png():
    """Correct signature, corrupt header."""
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 40


def tiny_png():
    """A real image, far too small to be a photograph of a card."""
    return png_bytes(8, 8)


def empty():
    return b""


def png_with_marker(marker):
    """A valid PNG carrying a recognisable byte sequence, for leak hunting."""
    base = png_bytes(320, 240)
    tag = b"tEXt"
    payload = b"marker\x00" + marker
    comment = (struct.pack(">I", len(payload)) + tag + payload
               + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))
    return base[:-12] + comment + base[-12:]
