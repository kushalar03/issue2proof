# Offline upload example

Upload `pricing-project.zip` through the browser and use this bug report:

> An excess discount makes the total negative. Clamp the total to zero while preserving normal order totals.

Inspection makes no model request. Before generating a draft, reserve
`tests/test_boundaries.py` as an independent check. Draft generation sends the
remaining reviewed fixture context to Nebius only when explicitly selected.
The sample is a synthetic reviewed fixture, not a held-out real bug.
