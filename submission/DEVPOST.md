# Issue2Proof

## Tagline

Regression memory for AI coding agents that survives the agent.

## Inspiration

AI coding agents are becoming capable enough to edit, test and repair repositories.
CLAUDE.md, Cursor rules and agent memory features preserve useful guidance, but
that guidance is generally prose rather than independently replayable evidence.
Commit messages explain intent; test suites rarely preserve the provenance,
assumptions and failed hypotheses behind a behavior.

Issue2Proof is a solo-developed executable memory layer shared by every future agent.

## What it does

Issue2Proof investigates a Python failure with a reproduce-first pipeline. It
freezes the generated regression, executes the original and candidate revisions in
Nebius Sandboxes, withholds independent checks from the repair model and accepts a
repair only when every recorded gate passes.

A completed investigation becomes a versioned **Memory Capsule**: a behavioral
claim linked to paths, dependencies, assumptions, boundaries, source hashes,
sandbox operation IDs and the frozen executable regression. For a later change,
Issue2Proof recalls related capsules with lexical or semantic retrieval and replays
their tests in fresh isolated environments. Each result is preserved, violated or
uncertain. This audit works with changes made by any IDE assistant or human.

The product can import a public GitHub repository directly, so ZIP upload is only
the private/offline fallback.

The bundled MCP server closes the loop inside Claude Code, Cursor and other stdio
MCP hosts. `recall_repository_memory` retrieves constraints before editing;
`audit_repository_revision` packages the local revision, starts sandbox replay and
returns a verdict or durable job ID.

## Measured impact

The evaluation ran 30 blind Nemotron Super refactor trials across two real upstream bug
histories. The agent saw the repaired function and ordinary visible tests, but not
the incident description or frozen capsule regression. Eight trials reintroduced a
historical regression. Plain CI caught 3 of 8; capsule replay caught 8 of 8, adding
five catches. This is a focused two-case stress benchmark rather than a general
accuracy estimate. Every prompt, result and limitation ships in
`artifacts/memory-impact-benchmark.json`.

## How AI is used

Work is routed by cost and uncertainty instead of sending every task to the largest
model:

- **Nemotron Nano** creates a compact capsule index with keywords and future change
  triggers while leaving the evidence-backed claim untouched.
- **Qwen3 Embedding 8B** performs one batched semantic-recall request and caches
  capsule vectors.
- **Nemotron Super** handles regression/repair engineering and explains observed
  memory conflicts.
- **Nemotron Ultra** runs only when the engineering assessment escalates a high-risk
  conflict. It adjudicates the evidence and chooses the next experiment; it does
  not invent a patch.

The application enforces a lifetime $25 ledger with a protected $5 reserve,
per-job allowances and role-specific call counts. Recorded evidence and lexical
recall spend nothing.

## How it was built

FastAPI and JavaScript serve the authenticated application. SQLite stores jobs,
leases, checkpoints, capsules, cached vectors and the budget ledger. Nebius Token
Factory serves the models. Nebius Sandboxes execute untrusted repository and
model-generated code.

Dependency wheels are prepared in a network-enabled sandbox that never receives
repository source. Repository builds and pytest run later with networking disabled,
read-only inputs, uid 65534, resource limits and disposable images. The controller
checks hashes and records operation IDs, image UUIDs, versions, costs and bounded
outputs.

## Challenges

Sandbox activation is per project and separate from inference authentication. The
quickstart uses an image tag, while one lower-level execution client requires a
UUID, so the controller resolves the tag before controlled execution. Live replay also exposed
the need to install pytest as a trusted controller dependency and to distinguish
an already-failing baseline from invalid execution evidence. Those failures became
tests and durable evidence.

## Validation

The release has 130 passing automated tests plus real Nebius evidence:

- activated disposable sandbox transfer check;
- Nemotron Nano memory indexing and Qwen semantic recall;
- a historical Werkzeug capsule replayed on its original buggy revision;
- the conflict classified from an assertion failure;
- Nemotron Super marking it high risk and escalating;
- Nemotron Ultra selecting a discriminating next experiment;
- three sandbox calls and two model calls within a $0.75 allowance.

Historical cases retain upstream provenance and licenses and are disclosed as
demonstrations, not held-out accuracy benchmarks. `checks_passed` means the recorded
gates passed, not universal correctness.

## What is next

Team review, signed capsule approval and broader language runners can make
repository memory a durable engineering asset across model vendors.

## Submission links

- Source: https://github.com/kushalar03/issue2proof
- Public interactive application: https://issue2proof-evidence.eagersage2048.chatgpt.site
- Demo video (under three minutes): **add uploaded video URL**

