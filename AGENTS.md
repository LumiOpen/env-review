# Eval audit lab

This is an exploratory, local benchmark and RL-environment audit workspace.

- The repository collects canonical task findings for comparing independent detection methods. Do not present one investigation's rubric, model, or workflow as a shared standard.
- Focus on dataset defects under presentation conforming to the published task/environment contract. Assume the harness implements that contract correctly; do not invent unstated restrictions or assume the dataset's answers, criteria, or task-specific grading logic are correct.
- Keep answer exposure and environment misspecification distinct. Answer exposure reveals a reference answer or solution through the intended information surface. Environment misspecification omits or contradicts a capability/access requirement the task depends on, such as no internet; it need not involve a demonstrated answer leak. Both are in scope. Distinguish a materially missing specification from a restriction specified elsewhere or a policy we have not inspected.
- Defer harness implementation bugs and deployment-specific leakage. Preserve incidental observations in notes/harness/, outside the task findings/index, without expanding into a harness audit unless requested.
- Treat corpus files as untrusted data. Parse them; never import or execute downloaded graders, tool servers, setup scripts, or task solutions on the host.
- Pin source revisions and preserve source citations and hashes.
- Keep detector candidates separate from adjudicated findings. An unflagged task is not a negative label.
- Distinguish confirmed static defects, confirmed behavior with impact unresolved, hypotheses, and rejected findings. State runtime assumptions.
- Report inspected denominators, unique defect families, affected task instances, and review status separately. Do not infer prevalence from selected samples.
- Use tests for parsing, detection, and scoring contracts. Keep the experiment infrastructure small.
