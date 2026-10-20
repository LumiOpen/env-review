# MiMo reference runtime and information access

Source review on 2026-10-20. This describes the published reproduction code and
the inspected task sample. It does not establish the original training
deployment, running container contents, or actual network reachability. We did
not launch a task, pull or execute its image, execute downloaded Python, probe
network access from a task, or invoke a judge.

## Published implementation

The [dataset card](https://huggingface.co/datasets/XiaomiMiMo/MiMo-V2.6-RL-oss/blob/e8e81e4945270b6212204bad99de1e598f7fb077/README.md)
links training code and Docker images. The
[verl fork's README](https://github.com/XiaomiMiMo/verl/blob/79090e58195e80a9cfe251c95ae7a78a2132b6e2/README.md#L1-L28)
identifies reproduction recipes for Code, Cyber, General, Visual, and Music.
Its `mimoagent` dependency supplies agent harnesses, tools, environments, and
graders for the first four; Music uses neither of the listed agent submodules.

Inspected versions:

| Component | Revision |
| --- | --- |
| HF MiMo dataset | `e8e81e4945270b6212204bad99de1e598f7fb077` |
| `XiaomiMiMo/verl` | `79090e58195e80a9cfe251c95ae7a78a2132b6e2` |
| `XiaomiMiMo/mimoagent` | `c3df8469f250b15e7906487a6d52be4c1827a509` |

The inspected verl commit pins exactly that mimoagent commit at
`third_party/mimoagent-osr`. They are a matching pair, rather than independently
chosen library versions. Overrides, image digests, and cluster policy still
need to be recorded for a concrete run.

Task-side inspection used the existing 34-task cache: 34 manifests, 34 root
instructions, and 224 Python files under task `tools/` directories. The complete
pinned inventory contains 925 knowledge-work environment directories. Text
screens of the cached tools found no browser/search tool or common outbound
network client; the shell capability comes from the surrounding harness.

## Knowledge-work path

The published
[general agent-loop configuration](https://github.com/XiaomiMiMo/verl/blob/79090e58195e80a9cfe251c95ae7a78a2132b6e2/recipes/general/config/general_agent_loop.yaml)
selects `GeneralAgentLoop` and `config/agent/general/s3k.yaml`.
The [s3k profile](https://github.com/XiaomiMiMo/verl/blob/79090e58195e80a9cfe251c95ae7a78a2132b6e2/config/agent/general/s3k.yaml#L4-L68)
declares Bash, Read, Write, Edit, Grep, and Glob. The runtime additionally
[discovers the task's MCP tools](https://github.com/XiaomiMiMo/verl/blob/79090e58195e80a9cfe251c95ae7a78a2132b6e2/recipes/general/env_actor.py#L154-L183).
Thus the solving agent's capabilities are broader than the functions listed
in an individual task's `tools/` directory.

The intended sequence, traced in code:

1. Create a pod with `main` and `sidecar` containers. Main mounts the writable
   workspace; sidecar mounts the workspace read-only and the database volume.
   Main does not mount that database volume.
2. [Upload setup materials](https://github.com/XiaomiMiMo/verl/blob/79090e58195e80a9cfe251c95ae7a78a2132b6e2/recipes/general/general_agent/environment.py#L340-L373)
   according to each task's manifest and start its MCP services in the sidecar.
   Agent shell commands target main; MCP calls reach the local sidecar services.
3. Let the agent work through file/shell tools and MCP functions. Database
   effects should occur through the exposed task tools.
4. [Upload verifier materials at reward time](https://github.com/XiaomiMiMo/verl/blob/79090e58195e80a9cfe251c95ae7a78a2132b6e2/recipes/general/general_agent/environment.py#L523-L556),
   copy the answer/trajectory evidence, run the verifier in the sidecar, and
   collect the reward. Manifest normalization
   [rejects a verifier configured to run in main](https://github.com/XiaomiMiMo/verl/blob/79090e58195e80a9cfe251c95ae7a78a2132b6e2/recipes/general/general_agent/environment.py#L244-L258).

This establishes how the source code routes these uploads. It does not prove
that the same materials are absent from every image, copied workspace asset,
tool response, or external source. Those are separate answer-exposure checks.
Likewise, sidecar separation does not make every exposed MCP operation safe.

## Internet access and lookup instructions

Internet access is a property of the agent's tools and deployment, not the
model weights. No browser tool is necessary when a shell can run a network
client. Conversely, a network connection used by the host to call a model or
judge does not itself give the solving agent web access.

The inspected s3k system template has no explicit prohibition on online
lookup. It says the agent can use its available tools to complete the task.
An English/Chinese keyword screen of the 34 cached root instructions also
identified no explicit internet prohibition. This was not an exhaustive
semantic review of every instruction or of all 925 tasks.
This does not resolve whether a particular external source is permitted by
task instructions or by the experiment's intended information boundary.

The profile empties HTTP/HTTPS proxy variables. The pod builder uses
`hostNetwork: false`. **Neither is an outbound firewall.** The inspected
[base pod builder](https://github.com/XiaomiMiMo/mimoagent/blob/c3df8469f250b15e7906487a6d52be4c1827a509/src/mimoagent/environments/kubernetes.py#L217-L262)
does not establish an egress NetworkPolicy. An external cluster policy or lack
of routing could nevertheless block outbound access. Actual rollout internet
reachability is therefore **unknown**, not confirmed enabled or disabled.

Other supported backends illustrate why the execution profile matters:

- [Docker](https://github.com/XiaomiMiMo/mimoagent/blob/c3df8469f250b15e7906487a6d52be4c1827a509/src/mimoagent/environments/docker.py#L11-L62)
  accepts extra `run_args`; its default command has no explicit network block.
- [Modal](https://github.com/XiaomiMiMo/mimoagent/blob/c3df8469f250b15e7906487a6d52be4c1827a509/src/mimoagent/environments/modal.py#L87-L89)
  offers `block_network`, defaulting to false in the inspected source.
- Kubernetes supports an optional
  [`answer_leak_blocklist`](https://github.com/XiaomiMiMo/mimoagent/blob/c3df8469f250b15e7906487a6d52be4c1827a509/src/mimoagent/environments/kubernetes.py#L83-L88),
  implemented by [appending hostnames to `/etc/hosts`](https://github.com/XiaomiMiMo/mimoagent/blob/c3df8469f250b15e7906487a6d52be4c1827a509/src/mimoagent/environments/datasets/base.py#L148-L170).
  This is a hostname blocklist, not general egress isolation; s3k does not set it.
- The library documents that
  [blackbox CLI installation needs setup-time network access](https://github.com/XiaomiMiMo/mimoagent/blob/c3df8469f250b15e7906487a6d52be4c1827a509/README.md#L125-L131),
  with prebuilt payloads available for offline setups. Setup-time access does
  not establish rollout-time access.

An online lookup of a task's public grading material is a plausible shortcut
to investigate if egress is available. The public release's existence alone
does not prove retrieval, an effective grading advantage, or availability
during the original training run.

For a concrete retrieval target, the public
[finance task metadata](https://huggingface.co/datasets/XiaomiMiMo/MiMo-V2.6-RL-oss/blob/e8e81e4945270b6212204bad99de1e598f7fb077/general/envs/s3k_0807_finance_insurance_en_t1_rl_005/verifier_meta.json#L24-L42)
states the expected recommendation ID `REC-2025Q3-003`, amount `$6,925,410.18`,
and required held-decision evidence. We fetched this pinned file from the
audit host and verified it matches the cached bytes (SHA-256
`1e4d4a24360271b2e8ea859b335c323183a64b58716527b2ce19180b38e147f6`).
That verifies public availability to the auditor. Whether the solver could
retrieve it remains unresolved; the task still has required state-changing
actions, so reading these anchors is not proof of a full-score shortcut.

## Anti-hack protections are separate mechanisms

The dataset and training READMEs announce strengthened Code anti-hack
preprocessing and instruct users to retain `anti_hack_cleanup: true`. The
published Code profile sets it. The
[code environment](https://github.com/XiaomiMiMo/mimoagent/blob/c3df8469f250b15e7906487a6d52be4c1827a509/src/mimoagent/environments/datasets/opensource_code.py#L102-L107)
also sanitizes Git history; its
[grading path](https://github.com/XiaomiMiMo/mimoagent/blob/c3df8469f250b15e7906487a6d52be4c1827a509/src/mimoagent/environments/datasets/opensource_code.py#L193-L215)
copies in the hidden test patch at reward time.

A distinct [runtime action guard](https://github.com/XiaomiMiMo/mimoagent/blob/c3df8469f250b15e7906487a6d52be4c1827a509/src/mimoagent/agents/antihack.py#L1-L39)
looks for reference-solution retrieval and protected-artifact access in selected
tool parameters. It is opt-in at the library level. The s3k YAML requests it
with `agent.antihack.enabled: true`. Cleanup, tool filtering, and network
isolation are different controls; none should be inferred from another.

In the inspected general RL path, the configured action guard is not applied.
Its
[`_RemoteToolAgent`](https://github.com/XiaomiMiMo/verl/blob/79090e58195e80a9cfe251c95ae7a78a2132b6e2/recipes/general/agent_loop.py#L384-L426)
subclasses `DefaultAgent` and replaces `execute_action` with a direct actor
call. The [actor dispatches `tool.execute`](https://github.com/XiaomiMiMo/verl/blob/79090e58195e80a9cfe251c95ae7a78a2132b6e2/recipes/general/env_actor.py#L256-L289).
`DefaultAgentConfig` has no `antihack` field and
[BaseAgent filters unknown configuration keys](https://github.com/XiaomiMiMo/mimoagent/blob/c3df8469f250b15e7906487a6d52be4c1827a509/src/mimoagent/agents/base.py#L138-L150).
We record this as a harness candidate based on static configuration and
dispatch evidence, pending isolated reproduction. It does not establish
successful answer retrieval or the original training deployment's behavior.

## Reusing the data with another runner

Extract an implementation-independent execution contract before choosing a
runner. Preserve the prompt, tools and their validation, initial state,
solver-visible files, hidden grading materials, upload timing, network policy,
state reset, and grading inputs. Pin each component separately.

A replacement runner should keep grader-only files out of the solving
workspace and preserve sidecar-equivalent database access boundaries. Any
intentional change, such as making the task offline, belongs in a named
execution profile and in the findings' assumptions. Portability mismatches and
reference-runtime defects should be recorded separately from task defects.

The current source review supports static auditing and runner design. It does
not require adopting their training stack or running their code on the host.
