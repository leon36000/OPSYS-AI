# -*- coding: utf-8 -*-
"""Mesures de cohérence du cadrage BMAD M2.

Durci après la revue round 5 : la version précédente ne cherchait QUE ce que
j'attendais (elle n'a pas vu un en-tête dupliqué, un critère concaténé ni un
bégaiement). Elle cherche désormais aussi les ANOMALIES de forme.
"""
import re
import sys
from pathlib import Path

D = Path("/media/pc1/Storage/Repo/OPSYS-AI/Modules M/M2-revenue-crm/docs/bmad")
DOCS = {n: (D / n).read_text(encoding="utf-8")
        for n in ("01-BRIEF-ANALYSTE.md", "02-PRD-PM.md", "03-ARCHITECTURE.md")}
brief, prd, arch = DOCS["01-BRIEF-ANALYSTE.md"], DOCS["02-PRD-PM.md"], DOCS["03-ARCHITECTURE.md"]
echecs = []


def verifie(libelle, condition, detail=""):
    print(f"{'OK  ' if condition else 'ECHEC'} {libelle}" + (f" — {detail}" if detail else ""))
    if not condition:
        echecs.append(libelle)


# --- cohérence de fond -------------------------------------------------------
m6 = re.search(r"^6\. Crit.*?(?=^7\. Hors)", prd, re.S | re.M)
listes = sorted({int(c) for c in re.findall(r"CA-M2-(\d+)", m6.group(0))}) if m6 else []
invoques = {int(c) for c in re.findall(r"CA-M2-(\d+)", brief + prd + arch)}
verifie("tous les critères invoqués figurent dans la liste §6",
        not (invoques - set(listes)), f"{len(listes)} listés, orphelins : {sorted(invoques - set(listes)) or 'aucun'}")

sec9 = arch.split("## 9.")[1] if "## 9." in arch else ""
stories = re.findall(r"^- M2-S(\d+) \((T\d)", sec9, re.M)
verifie("8 stories bien formées (Tier + dépendances)", len(stories) == 8, f"{len(stories)}/8")

verifie("aucune lecture croisée d'arborescence inter-modules",
        not re.search(r"fichier source M1", arch))
dbl = re.search(r"doublons potentiels[^.]*\.", brief)
verifie("critère de doublon disjonctif au brief", bool(dbl) and " OU " in dbl.group(0))
verifie("aucun critère non déterministe (latence)",
        not re.findall(r"100 ?ms|millisecond", prd + arch))
verifie("aucun pourcentage de couverture", not re.findall(r"9[0-9] ?%", brief + prd + arch))
verifie("l'architecte n'a livré aucun code", arch.count("```") == 0)

# --- anomalies de FORME (ce que la version précédente ne voyait pas) ---------
for nom, txt in DOCS.items():
    titres = [re.sub(r"^#+\s*", "", l).strip().lower()
              for l in txt.splitlines() if re.match(r"^#{1,3} ", l)]
    dupes = {t for t in titres if titres.count(t) > 1}
    verifie(f"{nom} : aucun titre dupliqué", not dupes, str(dupes) if dupes else "")

    brut = [l.strip() for l in txt.splitlines()
            if re.match(r"^\d\.\s+\w", l) and not l.startswith("#")]
    md = {re.sub(r"^#+\s*", "", l).strip() for l in txt.splitlines() if re.match(r"^#{1,3} \d\.", l)}
    collision = [b for b in brut if b in md]
    verifie(f"{nom} : aucun en-tête en double forme (brut + markdown)", not collision, str(collision))

    beg = re.findall(r"\b(\w[\w' ]{20,60}?)\s+\1\b", txt)
    verifie(f"{nom} : aucun bégaiement de copier-coller", not beg,
            (beg[0][:50] + "…") if beg else "")

# NOTE : la version précédente comparait deux portées DIFFÉRENTES (tout le PRD
# vs la seule §6) et rapportait un faux positif. On reste dans §6.
sec6 = m6.group(0) if m6 else ""
debut_ligne = {int(c) for c in re.findall(r"^CA-M2-(\d+) :", sec6, re.M)}
verifie("chaque critère listé commence sa propre ligne DANS §6",
        debut_ligne == set(listes),
        f"début de ligne {sorted(debut_ligne)} vs listés {listes}")

# Les ENSEMBLES dédupliquent : sans ce contrôle, un critère écrit deux fois
# passerait inaperçu (objection de revue round 7, fondée).
from collections import Counter
# ANGLE MORT CORRIGE (objection round 8, fondee) : « ^CA-M2-NN : » ne voyait QUE
# les definitions en debut de ligne. Une definition CONCATENEE en fin d'une autre
# ligne restait invisible — et j'avais refute l'objection en utilisant ce meme
# instrument aveugle. On cherche desormais N'IMPORTE OU dans la section.
partout = re.findall(r"CA-M2-(\d+)\s*:", sec6)
doublons = {n: c for n, c in Counter(partout).items() if c > 1}
verifie("aucun critère défini deux fois dans §6 (recherche n'importe où)",
        not doublons, str(doublons))
concatenes = [m.group(1) for m in re.finditer(r"CA-M2-(\d+)\s*:", sec6)
              if sec6.rfind("\n", 0, m.start()) + 1 != m.start()]
verifie("aucune définition concaténée en milieu de ligne", not concatenes, str(concatenes))
hors6 = len(re.findall(r"^CA-M2-\d+ :", prd, re.M)) - len(re.findall(r"^CA-M2-\d+ :", sec6, re.M))
verifie("aucun critère défini hors de §6", hors6 == 0, f"{hors6} définition(s) hors section")

print()
print("VERDICT :", "TOUT VERT" if not echecs else f"{len(echecs)} ÉCHEC(S) : {echecs}")
sys.exit(1 if echecs else 0)
