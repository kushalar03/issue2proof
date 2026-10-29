# Deploy the live judge instance on Render Free

Render is the fallback deployment for the real authenticated application while
Railway blocks new account creation. The existing Vercel site remains the
credit-free public tour. Render Free runs the Docker application without a
persistent disk, allowing judges to import a new repository and request bounded
Nemotron and Nebius Sandbox execution. Its local state is temporary, so this setup
is intended for a bounded hackathon trial rather than durable production hosting.

## 1. Create a Blueprint

1. Sign in at https://dashboard.render.com with GitHub.
2. Choose **New → Blueprint**.
3. Connect `https://github.com/kushalar03/issue2proof`.
4. Render reads `render.yaml` and proposes the free `issue2proof-live` web service
   with the non-secret budget variables.
5. Create the Blueprint without adding a persistent disk.

Render Free may sleep after inactivity. Its first request can take approximately
one minute while the container starts. SQLite data normally remains available
while that container lives, but a restart or redeployment can erase investigations,
Memory Capsules, job history, and application budget usage. Bundled reviewed
evidence remains available because it is part of the image.

## 2. Enter the private values

Render prompts for variables marked `sync: false`:

- `ISSUE2PROOF_ACCESS_TOKEN`: generate a random administrator value of at least 32 characters and keep it private;
- `ISSUE2PROOF_JUDGE_TOKEN`: generate a different random value of at least 32 characters and give only this restricted value to judges;
- `ISSUE2PROOF_CAPSULE_SIGNING_KEY`: generate a third random value of at least 32 characters for authenticated Memory Capsule bundles;
- `NEBIUS_API_KEY`: enter the private Nebius API key.

Never place any private value in GitHub, Vercel, a recording, or a public Devpost
field. The Nebius project ID and bounded budget values are already declared in the
Blueprint.

Set a matching **$25 hard spending limit in the Nebius account**. Render Free uses
ephemeral storage, so a restart or redeployment can erase the local lifetime
ledger. The provider limit is the authoritative protection against charges after
the allocation is consumed.

## 3. Validate the deployment

Render supplies a URL similar to:

```text
https://issue2proof-live.onrender.com
```

Open that URL, sign in with `ISSUE2PROOF_JUDGE_TOKEN`, and verify:

1. `/api/health` reports that authentication is required and the remote provider
   configuration is complete;
2. saved Werkzeug evidence opens without spending provider credit;
3. the Budget panel shows a $25.00 daily and lifetime allowance with no overage reserve;
4. one approved small-repository investigation reaches a terminal result;
5. the bundled reviewed evidence remains available after a restart.

Use `https://github.com/pallets/itsdangerous` for the single smoke test with this
behavior description:

> `URLSafeTimedSerializer.loads` must reject signatures older than `max_age`,
> while valid non-expired signatures and ordinary serialization round trips must
> continue to work.

For conservative testing, change **Scheduling allowance** from the UI default of
`$2.00` to `$0.75`. The application stops new paid actions when its retained
ledger reaches $25 and returns HTTP 402 for synchronous paid requests.

## 4. Submit the correct URLs

- Devpost **Try it out / Live app**: the Render `onrender.com` URL.
- Public product tour: https://issue2proof-demo.vercel.app
- Source code: https://github.com/kushalar03/issue2proof
- Video: the uploaded `submission/final-demo.mp4` URL.

Put the temporary judge access token only in a private testing-instructions field.
If Devpost exposes every field publicly, do not publish the token. Use the Vercel
tour as the public URL and state that authenticated live access is available to
judges on request.

Saved evidence and the Vercel site do not spend Nebius credit. The free Render
instance permits at most $1.00 of application-scheduled work before its protected
reserve. Because ephemeral state can reset, configure a Nebius account-level
spending limit as the authoritative cap. When the live allowance is exhausted,
paid operations stop while bundled evidence remains available.
