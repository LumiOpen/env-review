"""Download pinned corpus files as inert data; never load dataset Python code."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path, PurePosixPath
import time
from urllib.parse import quote
from urllib.request import urlopen

DEFAULT_RUN = "env/XiaomiMiMo/MiMo-V2.6-RL-oss/runs/2026-10-20-initial"


def load_inventory(root: Path, dataset: str, revision: str) -> dict:
    path = root / "dataset-api.raw"
    if path.exists():
        inventory = json.loads(path.read_text())
    else:
        url = f"https://huggingface.co/api/datasets/{dataset}/revision/{revision}"
        with urlopen(url, timeout=25) as response:
            inventory = json.load(response)
    if inventory.get("sha") != revision:
        raise ValueError("Inventory revision differs from dataset lock; use a separate cache")
    if not path.exists():
        root.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(inventory))
    return inventory


def selected_paths(inventory: list[str], task_ids: list[str]) -> list[str]:
    prefixes = tuple(f"general/envs/{task}/" for task in task_ids)
    return sorted(p for p in inventory if p.startswith(prefixes)
                  and PurePosixPath(p).suffix in {".py", ".md", ".json", ".sql", ".db"}
                  and "/workspace/" not in p)


def destination(root: Path, relative: str) -> Path:
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or "\\" in relative or not path.parts:
        raise ValueError(f"Unsafe corpus path: {relative!r}")
    resolved = (root / str(path)).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"Corpus path escapes cache: {relative!r}")
    return resolved


def acquire_one(root: Path, relative: str, dataset: str, revision: str) -> dict:
    target = destination(root, relative)
    cached = target.is_file()
    if not cached:
        url = f"https://huggingface.co/datasets/{dataset}/resolve/{revision}/{quote(relative)}"
        for attempt in range(3):
            try:
                with urlopen(url, timeout=25) as response:
                    body = response.read(20_000_001)
                if len(body) > 20_000_000:
                    raise ValueError("File exceeds the 20 MB exploration download limit")
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_suffix(target.suffix + ".part")
                temporary.write_bytes(body)
                temporary.replace(target)
                break
            except Exception as error:
                if attempt == 2:
                    return {"path": relative, "error": str(error)}
                time.sleep(2 ** attempt)
    body = target.read_bytes()
    return {"path": relative, "sha256": hashlib.sha256(body).hexdigest(),
            "bytes": len(body), "cached": cached}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", default=f"{DEFAULT_RUN}/sample-001.json")
    parser.add_argument("--cache", default="data/mimo")
    parser.add_argument("--lock", default=f"{DEFAULT_RUN}/dataset-lock.json")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--output", default="reports/acquisition.json")
    args = parser.parse_args()
    if not 1 <= args.workers <= 16:
        parser.error("workers must be between 1 and 16")
    root = Path(args.cache)
    lock = json.loads(Path(args.lock).read_text())
    sample = json.loads(Path(args.sample).read_text())
    inventory = load_inventory(root, lock["dataset"], lock["revision"])
    paths = selected_paths([p["rfilename"] for p in inventory["siblings"]], sample["task_ids"])
    start = time.monotonic()
    records = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs = [pool.submit(acquire_one, root, p, lock["dataset"], lock["revision"]) for p in paths]
        for future in as_completed(jobs):
            records.append(future.result())
            if len(records) % 50 == 0:
                print(f"Fetched {len(records)}/{len(paths)} files; errors={sum('error' in r for r in records)}", flush=True)
    output = {"dataset": lock["dataset"], "revision": lock["revision"],
              "sample": args.sample, "workers": args.workers, "timeout_seconds": 25,
              "max_attempts": 3, "elapsed_seconds": round(time.monotonic() - start, 3),
              "files": sorted(records, key=lambda r: r["path"])}
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(output, indent=2) + "\n")
    errors = sum("error" in r for r in records)
    print(f"Completed {len(records)} files; {errors} errors; {output['elapsed_seconds']} seconds")
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
