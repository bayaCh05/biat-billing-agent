import hashlib
from pathlib import Path


def sha256(file_path: str) -> str:
    """Compute the SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def mime_type(file_path: str) -> str:
    """Detect MIME type from file content (not extension)."""
    import magic
    return magic.from_file(file_path, mime=True)


def is_supported(file_path: str, supported_formats: list[str]) -> bool:
    return Path(file_path).suffix.lstrip(".").lower() in supported_formats
