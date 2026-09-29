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
    ``equipe``      une équipe ADMISSIBLE, calculée par le code (``admissibilite.py``) à partir du profil des
                    équipes de l'entreprise (PLAN T4.12) : elle détient toutes les compétences du service et a un
                    quart assez long pour sa durée. Sans profil, ou sans durée pour ce service : ``manque``, et le
                    volet dit quoi déclarer. Un lead v1 (``type_travaux``) n'a pas de service : ``non_verifiable`` ;
    ``materiel``    la charge ``m6.materiel_pret`` la plus récente du devis, reçue par le bus et rangée par M4
                    (``materiel.py``, PLAN T4.14-b) : ``ok`` seulement si M6 dit ``pret`` ET que la réservation est
                    active ET qu'aucune ligne ne manque ; sinon ``manque`` (``partiel`` ou ``a_commander``, avec les
                    lignes manquantes) ; aucune charge reçue : ``non_verifiable`` (M6 n'a rien vérifié) ;
    ``meteo``       les RÈGLES météo du service, lues dans le profil de l'entreprise (``opsys.meteo``, PLAN T4.13) :
                    ``ok`` seulement si chaque risque du service est jugé (un seuil) ou déclaré sans objet ; sinon
                    ``manque`` (« seuil à configurer », avec les risques sans décision et où les déclarer). La
                    préparation n'a pas de date : elle certifie que la météo SE JUGE (les règles existent), pas qu'il
                    fera beau. La prévision d'un créneau se juge quand la cédule en propose un
                    (``m4_verifier_meteo_creneau``, ``meteo_creneaux.py``). Un lead v1 n'a pas de service :
                    ``non_verifiable``.
Sans lecture du profil météo (``lire_meteo`` absente), le volet reste ``non_verifiable`` : la forme du verdict ne change
pas, et aucun verdict n'est ``pret`` faute de lecture (la porte ``a_planifier -> planifiee`` reste fermée).

Ce module ne promet aucune date ni aucun créneau : il ne parle pas du calendrier (frontière T3 du produit).
Il ne lit ni ne rend aucune coordonnée, aucun contact, aucun prix.
"""

from __future__ import annotations

from . import admissibilite, etats, materiel, meteo, verdicts

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


def _volet_soumission(_registre, inscription, _lire_position, _lire_equipes, _lire_meteo):
    devis_id = inscription.get("devis_id")
    if isinstance(devis_id, str) and devis_id != "":
        return _volet(STATUT_OK, detail=f"devis accepté {devis_id}")
    return _volet(
        STATUT_MANQUE,
        manque="aucun devis accepté n'est rattaché à cette intervention (devis_id absent de l'inscription)",
    )


def _volet_adresse(registre_cible, inscription, lire_position, _lire_equipes, _lire_meteo):
    position, verdict = lire_position(registre_cible, inscription["lead_id"])
    if verdict is not None:
        return _volet(STATUT_MANQUE, manque=verdict["detail"], detail=verdict["code"])
    return _volet(STATUT_OK, detail=f"coordonnées confirmées (version {position['version']})")


def _volet_equipe(_registre, inscription, _lire_position, lire_equipes, _lire_meteo):
    if lire_equipes is None:
        return _volet(
            STATUT_NON_VERIFIABLE,
            manque=(
                "lecture du profil des équipes : aucune n'a été fournie à l'évaluation, l'admissibilité ne se "
                "calcule pas"
            ),
        )
    profil, verdict = lire_equipes()
    if verdict is not None:
        return _volet(STATUT_MANQUE, manque=verdict["detail"], detail=verdict["code"])
    cle_travaux, service = etats.travaux_de(inscription)
    if cle_travaux != etats.CLE_SERVICE:
        return _volet(
            STATUT_NON_VERIFIABLE,
            manque=(
                f"intervention issue d'un lead v1 (type_travaux {service!r}) : le profil des équipes est par service, "
                "l'admissibilité d'une équipe ne se calcule pas pour un type de travaux"
            ),
        )
    resultat, verdict = admissibilite.equipes_admissibles(profil, service)
    if verdict is not None:
        return _volet(STATUT_MANQUE, manque=verdict["detail"], detail=verdict["code"])
    if not resultat["admissibles"]:
        raisons = " ; ".join(f"{ligne['equipe']} : {ligne['detail']}" for ligne in resultat["ecartees"])
        return _volet(
            STATUT_MANQUE,
            manque=(
                f"aucune équipe admissible pour le service {service!r} ({raisons}) : ajuster les équipes, leurs "
                "compétences ou leurs quarts dans le profil (`opsys equipes declarer`)"
            ),
        )
    return _volet(STATUT_OK, detail=f"équipes admissibles pour {service} : {', '.join(resultat['admissibles'])}")


def _volet_materiel(registre_cible, inscription, _lire_position, _lire_equipes, _lire_meteo):
    devis_id = inscription.get("devis_id")
    if not isinstance(devis_id, str) or devis_id == "":
        return _volet(
            STATUT_NON_VERIFIABLE,
            manque=(
                "matériel : M6 réserve par devis accepté et cette intervention n'en a pas (devis_id absent de "
                "l'inscription) : rien à lire"
            ),
        )
    charge = materiel.charge_retenue(registre_cible, devis_id)
    if charge is None:
        return _volet(
            STATUT_NON_VERIFIABLE,
            manque=(
                f"matériel : M4 n'a reçu aucun état « matériel prêt » (m6.materiel_pret) pour le devis {devis_id} ; "
                "M6 ne dit rien d'un prévu vide, et un matériel que personne n'a vérifié n'est pas prêt"
            ),
        )
    etat = materiel.etat_du_materiel(charge)
    revision = charge["revision"]
    if etat == materiel.ETAT_PRET:
        return _volet(STATUT_OK, detail=f"matériel prêt et réservé (M6, révision {revision})")
    lignes = materiel.lignes_manquantes_en_texte(charge["lignes_manquantes"])
    return _volet(
        STATUT_MANQUE,
        manque=(
            f"matériel {etat} selon M6 (révision {revision})"
            + (f" : {lignes}" if lignes else "")
            + " ; M6 ne crée aucun bon de commande seul (l'admin le demande à M6)"
        ),
        detail=etat,
    )


def _volet_meteo(_registre, inscription, _lire_position, _lire_equipes, lire_meteo):
    if lire_meteo is None:
        return _volet(
            STATUT_NON_VERIFIABLE,
            manque=(
                "lecture du profil météo : aucune n'a été fournie à l'évaluation, les règles météo du service ne "
                "se lisent pas"
            ),
        )
    profil, verdict = lire_meteo()
    if verdict is not None:
        return _volet(STATUT_MANQUE, manque=verdict["detail"], detail=verdict["code"])
    cle_travaux, service = etats.travaux_de(inscription)
    if cle_travaux != etats.CLE_SERVICE:
        return _volet(
            STATUT_NON_VERIFIABLE,
            manque=(
                f"intervention issue d'un lead v1 (type_travaux {service!r}) : les règles météo sont par service, "
                "aucune ne s'applique à un type de travaux"
            ),
        )
    regles = profil.get("services", {}).get(service)
    a_decider = meteo.risques_a_decider(regles)
    if a_decider:
        return _volet(
            STATUT_MANQUE,
            manque=(
                f"seuil à configurer pour le service {service!r} : {', '.join(a_decider)} (un seuil par risque jugé, "
                "ou le risque déclaré sans objet : `opsys meteo declarer`) ; aucun seuil n'est jamais inventé"
            ),
            detail="REJ-CHAMP-MANQUANT",
        )
    jugees = ", ".join(regles.get("seuils", {})) or "aucune"
    sans_objet = ", ".join(regles.get("sans_objet", ())) or "aucun"
    return _volet(
        STATUT_OK,
        detail=(
            f"règles météo déclarées pour {service} : mesures jugées {jugees} ; risques sans objet {sans_objet} ; la "
            "prévision d'un créneau se juge par m4_verifier_meteo_creneau, la préparation n'a pas de date"
        ),
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


def evaluer(registre_cible, intervention_id, lire_position, lire_equipes=None, lire_meteo=None):
    """``(verdict, None)`` ou ``(None, refus)`` : la préparation de l'intervention, volet par volet.

    ``lire_position(registre, chantier_id)`` rend ``(position, None)`` ou ``(None, verdict)`` : la même lecture
    que la cédule par tournées (``outils.lire_localisation_confirmee``). Le chantier d'une intervention est
    identifié par son ``lead_id``, comme dans la cédule.

    ``lire_equipes()`` rend ``(profil, None)`` ou ``(None, verdict)`` : le profil des équipes que l'adaptateur a lu
    (``opsys.equipes.charger_equipes``). Sans elle (``None``), le volet équipe reste ``non_verifiable`` : jamais ``ok``
    faute de lecture.

    ``lire_meteo()`` rend ``(profil, None)`` ou ``(None, verdict)`` : le profil météo que l'adaptateur a lu
    (``opsys.meteo.charger_meteo``). Sans elle (``None``), le volet météo reste ``non_verifiable`` : jamais ``ok`` faute
    de lecture.

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
    volets = {
        nom: fonction(registre_cible, inscription, lire_position, lire_equipes, lire_meteo) for nom, fonction in _VOLETS
    }
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
