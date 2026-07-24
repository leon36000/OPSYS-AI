#!/usr/bin/env python3
"""Phase C — distribution du pack aux modeles via la passerelle + collecte des verdicts scelles (C-02, brique no 13).
MODE LIVE: requiert la passerelle (P0-2). BLOCKED tant que la clef n'est pas tournee (R-002).
MODE --mock: auto-test du circuit collecte->tally avec verdicts factices (preuve du mecanisme)."""
import json, sys, os, subprocess
HERE = os.path.dirname(__file__)
def mock():
    d = os.path.join(HERE, "..", "registries", "verdicts", "mock-phaseC")
    os.makedirs(d, exist_ok=True)
    for r, vend, verdict, obj in [("glm-5.2","zhipu","APPROVE",[]),
                                  ("gemini-3.1-pro","google","APPROVE",[]),
                                  ("longcat-2.0","meituan","APPROVE",[{"severite":"mineure","fichier":"pack","description":"exemple","preuve":"n/a"}])]:
        json.dump({"reviewer":r,"vendor":vend,"verdict":verdict,"objections":obj},
                  open(os.path.join(d, r + ".json"), "w", encoding="utf-8"), ensure_ascii=False)
    rc = subprocess.call([sys.executable, os.path.join(HERE,"tally.py"), d, "deepseek"])
    print("PREUVE: circuit collecte->tally =", "OK" if rc == 0 else f"echec rc={rc}")
    sys.exit(rc)
if __name__ == "__main__":
    if "--mock" in sys.argv: mock()
    print("BLOCKED: mode live requiert la passerelle configuree (P0-2) et la clef tournee (P0-4/R-002)."); sys.exit(4)
