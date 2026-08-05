#!/usr/bin/env python3
# verif_coherence.py — gate déterministe du CADRAGE de l'audit AUDIT-000
# Vérifie la cohérence interne des trois documents BMAD (brief, PRD, architecture).
# Sortie : une ligne par contrôle, puis VERDICT : TOUT VERT ou ÉCARTS: n
# Exit 1 si écarts.
#
# Adapté du patron M5/M10 (qui EXIGE l'échappatoire D-032 sur chaque énuméré fermé).
# Spécificités de ce gate, absentes des gates de module :
#   - il vérifie que les 9 hypothèses d'entrée H1..H9 sont TOUTES rattachées à un lot
#     (une hypothèse orpheline serait un fait mesuré que l'audit ne va jamais prouver) ;
#   - il vérifie que le brief énonce ce que l'audit NE prétend PAS être (§7) — sans quoi
#     le rapport final pourrait surpromettre ;
#   - il vérifie que « l'audit ne corrige rien » est présent dans les TROIS documents,
#     puisque c'est l'invariant dont dépend la validité de tous les témoins.

import re
import sys
from pathlib import Path

# Chemin déduit de l'EMPLACEMENT DU SCRIPT, jamais du répertoire courant (DA-AUD-05).
BASE = Path(__file__).resolve().parent
FICHIERS = {
    "brief": BASE / "01-BRIEF-ANALYSTE.md",
    "prd": BASE / "02-PRD-PM.md",
    "arch": BASE / "03-ARCHITECTURE.md",
}

VALEURS_SEVERITE = {"critique", "majeure", "mineure", "indetermine"}
VALEURS_CLASSE = {
    "defaut-code",
    "ecart-plan",
    "faille-securite",
    "goulot-performance",
    "incoherence-documentaire",
    "indetermine",
}
VALEURS_STATUT_CONSTAT = {
    "ouvert",
    "confirme",
    "refute",
    "arbitrage-humain",
    "indetermine",
}

ENUMS_FERMES = {
    "SEVERITE": {"valeurs": VALEURS_SEVERITE, "echappatoire": "indetermine"},
    "CLASSE": {"valeurs": VALEURS_CLASSE, "echappatoire": "indetermine"},
    "STATUT_CONSTAT": {
        "valeurs": VALEURS_STATUT_CONSTAT,
        "echappatoire": "indetermine",
    },
}

LOTS = ("A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8")
HYPOTHESES = tuple(f"H{n}" for n in range(1, 10))

MOTS_INTERDITS = {
    # "responsable" est délibérément EXCLU : trop générique (faux positif garanti sur
    # les tableaux de portée — leçon M8).
    "raison_signalee",
    "coupable",
}

NEG_PATTERNS = [
    re.compile(r"\b" + re.escape(w) + r"\b", re.IGNORECASE)
    for w in {
        "jamais", "interdit", "interdits", "interdites", "aucun", "aucune",
        "hors", "absence", "rejet", "rejette", "rejetee", "rejete", "REJ-",
        "ne produit", "pas de", "sans", "nulle part",
    }
] + [re.compile(r"\bpas\s+de\b", re.IGNORECASE)]

# Ces motifs ne réutilisent délibérément pas NEG_PATTERNS : cette dernière liste sert
# au contrôle des mots d'accusation et accepte toute négation présente sur une ligne.
# Un rattachement ne peut être invalidé que par une exclusion explicite portant sur
# l'hypothèse elle-même ; « sans preuve » décrivant un autre objet ne l'exclut pas.
EXCLUSION_HYPOTHESE_PATTERNS = [
    re.compile(
        r"\bne\s+(?:traite|couvre|vise|cible|inclut|prend\s+en\s+charge)\s+pas\s+"
        r"(H\d)\b",
        re.IGNORECASE,
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
    """Une négation ne vaut que pour sa propre ligne.

    Une portée au paragraphe désarmait des accusations présentes sur les lignes voisines.
    """
    return any(pattern.search(ligne) for pattern in NEG_PATTERNS)


def _hypotheses_explicitement_exclues(ligne: str) -> set[str]:
    """Retourne seulement les hypothèses visées par une exclusion explicite."""
    exclues = set()
    for pattern in EXCLUSION_HYPOTHESE_PATTERNS:
        exclues.update(match.group(1).upper() for match in pattern.finditer(ligne))
    return exclues


def _extraire_affectation_enumere(contenu: str, nom_enum: str) -> str | None:
    """Retourne l'unique affectation `NOM = (...)`, jamais la prose voisine.

    Plusieurs affectations du même énuméré sont ambiguës : choisir la première ferait
    dépendre le contrôle de l'ordre d'un exemple et de la définition normative.
    """
    motif = re.compile(
        rf"^\s*{re.escape(nom_enum)}\s*=\s*\((.*?)\)",
        re.MULTILINE | re.DOTALL,
    )
    correspondances = motif.findall(contenu)
    if len(correspondances) > 1:
        raise AffectationEnumereeAmbigueError(nom_enum)
    return correspondances[0] if correspondances else None


def _extraire_bloc_stories(contenu_prd: str) -> str:
    # [^\n]* (jamais .*) sur la ligne de titre : empêche un "stories" répété plus loin
    # dans la prose de capturer le mauvais titre par backtracking glouton.
    m = re.search(
        r"^##\s+[^\n]*(?:STORIES|Stories)\b[^\n]*\n(.*?)(?=\n##\s|\Z)",
        contenu_prd,
        re.DOTALL | re.IGNORECASE | re.MULTILINE,
    )
    return m.group(1) if m else ""


def _extraire_lots(contenu_prd: str) -> dict[str, str]:
    bloc = _extraire_bloc_stories(contenu_prd)
    if not bloc:
        return {}

    correspondances = list(
        re.finditer(r"^###\s+AUD-(A\d)\b.*$", bloc, re.IGNORECASE | re.MULTILINE)
    )

    lots = {}
    for i, corr in enumerate(correspondances):
        debut = corr.start()
        fin = correspondances[i + 1].start() if i + 1 < len(correspondances) else len(bloc)
        lots[corr.group(1).upper()] = bloc[debut:fin]
    return lots


def _extraire_section_lots_architecture(contenu_arch: str) -> str:
    """Retourne la section d'architecture consacrée à ce que prouve chaque lot."""
    titre = re.search(
        r"^(#{1,6})\s+[^\n]*\bCE\s+QUE\s+CHAQUE\s+LOT\s+PROUVE\b[^\n]*$",
        contenu_arch,
        re.IGNORECASE | re.MULTILINE,
    )
    if titre is None:
        return ""

    niveau = len(titre.group(1))
    suite = contenu_arch[titre.end():]
    fin = re.search(
        rf"^#{{1,{niveau}}}\s+",
        suite,
        re.MULTILINE,
    )
    return suite[:fin.start()] if fin else suite


# -----------------------------------------------------------------------------
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
        # Un même critère répété dans un lot reste porté par ce seul lot.
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


def check_tier_des_lots(contenu_prd):
    """Chaque lot porte son Tier, et il correspond à ce que le lot DÉCIDE.

    Un lot d'inventaire pur (la sortie de sonde EST le constat) est T1 ; un lot
    exigeant un jugement de gravité ou d'interprétation est T2.
    """
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

        # Seule la ligne dédiée du tableau déclare le Tier ; une mention en prose
        # peut être un renvoi vers le Tier d'un autre lot.
        tm = re.search(
            r"^\s*\|\s*\*\*Tier\*\*\s*\|\s*\**(T[0123])\b",
            bloc,
            re.IGNORECASE | re.MULTILINE,
        )
        if tm is None:
            ecarts.append(f"Lot AUD-{lot} : Tier manquant ou invalide")
            continue

        tier = tm.group(1).upper()
        if tier != attendus[lot]:
            ecarts.append(f"Lot AUD-{lot} devrait être {attendus[lot]} mais est {tier}")

    return ecarts


def check_enums_fermes(c_prd, c_arch):
    """Les trois énumérés portent l'échappatoire D-032, dans les DEUX documents.

    Les valeurs sont cherchées dans l'AFFECTATION elle-même, jamais dans la prose.
    """
    ecarts = []

    for nom_enum, config in ENUMS_FERMES.items():
        valeurs = config["valeurs"]
        echappatoire = config["echappatoire"]

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
                v for v in valeurs
                if re.search(rf'["\']{re.escape(v)}["\']', affectation)
            }

            if manquantes := valeurs - mentionnees:
                ecarts.append(
                    f"{nom_enum} incomplet dans {nom_doc}: manquantes {sorted(manquantes)}"
                )
            if echappatoire not in mentionnees:
                ecarts.append(
                    f"{nom_enum} dans {nom_doc} : échappatoire D-032 "
                    f"({echappatoire}) absente"
                )

    return ecarts


def check_hypotheses_rattachees(c_brief, c_prd):
    """Les 9 hypothèses d'entrée sont TOUTES déclarées au brief ET rattachées à un lot.

    Une hypothèse mesurée mais orpheline serait un fait que l'audit ne prouvera jamais —
    exactement le mode de défaillance « une parade annoncée mais rattachée à aucune
    story n'existe pas » déjà rencontré dans ce dépôt.
    """
    ecarts = []

    if c_brief is None:
        return ["Brief manquant"]
    if c_prd is None:
        return ["PRD manquant"]

    for h in HYPOTHESES:
        if not re.search(rf"\|\s*{h}\s*\|", c_brief):
            ecarts.append(f"{h} absente du tableau des hypothèses du brief")

    # Seule l'hypothèse explicitement exclue ne compte pas comme cible. Les autres
    # hypothèses de la même ligne, ainsi que les négations descriptives sans portée
    # sur une hypothèse, restent des rattachements valides.
    lots = _extraire_lots(c_prd)
    citees = set()
    for bloc in lots.values():
        for ligne in bloc.splitlines():
            exclues = _hypotheses_explicitement_exclues(ligne)
            citees.update(
                hypothese
                for hypothese in re.findall(r"\bH\d\b", ligne)
                if hypothese.upper() not in exclues
            )

    for h in HYPOTHESES:
        if h not in citees:
            ecarts.append(f"{h} n'est cible d'aucun lot du PRD")

    return ecarts


def check_lots_definis_partout(c_prd, c_arch):
    """Les 7 lots existent dans le PRD et ouvrent une ligne de tableau en architecture."""
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
            # Une définition structurée est une ligne de tableau dont la première
            # cellule est le lot ; une mention en prose ou dans une autre cellule
            # ne définit donc pas le lot.
            if not re.search(
                rf"^\|\s*(?:\*\*)?{re.escape(lot)}(?:\*\*)?\s*\|",
                section_lots,
                re.IGNORECASE | re.MULTILINE,
            ):
                ecarts.append(f"Lot {lot} absent des sections de l'architecture")

    return ecarts


def check_decisions_architecture(c_arch):
    """Les 8 décisions structurantes sont DÉFINIES en titre de section.

    Exiger la définition et non la simple mention : ces identifiants sont cités
    plusieurs fois ailleurs (tableaux, renvois), et un contrôle de présence resterait
    VERT si la section de définition était renommée. Défaut mesuré sur le gate de M10.
    """
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

    ecarts = []
    for ident, libelle in attendues.items():
        if not re.search(rf"^#+\s+{re.escape(ident)}\b", c_arch, re.MULTILINE):
            ecarts.append(f"{ident} ({libelle}) n'est pas DÉFINIE comme section")

    return ecarts


def check_invariant_ne_corrige_rien(c_brief, c_prd, c_arch):
    """« L'audit ne corrige rien » doit figurer dans les TROIS documents.

    C'est l'invariant dont dépend la validité de TOUS les témoins : si l'audit
    corrigeait, le témoin RED passerait au vert et la preuve du constat s'évaporerait.
    """
    ecarts = []
    motif = re.compile(r"ne\s+corrige\s+rien", re.IGNORECASE)

    for nom, contenu in (
        ("brief", c_brief), ("PRD", c_prd), ("architecture", c_arch)
    ):
        if contenu is None:
            ecarts.append(f"{nom} manquant")
        elif not motif.search(contenu):
            ecarts.append(f"{nom} : l'invariant « l'audit ne corrige rien » est absent")

    return ecarts


def check_limites_annoncees(c_brief):
    """Le brief énonce ce que l'audit NE prétend PAS être.

    Sans cette section, le rapport final pourrait laisser croire qu'il prouve l'absence
    de défauts — proposition non vérifiable.
    """
    if c_brief is None:
        return ["Brief manquant"]

    if not re.search(r"NE\s+PR[ÉE]TENDRA\s+PAS", c_brief, re.IGNORECASE):
        return ["Le brief n'énonce pas ce que l'audit ne prétend pas être"]

    return []


def check_mots_interdits(c_brief, c_prd, c_arch):
    ecarts = []

    for nom, cont in [
        ("01-BRIEF-ANALYSTE.md", c_brief),
        ("02-PRD-PM.md", c_prd),
        ("03-ARCHITECTURE.md", c_arch),
    ]:
        if cont is None:
            continue

        for numero, ligne in enumerate(cont.splitlines(), start=1):
            # Une négation ne protège jamais les autres lignes du paragraphe.
            if _ligne_porte_negation(ligne):
                continue

            low = ligne.lower()
            if not any(
                re.search(r"\b" + re.escape(w) + r"\b", low) for w in MOTS_INTERDITS
            ):
                continue
            ecarts.append(f"Mot interdit dans {nom}:{numero}: {ligne.strip()[:80]}")

    return ecarts


# -----------------------------------------------------------------------------
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
