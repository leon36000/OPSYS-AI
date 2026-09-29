"""Préparation d'une intervention avant la cédule (M4.6, PLAN T4.10-b).

Module pur (stdlib et modules de M4 ; aucun import ``opsys``, aucune horloge, aucun aléa, aucun réseau ; un
test le vérifie par analyse du code). Il répond à une seule question : « cette intervention peut-elle être
planifiée ? », et il répond par un verdict qui NOMME CE QUI MANQUE, jamais par un « prêt » supposé.

Le verdict est une liste de volets, chacun dans l'un de trois états :

    ``ok``              le code a lu le fait à sa source et il est là ;
    ``manque``          le fait est attendu et absent : le volet dit quoi fournir ;
    ``non_verifiable``  M4 n'a pas encore de quoi le lire : le volet dit ce qui manque pour le vérifier.

Le verdict d'ensemble est ``pret`` SEULEMENT si tous les volets sont ``ok``. Un volet ``manque`` donne
``bloque`` ; sinon un volet ``non_verifiable`` donne ``non_verifiable``. « Non vérifiable » n'est jamais « ok »
(fail-closed, AGENTS.md) : un volet sans source de vérité ne se passe pas sous silence.

Les volets et leur source (DEFINITION-PRODUIT §7, M4.6 : « client confirmé, adresse validée, soumission
acceptée, matériel connu, équipe admissible, météo »)
    ``soumission``  le devis accepté qui a fait naître l'intervention (``devis_id`` de l'inscription) ;
    ``adresse``     la position CONFIRMÉE du chantier, lue comme la lit la cédule par tournées
                    (``lire_position``, injectée par l'adaptateur : la clé de chiffrement vit dans le socle) ;
    ``equipe``      non vérifiable : M4 ne tient pas encore le profil des équipes (équipes, compétences par
                    service, dépôt, quarts, durée par service) — PLAN T4.12 ;
    ``materiel``    non vérifiable : M4 ne lit pas encore ``m6.materiel_pret`` — PLAN T4.14 ;
    ``meteo``       non vérifiable : aucun fournisseur météo ni règle par service — PLAN T4.13.
Chacun des trois derniers deviendra un volet vérifié quand sa tâche livrera sa source : il suffit de remplacer sa
fonction dans ``_VOLETS``, la forme du verdict ne change pas.

Ce module ne promet aucune date ni aucun créneau : il ne parle pas du calendrier (frontière T3 du produit).
Il ne lit ni ne rend aucune coordonnée, aucun contact, aucun prix.
"""

from __future__ import annotations

from . import etats, verdicts

# « ok » et « pret » sont définis par la machine à états (`etats.py`), qui refuse un passage à planifiee sans eux :
# une seule source pour le mot que les deux modules doivent partager.
STATUT_OK = etats.STATUT_VOLET_OK
STATUT_MANQUE = "manque"
STATUT_NON_VERIFIABLE = "non_verifiable"

VERDICT_PRET = etats.VERDICT_PREPARATION_PRET
VERDICT_BLOQUE = "bloque"
VERDICT_NON_VERIFIABLE = "non_verifiable"

# Statuts d'avant le départ, où la question « prête à planifier ? » a un sens. `en_route` et après : l'équipe
# est déjà partie ; un état terminal : il n'y a plus rien à préparer.
STATUTS_PREPARABLES = ("a_planifier", "planifiee", "reportee")

__all__ = [
    "STATUT_OK",
    "STATUT_MANQUE",
    "STATUT_NON_VERIFIABLE",
    "VERDICT_PRET",
    "VERDICT_BLOQUE",
    "VERDICT_NON_VERIFIABLE",
    "STATUTS_PREPARABLES",
    "VOLETS",
    "verdict_des_volets",
    "evaluer",
]


def _volet(statut, manque=None, detail=None):
    return {"statut": statut, "manque": manque, "detail": detail}


def _volet_soumission(_registre, inscription, _lire_position):
    devis_id = inscription.get("devis_id")
    if isinstance(devis_id, str) and devis_id != "":
        return _volet(STATUT_OK, detail=f"devis accepté {devis_id}")
    return _volet(
        STATUT_MANQUE,
        manque="aucun devis accepté n'est rattaché à cette intervention (devis_id absent de l'inscription)",
    )


def _volet_adresse(registre_cible, inscription, lire_position):
    position, verdict = lire_position(registre_cible, inscription["lead_id"])
    if verdict is not None:
        return _volet(STATUT_MANQUE, manque=verdict["detail"], detail=verdict["code"])
    return _volet(STATUT_OK, detail=f"coordonnées confirmées (version {position['version']})")


def _volet_equipe(_registre, _inscription, _lire_position):
    return _volet(
        STATUT_NON_VERIFIABLE,
        manque=(
            "profil des équipes de l'entreprise (équipes, compétences par service, dépôt, quarts, durée par "
            "service) : M4 ne le tient pas encore, l'admissibilité d'une équipe ne se calcule pas"
        ),
    )


def _volet_materiel(_registre, _inscription, _lire_position):
    return _volet(
        STATUT_NON_VERIFIABLE,
        manque="état « matériel prêt » de M6 pour ce chantier : M4 ne le reçoit pas encore",
    )


def _volet_meteo(_registre, _inscription, _lire_position):
    return _volet(
        STATUT_NON_VERIFIABLE,
        manque="prévision météo et règles météo par service : aucun fournisseur ni seuil n'est configuré",
    )


# Ordre d'affichage : ce qui est vérifiable maintenant d'abord.
_VOLETS = (
    ("soumission", _volet_soumission),
    ("adresse", _volet_adresse),
    ("equipe", _volet_equipe),
    ("materiel", _volet_materiel),
    ("meteo", _volet_meteo),
)
VOLETS = tuple(nom for nom, _ in _VOLETS)


def verdict_des_volets(volets):
    """Verdict d'ensemble d'une liste de volets ``{nom: {statut, manque, detail}}`` : ``pret`` seulement si
    TOUS sont ``ok`` ; ``bloque`` si l'un manque ; sinon ``non_verifiable``. Fonction pure, sans repli : un
    ensemble vide n'est pas « prêt » (aucun volet n'a été vérifié)."""
    statuts = [volet["statut"] for volet in volets.values()]
    if not statuts:
        return VERDICT_NON_VERIFIABLE
    if STATUT_MANQUE in statuts:
        return VERDICT_BLOQUE
    if STATUT_NON_VERIFIABLE in statuts:
        return VERDICT_NON_VERIFIABLE
    return VERDICT_PRET


def _inscription(registre_cible, intervention_id):
    for maillon in registre_cible.lire():
        if maillon["type_entree"] == etats.TYPE_INSCRIPTION and maillon["intervention_id"] == intervention_id:
            return maillon
    return None


def evaluer(registre_cible, intervention_id, lire_position):
    """``(verdict, None)`` ou ``(None, refus)`` : la préparation de l'intervention, volet par volet.

    ``lire_position(registre, chantier_id)`` rend ``(position, None)`` ou ``(None, verdict)`` : la même lecture
    que la cédule par tournées (``outils.lire_localisation_confirmee``). Le chantier d'une intervention est
    identifié par son ``lead_id``, comme dans la cédule.

    Refus (``REJ-TRANSITION-ILLEGALE``, rien n'est écrit, la fonction n'écrit jamais) : intervention inconnue,
    ou statut hors de ``STATUTS_PREPARABLES``. Le verdict rendu ne porte ni coordonnée, ni contact, ni prix.
    """
    statut = etats.statut_courant(registre_cible, intervention_id)
    if statut is None:
        return None, verdicts.construire_verdict("REJ-TRANSITION-ILLEGALE", detail="intervention inexistante")
    if statut not in STATUTS_PREPARABLES:
        return None, verdicts.construire_verdict(
            "REJ-TRANSITION-ILLEGALE", statut=statut,
            detail=f"préparation sans objet : l'intervention est {statut} (attendu {', '.join(STATUTS_PREPARABLES)})",
        )
    inscription = _inscription(registre_cible, intervention_id)
    volets = {nom: fonction(registre_cible, inscription, lire_position) for nom, fonction in _VOLETS}
    statut_global = verdict_des_volets(volets)
    verdict = {
        "intervention_id": intervention_id,
        "statut_intervention": statut,
        "statut": statut_global,
        "pret": statut_global == VERDICT_PRET,
        "volets": volets,
        "a_fournir": [
            {"volet": nom, "statut": volet["statut"], "manque": volet["manque"]}
            for nom, volet in volets.items() if volet["statut"] != STATUT_OK
        ],
    }
    verdict["empreinte"] = etats.empreinte_preparation(verdict)
    return verdict, None
