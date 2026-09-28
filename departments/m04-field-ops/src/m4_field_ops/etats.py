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
    annulee                   -> annulee (inchangé ; proche de cancelled)

``completed_pending_review``/``completed_verified`` restent, comme
``terminee`` avant elles, refusées ICI comme cible directe de
``transitionner`` (voir plus bas) : seul ``outbox.completer_intervention``
les écrit, dans le MÊME maillon que le WCT (CA-M4-11). Toute autre tentative
de cible produit une transition illégale nommée (REJ-TRANSITION-ILLEGALE).
"""

import copy
from . import cedule
from . import contrats
from . import horodatage
from . import verdicts
from . import encodage
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
)

TYPE_INSCRIPTION = "intervention_inscrite"
TYPE_TRANSITION = "transition_statut"

__all__ = [
    "ETATS",
    "ETATS_TERMINAUX",
    "MOTIFS_REPORT",
    "TRANSITIONS_AUTORISEES",
    "TYPE_INSCRIPTION",
    "TYPE_TRANSITION",
    "statut_courant",
    "inscrire_intervention",
    "transitionner",
    "lister_interventions",
]

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
        contrat: dict validé par contrats.valider_entree.
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
    maillon = {
        "type_entree": TYPE_INSCRIPTION,
        "intervention_id": intervention_id,
        "lead_id": copy.deepcopy(contrat["lead_id"]),
        "conversation_id": copy.deepcopy(contrat["conversation_id"]),
        "type_travaux": copy.deepcopy(contrat["type_travaux"]),
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


def transitionner(
    intervention_id, statut_cible, registre_cible, horodatage_arg, motif=None,
    assignation=None,
):
    """
    Effectue une transition d’état pour une intervention existante.

    Args:
        intervention_id: identifiant de l’intervention.
        statut_cible: état visé (doit appartenir à ETATS).
        registre_cible: instance de Registre.
        horodatage_arg: horodatage chaîne (RFC 3339 avec fuseau).
        motif: obligatoire pour un report, interdit sinon.
        assignation: obligatoire pour planifiee -> en_route (PRD §4 : cette
            transition est « conditionnée à l’assignation effective d’un
            technicien et au pointage de départ du dépôt » — le présent
            horodatage validé EST ce pointage de départ ; ``assignation``
            en fournit la seconde moitié, l’identité du technicien). Interdit
            pour toute autre cible, comme ``motif`` l’est hors report.

    Returns:
        (accusé, None) en cas de succès, ou (None, verdict) en cas d’échec.
    """
    # 1. Horodatage
    try:
        horodatage.valider_horodatage(horodatage_arg)
    except ValueError:
        return None, verdicts.construire_verdict("REJ-HORODATAGE-INVALIDE")

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
    if statut_cible == "en_route":
        # Preuve de terrain persistée : pointage.py vérifie l'IDENTITÉ du
        # technicien qui pointe (arrivée/départ) contre CE champ, plutôt que
        # la seule déclaration non vérifiée de l'appelant (voir pointage.py).
        maillon["technicien_id"] = assignation["technicien_id"]

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
      - ``technicien_assigne`` : le ``technicien_id`` de la DERNIÈRE transition
        ``en_route`` de l'intervention (seul endroit où ce fait entre au
        registre, cf. ``transitionner``/PRD §4) — ``None`` tant qu'aucune
        n'a eu lieu.
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
        intervention_id pour un résultat déterministe.

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
        resultat.append({
            "intervention_id": iid,
            "statut": statut_iid,
            "lead_id": inscription["lead_id"],
            "type_travaux": inscription["type_travaux"],
            "devis_id": inscription.get("devis_id"),
            "technicien_assigne": _technicien_assigne_durable(registre_cible, iid),
            "fenetre_planifiee": None,
        })
    resultat.sort(key=lambda e: e["intervention_id"])
    return resultat


def _technicien_assigne_durable(registre_cible, intervention_id):
    """``technicien_id`` de la DERNIÈRE transition ``en_route`` de cette intervention dans le
    registre, ou ``None`` si elle n'a jamais atteint ``en_route`` (T1.4-e2). Historique, pas un
    statut d'assignation courante : un report ou une annulation ultérieurs laissent ce champ tel
    quel (le fait « qui a été envoyé » reste vrai même si le chantier a ensuite été reporté), à
    lire aux côtés de ``statut`` pour l'image complète — même discipline que
    ``m4_field_ops.outils._depuis_pending_review``."""
    technicien = None
    for maillon in registre_cible.lire():
        if (maillon.get("type_entree") == TYPE_TRANSITION
                and maillon.get("intervention_id") == intervention_id
                and maillon.get("statut") == "en_route"):
            technicien = maillon.get("technicien_id")
    return technicien
