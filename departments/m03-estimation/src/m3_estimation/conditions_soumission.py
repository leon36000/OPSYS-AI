"""Exclusions, hypothèses, délai et validité d'une soumission, tirés de DONNÉES DÉCLARÉES (M3-C2).

La soumission d'avant ne portait que les clauses statiques d'un modèle de texte : ni exclusions, ni hypothèses de
l'estimation, ni délai, ni validité. Ce module compose ces quatre sections pour un devis dont l'estimation source
est DÉCLARÉE (barème et mesure référencés), et seulement à partir de ce qui est déclaré :

- EXCLUSIONS et HYPOTHÈSES déclarées : les textes que le propriétaire a écrits dans la version de barème citée par
  l'estimation (``soumission.exclusions``, ``soumission.hypotheses``), repris tels quels. Aucun texte n'est inventé :
  sans déclaration, la section est absente ;
- HYPOTHÈSES de la mesure : phrases à gabarit fixe, qui ne disent que ce que la mesure déclare (quantité retenue,
  méthode, date, plage). Ces gabarits sont du texte à faire valider par l'entreprise (À valider auprès d'un
  professionnel qualifié pour toute portée juridique) ;
- DÉLAI : la durée de main-d'œuvre estimée (minutes de l'estimation, converties en heures), JAMAIS une date. Le
  texte dit qu'aucune date de début ni de fin n'est promise : l'échéancier relève de la planification des travaux
  (M4) ;
- VALIDITÉ : ``soumission.validite_jours`` déclaré, ajouté à la date DU DEVIS (jamais à l'horloge) ;
- aucune garantie : ce module n'en écrit aucune. Une garantie n'existe dans la soumission que si l'entreprise l'a
  écrite dans ses textes déclarés.

Module pur (ADR-0009) : aucun import ``opsys``, aucune horloge, aucun accès réseau."""

from __future__ import annotations

import unicodedata
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from . import verdicts

__all__ = ["VERSION_CONDITIONS", "composer", "valider"]

VERSION_CONDITIONS = "m3.conditions-soumission/v1"
_MOIS = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)
_LIBELLES_METHODE = {
    "releve_sur_place": "un relevé sur place",
    "plan": "un plan",
    "photo_echelle_mesuree": "une photo à l'échelle mesurée à la main",
    "estimation_grossiere": "une estimation grossière",
}
_UN_DIXIEME = Decimal("0.1")
_CLES = frozenset({"version", "exclusions", "hypotheses", "delai", "validite"})
_MAX_TEXTES = 40


def _date_fr(jour: date) -> str:
    return f"{jour.day} {_MOIS[jour.month - 1]} {jour.year}"


def _nombre_fr(texte: str) -> str:
    """``"120.50"`` -> ``"120,5"`` : virgule décimale, zéros inutiles retirés."""
    brut = format(Decimal(texte), "f")
    if "." in brut:
        brut = brut.rstrip("0").rstrip(".")
    return brut.replace(".", ",")


def _invalide(detail: str) -> dict:
    return verdicts.construire_verdict("REJ-CONTRAT-INVALIDE", detail=detail)


def composer(
    *, version_bareme: dict[str, Any], mesure: dict[str, Any],
    duree_estimee_minutes: str | None, horodatage_devis: str,
) -> tuple[dict[str, Any] | None, dict | None]:
    """Les sections de la soumission pour une estimation déclarée.

    ``version_bareme`` : la version EXACTE du barème que l'estimation source cite (même remplacée depuis) ;
    ``mesure`` : la révision exacte de la mesure citée ; ``duree_estimee_minutes`` : celle de l'estimation ;
    ``horodatage_devis`` : l'horodatage ISO 8601 du devis, d'où part la validité."""
    try:
        jour_devis = datetime.fromisoformat(horodatage_devis).date()
        declare = version_bareme["soumission"]
        exclusions = list(declare.get("exclusions", []))
        hypotheses = list(declare.get("hypotheses", []))
        unite, valeur = mesure["unite"], mesure["valeur"]
        hypotheses.append(
            f"Quantité retenue : {_nombre_fr(valeur)} {unite} ({mesure['grandeur']}), établie par "
            f"{_LIBELLES_METHODE[mesure['methode']]} le "
            f"{_date_fr(datetime.fromisoformat(mesure['mesure_le']).date())}."
        )
        if mesure["borne_basse"] != valeur or mesure["borne_haute"] != valeur:
            hypotheses.append(
                f"La quantité est une plage de {_nombre_fr(mesure['borne_basse'])} à "
                f"{_nombre_fr(mesure['borne_haute'])} {unite} ; la valeur retenue est {_nombre_fr(valeur)} {unite}."
            )
        delai = None
        if duree_estimee_minutes is not None:
            heures = (Decimal(duree_estimee_minutes) / 60).quantize(_UN_DIXIEME, rounding=ROUND_HALF_UP)
            delai = {
                "duree_main_oeuvre_heures": _nombre_fr(format(heures, "f")),
                "texte": (
                    f"Durée de travail estimée : environ {_nombre_fr(format(heures, 'f'))} heures de main-d'œuvre. "
                    "Aucune date de début ni de fin n'est promise par la présente soumission ; la planification des "
                    "travaux est établie séparément."
                ),
            }
        validite = None
        if "validite_jours" in declare:
            jusqu_au = jour_devis + timedelta(days=declare["validite_jours"])
            validite = {
                "jours": declare["validite_jours"],
                "jusqu_au": jusqu_au.isoformat(),
                "texte": f"Cette soumission est valide jusqu'au {_date_fr(jusqu_au)}.",
            }
    except (KeyError, TypeError, ValueError, InvalidOperation, OverflowError):
        return None, _invalide(
            "conditions de soumission : barème, mesure ou date du devis illisibles (déclaration incohérente)"
        )
    conditions = {
        "version": VERSION_CONDITIONS, "exclusions": exclusions, "hypotheses": hypotheses, "delai": delai,
        "validite": validite,
    }
    _, verdict = valider(conditions)
    if verdict is not None:
        return None, verdict
    return conditions, None


def _texte_ok(valeur: Any) -> bool:
    return (
        type(valeur) is str and 0 < len(valeur) <= 600
        and not any(unicodedata.category(c) in {"Cc", "Cs"} and c != "\n" for c in valeur)
    )


def valider(conditions: Any) -> tuple[dict[str, Any] | None, dict | None]:
    """Valide la forme fermée des sections (``contenu_client`` n'accepte rien d'autre dans un document client)."""
    if (
        not isinstance(conditions, dict) or set(conditions) != _CLES or conditions["version"] != VERSION_CONDITIONS
        or not all(
            isinstance(conditions[cle], list) and len(conditions[cle]) <= _MAX_TEXTES
            and all(_texte_ok(t) for t in conditions[cle])
            for cle in ("exclusions", "hypotheses")
        )
    ):
        return None, _invalide("conditions de soumission : forme fermée non respectée")
    delai, validite = conditions["delai"], conditions["validite"]
    if delai is not None and (
        not isinstance(delai, dict) or set(delai) != {"duree_main_oeuvre_heures", "texte"}
        or not all(_texte_ok(v) for v in delai.values())
    ):
        return None, _invalide("conditions de soumission : délai illisible")
    if validite is not None and (
        not isinstance(validite, dict) or set(validite) != {"jours", "jusqu_au", "texte"}
        or type(validite["jours"]) is not int or not _texte_ok(validite["jusqu_au"]) or not _texte_ok(validite["texte"])
    ):
        return None, _invalide("conditions de soumission : validité illisible")
    return conditions, None
