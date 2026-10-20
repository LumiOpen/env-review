#!/usr/bin/env python3
"""Inventory pinned MiMo Cyber, Webdev, and Music parquet data as inert data."""
from __future__ import annotations
import hashlib, json, os, re
from collections import Counter
from pathlib import Path
from urllib.request import urlopen

REV = "e8e81e4945270b6212204bad99de1e598f7fb077"
BASE = Path(__file__).resolve().parent
RAW = BASE / "raw"
HF = "https://huggingface.co/datasets/XiaomiMiMo/MiMo-V2.6-RL-oss/resolve/" + REV + "/"
FILES = {
  "cyber.parquet": ("9e6e69034f4f3e6cfb5c901de642dddc7f4bacf35ab886b0e8eb53eb03084ba1", 1000),
  "webdev.parquet": ("56ca6c96642666a27b756e20694ba60a4386d1761baadae86fd6768553d2cbac", 2093),
  "music.parquet": ("8fa2c95fb008df032eae184f3304dd3a73e3d25727e3aac0a715484859fa4856", 1000),
}

def sha(path):
  h=hashlib.sha256()
  with path.open('rb') as f:
    for b in iter(lambda:f.read(1<<20), b''): h.update(b)
  return h.hexdigest()

def dec(v):
  if isinstance(v, bytes): return v.decode('utf-8', 'replace')
  return v

def slim(v, depth=0):
  v=dec(v)
  if depth > 4: return f"<{type(v).__name__}>"
  if isinstance(v, dict): return {str(k):slim(x,depth+1) for k,x in list(v.items())[:40]}
  if isinstance(v, list): return [slim(x,depth+1) for x in v[:12]]
  if isinstance(v, str): return v[:700]
  if v is None or isinstance(v,(int,float,bool)): return v
  return str(v)[:300]

def parse_jsonish(v):
  v=dec(v)
  if isinstance(v, str):
    try: return json.loads(v)
    except Exception: return v
  return v

def collect_strings(obj, path=""):
  if isinstance(obj, dict):
    for k,v in obj.items(): yield from collect_strings(v, f"{path}.{k}" if path else str(k))
  elif isinstance(obj,list):
    for i,v in enumerate(obj): yield from collect_strings(v, f"{path}[{i}]")
  elif isinstance(obj,str): yield path,obj

def row_record(row):
  row={str(k):dec(v) for k,v in row.items()}
  extra=parse_jsonish(row.get('extra_info'))
  inst=None
  if isinstance(extra,dict): inst=parse_jsonish(extra.get('instance_json'))
  if inst is None: inst=parse_jsonish(row.get('instance_json'))
  return row,extra,inst

def main():
  if not os.environ.get('SLURM_JOB_ID') or os.environ.get('SLURM_JOB_PARTITION') != 'amd-tw-verification':
    raise SystemExit('Run the inventory in a Slurm job on amd-tw-verification')
  import pyarrow
  import pyarrow.parquet as pq
  if pyarrow.__version__ != '24.0.0':
    raise SystemExit('Inventory requires pyarrow==24.0.0')
  RAW.mkdir(parents=True,exist_ok=True)
  out={"dataset":"XiaomiMiMo/MiMo-V2.6-RL-oss","revision":REV,"domains":{}}
  id_rules={}
  reps={"dataset_revision":REV,"domains":{}}
  for name,(expected,nrows) in FILES.items():
    path=RAW/name
    if not path.exists():
      with urlopen(HF+name, timeout=90) as r: data=r.read(8 * 1024 * 1024 + 1)
      if len(data) > 8 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != expected:
        raise RuntimeError(f'download size/hash mismatch: {name}')
      temporary=path.with_suffix('.parquet.partial')
      temporary.write_bytes(data)
      temporary.replace(path)
    actual=sha(path)
    if actual != expected: raise RuntimeError(f"hash mismatch {name}: {actual} expected {expected}")
    pf=pq.ParquetFile(path)
    table=pf.read()
    dname=name.removesuffix('.parquet')
    if table.num_rows != nrows: raise RuntimeError(f"row count mismatch {name}: {table.num_rows} expected {nrows}")
    rows=table.to_pylist()
    field_counts=Counter()
    null_counts=Counter()
    top_values={}
    ids=[]; dup_prompt=Counter(); value_counters={}; nested_nulls=Counter(); id_agreement=Counter()
    compact=[]
    for i,raw in enumerate(rows):
      row,extra,inst=row_record(raw)
      for scope,obj in (("extra_info",extra),("instance_json",inst)):
        if isinstance(obj,dict):
          for k,v in obj.items():
            if v is None: nested_nulls[f"{scope}.{k}"]+=1
      if isinstance(extra,dict) and isinstance(inst,dict):
        pairs=[("instance_id",extra.get("instance_id"),inst.get("instance_id"))]
        if inst.get("task_id") is not None: pairs.append(("instance_id_vs_task_id",extra.get("instance_id"),inst.get("task_id")))
        for k,a,b in pairs:
          if a is not None or b is not None: id_agreement[f"{k}:both_equal" if a==b else f"{k}:different_or_missing"]+=1
      for k,v in row.items():
        field_counts[k]+=1
        if v is None: null_counts[k]+=1
      candidates=[]
      for source,label in ((row,'row'),(extra,'extra_info'),(inst,'instance_json')):
        if isinstance(source,dict):
          for key in ('task_id','id','instance_id','uid','problem_id','question_id','src_id'):
            if source.get(key) is not None: candidates.append((label+'.'+key,str(source[key])))
      ids.append(candidates[0][1] if candidates else None)
      # distributions from scalar metadata only
      for source,label in ((row,'row'),(extra,'extra_info'),(inst,'instance_json')):
        if isinstance(source,dict):
          for k,v in source.items():
            if isinstance(v,(str,int,float,bool)) or v is None:
              key=f"{label}.{k}"
              value_counters.setdefault(key,Counter())[str(v)[:120]]+=1
      prompt=row.get("prompt")
      if isinstance(prompt,list):
        ptxt="\n".join(f"{m.get('role','')}: {m.get('content','')}" for m in prompt if isinstance(m,dict))
      else: ptxt=str(prompt or "")
      if ptxt: dup_prompt[hashlib.sha256(ptxt.encode()).hexdigest()]+=1
      if i < 3:
        compact.append({"row_index":i,"row_fields":slim(row),"extra_info":slim(extra),"parsed_instance_json":slim(inst),"id_candidates":candidates})
    duplicate_ids=Counter(x for x in ids if x is not None)
    if dname=="cyber": id_rules[dname]={"field":"extra_info.instance_id","fallback":None}
    elif dname=="webdev": id_rules[dname]={"field":"extra_info.instance_id","equivalent_field":"extra_info.instance_json.task_id","fallback":None}
    else: id_rules[dname]={"field":"extra_info.src_id","fallback":None}
    d={"file":name,"url":HF+name,"sha256":actual,"expected_lfs_sha256":expected,"bytes":path.stat().st_size,
       "row_count":table.num_rows,"row_group_count":pf.num_row_groups,
       "schema":str(pf.schema_arrow),"schema_fields":[{"name":f.name,"type":str(f.type),"nullable":f.nullable} for f in pf.schema_arrow],
       "null_counts":dict(null_counts),"nested_null_counts":dict(nested_nulls),"id_field_agreement":dict(id_agreement),"task_id_rule":id_rules[dname],"id_candidate_presence":{"rows_with_candidate":sum(x is not None for x in ids),"rows_without_candidate":sum(x is None for x in ids),"unique_nonnull":len(set(x for x in ids if x is not None)),"duplicate_values":{k:v for k,v in duplicate_ids.items() if v>1}},
       "likely_prompt_hashes":{"unique":len(dup_prompt),"duplicate_prompt_groups":sum(1 for n in dup_prompt.values() if n>1),"max_multiplicity":max(dup_prompt.values(),default=0)},
       "scalar_distributions":{k:{"distinct":len(c),"top":c.most_common(30)} for k,c in value_counters.items()},
       "first_rows":compact}
    out['domains'][dname]=d
    reps['domains'][dname]=compact
  (BASE/'task_id_rules.json').write_text(json.dumps({"dataset_revision":REV,"domains":id_rules},ensure_ascii=False,indent=2)+'\n')
  (BASE/'inventory.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,default=str)+'\n')
  (BASE/'representative_rows.json').write_text(json.dumps(reps,ensure_ascii=False,indent=2,default=str)+'\n')
  print(json.dumps({k:{"rows":v['row_count'],"sha256":v['sha256'],"fields":[f['name'] for f in v['schema_fields']],"id_candidates":v['id_candidate_presence']} for k,v in out['domains'].items()},indent=2))
if __name__=='__main__': main()
