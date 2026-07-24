#!/usr/bin/env python3
"""Ajout append-only HASH-CHAINE aux registres jsonl (D-042). JAMAIS d'ecriture manuelle."""
import json, hashlib, sys, time, os
LEDGER_DIR = os.path.join(os.path.dirname(__file__), "..", "registries", "ledger")
FILES = {"decision": "decisions.jsonl", "preuve": "preuves.jsonl",
         "execution": "executions.jsonl", "installation": "installations.jsonl"}

def _canon(o): return json.dumps(o, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

def last_hash(path):
    if not os.path.exists(path): return "GENESIS"
    h = "GENESIS"
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line: h = json.loads(line)["hash"]
    return h

def append(kind, payload):
    if kind not in FILES: raise SystemExit(f"type inconnu: {kind}")
    if kind == "preuve" and not (payload.get("preuve") or payload.get("blocked")):
        raise SystemExit("REJETE: entree DONE sans preuve (REG-01/D-042)")
    path = os.path.join(LEDGER_DIR, FILES[kind])
    prev = last_hash(path)
    entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
             "type": kind, "payload": payload, "prev_hash": prev}
    entry["hash"] = hashlib.sha256((prev + _canon({k: entry[k] for k in ("ts","type","payload")})).encode()).hexdigest()
    with open(path, "a", encoding="utf-8") as f:
        f.write(_canon(entry) + "\n")
    return entry["hash"]

def verify(kind):
    path = os.path.join(LEDGER_DIR, FILES[kind])
    if not os.path.exists(path): return True, 0
    prev, n = "GENESIS", 0
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line: continue
            e = json.loads(line)
            expect = hashlib.sha256((prev + _canon({k: e[k] for k in ("ts","type","payload")})).encode()).hexdigest()
            if e.get("prev_hash") != prev or e.get("hash") != expect:
                return False, i
            prev, n = e["hash"], i
    return True, n

if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "verify":
        ok_all = True
        for k in FILES:
            ok, n = verify(k)
            print(f"{FILES[k]}: {'OK' if ok else 'CHAINE BRISEE'} ({n} entrees)")
            ok_all &= ok
        sys.exit(0 if ok_all else 2)
    if len(sys.argv) < 3:
        print("usage: ledger_append.py <decision|preuve|execution|installation> '<json payload>' | verify"); sys.exit(1)
    print("hash:", append(sys.argv[1], json.loads(sys.argv[2])))
