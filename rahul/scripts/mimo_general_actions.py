#!/usr/bin/env python3
"""Conservative source-only General prompt-action screen; no task code runs."""
from __future__ import annotations
import hashlib, json, re
from collections import Counter
from pathlib import Path
import requests
import pyarrow.parquet as pq

REV="e8e81e4945270b6212204bad99de1e598f7fb077"
REPO="XiaomiMiMo/MiMo-V2.6-RL-oss"
BASE=Path(__file__).resolve().parents[1]
PARQUET=BASE/"research/mimo/inventory/raw/general_train.parquet"
OUT=BASE/"research/mimo/general_actions"
EXCLUDED={"s3k_0000_accounting_audit_tax_en_t1_rl_008","s3k_0001_accounting_audit_tax_en_t1_rl_002","s3k_0001_accounting_audit_tax_en_t1_rl_003"}
MAX_BYTES=2_000_000
FILES=("instruction.md","verifier_meta.json","manifest.json")
ACTION=re.compile(r"\b(?:write|writes|wrote|written|create|creates|created|creating|update|updates|updated|updating|modify|modifies|modified|modifying|edit|edits|edited|save|saves|saved|upload|uploads|uploaded|submit|submits|submitted|send|sends|sent|post|posts|posted|insert|inserts|inserted|delete|deletes|deleted|remove|removes|removed|add|adds|added|set|sets|configure|configures|configured|schedule|schedules|scheduled|book|books|booked|transfer|transfers|transferred|export|exports|exported|generate|generates|generated|produce|produces|produced|draft|drafts|prepare|prepares|prepared|attach|attaches|attached|commit|commits|committed)\b",re.I)
ARTIFACT=re.compile(r"\b(?:file|report|memo|answer|document|spreadsheet|workbook|csv|xlsx|pdf|deck|slides?|presentation|output|artifact|deliverable|draft|proposal|email|ticket|form|plan|schedule|invoice|letter|brief|summary|response|markdown|\.md)\b",re.I)
SYSTEM=re.compile(r"\b(?:mcp|system|database|record|account|workspace|sharepoint|salesforce|crm|erp|dealcloud|servicenow|jira|ticket|calendar|mailbox|drive|folder|repository|repo|portal|table|row|entry|transaction|customer|supplier|vendor|employee|patient|case|booking|order)\b",re.I)
NEGATION=re.compile(r"\b(?:do\s+not|don't|does\s+not|doesn't|must\s+not|should\s+not|never|without)\b",re.I)
PAST_HISTORY=re.compile(r"\b(?:previously|historically|earlier|already|formerly|was|were|had)\s+(?:\w+\s+){0,2}(?:written|created|updated|modified|edited|saved|uploaded|submitted|sent|posted|inserted|deleted|removed|added|configured|scheduled|booked|transferred|exported|generated|produced|drafted|prepared|attached|committed)\b",re.I)


def sha(b): return hashlib.sha256(b).hexdigest()
def write_same(p,b):
    if p.exists():
        if p.read_bytes()!=b: raise RuntimeError(f"Refusing to overwrite different artifact {p}")
    else: p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(b)
def prompt_of(row):
    v=row.get("prompt")
    if isinstance(v,list): return "\n".join(str(x.get("content","")) for x in v if isinstance(x,dict) and x.get("role")=="user")
    return v if isinstance(v,str) else ""
def clauses(text):
    return [x.strip() for x in re.split(r"(?<=[.!?])\s+|\n+",text) if x.strip()]
def action_matches(text):
    results=[]
    for clause in clauses(text):
        verbs=[m.group(0).lower() for m in ACTION.finditer(clause)]
        if not verbs: continue
        targets=[]
        if ARTIFACT.search(clause): targets.append("artifact_or_deliverable")
        if SYSTEM.search(clause): targets.append("system_or_record")
        if re.search(r"\b(?:save|write|export|upload|submit|attach)\b.{0,100}(?:to|as|at)\s+[`'\"]?[/\w.-]+",clause,re.I): targets.append("explicit_destination")
        if not targets: continue
        neg=bool(NEGATION.search(clause))
        historic=bool(PAST_HISTORY.search(clause))
        # A keyword hit is only a candidate action. Preserve excluded hits for
        # counterexample review; do not elevate negated/past-tense descriptions.
        status="negative" if neg else "historical_description" if historic else "possible_explicit_action"
        strength=(3 if "explicit_destination" in targets else 0)+(2 if "artifact_or_deliverable" in targets else 0)+(1 if "system_or_record" in targets else 0)+min(len(verbs),3)
        results.append({"clause":clause,"action_verbs":sorted(set(verbs)),"target_types":targets,"status":status,"heuristic_score":strength})
    return results

def fetch(iid,name):
    # Reuse the previous 12-task source snapshot when present; otherwise fetch
    # only this named metadata file at the pinned revision.
    candidates=[OUT/"snapshots"/iid/name,BASE/"research/mimo/general_sample/snapshots"/iid/name]
    for p in candidates:
        if p.exists(): return p.read_bytes(),p
    p=OUT/"snapshots"/iid/name
    url=f"https://huggingface.co/datasets/{REPO}/resolve/{REV}/general/envs/{iid}/{name}"
    r=requests.get(url,timeout=45); r.raise_for_status(); data=r.content
    write_same(p,data)
    return data,p

def main():
    records=[]
    for ix,row in enumerate(pq.read_table(PARQUET).to_pylist()):
        info=row.get("extra_info") or {}
        try: inst=json.loads(info.get("instance_json","{}"))
        except Exception: inst={}
        if inst.get("dataset_type")!="general_agent": continue
        iid=str(inst.get("instance_id","")); prompt=prompt_of(row)
        matches=action_matches(prompt)
        records.append({"row_index":ix,"task_id":iid,"prompt":prompt,"prompt_chars":len(prompt),"matches":matches})
    eligible=[r for r in records if r["task_id"] not in EXCLUDED]
    positive=[r for r in eligible if any(m["status"]=="possible_explicit_action" for m in r["matches"])]
    positive.sort(key=lambda r:(-sum(m["heuristic_score"] for m in r["matches"] if m["status"]=="possible_explicit_action"),-len([m for m in r["matches"] if m["status"]=="possible_explicit_action"]),r["task_id"]))
    # Prefer distinct task IDs and domains among the strongest matches; domain is
    # taken from anchored IDs only and never guessed from prose.
    selected=[]; seen_domains=set()
    def domain(iid):
        m=re.match(r"^s3k_\d+_(.+)_(?:en|zh)_t[1-5]_rl_\d+$",iid)
        return m.group(1) if m else None
    for r in positive:
        d=domain(r["task_id"])
        if d not in seen_domains:
            selected.append(r); seen_domains.add(d)
            if len(selected)==8: break
    controls=sorted((r for r in eligible if r not in selected),key=lambda r:(-r["prompt_chars"],-len(r["prompt"].split()),r["task_id"]))[:2]
    selected_ids={r["task_id"] for r in selected}
    for r in controls:
        if r["task_id"] not in selected_ids: selected.append(r); selected_ids.add(r["task_id"])
    total=0; details=[]
    for rank,r in enumerate(selected,1):
        iid=r["task_id"]; blobs={}; paths={}
        for name in FILES:
            data,path=fetch(iid,name); total+=len(data); blobs[name]=data; paths[name]=path
        if total>MAX_BYTES: raise RuntimeError(f"Selected source files exceed {MAX_BYTES} bytes")
        meta=json.loads(blobs["verifier_meta.json"]); manifest=json.loads(blobs["manifest.json"])
        items=meta.get("items",[]) if isinstance(meta.get("items"),list) else []
        methods=Counter(str(i.get("method","unspecified")) for i in items if isinstance(i,dict))
        clauses_pos=[m for m in r["matches"] if m["status"]=="possible_explicit_action"]
        criterion_files=sorted({str(f) for i in items if isinstance(i,dict) for f in (i.get("files") or [])})
        action_terms=sorted({v for m in clauses_pos for v in m["action_verbs"]})
        target_terms=sorted({v for m in clauses_pos for v in m["target_types"]})
        comparison={"prompt_action_clause_count":len(clauses_pos),"prompt_negative_or_historical_match_count":sum(m["status"]!="possible_explicit_action" for m in r["matches"]),"verifier_item_count":len(items),"verifier_method_counts":dict(sorted(methods.items())),"verifier_item_files":criterion_files,"verifier_act":meta.get("act"),"verifier_output":meta.get("output"),"manifest_act":manifest.get("act"),"manifest_output":manifest.get("output"),"prompt_artifact_terms_with_no_criterion_file_overlap":bool(clauses_pos and not criterion_files),"metadata_action_counterexample":bool(clauses_pos and all(str(meta.get(k,"none")).lower() in {"none","null",""} for k in ("act","output")) and all(str(manifest.get(k,"none")).lower() in {"none","null",""} for k in ("act","output"))),"interpretation":"Metadata disagreement is a heuristic counterexample for manual review, not evidence of a grader defect; grader criteria may assess the final response rather than post-state."}
        details.append({"rank":rank,"selection_role":"strongest_action_match" if r in positive and len(clauses_pos)>0 and r not in controls else "long_prompt_control","task_id":iid,"row_index":r["row_index"],"prompt_chars":r["prompt_chars"],"action_matches":r["matches"],"matched_action_verbs":action_terms,"matched_target_types":target_terms,"selection_score":sum(m["heuristic_score"] for m in clauses_pos),"full_prompt":r["prompt"],"grader_comparison":comparison,"source_files":{n:{"path":str(paths[n]),"bytes":len(blobs[n]),"sha256":sha(blobs[n])} for n in FILES},"manifest":manifest,"verifier_items":[{k:i.get(k) for k in ("id","method","tier","weight","files","question") if k in i} for i in items if isinstance(i,dict)]})
    if len(details)>10: raise RuntimeError("Selection exceeded 8 action candidates plus 2 controls")
    positive_ids={r["task_id"] for r in positive}
    summary={"schema_version":"mimo-general-action-screen/1","revision":REV,"source_parquet_sha256":sha(PARQUET.read_bytes()),"source_scope":"Scanned all 925 general_agent prompts in the cached General parquet; candidate universe is 922 after excluding the three previously reviewed IDs.","classification":"Conservative keyword heuristic for explicit artifact/system action requests. Every match includes the exact clause; negative and historical descriptions are separately labeled. Not authoritative.","classifier_patterns":{"action_verb_regex":ACTION.pattern,"target_classes":["artifact_or_deliverable","system_or_record","explicit_destination"],"negation_context":NEGATION.pattern,"historical_context":PAST_HISTORY.pattern},"counts":{"general_agent_rows":len(records),"eligible_unreviewed_rows":len(eligible),"rows_with_any_action_or_target_phrase":sum(bool(r["matches"]) for r in eligible),"rows_with_positive_possible_action":len(positive_ids),"negative_or_historical_matches":sum(m["status"]!="possible_explicit_action" for r in eligible for m in r["matches"])},"selection":{"up_to_8_strongest_action_candidates":"Highest summed heuristic score, then match count, unique parsed domain preferred, then stable task ID.","controls":"Two longest remaining prompts by character count, word-count tie break, stable task ID.","not_representative":True},"selected_tasks":details,
        "counterexamples_to_heuristic":[
            {"task_id":"s3k_0399_consulting_bizops_analytics_en_t2_rl_004","matched_clause":"Include the key source facts and all conclusions in the final response; no file edit or database mutation is requested.","counterexample":"The screen also matched 'export' and 'posted' elsewhere in the prompt; this explicit clause says the requested response requires no file or database mutation. Its verifier criteria use LLM items on answer.md."},
            {"task_id":"s3k_0111_accounting_audit_tax_en_t3_rl_007","matched_clause":"Recompute the posted 2023 invoice-basis activity ...; identify the reimbursement invoice ... trace it to the posted cash receipt.","counterexample":"'posted' describes historical accounting records, not a request to post or mutate them. Verifier act/output are none and the seven criteria use LLM on answer.md."},
            {"task_id":"s3k_1914_last_mile_logistics_en_t2_rl_009","matched_clause":"For each calendar date, aggregate the removed deliverable stops represented by the active cases.","counterexample":"'removed' describes quantities to aggregate, not a request to remove stops from a system. Verifier act/output are none and the seven criteria use LLM on answer.md."},
            {"task_id":"s3k_1611_hr_people_en_t2_rl_009","matched_clause":"This is a read-only review; do not modify the workspace or any source system.","counterexample":"The broad target/action co-occurrence also flags 'prepare a governance-ready exception review'; the explicit negative clause rules out source-system modification."}
        ],
        "downloaded_total_bytes":total,"download_file_limit_bytes":MAX_BYTES,"download_scope":"Only instruction.md, verifier_meta.json, and manifest.json for selected tasks; prior metadata snapshots reused when present. No documents, images, runtime code, verifier source, Docker, or model calls."}
    OUT.mkdir(parents=True,exist_ok=True)
    write_same(OUT/"screening.json",(json.dumps(summary,ensure_ascii=False,indent=2)+"\n").encode())
    print(json.dumps({"counts":summary["counts"],"selected":[{"role":d["selection_role"],"task_id":d["task_id"],"score":d["selection_score"],"prompt_chars":d["prompt_chars"],"metadata_counterexample":d["grader_comparison"]["metadata_action_counterexample"],"methods":d["grader_comparison"]["verifier_method_counts"]} for d in details],"downloaded_bytes":total,"output":str(OUT/"screening.json")},indent=2))
if __name__=="__main__": main()
