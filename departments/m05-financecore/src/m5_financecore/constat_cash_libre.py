"""Le constat du cash libre, tel que M5 le publie au bus (PLAN T4.19-b ; DEFINITION-PRODUIT §7 M5 « source de
vérité financière », §7 M8 « pour la finance, M8 consomme M5 et ne recalcule pas »).

Module PUR (ADR-0009, même règle que `cash_libre.py`) : aucune horloge, aucun accès à un registre, aucun import
`opsys`. `outils.py` (l'adaptateur, seul) lit les registres, fait calculer le cash libre
(`cash_libre.calculer_cash_libre`), donne le rang du constat et le publie. Ici, on ne fait que RENDRE ce que le
calcul a rendu, sous la forme du catalogue du socle (`src/opsys/evenements/catalogue/m5.cash_libre_constate.json`,
schéma fermé) : aucun montant n'est calculé, arrondi, additionné ni corrigé. Chaque montant est le texte décimal
(jamais un flottant) que `cash_libre.vue_cash_libre` rend déjà à `m5_etat_tresorerie` : les deux ne peuvent pas
diverger.

CE QUI SORT, ET CE QUI NE SORT PAS. Sort : les montants, chaque composante avec sa source (l'origine du chiffre, le
nom, la taille et le début de la tête du registre lu) et sa fraîcheur (la pièce la plus récente et leur nombre), le
statut (calculé, ou non calculable avec ce qui manque, par CODE), la lecture en une phrase, les réserves, les
hypothèses et la mention obligatoire. Ne sort JAMAIS : un texte saisi par le propriétaire (la source d'une
déclaration est dite par son origine, pas par ses mots : elle pourrait nommer un employé), le détail d'un verdict, le
détail d'une composante (TPS et TVQ, PO non calculables, factures sans PO), un client, un fournisseur, un employé.
Un renseignement personnel ne peut donc pas voyager par cet événement, et le catalogue (schéma fermé) le refuse si un
producteur fautif essayait.

UN CONSTAT PAR DATE DE RÉFÉRENCE ET PAR VERSION DES DONNÉES. La version est l'empreinte du calcul
(`cash_libre_id`) ; la date est celle que l'appelant donne (M5 n'a pas d'horloge). L'identifiant est déterministe :
rang du constat (`sequence`), date, début de la version. Le rang fait qu'un retour à une version antérieure des
données (une déclaration du propriétaire remise à sa valeur d'avant) publie un événement DISTINCT : sans lui, le bus
avalerait l'événement (no-op) et le consommateur resterait sur l'état précédent.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date
from typing import Any

from . import cash_libre, validation

__all__ = [
    "TYPE_EVENEMENT_CASH_LIBRE",
    "charge_evenement",
    "construire_trace",
    "identifiant",
    "lire_jour",
    "resume",
]

TYPE_EVENEMENT_CASH_LIBRE = "m5.cash_libre_constate"

_LONGUEUR_VERSION_DANS_L_ID = 16
_JOUR = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_STATUT_CALCULE = "CALCULE"
_STATUT_NON_CALCULABLE = "NON_CALCULABLE"
_ORIGINE_REGISTRE = "REGISTRE"
_ORIGINE_DECLARATION = "DECLARATION_PROPRIETAIRE"
_ORIGINE_AUCUNE = "AUCUNE"


def lire_jour(brut: Any) -> tuple[date | None, dict[str, Any] | None]:
    """`aujourd_hui` : `(date, None)` ou `(None, verdict)`. Le module n'a pas d'horloge et ne devine jamais la
    date : un texte qui n'est pas exactement `AAAA-MM-JJ` (ni un jour du calendrier) est refusé, jamais corrigé."""
    if isinstance(brut, str) and _JOUR.fullmatch(brut):
        try:
            return date.fromisoformat(brut), None
        except ValueError:
            pass
    return None, validation.construire_verdict(
        "REJ-CONSTAT-DATE-INVALIDE", detail=f"aujourd_hui : date AAAA-MM-JJ exigée (reçu {brut!r})"
    )


def identifiant(jour: date, sequence: int, version: str) -> str:
    """L'identifiant de l'événement : `m5-cash-libre-<rang>-<jour>-<début de la version>`. Déterministe : le même
    constat (même rang, même jour, même version) redonne le même identifiant, donc un no-op du bus."""
    return f"m5-cash-libre-{sequence}-{jour.isoformat()}-{version[:_LONGUEUR_VERSION_DANS_L_ID]}"


def _origine(composante: Mapping[str, Any]) -> str:
    """D'où vient le chiffre d'une composante : d'un registre (il est nommé), de la déclaration du propriétaire (un
    montant sans registre), ou d'aucune source (rien de connu). Ne lit que la forme du calcul, jamais un texte
    libre."""
    if composante["source"]["registres"]:
        return _ORIGINE_REGISTRE
    return _ORIGINE_DECLARATION if composante["montant"] is not None else _ORIGINE_AUCUNE


def _composante(vue: Mapping[str, Any], calculee: Mapping[str, Any]) -> dict[str, Any]:
    """Une composante du constat : `vue` est celle de `cash_libre.vue_cash_libre` (montants déjà en texte),
    `calculee` celle de `calculer_cash_libre` (le libellé et l'origine). Une liste blanche : le texte de la source et
    le détail de la composante n'y passent pas."""
    registres = vue["source"].get("registres", [])
    return {
        "id": vue["id"],
        "libelle": calculee["libelle"],
        "statut": vue["statut"],
        "montant_cad": vue["montant"],
        "plancher_cad": vue.get("plancher"),
        "source": {
            "origine": _origine(calculee),
            "registres": [
                {"registre": r["registre"], "taille": r["taille"], "tete": r["tete"]} for r in registres
            ],
        },
        "fraicheur": {
            "derniere_piece": vue["fraicheur"]["derniere_piece"],
            "pieces": vue["fraicheur"]["pieces"],
        },
    }


def charge_evenement(resultat: Mapping[str, Any], jour: date, sequence: int) -> dict[str, Any]:
    """La charge de `m5.cash_libre_constate` pour un cash libre que `calculer_cash_libre` vient de rendre.

    `resultat` : ce que `calculer_cash_libre` rend (montants en `Decimal`) ; `jour` : la date de référence, donnée
    par l'appelant ; `sequence` : le rang du constat au registre de M5 (1 pour le premier). Chaque montant est le
    texte décimal de `cash_libre.vue_cash_libre` (la même lecture que `m5_etat_tresorerie`), rien n'est recalculé
    ici. Le statut dit « calculé » ou « non calculable » ; `manque` porte la composante et le code de chaque manque,
    sans détail. Ne lève pas sur un résultat de `calculer_cash_libre` (le catalogue valide la charge à la
    publication)."""
    vue = cash_libre.vue_cash_libre(resultat)
    version = resultat["cash_libre_id"]
    return {
        "evenement_id": identifiant(jour, sequence, version),
        "sequence": sequence,
        "date_reference": jour.isoformat(),
        "version_donnees": version,
        "devise": "CAD",
        "statut": _STATUT_CALCULE if resultat["calculable"] else _STATUT_NON_CALCULABLE,
        "cash_libre_cad": vue["cash_libre"],
        "au_plus_cad": vue["au_plus"],
        "en_deficit": vue["en_deficit"],
        "lecture": vue["lecture"],
        "solde": _composante(vue["solde"], resultat["solde"]),
        "composantes": [
            _composante(vue_composante, calculee)
            for vue_composante, calculee in zip(vue["composantes"], resultat["composantes"], strict=True)
        ],
        "manque": [{"composante": m["composante"], "code": m["code"]} for m in resultat["manque"]],
        "reserves": list(vue["reserves"]),
        "hypotheses": list(vue["hypotheses"]),
        "mention": vue["mention"],
    }


def construire_trace(charge: Mapping[str, Any]) -> dict[str, Any]:
    """Le maillon qui trace un constat publié (registre `constats_cash_libre`, DÉRIVÉ : ni le grand livre, ni les
    factures). Il ne garde que l'en-tête : le rang, le jour, la version, le statut et l'identifiant ; la charge
    complète est celle du bus. Aucun instant : la date de référence est la seule date que M5 connaisse (DA-M5-06,
    aucune horloge)."""
    return {
        "type_entree": "cash_libre_constate",
        "sequence": charge["sequence"],
        "date_reference": charge["date_reference"],
        "version_donnees": charge["version_donnees"],
        "statut": charge["statut"],
        "evenement_id": charge["evenement_id"],
    }


def resume(charge: Mapping[str, Any]) -> dict[str, Any]:
    """Ce que la réponse de l'outil dit d'un constat : l'en-tête, le statut, les montants tels que publiés, la
    lecture, ce qui manque et les réserves. Court, sous la limite de sortie du socle : la charge complète part au
    bus, M8 la montre."""
    return {
        "evenement_id": charge["evenement_id"],
        "sequence": charge["sequence"],
        "date_reference": charge["date_reference"],
        "version_donnees": charge["version_donnees"],
        "statut": charge["statut"],
        "cash_libre_cad": charge["cash_libre_cad"],
        "au_plus_cad": charge["au_plus_cad"],
        "en_deficit": charge["en_deficit"],
        "lecture": charge["lecture"],
        "manque": [dict(m) for m in charge["manque"]],
        "reserves": list(charge["reserves"]),
    }
