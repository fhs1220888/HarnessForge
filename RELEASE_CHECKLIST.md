# Release checklist

Target: `v0.1.0` portfolio release.

## Automated gate

```bash
make install
make release-check
git status --short
```

Expected:

- Ruff clean;
- full deterministic test suite passes;
- offline demo says `Scorecard integrity: VERIFIED`;
- working tree is clean;
- GitHub CI `Install`, `Lint`, `Offline evidence demo`, and `Test` steps are green;
- GitHub Pages deployment is green.

## Manual evidence audit

- `BENCHMARK.md` uses Terminal-Bench—not the native suite—as the capability headline.
- Every rate includes a numerator/denominator and interval.
- `docs/data/benchmark_scorecard.json` matches `make demo`.
- The rejected 4/5 candidate remains rejected and the live `harness/` is unchanged.
- No `.env`, API key, `runs/`, absolute local path, or benchmark workspace is tracked.
- README architecture links, evidence links, and Pages dashboard load successfully.

## Tagging commands

Run only after the automated and manual gates pass:

```bash
git tag -a v0.1.0 -m "HarnessForge v0.1.0"
git push origin v0.1.0
```

Use the `0.1.0` section of [CHANGELOG.md](CHANGELOG.md) as the GitHub release notes.
Tagging and publishing are intentionally separate from ordinary CI pushes.
