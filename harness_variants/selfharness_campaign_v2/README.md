# Self-Harness campaign v2 frozen lineage

This directory preserves the exact provenance and promoted diff from the completed
three-round autonomous campaign recorded in
`docs/data/selfharness_campaign_v2_report.json`.

- source revision: `c9380454cba4b5da2843c5ca1e4316da73ad0841`
- round-0 Harness: `cd2d29eae108`
- final Harness: `a6a55ef4f4bf`
- changed component: `harness/system_prompt.md`
- unchanged component hashes are recorded in `manifest.json`

Materialize the control from `harness/` at the source revision and apply
`promoted.patch` to create the treatment. The source and treatment contents must hash
to the Harness versions above before running a causal A/B.
