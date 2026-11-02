"""Lecture des entrées du rapport hebdomadaire que M7 POSSÈDE : sa propre performance de campagnes, son calendrier,
ses avis et
ses observations de croissance.

Ce que M7 ne possède pas (les mesures de l'entrepôt de M8 : coût par lead, leads par contenu) ne se lit pas ici :
l'exécuteur du
planificateur (`opsys.connecteurs_planification.exec_m7_rapport`) les lit par les outils de lecture de M8, N0, liste
fermée,
sans identité d'appareil ni droit élargi, et les passe à `service.constater`. M7 n'importe jamais le code d'un autre
département.

Lecture seule, dans la transaction ambiante. Une source illisible ou hors borne est rendue `None` avec son code
d'anomalie : le
rapport la traite comme ABSENTE (il le dit), jamais comme vide.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from opsys import stockage

from .. import growth_lecture, performance_campagnes
from ..reputation import classifier, inbox, metrics
from ..usine import registre as registre_usine
from ..usine import service as usine_service

_ERREURS = (ValueError, KeyError, TypeError, AttributeError, growth_lecture.GrowthLectureErreur)


def _jour(valeur: Any) -> dt.date | None:
    if not isinstance(valeur, str):
        return None
    try:
        return dt.datetime.fromisoformat(valeur.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return dt.date.fromisoformat(valeur[:10])
        except ValueError:
            return None


def performance(debut: dt.date, fin: dt.date) -> dict[str, Any]:
    return performance_campagnes.lire_performance(debut, fin)


def calendrier(debut: dt.date, fin: dt.date) -> dict[str, int]:
    propositions = list(stockage.maillons(*usine_service.REGISTRE_CONTENUS_CHANTIER))
    decisions = list(stockage.maillons(*usine_service.REGISTRE_DECISIONS_CONTENU))
    retraits = list(stockage.maillons(*usine_service.REGISTRE_RETRAITS))
    exports = list(stockage.maillons(*usine_service.REGISTRE_EXPORTS_PAQUET))
    creneaux = list(stockage.maillons(*usine_service.REGISTRE_CALENDRIER))
    courantes = registre_usine.dernieres_revisions(propositions)
    exportes = {e["contenu_id"] for e in exports if isinstance(e, dict) and "contenu_id" in e}
    en_attente = approuves = 0
    for p in courantes:
        statut = registre_usine.statut(p, decisions, retraits)
        if statut == registre_usine.STATUT_PROPOSE:
            en_attente += 1
        elif statut == registre_usine.STATUT_APPROUVE and p["contenu_id"] not in exportes:
            approuves += 1
    dans_semaine = lambda d: d is not None and debut <= d <= fin  # noqa: E731
    return {
        "en_attente_de_decision": en_attente,
        "approuves_non_exportes": approuves,
        "exportes_semaine": sum(1 for e in exports if dans_semaine(_jour(e.get("horodatage")))),
        "creneaux_semaine": sum(1 for c in creneaux if dans_semaine(_jour(c.get("planifie_le")))),
    }


def reputation(debut: dt.date, fin: dt.date) -> dict[str, Any]:
    avis = [a for a in inbox._lire(inbox._AVIS) if dans(debut, fin, a.get("date_avis"))]  # noqa: SLF001
    decides = {d["avis_id"] for d in inbox._lire(inbox._DECISIONS)}  # noqa: SLF001
    exportes = {e["avis_id"] for e in inbox._lire(inbox._EXPORTS)}  # noqa: SLF001
    notes = [a["note"] for a in avis if type(a.get("note")) is int]
    categories = {"litige": 0, "urgence": 0, "eloge": 0, "neutre": 0}
    negatifs = 0
    sans_reponse = 0
    for a in avis:
        categorie = (
            a.get("categorie")
            if a.get("categorie") in categories
            else classifier.classifier_avis({"note": a["note"], "texte": a["texte"]})
        )
        categories[categorie] = categories.get(categorie, 0) + 1
        sans = a["avis_id"] not in decides and a["avis_id"] not in exportes
        sans_reponse += sans
        if sans and (a["note"] <= 2 or categorie in ("litige", "urgence")):
            negatifs += 1
    return {
        "avis_semaine": len(avis),
        "note_moyenne_semaine": metrics.calculer_note_moyenne([{"note": n} for n in notes]) if notes else None,
        "categories": categories,
        "sans_reponse": sans_reponse,
        "negatifs_sans_reponse": negatifs,
    }


def dans(debut: dt.date, fin: dt.date, valeur: Any) -> bool:
    d = _jour(valeur)
    return d is not None and debut <= d <= fin


def croissance() -> list[dict[str, Any]]:
    cnx = stockage.connexion_courante()
    if cnx is None:
        raise ValueError("lecture de la croissance hors transaction")
    textes, _tete = growth_lecture.lire_prefixe(cnx)
    return [
        {k: o[k] for k in ("observation_id", "metrique", "valeur", "unite", "periode", "plateforme", "campagne")}
        for o in growth_lecture.decoder_prefixe(textes)
    ]


def lire(debut: dt.date, fin: dt.date) -> tuple[dict[str, Any], dict[str, str]]:
    """Les quatre sources de M7 : `(entrees, anomalies)`. Une source illisible vaut `None` et son nom est dans
    `anomalies`."""
    entrees: dict[str, Any] = {}
    anomalies: dict[str, str] = {}
    for nom, lecteur in (
        ("performance", lambda: performance(debut, fin)),
        ("calendrier", lambda: calendrier(debut, fin)),
        ("reputation", lambda: reputation(debut, fin)),
        ("croissance", croissance),
    ):
        try:
            entrees[nom] = lecteur()
        except _ERREURS as exc:
            entrees[nom] = None
            anomalies[nom] = str(exc)[:80]
    return entrees, anomalies
