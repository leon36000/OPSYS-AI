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

from opsys import taxonomie

from . import contrats
from . import verdicts

# ---------------------------------------------------------------------------
# Bornes DÉFENSIVES d'implémentation, sans aucune signification métier —
# aucun critère d'acceptation ne les ratifie et elles ne doivent pas être
# lues comme une règle. Elles empêchent qu'une entrée hostile à imbrication
# profonde épuise la pile du parcours ITÉRATIF de la garde noire, en NOMMANT
# le refus (REJ-PROFONDEUR-EXCESSIVE) plutôt qu'en le subissant comme un
# plantage.
#
# Comptage des profondeurs : la garde empile les entrées à la profondeur 0
# et rejette sur « strictement supérieur à la borne », c'est-à-dire dès que
# profondeur > PROFONDEUR_MAX. Les profondeurs ci-dessous sont mesurées dans
# CETTE base — celle que la garde compare, pas une base 1 — sur les entrées
# légitimes réelles :
#   contrat complet ............... profondeur 2, 11 nœuds
#   marqueur ...................... profondeur 1, 6 nœuds
#   lot de 20 photos avec référence  profondeur 3, 141 nœuds
# Marge laissée : facteur supérieur à 10 en profondeur, 70 en nœuds. Le test
# test_une_entree_legitime_maximale_reste_sous_les_bornes verrouille la
# borne par le BAS : resserrer sous le besoin réel fait rougir la suite.
# ---------------------------------------------------------------------------
PROFONDEUR_MAX = 32
NOEUDS_MAX = 10000

_CHIFFRES_HEXA = frozenset("0123456789abcdefABCDEF")

_CHAMPS_CHAINES_CONTRAT = ("lead_id", "conversation_id", "ville", "canal")
_CHAMPS_CHAINES_CONTRAT_V2 = ("lead_id", "conversation_id", "ville", "canal", "service")


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


# Périmètre réel de la visite : seuls les dict et les list/tuple sont
# descendus — jamais les set ni les frozenset, et ce n'est PAS un trou : un
# dict y est inhashable, Python lève TypeError, il est donc PROUVÉ impossible
# qu'une clé interdite s'y cache. La limite réelle est ailleurs : les
# attributs d'un objet quelconque ne sont pas inspectés. Ce cas est HORS
# PÉRIMÈTRE : le contrat d'entrée est une structure de données JSON —
# dictionnaires, listes, chaînes, nombres, booléens, None.
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


def _valider_contrat(contrat, services=None):
    """Garde blanche du contrat LeadQualifie, dans la version qu'il DÉCLARE (PLAN T0.13) :
    `schema_version` présent = v2, absent = v1 gelé. Retourne un verdict ou None."""
    if not isinstance(contrat, dict):
        return verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            detail="le contrat n'est pas un dictionnaire",
        )
    if "schema_version" in contrat:
        return _valider_contrat_v2(contrat, services)
    cles_presentes = set(contrat.keys())
    cles_attendues = set(contrats.CHAMPS_CONTRAT_GELE)
    cles_permises = cles_attendues | set(contrats.CHAMPS_CONTRAT_OPTIONNELS)
    manquantes = sorted(cles_attendues - cles_presentes)
    inconnues = sorted(cles_presentes - cles_permises)
    if manquantes or inconnues:
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
    return _valider_contact_urgence_optionnels(contrat)


def _valider_contrat_v2(contrat, services):
    """Contrat v2 : `service` validé contre la taxonomie du socle, jamais contre un énuméré local.

    Un service hors du profil d'entreprise de l'instance, ou l'absence de profil, est un refus
    NOMMÉ dont le détail dit quoi configurer : aucun service par défaut, aucun repli sur « autre ».
    """
    if type(contrat["schema_version"]) is not int or contrat["schema_version"] != contrats.VERSION_CONTRAT_V2:
        return verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            detail=f"champ 'schema_version' : la valeur {contrats.VERSION_CONTRAT_V2} (entier) est exigée",
        )
    cles_presentes = set(contrat.keys())
    cles_attendues = set(contrats.CHAMPS_CONTRAT_GELE_V2)
    cles_permises = cles_attendues | set(contrats.CHAMPS_CONTRAT_OPTIONNELS)
    manquantes = sorted(cles_attendues - cles_presentes)
    inconnues = sorted(cles_presentes - cles_permises)
    if manquantes or inconnues:
        return verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            detail=(
                f"clés du contrat v2 non conformes "
                f"(manquantes={manquantes}, inconnues={inconnues})"
            ),
        )
    for champ in _CHAMPS_CHAINES_CONTRAT_V2:
        if not _est_chaine_non_vide(contrat[champ]):
            return verdicts.construire_verdict(
                "REJ-CONTRAT-INVALIDE",
                detail=f"champ {champ!r} : chaîne non vide exigée",
            )
    _, verdict_service = taxonomie.valider_service(contrat["service"], services)
    if verdict_service is not None:
        return verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            detail=f"champ 'service' : {verdict_service['code']} : {verdict_service['detail']}",
        )
    return _valider_contact_urgence_optionnels(contrat)


def _valider_contact_urgence_optionnels(contrat):
    """Suite commune aux versions v1 et v2 : contact, urgence déclarée, clés optionnelles."""
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
    return _valider_champs_optionnels(contrat)


def _valider_champs_optionnels(contrat):
    """Clés optionnelles du LeadQualifie (PLAN T2.2), validées À L'IDENTIQUE de M2 SI PRÉSENTES.

    Absentes : aucune erreur et aucune valeur par défaut. Présentes : ``source`` et
    ``campagne`` sont des chaînes non vides ; ``utm`` est un dictionnaire non vide dont les
    clés appartiennent à ``CHAMPS_UTM`` et dont les valeurs sont des chaînes non vides. Un
    consommateur plus souple ou plus strict que M2 accepterait ou rejetterait des leads que
    son voisin traite autrement. M3 ne se sert d'aucune de ces clés pour estimer. Retourne
    un verdict ou None."""
    for champ in ("source", "campagne"):
        if champ in contrat and not _est_chaine_non_vide(contrat[champ]):
            return verdicts.construire_verdict(
                "REJ-CONTRAT-INVALIDE",
                detail=f"champ optionnel {champ!r} : chaîne non vide exigée s'il est fourni",
            )
    if "utm" not in contrat:
        return None
    utm = contrat["utm"]
    if not isinstance(utm, dict) or not utm:
        return verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            detail="champ optionnel 'utm' : dictionnaire non vide exigé s'il est fourni",
        )
    for cle, valeur in utm.items():
        if cle not in contrats.CHAMPS_UTM or not _est_chaine_non_vide(valeur):
            return verdicts.construire_verdict(
                "REJ-CONTRAT-INVALIDE",
                detail=(
                    f"champ optionnel 'utm' : sous-clé {cle!r} hors de CHAMPS_UTM "
                    f"ou valeur qui n'est pas une chaîne non vide"
                ),
            )
    return None


def _valider_marqueur(marqueur):
    """Garde blanche STRUCTURELLE du marqueur de readiness : ensemble exact
    de clés, format hexadécimal de l'empreinte et de l'identifiant de tête,
    fuseau horaire de l'horodatage et ``lead_id`` chaîne non vide —
    l'empreinte est contrôlée en forme, jamais recalculée. La casse
    hexadécimale est indifférente : majuscules et minuscules sont toutes
    deux acceptées. Retourne un verdict ou None."""
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


def valider_entrees(contrat, marqueur, photos, services=None):
    """Valide les trois entrées de M3 et produit un accusé ou un verdict.

    Ordre ÉPINGLÉ ; rien n'est produit si un contrôle échoue. La garde
    NOIRE précède la liste blanche parce que CA-M3-02 exige un rejet
    DISTINCT du rejet générique : inversés, une clé interdite au premier
    niveau serait dégradée en « clé inconnue ». La concordance du
    ``lead_id`` vient APRÈS la validation structurelle du marqueur, parce
    que comparer un champ qu'on n'a pas encore validé n'a pas de sens.

    ``services`` : déclaration de services à confronter pour un lead v2 (tests, appelant qui l'a
    déjà lue) ; absente, le profil d'entreprise de l'instance est lu (`opsys.taxonomie`).

    Returns:
        (accuse, None) si toutes les entrées sont valides, (None, verdict)
        sinon. L'accusé d'un lead v1 porte `type_travaux` (inchangé) ; celui d'un lead v2 porte
        `service` et `schema_version`, jamais `type_travaux`.
    """
    # 1. Garde NOIRE d'abord, sur les TROIS entrées : c'est l'ORDRE des
    #    gardes qui protège le diagnostic. La garde noire s'exécute AVANT
    #    la liste blanche, donc une clé interdite est rejetée comme clé
    #    interdite et ne peut jamais être dégradée en « clé inconnue » par
    #    la garde blanche. Elle retourne au PREMIER interdit rencontré.
    verdict = _garde_noire(
        (("contrat", contrat), ("marqueur", marqueur), ("photos", photos))
    )
    if verdict is not None:
        return None, verdict

    # 2. Garde blanche du contrat LeadQualifie.
    verdict = _valider_contrat(contrat, services)
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
        "ville": contrat["ville"],
        "empreinte_marqueur_m2": marqueur["empreinte"],
        "nombre_photos": len(photos),
    }
    if "schema_version" in contrat:
        accuse["service"] = contrat["service"]
        accuse["schema_version"] = contrat["schema_version"]
    else:
        accuse["type_travaux"] = contrat["type_travaux"]
    return accuse, None


__all__ = ["valider_entrees", "PROFONDEUR_MAX", "NOEUDS_MAX"]


# Les ancres du cadrage sont EXTRAITES, jamais paraphrasées
