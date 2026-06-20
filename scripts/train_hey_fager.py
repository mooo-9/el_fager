"""
Train a custom "Hey Fager" wake word model for El Fager.

Pipeline:
  1. Generate TTS audio of "Hey Fager" (positive) and other phrases (negative)
     using pyttsx3 Windows SAPI voices (no ffmpeg needed)
  2. Resample everything to 16kHz mono float32
  3. Run through openwakeword's mel+embedding pipeline → [frames, 96] per clip
  4. Build training samples: last 16-frame window per clip
  5. Train sklearn LogisticRegression
  6. Export as ONNX (input [1,16,96] → output [1,1]) matching openwakeword format
  7. Save to data/hey_fager.onnx

Run: python scripts/train_hey_fager.py
"""

import os, sys, time, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import scipy.signal
import scipy.io.wavfile as wavfile
import pyttsx3
import onnx
from onnx import helper, TensorProto, numpy_helper
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import classification_report
from openwakeword.model import Model

TARGET_RATE = 16000
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
OUTPUT_PATH = os.path.join(DATA_DIR, "hey_fager.onnx")


# ─── Audio generation ─────────────────────────────────────────────────────────

def _voices() -> list[str]:
    engine = pyttsx3.init()
    return [v.id for v in engine.getProperty("voices")
            if "en" in v.id.lower() or "english" in (v.name or "").lower()]


def _tts_to_wav(text: str, voice_id: str, rate: int = 150) -> np.ndarray | None:
    """Render text via pyttsx3 → resample to 16kHz float32 numpy array."""
    engine = pyttsx3.init()
    engine.setProperty("voice", voice_id)
    engine.setProperty("rate", rate)

    tmp = tempfile.mktemp(suffix=".wav")
    try:
        engine.save_to_file(text, tmp)
        engine.runAndWait()
        time.sleep(0.3)  # pyttsx3 can be async on Windows

        if not os.path.exists(tmp) or os.path.getsize(tmp) < 1000:
            return None

        orig_rate, data = wavfile.read(tmp)

        # Convert to float32 mono
        if data.ndim > 1:
            data = data.mean(axis=1)
        data = data.astype(np.float32)
        if data.dtype == np.float32 and data.max() > 1.0:
            data /= 32768.0
        elif data.max() > 1.0:
            data /= 32768.0

        # Resample to 16kHz
        if orig_rate != TARGET_RATE:
            gcd = np.gcd(TARGET_RATE, orig_rate)
            data = scipy.signal.resample_poly(data, TARGET_RATE // gcd, orig_rate // gcd)

        return data.astype(np.float32)

    except Exception as e:
        print(f"  [TTS error] {text!r} @ {voice_id}: {e}")
        return None
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def generate_samples() -> tuple[list[np.ndarray], list[np.ndarray]]:
    voices = _voices()
    if not voices:
        raise RuntimeError("No English voices found in pyttsx3. Check Windows TTS settings.")
    print(f"[Train] Found {len(voices)} voice(s).")

    POSITIVE = [
        # Hey Fager variants
        "Hey Fager", "hey fager", "Hey, Fager", "HEY FAGER",
        "Hey Fager!", "okay Fager", "Hey Fager are you there",
        "Hey Fager help me", "Hey Fager open Chrome",
        # Wake up Fager variants
        "Wake up Fager", "wake up fager", "Wake Up Fager",
        "wake up fager please", "Fager wake up",
        # Wake up Jarvis variants
        "Wake up Jarvis", "wake up jarvis", "Wake Up Jarvis",
        "wake up jarvis please", "Jarvis wake up",
    ]
    NEGATIVE = [
        "What time is it", "Open Chrome", "Set a reminder",
        "Hey Google what is the weather", "Hello there",
        "Hey Siri play music", "Alexa turn on the light",
        "OK Google search for news", "Tell me a joke",
        "What is on my calendar", "Good morning",
        "Turn off the lights", "Hey Cortana",
        "Search for restaurants nearby", "Call mom",
        "Play some music", "Read my emails",
        "How is the weather today", "Navigate home",
        "Set an alarm for seven AM",
    ]

    rates = [130, 150, 170]

    pos_clips, neg_clips = [], []

    print("[Train] Generating POSITIVE samples...")
    for phrase in POSITIVE:
        for vid in voices:
            for rate in rates:
                clip = _tts_to_wav(phrase, vid, rate)
                if clip is not None and len(clip) > TARGET_RATE * 0.2:
                    # Pad with 0.3s silence on both sides (simulates real conditions)
                    pad = np.zeros(int(TARGET_RATE * 0.3), dtype=np.float32)
                    pos_clips.append(np.concatenate([pad, clip, pad]))
                    sys.stdout.write(".")
                    sys.stdout.flush()
    print(f"\n[Train] {len(pos_clips)} positive clips")

    print("[Train] Generating NEGATIVE samples...")
    for phrase in NEGATIVE:
        for vid in voices:
            clip = _tts_to_wav(phrase, vid, 150)
            if clip is not None and len(clip) > TARGET_RATE * 0.2:
                neg_clips.append(clip)
                sys.stdout.write(".")
                sys.stdout.flush()
    # Also add pure silence clips as negatives
    for _ in range(10):
        neg_clips.append(np.zeros(TARGET_RATE * 2, dtype=np.float32))
        # (silence is float32 zeros — will be converted to int16 in extract_features)
    print(f"\n[Train] {len(neg_clips)} negative clips")

    return pos_clips, neg_clips


# ─── Feature extraction ───────────────────────────────────────────────────────

def extract_features(clips: list[np.ndarray], oww: Model, label: str) -> np.ndarray:
    """
    For each audio clip, run through openwakeword embedding pipeline.
    Returns an array of shape (N, 1536) — the last 16-embedding window per clip,
    flattened. The "last" window captures the moment right after the phrase ends.
    """
    features = []
    min_samples = TARGET_RATE * 1  # at least 1s of audio

    for i, clip in enumerate(clips):
        # Pad short clips
        if len(clip) < min_samples:
            clip = np.concatenate([clip, np.zeros(min_samples - len(clip), dtype=np.float32)])

        # Normalise amplitude
        peak = np.abs(clip).max()
        if peak > 0:
            clip = clip / peak * 0.7

        # embed_clips expects int16 shape (N, samples) — wrap in batch of 1
        clip_int16 = (clip * 32767.0).clip(-32768, 32767).astype(np.int16)
        try:
            embs = oww.preprocessor.embed_clips(clip_int16[np.newaxis, :], batch_size=1)
            # embs shape: (1, frames, 96)
            emb_seq = embs[0]  # (frames, 96)

            if emb_seq.shape[0] < 16:
                # Pad with zeros at front
                pad = np.zeros((16 - emb_seq.shape[0], 96), dtype=np.float32)
                emb_seq = np.vstack([pad, emb_seq])

            # Take the last window of 16 embeddings (when the phrase has just been spoken)
            window = emb_seq[-16:, :]  # (16, 96)
            features.append(window.flatten())  # 1536-dim
        except Exception as e:
            print(f"\n  [Feature error] {label} clip {i}: {e}")
            continue

        if (i + 1) % 20 == 0:
            print(f"  [{label}] {i+1}/{len(clips)} done")

    return np.array(features, dtype=np.float32)


# ─── ONNX model construction ──────────────────────────────────────────────────

def build_onnx_model(weights: np.ndarray, bias: float,
                     scaler_mean: np.ndarray, scaler_scale: np.ndarray) -> onnx.ModelProto:
    """
    Build an ONNX model that matches openwakeword's expected I/O:
      Input:  "x.1"  shape [1, 16, 96]  float32
      Output: "53"   shape [1, 1]        float32

    The graph:
      Reshape([1,16,96] → [1,1536]) → Standardize → MatMul → Add → Sigmoid
    """
    W = weights.astype(np.float32).reshape(1536, 1)
    b = np.array([bias], dtype=np.float32)
    mean = scaler_mean.astype(np.float32).reshape(1, 1536)
    scale = scaler_scale.astype(np.float32).reshape(1, 1536)

    shape_init = numpy_helper.from_array(np.array([1, 1536], dtype=np.int64), name="reshape_shape")
    mean_init  = numpy_helper.from_array(mean,  name="scaler_mean")
    scale_init = numpy_helper.from_array(scale, name="scaler_scale")
    W_init     = numpy_helper.from_array(W,     name="lr_weight")
    b_init     = numpy_helper.from_array(b,     name="lr_bias")

    # Nodes
    reshape = helper.make_node("Reshape",  inputs=["x.1", "reshape_shape"], outputs=["flat"])
    sub     = helper.make_node("Sub",      inputs=["flat", "scaler_mean"],   outputs=["centered"])
    div     = helper.make_node("Div",      inputs=["centered", "scaler_scale"], outputs=["scaled"])
    matmul  = helper.make_node("MatMul",   inputs=["scaled", "lr_weight"],   outputs=["logit"])
    add     = helper.make_node("Add",      inputs=["logit", "lr_bias"],      outputs=["logit_b"])
    sigmoid = helper.make_node("Sigmoid",  inputs=["logit_b"],               outputs=["53"])

    input_info  = helper.make_tensor_value_info("x.1", TensorProto.FLOAT, [1, 16, 96])
    output_info = helper.make_tensor_value_info("53",  TensorProto.FLOAT, [1, 1])

    graph = helper.make_graph(
        [reshape, sub, div, matmul, add, sigmoid],
        "hey_fager",
        [input_info],
        [output_info],
        initializer=[shape_init, mean_init, scale_init, W_init, b_init],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 7
    onnx.checker.check_model(model)
    return model


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    print("[Train] Loading openwakeword embedding pipeline...")
    oww = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")

    print("[Train] Generating audio samples (this takes 1-2 minutes)...")
    pos_clips, neg_clips = generate_samples()

    if len(pos_clips) < 5:
        print("[Train] ERROR: too few positive clips — check pyttsx3 setup.")
        sys.exit(1)

    print("[Train] Extracting features from positive clips...")
    X_pos = extract_features(pos_clips, oww, "POS")
    print("[Train] Extracting features from negative clips...")
    X_neg = extract_features(neg_clips, oww, "NEG")

    print(f"[Train] Positive features: {X_pos.shape}")
    print(f"[Train] Negative features: {X_neg.shape}")

    X = np.vstack([X_pos, X_neg])
    y = np.array([1] * len(X_pos) + [0] * len(X_neg))

    # Standardise
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Train
    print("[Train] Training LogisticRegression...")
    clf = LogisticRegression(C=1.0, class_weight="balanced", max_iter=2000, solver="lbfgs")
    clf.fit(X_scaled, y)

    preds = clf.predict(X_scaled)
    print("\n[Train] Training set report:")
    print(classification_report(y, preds, target_names=["negative", "hey_fager"]))

    # Build and save ONNX
    print("[Train] Building ONNX model...")
    onnx_model = build_onnx_model(
        weights=clf.coef_[0],
        bias=float(clf.intercept_[0]),
        scaler_mean=scaler.mean_,
        scaler_scale=scaler.scale_,
    )
    onnx.save(onnx_model, OUTPUT_PATH)
    print(f"[Train] Saved: {OUTPUT_PATH}")

    # Quick smoke test
    import onnxruntime as ort
    sess = ort.InferenceSession(OUTPUT_PATH, providers=["CPUExecutionProvider"])
    dummy = np.zeros((1, 16, 96), dtype=np.float32)
    score = sess.run(None, {"x.1": dummy})[0]
    print(f"[Train] Smoke test (silence -> score): {score[0][0]:.4f}  (expect ~0)")

    print("\n[Train] Done! Add to .env:")
    print("  WAKE_WORD_MODEL=hey_jarvis,data/hey_fager.onnx")


if __name__ == "__main__":
    main()
