# Deploy the live judge instance on Render

Render is the fallback deployment for the real authenticated application while
Railway blocks new account creation. The existing Vercel site remains the
credit-free public tour. Render runs the Docker application with a persistent
disk, allowing judges to import a new repository and request bounded Nemotron and
Nebius Sandbox execution.

## 1. Create a Blueprint

1. Sign in at https://dashboard.render.com with GitHub.
2. Choose **New → Blueprint**.
3. Connect `https://github.com/kushalar03/issue2proof`.
4. Render reads `render.yaml` and proposes the `issue2proof-live` web service, a
   1 GB persistent disk mounted at `/data`, and the non-secret budget variables.
5. Select the Starter instance required for a persistent disk. Confirm the current
   Render price before creating the service.

The application cannot safely use Render's stateless free tier because job,
budget, Memory Capsule, and evidence records must survive container restarts.

## 2. Enter the two private values

Render prompts for variables marked `sync: false`:

- `ISSUE2PROOF_ACCESS_TOKEN`: generate a random value of at least 32 characters;
- `NEBIUS_API_KEY`: enter the private Nebius API key.

Never place either value in GitHub, Vercel, a recording, or a public Devpost
field. The Nebius project ID and bounded budget values are already declared in the
Blueprint.

## 3. Validate the deployment

Render supplies a URL similar to:

```text
https://issue2proof-live.onrender.com
```

Open that URL, sign in with `ISSUE2PROOF_ACCESS_TOKEN`, and verify:

1. `/api/health` reports that authentication is required and the remote provider
   configuration is complete;
2. saved Werkzeug evidence opens without spending provider credit;
3. the Budget panel shows $2.25 daily, $3.50 lifetime, and $1.00 protected;
4. records remain available after a manual service restart;
5. one approved small-repository investigation reaches a terminal result.

Use `https://github.com/pallets/itsdangerous` for the single smoke test with this
behavior description:

> `URLSafeTimedSerializer.loads` must reject signatures older than `max_age`,
> while valid non-expired signatures and ordinary serialization round trips must
> continue to work.

## 4. Submit the correct URLs

- Devpost **Try it out / Live app**: the Render `onrender.com` URL.
- Public product tour: https://issue2proof-demo.vercel.app
- Source code: https://github.com/kushalar03/issue2proof
- Video: the uploaded `submission/final-demo.mp4` URL.

Put the temporary judge access token only in a private testing-instructions field.
If Devpost exposes every field publicly, do not publish the token. Use the Vercel
tour as the public URL and state that authenticated live access is available to
judges on request.

Saved evidence and the Vercel site do not spend Nebius credit. Fresh Render
investigations share the configured allowance. When the allowance is exhausted,
paid operations stop while saved evidence remains available.
