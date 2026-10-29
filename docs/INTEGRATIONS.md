# Integrating Issue2Proof with coding agents and CI

Issue2Proof is both a web application and a headless repository-memory service.
The web interface is useful for investigation and review. Agents and automation use
the same REST API, so teams do not need to replace their editor or coding agent.
The public Render workspace needs no token; private deployments can require one.

## Install as an MCP plugin

Issue2Proof includes `scripts/mcp_server.py`, a standard local MCP server exposing
`recall_repository_memory` and `audit_repository_revision`. Copy
`integrations/mcp.example.json` into the
MCP configuration used by your host and replace the absolute script path and
service URL. For a private service, keep `ISSUE2PROOF_ACCESS_TOKEN` in the host's
secret environment. Leave it unset for the public Render workspace.

The same adapter works with Claude Code, Cursor, Codex-compatible MCP hosts, VS
Code extensions and other clients that support local stdio MCP servers. Once
installed, the host can call the tool before editing code:

```json
{
  "change": "Refactor safe_join and Windows path normalization",
  "repository": "pallets/werkzeug",
  "semantic": true
}
```

Semantic recall is enabled by default and uses one budgeted
`Qwen/Qwen3-Embedding-8B` batch. Set `"semantic": false` for free lexical recall.
The October 21, 2026 Token Factory `/models` response listed no NVIDIA embedding
model, so the implementation does not substitute an unverified model name.

After editing, the host can close the loop in the same session:

```json
{
  "repository_path": ".",
  "change": "Refactor safe_join and Windows path normalization",
  "memory_ids": ["capsule-id-from-recall"],
  "wait_seconds": 120,
  "analyze_conflict": true,
  "allow_ultra": false
}
```

The audit tool creates a bounded ZIP from the host working directory, excludes
common credential and dependency paths, imports the revision, starts remote replay,
and returns a verdict or durable job ID. The path must remain below the MCP process
working directory. Ultra escalation is disabled by default to protect the budget.

The recall tool returns the same structured memory packet as the REST endpoint.
The AI platform remains responsible for editing code; Issue2Proof supplies verified
constraints and performs independent replay.

## Agent context packet

`POST /api/integrations/context` returns a vendor-neutral packet containing the
relevant behavioral claims, affected paths, assumptions, risk boundaries and
regression hashes. Regression source is deliberately withheld: the agent receives
the contract while Issue2Proof retains independent replay authority.

```json
{
  "query": "Refactor Windows path joining",
  "repository_key": "pallets/werkzeug",
  "semantic": false,
  "authorize_nebius": false,
  "limit": 5
}
```

Use the bundled CLI from Codex, Claude Code, Cursor tasks, a git hook or CI:

```sh
python scripts/agent_context.py \
  --url https://issue2proof-live.onrender.com \
  --repository pallets/werkzeug \
  --change "Refactor safe_join and path normalization"
```

For a protected private deployment, the optional token is read only from the
process environment. Do not put it in prompts, command arguments, repository
files or logs.

## Typical integrations

### Coding agent

Add a pre-task command that fetches the packet and place its JSON in the agent's
bounded repository context. The agent treats claims as constraints, not patch
instructions. After it prepares a revision, import that revision and start
`POST /api/projects/{run_id}/audit-memory` with the selected capsule IDs.

### Pull-request CI

The root composite action is a ready-to-use pull request Memory Gate. It validates
a portable bundle, combines pull request text with changed paths, recalls matching
capsules locally, and writes the verified claims and regression hashes into the
GitHub job summary. This recall-only mode has no provider cost.

Audit mode imports the bundle into a protected private Issue2Proof service, uploads the
checked-out repository as a bounded ZIP, replays matched regressions, and blocks
the check on `memory_conflict` or `memory_uncertain`. Store only the application
access token as a GitHub secret; never store a Nebius key in the repository. See
`docs/GITHUB_ACTION.md` for both workflows.

### Portable memory and historical adoption

`GET /api/memories/export` creates an `issue2proof.memory-bundle.v1` document with
per-capsule SHA-256 hashes and a manifest hash. `POST /api/memories/import`
revalidates the envelope, provenance, capsule content and frozen regression source.

Existing Issue2Proof report archives can seed memory without a model call:

```sh
python scripts/import_history.py artifacts/ \
  --repository-key owner/repository \
  --bundle-output .issue2proof/memory.json
```

Only `checks_passed` reports with a matching frozen regression hash are promoted.
Skipped records and reasons appear in the command output.

### IDE extension

Call the context endpoint when files in a capsule's scope change. Display claims
beside the diff, then offer a server-side replay action. The extension does not need
Nebius credentials because the private Issue2Proof service owns provider access and
budget enforcement.

### Direct REST or internal tools

Any system capable of HTTPS and JSON can use the API. FastAPI exposes the complete
OpenAPI schema at `/docs` and `/openapi.json`. Bearer authentication and signed web
sessions use the same application access policy.

The context packet is model-neutral and works through MCP, CLI, REST, CI and IDE
extensions.
