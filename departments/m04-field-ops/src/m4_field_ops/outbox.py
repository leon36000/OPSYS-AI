"""
Module outbox transactionnel – M4-S008.

Contient le Work Completion Trigger, le seul chemin d'écriture vers l'état
``terminee``, garantissant qu'un seul maillon composite porte à la fois la
transition et le wct.  Fournit également les fonctions de lecture, de vérification
d'invariants, la garde statique d'unicité d'écriture et un consommateur de
référence idempotent.

PLAN T1.3-b ajoute le TROISIÈME et dernier chemin d'écriture d'un statut de complétion,
``resoudre_revue_completion`` : la revue HUMAINE d'une complétion ``completed_pending_review``
(vérifiée -> ``completed_verified``, ou correction NOMMÉE -> ``completed_pending_review``, un
nouveau maillon d'audit sans jamais rouvrir le chantier). Comme ``confirmer_verification``, ce
module reste pur (aucune identité, aucun rôle) : la signature humaine appartient au socle
(``opsys.approbations``), que l'outil qui l'enveloppe (``outils.py``) déclare au niveau N4.
``enregistrer_signal_variance``/``dernier_signal_variance`` tracent, dans le registre de M4
lui-même, le signal ``m6.variance_chantier`` reçu quand il ne mène PAS à une vérification
automatique — pour que ``attentes()`` (file du propriétaire) puisse l'afficher sans deviner.
"""

import ast
import copy
from datetime import datetime
from pathlib import Path

from . import encodage, etats, horodatage, pointage, verdicts

# --------------------------------------------------------------------- constantes
# L'ordre exact des tuples ci-dessous fait partie du contrat Ratifié WorkCompletionTriggerV1.
CONSOMMATEURS_CIBLES = ("M6", "M5", "M2", "M7", "M8", "M10")

CHAMPS_WCT = (
    "wct_id", "intervention_id", "lead_id", "technicien_id", "horodatage_completion",
    "fix_gps_completion", "duree_reelle_minutes", "ecart_signale", "revue_id",
    "hash_maillon", "consommateurs_cibles", "devis_id", "statut",
)

# T1.2-f : champs OPTIONNELS du WCT/événement publié (catalogue socle,
# src/opsys/evenements/catalogue/m4.travaux_termines.json) — JAMAIS dans CHAMPS_WCT : ce
# contrat requis reste figé à ses 13 clés (M6/M10 en gardent chacun une copie épinglée,
# ``valider_wct``, qui refuse toute clé « inattendue » : un consommateur qui n'a pas encore
# appris à filtrer ces nouvelles clés optionnelles doit les recevoir seulement là où il sait
# déjà les ignorer — cf. m10_memoire.outils._recevoir_travaux_termines, déjà écrit ainsi).
# Présents SEULEMENT quand M4 les connaît réellement :
#   - ``type_travaux`` : tiré de l'inscription (contrat LeadQualifie gelé), jamais deviné ;
#   - les quatre autres : des faits du CLIENT (Loi 25), acceptés par
#     ``m4_completer_intervention`` SEULEMENT pendant un appel d'appareil (voir outils.py).
# ``ville`` N'EST PAS dans ce tuple : M4 ne connaît la ville qu'au travers de
# ``ville_tokenisee`` (registre immuable, Architecture §2 — docs/bmad/03-ARCHITECTURE.md ;
# invariant testé par test_aucune_ville_en_clair_dans_le_registre). La révéler en clair, même
# dans le WCT, romprait cet invariant Loi 25 déjà prouvé ; le champ reste donc
# structurellement absent, exactement comme le catalogue (optionnel) le permet.
CHAMPS_WCT_OPTIONNELS = (
    "type_travaux", "photos", "description_factuelle", "consentement_marketing", "client_satisfait",
)

# Sentinelle interne : distincte de ``None``, qui est une valeur VALIDE pour
# ``client_satisfait`` (« non recueilli », catalogue). Un paramètre resté à cette valeur par
# défaut signifie « l'appelant n'a rien fourni », jamais « fourni comme vide ».
NON_FOURNI = object()

CLE_WCT = "wct"

# T1.1-b#2 : les deux SEULES cibles que la complétion peut écrire (ex-``terminee``
# scindée selon ``ecart_detecte``, jamais déduit). Centralisé ici : c'est la
# même paire que ``completer_intervention`` calcule, que ``garde_ecriture_unique``
# protège et que ``verifier_invariants_outbox`` reconnaît comme terminale-WCT.
STATUTS_COMPLETION = ("completed_pending_review", "completed_verified")

# PLAN T1.3-b : décisions possibles de la revue HUMAINE d'une complétion
# ``completed_pending_review`` (``resoudre_revue_completion`` ci-dessous). ``verifiee`` confirme
# (même transition que ``confirmer_verification``, mais décidée par une personne plutôt que
# déduite d'un signal M6 sans dépassement) ; ``correction`` NOMME un problème sans jamais rouvrir
# le chantier (le WCT déjà publié aux 6 départements consommateurs reste le fait déclaré).
DECISIONS_REVUE = ("verifiee", "correction")

# PLAN T1.3-b : type d'entrée de la trace, dans le registre de M4, d'un signal m6.variance_chantier
# reçu qui ne mène PAS à une vérification automatique (``confirmer_verification``) — pour que
# ``attentes()`` (outils.py, file du propriétaire) puisse l'afficher sans jamais le deviner.
TYPE_SIGNAL_VARIANCE = "variance_m6_recue"

# --------------------------------------------------------------------- helpers
def _extraire_lead_id(registre_cible, intervention_id):
    """Renvoie le ``lead_id`` du maillon d'inscription de l'intervention."""
    for maillon in registre_cible.lire():
        if (maillon.get("type_entree") == etats.TYPE_INSCRIPTION
                and maillon.get("intervention_id") == intervention_id):
            return maillon["lead_id"]
    return None


def _extraire_devis_id(registre_cible, intervention_id):
    """Renvoie le ``devis_id`` (T1.1-b#1) du maillon d'inscription, ou None si
    l'intervention a été inscrite sans devis (M3 n'alimente pas encore tous
    les chemins d'entrée) — jamais une valeur inventée, symétrique à
    ``_extraire_lead_id``. Porté TEL QUEL par le WCT."""
    for maillon in registre_cible.lire():
        if (maillon.get("type_entree") == etats.TYPE_INSCRIPTION
                and maillon.get("intervention_id") == intervention_id):
            return maillon.get("devis_id")
    return None


def _extraire_type_travaux(registre_cible, intervention_id):
    """Renvoie le ``type_travaux`` (T1.2-f) du maillon d'inscription, ou None si absent (un
    registre écrit avant ce champ, ou une intervention introuvable) — jamais deviné, symétrique
    à ``_extraire_devis_id``. Porté TEL QUEL par le WCT quand connu (catalogue, champ optionnel :
    CHAMPS_WCT_OPTIONNELS)."""
    for maillon in registre_cible.lire():
        if (maillon.get("type_entree") == etats.TYPE_INSCRIPTION
                and maillon.get("intervention_id") == intervention_id):
            return maillon.get("type_travaux")
    return None


def _dernier_depart(registre_cible, intervention_id):
    """Renvoie le dernier pointage de départ (technicien_id, horodatage, latitude, longitude)."""
    dernier = None
    for maillon in registre_cible.lire():
        if (maillon.get("type_entree") == pointage.TYPE_POINTAGE
                and maillon.get("intervention_id") == intervention_id
                and maillon.get("action") == "depart"):
            dernier = maillon
    if dernier is None:
        return None
    return (dernier.get("technicien_id"),
            dernier.get("horodatage"),
            dernier.get("latitude"),
            dernier.get("longitude"))


# --------------------------------------------------------------------- API publique
def calculer_minutes_pause(registre_cible, intervention_id):
    """
    Somme les pauses (T1.1-c#1) d'une intervention, en minutes.

    Règle DÉTERMINISTE, symétrique à ``calculer_duree_reelle`` : chaque
    ``pause_debut`` se referme sur le PROCHAIN ``pause_fin`` qui le suit dans
    l'ordre du registre (ordre d'écriture = ordre chronologique, CA-M4-07). Les
    pauses sont SANS EFFET sur le statut (``pointage.enregistrer_pointage``) —
    ce calcul est la seule chose qui les rend visibles, ici et dans le
    brouillon de temps (``temps.produire_brouillon_temps``).

    Returns:
        (minutes, None) ou (None, code_verdict). Fail-closed : une pause
        ouverte sans ``pause_fin``, ou un ``pause_fin`` sans ``pause_debut``
        préalable, ne comptent JAMAIS pour 0 minute (valeur inventée) — elles
        bloquent avec un verdict nommé. Aucune pause : 0 minute, légitimement
        (une intervention peut n'avoir jamais fait de pause).
    """
    pointages = [
        m for m in registre_cible.lire()
        if m.get("type_entree") == pointage.TYPE_POINTAGE
        and m.get("intervention_id") == intervention_id
        and m.get("action") in ("pause_debut", "pause_fin")
    ]

    total_minutes = 0
    debut_pause_ouverte = None
    for p in pointages:
        if p["action"] == "pause_debut":
            if debut_pause_ouverte is not None:
                return None, "REJ-CONTRAT-INVALIDE"
            debut_pause_ouverte = datetime.fromisoformat(p["horodatage"])
        else:  # pause_fin
            if debut_pause_ouverte is None:
                return None, "REJ-CONTRAT-INVALIDE"
            dt_fin = datetime.fromisoformat(p["horodatage"])
            total_minutes += int((dt_fin - debut_pause_ouverte).total_seconds() // 60)
            debut_pause_ouverte = None
    if debut_pause_ouverte is not None:
        return None, "REJ-CONTRAT-INVALIDE"

    return total_minutes, None


def calculer_minutes_deplacement(registre_cible, intervention_id):
    """
    Calcule le temps de déplacement (T1.1-c#2) : de la transition planifiee ->
    en_route jusqu'au PREMIER pointage d'arrivée, DISTINCT du temps sur site
    (``calculer_duree_reelle``).

    Symétrique à ``calculer_duree_reelle`` : s'il existe plusieurs transitions
    en_route (report puis replanification), la DERNIÈRE fait foi — même
    convention que ``pointage.enregistrer_pointage`` pour retrouver le
    technicien réellement envoyé.

    Returns:
        (minutes, None) ou (None, code_verdict). Fail-closed : aucune
        transition en_route, aucune arrivée, ou arrivée ANTÉRIEURE au départ
        déclaré. Aucune valeur conventionnelle n'est jamais substituée.
    """
    horodatage_en_route = None
    for maillon in registre_cible.lire():
        if (maillon.get("type_entree") == etats.TYPE_TRANSITION
                and maillon.get("intervention_id") == intervention_id
                and maillon.get("statut") == "en_route"):
            horodatage_en_route = maillon.get("horodatage")
    if horodatage_en_route is None:
        return None, "REJ-CONTRAT-INVALIDE"

    arrivees = [
        m for m in registre_cible.lire()
        if m.get("type_entree") == pointage.TYPE_POINTAGE
        and m.get("intervention_id") == intervention_id
        and m.get("action") == "arrivee"
    ]
    if not arrivees:
        return None, "REJ-CONTRAT-INVALIDE"

    dt_route = datetime.fromisoformat(horodatage_en_route)
    dt_arr = min(datetime.fromisoformat(p["horodatage"]) for p in arrivees)
    if dt_arr < dt_route:
        return None, "REJ-HORODATAGE-ANTERIEUR"

    return int((dt_arr - dt_route).total_seconds() // 60), None


def calculer_duree_reelle(registre_cible, intervention_id):
    """
    Calcule la durée réelle de l'intervention à partir des pointages de terrain.

    Args:
        registre_cible: instance de Registre.
        intervention_id: identifiant de l'intervention.

    Règle DÉTERMINISTE : du PREMIER pointage d'arrivée au DERNIER pointage de
    départ, MOINS les pauses (T1.1-c#1 : deux pauses de 15 min réduisent la
    durée réelle de 30 min — ``calculer_minutes_pause`` ci-dessus). La règle
    « exactement une paire » a été écartée après mesure : une anomalie de
    pointage produit LÉGITIMEMENT un second départ (départ incohérent ->
    revue), donc exiger une paire unique rendait toute intervention arbitrée
    IMPOSSIBLE à compléter — le chemin de revue de CA-M4-10 devenait inatteignable.

    Distinct du temps de DÉPLACEMENT (``calculer_minutes_deplacement``,
    T1.1-c#2) : celui-ci reste hors de ce calcul, comme avant — déplacement et
    travail restent deux nombres séparés, seule leur somme, prouvée par les
    tests existants sur des fixtures où le déplacement est nul, égale la durée
    globale.

    Returns:
        (minutes, None) ou (None, code_verdict). Fail-closed : aucune arrivée,
        aucun départ, dernier départ ANTÉRIEUR à la première arrivée, ou pauses
        mal formées (voir ``calculer_minutes_pause``). Aucune valeur
        conventionnelle n'est jamais substituée.
    """
    pointages = []
    for maillon in registre_cible.lire():
        if (maillon.get("type_entree") == pointage.TYPE_POINTAGE
                and maillon.get("intervention_id") == intervention_id):
            pointages.append(maillon)

    arrivees = [p for p in pointages if p.get("action") == "arrivee"]
    departs = [p for p in pointages if p.get("action") == "depart"]

    if not arrivees or not departs:
        return None, "REJ-CONTRAT-INVALIDE"

    # Premier arrivée / dernier départ : l'ordre du registre est l'ordre
    # d'écriture, et les horodatages sont non décroissants par pointage (CA-M4-07).
    dt_arr = min(datetime.fromisoformat(p["horodatage"]) for p in arrivees)
    dt_dep = max(datetime.fromisoformat(p["horodatage"]) for p in departs)

    if dt_dep < dt_arr:
        return None, "REJ-HORODATAGE-ANTERIEUR"

    minutes_pause, code_pause = calculer_minutes_pause(registre_cible, intervention_id)
    if minutes_pause is None:
        return None, code_pause

    minutes = int((dt_dep - dt_arr).total_seconds() // 60) - minutes_pause
    return minutes, None


def completer_intervention(
    intervention_id, horodatage_arg, registre_cible, *, ecart_detecte, revue_id=None,
    photos=NON_FOURNI, description_factuelle=NON_FOURNI,
    consentement_marketing=NON_FOURNI, client_satisfait=NON_FOURNI,
):
    """
    Réalise la complétion et émet le WCT en une unique écriture.

    Args:
        intervention_id: identifiant de l'intervention à terminer.
        horodatage_arg: horodatage RFC 3339 avec fuseau.
        registre_cible: instance de Registre.
        ecart_detecte: booléen EXPLICITE (mot-clé obligatoire, aucun défaut,
            T1.1-b#2), JAMAIS déduit par cette fonction d'un autre signal
            (ex. la seule présence de ``revue_id``) : l'appelant décide, cette
            fonction applique. Détermine l'ISSUE de la complétion :
                vrai  -> statut completed_pending_review
                faux  -> statut completed_verified
            (DEFINITION-PRODUIT.md §6). Porté tel quel dans wct.ecart_signale.
        revue_id: éventuel identifiant de la demande de revue ayant déclenché
            la complétion. S'il est fourni, il DOIT correspondre à un écart
            métier déjà confirmé : ``ecart_detecte`` doit alors valoir vrai
            (cohérence vérifiée ci-dessous) — une revue validée ne peut pas
            prétendre qu'aucun écart n'a été détecté.
        photos, description_factuelle, consentement_marketing, client_satisfait
            (T1.2-f, CHAMPS_WCT_OPTIONNELS) : des faits du CLIENT, restés à la
            sentinelle ``NON_FOURNI`` par défaut (« l'appelant n'a rien fourni »,
            distinct d'un ``None`` explicite — significatif pour
            ``client_satisfait``, catalogue ``[boolean, null]``, « non recueilli »).
            Cette fonction ne vérifie QUE leur FORME si fournis (fail-closed) ;
            savoir SI l'appelant a le droit de les fournir (appel d'appareil,
            Loi 25) est une décision de ``outils.py`` — ce module reste pur,
            sans import ``opsys``, et ne la prend jamais.

    Returns:
        (accusé, None) ou (None, verdict).
    """
    # 1. Horodatage valide
    try:
        horodatage.valider_horodatage(horodatage_arg)
    except ValueError:
        return None, verdicts.construire_verdict("REJ-HORODATAGE-INVALIDE")

    # 2. ecart_detecte : booléen STRICT, jamais une valeur approchante (int,
    # None...) qu'on interpréterait à sa place — ce serait déduire.
    if type(ecart_detecte) is not bool:
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            detail="ecart_detecte doit être un booléen explicite (jamais déduit)",
        )
    statut_cible = "completed_pending_review" if ecart_detecte else "completed_verified"

    # 2 bis. T1.2-f : forme des champs CLIENT optionnels, SI fournis (NON_FOURNI sinon) —
    # fail-closed, jamais une valeur mal typée acceptée silencieusement.
    if consentement_marketing is not NON_FOURNI and type(consentement_marketing) is not bool:
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            detail="consentement_marketing doit être un booléen explicite (jamais déduit)",
        )
    if (client_satisfait is not NON_FOURNI and client_satisfait is not None
            and type(client_satisfait) is not bool):
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            detail="client_satisfait doit être un booléen ou null explicite (« non recueilli »)",
        )
    if photos is not NON_FOURNI and (
        not isinstance(photos, list) or not all(isinstance(p, str) for p in photos)
    ):
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            detail="photos doit être une liste de chaînes (références, jamais de binaire)",
        )
    if description_factuelle is not NON_FOURNI and not isinstance(description_factuelle, str):
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            detail="description_factuelle doit être une chaîne",
        )

    # 3. Statut courant
    courant = etats.statut_courant(registre_cible, intervention_id)
    if courant is None:
        return None, verdicts.construire_verdict(
            "REJ-TRANSITION-ILLEGALE",
            detail="intervention inexistante",
        )

    # 4. La table des transitions reste l'autorité sur la légalité théorique
    if (courant, statut_cible) not in etats.TRANSITIONS_AUTORISEES:
        return None, verdicts.construire_verdict(
            "REJ-TRANSITION-ILLEGALE",
            statut=courant,
            detail=f"{courant} -> {statut_cible}",
        )

    # 5. Revue_id (si fourni) doit exister ET impliquer un écart détecté :
    # une demande d'écart métier VALIDÉE (le seul chemin qui fournit revue_id,
    # cf. ecarts.resoudre_demande) constate justement qu'un écart existe —
    # prétendre ecart_detecte=faux en même temps serait une incohérence que le
    # fail-closed doit fermer, pas seulement ignorer.
    if revue_id is not None:
        trouve = False
        for maillon in registre_cible.lire():
            if (maillon.get("type_entree") == pointage.TYPE_DEMANDE_REVUE
                    and maillon.get("demande_id") == revue_id):
                trouve = True
                break
        if not trouve:
            return None, verdicts.construire_verdict(
                "REJ-CONTRAT-INVALIDE",
                detail="revue introuvable",
            )
        if not ecart_detecte:
            return None, verdicts.construire_verdict(
                "REJ-CONTRAT-INVALIDE",
                detail="revue_id fourni implique ecart_detecte=true",
            )

    # 6. Durée réelle
    duree_minutes, code_duree = calculer_duree_reelle(registre_cible, intervention_id)
    if duree_minutes is None:
        return None, verdicts.construire_verdict(
            code_duree,
            detail="durée réelle indéterminable",
        )

    # 7. Extraction des données terrain (ne fait pas confiance à l'appelant)
    lead_id = _extraire_lead_id(registre_cible, intervention_id)
    if lead_id is None:
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            detail="lead_id introuvable dans le registre",
        )
    # T1.1-b#1 : porté TEL QUEL, jamais redemandé ni recalculé — None si
    # l'intervention a été inscrite sans devis (M3 n'alimente pas encore tous
    # les chemins d'entrée).
    devis_id = _extraire_devis_id(registre_cible, intervention_id)
    # T1.2-f : porté TEL QUEL quand connu, jamais deviné — voir CHAMPS_WCT_OPTIONNELS.
    type_travaux = _extraire_type_travaux(registre_cible, intervention_id)

    depart = _dernier_depart(registre_cible, intervention_id)
    if depart is None:
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            detail="pointage de départ absent",
        )
    technicien_id, horodatage_depart, lat, lon = depart

    # 8. Partie transition SEULE (sans le wct)
    partie_transition = {
        "type_entree": etats.TYPE_TRANSITION,
        "intervention_id": intervention_id,
        "statut": statut_cible,
        "statut_precedent": courant,
        "horodatage": horodatage_arg,
    }

    # 9. Empreinte de la partie transition (jamais circulaire car le wct n'y figure pas)
    hash_maillon = encodage.empreinte(partie_transition)

    # 10. Identifiant du wct
    wct_id = encodage.empreinte("wct", intervention_id, horodatage_arg)

    # 11. Assemblage du wct
    wct = {
        "wct_id": wct_id,
        "intervention_id": intervention_id,
        "lead_id": lead_id,
        "technicien_id": technicien_id,
        "horodatage_completion": horodatage_depart,
        "fix_gps_completion": {"latitude": lat, "longitude": lon},
        "duree_reelle_minutes": duree_minutes,
        "ecart_signale": ecart_detecte,
        "revue_id": revue_id,
        "hash_maillon": hash_maillon,
        "consommateurs_cibles": list(CONSOMMATEURS_CIBLES),
        "devis_id": devis_id,
        "statut": statut_cible,
    }
    # T1.2-f (CHAMPS_WCT_OPTIONNELS) : ajoutés SEULEMENT quand connus/fournis — jamais une clé
    # absente traitée comme null, jamais une clé null traitée comme absente (client_satisfait).
    if type_travaux is not None:
        wct["type_travaux"] = type_travaux
    if photos is not NON_FOURNI:
        wct["photos"] = photos
    if description_factuelle is not NON_FOURNI:
        wct["description_factuelle"] = description_factuelle
    if consentement_marketing is not NON_FOURNI:
        wct["consentement_marketing"] = consentement_marketing
    if client_satisfait is not NON_FOURNI:
        wct["client_satisfait"] = client_satisfait

    # 12. Maillon composite : exactement UN appel à ajouter
    maillon = copy.deepcopy(partie_transition)
    maillon[CLE_WCT] = wct
    ligne_id = registre_cible.ajouter(maillon)

    # 13. Accusé
    accuse = {
        "wct_id": wct_id,
        "intervention_id": intervention_id,
        "ligne_id": ligne_id,
        "statut": statut_cible,
        "hash_maillon": hash_maillon,
        "duree_reelle_minutes": duree_minutes,
        "ecart_signale": ecart_detecte,
        "tete_chaine": registre_cible.tete(),
    }
    return accuse, None


def confirmer_verification(intervention_id, horodatage_arg, registre_cible, *, evenement_id_variance):
    """
    Deuxième et DERNIER chemin d'écriture d'un statut de complétion (avec
    ``completer_intervention``) : fait passer une intervention de
    ``completed_pending_review`` à ``completed_verified`` — PLAN T1.2, point 4.

    Le code calcule, jamais un agent (T1.1-b) : cette fonction n'est appelée que par le
    consommateur de ``m6.variance_chantier`` (``outils.py``), jamais par un outil d'agent.
    Elle n'écrit RIEN d'autre que ce seul statut : les preuves de complétion
    (PreuvesCompletion) sont déjà garanties par ``completer_intervention`` (T1.1-b#3, la
    complétion n'existe pas sans elles) — aucune re-vérification à faire ici.

    Contrairement à ``completer_intervention``, cette transition n'émet PAS de WCT (le WCT
    existe déjà, écrit à la complétion) : le maillon de transition ne porte jamais la clé
    ``CLE_WCT`` — ``garde_ecriture_unique`` le vérifie. Elle bypasse volontairement
    ``etats.transitionner`` (qui refuse ``completed_verified`` comme cible, CA-M4-11) pour
    la même raison que ``completer_intervention`` le bypasse déjà : la table des
    transitions dit ce qui est LÉGAL, ce module seul dit qui ÉCRIT.

    Args:
        intervention_id: identifiant de l'intervention à vérifier.
        horodatage_arg: horodatage RFC 3339 avec fuseau — TOUJOURS celui du WCT d'origine
            (``m6.variance_chantier.horodatage_completion``, porté tel quel depuis
            ``m4.travaux_termines``), jamais une horloge consultée ici (``garde_absence_horloge``
            interdit tout appel d'horloge dans ce paquet) : la vérification date le MÊME
            instant que la complétion qu'elle confirme, elle ne crée pas un nouveau fait.
        registre_cible: instance de Registre.
        evenement_id_variance: ``evenement_id`` de l'événement ``m6.variance_chantier`` qui
            justifie la décision (mot-clé obligatoire, jamais None) — tracé sur le maillon
            pour que l'audit retrouve la base exacte de la transition (PLAN T1.2, point 4).

    Returns:
        (accusé, None) ou (None, verdict). Idempotent : si l'intervention est DÉJÀ
        ``completed_verified`` (redélivrance du même événement, ou concurrence), AUCUNE
        écriture n'a lieu — l'accusé porte ``deja_verifie=True``, ce n'est jamais un refus
        (une redélivrance n'est pas une erreur, CA-M4-11 / PLAN T1.2).
    """
    if not isinstance(evenement_id_variance, str) or not evenement_id_variance:
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE", detail="evenement_id_variance requis"
        )

    courant = etats.statut_courant(registre_cible, intervention_id)

    # Idempotence AVANT toute autre validation : une redélivrance du même événement ne doit
    # jamais dépendre de la fraîcheur de l'horodatage rejoué ni de quoi que ce soit d'autre.
    if courant == "completed_verified":
        return {
            "intervention_id": intervention_id,
            "statut": "completed_verified",
            "deja_verifie": True,
            "tete_chaine": registre_cible.tete(),
        }, None

    if courant != "completed_pending_review":
        return None, verdicts.construire_verdict(
            "REJ-TRANSITION-ILLEGALE",
            statut=courant,
            detail=(
                "confirmer_verification n'accepte que completed_pending_review -> "
                "completed_verified"
            ),
        )

    try:
        horodatage.valider_horodatage(horodatage_arg)
    except ValueError:
        return None, verdicts.construire_verdict("REJ-HORODATAGE-INVALIDE")

    maillon = {
        "type_entree": etats.TYPE_TRANSITION,
        "intervention_id": intervention_id,
        "statut": "completed_verified",
        "statut_precedent": courant,
        "horodatage": horodatage_arg,
        "evenement_id_variance": evenement_id_variance,
    }
    ligne_id = registre_cible.ajouter(maillon)

    return {
        "intervention_id": intervention_id,
        "statut": "completed_verified",
        "deja_verifie": False,
        "ligne_id": ligne_id,
        "evenement_id_variance": evenement_id_variance,
        "tete_chaine": registre_cible.tete(),
    }, None


def resoudre_revue_completion(
    intervention_id, decision, horodatage_arg, registre_cible, *, motif,
):
    """
    TROISIÈME et DERNIER chemin d'écriture d'un statut de complétion (avec
    ``completer_intervention`` et ``confirmer_verification``) : la revue HUMAINE d'une
    complétion ``completed_pending_review`` (PLAN T1.3-b), jamais un agent seul.

    Le code calcule, jamais un agent (T1.1-b) : cette fonction reste pure, elle ne connaît ni
    personne ni rôle. La signature humaine (« qui », « quel rôle ») appartient au SOCLE
    (``opsys.approbations.decider``, ADR-0009 §5) : l'outil qui enveloppe cette fonction
    (``m4_field_ops.outils.resoudre_revue_completion``) déclare le niveau N4, ce qui force
    TOUTE demande à passer par la file d'approbation du socle avant exécution — un agent peut
    PROPOSER une décision, jamais l'exécuter lui-même. ``motif`` (mot-clé obligatoire, aucun
    défaut) est le contenu MÉTIER de la décision : pourquoi elle vérifie, ou ce qu'elle nomme à
    corriger — distinct du motif d'approbation que le socle enregistre séparément sur sa propre
    demande (``APPROBATIONS.motif_decision``).

    Args:
        intervention_id: identifiant de l'intervention, actuellement ``completed_pending_review``
            (sinon REJ-TRANSITION-ILLEGALE : cette fonction n'accepte que cette entrée, comme
            ``confirmer_verification``).
        decision: l'une de ``DECISIONS_REVUE`` :
            ``verifiee``   -> completed_verified (même transition que ``confirmer_verification``,
                              décidée par une personne). AUCUN wct : il vit déjà sur le premier
                              maillon (complétion).
            ``correction`` -> completed_pending_review (self-loop : même statut, NOUVEAU maillon
                              d'audit portant le motif). Ne rouvre JAMAIS le chantier (aucune
                              transition FSM vers sur_site/en_revue, aucun nouveau WCT) : le fait
                              déjà publié aux 6 départements consommateurs (``m4.travaux_termines``)
                              reste ce qu'il est ; ``motif`` documente ce qui doit être corrigé EN
                              DEHORS de cette machine à états (ex. une correction d'inventaire M6),
                              jamais deviné ici.
        horodatage_arg: horodatage RFC 3339 avec fuseau de la décision.
        registre_cible: instance de Registre.
        motif: chaîne non vide obligatoire — la décision cite TOUJOURS pourquoi (personne, rôle,
            motif : les deux premiers sont ceux de l'approbation du socle, le motif est ici).

    Returns:
        (accusé, None) ou (None, verdict). Fail-closed : ``decision`` hors ``DECISIONS_REVUE``,
        motif vide, horodatage invalide, ou intervention hors ``completed_pending_review`` sont
        tous des refus nommés — rien n'est écrit. Contrairement à ``confirmer_verification``
        (redélivrance d'événement), cette fonction n'est PAS idempotente : une seconde décision
        sur une intervention déjà résolue par la première (``verifiee``) est un refus nommé, pas
        un no-op silencieux — une décision humaine tardive doit être visible, jamais masquée.
    """
    try:
        horodatage.valider_horodatage(horodatage_arg)
    except ValueError:
        return None, verdicts.construire_verdict("REJ-HORODATAGE-INVALIDE")

    if decision not in DECISIONS_REVUE:
        return None, verdicts.construire_verdict(
            "REJ-ENUM-INVALIDE", detail=f"decision doit être l'une de {DECISIONS_REVUE}"
        )

    if not isinstance(motif, str) or not motif.strip():
        return None, verdicts.construire_verdict(
            "REJ-CHAMP-VIDE", detail="motif requis : la décision cite toujours pourquoi"
        )

    courant = etats.statut_courant(registre_cible, intervention_id)
    if courant != "completed_pending_review":
        return None, verdicts.construire_verdict(
            "REJ-TRANSITION-ILLEGALE",
            statut=courant,
            detail="resoudre_revue_completion n'accepte que completed_pending_review en entrée",
        )

    statut_cible = "completed_verified" if decision == "verifiee" else "completed_pending_review"
    maillon = {
        "type_entree": etats.TYPE_TRANSITION,
        "intervention_id": intervention_id,
        "statut": statut_cible,
        "statut_precedent": courant,
        "horodatage": horodatage_arg,
        "decision_revue": decision,
        "motif_revue": motif.strip(),
    }
    ligne_id = registre_cible.ajouter(maillon)

    return {
        "intervention_id": intervention_id,
        "statut": statut_cible,
        "decision": decision,
        "ligne_id": ligne_id,
        "tete_chaine": registre_cible.tete(),
    }, None


def enregistrer_signal_variance(intervention_id, charge_variance, registre_cible):
    """
    Trace, dans le registre de M4 lui-même, qu'une charge ``m6.variance_chantier`` a été reçue
    pour cette intervention SANS mener à ``confirmer_verification`` (PLAN T1.3-b) — appelée par
    ``outils.py::_recevoir_variance_chantier`` dans la branche qui NE vérifie PAS automatiquement
    (signal critique, ou ``statut_variance`` pas encore ``evaluee``). Sans ce maillon,
    ``attentes()`` (file du propriétaire) n'aurait aucune trace DURABLE, dans le registre de M4,
    du signal M6 : le seul autre enregistrement (``opsys.evenements``/``EVENEMENTS_RECUS``)
    appartient au socle, jamais lu depuis ce paquet (M4 reste pur du point de vue de son propre
    registre — c'est ``outils.py``, l'adaptateur, seul, qui a lu la charge sur le bus).

    Ne DÉCIDE rien : l'appelant a déjà décidé de ne PAS appeler ``confirmer_verification``. Porte
    tel quel les champs utiles au résumé de l'attente (jamais recalculés) : ``statut_variance``,
    ``signal_critique``, ``seuil_pourcentage``, ``evenement_id`` de la charge M6 d'origine
    (catalogue ``opsys.evenements.catalogue.m6.variance_chantier``).

    Returns:
        ligne_id (str) du maillon écrit.
    """
    maillon = {
        "type_entree": TYPE_SIGNAL_VARIANCE,
        "intervention_id": intervention_id,
        "horodatage": charge_variance["horodatage_completion"],
        "evenement_id_variance": charge_variance["evenement_id"],
        "statut_variance": charge_variance["statut_variance"],
        "signal_critique": charge_variance["signal_critique"],
        "seuil_pourcentage": charge_variance["seuil_pourcentage"],
    }
    return registre_cible.ajouter(maillon)


def dernier_signal_variance(registre_cible, intervention_id):
    """
    Dernier signal ``m6.variance_chantier`` connu pour cette intervention (PLAN T1.3-b,
    ``attentes()`` de ``outils.py``) : celui au statut ``evaluee`` s'il existe (terminal — au
    plus un par WCT, catalogue ``m6.variance_chantier``), sinon le plus récent des autres statuts
    (``prevu_absent``/``declaration_absente``/``seuil_absent``). ``None`` si M4 n'a encore rien
    reçu pour cette intervention — jamais deviné (``attentes()`` doit pouvoir dire « pas encore
    de nouvelles de M6 » plutôt que de supposer un signal absent).
    """
    candidats = [
        m for m in registre_cible.lire()
        if m.get("type_entree") == TYPE_SIGNAL_VARIANCE and m.get("intervention_id") == intervention_id
    ]
    if not candidats:
        return None
    for candidat in candidats:
        if candidat["statut_variance"] == "evaluee":
            return candidat
    return candidats[-1]


def lire_outbox(registre_cible, depuis_index=0):
    """
    Lit les WCT émis depuis un certain index (inclus) du registre.

    Args:
        registre_cible: instance de Registre.
        depuis_index: position de départ dans la liste des maillons.

    Returns:
        Liste de couples (index, wct) – copies profondes.

    Raises:
        ValueError: si depuis_index est négatif.
    """
    if depuis_index < 0:
        raise ValueError("depuis_index négatif")

    resultat = []
    for i, maillon in enumerate(registre_cible.lire()):
        if i < depuis_index:
            continue
        if CLE_WCT in maillon:
            resultat.append((i, copy.deepcopy(maillon[CLE_WCT])))
    return resultat


def verifier_invariants_outbox(registre_cible):
    """
    Vérifie l'intégrité des WCT présents dans le registre, PLUS (PLAN T1.2, point 4 ; PLAN
    T1.3-b) la cohérence des DEUX transitions de confirmation qui suivent une complétion.

    Depuis PLAN T1.2, un maillon de statut ``completed_verified`` peut être :
    - la PREMIÈRE complétion (``statut_precedent`` hors ``STATUTS_COMPLETION``, ex.
      ``sur_site``) : porte le wct, exactement comme avant (contrôles inchangés) ;
    - une CONFIRMATION AUTOMATIQUE (``statut_precedent == "completed_pending_review"``, sans
      ``decision_revue``, écrite par ``confirmer_verification`` sur un signal M6 sans
      dépassement) : ne porte JAMAIS de wct — il vit déjà sur le premier maillon de cette même
      intervention — et ne peut viser que ``completed_verified`` depuis
      ``completed_pending_review`` (la seule paire que ``confirmer_verification`` écrit).

    Depuis PLAN T1.3-b, un maillon PORTANT LA CLÉ ``decision_revue`` (écrit exclusivement par
    ``resoudre_revue_completion``, la revue HUMAINE) est une confirmation d'une autre forme, elle
    aussi sans jamais de wct :
    - ``decision_revue == "verifiee"``   : ``completed_pending_review -> completed_verified``
      (même paire que la confirmation automatique, mais décidée par une personne) ;
    - ``decision_revue == "correction"`` : ``completed_pending_review -> completed_pending_review``
      (self-loop NOMMÉ : un nouveau maillon d'audit, jamais une réouverture du chantier).

    Returns:
        (True, "") ou (False, message) en cas d'incohérence.
    """
    for maillon in registre_cible.lire():
        statut = maillon.get("statut")
        statut_precedent = maillon.get("statut_precedent")
        wct = maillon.get(CLE_WCT)
        decision_revue = maillon.get("decision_revue")
        confirmation = (
            (statut in STATUTS_COMPLETION and statut_precedent in STATUTS_COMPLETION)
            or decision_revue is not None
        )

        if confirmation:
            if wct is not None:
                return False, "maillon de confirmation porte un wct (devrait vivre sur le premier)"
            if decision_revue is not None:
                # PLAN T1.3-b : revue humaine — seules ces deux paires exactes sont légales.
                attendu = {
                    "verifiee": ("completed_pending_review", "completed_verified"),
                    "correction": ("completed_pending_review", "completed_pending_review"),
                }.get(decision_revue)
                if attendu is None or (statut_precedent, statut) != attendu:
                    return False, (
                        f"revue de complétion illégale : decision_revue={decision_revue!r} "
                        f"{statut_precedent} -> {statut}"
                    )
                continue
            if statut != "completed_verified" or statut_precedent != "completed_pending_review":
                return False, (
                    f"confirmation illégale : {statut_precedent} -> {statut} "
                    "(seule completed_pending_review -> completed_verified est permise)"
                )
            continue

        # Première complétion (l'une des deux issues T1.1-b#2) : doit porter un wct.
        if statut in STATUTS_COMPLETION:
            if wct is None:
                return False, f"maillon {statut} sans wct (index implicite)"
            # T1.2-f : le wct porte AU MOINS les 13 clés requises (CHAMPS_WCT), et JAMAIS
            # rien d'autre que celles-ci plus un sous-ensemble des optionnelles connues
            # (CHAMPS_WCT_OPTIONNELS) — toujours fermé, jamais une clé étrangère tolérée.
            cles_wct = set(wct.keys())
            cles_permises = set(CHAMPS_WCT) | set(CHAMPS_WCT_OPTIONNELS)
            if not set(CHAMPS_WCT) <= cles_wct or not cles_wct <= cles_permises:
                return False, f"wct avec clés incorrectes: {cles_wct}"
            if wct["consommateurs_cibles"] != list(CONSOMMATEURS_CIBLES):
                return False, "consommateurs_cibles du wct invalides"
            if wct["intervention_id"] != maillon.get("intervention_id"):
                return False, "wct.intervention_id # maillon.intervention_id"
            if wct["statut"] != statut:
                return False, "wct.statut # maillon.statut"

            # Recalcul du hash sur la partie transition (sans wct, ligne_id, precedent_ligne_id)
            partie = {
                k: v for k, v in maillon.items()
                if k not in (CLE_WCT, "ligne_id", "precedent_ligne_id")
            }
            recalcul = encodage.empreinte(partie)
            if wct["hash_maillon"] != recalcul:
                return False, "hash_maillon incohérent"

        # Aucun maillon non-complété ne doit porter la clé wct
        elif statut not in STATUTS_COMPLETION and wct is not None:
            return False, f"maillon non complété porte un wct (statut={statut})"

    return True, ""


#: Fonctions autorisées à écrire, chacune, LEUR forme précise de maillon de complétion
#: (PLAN T1.2, point 4 ; PLAN T1.3-b) : ``completer_intervention`` écrit le maillon composite
#: avec wct (première complétion, T1.1-b#2/CA-M4-11) ; ``confirmer_verification`` écrit
#: SEULEMENT le maillon de confirmation AUTOMATIQUE sans wct (``completed_pending_review ->
#: completed_verified``, PLAN T1.2) ; ``resoudre_revue_completion`` (PLAN T1.3-b) écrit SEULEMENT
#: le maillon de revue HUMAINE sans wct (même paire, ou le self-loop de correction nommée —
#: jamais un agent seul, la signature appartient au socle des approbations). Aucune autre
#: fonction, dans ce fichier ou ailleurs, ne peut écrire l'un de ces trois : c'est exactement ce
#: que ``garde_ecriture_unique`` vérifie ci-dessous.
_FONCTIONS_AUTORISEES_STATUT_COMPLETION = (
    "completer_intervention", "confirmer_verification", "resoudre_revue_completion",
)


def garde_ecriture_unique(chemin_source=None):
    """
    Vérification statique (par AST) qu'aucun autre module n'écrit un statut de complétion.

    Trois contrôles :
    1. Seul ``completer_intervention`` écrit un maillon portant la clé ``CLE_WCT`` (le WCT).
    2. Seules ``completer_intervention``, ``confirmer_verification`` (PLAN T1.2, point 4) et
       ``resoudre_revue_completion`` (PLAN T1.3-b) écrivent, par ``ajouter(...)``, un maillon
       dont la clé ``"statut"`` littérale vaut ``completed_pending_review`` ou
       ``completed_verified`` — ce qui couvre le maillon composite de ``completer_intervention``
       ET les maillons de confirmation, sans wct, des deux autres : les trois SEULS chemins
       d'écriture de ces statuts.
    3. Chacune de ces trois fonctions n'appelle ``ajouter`` qu'une fois (textuellement).

    Limite connue : un appel indirect (getattr, alias) échapperait à la garde, de même
    qu'une valeur ``statut`` construite dynamiquement (variable plutôt que littéral) —
    ``completer_intervention`` et ``resoudre_revue_completion`` y échappent déjà ainsi
    (``statut_cible`` est une variable dans les deux), sans conséquence puisque ces fonctions
    restent de toute façon autorisées. Le refus au runtime de ``transitionner(...,
    "completed_pending_review"/"completed_verified", ...)``, le rejet de ``confirmer_verification``
    et de ``resoudre_revue_completion`` en dehors de ``completed_pending_review`` constituent la
    défense en profondeur.

    Args:
        chemin_source: dossier des sources à analyser (défaut : dossier du module).

    Returns:
        (True, "") ou (False, message)
    """
    if chemin_source is None:
        chemin_source = str(Path(__file__).parent)

    violations = []

    for path in Path(chemin_source).glob("*.py"):
        # Exclure __init__.py pour éviter les faux positifs
        if path.name == "__init__.py":
            continue
        try:
            arbre = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue

        # Parcours avec pile de fonctions pour savoir dans quelle fonction on se trouve
        pile_fonctions = []

        class Visitor(ast.NodeVisitor):
            def __init__(self, nom_fichier, pile_fonctions):
                self.nom_fichier = nom_fichier
                self.pile_fonctions = pile_fonctions

            def visit_FunctionDef(self, node):
                self.pile_fonctions.append(node.name)
                self.generic_visit(node)
                self.pile_fonctions.pop()

            def visit_Call(self, node):
                # 1. Appels à ajouter(...) avec un dict littéral contenant CLE_WCT ou
                # "statut": <completed_pending_review|completed_verified> littéral.
                if isinstance(node.func, ast.Attribute) and node.func.attr == "ajouter":
                    for arg in node.args:
                        if not isinstance(arg, ast.Dict):
                            continue
                        porte_wct = any(
                            isinstance(key, ast.Constant) and key.value == CLE_WCT
                            for key in arg.keys
                        )
                        if porte_wct and "completer_intervention" not in self.pile_fonctions:
                            violations.append(
                                f"{self.nom_fichier}: appel à ajouter avec clé {CLE_WCT} "
                                f"hors de completer_intervention"
                            )
                        for key, valeur in zip(arg.keys, arg.values, strict=True):
                            if not (isinstance(key, ast.Constant) and key.value == "statut"):
                                continue
                            if not (isinstance(valeur, ast.Constant) and valeur.value in STATUTS_COMPLETION):
                                continue
                            if not any(f in self.pile_fonctions for f in _FONCTIONS_AUTORISEES_STATUT_COMPLETION):
                                violations.append(
                                    f"{self.nom_fichier}: appel à ajouter avec statut={valeur.value!r} "
                                    f"hors de {_FONCTIONS_AUTORISEES_STATUT_COMPLETION}"
                                )

                # 2. Appels à transitionner(..., "completed_pending_review"
                # / "completed_verified", ...) — les deux SEULES cibles de complétion
                # (T1.1-b#2, ex-"terminee"), interdites à transitionner quel que soit
                # l'appelant (elle-même les refuse déjà au runtime, défense en profondeur).
                nom_fonc = None
                if isinstance(node.func, ast.Attribute):
                    nom_fonc = node.func.attr
                elif isinstance(node.func, ast.Name):
                    nom_fonc = node.func.id
                if nom_fonc == "transitionner":
                    for arg in node.args:
                        if isinstance(arg, ast.Constant) and arg.value in STATUTS_COMPLETION:
                            violations.append(
                                f"{self.nom_fichier}: appel à transitionner avec {arg.value!r}"
                            )
                    for kw in node.keywords:
                        # BUG CORRIGÉ : kw.value est le NŒUD ast.Constant lui-même,
                        # jamais égal à la chaîne visée (comparaison objet-vs-str
                        # toujours fausse) — c'est sa .value qui porte la constante
                        # Python réelle. Sans .value, la forme mot-clé
                        # (transitionner(..., statut_cible="completed_verified"))
                        # échappait entièrement à la garde alors que la forme
                        # positionnelle, elle, était bien détectée juste au-dessus.
                        if isinstance(kw.value, ast.Constant) and kw.value.value in STATUTS_COMPLETION:
                            violations.append(
                                f"{self.nom_fichier}: appel à transitionner avec keyword {kw.value.value!r}"
                            )

                self.generic_visit(node)

        Visitor(path.name, pile_fonctions).visit(arbre)

    # Vérification additionnelle : completer_intervention ET confirmer_verification
    # n'appellent ajouter qu'une seule fois (textuellement) chacune. On rouvre spécifiquement
    # outbox.py, qui les contient toutes les deux.
    own_path = Path(__file__) if chemin_source is None else None
    if own_path is None:
        own_path = Path(chemin_source) / "outbox.py"
    if own_path.exists():
        own_arbre = ast.parse(own_path.read_text(encoding="utf-8"))

        class CompteurAjout(ast.NodeVisitor):
            def visit_FunctionDef(self, node):
                if node.name in _FONCTIONS_AUTORISEES_STATUT_COMPLETION:
                    compteur = 0

                    class LocalVisitor(ast.NodeVisitor):
                        def visit_Call(self, inner_node):
                            nonlocal compteur
                            if isinstance(inner_node.func, ast.Attribute) and inner_node.func.attr == "ajouter":
                                compteur += 1
                            self.generic_visit(inner_node)

                    LocalVisitor().visit(node)
                    if compteur != 1:
                        violations.append(
                            f"outbox.py: {node.name} contient {compteur} appel(s) à ajouter (attendu: 1)"
                        )
                else:
                    self.generic_visit(node)

        CompteurAjout().visit(own_arbre)

    if violations:
        return False, "; ".join(violations)
    return True, ""


class ConsommateurReference:
    """
    Consommateur idempotent des WCT, utilisant un curseur de position et un
    ensemble de ``wct_id`` déjà traités.  L'idempotence est assurée par le set,
    pas par le curseur (qui sert uniquement à l'incrément).
    """

    def __init__(self):
        self.curseur = 0
        self.wct_vus = set()
        self.effets = []

    def consommer(self, registre_cible, depuis_index=None):
        """
        Consomme tous les wct émis depuis un certain index.

        Args:
            registre_cible: instance de Registre.
            depuis_index: index de départ (par défaut, reprend au curseur interne).

        Returns:
            Nombre de nouveaux effets appliqués.
        """
        if depuis_index is None:
            depuis_index = self.curseur

        wcts = lire_outbox(registre_cible, depuis_index=depuis_index)
        nouveaux = 0
        for _, wct in wcts:
            if wct["wct_id"] in self.wct_vus:
                continue
            self.wct_vus.add(wct["wct_id"])
            self.effets.append(copy.deepcopy(wct))
            nouveaux += 1

        if wcts:
            dernier_index = max(idx for idx, _ in wcts)
            self.curseur = max(self.curseur, dernier_index + 1)
        return nouveaux


__all__ = [
    "CONSOMMATEURS_CIBLES",
    "CHAMPS_WCT",
    "CHAMPS_WCT_OPTIONNELS",
    "NON_FOURNI",
    "CLE_WCT",
    "STATUTS_COMPLETION",
    "DECISIONS_REVUE",
    "TYPE_SIGNAL_VARIANCE",
    "calculer_minutes_pause",
    "calculer_minutes_deplacement",
    "calculer_duree_reelle",
    "completer_intervention",
    "confirmer_verification",
    "resoudre_revue_completion",
    "enregistrer_signal_variance",
    "dernier_signal_variance",
    "lire_outbox",
    "verifier_invariants_outbox",
    "garde_ecriture_unique",
    "ConsommateurReference",
]
