# El Fager — Personal AI Assistant

Your JARVIS for Windows 11. Starts when you launch it, lives in the system tray while it runs, wakes up with `Ctrl+Space`, listens to you in English, thinks with Claude, and talks back.

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.14+ | Already installed |
| ffmpeg | Optional but recommended. `winget install Gyan.FFmpeg` then add `C:\ffmpeg\bin` to PATH. Whisper works without it when using this app since audio is passed as numpy arrays directly. |
| Anthropic API key | Get one at console.anthropic.com |
| Internet connection | Required for Claude API and Edge TTS (voice synthesis) |

---

## First-Time Setup

### 1. Add your API key

Open `.env` and replace the placeholder:

```
ANTHROPIC_API_KEY=sk-ant-your-actual-key-here
```

### 2. Install Python dependencies

**Important:** Install PyTorch CPU-only first to avoid a 2GB CUDA download (we don't use GPU):

```powershell
cd "C:\claude proj\el_fager"

python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
python -m pip install openai-whisper
python -m pip install -r requirements.txt
```

> **Note on pygame:** This project uses `pygame-ce` (the community edition) because `pygame` has no wheel for Python 3.14. It's a drop-in replacement with the same `import pygame` syntax.

### 3. Run

```powershell
python main.py
```

El Fager starts silently in the system tray. **Right-click the tray icon** and pin it to the taskbar if Windows hides it in the overflow area.

---

## First Launch (What to Expect)

On first launch, two models download automatically:

| Model | Size | Where | When |
|---|---|---|---|
| Whisper `large-v3-turbo` (faster-whisper, override with `WHISPER_MODEL`) | ~1.6 GB | `~/.cache/huggingface/` | Background at startup — skipped entirely when `GROQ_API_KEY` is set (cloud transcription) |
| Sentence-transformer `all-MiniLM-L6-v2` | ~90 MB | `~/.cache/torch/` | On first memory query |

The Whisper download happens in the background — El Fager will show "Loading Whisper model..." if you press `Ctrl+Space` before it's ready. Just wait a moment.

---

## How to Use

| Action | What Happens |
|---|---|
| `Ctrl+Space` or `Ctrl+F12` | Opens the overlay and starts listening immediately |
| `Ctrl+Shift+Space` or `Ctrl+Shift+F12` | Opens the Command Center |
| Speak naturally | English |
| Stop speaking | El Fager detects silence (~1.5s) and starts thinking |
| `Escape` | Closes the overlay and cancels any in-progress recording |
| `Ctrl+Space` again | Closes overlay if already open |
| Type in the text box | Alternative to speaking — press Enter to submit |

---

## Project Structure

```
el_fager/
├── core/
│   ├── brain.py      ← Claude API + tool dispatch + system prompt
│   ├── voice_in.py   ← Whisper speech-to-text
│   ├── voice_out.py  ← Edge TTS + pygame-ce playback
│   ├── memory.py     ← ChromaDB vector memory
│   └── pipeline.py   ← QThread worker that runs the full voice loop
├── tools/
│   ├── files_tool.py   ← File search and open
│   ├── system_tool.py  ← App launcher, PowerShell runner
│   ├── web_tool.py     ← Web search (scaffold — see Phase 2)
│   └── calendar_tool.py ← Google Calendar (scaffold — see Phase 2)
├── ui/
│   └── overlay.py    ← PyQt6 dark floating overlay
├── main.py           ← Entry point
├── profile.json      ← Your personal context (name, paths)
├── .env              ← API keys
└── data/
    └── chroma/       ← ChromaDB conversation memory (auto-created)
```

---

## Google Calendar Setup

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (e.g. "El Fager")
3. Enable the Google Calendar API
4. Go to **APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID**
5. Application type: **Desktop app**
6. Download the JSON file → rename to `credentials.json` → place in `data/credentials.json`
7. Run El Fager and say "what do I have today?" — a browser will open for you to authorize
8. After authorizing, `data/token.json` is created automatically — you won't need to authorize again

> **Note:** Keep `credentials.json` and `token.json` private — they are in `.gitignore`

Install the required packages:

```powershell
python -m pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client
```

---

## Phase 2: Capabilities Overview

| Feature | Status |
|---|---|
| Web search (DuckDuckGo) | ✅ Active |
| Clipboard read/write | ✅ Active |
| Windows reminders (toast) | ✅ Active |
| Screen capture + vision | ✅ Active |
| Long-term memory (facts) | ✅ Active |
| Google Calendar | ✅ Active (requires setup above) |

---

## Troubleshooting

**Ctrl+Space doesn't work**
- Try running `python main.py` as Administrator
- Some security software blocks global keyboard hooks
- Alternative: use the tray icon → "Open"

**"Nothing heard" error**
- Check that your default microphone is set in Windows Sound Settings
- Try increasing `SILENCE_THRESHOLD` in `core/voice_in.py` (default 0.01) if it cuts off too early, or decrease it if it doesn't stop

**TTS not speaking**
- Check your internet connection (Edge TTS uses Microsoft cloud)
- Check that audio output device is working

**Memory error on startup**
- Non-fatal — El Fager works fine without memory
- Usually means `sentence-transformers` didn't install correctly; try `pip install sentence-transformers --force-reinstall`

**`pygame` import error**
- Make sure you installed `pygame-ce`, not `pygame` (which has no Python 3.14 wheel)
- `pip uninstall pygame && pip install pygame-ce`

---

## Voices

TTS picks the best available backend: Groq Orpheus (neural, needs `GROQ_API_KEY`) with Edge TTS as the always-available fallback.

| Language | Orpheus (`.env` var) | Edge fallback (`.env` var) |
|---|---|---|
| English | `daniel` (`TTS_VOICE_EN`) | `en-US-GuyNeural` (`EDGE_VOICE_EN`) |

See the docstring in `core/voice_out.py` for all Orpheus voice options.
