#!/usr/bin/env python3
"""Depouillement PAR SCRIPT des verdicts scelles (D-041/F). Aucun LLM n'ecrit un score."""
import json, sys, glob, os
def run(dossier, vendor_codeur):
    files = sorted(glob.glob(os.path.join(dossier, "*.json")))
    if len(files) < 3: return fail(f"seulement {len(files)} verdicts deposes (3 requis)")
    verdicts, vendors = [], set()
    for fp in files:
        v = json.load(open(fp, encoding="utf-8"))
        for k in ("reviewer","vendor","verdict","objections"):
            if k not in v: return fail(f"{os.path.basename(fp)}: champ manquant '{k}' (schema scelle)")
        if v["verdict"] not in ("APPROVE","REJECT"): return fail(f"{os.path.basename(fp)}: verdict hors enum (choix force, C-12)")
        if v["vendor"] == vendor_codeur: return fail(f"{os.path.basename(fp)}: vendor = vendor du codeur (CIV, REG-04)")
        vendors.add(v["vendor"]); verdicts.append(v)
    if len(vendors) < 3: return fail(f"{len(vendors)} vendors distincts (3 requis, REG-05)")
    crit = [o for v in verdicts for o in v["objections"] if o.get("severite") == "critique"]
    rejects = [v["reviewer"] for v in verdicts if v["verdict"] == "REJECT"]
    if rejects or crit:
        print(json.dumps({"resultat":"REJECTED","rejects":rejects,
              "objections_critiques":len(crit),"suite":"Delphi anonymise (max 2 rounds) -> arbitrage Orchestrateur SUR PIECES"},
              ensure_ascii=False)); sys.exit(3)
    print(json.dumps({"resultat":"APPROVED","reviewers":[v["reviewer"] for v in verdicts],
          "vendors":sorted(vendors)}, ensure_ascii=False)); sys.exit(0)
def fail(msg):
    print(json.dumps({"resultat":"INVALIDE","raison":msg}, ensure_ascii=False)); sys.exit(2)
if __name__ == "__main__":
    if len(sys.argv) < 3: print("usage: tally.py <dossier_verdicts> <vendor_codeur>"); sys.exit(1)
    run(sys.argv[1], sys.argv[2])
