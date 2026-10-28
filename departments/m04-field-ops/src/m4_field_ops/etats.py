"""
Machine à états de l'intervention pour M4 – S004.

Ce module implémente la table des transitions RATIFIÉE du PRD (M4-S004).
La plupart des conditions sémantiques des chemins (pointage cohérent, fix
GPS, écart détecté, validation humaine) sont vérifiées par les modules
appelants : cette machine garantit la fermeture de l’énuméré et de la table,
pas les faits de terrain en général.

EXCEPTION ÉPINGLÉE, corrigée (bug mesuré : la transition passait sans AUCUNE
condition) : planifiee -> en_route exige une ``assignation`` (PRD §4,
« conditionnée à l’assignation effective d’un technicien et au pointage de
départ du dépôt ») validée ICI, dans ``transitionner``, et non déléguée à un
appelant — parce qu’aucun autre module n’écrit cette transition (contrairement
à ``completed_pending_review``/``completed_verified``, dont l’écriture
appartient exclusivement à ``outbox.py``).

CORRESPONDANCE ANCIEN -> NOUVEAU (T1.1-b#2, alignement sur le cycle de vie de
DEFINITION-PRODUIT.md §7 M4 « Statuts d'un job », dans la seule mesure utile à
la tranche « travaux terminés » — les autres états ne sont PAS étendus au
catalogue complet du produit, hors périmètre de cette tranche) :

    planifiee                 -> planifiee (inchangé ; regroupe, en v1, les
                                  statuts produit ready_to_schedule..assigned,
                                  qu'un seul état M4 porte encore)
    en_route                  -> en_route (inchangé : déjà le mot du produit)
    sur_site                  -> sur_site (inchangé ; regroupe arrived+started
                                  du produit, qu'un seul état M4 porte encore)
    en_revue                  -> en_revue (inchangé : arbitrage interne M4 —
                                  GPS incohérent ou écart métier déclaré — SANS
                                  équivalent direct au catalogue produit ; il
                                  précède toujours la complétion, jamais après)
    reportee                  -> reportee (inchangé ; proche de rescheduled,
                                  mais PAS terminal ici : reportee->planifiee
                                  reste légal, alors que rescheduled est un
                                  sous-état de closed côté produit)
    terminee                  -> SCINDÉ, selon ecart_detecte (jamais déduit,
                                  fourni par l'appelant à la complétion) :
                                    vrai  -> completed_pending_review
                                    faux  -> completed_verified
                                  (DEFINITION-PRODUIT.md §6 : « S'il manque
                                  quelque chose ou si le matériel diffère du
                                  prévu, le statut devient
                                  completed_pending_review, pas
                                  completed_verified. »)
                                  T1.5-c : ``outbox.completer_intervention`` garde
                                  completed_pending_review même sans écart tant que
                                  la vérification est en attente (les matériaux ne
                                  sont pas encore comparés au prévu), sans inventer
                                  un ``ecart_detecte`` vrai pour l'obtenir.
    annulee                   -> annulee (inchangé ; proche de cancelled)

AJOUT ADDITIF (PLAN T4.10-b, DEFINITION-PRODUIT §7 M4.5 « Réception d'un job depuis M2/M3 »)
-------------------------------------------------------------------------------------------
``a_planifier`` : l'état d'une intervention qui vient de naître d'un devis accepté (``m3.devis_accepte``,
``inscrire_depuis_devis``), avant sa préparation (``preparation.py``, M4.6) et sa cédule. Il précède
``planifiee`` (« regroupe » ready_to_schedule..assigned du produit) sans rien changer aux états ni aux
transitions d'avant : les seize couples existants sont intacts, deux s'ajoutent en fin de table.
    a_planifier -> planifiee   exige un verdict de préparation ``pret`` (``preparation.evaluer``), c'est-à-dire
                               TOUS les volets vérifiés : tant que l'équipe, le matériel et la météo n'ont pas de
                               source dans M4, aucun verdict n'est ``pret`` et cette porte reste fermée ;
    a_planifier -> annulee     sans condition, comme planifiee -> annulee (le devis est retiré, le client renonce).
Une intervention inscrite par ``inscrire_intervention`` (``m4_planifier_intervention``) naît toujours ``planifiee``,
inchangé.

``completed_pending_review``/``completed_verified`` restent, comme
``terminee`` avant elles, refusées ICI comme cible directe de
``transitionner`` (voir plus bas) : seul ``outbox.completer_intervention``
les écrit, dans le MÊME maillon que le WCT (CA-M4-11). Toute autre tentative
de cible produit une transition illégale nommée (REJ-TRANSITION-ILLEGALE).
"""

import copy

from . import cedule, contrats, encodage, frontieres, horodatage, verdicts

# registre n’est pas importé en tant que module car on n’en utilise que les instances passées.

# ---------------------------------------------------------------------------
# Constantes épinglées
# ---------------------------------------------------------------------------
ETATS = (
    "planifiee",
    "en_route",
    "sur_site",
    "en_revue",
    "reportee",
    "completed_pending_review",
    "completed_verified",
    "annulee",
    "a_planifier",  # PLAN T4.10-b : additif, en fin de liste, les huit d'avant gardent leur rang
)
ETATS_TERMINAUX = ("completed_pending_review", "completed_verified", "annulee")
MOTIFS_REPORT = ("client_absent", "meteo", "decision_admin")
TRANSITIONS_AUTORISEES = (
    ("planifiee", "en_route"),
    ("planifiee", "reportee"),
    ("planifiee", "annulee"),
    ("en_route", "sur_site"),
    ("en_route", "reportee"),
    ("en_route", "annulee"),
    ("sur_site", "en_revue"),
    ("sur_site", "completed_pending_review"),
    ("sur_site", "completed_verified"),
    ("en_revue", "completed_pending_review"),
    ("en_revue", "completed_verified"),
    ("en_revue", "annulee"),
    ("en_revue", "sur_site"),
    ("en_route", "en_revue"),
    ("reportee", "planifiee"),
    ("reportee", "annulee"),
    # PLAN T4.10-b : additifs. a_planifier -> planifiee n'a de sens qu'avec un verdict de préparation « pret ».
    ("a_planifier", "planifiee"),
    ("a_planifier", "annulee"),
    ("sur_site", "reportee"),  # CRM-01 : uniquement après clôture vérifiée.
)

TYPE_INSCRIPTION = "intervention_inscrite"
TYPE_TRANSITION = "transition_statut"
# PLAN T1.4-k : maillon « ce technicien est assigné à cette intervention », écrit AVANT le départ
# (`m4_planifier_intervention` y consigne la cédule). Sans statut : il ne change pas l'état de
# l'intervention, il dit seulement à qui elle est.
TYPE_ASSIGNATION = "assignation_technicien"
# PLAN T4.10-b : d'où vient une intervention née du bus (champ `source` du maillon d'inscription). Une inscription
# faite par `inscrire_intervention` ne porte pas ce champ.
SOURCE_DEVIS_ACCEPTE = "m3.devis_accepte"
# Vocabulaire du verdict de préparation (`preparation.py`) que la machine à états doit reconnaître pour refuser un
# passage à planifiee sans « pret » : définis ICI pour que `preparation.py` (qui importe `etats`) les reprenne
# sans cycle d'import.
VERDICT_PREPARATION_PRET = "pret"
STATUT_VOLET_OK = "ok"

__all__ = [
    "ETATS",
    "ETATS_TERMINAUX",
    "MOTIFS_REPORT",
    "TRANSITIONS_AUTORISEES",
    "TYPE_INSCRIPTION",
    "TYPE_TRANSITION",
    "TYPE_ASSIGNATION",
    "SOURCE_DEVIS_ACCEPTE",
    "VERDICT_PREPARATION_PRET",
    "STATUT_VOLET_OK",
    "CLE_TYPE_TRAVAUX",
    "CLE_SERVICE",
    "travaux_de",
    "statut_courant",
    "inscrire_intervention",
    "inscrire_depuis_devis",
    "intervention_du_devis",
    "intervention_nee_du_bus_du_lead",
    "empreinte_preparation",
    "assigner_technicien",
    "technicien_assigne",
    "transitionner",
    "lister_interventions",
]

# PLAN T0.13-b : ce que l'inscription retient de la nature des travaux dépend de la version du
# LeadQualifie qui l'a produite, lue dans le lead à l'inscription et jamais devinée. Un lead v1 (gelé)
# porte `type_travaux` ; un lead v2 porte `service` (taxonomie du socle) et `schema_version`. L'un n'est
# JAMAIS déduit de l'autre : une inscription porte exactement l'une des deux clés.
CLE_TYPE_TRAVAUX = "type_travaux"
CLE_SERVICE = "service"


def travaux_de(inscription):
    """`(clé, valeur)` de la nature des travaux d'une inscription : ``("type_travaux", v)`` pour un
    lead v1, ``("service", v)`` pour un lead v2. Lève ``ValueError`` si l'inscription porte les deux
    clés ou aucune (registre altéré : jamais l'une choisie ou déduite à la place de l'autre).

    Toute lecture qui range ou rend la nature des travaux (liste des interventions, état d'une
    cédule, WCT) passe par ici : la règle est écrite une seule fois."""
    a_type = CLE_TYPE_TRAVAUX in inscription
    a_service = CLE_SERVICE in inscription
    if a_type == a_service:
        raise ValueError(
            "inscription incohérente : elle doit porter exactement l'une des clés "
            f"{CLE_TYPE_TRAVAUX!r} (lead v1) ou {CLE_SERVICE!r} (lead v2)"
        )
    cle = CLE_SERVICE if a_service else CLE_TYPE_TRAVAUX
    return cle, inscription[cle]


# ---------------------------------------------------------------------------
# Fonctions publiques
# ---------------------------------------------------------------------------

def statut_courant(registre_cible, intervention_id):
    """
    Calcule le statut actuel d’une intervention en rejouant le registre.

    Args:
        registre_cible: instance de Registre.
        intervention_id: identifiant de l’intervention.

    Returns:
        Le dernier statut rencontré, ou None si l’intervention est inexistante.
    """
    dernier_statut = None
    for maillon in registre_cible.lire():
        if maillon["type_entree"] not in (TYPE_INSCRIPTION, TYPE_TRANSITION):
            continue
        if maillon.get("intervention_id") != intervention_id:
            continue
        dernier_statut = maillon["statut"]
    return dernier_statut


def inscrire_intervention(contrat, marqueur, registre_cible, horodatage_arg, sel, devis_id=None):
    """
    Enregistre une nouvelle intervention (transition vide → planifiee).

    Args:
        contrat: dict validé par contrats.valider_entree (LeadQualifie v1 ou v2,
            selon la version qu'il déclare).
        marqueur: dict de readiness.
        registre_cible: instance de Registre.
        horodatage_arg: horodatage chaîne (RFC 3339 avec fuseau).
        sel: sel de tokenisation de la ville, fourni par l’appelant (obligatoire).
        devis_id: identifiant du devis M3 accepté (T1.1-b#1), OPTIONNEL. Fourni
            À L'INSCRIPTION plutôt qu'à la complétion : M4.5 (« Réception d’un
            job depuis M2/M3, soumission acceptée ») fait du devis accepté la
            RAISON D'ÊTRE de l'intervention dès sa création, donc la donnée est
            déjà connue à ce moment-là ; la porter tel quel jusqu'au WCT
            (``outbox._extraire_devis_id``) évite de la redemander à la
            complétion, des heures ou des jours plus tard. Omis (None), aucun
            rejet : M3 n'alimente pas encore tous les chemins d'entrée (P10,
            dégradation gracieuse) — et les appels existants à 5 arguments
            positionnels restent valides tels quels.

    Returns:
        (accusé, None) en cas de succès, ou (None, verdict) en cas d’échec.
    """
    # 1. Validation du contrat + marqueur
    ok, verdict = contrats.valider_entree(contrat, marqueur)
    if not ok:
        return None, verdict  # verdict déjà construit

    # 1 bis. Le sel de tokenisation est OBLIGATOIRE : une empreinte nue de nom de
    # ville est attaquable par dictionnaire (quelques milliers de villes).
    if not isinstance(sel, str) or sel == "":
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE", detail="sel de tokenisation absent"
        )

    # 1 ter. devis_id (T1.1-b#1) : optionnel, jamais un défaut inventé si
    # fourni mais malformé — fail-closed comme le reste du contrat.
    if devis_id is not None:
        if not isinstance(devis_id, str):
            return None, verdicts.construire_verdict(
                "REJ-CONTRAT-INVALIDE", detail="devis_id doit être une chaîne ou null"
            )
        if devis_id == "":
            return None, verdicts.construire_verdict(
                "REJ-CHAMP-VIDE", detail="devis_id vide"
            )

    # 2. Validation de l’horodatage
    try:
        horodatage.valider_horodatage(horodatage_arg)
    except ValueError:
        return None, verdicts.construire_verdict("REJ-HORODATAGE-INVALIDE")

    # 2 bis. PLAN T4.12 : un devis n'a qu'une intervention. `m3.devis_accepte` fait déjà naître une intervention
    # `a_planifier` (``inscrire_depuis_devis``) : la planifier une seconde fois à la main en ferait deux pour le même
    # chantier. Refusé ICI, à la source, pour tenir quel que soit l'appelant (même patron que la porte de préparation).
    verdict_doublon = _refuser_le_doublon_du_bus(registre_cible, contrat["lead_id"], devis_id)
    if verdict_doublon is not None:
        return None, verdict_doublon

    # 3. Génération de l’identifiant d’intervention
    intervention_id = encodage.empreinte(
        "intervention", contrat["lead_id"], horodatage_arg
    )

    # 4. Vérification de non‑réinscription
    if statut_courant(registre_cible, intervention_id) is not None:
        return None, verdicts.construire_verdict(
            "REJ-TRANSITION-ILLEGALE",
            detail=(
                "intervention déjà inscrite : l'inscription est la transition "
                "vide->planifiee, fermée depuis un état existant"
            ),
        )

    # 5. Construction du maillon d’inscription
    # INTERDIT ABSOLU : ne jamais copier contrat["contact"] (données personnelles)
    # PLAN T0.13-b : la nature des travaux suit la version DÉCLARÉE par le lead (contrats.py) : un lead
    # v2 (`schema_version`) donne `service` et sa version, un lead v1 donne `type_travaux` (maillon
    # inchangé, octet pour octet). Jamais l'un déduit de l'autre.
    if "schema_version" in contrat:
        travaux = {
            "schema_version": copy.deepcopy(contrat["schema_version"]),
            CLE_SERVICE: copy.deepcopy(contrat[CLE_SERVICE]),
        }
    else:
        travaux = {CLE_TYPE_TRAVAUX: copy.deepcopy(contrat[CLE_TYPE_TRAVAUX])}
    maillon = {
        "type_entree": TYPE_INSCRIPTION,
        "intervention_id": intervention_id,
        "lead_id": copy.deepcopy(contrat["lead_id"]),
        "conversation_id": copy.deepcopy(contrat["conversation_id"]),
        **travaux,
        # Architecture §2 : l'entité Intervention porte la ville TOKENISÉE.
        # Le registre est immuable : une ville en clair y serait irrattrapable.
        "ville_tokenisee": cedule.tokeniser_ville(sel, contrat["ville"]),
        "urgence_declaree": copy.deepcopy(contrat["urgence_declaree"]),
        "devis_id": devis_id,
        "statut": "planifiee",
        "horodatage": horodatage_arg,
        "empreinte_contrat": encodage.empreinte(contrat),
        "empreinte_marqueur": encodage.empreinte(marqueur),
    }

    # 6. Écriture dans le registre, puis relecture PAR ligne_id (hash, pas un index)
    ligne_id = registre_cible.ajouter(maillon)
    maillon_relu = None
    for m in registre_cible.lire():
        if m.get("ligne_id") == ligne_id:
            maillon_relu = m
            break
    if maillon_relu is None:
        raise RuntimeError(
            "Incohérence interne : l’entrée ajoutée est introuvable dans le registre."
        )

    # 7. Fabrication de l’accusé
    accuse = {
        "intervention_id": intervention_id,
        "ligne_id": ligne_id,
        "statut": "planifiee",
        "empreinte_maillon": encodage.empreinte(maillon_relu),
        "tete_chaine": registre_cible.tete(),
        "horodatage": horodatage_arg,
    }
    return accuse, None


def intervention_du_devis(registre_cible, devis_id):
    """``intervention_id`` de la première intervention qui porte ce ``devis_id``, ou ``None`` (PLAN T4.10-b).

    Toute inscription compte, quelle qu'en soit l'origine (``inscrire_intervention`` avec un ``devis_id``, ou
    ``inscrire_depuis_devis``) : un devis n'a qu'une intervention, jamais une seconde née du bus à côté d'une
    intervention déjà planifiée à la main. Lu au registre, jamais déduit."""
    if not isinstance(devis_id, str) or devis_id == "":
        return None
    for maillon in registre_cible.lire():
        if maillon["type_entree"] == TYPE_INSCRIPTION and maillon.get("devis_id") == devis_id:
            return maillon["intervention_id"]
    return None


def intervention_nee_du_bus_du_lead(registre_cible, lead_id):
    """``intervention_id`` de la première intervention ACTIVE (non annulée) née d'un devis accepté (``source``
    ``m3.devis_accepte``) pour ce lead, ou ``None`` (PLAN T4.12). Lu au registre, jamais déduit.

    Sert quand la planification à la main n'a pas de ``devis_id`` à comparer : une intervention encore à faire, née du
    devis de CE lead, est presque sûrement le même chantier."""
    for maillon in registre_cible.lire():
        if (
            maillon["type_entree"] == TYPE_INSCRIPTION
            and maillon.get("source") == SOURCE_DEVIS_ACCEPTE
            and maillon.get("lead_id") == lead_id
            and statut_courant(registre_cible, maillon["intervention_id"]) != "annulee"
        ):
            return maillon["intervention_id"]
    return None


def _refuser_le_doublon_du_bus(registre_cible, lead_id, devis_id):
    """Verdict de refus si planifier à la main ferait un doublon d'une intervention née du bus, sinon ``None``.

    Avec ``devis_id`` : toute inscription qui porte ce devis compte, née du bus ou non, annulée ou non (un devis n'a
    qu'une intervention, comme pour ``inscrire_depuis_devis``). Sans ``devis_id`` : une intervention active née du bus
    pour le même lead compte ; fournir le ``devis_id`` (d'un autre devis du lead) lève le refus."""
    if devis_id is not None:
        existante = intervention_du_devis(registre_cible, devis_id)
        if existante is None:
            return None
        return verdicts.construire_verdict(
            "REJ-TRANSITION-ILLEGALE",
            statut=statut_courant(registre_cible, existante),
            detail=(
                f"une intervention existe déjà pour le devis {devis_id!r} ({existante}, "
                f"{statut_courant(registre_cible, existante)}) : un devis n'a qu'une intervention ; la préparer "
                "(m4_verifier_preparation) et la céduler (m4_proposer_cedule) au lieu de la planifier une seconde fois"
            ),
        )
    nee = intervention_nee_du_bus_du_lead(registre_cible, lead_id)
    if nee is None:
        return None
    return verdicts.construire_verdict(
        "REJ-TRANSITION-ILLEGALE",
        statut=statut_courant(registre_cible, nee),
        detail=(
            f"une intervention née d'un devis accepté attend déjà pour ce lead ({nee}, "
            f"{statut_courant(registre_cible, nee)}) : sans devis_id, cette planification en ferait un doublon ; "
            "fournir le devis_id d'un AUTRE devis, ou préparer et céduler l'intervention existante"
        ),
    )


def inscrire_depuis_devis(registre_cible, devis_id, lead, sel, horodatage_arg):
    """
    Inscrit l'intervention qui naît d'un devis accepté, au statut ``a_planifier`` (PLAN T4.10-b, M4.5).

    Le devis (``m3.devis_accepte``) porte ``devis_id`` et ``lead_id`` ; il ne porte pas le service, la ville ni
    l'urgence du chantier. Ceux-là viennent de ``lead`` : le LeadQualifie v2 que M1 a publié pour ce lead, relu à
    la source du bus par l'adaptateur (``outils._recevoir_devis_accepte``), jamais fourni par un agent ni deviné.

    Args:
        devis_id: identifiant du devis M3 accepté (chaîne non vide).
        lead: LeadQualifie v2, validé ICI comme partout dans M4 (frontières, puis structure v2 : le service doit
            être un code déclaré par le profil d'entreprise de l'instance, ``opsys.taxonomie``).
        sel: sel de la ville tokenisée (Architecture §2 : le registre est immuable, une ville en clair y serait
            irrattrapable). Fourni par l'adaptateur, qui le tient du coffre du socle : une inscription née du bus
            n'a pas d'appelant qui le donne.
        horodatage_arg: heure de l'acceptation du devis (RFC 3339 avec fuseau), jamais une horloge de M4.

    Refus, sans rien écrire (fail-closed) : frontière violée, lead qui n'est pas un v2 valide, ``devis_id`` ou
    ``sel`` absent, horodatage invalide, intervention déjà inscrite pour ce devis (REJ-TRANSITION-ILLEGALE).

    Le maillon ne porte AUCUN contact du client (ni nom, ni téléphone, ni courriel, ni empreinte de ceux-ci) ni
    identifiant de conversation, ni prix : seulement ce que M4 planifie. Aucune date ni créneau n'est fixé.
    Pas de marqueur de readiness : c'est celui de M2, M4 n'en a pas ; la preuve d'entrée est le devis accepté.

    Returns:
        (accusé, None) en cas de succès, ou (None, verdict) en cas d'échec.
    """
    if not isinstance(devis_id, str):
        return None, verdicts.construire_verdict("REJ-CONTRAT-INVALIDE", detail="devis_id doit être une chaîne")
    if devis_id == "":
        return None, verdicts.construire_verdict("REJ-CHAMP-VIDE", detail="devis_id vide")

    ok_front, verdict_front = frontieres.verifier_frontieres(lead)
    if not ok_front:
        return None, verdict_front
    if not isinstance(lead, dict) or "schema_version" not in lead:
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            detail="LeadQualifie v2 attendu (schema_version) : c'est le contrat que M1 publie",
        )
    ok_struct, code_struct, detail_struct = contrats.valider_structure_avec_detail(lead)
    if not ok_struct:
        return None, verdicts.construire_verdict(code_struct, detail=detail_struct)

    if not isinstance(sel, str) or sel == "":
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE", detail="sel de tokenisation absent"
        )
    try:
        horodatage.valider_horodatage(horodatage_arg)
    except ValueError:
        return None, verdicts.construire_verdict("REJ-HORODATAGE-INVALIDE")

    intervention_id = encodage.empreinte("intervention-devis", lead["lead_id"], devis_id)
    if intervention_du_devis(registre_cible, devis_id) is not None:
        return None, verdicts.construire_verdict(
            "REJ-TRANSITION-ILLEGALE",
            detail="une intervention existe déjà pour ce devis : un devis n'a qu'une intervention",
        )

    maillon = {
        "type_entree": TYPE_INSCRIPTION,
        "intervention_id": intervention_id,
        "lead_id": copy.deepcopy(lead["lead_id"]),
        "schema_version": copy.deepcopy(lead["schema_version"]),
        CLE_SERVICE: copy.deepcopy(lead[CLE_SERVICE]),
        "ville_tokenisee": cedule.tokeniser_ville(sel, lead["ville"]),
        "urgence_declaree": copy.deepcopy(lead["urgence_declaree"]),
        "devis_id": devis_id,
        "source": SOURCE_DEVIS_ACCEPTE,
        "statut": "a_planifier",
        "horodatage": horodatage_arg,
    }
    ligne_id = registre_cible.ajouter(maillon)
    maillon_relu = None
    for m in registre_cible.lire():
        if m.get("ligne_id") == ligne_id:
            maillon_relu = m
            break
    if maillon_relu is None:
        raise RuntimeError(
            "Incohérence interne : l’entrée ajoutée est introuvable dans le registre."
        )
    return {
        "intervention_id": intervention_id,
        "ligne_id": ligne_id,
        "statut": "a_planifier",
        "empreinte_maillon": encodage.empreinte(maillon_relu),
        "tete_chaine": registre_cible.tete(),
        "horodatage": horodatage_arg,
    }, None


def empreinte_preparation(verdict):
    """Empreinte SHA-256 canonique de ce qu'un verdict de préparation DIT (intervention, verdict d'ensemble, volets).

    ``preparation.evaluer`` la pose sur son verdict ; ``transitionner`` la recalcule pour refuser un verdict
    dont le contenu aurait été modifié après coup (un « pret » posé sur des volets qui n'ont pas été vérifiés)."""
    return encodage.empreinte(
        {cle: verdict[cle] for cle in ("intervention_id", "statut", "volets")}
    )


def _preparation_prete(preparation, intervention_id):
    """Vrai seulement pour un verdict de préparation de CETTE intervention, ``pret``, dont tous les volets sont
    ``ok`` et dont l'empreinte est celle de son contenu. Un dictionnaire quelconque ne passe jamais."""
    if not isinstance(preparation, dict):
        return False
    volets = preparation.get("volets")
    if not isinstance(volets, dict) or not volets:
        return False
    try:
        empreinte_attendue = empreinte_preparation(preparation)
    except (KeyError, TypeError, ValueError):
        return False
    return (
        preparation.get("intervention_id") == intervention_id
        and preparation.get("statut") == VERDICT_PREPARATION_PRET
        and preparation.get("pret") is True
        and all(isinstance(v, dict) and v.get("statut") == STATUT_VOLET_OK for v in volets.values())
        and preparation.get("empreinte") == empreinte_attendue
    )


def assigner_technicien(intervention_id, technicien_id, registre_cible, horodatage_arg):
    """
    Consigne qu'un technicien est assigné à une intervention, AVANT son départ (PLAN T1.4-k).

    Jusqu'ici l'assignation n'entrait au registre qu'avec la transition ``en_route``
    (``transitionner``, PRD §4) : avant de partir, aucune intervention n'était « à quelqu'un », donc
    ni la liste du jour d'un employé ni le contrôle d'accès par intervention n'avaient de fait sur
    quoi s'appuyer. Ce maillon n'est PAS une transition : il ne change pas le statut et n'ouvre aucun
    droit de départ à lui seul (``planifiee -> en_route`` exige toujours l'assignation, validée à
    ``transitionner``).

    Refus, sans rien écrire (fail-closed) :
      - horodatage invalide : REJ-HORODATAGE-INVALIDE ;
      - intervention inexistante ou déjà dans un état terminal : REJ-TRANSITION-ILLEGALE (on
        n'assigne pas un chantier clos) ;
      - ``technicien_id`` absent, non textuel ou vide : REJ-CHAMP-VIDE / REJ-CONTRAT-INVALIDE —
        jamais un technicien par défaut.

    Returns:
        (accusé, None) en cas de succès, ou (None, verdict) en cas d'échec.
    """
    try:
        horodatage.valider_horodatage(horodatage_arg)
    except ValueError:
        return None, verdicts.construire_verdict("REJ-HORODATAGE-INVALIDE")

    courant = statut_courant(registre_cible, intervention_id)
    if courant is None:
        return None, verdicts.construire_verdict(
            "REJ-TRANSITION-ILLEGALE", detail="intervention inexistante"
        )
    if courant in ETATS_TERMINAUX:
        return None, verdicts.construire_verdict(
            "REJ-TRANSITION-ILLEGALE",
            statut=courant,
            detail=f"assignation impossible depuis un état terminal ({courant})",
        )

    if not isinstance(technicien_id, str):
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE", detail="technicien_id doit être une chaîne"
        )
    if technicien_id == "":
        return None, verdicts.construire_verdict("REJ-CHAMP-VIDE", detail="technicien_id vide")

    ligne_id = registre_cible.ajouter({
        "type_entree": TYPE_ASSIGNATION,
        "intervention_id": intervention_id,
        "technicien_id": technicien_id,
        "horodatage": horodatage_arg,
    })
    return {
        "intervention_id": intervention_id,
        "technicien_id": technicien_id,
        "ligne_id": ligne_id,
        "horodatage": horodatage_arg,
        "tete_chaine": registre_cible.tete(),
    }, None


def technicien_assigne(registre_cible, intervention_id):
    """
    ``technicien_id`` assigné à cette intervention, ou ``None`` si aucun fait d'assignation n'existe.

    Le DERNIER fait d'assignation du registre l'emporte, qu'il vienne de la planification
    (``assigner_technicien``, avant le départ) ou du départ (transition ``en_route``, où
    ``transitionner`` persiste le technicien réellement envoyé) : c'est la même question posée à
    deux moments, et celui qui vient après la précédente décision la remplace. Historique, pas un
    droit d'agir : un report ou une annulation ultérieurs laissent ce champ tel quel (le fait « à qui
    elle est » reste vrai), à lire aux côtés de ``statut_courant``. Jamais déduit d'un argument
    d'appelant : seul le registre le dit (``None`` = personne, fail-closed pour qui filtre dessus).
    """
    technicien = None
    for maillon in registre_cible.lire():
        if maillon.get("intervention_id") != intervention_id:
            continue
        type_entree = maillon.get("type_entree")
        if type_entree == TYPE_ASSIGNATION or (
            type_entree == TYPE_TRANSITION and maillon.get("statut") == "en_route"
        ):
            technicien = maillon.get("technicien_id")
    return technicien


def transitionner(
    intervention_id, statut_cible, registre_cible, horodatage_arg, motif=None,
    assignation=None, preparation=None, horodatage_appareil=None, registre_visites=None,
):
    """
    Effectue une transition d’état pour une intervention existante.

    Args:
        intervention_id: identifiant de l’intervention.
        statut_cible: état visé (doit appartenir à ETATS).
        registre_cible: instance de Registre.
        horodatage_arg: horodatage chaîne (RFC 3339 avec fuseau).
        horodatage_appareil: PLAN T4.27-a2, optionnel — l'heure de l'appareil (ISO 8601 avec fuseau), gardée À PART sous
            la clé sœur ``horodatage_appareil`` du maillon et de l'accusé : affichage seulement, jamais lue pour un
            calcul. La fournir DÉCLARE que ``horodatage_arg`` est l'heure de RÉCEPTION du serveur (le fait d'un appel
            d'appareil) : ce module n'a aucune horloge, c'est ``outils.py`` seul qui décide d'où vient l'heure
            (``horodatage.origine`` relit ce signe). ``None`` (défaut, tout appel d'avant) : le maillon et l'accusé
            restent exactement ce qu'ils étaient, l'heure écrite par l'appelant fait foi.
        motif: obligatoire pour un report, interdit sinon.
        assignation: obligatoire pour planifiee -> en_route (PRD §4 : cette
            transition est « conditionnée à l’assignation effective d’un
            technicien et au pointage de départ du dépôt » — le présent
            horodatage validé EST ce pointage de départ ; ``assignation``
            en fournit la seconde moitié, l’identité du technicien). Interdit
            pour toute autre cible, comme ``motif`` l’est hors report.
        preparation: obligatoire pour a_planifier -> planifiee (PLAN T4.10-b) : le verdict de
            ``preparation.evaluer``, ``pret`` avec TOUS ses volets ``ok`` et son empreinte intacte. Interdit pour
            toute autre transition, comme ``assignation``. Tant qu'un volet n'est pas vérifiable, aucun verdict
            n'est ``pret`` : la porte reste fermée, jamais ouverte par défaut.

    Returns:
        (accusé, None) en cas de succès, ou (None, verdict) en cas d’échec.
    """
    # 1. Horodatage
    try:
        horodatage.valider_horodatage(horodatage_arg)
    except ValueError:
        return None, verdicts.construire_verdict("REJ-HORODATAGE-INVALIDE")

    # 1 bis. Heure de l'appareil (PLAN T4.27-a2) : sa forme seulement, jamais lue pour un calcul. Mal formée : refus,
    # rien n'est écrit (jamais une clé sœur illisible dans un registre immuable).
    if horodatage_appareil is not None:
        try:
            horodatage.valider_horodatage(horodatage_appareil)
        except ValueError:
            return None, verdicts.construire_verdict(
                "REJ-HORODATAGE-INVALIDE",
                detail="horodatage_appareil : une heure ISO 8601 avec fuseau est attendue",
            )

    # 2. Existence de l’intervention
    courant = statut_courant(registre_cible, intervention_id)
    if courant is None:
        return None, verdicts.construire_verdict(
            "REJ-TRANSITION-ILLEGALE", detail="intervention inexistante"
        )

    # 3. validité de la cible dans l’énuméré
    if statut_cible not in ETATS:
        return None, verdicts.construire_verdict(
            "REJ-ENUM-INVALIDE",
            statut=courant,
            detail=f"statut_cible invalide : {statut_cible}",
        )

    # 4. État terminal interdit comme départ
    if courant in ETATS_TERMINAUX:
        return None, verdicts.construire_verdict(
            "REJ-TRANSITION-ILLEGALE",
            detail=f"transition impossible depuis un état terminal ({courant})",
        )

    # 5. Vérification dans la table des transitions autorisées
    if (courant, statut_cible) not in TRANSITIONS_AUTORISEES:
        return None, verdicts.construire_verdict(
            "REJ-TRANSITION-ILLEGALE",
            detail=f"transition non autorisée : {courant} -> {statut_cible}",
        )

    # 5 bis. Les cibles completed_pending_review et completed_verified sont
    # REFUSÉES ici (T1.1-b#2, ex-``terminee`` scindée en deux issues selon
    # ecart_detecte) : la transition vers l'une d'elles et l'événement WCT
    # doivent être écrits par UNE SEULE opération d'ajout (CA-M4-11), donc par
    # l'outbox seul. La table conserve les quatre couples légaux
    # (sur_site|en_revue, completed_pending_review|completed_verified) : elle
    # dit ce qui est LÉGAL, l'outbox est le seul qui ÉCRIT.
    if statut_cible in ("completed_pending_review", "completed_verified"):
        return None, verdicts.construire_verdict(
            "REJ-TRANSITION-ILLEGALE",
            statut=courant,
            detail=(
                "la complétion passe exclusivement par l'outbox : la transition vers "
                "completed_pending_review ou completed_verified et l'événement WCT "
                "doivent être écrits par UNE SEULE opération d'ajout (CA-M4-11)"
            ),
        )

    # 6. Contrôle du motif
    if statut_cible == "reportee":
        if motif not in MOTIFS_REPORT:
            return None, verdicts.construire_verdict(
                "REJ-ENUM-INVALIDE",
                statut=courant,
                detail=f"motif de report invalide ou manquant : {motif}",
            )
    else:
        if motif is not None:
            return None, verdicts.construire_verdict(
                "REJ-ENUM-INVALIDE",
                statut=courant,
                detail="motif réservé au report",
            )

    # L'interruption d'un travail commencé exige une session intégralement
    # fermée et ses sources : le statut seul ne prouve jamais un départ.
    fermeture_visite = None
    if courant == "sur_site" and statut_cible == "reportee":
        from . import visites_chantier
        try:
            if registre_visites is None:
                raise ValueError("registre de visites absent")
            visites_chantier.calculer_faits_certifies(registre_cible, registre_visites, intervention_id,
                                                        ignorer_anciens=True)
            fermetures = [m for m in registre_cible.lire() if m.get("type_entree") == "visite_fermee"
                          and m.get("intervention_id") == intervention_id]
            if (not fermetures or visites_chantier._instant(horodatage_arg)
                    < visites_chantier._instant(fermetures[-1]["horodatage"])):
                raise ValueError("fermeture ou chronologie invalide")
            fermeture_visite = fermetures[-1]
        except ValueError:
            return None, verdicts.construire_verdict(
                "REJ-TRANSITION-ILLEGALE", statut=courant, detail="visite fermée et sources vérifiées requises")
    elif registre_visites is not None:
        return None, verdicts.construire_verdict("REJ-CONTRAT-INVALIDE", detail="registre de visites inattendu")

    # 6 bis. planifiee -> en_route exige la PREUVE d'assignation effective
    # d'un technicien (PRD §4). Sans ce contrôle, la machine garantirait
    # SEULEMENT la fermeture de la table (docstring du module), jamais le
    # fait de terrain — exactement ce que « sans condition » signifiait ici :
    # n'importe quel appelant pouvait faire partir un technicien fictif.
    if statut_cible == "en_route":
        assignation_valide = (
            isinstance(assignation, dict)
            and set(assignation) == {"intervention_id", "technicien_id"}
            and assignation.get("intervention_id") == intervention_id
            and isinstance(assignation.get("technicien_id"), str)
            and assignation["technicien_id"] != ""
        )
        if not assignation_valide:
            return None, verdicts.construire_verdict(
                "REJ-PUNCH-SANS-INTERVENTION",
                statut=courant,
                detail=(
                    "planifiee -> en_route exige l'assignation effective d'un "
                    "technicien (intervention_id et technicien_id concordants)"
                ),
            )
    else:
        if assignation is not None:
            return None, verdicts.construire_verdict(
                "REJ-ENUM-INVALIDE",
                statut=courant,
                detail="assignation réservée à la transition planifiee -> en_route",
            )

    # 6 ter. a_planifier -> planifiee exige un verdict de préparation « pret » (PLAN T4.10-b, M4.6) : vérifié ICI, à la
    # source, pour tenir quel que soit l'outil appelant (même patron que l'assignation ci-dessus).
    if courant == "a_planifier" and statut_cible == "planifiee":
        if not _preparation_prete(preparation, intervention_id):
            return None, verdicts.construire_verdict(
                "REJ-TRANSITION-ILLEGALE",
                statut=courant,
                detail=(
                    "a_planifier -> planifiee exige un verdict de préparation « pret » de cette intervention "
                    "(preparation.evaluer) : tous les volets doivent être vérifiés, aucun n'est présumé"
                ),
            )
    elif preparation is not None:
        return None, verdicts.construire_verdict(
            "REJ-ENUM-INVALIDE",
            statut=courant,
            detail="preparation réservée à la transition a_planifier -> planifiee",
        )

    # Une visite ouverte est l'unique ancre pour une nouvelle mise en route.
    visite = None
    if statut_cible == "en_route":
        from . import visites_chantier
        try:
            visite = visites_chantier.visite_active(registre_cible, intervention_id)
            if visite:
                visites_chantier.verifier_ouverture_courante(registre_cible, visite)
            if visite and (visites_chantier._instant(horodatage_arg) <
                           visites_chantier._instant(visite["horodatage"])):
                raise ValueError("chronologie de visite invalide")
            if visite is None and any(m.get("type_entree") == "visite_ouverte"
                                      and m.get("intervention_id") == intervention_id
                                      for m in registre_cible.lire()):
                raise ValueError("aucune visite active")
        except ValueError:
            return None, verdicts.construire_verdict("REJ-CONTRAT-INVALIDE",
                                                       detail="visite ouverte incohérente")

    # 7. Construction du maillon de transition
    maillon = {
        "type_entree": TYPE_TRANSITION,
        "intervention_id": intervention_id,
        "statut": statut_cible,
        "statut_precedent": courant,
        "horodatage": horodatage_arg,
    }
    if statut_cible == "reportee":
        maillon["motif"] = motif
        if fermeture_visite is not None:
            maillon["visite_id"] = fermeture_visite["visite_id"]
            maillon["source_fermeture"] = fermeture_visite["ligne_id"]
    if visite is not None:
        maillon["visite_id"] = visite["visite_id"]
    if statut_cible == "en_route":
        # Preuve de terrain persistée : pointage.py vérifie l'IDENTITÉ du
        # technicien qui pointe (arrivée/départ) contre CE champ, plutôt que
        # la seule déclaration non vérifiée de l'appelant (voir pointage.py).
        maillon["technicien_id"] = assignation["technicien_id"]
    if courant == "a_planifier" and statut_cible == "planifiee":
        # Ce sur quoi la transition s'appuie : l'empreinte du verdict de préparation, pas le verdict lui-même.
        maillon["empreinte_preparation"] = preparation["empreinte"]
    if horodatage_appareil is not None:
        # PLAN T4.27-a2 : l'heure de l'appareil, À PART (affichage seulement) ; sa présence dit que ``horodatage``
        # est l'heure de réception du serveur (``horodatage.origine``). Absente : le maillon est celui d'avant.
        maillon[horodatage.CLE_HORODATAGE_APPAREIL] = horodatage_appareil

    # 8. Écriture, puis relecture PAR ligne_id (hash, pas un index)
    ligne_id = registre_cible.ajouter(maillon)
    maillon_relu = None
    for m in registre_cible.lire():
        if m.get("ligne_id") == ligne_id:
            maillon_relu = m
            break
    if maillon_relu is None:
        raise RuntimeError(
            "Incohérence interne : l’entrée ajoutée est introuvable dans le registre."
        )

    # 9. Accusé
    accuse = {
        "intervention_id": intervention_id,
        "ligne_id": ligne_id,
        "statut": statut_cible,
        "statut_precedent": courant,
        "empreinte_maillon": encodage.empreinte(maillon_relu),
        "tete_chaine": registre_cible.tete(),
        "horodatage": horodatage_arg,
    }
    if horodatage_appareil is not None:
        accuse[horodatage.CLE_HORODATAGE_APPAREIL] = horodatage_appareil  # T4.27-a2 : additif, absent sans appareil
    return accuse, None


def lister_interventions(registre_cible, statut=None):
    """
    Liste les interventions connues, sans AUCUNE donnée de contact (T1.1-b#4).

    Lecture pure (T0) : rejoue le registre pour dériver, par intervention, son
    statut courant (même logique que ``statut_courant``, appliquée à toutes les
    interventions plutôt qu'à une seule). Le contact (nom/téléphone/courriel)
    n'entre JAMAIS au registre (cf. ``inscrire_intervention``) : il est donc
    structurellement absent d'ici, pas seulement filtré.

    T1.4-e2 (écran « chantiers du jour ») : ``technicien_assigne`` et
    ``fenetre_planifiee`` sont rendus QUAND le registre les porte, jamais
    devinés (AGENTS.md, fail-closed) :
      - ``technicien_assigne`` : le DERNIER fait d'assignation de
        l'intervention (``technicien_assigne``) — l'assignation consignée à
        la planification (``assigner_technicien``, PLAN T1.4-k) ou, si elle
        est plus récente, le technicien de la transition ``en_route``
        (cf. ``transitionner``/PRD §4) — ``None`` tant qu'aucun n'existe.
        Avant T1.4-k, seul ``en_route`` le portait : une intervention
        planifiée n'était encore à personne.
      - ``fenetre_planifiee`` : TOUJOURS ``None`` aujourd'hui. La cédule
        choisie par ``m4_planifier_intervention`` (``cedule.generer_cedule``)
        est une fonction PURE, sans registre — son résultat est rendu à
        l'appelant de cet outil-là, jamais écrit à un maillon. Le registre ne
        porte donc structurellement aucune fenêtre à ce jour ; la persister
        est un changement d'état de machine hors de portée de ce point
        (PLAN T1.4-e2, « ce qui reste »).

    Args:
        registre_cible: instance de Registre.
        statut: None (toutes les interventions) ou un état parmi ETATS.

    Returns:
        Liste de dicts {intervention_id, statut, lead_id, type_travaux,
        devis_id, technicien_assigne, fenetre_planifiee}, triée par
        intervention_id pour un résultat déterministe. PLAN T0.13-b : pour une
        intervention issue d'un lead v2, la clé ``service`` REMPLACE ``type_travaux``
        (jamais les deux, jamais l'un déduit de l'autre — ``travaux_de``).

    Raises:
        ValueError: si `statut` est fourni et n'appartient pas à ETATS.
    """
    if statut is not None and statut not in ETATS:
        raise ValueError("statut inconnu")

    inscriptions = {}
    for maillon in registre_cible.lire():
        if maillon["type_entree"] != TYPE_INSCRIPTION:
            continue
        iid = maillon["intervention_id"]
        if iid not in inscriptions:
            inscriptions[iid] = maillon

    resultat = []
    for iid, inscription in inscriptions.items():
        statut_iid = statut_courant(registre_cible, iid)
        if statut is not None and statut_iid != statut:
            continue
        cle_travaux, valeur_travaux = travaux_de(inscription)
        resultat.append({
            "intervention_id": iid,
            "statut": statut_iid,
            "lead_id": inscription["lead_id"],
            cle_travaux: valeur_travaux,
            "devis_id": inscription.get("devis_id"),
            "technicien_assigne": technicien_assigne(registre_cible, iid),
            "fenetre_planifiee": None,
        })
    resultat.sort(key=lambda e: e["intervention_id"])
    return resultat
