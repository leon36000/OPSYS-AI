"""Faits stratégiques d'Athéna (M9) : M10 les mémorise tels quels, avec leur provenance, sans jamais les interpréter.

M9 publie ``m9.fait_strategique`` : UNE entrée de sa boucle « décision → résultat mesuré → leçon » par événement. M10
range
chaque événement dans son registre ``faits_strategiques`` (append-only, chaîné), distinct des registres Événements,
Affaires et Faits analytiques : ce n'est pas un fait d'affaire (aucun ``lead_id``).

Règles :

* LISTE BLANCHE, FORMES FERMÉES. Chaque champ gardé a une forme (identifiant, énuméré, texte décimal, instant) ; un
champ de
  plus, manquant ou hors forme est un refus nommé qui dit le CHAMP, jamais la valeur. Le seul texte libre conservé est
  l'énoncé de la décision ou le gabarit de la leçon, borné, rendu à la lecture comme une DONNÉE non fiable ;
* CONFIDENTIALITÉ. L'entrée est ``FINANCIAL`` (décisions d'affaires de la direction) : elle ne sort dans aucun paquet de
  contexte, pour aucun agent (``confidentialite.py``) ; elle se lit dans M10, avec son outil et son rôle ;
* IDEMPOTENCE. Un fait par ``evenement_id`` : une relivraison ne crée aucun second maillon ;
* UN RISQUE CRITIQUE (genre ``risque``, statut ``signale_par_le_radar``) est l'escalade INTERNE du radar de M9 : un
texte
  assemblé de codes et de valeurs de propriétaires, sans leçon, sans attendus, sans signataire, sans cause ;
* UNE LEÇON N'EST PAS UNE CAUSE : un événement ``lecon`` au statut ``proposee_non_validee`` est mémorisé comme tel et ne
devient
  jamais « validée » ailleurs que par un événement de la direction.

Module pur (DA-M10-08) : aucun import d'``opsys``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from . import confidentialite, validation

TYPE_EVENEMENT = "m9.fait_strategique"
TYPE_ENTREE = "fait_strategique"
PRODUCTEUR = "m09-strategic-intelligence"
MAX_PAGE = 8
LIMITE_TEXTE = 1200

REJ_STRATEGIQUE_CHAMP_MANQUANT = "REJ-STRATEGIQUE-CHAMP-MANQUANT"
REJ_STRATEGIQUE_CHAMP_INVALIDE = "REJ-STRATEGIQUE-CHAMP-INVALIDE"

_IDENTIFIANT_EVENEMENT = re.compile(r"^m9-strat-[0-9a-f]{64}$")
_EMPREINTE = re.compile(r"^[0-9a-f]{64}$")
_MESURE_ID = re.compile(r"^m8_[a-z0-9_]{1,76}$")
_DECISION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:\-]{0,127}$")
_LECON_ID = re.compile(r"^lecon-[0-9a-f]{24}$")
_DECIMAL = re.compile(r"^-?[0-9]+(\.[0-9]+)?$")
_INSTANT = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.+\-Zz]{6,32}$")
_GENRES = frozenset({"decision", "resultat_observe", "lecon", "risque"})
_STATUTS = frozenset(
    {"declaree_par_la_direction", "observe_par_mesure", "proposee_non_validee", "validee_par_la_direction",
     "rejetee_par_la_direction", "signale_par_le_radar"}
)  # fmt: skip
_GENRE_STATUT = {
    "decision": {"declaree_par_la_direction"},
    "resultat_observe": {"observe_par_mesure"},
    "lecon": {"proposee_non_validee", "validee_par_la_direction", "rejetee_par_la_direction"},
    "risque": {"signale_par_le_radar"},
}
_SENS = frozenset({"hausse", "baisse", "stable"})
_CONCORDANCES = frozenset({"CONCORDE", "NE_CONCORDE_PAS", "NON_MESURABLE", "MIXTE"})
_ROLES = frozenset({"admin", "nathan_owner"})
_CLES = frozenset(
    {
        "evenement_id", "genre", "decision_id", "lecon_id", "statut", "texte", "attendus", "observations",
            "concordance",
        "decide_role", "enregistre_le", "source_empreinte", "mention",
    }
)  # fmt: skip


class ChampRefuse(ValueError):
    """Un champ manque ou sort de sa forme fermée. ``code`` est le verdict, ``detail`` le CHAMP (jamais sa valeur)."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code} : {detail}")
        self.code = code
        self.detail = detail

    def verdict(self) -> dict[str, Any]:
        return validation.construire_verdict(self.code, self.detail)


def _texte(valeur: Any, champ: str, motif: re.Pattern[str] | None = None, maximum: int = 400) -> str:
    if (
        not isinstance(valeur, str)
        or not valeur
        or len(valeur) > maximum
        or (motif is not None and not motif.fullmatch(valeur))
    ):
        raise ChampRefuse(REJ_STRATEGIQUE_CHAMP_INVALIDE, champ)
    return valeur


def _optionnel(valeur: Any, champ: str, motif: re.Pattern[str] | None = None, maximum: int = 400) -> str | None:
    return None if valeur is None else _texte(valeur, champ, motif, maximum)


def _attendu(brut: Any, rang: int) -> dict[str, Any]:
    if not isinstance(brut, Mapping) or set(brut) != {"metric_id", "sens"} or brut["sens"] not in _SENS:
        raise ChampRefuse(REJ_STRATEGIQUE_CHAMP_INVALIDE, f"attendus[{rang}]")
    return {"metric_id": _texte(brut["metric_id"], f"attendus[{rang}].metric_id", _MESURE_ID), "sens": brut["sens"]}


def _observation(brut: Any, rang: int) -> dict[str, Any]:
    cles = {"metric_id", "sens_attendu", "sens_observe", "valeur_avant", "valeur_apres", "concordance"}
    if (
        not isinstance(brut, Mapping)
        or set(brut) != cles
        or brut["sens_attendu"] not in _SENS
        or (brut["sens_observe"] is not None and brut["sens_observe"] not in _SENS)
        or brut["concordance"] not in {"CONCORDE", "NE_CONCORDE_PAS", "NON_MESURABLE"}
    ):
        raise ChampRefuse(REJ_STRATEGIQUE_CHAMP_INVALIDE, f"observations[{rang}]")
    if (brut["concordance"] == "NON_MESURABLE") != (brut["sens_observe"] is None):
        raise ChampRefuse(REJ_STRATEGIQUE_CHAMP_INVALIDE, f"observations[{rang}].sens_observe")
    return {
        "metric_id": _texte(brut["metric_id"], f"observations[{rang}].metric_id", _MESURE_ID),
        "sens_attendu": brut["sens_attendu"],
        "sens_observe": brut["sens_observe"],
        "valeur_avant": _optionnel(brut["valeur_avant"], f"observations[{rang}].valeur_avant", _DECIMAL, 24),
        "valeur_apres": _optionnel(brut["valeur_apres"], f"observations[{rang}].valeur_apres", _DECIMAL, 24),
        "concordance": brut["concordance"],
    }


def extraire(charge: Mapping[str, Any]) -> dict[str, Any]:
    """Les champs à garder d'une charge ``m9.fait_strategique`` : liste blanche, formes fermées, cohérence
    genre/statut."""
    if not isinstance(charge, Mapping):
        raise ChampRefuse(REJ_STRATEGIQUE_CHAMP_INVALIDE, "charge")
    for cle in sorted(_CLES):
        if cle not in charge:
            raise ChampRefuse(REJ_STRATEGIQUE_CHAMP_MANQUANT, cle)
    if set(charge) - _CLES:
        raise ChampRefuse(REJ_STRATEGIQUE_CHAMP_INVALIDE, "champ inconnu")
    genre, statut = charge["genre"], charge["statut"]
    if genre not in _GENRES or statut not in _STATUTS or statut not in _GENRE_STATUT[genre]:
        raise ChampRefuse(REJ_STRATEGIQUE_CHAMP_INVALIDE, "genre/statut")
    attendus, observations = charge["attendus"], charge["observations"]
    if (
        not isinstance(attendus, list)
        or len(attendus) > 8
        or not isinstance(observations, list)
        or len(observations) > 8
    ):
        raise ChampRefuse(REJ_STRATEGIQUE_CHAMP_INVALIDE, "attendus/observations")
    if charge["concordance"] is not None and charge["concordance"] not in _CONCORDANCES:
        raise ChampRefuse(REJ_STRATEGIQUE_CHAMP_INVALIDE, "concordance")
    if charge["decide_role"] is not None and charge["decide_role"] not in _ROLES:
        raise ChampRefuse(REJ_STRATEGIQUE_CHAMP_INVALIDE, "decide_role")
    if genre == "decision" and (not attendus or charge["texte"] is None):
        raise ChampRefuse(REJ_STRATEGIQUE_CHAMP_INVALIDE, "decision : énoncé et attendus requis")
    if genre == "resultat_observe" and (not observations or charge["concordance"] is None):
        raise ChampRefuse(REJ_STRATEGIQUE_CHAMP_INVALIDE, "resultat_observe : observations et concordance requises")
    if genre == "lecon" and (charge["lecon_id"] is None or charge["texte"] is None):
        raise ChampRefuse(REJ_STRATEGIQUE_CHAMP_INVALIDE, "lecon : identifiant et texte requis")
    if genre == "risque" and (
        charge["texte"] is None or charge["lecon_id"] is not None or attendus or observations
        or charge["concordance"] is not None or charge["decide_role"] is not None
    ):
        raise ChampRefuse(REJ_STRATEGIQUE_CHAMP_INVALIDE, "risque : texte seul (ni leçon, ni attendus, ni signataire)")
    return {
        "evenement_id": _texte(charge["evenement_id"], "evenement_id", _IDENTIFIANT_EVENEMENT),
        "genre": genre,
        "decision_id": _texte(charge["decision_id"], "decision_id", _DECISION_ID, 128),
        "lecon_id": _optionnel(charge["lecon_id"], "lecon_id", _LECON_ID, 64),
        "statut": statut,
        "texte": _optionnel(charge["texte"], "texte", None, LIMITE_TEXTE),
        "attendus": [_attendu(a, rang) for rang, a in enumerate(attendus)],
        "observations": [_observation(o, rang) for rang, o in enumerate(observations)],
        "concordance": charge["concordance"],
        "decide_role": charge["decide_role"],
        "horodatage": _texte(charge["enregistre_le"], "enregistre_le", _INSTANT, 40),
        "source_empreinte": _texte(charge["source_empreinte"], "source_empreinte", _EMPREINTE),
        "mention": _texte(charge["mention"], "mention", None, 400),
    }


def entree(champs: Mapping[str, Any]) -> dict[str, Any]:
    """Le maillon à écrire : les champs extraits, puis ce que M10 pose. Une charge ne peut ni choisir le type, ni le
    producteur, ni le niveau de confidentialité : ces clés sont écrites APRÈS elle."""
    return {
        **champs,
        "type_entree": TYPE_ENTREE,
        "producteur": PRODUCTEUR,
        "confidentialite": confidentialite.NIVEAU_FINANCIER,
    }


def memoriser(charge: Mapping[str, Any], registre_cible: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Mémorise un fait stratégique ; rend ``(resultat, None)`` ou ``(None, verdict)``, sans rien écrire au refus.
    ``resultat`` : ``{maillon, deja_memorise}``. Un seul maillon par ``evenement_id``."""
    try:
        champs = extraire(charge)
    except ChampRefuse as refus:
        return None, refus.verdict()
    for maillon in registre_cible.lire():
        if maillon.get("type_entree") == TYPE_ENTREE and maillon.get("evenement_id") == champs["evenement_id"]:
            return {"maillon": maillon, "deja_memorise": True}, None
    ligne_id = registre_cible.ajouter(entree(champs))
    maillon = next(m for m in registre_cible.lire() if m["ligne_id"] == ligne_id)
    return {"maillon": maillon, "deja_memorise": False}, None


def lister(registre_cible: Any, limite: int, decalage: int, decision_id: str | None = None) -> dict[str, Any]:
    """Les faits mémorisés, du plus récent au plus ancien, une page à la fois, avec leur provenance. Le texte est une
    DONNÉE non fiable : il est rendu marqué comme tel, jamais comme une consigne."""
    maillons = [
        m
        for m in registre_cible.lire()
        if m.get("type_entree") == TYPE_ENTREE and (decision_id is None or m["decision_id"] == decision_id)
    ]
    recents = list(reversed(maillons))
    page = recents[decalage : decalage + limite]
    return {
        "total": len(maillons),
        "decalage": decalage,
        "limite": limite,
        "faits": [
            {
                "evenement_id": m["evenement_id"],
                "genre": m["genre"],
                "statut": m["statut"],
                "decision_id": m["decision_id"],
                "lecon_id": m["lecon_id"],
                "enregistre_le": m["horodatage"],
                "concordance": m["concordance"],
                "attendus": m["attendus"],
                "observations": m["observations"],
                "texte": m["texte"],
                "fiabilite_du_texte": "donnee_non_fiable",
                "source_empreinte": m["source_empreinte"],
                "ligne_id": m["ligne_id"],
            }
            for m in page
        ],
        "suivant": decalage + limite if decalage + limite < len(recents) else None,
        "confidentialite": confidentialite.NIVEAU_FINANCIER,
        "regle": "Une leçon n'est une leçon qu'au statut validee_par_la_direction ; une leçon proposée n'établit "
                 "aucune cause.",
    }
