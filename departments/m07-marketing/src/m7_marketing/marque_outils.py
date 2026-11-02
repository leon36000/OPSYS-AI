"""Outils de lecture de la marque (M7-MARQUE) : audit de conformité d'un contenu existant et guide de ton.

Deux outils T0 (lecture pure, agent seulement, aucun droit d'appareil) qui enveloppent les modules purs
`brand.conformite`
et `brand.guide` sur le profil de marque DURABLE courant (`brand.registre.lire_snapshot_marque`) :

  - `m7_auditer_contenu_marque` : évalue des textes déjà écrits (publications existantes, brouillons du modèle) contre
  le
    profil : verdict de la porte qualité, score, sous-scores et raisons. Rien n'est écrit, rien n'est approuvé : c'est
    un
    constat. Profil absent, non configuré ou illisible : refus nommé, aucun score (fail-closed).
  - `m7_guide_de_ton_marque` : le guide de ton généré du profil, avec ce qui manque.

La réponse d'un outil tient sous la borne de 6 000 caractères du socle : les audits sont rendus par pages entières
(`reprendre_a`), jamais coupés en deux.
"""

from __future__ import annotations

import json
import re
from typing import Any

from opsys.outils import Outil

from .brand import conformite, guide
from .brand import registre as brand_registre
from .usine import plateformes
from .usine.controle_texte import TEXTE_MAX_CONTROLE

AUDIT_MAX_PAR_APPEL = 8
RAISONS_MAX_PAR_CONTENU = 6
DETAIL_MAX = 140
BUDGET_SORTIE = 5400
_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_DETAIL_CONFIDENTIEL = "renseignement de confidentialité détecté dans le texte (valeur non répétée) ; retire-le"
STATUT_PROFIL_NON_CONFIGURE = "profil_marque_non_configure"
_ABANDON = (
    "Par plateforme",
    "Mentions",
    "Ce que la marque peut dire",
    "À faire valider par le propriétaire (ne pas citer)",
    "Voix déclarée",
    "Identité",
)


def _snapshot() -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """`(profil, None)` ou `(None, refus)` : le profil durable courant, jamais un repli sur un gabarit."""
    snapshot = brand_registre.lire_snapshot_marque()
    profil = snapshot.get("profil")
    if snapshot.get("statut") != "configure" or profil is None:
        return None, {
            "statut": STATUT_PROFIL_NON_CONFIGURE,
            "motif": snapshot.get("motif") or "profil de marque non configuré",
            "a_faire": "faire configurer le profil de marque par le propriétaire (m7_configurer_profil_marque)",
        }
    return profil, None


def _valider_contenus(contenus: Any) -> list[dict[str, str]]:
    if not isinstance(contenus, list) or not contenus:
        raise ValueError("contenus : une liste non vide de {reference, plateforme, texte} est attendue")
    if len(contenus) > 30:
        raise ValueError("contenus : 30 au plus par appel")
    vus: set[str] = set()
    sortie = []
    for item in contenus:
        if not isinstance(item, dict) or set(item) != {"reference", "plateforme", "texte"}:
            raise ValueError("contenus : chaque entrée est {reference, plateforme, texte}")
        reference, plateforme, texte = item["reference"], item["plateforme"], item["texte"]
        if not isinstance(reference, str) or not _REFERENCE.fullmatch(reference) or reference in vus:
            raise ValueError(
                "contenus.reference : identifiant unique de 1 à 64 caractères (lettres, chiffres, . _ : -)"
            )
        vus.add(reference)
        if plateforme not in plateformes.CODES_PLATEFORMES:
            raise ValueError(f"contenus.plateforme : {', '.join(plateformes.CODES_PLATEFORMES)}")
        if not isinstance(texte, str) or len(texte) > TEXTE_MAX_CONTROLE:
            raise ValueError(f"contenus.texte : un texte d'au plus {TEXTE_MAX_CONTROLE} caractères")
        sortie.append({"reference": reference, "plateforme": plateforme, "texte": texte})
    return sortie


def _ligne_audit(reference: str, plateforme: str, rapport: dict[str, Any]) -> dict[str, Any]:
    raisons = [
        {
            "dimension": r["dimension"],
            "code": r["code"],
            "bloquante": r["bloquante"],
            # Une adresse, une coordonnée ou un nom de client n'est jamais répété dans une réponse d'outil (traces,
            # journaux).
            "detail": _DETAIL_CONFIDENTIEL
            if r["dimension"] == conformite.CONFIDENTIALITE
            else r["detail"][:DETAIL_MAX],
        }
        for r in rapport["raisons"]
    ]
    return {
        "reference": reference,
        "plateforme": plateforme,
        "verdict": rapport["verdict"],
        "score_global": rapport["score_global"],
        "sous_scores": {nom: s["score"] for nom, s in rapport["sous_scores"].items()},
        "raisons": raisons[:RAISONS_MAX_PAR_CONTENU],
        "raisons_omises": max(0, len(raisons) - RAISONS_MAX_PAR_CONTENU),
        "non_evaluables": rapport["non_evaluables"],
    }


def auditer_contenu_marque(contenus: list[dict[str, str]], depart: int = 0) -> dict[str, Any]:
    """Audite des textes existants contre le profil de marque courant. Lecture pure."""
    valides = _valider_contenus(contenus)
    if type(depart) is not int or not 0 <= depart < len(valides):
        raise ValueError("depart : un indice de la liste (0 pour commencer)")
    profil, refus = _snapshot()
    if refus is not None:
        return refus
    lignes: list[dict[str, Any]] = []
    rapport_profil: dict[str, Any] = {}
    compte: dict[str, int] = {}
    for item in valides[depart : depart + AUDIT_MAX_PAR_APPEL]:
        evaluation = conformite.evaluer(item["texte"], profil, plateformes.plateforme(item["plateforme"]))
        ligne = _ligne_audit(item["reference"], item["plateforme"], evaluation.rapport)
        rapport_profil = evaluation.rapport["profil"]
        if lignes and len(json.dumps(lignes + [ligne], ensure_ascii=False)) > BUDGET_SORTIE:
            break
        lignes.append(ligne)
        compte[ligne["verdict"]] = compte.get(ligne["verdict"], 0) + 1
    suivant = depart + len(lignes)
    return {
        "statut": "audite",
        "version_regles": conformite.VERSION_REGLES,
        "audits": lignes,
        "synthese": {
            "verdicts": compte,
            "profil": {"version": rapport_profil.get("version"), "a_fournir": rapport_profil.get("a_fournir", [])[:6]},
        },
        "reprendre_a": suivant if suivant < len(valides) else None,
        "lecture": "Constat seulement : rien n'est approuvé ni écrit. La porte binaire reste la loi ; le score "
        "l'explique. "
        "Un contenu « conforme » ne dit rien des dimensions non évaluables (profil incomplet).",
    }


def guide_de_ton_marque() -> dict[str, Any]:
    """Le guide de ton généré du profil de marque courant. Lecture pure."""
    profil, refus = _snapshot()
    if refus is not None:
        return refus
    resultat = guide.generer(profil)
    sections = list(resultat["sections"])
    omises: list[str] = []
    while True:
        texte = "\n\n".join(f"{s['titre']}\n" + "\n".join(f"- {ligne}" for ligne in s["lignes"]) for s in sections)
        if len(texte) <= BUDGET_SORTIE - 800 or len(sections) <= 1:
            break
        # Ordre d'abandon : le moins utile à la rédaction d'abord ; « À ne jamais dire » et « À fournir » restent.
        titre = next((t for t in _ABANDON if any(s["titre"] == t for s in sections)), None)
        if titre is None:
            break
        sections = [s for s in sections if s["titre"] != titre]
        omises.append(titre)
    return {
        "statut": "guide",
        "version": resultat["version"],
        "guide_id": resultat["guide_id"],
        "texte": texte,
        "sections_omises": omises,
        "completude": {
            "version_de_lecture": resultat["completude"]["version_de_lecture"],
            "a_fournir": resultat["completude"]["a_fournir"],
            "a_valider_par_le_proprietaire": resultat["completude"]["a_valider_par_le_proprietaire"],
        },
    }


def outils() -> tuple[Outil, ...]:
    return (
        Outil(
            nom="m7_auditer_contenu_marque",
            description=(
                "Audite des textes EXISTANTS (publications, brouillons) contre le profil de marque courant : verdict "
                "de la "
                "porte qualité (conforme, conforme_avec_reserves, refuse), score global, sous-scores par dimension "
                "(mots "
                "interdits, messages interdits, promesses non validées, prix et chiffres, confidentialité, ton, "
                "longueur, "
                "style, mentions) et raisons nommées. La porte binaire reste la loi, le score l'explique ; aucun "
                "modèle "
                "ne note. Une dimension que le profil ne permet pas d'évaluer est dite « non évaluable », jamais "
                "notée. "
                "Profil absent ou non configuré : refus nommé, aucun score. Huit contenus au plus par page "
                "(`reprendre_a`). Lecture pure : rien n'est approuvé ni écrit."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "contenus": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 30,
                        "items": {
                            "type": "object",
                            "properties": {
                                "reference": {"type": "string", "description": "identifiant de votre choix, unique"},
                                "plateforme": {"type": "string", "enum": list(plateformes.CODES_PLATEFORMES)},
                                "texte": {"type": "string", "maxLength": TEXTE_MAX_CONTROLE},
                            },
                            "required": ["reference", "plateforme", "texte"],
                            "additionalProperties": False,
                        },
                    },
                    "depart": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "reprendre à cet indice (`reprendre_a`)",
                    },
                },
                "required": ["contenus"],
                "additionalProperties": False,
            },
            fonction=auditer_contenu_marque,
        ),
        Outil(
            nom="m7_guide_de_ton_marque",
            description=(
                "Génère le guide de ton et de marque du profil courant : voix déclarée, ce que la marque peut dire "
                "(énoncés "
                "VALIDÉS par le propriétaire seulement), ce qu'elle ne dit jamais, style par plateforme, mentions, "
                "et ce qui "
                "reste à fournir ou à faire valider. Déterministe : aucune phrase inventée. Profil non configuré : "
                "refus "
                "nommé. Lecture pure."
            ),
            parametres={"type": "object", "properties": {}, "additionalProperties": False},
            fonction=guide_de_ton_marque,
        ),
    )
