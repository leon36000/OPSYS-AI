"""Priorisation et allocation M9.11 : classement explicable et proposition de capacité, sans engager personne.

Module pur et déterministe. Les CRITÈRES sont des entrées déclarées (par la personne ou comme proposition non validée du
conseil),
jamais déduits ici ; la POLITIQUE de pondération est versionnée et rendue avec le résultat, donc chaque rang se refait à
la main :
``score = poids_impact × impact + poids_urgence × urgence + poids_confiance × confiance`` (entiers 1–5), égalité
départagée par
l'effort le plus faible puis l'identifiant.

L'allocation ne distribue que des JOURS-PERSONNES sur une capacité qui doit venir d'un fait cité du dossier (M4) : sans
capacité
connue, le classement est rendu mais AUCUNE allocation n'est proposée. Elle n'attribue aucune personne, aucune date,
aucun budget.
Une proposition qui exige une validation humaine (dépense, embauche, budget marketing, prix global, etc.) reste marquée
``VALIDATION_HUMAINE_REQUISE`` même retenue. Des priorités incompatibles ne sont pas arbitrées : le conflit est nommé
avec les deux
voies et l'arbitrage est humain. Dépendance non satisfaite, effort inconnu, capacité nulle ou hypothèse hors bornes :
refus nommé.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from decimal import Decimal

from . import conseil

VERSION = "2026-10-28.1"
POLITIQUE = {
    "version": VERSION,
    "poids_impact": 3,
    "poids_urgence": 2,
    "poids_confiance": 1,
    "departage": "effort puis id",
}
MAX_CANDIDATS = 40
SOURCE_HYPOTHESE = "HYPOTHESE_DECLAREE_PAR_LA_PERSONNE"
ORIGINES = frozenset({"DECLAREE_PAR_LA_PERSONNE", "PROPOSITION_CONSEIL_NON_VALIDEE"})
_DECIMAL = re.compile(r"\d{1,9}(\.\d{1,2})?")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:\-]{0,63}")
_CHAMPS = frozenset(
    {"id", "libelle", "origine", "impact", "urgence", "confiance", "effort_jours_personnes", "validation"}
    | {"depend_de", "incompatible_avec", "refs"}
)
_LIMITES = (
    "Classement d'entrées déclarées selon une politique versionnée : ni une décision ni une prévision de résultat.",
    "L'allocation compte des jours-personnes sur une capacité citée ; elle n'affecte aucune personne, date ni budget.",
)


def _refus(code: str, detail: str) -> ValueError:
    return ValueError(f"{code} : {detail}")


def _note(valeur: object, nom: str) -> int:
    if type(valeur) is not int or not 1 <= valeur <= 5:
        raise _refus("REJ-PRIORITE-HYPOTHESE", f"{nom} : entier de 1 à 5 requis")
    return valeur


def _candidat(brut: object) -> dict:
    if (
        not isinstance(brut, Mapping)
        or not {"id", "libelle", "origine", "impact", "urgence", "confiance"} <= set(brut) <= _CHAMPS
    ):
        raise _refus("REJ-PRIORITE-CANDIDAT", "candidat {id, libelle, origine, impact, urgence, confiance[, …]} requis")
    if type(brut["id"]) is not str or not _ID.fullmatch(brut["id"]):
        raise _refus("REJ-PRIORITE-CANDIDAT", "identifiant sobre requis")
    if type(brut["libelle"]) is not str or not brut["libelle"].strip() or len(brut["libelle"]) > 300:
        raise _refus("REJ-PRIORITE-CANDIDAT", "libellé borné requis")
    if brut["origine"] not in ORIGINES:
        raise _refus("REJ-PRIORITE-CANDIDAT", f"origine parmi {sorted(ORIGINES)}")
    effort = brut.get("effort_jours_personnes")
    if effort is not None and (type(effort) is not str or not _DECIMAL.fullmatch(effort)):
        raise _refus("REJ-PRIORITE-HYPOTHESE", "effort : décimal textuel positif sobre ou absent")
    validation = brut.get("validation")
    if validation is not None and validation not in conseil.ACTIONS_SENSIBLES:
        raise _refus("REJ-PRIORITE-CANDIDAT", "validation : type d'action sensible connu ou absent")
    for cle in ("depend_de", "incompatible_avec", "refs"):
        liste = brut.get(cle, [])
        if type(liste) is not list or len(liste) > 16 or any(type(x) is not str or not _ID.fullmatch(x) for x in liste):
            raise _refus("REJ-PRIORITE-CANDIDAT", f"{cle} : liste bornée d'identifiants")
    return {
        "id": brut["id"],
        "libelle": brut["libelle"],
        "origine": brut["origine"],
        "impact": _note(brut["impact"], "impact"),
        "urgence": _note(brut["urgence"], "urgence"),
        "confiance": _note(brut["confiance"], "confiance"),
        "effort": Decimal(effort) if effort is not None else None,
        "validation": validation,
        "depend_de": list(brut.get("depend_de", [])),
        "incompatible_avec": list(brut.get("incompatible_avec", [])),
        "refs": list(brut.get("refs", [])),
    }


def classer(candidats: Sequence[object]) -> list[dict]:
    if not isinstance(candidats, Sequence) or isinstance(candidats, str) or not 1 <= len(candidats) <= MAX_CANDIDATS:
        raise _refus("REJ-PRIORITE-CANDIDAT", f"1 à {MAX_CANDIDATS} candidats requis")
    propres = [_candidat(c) for c in candidats]
    if len({c["id"] for c in propres}) != len(propres):
        raise _refus("REJ-PRIORITE-CANDIDAT", "identifiants distincts requis")
    ids = {c["id"] for c in propres}
    for c in propres:
        inconnus = (set(c["depend_de"]) | set(c["incompatible_avec"])) - ids
        if inconnus or c["id"] in c["depend_de"] or c["id"] in c["incompatible_avec"]:
            raise _refus("REJ-PRIORITE-CANDIDAT", f"{c['id']} : références inconnues ou circulaires {sorted(inconnus)}")
    for c in propres:
        c["contributions"] = {
            "impact": POLITIQUE["poids_impact"] * c["impact"],
            "urgence": POLITIQUE["poids_urgence"] * c["urgence"],
            "confiance": POLITIQUE["poids_confiance"] * c["confiance"],
        }
        c["score"] = sum(c["contributions"].values())
    propres.sort(key=lambda c: (-c["score"], c["effort"] if c["effort"] is not None else Decimal("Infinity"), c["id"]))
    for rang, c in enumerate(propres, 1):
        c["rang"] = rang
    return propres


# Lectures dont la capacité n'est PAS en jours-personnes : la citer comme capacité d'allocation mélangerait des unités.
# M4 (m4.capacite_equipe) publie des heures d'horloge d'équipe et interdit toute conversion en jours-personnes.
UNITES_INCOMPATIBLES = {"m4.capacite_equipe": "heures_declarees"}


def allouer(candidats: Sequence[object], *, capacite: str | None, source_capacite: str | None = None) -> dict:
    """Classement, puis allocation gloutonne dans l'ordre des rangs sur ``capacite`` (jours-personnes)."""
    if type(source_capacite) is str and source_capacite.split("#", 1)[0] in UNITES_INCOMPATIBLES:
        unite = UNITES_INCOMPATIBLES[source_capacite.split("#", 1)[0]]
        raise _refus(
            "REJ-PRIORITE-UNITE",
            f"la capacité citée est en {unite}, l'allocation compte des jours-personnes : "
            "aucune conversion n'est faite",
        )
    classes = classer(candidats)
    par_id = {c["id"]: c for c in classes}
    resultat: dict = {
        "type": "PRIORISATION",
        "politique": dict(POLITIQUE),
        "classement": [
            {k: c[k] for k in ("rang", "id", "libelle", "origine", "score", "contributions", "refs")}
            | {
                "effort_jours_personnes": str(c["effort"]) if c["effort"] is not None else None,
                "validation": c["validation"],
            }
            for c in classes
        ],
        "limites": list(_LIMITES),
    }  # fmt: skip
    # Conflits : paires incompatibles dont les deux membres pourraient être retenus ; le conflit est nommé, jamais
    # arbitré ici.
    conflits = sorted({tuple(sorted((c["id"], autre))) for c in classes for autre in c["incompatible_avec"]})
    resultat["conflits"] = [
        {
            "entre": list(paire),
            "meilleur_rang": min(par_id[paire[0]]["rang"], par_id[paire[1]]["rang"]),
            "arbitrage": "HUMAIN_REQUIS",
            "voies": [f"retenir {paire[0]} sans {paire[1]}", f"retenir {paire[1]} sans {paire[0]}"],
        }
        for paire in conflits
    ]
    if capacite is None:
        resultat["allocation"] = {
            "statut": "CAPACITE_INCONNUE",
            "raison": "aucune capacité citée : aucune allocation proposée",
        }
        resultat["retenus"], resultat["non_retenus"] = (
            [],
            [{"id": c["id"], "raison": "CAPACITE_INCONNUE"} for c in classes],
        )
        return _signer(resultat)
    if type(capacite) is not str or not _DECIMAL.fullmatch(capacite):
        raise _refus("REJ-PRIORITE-HYPOTHESE", "capacité : décimal textuel sobre")
    reste = total = Decimal(capacite)
    if total <= 0:
        raise _refus("REJ-PRIORITE-INFAISABLE", "capacité nulle : aucune allocation possible, aucun défaut inventé")
    retenus: list[str] = []
    raisons: dict[str, str] = {}
    exclus: set[str] = set()
    restants = list(classes)
    progres = True
    while progres:  # une dépendance mieux classée que son dépendant est retenue d'abord ; le dépendant est revu ensuite
        progres = False
        for c in list(restants):
            raison = None
            if c["effort"] is None:
                raison = "EFFORT_INCONNU"
            elif any(d not in retenus for d in c["depend_de"]):
                raison = "DEPENDANCE_NON_SATISFAITE"
            elif c["id"] in exclus:
                raison = "EXCLU_PAR_CONFLIT"
            elif c["effort"] > reste:
                raison = "CAPACITE_INSUFFISANTE"
            if raison is not None:
                raisons[c["id"]] = raison
                continue
            retenus.append(c["id"])
            restants.remove(c)
            raisons.pop(c["id"], None)
            reste -= c["effort"]
            exclus.update(c["incompatible_avec"])
            exclus.update(a["id"] for a in classes if c["id"] in a["incompatible_avec"])
            progres = True
    non = [
        {"id": c["id"], "raison": raisons[c["id"]]} for c in classes if c["id"] in raisons and c["id"] not in retenus
    ]
    resultat["allocation"] = {
        "statut": "PROPOSEE",
        "unite": "jours-personnes",
        "capacite": str(total),
        "source_capacite": source_capacite,
        "utilisee": str(total - reste),
        "restante": str(reste),
        "personnes_affectees": [],
    }
    resultat["retenus"] = [
        {
            "id": i,
            "validation": par_id[i]["validation"],
            "mandataire": conseil.ACTIONS_SENSIBLES.get(par_id[i]["validation"]),
            "statut": "VALIDATION_HUMAINE_REQUISE" if par_id[i]["validation"] else "PROPOSABLE",
        }
        for i in retenus
    ]
    resultat["non_retenus"] = non
    # Alternatives : retirer le dernier retenu libère de la capacité — quels non retenus y tiendraient ?
    alternatives = []
    if retenus:
        dernier = par_id[retenus[-1]]
        liberee = reste + dernier["effort"]
        for n in non:
            candidat = par_id[n["id"]]
            if n["raison"] == "CAPACITE_INSUFFISANTE" and candidat["effort"] <= liberee and len(alternatives) < 3:
                alternatives.append({"retirer": dernier["id"], "ajouter": candidat["id"],
                                     "capacite_restante_apres": str(liberee - candidat["effort"])})  # fmt: skip
    resultat["alternatives"] = alternatives
    return _signer(resultat)


def _signer(resultat: dict) -> dict:
    resultat["priorisation_id"] = hashlib.sha256(
        json.dumps(resultat, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()
    return resultat
