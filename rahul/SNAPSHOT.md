# Stable snapshot

This is Rahul's independent `rlaudit` toolkit, exported from the completed shared-adapter release. It does not change the parent repository's finding schema, scope, or review workflow. Historical findings remain evidence from that investigation and are not added to the shared task index.

The implementation in `src/rlaudit/` exactly matches the archived engine validated by 81 tests and 34 Prime component cases, with four preserved findings and matching frozen replays. `SNAPSHOT.json` records its source hashes and Slurm job IDs. The ongoing 100-environment experiment is excluded.

Run toolkit commands from this `rahul/` directory; see [README.md](README.md). The local toy and Verifiers demo inputs are included. Bulk cached datasets and database state files are omitted, so cached-data examples require reacquiring their declared inputs. The existing source hashes and preparation scripts identify those inputs. Project memory and transient logs are excluded.

The parent repository treats downloaded corpus code as inert data. Source-backed integration checks and environment execution require an approved isolated runtime; the original compute validation is historical evidence, not authorization to execute downloaded graders on the host.

Export verification on `amd-tw-verification` (job55740): 13 engine file hashes matched; 73 toolkit tests passed, 8 source-execution/cached-data checks skipped; all 96 destination-repository tests passed and its catalog remained structurally valid.
