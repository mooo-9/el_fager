# El Fager — UI/UX Design Brief (for Fable 5 via Claude Design 2.0)

> Paste everything below the line into Claude Design 2.0. It is written as a
> single self-contained brief so Fable 5 has full context and maximum creative
> latitude. You are the **designer**, not the implementer — invent the design
> language, don't just decorate the existing one.

---

## Your role

You are the lead product designer for **El Fager**, a voice-first personal AI
assistant that lives on a Windows desktop. I want you to design its entire
visual and interaction language **from a blank page**. Treat this as a real
design engagement: form your own point of view, make the hard calls yourself,
and deliver complete, buildable design specs. **Do not ask me to make design
decisions you can make with taste** — palette, type, motion, spacing, component
anatomy, states are all yours. Where a genuine product tradeoff exists, state
your recommendation and why, then move on.

Be creative. Be opinionated. I would rather see one distinctive, coherent
design with a strong personality than a safe committee design. Surprise me — but
every creative choice must serve the product, not fight it.

## What El Fager is

**El Fager** (Arabic: الفجر, "the dawn") is a Jarvis-style AI operating layer
for one power user. It is **voice-first**: the primary way to use it is to press
Ctrl+Space or say "hey Fager," speak, and get a spoken answer streamed back as
it thinks. Typing is the secondary path. It is always running in the system
tray, ambient and mostly invisible until summoned.

It is **agentic** — it doesn't just chat, it *acts*: reads and drafts Gmail,
sends WhatsApp messages, manages a calendar and Todoist tasks, reads the news,
analyzes what's on screen, drives a browser, tracks health/nutrition, remembers
facts about its user, learns habits, and runs proactive routines (morning
briefing, evening shutdown, focus mode, gym mode). Every outbound action goes
through a **stage → preview → confirm** flow so nothing is sent without a look.

It is **bilingual**: fluent English and Egyptian Arabic, often mixed in the same
sentence (code-switching). The design must feel native in **both LTR English and
RTL Arabic**, including Arabic typography that looks intentional, not bolted on.

The user, **Mo**, is a young, technical, fast-moving Egyptian power user. He
values **speed above almost everything** (every interaction should feel
instant), density of real information over decoration, and a product that feels
like a private, high-end piece of personal technology — not a consumer chatbot.
Think "the assistant a sci-fi protagonist would actually own": calm, precise,
alive, a little cinematic, never toy-like or corporate.

## The surfaces you're designing

Design a **single coherent design system**, then apply it to each surface. The
surfaces differ in size and density but must feel like one product.

1. **The Overlay (primary surface).** A small floating card that appears
   instantly on Ctrl+Space, anchored near the cursor / screen edge. Contains:
   the live conversation (user + assistant message bubbles), a **state
   indicator** that shows what the assistant is doing right now, a live
   transcript line while listening, and a text input as the fallback to voice.
   It must read at a glance and disappear cleanly. This is what Mo sees 50× a
   day — it has to be beautiful *and* fast to parse.

2. **The Command Center (dashboard).** A larger "today at a glance" window: a
   greeting + daily briefing, then data cards — **calendar** (today's events),
   **tasks** (top Todoist items), **mail** (unread/priority summary), **news**
   (brief), and **health** (a calorie ring + macro bars + trend sparklines).
   Plus one global command bar (type or talk) at the bottom that runs the same
   brain. Design the card system, the information hierarchy, the health data-viz,
   and how "learned facts / active skills / proposed automations" surface here so
   the "it's getting to know me" promise is *visible*.

3. **The full-screen HUD (ambient/cinematic mode).** An optional immersive view
   — the "cockpit." This is where you can be most expressive: a living
   representation of the assistant (an orb, waveform, particle field, reactive
   geometry — your call) that responds to voice and state, surrounded by ambient
   readouts. It's shown occasionally, so it can be richer and more animated than
   the everyday surfaces.

4. **The phone dashboard (companion web view).** A responsive web page Mo opens
   on his phone showing the same "today" data. Design it as a first-class mobile
   surface, not a shrunk desktop.

## The core design problem to solve

Right now El Fager has **two competing color identities** that don't belong to
the same product: a **warm copper** accent (`#E39660`) on a layered dark card
for the overlay, and a cold **"JARVIS cyan"** (`#38E0FF`) on near-black for the
command center. **Resolve this.** Decide the *one* soul of El Fager's color and
light, and make every surface obey it. You may keep warmth, go cold, or invent
something neither — but justify it and apply it system-wide. (For reference, the
name means *dawn* — there may be something there. Or not. Your call.)

## The assistant's "states" — the heart of the interaction

Because it's voice-first, the single most important UI element is **showing what
the assistant is doing**. There are five states, and each needs its own
instantly-readable visual language (color, motion, shape):

- **idle** — ambient, resting, waiting to be summoned
- **listening** — actively hearing the user (mic open, transcribing)
- **processing / thinking** — the model is working / calling tools
- **speaking** — audio is streaming out (TTS)
- **error** — something failed

Design these as a coherent *set*. The state should be legible from across the
room in the HUD and in a 4px detail in the overlay. Motion is central here —
specify the idle breathing, the listening reaction to voice amplitude, the
thinking pulse, the speaking rhythm, and the transitions between them.

## Technical reality (so your design is buildable)

- Built in **Python + PyQt6** (native Qt widgets), styled with Qt Style Sheets
  (a CSS-like subset — no CSS grid/flex, no web animations; custom visuals are
  hand-painted with QPainter). A few rich panels use **QWebEngine** (real
  HTML/CSS/JS) loaded lazily.
- So: give me **two tiers of spec.** (a) A platform-agnostic design system
  (tokens, type scale, spacing, radii, elevation, motion curves, component
  anatomy) that any engineer can implement. (b) Notes on what's cheap vs.
  expensive in Qt vs. the web panels, so the ambitious motion lands in the HUD /
  web surfaces and the everyday native surfaces stay instant. **Speed is a
  feature** — nothing on the summon path can be heavy.
- Dark is the default and the identity. Consider whether a light theme is even
  desirable (I lean no, but argue it).
- Windows 11 is the host OS — it can sit alongside Fluent/Mica, or deliberately
  ignore it. Your choice, but be deliberate.

## What I want delivered

Produce a complete, usable design package. At minimum:

1. **Design language / mood** — the concept in a few sentences + the feeling.
   What is El Fager's personality made visible?
2. **Color system** — full palette with hex + roles (surfaces, text tiers,
   accent(s), the 5 state colors, semantic ok/warn/bad), in tokens. Resolve the
   copper-vs-cyan conflict explicitly.
3. **Typography** — families (with an Arabic/RTL plan), scale, weights, usage.
4. **Spacing, radii, elevation, borders, grid** — the structural tokens.
5. **Motion system** — durations, easing curves, the state animations, and the
   HUD "living assistant" concept described concretely enough to build.
6. **Component library** — message bubbles, the state indicator, command/input
   bar, data cards, chips, buttons, the calorie ring + macro bars + sparklines,
   the stage→preview→confirm action card, scrollbars, dialogs. Give anatomy +
   states for each.
7. **Per-surface layouts** — overlay, command center, HUD, phone dashboard.
   Wireframe-level layout + how the system applies to each. Show the RTL Arabic
   variant of at least one surface.
8. **Rationale** — short "why" behind the big decisions and the tradeoffs you weighed.

Render the visual concepts (palettes, type specimens, component sheets, surface
mockups, state/motion studies) so I can see them, not just read them. Make it
beautiful. Take real creative swings — I want El Fager to have a face people
remember.
