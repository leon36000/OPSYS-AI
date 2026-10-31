"""Évaluation d'un critère mesurable sur les captures des propriétaires (playbooks, plans, expériences).

Module pur. Un critère lit la DERNIÈRE capture complète et non contradictoire d'une lecture ; une lecture absente,
refusée, partielle ou contradictoire donne INCONNU, jamais un succès ni un échec supposé. Une cible absente donne
INCONNU. Un critère ``manuel`` n'est jamais mesuré : il reste à juger par la personne. Les valeurs se comparent en
texte exact ou en Decimal ; rien n'est arrondi ni calculé ici.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation

from . import capture_strategique as cs

OPERATEURS = frozenset({"==", "!=", ">=", "<=", "aucun", "manuel"})


def texte(valeur: object) -> str:
    if isinstance(valeur, bool):
        return "true" if valeur else "false"
    return valeur if isinstance(valeur, str) else json.dumps(valeur)


def evaluer(critere: Mapping, captures: Sequence[Mapping], en_conflit: set) -> dict:
    sortie = {
        "id": critere["id"],
        "libelle": critere["libelle"],
        "operateur": critere["operateur"],
        "cible": critere["cible"],
    }
    if critere["operateur"] == "manuel":
        return sortie | {"statut": "A_JUGER_PAR_LA_PERSONNE", "raison": "critère non mesurable par un producteur"}
    lues = [c for c in captures if c["lecture_id"] == critere["lecture"]]
    utilisables = [
        c
        for c in lues
        if c["verdict"] == "ACCEPTEE" and c["complete"] and (c["lecture_id"], c["arguments_sha256"]) not in en_conflit
    ]
    if not utilisables or lues[-1] is not utilisables[-1]:
        return sortie | {"statut": "INCONNU", "raison": "lecture absente, refusée, partielle ou contradictoire"}
    capture = utilisables[-1]
    valeurs = [v for page in capture["pages"] for v in cs.extraire(page, critere["chemin"])]
    sortie["source"] = {"capture": capture["index"], "hash": capture["hash_maillon"], "recu_a": capture["recu_a"]}
    operateur = critere["operateur"]
    if operateur == "aucun":
        return sortie | {"statut": "SATISFAIT" if not valeurs else "NON_SATISFAIT", "valeurs": len(valeurs)}
    if critere["cible"] is None:
        return sortie | {"statut": "INCONNU", "raison": "cible non définie : à lier par la personne"}
    if not valeurs:
        return sortie | {"statut": "INCONNU", "raison": "aucune valeur lue à ce chemin"}
    textes = [texte(v) for v in valeurs]
    if operateur in ("==", "!="):
        accepte = [(t == critere["cible"]) == (operateur == "==") for t in textes]
    else:
        try:
            cible = Decimal(critere["cible"])
            accepte = [(Decimal(t) >= cible) if operateur == ">=" else (Decimal(t) <= cible) for t in textes]
        except InvalidOperation:
            return sortie | {"statut": "INCONNU", "raison": "valeur non numérique face à une cible numérique"}
    return sortie | {"statut": "SATISFAIT" if all(accepte) else "NON_SATISFAIT", "valeurs": len(textes)}
