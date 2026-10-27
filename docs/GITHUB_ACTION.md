# Pull request Memory Gate

The repository includes a composite GitHub Action that recalls portable,
hash-backed Memory Capsules for each pull request. Local recall is free and needs
no service or provider key. Optional audit mode uploads the checked-out revision
to a private Issue2Proof service and replays matched regressions in fresh Nebius
Sandboxes.

Export memory from the API and commit the bundle:

```sh
curl -H "Authorization: Bearer $ISSUE2PROOF_ACCESS_TOKEN" \
  "$ISSUE2PROOF_URL/api/memories/export?repository_key=owner/repository" \
  > .issue2proof/memory.json
```

The portable bundle contains the frozen regression source so another trusted
Issue2Proof instance can import and replay it. Treat the bundle like repository
test code. Use the authenticated context endpoint instead when the regression must
remain hidden from the coding agent.

Add `.github/workflows/issue2proof.yml` to the protected repository:

```yaml
name: Issue2Proof
on: pull_request
permissions:
  contents: read
jobs:
  memory-gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: kushalar03/issue2proof@main
        with:
          memory-bundle: .issue2proof/memory.json
```

That mode verifies the bundle, matches pull request text and changed paths, and
adds a table of recalled claims to the job summary. It reports
`recall_required` when a relevant capsule exists.

For the closed replay loop, deploy the authenticated application on a persistent
server, add `ISSUE2PROOF_ACCESS_TOKEN` as a GitHub Actions secret, and configure:

```yaml
      - uses: kushalar03/issue2proof@main
        with:
          memory-bundle: .issue2proof/memory.json
          issue2proof-url: https://proof.example.com
          access-token: ${{ secrets.ISSUE2PROOF_ACCESS_TOKEN }}
          audit: "true"
          semantic: "true"
```

The action fails on `memory_conflict`, `memory_uncertain`, setup failure, or a
failed background audit. `memory_preserved` means only that the selected frozen
behaviors passed in the recorded environment.
