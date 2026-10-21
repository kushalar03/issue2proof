"""Build stable, chapter-aligned narration and captions for the demo recording."""

import json
import os
import subprocess
from pathlib import Path

import soundfile as sf
from kokoro_onnx import Kokoro

ROOT = Path(__file__).resolve().parents[1]
SUBMISSION = ROOT / "submission"
DEMO_DURATION = 92.1
SEGMENTS = [
    (0.20, 1.20, "Issue Two Proof.", "Issue Two Proof."),
    (
        1.65,
        8.10,
        "Regression memory for AI coding agents that survives the agent. Rules store guidance; Issue2Proof stores executable, hash-backed evidence.",
        "Regression memory for A. I. coding agents that survives the agent. Rules store guidance. Issue Two Proof stores executable, hash-backed evidence.",
    ),
    (
        8.65,
        19.40,
        "Install Issue2Proof as two MCP tools in Claude Code, Cursor, Codex-compatible hosts, or other AI platforms: recall before editing, then audit the revision.",
        "Install Issue Two Proof as two M. C. P. tools in Claude Code; Cursor; Codex-compatible hosts; or other A. I. platforms. Recall before editing. Then audit the revision.",
    ),
    (
        19.90,
        32.25,
        "Here is a working example, not a mock-up. I open recorded evidence from a real Werkzeug repair. The original failure was reproduced, and the candidate passed the frozen, existing, and independent checks.",
        "Here is a working example — not a mock-up. I open recorded evidence from a real Verk-tsoyk repair. First, the original failure was reproduced. Then, the candidate passed the frozen regression, the existing tests, and the independent tests.",
    ),
    (
        32.75,
        45.60,
        "I select Create Executable Memory Capsule. The verified repair becomes a versioned record containing the behavioral claim, affected file, model index, sandbox evidence, frozen regression, and known boundaries.",
        "I select: Create Executable Memory Capsule. The verified repair becomes a versioned record. It contains the behavioral claim; the affected file; the model index; the Nebius Sandbox evidence; the frozen regression; and the known boundaries.",
    ),
    (
        46.10,
        63.00,
        "Before a later agent changes Windows path handling, I describe that proposed change and search memory. Issue Two Proof recalls the relevant device-name contract and shows the evidence and limitations the new agent must preserve.",
        "Before a later agent changes Windows path handling, I describe the proposed change, and search memory. Issue Two Proof recalls the relevant Windows device-name contract. It also shows the evidence, and the limitations, that the new agent must preserve.",
    ),
    (
        63.55,
        86.35,
        "Finally, I open the completed audit. Fresh, network-disabled Nebius Sandboxes replayed the historical regression against the proposed revision and observed a real memory conflict. Nemotron Super explains the high-risk cause and next experiment. Because the evidence is risky, Nemotron Ultra is called only for final adjudication.",
        "Finally, I open the completed audit. Fresh, network-disabled, Nebius Sandboxes replayed the historical regression against the proposed revision. They observed a real memory conflict. Nem-o-tron Super explains the high-risk cause, and the next experiment. Because the evidence is risky, Nem-o-tron Ultra is called only for final adjudication.",
    ),
    (
        86.80,
        91.85,
        "The result is shared engineering memory that follows every coding agent and protects every future change.",
        "The result is shared engineering memory. It follows every coding agent, and protects every future change.",
    ),
]


def run(*args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def duration(path):
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(json.loads(result.stdout)["format"]["duration"])


def srt_time(value):
    millis = round(value * 1000)
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    seconds, millis = divmod(millis, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"


def main():
    model = Path(os.environ.get("KOKORO_MODEL", "/tmp/kokoro-model/kokoro-v1.0.onnx"))
    voices = Path(os.environ.get("KOKORO_VOICES", "/tmp/kokoro-model/voices-v1.0.bin"))
    if not model.exists() or not voices.exists():
        raise SystemExit("Set KOKORO_MODEL and KOKORO_VOICES to the Kokoro v1 model files.")
    kokoro = Kokoro(str(model), str(voices))
    build = SUBMISSION / "demo-voice-segments"
    build.mkdir(exist_ok=True)
    inputs = []
    filters = []
    captions = []
    narration = []
    spoken_narration = []
    for index, (start, end, caption, spoken) in enumerate(SEGMENTS):
        synth_path = build / f"{index:02}-synth.wav"
        raw_path = build / f"{index:02}-raw.wav"
        voice_path = build / f"{index:02}.wav"
        if os.environ.get("REUSE_DEMO_VOICE") != "1" or not synth_path.exists():
            samples, sample_rate = kokoro.create(
                spoken,
                voice="am_michael",
                speed=0.98,
                lang="en-us",
            )
            sf.write(synth_path, samples, sample_rate)
        run(
            "ffmpeg",
            "-y",
            "-i",
            str(synth_path),
            "-af",
            "highpass=f=75,lowpass=f=10500,loudnorm=I=-18:LRA=5:TP=-2",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(raw_path),
        )
        available = end - start - 0.25
        raw_duration = duration(raw_path)
        tempo = max(1.0, raw_duration / available)
        run(
            "ffmpeg",
            "-y",
            "-i",
            str(raw_path),
            "-af",
            f"atempo={tempo:.6f},afade=t=in:st=0:d=0.08,afade=t=out:st={min(available, raw_duration / tempo) - .12:.3f}:d=0.1",
            str(voice_path),
        )
        inputs.extend(["-i", str(voice_path)])
        delay = round(start * 1000)
        filters.append(f"[{index}:a]adelay={delay}|{delay}[a{index}]")
        captions.append(f"{index + 1}\n{srt_time(start)} --> {srt_time(end)}\n{caption}\n")
        narration.append(caption)
        spoken_narration.append(spoken)

    mixed = ";".join(filters) + ";" + "".join(
        f"[a{index}]" for index in range(len(SEGMENTS))
    ) + f"amix=inputs={len(SEGMENTS)}:duration=longest:normalize=0,apad=whole_dur={DEMO_DURATION}[out]"
    run(
        "ffmpeg",
        "-y",
        *inputs,
        "-filter_complex",
        mixed,
        "-map",
        "[out]",
        "-t",
        str(DEMO_DURATION),
        "-ar",
        "48000",
        "-ac",
        "2",
        str(SUBMISSION / "memory-demo-voice.wav"),
    )
    (SUBMISSION / "memory-demo.srt").write_text("\n".join(captions))
    (SUBMISSION / "memory-demo-narration.txt").write_text("\n\n".join(narration) + "\n")
    (SUBMISSION / "memory-demo-voice.txt").write_text("\n".join(spoken_narration) + "\n")


if __name__ == "__main__":
    main()
