"""Les gestes de sortie du flux WordPress : transmettre un brouillon, publier avec un jeton, réconcilier une réponse
perdue.

Comme `sas_social.executeur`, ce n'est PAS un outil d'agent : un exécuteur hors transaction (le secret sort du
coffre le temps
d'un appel) les appelle avec un `ClientWordPress`. Dans cette tranche ils ne sont exercés qu'avec un transport de test.

Publication : (1) l'approbation humaine consignée est relue et vérifiée ; (2) l'état du site est relu et son
empreinte doit
être celle qui a été approuvée (sinon la revue est rouverte, l'approbation tombe) ; (3) le jeton est CONSIGNÉ comme
émis avant
d'être envoyé (une approbation sert une fois, même si la réponse se perd) ; (4) le site publie ou refuse ; (5) le
résultat est
consigné. Une réponse perdue se réconcilie en relisant le site (`reconcilier`), jamais en renvoyant un jeton.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..sas_social.modele import en_instant
from . import flux
from .client import ClientWordPress

REJ_NON_CONFIRMEE = "REJ-WP-PUBLICATION-NON-CONFIRMEE"
REJ_TRANSPORT = "REJ-WP-TRANSPORT"


def _premier(resultat: dict[str, Any]) -> tuple[str, str]:
    refus = resultat["refus"][0]
    return refus["code"], refus["detail"]


def transmettre_brouillon(
    journal: Any, publication_id: str, client: ClientWordPress, maintenant: datetime
) -> dict[str, Any]:
    """Crée (ou met à jour) le brouillon sur le site, statut `draft`/`pending` seulement ; consigne l'empreinte du
    site.
    """
    horodatage = en_instant(maintenant)
    tous, refus = flux.charger(journal)
    if refus is not None:
        return refus
    courant = tous.get(publication_id)
    if courant is None:
        return {
            "accepte": False,
            "refus": [{"code": flux.REJ_INCONNUE, "chemin": "$.publication_id", "detail": publication_id}],
        }
    if courant.etat not in (flux.BROUILLON, flux.EN_REVUE, flux.ECHEC):
        return {
            "accepte": False,
            "refus": [{"code": flux.REJ_ETAT, "chemin": "$", "detail": f"publication {courant.etat}"}],
        }
    article = courant.article
    if courant.post_id is None:
        resultat = client.creer_brouillon(
            article["type"],
            article["titre"],
            article["contenu"],
            article["extrait"],
            article["slug"],
            courant.statut_cible,
            courant.cle_idempotence,
        )
    else:
        resultat = client.maj_brouillon(
            courant.post_id,
            {
                "titre": article["titre"],
                "contenu": article["contenu"],
                "extrait": article["extrait"],
                "slug": article["slug"],
                "statut": courant.statut_cible,
            },
        )
    if not resultat["accepte"]:
        code, detail = _premier(resultat)
        flux.consigner_echec_transmission(journal, publication_id, code, detail, horodatage)
        return resultat
    donnees = resultat["donnees"]
    consigne = flux.consigner_transmission(
        journal, publication_id, donnees["post_id"], donnees["empreinte"], horodatage
    )
    if not consigne["accepte"]:
        return consigne
    return {
        "accepte": True,
        "publication_id": publication_id,
        "etat": flux.EN_REVUE,
        "post_id": donnees["post_id"],
        "empreinte_serveur": donnees["empreinte"],
        "divergence": consigne["divergence"],
    }


def publier(journal: Any, publication_id: str, client: ClientWordPress, maintenant: datetime) -> dict[str, Any]:
    horodatage = en_instant(maintenant)
    approbation = flux.approbation_verifiee(journal, publication_id, maintenant)
    if isinstance(approbation, dict):
        return approbation
    lu = client.etat(approbation.post_id)
    if not lu["accepte"]:
        return lu
    if lu["donnees"]["empreinte"] != approbation.empreinte or not lu["donnees"]["gere"]:
        # Le brouillon a changé sur le site depuis l'approbation : la revue est rouverte, l'approbation tombe.
        flux.consigner_transmission(
            journal, publication_id, approbation.post_id, lu["donnees"]["empreinte"], horodatage
        )
        return {
            "accepte": False,
            "refus": [
                {
                    "code": flux.REJ_DIVERGENCE,
                    "chemin": "$",
                    "detail": (
                        "le contenu du site n'est plus celui qui a été approuvé : "
                        "nouvelle revue et nouvelle approbation requises"
                    ),
                }
            ],
        }
    flux.consigner_jeton_emis(journal, approbation, horodatage)
    resultat = client.publier(approbation)
    if resultat["accepte"]:
        donnees = resultat["donnees"]
        flux.consigner_publication(journal, publication_id, donnees["statut"], donnees["lien_public"], horodatage)
        return {
            "accepte": True,
            "publication_id": publication_id,
            "etat": flux.PUBLIE,
            "statut_site": donnees["statut"],
        }
    code, detail = _premier(resultat)
    if code != REJ_TRANSPORT:
        flux.consigner_echec(journal, publication_id, code, detail, horodatage)
    return resultat


def reconcilier(journal: Any, publication_id: str, client: ClientWordPress, maintenant: datetime) -> dict[str, Any]:
    """Après une réponse perdue (jeton émis, ni publication ni échec consignés) : relit le site. Publié avec l'empreinte
    approuvée -> consigné publié ; sinon -> échec consigné (l'approbation est brûlée, la direction en donne une
    autre)."""
    horodatage = en_instant(maintenant)
    tous, refus = flux.charger(journal)
    if refus is not None:
        return refus
    courant = tous.get(publication_id)
    if courant is None or courant.etat != flux.APPROUVE or not courant.jeton_emis or courant.approbation is None:
        return {"accepte": False, "refus": [{"code": flux.REJ_ETAT, "chemin": "$", "detail": "rien à réconcilier"}]}
    lu = client.etat(courant.post_id)
    if not lu["accepte"]:
        return lu
    donnees = lu["donnees"]
    # WordPress complète l'adresse (slug) à la publication : l'empreinte « vivante » change, pas l'empreinte vérifiée à
    # la sortie, que le plugin mémorise (`empreinte_publiee`) et que l'approbation doit retrouver.
    if donnees["statut"] in ("publish", "future") and donnees["empreinte_publiee"] == courant.approbation["empreinte"]:
        flux.consigner_publication(journal, publication_id, donnees["statut"], donnees["lien_public"], horodatage)
        return {"accepte": True, "publication_id": publication_id, "etat": flux.PUBLIE, "reconcilie": True}
    flux.consigner_echec(
        journal, publication_id, REJ_NON_CONFIRMEE, f"statut du site : {donnees['statut']}", horodatage
    )
    return {
        "accepte": False,
        "refus": [
            {"code": REJ_NON_CONFIRMEE, "chemin": "$", "detail": "le site n'a pas publié ; l'approbation est brûlée"}
        ],
    }
