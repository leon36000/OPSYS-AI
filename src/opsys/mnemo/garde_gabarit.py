"""Garde de non-régression d'une leçon contre le gabarit d'évaluation COMMUN (`docs/architecture/EVALUATION.md`).

Une leçon est du texte que l'agent d'un département lira. Avant qu'une personne puisse la promouvoir, on mesure ce que
ce texte, AJOUTÉ à chaque réponse de référence du corpus du département visé, fait aux contrôles universels du gabarit
: un chiffre inventé, une action présentée comme faite, un motif interdit, une autorité contournée feraient échouer
des cas qui réussissaient. On compare le rapport « avec la leçon » au rapport de référence (`rapport.comparer`) :
aucune régression, aucun cas bloquant échoué en plus.

Limite DITE : le répondant est un double déterministe (la réponse de référence plus le texte de la leçon), jamais un
modèle. Cela prouve que le TEXTE de la leçon est inoffensif pour les contrôles du gabarit ; cela ne prouve pas qu'un
modèle réel se comportera mieux, ni même pareil, avec elle. La mesure sur un vrai modèle (répondant « passerelle »)
reste à faire.
"""

from __future__ import annotations

import dataclasses
import hashlib
from collections.abc import Mapping
from typing import Any

from ..evaluation import executeur, rapport
from ..evaluation.repondants import RepondantReference, Reponse, RequeteCas


class RepondantAvecLecon(RepondantReference):
    """La réponse de référence du cas, suivie du texte de la leçon."""

    nom = "reference+lecon"

    def __init__(self, corpus: Any, texte: str) -> None:
        super().__init__(corpus)
        self._texte = texte

    def identite(self) -> dict[str, Any]:
        base = super().identite()
        return {**base, "nom": self.nom, "lecon_sha256": hashlib.sha256(self._texte.encode("utf-8")).hexdigest()}

    def repondre(self, requete: RequeteCas) -> Reponse:
        reponse = super().repondre(requete)
        return dataclasses.replace(reponse, texte=f"{reponse.texte} {self._texte}")


def empreinte_garde(
    departements: Mapping[str, Any], cible: str, fichiers_supplementaires: tuple[bytes, ...] = ()
) -> str:
    """Empreinte du corpus de garde COURANT : le corpus du gabarit du département visé (et d'éventuels fichiers de garde
    en plus). Une évaluation faite sur un autre corpus ne vaut plus pour promouvoir."""
    entrees = executeur.charger_corpus_departements(departements, [cible])
    h = hashlib.sha256()
    for e in entrees:
        h.update(e["sha256"].encode())
    for octets in fichiers_supplementaires:
        h.update(hashlib.sha256(octets).hexdigest().encode())
    return h.hexdigest()


def comparer_au_gabarit(departements: Mapping[str, Any], cible: str, texte: str) -> dict[str, Any]:
    """Rapport avec la leçon contre rapport sans elle, pour le département `cible` : régressions nommées par cas."""
    entrees = executeur.charger_corpus_departements(departements, [cible])
    corpus = [e["corpus"] for e in entrees]
    base = executeur.evaluer(entrees, RepondantReference(corpus), departements)
    avec = executeur.evaluer(entrees, RepondantAvecLecon(corpus, texte), departements)
    comp = rapport.comparer(base, avec)
    dep_base, dep_avec = base["departements"][cible], avec["departements"][cible]
    return {
        "departement": cible,
        "effectif": dep_base["effectif"],
        "score_sans_lecon": dep_base["score"],
        "score_avec_lecon": dep_avec["score"],
        "qualifie_sans_lecon": dep_base["qualifie"],
        "qualifie_avec_lecon": dep_avec["qualifie"],
        "regressions": [
            {
                "cas": r["cas"],
                "categorie": r["categorie"],
                "gravite": r["gravite"],
                "ecarts": [e.get("controle") for e in r["ecarts"]],
            }
            for r in comp["regressions"]
        ],
        "bloquants_nouveaux": [r["cas"] for r in comp["regressions_bloquantes"]],
        "repondant": "reference+lecon (double déterministe, aucun modèle réel)",
    }
