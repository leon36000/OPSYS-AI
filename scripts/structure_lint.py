#!/usr/bin/env python3
"""Lint d'arborescence D-038 — bijection registre<->disque. Un framework mal range = build rouge."""
import os, re, sys
ROOT = os.path.join(os.path.dirname(__file__), "..")
MODS = ["M1-front-office","M2-revenue-crm","M3-estimation","M4-field-ops","M5-financecore",
        "M6-material-control","M7-marketing","M8-analytics","M9-strategic-intelligence","M10-memoire"]
errs = []
mm = os.path.join(ROOT, "Modules M")
if not os.path.isdir(mm): errs.append("Dossier 'Modules M/' manquant")
for m in MODS:
    p = os.path.join(mm, m)
    if not os.path.isdir(p): errs.append(f"Module manquant: Modules M/{m}"); continue
    for sub in ("frameworks","src","tests","contracts","metrics","docs"):
        if not os.path.isdir(os.path.join(p, sub)): errs.append(f"{m}: sous-dossier manquant '{sub}/'")
    if not os.path.isfile(os.path.join(p, "README.md")): errs.append(f"{m}: README.md manquant")
# bijection frameworks
reg = os.path.join(ROOT, "registries", "frameworks.yaml")
declared = set()
if os.path.isfile(reg):
    txt = open(reg, encoding="utf-8").read()
    declared = {m.group(1).strip() for m in re.finditer(r"path:\s*(.+)", txt)}
else:
    errs.append("registries/frameworks.yaml manquant")
on_disk = set()
for base in [os.path.join(mm, m, "frameworks") for m in MODS] + [os.path.join(ROOT, "core", "frameworks")]:
    if os.path.isdir(base):
        for d in os.listdir(base):
            full = os.path.join(base, d)
            if os.path.isdir(full):
                rel = os.path.relpath(full, ROOT)
                on_disk.add(rel)
                if not os.path.isfile(os.path.join(full, "FRAMEWORK.md")):
                    errs.append(f"{rel}: FRAMEWORK.md manquant")
for rel in sorted(on_disk - declared): errs.append(f"Framework sur disque ABSENT du registre: {rel}")
for rel in sorted(declared - on_disk): errs.append(f"Framework au registre ABSENT du disque: {rel}")
if errs:
    print("STRUCTURE_LINT: ROUGE"); [print(" -", e) for e in errs]; sys.exit(2)
print(f"STRUCTURE_LINT: VERT (10 modules, {len(on_disk)} frameworks, bijection OK)")
