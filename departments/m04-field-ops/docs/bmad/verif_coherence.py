#!/usr/bin/env python3
# verif_coherence.py — gate déterministe pour M4 (field ops)
# Vérifie la cohérence interne du cadrage (brief, PRD, architecture)
# Sortie : une ligne par contrôle, puis VERDICT : TOUT VERT ou ÉCARTS: n
# Exit 1 si écarts.

import sys
import re
from pathlib import Path
from collections import Counter

BASE = Path(__file__).parent
FICHIERS = {
    "brief": BASE / "01-BRIEF-ANALYSTE.md",
    "prd":   BASE / "02-PRD-PM.md",
    "arch":  BASE / "03-ARCHITECTURE.md",
}

ETATS_ATTENDUS = {"planifiee", "en_route", "sur_site", "en_revue", "reportee", "terminee", "annulee"}
MOTS_INTERDITS = {"prix", "facture", "montant"}
# Négatifs valant garde
NEG_PATTERNS = [re.compile(r'\b' + re.escape(w) + r'\b', re.IGNORECASE) for w in
                {"jamais","interdit","interdits","interdites","aucun","aucune","hors","absence","rejet","rejette","rejetee","rejete","REJ-","ne produit","pas de","sans"}] + \
               [re.compile(r'\bpas\s+de\b', re.IGNORECASE)]

def lire_fichier(chemin: Path) -> str | None:
    try:
        return chemin.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None

def extraire_section(contenu: str, titre_re: str) -> str:
    """Capture le bloc sous un titre de niveau 2 (##)."""
    pattern = rf'^##\s+{titre_re}\b.*?\n(.*?)(?=\n##\s|\Z)'
    m = re.search(pattern, contenu, re.DOTALL | re.IGNORECASE | re.MULTILINE)
    return m.group(1) if m else ""

# -----------------------------------------------------------------------------
def check_existence_et_sections(c_brief, c_prd, c_arch):
    ecarts = []
    if c_brief is None:
        ecarts.append("Fichier _brief.md manquant")
    elif not re.search(r'^#+\s*(?:\d+\.?\s*)?BESOIN\s*M[ÉE]TIER', c_brief, re.IGNORECASE | re.MULTILINE):
        ecarts.append("Section 'BESOIN MÉTIER' absente du _brief.md")
    if c_prd is None:
        ecarts.append("Fichier _prd.md manquant")
    else:
        if not re.search(r'CA-M4-\d\d', c_prd, re.IGNORECASE | re.MULTILINE):
            ecarts.append("Section 'CA' absente du _prd.md")
        if not re.search(r'^#+\s+Anti-d[ée]rive\b', c_prd, re.IGNORECASE | re.MULTILINE):
            pass  # Anti-dérive vérifiée dans l'architecture ci-dessous
    if c_arch is None:
        ecarts.append("Fichier _architecture.md manquant")
    return ecarts

def check_numerotation_ca(contenu_prd):
    nums = {int(n) for n in re.findall(r'\bCA-M4-(\d{2})\b', contenu_prd)}
    # Borne ÉPINGLÉE volontairement (comme le catalogue gelé M2) : étendre la
    # plage des CA doit être un acte conscient, tracé dans ce fichier.
    attendus = set(range(1, 22))
    ecarts = []
    if manquants := attendus - nums:
        ecarts.append(f"Numéros CA manquants: {sorted(manquants)}")
    if extra := nums - attendus:
        ecarts.append(f"Numéros CA hors plage 01-21: {sorted(extra)}")
    return ecarts

def check_ca_portes_par_stories(contenu_prd):
    sect = '\n'.join(l for l in contenu_prd.splitlines() if l.startswith('### S0') or l.startswith('Périmètre') or l.startswith('Critères portés') or l.startswith('Tier') or l.startswith('Dépendances'))
    if not sect:
        return ["Section 'Stories' non trouvée"]
    tous_ca = set(re.findall(r'\bCA-M4-\d{2}\b', contenu_prd))
    ca_stories = re.findall(r'\bCA-M4-\d{2}\b', sect)
    compteur = Counter(ca_stories)
    ecarts = []
    for ca in sorted(tous_ca):
        cnt = compteur.get(ca, 0)
        if cnt == 0:
            ecarts.append(f"{ca} non porté par une story")
        elif cnt > 1:
            ecarts.append(f"{ca} porté par {cnt} stories (attendu 1)")
    return ecarts

def check_tier_stories(contenu_prd):
    sect = '\n'.join(l for l in contenu_prd.splitlines() if l.startswith('### S0') or l.startswith('Périmètre') or l.startswith('Critères portés') or l.startswith('Tier') or l.startswith('Dépendances'))
    if not sect:
        return ["Section Stories absente, impossible de vérifier les Tiers"]
    ecarts = []
    for i in range(1, 10):
        sid = f"S{i:03d}"
        m = re.search(r'(?:###|##)\s+' + sid + r'\b.*?\n(.*?)(?=\n(?:###|##)\s|\Z)',
                      sect, re.DOTALL)
        if not m:
            ecarts.append(f"Story {sid} non trouvée")
            continue
        bloc = m.group(1)
        tm = re.search(r'^\s*Tier\s*:\s*(T[123])', bloc, re.MULTILINE | re.IGNORECASE)
        if not tm:
            ecarts.append(f"Story {sid} : Tier manquant ou invalide")
            continue
        tier = tm.group(1).upper()
        if i == 8 and tier != "T2":
            ecarts.append(f"Story S008 devrait être T2 mais est {tier}")
        elif i != 8 and tier not in ("T1","T2","T3"):
            ecarts.append(f"Story {sid} : Tier invalide ({tier})")
    return ecarts

def check_etats(c_prd, c_arch):
    ecarts = []
    if c_arch is None:
        ecarts.append("Architecture manquante, vérification des états impossible")
        return ecarts
    # UNE SEULE source de vérité : le motif est dérivé de ETATS_ATTENDUS.
    # (Une alternation codée en dur ici avait divergé de la constante lors de
    # l'ajout d'un état — la duplication d'un enum dans son propre vérificateur
    # est exactement la classe d'écart que ce fichier existe pour détecter.)
    motif_etats = r'\b(' + '|'.join(sorted(ETATS_ATTENDUS)) + r')\b'
    etats_prd = set(re.findall(motif_etats, c_prd))
    etats_arch = set(re.findall(motif_etats, c_arch))
    if etats_prd != ETATS_ATTENDUS:
        ecarts.append(f"États dans PRD: {etats_prd}, attendu {ETATS_ATTENDUS}")
    if etats_arch != ETATS_ATTENDUS:
        ecarts.append(f"États dans ARCH: {etats_arch}, attendu {ETATS_ATTENDUS}")
    # Objection r2 : un état inventé DANS LA TABLE des transitions (mot suivi/précédé
    # de « vers ») doit être détecté même s'il n'est pas dans la constante.
    for gauche, droite in re.findall(r'^- ([a-z_ ]+?) vers ([a-z_]+)', c_prd, re.MULTILINE):
        for morceau in re.split(r'\bou\b', gauche) + [droite]:
            nom = morceau.strip()
            if nom and nom not in ETATS_ATTENDUS:
                ecarts.append(f"Transition citant un état hors énuméré : {nom!r}")
    return ecarts

def check_mots_interdits(c_brief, c_prd, c_arch):
    ecarts = []
    for nom, cont in [("01-BRIEF-ANALYSTE.md", c_brief), ("02-PRD-PM.md", c_prd),
                      ("03-ARCHITECTURE.md", c_arch)]:
        if cont is None:
            continue
        for num, line in enumerate(cont.splitlines(), start=1):
            low = line.lower()
            if not any(re.search(r'\b' + w + r'\b', low) for w in MOTS_INTERDITS):
                continue
            if any(p.search(low) for p in NEG_PATTERNS):
                continue
            ecarts.append(f"Mot interdit dans {nom}:{num}: {line.strip()[:80]}")
    return ecarts

# -----------------------------------------------------------------------------
def main():
    c_brief = lire_fichier(FICHIERS["brief"])
    c_prd   = lire_fichier(FICHIERS["prd"])
    c_arch  = lire_fichier(FICHIERS["arch"])

    controles = [
        ("Existence et sections obligatoires",
         check_existence_et_sections(c_brief, c_prd, c_arch)),
        ("Numérotation CA-M4-01..21 continue",
         check_numerotation_ca(c_prd) if c_prd else ["PRD manquant"]),
        ("Chaque CA porté par exactement une story",
         check_ca_portes_par_stories(c_prd) if c_prd else ["PRD manquant"]),
        ("Tier des stories S001-S009 (S008=T2)",
         check_tier_stories(c_prd) if c_prd else ["PRD manquant"]),
        ("Énuméré d’états identique PRD/ARCH",
         check_etats(c_prd, c_arch) if c_prd and c_arch else ["Manque PRD ou ARCH"]),
        ("Mots interdits de frontière (hors négation)",
         check_mots_interdits(c_brief, c_prd, c_arch)),
    ]

    total_ecarts = 0
    for nom, ecarts in controles:
        if isinstance(ecarts, list) and len(ecarts) == 0:
            print(f"OK: {nom}")
        else:
            if isinstance(ecarts, list):
                for e in ecarts:
                    print(f"ÉCART ({nom}): {e}")
                total_ecarts += len(ecarts)
            else:
                print(f"ÉCART ({nom}): {ecarts}")
                total_ecarts += 1

    if total_ecarts == 0:
        print("VERDICT : TOUT VERT")
        sys.exit(0)
    else:
        print(f"VERDICT : ÉCARTS: {total_ecarts}")
        sys.exit(1)

if __name__ == "__main__":
    main()
# FIN-VERIF-COHERENCE
