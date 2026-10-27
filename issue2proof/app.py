import io
import json
import os
import sqlite3
import uuid
import zipfile
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .access import (
    COOKIE,
    authorized,
    configured_token,
    guard,
    login,
    validate_configuration,
)
from .draft import generate_draft
from .engine import run_demo
from .execution import verify_repository
from .fixtures import CASES
from .jobs import Worker
from .provider import DEFAULT_MODEL
from .repair import run_repair
from .repository import MAX_ARCHIVE, inspect_archive
from .settings import load_environment

load_environment()


@asynccontextmanager
async def lifespan(app):
    validate_configuration()
    worker = Worker() if os.environ.get("ISSUE2PROOF_WORKER", "1") == "1" else None
    if worker:
        worker.start()
    yield
    if worker:
        worker.close()


app = FastAPI(title="Issue2Proof", version="2.0.0", lifespan=lifespan)
app.middleware("http")(guard)
STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@contextmanager
def connection():
    db = sqlite3.connect(os.environ.get("ISSUE2PROOF_DB", "runs.sqlite3"), timeout=10)
    db.execute(
        "CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, created_at TEXT, report TEXT)"
    )
    try:
        with db:
            yield db
    finally:
        db.close()


class RunRequest(BaseModel):
    case: Literal["repair", "reject", "unresolved", "ambiguous"] = "reject"
    mode: Literal["demo", "remote"] = "demo"


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health(request: Request):
    return {
        "status": "ok",
        "mode": "repository_memory",
        "repository_execution_integrated": True,
        "authentication_required": bool(configured_token()),
        "authenticated": authorized(request),
        "model_configured": bool(os.environ.get("NEBIUS_API_KEY")),
        "remote_sandbox_integrated": True,
        "remote_configuration_complete": all(
            os.environ.get(name) for name in ("NEBIUS_API_KEY", "NEBIUS_PROJECT_ID")
        ),
        "model": os.environ.get("NEBIUS_MODEL") or DEFAULT_MODEL,
        "models": {
            "fast": os.environ.get("ISSUE2PROOF_MODEL_FAST")
            or "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
            "engineering": os.environ.get("ISSUE2PROOF_MODEL_ENGINEERING")
            or os.environ.get("NEBIUS_MODEL")
            or DEFAULT_MODEL,
            "reasoning": os.environ.get("ISSUE2PROOF_MODEL_REASONING")
            or "nvidia/Nemotron-3-Ultra-550b-a55b",
            "embedding": os.environ.get("ISSUE2PROOF_EMBEDDING_MODEL")
            or "Qwen/Qwen3-Embedding-8B",
        },
    }


@app.get("/api/budget")
def budget():
    from .jobs import budget_status

    return budget_status()


@app.get("/api/cases")
def cases():
    return [
        {"id": key, "title": value["title"], "issue": value["issue"]}
        for key, value in CASES.items()
    ]


@app.post("/api/runs", status_code=201)
def create_run(request: RunRequest):
    if request.mode == "remote" and all(
        os.environ.get(name) for name in ("NEBIUS_API_KEY", "NEBIUS_PROJECT_ID")
    ):
        raise HTTPException(
            409,
            "Live execution uses budgeted background investigations. Upload a project and start an investigation.",
        )
    report = (
        run_repair(request.case) if request.mode == "remote" else run_demo(request.case)
    )
    return save_report(report)


def save_report(report):
    report.update(id=str(uuid.uuid4()), created_at=datetime.now(UTC).isoformat())
    with connection() as db:
        db.execute(
            "INSERT INTO runs VALUES (?, ?, ?)",
            (report["id"], report["created_at"], json.dumps(report)),
        )
    return report


@app.get("/api/runs")
def list_runs(summaries: bool = False):
    with connection() as db:
        reports = [
            json.loads(row[0])
            for row in db.execute(
                "SELECT report FROM runs ORDER BY created_at DESC LIMIT 30"
            )
        ]
    if summaries:
        return [
            {
                key: report.get(key)
                for key in ("id", "case", "mode", "verdict", "created_at", "job_id")
            }
            for report in reports
        ]
    return reports


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    with connection() as db:
        row = db.execute("SELECT report FROM runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Run not found")
    return json.loads(row[0])


@app.get("/api/runs/{run_id}/report")
def download(run_id: str):
    report = get_run(run_id)
    return Response(
        json.dumps(report, indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="issue2proof-{report["id"]}.json"'
        },
    )


class DraftRequest(BaseModel):
    send_to_nebius: bool = False
    independent_test_paths: list[str] = Field(default_factory=list, max_length=100)


class GitHubImportRequest(BaseModel):
    repository_url: str = Field(min_length=20, max_length=300)
    issue: str = Field(min_length=1, max_length=4000)
    ref: str = Field(default="HEAD", min_length=1, max_length=200)


@app.post("/api/projects", status_code=201)
async def import_project(
    request: Request, issue: str = Query(min_length=1, max_length=4000)
):
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_ARCHIVE:
            raise HTTPException(413, "Archive exceeds the 10 MB upload limit.")
        data.extend(chunk)
    try:
        report = inspect_archive(bytes(data), issue)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    return save_report(report)


@app.post("/api/projects/github", status_code=201)
def import_github_project(body: GitHubImportRequest):
    from .github import import_public_repository

    try:
        return save_report(
            import_public_repository(body.repository_url, body.issue, ref=body.ref)
        )
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


@app.post("/api/projects/{run_id}/draft")
def draft_project(run_id: str, request: DraftRequest):
    if os.environ.get("ISSUE2PROOF_LEGACY_API", "0") != "1":
        raise HTTPException(
            410, "Use the reproduce-first background investigation endpoint."
        )
    report = get_run(run_id)
    if report.get("case") != "repository":
        raise HTTPException(400, "This investigation is not a repository upload.")
    if not request.send_to_nebius:
        raise HTTPException(
            422,
            "Review the included files and explicitly authorize sending them to Nebius.",
        )
    # Atomically claim the draft so concurrent clicks cannot duplicate paid calls.
    original = json.dumps(report)
    if any(
        name not in report["existing_tests"] for name in request.independent_test_paths
    ):
        raise HTTPException(422, "Independent checks must be existing test paths.")
    report["independent_test_paths"] = sorted(set(request.independent_test_paths))
    report.update(
        verdict="generating_draft",
        explanation="Generating regression and repair artifacts; no code is being executed.",
    )
    with connection() as db:
        changed = db.execute(
            "UPDATE runs SET report = ? WHERE id = ? AND report = ? AND json_extract(report, '$.verdict') = 'awaiting_model'",
            (json.dumps(report), run_id, original),
        ).rowcount
    if not changed:
        raise HTTPException(
            409,
            "Draft generation already started. Inspect its report or upload a new investigation.",
        )
    try:
        report = generate_draft(report)
    except ValueError as error:
        report.update(verdict="draft_failed", explanation=str(error))
    with connection() as db:
        db.execute(
            "UPDATE runs SET report = ? WHERE id = ?", (json.dumps(report), run_id)
        )
    return report


@app.get("/api/runs/{run_id}/artifacts")
def download_artifacts(run_id: str):
    return artifact_bundle(get_run(run_id), run_id)


def artifact_bundle(report: dict, run_id: str):
    if not report.get("draft_changes"):
        raise HTTPException(409, "No completed repair draft is available.")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("candidate.patch", report["draft_diff"])
        archive.writestr(
            report["generated_regression"]["path"],
            report["generated_regression"]["source"],
        )
        archive.writestr("evidence.json", json.dumps(report, indent=2))
        archive.writestr(
            "README.txt",
            (
                "CHECKS PASSED. Review evidence.json for execution results and limitations. This is not a proof of universal correctness.\n"
                if report["verdict"] == "checks_passed"
                else "UNVERIFIED DRAFT. Inspect evidence.json for any completed checks. Do not treat this candidate as an accepted repair.\n"
            ),
        )
    return Response(
        buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="issue2proof-draft-{run_id}.zip"'
        },
    )


class VerifyRequest(BaseModel):
    execute_remote: bool = False


@app.post("/api/projects/{run_id}/verify")
def verify_project(run_id: str, request: VerifyRequest):
    if os.environ.get("ISSUE2PROOF_LEGACY_API", "0") != "1":
        raise HTTPException(410, "Use budgeted background investigations.")
    report = get_run(run_id)
    if report.get("case") != "repository" or not report.get("draft_changes"):
        raise HTTPException(409, "A completed repository repair draft is required.")
    if not request.execute_remote:
        raise HTTPException(
            422, "Authorize remote sandbox execution before verification."
        )
    original = json.dumps(report)
    if report["verdict"] != "awaiting_sandbox":
        raise HTTPException(
            409, "Verification already started or completed for this investigation."
        )
    report.update(
        verdict="verifying",
        explanation="Running original and candidate checks in fresh remote sandboxes.",
    )
    with connection() as db:
        changed = db.execute(
            "UPDATE runs SET report=? WHERE id=? AND report=?",
            (json.dumps(report), run_id, original),
        ).rowcount
    if not changed:
        raise HTTPException(
            409, "Another verification request already claimed this investigation."
        )
    try:
        report = verify_repository(report)
    except ValueError as error:
        report.update(verdict="verification_failed", explanation=str(error))
    with connection() as db:
        db.execute("UPDATE runs SET report=? WHERE id=?", (json.dumps(report), run_id))
    return report


@app.get("/api/examples")
def saved_examples():
    return [
        {"id": name, "title": title}
        for name, title in [
            ("live-pricing-repair", "Live AI pricing repair"),
            ("live-repository-repair", "Live uploaded-project repair"),
            ("live-rejection-evaluation", "Live bad-candidate rejection"),
            ("real-bug-werkzeug", "Historical Werkzeug repair"),
            ("real-bug-requests", "Historical Requests repair"),
            ("live-dependency-investigation", "Package and dependency repair"),
        ]
        if (Path(__file__).parent.parent / "artifacts" / f"{name}.json").exists()
    ]


@app.get("/api/examples/{name}")
def saved_example(name: str):
    allowed = {item["id"] for item in saved_examples()}
    if name not in allowed:
        raise HTTPException(404, "Example not found")
    report = json.loads(
        (Path(__file__).parent.parent / "artifacts" / f"{name}.json").read_text()
    )
    return {**report, "saved_example": True, "id": "example-" + name}


@app.get("/api/examples/{name}/artifacts")
def saved_artifacts(name: str):
    return artifact_bundle(saved_example(name), name)


class LoginRequest(BaseModel):
    token: str = Field(min_length=1, max_length=1000)


@app.post("/api/login")
def sign_in(request: Request, body: LoginRequest):
    return login(request, body.token)


@app.post("/api/logout")
def sign_out():
    response = Response(status_code=204)
    response.delete_cookie(COOKIE)
    return response


class InvestigationRequest(BaseModel):
    send_to_nebius: bool = False
    execute_remote: bool = False
    prepare_dependencies: bool = True
    independent_test_paths: list[str] = Field(min_length=1, max_length=100)
    source_paths: list[str] = Field(default_factory=list, max_length=100)
    max_repairs: int = Field(default=3, ge=1, le=3)
    max_model_calls: int = Field(default=5, ge=2, le=5)
    max_sandbox_calls: int = Field(default=16, ge=6, le=20)
    budget_usd: float = Field(default=2.0, ge=0.1, le=5)


class MemoryRequest(BaseModel):
    repository_key: str | None = Field(default=None, min_length=3, max_length=200)


class MemorySearchRequest(BaseModel):
    query: str = Field(min_length=3, max_length=4000)
    repository_key: str | None = Field(default=None, min_length=3, max_length=200)
    limit: int = Field(default=5, ge=1, le=20)
    semantic: bool = False
    authorize_nebius: bool = False


class MemoryEnrichmentRequest(BaseModel):
    authorize_nebius: bool = False


class AgentContextRequest(MemorySearchRequest):
    pass


class SupersedeRequest(BaseModel):
    replacement_id: str = Field(min_length=1, max_length=100)


class MemoryAuditRequest(BaseModel):
    memory_ids: list[str] = Field(min_length=1, max_length=10)
    execute_remote: bool = False
    prepare_dependencies: bool = True
    max_model_calls: int = Field(default=0, ge=0, le=2)
    max_sandbox_calls: int = Field(default=8, ge=2, le=12)
    max_repairs: int = Field(default=1, ge=1, le=2)
    budget_usd: float = Field(default=0.75, ge=0.1, le=1)
    analyze_conflict: bool = True
    allow_ultra: bool = True


@app.post("/api/runs/{run_id}/memory", status_code=201)
def remember_investigation(run_id: str, body: MemoryRequest):
    from .memory import capsule_from_report, save_capsule

    try:
        return save_capsule(
            capsule_from_report(get_run(run_id), key=body.repository_key)
        )
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


@app.post("/api/examples/{name}/memory", status_code=201)
def remember_saved_example(name: str, body: MemoryRequest):
    from .memory import capsule_from_report, save_capsule

    try:
        return save_capsule(
            capsule_from_report(saved_example(name), key=body.repository_key)
        )
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


@app.get("/api/memories")
def memories(repository_key: str | None = Query(default=None, max_length=200)):
    from .memory import list_capsules

    return list_capsules(repository_key)


@app.get("/api/memories/export")
def export_memories(repository_key: str | None = Query(default=None, max_length=200)):
    from .memory import export_capsule_bundle

    return export_capsule_bundle(repository_key)


@app.post("/api/memories/import")
def import_memories(bundle: dict):
    from .memory import import_capsule_bundle

    try:
        return import_capsule_bundle(bundle)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


@app.get("/api/memories/{capsule_id}")
def memory(capsule_id: str):
    from .memory import get_capsule

    try:
        return get_capsule(capsule_id)
    except KeyError:
        raise HTTPException(404, "Memory Capsule not found") from None


@app.post("/api/memories/search")
def search_memory(body: MemorySearchRequest):
    from .memory import search_capsules, semantic_search

    if body.semantic:
        if not body.authorize_nebius:
            raise HTTPException(
                422, "Explicitly authorize the budgeted Nebius embedding request."
            )
        try:
            return semantic_search(
                body.query, key=body.repository_key, limit=body.limit
            )
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
    return search_capsules(body.query, key=body.repository_key, limit=body.limit)


@app.post("/api/integrations/context")
def agent_context(body: AgentContextRequest):
    """Return a vendor-neutral packet for coding agents, hooks and CI systems."""
    response = search_memory(body)
    matches = response["results"] if isinstance(response, dict) else response
    return {
        "schema": "issue2proof.agent-context.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "proposed_change": body.query,
        "repository_key": body.repository_key,
        "recall": {
            "method": "semantic" if body.semantic else "lexical",
            "model": response.get("model") if isinstance(response, dict) else None,
        },
        "instructions": [
            "Treat claims as behavioral constraints, not implementation instructions.",
            "Do not modify or expose the frozen regression; request a server-side replay.",
            "If the intended contract changed, supersede the memory with reviewed evidence.",
        ],
        "memories": [
            {
                "id": item["capsule"]["id"],
                "version": item["capsule"]["version"],
                "relevance": item["score"],
                "claim": item["capsule"]["claim"],
                "scope": item["capsule"]["scope"],
                "assumptions": item["capsule"].get("assumptions", []),
                "risk_boundaries": item["capsule"].get("risk_boundaries", []),
                "invalidated_when": item["capsule"].get("invalidated_when", []),
                "regression": {
                    "path": item["capsule"]["evidence"]["regression"]["path"],
                    "sha256": item["capsule"]["evidence"]["regression"]["sha256"],
                    "source_withheld": True,
                },
            }
            for item in matches
        ],
    }


@app.post("/api/memories/{capsule_id}/supersede")
def supersede_memory(capsule_id: str, body: SupersedeRequest):
    from .memory import supersede_capsule

    try:
        return supersede_capsule(capsule_id, body.replacement_id)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


@app.post("/api/memories/{capsule_id}/enrich")
def enrich_memory(capsule_id: str, body: MemoryEnrichmentRequest):
    from .memory import enrich_capsule

    if not body.authorize_nebius:
        raise HTTPException(422, "Explicitly authorize the budgeted Nebius request.")
    try:
        return enrich_capsule(capsule_id)
    except KeyError:
        raise HTTPException(404, "Memory Capsule not found") from None
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


@app.post("/api/projects/{run_id}/audit-memory", status_code=202)
def start_memory_audit(run_id: str, body: MemoryAuditRequest):
    from .jobs import enqueue
    from .memory import get_capsule

    report = get_run(run_id)
    if report.get("case") != "repository" or report["verdict"] != "awaiting_model":
        raise HTTPException(409, "Audit a newly inspected repository revision.")
    if not body.execute_remote:
        raise HTTPException(422, "Authorize remote replay in Nebius Sandboxes.")
    try:
        for capsule_id in body.memory_ids:
            get_capsule(capsule_id)
        options = body.model_dump()
        options["workflow"] = "memory_audit"
        return enqueue(run_id, options)
    except KeyError:
        raise HTTPException(422, "Selected Memory Capsule does not exist.") from None
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


@app.post("/api/projects/{run_id}/investigate", status_code=202)
def start_investigation(run_id: str, body: InvestigationRequest):
    from .environments import dependency_plan
    from .jobs import enqueue

    report = get_run(run_id)
    if report.get("case") != "repository" or report["verdict"] != "awaiting_model":
        raise HTTPException(
            409, "Start a complete investigation from a newly inspected repository."
        )
    if not body.send_to_nebius or not body.execute_remote:
        raise HTTPException(422, "Authorize inference and remote code execution.")
    if any(path not in report["sources"] for path in body.source_paths):
        raise HTTPException(422, "Context paths must be implementation files.")
    paths = set(body.independent_test_paths)
    if (
        not paths.issubset(report["existing_tests"])
        or not set(report["existing_tests"]) - paths
    ):
        raise HTTPException(
            422,
            "Reserve existing independent tests and keep at least one ordinary test.",
        )
    from .pipeline import build_model_context

    context = build_model_context(report, body.model_dump())
    if not context["sources"]:
        raise HTTPException(422, "Select at least one implementation file for repair.")
    try:
        dependency_plan(report["dependency_manifests"])
        return enqueue(run_id, body.model_dump())
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


@app.get("/api/jobs")
def investigations():
    from .jobs import list_jobs

    return list_jobs()


@app.get("/api/jobs/{job_id}")
def investigation(job_id: str):
    from .jobs import get_job

    try:
        return get_job(job_id)
    except KeyError:
        raise HTTPException(404, "Investigation not found") from None


@app.post("/api/jobs/{job_id}/cancel")
def cancel_investigation(job_id: str):
    from .jobs import cancel

    try:
        return cancel(job_id)
    except KeyError:
        raise HTTPException(404, "Investigation not found") from None


@app.post("/api/jobs/{job_id}/resume")
def resume_investigation(job_id: str):
    from .jobs import resume

    try:
        return resume(job_id)
    except ValueError as error:
        raise HTTPException(409, str(error)) from None


@app.delete("/api/runs/{run_id}", status_code=204)
def delete_investigation(run_id: str):
    from .jobs import database

    with database() as db:
        if db.execute(
            "SELECT 1 FROM jobs WHERE run_id=? AND state IN ('running','queued')",
            (run_id,),
        ).fetchone():
            raise HTTPException(
                409, "Cancel the active investigation before deleting it."
            )
        db.execute(
            "DELETE FROM job_events WHERE job_id IN(SELECT id FROM jobs WHERE run_id=?)",
            (run_id,),
        )
        db.execute("DELETE FROM jobs WHERE run_id=?", (run_id,))
        db.execute("DELETE FROM runs WHERE id=?", (run_id,))
    return Response(status_code=204)


class ClarificationRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=2000)


@app.post("/api/jobs/{job_id}/clarify")
def clarify_investigation(job_id: str, body: ClarificationRequest):
    from .jobs import database, get_job

    job = get_job(job_id)
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        report = json.loads(
            db.execute(
                "SELECT report FROM runs WHERE id=?", (job["run_id"],)
            ).fetchone()[0]
        )
        if report["verdict"] != "needs_clarification" or job["state"] != "completed":
            raise HTTPException(
                409, "This investigation is not awaiting clarification."
            )
        report.setdefault("original_issue", report["issue"])
        report["issue"] = (
            report["original_issue"] + "\nUser clarification: " + body.answer
        )
        report.update(
            verdict="queued",
            explanation="Clarification received; resuming with the existing budget and checkpoints.",
        )
        db.execute(
            "UPDATE runs SET report=? WHERE id=?", (json.dumps(report), job["run_id"])
        )
        db.execute(
            "UPDATE jobs SET state='queued',stage='clarification_received',owner=NULL,lease=NULL,error=NULL WHERE id=?",
            (job_id,),
        )
    return get_job(job_id)


@app.get("/api/samples/{name}")
def sample_archive(name: str):
    mapping = {
        "calendar": "calendar-project.zip",
        "werkzeug": "real-bugs/werkzeug-safe-join.zip",
        "pricing": "pricing-project.zip",
    }
    if name not in mapping:
        raise HTTPException(404, "Example not found")
    path = Path(__file__).parent.parent / "examples" / mapping[name]
    if not path.is_file():
        raise HTTPException(404, "Example archive unavailable in this installation")
    return FileResponse(path, media_type="application/zip", filename=path.name)
