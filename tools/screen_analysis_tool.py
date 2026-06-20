"""
Screen vision tool — captures the screen and sends it to Claude vision API
to answer a question about what's visible.

Unlike capture_screenshot (which does OCR text extraction only), this tool
understands visual layout, graphs, icons, images, and UI structure.
"""

import base64
import io
import os

# Load .env in case this module is imported before main.py runs dotenv
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def analyze_screen(question: str = "What do you see on screen?") -> str:
    """Capture current screen and use Claude vision to answer a question about it."""
    try:
        import mss
        from PIL import Image
        import anthropic

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return "[Screen analysis failed: ANTHROPIC_API_KEY not set in .env]"

        with mss.mss() as sct:
            monitor = sct.monitors[1]
            shot = sct.grab(monitor)
            img = Image.frombytes("RGB", shot.size, shot.rgb)

        w, h = img.size
        if w > 1280:
            img = img.resize((1280, int(h * 1280 / w)), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        img_b64 = base64.b64encode(buf.getvalue()).decode()

        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": img_b64,
                        },
                    },
                    {"type": "text", "text": question},
                ],
            }],
        )
        return resp.content[0].text

    except Exception as e:
        return f"[Screen analysis failed: {e}]"
