# Record the live MCP workflow

The completed Codex recording is available at `submission/codex-mcp-demo.mp4`.
Its compact, reviewable result packet is
`artifacts/codex-mcp-live-validation.json`. The instructions below reproduce the
same two-tool workflow without exposing credentials.

This recording shows the real `recall_repository_memory → audit_repository_revision`
loop through an MCP-compatible coding agent. It uses the bundled historical
Werkzeug repository and produces a real `memory_conflict` verdict from Nebius
Sandbox replay.

## Before recording

Use a 1920 × 1080 desktop, browser and terminal zoom at 100%, and a visible cursor.
Record only the application and agent windows. Keep `.env`, API keys, application
tokens, shell history, notifications and account menus outside the captured area.

Capture this segment without narration. A synchronized voice track and captions
will be added when the clip is merged into the final demo. Aim for 35–45 seconds.

The live audit consumes a small amount of Nebius Sandbox credit and may use one
Nemotron conflict-analysis call. The configured audit ceiling is $0.75; actual
recorded Werkzeug validation used three sandbox calls and two model calls within
that ceiling.

## 1. Start the private Issue2Proof service

From the repository root, confirm that `.env` contains the activated Nebius
project ID, API key, and a private Issue2Proof access token. Do not display the
file while recording.

```sh
. .venv/bin/activate
set -a
. ./.env
set +a
./scripts/start.sh
```

Leave that terminal outside the recording crop. The service runs at
`http://127.0.0.1:8000`.

## 2. Seed the verified Werkzeug capsule

Run this before recording. It promotes the saved checks-passed report using the
same evidence gate as a new investigation.

```sh
curl --silent --show-error \
  -H "Authorization: Bearer $ISSUE2PROOF_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"repository_key":"pallets/werkzeug"}' \
  http://127.0.0.1:8000/api/examples/real-bug-werkzeug/memory
```

Do not show this command in the recorded clip because the shell contains a secret
environment reference. The endpoint is idempotent for the same source report.

## 3. Configure the MCP host

Use `integrations/mcp.example.json` as the template. Set the command path to the
absolute repository location and keep the access token in the host's protected
environment or secret store.

```json
{
  "mcpServers": {
    "issue2proof": {
      "command": "python",
      "args": ["/absolute/path/to/issue2proof/scripts/mcp_server.py"],
      "env": {
        "ISSUE2PROOF_URL": "http://127.0.0.1:8000",
        "ISSUE2PROOF_ACCESS_TOKEN": "stored-outside-the-recording"
      }
    }
  }
}
```

Start the MCP host with the Issue2Proof repository as its working directory. This
allows the audit tool to package the bundled fixture below the process boundary.

## 4. Record this exact agent prompt

Open a fresh agent session and enter:

> Before changing Werkzeug `safe_join`, use Issue2Proof to recall verified memory
> for “Refactor safe_join and Windows path normalization” in repository
> `pallets/werkzeug`. Do not edit any files. Then audit the current revision at
> `examples/real-bugs/werkzeug-safe-join` with the recalled memory ID. Wait for the
> final verdict and explain only the observed evidence.

Keep the cursor near each tool card while it is explained. The clip should visibly
show:

1. `recall_repository_memory` invoked by the agent;
2. the Windows device-name behavioral claim and regression hash;
3. `audit_repository_revision` invoked with the returned capsule ID;
4. the queued or running audit state;
5. the final `memory_conflict` verdict;
6. the assertion showing that `safe_join("trusted", "CON")` returned a path;
7. the recorded network-disabled sandbox evidence.

Do not wait on an empty terminal in the final clip. Cut the waiting interval between
the running state and completed verdict.

## 5. Upload for final assembly

Upload the original MP4 without extra captions, music, or voice processing. Include
the capture resolution and frame rate in the upload message. The final edit will
add the technical narration, pointer emphasis, chapter title, and captions in a
dedicated lower band that does not cover the application.

If the live audit cannot be completed, upload a screen recording that opens
`artifacts/mcp-audit-live-validation.jsonl` and follows the initialize, tool list,
and completed audit packets. Label that segment “recorded live validation” rather
than presenting it as a fresh run.
