# Analysis of error lines found in validation

Special-token contamination in the `dolci_think_7B` CPT corpus, present in the raw
`dolci_think_7B.jsonl` before preprocessing. Line numbers are 1-based into that file.

Inspected denominator: **12 flagged documents out of 500,000 inspected**
(7,754,439,782 tokens). The corpus holds 2,268,179 documents in total; the remaining
1,768,179 were not scanned, so this is not a corpus prevalence rate.

| Line | Error token | Verdict |
|---|---|---|
| **9165** | `<\|endoftext\|>` ×22 | **FAIL — EOS-as-delimiter** |
| **30478** | `<\|im_start\|>` ×41, `<\|im_end\|>` ×37 | **FAIL — ChatML emitted as structure** |
| **37250** | `<\|im_start\|>` ×16, `<\|im_end\|>` ×10 | **FAIL — ChatML emitted as structure** |
| 38832 | `<\|endoftext\|>` ×1 | NO FAILURE |
| **40911** | `<\|im_start\|>` ×33, `<\|im_end\|>` ×31 | **FAIL — ChatML emitted as structure** |
| 51441 | `<\|im_start\|>` ×1, `<\|im_end\|>` ×1 | NO FAILURE |
| **56642** | `<\|endoftext\|>` ×19 | **FAIL — EOS-in-prose** |
| 60924 | `<\|im_start\|>` ×2, `<\|im_end\|>` ×2 | NO FAILURE |
| **62763** | `<\|endoftext\|>` ×27 | **FAIL — EOS-as-delimiter** |
| 63678 | `<\|im_start\|>` ×3, `<\|im_end\|>` ×2 | NO FAILURE |
| **63814** | `<\|endoftext\|>` ×13 | **FAIL — EOS-as-delimiter** |
| 78506 | `<\|im_start\|>` ×4, `<\|im_end\|>` ×3 | NO FAILURE |

7 fail, 5 clean. Counts are embedded occurrences only, so each `<|endoftext|>` row is one
lower than the original validation report, which included the legitimate terminal
end-of-document token.

## Error types

- **EOS-as-delimiter** — the assistant turn emits the real EOS token repeatedly as a
  section separator, each followed by fluent continuation (gaps of 50–84 tokens).
- **ChatML emitted as structure** — the assistant turn writes well-formed ChatML of this
  tokenizer's own template, including `<|im_start|>assistant` followed by a self-answer.
- **EOS-in-prose** — EOS appears mid-sentence as a token being discussed, immediately
  followed by a sentence continuation.

Lines marked NO FAILURE carry 1–7 occurrences inside quoted code or configuration (Jinja
`chat_template` strings, Ollama `TEMPLATE` blocks, a quoted `tokenizer.json`, prose naming
the tokens) with no repeating structure.

## Notes

The literal tag text is legitimate content in all 12 documents — they are WildChat
conversations about chat templates, tokenizers and Ollama Modelfiles. The defect is that
tokenization parsed the literal text into real control-token IDs (248044 `<|endoftext|>`,
248045 `<|im_start|>`, 248046 `<|im_end|>`) rather than ordinary sub-word pieces.


Source artifacts (internal):

- `dolci_think_7B/raw/dolci_think_7B.jsonl`
- validation report `VALID_500k_dolci_think_7B_text_document`,
  sha256 `9b538a245a935098310e5aa794ff918d68566bb0c787c2b8b63b1a59ed28b1ae`
- tokenized index `dolci_think_7B_text_document.idx`,
  sha256 `41c780e522f1b661ccf4c927865be64355a59293d0b69cf8b12f6360ee73ff0a`
