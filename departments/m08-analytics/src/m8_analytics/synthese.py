"""Mesures de SYNTHÈSE de M8 : agrégats d'entreprise tirés des faits déjà reçus (M8.2, M8.8, M8.11, M8.12).

Module PUR (ADR-0009) : aucun import d'``opsys``, aucune horloge (les instants viennent des faits reçus). Même patron
que ``entonnoir.py`` et ``contenus.py`` : chaque métrique est définie une seule fois dans
``metrics/m8-synthese.v1.yaml`` et porte la version de sa définition ; une entrée absente donne « non calculable, manque
X », jamais un zéro inventé ; M8 ne recalcule aucun montant de M5.

Quatre mesures, toutes d'ENTREPRISE (aucun technicien, aucun client, aucune personne) :

* ``m8_chantiers_termines`` : un comptage de ``wct_id`` distincts ;
* ``m8_ecart_duree_equipe_pct`` : l'écart de l'ÉQUIPE (déjà calculé par ``mesures_chantier.performance_equipe``, jamais
  recalculé ici, jamais le détail par technicien) ;
* ``m8_chantiers_signal_materiaux`` : le verdict de M6 repris (``signal_critique``), compté, sans seuil de M8 ;
* ``m8_cash_libre_cad`` : le dernier constat de M5, repris tel quel (``cash_libre.constat_courant``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import cash_libre, entonnoir, mesures_chantier

MODULE_DEFINITIONS = entonnoir.MODULE_DEFINITIONS

_CHEMIN_METRIQUES = Path(__file__).resolve().parents[2] / "metrics" / "m8-synthese.v1.yaml"
_REGISTRE = "de synthèse"
_STATUT_CASH_CALCULE = "CALCULE"

Resultat = tuple[str | None, dict[str, Any], list[dict[str, str]], str | None]


def charger_definitions(chemin: str | Path | None = None) -> dict[str, dict[str, str]]:
    """Définitions de ``metrics/m8-synthese.v1.yaml`` : mêmes contrôles et mêmes refus que l'entonnoir (fail-closed,
    chaque métrique a un propriétaire connu)."""
    return entonnoir.charger_definitions(chemin if chemin is not None else _CHEMIN_METRIQUES, registre=_REGISTRE)


def _manque(champ: str, source: str, raison: str) -> dict[str, str]:
    return {"champ": champ, "source": source, "raison": raison}


_MANQUE_WCT = _manque(
    "m4.travaux_termines",
    "M4 (m4.travaux_termines)",
    "aucun chantier terminé reçu : rien terminé par M4, ou rien livré par le bus",
)
_MANQUE_DUREE_ESTIMEE = _manque(
    "duree_estimee_minutes",
    "M3 (m3.devis_accepte)",
    "aucun chantier terminé ne porte à la fois sa durée réelle (M4) et une durée estimée positive (M3)",
)
_MANQUE_VARIANCE = _manque(
    "m6.variance_chantier",
    "M6 (m6.variance_chantier)",
    "aucune variance de matériaux évaluée reçue de M6 : rien publié par M6, ou rien livré par le bus",
)
_MANQUE_CONSTAT = _manque(
    "m5.cash_libre_constate",
    "M5 (m5.cash_libre_constate)",
    "aucun constat du cash libre reçu : M5 n'en a publié aucun (m5_constater_cash_libre, admin), ou rien livré par le "
    "bus",
)


def _wcts_uniques(faits_chantier: list[dict[str, Any]]) -> list[dict[str, Any]]:
    vus: dict[str, dict[str, Any]] = {}
    for fait in faits_chantier:
        identifiant = fait.get("wct_id")
        if fait.get("type_entree") == "wct" and isinstance(identifiant, str) and identifiant:
            vus[identifiant] = fait
    return list(vus.values())


def _plus_recent_completion(wcts: list[dict[str, Any]]) -> str | None:
    lus = [(entonnoir.instant_lu(w.get("horodatage_completion")), w["horodatage_completion"]) for w in wcts]
    lisibles = [(instant, texte) for instant, texte in lus if instant is not None]
    return max(lisibles, key=lambda paire: paire[0])[1] if lisibles else None


def _chantiers_termines(faits_chantier: list[dict[str, Any]], _faits_cash: list[dict[str, Any]]) -> Resultat:
    wcts = _wcts_uniques(faits_chantier)
    if not wcts:
        return None, {}, [_MANQUE_WCT], None
    return str(len(wcts)), {}, [], _plus_recent_completion(wcts)


def _ecart_duree_equipe_pct(faits_chantier: list[dict[str, Any]], _faits_cash: list[dict[str, Any]]) -> Resultat:
    wcts = _wcts_uniques(faits_chantier)
    if not wcts:
        return None, {}, [_MANQUE_WCT], None
    equipe = mesures_chantier.performance_equipe(faits_chantier, None)["equipe"]
    entrees = {
        "n_chantiers_mesures": equipe["n_chantiers_mesures"],
        "n_chantiers_sans_temps_prevu": equipe["n_chantiers_sans_temps_prevu"],
    }
    if equipe["n_chantiers_mesures"] == 0 or equipe["ecart_pct"] is None:
        return None, entrees, [_MANQUE_DUREE_ESTIMEE], _plus_recent_completion(wcts)
    return equipe["ecart_pct"], entrees, [], _plus_recent_completion(wcts)


def _chantiers_signal_materiaux(faits_chantier: list[dict[str, Any]], _faits_cash: list[dict[str, Any]]) -> Resultat:
    wcts = _wcts_uniques(faits_chantier)
    if not wcts:
        return None, {}, [_MANQUE_WCT], None
    evalues = 0
    critiques = 0
    portes: list[dict[str, Any]] = []
    for wct in wcts:
        faits = mesures_chantier.assembler_faits(wct["wct_id"], faits_chantier)
        variance = faits["variance"] if faits is not None else None
        if variance is not None and variance.get("statut_variance") == "evaluee":
            evalues += 1
            portes.append(wct)
            if variance.get("signal_critique") is True:
                critiques += 1
    if evalues == 0:
        return None, {"n_chantiers_termines": len(wcts)}, [_MANQUE_VARIANCE], _plus_recent_completion(wcts)
    entrees = {
        "n_chantiers_termines": len(wcts),
        "n_variances_evaluees": evalues,
        "n_chantiers_sans_variance_evaluee": len(wcts) - evalues,
    }
    return str(critiques), entrees, [], _plus_recent_completion(portes)


def _jour_en_instant(date_reference: Any) -> str | None:
    """Le constat de M5 est daté d'un JOUR (AAAA-MM-JJ, M5 n'a pas d'horloge) : l'instant retenu est le DÉBUT de ce
    jour (UTC), le plus ancien possible, pour ne jamais faire paraître un constat plus récent qu'il n'est."""
    if cash_libre.age_en_jours(date_reference, date_reference) is None:
        return None  # date illisible : aucun instant, la fraîcheur sera « inconnue », jamais devinée
    return f"{date_reference}T00:00:00+00:00"


def _cash_libre_cad(_faits_chantier: list[dict[str, Any]], faits_cash: list[dict[str, Any]]) -> Resultat:
    constat = cash_libre.constat_courant(faits_cash)
    if constat is None:
        return None, {}, [_MANQUE_CONSTAT], None
    instant = _jour_en_instant(constat.get("date_reference"))
    entrees = {
        "date_reference": constat.get("date_reference"),
        "sequence": constat.get("sequence"),
        "statut_m5": constat.get("statut"),
        "en_deficit": constat.get("en_deficit"),
    }
    montant = constat.get("cash_libre_cad")
    if constat.get("statut") != _STATUT_CASH_CALCULE or montant is None:
        codes = [
            f"{m.get('composante')} : {m.get('code')}" for m in (constat.get("manque") or []) if isinstance(m, dict)
        ]
        raison = "M5 a constaté le cash libre « non calculable »" + (f" (manque : {', '.join(codes)})" if codes else "")
        return None, entrees, [_manque("cash_libre", "M5 (m5.cash_libre_constate)", raison)], instant
    return str(montant), entrees, [], instant


# Les mêmes règles, offertes aux mesures interdépartements (`mesures_interdepartements.py`) : une seule lecture des
# chantiers terminés et une seule façon de dater un constat quotidien de M5.
wcts_uniques = _wcts_uniques
plus_recent_completion = _plus_recent_completion
jour_en_instant = _jour_en_instant

_CALCULS = {
    "m8_chantiers_termines": _chantiers_termines,
    "m8_ecart_duree_equipe_pct": _ecart_duree_equipe_pct,
    "m8_chantiers_signal_materiaux": _chantiers_signal_materiaux,
    "m8_cash_libre_cad": _cash_libre_cad,
}


def mesurer(
    faits_chantier: list[dict[str, Any]],
    faits_cash_libre: list[dict[str, Any]],
    definitions: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    """Les mesures de synthèse, une par métrique du registre, dans l'ordre du registre (forme de
    ``entonnoir.construire_mesure``, plus ``dernier_fait_le`` : l'instant du fait qui porte la mesure, ``None`` si
    aucun). Une métrique du registre sans calcul est non calculable, nommément."""
    mesures = []
    for metric_id, definition in definitions.items():
        calcul = _CALCULS.get(metric_id)
        if calcul is None:
            valeur: str | None = None
            entrees: dict[str, Any] = {}
            manque = [_manque("calcul", "M8", "aucun calcul enregistré pour cette métrique")]
            instant: str | None = None
        else:
            valeur, entrees, manque, instant = calcul(faits_chantier, faits_cash_libre)
        mesure = entonnoir.construire_mesure(metric_id, definition, valeur, entrees, manque)
        mesure["dernier_fait_le"] = instant
        mesures.append(mesure)
    return mesures


__all__ = [
    "MODULE_DEFINITIONS",
    "charger_definitions",
    "jour_en_instant",
    "mesurer",
    "plus_recent_completion",
    "wcts_uniques",
]
