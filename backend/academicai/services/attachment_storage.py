"""Blob storage for supporting material.

This is the only place in the project that writes user-supplied bytes to disk,
so the rules live here rather than being spread across the service and the
route.

WHAT A FILENAME IS
------------------
User input. It is kept for DISPLAY, because "COS202_Assignment1.pdf" is how a
student recognises the paper, and it is never used to build a path. The bytes
are located by a `storage_key` this module generates, and the extension on disk
comes from the format we detected, not from what the upload claimed.

WHAT A CONTENT TYPE IS
----------------------
A claim. The browser sends one and it is not evidence, so every upload is
sniffed: the declared type has to agree with the leading bytes, and a file
whose signature we do not recognise is refused. That is what stops a script
being stored as a PDF.

NOTHING HERE IS EXECUTABLE
--------------------------
Files are written outside the static root, with no execute bit, and are only
ever returned through a route that has already checked membership. No path from
the web maps to this directory.
"""
import hashlib
import os
import secrets

from ..errors import ValidationError

# Accepted formats, keyed by the content type a browser will send. Each entry
# gives the extension used on disk and the magic-byte signatures that a file of
# that type must start with. A short allow-list is the point: this exists to
# preserve a lecturer's brief, not to accept arbitrary uploads.
#
# `None` for signatures means the format has no reliable magic number (plain
# text), and the check falls back to "decodes as UTF-8".
ALLOWED = {
    "application/pdf": (".pdf", (b"%PDF-",)),
    "image/png": (".png", (b"\x89PNG\r\n\x1a\n",)),
    "image/jpeg": (".jpg", (b"\xff\xd8\xff",)),
    "image/webp": (".webp", (b"RIFF",)),
    "image/heic": (".heic", (b"\x00\x00\x00\x18ftypheic", b"\x00\x00\x00\x18ftypheix",
                             b"\x00\x00\x00\x18ftyphevc", b"\x00\x00\x00\x24ftypheic")),
    # DOCX/PPTX/XLSX are ZIP containers; DOC is the older OLE compound file.
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        (".docx", (b"PK\x03\x04",)),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation":
        (".pptx", (b"PK\x03\x04",)),
    "application/msword": (".doc", (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",)),
    "text/plain": (".txt", None),
}

# What a person is told they can attach, in their words rather than in MIME.
HUMAN_FORMATS = "PDF, Word, PowerPoint, plain text, or a photo (PNG, JPEG, WebP, HEIC)"

_READ_CHUNK = 64 * 1024


def describe_formats():
    return HUMAN_FORMATS


def _normalise_type(declared):
    value = (declared or "").split(";")[0].strip().lower()
    # Browsers occasionally send image/jpg, which is not a registered type.
    if value == "image/jpg":
        value = "image/jpeg"
    return value


def _signature_matches(head, signatures, content_type):
    if signatures is None:
        try:
            head.decode("utf-8")
        except UnicodeDecodeError:
            return False
        return True
    if content_type == "image/webp":
        # RIFF....WEBP - the container tag sits after the 4-byte length.
        return head.startswith(b"RIFF") and head[8:12] == b"WEBP"
    return any(head.startswith(sig) for sig in signatures)


def validate_type(declared_type, head):
    """Return the canonical content type, or refuse.

    Both halves have to agree. A declared type we do not accept is refused
    before anything is read, and a file whose bytes do not match what it
    claimed is refused after - neither the claim nor the bytes is trusted
    alone.
    """
    content_type = _normalise_type(declared_type)
    if content_type not in ALLOWED:
        raise ValidationError(
            f"That file type is not supported. Attach {HUMAN_FORMATS}.")
    _, signatures = ALLOWED[content_type]
    if not _signature_matches(head, signatures, content_type):
        raise ValidationError(
            "That file's contents do not match its type, so it was not saved. "
            f"Attach {HUMAN_FORMATS}.")
    return content_type


def new_storage_key(content_type):
    """An unguessable, application-generated name. Never derived from input."""
    extension = ALLOWED[content_type][0]
    return f"{secrets.token_hex(16)}{extension}"


def _path_for(root, storage_key):
    # Sharded so one directory does not accumulate every file, and joined from
    # the generated key only - there is no user input anywhere in this path.
    return os.path.join(root, storage_key[:2], storage_key)


def save(root, stream, declared_type, max_bytes):
    """Stream an upload to disk under a generated key.

    Returns (storage_key, content_type, byte_size, checksum).

    The size limit is enforced WHILE reading rather than from the Content-Length
    header, which a client controls. If the limit is passed, the partial file is
    removed before the error propagates.
    """
    head = stream.read(_READ_CHUNK)
    if not head:
        raise ValidationError("That file is empty.")
    content_type = validate_type(declared_type, head)

    storage_key = new_storage_key(content_type)
    path = _path_for(root, storage_key)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    digest = hashlib.sha256()
    total = 0
    chunk = head
    try:
        # 0o600: readable by the application only, and never executable.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh:
            while chunk:
                total += len(chunk)
                if total > max_bytes:
                    raise ValidationError(
                        f"That file is larger than the {max_bytes // (1024 * 1024)}MB limit.")
                digest.update(chunk)
                fh.write(chunk)
                chunk = stream.read(_READ_CHUNK)
    except Exception:
        delete(root, storage_key)
        raise
    return storage_key, content_type, total, digest.hexdigest()


def open_stream(root, storage_key):
    path = _path_for(root, storage_key)
    if not os.path.exists(path):
        return None
    return open(path, "rb")


def delete(root, storage_key):
    """Remove the bytes. Safe to call when they are already gone."""
    path = _path_for(root, storage_key)
    try:
        os.remove(path)
    except FileNotFoundError:
        return False
    except OSError:
        return False
    return True
