"""
Translation tool — Phase 6C.
Uses MyMemory API (free, no API key, 5,000 chars/day).
Supports Arabic, English, French, and 60+ other languages.
"""

import httpx

_LANG_ALIASES = {
    "arabic": "ar", "عربي": "ar", "عربية": "ar",
    "english": "en", "إنجليزي": "en",
    "french": "fr", "français": "fr", "فرنسي": "fr",
    "german": "de", "spanish": "es", "italian": "it",
    "turkish": "tr", "chinese": "zh", "japanese": "ja",
    "russian": "ru", "portuguese": "pt", "hindi": "hi",
    "korean": "ko", "dutch": "nl", "polish": "pl",
}

_LANG_NAMES = {
    "ar": "Arabic", "en": "English", "fr": "French",
    "de": "German", "es": "Spanish", "it": "Italian",
    "tr": "Turkish", "zh": "Chinese", "ja": "Japanese",
    "ru": "Russian", "pt": "Portuguese", "hi": "Hindi",
    "ko": "Korean", "nl": "Dutch", "pl": "Polish",
}


def _resolve(lang: str) -> str:
    l = lang.strip().lower()
    return _LANG_ALIASES.get(l, l)


def translate_text(
    text: str,
    target_language: str,
    source_language: str = "auto",
) -> str:
    """
    Translate text to the target language using MyMemory API.
    target_language — language name ('French', 'Arabic') or code ('fr', 'ar')
    source_language — source language or 'auto' for auto-detection
    """
    if not text.strip():
        return "Nothing to translate."

    tgt = _resolve(target_language)
    src = "auto" if source_language.lower() in ("auto", "") else _resolve(source_language)

    langpair = f"{'en' if src == 'auto' else src}|{tgt}"

    try:
        resp = httpx.get(
            "https://api.mymemory.translated.net/get",
            params={"q": text[:4900], "langpair": langpair},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("responseStatus") == 200:
            translation = data["responseData"]["translatedText"]
            tgt_name = _LANG_NAMES.get(tgt, tgt.upper())
            return f"[{tgt_name}] {translation}"
        else:
            return f"[Translation error: {data.get('responseDetails', 'unknown error')}]"
    except Exception as e:
        return f"[Translation error: {e}]"
