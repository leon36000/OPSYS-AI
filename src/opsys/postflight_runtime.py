"""Dépôt hôte privé lié au profil courant, utilisant le registre candidat canonique M10.

L'origine vient de la route authentifiée et de la base, jamais d'un argument de modèle.
Le jeton hôte atteste un résultat observé : aucun outil source n'est exécuté ici et aucune
vérité métier n'est consolidée. Le reçu n'est émis qu'après commit de toute l'unité.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select

from . import admission_agents, stockage
from .departements import Departement
from .outils import Outil, valider_arguments
from .stockage.schema import AGENTS_CONFIGURABLES

NOM = "opsys_runtime_deposer_faits"


def _outil(departements: Mapping[str, Departement]) -> Outil:
    memoire = departements.get("m10-memoire")
    if memoire is None:
        raise ValueError("département mémoire indisponible")
    for outil in memoire.charger_outils():
        if outil.nom == "m10_deposer_faits_candidats":
            return outil
    raise ValueError("dépôt canonique M10 indisponible")


def schema(departements: Mapping[str, Departement]) -> dict[str, Any]:
    """Étend le contrat canonique, en retirant l'origine contrôlée exclusivement par l'hôte."""
    resultat = copy.deepcopy(_outil(departements).parametres)
    resultat["properties"].pop("departement")
    resultat["properties"]["revision_profil"] = {"type": "integer", "minimum": 1}
    resultat["properties"]["faits"].update(minItems=1, maxItems=20)
    resultat["required"] = ["affaire_id", "faits", "horodatage", "revision_profil"]
    resultat["additionalProperties"] = False
    return resultat


def deposer(
    departements: Mapping[str, Departement], cnx_factory: Any, profil_id: str, arguments: Mapping[str, Any]
) -> dict[str, Any]:
    """Revalide les outils source et écrit tous les faits dans une seule transaction durable."""
    if valider_arguments(schema(departements), arguments):
        raise ValueError("arguments POSTFLIGHT invalides")
    revision = arguments["revision_profil"]
    if type(revision) is not int or revision < 1:
        raise ValueError("révision POSTFLIGHT invalide")
    # Freeze the input handed to the owner; later caller mutations cannot change the ACK identity.
    affaire_id = arguments["affaire_id"]
    faits = copy.deepcopy(arguments["faits"])
    horodatage = arguments["horodatage"]
    with cnx_factory() as cnx:
        def verifier_base() -> None:
            if stockage.connexion_courante() is not cnx or cnx.engine.url != stockage.moteur().url:
                raise ValueError("base durable POSTFLIGHT non canonique")
        verifier_base()
        profil = cnx.execute(select(AGENTS_CONFIGURABLES).where(
            AGENTS_CONFIGURABLES.c.id == profil_id
        ).with_for_update()).mappings().fetchone()
        if profil is None:
            raise admission_agents.AdmissionRefusee("profil POSTFLIGHT inconnu")
        departement_id = profil["departement"]
        departement = departements.get(departement_id)
        if departement is None:
            raise admission_agents.AdmissionRefusee("département POSTFLIGHT indisponible")
        def verifier_sources() -> None:
            for fait in faits:
                admission_agents.verifier_outil_runtime(
                    cnx, profil_id, departements, f"opsys_{departement.prefixe_outils}__{fait['outil']}",
                    revision, verrouiller=True,
                )
        verifier_sources()
        # Canonical M10 owner already uses MaillonsDurables and the current transaction.
        resultat = _outil(departements).fonction(
            affaire_id=affaire_id, departement=departement_id, faits=faits, horodatage=horodatage,
        )
        if not isinstance(resultat, Mapping) or resultat.get("accepte") is not True:
            raise ValueError("dépôt M10 refusé")
        compteurs = resultat.get("resultat")
        if (not isinstance(compteurs, Mapping) or type(compteurs.get("ecrits")) is not int
                or type(compteurs.get("deja_deposes")) is not int
                or compteurs["ecrits"] < 0 or compteurs["deja_deposes"] < 0
                or compteurs["ecrits"] + compteurs["deja_deposes"] != len(faits)):
            raise ValueError("compteurs M10 non conformes")
        verifier_base()
        verifier_sources()
        ack = {
            "accepte": True,
            "source": {"profil_id": profil_id, "revision": revision,
                       "departement": departement_id, "engine_id": "opsys"},
            "affaire_id": affaire_id,
            "cles": [fait["cle"] for fait in faits],
            "resultat": dict(compteurs),
        }
    return {"ok": True, "resultat": ack}
