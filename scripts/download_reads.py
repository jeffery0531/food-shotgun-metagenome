#!/usr/bin/env python3
"""Download FASTQ files for runs in catalog/food_shotgun_runs.tsv, with resume and MD5 checks.

Check the plan first, then run the same command without --dry-run:

  python3 -I scripts/download_reads.py --out /Volumes/FoodReads --dry-run
  python3 -I scripts/download_reads.py --out /Volumes/FoodReads --category dairy --jobs 4

Selection (filters combine):
  --tier core[,review,keyword]   default core
  --archive INSDC,GSA            default both
  --category dairy,meat,...      food categories as in catalog/summary.md; default all
  --runs FILE                    only these run accessions, one per line; replaces
                                 --tier/--archive/--category
  --skip-flags LIST              drop runs carrying any of these flags. Default:
                                 low_depth,tiny_run,no_fastq,cfmd_filtered,enrichment,
                                 not_food (the catalog's "recommended" set); with --runs
                                 only no_fastq. '' keeps all
  --limit N                      first N selected runs, e.g. for a test

Files land in <out>/<run_accession>/. Each download goes to <file>.part, resumes after an
interruption, and is renamed only once its MD5 (or its size, when no MD5 is published) matches,
so finished files are skipped and the same command can simply be re-run after a failure.
Every attempt is appended to <out>/download_log.tsv.

--export FILE writes url / md5 / bytes / destination for the selection instead of downloading,
for use with another downloader or on a server.
"""
import argparse
import collections
import csv
import hashlib
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

UA = "netbio-food-catalog/0.1"  # same as build_catalog.py (GSA rejects some client names)
DEFAULT_CATALOG = Path(__file__).resolve().parent.parent / "catalog" / "food_shotgun_runs.tsv"
# same default set as build_catalog.py
DEFAULT_SKIP = "low_depth,tiny_run,no_fastq,cfmd_filtered,enrichment,not_food"
STOP = threading.Event()


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    p.add_argument("--out", type=Path, required=True, help="destination directory")
    p.add_argument("--tier", default="core")
    p.add_argument("--archive", default="INSDC,GSA")
    p.add_argument("--category", default="")
    p.add_argument("--runs", type=Path)
    p.add_argument("--skip-flags", default=None)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--jobs", type=int, default=4, help="parallel downloads (default 4)")
    p.add_argument("--dry-run", action="store_true", help="show the plan and exit")
    p.add_argument("--export", type=Path, help="write the file list as TSV and exit")
    p.add_argument("--force", action="store_true",
                   help="start even if free space looks insufficient")
    return p.parse_args()


def split(s, sep=","):
    return [x.strip() for x in s.split(sep) if x.strip()]


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1000:
            return f"{n:,.1f} {unit}"
        n /= 1000
    return f"{n:,.2f} TB"


def select(rows, a):
    if a.runs:
        wanted = {x.strip() for x in a.runs.read_text().splitlines() if x.strip()}
        rows = [r for r in rows if r["run_accession"] in wanted]
        missing = wanted - {r["run_accession"] for r in rows}
        if missing:
            print(f"warning: {len(missing)} accessions from {a.runs} are not in the catalog",
                  file=sys.stderr)
    else:
        tiers, archives, cats = set(split(a.tier)), set(split(a.archive)), set(split(a.category))
        rows = [r for r in rows if r["tier"] in tiers and r["archive"] in archives
                and (not cats or r["food_category"] in cats)]
    if a.skip_flags is None:  # an explicit run list is taken as is, except runs with no files
        a.skip_flags = "no_fastq" if a.runs else DEFAULT_SKIP
    skip, before = set(split(a.skip_flags)), len(rows)
    rows = [r for r in rows if not skip & set(split(r["flags"], ";"))]
    if len(rows) < before:
        print(f"skipped {before - len(rows):,} runs flagged {','.join(sorted(skip))}",
              file=sys.stderr)
    return rows[:a.limit] if a.limit else rows


def jobs_for(rows, out):
    jobs = []
    for r in rows:
        urls = [u for u in r["fastq_urls"].split(";") if u]
        md5s, sizes = r["fastq_md5"].split(";"), r["fastq_file_bytes"].split(";")
        for i, url in enumerate(urls):
            size = sizes[i].strip() if i < len(sizes) else ""
            jobs.append({
                "run": r["run_accession"], "url": url,
                "md5": (md5s[i] if i < len(md5s) else "").strip().lower(),
                "bytes": int(size) if size.isdigit() else None,
                "dest": out / r["run_accession"] / url.rsplit("/", 1)[-1],
            })
    return jobs


def part_of(job):
    return job["dest"].with_name(job["dest"].name + ".part")


def md5_of(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 23), b""):
            h.update(chunk)
    return h.hexdigest()


def problem_with(path, job):
    """'' if the file matches the catalog, else what is wrong with it."""
    if job["md5"]:
        got = md5_of(path)
        return "" if got == job["md5"] else f"md5 {got} != {job['md5']}"
    size = path.stat().st_size
    if job["bytes"] is not None and size != job["bytes"]:
        return f"size {size} != {job['bytes']}"
    return ""


class Log:
    def __init__(self, path):
        self.path, self.lock = path, threading.Lock()
        if not path.exists():
            path.write_text("time\trun\tfile\tstatus\tbytes\tseconds\tdetail\n")

    def write(self, job, status, seconds, detail=""):
        f = job["dest"] if job["dest"].exists() else part_of(job)
        size = f.stat().st_size if f.exists() else 0
        line = "\t".join((time.strftime("%Y-%m-%d %H:%M:%S"), job["run"], job["dest"].name,
                          status, str(size), f"{seconds:.0f}", detail.replace("\t", " ")))
        with self.lock, open(self.path, "a") as fh:
            fh.write(line + "\n")


MAX_STALLS = 5  # give up after this many consecutive curl attempts that add no bytes
MAX_BAD_CHECKSUMS = 2


def size_of(path):
    return path.stat().st_size if path.exists() else 0


def fetch(job, log):
    """Download one file; returns (status, detail).

    curl's own --retry truncates the file back to where that curl call started, discarding
    everything received before a connection reset (GSA resets often). So curl runs without
    --retry and this loop re-invokes it; each call resumes from the current .part size."""
    dest, part = job["dest"], part_of(job)
    if dest.exists():
        return "present", ""
    dest.parent.mkdir(parents=True, exist_ok=True)
    stalls = bad = 0
    detail = ""
    while stalls < MAX_STALLS and bad < MAX_BAD_CHECKSUMS:
        if STOP.is_set():
            return "interrupted", ""
        t0, before = time.time(), size_of(part)
        if job["bytes"] is None or before != job["bytes"]:
            cmd = ["curl", "--fail", "--location", "--silent", "--show-error",
                   "--connect-timeout", "60", "--speed-limit", "10000", "--speed-time", "120",
                   "--user-agent", UA, "--continue-at", "-", "--output", str(part), job["url"]]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode < 0 or STOP.is_set():
                return "interrupted", ""
            if proc.returncode != 0:
                detail = f"curl exit {proc.returncode}: {' '.join(proc.stderr.split())[-200:]}"
                if proc.returncode in (33, 36) or " 416" in proc.stderr:  # cannot resume
                    part.unlink(missing_ok=True)
                stalls = 0 if size_of(part) > before else stalls + 1
                log.write(job, "retry", time.time() - t0, detail)
                time.sleep(min(60, 5 * stalls))
                continue
        problem = problem_with(part, job)
        if problem:
            detail, bad = problem, bad + 1
            part.unlink(missing_ok=True)
            log.write(job, "bad_checksum", time.time() - t0, problem)
            continue
        part.replace(dest)
        log.write(job, "ok", time.time() - t0)
        return "ok", ""
    return "failed", detail


def main():
    a = parse_args()
    with open(a.catalog, newline="", encoding="utf-8") as f:
        catalog = list(csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE))
    rows = select(catalog, a)
    jobs = jobs_for(rows, a.out)
    todo = [j for j in jobs if not j["dest"].exists()]
    total = sum(j["bytes"] or 0 for j in jobs)
    partial = sum(part_of(j).stat().st_size for j in todo if part_of(j).exists())
    need = sum(j["bytes"] or 0 for j in todo) - partial
    unknown = sum(1 for j in todo if j["bytes"] is None)
    probe = a.out
    while not probe.exists():
        probe = probe.parent
    free = shutil.disk_usage(probe).free

    samples = {r["sample_accession"] or r["run_accession"] for r in rows}
    print(f"selected {len(rows):,} runs ({len(samples):,} samples), {len(jobs):,} files, "
          f"{human(total)}")
    print(f"already done {len(jobs) - len(todo):,} files; to download {human(need)}"
          + (f" (+{unknown} files of unknown size)" if unknown else ""))
    print(f"free space at {probe}: {human(free)}")
    if a.dry_run or a.export:
        by_cat = collections.defaultdict(lambda: [0, 0])
        for r in rows:
            c = by_cat[r["food_category"] or "(unknown)"]
            c[0] += 1
            c[1] += int(r["fastq_bytes"] or 0)
        for cat, (n, size) in sorted(by_cat.items(), key=lambda kv: -kv[1][1]):
            print(f"  {cat:<34} {n:>6,} runs {human(size):>12}")
    if a.export:
        with open(a.export, "w", encoding="utf-8") as f:
            f.write("url\tmd5\tbytes\tdest\n")
            for j in jobs:
                f.write(f"{j['url']}\t{j['md5']}\t{j['bytes'] or ''}\t{j['dest']}\n")
        print(f"wrote {len(jobs):,} files to {a.export}")
        return
    if a.dry_run:
        for j in todo[:3]:
            print(f"  e.g. {j['url']} -> {j['dest']}")
        return
    if not todo:
        print("nothing to do")
        return
    if need > 0.95 * free and not a.force:
        sys.exit(f"not enough free space at {probe} ({human(free)} free, {human(need)} needed); "
                 f"narrow the selection, use another --out, or pass --force")

    a.out.mkdir(parents=True, exist_ok=True)
    log = Log(a.out / "download_log.tsv")
    counts = collections.Counter()
    pool = ThreadPoolExecutor(max_workers=a.jobs)
    futures = {pool.submit(fetch, j, log): j for j in todo}
    try:
        for i, fut in enumerate(as_completed(futures), 1):
            j = futures[fut]
            try:
                status, detail = fut.result()
            except Exception as e:  # noqa: BLE001  (e.g. disk full)
                status, detail = "failed", repr(e)
            counts[status] += 1
            size = j["dest"].stat().st_size if j["dest"].exists() else 0
            print(f"[{i}/{len(todo)}] {j['run']} {j['dest'].name} {status}"
                  + (f" {human(size)}" if status == "ok" else f" {detail}"), flush=True)
    except KeyboardInterrupt:
        STOP.set()
        pool.shutdown(wait=True, cancel_futures=True)
        sys.exit("interrupted; partial files are kept and resume on the next run")
    pool.shutdown()
    print("done: " + ", ".join(f"{k} {v}" for k, v in counts.most_common())
          + f". Log: {a.out / 'download_log.tsv'}")
    if counts["failed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
