# Deploy the live judge instance on Railway

The Vercel deployment is a credit-free recorded-evidence product tour. This
Railway service is the real authenticated application: judges can import a new
Python repository, authorize bounded provider work, and inspect fresh Nemotron
and Nebius Sandbox evidence.

## 1. Create the service

1. In Railway, choose **New Project → Deploy from GitHub repo**.
2. Select `kushalar03/issue2proof` and the `main` branch.
3. Railway detects `railway.json` and builds the supplied `Dockerfile`.
4. Add a persistent volume mounted at `/data`. The application stores SQLite job,
   budget, memory, and evidence state in `/data/runs.sqlite3`.
5. Generate a public Railway domain after the first healthy deployment.

Do not deploy this backend to a stateless serverless function. Durable jobs and
SQLite require one persistent container and the `/data` volume.

## 2. Configure private variables

Set these variables in Railway. Never put their values in GitHub, Vercel, a demo
video, or a public Devpost field.

```text
ISSUE2PROOF_PUBLIC=1
ISSUE2PROOF_ACCESS_TOKEN=<random value with at least 32 characters>
NEBIUS_API_KEY=<private Nebius API key>
NEBIUS_PROJECT_ID=aiproject-e00sh5janzbr6dp49w
NEBIUS_SANDBOX_IMAGE=python:3.12-slim
ISSUE2PROOF_DAILY_BUDGET_USD=2.25
ISSUE2PROOF_TOTAL_BUDGET_USD=3.50
ISSUE2PROOF_PROTECTED_RESERVE_USD=1.00
ISSUE2PROOF_RETENTION_DAYS=7
```

The values above permit at most $2.50 of spendable work over the lifetime of that
database and at most $2.25 on one UTC day. The final $1.00 remains protected. The
provider account's own billing limit remains the outer control.

## 3. Validate before sharing

Open the Railway URL and sign in with `ISSUE2PROOF_ACCESS_TOKEN`. Confirm that:

1. `/api/health` reports authentication required, model configured, and remote
   sandbox configuration complete;
2. the saved Werkzeug evidence opens without provider spend;
3. one small repository can be imported;
4. a paid investigation requires the explicit authorization checkbox;
5. the Budget panel shows the configured daily, lifetime, and protected amounts;
6. the service remains healthy after a restart and saved records remain available.

Use `https://github.com/pallets/itsdangerous` for the judge smoke test and describe
this behavior:

> `URLSafeTimedSerializer.loads` must reject signatures older than `max_age`,
> while valid non-expired signatures and ordinary serialization round trips must
> continue to work.

Stop after one fresh investigation during validation. Repeated rehearsals consume
the same allowance intended for judges.

## 4. Give judges access

Put the Railway application URL in the Devpost **Try it out** or testing field.
Place the temporary `ISSUE2PROOF_ACCESS_TOKEN` only in the private judging/testing
instructions when Devpost provides such a field. If every submission field is
public, provide the Vercel demo URL publicly and state that live-backend access is
available to judges on request; do not publish the token.

Recommended testing note:

> Open the live application and sign in with the supplied judge access token.
> Saved real evidence can be reviewed without spending credits. For one fresh
> trial, import the suggested small Python repository, inspect it, enable the
> explicit Nebius authorization checkbox, and start the investigation. The
> application enforces daily, lifetime, request-count, repair-count, and sandbox
> limits. If the live allowance is exhausted, the Vercel product tour and all
> saved evidence remain available.

## 5. End or rotate access

After judging, rotate `ISSUE2PROOF_ACCESS_TOKEN`, remove the public Railway domain,
or stop the service. Preserve `/data/runs.sqlite3` only if the evidence remains
useful and handle its backups as source-code data.
