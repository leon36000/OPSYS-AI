#!/usr/bin/env python3
# verif_coherence.py — gate déterministe pour M10 (memoire)
# Vérifie la cohérence interne du cadrage (brief, PRD, architecture)
# Sortie : une ligne par contrôle, puis VERDICT : TOUT VERT ou ÉCARTS: n
# Exit 1 si écarts.
#
# Particularité M10 : ce gate est adapté du patron M5/M8 (qui EXIGE l'échappatoire
# D-032 sur chaque énuméré fermé), et surtout PAS du patron M9, dont le contrôle
# `check_absence_enum_documentee` exige au contraire l'ABSENCE d'énuméré fermé.
# M10 possède DEUX vrais énumérés de domaine (STATUT_DECISION, STATUT_REVISION) :
# reproduire le gate de M9 ici serait un faux négatif garanti (architecture §8.1).
#
# Contrôle supplémentaire propre à M10 : l'absence de toute valeur de FUSION dans
# les énumérés de révision (DA-M10-05 — réviser n'est jamais fusionner, le piège
# central du module).

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

VALEURS_STATUT_DECISION = {
    "proposee",
    "validee",
    "remplacee",
    "annulee",
    "indetermine",
}

VALEURS_STATUT_REVISION = {
    "en_attente",
    "distincts_confirmes",
    "obsolete_marquee",
    "indetermine",
}

ENUMS_FERMES = {
    "STATUT_DECISION": {
        "valeurs": VALEURS_STATUT_DECISION,
        "echappatoire": "indetermine",
    },
    "STATUT_REVISION": {
        "valeurs": VALEURS_STATUT_REVISION,
        "echappatoire": "indetermine",
    },
}

# DA-M10-05 : aucune valeur de fusion ne doit exister dans un énuméré de M10.
# Une fusion est irréversible dans un registre append-only — le dépôt a tranché
# l'inverse dans m2_revenue_crm/doublons.py (détecter, signaler, arbitrer).
VALEURS_FUSION_INTERDITES = {
    "fusionnes",
    "fusionne",
    "fusionnee",
    "fusionnees",
}

MOTS_INTERDITS = {
    # "responsable" est délibérément EXCLU : trop générique (ex. "Fichier(s) responsable(s)"
    # apparaît légitimement dans les tableaux de portée, faux positif garanti — leçon M8).
    "raison_signalee",
    "coupable",
}

NEG_PATTERNS = [
    re.compile(
        r"\b" + re.escape(w) + r"\b",
        re.IGNORECASE,
    )
    for w in {
        "jamais",
        "interdit",
        "interdits",
        "interdites",
        "aucun",
        "aucune",
        "hors",
        "absence",
        "rejet",
        "rejette",
        "rejetee",
        "rejete",
        "REJ-",
        "ne produit",
        "pas de",
        "sans",
        "nulle part",
    }
] + [
    re.compile(r"\bpas\s+de\b", re.IGNORECASE),
]


def lire_fichier(chemin: Path) -> str | None:
    try:
        return chemin.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def _extraire_bloc_titre(contenu: str, titre: str) -> str:
    """Capture le bloc d'un titre Markdown contenant le nom demandé."""
    lignes = contenu.splitlines()
    debut = None
    niveau = None

    motif = re.compile(
        rf"^\s*(#+)\s+.*{re.escape(titre)}.*$",
        re.IGNORECASE,
    )

    for i, ligne in enumerate(lignes):
        m = motif.search(ligne)
        if m:
            debut = i
            niveau = len(m.group(1))
            break

    if debut is None:
        return ""

    fin = len(lignes)
    for i in range(debut + 1, len(lignes)):
        m = re.match(r"^\s*(#+)\s+", lignes[i])
        if m and len(m.group(1)) <= niveau:
            fin = i
            break

    return "\n".join(lignes[debut:fin])


def _extraire_bloc_stories(contenu_prd: str) -> str:
    # [^\n]* (jamais .*) sur la ligne de titre : empêche un "stories" répété plus loin
    # dans la prose (backtracking glouton avec DOTALL) de capturer le mauvais titre.
    m = re.search(
        r"^##\s+[^\n]*(?:STORIES|Stories)\b[^\n]*\n(.*?)(?=\n##\s|\Z)",
        contenu_prd,
        re.DOTALL | re.IGNORECASE | re.MULTILINE,
    )
    return m.group(1) if m else ""


def _extraire_stories(contenu_prd: str) -> dict[str, str]:
    bloc = _extraire_bloc_stories(contenu_prd)
    if not bloc:
        return {}

    correspondances = list(
        re.finditer(
            r"^###\s+(S\d{3})\b.*$",
            bloc,
            re.IGNORECASE | re.MULTILINE,
        )
    )

    stories = {}
    for i, correspondance in enumerate(correspondances):
        debut = correspondance.start()
        fin = (
            correspondances[i + 1].start()
            if i + 1 < len(correspondances)
            else len(bloc)
        )
        stories[correspondance.group(1).upper()] = bloc[debut:fin]

    return stories


# -----------------------------------------------------------------------------
def check_existence_et_sections(c_brief, c_prd, c_arch):
    ecarts = []

    if c_brief is None:
        ecarts.append("Fichier _brief.md manquant")
    elif not re.search(
        r"^#+\s*(?:\d+\.?\s*)?BESOIN\s*M[ÉE]TIER",
        c_brief,
        re.IGNORECASE | re.MULTILINE,
    ):
        ecarts.append("Section 'BESOIN MÉTIER' absente du _brief.md")

    if c_prd is None:
        ecarts.append("Fichier _prd.md manquant")
    elif not re.search(r"CA-M10-\d\d", c_prd, re.IGNORECASE | re.MULTILINE):
        ecarts.append("Section 'CA' absente du _prd.md")

    if c_arch is None:
        ecarts.append("Architecture manquante")

    return ecarts


def check_numerotation_ca(contenu_prd):
    nums = {
        int(n)
        for n in re.findall(r"\bCA-M10-(\d{2})\b", contenu_prd)
    }
    attendus = set(range(1, 13))
    ecarts = []

    if manquants := attendus - nums:
        ecarts.append(f"Numéros CA manquants: {sorted(manquants)}")
    if extra := nums - attendus:
        ecarts.append(f"Numéros CA hors plage 01-12: {sorted(extra)}")

    return ecarts


def check_ca_portes_par_stories(contenu_prd):
    stories = _extraire_stories(contenu_prd)
    if not stories:
        return ["Section 'Stories' non trouvée"]

    tous_ca = set(re.findall(r"\bCA-M10-\d{2}\b", contenu_prd))
    ca_stories = []

    for bloc in stories.values():
        ca_stories.extend(re.findall(r"\bCA-M10-\d{2}\b", bloc))

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
    stories = _extraire_stories(contenu_prd)
    if not stories:
        return ["Section Stories absente, impossible de vérifier les Tiers"]

    ecarts = []
    attendus_tiers = {
        "S001": "T2",
        "S002": "T1",
        "S003": "T2",
        "S004": "T2",
        "S005": "T2",
        "S006": "T1",
    }

    for i in range(1, 7):
        sid = f"S{i:03d}"
        bloc = stories.get(sid)

        if bloc is None:
            ecarts.append(f"Story {sid} non trouvée")
            continue

        tm = re.search(
            r"\|\s*\**Tier\**\s*\|\s*\**(T[123])\b",
            bloc,
            re.IGNORECASE,
        )
        if tm is None:
            tm = re.search(
                r"\*\*(T[123])\*\*",
                bloc,
                re.IGNORECASE,
            )
        if tm is None:
            tm = re.search(
                r"^\s*Tier\s*:\s*(T[123])\b",
                bloc,
                re.IGNORECASE | re.MULTILINE,
            )

        if tm is None:
            ecarts.append(f"Story {sid} : Tier manquant ou invalide")
            continue

        tier = tm.group(1).upper()
        attendu = attendus_tiers[sid]
        if tier != attendu:
            ecarts.append(
                f"Story {sid} devrait être {attendu} mais est {tier}"
            )

    return ecarts


def _extraire_affectation_enumere(contenu: str, nom_enum: str) -> str | None:
    """Retourne le texte de l'AFFECTATION `NOM = (...)`, jamais la prose voisine.

    Chercher les valeurs dans un bloc de titre — ou pire, dans le document entier
    en repli — rend le contrôle aveugle : la prose qui COMMENTE l'échappatoire
    (« L'échappatoire `indetermine` est une valeur explicitement choisie… »)
    suffirait à la déclarer présente alors qu'elle serait absente de l'énuméré
    réel. Mesuré par la batterie de mutation : retirer `"indetermine"` de
    STATUT_DECISION laissait le gate VERT.
    """
    motif = re.compile(
        rf"^\s*{re.escape(nom_enum)}\s*=\s*\((.*?)\)",
        re.MULTILINE | re.DOTALL,
    )
    correspondance = motif.search(contenu)
    return correspondance.group(1) if correspondance else None


def check_enums_fermes(c_prd, c_arch):
    """M10 a DEUX vrais énumérés de domaine : l'échappatoire D-032 est EXIGÉE sur
    chacun (patron M5/M8). Contrairement au gate de M9, qui exige l'inverse.

    Les valeurs sont cherchées dans l'AFFECTATION elle-même, jamais dans la prose
    (voir _extraire_affectation_enumere)."""
    ecarts = []

    for nom_enum, config in ENUMS_FERMES.items():
        valeurs = config["valeurs"]
        echappatoire = config["echappatoire"]

        for nom_document, contenu in (
            ("PRD", c_prd),
            ("ARCH", c_arch),
        ):
            if contenu is None:
                continue

            affectation = _extraire_affectation_enumere(contenu, nom_enum)
            if affectation is None:
                ecarts.append(
                    f"{nom_enum} : aucune affectation `{nom_enum} = (...)` "
                    f"trouvée dans {nom_document}"
                )
                continue

            mentionnees = {
                valeur
                for valeur in valeurs
                if re.search(
                    rf'["\']{re.escape(valeur)}["\']',
                    affectation,
                )
            }

            manquantes = valeurs - mentionnees
            if manquantes:
                ecarts.append(
                    f"{nom_enum} incomplet dans {nom_document}: "
                    f"valeurs manquantes {sorted(manquantes)}"
                )

            if echappatoire not in mentionnees:
                ecarts.append(
                    f"{nom_enum} dans {nom_document} : "
                    f"échappatoire D-032 ({echappatoire}) absente"
                )

    return ecarts


def check_aucune_valeur_de_fusion(c_prd, c_arch):
    """DA-M10-05 : réviser n'est JAMAIS fusionner. Aucune valeur de fusion ne doit
    apparaître comme état d'un énuméré — une fusion est irréversible dans un
    registre append-only (patron m2_revenue_crm/doublons.py)."""
    ecarts = []

    for nom_document, contenu in (("PRD", c_prd), ("ARCH", c_arch)):
        if contenu is None:
            continue

        bloc = _extraire_bloc_titre(contenu, "STATUT_REVISION") or contenu
        for valeur in sorted(VALEURS_FUSION_INTERDITES):
            # Cherché comme valeur d'énuméré (entre guillemets), jamais comme mot
            # de prose : la prose DOIT pouvoir dire « aucune fusion » sans échouer.
            if re.search(rf'["\']{re.escape(valeur)}["\']', bloc, re.IGNORECASE):
                ecarts.append(
                    f"{nom_document} : valeur de fusion interdite dans un énuméré "
                    f"({valeur}) — DA-M10-05"
                )

    return ecarts


def check_mots_interdits(c_brief, c_prd, c_arch):
    ecarts = []

    for nom, cont in [
        ("01-BRIEF-ANALYSTE.md", c_brief),
        ("02-PRD-PM.md", c_prd),
        ("03-ARCHITECTURE.md", c_arch),
    ]:
        if cont is None:
            continue

        lignes = cont.splitlines()
        paragraphes = []
        paragraphe_courant = []

        for numero, ligne in enumerate(lignes, start=1):
            if ligne.strip():
                paragraphe_courant.append((numero, ligne))
            elif paragraphe_courant:
                paragraphes.append(paragraphe_courant)
                paragraphe_courant = []

        if paragraphe_courant:
            paragraphes.append(paragraphe_courant)

        for paragraphe in paragraphes:
            texte_paragraphe = "\n".join(
                ligne for _, ligne in paragraphe
            )

            for numero, ligne in paragraphe:
                texte_fenetre_negation = (
                    ligne
                    if ligne.lstrip().startswith("|")
                    else texte_paragraphe
                )

                if any(
                    p.search(texte_fenetre_negation)
                    for p in NEG_PATTERNS
                ):
                    continue

                low = ligne.lower()

                if not any(
                    re.search(r"\b" + re.escape(w) + r"\b", low)
                    for w in MOTS_INTERDITS
                ):
                    continue

                ecarts.append(
                    f"Mot interdit dans {nom}:{numero}: {ligne.strip()[:80]}"
                )

    return ecarts


def check_decisions_architecture(c_arch):
    """Les décisions structurantes de M10 doivent être documentées explicitement :
    DA-M10-01 (patron de registre M5, pas M8 — anti-mimétisme), DA-M10-03 (le WCT
    n'est jamais re-signé), DA-M10-05 (jamais de fusion), DA-M10-06 (garde
    anti-mutation), DA-M10-08 (anti-import de domaine et de core)."""
    if c_arch is None:
        return ["Architecture manquante"]

    ecarts = []
    attendues = {
        "DA-M10-01": "patron de registre générique M5 (anti-mimétisme DA-M9-01)",
        "DA-M10-03": "le consommateur ne re-signe jamais le WCT",
        "DA-M10-05": "réviser n'est jamais fusionner",
        "DA-M10-06": "garde anti-mutation structurelle",
        "DA-M10-08": "aucun import de domaine ni de core",
    }

    for identifiant, libelle in attendues.items():
        # Exiger une DÉFINITION en titre de section, jamais une simple mention :
        # ces identifiants sont cités plusieurs fois dans le document (tableau des
        # fichiers, section de risques). Un contrôle de simple présence resterait
        # VERT si la section de définition était renommée — mesuré par la batterie
        # de mutation (le renommage du titre DA-M10-06 n'était pas détecté).
        if not re.search(
            rf"^#+\s+{re.escape(identifiant)}\b",
            c_arch,
            re.MULTILINE,
        ):
            ecarts.append(
                f"{identifiant} ({libelle}) n'est pas DÉFINIE comme section de "
                f"l'architecture"
            )

    return ecarts


def check_consommateur_wct_documente(c_brief, c_arch):
    """M10 est un consommateur DÉCLARÉ du WCT de M4 (m4_field_ops/outbox.py) sans
    implémentation — c'est la justification centrale de l'existence du module.
    Le brief ET l'architecture doivent le citer explicitement."""
    ecarts = []

    for nom_document, contenu in (("BRIEF", c_brief), ("ARCH", c_arch)):
        if contenu is None:
            ecarts.append(f"{nom_document} manquant")
            continue
        if not re.search(r"CONSOMMATEURS_CIBLES", contenu):
            ecarts.append(
                f"{nom_document} : la citation du contrat WCT de M4 "
                f"(CONSOMMATEURS_CIBLES) est absente"
            )

    return ecarts


# -----------------------------------------------------------------------------
def main():
    c_brief = lire_fichier(FICHIERS["brief"])
    c_prd = lire_fichier(FICHIERS["prd"])
    c_arch = lire_fichier(FICHIERS["arch"])

    controles = [
        (
            "Existence et sections obligatoires",
            check_existence_et_sections(c_brief, c_prd, c_arch),
        ),
        (
            "Numérotation CA-M10-01..12 continue",
            check_numerotation_ca(c_prd)
            if c_prd
            else ["PRD manquant"],
        ),
        (
            "Chaque CA porté par exactement une story",
            check_ca_portes_par_stories(c_prd)
            if c_prd
            else ["PRD manquant"],
        ),
        (
            "Tier des stories S001-S006",
            check_tier_stories(c_prd)
            if c_prd
            else ["PRD manquant"],
        ),
        (
            "Énumérés fermés PRD/ARCH (échappatoire D-032 EXIGÉE)",
            check_enums_fermes(c_prd, c_arch)
            if c_prd and c_arch
            else ["Manque PRD ou ARCH"],
        ),
        (
            "Aucune valeur de fusion dans un énuméré (DA-M10-05)",
            check_aucune_valeur_de_fusion(c_prd, c_arch),
        ),
        (
            "Mots interdits d'accusation (hors négation)",
            check_mots_interdits(c_brief, c_prd, c_arch),
        ),
        (
            "Décisions d'architecture structurantes documentées",
            check_decisions_architecture(c_arch),
        ),
        (
            "Contrat WCT de M4 cité (justification du module)",
            check_consommateur_wct_documente(c_brief, c_arch),
        ),
    ]

    total_ecarts = 0

    for nom, ecarts in controles:
        if isinstance(ecarts, list) and len(ecarts) == 0:
            print(f"OK: {nom}")
        else:
            if isinstance(ecarts, list):
                for ecart in ecarts:
                    print(f"ÉCART ({nom}): {ecart}")
                total_ecarts += len(ecarts)
            else:
                print(f"ÉCART ({nom}): {ecarts}")
                total_ecarts += 1

    if total_ecarts == 0:
        print("VERDICT : TOUT VERT")
        sys.exit(0)

    print(f"VERDICT : ÉCARTS: {total_ecarts}")
    sys.exit(1)


if __name__ == "__main__":
    main()

# FIN-VERIF-COHERENCE
