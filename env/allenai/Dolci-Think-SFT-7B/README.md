# Dolci-Think-SFT-7B: instruction-following audit

At [revision `72ec0fe`](https://huggingface.co/datasets/allenai/Dolci-Think-SFT-7B/tree/72ec0fe32428bada1ec686a9168a0681eecd2094), we scanned all **358,915 IF rows** in the 2,268,178-row SFT mix: 223,123 Persona IF and 135,792 Precise IF. The scan covered their complete, contiguous source blocks in the published Parquet shards. Results below are scoped to those two sources.

| Finding | Measured scope | Interpretation |
| --- | ---: | --- |
| Exact paragraph count followed by a requirement for a later nonexistent paragraph | **46 Precise IF rows** | Confirmed contradiction; [row 1264478](findings/ER-52276d60.yaml) is a reviewed witness |
| “Entire response” must be lowercase; final answer is lowercase, but `<think>` contains capitals | **4,566 / 4,571 matching rows** | Confirmed stored-message mismatch; [row 1264375](findings/ER-f2addcc0.yaml) is a reviewed witness. Whether reasoning is exempt needs an explicit contract |
| “Entire response” bans `!`; final answer has none, but `<think>` contains `!` | **1,413 / 5,727 matching rows** | Same scope issue; counts overlap with other flags |
| Post-`</think>` answer itself violates the matched lowercase or `!` requirement | **3 lowercase rows; 6 exclamation rows** | Narrow literal checks, not a complete IF failure rate |

The contradiction reproduces the issue seen in [Dolci-Think-RL-7B](../Dolci-Think-RL-7B/README.md). In contrast, our [AutoIF-FI](../../LumiOpen/AutoIF-FI/README.md) scan found no conflict under its targeted mechanical rules. Different constraints, selection rules, and training uses prevent a direct quality-rate comparison.

**Method and limit.** We scanned every published row whose `dataset_source` is `allenai/persona-precise-if-r1-final-content-filtered-chinese-filtered` or `saumyamalik/if_qwq_reasoning_verified_filtered_decontam_v2`. The paragraph rule requires explicit “There should be N paragraphs” and “Paragraph M must start” clauses with `M > N`. The format counts use the exact lowercase and no-exclamation instruction phrasings, comparing the complete saved assistant `messages[].content` with the text after `</think>`. The dataset card says reasoning is stored in `<think>` within the assistant message. The public SFT schema does not publish verification functions or pass/fail records, so we cannot establish which component checked which span. Unflagged rows remain unlabeled.
