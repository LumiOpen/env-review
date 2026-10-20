# Add an environment without a driver

This small token-copy environment uses the actual pinned Verifiers v0 runtime.
`environment.py` is the environment being audited, not an audit driver.
`contract.json` declares its loader, row binding, metric, and exact-text oracle.
`pipeline.json` supplies a correct and incorrect completion to the same shared
adapter used by the three Prime packages.

From the repository root:

```sh
PYTHONPATH=src python -m rlaudit plan examples/verifiers_demo/pipeline.json
PYTHONPATH=src python -m rlaudit run examples/verifiers_demo/pipeline.json --output runs/demo-new
```

Execution is submitted to `amd-tw-verification`; wait for the returned job ID
before verifying the bundle. Expected rewards are `[1, 0]`, with no finding.
This synthetic example validates adapter reuse, not an upstream environment.
See [environment contracts](../../docs/environment-contracts.md) for the schema,
replay requirements, and current runtime limitations.
