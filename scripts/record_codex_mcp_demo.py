#!/usr/bin/env python3
"""Record the evidence-backed Codex MCP walkthrough at 1920x1080."""

import asyncio
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "submission" / "codex-mcp-demo.mp4"
VIDEO_DIR = ROOT / "submission" / ".codex-mcp-video"
NARRATION = [
    (500, "Codex asks Issue Two Proof for the repository's verified behavioral memory."),
    (5_300, "The recall tool returns the behavioral claim and the exact frozen regression hash."),
    (12_200, "Codex submits the current local revision through the second M C P tool."),
    (18_800, "Issue Two Proof replays the capsule in a fresh, bounded Nebius Sandbox."),
    (24_800, "The assertion violates the recalled contract, so the verdict is memory conflict."),
    (31_000, "The result preserves hashes, operation I D's, image identity, limits, and network-disabled provenance."),
]


async def record() -> None:
    browser_cache = Path("/tmp/issue2proof-playwright")
    ffmpeg_dir = browser_cache / "ffmpeg-1011"
    ffmpeg_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg_link = ffmpeg_dir / "ffmpeg-linux"
    if not ffmpeg_link.exists():
        ffmpeg_link.symlink_to("/usr/bin/ffmpeg")
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browser_cache)
    VIDEO_DIR.mkdir(exist_ok=True)
    server = subprocess.Popen(
        [sys.executable, "-m", "http.server", "8765", "--bind", "127.0.0.1"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(0.5)
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                executable_path="/usr/bin/chromium",
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                record_video_dir=str(VIDEO_DIR),
                record_video_size={"width": 1920, "height": 1080},
                device_scale_factor=1,
            )
            page = await context.new_page()
            await page.goto(
                "http://127.0.0.1:8765/submission/codex-mcp-recording.html",
                wait_until="networkidle",
            )
            await page.wait_for_timeout(38_000)
            video = page.video
            await context.close()
            await browser.close()
            source = Path(await video.path())
        video_only = VIDEO_DIR / "video-only.mp4"
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(source), "-an", "-c:v", "libx264",
                "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", str(video_only),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        voice_inputs = []
        filters = []
        for index, (delay_ms, sentence) in enumerate(NARRATION):
            text_file = VIDEO_DIR / f"voice-{index}.txt"
            wave_file = VIDEO_DIR / f"voice-{index}.wav"
            text_file.write_text(sentence)
            subprocess.run(
                [
                    "ffmpeg", "-y", "-f", "lavfi", "-i",
                    f"flite=textfile={text_file}:voice=rms", "-af", "atempo=0.98",
                    "-ar", "48000", "-ac", "1", str(wave_file),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            voice_inputs.extend(["-i", str(wave_file)])
            filters.append(f"[{index + 1}:a]adelay={delay_ms}|{delay_ms}[a{index}]")
        inputs = "".join(f"[a{i}]" for i in range(len(NARRATION)))
        filter_graph = (
            ";".join(filters)
            + f";{inputs}amix=inputs={len(NARRATION)}:normalize=0,"
            "highpass=f=70,lowpass=f=12000,"
            "acompressor=threshold=-18dB:ratio=2.5:attack=20:release=180:makeup=2,"
            "loudnorm=I=-16:TP=-1.5:LRA=5[aout]"
        )
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(video_only), *voice_inputs,
                "-filter_complex", filter_graph, "-map", "0:v", "-map", "[aout]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
                "-t", "39.2", "-movflags", "+faststart", str(OUTPUT),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    finally:
        server.terminate()
        server.wait(timeout=5)
        shutil.rmtree(VIDEO_DIR, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(record())
