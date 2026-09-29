"""Prévision de trésorerie des flux CONNUS et DATÉS (M5.7, PLAN T4.16-d ; DEFINITION-PRODUIT §7 M5.7).

Ce que le module rend : semaine par semaine, sur un horizon borné, ce que le solde devient si rien ne se passe que ce
que l'entreprise sait déjà : les encaissements et les décaissements CONNUS (montant lu à sa source) et DATÉS (une date
qu'une pièce, une règle du calendrier fiscal ou une déclaration du propriétaire donne). Ce n'est pas une projection
d'activité : aucune vente, aucune dépense, aucune paie ni aucune taxe future n'est supposée, aucune moyenne, aucune
tendance (R-009 : le forecast statistique reste bloqué). Module pur (ADR-0009, même règle que `cash_libre.py`) : aucune
horloge (`aujourd_hui` et l'horizon sont des arguments), aucun réseau, aucun registre, aucun import d'un autre
département. `outils.py` (l'adaptateur, seul) lit les registres et la configuration ; ce module valide, date, place,
additionne et décide.

POINT DE DÉPART : le SOLDE du registre (la composante « solde » du cash libre, T4.16), pas le cash libre lui-même. Le
cash libre a déjà retranché TOUTES les obligations connues (taxes, paies, DAS, comptes à payer, dettes, réserves) :
partir de lui puis retrancher ces mêmes obligations à leur échéance les compterait deux fois. La prévision les applique
donc à leur date sur le solde, et le cash libre d'aujourd'hui est repris tel quel (`cash_libre_prevu` = cash libre +
encaissements déjà tombés : les obligations y sont déjà). Ce sont les mêmes sources que T4.16 : une seule vérité.

SEMAINES : des périodes de 7 jours qui commencent à `aujourd_hui` (la semaine 1 le contient). Le solde d'une semaine est
celui de sa FIN ; un creux au milieu d'une semaine n'est pas vu.

CHAQUE LIGNE PORTE SA SOURCE : d'où vient le montant (la pièce), la date et la RÈGLE qui l'a donnée (échéance du
calendrier fiscal, date déclarée par le propriétaire, ou date de la pièce plus un délai déclaré). Aucune échéance de
paiement n'est enregistrée sur les factures (ni clients, ni fournisseurs) : sans délai déclaré par le propriétaire (GATE
NATHAN), une facture n'a pas de date.

UNE DONNÉE INCONNUE DONNE « NON CALCULABLE À PARTIR DE LA SEMAINE X, MANQUE Y », JAMAIS ZÉRO NI UNE MOYENNE (AGENTS.md,
fail-closed). Deux régimes, selon le sens dans lequel compter zéro se tromperait :
- un DÉCAISSEMENT dont le montant ou la date est inconnu bloque : compter zéro surestimerait le solde. Sa semaine est
  celle de sa date (un décaissement échu tombe en semaine 1), ou la semaine 1 si la date est inconnue (il peut tomber
  n'importe quand). Cette semaine et toutes les suivantes sont non calculables ; les précédentes restent exactes ;
- un ENCAISSEMENT dont le montant ou la date est inconnu, ou déjà échu, n'est PAS compté et est DIT, avec son montant
  connu (prudent : le solde prévu ne peut alors qu'être sous-estimé, jamais surestimé). Un client en retard ne paie pas
  « à la semaine 1 » parce qu'on l'espère.

ALERTE, déterministe : le solde de fin d'une semaine est sous le seuil (`solde_fin` < seuil, strictement). Le seuil est
celui du propriétaire (GATE NATHAN) ; absent ou illisible, l'alerte dit « seuil à configurer » et n'en invente aucun.
Un solde prévu négatif est rendu tel quel (`en_deficit`), un fait et non une alerte : zéro n'est pas un seuil choisi.

CE MODULE NE FAIT JAMAIS : payer, remettre, déclarer, écrire. Il lit et calcule.
`conformite.verifier_aucun_decaissement` le prouve par l'AST (aucune mention d'un mouvement financier, aucun import du
registre).

ARRONDI : aucun. Les montants sont des sommes de montants exacts au cent (un montant qui ne l'est pas est illisible et
n'entre jamais arrondi) ; `_au_cent` ne sert qu'à écrire un zéro « 0.00 » ou un total au cent.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from . import analyse, calendrier_fiscal, cash_libre, encodage, validation

__all__ = [
    "DELAI_MAX_JOURS",
    "ENTREE",
    "HORIZON_MAX",
    "SORTIE",
    "assembler",
    "flux_clients",
    "flux_fournisseurs",
    "flux_obligations",
    "flux_taxes",
    "limites",
    "lire_delai",
    "lire_echeances_obligations",
    "lire_horizon",
    "lire_jour",
    "lire_reglages",
    "lire_seuil",
    "vue_prevision",
    "vue_semaine",
]

HORIZON_MAX = 26
DELAI_MAX_JOURS = 365
ENTREE = "ENTREE"
SORTIE = "SORTIE"

_JOURS_PAR_SEMAINE = 7
_CENT = Decimal("0.01")
_ZERO = Decimal("0")
# Ordre de grandeur au-delà duquel un montant est illisible : 10^12 dollars (même plafond que les comptes à payer).
_EXPOSANT_MAX = 11
_TEXTE_MONTANT = re.compile(r"^[0-9]{1,12}(\.[0-9]{1,2})?$")
_DATE_ISO = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_LONGUEUR_SOURCE_MAX = 120
_LONGUEUR_DETAIL_AFFICHE = 200
_LONGUEUR_IDENTIFIANT_AFFICHE = 40
_EXEMPLES_AFFICHES = 3
_LONGUEUR_TETE_AFFICHEE = 16

_CLES_REGLAGES = frozenset({
    "horizon_semaines", "seuil_alerte", "delai_encaissement_clients_jours", "delai_paiement_fournisseurs_jours",
    "echeances_obligations",
})
_CHAMPS_SEUIL = frozenset({"montant", "source", "au"})
_OBLIGATIONS = ("paies", "das", "dettes")
_CLES_FLUX = frozenset({"id", "sens", "nature", "montant", "date", "regle_de_date", "source", "manque", "reserves"})
_CODE_ECHU = "REJ-PREVISION-ENCAISSEMENT-ECHU"

_LIMITES = (
    "seuls les flux connus et datés sont placés : aucune vente, dépense, paie ni taxe future n'est prévue, et aucune "
    "projection statistique n'est faite",
    "le solde de départ est celui du registre des mouvements (T4.16) : un paiement ou un encaissement que le registre "
    "ignore n'y est pas",
    "un encaissement est placé à son échéance, sans retard de paiement du client ; un encaissement échu ou sans date "
    "n'est pas compté (prudent)",
    "un décaissement échu est placé en semaine 1 : le registre ne constate aucun paiement (prudent)",
    "aucune échéance n'est enregistrée sur les factures : leur date vient d'un délai déclaré par le propriétaire",
    "la taxe d'une période non terminée est celle des factures déjà émises ; un remboursement de taxes n'est jamais "
    "compté ; les dates du calendrier fiscal sont à valider par le CPA ; acomptes provisionnels et CNESST hors "
    "calendrier",
    "le solde d'une semaine est celui de sa fin : un creux au milieu d'une semaine n'est pas vu",
)


def limites() -> list[str]:
    """Ce que la prévision ne sait pas : elles voyagent avec chaque réponse."""
    return list(_LIMITES)


def _verdict(code: str, detail: str = "") -> dict[str, Any]:
    return validation.construire_verdict(code, detail=detail)


# ------------------------------------------------------------------------------------------ petits outils
def _au_cent(valeur: Decimal) -> Decimal:
    return valeur.quantize(_CENT, rounding=ROUND_HALF_UP)


def _somme(valeurs: Iterable[Decimal]) -> Decimal:
    """Somme de montants au cent, rendue au cent (une somme vide vaut `0.00`, jamais `0`)."""
    return _au_cent(sum(valeurs, _ZERO))


def _texte(valeur: Decimal | None) -> str | None:
    """Un montant en texte positionnel au cent (jamais de notation scientifique) ; `None` reste `None`."""
    return None if valeur is None else format(_au_cent(valeur), "f")


def _court(texte: Any, limite: int = _LONGUEUR_IDENTIFIANT_AFFICHE) -> str:
    """Un texte abrégé pour un message : la réponse d'un outil est bornée par le socle (6 000 caractères)."""
    chaine = str(texte)
    return chaine if len(chaine) <= limite else chaine[: limite - 1] + "…"


def _date(valeur: Any) -> date | None:
    if not isinstance(valeur, str) or _DATE_ISO.fullmatch(valeur) is None:
        return None
    try:
        return date.fromisoformat(valeur)
    except ValueError:
        return None


def _jour_de(horodatage: Any) -> date | None:
    """Le jour, tel qu'écrit, d'un horodatage ISO 8601 (ou d'une date) ; `None` s'il est illisible."""
    if not isinstance(horodatage, str):
        return None
    try:
        return datetime.fromisoformat(horodatage).date()
    except ValueError:
        return None


def _montant_valide(valeur: Any) -> Decimal | None:
    """Un montant lisible : `Decimal` fini, zéro ou plus, exactement au cent. `None` sinon : jamais arrondi."""
    if not isinstance(valeur, Decimal) or not valeur.is_finite() or valeur < _ZERO or valeur.adjusted() > _EXPOSANT_MAX:
        return None
    return valeur if valeur == _au_cent(valeur) else None


def _semaine_de(jour: date, aujourd_hui: date) -> int:
    """Numéro (à partir de 1) de la semaine de 7 jours qui contient `jour` ; 0 ou moins si `jour` est déjà passé."""
    return (jour - aujourd_hui).days // _JOURS_PAR_SEMAINE + 1


def _taille(objet: Any) -> int:
    """Taille sérialisée EXACTE telle que `Capacites._tronquer` la mesure (`json.dumps`, sans échappement ASCII)."""
    return len(json.dumps(objet, ensure_ascii=False))


# ------------------------------------------------------------------ ce que le propriétaire décide (configuration)
def lire_jour(brut: Any) -> tuple[date | None, dict[str, Any] | None]:
    """`aujourd_hui` : `(date, None)` ou `(None, verdict)`. Le module n'a pas d'horloge et ne devine jamais la date."""
    jour = _date(brut)
    if jour is None:
        return None, _verdict("REJ-PREVISION-DATE-INVALIDE", f"aujourd_hui : date AAAA-MM-JJ exigée (reçu {brut!r})")
    return jour, None


def lire_horizon(brut: Any) -> tuple[int | None, dict[str, Any] | None]:
    """L'horizon, en semaines : `(entier, None)` ou `(None, verdict)`. Absent : `REJ-PREVISION-HORIZON-A-CONFIGURER`
    (une décision du propriétaire, GATE NATHAN : aucun horizon n'est supposé) ; hors de 1 à `HORIZON_MAX` (ou pas un
    entier, un booléen compris) : `REJ-PREVISION-HORIZON-INVALIDE`."""
    if brut is None:
        return None, _verdict(
            "REJ-PREVISION-HORIZON-A-CONFIGURER",
            "l'horizon de la prévision (en semaines) est une décision du propriétaire (GATE NATHAN) : le déclarer dans "
            "configuration.prevision.horizon_semaines ou le fournir en argument ; aucun horizon n'est supposé",
        )
    if isinstance(brut, bool) or not isinstance(brut, int) or not 1 <= brut <= HORIZON_MAX:
        return None, _verdict(
            "REJ-PREVISION-HORIZON-INVALIDE",
            f"horizon_semaines : entier de 1 à {HORIZON_MAX} exigé (reçu {brut!r})",
        )
    return brut, None


def lire_reglages(brut: Any) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """`configuration.prevision` de `department.yaml`, telle que le propriétaire l'a écrite : `(réglages, None)`, ou
    `({}, verdict)`. Absente : `({}, None)`, chaque décision est alors « à déclarer ». Qui n'est pas un objet ou porte
    une clé inconnue : `REJ-PREVISION-CONFIGURATION-INVALIDE`, jamais une déclaration à moitié lue (une faute de
    frappe ne passe pas en silence)."""
    if brut is None:
        return {}, None
    if not isinstance(brut, Mapping):
        return {}, _verdict("REJ-PREVISION-CONFIGURATION-INVALIDE", "configuration.prevision doit être un objet")
    inconnues = sorted(str(cle) for cle in brut if cle not in _CLES_REGLAGES)
    if inconnues:
        return {}, _verdict(
            "REJ-PREVISION-CONFIGURATION-INVALIDE",
            f"configuration.prevision : clé(s) inconnue(s) {inconnues} (attendu : {sorted(_CLES_REGLAGES)})",
        )
    return dict(brut), None


def lire_seuil(brut: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Le seuil d'alerte (`configuration.prevision.seuil_alerte`) : `({"montant", "source", "au"}, None)` ou `(None,
    verdict)`. Même forme qu'une obligation déclarée : `montant` (texte décimal, 2 décimales au plus, zéro ou plus),
    `source` (qui l'a décidé, 120 caractères au plus) et `au` (AAAA-MM-JJ). Absent :
    `REJ-PREVISION-SEUIL-A-CONFIGURER` ; illisible : `REJ-PREVISION-SEUIL-INVALIDE`, jamais un seuil corrigé en
    silence ni inventé (un « 0.00 » déclaré est un seuil connu)."""
    if brut is None:
        return None, _verdict(
            "REJ-PREVISION-SEUIL-A-CONFIGURER",
            "seuil à configurer : le seuil d'alerte est une décision du propriétaire (GATE NATHAN), à déclarer dans "
            "configuration.prevision.seuil_alerte (montant, source, au) ; aucun seuil n'est supposé",
        )
    montant = jour = None
    source_ok = False
    if isinstance(brut, Mapping) and set(brut) == _CHAMPS_SEUIL:
        texte, source, au = brut["montant"], brut["source"], brut["au"]
        if isinstance(texte, str) and _TEXTE_MONTANT.fullmatch(texte):
            montant = Decimal(texte)
        jour = _date(au)
        source_ok = isinstance(source, str) and 0 < len(source.strip()) <= _LONGUEUR_SOURCE_MAX
    if montant is None or jour is None or not source_ok:
        return None, _verdict(
            "REJ-PREVISION-SEUIL-INVALIDE",
            f"configuration.prevision.seuil_alerte : exactement montant (texte décimal, 2 décimales au plus, zéro ou "
            f"plus), source (texte non vide, {_LONGUEUR_SOURCE_MAX} caractères au plus) et au (AAAA-MM-JJ, entre "
            "guillemets) sont exigés",
        )
    return {"montant": _au_cent(montant), "source": brut["source"].strip(), "au": jour}, None


def lire_delai(brut: Any, cle: str, code_a_declarer: str) -> tuple[int | None, dict[str, Any] | None]:
    """Un délai de paiement, en jours (`configuration.prevision.<cle>`) : `(jours, None)` ou `(None, verdict)`. Absent :
    `code_a_declarer` (une décision du propriétaire, GATE NATHAN : aucune échéance n'est enregistrée sur les factures et
    aucun délai n'est supposé) ; illisible (pas un entier, un booléen, hors de 0 à `DELAI_MAX_JOURS`) :
    `REJ-PREVISION-DELAI-INVALIDE`."""
    if brut is None:
        return None, _verdict(
            code_a_declarer,
            f"aucune échéance n'est enregistrée sur les factures : déclarer configuration.prevision.{cle} (nombre de "
            "jours entre la date de la pièce et son paiement, GATE NATHAN) ; aucun délai n'est supposé",
        )
    if isinstance(brut, bool) or not isinstance(brut, int) or not 0 <= brut <= DELAI_MAX_JOURS:
        return None, _verdict(
            "REJ-PREVISION-DELAI-INVALIDE",
            f"configuration.prevision.{cle} : entier de 0 à {DELAI_MAX_JOURS} jours exigé (reçu {brut!r})",
        )
    return brut, None


def lire_echeances_obligations(brut: Any) -> dict[str, tuple[date | None, dict[str, Any] | None]]:
    """La date de sortie de chaque obligation que le propriétaire déclare (paies, DAS, dettes ; leurs montants sont
    dans `configuration.obligations_declarees`, T4.16) : `{clé: (date, None) ou (None, verdict)}`. Absente :
    `REJ-PREVISION-ECHEANCE-A-DECLARER` ; illisible (pas un objet, une clé inconnue, une date qui n'est pas
    AAAA-MM-JJ) : `REJ-PREVISION-ECHEANCE-INVALIDE` pour les trois, jamais une déclaration à moitié lue."""
    if brut is None:
        brut = {}
    elif not isinstance(brut, Mapping) or set(brut) - set(_OBLIGATIONS):
        invalide = _verdict(
            "REJ-PREVISION-ECHEANCE-INVALIDE",
            f"configuration.prevision.echeances_obligations : un objet dont les clés sont parmi {list(_OBLIGATIONS)}",
        )
        return {cle: (None, invalide) for cle in _OBLIGATIONS}
    resultat: dict[str, tuple[date | None, dict[str, Any] | None]] = {}
    for cle in _OBLIGATIONS:
        valeur = brut.get(cle)
        if valeur is None:
            resultat[cle] = (None, _verdict(
                "REJ-PREVISION-ECHEANCE-A-DECLARER",
                f"la date de sortie de « {cle} » n'est pas connue : déclarer configuration.prevision."
                f"echeances_obligations.{cle} (AAAA-MM-JJ, entre guillemets) ; aucune date n'est supposée",
            ))
            continue
        jour = _date(valeur)
        resultat[cle] = (jour, None) if jour is not None else (None, _verdict(
            "REJ-PREVISION-ECHEANCE-INVALIDE",
            f"configuration.prevision.echeances_obligations.{cle} : date AAAA-MM-JJ, entre guillemets, exigée "
            f"(reçu {valeur!r})",
        ))
    return resultat


# ----------------------------------------------------------------------------------------- les flux, par source
def _flux(
    identifiant: str, sens: str, nature: str, montant: Decimal | None, jour: date | None, regle: str | None,
    source: str, manque: list[dict[str, Any]], reserves: Iterable[str] = (), **extras: Any,
) -> dict[str, Any]:
    """Un flux, toujours de la même forme : ce qui sort ou entre, quand, d'où l'on tient le montant et la date, et ce
    qui manque quand l'un des deux est inconnu (`manque` est vide si tout est connu)."""
    return {
        "id": identifiant, "sens": sens, "nature": nature, "montant": montant, "date": jour, "regle_de_date": regle,
        "source": source, "manque": manque, "reserves": sorted(set(reserves)), **extras,
    }


def flux_clients(
    factures: Iterable[Mapping[str, Any]], delai_jours: int | None, verdict_delai: Mapping[str, Any] | None
) -> list[dict[str, Any]]:
    """Un ENCAISSEMENT par facture cliente envoyée (`ENVOYEE` : la seule encore due ; une brouillon n'est pas envoyée,
    une payée ou une annulée n'est plus due), pour son montant après taxes, à la date de son envoi plus le délai
    déclaré par le propriétaire (`delai_jours`). Sans délai (`delai_jours` nul, `verdict_delai` dit quoi déclarer) ou
    avec une date ou un montant illisible, le flux est INCONNU : il porte son `manque` et n'est jamais compté
    (`assembler`). Une facture de zéro n'est pas un flux."""
    if delai_jours is None and verdict_delai is None:
        raise ValueError("un délai absent doit venir avec le verdict qui dit quoi déclarer")
    flux = []
    for facture in sorted(factures, key=lambda f: str(f.get("facture_id"))):
        identifiant = str(facture.get("facture_id"))
        montant = _montant_valide(facture.get("montant_apres_taxes"))
        if montant == _ZERO:
            continue
        envoi = _jour_de(facture.get("date_envoi"))
        manque: list[dict[str, Any]] = []
        if montant is None:
            manque.append(_verdict(
                "REJ-CREANCES-MONTANT-ILLISIBLE", f"facture {_court(identifiant)} : montant illisible"))
        jour = None
        if envoi is None:
            manque.append(_verdict(
                "REJ-CREANCES-DATE-ENVOI-INVALIDE", f"facture {_court(identifiant)} : date d'envoi illisible"))
        elif delai_jours is None:
            manque.append(dict(verdict_delai or {}))
        else:
            jour = envoi + timedelta(days=delai_jours)
        flux.append(_flux(
            f"client:{identifiant}", ENTREE, "facture_client", montant, jour,
            None if jour is None else f"envoi du {envoi} + {delai_jours} jours (délai déclaré par le propriétaire)",
            f"facture client {identifiant}" + ("" if envoi is None else f" envoyée le {envoi}"),
            manque,
        ))
    return flux


def _jour_de_la_dette(dette: Mapping[str, Any]) -> date | None:
    return _jour_de(dette.get("date_base"))


def flux_fournisseurs(
    dettes: Iterable[Mapping[str, Any]] | None, delai_jours: int | None, verdict_delai: Mapping[str, Any] | None,
    verdict_dettes: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Un DÉCAISSEMENT par dette envoyée par `comptes_a_payer.dettes_datables` : chaque facture fournisseur vivante, à
    sa date imprimée, et l'attendu non facturé de chaque PO, à sa PREMIÈRE réception (la date la plus prudente), plus
    le délai de paiement déclaré par le propriétaire. Un attendu porte la réserve de l'unité des prix (T4.15).

    Sans délai, ou avec une date ou un montant inconnu, le flux est INCONNU et BLOQUE la prévision (`assembler`) :
    compter zéro surestimerait le solde. `dettes` nul (un taux fiscal manque : `verdict_dettes` le dit) : une seule
    dette inconnue, sans montant ni date, qui bloque dès la semaine 1."""
    if dettes is None:
        if verdict_dettes is None:
            raise ValueError("des dettes absentes doivent venir avec le verdict qui dit pourquoi")
        return [_flux(
            "fournisseur:inconnu", SORTIE, "facture_fournisseur", None, None, None,
            "comptes à payer : non calculables", [dict(verdict_dettes)],
        )]
    if delai_jours is None and verdict_delai is None:
        raise ValueError("un délai absent doit venir avec le verdict qui dit quoi déclarer")
    flux = []
    for dette in dettes:
        attendu = dette["type"] == "ATTENDU"
        base = _jour_de_la_dette(dette)
        manque = [_verdict(code, f"attendu du PO {_court(dette['po_id'])}") for code in dette["manque"]]
        jour = None
        if base is None:
            manque.append(_verdict(
                "REJ-CASH-FACTURE-ILLISIBLE", f"dette {_court(dette['id'])} : date de départ illisible"))
        elif delai_jours is None:
            manque.append(dict(verdict_delai or {}))
        else:
            jour = base + timedelta(days=delai_jours)
        montant = _montant_valide(dette["montant"])
        if dette["montant"] is not None and montant is None:
            manque.append(_verdict(
                "REJ-AP-MONTANT-ILLISIBLE", f"dette {_court(dette['id'])} : montant illisible"))
        source = (
            f"attendu non facturé du PO {dette['po_id']}, première réception le {base}" if attendu
            else f"facture fournisseur {dette['fournisseur_id']} n° {dette['numero_facture']} du {base}"
        )
        flux.append(_flux(
            f"{'attendu' if attendu else 'fournisseur'}:{dette['id']}", SORTIE,
            "attendu_fournisseur" if attendu else "facture_fournisseur", montant, jour,
            None if jour is None else (
                f"{'première réception' if attendu else 'facture'} du {base} + {delai_jours} jours "
                "(délai déclaré par le propriétaire)"),
            source, manque, dette["reserves"],
        ))
    return flux


def _couvert_jusqu_au(periodes: list[Mapping[str, Any]], remises: date) -> date:
    """La fin de la dernière période du calendrier CONTIGUË à la dernière remise : au-delà, il ne date rien."""
    courant = remises
    for periode in periodes:
        if periode["debut"] == courant + timedelta(days=1):
            courant = periode["fin"]
        elif periode["debut"] > courant + timedelta(days=1):
            break
    return courant


def _taxes_inconnues(identifiant: str, verdict: Mapping[str, Any]) -> dict[str, Any]:
    return _flux(
        identifiant, SORTIE, "taxes", None, None, None, "TPS/TVQ à remettre : échéances inconnues", [dict(verdict)])


def flux_taxes(
    clients: list[Mapping[str, Any]], fournisseurs: list[Mapping[str, Any]],
    calendrier: Mapping[int, Mapping[str, Any]] | None, verdict_calendrier: Mapping[str, Any] | None,
    fiscal: Any, aujourd_hui: date,
) -> list[dict[str, Any]]:
    """Un DÉCAISSEMENT par période de déclaration TPS/TVQ pas encore remise, à la limite de paiement du calendrier
    fiscal (`calendrier_fiscal`, transcrite de Revenu Québec, à valider par le CPA), pour la TPS/TVQ NETTE des
    factures de cette période (`cash_libre.calculer_taxes_nettes` : la même règle qu'au cash libre). Une période sans
    taxe à remettre (zéro, ou un remboursement, jamais de l'argent) n'est pas un flux. La taxe d'une période non
    terminée est celle des factures déjà émises (`partielle`) ; une limite échue tombe en semaine 1 (`assembler`).

    `clients` : les factures `ENVOYEE` et `PAYEE` ; `fournisseurs` : les factures saisies vivantes (T4.15). Ce qui
    empêche de dater ou de chiffrer est un flux INCONNU qui bloque : le calendrier illisible ou d'une année non
    déclarée, la fréquence, la fin d'exercice, le statut d'inscrit ou la dernière remise non déclarés (les verdicts de
    T4.16), une remise qui n'a pas fini avant `aujourd_hui`, des factures datées après la fin du calendrier connu, ou
    une facture dont la date ou la taxe est illisible (`REJ-CASH-FACTURE-ILLISIBLE`, à la limite de la période)."""
    if calendrier is None:
        return [_taxes_inconnues("taxes:calendrier", verdict_calendrier or _verdict(
            "REJ-CALENDRIER-INVALIDE", "le calendrier fiscal n'a pas pu être lu"))]
    configuration, verdict = calendrier_fiscal.lire_configuration_fiscale(fiscal)
    if verdict is not None:
        return [_taxes_inconnues("taxes:configuration", verdict)]
    remises, verdict = calendrier_fiscal.lire_taxes_remises(fiscal, calendrier, configuration)
    if verdict is not None:
        return [_taxes_inconnues("taxes:remise", verdict)]
    if remises >= aujourd_hui:
        return [_taxes_inconnues("taxes:remise", _verdict(
            "REJ-FISCAL-CONFIGURATION-INVALIDE",
            f"taxes_remises_jusqu_au {remises} : une période remise a fini avant le {aujourd_hui}"))]
    periodes = sorted(
        (p for p in calendrier_fiscal.periodes_applicables(calendrier, configuration, sorted(calendrier))
         if p["fin"] > remises),
        key=lambda p: p["debut"],
    )
    couvert = _couvert_jusqu_au(periodes, remises)
    flux: list[dict[str, Any]] = []
    apres_le_calendrier = cash_libre.calculer_taxes_nettes(clients, fournisseurs, apres=couvert)
    if apres_le_calendrier["factures_clients"] + apres_le_calendrier["factures_fournisseurs"]:
        flux.append(_taxes_inconnues("taxes:couverture", _verdict(
            "REJ-CALENDRIER-ANNEE-NON-DECLAREE",
            f"des factures sont datées après le {couvert}, fin du calendrier fiscal connu : leur échéance n'est pas "
            f"au calendrier (années déclarées : {sorted(calendrier)}) ; ajouter l'année à "
            "contracts/calendrier_fiscal.v1.yaml depuis les tableaux officiels de Revenu Québec")))
    for periode in periodes:
        if periode["debut"] > couvert:
            break
        taxes = cash_libre.calculer_taxes_nettes(
            clients, fournisseurs, apres=max(remises, periode["debut"] - timedelta(days=1)), jusqu_a=periode["fin"])
        identifiant = f"taxes:{periode['debut']}:{periode['fin']}"
        version = calendrier[periode["fin"].year]["version"]
        regle = f"limite de paiement du calendrier fiscal {version} (à valider par le CPA)"
        if taxes["illisibles"]:
            flux.append(_flux(
                identifiant, SORTIE, "taxes", None, periode["limite_paiement"], regle,
                f"TPS/TVQ de la période du {periode['debut']} au {periode['fin']}",
                [_verdict(
                    "REJ-CASH-FACTURE-ILLISIBLE",
                    f"{len(taxes['illisibles'])} facture(s) dont la date ou la taxe est illisible : "
                    f"{', '.join(_court(i) for i in taxes['illisibles'][:_EXEMPLES_AFFICHES])}")],
            ))
        elif taxes["total_a_remettre"] > _ZERO:
            a_remettre = taxes["a_remettre"]
            flux.append(_flux(
                identifiant, SORTIE, "taxes", taxes["total_a_remettre"], periode["limite_paiement"], regle,
                f"TPS/TVQ nette de la période du {periode['debut']} au {periode['fin']} : TPS "
                f"{_texte(a_remettre['tps_federale'])} + TVQ {_texte(a_remettre['tvq_quebec'])}"
                + (" (période non terminée : factures déjà émises)" if periode["fin"] >= aujourd_hui else ""),
                [], partielle=periode["fin"] >= aujourd_hui,
            ))
    return flux


def flux_obligations(
    composantes: Mapping[str, Mapping[str, Any]],
    echeances: Mapping[str, tuple[date | None, Mapping[str, Any] | None]],
) -> list[dict[str, Any]]:
    """Un DÉCAISSEMENT par obligation que le propriétaire déclare (paies, DAS, dettes) : le montant est celui de la
    composante du cash libre (`cash_libre.composante_declaree` : une seule déclaration, une seule source), la date
    celle de `configuration.prevision.echeances_obligations` (`lire_echeances_obligations`). Un « 0.00 » déclaré est
    un zéro connu : rien ne sort, aucune date n'est exigée. Un montant non déclaré ou illisible (le manque de la
    composante) ou une date absente rend le flux INCONNU : il bloque."""
    flux = []
    for cle in _OBLIGATIONS:
        composante = composantes[cle]
        montant = composante["montant"]
        if montant is not None and montant == _ZERO:
            continue
        jour, verdict_date = echeances[cle]
        manque = [dict(m) for m in composante["manque"]]
        if jour is None:
            manque.append(dict(verdict_date or {}))
        flux.append(_flux(
            f"obligation:{cle}", SORTIE, cle, montant, jour,
            None if jour is None else "date de sortie déclarée par le propriétaire "
            "(configuration.prevision.echeances_obligations)",
            composante["source"]["description"], manque,
        ))
    return flux


# --------------------------------------------------------------------------------------------- l'assemblage
def _controler_flux(flux: Any) -> dict[str, Any]:
    """Le flux tel quel s'il est bien formé. LÈVE `ValueError` sur une erreur d'assemblage du code (ce n'est pas une
    donnée de l'entreprise, c'est un défaut à corriger) : un flux mal formé, ou inconnu sans dire ce qui manque."""
    if not isinstance(flux, Mapping) or not set(flux) >= _CLES_FLUX:
        raise ValueError(f"flux mal formé (clés attendues : {sorted(_CLES_FLUX)})")
    if flux["sens"] not in (ENTREE, SORTIE):
        raise ValueError(f"flux {flux['id']} : sens inconnu {flux['sens']!r}")
    montant, jour = flux["montant"], flux["date"]
    if montant is not None and (type(montant) is not Decimal or not montant.is_finite() or montant < _ZERO):
        raise ValueError(f"flux {flux['id']} : montant fini et non négatif exigé")
    if jour is not None and type(jour) is not date:
        raise ValueError(f"flux {flux['id']} : la date doit être une date (jamais un texte ni un horodatage)")
    if (montant is None or jour is None) and not flux["manque"]:
        raise ValueError(f"flux {flux['id']} : inconnu sans dire ce qui manque (on ne saurait pas quoi demander)")
    return dict(flux)


def _controler_entrees(
    aujourd_hui: Any, horizon: Any, solde: Any, seuil: Any, verdict_seuil: Any
) -> None:
    if type(aujourd_hui) is not date:
        raise ValueError("aujourd_hui : une date exigée (jamais un texte ni un horodatage)")
    if isinstance(horizon, bool) or not isinstance(horizon, int) or not 1 <= horizon <= HORIZON_MAX:
        raise ValueError(f"horizon : entier de 1 à {HORIZON_MAX} exigé")
    if not isinstance(solde, Mapping) or "montant" not in solde or "manque" not in solde:
        raise ValueError("solde : la composante du cash libre est exigée")
    montant = solde["montant"]
    if montant is None:
        if not solde["manque"]:
            raise ValueError("solde inconnu sans dire ce qui manque")
    elif type(montant) is not Decimal or not montant.is_finite():
        raise ValueError("solde : montant fini exigé")
    if seuil is None and verdict_seuil is None:
        raise ValueError("un seuil absent doit venir avec le verdict qui dit quoi configurer")
    if seuil is not None and (type(seuil["montant"]) is not Decimal or seuil["montant"] < _ZERO):
        raise ValueError("seuil : montant non négatif exigé")


def _cle_de_tri(flux: Mapping[str, Any]) -> tuple[Any, ...]:
    """Ordre total et stable : par date (les inconnues à la fin), les sorties avant les entrées, puis nature et id."""
    jour = flux["date"]
    return jour is None, jour or date.min, 0 if flux["sens"] == SORTIE else 1, flux["nature"], flux["id"]


def _bloqueurs(flux: Mapping[str, Any], semaine: int) -> list[dict[str, Any]]:
    return [
        {"semaine": semaine, "code": m["code"], "detail": m["detail"], "flux": flux["id"]} for m in flux["manque"]
    ]


def _groupes_de_manque(bloqueurs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ce qui manque, PAR CODE : la première semaine touchée, les flux concernés (leurs identifiants) et de quoi
    comprendre. Un code, une ligne : cent factures sans délai ne font pas cent lignes."""
    groupes: dict[str, dict[str, Any]] = {}
    for bloqueur in bloqueurs:
        groupe = groupes.setdefault(bloqueur["code"], {
            "code": bloqueur["code"], "a_partir_de_semaine": bloqueur["semaine"], "flux": [],
            "detail": bloqueur["detail"],
        })
        groupe["a_partir_de_semaine"] = min(groupe["a_partir_de_semaine"], bloqueur["semaine"])
        if bloqueur["flux"] not in groupe["flux"]:
            groupe["flux"].append(bloqueur["flux"])
    return sorted(groupes.values(), key=lambda g: (g["a_partir_de_semaine"], g["code"]))


def _resume_au_dela(flux: list[Mapping[str, Any]]) -> dict[str, Any]:
    connus = [f["montant"] for f in flux if f["montant"] is not None]
    return {"nombre": len(flux), "total": _somme(connus), "non_chiffres": len(flux) - len(connus)}


def _groupes_non_comptes(non_comptes: list[tuple[Mapping[str, Any], str]]) -> list[dict[str, Any]]:
    groupes: dict[str, dict[str, Any]] = {}
    for flux, code in non_comptes:
        groupe = groupes.setdefault(code, {"code": code, "flux": [], "connus": []})
        groupe["flux"].append(flux["id"])
        if flux["montant"] is not None:
            groupe["connus"].append(flux["montant"])
    return [
        {"code": code, "nombre": len(g["flux"]), "montant_connu": _somme(g["connus"]), "flux": g["flux"]}
        for code, g in sorted(groupes.items())
    ]


def _alerte(
    semaines: list[dict[str, Any]], seuil: Mapping[str, Any] | None, verdict_seuil: Mapping[str, Any] | None,
    bloque_des: int | None,
) -> dict[str, Any]:
    sous = [s["semaine"] for s in semaines if s["sous_seuil"]]
    if seuil is None:
        statut = "SEUIL_A_CONFIGURER"
    elif sous:
        statut = "ALERTE"
    elif bloque_des is not None:
        statut = "NON_EVALUEE"
    else:
        statut = "AUCUNE"
    return {
        "statut": statut,
        "seuil": None if seuil is None else seuil["montant"],
        "source_du_seuil": None if seuil is None else {"source": seuil["source"], "au": seuil["au"]},
        "semaines": sous,
        "premiere_semaine": sous[0] if sous else None,
        "non_evaluee_a_partir_de": bloque_des,
        "manque": None if seuil is not None else dict(verdict_seuil or {}),
    }


def assembler(
    aujourd_hui: date, horizon_semaines: int, solde: Mapping[str, Any], flux: Iterable[Mapping[str, Any]], *,
    seuil: Mapping[str, Any] | None = None, verdict_seuil: Mapping[str, Any] | None = None,
    cash_libre_resultat: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """La prévision : le solde de départ (`solde`, la composante du cash libre), les `flux` (les listes de
    `flux_clients`, `flux_fournisseurs`, `flux_taxes` et `flux_obligations`) placés dans les `horizon_semaines`
    semaines qui commencent à `aujourd_hui`, et le solde de fin de chaque semaine.

    Placement : un flux est dans la semaine de sa date. Un DÉCAISSEMENT échu (date passée) tombe en semaine 1
    (`echu`). Un flux daté après l'horizon n'est pas placé : il est seulement AGRÉGÉ (`au_dela_de_l_horizon`, pour voir
    ce qui vient juste après). Un ENCAISSEMENT inconnu ou échu n'est pas compté, et il est DIT
    (`encaissements_non_comptes`). Un DÉCAISSEMENT inconnu bloque à partir de sa semaine (la semaine 1 si sa date est
    inconnue), comme un solde inconnu. Toutes les semaines à partir de là sont `NON_CALCULABLE`, sans aucun chiffre, et
    `manque` dit, par code, quoi demander.

    `seuil` (`lire_seuil`) et son `verdict_seuil` : le seuil d'alerte du propriétaire, ou ce qu'il faut configurer.
    `cash_libre_resultat` : le résultat de `cash_libre.calculer_cash_libre`, dont `cash_libre_prevu` part (le cash
    libre d'aujourd'hui plus les encaissements déjà tombés : les obligations y sont déjà retranchées) ; sans lui, ou
    s'il est non calculable, aucun cash libre prévu n'est donné.

    Rend un résultat complet en `Decimal` et en `date` (`vue_prevision` et `vue_semaine` le rendent en texte), avec
    une empreinte (`prevision_id`) : les mêmes entrées, dans n'importe quel ordre, donnent le même résultat. Lève
    `ValueError` sur une erreur d'assemblage du code (entrées mal formées, deux flux de même identifiant)."""
    _controler_entrees(aujourd_hui, horizon_semaines, solde, seuil, verdict_seuil)
    liste = sorted((_controler_flux(f) for f in flux), key=_cle_de_tri)
    identifiants = [f["id"] for f in liste]
    if len(set(identifiants)) != len(identifiants):
        raise ValueError("deux flux portent le même identifiant")

    fin_horizon = aujourd_hui + timedelta(days=_JOURS_PAR_SEMAINE * horizon_semaines - 1)
    par_semaine: dict[int, list[dict[str, Any]]] = {k: [] for k in range(1, horizon_semaines + 1)}
    bloqueurs: list[dict[str, Any]] = []
    non_comptes: list[tuple[dict[str, Any], str]] = []
    au_dela: dict[str, list[dict[str, Any]]] = {ENTREE: [], SORTIE: []}
    if solde["montant"] is None:
        bloqueurs.extend(_bloqueurs({"id": "solde", "manque": solde["manque"]}, 1))
    for f in liste:
        jour = f["date"]
        if f["sens"] == ENTREE:
            if f["montant"] is None or jour is None:
                non_comptes.append((f, f["manque"][0]["code"]))
                continue
            semaine = _semaine_de(jour, aujourd_hui)
            if semaine < 1:
                non_comptes.append((f, _CODE_ECHU))
            elif semaine > horizon_semaines:
                au_dela[ENTREE].append(f)
            else:
                par_semaine[semaine].append({**f, "echu": False})
        elif jour is None:
            bloqueurs.extend(_bloqueurs(f, 1))
        else:
            semaine = _semaine_de(jour, aujourd_hui)
            echu = semaine < 1
            semaine = max(semaine, 1)
            if semaine > horizon_semaines:
                au_dela[SORTIE].append(f)
                continue
            par_semaine[semaine].append({**f, "echu": echu})
            if f["montant"] is None:
                bloqueurs.extend(_bloqueurs(f, semaine))

    bloque_des = min((b["semaine"] for b in bloqueurs), default=None)
    cash = None if cash_libre_resultat is None else cash_libre_resultat["cash_libre"]
    solde_courant = solde["montant"]
    semaines: list[dict[str, Any]] = []
    for k in range(1, horizon_semaines + 1):
        debut = aujourd_hui + timedelta(days=_JOURS_PAR_SEMAINE * (k - 1))
        ligne = {
            "semaine": k, "debut": debut, "fin": debut + timedelta(days=_JOURS_PAR_SEMAINE - 1),
            "statut": "NON_CALCULABLE", "solde_debut": None, "entrees": None, "sorties": None, "solde_fin": None,
            "cash_libre_prevu": None, "sous_seuil": None, "en_deficit": None, "lignes": par_semaine[k],
        }
        if bloque_des is None or k < bloque_des:
            entrees = _somme(f["montant"] for f in par_semaine[k] if f["sens"] == ENTREE)
            sorties = _somme(f["montant"] for f in par_semaine[k] if f["sens"] == SORTIE)
            solde_fin = solde_courant + entrees - sorties
            if cash is not None:
                cash = cash + entrees
            ligne.update({
                "statut": "CALCULE", "solde_debut": solde_courant, "entrees": entrees, "sorties": sorties,
                "solde_fin": solde_fin, "cash_libre_prevu": cash, "en_deficit": solde_fin < _ZERO,
                "sous_seuil": None if seuil is None else solde_fin < seuil["montant"],
            })
            solde_courant = solde_fin
        semaines.append(ligne)

    calculees = [s for s in semaines if s["statut"] == "CALCULE"]
    plus_bas = min(calculees, key=lambda s: (s["solde_fin"], s["semaine"]), default=None)
    en_deficit = [s["semaine"] for s in calculees if s["en_deficit"]]
    contenu = {
        "type": "PREVISION_TRESORERIE",
        "aujourd_hui": aujourd_hui,
        "horizon_semaines": horizon_semaines,
        "fin_horizon": fin_horizon,
        "solde": solde,
        "cash_libre": {
            "montant": None if cash_libre_resultat is None else cash_libre_resultat["cash_libre"],
            "manque": [] if cash_libre_resultat is None else list(cash_libre_resultat["manque"]),
        },
        "calculable": bloque_des is None,
        "non_calculable_a_partir_de": bloque_des,
        "manque": _groupes_de_manque(bloqueurs),
        "semaines": semaines,
        "alerte": _alerte(semaines, seuil, verdict_seuil, bloque_des),
        "plus_bas": None if plus_bas is None else {"semaine": plus_bas["semaine"], "solde": plus_bas["solde_fin"]},
        "premiere_semaine_en_deficit": en_deficit[0] if en_deficit else None,
        "au_dela_de_l_horizon": {
            "entrees": _resume_au_dela(au_dela[ENTREE]), "sorties": _resume_au_dela(au_dela[SORTIE])},
        "encaissements_non_comptes": _groupes_non_comptes(non_comptes),
        "reserves": sorted({code for f in liste for code in f["reserves"]}),
    }
    return {**contenu, "prevision_id": encodage.empreinte(contenu)}


# ---------------------------------------------------------------------------------------------------- les vues
def _lecture(resultat: Mapping[str, Any]) -> str:
    """Une phrase, faite des seuls faits du résultat : rien n'est calculé ici."""
    semaines = resultat["semaines"]
    x = resultat["non_calculable_a_partir_de"]
    alerte = resultat["alerte"]
    if x is not None:
        phrase = (
            "Prévision non calculable dès la semaine 1 : aucun chiffre n'est donné (voir manque)." if x == 1 else
            f"Prévision non calculable à partir de la semaine {x} (voir manque) : les semaines 1 à {x - 1} sont "
            "calculées."
        )
    else:
        fin = semaines[-1]
        phrase = (
            f"Solde prévu : {_texte(resultat['solde']['montant'])} $ aujourd'hui, "
            f"{_texte(fin['solde_fin'])} $ à la fin de la semaine {fin['semaine']} ; le plus bas : "
            f"{_texte(resultat['plus_bas']['solde'])} $ (semaine {resultat['plus_bas']['semaine']})."
        )
    if alerte["statut"] == "ALERTE":
        phrase += (
            f" Alerte : sous le seuil de {_texte(alerte['seuil'])} $ en semaine(s) "
            f"{', '.join(str(s) for s in alerte['semaines'])}."
        )
    elif alerte["statut"] == "SEUIL_A_CONFIGURER":
        phrase += " Seuil à configurer : aucune alerte n'est évaluée."
    elif alerte["statut"] == "NON_EVALUEE":
        phrase += f" Aucune alerte parmi les semaines calculées ; à partir de la semaine {x}, elle n'est pas évaluée."
    if resultat["premiere_semaine_en_deficit"] is not None:
        phrase += f" Solde prévu négatif dès la semaine {resultat['premiere_semaine_en_deficit']}."
    return phrase


def _vue_ligne(flux: Mapping[str, Any]) -> dict[str, Any]:
    vue: dict[str, Any] = {
        "id": flux["id"], "sens": flux["sens"], "nature": flux["nature"], "date": flux["date"].isoformat(),
        "montant": _texte(flux["montant"]), "source": flux["source"], "regle_de_date": flux["regle_de_date"],
    }
    if flux.get("echu"):
        vue["echu"] = True
    if flux.get("partielle"):
        vue["partielle"] = True
    if flux["reserves"]:
        vue["reserves"] = list(flux["reserves"])
    if flux["manque"]:
        vue["manque"] = [m["code"] for m in flux["manque"]]
    return vue


def _vue_resume_semaine(semaine: Mapping[str, Any]) -> dict[str, Any]:
    """Une semaine de la série : compacte (les lignes se lisent avec `vue_semaine`). Les indicateurs booléens n'y sont
    que s'ils sont vrais."""
    vue: dict[str, Any] = {
        "semaine": semaine["semaine"], "du": semaine["debut"].isoformat(), "statut": semaine["statut"],
    }
    if semaine["statut"] == "CALCULE":
        vue.update({
            "entrees": _texte(semaine["entrees"]), "sorties": _texte(semaine["sorties"]),
            "solde_fin": _texte(semaine["solde_fin"]), "cash_libre_prevu": _texte(semaine["cash_libre_prevu"]),
        })
        if semaine["sous_seuil"]:
            vue["sous_seuil"] = True
        if semaine["en_deficit"]:
            vue["en_deficit"] = True
    vue["lignes"] = len(semaine["lignes"])
    return vue


def _vue_alerte(alerte: Mapping[str, Any]) -> dict[str, Any]:
    vue: dict[str, Any] = {"statut": alerte["statut"], "seuil": _texte(alerte["seuil"])}
    if alerte["source_du_seuil"] is not None:
        vue["source_du_seuil"] = {
            "source": alerte["source_du_seuil"]["source"], "au": alerte["source_du_seuil"]["au"].isoformat()}
    if alerte["semaines"]:
        vue["semaines"] = list(alerte["semaines"])
    if alerte["non_evaluee_a_partir_de"] is not None:
        vue["non_evaluee_a_partir_de"] = alerte["non_evaluee_a_partir_de"]
    if alerte["manque"] is not None:
        vue["manque"] = {"code": alerte["manque"]["code"], "detail": _court(alerte["manque"]["detail"], 160)}
    return vue


def _vue_manque(groupe: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "code": groupe["code"], "a_partir_de_semaine": groupe["a_partir_de_semaine"], "nombre": len(groupe["flux"]),
        "exemples": [_court(i) for i in groupe["flux"][:_EXEMPLES_AFFICHES]],
        "detail": _court(groupe["detail"], _LONGUEUR_DETAIL_AFFICHE),
    }


def _vue_au_dela(resume: Mapping[str, Any]) -> dict[str, Any]:
    vue = {"nombre": resume["nombre"], "total": _texte(resume["total"])}
    if resume["non_chiffres"]:
        vue["non_chiffres"] = resume["non_chiffres"]
    return vue


def _vue_source_solde(solde: Mapping[str, Any]) -> dict[str, Any]:
    registres = [
        {**r, "tete": None if r["tete"] is None else r["tete"][:_LONGUEUR_TETE_AFFICHEE]}
        for r in solde["source"]["registres"]
    ]
    return {
        "montant": _texte(solde["montant"]), "source": solde["source"]["description"], "registres": registres,
        "fraicheur": dict(solde["fraicheur"]),
    }


def _en_tete(resultat: Mapping[str, Any]) -> dict[str, Any]:
    """Tout ce qui est vrai de l'ensemble de la prévision, hors les semaines (dites page par page) et les limites."""
    return {
        "type": resultat["type"],
        "lecture": _lecture(resultat),
        "aujourd_hui": resultat["aujourd_hui"].isoformat(),
        "horizon_semaines": resultat["horizon_semaines"],
        "fin_horizon": resultat["fin_horizon"].isoformat(),
        "calculable": resultat["calculable"],
        "non_calculable_a_partir_de": resultat["non_calculable_a_partir_de"],
        "manque": [_vue_manque(g) for g in resultat["manque"]],
        "alerte": _vue_alerte(resultat["alerte"]),
        "plus_bas": None if resultat["plus_bas"] is None else {
            "semaine": resultat["plus_bas"]["semaine"], "solde": _texte(resultat["plus_bas"]["solde"])},
        "premiere_semaine_en_deficit": resultat["premiere_semaine_en_deficit"],
        "solde_initial": _vue_source_solde(resultat["solde"]),
        "cash_libre_aujourd_hui": {
            "montant": _texte(resultat["cash_libre"]["montant"]),
            "manque": [f"{m['composante']} : {m['code']}" for m in resultat["cash_libre"]["manque"]],
        },
        "au_dela_de_l_horizon": {
            "entrees": _vue_au_dela(resultat["au_dela_de_l_horizon"]["entrees"]),
            "sorties": _vue_au_dela(resultat["au_dela_de_l_horizon"]["sorties"]),
        },
        "encaissements_non_comptes": [
            {"code": g["code"], "nombre": g["nombre"], "montant_connu": _texte(g["montant_connu"]),
             "exemples": [_court(i) for i in g["flux"][:_EXEMPLES_AFFICHES]]}
            for g in resultat["encaissements_non_comptes"]
        ],
        "reserves": list(resultat["reserves"]),
        "prevision_id": resultat["prevision_id"],
    }


def _page(
    corps: Mapping[str, Any], cle: str, elements: list[Any], depart: int, nombre: int, unite: str
) -> dict[str, Any]:
    fin = depart + nombre
    reste = len(elements) - fin
    return {
        **corps,
        "total": len(elements), "depart": depart, "affichees": nombre, "reste": reste,
        "prochain_depart": fin if reste else None,
        "message": None if not reste else f"{reste} {unite} non affichée(s) : poursuivre avec depart={fin}.",
        cle: elements[depart:fin],
        "mention": analyse.MENTION_ANALYSE_PREPARATOIRE,
    }


def _plus_grande_page(
    fabrique: Any, elements: list[Any], depart: int, budget_caracteres: int
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """La plus longue page qui tient sous `budget_caracteres` (taille MESURÉE, jamais estimée), d'abord avec les
    limites, puis sans (`limites_omises` dit combien). Au moins un élément ; sinon
    `REJ-PREVISION-REPONSE-TROP-GROSSE`."""
    for avec_limites in (True, False):
        nombre = 0
        while depart + nombre < len(elements) and _taille(fabrique(nombre + 1, avec_limites)) <= budget_caracteres:
            nombre += 1
        if nombre:
            return fabrique(nombre, avec_limites), None
    return None, _verdict(
        "REJ-PREVISION-REPONSE-TROP-GROSSE",
        f"un seul élément dépasse la borne de {budget_caracteres} caractères de la réponse",
    )


def vue_prevision(
    resultat: Mapping[str, Any], *, depart: Any = 0, budget_caracteres: int
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """La prévision en JSON sûr (montants en texte, dates ISO) : `(page, None)` ou `(None, verdict)`. L'en-tête
    (lecture, alerte, manque, solde de départ, cash libre, hors horizon, encaissements non comptés, limites, mention,
    empreinte) est celui de TOUT l'horizon ; les semaines viennent page par page (`depart` est un rang de semaine à
    partir de 0, `prochain_depart` le suivant, `None` à la fin), sous `budget_caracteres`, jamais tronquées. Aucun
    chiffre n'est produit ici : seulement rendu."""
    semaines = [_vue_resume_semaine(s) for s in resultat["semaines"]]
    if isinstance(depart, bool) or not isinstance(depart, int) or not 0 <= depart < len(semaines):
        return None, _verdict(
            "REJ-PREVISION-DEPART-INVALIDE",
            f"depart : entier de 0 à {len(semaines) - 1} exigé pour cet horizon (reçu {depart!r})",
        )
    en_tete = _en_tete(resultat)

    def fabrique(nombre: int, avec_limites: bool) -> dict[str, Any]:
        corps = {**en_tete, **({"limites": limites()} if avec_limites else {"limites_omises": len(_LIMITES)})}
        return _page(corps, "semaines", semaines, depart, nombre, "semaine")

    return _plus_grande_page(fabrique, semaines, depart, budget_caracteres)


def vue_semaine(
    resultat: Mapping[str, Any], semaine: Any, *, depart: Any = 0, budget_caracteres: int
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Les LIGNES d'une semaine (chacune avec son montant, sa date, sa source et la règle qui a donné sa date), page
    par page sous `budget_caracteres` : `(page, None)` ou `(None, verdict)`. `semaine` (1 à l'horizon) hors de
    l'horizon : `REJ-PREVISION-SEMAINE-INVALIDE` ; `depart` (rang de ligne) hors de la semaine :
    `REJ-PREVISION-DEPART-INVALIDE`. Les soldes de la semaine n'y sont que si elle est calculable."""
    horizon = resultat["horizon_semaines"]
    if isinstance(semaine, bool) or not isinstance(semaine, int) or not 1 <= semaine <= horizon:
        return None, _verdict(
            "REJ-PREVISION-SEMAINE-INVALIDE",
            f"semaine : entier de 1 à {horizon} exigé pour cet horizon (reçu {semaine!r})")
    courante = resultat["semaines"][semaine - 1]
    lignes = [_vue_ligne(f) for f in courante["lignes"]]
    derniere = max(len(lignes) - 1, 0)
    if isinstance(depart, bool) or not isinstance(depart, int) or not 0 <= depart <= derniere:
        return None, _verdict(
            "REJ-PREVISION-DEPART-INVALIDE",
            f"depart : entier de 0 à {derniere} exigé pour cette semaine (reçu {depart!r})",
        )
    corps: dict[str, Any] = {
        "type": "PREVISION_TRESORERIE_SEMAINE", "semaine": semaine, "du": courante["debut"].isoformat(),
        "au": courante["fin"].isoformat(), "statut": courante["statut"], "prevision_id": resultat["prevision_id"],
    }
    if courante["statut"] == "CALCULE":
        corps.update({
            "entrees": _texte(courante["entrees"]), "sorties": _texte(courante["sorties"]),
            "solde_fin": _texte(courante["solde_fin"]),
        })
    else:
        corps["non_calculable_a_partir_de"] = resultat["non_calculable_a_partir_de"]

    def fabrique(nombre: int, _avec_limites: bool) -> dict[str, Any]:
        return _page(corps, "lignes", lignes, depart, nombre, "ligne")

    if not lignes:
        return fabrique(0, True), None
    return _plus_grande_page(fabrique, lignes, depart, budget_caracteres)
