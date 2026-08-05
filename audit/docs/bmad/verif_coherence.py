#!/usr/bin/env python3
# verif_coherence.py — gate déterministe du CADRAGE de l'audit AUDIT-000.
# Les affectations CA sont relues dans les deux documents : une cohérence interne
# au seul PRD ne prouve pas que l'architecture porte les mêmes responsabilités.

import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
FICHIERS = {
    "brief": BASE / "01-BRIEF-ANALYSTE.md",
    "prd": BASE / "02-PRD-PM.md",
    "arch": BASE / "03-ARCHITECTURE.md",
}

VALEURS_SEVERITE = {"critique", "majeure", "mineure", "indetermine"}
VALEURS_CLASSE = {
    "defaut-code", "ecart-plan", "faille-securite", "goulot-performance",
    "incoherence-documentaire", "indetermine",
}
VALEURS_STATUT_CONSTAT = {
    "ouvert", "confirme", "refute", "arbitrage-humain", "indetermine",
}
ENUMS_FERMES = {
    "SEVERITE": {"valeurs": VALEURS_SEVERITE, "echappatoire": "indetermine"},
    "CLASSE": {"valeurs": VALEURS_CLASSE, "echappatoire": "indetermine"},
    "STATUT_CONSTAT": {
        "valeurs": VALEURS_STATUT_CONSTAT, "echappatoire": "indetermine",
    },
}

LOTS = ("A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8")
HYPOTHESES = tuple(f"H{n}" for n in range(1, 10))
MOTS_INTERDITS = {"raison_signalee", "coupable"}

NEG_PATTERNS = [
    re.compile(r"\b" + re.escape(w) + r"\b", re.IGNORECASE)
    for w in {
        "jamais", "interdit", "interdits", "interdites", "aucun", "aucune",
        "hors", "absence", "rejet", "rejette", "rejetee", "rejete", "REJ-",
        "ne produit", "pas de", "sans", "nulle part",
    }
] + [re.compile(r"\bpas\s+de\b", re.IGNORECASE)]

EXCLUSION_HYPOTHESE_PATTERNS = [
    re.compile(
        r"\bne\s+(?:traite|couvre|vise|cible|inclut|prend\s+en\s+charge)\s+pas\s+"
        r"(H\d)\b", re.IGNORECASE,
    ),
    re.compile(r"\bhors\s+p[ée]rim[èe]tre\s*:\s*(H\d)\b", re.IGNORECASE),
    re.compile(r"\b(H\d)\s+(?:est\s+)?exclu(?:e|s|es)?\b", re.IGNORECASE),
]


class AffectationEnumereeAmbigueError(ValueError):
    """Une énumération répétée ne permet pas d'identifier sa définition normative."""


def lire_fichier(chemin: Path) -> str | None:
    try:
        return chemin.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def _ligne_porte_negation(ligne: str) -> bool:
    return any(pattern.search(ligne) for pattern in NEG_PATTERNS)


def _hypotheses_explicitement_exclues(ligne: str) -> set[str]:
    exclues = set()
    for pattern in EXCLUSION_HYPOTHESE_PATTERNS:
        exclues.update(match.group(1).upper() for match in pattern.finditer(ligne))
    return exclues


def _extraire_affectation_enumere(contenu: str, nom_enum: str) -> str | None:
    motif = re.compile(
        rf"^\s*{re.escape(nom_enum)}\s*=\s*\((.*?)\)",
        re.MULTILINE | re.DOTALL,
    )
    correspondances = motif.findall(contenu)
    if len(correspondances) > 1:
        raise AffectationEnumereeAmbigueError(nom_enum)
    return correspondances[0] if correspondances else None


def _extraire_bloc_stories(contenu_prd: str) -> str:
    m = re.search(
        r"^##\s+[^\n]*(?:STORIES|Stories)\b[^\n]*\n(.*?)(?=\n##\s|\Z)",
        contenu_prd, re.DOTALL | re.IGNORECASE | re.MULTILINE,
    )
    return m.group(1) if m else ""


def _extraire_lots(contenu_prd: str) -> dict[str, str]:
    bloc = _extraire_bloc_stories(contenu_prd)
    if not bloc:
        return {}

    correspondances = list(re.finditer(
        r"^###\s+AUD-(A\d)\b.*$", bloc, re.IGNORECASE | re.MULTILINE,
    ))
    lots = {}
    for i, corr in enumerate(correspondances):
        fin = correspondances[i + 1].start() if i + 1 < len(correspondances) else len(bloc)
        lots[corr.group(1).upper()] = bloc[corr.start():fin]
    return lots


def _extraire_section_lots_architecture(contenu_arch: str) -> str:
    """Le titre, et non son numéro, rend le contrôle stable au renumérotage."""
    titre = re.search(
        r"^(#{1,6})\s+[^\n]*\bCE\s+QUE\s+CHAQUE\s+LOT\s+PROUVE\b[^\n]*$",
        contenu_arch, re.IGNORECASE | re.MULTILINE,
    )
    if titre is None:
        return ""

    niveau = len(titre.group(1))
    suite = contenu_arch[titre.end():]
    fin = re.search(rf"^#{{1,{niveau}}}\s+", suite, re.MULTILINE)
    return suite[:fin.start()] if fin else suite


def _extraire_criteres_cellule(cellule: str) -> set[str]:
    """Extrait une cellule exclusivement composée d'une liste de critères.

    Chaque élément est soit une référence complète CA-AUD-NN, soit une
    abréviation NN. Une abréviation n'est admise qu'après une référence
    complète déjà rencontrée dans la même liste. Toute cellule contenant un
    élément qui ne respecte pas cette grammaire est rejetée intégralement.
    """
    elements = cellule.split(",")
    if not elements:
        return set()

    criteres = set()
    enumeration_commencee = False

    for element in elements:
        element = element.strip()

        complet = re.fullmatch(r"CA-AUD-(\d{2})", element, re.IGNORECASE)
        if complet is not None:
            criteres.add(f"CA-AUD-{complet.group(1)}")
            enumeration_commencee = True
            continue

        abrege = re.fullmatch(r"(\d{2})", element)
        if abrege is not None and enumeration_commencee:
            criteres.add(f"CA-AUD-{abrege.group(1)}")
            continue

        return set()

    return criteres


def _ajouter_affectation(
    affectations: dict[str, set[str]], lot: str, criteres: set[str]
) -> None:
    for critere in criteres:
        affectations.setdefault(critere, set()).add(lot)


def _extraire_affectations_ca_prd(contenu_prd: str) -> tuple[dict[str, set[str]], set[str]]:
    """Lit exclusivement la ligne normative « Critères portés » de chaque story."""
    affectations: dict[str, set[str]] = {}
    lots_trouves = set()
    for lot, bloc in _extraire_lots(contenu_prd).items():
        lots_trouves.add(lot)
        for ligne in bloc.splitlines():
            cellules = [cellule.strip() for cellule in ligne.strip().split("|")]
            if len(cellules) < 4:
                continue
            if re.fullmatch(r"\*{0,2}Critères portés\*{0,2}", cellules[1], re.IGNORECASE):
                _ajouter_affectation(
                    affectations, lot, _extraire_criteres_cellule(cellules[2])
                )
    return affectations, lots_trouves


def _extraire_affectations_ca_architecture(
    contenu_arch: str,
) -> tuple[dict[str, set[str]], set[str]]:
    """Lit les affectations même si le gras de déclaration est absent.

    Le gras est une obligation de forme contrôlée par
    check_lots_definis_partout. Ici, accepter aussi « | A6 | » évite que la
    cohérence de contenu ne masque un défaut de présentation.
    """
    affectations: dict[str, set[str]] = {}
    lots_trouves = set()
    for ligne in _extraire_section_lots_architecture(contenu_arch).splitlines():
        cellules = [cellule.strip() for cellule in ligne.strip().split("|")]
        if len(cellules) < 4:
            continue
        lot_match = re.fullmatch(r"\*{0,2}(A\d+)\*{0,2}", cellules[1], re.IGNORECASE)
        if lot_match is None:
            continue
        lot = lot_match.group(1).upper()
        lots_trouves.add(lot)
        for cellule in cellules[2:-1]:
            criteres = _extraire_criteres_cellule(cellule)
            if criteres:
                _ajouter_affectation(affectations, lot, criteres)
    return affectations, lots_trouves


def _lots_affiches(lots: set[str]) -> str:
    return ", ".join(sorted(lots))


def check_existence_et_sections(c_brief, c_prd, c_arch):
    ecarts = []
    if c_brief is None:
        ecarts.append("01-BRIEF-ANALYSTE.md manquant")
    elif not re.search(r"^#+\s*(?:\d+\.?\s*)?BESOIN", c_brief, re.IGNORECASE | re.MULTILINE):
        ecarts.append("Section 'BESOIN' absente du brief")
    if c_prd is None:
        ecarts.append("02-PRD-PM.md manquant")
    elif not re.search(r"CA-AUD-\d+", c_prd):
        ecarts.append("Aucun critère CA-AUD-xx dans le PRD")
    if c_arch is None:
        ecarts.append("03-ARCHITECTURE.md manquant")
    return ecarts


def check_numerotation_ca(contenu_prd):
    nums = {int(n) for n in re.findall(r"\bCA-AUD-(\d+)\b", contenu_prd)}
    attendus = set(range(1, 14))
    ecarts = []
    if manquants := attendus - nums:
        ecarts.append(f"Numéros CA manquants: {sorted(manquants)}")
    if extra := nums - attendus:
        ecarts.append(f"Numéros CA hors plage 01-13: {sorted(extra)}")
    return ecarts


def check_ca_portes_par_lots(contenu_prd):
    lots = _extraire_lots(contenu_prd)
    if not lots:
        return ["Section des lots non trouvée dans le PRD"]

    tous_ca = set(re.findall(r"\bCA-AUD-\d+\b", contenu_prd))
    lots_par_ca = {}
    for lot, bloc in lots.items():
        for ca in set(re.findall(r"\bCA-AUD-\d+\b", bloc)):
            lots_par_ca.setdefault(ca, set()).add(lot)

    ecarts = []
    for ca in sorted(tous_ca):
        cnt = len(lots_par_ca.get(ca, set()))
        if cnt == 0:
            ecarts.append(f"{ca} non porté par un lot")
        elif cnt > 1:
            ecarts.append(f"{ca} porté par {cnt} lots (attendu 1)")
    return ecarts


def check_ca_coherents_entre_documents(c_prd, c_arch):
    """Exige la même application critère -> lot dans les deux sources normatives."""
    if c_prd is None:
        return ["PRD manquant"]
    if c_arch is None:
        return ["Architecture manquante"]

    prd, _lots_prd = _extraire_affectations_ca_prd(c_prd)
    arch, _lots_arch = _extraire_affectations_ca_architecture(c_arch)
    ecarts = []

    for critere in sorted(set(prd) | set(arch)):
        dans_prd = prd.get(critere, set())
        dans_arch = arch.get(critere, set())
        if not dans_prd:
            ecarts.append(
                f"{critere} présent dans l'architecture ({_lots_affiches(dans_arch)}) "
                "et absent du PRD"
            )
        elif not dans_arch:
            ecarts.append(
                f"{critere} présent dans le PRD ({_lots_affiches(dans_prd)}) "
                "et absent de l'architecture"
            )
        elif dans_prd != dans_arch:
            ecarts.append(
                f"{critere} affecté au(x) lot(s) {_lots_affiches(dans_prd)} dans le PRD "
                f"et au(x) lot(s) {_lots_affiches(dans_arch)} dans l'architecture"
            )

    return ecarts


def check_tier_des_lots(contenu_prd):
    lots = _extraire_lots(contenu_prd)
    if not lots:
        return ["Section des lots absente, impossible de vérifier les Tiers"]

    attendus = {
        "A1": "T1", "A2": "T2", "A3": "T2", "A4": "T2",
        "A5": "T2", "A6": "T2", "A7": "T1", "A8": "T2",
    }
    ecarts = []
    for lot in LOTS:
        bloc = lots.get(lot)
        if bloc is None:
            ecarts.append(f"Lot AUD-{lot} non trouvé")
            continue
        tm = re.search(
            r"^\s*\|\s*\*\*Tier\*\*\s*\|\s*\**(T[0123])\b",
            bloc, re.IGNORECASE | re.MULTILINE,
        )
        if tm is None:
            ecarts.append(f"Lot AUD-{lot} : Tier manquant ou invalide")
        elif tm.group(1).upper() != attendus[lot]:
            ecarts.append(
                f"Lot AUD-{lot} devrait être {attendus[lot]} mais est {tm.group(1).upper()}"
            )
    return ecarts


def check_enums_fermes(c_prd, c_arch):
    ecarts = []
    for nom_enum, config in ENUMS_FERMES.items():
        for nom_doc, contenu in (("PRD", c_prd), ("ARCH", c_arch)):
            if contenu is None:
                continue
            try:
                affectation = _extraire_affectation_enumere(contenu, nom_enum)
            except AffectationEnumereeAmbigueError:
                ecarts.append(
                    f"{nom_enum} : affectations `{nom_enum} = (...)` multiples et ambiguës "
                    f"dans {nom_doc}"
                )
                continue
            if affectation is None:
                ecarts.append(
                    f"{nom_enum} : aucune affectation `{nom_enum} = (...)` dans {nom_doc}"
                )
                continue
            mentionnees = {
                valeur for valeur in config["valeurs"]
                if re.search(rf'["\']{re.escape(valeur)}["\']', affectation)
            }
            if manquantes := config["valeurs"] - mentionnees:
                ecarts.append(
                    f"{nom_enum} incomplet dans {nom_doc}: manquantes {sorted(manquantes)}"
                )
            if config["echappatoire"] not in mentionnees:
                ecarts.append(
                    f"{nom_enum} dans {nom_doc} : échappatoire D-032 "
                    f"({config['echappatoire']}) absente"
                )
    return ecarts


def check_hypotheses_rattachees(c_brief, c_prd):
    ecarts = []
    if c_brief is None:
        return ["Brief manquant"]
    if c_prd is None:
        return ["PRD manquant"]
    for h in HYPOTHESES:
        if not re.search(rf"\|\s*{h}\s*\|", c_brief):
            ecarts.append(f"{h} absente du tableau des hypothèses du brief")

    citees = set()
    for bloc in _extraire_lots(c_prd).values():
        for ligne in bloc.splitlines():
            exclues = _hypotheses_explicitement_exclues(ligne)
            citees.update(
                h for h in re.findall(r"\bH\d\b", ligne) if h.upper() not in exclues
            )
    for h in HYPOTHESES:
        if h not in citees:
            ecarts.append(f"{h} n'est cible d'aucun lot du PRD")
    return ecarts


def check_lots_definis_partout(c_prd, c_arch):
    ecarts = []
    lots_prd = _extraire_lots(c_prd) if c_prd else {}
    for lot in LOTS:
        if lot not in lots_prd:
            ecarts.append(f"Lot {lot} absent des stories du PRD")
    if c_arch is None:
        ecarts.append("Architecture manquante")
    else:
        section_lots = _extraire_section_lots_architecture(c_arch)
        for lot in LOTS:
            if not re.search(
                rf"^\|\s*\*\*{re.escape(lot)}\*\*\s*\|",
                section_lots, re.IGNORECASE | re.MULTILINE,
            ):
                ecarts.append(f"Lot {lot} absent des sections de l'architecture")
    return ecarts


def check_decisions_architecture(c_arch):
    if c_arch is None:
        return ["Architecture manquante"]
    attendues = {
        "DA-AUD-01": "lots par axe",
        "DA-AUD-02": "le constat est une donnée",
        "DA-AUD-03": "sévérité calculée",
        "DA-AUD-04": "l'audit ne corrige rien",
        "DA-AUD-05": "zéro chemin absolu",
        "DA-AUD-06": "sonde n'est pas juge",
        "DA-AUD-07": "aucun import du code audité",
        "DA-AUD-08": "mutation sur copie jetable",
        "DA-AUD-09": "l'audit ne touche pas la CI qu'il mesure",
        "DA-AUD-10": "la dépendance externe est gelée par empreinte",
        "DA-AUD-11": "le lot A8 déroge à DA-AUD-07, de façon bornée",
    }
    return [
        f"{ident} ({libelle}) n'est pas DÉFINIE comme section"
        for ident, libelle in attendues.items()
        if not re.search(rf"^#+\s+{re.escape(ident)}\b", c_arch, re.MULTILINE)
    ]


def check_invariant_ne_corrige_rien(c_brief, c_prd, c_arch):
    ecarts = []
    motif = re.compile(r"ne\s+corrige\s+rien", re.IGNORECASE)
    for nom, contenu in (("brief", c_brief), ("PRD", c_prd), ("architecture", c_arch)):
        if contenu is None:
            ecarts.append(f"{nom} manquant")
        elif not motif.search(contenu):
            ecarts.append(f"{nom} : l'invariant « l'audit ne corrige rien » est absent")
    return ecarts


def check_limites_annoncees(c_brief):
    if c_brief is None:
        return ["Brief manquant"]
    if not re.search(r"NE\s+PR[ÉE]TENDRA\s+PAS", c_brief, re.IGNORECASE):
        return ["Le brief n'énonce pas ce que l'audit ne prétend pas être"]
    return []


def check_mots_interdits(c_brief, c_prd, c_arch):
    ecarts = []
    for nom, contenu in [
        ("01-BRIEF-ANALYSTE.md", c_brief),
        ("02-PRD-PM.md", c_prd),
        ("03-ARCHITECTURE.md", c_arch),
    ]:
        if contenu is None:
            continue
        for numero, ligne in enumerate(contenu.splitlines(), start=1):
            if _ligne_porte_negation(ligne):
                continue
            low = ligne.lower()
            if any(re.search(r"\b" + re.escape(mot) + r"\b", low) for mot in MOTS_INTERDITS):
                ecarts.append(f"Mot interdit dans {nom}:{numero}: {ligne.strip()[:80]}")
    return ecarts


def main():
    c_brief = lire_fichier(FICHIERS["brief"])
    c_prd = lire_fichier(FICHIERS["prd"])
    c_arch = lire_fichier(FICHIERS["arch"])

    controles = [
        ("Existence et sections obligatoires",
         check_existence_et_sections(c_brief, c_prd, c_arch)),
        ("Numérotation CA-AUD-01..13 continue",
         check_numerotation_ca(c_prd) if c_prd else ["PRD manquant"]),
        ("Chaque CA porté par exactement un lot",
         check_ca_portes_par_lots(c_prd) if c_prd else ["PRD manquant"]),
        ("Tier des 8 lots (T1 inventaire / T2 interprétation)",
         check_tier_des_lots(c_prd) if c_prd else ["PRD manquant"]),
        ("Les 8 lots définis dans le PRD ET l'architecture",
         check_lots_definis_partout(c_prd, c_arch)),
        ("Énumérés fermés PRD/ARCH (échappatoire D-032 EXIGÉE)",
         check_enums_fermes(c_prd, c_arch) if c_prd and c_arch else ["Manque PRD ou ARCH"]),
        ("Hypothèses H1..H9 déclarées et rattachées à un lot",
         check_hypotheses_rattachees(c_brief, c_prd)),
        ("Décisions d'architecture DA-AUD-01..11 définies en section",
         check_decisions_architecture(c_arch)),
        ("Invariant « l'audit ne corrige rien » dans les 3 documents",
         check_invariant_ne_corrige_rien(c_brief, c_prd, c_arch)),
        ("Le brief énonce les limites de l'audit",
         check_limites_annoncees(c_brief)),
        ("Mots interdits d'accusation (hors négation)",
         check_mots_interdits(c_brief, c_prd, c_arch)),
        ("Affectation critère -> lot identique dans le PRD et l'architecture",
         check_ca_coherents_entre_documents(c_prd, c_arch)),
    ]

    total = 0
    for nom, ecarts in controles:
        if isinstance(ecarts, list) and not ecarts:
            print(f"OK: {nom}")
        else:
            for ecart in ecarts:
                print(f"ÉCART ({nom}): {ecart}")
            total += len(ecarts)

    if total == 0:
        print("VERDICT : TOUT VERT")
        sys.exit(0)
    print(f"VERDICT : ÉCARTS: {total}")
    sys.exit(1)


if __name__ == "__main__":
    main()
