"""SQLite-backed investigations, leased claims, cancellation and request accounting."""

import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime

TERMINAL = {"completed", "failed", "cancelled", "interrupted", "budget_exhausted"}

DEFAULT_RESERVATIONS = {
    "embedding": 0.01,
    "model:fast": 0.01,
    "model:engineering": 0.03,
    "model:reasoning": 0.15,
    "model:challenger": 0.03,
    "sandbox": 0.075,
    "environment": 0.50,
}


@contextmanager
def database():
    path = os.environ.get("ISSUE2PROOF_DB", "runs.sqlite3")
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA secure_delete=ON")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,created_at TEXT,report TEXT);
    CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,run_id TEXT NOT NULL,state TEXT NOT NULL,stage TEXT NOT NULL,
      options TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL,owner TEXT,lease REAL,
      cancel_requested INTEGER NOT NULL DEFAULT 0,operation_id TEXT,model_calls INTEGER NOT NULL DEFAULT 0,
      sandbox_calls INTEGER NOT NULL DEFAULT 0,reserved_usd REAL NOT NULL DEFAULT 0,error TEXT);
    CREATE TABLE IF NOT EXISTS reservations(id INTEGER PRIMARY KEY,job_id TEXT,kind TEXT,amount REAL,created REAL);
    CREATE TABLE IF NOT EXISTS job_events(id INTEGER PRIMARY KEY,job_id TEXT,stage TEXT,created REAL);
    CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(state,created);
    """)
    try:
        with db:
            yield db
    finally:
        db.close()


def enqueue(run_id, options):
    now = time.time()
    job_id = str(uuid.uuid4())
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        if not db.execute("SELECT 1 FROM runs WHERE id=?", (run_id,)).fetchone():
            raise ValueError("Investigation not found.")
        if db.execute(
            "SELECT 1 FROM jobs WHERE run_id=? AND state IN ('queued','running','interrupted')",
            (run_id,),
        ).fetchone():
            raise ValueError(
                "This investigation already has an active or interrupted job."
            )
        if db.execute(
            "SELECT COUNT(*) FROM jobs WHERE state IN ('queued','running')"
        ).fetchone()[0] >= int(os.environ.get("ISSUE2PROOF_QUEUE_LIMIT", "20")):
            raise ValueError(
                "The queue is full; retry after an investigation finishes."
            )
        db.execute(
            "INSERT INTO jobs(id,run_id,state,stage,options,created,updated) VALUES(?,?,?,?,?,?,?)",
            (job_id, run_id, "queued", "queued", json.dumps(options), now, now),
        )
    return get_job(job_id)


def get_job(job_id):
    with database() as db:
        row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        raise KeyError(job_id)
    item = dict(row)
    item["options"] = json.loads(item["options"])
    item.pop("owner", None)
    with database() as db:
        item["events"] = [
            dict(row)
            for row in db.execute(
                "SELECT stage,created FROM job_events WHERE job_id=? ORDER BY id",
                (job_id,),
            )
        ]
        item["model_roles"] = {
            row["role"]: row["calls"]
            for row in db.execute(
                "SELECT substr(kind,7) role,COUNT(*) calls FROM reservations WHERE job_id=? AND kind LIKE 'model:%' GROUP BY kind",
                (job_id,),
            )
        }
    return item


def budget_status():
    """Return the application reservation ledger without exposing credentials."""
    total = max(0.0, float(os.environ.get("ISSUE2PROOF_TOTAL_BUDGET_USD", "25")))
    protected = max(
        0.0, float(os.environ.get("ISSUE2PROOF_PROTECTED_RESERVE_USD", "5"))
    )
    spendable = max(0.0, total - protected)
    today = (
        datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    )
    with database() as db:
        reserved = float(
            db.execute("SELECT COALESCE(SUM(amount),0) FROM reservations").fetchone()[0]
        )
        daily = float(
            db.execute(
                "SELECT COALESCE(SUM(amount),0) FROM reservations WHERE created>=?",
                (today,),
            ).fetchone()[0]
        )
        roles = {
            row["kind"]: {"calls": row["calls"], "reserved_usd": row["amount"]}
            for row in db.execute(
                "SELECT kind,COUNT(*) calls,ROUND(SUM(amount),8) amount FROM reservations GROUP BY kind ORDER BY kind"
            )
        }
    return {
        "total_credit_usd": total,
        "protected_reserve_usd": protected,
        "spendable_usd": spendable,
        "reserved_usd": round(reserved, 8),
        "remaining_spendable_usd": round(max(0.0, spendable - reserved), 8),
        "reserved_today_usd": round(daily, 8),
        "roles": roles,
    }


def reserve_system(kind: str, amount: float | None = None) -> int:
    """Reserve a bounded non-job call, such as one batched embedding request."""
    if kind not in DEFAULT_RESERVATIONS:
        raise ValueError("Unknown reservation kind.")
    amount = DEFAULT_RESERVATIONS[kind] if amount is None else max(0.0, float(amount))
    today = (
        datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    )
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        daily = db.execute(
            "SELECT COALESCE(SUM(amount),0) FROM reservations WHERE created>=?",
            (today,),
        ).fetchone()[0]
        if daily + amount > float(os.environ.get("ISSUE2PROOF_DAILY_BUDGET_USD", "10")):
            raise BudgetExceeded("Server daily estimated-cost allowance exhausted.")
        lifetime = db.execute(
            "SELECT COALESCE(SUM(amount),0) FROM reservations"
        ).fetchone()[0]
        spendable = max(
            0.0,
            float(os.environ.get("ISSUE2PROOF_TOTAL_BUDGET_USD", "25"))
            - float(os.environ.get("ISSUE2PROOF_PROTECTED_RESERVE_USD", "5")),
        )
        if lifetime + amount > spendable + 1e-9:
            raise BudgetExceeded(
                "Server lifetime spendable allowance exhausted; protected credit reserve was not used."
            )
        reservation = db.execute(
            "INSERT INTO reservations(job_id,kind,amount,created) VALUES(NULL,?,?,?)",
            (kind, amount, time.time()),
        )
    return reservation.lastrowid


def reconcile_system(reservation_id: int, actual_amount: float | None):
    if not isinstance(actual_amount, (int, float)):
        return
    with database() as db:
        db.execute(
            "UPDATE reservations SET amount=? WHERE id=? AND job_id IS NULL",
            (max(0.0, float(actual_amount)), reservation_id),
        )


def list_jobs():
    with database() as db:
        ids = [
            row[0]
            for row in db.execute("SELECT id FROM jobs ORDER BY created DESC LIMIT 100")
        ]
    return [get_job(job_id) for job_id in ids]


def claim(owner):
    now = time.time()
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "UPDATE jobs SET state='interrupted',stage='interrupted',operation_id=NULL,error='Worker lease expired; explicit resume required.',updated=? WHERE state='running' AND lease<?",
            (now, now),
        )
        row = db.execute(
            "SELECT * FROM jobs WHERE state='queued' AND cancel_requested=0 ORDER BY created LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        db.execute(
            "UPDATE jobs SET state='running',owner=?,lease=?,updated=? WHERE id=?",
            (owner, now + 120, now, row["id"]),
        )
    return get_job(row["id"])


def cancel(job_id):
    job = get_job(job_id)
    if job["state"] in TERMINAL:
        return job
    with database() as db:
        db.execute(
            "UPDATE jobs SET cancel_requested=1,state=CASE WHEN state='queued' THEN 'cancelled' ELSE state END,updated=? WHERE id=?",
            (time.time(), job_id),
        )
    return get_job(job_id)


def resume(job_id):
    with database() as db:
        changed = db.execute(
            "UPDATE jobs SET state='queued',stage='resuming',cancel_requested=0,owner=NULL,lease=NULL,operation_id=NULL,error=NULL,updated=? WHERE id=? AND state IN ('interrupted','failed')",
            (time.time(), job_id),
        ).rowcount
    if not changed:
        raise ValueError(
            "Only an interrupted or failed investigation can resume; budgets and completed checkpoints are retained."
        )
    return get_job(job_id)


class Cancelled(Exception):
    pass


class BudgetExceeded(Exception):
    pass


class Context:
    def __init__(self, job_id, owner):
        self.id = job_id
        self.owner = owner
        self.stop = threading.Event()
        self.heartbeat = threading.Thread(target=self._heartbeat, daemon=True)
        self.heartbeat.start()

    def _heartbeat(self):
        while not self.stop.wait(10):
            with database() as db:
                db.execute(
                    "UPDATE jobs SET lease=?,updated=? WHERE id=? AND owner=? AND state='running'",
                    (time.time() + 120, time.time(), self.id, self.owner),
                )
            with database() as db:
                current = db.execute(
                    "SELECT owner,state FROM jobs WHERE id=?", (self.id,)
                ).fetchone()
            if (
                current is None
                or current["owner"] != self.owner
                or current["state"] != "running"
            ):
                return
            job = get_job(self.id)
            if job["cancel_requested"] and job["operation_id"]:
                # This ID was registered by this job's executor, never user input.
                try:
                    from .execution import SandboxExecutor

                    runner = SandboxExecutor()
                    try:
                        runner.client.cancel_operation(job["operation_id"])
                    finally:
                        runner.close()
                except Exception as error:  # noqa: BLE001 - sanitize cancellation transport errors
                    with database() as db:
                        db.execute(
                            "UPDATE jobs SET error=? WHERE id=?",
                            ("Cancellation probe: " + type(error).__name__, self.id),
                        )

    def check(self):
        with database() as db:
            owner = db.execute(
                "SELECT owner FROM jobs WHERE id=?", (self.id,)
            ).fetchone()
        if owner is None or owner[0] != self.owner:
            raise Cancelled()
        job = get_job(self.id)
        if job["cancel_requested"]:
            raise Cancelled()
        if job["state"] != "running":
            raise Cancelled()

    def reserve(self, kind, *, role=None, amount=None):
        self.check()
        job = get_job(self.id)
        options = job["options"]
        ledger_kind = f"model:{role or 'engineering'}" if kind == "model" else kind
        if ledger_kind not in DEFAULT_RESERVATIONS:
            raise ValueError("Unknown reservation kind.")
        amount = (
            DEFAULT_RESERVATIONS[ledger_kind]
            if amount is None
            else max(0.0, float(amount))
        )
        column = "model_calls" if kind == "model" else "sandbox_calls"
        maximum = (
            options["max_model_calls"]
            if kind == "model"
            else options["max_sandbox_calls"]
        )
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE id=?", (self.id,)).fetchone()
            if (
                row[column] >= maximum
                or row["reserved_usd"] + amount > options["budget_usd"] + 1e-9
            ):
                raise BudgetExceeded(
                    "Investigation request or estimated-cost budget exhausted."
                )
            today = (
                datetime.now(UTC)
                .replace(hour=0, minute=0, second=0, microsecond=0)
                .timestamp()
            )
            daily = db.execute(
                "SELECT COALESCE(SUM(amount),0) FROM reservations WHERE created>=?",
                (today,),
            ).fetchone()[0]
            if daily + amount > float(
                os.environ.get("ISSUE2PROOF_DAILY_BUDGET_USD", "10")
            ):
                raise BudgetExceeded("Server daily estimated-cost allowance exhausted.")
            lifetime = db.execute(
                "SELECT COALESCE(SUM(amount),0) FROM reservations"
            ).fetchone()[0]
            total = max(
                0.0, float(os.environ.get("ISSUE2PROOF_TOTAL_BUDGET_USD", "25"))
            )
            protected = max(
                0.0,
                float(os.environ.get("ISSUE2PROOF_PROTECTED_RESERVE_USD", "5")),
            )
            if lifetime + amount > max(0.0, total - protected) + 1e-9:
                raise BudgetExceeded(
                    "Server lifetime spendable allowance exhausted; protected credit reserve was not used."
                )
            db.execute(
                f"UPDATE jobs SET {column}={column}+1,reserved_usd=reserved_usd+? WHERE id=?",
                (amount, self.id),
            )
            reservation = db.execute(
                "INSERT INTO reservations(job_id,kind,amount,created) VALUES(?,?,?,?)",
                (self.id, ledger_kind, amount, time.time()),
            )
        return reservation.lastrowid

    def reconcile(self, reservation_id, actual_amount):
        """Replace a conservative reservation with recorded provider usage."""
        if reservation_id is None or not isinstance(actual_amount, (int, float)):
            return
        actual = max(0.0, float(actual_amount))
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT amount FROM reservations WHERE id=? AND job_id=?",
                (reservation_id, self.id),
            ).fetchone()
            if row is None:
                return
            difference = actual - row["amount"]
            job = db.execute(
                "SELECT reserved_usd,options FROM jobs WHERE id=?", (self.id,)
            ).fetchone()
            if job is None:
                return
            options = json.loads(job["options"])
            if job["reserved_usd"] + difference > options["budget_usd"] + 1e-9:
                raise BudgetExceeded("Observed usage exceeded the job allowance.")
            db.execute(
                "UPDATE reservations SET amount=? WHERE id=?", (actual, reservation_id)
            )
            db.execute(
                "UPDATE jobs SET reserved_usd=MAX(0,reserved_usd+?) WHERE id=?",
                (difference, self.id),
            )

    def operation(self, operation_id):
        with database() as db:
            db.execute(
                "UPDATE jobs SET operation_id=? WHERE id=? AND owner=?",
                (operation_id, self.id, self.owner),
            )
        self.check()

    def save(self, report, stage):
        self.check()
        report["job_id"] = self.id
        with database() as db:
            db.execute(
                "UPDATE runs SET report=? WHERE id=?",
                (json.dumps(report), get_job(self.id)["run_id"]),
            )
            db.execute(
                "UPDATE jobs SET stage=?,updated=? WHERE id=?",
                (stage, time.time(), self.id),
            )
            db.execute(
                "INSERT INTO job_events(job_id,stage,created) VALUES(?,?,?)",
                (self.id, stage, time.time()),
            )

    def finish(self, state, error=None):
        self.stop.set()
        self.heartbeat.join(timeout=1)
        with database() as db:
            db.execute(
                "UPDATE jobs SET state=?,error=?,operation_id=NULL,updated=? WHERE id=? AND owner=?",
                (state, error, time.time(), self.id, self.owner),
            )


class Worker:
    def __init__(self):
        self.owner = str(uuid.uuid4())
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def start(self):
        self.thread.start()

    def close(self):
        self.stop.set()
        self.thread.join(timeout=2)

    def run_once(self):
        job = claim(self.owner)
        if not job:
            return False
        context = Context(job["id"], self.owner)
        with database() as db:
            report = json.loads(
                db.execute(
                    "SELECT report FROM runs WHERE id=?", (job["run_id"],)
                ).fetchone()[0]
            )
        try:
            if job["options"].get("workflow") == "memory_audit":
                from .audit import audit_memories

                report = audit_memories(report, job["options"], context)
            else:
                from .pipeline import investigate

                report = investigate(report, job["options"], context)
            context.save(report, "finished")
            context.finish("completed")
        except (Cancelled, BudgetExceeded) as error:
            state = "cancelled" if isinstance(error, Cancelled) else "budget_exhausted"
            report.update(
                verdict=state,
                explanation=str(error)
                or "Investigation cancelled. Completed evidence is retained.",
            )
            self._save_terminal(job, report, self.owner)
            context.finish(state, str(error))
        except Exception as error:  # noqa: BLE001 - job boundary sanitizes errors
            if get_job(job["id"])["cancel_requested"]:
                report.update(
                    verdict="cancelled",
                    explanation="Cancellation acknowledged. No further requests will be scheduled.",
                )
                self._save_terminal(job, report, self.owner)
                context.finish("cancelled")
                return True
            # Never serialize raw transport errors or credential-bearing payloads.
            report.update(
                verdict="investigation_failed",
                explanation="Investigation failed. Completed checkpoints and budget reservations are retained.",
                error_type=type(error).__name__,
            )
            if isinstance(error, ValueError) and not report.get("model_outputs"):
                report["explanation"] = (
                    "Invalid setup or response contract; review the recorded stage."
                )
            self._save_terminal(job, report, self.owner)
            context.finish("failed", type(error).__name__)
        return True

    @staticmethod
    def _save_terminal(job, report, owner):
        with database() as db:
            db.execute(
                "UPDATE runs SET report=? WHERE id=? AND EXISTS(SELECT 1 FROM jobs WHERE id=? AND owner=?)",
                (json.dumps(report), job["run_id"], job["id"], owner),
            )

    def run(self):
        count = 0
        while not self.stop.is_set():
            try:
                if count % 100 == 0:
                    prune()
                count += 1
                work = self.run_once()
            except Exception as error:  # noqa: BLE001 - keep queue alive after storage/service faults
                import logging

                logging.getLogger(__name__).error(
                    "Worker boundary: %s", type(error).__name__
                )
                work = False
            if not work:
                self.stop.wait(1)


def prune():
    days = max(1, int(os.environ.get("ISSUE2PROOF_RETENTION_DAYS", "7")))
    cutoff = datetime.fromtimestamp(time.time() - days * 86400, UTC).isoformat()
    with database() as db:
        ids = [
            row[0]
            for row in db.execute(
                "SELECT id FROM runs WHERE created_at<? AND NOT EXISTS(SELECT 1 FROM jobs WHERE jobs.run_id=runs.id AND jobs.state IN ('running','queued','interrupted'))",
                (cutoff,),
            )
        ]
        for run_id in ids:
            db.execute(
                "DELETE FROM job_events WHERE job_id IN(SELECT id FROM jobs WHERE run_id=?)",
                (run_id,),
            )
            db.execute("DELETE FROM jobs WHERE run_id=?", (run_id,))
            db.execute("DELETE FROM runs WHERE id=?", (run_id,))
        # The reservation ledger is intentionally retained: deleting it would make
        # a lifetime credit ceiling reset after the retention window.
    return len(ids)
