"""Calcul exact et préparatoire du brut régulier; aucune règle fiscale ou de paie officielle."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import contrats_salaries_horaires, validation

POLITIQUE_ARRONDI = "centime_demi_superieur"
MAX_JOURS_PERIODE = 31


def _refus(code: str, detail: str) -> tuple[None, dict[str, str]]:
    return None, validation.construire_verdict(code, detail=detail)


def _centimes(taux_horaire: str) -> int | None:
    taux = contrats_salaries_horaires._valider_taux(taux_horaire)
    if taux is None:
        return None
    signe, chiffres, exposant = taux.as_tuple()
    if signe:
        return None
    coefficient = int("".join(str(chiffre) for chiffre in chiffres))
    decalage = exposant + 2
    if decalage >= 0:
        return coefficient * 10**decalage
    diviseur = 10 ** (-decalage)
    centimes, reste = divmod(coefficient, diviseur)
    return centimes if reste == 0 else None


def valider_periode(debut: object, fin: object, fuseau: object) -> tuple[date, date] | None:
    if not isinstance(debut, str) or not isinstance(fin, str) or not isinstance(fuseau, str):
        return None
    try:
        date_debut, date_fin = date.fromisoformat(debut), date.fromisoformat(fin)
        ZoneInfo(fuseau)
    except (ValueError, ZoneInfoNotFoundError):
        return None
    if (
        date_debut.isoformat() != debut
        or date_fin.isoformat() != fin
        or date_fin < date_debut
        or date_fin == date.max
        or (date_fin - date_debut).days + 1 > MAX_JOURS_PERIODE
    ):
        return None
    zone = ZoneInfo(fuseau)
    try:
        minuit_debut = datetime.combine(date_debut, time.min, zone)
        minuit_fin_exclusif = datetime.combine(date_fin, time.min, zone) + timedelta(days=1)
        minuit_debut.astimezone(UTC)
        minuit_fin_exclusif.astimezone(UTC)
    except OverflowError:
        return None
    return date_debut, date_fin


def limite_minutes_regulieres(debut: str, fin: str, fuseau: str) -> int | None:
    """Borne physique des minutes d'une période; respecte les journées locales de 23/25 heures."""
    periode = valider_periode(debut, fin, fuseau)
    if periode is None:
        return None
    zone = ZoneInfo(fuseau)
    debut_local = datetime.combine(periode[0], time.min, zone)
    fin_exclusive_locale = datetime.combine(periode[1], time.min, zone) + timedelta(days=1)
    duree = fin_exclusive_locale.astimezone(UTC) - debut_local.astimezone(UTC)
    return int(duree.total_seconds() // 60)


def calculer_brut_regulier(
    taux_horaire: object,
    minutes_regulieres: object,
    politique_arrondi: object,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Calcule cents × minutes / 60 et applique uniquement l'arrondi explicitement choisi."""
    if not isinstance(taux_horaire, str) or _centimes(taux_horaire) is None:
        return _refus("REJ-SALAIRE-TAUX-INVALIDE", "taux CAD décimal texte positif et borné requis")
    if type(minutes_regulieres) is not int or minutes_regulieres < 0:
        return _refus("REJ-SALAIRE-STRUCTURE-INVALIDE", "minutes régulières entières non négatives requises")
    if politique_arrondi != POLITIQUE_ARRONDI:
        return _refus("REJ-SALAIRE-CONTRAT-INVALIDE", "politique d'arrondi explicite non supportée")

    taux_centimes = _centimes(taux_horaire)
    if taux_centimes is None:
        return _refus("REJ-SALAIRE-TAUX-INVALIDE", "taux CAD décimal texte positif et borné requis")
    numerateur_centimes = taux_centimes * minutes_regulieres
    quotient, reste = divmod(numerateur_centimes, 60)
    cents_arrondis = quotient + (reste * 2 >= 60)
    return {
        "brut_brouillon": f"{cents_arrondis // 100}.{cents_arrondis % 100:02d}",
        "brut_exact_fraction": {"numerateur_centimes": numerateur_centimes, "denominateur": 60},
        "minutes_regulieres": minutes_regulieres,
        "devise": "CAD",
    }, None
