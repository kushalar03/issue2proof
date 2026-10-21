# Issue2Proof

**Regression memory for AI coding agents that survives the agent.**

[Try the hosted evidence demo](https://issue2proof-evidence.eagersage2048.chatgpt.site)

Git records what changed. Issue2Proof records why behavior must keep working. It
turns a resolved failure into a versioned **Memory Capsule** containing the
behavioral claim, affected paths, assumptions, boundaries, provenance, immutable
hashes and a frozen executable regression. When a person or coding agent proposes
a later revision, Issue2Proof recalls related capsules and replays them in fresh
Nebius Sandboxes before the change ships.

Repository rules and agent memory can preserve useful guidance, but that guidance
is usually prose. Issue2Proof preserves executable, hash-backed evidence that can
be replayed independently across agents, sessions and tools.

## Core workflow

1. Import a public GitHub repository or a ZIP and describe the failure.
2. Investigate it with a reproduce-first repair pipeline. The generated regression
   must fail on the original revision before repair begins.
3. Accept a repair only after the frozen regression, existing suite and withheld
   independent checks pass in isolated sandboxes.
4. Convert that completed evidence into a versioned Memory Capsule.
5. Recall capsules for a future change using Qwen semantic embeddings by default,
   or opt into free lexical search.
6. Replay selected regressions on the proposed revision. Classify each memory as
   `preserved`, `violated` or `uncertain` without generating a patch.
7. Analyze conflicts with Nemotron Super; escalate only uncertain high-risk cases
   to Nemotron Ultra.

The UI includes recorded live evidence, so judges can create and recall memory
without spending credits. Paid actions require an explicit click.

## Measured impact

A reproducible blind-refactor stress benchmark ran 30 Nemotron Super trials across
two real upstream bug histories. The agent received the repaired function and
ordinary visible tests, but no incident description or frozen capsule regression.
Eight trials introduced a historical regression. Plain CI caught 3 of 8; capsule
replay caught 8 of 8, adding five catches that the visible suite missed. This is a
focused two-case stress test, not a claim about general production accuracy. The
complete prompts, outcomes and limitations are in
`artifacts/memory-impact-benchmark.json`.

## Model routing and the $25 budget

| Role | Model | When used |
|---|---|---|
| Fast indexing | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | Compress evidence into keywords and future change triggers |
| Engineering | `nvidia/nemotron-3-super-120b-a12b` | Generate regressions/repairs and explain memory conflicts |
| Deep reasoning | `nvidia/Nemotron-3-Ultra-550b-a55b` | Adjudicate only escalated high-risk conflicts |
| Semantic recall | `Qwen/Qwen3-Embedding-8B` | Match future changes to capsule meaning |
| Optional challenger | `moonshotai/Kimi-K2.7-Code` | Configured for future disagreement experiments |

The application enforces per-job, daily and lifetime reservation limits. Defaults
are $25 total credit, $20 spendable and a protected $5 reserve. Lexical recall and
recorded evidence are free. One embedding request batches the query and all
uncached capsules. Reservations are estimates and should be paired with provider
billing limits.

## Run locally

Requires Python 3.11+.

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.lock
pip install --no-deps --no-build-isolation -e .
python -m issue2proof.configure
```

Set `NEBIUS_API_KEY` and `NEBIUS_PROJECT_ID` in the generated private `.env`.
Sandboxes must be activated for that project. The default sandbox image is the
official quickstart reference `python:3.12-slim`; it is resolved to an immutable
UUID before low-level execution. `NEBIUS_SANDBOX_IMAGE` may pin a UUID directly.

```sh
./scripts/start.sh
```

Open <http://127.0.0.1:8000> and sign in with the generated application token.
Never use the Nebius API key as the application login.

## Execution boundary

Repository and model-generated Python never execute on the application host.
Issue2Proof prepares PyPI **binary wheels only** in a separate network-enabled
sandbox containing no repository code. It installs the project offline with
`--no-deps --no-build-isolation --no-index`, then runs pytest as uid 65534 with:

- guest networking disabled;
- read-only collected source and tests;
- frozen input hashes checked after execution;
- memory, CPU, process, file and wall-clock limits;
- bounded output and disposable result images.

The controller records operation IDs, image UUIDs, dependency versions, hashes,
costs and limitations. A passing replay proves only that the selected frozen
behavior passed in that environment; it is not universal correctness or a defense
against every adversarial test process.

Imports are bounded to 10 MB ZIP, 1,500 entries, 2 MB expanded text and 200 KB per
file. Unsafe paths, symlinks, encrypted archives, hidden credential files and
unsupported binary content are rejected. The GitHub importer accepts only exact
public repository roots and downloads from the fixed GitHub archive host.

## Durable jobs and evidence

SQLite stores reports, Memory Capsules, embeddings, queue leases, checkpoints,
cancellations and the lifetime budget ledger. Expired jobs become interrupted and
require explicit resume, preventing accidental paid retries. Completed checkpoints
are reused. Active investigations can be cancelled; retained source/evidence can
be deleted locally.

## Use with any coding agent or CI

The browser is one client, not the product boundary. The bundled
`scripts/mcp_server.py` installs Issue2Proof as `recall_repository_memory` and
`audit_repository_revision` MCP tools in Claude Code, Cursor, Codex-compatible
hosts and other MCP clients. `POST
/api/integrations/context` returns the same model-neutral memory packet for Codex, Claude
Code, Cursor, IDE extensions, git hooks and CI. It includes claims, scope,
assumptions, boundaries and regression hashes while withholding regression source
for independent server-side replay. The bundled `scripts/agent_context.py` CLI
reads its token from the environment and prints the packet as JSON. See
`docs/INTEGRATIONS.md` for agent, IDE and pull-request examples.

Historical Werkzeug and Requests cases preserve upstream provenance and licenses.
They are demonstration cases, not held-out benchmarks. Live evidence includes:

- `artifacts/real-bug-werkzeug.json` and `real-bug-requests.json`;
- `artifacts/sandbox-activation-validation.json`;
- `artifacts/live-memory-model-validation.json` (Nano + Qwen embedding);
- `artifacts/live-memory-audit.json` (full replay and risk-adaptive analysis);
- `artifacts/mcp-audit-live-validation.jsonl` (MCP import → sandbox replay → conflict);
- `artifacts/memory-impact-benchmark.json` (30 blind Nemotron refactor trials);
- browser, cancellation, recovery, dependency and container validations.

## Validation

```sh
.venv/bin/ruff check issue2proof tests
.venv/bin/pytest -q
node --check issue2proof/static/app.js
NEBIUS_PROJECT_ID=... .venv/bin/python -m issue2proof.check_sandbox
```

The automated suite has 130 tests after the executable-memory and MCP additions. External
calls are mocked in unit tests; the listed live artifacts record real Nebius calls.

## API highlights

- `POST /api/projects/github` or `POST /api/projects?issue=...`
- `POST /api/projects/{id}/investigate`
- `POST /api/runs/{id}/memory`, `POST /api/examples/{name}/memory`
- `GET /api/memories`, `POST /api/memories/search`
- `POST /api/memories/{id}/enrich`, `/supersede`
- `POST /api/integrations/context`: vendor-neutral agent and CI packet
- `POST /api/projects/{id}/audit-memory`
- `GET /api/budget`, `/api/jobs`, `/api/jobs/{id}`
- `POST /api/jobs/{id}/cancel`, `/resume`, `/clarify`
- `GET /api/runs/{id}/artifacts`, `DELETE /api/runs/{id}`

## Deployment and submission

`Dockerfile`, `compose.yaml` and `Caddyfile` provide an authenticated private HTTPS
deployment with a non-root, read-only application container and persistent SQLite
volume. Public hosting still requires a server, DNS name and operator-managed
secrets. See `docs/DEPLOYMENT.md`, `docs/SECURITY.md` and `submission/`.

Issue2Proof is MIT licensed. Upstream fixtures retain their original licenses.
