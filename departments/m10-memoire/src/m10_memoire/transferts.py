"""Mémoire des transferts et des plaintes ouverts par M1 (M10-02, tranche 1).

M1 publie deux événements d'ouverture au bus, dans la MÊME transaction que son registre anti-perte :
``m1.transfert_ouvert`` pour tout transfert, et ``m1.plainte_ouverte`` pour une plainte ou une urgence de sécurité,
EN PLUS du premier. Les deux charges sont volontairement minimales (M1-E) : identifiants, type fermé, catégories
reconnues, niveau, canal, déclencheur, instant. Chacune porte en outre ``conversation_id``, un pseudonyme du
correspondant qui ne doit jamais entrer dans la mémoire M10.

Ce module projette une LISTE BLANCHE, jamais la charge :

- ``transfert_id`` : l'identifiant public du fait (et sa clé d'idempotence) ;
- ``lead_id`` : l'affaire à laquelle le transfert est rattaché par M1, quand elle existe ;
- ``type_transfert`` et ``categories`` : deux ensembles fermés du catalogue ;
- ``niveau`` : N3, N4 ou N5 (un code, jamais un texte) ;
- ``horodatage`` : l'instant de RÉCEPTION fourni par la plateforme, celui de l'événement.

Ne sont jamais copiés : ``conversation_id``, ``evenement_id``, ``canal``, ``declenche_par``, ni aucun champ hors
contrat (contact, texte, résumé, termes). Le champ ``canal`` est écarté parce que le schéma le borne à 40 caractères
sans le fermer : y stocker une valeur serait accepter un texte libre. Une charge hors contrat est refusée en nommant le
CHAMP, jamais sa valeur (elle pourrait être une donnée personnelle).

Deux événements, UN fait. Pour un même transfert, une plainte produit le générique et sa spécialisation. Le fait
canonique dépend du seul ``type_transfert`` (plainte ou urgence -> ``m1.plainte_ouverte``, sinon
``m1.transfert_ouvert``), jamais de l'ordre d'arrivée : les deux ordres donnent le même maillon, et le second événement
est un no-op (``deja_memorise``). Un rejeu sous un autre ``evenement_id`` est aussi un no-op, parce que la clé est
``transfert_id``. Un second fait qui contredirait le premier (autre affaire, autres catégories, autre instant) n'est
jamais fusionné ni écrit : il rend ``identique: False`` et le consommateur le met en quarantaine visible.

``lead_id = null`` : M1 dit qu'aucune affaire n'existe (une plainte prime et n'ouvre jamais de lead). M10 ne déduit
RIEN de ``conversation_id`` ni d'un texte : il rend un résultat explicite ``TRANSFERT-SANS-AFFAIRE``, n'écrit aucun
fait et ne pollue aucune affaire. Le fait reste dans le bus, non rattaché ; ce n'est pas une résolution déguisée.

Confidentialité : un transfert est une donnée personnelle du client (Loi 25). Le maillon est ``CLIENT_PRIVATE``, comme
le client associé de M2. Le paquet de contexte ne le rend qu'aux agents de M1 et M2 (`confidentialite.py`) ; une
consolidation du jour qui en contient un est elle aussi ``CLIENT_PRIVATE`` (`consolidation.py`).

Le bus n'a pas d'acquittement séparé : rendre un résultat marque le reçu ``traite`` ; lever une exception le laisse
``echec`` avec réessais puis quarantaine (ADR-0009 §3). Ici, une charge invalide ou contradictoire lève donc
(``outils.py``), et un transfert sans affaire rend un résultat explicite, pour ne pas envoyer en quarantaine une
plainte légitime que M1 a publiée sans lead.

Module pur (DA-M10-08) : aucun import d'``opsys``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from . import affaire, confidentialite, validation

TYPE_TRANSFERT_OUVERT = "m1.transfert_ouvert"
TYPE_PLAINTE_OUVERTE = "m1.plainte_ouverte"
TYPES = frozenset({TYPE_TRANSFERT_OUVERT, TYPE_PLAINTE_OUVERTE})
TYPE_ENTREE_EVENEMENT = "evenement_memorise"

REJ_TRANSFERT_TYPE_INCONNU = "REJ-TRANSFERT-TYPE-INCONNU"
REJ_TRANSFERT_CHARGE_INVALIDE = "REJ-TRANSFERT-CHARGE-INVALIDE"
REJ_TRANSFERT_CHAMP_MANQUANT = "REJ-TRANSFERT-CHAMP-MANQUANT"
REJ_TRANSFERT_CHAMP_INATTENDU = "REJ-TRANSFERT-CHAMP-INATTENDU"
REJ_TRANSFERT_CHAMP_INVALIDE = "REJ-TRANSFERT-CHAMP-INVALIDE"
REJ_TRANSFERT_HORODATAGE_INVALIDE = "REJ-TRANSFERT-HORODATAGE-INVALIDE"

SANS_AFFAIRE = "TRANSFERT-SANS-AFFAIRE"

_CHAMPS = frozenset(
    {
        "evenement_id", "transfert_id", "conversation_id", "lead_id", "type_transfert", "categories",
        "niveau", "canal", "declenche_par", "horodatage",
    }
)
_TYPES_DE_TRANSFERT = frozenset(
    {"ventes", "estimation", "admin", "finance", "plainte", "urgence", "technique", "proprietaire"}
)
_TYPES_DE_PLAINTE = frozenset({"plainte", "urgence"})
_CATEGORIES = frozenset({"insatisfaction", "degat", "garantie", "avocat", "securite"})
_NIVEAUX = frozenset({"N3", "N4", "N5"})
_DECLENCHEURS = frozenset({"regles", "agent"})
_FORME_TRANSFERT = re.compile(r"^tr-[0-9a-f]{20}$")


class ChampRefuse(ValueError):
    """Un champ de la charge est absent, en trop ou hors de sa forme fermée. ``detail`` nomme le CHAMP, jamais sa
    valeur : elle pourrait être une donnée personnelle."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code} : {detail}")
        self.code = code
        self.detail = detail

    def verdict(self) -> dict[str, Any]:
        return validation.construire_verdict(self.code, self.detail)


def _refus(code: str, detail: str) -> ChampRefuse:
    return ChampRefuse(code, detail)


def _texte(charge: Mapping[str, Any], champ: str, maximum: int) -> str:
    valeur = charge.get(champ)
    if not isinstance(valeur, str) or not valeur or len(valeur) > maximum:
        raise _refus(REJ_TRANSFERT_CHAMP_INVALIDE, champ)
    return valeur


def _instant(charge: Mapping[str, Any], champ: str) -> str:
    valeur = charge.get(champ)
    try:
        instant = datetime.fromisoformat(valeur) if isinstance(valeur, str) else None
    except ValueError:
        instant = None
    if instant is None or instant.utcoffset() is None:
        raise _refus(REJ_TRANSFERT_HORODATAGE_INVALIDE, champ)
    return valeur


def _exiger_les_champs(charge: Mapping[str, Any]) -> None:
    if not isinstance(charge, Mapping):
        raise _refus(REJ_TRANSFERT_CHARGE_INVALIDE, "charge")
    recus = set(charge)
    manquants = sorted(_CHAMPS - recus)
    if manquants:
        raise _refus(REJ_TRANSFERT_CHAMP_MANQUANT, ", ".join(manquants))
    if recus - _CHAMPS:
        # Jamais le nom d'un champ ajouté : un producteur défaillant pourrait y avoir mis une donnée personnelle.
        raise _refus(REJ_TRANSFERT_CHAMP_INATTENDU, "champs hors contrat")


def extraire(type_evenement: str, charge: Mapping[str, Any]) -> dict[str, Any]:
    """La projection en liste blanche d'une charge d'ouverture, ou ``ChampRefuse``.

    ``conversation_id``, ``canal``, ``declenche_par`` et ``evenement_id`` sont VALIDÉS puis écartés : le contrat du
    catalogue est vérifié, mais rien de ce qui peut porter un pseudonyme ou un texte libre n'est gardé.
    """
    if type_evenement not in TYPES:
        raise _refus(REJ_TRANSFERT_TYPE_INCONNU, str(type_evenement))
    _exiger_les_champs(charge)

    evenement_id = _texte(charge, "evenement_id", 128)
    del evenement_id  # identifiant de l'enveloppe du bus, redondant avec la clé du fait
    transfert_id = charge.get("transfert_id")
    if not isinstance(transfert_id, str) or _FORME_TRANSFERT.fullmatch(transfert_id) is None:
        raise _refus(REJ_TRANSFERT_CHAMP_INVALIDE, "transfert_id")
    conversation_id = _texte(charge, "conversation_id", 200)
    del conversation_id  # pseudonyme du correspondant : jamais mémorisé

    lead_id = charge.get("lead_id")
    if lead_id is not None and (not isinstance(lead_id, str) or not affaire.est_lead(lead_id)):
        raise _refus(REJ_TRANSFERT_CHAMP_INVALIDE, "lead_id")

    type_transfert = charge.get("type_transfert")
    if not isinstance(type_transfert, str) or type_transfert not in _TYPES_DE_TRANSFERT:
        raise _refus(REJ_TRANSFERT_CHAMP_INVALIDE, "type_transfert")
    if type_evenement == TYPE_PLAINTE_OUVERTE and type_transfert not in _TYPES_DE_PLAINTE:
        raise _refus(REJ_TRANSFERT_CHAMP_INVALIDE, "type_transfert")

    categories = charge.get("categories")
    if not isinstance(categories, list):
        raise _refus(REJ_TRANSFERT_CHAMP_INVALIDE, "categories")
    if any(not isinstance(categorie, str) or categorie not in _CATEGORIES for categorie in categories):
        raise _refus(REJ_TRANSFERT_CHAMP_INVALIDE, "categories")
    if len(categories) != len(set(categories)):
        raise _refus(REJ_TRANSFERT_CHAMP_INVALIDE, "categories")

    niveau = charge.get("niveau")
    if not isinstance(niveau, str) or niveau not in _NIVEAUX:
        raise _refus(REJ_TRANSFERT_CHAMP_INVALIDE, "niveau")

    _texte(charge, "canal", 40)
    declenche_par = charge.get("declenche_par")
    if not isinstance(declenche_par, str) or declenche_par not in _DECLENCHEURS:
        raise _refus(REJ_TRANSFERT_CHAMP_INVALIDE, "declenche_par")
    horodatage = _instant(charge, "horodatage")

    return {
        "transfert_id": transfert_id,
        "lead_id": lead_id,
        "type_transfert": type_transfert,
        "categories": sorted(categories),
        "niveau": niveau,
        "horodatage": horodatage,
    }


def type_canonique(champs: Mapping[str, Any]) -> str:
    """Le type du SEUL fait gardé pour ce transfert : la spécialisation si le type est plainte/urgence, sinon
    l'ouverture générique. Déterministe, indépendant de l'ordre d'arrivée des deux événements."""
    return TYPE_PLAINTE_OUVERTE if champs["type_transfert"] in _TYPES_DE_PLAINTE else TYPE_TRANSFERT_OUVERT


def est_maillon(maillon: Any) -> bool:
    """Vrai pour un maillon que CE module a écrit : type d'entrée, type de transfert, clé et affaire valides."""
    return (
        isinstance(maillon, Mapping)
        and maillon.get("type_entree") == TYPE_ENTREE_EVENEMENT
        and maillon.get("type_evenement") in TYPES
        and isinstance(maillon.get("transfert_id"), str)
        and _FORME_TRANSFERT.fullmatch(maillon["transfert_id"]) is not None
        and affaire.est_lead(maillon.get("lead_id"))
    )


def type_du_maillon(maillon: Any) -> str | None:
    return maillon["type_evenement"] if est_maillon(maillon) else None


def identifiant(maillon: Any) -> str | None:
    return maillon["transfert_id"] if est_maillon(maillon) else None


def lead_du_maillon(maillon: Any) -> str | None:
    return maillon["lead_id"] if est_maillon(maillon) else None


def resume(maillon: Mapping[str, Any]) -> str:
    """Résumé déterministe, sans identifiant de conversation, sans texte et sans contact."""
    plainte = maillon.get("type_evenement") == TYPE_PLAINTE_OUVERTE
    type_transfert = maillon.get("type_transfert")
    if plainte and type_transfert == "plainte":
        ouverture = "Plainte ouverte"
    elif plainte:
        ouverture = f"Plainte ({type_transfert}) ouverte"
    else:
        ouverture = f"Transfert {type_transfert} ouvert"
    morceaux = [ouverture, f"niveau {maillon.get('niveau')}"]
    categories = [c for c in maillon.get("categories", []) if isinstance(c, str)]
    if categories:
        morceaux.append("catégories : " + ", ".join(categories))
    return " ; ".join(morceaux)


def _trouver(maillons: list[dict[str, Any]], transfert_id: str) -> dict[str, Any] | None:
    return next(
        (maillon for maillon in maillons if est_maillon(maillon) and maillon["transfert_id"] == transfert_id),
        None,
    )


def _identique(existant: Mapping[str, Any], champs: Mapping[str, Any], type_evenement: str) -> bool:
    return existant.get("type_evenement") == type_evenement and all(
        existant.get(cle) == valeur for cle, valeur in champs.items()
    )


def memoriser(
    type_evenement: str, charge: Mapping[str, Any], registre_cible: Any
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Mémorise UN fait par transfert, ou refuse sans rien écrire.

    Rend ``(resultat, None)`` ou ``(None, verdict)``. ``resultat`` : ``maillon`` (ou ``None`` sans affaire),
    ``type_evenement`` canonique, ``transfert_id``, ``lead_id``, ``deja_memorise``, ``identique``, ``ecrit``,
    ``rattachee`` et ``verdict`` (``TRANSFERT-SANS-AFFAIRE`` ou ``None``).
    """
    if type_evenement not in TYPES:
        return None, validation.construire_verdict(REJ_TRANSFERT_TYPE_INCONNU, str(type_evenement))
    try:
        champs = extraire(type_evenement, charge)
    except ChampRefuse as refus:
        return None, refus.verdict()

    canonique = type_canonique(champs)
    if champs["lead_id"] is None:
        # Aucune affaire : aucun fait, aucune déduction depuis conversation_id ou un texte. Le reçu du bus dira
        # explicitement que rien n'a été rattaché ; le résultat est stable, donc un rejeu dit la même chose.
        return {
            "maillon": None,
            "type_evenement": canonique,
            "transfert_id": champs["transfert_id"],
            "lead_id": None,
            "deja_memorise": False,
            "identique": True,
            "ecrit": False,
            "rattachee": False,
            "verdict": SANS_AFFAIRE,
        }, None

    maillons = registre_cible.lire()
    existant = _trouver(maillons, champs["transfert_id"])
    ecrit = False
    if existant is None:
        entree = {
            **champs,
            "type_entree": TYPE_ENTREE_EVENEMENT,
            "type_evenement": canonique,
            "confidentialite": confidentialite.NIVEAU_CLIENT_PRIVE,
        }
        ligne_id = registre_cible.ajouter(entree)
        maillons = registre_cible.lire()
        existant = next(
            (maillon for maillon in maillons if maillon.get("ligne_id") == ligne_id),
            None,
        )
        if existant is None:
            raise RuntimeError("maillon de transfert ajouté introuvable")
        ecrit = True

    return {
        "maillon": existant,
        "type_evenement": canonique,
        "transfert_id": champs["transfert_id"],
        "lead_id": existant.get("lead_id"),
        "deja_memorise": not ecrit,
        "identique": _identique(existant, champs, canonique),
        "ecrit": ecrit,
        "rattachee": True,
        "verdict": None,
    }, None
