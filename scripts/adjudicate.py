#!/usr/bin/env python3
"""Ask a stronger model to settle the items the two agents disagreed on.

    python3 scripts/adjudicate.py plan            # counts + one sample prompt, no model calls
    python3 scripts/adjudicate.py run             # adjudicate everything still pending
    python3 scripts/adjudicate.py run --limit 2   # pilot: first 2 cases only

Input: the review items computed by merge.py (events found by one agent only,
and events whose fields differ), grouped by decree. Each case sent to the
model has the full text of the decree(s), the events both agents already agree
on (context) and the items to settle; prompt in prompts/adjudicate.md.

Output: review/resolved/<case>.json = {"case", "resoluciones": [{id, veredicto,
evento, motivo}]}. merge.py applies them. Items that already have a resolution
are not asked again, so the script can be re-run after a usage cap or a reboot.

Env knobs: MODEL (fable), WORKERS (3), MAX_TRIES (40), MAX_CHARS (40000 of
decree text per case).
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import merge  # noqa: E402

ROOT = merge.ROOT
OUT = os.path.join(ROOT, "review", "resolved")
RAW = os.path.join(ROOT, "review", "raw")
MODEL = os.environ.get("MODEL", "fable")
WORKERS = int(os.environ.get("WORKERS", "3"))
MAX_TRIES = int(os.environ.get("MAX_TRIES", "40"))
MAX_CHARS = int(os.environ.get("MAX_CHARS", "40000"))
HDR = re.compile(r"^=== DECRETO (.*?) \| fecha (.*?) \| paginas PDF (.*?) \| id (\S+) ===[ \t]*$", re.M)
VERDICTS = ("confirmar", "descartar", "dudoso")

_lock = threading.Lock()
_logf = None


def log(msg):
    line = f"{time.strftime('%F %T')} {msg}"
    with _lock:
        print(line, flush=True)
        if _logf:
            _logf.write(line + "\n")
            _logf.flush()


def sections(batch):
    """Split batches/<batch>.txt into decrees."""
    text = open(os.path.join(ROOT, "batches", batch + ".txt"), encoding="utf-8").read()
    ms = list(HDR.finditer(text))
    out = []
    for i, m in enumerate(ms):
        body = text[m.start(): ms[i + 1].start() if i + 1 < len(ms) else len(text)].rstrip() + "\n"
        out.append({"sid": f"{batch}:{i}", "numero": merge.norm_decreto(m.group(1)), "text": body,
                    "flat": body.replace("-\n", "").replace("\n", " "),
                    "digits": re.sub(r"\D", "", body)})
    return out


def find_sections(secs, ev):
    """The decree(s) of this batch an event belongs to."""
    def mentions(s):
        if ev["_doc"] and len(ev["_doc"]) >= 5 and ev["_doc"] in s["digits"]:
            return True
        caps = [t for t in re.findall(r"[A-ZÁÉÍÓÚÑÜ]{3,}", ev["persona"])]
        return bool(caps) and all(t in s["flat"] for t in caps)

    same = [s for s in secs if s["numero"] == ev["decreto"]]
    if len(same) == 1:
        return same
    if same:
        return [s for s in same if mentions(s)] or same
    return [s for s in secs if mentions(s)][:3]


def public(ev):
    return {k: ev[k] for k in merge.FIELDS}


def build_cases():
    """Group the pending review items into cases. Returns (cases, n_items, n_skipped)."""
    _, _, _, _, confirmed, only_a, only_b, conflicts, _ = merge.compute()
    res = merge.load_resolutions()
    conf_ids = {id(e) for e in conflicts}
    agreed = defaultdict(list)  # (batch, decreto) -> events both agents fully agree on
    for e in confirmed:
        if id(e) not in conf_ids:
            agreed[(e["batch"], e["decreto"])].append(e)

    items = []
    for ev in only_a:
        items.append((ev, {"id": ev["_id"], "clase": "solo_a", "a": public(ev)}))
    for ev in only_b:
        items.append((ev, {"id": ev["_id"], "clase": "solo_b", "b": public(ev)}))
    for ev in conflicts:
        items.append((ev, {"id": ev["_id"], "clase": "conflicto", "a": public(ev["_a"]), "b": public(ev["_b"])}))
    total = len(items)
    items = [(ev, it) for ev, it in items if it["id"] not in res]

    by_batch = defaultdict(lambda: defaultdict(list))  # batch -> tuple(sids) -> items
    sec_cache, skipped = {}, 0
    for ev, it in items:
        b = ev["batch"]
        if b not in sec_cache:
            sec_cache[b] = sections(b)
        found = find_sections(sec_cache[b], ev.get("_a", ev))
        if not found:
            skipped += 1
            continue
        by_batch[b][tuple(s["sid"] for s in found)].append(it)

    cases = []
    for b in sorted(by_batch):
        secs = {s["sid"]: s for s in sec_cache[b]}
        cur, size = [], 0

        def flush():
            nonlocal cur, size
            if not cur:
                return
            ids = [it["id"] for _, its in cur for it in its]
            name = f"{b}_{hashlib.sha1('|'.join(ids).encode()).hexdigest()[:8]}"
            parts = []
            for sids, its in cur:
                for sid in sids:
                    s = secs[sid]
                    parts.append(s["text"])
                    ag = agreed.get((b, s["numero"]), [])
                    if ag:
                        parts.append("--- Eventos de este decreto ya confirmados por A y B (contexto, no devolver) ---")
                        parts += [f"{e['tipo']} | {e['persona']} | {e['documento'] or e['filiacion']}" for e in ag]
                parts.append("--- Ítems a resolver de este decreto ---")
                parts.append(json.dumps(its, ensure_ascii=False, indent=1))
                parts.append("")
            cases.append({"name": name, "ids": ids, "body": "\n".join(parts)})
            cur, size = [], 0

        for sids in sorted(by_batch[b]):
            n = sum(len(secs[s]["text"]) for s in sids)
            if cur and size + n > MAX_CHARS:
                flush()
            cur.append((sids, by_batch[b][sids]))
            size += n
        flush()
    return cases, total, len(items), skipped


def parse_reply(raw, ids):
    """Model reply -> list of valid resolutions for the ids of this case."""
    try:
        outer = json.loads(raw)
        if isinstance(outer, dict) and "result" in outer:
            if outer.get("is_error"):
                return None
            raw = outer["result"] if isinstance(outer["result"], str) else json.dumps(outer["result"])
    except Exception:  # noqa: BLE001
        pass
    raw = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", raw.strip())
    i, j = raw.find("{"), raw.rfind("}")
    if i < 0 or j < 0:
        return None
    try:
        d = json.loads(raw[i: j + 1])
    except Exception:  # noqa: BLE001
        return None
    out, seen = [], set()
    for r in d.get("resoluciones", []) if isinstance(d, dict) else []:
        if not isinstance(r, dict) or r.get("id") not in ids or r["id"] in seen:
            continue
        if r.get("veredicto") not in VERDICTS:
            continue
        if r["veredicto"] == "confirmar":
            e = r.get("evento")
            if not isinstance(e, dict) or not str(e.get("persona", "")).strip() or e.get("tipo") not in merge.TIPOS:
                continue
            r["evento"] = {k: str(e.get(k, "") or "").strip() for k in merge.FIELDS}
        seen.add(r["id"])
        out.append({k: r[k] for k in ("id", "veredicto", "evento", "motivo") if k in r})
    return out


def run_case(case, prompt_head):
    out = os.path.join(OUT, case["name"] + ".json")
    ids = set(case["ids"])
    best = []
    for t in range(1, MAX_TRIES + 1):
        log(f"START {case['name']} ({len(ids)} items, try {t}, model {MODEL})")
        try:
            p = subprocess.run(
                ["claude", "-p", "--model", MODEL, "--output-format", "json", "--tools", "",
                 "--no-session-persistence", "--strict-mcp-config"],
                input=prompt_head + case["body"], capture_output=True, text=True, timeout=3600)
            raw, err, rc = p.stdout, p.stderr, p.returncode
        except subprocess.TimeoutExpired:
            raw, err, rc = "", "timeout", 124
        open(os.path.join(RAW, case["name"] + ".txt"), "w", encoding="utf-8").write(raw)
        got = parse_reply(raw, ids) if rc == 0 else None
        if got is not None and len(got) > len(best):
            best = got
        if got is not None and len(got) == len(ids):
            break
        if got:  # valid but incomplete: one more try, then keep what we have
            log(f"PART  {case['name']} {len(got)}/{len(ids)} resolved")
            if t >= 2:
                break
            continue
        msg = (raw[:300] + " " + err[:200]).replace("\n", " ")
        try:
            msg = str(json.loads(raw).get("result", ""))[:300] + " " + err[:200]
        except Exception:  # noqa: BLE001
            pass
        log(f"FAIL  {case['name']} rc={rc}: {msg}")
        if re.search(r"rate.?limit|overloaded|429|usage limit|quota|capacity|hit your|limit reached|resets", msg, re.I):
            log("WAIT  10 min (rate limit)")
            time.sleep(600)
        else:
            time.sleep(min(60 * t, 600))
    if not best:
        log(f"GIVEUP {case['name']}")
        return 0
    json.dump({"case": case["name"], "model": MODEL, "resoluciones": best},
              open(out + ".tmp", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(out + ".tmp", out)
    c = defaultdict(int)
    for r in best:
        c[r["veredicto"]] += 1
    log(f"DONE  {case['name']} confirmar {c['confirmar']}, descartar {c['descartar']}, dudoso {c['dudoso']}"
        + (f", sin respuesta {len(ids) - len(best)}" if len(best) < len(ids) else ""))
    return len(best)


def main():
    global _logf
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["plan", "run"])
    ap.add_argument("--limit", type=int, default=0, help="only the first N cases")
    args = ap.parse_args()

    os.environ["PATH"] = os.path.expanduser("~/.local/bin") + os.pathsep + os.environ.get("PATH", "")
    cases, total, pending, skipped = build_cases()
    print(f"review items {total}, pending {pending}, without decree text {skipped}; "
          f"cases {len(cases)}, chars {sum(len(c['body']) for c in cases)}")
    head = open(os.path.join(ROOT, "prompts", "adjudicate.md"), encoding="utf-8").read() + "\n"
    if args.limit:
        cases = cases[: args.limit]
    if args.mode == "plan":
        if cases:
            c = min(cases, key=lambda c: len(c["body"]))
            print(f"\n===== sample case {c['name']} =====\n{c['body']}")
        return 0
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(RAW, exist_ok=True)
    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    _logf = open(os.path.join(ROOT, "logs", f"adjudicate_{time.strftime('%Y%m%d_%H%M%S')}.log"), "a", encoding="utf-8")
    log(f"cases: {len(cases)} ({WORKERS} workers, model {MODEL})")
    with ThreadPoolExecutor(WORKERS) as ex:
        done = sum(ex.map(lambda c: run_case(c, head), cases))
    asked = sum(len(c["ids"]) for c in cases)
    log(f"finished: {done} of {asked} items resolved")
    return 0 if done == asked else 1


if __name__ == "__main__":
    sys.exit(main())
