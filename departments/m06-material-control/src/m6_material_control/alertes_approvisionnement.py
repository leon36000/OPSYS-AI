"""C9 — alertes d'approvisionnement et rappels : des COMPTES neutres, jamais une accusation ni un nom d'employé.

Ce que ce module calcule, à partir des registres que M6 tient déjà :

- `ecarts_repetes_article` : nombre de constats de variance d'inventaire non nuls pour un article ;
- `items_manquants_repetes_article` : nombre de pertes/bris pour un article ;
- `items_manquants_repetes_equipe` : le même compte, regroupé par ÉQUIPE DÉCLARÉE (l'identifiant du profil des
  équipes, jamais un nom de personne ; un WCT dont l'identifiant n'est pas une équipe déclarée n'est jamais regroupé) ;
- `ajustements_frequents_article` : nombre d'ajustements d'inventaire pour un article ;
- `commande_recue_stock_disparu` : un article dont une réception positive existe et dont le stock théorique est nul ou
  négatif — la commande est arrivée, il n'y a plus rien ;
- `declaration_usage_manquante` : un WCT reçu, dans la fenêtre, sans AUCUN mouvement de matériaux qui le cite ;
- `reception_po_en_retard` : un PO encore `sent_to_supplier` dont l'ancienneté dépasse le délai habituel DÉCLARÉ du
  fournisseur (borne stricte : au-delà, pas à égalité).

Aucune valeur d'affaires n'est inventée. La fenêtre (`fenetre_jours`) et le seuil de répétition (`seuil_repetition`)
sont DÉCLARÉS (réglages de direction, CFG-1). Absents ou illisibles, le module ne compare rien : il rend une entrée
`non_evaluees` qui dit quelle clé déclarer, et les comptes restent visibles sans verdict. Un fournisseur sans
`delai_habituel_jours` n'est pas supposé à délai zéro : son PO part en `non_evaluees`.

Module pur (AGENTS.md, ADR-0009) : aucun import `opsys`, aucune horloge (l'instant est fourni), aucun aléa, aucun
réseau. Les quantités sont en texte décimal canonique (`stock.texte_canonique`), jamais un flottant affiché.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from . import encodage, stock

__all__ = ["TYPES_ALERTE", "calculer", "construire_instantane", "sceller", "version_donnees"]

TYPES_ALERTE = frozenset({
    "ecarts_repetes_article",
    "items_manquants_repetes_article",
    "items_manquants_repetes_equipe",
    "ajustements_frequents_article",
    "commande_recue_stock_disparu",
    "declaration_usage_manquante",
    "reception_po_en_retard",
})

_TYPES_STOCK = frozenset({"RECEPTION", "CONSOMMATION", "RETOUR", "PERTE", "BRIS", "AJUSTEMENT"})
_TYPES_MANQUANT = frozenset({"PERTE", "BRIS"})
_STATUT_ENVOYE = "sent_to_supplier"
_ZERO = Decimal(0)


def _entier(valeur: Any, minimum: int, maximum: int | None = None) -> int | None:
    if (isinstance(valeur, bool) or not isinstance(valeur, int) or valeur < minimum
            or (maximum is not None and valeur > maximum)):
        return None
    return valeur


def _quantite(valeur: Any) -> Decimal | None:
    """Décimal exact d'une quantité auditable (int, float ou Decimal fini, jamais un booléen ni un texte).

    Un maillon relu peut être corrompu (migration, écriture manuelle, ancien bug) : il ne doit jamais faire lever le
    constat. `None` dit « quantité illisible », jamais zéro.
    """
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float, Decimal)):
        return None
    if isinstance(valeur, float) and not math.isfinite(valeur):
        return None
    try:
        decimal = valeur if isinstance(valeur, Decimal) else Decimal(str(valeur))
    except (InvalidOperation, ValueError):
        return None
    return decimal if decimal.is_finite() else None


def _instant(valeur: Any) -> datetime | None:
    if not isinstance(valeur, str):
        return None
    try:
        lu = datetime.fromisoformat(valeur)
    except ValueError:
        return None
    return lu if lu.utcoffset() is not None else None


def _jours_entre(debut: datetime, fin: datetime) -> int:
    return max(0, (fin - debut).days)


def _non_evaluee(type_alerte: str, cle: str, action: str) -> dict[str, Any]:
    return {"type": type_alerte, "cle": cle, "action": action}


def _borne(instant: Any, maintenant: datetime, fenetre_jours: int) -> bool:
    lu = _instant(instant)
    if lu is None:
        return False
    ecart = maintenant - lu
    return 0 <= ecart.total_seconds() <= fenetre_jours * 86400


def _cle_article(alerte: dict[str, Any]) -> tuple[str, str, str]:
    return (alerte["type"], alerte.get("materiau_id") or alerte.get("equipe_id") or "", alerte.get("po_id")
            or alerte.get("wct_id") or "")


def _compte_par(mouvements: Iterable[Mapping[str, Any]], type_mouvement: str) -> Counter:
    compte: Counter = Counter()
    for mouvement in mouvements:
        if (mouvement.get("type_mouvement") == type_mouvement
                and isinstance(mouvement.get("materiau_id"), str)
                and _quantite(mouvement.get("quantite")) is not None):
            compte[mouvement["materiau_id"]] += 1
    return compte


def _compte_variance_non_nulle(mouvements: Iterable[Mapping[str, Any]]) -> tuple[Counter, bool]:
    """Les constats de variance d'inventaire dont l'écart n'est PAS nul, par article, et si une quantité était
    illisible. Un écart nul n'est pas un écart répété ; une quantité corrompue n'est jamais comptée comme un écart."""
    compte: Counter = Counter()
    invalide = False
    for mouvement in mouvements:
        if mouvement.get("type_mouvement") != "VARIANCE_INVENTAIRE":
            continue
        if not isinstance(mouvement.get("materiau_id"), str):
            continue
        quantite = _quantite(mouvement.get("quantite"))
        if quantite is None:
            invalide = True
            continue
        if quantite == 0:
            continue
        compte[mouvement["materiau_id"]] += 1
    return compte, invalide


def calculer(
    *,
    mouvements: Iterable[Mapping[str, Any]] = (),
    bons_commande: Iterable[Mapping[str, Any]] = (),
    fournisseurs: Iterable[Mapping[str, Any]] = (),
    wct_recus: Iterable[Mapping[str, Any]] = (),
    equipes_declarees: set[str] | frozenset[str] | None = None,
    equipes_par_wct: Mapping[str, str] | None = None,
    seuil_repetition: Any = None,
    fenetre_jours: Any = None,
    maintenant: Any = None,
) -> dict[str, Any]:
    """Les alertes et les règles NON ÉVALUÉES à un instant donné. Aucune écriture, aucun ordre implicite."""
    instant = maintenant if isinstance(maintenant, datetime) else _instant(maintenant)
    if instant is None or instant.utcoffset() is not None:
        return {"alertes": [], "non_evaluees": [
            _non_evaluee("horodatage", "maintenant", "Fournir un instant ISO 8601 avec fuseau.")]}
    mouvements = list(mouvements)
    bons_commande = list(bons_commande)
    fournisseurs = list(fournisseurs)
    wct_recus = list(wct_recus)
    fenetre = _entier(fenetre_jours, 1, 365)
    seuil = _entier(seuil_repetition, 2)
    non_evaluees: dict[tuple[str, str], dict[str, Any]] = {}
    if fenetre is None:
        non_evaluees[("faits_recents", "configuration.alertes_approvisionnement.fenetre_jours")] = _non_evaluee(
            "faits_recents", "configuration.alertes_approvisionnement.fenetre_jours",
            "La direction déclare la fenêtre en jours des alertes, entre 1 et 365 (réglage de direction).",
        )
    if seuil is None:
        non_evaluees[("repetitions", "configuration.alertes_approvisionnement.seuil_repetition")] = _non_evaluee(
            "repetitions", "configuration.alertes_approvisionnement.seuil_repetition",
            "La direction déclare à partir de combien de constats un écart est répété (réglage de direction).",
        )
    if fenetre is None:
        return {"alertes": [], "non_evaluees": sorted(non_evaluees.values(), key=lambda n: (n["type"], n["cle"]))}

    alertes: list[dict[str, Any]] = []
    base = {"seuil": seuil, "fenetre_jours": fenetre}

    if seuil is not None:
        variance_compte, variance_invalide = _compte_variance_non_nulle(mouvements)
        if variance_invalide:
            non_evaluees[("quantite_variance", "mouvements.quantite")] = _non_evaluee(
                "ecarts_repetes_article", "mouvements.quantite",
                "La quantité d'au moins une variance est illisible : les écarts répétés ne sont pas évalués. "
                "Corriger le maillon (quantité décimale finie).",
            )
        comptes = [
            ("items_manquants_repetes_article", _compte_par(mouvements, "PERTE") + _compte_par(mouvements, "BRIS")),
            ("ajustements_frequents_article", _compte_par(mouvements, "AJUSTEMENT")),
        ]
        if not variance_invalide:
            comptes.insert(0, ("ecarts_repetes_article", variance_compte))
        for type_alerte, compte in comptes:
            for materiau_id in sorted(compte):
                if compte[materiau_id] >= seuil:
                    alertes.append({
                        "type": type_alerte, "materiau_id": materiau_id, "compte": compte[materiau_id], **base,
                    })

        par_equipe: Counter = Counter()
        equipes_inconnues: set[str] = set()
        for mouvement in mouvements:
            if mouvement.get("type_mouvement") not in _TYPES_MANQUANT:
                continue
            wct_id = mouvement.get("wct_id")
            equipe = (equipes_par_wct or {}).get(wct_id) if isinstance(wct_id, str) else None
            if equipe is None:
                continue
            if equipes_declarees is None or equipe not in equipes_declarees:
                equipes_inconnues.add(equipe)
                continue
            par_equipe[equipe] += 1
        for equipe in sorted(par_equipe):
            if par_equipe[equipe] >= seuil:
                alertes.append({
                    "type": "items_manquants_repetes_equipe", "equipe_id": equipe, "compte": par_equipe[equipe],
                    **base,
                })
        equipe_absente_mais_utilisee = equipes_declarees is None and any(
            (equipes_par_wct or {}).get(m.get("wct_id")) for m in mouvements
            if m.get("type_mouvement") in _TYPES_MANQUANT
        )
        if equipes_inconnues or equipe_absente_mais_utilisee:
            non_evaluees[("equipe", "equipes.liste")] = _non_evaluee(
                "items_manquants_repetes_equipe", "equipes.liste",
                "Déclarer le profil des équipes (identifiants d'équipe) pour regrouper par équipe déclarée, jamais par "
                "personne.",
            )

    stocks: dict[str, Decimal] = {}
    recus: dict[str, Decimal] = {}
    quantites_corrompues = 0
    receptions_sans_date: set[str] = set()
    for mouvement in mouvements:
        type_mouvement = mouvement.get("type_mouvement")
        if type_mouvement not in _TYPES_STOCK or not isinstance(mouvement.get("materiau_id"), str):
            continue
        quantite = _quantite(mouvement.get("quantite"))
        if quantite is None:
            quantites_corrompues += 1
            continue
        materiau_id = mouvement["materiau_id"]
        stocks[materiau_id] = stocks.get(materiau_id, _ZERO) + quantite
        if type_mouvement == "RECEPTION" and quantite > 0:
            horodatage = mouvement.get("horodatage")
            if horodatage is None:
                receptions_sans_date.add(materiau_id)
                recus[materiau_id] = recus.get(materiau_id, _ZERO) + quantite
            elif _borne(horodatage, instant, fenetre):
                recus[materiau_id] = recus.get(materiau_id, _ZERO) + quantite
    if quantites_corrompues:
        non_evaluees[("quantite_stock", "mouvements.quantite")] = _non_evaluee(
            "commande_recue_stock_disparu", "mouvements.quantite",
            f"{quantites_corrompues} mouvement(s) de stock ont une quantité illisible : la règle « commande reçue, "
            "stock disparu » n'est pas évaluée. Corriger ces maillons (quantité décimale finie).",
        )
    else:
        for materiau_id in sorted(recus):
            if recus[materiau_id] > 0 and stocks.get(materiau_id, _ZERO) <= 0:
                alertes.append({
                    "type": "commande_recue_stock_disparu", "materiau_id": materiau_id,
                    "quantite_recue": stock.texte_canonique(recus[materiau_id]),
                    "stock_actuel": stock.texte_canonique(stocks.get(materiau_id, _ZERO)),
                    "fenetre_jours": fenetre,
                })
    for materiau_id in sorted(receptions_sans_date):
        non_evaluees[("faits_recents", f"materiau:{materiau_id}")] = _non_evaluee(
            "commande_recue_stock_disparu", f"materiau:{materiau_id}",
            "Une réception de cet article n'a pas d'horodatage : la fenêtre déclarée ne peut pas l'exclure. "
            "Horodater les mouvements de réception.",
        )

    wct_avec_mouvement = {m.get("wct_id") for m in mouvements if isinstance(m.get("wct_id"), str)}
    for wct in wct_recus:
        wct_id = wct.get("wct_id")
        if not isinstance(wct_id, str) or not wct_id or wct_id in wct_avec_mouvement:
            continue
        completion = _instant(wct.get("horodatage_completion"))
        if completion is None or not _borne(wct.get("horodatage_completion"), instant, fenetre):
            continue
        alertes.append({
            "type": "declaration_usage_manquante", "wct_id": wct_id,
            "intervention_id": wct.get("intervention_id"),
            "jours_depuis_completion": _jours_entre(completion, instant),
            "fenetre_jours": fenetre,
        })

    delais = {
        f.get("fournisseur_id"): f.get("delai_habituel_jours")
        for f in fournisseurs if isinstance(f.get("fournisseur_id"), str)
    }
    for po in bons_commande:
        if po.get("statut") != _STATUT_ENVOYE:
            continue
        po_id = po.get("po_id")
        fournisseur_id = po.get("fournisseur_id")
        envoye = _instant(po.get("horodatage"))
        if (not isinstance(po_id, str) or not po_id or envoye is None
                or not _borne(po.get("horodatage"), instant, fenetre)):
            continue
        delai = _entier(delais.get(fournisseur_id), 1)
        if delai is None:
            non_evaluees[("po", f"fournisseur:{fournisseur_id}:delai_habituel_jours")] = _non_evaluee(
                "reception_po_en_retard", f"fournisseur:{fournisseur_id}:delai_habituel_jours",
                "Déclarer le délai habituel du fournisseur (fiche fournisseur, "
                "delai_habituel_jours).",
            )
            continue
        age = _jours_entre(envoye, instant)
        if age > delai:
            alertes.append({
                "type": "reception_po_en_retard", "po_id": po_id, "fournisseur_id": fournisseur_id,
                "jours_depuis_envoi": age, "delai_habituel_jours": delai,
            })

    alertes.sort(key=_cle_article)
    return {
        "alertes": alertes,
        "non_evaluees": sorted(non_evaluees.values(), key=lambda n: (n["type"], n["cle"])),
    }


def version_donnees(contenu: Mapping[str, Any]) -> str:
    """La version des DONNÉES (16 hexadécimaux) : tout sauf l'identifiant, le jour et l'instant du constat."""
    sans_id = {cle: valeur for cle, valeur in contenu.items()
               if cle not in ("constat_id", "date_reference", "constate_le", "hash_precedent", "hash_maillon")}
    return encodage.empreinte(["m6.alertes_approvisionnement.v1", sans_id])[:16]


def construire_instantane(
    *,
    constate_le: str,
    date_reference: str,
    mouvements: Iterable[Mapping[str, Any]] = (),
    bons_commande: Iterable[Mapping[str, Any]] = (),
    fournisseurs: Iterable[Mapping[str, Any]] = (),
    wct_recus: Iterable[Mapping[str, Any]] = (),
    equipes_declarees: set[str] | frozenset[str] | None = None,
    equipes_par_wct: Mapping[str, str] | None = None,
    seuil_repetition: Any = None,
    fenetre_jours: Any = None,
    maintenant: Any = None,
) -> dict[str, Any]:
    """L'instantané d'alertes, identifiant déterministe compris (`constat_id`)."""
    calcule = calculer(
        mouvements=mouvements, bons_commande=bons_commande, fournisseurs=fournisseurs, wct_recus=wct_recus,
        equipes_declarees=equipes_declarees, equipes_par_wct=equipes_par_wct,
        seuil_repetition=seuil_repetition, fenetre_jours=fenetre_jours, maintenant=maintenant,
    )
    contenu = {
        "date_reference": date_reference,
        "alertes": calcule["alertes"],
        "non_evaluees": calcule["non_evaluees"],
        "comptes": dict(sorted(Counter(a["type"] for a in calcule["alertes"]).items())),
    }
    version = version_donnees(contenu)
    marque = encodage.empreinte(["m6.alertes_approvisionnement.constate_le", constate_le])[:8]
    return {
        "constat_id": f"m6-alertes-{date_reference}-{version}-{marque}",
        "constate_le": constate_le,
        "version_donnees": version,
        **contenu,
    }


def sceller(instantane: Mapping[str, Any], maillon_precedent: Mapping[str, Any] | None) -> dict[str, Any]:
    """Ajoute le lien de chaîne à un instantané (aucune écriture) : `hash_precedent` puis `hash_maillon`."""
    maillon = dict(instantane)
    maillon["hash_precedent"] = maillon_precedent["hash_maillon"] if maillon_precedent else ""
    maillon["hash_maillon"] = encodage.empreinte(
        maillon["constat_id"], maillon["constate_le"], maillon["version_donnees"],
        maillon["alertes"], maillon["non_evaluees"], maillon["comptes"], maillon["hash_precedent"],
    )
    return maillon
