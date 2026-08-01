"""Batterie de mutations M3-S002 — rejouable. Chaque garde neutralisée isolément doit ROUGIR."""
import pathlib, subprocess, sys, shutil, re
D = pathlib.Path("Modules M/M3-estimation/src/m3_estimation")
Q, S, C = D/"qualite_photos.py", D/"signaux.py", D/"contrats.py"
TQ, TS = "Modules M/M3-estimation/tests/test_qualite_photos.py", "Modules M/M3-estimation/tests/test_signaux.py"
originaux = {p: p.read_text(encoding="utf-8") for p in (Q, S, C)}

def run(cible):
    for p in pathlib.Path("Modules M/M3-estimation/src").rglob("__pycache__"):
        shutil.rmtree(p, ignore_errors=True)
    return subprocess.run([sys.executable, "-B", "-m", "pytest", cible, "-q", "--color=no",
                           "--no-header", "-p", "no:cacheprovider"],
                          capture_output=True, text=True, timeout=400).returncode

MUTATIONS = [
 ("regle des DEUX dimensions : min -> max", Q, TQ, "        plus_petite_dimension = min(", "        plus_petite_dimension = max("),
 ("borne resolution : < devient <=", Q, TQ, "        if plus_petite_dimension < resolution_minimale:", "        if plus_petite_dimension <= resolution_minimale:"),
 ("borne eclairage : < devient <=", Q, TQ, '        if photo["eclairage"] < eclairage_minimal:', '        if photo["eclairage"] <= eclairage_minimal:'),
 ("echelle 0-10 retiree", Q, TQ, "    if type(eclairage) not in (int, float) or not 0 <= eclairage <= 10:", "    if type(eclairage) not in (int, float):"),
 ("typage STRICT -> isinstance (accepte True)", Q, TQ, '    if type(seuils["resolution_minimale"]) is not int:', '    if not isinstance(seuils["resolution_minimale"], int):'),
 ("cles des seuils : egalite -> sous-ensemble", Q, TQ, "    if set(seuils) != set(contrats.CHAMPS_SEUILS_QUALITE):", "    if not set(seuils) <= set(contrats.CHAMPS_SEUILS_QUALITE):"),
 ("CHAMPS_SEUILS_QUALITE tronque", C, TQ, '"resolution_minimale", "eclairage_minimal"', '"resolution_minimale"'),
 ("emission_count devient un compteur", S, TS, "EMISSION_UNIQUE = 1", "EMISSION_UNIQUE = 2"),
]
tout = True
for libelle, fichier, cible, avant, apres in MUTATIONS:
    o = originaux[fichier]
    if o.count(avant) != 1:
        print(f"{libelle:44} -> *** ANCRE x{o.count(avant)} ***"); tout = False; continue
    fichier.write_text(o.replace(avant, apres, 1), encoding="utf-8")
    try:
        rc = run(cible)
    finally:
        fichier.write_text(o, encoding="utf-8")
    ok = rc != 0
    tout &= ok
    print(f"{libelle:44} -> {'ROUGE' if ok else '*** RESTE VERT ***'}")

# CHAMPS_PHOTO : la derniere cle, reperee par mesure et non ecrite en dur
m = re.search(r"CHAMPS_PHOTO\s*=\s*\((.*?)\)", originaux[C], re.DOTALL)
cles = re.findall(r'"([a-z_]+)"', m.group(1))
C.write_text(originaux[C].replace(m.group(0), m.group(0).replace(f'"{cles[-1]}"', "", 1), 1), encoding="utf-8")
try:
    rc = run(TQ)
finally:
    C.write_text(originaux[C], encoding="utf-8")
tout &= rc != 0
print(f"{'CHAMPS_PHOTO ampute de sa derniere cle':44} -> {'ROUGE' if rc else '*** RESTE VERT ***'}")

# copie defensive et refus de la liste vide : ancres reperees par mesure
os_ = originaux[S]
for libelle, candidats, transf in [
    ("copie defensive retiree", [l for l in os_.splitlines() if "elements_manquants" in l and "list(" in l],
     lambda l: re.sub(r"list\(([^)]*)\)", r"\1", l)),
    ("refus de la liste vide neutralise", [l for l in os_.splitlines() if "elements_manquants" in l and "if" in l and ("not " in l or "len(" in l)],
     lambda l: re.sub(r"if .*:", "if False:", l))]:
    if len(candidats) != 1:
        print(f"{libelle:44} -> *** {len(candidats)} candidates ***"); tout = False; continue
    S.write_text(os_.replace(candidats[0], transf(candidats[0]), 1), encoding="utf-8")
    try:
        rc = run(TS)
    finally:
        S.write_text(os_, encoding="utf-8")
    tout &= rc != 0
    print(f"{libelle:44} -> {'ROUGE' if rc else '*** RESTE VERT ***'}")


# Gardes couvertes après la revue scellée round 6 — chacune isolée par un cas dédié.
GARDES_TARDIVES = [
 ("garde « photos est une liste »", Q, TQ, "    if not isinstance(photos, list):", "    if False:"),
 ("borne INFERIEURE de l echelle 0-10", Q, TQ, "not 0 <= eclairage <= 10", "eclairage > 10"),
 ("cles exactes de reference_echelle", Q, TQ, '        if not isinstance(reference, dict) or set(reference) != {', '        if not isinstance(reference, dict) or not set(reference) <= {'),
 ("type booleen STRICT de dimensions_connues", Q, TQ, '        if type(reference["dimensions_connues"]) is not bool:', "        if False:"),
]
for libelle, fichier, cible, avant, apres in GARDES_TARDIVES:
    o = originaux[fichier]
    if o.count(avant) != 1:
        print(f"{libelle:44} -> *** ANCRE x{o.count(avant)} ***"); tout = False; continue
    fichier.write_text(o.replace(avant, apres, 1), encoding="utf-8")
    try:
        rc = run(cible)
    finally:
        fichier.write_text(o, encoding="utf-8")
    tout &= rc != 0
    print(f"{libelle:44} -> {'ROUGE' if rc else '*** RESTE VERT ***'}")

intactes = all(p.read_text(encoding="utf-8") == o for p, o in originaux.items())
print(f"\n{'15/15 mordent' if tout else '*** BATTERIE INCOMPLETE ***'} | sources restaurees a l identique : {intactes}")
sys.exit(0 if tout and intactes else 1)
