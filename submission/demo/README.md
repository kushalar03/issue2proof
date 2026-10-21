# Standalone evidence explorer

No credentials or Python dependencies are required. From the project root:

```sh
python3 -m http.server 9000 --bind 127.0.0.1 --directory submission/demo
```

Open http://127.0.0.1:9000. Switch among completed live repairs and a rejected bad
candidate; inspect logs and download evidence JSON. The page is self-contained,
works without an internet connection once served locally, and makes no paid API
calls. This is recorded evidence, not a fresh live model/verification request.

For a public working-demo URL, use the included manual GitHub Pages workflow after
publishing your repository. See ../PUBLISH.md.
