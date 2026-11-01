"""La sortie du sas : publier une publication APPROUVÉE et PLANIFIÉE par l'adaptateur de son réseau.

Ce n'est PAS un outil d'agent et aucun outil ne l'appelle. Il est écrit pour l'exécuteur qui tournera hors transaction
(le jeton d'accès sort du coffre pendant l'appel, ce que le coffre interdit dans une transaction métier). Dans cette
tranche, il n'est exercé qu'avec les doubles de test : AUCUN message n'a jamais été publié par ce code sur un réseau
réel.

Le point de sortie REVÉRIFIE tout, comme l'exige la recherche R4 (§7, principe 1) : le journal est intègre, la
publication est
planifiée, l'approbation porte l'empreinte du contenu actuel (recalculée) et un niveau suffisant, l'heure approuvée est
arrivée et n'est pas trop dépassée, la fenêtre de publication et le quota tiennent encore, les contrôles de contenu
passent
toujours. Un doute écarte la publication (refus sans écriture si on peut réessayer plus tard, `echec` si c'est
définitif).

Idempotence et pannes : AVANT d'appeler le réseau on écrit `tentative`. Si une tentative n'a ni `publiee` ni `echec`
connu (processus tué, délai dépassé après l'envoi), l'état est `incertain` : le sas demande à l'adaptateur de
RETROUVER la
publication par son contenu exact avant de renvoyer quoi que ce soit. Il ne republie jamais à l'aveugle. Le détail d'un
échec est masqué des secrets (jetons du coffre) et tronqué avant d'entrer au journal.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from opsys.secrets_coffre import masquage

from .. import journal_chaine
from . import etats, garde_fous, modele, service
from .etats import EtatPublication
from .politique import PolitiqueSas
from .reseaux import AdaptateurReseau, ErreurReseau, FournisseurSecret, RequetePublication, ResultatPublication

REJ_PAS_ENCORE = "REJ-SOCIAL-PAS-ENCORE"
REJ_NON_APPROUVEE = "REJ-SOCIAL-NON-APPROUVEE"
REJ_ECHEANCE_DEPASSEE = "REJ-SOCIAL-ECHEANCE-DEPASSEE"
REJ_TENTATIVES_EPUISEES = "REJ-SOCIAL-TENTATIVES-EPUISEES"
REJ_ERREUR_ADAPTATEUR = "REJ-SOCIAL-ERREUR-ADAPTATEUR"
REJ_REPRISE = "REJ-SOCIAL-REPRISE-IMPOSSIBLE"
DETAIL_MAX = 300


def _masque(texte: str) -> str:
    return masquage.masquer_texte(texte)[:DETAIL_MAX]


def requete_de(courant: EtatPublication, publication: modele.Publication) -> RequetePublication:
    return RequetePublication(
        reseau=publication.reseau,
        compte=publication.compte,
        texte=publication.texte,
        titre=publication.titre,
        medias=tuple(
            {
                "reference": m.reference,
                "type_media": m.type_media,
                "format": m.format,
                "sha256": m.sha256,
                "alt": m.alt,
            }
            for m in publication.medias
        ),
        cle_idempotence=courant.cle_idempotence,
        empreinte=courant.empreinte,
        divulgation={
            "texte_ia": publication.divulgation.texte_ia,
            "media_synthetique_realiste": publication.divulgation.media_synthetique_realiste,
            "contenu_commercial": publication.divulgation.contenu_commercial,
        },
        type_publication=publication.type_publication,
        budget=None
        if publication.budget is None
        else {
            "montant_cents": publication.budget.montant_cents,
            "plafond_quotidien_cents": publication.budget.plafond_quotidien_cents,
            "duree_jours": publication.budget.duree_jours,
        },
        options=dict(publication.options),
    )


def _ecrire_echec(
    journal: Any,
    publication_id: str,
    code: str,
    detail: str,
    *,
    transitoire: bool,
    incertain: bool,
    horodatage: str,
) -> None:
    journal_chaine.ajouter(
        journal,
        etats.MAILLON_ECHEC,
        {
            "publication_id": publication_id,
            "code": code,
            "detail": _masque(detail),
            "transitoire": transitoire,
            "resultat_incertain": incertain,
        },
        horodatage,
    )


def _refus(code: str, detail: str) -> dict[str, Any]:
    return {"accepte": False, "publie": False, "refus": [{"code": code, "chemin": "$", "detail": detail}]}


def _ecrire_publiee(
    journal: Any,
    courant: EtatPublication,
    resultat: ResultatPublication,
    tentative: int,
    horodatage: str,
    *,
    retrouvee: bool,
) -> dict[str, Any]:
    journal_chaine.ajouter(
        journal,
        etats.MAILLON_PUBLIEE,
        {
            "publication_id": courant.publication_id,
            "id_externe": resultat.id_externe,
            "url": resultat.url,
            "publie_le": horodatage,
            "publie_le_externe": resultat.publie_le,
            "tentative": tentative,
            "retrouvee": retrouvee,
        },
        horodatage,
    )
    return {
        "accepte": True,
        "publie": True,
        "publication_id": courant.publication_id,
        "id_externe": resultat.id_externe,
        "retrouvee": retrouvee,
    }


def executer(
    journal: Any,
    publication_id: str,
    adaptateurs: Mapping[str, AdaptateurReseau],
    fournisseur_secret: FournisseurSecret,
    politique: PolitiqueSas,
    maintenant: datetime,
) -> dict[str, Any]:
    """Une tentative de publication. Rend `{accepte, publie, ...}` ou `{accepte: False, publie: False, refus}`.

    `fournisseur_secret` donne le jeton d'accès du compte, du coffre, le temps d'un appel : il n'est appelé qu'au moment
    d'écrire sur le réseau (jamais pour un refus), enregistré au masquage pendant l'appel, et n'entre jamais au
    journal."""
    horodatage = modele.en_instant(maintenant)
    tous, refus = service.charger(journal)
    if refus is not None:
        return {**refus, "publie": False}
    courant = tous.get(publication_id)
    if courant is None:
        return {**service._refus(service.REJ_PUBLICATION_INCONNUE, "$.publication_id", publication_id), "publie": False}
    if courant.etat != etats.PLANIFIE:
        return _refus(service.REJ_ETAT, f"publication {courant.etat} : seule une publication planifiée sort")
    publication, refus_pub = service._publication(courant)
    if refus_pub is not None:
        return {**refus_pub, "publie": False}
    approbation = courant.approbation
    if (
        approbation is None
        or approbation["empreinte"] != courant.empreinte
        or approbation["approbation"].get("role") != service.ROLE_DECIDEUR
        or approbation["niveau"] != garde_fous.niveau_requis(publication)
    ):
        return _refus(REJ_NON_APPROUVEE, "aucune approbation valable pour le contenu actuel au niveau exigé")
    adaptateur = service._adaptateur_de(publication.reseau, adaptateurs)
    if isinstance(adaptateur, dict):
        return {**adaptateur, "publie": False}
    prevu = modele.instant(publication.planifie_le)
    if maintenant < prevu:
        return _refus(REJ_PAS_ENCORE, f"prévue pour {publication.planifie_le}")
    if maintenant > prevu + timedelta(seconds=politique.tolerance_retard_s):
        _ecrire_echec(
            journal,
            publication_id,
            REJ_ECHEANCE_DEPASSEE,
            f"{politique.tolerance_retard_s} s de retard tolérés sur {publication.planifie_le}",
            transitoire=False,
            incertain=courant.incertain,
            horodatage=horodatage,
        )
        return _refus(REJ_ECHEANCE_DEPASSEE, "l'heure approuvée est trop dépassée pour publier")
    if not politique.fenetre.contient(maintenant):
        return _refus(garde_fous.REJ_HORS_FENETRE, "hors de la fenêtre de publication : réessayer dans la fenêtre")
    problemes = garde_fous.controler_contenu(publication, adaptateur, politique)
    if problemes:
        _ecrire_echec(
            journal,
            publication_id,
            problemes[0]["code"],
            problemes[0]["detail"],
            transitoire=False,
            incertain=courant.incertain,
            horodatage=horodatage,
        )
        return {"accepte": False, "publie": False, "refus": problemes}
    quota = garde_fous.quota_applicable(adaptateur.LIMITES, politique)
    autres = [
        h
        for h in service.horaires_du_compte(tous, publication.reseau, publication.compte, exclure=publication_id)
        if h <= maintenant
    ]
    if not garde_fous.quota_respecte(autres, maintenant, quota):
        return _refus(garde_fous.REJ_QUOTA, f"plus de {quota} publications sur 24 h glissantes : réessayer plus tard")
    requete = requete_de(courant, publication)
    if courant.incertain:
        try:
            with fournisseur_secret() as jeton:
                masquage.enregistrer(jeton)
                try:
                    retrouvee = adaptateur.retrouver(requete, courant.derniere_tentative_le or horodatage, jeton)
                finally:
                    masquage.oublier(jeton)
        except ErreurReseau as exc:
            return _refus(
                exc.code, "impossible de vérifier si la tentative précédente est passée : aucune nouvelle tentative"
            )
        if retrouvee is not None:
            return _ecrire_publiee(journal, courant, retrouvee, courant.tentatives, horodatage, retrouvee=True)
    if courant.tentatives >= politique.tentatives_max:
        _ecrire_echec(
            journal,
            publication_id,
            REJ_TENTATIVES_EPUISEES,
            f"{courant.tentatives} tentatives",
            transitoire=False,
            incertain=False,
            horodatage=horodatage,
        )
        return _refus(REJ_TENTATIVES_EPUISEES, "nombre maximal de tentatives atteint")
    journal_chaine.ajouter(
        journal,
        etats.MAILLON_TENTATIVE,
        {
            "publication_id": publication_id,
            "tentative": courant.tentatives + 1,
            "cle_idempotence": courant.cle_idempotence,
        },
        horodatage,
    )
    with fournisseur_secret() as jeton:
        masquage.enregistrer(jeton)
        try:
            resultat = adaptateur.publier(requete, jeton)
        except ErreurReseau as exc:
            # Le détail est masqué ICI, jeton encore actif : hors du bloc, plus rien ne le reconnaîtrait.
            detail = _masque(exc.detail)
            _ecrire_echec(
                journal,
                publication_id,
                exc.code,
                detail,
                transitoire=exc.transitoire,
                incertain=exc.incertain,
                horodatage=horodatage,
            )
            return {
                "accepte": False,
                "publie": False,
                "refus": [{"code": exc.code, "chemin": "$", "detail": detail}],
                "transitoire": exc.transitoire,
                "resultat_incertain": exc.incertain,
            }
        except Exception as exc:  # noqa: BLE001 — l'adaptateur n'est pas de confiance : son message pourrait citer un secret
            _ecrire_echec(
                journal,
                publication_id,
                REJ_ERREUR_ADAPTATEUR,
                f"exception {type(exc).__name__}",
                transitoire=True,
                incertain=True,
                horodatage=horodatage,
            )
            return {
                "accepte": False,
                "publie": False,
                "refus": [{"code": REJ_ERREUR_ADAPTATEUR, "chemin": "$", "detail": type(exc).__name__}],
                "transitoire": True,
                "resultat_incertain": True,
            }
        finally:
            masquage.oublier(jeton)
    return _ecrire_publiee(journal, courant, resultat, courant.tentatives + 1, horodatage, retrouvee=False)


def reprendre(journal: Any, publication_id: str, politique: PolitiqueSas, horodatage: str) -> dict[str, Any]:
    """echec -> planifie, SEULEMENT pour un échec transitoire et tant que les tentatives ne sont pas épuisées. L'heure
    approuvée reste la même (la tolérance de retard s'applique)."""
    tous, refus = service.charger(journal)
    if refus is not None:
        return refus
    courant = tous.get(publication_id)
    if courant is None:
        return service._refus(service.REJ_PUBLICATION_INCONNUE, "$.publication_id", publication_id)
    if courant.etat != etats.ECHEC or not (courant.derniere_erreur or {}).get("transitoire"):
        return service._refus(REJ_REPRISE, "$.publication_id", "seul un échec transitoire se reprend")
    # Une dernière reprise reste permise quand le résultat est INCERTAIN, même tentatives épuisées : `executer` demande
    # alors à l'adaptateur de retrouver la publication avant de conclure à l'échec (jamais un « échec » sur un
    # message sorti).
    if courant.tentatives >= politique.tentatives_max and not courant.incertain:
        return service._refus(REJ_REPRISE, "$.publication_id", "tentatives épuisées")
    journal_chaine.ajouter(journal, etats.MAILLON_REPRISE, {"publication_id": publication_id}, horodatage)
    return {"accepte": True, "publication_id": publication_id, "etat": etats.PLANIFIE}
