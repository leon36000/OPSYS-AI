"""Le constat de trésorerie prévue, tel que M5 le publie au bus (chantier C5 ; DEFINITION-PRODUIT §7 M5 « source de
vérité financière », §7 M8 « pour la finance, M8 consomme M5 et ne recalcule pas »).

Module PUR (ADR-0009, même règle que `constat_cash_libre.py`) : aucune horloge, aucun accès à un registre, aucun
import `opsys`. `outils.py` (l'adaptateur, seul) lit les registres, fait assembler la prévision
(`prevision.assembler`, flux CONNUS et DATÉS seulement, PLAN T4.16-d), donne le rang du constat et le publie. Ici, on
ne fait que RENDRE ce que `prevision.assembler` a rendu, sous la forme du catalogue du socle
(`src/opsys/evenements/catalogue/m5.tresorerie_prevue_constatee.json`, schéma fermé) : aucun montant n'est calculé,
arrondi, additionné ni corrigé. Chaque montant est le texte décimal (jamais un flottant) que
`prevision.vue_prevision` rend déjà à `m5_prevoir_tresorerie` : les deux ne peuvent pas diverger.

CE QUI SORT, ET CE QUI NE SORT PAS. Sort : l'horizon déclaré, le solde minimal prévu et sa semaine (parmi les
semaines CALCULÉES seulement), les semaines sous le seuil (vide quand le seuil n'est pas configuré), la série des
soldes hebdomadaires (un par semaine, `CALCULE` ou `NON_CALCULABLE`, pour le prévu-contre-réel de M8), le statut
d'alerte et le seuil du propriétaire, ce qui manque (par CODE, jamais le détail), l'instant d'émission et la mention
obligatoire. Ne sort JAMAIS : les lignes de flux (leurs sources détaillées se lisent dans `m5_prevoir_tresorerie`),
un texte saisi par le propriétaire, le détail d'un verdict, un client, un fournisseur, un employé. Un renseignement
personnel ne peut donc pas voyager par cet événement, et le catalogue (schéma fermé) le refuse si un producteur
fautif essayait.

UN CONSTAT PAR DATE DE RÉFÉRENCE ET PAR VERSION DES DONNÉES. La version est l'empreinte du calcul
(`prevision_id`) ; la date est celle que l'appelant donne (M5 n'a pas d'horloge). L'identifiant est déterministe :
rang du constat (`sequence`), date, début de la version. Le rang fait qu'un retour à une version antérieure des
données publie un événement DISTINCT : sans lui, le bus avalerait l'événement (no-op) et le consommateur resterait
sur l'état précédent.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from . import analyse, prevision, validation

__all__ = [
    "TYPE_EVENEMENT_TRESORERIE_PREVUE",
    "charge_evenement",
    "construire_trace",
    "entete",
    "identifiant",
    "lire_emission",
    "lire_jour",
    "resume",
]

TYPE_EVENEMENT_TRESORERIE_PREVUE = "m5.tresorerie_prevue_constatee"

_LONGUEUR_VERSION_DANS_L_ID = 16
_JOUR = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_INSTANT = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}[-+][0-9]{2}:[0-9]{2}$")
_STATUT_ALERTE_ATTENDUS = frozenset({"ALERTE", "SEUIL_A_CONFIGURER", "NON_EVALUEE", "AUCUNE"})

# `validation.py` est épinglé par empreinte dans `contracts/admission_paie_preparatoire.v1.json` (génération serveur
# de l'admission paie) : un verdict propre à C5 vit ici, même forme que `validation.construire_verdict`, sans passer
# par sa liste fermée (même patron que `cout_reel.CODE_CERTIFIE_A_RECALCULER`).
_CODE_EMISSION_INVALIDE = "REJ-CONSTAT-EMISSION-INVALIDE"


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


def lire_emission(brut: Any) -> tuple[str | None, dict[str, Any] | None]:
    """`emise_le` (l'instant d'émission, donné par le planificateur) : `(texte, None)` ou `(None, verdict)`. M5 n'a
    pas d'horloge : l'instant vient de l'appelant, jamais deviné, jamais corrigé. Le motif ferme la forme ; la lecture
    par `datetime.fromisoformat` ferme le CALENDRIER et l'horloge (30 février, 25 h, fuseau hors bornes), comme
    `lire_jour` le fait pour une date."""
    if isinstance(brut, str) and _INSTANT.fullmatch(brut):
        try:
            datetime.fromisoformat(brut)
        except ValueError:
            pass
        else:
            return brut, None
    return None, {"code": _CODE_EMISSION_INVALIDE,
                  "detail": f"emise_le : instant ISO 8601 avec fuseau exigé et réel (reçu {brut!r})"}


def identifiant(jour: date, sequence: int, version: str) -> str:
    """L'identifiant de l'événement : `m5-tresorerie-prevue-<rang>-<jour>-<début de la version>`. Déterministe : le
    même constat (même rang, même jour, même version) redonne le même identifiant, donc un no-op du bus."""
    return f"m5-tresorerie-prevue-{sequence}-{jour.isoformat()}-{version[:_LONGUEUR_VERSION_DANS_L_ID]}"


def _semaine_rangee(semaine: Mapping[str, Any]) -> dict[str, Any]:
    """Une semaine de la série pour le prévu-contre-réel de M8 : le rang, le statut et le solde de fin (texte de la
    prévision, jamais recalculé), ou `None` quand elle n'est pas calculable. Jamais zéro à la place d'un manque."""
    statut = semaine["statut"]
    return {
        "semaine": semaine["semaine"],
        "statut": statut,
        "solde_fin_cad": prevision._texte(semaine["solde_fin"]) if statut == "CALCULE" else None,
    }


def _minimal(calculees: list[Mapping[str, Any]]) -> tuple[str | None, int | None]:
    """Le solde minimal prévu (texte) et sa semaine, parmi les semaines CALCULÉES. Aucune semaine calculée : les deux
    sont `None`, jamais zéro."""
    if not calculees:
        return None, None
    basse = min(calculees, key=lambda s: (s["solde_fin"], s["semaine"]))
    return prevision._texte(basse["solde_fin"]), basse["semaine"]


def _semaines_alerte(resultat: Mapping[str, Any]) -> list[int]:
    """Les semaines sous le seuil, telles que `prevision.assembler` les rend ; vide quand le seuil n'est pas
    configuré (jamais une semaine devinée)."""
    alerte = resultat["alerte"]
    if alerte["statut"] == "SEUIL_A_CONFIGURER":
        return []
    return [int(s) for s in alerte["semaines"]]


def _codes_manque(resultat: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Ce qui manque, par CODE (`prevision._groupes_de_manque`), sans détail ni exemple : un code, une ligne."""
    return [
        {"code": groupe["code"], "a_partir_de_semaine": groupe["a_partir_de_semaine"]}
        for groupe in resultat["manque"]
    ]


def charge_evenement(resultat: Mapping[str, Any], jour: date, sequence: int, emise_le: str) -> dict[str, Any]:
    """La charge de `m5.tresorerie_prevue_constatee` pour une prévision que `prevision.assembler` vient de rendre.

    `resultat` : ce que `prevision.assembler` rend (montants en `Decimal`, semaines en `date`) ; `jour` : la date de
    référence, donnée par l'appelant ; `sequence` : le rang du constat au registre de M5 (1 pour le premier) ;
    `emise_le` : l'instant d'émission (ISO 8601 avec fuseau), donné par le planificateur. Chaque montant est le texte
    décimal de `prevision.vue_prevision` (la même lecture que `m5_prevoir_tresorerie`), rien n'est recalculé ici. Le
    minimal et les semaines sous le seuil ne portent que sur les semaines CALCULÉES ; le seuil est celui du
    propriétaire, ou `None` (« seuil à configurer »). `manque` porte les codes de `prevision`, sans détail. Ne lève
    pas sur un résultat de `prevision.assembler` (le catalogue valide la charge à la publication)."""
    if resultat["alerte"]["statut"] not in _STATUT_ALERTE_ATTENDUS:
        raise ValueError(f"statut d'alerte de prévision inconnu : {resultat['alerte']['statut']!r}")
    calculees = [s for s in resultat["semaines"] if s["statut"] == "CALCULE"]
    minimal, semaine_minimale = _minimal(calculees)
    seuil = resultat["alerte"]["seuil"]
    return {
        "evenement_id": identifiant(jour, sequence, resultat["prevision_id"]),
        "sequence": sequence,
        "date_reference": jour.isoformat(),
        "emise_le": emise_le,
        "prevision_id": resultat["prevision_id"],
        "version_donnees": resultat["prevision_id"],
        "devise": "CAD",
        "horizon_semaines": resultat["horizon_semaines"],
        "statut_alerte": resultat["alerte"]["statut"],
        "seuil_cad": None if seuil is None else prevision._texte(seuil),
        "semaines_sous_seuil": _semaines_alerte(resultat),
        "solde_minimal_prevu_cad": minimal,
        "semaine_solde_minimal": semaine_minimale,
        "non_calculable_a_partir_de": resultat["non_calculable_a_partir_de"],
        "manque": _codes_manque(resultat),
        "soldes_hebdo": [_semaine_rangee(s) for s in resultat["semaines"]],
        "mention": analyse.MENTION_ANALYSE_PREPARATOIRE,
    }


def construire_trace(charge: Mapping[str, Any]) -> dict[str, Any]:
    """Le maillon qui trace un constat publié (registre `constats_tresorerie_prevue`, DÉRIVÉ : ni le grand livre, ni
    les factures). Il ne garde que l'en-tête : le rang, le jour, la version, le statut d'alerte et l'identifiant ; la
    charge complète est celle du bus. Aucun instant : la date de référence est la seule date que M5 connaisse
    (DA-M5-06, aucune horloge) ; `emise_le` est l'instant d'émission donné par le planificateur, gardé dans la
    charge, pas dans la trace."""
    return {
        "type_entree": "tresorerie_prevue_constatee",
        "sequence": charge["sequence"],
        "date_reference": charge["date_reference"],
        "version_donnees": charge["version_donnees"],
        "statut_alerte": charge["statut_alerte"],
        "evenement_id": charge["evenement_id"],
    }


def resume(charge: Mapping[str, Any]) -> dict[str, Any]:
    """Ce que la réponse de l'outil dit d'un constat : l'en-tête, le statut d'alerte, les montants tels que publiés,
    ce qui manque. Court, sous la limite de sortie du socle : la charge complète part au bus, M8 la montre."""
    return {
        "evenement_id": charge["evenement_id"],
        "sequence": charge["sequence"],
        "date_reference": charge["date_reference"],
        "emise_le": charge["emise_le"],
        "version_donnees": charge["version_donnees"],
        "horizon_semaines": charge["horizon_semaines"],
        "statut_alerte": charge["statut_alerte"],
        "solde_minimal_prevu_cad": charge["solde_minimal_prevu_cad"],
        "semaine_solde_minimal": charge["semaine_solde_minimal"],
        "semaines_sous_seuil": list(charge["semaines_sous_seuil"]),
        "manque": [dict(m) for m in charge["manque"]],
    }


def entete(constat: Mapping[str, Any]) -> dict[str, Any]:
    """Ce que la réponse de la variante PLANIFIÉE (`m5_constater_tresorerie_prevue_planifie`) dit d'un constat :
    l'en-tête et le statut, avec les CODES de ce qui manque, et RIEN d'autre. Une liste blanche : aucun montant (ni
    minimal prévu, ni seuil, ni soldes hebdomadaires) ne revient à l'appelant ; les montants ne voyagent que par
    l'événement du bus, que M8 montre selon le rôle de celui qui lit. C'est ce qui sépare cette variante (niveau N2,
    planificateur seulement) de `m5_constater_tresorerie_prevue` (N3), dont la réponse porte les montants à la
    personne ou à l'agent qui les a demandés."""
    return {
        "evenement_id": constat["evenement_id"],
        "sequence": constat["sequence"],
        "date_reference": constat["date_reference"],
        "emise_le": constat["emise_le"],
        "version_donnees": constat["version_donnees"],
        "horizon_semaines": constat["horizon_semaines"],
        "statut_alerte": constat["statut_alerte"],
        "manque": [dict(m) for m in constat["manque"]],
    }
