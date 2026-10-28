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
    if isinstance(minutes, bool) or not isinstance(minutes, int) or not 0 < minutes <= 10**9:
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
