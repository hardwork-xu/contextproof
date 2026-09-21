# Contributing

Install Python 3.11 or later, then run `pip install -e '.[dev]'`, `pytest`, and
`ruff check .`. The runtime core has no external dependencies. Optional token
counting uses `pip install -e '.[tokens]'`.

Changes to evidence status rules need an adversarial regression example. Changes
to ranking need the same committed queries, snapshots, and budgets for both methods.
Keep negative results. Report actual hardware and environment with timings.

Do not commit upstream source archives, local indexes, credentials, or private
repository context. Benchmarks download explicitly listed public snapshots to
the ignored `work/` directory. Never execute target repository code during indexing.

Before calling a change a research contribution, compare it with the related work
in `docs/RESEARCH.md` and distinguish a hypothesis from a measured result.
