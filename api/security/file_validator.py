"""File upload validation — MIME magic bytes + size + filename sanitization."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import HTTPException

MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "20"))
MAX_FILE_SIZE = MAX_FILE_SIZE_MB * 1024 * 1024

# Allowed file types from env (comma-separated extensions)
_ALLOWED_EXT_STR = os.getenv("ALLOWED_FILE_TYPES", "pdf,jpg,jpeg,png,tiff")
ALLOWED_EXTENSIONS = {e.strip().lower() for e in _ALLOWED_EXT_STR.split(",")}

# Magic byte signatures mapped to canonical type name
_MAGIC: list[tuple[bytes, str]] = [
    (b"%PDF",           "pdf"),
    (b"\xff\xd8\xff",  "jpeg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"II*\x00",       "tiff"),
    (b"MM\x00*",       "tiff"),
]


def validate(filename: str, content: bytes) -> dict:
    """
    Validate an uploaded file's size, MIME type, and filename safety.
    Returns dict with detected_type, file_size_bytes, safe_filename.
    Raises HTTPException on any violation.
    """
    # 1. File size
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Fichier trop volumineux. "
                f"Maximum: {MAX_FILE_SIZE_MB} MB. "
                f"Reçu: {len(content) / 1024 / 1024:.1f} MB."
            ),
        )

    # 2. Null bytes in filename
    if "\x00" in (filename or ""):
        raise HTTPException(status_code=400, detail="Nom de fichier invalide.")

    # 3. Filename sanitization — no path traversal
    safe_filename = Path(filename or "upload").name
    if safe_filename != filename and "/" not in filename and "\\" not in filename:
        pass  # Accept filenames that differ only by path stripping
    if not safe_filename:
        raise HTTPException(status_code=400, detail="Nom de fichier invalide.")

    # 4. MIME type via magic bytes
    header = content[:8]
    detected_type: str | None = None
    for magic, ftype in _MAGIC:
        if header.startswith(magic):
            detected_type = ftype
            break

    if not detected_type:
        raise HTTPException(
            status_code=400,
            detail=(
                "Type de fichier non autorisé. "
                "Seuls PDF et images (JPG, PNG, TIFF) sont acceptés."
            ),
        )

    # 5. Extension matches content
    ext = Path(safe_filename).suffix.lower().lstrip(".")
    if ext == "jpg":
        ext = "jpeg"
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Extension .{ext} non autorisée.",
        )

    # 6. Extension consistent with magic bytes
    if detected_type == "jpeg" and ext not in ("jpeg", "jpg"):
        raise HTTPException(status_code=400, detail="Extension incohérente avec le contenu du fichier.")
    if detected_type == "png" and ext != "png":
        raise HTTPException(status_code=400, detail="Extension incohérente avec le contenu du fichier.")
    if detected_type == "tiff" and ext not in ("tiff", "tif"):
        raise HTTPException(status_code=400, detail="Extension incohérente avec le contenu du fichier.")

    return {
        "detected_type": detected_type,
        "file_size_bytes": len(content),
        "safe_filename": safe_filename,
    }
