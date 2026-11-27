import json
import shutil
import subprocess
import sys
import wave
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
STAGE = SCRIPT_DIR.parent
ROOT = STAGE.parent
IN = STAGE / "input"
OUT = STAGE / "output"
AUDIO_DIR = OUT / "audio"

sys.path.insert(0, str(ROOT / "app"))
import config

FULL_WAV = IN / "audio16k_full.wav"
PROC_WAV = AUDIO_DIR / "audio16k.wav"
OPUS = AUDIO_DIR / "voice_only_16k.opus"
MP3 = AUDIO_DIR / "voice_only_16k.mp3"
TAIL_SECONDS = float(config.get("outro", "tail_seconds", 2.0))
CONFIDENCE_THRESHOLD = float(config.get("outro", "confidence_threshold", 0.05))


def hhmmss(seconds):
    seconds = max(0, int(round(seconds)))
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


def run_ffmpeg(*args):
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args],
        check=True,
    )


def wav_duration(path):
    with wave.open(str(path), "rb") as fh:
        return fh.getnframes() / fh.getframerate()


def main():
    words = json.load(open(OUT / "whisper_words.json", encoding="utf-8"))
    if not words:
        raise SystemExit("no whisper words to compute speech end")

    confident = [w for w in words if float(w.get("probability", 0)) >= CONFIDENCE_THRESHOLD]
    speech_end = max(float(word["end"]) for word in (confident or words))

    if not FULL_WAV.exists():
        if not PROC_WAV.exists():
            raise SystemExit(f"missing source audio: {PROC_WAV}")
        shutil.copyfile(PROC_WAV, FULL_WAV)
        print(f"[trim] created {FULL_WAV.name} from {PROC_WAV.name}")

    duration = wav_duration(FULL_WAV)
    trim_end = min(speech_end + TAIL_SECONDS, duration)
    trimmed = (duration - trim_end) > 0.05

    if trimmed:
        run_ffmpeg(
            "-i", str(FULL_WAV), "-t", f"{trim_end:.3f}",
            "-c:a", "pcm_s16le", str(PROC_WAV),
        )
    else:
        shutil.copyfile(FULL_WAV, PROC_WAV)

    run_ffmpeg(
        "-i", str(FULL_WAV), "-t", f"{trim_end:.3f}",
        "-ac", "1", "-ar", "16000", "-c:a", "libopus", "-b:a", "24k", str(OPUS),
    )
    run_ffmpeg(
        "-i", str(FULL_WAV), "-t", f"{trim_end:.3f}",
        "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "32k", str(MP3),
    )

    metadata = {
        "speech_end": hhmmss(speech_end),
        "speech_end_seconds": round(speech_end, 3),
        "trim_end": hhmmss(trim_end),
        "trim_end_seconds": round(trim_end, 3),
        "trimmed": trimmed,
        "source": "input/audio16k_full.wav",
        "processing_wav": "output/audio/audio16k.wav",
    }
    with open(OUT / "metadata.json", "w", encoding="utf-8") as fh:
        json.dump(metadata, fh, indent=1)

    action = "trimmed" if trimmed else "no trim (speech runs to end)"
    print(
        f"[trim] speech_end={metadata['speech_end']} "
        f"trim_end={metadata['trim_end']} {action}"
    )


if __name__ == "__main__":
    main()
