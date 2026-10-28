"""Calcul économique pur d'une ligne d'équipe, indépendant du format M4.

Ce module ne certifie ni l'origine ni l'intégrité des faits. Son appelant devra
vérifier le contrat M4 publié, les références et la fraîcheur avant imputation.
Les minutes sont des minutes nettes sur site : pauses exclues et déplacement
exclu, pour éviter de compter le déplacement déjà traité ailleurs. Chaque ligne
est arrondie au cent, ROUND_HALF_UP, puis les lignes peuvent être additionnées.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from typing import Any


def calculer_ligne_equipe(
    minutes: Any, taux: Any, *, unite: Any, devise: Any, source: Any,
    version: Any, date_effet: Any, date_fin: Any, date_travail: Any,
) -> dict[str, Any]:
    """Calcule une ligne déjà ventilée; aucun effectif n'est supposé.

    Le taux est strictement positif, exprimé en CAD/heure-équipe. Les dates
    d'effet sont inclusives. Une donnée insuffisante conserve un coût inconnu.
    La présence individuelle n'est pas calculable à partir de cette unité.
    """
    raisons = []
    if isinstance(minutes, bool) or not isinstance(minutes, int) or not 0 <= minutes <= 10**9:
        raisons.append("minutes nettes sur site absentes ou hors limites")
    nombre = None
    if isinstance(taux, (str, Decimal)) and not isinstance(taux, bool):
        try:
            nombre = Decimal(taux)
            if not nombre.is_finite() or nombre <= 0 or nombre.adjusted() > 11 or nombre.as_tuple().exponent < -12:
                nombre = None
        except (InvalidOperation, ValueError):
            nombre = None
    if nombre is None:
        raisons.append("taux décimal positif et borné requis")
    if unite != "heure-equipe":
        raisons.append("unité heure-equipe requise; présence individuelle non établie")
    if devise != "CAD":
        raisons.append("devise CAD explicite requise")
    if not isinstance(source, str) or not source.strip():
        raisons.append("source du taux requise")
    if not isinstance(version, str) or not version.strip():
        raisons.append("version de la source du taux requise")
    dates = (date_effet, date_fin, date_travail)
    if any(not isinstance(d, date) or isinstance(d, datetime) for d in dates):
        raisons.append("période et date civile du travail requises")
    elif date_effet > date_fin or not date_effet <= date_travail <= date_fin:
        raisons.append("taux hors période d'effet")
    cout = None
    if not raisons:
        with localcontext() as contexte:
            contexte.prec = 64
            cout = (Decimal(minutes) * nombre / Decimal(60)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "cout": cout,
        "statut": "complet" if cout is not None else "non_disponible",
        "raisons": raisons,
        "minutes_nettes": minutes,
        "taux": nombre,
        "unite": unite,
        "devise": devise,
        "source": source,
        "version": version,
        "date_effet": date_effet,
        "date_fin": date_fin,
        "date_travail": date_travail,
        "politique": "minutes nettes sur site; pauses et déplacements exclus",
        "arrondi": "ROUND_HALF_UP au cent par ligne",
    }


def _date_civile(valeur: Any) -> date | None:
    if not isinstance(valeur, str):
        return None
    try:
        jour = date.fromisoformat(valeur)
    except ValueError:
        return None
    return jour if jour.isoformat() == valeur else None


def chiffrer_visites(visites: Any, tarifs: Any) -> dict[str, Any]:
    """Chiffre des faits déjà validés par leur propriétaire, sans certifier leur origine.

    Les périodes inclusives doivent être non ambiguës pour chaque équipe et jour.
    Le statut de revue, la fraîcheur et l'autorité ne sont pas vérifiés ici :
    l'appelant doit les vérifier avant toute imputation ou total certifié.
    """
    if not isinstance(visites, list) or not visites or len(visites) > 1000:
        return {"complet": False, "cout_total": None, "cout_connu": None,
                "lignes": [], "raisons": ["liste de visites absente ou hors limites"]}
    if not isinstance(tarifs, list) or len(tarifs) > 10000:
        return {"complet": False, "cout_total": None, "cout_connu": None,
                "lignes": [], "raisons": ["liste de tarifs absente ou hors limites"]}
    lignes = []
    raisons = []
    for visite in visites:
        if not isinstance(visite, dict):
            lignes.append({"cout": None})
            raisons.append("visite illisible")
            continue
        identifiant = visite.get("visite_id")
        equipe = visite.get("equipe_pointee")
        equipe_id = (
            equipe.get("identifiant") if isinstance(equipe, dict) and equipe.get("statut") == "identifiee" else None
        )
        composition = visite.get("composition_declaree")
        jour = _date_civile(composition.get("jour")) if isinstance(composition, dict) else None
        minutes = visite.get("minutes")
        minutes = minutes.get("travail") if isinstance(minutes, dict) else None
        candidats = [tarif for tarif in tarifs if isinstance(tarif, dict) and tarif.get("equipe_id") == equipe_id]
        periodes = [(_date_civile(t.get("date_effet")), _date_civile(t.get("date_fin"))) for t in candidats]
        invalides = any(debut is None or fin is None or debut > fin for debut, fin in periodes)
        eligibles = [t for t, (debut, fin) in zip(candidats, periodes, strict=True)
                     if jour is not None and debut is not None and fin is not None and debut <= jour <= fin]
        if not isinstance(equipe_id, str) or not equipe_id or jour is None or invalides or len(eligibles) != 1:
            lignes.append({"visite_id": identifiant, "equipe_id": equipe_id, "cout": None})
            raisons.append(f"{identifiant} : équipe, date ou tarif applicable unique non établi")
            continue
        tarif = eligibles[0]
        ligne = calculer_ligne_equipe(
            minutes, tarif.get("taux"), unite=tarif.get("unite"), devise=tarif.get("devise"),
            source=tarif.get("source"), version=tarif.get("version"),
            date_effet=_date_civile(tarif.get("date_effet")), date_fin=_date_civile(tarif.get("date_fin")),
            date_travail=jour,
        )
        ligne.update({"visite_id": identifiant, "equipe_id": equipe_id})
        lignes.append(ligne)
        raisons.extend(f"{identifiant} : {raison}" for raison in ligne["raisons"])
    montants = [ligne["cout"] for ligne in lignes if ligne["cout"] is not None]
    connu = sum(montants, Decimal("0")) if montants else None
    complet = not raisons and len(montants) == len(visites)
    return {"complet": complet, "cout_total": connu if complet else None,
            "cout_connu": connu, "lignes": lignes, "raisons": raisons}
