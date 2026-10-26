# Public interactive demo

This directory publishes the same light workspace used by the authenticated
application and shown in the demo video. Its buttons operate on compact reviewed
evidence summaries through `demo-api.js`, so public visitors can inspect reports, run the
reviewed scenario, recall a Memory Capsule and create a capsule without receiving
an application token or spending project credits.

From the repository root:

```sh
python3 -m http.server 9000 --bind 127.0.0.1 --directory submission/demo
```

Open http://127.0.0.1:9000. The hosted version is available at
https://issue2proof-evidence.eagersage2048.chatgpt.site.

The authenticated FastAPI application uses the same frontend from
`issue2proof/static/` and performs fresh model and sandbox operations when a
signed-in operator explicitly authorizes them.

## Vercel

Import the repository into Vercel and set the project root directory to
`submission/demo`. Select **Other** as the framework preset and leave the build
command empty. Vercel publishes the static files directly and applies the security
headers in `vercel.json`.
