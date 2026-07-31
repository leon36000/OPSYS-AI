"""Validation des entrées de M3-estimation (cahier M3-S001).

Règle d'architecture qui gouverne ce module :
la readiness est constatée, jamais re-déduite.
M3 ne re-juge pas la readiness à partir du contenu du contrat ; il constate
la signature que M2 a produite.

Ancre du critère CA-M3-03 (emplacement « docstring de module ») :
validation STRUCTURELLE du marqueur : M3 ne recalcule pas l'empreinte, qui couvre des conditions extraites du registre de M2

NOTE D'ANCRE : la phrase « la readiness est constatée, jamais re-déduite »
tient volontairement sur UNE SEULE LIGNE ci-dessus parce qu'elle est une
ANCRE vérifiée mot pour mot par un test qui recherche cette sous-chaîne
exacte dans la source — la couper par un retour à la ligne la rendrait
introuvable, donc tout reformatage doit la laisser intacte.

NOTE D'ANCRE (CA-M3-03) : la phrase d'ancre du critère CA-M3-03 reproduite
plus haut sur sa propre ligne est une ANCRE comparée mot pour mot par le
gate de cohérence du cadrage, et tout reformatage qui la coupe, la reformule
ou la répartit sur plusieurs lignes la casse.

Limite déclarée : la validation du marqueur de readiness est STRUCTURELLE
uniquement — ensemble exact de clés, format hexadécimal de l'empreinte et de
l'identifiant de tête, fuseau horaire de l'horodatage. L'empreinte n'est
JAMAIS recalculée ici : M3 ne possède ni le registre ni les secrets de M2 et
ne peut donc ni vérifier ni reconstruire la chaîne de hachage amont.
"""

from datetime import datetime

from . import contrats
from . import verdicts

# ---------------------------------------------------------------------------
# Bornes du parcours de la garde noire (parcours ITÉRATIF, pile explicite,
# jamais de récursion). Les entrées légitimes ne dépassent jamais deux niveaux
# sous la racine ; la borne de profondeur laisse passer ces entrées et refuse
# les structures artificiellement profondes (200 niveaux imbriqués, par
# exemple) sans jamais planter ni épuiser la pile d'appels.
# ---------------------------------------------------------------------------
PROFONDEUR_MAX = 32
NOEUDS_MAX = 10000

_CHIFFRES_HEXA = frozenset("0123456789abcdefABCDEF")

_CHAMPS_CHAINES_CONTRAT = ("lead_id", "conversation_id", "ville", "canal")


def _est_chaine_non_vide(valeur):
    """Retourne True si ``valeur`` est une chaîne de caractères non vide."""
    return isinstance(valeur, str) and valeur != ""


def _est_hexadecimal_64(valeur):
    """Retourne True si ``valeur`` est une chaîne hexadécimale d'exactement
    64 caractères."""
    if not isinstance(valeur, str) or len(valeur) != 64:
        return False
    return all(caractere in _CHIFFRES_HEXA for caractere in valeur)


def _est_horodatage_avec_fuseau(valeur):
    """Retourne True si ``valeur`` est un horodatage ISO-8601 portant un
    fuseau horaire explicite."""
    if not isinstance(valeur, str):
        return False
    try:
        moment = datetime.fromisoformat(valeur)
    except ValueError:
        return False
    return moment.tzinfo is not None


def _garde_noire(entrees):
    """Traque les clés interdites à toute profondeur des trois entrées.

    Parcours ITÉRATIF borné par PROFONDEUR_MAX et NOEUDS_MAX. Retourne un
    verdict si une faute est trouvée, None sinon.
    """
    pile = [(valeur, 0, nom) for nom, valeur in entrees]
    noeuds_visites = 0
    while pile:
        valeur, profondeur, nom_entree = pile.pop()
        if profondeur > PROFONDEUR_MAX:
            return verdicts.construire_verdict(
                "REJ-PROFONDEUR-EXCESSIVE",
                detail=(
                    f"profondeur {profondeur} supérieure à la borne "
                    f"{PROFONDEUR_MAX} dans l'entrée {nom_entree!r}"
                ),
            )
        noeuds_visites += 1
        if noeuds_visites > NOEUDS_MAX:
            return verdicts.construire_verdict(
                "REJ-PROFONDEUR-EXCESSIVE",
                detail=f"plus de {NOEUDS_MAX} nœuds visités",
            )
        if isinstance(valeur, dict):
            for cle, sous_valeur in valeur.items():
                if cle in contrats.CLES_INTERDITES:
                    return verdicts.construire_verdict(
                        "REJ-CLE-INTERDITE",
                        detail=(
                            f"clé interdite {cle!r} trouvée dans "
                            f"l'entrée {nom_entree!r}"
                        ),
                    )
                pile.append((sous_valeur, profondeur + 1, nom_entree))
        elif isinstance(valeur, (list, tuple)):
            for element in valeur:
                pile.append((element, profondeur + 1, nom_entree))
    return None


def _valider_contrat(contrat):
    """Garde blanche du contrat LeadQualifie. Retourne un verdict ou None."""
    if not isinstance(contrat, dict):
        return verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            detail="le contrat n'est pas un dictionnaire",
        )
    cles_presentes = set(contrat.keys())
    cles_attendues = set(contrats.CHAMPS_CONTRAT_GELE)
    if cles_presentes != cles_attendues:
        manquantes = sorted(cles_attendues - cles_presentes)
        inconnues = sorted(cles_presentes - cles_attendues)
        return verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            detail=(
                f"clés du contrat non conformes "
                f"(manquantes={manquantes}, inconnues={inconnues})"
            ),
        )
    for champ in _CHAMPS_CHAINES_CONTRAT:
        if not _est_chaine_non_vide(contrat[champ]):
            return verdicts.construire_verdict(
                "REJ-CONTRAT-INVALIDE",
                detail=f"champ {champ!r} : chaîne non vide exigée",
            )
    if contrat["type_travaux"] not in contrats.TYPES_TRAVAUX:
        return verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            detail=(
                f"champ 'type_travaux' : valeur "
                f"{contrat['type_travaux']!r} hors énuméré"
            ),
        )
    contact = contrat["contact"]
    if not isinstance(contact, dict) or not set(contact.keys()) <= set(
        contrats.CHAMPS_CONTACT
    ):
        return verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            detail=(
                "champ 'contact' : sous-objet dont les clés doivent "
                "appartenir à CHAMPS_CONTACT"
            ),
        )
    if type(contrat["urgence_declaree"]) is not bool:
        return verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            detail="champ 'urgence_declaree' : booléen strict exigé",
        )
    return None


def _valider_marqueur(marqueur):
    """Garde blanche STRUCTURELLE du marqueur de readiness : ensemble exact
    de clés, format hexadécimal de l'empreinte et de l'identifiant de tête,
    fuseau horaire de l'horodatage et ``lead_id`` chaîne non vide —
    l'empreinte est contrôlée en forme, jamais recalculée. Retourne un
    verdict ou None."""
    if not isinstance(marqueur, dict):
        return verdicts.construire_verdict(
            "REJ-MARQUEUR-INVALIDE",
            detail="le marqueur est absent ou n'est pas un dictionnaire",
        )
    if set(marqueur.keys()) != set(contrats.CHAMPS_MARQUEUR):
        return verdicts.construire_verdict(
            "REJ-MARQUEUR-INVALIDE",
            detail="clés du marqueur non conformes à CHAMPS_MARQUEUR",
        )
    if not _est_hexadecimal_64(marqueur["empreinte"]):
        return verdicts.construire_verdict(
            "REJ-MARQUEUR-INVALIDE",
            detail="champ 'empreinte' : chaîne hexadécimale de 64 caractères exigée",
        )
    if not _est_hexadecimal_64(marqueur["hash_tete_registre"]):
        return verdicts.construire_verdict(
            "REJ-MARQUEUR-INVALIDE",
            detail=(
                "champ 'hash_tete_registre' : chaîne hexadécimale de "
                "64 caractères exigée"
            ),
        )
    if not _est_horodatage_avec_fuseau(marqueur["horodatage"]):
        return verdicts.construire_verdict(
            "REJ-MARQUEUR-INVALIDE",
            detail="champ 'horodatage' : horodatage ISO-8601 avec fuseau exigé",
        )
    if not _est_chaine_non_vide(marqueur["lead_id"]):
        return verdicts.construire_verdict(
            "REJ-MARQUEUR-INVALIDE",
            detail="champ 'lead_id' : chaîne non vide exigée",
        )
    return None


def _valider_photos(photos):
    """Garde blanche des photos : une liste de dictionnaires. Retourne un
    verdict ou None."""
    if not isinstance(photos, list):
        return verdicts.construire_verdict(
            "REJ-PHOTOS-INVALIDES",
            detail="les photos doivent être fournies en liste",
        )
    for indice, element in enumerate(photos):
        if not isinstance(element, dict):
            return verdicts.construire_verdict(
                "REJ-PHOTOS-INVALIDES",
                detail=f"photo d'indice {indice} : dictionnaire exigé",
            )
    return None


def valider_entrees(contrat, marqueur, photos):
    """Valide les trois entrées de M3 et produit un accusé ou un verdict.

    Ordre ÉPINGLÉ ; rien n'est produit si un contrôle échoue. La garde
    NOIRE précède la liste blanche parce que CA-M3-02 exige un rejet
    DISTINCT du rejet générique : inversés, une clé interdite au premier
    niveau serait dégradée en « clé inconnue ». La concordance du
    ``lead_id`` vient APRÈS la validation structurelle du marqueur, parce
    que comparer un champ qu'on n'a pas encore validé n'a pas de sens.

    Returns:
        (accuse, None) si toutes les entrées sont valides, (None, verdict)
        sinon.
    """
    # 1. Garde NOIRE d'abord, récursive, sur les TROIS entrées : en cas de
    #    double faute, le verdict le plus significatif pour l'audit l'emporte
    #    sur le rejet générique.
    verdict = _garde_noire(
        (("contrat", contrat), ("marqueur", marqueur), ("photos", photos))
    )
    if verdict is not None:
        return None, verdict

    # 2. Garde blanche du contrat LeadQualifie.
    verdict = _valider_contrat(contrat)
    if verdict is not None:
        return None, verdict

    # 3. Garde blanche structurelle du marqueur (jamais de recalcul).
    verdict = _valider_marqueur(marqueur)
    if verdict is not None:
        return None, verdict

    # 4. Readiness CONSTATÉE : M3 ne re-déduit RIEN du contrat, il constate la
    #    signature de M2 — l'identité à True refuse la chaîne "true" et
    #    l'entier 1.
    if marqueur["readiness_ok"] is not True:
        return None, verdicts.construire_verdict(
            "REJ-READINESS-NON-CONSTATEE",
            detail="champ 'readiness_ok' : la valeur True (booléen) est exigée",
        )

    # 5. Concordance : empêche qu'un marqueur authentique signé pour un lead A
    #    soit présenté avec le contrat d'un lead B.
    if marqueur["lead_id"] != contrat["lead_id"]:
        return None, verdicts.construire_verdict(
            "REJ-LEAD-ID-DISCORDANT",
            detail="le lead_id du marqueur ne concorde pas avec celui du contrat",
        )

    # 6. Photos : la liste VIDE est acceptée ici — le blocage pour qualité
    #    insuffisante appartient à S002, pas à S001.
    verdict = _valider_photos(photos)
    if verdict is not None:
        return None, verdict

    # 7. Accusé : l'empreinte transportée est celle du MARQUEUR, jamais
    #    recalculée.
    accuse = {
        "lead_id": contrat["lead_id"],
        "type_travaux": contrat["type_travaux"],
        "ville": contrat["ville"],
        "empreinte_marqueur_m2": marqueur["empreinte"],
        "nombre_photos": len(photos),
    }
    return accuse, None


__all__ = ["valider_entrees", "PROFONDEUR_MAX", "NOEUDS_MAX"]


# Les ancres du cadrage sont EXTRAITES, jamais paraphrasées
