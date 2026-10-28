#!/usr/bin/env python3
"""Replace demo narration with a natural Kokoro ONNX voice.

Install ``kokoro-onnx`` and ``soundfile``, then download ``kokoro-v1.0.onnx``
and ``voices-v1.0.bin`` from the ``model-files-v1.1`` release at
https://github.com/thewh1teagle/kokoro-onnx/releases. Set ``KOKORO_MODEL`` and
``KOKORO_VOICES`` to those paths before running this script. The model files
remain outside the repository and are not included in releases.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import soundfile as sf
from kokoro_onnx import Kokoro

ROOT = Path(__file__).resolve().parents[1]
SUBMISSION = ROOT / "submission"
VOICE = os.environ.get("KOKORO_VOICE", "af_heart")
MODEL = Path(os.environ["KOKORO_MODEL"])
VOICES = Path(os.environ["KOKORO_VOICES"])

MCP_LINES = [
    (0.5, "Codex asks Issue Two Proof for the repository's verified behavioral memory."),
    (5.3, "The recall tool returns the behavioral claim — and the exact frozen regression, S. H. A. two fifty-six hash."),
    (12.2, "Codex submits the current local revision through the second M. C. P. tool."),
    (18.8, "Issue Two Proof replays the capsule in a fresh, bounded Nebius Sandbox."),
    (24.8, "The assertion violates the recalled contract. So the verdict is: memory conflict."),
    (31.0, "The result preserves hashes, operation I.D.s, image identity, execution limits, and network-disabled provenance."),
]

FINAL_LINES = [
    (0.5, "Coding agents can already edit code — and run tests."),
    (5.0, "Issue Two Proof is regression memory for A.I. coding agents. It survives the agent."),
    (11.0, "It turns a repaired failure into evidence that can be recalled — and executed again."),
    (18.5, "Repository rules and agent memory preserve useful guidance."),
    (24.0, "A Memory Capsule adds the behavioral claim, frozen regression, hashes, assumptions, boundaries, and sandbox provenance."),
    (32.0, "It is executable, hash-backed evidence — rather than an unverified note."),
    (38.5, "A failure arrives from GitHub, or a repository zip, with the behavior that should remain true."),
    (46.5, "The original revision must fail the frozen regression before a repair can be trusted."),
    (54.5, "A candidate is accepted only after the regression, existing suite, and independent boundaries pass."),
    (63.0, "The completed evidence becomes a versioned Memory Capsule."),
    (70.0, "A later refactor recalls the same claim — and regression hash — before code changes begin."),
    (75.2, "The browser is only one client. The same evidence is available through M. C. P."),
    *[(80.0 + at, text) for at, text in MCP_LINES],
    (119.78, "In thirty blind Nemotron refactor trials, across two real bug histories, eight changes reintroduced the historical failure."),
    (127.78, "Plain visible C.I. caught three. Capsule replay caught all eight."),
    (133.28, "Nano indexes memory. Qwen retrieves meaning. Super handles engineering. And Ultra is reserved for escalated, high-risk uncertainty."),
    (143.78, "A passing replay is not universal correctness."),
    (148.28, "It means the selected, frozen behavior passed in the recorded environment."),
    (154.28, "Git records what changed. Issue Two Proof preserves why the behavior must keep working — and checks it again."),
]


def run(command):
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def synthesize(kokoro, lines, video, output, duration, work):
    work.mkdir(parents=True, exist_ok=True)
    inputs = []
    filters = []
    for index, (at, text) in enumerate(lines):
        samples, sample_rate = kokoro.create(
            text,
            voice=VOICE,
            speed=1.02,
            lang="en-us",
            sentence_pause=0.22,
            clause_pause=0.11,
        )
        wave = work / f"voice-{index:02d}.wav"
        sf.write(wave, samples, sample_rate)
        inputs.extend(["-i", str(wave)])
        delay = int(at * 1000)
        filters.append(f"[{index + 1}:a]adelay={delay}|{delay}[a{index}]")
    labels = "".join(f"[a{i}]" for i in range(len(lines)))
    graph = (
        ";".join(filters)
        + f";{labels}amix=inputs={len(lines)}:normalize=0,"
        "highpass=f=65,lowpass=f=13500,"
        "acompressor=threshold=-20dB:ratio=2:attack=15:release=160:makeup=1.5,"
        "loudnorm=I=-16:TP=-1.5:LRA=7[aout]"
    )
    temporary = work / output.name
    run(
        [
            "ffmpeg", "-y", "-i", str(video), *inputs,
            "-filter_complex", graph, "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-t", str(duration), "-movflags", "+faststart", str(temporary),
        ]
    )
    shutil.move(temporary, output)


def main():
    kokoro = Kokoro(str(MODEL), str(VOICES))
    with tempfile.TemporaryDirectory(prefix="issue2proof-neural-voice-") as directory:
        work = Path(directory)
        synthesize(
            kokoro,
            MCP_LINES,
            SUBMISSION / "codex-mcp-demo.mp4",
            SUBMISSION / "codex-mcp-demo.mp4",
            39.28,
            work / "mcp",
        )
        synthesize(
            kokoro,
            FINAL_LINES,
            SUBMISSION / "final-demo.mp4",
            SUBMISSION / "final-demo.mp4",
            161.36,
            work / "final",
        )


if __name__ == "__main__":
    main()
