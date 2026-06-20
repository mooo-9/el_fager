"""
Developer utility tools for El Fager.

Hash strings, encode/decode Base64 and URLs, generate passwords, UUIDs, QR codes.
Stdlib only except generate_qr (qrcode[pil]).
"""

import hashlib
import base64
import uuid
import secrets
import string
import urllib.parse
import os


def hash_text(text: str, algorithm: str = "sha256") -> str:
    """Hash a string. algorithm: md5, sha1, sha256, sha512."""
    try:
        algo = algorithm.lower().replace("-", "")
        supported = {"md5", "sha1", "sha256", "sha512"}
        if algo not in supported:
            return f"[hash_text: unknown algorithm '{algorithm}'. Supported: {', '.join(sorted(supported))}]"
        h = hashlib.new(algo, text.encode("utf-8"))
        return f"{algorithm.upper()}: {h.hexdigest()}"
    except Exception as e:
        return f"[hash_text failed: {e}]"


def encode_base64(text: str) -> str:
    """Base64 encode a string."""
    try:
        encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
        return f"Base64: {encoded}"
    except Exception as e:
        return f"[encode_base64 failed: {e}]"


def decode_base64(encoded: str) -> str:
    """Base64 decode a string back to plain text."""
    try:
        decoded = base64.b64decode(encoded.strip()).decode("utf-8")
        return f"Decoded: {decoded}"
    except Exception as e:
        return f"[decode_base64 failed: {e}]"


def url_encode(text: str) -> str:
    """URL-encode a string (percent-encode special characters)."""
    try:
        encoded = urllib.parse.quote(text, safe="")
        return f"URL-encoded: {encoded}"
    except Exception as e:
        return f"[url_encode failed: {e}]"


def url_decode(text: str) -> str:
    """Decode a percent-encoded URL string."""
    try:
        decoded = urllib.parse.unquote(text)
        return f"URL-decoded: {decoded}"
    except Exception as e:
        return f"[url_decode failed: {e}]"


def generate_password(length: int = 16, include_symbols: bool = True) -> str:
    """Generate a cryptographically secure random password."""
    try:
        if length < 4 or length > 128:
            return "[generate_password: length must be between 4 and 128]"
        chars = string.ascii_letters + string.digits
        if include_symbols:
            chars += "!@#$%^&*()-_=+[]{}|;:,.<>?"
        password = "".join(secrets.choice(chars) for _ in range(length))
        return f"Password ({length} chars): {password}"
    except Exception as e:
        return f"[generate_password failed: {e}]"


def generate_uuid() -> str:
    """Generate a random UUID4."""
    try:
        return f"UUID: {uuid.uuid4()}"
    except Exception as e:
        return f"[generate_uuid failed: {e}]"


def generate_qr(text: str, output_path: str = None) -> str:
    """Generate a QR code PNG from text or URL. Saved to data/ if no path given."""
    try:
        import qrcode

        if output_path is None:
            os.makedirs("data", exist_ok=True)
            safe = "".join(c if c.isalnum() else "_" for c in text[:20])
            output_path = f"data/qr_{safe}.png"
        else:
            parent = os.path.dirname(output_path)
            if parent:
                os.makedirs(parent, exist_ok=True)

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(text)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        img.save(output_path)
        size_kb = os.path.getsize(output_path) // 1024
        return f"QR code saved: {output_path} ({size_kb} KB). Encodes: {text[:60]}"
    except ImportError:
        return "[generate_qr failed: qrcode not installed. Run: pip install qrcode[pil]]"
    except Exception as e:
        return f"[generate_qr failed: {e}]"
