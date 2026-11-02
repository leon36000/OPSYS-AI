"""Escalade INTERNE d'un risque critique (M9.12) : un avis, une tâche, une trace pour la mémoire — jamais un message.

Module pur. Un risque ``CRITIQUE`` et ``ACTIF`` du radar (``risques.evaluer``) produit, par le code et sans modèle :

* un AVIS interne : un maillon du registre chaîné ``avis_risques`` (``AVIS``), qui cite la règle, la mesure du
  propriétaire, le seuil déclaré, la source et les preuves, et dit en toutes lettres qu'aucune cause n'est établie et
  qu'aucun message externe n'est envoyé ;
* une TÂCHE : un plan M9 (``plans.py``) dont le porteur est la direction, l'échéance le jour de l'escalade et le seul
  résultat clé « manuel » : l'atténuation est examinée par une personne. Une tâche déjà ouverte pour la même règle et le
  même sujet n'est pas doublée ;
* une MÉMOIRE : la charge ``m9.fait_strategique`` (genre ``risque``) que M10 range, telle quelle, dans ses faits
  stratégiques (FINANCIAL : jamais dans un paquet de contexte).

Rien de tout cela ne sort de l'entreprise : aucun courriel, aucun SMS, aucune publication, aucune approbation demandée,
aucun appel d'un autre département. Le texte de l'avis est assemblé de codes et de valeurs publiées par les
propriétaires (jamais d'un texte libre, d'un nom ou d'un contact). Un avis par règle, sujet et jour : rejouer
l'escalade du même jour n'ajoute rien.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence

from . import capture_strategique as cs
from . import chainage

SCHEMA = "m9.avis_risques.v1"
TYPES = frozenset({"AVIS"})
TYPE_EVENEMENT = "m9.fait_strategique"
GENRE_MEMOIRE = "risque"
STATUT_MEMOIRE = "signale_par_le_radar"
CANAUX = ("avis interne (registre avis_risques)", "tâche interne (plan M9)", "mémoire M10 (m9.fait_strategique)")
MENTION = (
    "Signal du radar de risques de M9 : une mesure publiée par son propriétaire face à un seuil déclaré par la "
    "direction. Aucune cause établie, aucune action exécutée, aucun message externe. À valider auprès d'un "
    "professionnel qualifié pour tout avis comptable, fiscal ou juridique."
)
_LIMITES = (
    "Un avis n'est ni une cause ni une décision : la direction examine, M9 n'agit pas.",
    "Aucun canal externe : ni courriel, ni SMS, ni publication, ni demande d'approbation n'est créé par l'escalade.",
)


def _refus(code: str, detail: str) -> ValueError:
    return ValueError(f"{code} : {detail}")


def valider_chaine(chaine: Sequence[Mapping]) -> tuple[bool, str]:
    return chainage.valider(SCHEMA, TYPES, chaine)


def selection(radar: Mapping) -> list[Mapping]:
    """Les risques à escalader : ACTIFS et CRITIQUES seulement (jamais un levé, un à reconfirmer ni un inconnu)."""
    return sorted(
        (r for r in radar["risques"] if r["statut"] == "ACTIF" and r["gravite"] == "CRITIQUE"),
        key=lambda r: (r["regle"], r["sujet"]),
    )


def _court(*morceaux: str) -> str:
    return hashlib.sha256("|".join(morceaux).encode()).hexdigest()


def jour_de(connaissance: str) -> str:
    instant = cs.instant(connaissance)
    if instant is None:
        raise _refus("REJ-ESCALADE-TEMPS", "instant de connaissance avec fuseau explicite requis")
    return instant.date().isoformat()


def identifiants(risque: Mapping, connaissance: str) -> dict:
    jour = jour_de(connaissance)
    cle = _court(risque["regle"], risque["sujet"])
    return {
        "avis_id": "avis-" + _court("avis", risque["regle"], risque["sujet"], jour)[:24],
        "tache_id": "tache-" + _court("tache", risque["regle"], risque["sujet"], jour)[:24],
        "suivi_ref": "risque-" + cle[:24],
        "jour": jour,
    }


def _clef_valeur(bloc: Mapping | None) -> str:
    if not bloc:
        return "aucune"
    return ", ".join(f"{k} = {v}" for k, v in sorted(bloc.items()) if v is not None and not isinstance(v, Mapping))


def texte_avis(risque: Mapping) -> str:
    source = risque["source"]
    seuil = risque["seuil"]
    morceaux = [
        f"Risque critique ({risque['domaine']}) : {risque['raison']}.",
        f"Mesure du propriétaire : {_clef_valeur(risque['mesure'])}.",
        f"Seuil déclaré : {_clef_valeur(seuil)}."
        if seuil
        else "Seuil : fait structurel du propriétaire (aucun seuil).",
        f"Règle {risque['regle']}, sujet {risque['sujet']} ; source {source['lecture_id']} "
        f"capture n° {source['capture']} reçue le {source['recu_a']}.",
        "Aucune cause établie. À examiner par la direction ; aucun message externe n'est envoyé.",
    ]
    return " ".join(morceaux)


def avis(chaine: Sequence[Mapping], risque: Mapping, radar: Mapping, *, connaissance: str, par: str) -> dict | None:
    """Le maillon AVIS du risque, ou ``None`` s'il existe déjà pour (règle, sujet, jour)."""
    if risque["statut"] != "ACTIF" or risque["gravite"] != "CRITIQUE":
        raise _refus("REJ-ESCALADE-RISQUE", "seul un risque critique et actif s'escalade")
    ids = identifiants(risque, connaissance)
    if any(m["avis_id"] == ids["avis_id"] for m in chaine):
        return None
    source = risque["source"]
    return chainage.suivant(
        SCHEMA,
        chaine,
        {
            "type": "AVIS",
            "avis_id": ids["avis_id"],
            "jour": ids["jour"],
            "tache_id": ids["tache_id"],
            "suivi_ref": ids["suivi_ref"],
            "risque_id": risque["risque_id"],
            "regle": risque["regle"],
            "domaine": risque["domaine"],
            "sujet": risque["sujet"],
            "gravite": risque["gravite"],
            "raison": risque["raison"],
            "mesure": risque["mesure"],
            "seuil": risque["seuil"],
            "source": {k: source[k] for k in ("lecture_id", "capture", "hash", "recu_a")},
            "preuves": list(risque["preuves"]),
            "radar_id": radar["radar_id"],
            "texte": texte_avis(risque),
            "canal": "interne",
            "externe": False,
            "origine_etablie": False,
            "limites": list(_LIMITES),
            "recu_a": connaissance,
            "par": par,
        },
    )


def tache(risque: Mapping, *, connaissance: str) -> dict:
    """Le plan M9 de la tâche : porteur la direction, échéance le jour de l'escalade, un seul résultat clé manuel."""
    ids = identifiants(risque, connaissance)
    return {
        "plan_id": ids["tache_id"],
        "objectif": f"Examiner le risque critique {risque['regle']} ({risque['sujet']}) et décider de l'atténuation",
        "porteur": "direction (rôle admin)",
        "echeance": ids["jour"],
        "resultats_cles": [
            {
                "id": "attenuation_examinee",
                "libelle": "Une personne a examiné le risque et décidé de la suite",
                "operateur": "manuel",
            }
        ],
        "decision_ref": ids["suivi_ref"],
    }


def evenement_memoire(maillon: Mapping) -> dict:
    """La charge ``m9.fait_strategique`` (genre ``risque``) : identifiant lié à l'empreinte du maillon, toutes les clés
    requises, aucun nom de personne."""
    return {
        "evenement_id": "m9-strat-" + maillon["hash_maillon"],
        "genre": GENRE_MEMOIRE,
        "decision_id": maillon["avis_id"],
        "lecon_id": None,
        "statut": STATUT_MEMOIRE,
        "texte": maillon["texte"],
        "attendus": [],
        "observations": [],
        "concordance": None,
        "decide_role": None,
        "enregistre_le": maillon["recu_a"],
        "source_empreinte": maillon["hash_maillon"],
        "mention": MENTION,
    }


def vue(chaine: Sequence[Mapping], *, depart: int = 0, limite: int = 10) -> dict:
    """Les avis, du plus récent au plus ancien."""
    recents = list(reversed(chaine))
    page = recents[depart : depart + limite]
    return {
        "type": "AVIS_RISQUES",
        "total": len(chaine),
        "avis": [
            {
                k: m[k]
                for k in (
                    "avis_id",
                    "jour",
                    "regle",
                    "domaine",
                    "sujet",
                    "gravite",
                    "raison",
                    "texte",
                    "tache_id",
                    "canal",
                    "externe",
                    "recu_a",
                    "hash_maillon",
                )
            }
            for m in page
        ],
        "depart": depart,
        "prochain_depart": depart + len(page) if depart + len(page) < len(recents) else None,
        "limites": list(_LIMITES),
    }
