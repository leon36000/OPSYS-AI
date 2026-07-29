"""Détection, signalement et arbitrage humain des doublons potentiels.

Ce module ne regroupe jamais deux leads : il détecte les ressemblances,
inscrit un signalement dans le registre append-only hash-chaîné, puis
consigne l'arbitrage humain. Après signalement comme après arbitrage, les
deux leads demeurent des maillons distincts du registre ; les seuls états
d'arbitrage existants sont ``en_attente`` et ``distincts_confirmes``.
"""

import copy
from datetime import datetime, timezone

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
    La normalisation préalable en UTC garantit qu'un même instant exprimé
    dans deux fuseaux différents donne la même date calendaire, évitant un
    biais inter-fuseau dans le décompte des jours.
    """
    date_a = datetime.fromisoformat(horodatage_a).astimezone(timezone.utc).date()
    date_b = datetime.fromisoformat(horodatage_b).astimezone(timezone.utc).date()
    return abs((date_b - date_a).days) <= FENETRE_JOURS


def _non_vide(valeur) -> bool:
    """Vrai si la valeur est une donnée exploitable (non None, non vide).

    POURQUOI : deux leads dépourvus d'un champ (contact/ville/type_travaux absent
    ou vide) ne doivent JAMAIS se rapprocher — sans ce garde, ``None == None`` ou
    ``"" == ""`` déclencherait faussement un critère sur l'absence de données. Le
    contrat gelé garantit ces champs à l'ingestion, mais la détection opère sur
    des maillons qu'elle ne contrôle pas : elle reste fail-closed.
    """
    return valeur is not None and valeur != "" and valeur != {}


def _critere_entre(contrat_a, contrat_b):
    """Critère de rapprochement entre deux contrats, ou None si aucun.

    Priorité figée : contact_identique > ville_et_travaux. Un critère n'est
    retenu que si les valeurs comparées sont NON VIDES des deux côtés (voir
    _non_vide) — l'absence de données ne constitue pas une similitude.
    """
    contact_a, contact_b = contrat_a.get("contact"), contrat_b.get("contact")
    if _non_vide(contact_a) and contact_a == contact_b:
        return "contact_identique"
    ville_a, ville_b = contrat_a.get("ville"), contrat_b.get("ville")
    travaux_a, travaux_b = contrat_a.get("type_travaux"), contrat_b.get("type_travaux")
    if (_non_vide(ville_a) and ville_a == ville_b
            and _non_vide(travaux_a) and travaux_a == travaux_b):
        return "ville_et_travaux"
    return None


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
        if _critere_entre(contrat_cible, contrat) is None:
            continue
        if not _dans_fenetre(maillon_cible["horodatage"], maillon["horodatage"]):
            continue
        resultat.append(lead_id)
    return resultat


def signaler(registre_cible, lead_id_a, lead_id_b, horodatage) -> tuple[dict | None, dict | None]:
    """Inscrit un signalement de doublon potentiel à l'arbitrage ``en_attente``.

    Le critère de doublon est **déterminé** par le module à partir des contrats
    des deux leads, en suivant la priorité figée contact_identique >
    ville_et_travaux. L'appelant ne le choisit pas.

    Ordre des contrôles figé par le cadrage (POURQUOI : un rejet doit porter
    le premier verdict applicable pour rester déterministe en CI) :
    1. horodatage ISO-8601 avec fuseau, sinon REJ-HORODATAGE-INVALIDE ;
    2. deux identifiants distincts, sinon REJ-TRANSITION-ILLEGALE (un lead
       n'est pas son propre doublon) ;
    3. existence des deux leads via leur maillon ``lead_ingere``, sinon
       REJ-TRANSITION-ILLEGALE ;
    4. les contrats des deux leads doivent présenter une similitude : si
       les contacts sont identiques le critère est ``contact_identique``,
       sinon si la ville ET le type de travaux sont identiques le critère
       est ``ville_et_travaux``, sinon REJ-TRANSITION-ILLEGALE (les deux
       leads ne sont pas des doublons potentiels).
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
    ingeres = _maillons_ingeres(registre_cible)
    ids_ingeres = {maillon["lead_id"] for maillon in ingeres}
    if lead_id_a not in ids_ingeres or lead_id_b not in ids_ingeres:
        return None, verdicts.construire_verdict(
            "REJ-TRANSITION-ILLEGALE",
            detail=f"maillon lead_ingere absent pour {lead_id_a!r} ou {lead_id_b!r}",
        )
    # Récupération des contrats des deux leads
    contrat_a = None
    contrat_b = None
    for maillon in ingeres:
        if maillon["lead_id"] == lead_id_a:
            contrat_a = maillon["contrat"]
        if maillon["lead_id"] == lead_id_b:
            contrat_b = maillon["contrat"]
    # Détermination du critère (même logique que detecter, factorisée pour ne
    # pas diverger : un fix ponctuel non factorisé finit toujours par se
    # désynchroniser entre les deux sites).
    critere = _critere_entre(contrat_a, contrat_b)
    if critere is None:
        return None, verdicts.construire_verdict(
            "REJ-TRANSITION-ILLEGALE",
            detail="les deux leads ne sont pas des doublons potentiels",
        )

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
    entree = {
        "type_entree": TYPE_ENTREE,
        "signalement_id": signalement_id,
        "lead_id_a": signalement_origine["lead_id_a"],
        "lead_id_b": signalement_origine["lead_id_b"],
        "critere": signalement_origine["critere"],
        "horodatage": horodatage_valide,
        "arbitrage": "distincts_confirmes",
    }
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
    cles = ("signalement_id", "lead_id_a", "lead_id_b", "critere", "horodatage", "arbitrage")
    return [
        {c: copy.deepcopy(maillon[c]) for c in cles}
        for maillon in registre_cible.lire()
        if maillon.get("type_entree") == TYPE_ENTREE
    ]
