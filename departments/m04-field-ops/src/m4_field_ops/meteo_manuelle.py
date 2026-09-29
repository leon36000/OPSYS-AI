"""Adaptateur « saisie manuelle » du port ``FournisseurMeteo`` (PLAN T4.13, M4.10).

Aucun réseau, aucune horloge : l'admin (ou l'agent qui l'assiste) saisit la prévision qu'il a lue quelque part (bulletin
d'Environnement Canada, alerte reçue, appel au chantier) avec CE QUI PERMET DE LA CITER : qui l'a saisie, d'où elle
vient et à quelle heure elle a été émise. C'est l'adaptateur qui existe toujours : un fournisseur réseau se ferme par la
configuration (`opsys-metier meteo declarer`), la saisie manuelle jamais.

Forme de la saisie (``previsions_saisies`` de ``m4_verifier_meteo_creneau``) ::

    {"saisi_par": "nathan",
     "source": "bulletin d'Environnement Canada, région de Lanaudière",     # texte libre, obligatoire
     "emise_le": "2026-10-04T18:00:00-04:00",                               # heure d'ÉMISSION, ISO 8601 avec fuseau
     "points": [{"heure": "2026-10-05T09:00", "vent_kmh": 62, "rafales_kmh": 80, "temperature_c": 7, ...}]}

Chaque point est HORAIRE (heure locale du chantier, minutes à zéro). Une mesure que la saisie ne donne pas est ``null``
: la règle qui la demande reste « inconnue », jamais « ok ». Les nombres JSON décimaux (12.5) sont lus comme des
décimaux EXACTS (``Decimal(str(x))``) : aucun calcul en virgule flottante n'est fait sur la prévision.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from . import horodatage, meteo, verdicts

SOURCE_SAISIE = "saisie_manuelle"
HEURE_TYPE_SAISIE = "heure_d_emission_saisie"
_CLES_SAISIE = ("saisi_par", "source", "emise_le", "points")

__all__ = [
    "SOURCE_SAISIE",
    "HEURE_TYPE_SAISIE",
    "FournisseurSaisieManuelle",
    "creer_fournisseur_manuel",
]


def _refus(detail):
    return verdicts.construire_verdict("REJ-CONTRAT-INVALIDE", detail=f"prévision saisie : {detail}")


def _nombre(valeur):
    """Un nombre JSON en ``Decimal`` exact (entier, ou décimal lu depuis son texte) ; ``None`` s'il n'en est pas un."""
    if isinstance(valeur, bool) or valeur is None:
        return valeur
    if isinstance(valeur, (int, float)):
        try:
            nombre = Decimal(str(valeur))
        except InvalidOperation:
            return valeur
        return nombre if nombre.is_finite() else valeur
    return valeur


def _point(point):
    """Le point de la saisie au format du port : les nombres en ``Decimal``, une mesure absente à ``None`` (jamais
    zéro), le reste tel quel (validé ensuite)."""
    if not isinstance(point, dict):
        return point
    complet = {champ: None for champ in meteo.CLES_POINT}
    complet.update({cle: (_nombre(valeur) if cle in meteo.CHAMPS_NOMBRE else valeur) for cle, valeur in point.items()})
    return complet


class FournisseurSaisieManuelle:
    """Fournisseur de la prévision saisie : rend les points saisis, cités avec leur auteur et leur heure d'émission.

    À créer par ``creer_fournisseur_manuel`` (qui rend un verdict) ; le constructeur ne valide pas. Sans état."""

    def __init__(self, saisi_par, source, emise_le, points):
        self._saisi_par = saisi_par
        self._source = source
        self._emise_le = emise_le
        self._points = points

    def descripteur(self):
        """Métadonnées stables. Aucune attribution : la saisie n'est pas une donnée sous licence (l'auteur est cité)."""
        return {"fournisseur": SOURCE_SAISIE, "saisi_par": self._saisi_par, "reference": self._source}

    def previsions(self, lieu, date_debut, date_fin):
        """Les points saisis, tels quels : la saisie ne dépend pas du lieu (rien ne quitte le serveur) ni des dates."""
        return {
            "citation": {
                "source": SOURCE_SAISIE,
                "emise_le": self._emise_le,
                "heure_type": HEURE_TYPE_SAISIE,
                "saisi_par": self._saisi_par,
                "reference": self._source,
                "attribution": None,
            },
            "points": [dict(point) for point in self._points],
        }, None


def creer_fournisseur_manuel(saisie):
    """Crée le fournisseur après validation. Retourne ``(fournisseur, None)`` ou ``(None, verdict)``.

    Refuse, sans rien créer : une saisie qui n'est pas un objet aux clés attendues, un auteur ou une source vides, une
    heure d'émission qui n'est pas ISO 8601 avec fuseau, un point qui ne respecte pas le port
    (``meteo.valider_previsions``)."""
    if not isinstance(saisie, dict) or set(saisie) != set(_CLES_SAISIE):
        return None, _refus(f"un objet {{{', '.join(_CLES_SAISIE)}}} est attendu")
    for cle in ("saisi_par", "source"):
        if not isinstance(saisie[cle], str) or saisie[cle].strip() == "":
            return None, _refus(f"{cle} : texte non vide requis (la prévision se cite toujours)")
    try:
        horodatage.valider_horodatage(saisie["emise_le"])
    except ValueError:
        return None, _refus("emise_le : heure d'émission ISO 8601 avec fuseau requise (ex. 2026-10-04T18:00:00-04:00)")
    if not isinstance(saisie["points"], list):
        return None, _refus("points : une liste est attendue")
    points = [_point(point) for point in saisie["points"]]
    probleme = meteo.valider_previsions(
        {
            "citation": {"source": SOURCE_SAISIE, "emise_le": saisie["emise_le"], "heure_type": HEURE_TYPE_SAISIE},
            "points": points,
        }
    )
    if probleme is not None:
        return None, _refus(probleme)
    return FournisseurSaisieManuelle(saisie["saisi_par"], saisie["source"], saisie["emise_le"], points), None
