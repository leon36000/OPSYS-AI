"""Détection, signalement et arbitrage humain des doublons potentiels.

Ce module ne regroupe jamais deux leads : il détecte les ressemblances,
inscrit un signalement dans le registre append-only hash-chaîné, puis
consigne l'arbitrage humain. Après signalement comme après arbitrage, les
deux leads demeurent des maillons distincts du registre ; les seuls états
d'arbitrage existants sont ``en_attente`` et ``distincts_confirmes``.
"""

import copy
from datetime import datetime

import encodage
import horodatage as _horodatage
import verdicts

CRITERES = ("contact_identique", "ville_et_travaux")
ARBITRAGES = ("en_attente", "distincts_confirmes")
FENETRE_JOURS = 7
TYPE_ENTREE = "doublon_signale"
TYPE_LEAD_INGERE = "lead_ingere"


def _maillons_ingeres(registre_cible) -> list:
    """Retourne les maillons ``lead_ingere`` du registre, dans l'ordre de la chaîne."""
    return [
        maillon
        for maillon in registre_cible.lire()
        if maillon.get("type_entree") == TYPE_LEAD_INGERE
    ]


def _dans_fenetre(horodatage_a: str, horodatage_b: str) -> bool:
    """Vrai si les deux horodatages sont à 7 jours calendaires ou moins.

    POURQUOI la partie date et non l'instant : le cadrage fige une fenêtre
    glissante de 7 jours CALENDAIRES, bord J+7 inclus. Deux horodatages
    comme 2026-03-01T23:00 et 2026-03-08T01:00 sont à 7 jours calendaires
    (donc dans la fenêtre) même si l'écart en heures diffère ; on compare
    donc les ``date()`` et l'écart en jours entiers, jamais les secondes.
    """
    date_a = datetime.fromisoformat(horodatage_a).date()
    date_b = datetime.fromisoformat(horodatage_b).date()
    return abs((date_b - date_a).days) <= FENETRE_JOURS


def detecter(registre_cible, lead_id_nouveau) -> list:
    """Liste les ``lead_id`` des autres leads doublons potentiels du lead donné.

    Fonction pure : aucune écriture dans le registre, aucun index parallèle ;
    contact, ville, type_travaux et horodatage d'ingestion (le ``horodatage``
    du maillon ``lead_ingere``) sont relus depuis les maillons à chaque appel.
    Un lead n'est jamais son propre doublon : son identifiant est exclu du
    résultat. Critère retenu : contact identique OU (même ville ET même type
    de travaux), dans la fenêtre de 7 jours calendaires.
    """
    ingeres = _maillons_ingeres(registre_cible)
    maillon_cible = None
    for maillon in ingeres:
        if maillon.get("lead_id") == lead_id_nouveau:
            maillon_cible = maillon
    if maillon_cible is None:
        return []
    contrat_cible = maillon_cible["contrat"]
    resultat = []
    for maillon in ingeres:
        lead_id = maillon["lead_id"]
        if lead_id == lead_id_nouveau:
            continue
        contrat = maillon["contrat"]
        contact_identique = contrat.get("contact") == contrat_cible.get("contact")
        ville_et_travaux = (
            contrat.get("ville") == contrat_cible.get("ville")
            and contrat.get("type_travaux") == contrat_cible.get("type_travaux")
        )
        if not (contact_identique or ville_et_travaux):
            continue
        if not _dans_fenetre(maillon_cible["horodatage"], maillon["horodatage"]):
            continue
        resultat.append(lead_id)
    return resultat


def signaler(registre_cible, lead_id_a, lead_id_b, critere, horodatage) -> tuple[dict | None, dict | None]:
    """Inscrit un signalement de doublon potentiel à l'arbitrage ``en_attente``.

    Ordre des contrôles figé par le cadrage (POURQUOI : un rejet doit porter
    le premier verdict applicable pour rester déterministe en CI) :
    1. horodatage ISO-8601 avec fuseau, sinon REJ-HORODATAGE-INVALIDE ;
    2. deux identifiants distincts, sinon REJ-TRANSITION-ILLEGALE (un lead
       n'est pas son propre doublon) ;
    3. existence des deux leads via leur maillon ``lead_ingere``, sinon
       REJ-TRANSITION-ILLEGALE ;
    4. critère dans l'énumération ``CRITERES``, sinon REJ-ENUM-INVALIDE.
    Aucun maillon de rejet n'est écrit : seul le succès ajoute un maillon.
    Convention du couple : succès = (signalement, None).
    """
    try:
        horodatage_valide = _horodatage.valider_horodatage(horodatage)
    except ValueError as exc:
        return None, verdicts.construire_verdict("REJ-HORODATAGE-INVALIDE", detail=str(exc))
    if lead_id_a == lead_id_b:
        return None, verdicts.construire_verdict(
            "REJ-TRANSITION-ILLEGALE",
            detail="un lead ne peut pas être signalé comme doublon de lui-même",
        )
    ids_ingeres = {maillon["lead_id"] for maillon in _maillons_ingeres(registre_cible)}
    if lead_id_a not in ids_ingeres or lead_id_b not in ids_ingeres:
        return None, verdicts.construire_verdict(
            "REJ-TRANSITION-ILLEGALE",
            detail=f"maillon lead_ingere absent pour {lead_id_a!r} ou {lead_id_b!r}",
        )
    if critere not in CRITERES:
        return None, verdicts.construire_verdict(
            "REJ-ENUM-INVALIDE",
            detail=f"critère hors énumération : {critere!r}",
        )
    # Tri des identifiants : le signalement_id devient indépendant de l'ordre
    # d'appel, donc signaler(a, b) et signaler(b, a) désignent le même couple.
    lead_id_1, lead_id_2 = sorted([lead_id_a, lead_id_b])
    signalement_id = encodage.encoder_canonique(lead_id_1, lead_id_2, critere)
    entree = {
        "type_entree": TYPE_ENTREE,
        "signalement_id": signalement_id,
        "lead_id_a": lead_id_1,
        "lead_id_b": lead_id_2,
        "critere": critere,
        "horodatage": horodatage_valide,
        "arbitrage": "en_attente",
    }
    registre_cible.ajouter(entree)
    signalement = {
        "signalement_id": signalement_id,
        "lead_id_a": lead_id_1,
        "lead_id_b": lead_id_2,
        "critere": critere,
        "horodatage": horodatage_valide,
        "arbitrage": "en_attente",
    }
    return signalement, None


def arbitrer(registre_cible, signalement_id, decision, horodatage) -> tuple[dict | None, dict | None]:
    """Consigne l'arbitrage humain d'un signalement de doublon potentiel.

    Seul état de sortie en v1 : ``distincts_confirmes`` — les deux leads
    demeurent des maillons distincts du registre. Toute autre décision, y
    compris ``en_attente`` ou toute valeur évoquant un regroupement des
    leads, reçoit REJ-ENUM-INVALIDE. Ordre des contrôles figé : horodatage,
    puis décision, puis existence du signalement. Aucun maillon de rejet.
    """
    try:
        horodatage_valide = _horodatage.valider_horodatage(horodatage)
    except ValueError as exc:
        return None, verdicts.construire_verdict("REJ-HORODATAGE-INVALIDE", detail=str(exc))
    if decision != "distincts_confirmes":
        return None, verdicts.construire_verdict(
            "REJ-ENUM-INVALIDE",
            detail=f"décision d'arbitrage hors énumération v1 : {decision!r}",
        )
    signalement_origine = None
    for maillon in registre_cible.lire():
        if (
            maillon.get("type_entree") == TYPE_ENTREE
            and maillon.get("signalement_id") == signalement_id
        ):
            signalement_origine = maillon
            break
    if signalement_origine is None:
        return None, verdicts.construire_verdict(
            "REJ-TRANSITION-ILLEGALE",
            detail=f"signalement introuvable : {signalement_id!r}",
        )
    # Le maillon d'arbitrage reprend le contexte du signalement d'origine
    # (couple trié et critère) pour que la chaîne reste auto-porteuse.
    entree = {
        "type_entree": TYPE_ENTREE,
        "signalement_id": signalement_id,
        "lead_id_a": signalement_origine["lead_id_a"],
        "lead_id_b": signalement_origine["lead_id_b"],
        "critere": signalement_origine["critere"],
        "horodatage": horodatage_valide,
        "arbitrage": "distincts_confirmes",
    }
    # ajouter() retourne le ligne_id (chaîne), pas le maillon.
    ligne_id = registre_cible.ajouter(entree)
    accuse = {
        "signalement_id": signalement_id,
        "arbitrage": "distincts_confirmes",
        "ligne_id": ligne_id,
        "tete_chaine": registre_cible.tete(),
        "horodatage": horodatage_valide,
    }
    return accuse, None


def lister_signalements(registre_cible) -> list:
    """Retourne tous les signalements (forme SignalementDoublon) en copies.

    Signalements initiaux et arbitrages sont retournés dans l'ordre de la
    chaîne ; c'est le champ ``arbitrage`` de chaque maillon qui les distingue.
    Les copies profondes interdisent toute mutation de l'état du registre
    par l'appelant.
    """
    # On projette chaque maillon doublon_signale sur la forme SignalementDoublon
    # (les six clés du contrat), sans exposer les champs internes du registre
    # (type_entree, ligne_id, precedent_ligne_id) : lister_signalements rend des
    # signalements, pas des maillons bruts. Copie profonde pour l'immuabilité.
    cles = ("signalement_id", "lead_id_a", "lead_id_b", "critere", "horodatage", "arbitrage")
    return [
        {c: copy.deepcopy(maillon[c]) for c in cles}
        for maillon in registre_cible.lire()
        if maillon.get("type_entree") == TYPE_ENTREE
    ]
