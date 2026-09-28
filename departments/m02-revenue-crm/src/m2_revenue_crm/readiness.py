"""Gate de préparation pour la transmission vers M3 (S005/S006).

Évalue si un lead qualifié remplit toutes les conditions pour être transmis
à l'étape d'estimation. Le contrat de recalcul du marqueur est le suivant :
l'empreinte est calculée par encoder_canonique(conditions, lead_id, tete) où
conditions est un dict déterministe contenant les valeurs réelles de owner,
des travaux demandés, ville et le booléen interaction_post_qualification. Les
travaux demandés sont portés par `type_travaux` pour un lead v1 (contrat gelé,
octets inchangés) et par `service` pour un lead v2 (PLAN T0.13) : la clé suit la
version déclarée du contrat. M3 doit reproduire exactement ce calcul pour
vérifier le marqueur.
Fonctions pures (evaluer) ou produisant un marqueur horodaté signé.
"""

from datetime import datetime

from opsys import taxonomie

from . import horodatage as _horodatage
from .contrats import TYPES_TRAVAUX, VERSION_CONTRAT_V2
from .encodage import encoder_canonique
from .verdicts import construire_verdict
from .statuts import statut_courant

# Types de travaux autorisés en v1 (énumération fermée) : UNE seule copie, celle de contrats.py.
# En v2, le service est validé contre le profil d'entreprise de l'instance (opsys.taxonomie).


def _maillon_lead_ingere(registre_cible, lead_id):
    """Retourne le maillon 'lead_ingere' du lead (None si absent)."""
    for m in registre_cible.lire():
        if m.get("type_entree") == "lead_ingere" and m.get("lead_id") == lead_id:
            return m
    return None


def _dernier_maillon_transition_qualifie(registre_cible, lead_id):
    """Retourne le dernier maillon 'transition_statut' ayant statut='qualifie' (ou None)."""
    dernier = None
    for m in registre_cible.lire():
        if (m.get("type_entree") == "transition_statut" and
                m.get("lead_id") == lead_id and
                m.get("statut") == "qualifie"):
            dernier = m
    return dernier


def _extraire_conditions(registre_cible, lead_id):
    """Analyse les conditions de readiness.

    Retourne un dict contenant les valeurs et booléens nécessaires à l'évaluation,
    ou None si le lead n'est pas dans l'état qualifié ou si des données essentielles
    sont absentes.

    Les clés retournées :
    - owner, travaux, ville : valeurs brutes (chaînes après strip) ; `travaux` est le
      `type_travaux` d'un lead v1 ou le `service` d'un lead v2
    - cle_travaux : "type_travaux" (lead v1) ou "service" (lead v2), la clé du contrat
    - owner_valide, travaux_valide, ville_valide : booléens de conformité
      (`travaux_valide` : énuméré v1, ou service déclaré par le profil d'entreprise en v2)
    - interaction_ok : booléen indiquant une interaction post-qualification
    - transition_horodatage : horodatage de la transition vers qualifié (chaîne)
    """
    # Le pré-requis strict : le statut courant doit être "qualifie"
    statut = statut_courant(registre_cible, lead_id)
    if statut != "qualifie":
        return None

    # Contrat initial du lead
    ingere = _maillon_lead_ingere(registre_cible, lead_id)
    if ingere is None:
        return None
    contrat = ingere.get("contrat", {})
    # Version explicite du contrat ingéré : `schema_version` présent = v2, sinon v1.
    est_v2 = contrat.get("schema_version") == VERSION_CONTRAT_V2
    cle_travaux = "service" if est_v2 else "type_travaux"
    travaux = contrat.get(cle_travaux, "").strip()
    ville = contrat.get("ville", "").strip()

    # Dernier changement de statut vers qualifié (contient l'owner)
    trans = _dernier_maillon_transition_qualifie(registre_cible, lead_id)
    if trans is None:
        return None
    owner = trans.get("owner", "").strip()
    horodatage_trans = trans.get("horodatage")
    if not horodatage_trans:
        return None

    # Conversion sécurisée de l'horodatage de transition (fromisoformat)
    try:
        dt_transition = datetime.fromisoformat(horodatage_trans)
    except Exception:
        # si l'horodatage est mal formé, on ne peut pas comparer, donc readiness impossible
        return None

    # Présence d'au moins une interaction postérieure ou égale à la transition
    interaction_ok = False
    for m in registre_cible.lire():
        if m.get("type_entree") == "interaction" and m.get("lead_id") == lead_id:
            h_str = m.get("horodatage")
            if not h_str:
                continue
            # La comparaison est DANS le try : un maillon falsifié portant un
            # horodatage naïf face à une transition aware lèverait TypeError et
            # ferait planter la gate au lieu de l'ignorer (contrat fail-closed :
            # une valeur incomparable ne satisfait pas la condition, elle ne
            # casse pas l'évaluation). Inaccessible par l'API publique — mesuré —
            # mais la gate est appelée sur un état de registre qu'elle ne
            # contrôle pas.
            try:
                dt_inter = datetime.fromisoformat(h_str)
                if dt_inter >= dt_transition:
                    interaction_ok = True
                    break
            except (ValueError, TypeError):
                continue

    # v2 : le service doit être déclaré par le profil d'entreprise AU MOMENT de la readiness
    # (fail-closed : un profil retiré ou cassé depuis l'ingestion rend le lead non prêt).
    if est_v2:
        travaux_valide = taxonomie.valider_service(travaux)[1] is None
    else:
        travaux_valide = travaux in TYPES_TRAVAUX

    return {
        "owner": owner,
        "travaux": travaux,
        "cle_travaux": cle_travaux,
        "ville": ville,
        "owner_valide": bool(owner),
        "travaux_valide": travaux_valide,
        "ville_valide": bool(ville),
        "interaction_ok": interaction_ok,
        "transition_horodatage": horodatage_trans,
    }


def evaluer(registre_cible, lead_id):
    """Évalue si le lead est prêt pour M3 (readiness gate).

    PRÉ-REQUIS : le statut courant doit être "qualifie" (sinon False).
    Conditions (conjointes) :
    - owner non vide (extrait du dernier transition_statut qualifie)
    - type_travaux dans l'énumération fermée (v1), ou service déclaré par le profil d'entreprise (v2)
    - ville non vide
    - au moins une interaction postérieure ou égale à la transition qualifie.

    Aucun effet de bord, pure.
    """
    cond = _extraire_conditions(registre_cible, lead_id)
    if cond is None:
        return False
    return (cond["owner_valide"] and
            cond["travaux_valide"] and
            cond["ville_valide"] and
            cond["interaction_ok"])


def emettre_marqueur(registre_cible, lead_id, horodatage):
    """Émet un marqueur de readiness signé (hashé) si les conditions sont réunies.

    Contrôles :
    1. horodatage valide (ValueError → REJ-HORODATAGE-INVALIDE)
    2. evalue() == True → sinon REJ-TRANSITION-ILLEGALE avec détail
    3. Construction du marqueur (AUCUNE écriture au registre)

    Retourne (marqueur, None) ou (None, verdict).
    """
    # 1. Validation horodatage
    try:
        horodatage_valide = _horodatage.valider_horodatage(horodatage)
    except ValueError as e:
        return (None, construire_verdict("REJ-HORODATAGE-INVALIDE", detail=str(e)))

    # 2. Vérification de la readiness
    if not evaluer(registre_cible, lead_id):
        # Construction d'un message détaillé
        cond = _extraire_conditions(registre_cible, lead_id)
        if cond is None:
            statut = statut_courant(registre_cible, lead_id)
            if statut is None:
                msg = f"lead {lead_id} inexistant"
            else:
                msg = (f"readiness non satisfaite : statut actuel '{statut}' "
                       f"au lieu de 'qualifie'")
        else:
            manques = []
            if not cond["owner_valide"]:
                manques.append("owner manquant")
            if not cond["travaux_valide"]:
                manques.append(f"{cond['cle_travaux']} invalide '{cond['travaux']}'")
            if not cond["ville_valide"]:
                manques.append("ville manquante")
            if not cond["interaction_ok"]:
                manques.append("aucune interaction post-qualification")
            msg = "readiness non satisfaite : " + ", ".join(manques)
        return (None, construire_verdict("REJ-TRANSITION-ILLEGALE", detail=msg))

    # 3. Construction du marqueur (aucun enregistrement)
    # Relecture des conditions réelles pour signer le marqueur
    cond = _extraire_conditions(registre_cible, lead_id)  # toujours non None et valide ici
    tete = registre_cible.tete()
    conditions = {
        "owner": cond["owner"],
        cond["cle_travaux"]: cond["travaux"],
        "ville": cond["ville"],
        "interaction_post_qualification": True,
    }
    empreinte = encoder_canonique(conditions, lead_id, tete)

    marqueur = {
        "readiness_ok": True,
        "lead_id": lead_id,
        "hash_tete_registre": tete,
        "horodatage": horodatage_valide,
        "empreinte": empreinte,
    }
    return (marqueur, None)


def verifier_marqueur(marqueur, registre_cible):
    """Vérifie un marqueur de readiness par recalcul complet (confiance zéro).

    - Contrôle des clés obligatoires et de readiness_ok == True.
    - Vérification que l'ancre (hash_tete_registre) correspond à une chaîne valide.
    - Recalcul de l'empreinte avec les données actuelles du registre,
      puis comparaison.

    Échoue (False) pour toute incohérence, y compris si le registre a évolué
    depuis l'émission (l'ancre ne correspond plus à la tête).

    Fail-closed : toute exception interne entraîne False.
    """
    if not isinstance(marqueur, dict):
        return False
    cles_attendues = {"readiness_ok", "lead_id", "hash_tete_registre",
                      "horodatage", "empreinte"}
    if not cles_attendues.issubset(marqueur.keys()):
        return False
    if marqueur.get("readiness_ok") is not True:
        return False

    ancre = marqueur["hash_tete_registre"]
    lead_id = marqueur["lead_id"]

    try:
        # L'ancre doit être le hash de tête actuel (valider_chaine échoue sinon)
        if not registre_cible.valider_chaine(ancre=ancre):
            return False

        # Recalcul des conditions depuis le registre (même état qu'à l'émission)
        cond = _extraire_conditions(registre_cible, lead_id)
        if cond is None:
            return False
        if not (cond["owner_valide"] and cond["travaux_valide"]
                and cond["ville_valide"] and cond["interaction_ok"]):
            # Si les conditions ont changé entre-temps, le marqueur devient invalide
            return False

        conditions_recalc = {
            "owner": cond["owner"],
            cond["cle_travaux"]: cond["travaux"],
            "ville": cond["ville"],
            "interaction_post_qualification": True,
        }
        empreinte_attendue = encoder_canonique(conditions_recalc, lead_id, ancre)
        return empreinte_attendue == marqueur["empreinte"]

    except Exception:
        # Fail-closed : le marqueur est considéré invalide par sécurité
        return False
