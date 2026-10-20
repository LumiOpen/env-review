# Dolci-Think-SFT-7B: instruction-following audit

At [revision `72ec0fe`](https://huggingface.co/datasets/allenai/Dolci-Think-SFT-7B/tree/72ec0fe32428bada1ec686a9168a0681eecd2094), we scanned all **358,915 IF rows** in the 2,268,178-row SFT mix: 223,123 Persona IF and 135,792 Precise IF. The scan covered their complete, contiguous source blocks in the published Parquet shards. Results below are scoped to those two sources.

| Finding | Measured scope | Interpretation |
| --- | ---: | --- |
| Exact paragraph count followed by a requirement for a later nonexistent paragraph | **46 Precise IF rows** | Confirmed contradiction; [row 1264478](findings/ER-52276d60.yaml) is a reviewed witness |
| Final answer contains `!` despite an explicit ban | **4 / 5,727 matching rows** | Confirmed answer violations; [row 1060881](findings/ER-7eb9a86f.yaml) is a reviewed witness |
| Final answer contains capitals despite the exact lowercase instruction | **0 / 4,571 matching rows** | Narrow literal check; other IF constraints remain untested |

The contradiction reproduces the issue seen in [Dolci-Think-RL-7B](../Dolci-Think-RL-7B/README.md). In contrast, our [AutoIF-FI](../../LumiOpen/AutoIF-FI/README.md) scan found no conflict under its targeted mechanical rules. Different constraints, selection rules, and training uses prevent a direct quality-rate comparison.

**Method and limit.** We scanned every published row whose `dataset_source` is `allenai/persona-precise-if-r1-final-content-filtered-chinese-filtered` or `saumyamalik/if_qwq_reasoning_verified_filtered_decontam_v2`. The paragraph rule requires explicit “There should be N paragraphs” and “Paragraph M must start” clauses with `M > N`. Format checks apply only to the final answer after the last `</think>`, excluding reasoning. They match the exact lowercase and no-exclamation instruction phrasings. The public SFT schema does not publish verification functions or pass/fail records, so these answer violations do not establish checker behavior. Unflagged rows remain unlabeled.
