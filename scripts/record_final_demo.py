#!/usr/bin/env python3
"""Build the narrated, multi-page Issue2Proof submission demo."""

import asyncio
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "submission" / ".final-video"
OUTPUT = ROOT / "submission" / "final-demo.mp4"

SEGMENTS = [
    {
        "name": "01-overview", "page": "demo/index.html", "chapter": "The idea", "duration": 18,
        "lines": [
            (0.5, "Coding agents can already edit code and run tests."),
            (5.0, "Issue Two Proof is regression memory for AI coding agents that survives the agent."),
            (11.0, "It turns a repaired failure into evidence that can be recalled and executed again."),
        ],
        "actions": [(2, "move", 1080, 330), (8, "scroll", ".story-section"), (12, "move", 1040, 430)],
    },
    {
        "name": "02-memory", "page": "demo/memory.html", "chapter": "The novelty", "duration": 20,
        "lines": [
            (0.5, "Repository rules and agent memory preserve useful guidance."),
            (6.0, "A Memory Capsule adds the behavioral claim, frozen regression, hashes, assumptions, boundaries, and sandbox provenance."),
            (14.0, "It is executable, hash-backed evidence rather than an unverified note."),
        ],
        "actions": [(2, "move", 1450, 350), (7, "scroll", ".capsule-anatomy"), (10, "move", 980, 510), (15, "scroll", ".timeline-panel")],
    },
    {
        "name": "03-workspace", "page": "demo/workspace.html", "chapter": "Working product", "duration": 42,
        "lines": [
            (0.5, "A failure arrives from GitHub or a repository zip, with the behavior that should remain true."),
            (8.5, "The original revision must fail the frozen regression before a repair can be trusted."),
            (16.5, "A candidate is accepted only after the regression, existing suite, and independent boundaries pass."),
            (25.0, "The completed evidence becomes a versioned Memory Capsule."),
            (32.0, "A later refactor recalls the same claim and regression hash before code changes begin."),
        ],
        "actions": [(2, "move", 310, 520), (5, "click", "a[href='#werkzeug-demo']"), (9, "move", 1100, 320), (18, "click_text", "Create executable Memory Capsule"), (23, "move", 1180, 420), (29, "click", "#search-memory"), (33, "click", ".memory-card"), (36, "move", 1050, 590)],
    },
    {
        "name": "05-evidence", "page": "demo/evidence.html", "chapter": "Measured impact", "duration": 24,
        "lines": [
            (0.5, "In thirty blind Nemotron refactor trials across two real bug histories, eight changes reintroduced the historical failure."),
            (8.5, "Plain visible C I caught three. Capsule replay caught all eight."),
            (14.0, "Nano indexes memory, Qwen retrieves meaning, Super handles engineering, and Ultra is reserved for escalated high-risk uncertainty."),
        ],
        "actions": [(2, "move", 1480, 380), (7, "scroll", ".benchmark-panel"), (10, "move", 1400, 440), (15, "scroll", ".model-routing"), (18, "move", 1290, 540)],
    },
    {
        "name": "06-close", "page": "demo/evidence.html", "chapter": "The boundary", "duration": 18,
        "lines": [
            (0.5, "A passing replay is not universal correctness."),
            (5.0, "It means the selected frozen behavior passed in the recorded environment."),
            (11.0, "Git records what changed. Issue Two Proof preserves why the behavior must keep working, and checks it again."),
        ],
        "actions": [(1, "scroll", ".limitations"), (4, "move", 1280, 470), (10, "page", "demo/index.html"), (13, "move", 760, 320)],
    },
]


def run(command):
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def set_caption(page, text):
    await page.evaluate("value => window.videoDemo.caption(value)", text)


async def perform(page, action):
    kind = action[1]
    frame = page.frames[1]
    if kind == "move":
        await page.evaluate("p => window.videoDemo.move(p[0],p[1])", [action[2], action[3]])
    elif kind == "scroll":
        await frame.locator(action[2]).scroll_into_view_if_needed()
    elif kind == "click":
        await frame.locator(action[2]).first.click()
    elif kind == "click_text":
        await frame.get_by_text(action[2], exact=True).click()
    elif kind == "page":
        await page.evaluate("value => window.videoDemo.page(value)", action[2])
        await page.wait_for_timeout(1_200)


async def capture_segment(browser, segment):
    video_dir = WORK / segment["name"]
    video_dir.mkdir(parents=True, exist_ok=True)
    context = await browser.new_context(
        viewport={"width": 1920, "height": 1080}, record_video_dir=str(video_dir),
        record_video_size={"width": 1920, "height": 1080}, device_scale_factor=1,
    )
    page = await context.new_page()
    url = "http://127.0.0.1:8765/submission/final-video-shell.html?" + \
        f"page={segment['page']}&chapter={segment['chapter']}"
    await page.goto(url, wait_until="networkidle")
    await page.wait_for_timeout(800)
    timeline = [(at, "caption", text) for at, text in segment["lines"]] + segment["actions"]
    timeline.sort(key=lambda item: item[0])
    start = time.monotonic()
    for item in timeline:
        await page.wait_for_timeout(max(0, int((start + item[0] - time.monotonic()) * 1000)))
        if item[1] == "caption":
            await set_caption(page, item[2])
        else:
            await perform(page, item)
    await page.wait_for_timeout(max(0, int((start + segment["duration"] - time.monotonic()) * 1000)))
    video = page.video
    await context.close()
    return Path(await video.path())


def narrate(segment, video_source):
    base = WORK / segment["name"]
    video_only = base / "video.mp4"
    run(["ffmpeg", "-y", "-i", str(video_source), "-t", str(segment["duration"]), "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", str(video_only)])
    voice_inputs, filters = [], []
    for index, (at, sentence) in enumerate(segment["lines"]):
        text_file, wave_file = base / f"voice-{index}.txt", base / f"voice-{index}.wav"
        text_file.write_text(sentence)
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"flite=textfile={text_file}:voice=slt", "-af", "atempo=1.03", "-ar", "48000", "-ac", "1", str(wave_file)])
        voice_inputs.extend(["-i", str(wave_file)])
        delay = int(at * 1000)
        filters.append(f"[{index + 1}:a]adelay={delay}|{delay}[a{index}]")
    inputs = "".join(f"[a{i}]" for i in range(len(segment["lines"])))
    graph = ";".join(filters) + f";{inputs}amix=inputs={len(segment['lines'])}:normalize=0[aout]"
    output = WORK / f"{segment['name']}.mp4"
    run(["ffmpeg", "-y", "-i", str(video_only), *voice_inputs, "-filter_complex", graph, "-map", "0:v", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-t", str(segment["duration"]), str(output)])
    return output


async def build():
    browser_cache = Path("/tmp/issue2proof-playwright")
    ffmpeg_dir = browser_cache / "ffmpeg-1011"
    ffmpeg_dir.mkdir(parents=True, exist_ok=True)
    link = ffmpeg_dir / "ffmpeg-linux"
    if not link.exists():
        link.symlink_to("/usr/bin/ffmpeg")
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browser_cache)
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir()
    server = subprocess.Popen([sys.executable, "-m", "http.server", "8765", "--bind", "127.0.0.1"], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(0.5)
        outputs = []
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox", "--disable-dev-shm-usage"])
            for segment in SEGMENTS:
                outputs.append(narrate(segment, await capture_segment(browser, segment)))
            await browser.close()
        outputs.insert(3, ROOT / "submission" / "codex-mcp-demo.mp4")
        concat = WORK / "concat.txt"
        concat.write_text("".join(f"file '{path}'\n" for path in outputs))
        run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(OUTPUT)])
    finally:
        server.terminate()
        server.wait(timeout=5)
        shutil.rmtree(WORK, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(build())
