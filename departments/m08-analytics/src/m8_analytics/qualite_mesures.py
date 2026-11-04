"""Qualité des données BRANCHÉE sur le catalogue des mesures (M8.3, chantier C4 de l'analyse M8).

Module PUR (ADR-0009) : aucun import d'``opsys``, aucune horloge, aucun accès à un registre (``outils.py`` lui passe les
faits). Déterministe : les mêmes faits, les mêmes règles, le même verdict.

Avant ce chantier, une donnée aberrante (un revenu négatif, un total qui n'est pas la somme de ses tranches, des clics
plus nombreux que les impressions) traversait tout M8 : la tuile la montrait, le copilote la citait, le score de
santé la notait. Ici, les règles de ``definitions/m8-qualite.v1.yaml`` (un ensemble FERMÉ de genres : ``plage``,
``relation``, ``controle``) sont évaluées sur les faits reçus et sur les valeurs que le moteur en a tirées ; une
règle qui échoue BLOQUE les mesures qu'elle nomme :

* la mesure devient « non calculable » (aucune valeur, aucune entrée), avec la raison nommée (``manque`` porte le champ
  ``qualite`` et le libellé de la règle) ; la valeur douteuse n'est jamais conservée ni montrée ;
* elle porte ``qualite = {statut: echec, ...}`` : les surfaces s'y fient pour la pastille QUALITY_FAIL
(``pastilles``), le refus du copilote, l'indétermination du score de santé et l'anomalie mémorisée par M10 ;
* quand les faits sont corrigés (un nouveau constat arrive), la règle passe et la mesure se rétablit d'elle-même :
rien n'est rangé, le blocage est une fonction des faits.

Ce n'est pas la fraîcheur : une donnée vieille n'est pas une donnée fausse (pastille STALE, jamais QUALITY_FAIL), et ce
n'est pas un seuil d'affaires : une règle dit ce qu'aucune entreprise ne peut violer sans qu'une donnée soit fausse. Une
mesure qu'aucune règle ne couvre est « non évaluée », dite telle : jamais un « ok » par défaut.

Aucun chiffre tiré d'une donnée n'est repris dans le verdict : il nomme la règle, ce qu'elle vérifie (texte du
fichier de règles), le nombre de faits en cause et, pour un fait, sa référence (identifiant de facture, date de
référence), de quoi retrouver la source sans recopier la valeur douteuse.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from . import cash_libre, entonnoir, mesures_constats, nombres, operations_recues

SCHEMA = "opsys.m8.qualite_mesures/v1"
_CHEMIN = Path(__file__).resolve().parents[2] / "definitions" / "m8-qualite.v1.yaml"

STATUT_OK = "ok"
STATUT_ECHEC = "echec"
STATUT_NON_EVALUEE = "non_evaluee"
_STATUTS = frozenset({STATUT_OK, STATUT_ECHEC, STATUT_NON_EVALUEE})

REJ_QUALITE_ILLISIBLE = "REJ-QUALITE-REGLES-ILLISIBLES"
REJ_QUALITE_INVALIDE = "REJ-QUALITE-REGLES-INVALIDES"
CHAMP_BLOCAGE = "qualite"
REFERENCES_MAX = 5
REFERENCE_LONGUEUR_MAX = 60
_REFERENCE_SURE = re.compile(r"[^A-Za-z0-9._:\-]")

_CLES_RACINE = frozenset({"schema", "version", "regles"})
_CLES_COMMUNES = frozenset({"id", "type", "libelle", "correction"})
_CLES_PAR_GENRE = {
    "plage": _CLES_COMMUNES | {"mesures", "min", "max"},
    "relation": _CLES_COMMUNES | {"gauche", "operateur", "droite"},
    "controle": _CLES_COMMUNES | {"controle", "bloque"},
}
_OBLIGATOIRES_PAR_GENRE = {
    "plage": _CLES_COMMUNES | {"mesures"},
    "relation": _CLES_COMMUNES | {"gauche", "operateur", "droite"},
    "controle": _CLES_COMMUNES | {"controle", "bloque"},
}
_OPERATEURS = frozenset({"au_plus"})
_TEXTE_MAX = 400
_REGLES_MAX = 200


class QualiteRefusee(ValueError):
    """Le fichier de règles est refusé : ``code`` est le verdict, ``detail`` dit la règle fautive."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code} : {detail}")
        self.code = code
        self.detail = detail


def _refus(detail: str) -> QualiteRefusee:
    return QualiteRefusee(REJ_QUALITE_INVALIDE, detail)


# ---------------------------------------------------------------------------
# Les vérifications de cohérence d'un fait source (ensemble fermé, dans le code)
# ---------------------------------------------------------------------------
# Une vérification reçoit les registres lus et rend ``None`` (rien à vérifier : aucun fait) ou la LISTE des faits en
# cause (vide : tout est cohérent), chacun par sa référence. Elle ne corrige rien et ne recalcule aucun montant : elle
# compare des nombres que le département source a lui-même publiés.
Verification = Callable[[dict[str, list[dict[str, Any]]]], "list[str] | None"]


def _creances_total_egale_tranches(registres: dict[str, list[dict[str, Any]]]) -> list[str] | None:
    dernier = operations_recues.dernier_constat_comptable(registres["operations"])
    if dernier is None:
        return None
    reference = f"mesures-comptables:{dernier.get('date_reference')}"
    creances = dernier.get("creances")
    if not isinstance(creances, dict):
        return [reference]
    total = nombres.decimal_lu(creances.get("total"))
    tranches = creances.get("par_tranche")
    if total is None or not isinstance(tranches, dict) or not tranches:
        return [reference]
    lues = [nombres.decimal_lu(valeur) for valeur in tranches.values()]
    if any(valeur is None or valeur < 0 for valeur in lues):
        return [reference]
    return [] if sum((v for v in lues if v is not None), Decimal(0)) == total else [reference]


def _factures_emises_coherentes(registres: dict[str, list[dict[str, Any]]]) -> list[str] | None:
    courantes = mesures_constats.factures_courantes(registres["operations"])
    if not courantes:
        return None
    en_cause = []
    for facture in courantes:
        avant = nombres.decimal_lu(facture.get("montant_avant_taxes_cad"))
        taxes = nombres.decimal_lu(facture.get("total_taxes_cad"))
        apres = nombres.decimal_lu(facture.get("montant_apres_taxes_cad"))
        if avant is None or taxes is None or apres is None or avant < 0 or taxes < 0 or apres != avant + taxes:
            en_cause.append(f"facture:{facture.get('facture_id')}")
    return sorted(en_cause)


def _cash_libre_coherent(registres: dict[str, list[dict[str, Any]]]) -> list[str] | None:
    constat = cash_libre.constat_courant(registres["cash_libre"])
    if constat is None:
        return None
    reference = f"cash-libre:{constat.get('date_reference')}"
    statut = constat.get("statut")
    montant = nombres.decimal_lu(constat.get("cash_libre_cad"))
    if statut == "NON_CALCULABLE":
        return [reference] if constat.get("cash_libre_cad") is not None else []
    if statut != "CALCULE" or montant is None:
        return [reference]
    if constat.get("en_deficit") is not (montant < 0):
        return [reference]
    composantes = constat.get("composantes") if isinstance(constat.get("composantes"), list) else []
    for composante in composantes:
        if isinstance(composante, dict) and composante.get("id") == "comptes_a_payer":
            a_payer = nombres.decimal_lu(composante.get("montant_cad"))
            if composante.get("statut") == "CALCULE" and (a_payer is None or a_payer < 0):
                return [reference]
    return []


def _tresorerie_prevue_coherente(registres: dict[str, list[dict[str, Any]]]) -> list[str] | None:
    """Le dernier constat de trésorerie prévue : bornes de l'horizon et des semaines, série complète et ordonnée
    (une semaine CALCULE a un montant, une NON_CALCULABLE n'en a pas), blocage continu, solde minimal égal au minimum
    des semaines CALCULÉES et à sa première semaine, semaines sous le seuil exactement celles que le seuil déclaré
    commande, statut d'alerte cohérent. ``None`` sans constat (rien à vérifier). M8 reprend M5 tel quel : un écart à
    l'invariant bloque les trois mesures C5, il ne corrige jamais le constat."""
    constat = mesures_constats.dernier_constat_tresorerie_prevue(registres["operations"])
    if constat is None:
        return None
    reference = (
        f"tresorerie-prevue:{constat.get('date_reference')}-s{constat.get('sequence')}"
    )
    horizon = constat.get("horizon_semaines")
    serie = constat.get("soldes_hebdo")
    if (
        type(horizon) is not int
        or not 1 <= horizon <= 26
        or not isinstance(serie, list)
        or len(serie) != horizon
    ):
        return [reference]
    calcules: dict[int, Decimal] = {}
    for attendue, ligne in enumerate(serie, start=1):
        if (
            not isinstance(ligne, dict)
            or type(ligne.get("semaine")) is not int
            or ligne.get("semaine") != attendue
        ):
            return [reference]
        montant = nombres.decimal_lu(ligne.get("solde_fin_cad"))
        if ligne.get("statut") == "CALCULE":
            if montant is None:
                return [reference]
            calcules[attendue] = montant
        elif ligne.get("statut") == "NON_CALCULABLE":
            if ligne.get("solde_fin_cad") is not None:
                return [reference]
        else:
            return [reference]
    bloque = constat.get("non_calculable_a_partir_de")
    if bloque is not None:
        if type(bloque) is not int or not 1 <= bloque <= horizon:
            return [reference]
        if any(semaine >= bloque for semaine in calcules):
            return [reference]
        if set(calcules) != set(range(1, bloque)):
            return [reference]
    elif len(calcules) != horizon:
        return [reference]
    minimal = nombres.decimal_lu(constat.get("solde_minimal_prevu_cad"))
    semaine_minimale = constat.get("semaine_solde_minimal")
    if minimal is None:
        if semaine_minimale is not None or calcules:
            return [reference]
    else:
        if (
            type(semaine_minimale) is not int
            or semaine_minimale not in calcules
            or minimal != min(calcules.values())
            or semaine_minimale != min(semaine for semaine, montant in calcules.items() if montant == minimal)
        ):
            return [reference]
    statut = constat.get("statut_alerte")
    seuil = nombres.decimal_lu(constat.get("seuil_cad"))
    semaines = constat.get("semaines_sous_seuil")
    if statut not in {"ALERTE", "SEUIL_A_CONFIGURER", "NON_EVALUEE", "AUCUNE"}:
        return [reference]
    if (
        not isinstance(semaines, list)
        or any(type(semaine) is not int for semaine in semaines)
        or any(semaine < 1 or semaine > horizon for semaine in semaines)
        or len(set(semaines)) != len(semaines)
        or semaines != sorted(semaines)
    ):
        return [reference]
    if statut == "SEUIL_A_CONFIGURER":
        return [] if constat.get("seuil_cad") is None and not semaines else [reference]
    if seuil is None or seuil < 0:
        return [reference]
    attendues = sorted(semaine for semaine, montant in calcules.items() if montant < seuil)
    if semaines != attendues:
        return [reference]
    if statut == "ALERTE":
        return [] if semaines else [reference]
    if statut == "NON_EVALUEE":
        return [] if not semaines and bloque is not None else [reference]
    return [] if not semaines and bloque is None else [reference]


_VERIFICATIONS: dict[str, Verification] = {
    "creances_total_egale_tranches": _creances_total_egale_tranches,
    "factures_emises_coherentes": _factures_emises_coherentes,
    "cash_libre_coherent": _cash_libre_coherent,
    "tresorerie_prevue_coherente": _tresorerie_prevue_coherente,
}


def verifications_possibles() -> tuple[str, ...]:
    """L'ensemble FERMÉ des vérifications de cohérence que le fichier de règles peut nommer."""
    return tuple(sorted(_VERIFICATIONS))


# ---------------------------------------------------------------------------
# Le fichier de règles
# ---------------------------------------------------------------------------
def _texte(brut: Any, regle: str, cle: str) -> str:
    if not isinstance(brut, str) or not brut.strip() or len(brut) > _TEXTE_MAX or brut != brut.strip():
        raise _refus(f"{regle} : {cle} : un texte de 1 à {_TEXTE_MAX} caractères, sans espace aux bords")
    return brut


def _borne(brut: Any, regle: str, cle: str) -> Decimal:
    lue = nombres.decimal_lu(brut) if isinstance(brut, str) else None
    if lue is None:
        raise _refus(f"{regle} : {cle} : un texte décimal est attendu (jamais un flottant)")
    return lue


def _liste_de_mesures(brut: Any, connues: set[str], regle: str, cle: str) -> list[str]:
    if not isinstance(brut, list) or not brut or not all(isinstance(m, str) for m in brut):
        raise _refus(f"{regle} : {cle} : une liste non vide de mesures du catalogue")
    if len(set(brut)) != len(brut):
        raise _refus(f"{regle} : {cle} : une mesure nommée deux fois")
    inconnues = sorted(set(brut) - connues)
    if inconnues:
        raise _refus(f"{regle} : {cle} : mesure(s) hors du catalogue fermé : {inconnues}")
    return list(brut)


def _valider_regle(brut: Any, connues: set[str]) -> dict[str, Any]:
    if not isinstance(brut, dict):
        raise _refus("chaque règle est un objet")
    identifiant = brut.get("id")
    if not isinstance(identifiant, str) or not identifiant.startswith("Q-") or len(identifiant) > 80:
        raise _refus("une règle sans identifiant « Q-… »")
    genre = brut.get("type")
    if genre not in _CLES_PAR_GENRE:
        raise _refus(f"{identifiant} : type : {sorted(_CLES_PAR_GENRE)} attendu")
    inconnues = set(brut) - _CLES_PAR_GENRE[genre]
    manquantes = _OBLIGATOIRES_PAR_GENRE[genre] - set(brut)
    if inconnues or manquantes:
        raise _refus(f"{identifiant} : clés inconnues {sorted(inconnues)} ou manquantes {sorted(manquantes)}")
    regle: dict[str, Any] = {
        "id": identifiant,
        "type": genre,
        "libelle": _texte(brut["libelle"], identifiant, "libelle"),
        "correction": _texte(brut["correction"], identifiant, "correction"),
    }
    if genre == "plage":
        regle["mesures"] = _liste_de_mesures(brut["mesures"], connues, identifiant, "mesures")
        bornes = {cle: _borne(brut[cle], identifiant, cle) for cle in ("min", "max") if cle in brut}
        if not bornes:
            raise _refus(f"{identifiant} : au moins une borne (min ou max)")
        if "min" in bornes and "max" in bornes and bornes["min"] > bornes["max"]:
            raise _refus(f"{identifiant} : min dépasse max")
        regle["min"], regle["max"] = bornes.get("min"), bornes.get("max")
    elif genre == "relation":
        if brut["operateur"] not in _OPERATEURS:
            raise _refus(f"{identifiant} : operateur : {sorted(_OPERATEURS)} attendu")
        gauche, droite = brut["gauche"], brut["droite"]
        mesures = _liste_de_mesures([gauche, droite], connues, identifiant, "gauche/droite")
        regle.update(gauche=mesures[0], droite=mesures[1], operateur=brut["operateur"])
    else:
        if brut["controle"] not in _VERIFICATIONS:
            raise _refus(f"{identifiant} : controle : {verifications_possibles()} attendu")
        regle["controle"] = brut["controle"]
        regle["bloque"] = _liste_de_mesures(brut["bloque"], connues, identifiant, "bloque")
    return regle


def _signature(regle: dict[str, Any]) -> tuple[Any, ...]:
    if regle["type"] == "plage":
        return ("plage", tuple(sorted(regle["mesures"])), regle["min"], regle["max"])
    if regle["type"] == "relation":
        return ("relation", regle["gauche"], regle["droite"])
    return ("controle", regle["controle"])


def valider(brut: Any, catalogue: dict[str, Any]) -> dict[str, Any]:
    """Le fichier de règles validé (fail-closed : une clé de plus, une mesure hors catalogue, un identifiant ou une
    règle
    en double, une borne illisible, une vérification inconnue refuse le fichier entier)."""
    if not isinstance(brut, dict) or brut.get("schema") != SCHEMA:
        raise _refus(f"schema attendu : {SCHEMA}")
    inconnues = set(brut) - _CLES_RACINE
    if inconnues or _CLES_RACINE - set(brut):
        raise _refus(f"clés inconnues {sorted(inconnues)} ou manquantes {sorted(_CLES_RACINE - set(brut))}")
    if type(brut["version"]) is not int or brut["version"] < 1:
        raise _refus("version : entier ≥ 1")
    liste = brut["regles"]
    if not isinstance(liste, list) or not 1 <= len(liste) <= _REGLES_MAX:
        raise _refus(f"regles : 1 à {_REGLES_MAX} règles")
    connues = {entree["metric_id"] for entree in catalogue["mesures"]}
    regles: list[dict[str, Any]] = []
    identifiants: set[str] = set()
    signatures: set[tuple[Any, ...]] = set()
    for element in liste:
        regle = _valider_regle(element, connues)
        if regle["id"] in identifiants:
            raise _refus(f"{regle['id']} : identifiant défini deux fois")
        signature = _signature(regle)
        if signature in signatures:
            raise _refus(f"{regle['id']} : règle déclarée en double")
        identifiants.add(regle["id"])
        signatures.add(signature)
        regles.append(regle)
    return {"version": brut["version"], "regles": regles}


def charger(catalogue: dict[str, Any], chemin: str | Path | None = None) -> dict[str, Any]:
    """Les règles de ``definitions/m8-qualite.v1.yaml``, validées contre le catalogue fermé."""
    fichier = Path(chemin) if chemin is not None else _CHEMIN
    try:
        brut = yaml.safe_load(fichier.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as erreur:
        raise QualiteRefusee(REJ_QUALITE_ILLISIBLE, f"{fichier.name} ({erreur})") from erreur
    return valider(brut, catalogue)


# ---------------------------------------------------------------------------
# L'évaluation
# ---------------------------------------------------------------------------
def reference_sure(texte: Any) -> str:
    """Une référence de fait (identifiant de facture, jour d'un constat) rendue INOFFENSIVE : une donnée hostile
    (retour à la ligne, consigne glissée, balisage) n'entre jamais telle quelle dans un rapport lu par un agent ou
    une personne. Seuls les
    caractères d'un identifiant sont gardés, le reste devient « ? », la longueur est bornée."""
    return _REFERENCE_SURE.sub("?", str(texte))[:REFERENCE_LONGUEUR_MAX]


def _echec(regle: dict[str, Any], references: list[str] | None = None) -> dict[str, Any]:
    echec: dict[str, Any] = {"regle": regle["id"], "genre": regle["type"], "verifie": regle["libelle"]}
    if references is not None:
        echec["nombre"] = len(references)
        echec["references"] = [reference_sure(r) for r in references[:REFERENCES_MAX]]
    return echec


def _valeur(mesure: dict[str, Any]) -> tuple[bool, Decimal | None]:
    """``(calculee, valeur)`` : une mesure calculée dont la valeur est illisible est ``(True, None)`` (une valeur
    absente ou illisible d'une mesure calculée est elle-même un échec : « non nul »)."""
    if mesure["statut"] != entonnoir.STATUT_CALCULEE:
        return False, None
    return True, nombres.decimal_lu(mesure["valeur"])


def evaluer(
    regles: dict[str, Any], mesures: list[dict[str, Any]], registres: dict[str, list[dict[str, Any]]]
) -> dict[str, dict[str, Any]]:
    """Le verdict de qualité de chaque mesure : ``{metric_id: {statut, regles_evaluees, echecs}}``. ``statut`` vaut
    ``ok`` (au moins une règle a pu juger et aucune n'a échoué), ``echec`` ou ``non_evaluee`` (aucune règle n'a pu
    juger :
    mesure non calculable sans règle d'échec, ou aucune règle ne la couvre). Lecture pure."""
    par_id = {mesure["metric_id"]: mesure for mesure in mesures}
    jugees: dict[str, int] = dict.fromkeys(par_id, 0)
    echecs: dict[str, list[dict[str, Any]]] = {metric_id: [] for metric_id in par_id}
    for regle in regles["regles"]:
        if regle["type"] == "plage":
            for metric_id in regle["mesures"]:
                if metric_id not in par_id:  # une lecture partielle du catalogue ne juge que ce qu'elle porte
                    continue
                calculee, valeur = _valeur(par_id[metric_id])
                if not calculee:
                    continue
                jugees[metric_id] += 1
                hors = (
                    valeur is None
                    or (regle["min"] is not None and valeur < regle["min"])
                    or (regle["max"] is not None and valeur > regle["max"])
                )
                if hors:
                    echecs[metric_id].append(_echec(regle))
        elif regle["type"] == "relation":
            if regle["gauche"] not in par_id or regle["droite"] not in par_id:
                continue
            (calc_g, gauche), (calc_d, droite) = _valeur(par_id[regle["gauche"]]), _valeur(par_id[regle["droite"]])
            if not (calc_g and calc_d):
                continue
            for metric_id in (regle["gauche"], regle["droite"]):
                jugees[metric_id] += 1
            if gauche is None or droite is None or gauche > droite:
                for metric_id in (regle["gauche"], regle["droite"]):
                    echecs[metric_id].append(_echec(regle))
        else:
            en_cause = _VERIFICATIONS[regle["controle"]](registres)
            if en_cause is None:
                continue
            for metric_id in (m for m in regle["bloque"] if m in par_id):
                jugees[metric_id] += 1
                if en_cause:
                    echecs[metric_id].append(_echec(regle, en_cause))
    verdicts = {}
    for metric_id in par_id:
        statut = STATUT_ECHEC if echecs[metric_id] else (STATUT_OK if jugees[metric_id] else STATUT_NON_EVALUEE)
        verdicts[metric_id] = {"statut": statut, "regles_evaluees": jugees[metric_id], "echecs": echecs[metric_id]}
    return verdicts


def appliquer(
    regles: dict[str, Any], mesures: list[dict[str, Any]], registres: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    """Les mesures, chacune avec son verdict ``qualite``. Une mesure en ÉCHEC est BLOQUÉE : non calculable, sans
    valeur ni entrée (la valeur douteuse n'est conservée nulle part), avec la raison nommée. Les autres sont rendues
    telles quelles (plus ``qualite``)."""
    verdicts = evaluer(regles, mesures, registres)
    resultat = []
    for mesure in mesures:
        verdict = verdicts[mesure["metric_id"]]
        if verdict["statut"] != STATUT_ECHEC:
            resultat.append({**mesure, "qualite": verdict})
            continue
        libelles = " ".join(e["verifie"] for e in verdict["echecs"][:2])
        resultat.append(
            {
                **mesure,
                "qualite": verdict,
                "statut": entonnoir.STATUT_NON_CALCULABLE,
                "valeur": None,
                "entrees": {},
                "couverture": {"etat": "inconnue"},
                "manque": [
                    {
                        "champ": CHAMP_BLOCAGE,
                        "source": mesure["proprietaire"],
                        "raison": "contrôle de qualité en échec : " + libelles,
                    }
                ],
                "detail": "non calculable, contrôle de qualité des données en échec (QUALITY_FAIL) : " + libelles,
            }
        )
    return resultat


def en_echec(mesure: dict[str, Any]) -> bool:
    """Vrai si la mesure est bloquée par le contrôle de qualité (``qualite.statut`` vaut ``echec``)."""
    qualite = mesure.get("qualite")
    return isinstance(qualite, dict) and qualite.get("statut") == STATUT_ECHEC


# ---------------------------------------------------------------------------
# Le rapport de qualité (lecture)
# ---------------------------------------------------------------------------
def rapport(regles: dict[str, Any], mesures: list[dict[str, Any]]) -> dict[str, Any]:
    """Le rapport de qualité à partir de mesures déjà passées par ``appliquer`` : les échecs PAR DÉPARTEMENT source
    (propriétaire de la mesure bloquée), la règle qui échoue, ce qu'elle vérifie, le geste de correction (gabarit du
    fichier de règles), et le compte de mesures ok, en échec ou non évaluées. Aucune valeur de mesure."""
    par_regle = {regle["id"]: regle for regle in regles["regles"]}
    par_departement: dict[str, dict[str, Any]] = {}
    for mesure in mesures:
        qualite = mesure["qualite"]
        for echec in qualite["echecs"]:
            regle = par_regle[echec["regle"]]
            groupe = par_departement.setdefault(mesure["proprietaire"], {"departement": mesure["proprietaire"],
                                                                           "echecs": []})
            groupe["echecs"].append(
                {
                    "metric_id": mesure["metric_id"],
                    "nom": mesure["nom"],
                    "regle": regle["id"],
                    "verifie": regle["libelle"],
                    "correction": regle["correction"],
                    "nombre": echec.get("nombre"),
                    "references": echec.get("references", []),
                }
            )
    comptes = {statut: sum(1 for m in mesures if m["qualite"]["statut"] == statut) for statut in sorted(_STATUTS)}
    return {
        "version_regles": regles["version"],
        "n_regles": len(regles["regles"]),
        "n_mesures": len(mesures),
        "comptes": comptes,
        "departements": [par_departement[d] for d in sorted(par_departement)],
        "lecture": (
            f"{comptes[STATUT_ECHEC]} mesure(s) bloquée(s) par le contrôle de qualité sur {len(mesures)} ; "
            f"{comptes[STATUT_OK]} contrôlée(s) et conforme(s), {comptes[STATUT_NON_EVALUEE]} non évaluée(s) "
            "(aucune règle n'a pu juger : mesure non calculable ou sans règle)."
        ),
    }


__all__ = [
    "CHAMP_BLOCAGE",
    "REJ_QUALITE_ILLISIBLE",
    "REJ_QUALITE_INVALIDE",
    "SCHEMA",
    "STATUT_ECHEC",
    "STATUT_NON_EVALUEE",
    "STATUT_OK",
    "QualiteRefusee",
    "appliquer",
    "charger",
    "en_echec",
    "evaluer",
    "rapport",
    "reference_sure",
    "valider",
    "verifications_possibles",
]
