"""Contrats des propriétaires : ce que M9 sait lire, sans rien fabriquer.

Module pur. Pour chaque donnée que M9 attendait d'un propriétaire (capacité d'équipe M4, dépenses marketing M7, plaintes
structurées M1), ce module nomme le contrat et valide une charge contre lui. Une fois la lecture publiée et branchée, la
validation est celle du contrat RÉEL du propriétaire (``charges_producteurs``, la même que la capture applique) ; tant
qu'elle ne l'est pas, c'est la forme attendue. Il ne produit aucune valeur : une charge incomplète est rendue avec la
liste
de ce qui manque, jamais complétée ; un nombre doit arriver en TEXTE décimal exact (un flottant est refusé) ; une
valeur hors de l'énuméré fermé est refusée.

L'état d'un contrat se lit sur le catalogue des lectures de M9 (``catalogue_producteurs``) : tant que la lecture
attendue n'y figure pas, le contrat est ``ABSENT_CHEZ_LE_PROPRIETAIRE`` et M9 le dit. Une extrapolation de M9
(``origine == "tendance_extrapolee"``) n'est jamais une prévision de propriétaire : ``refuser_extrapolation`` la refuse
si elle est présentée comme telle.

Le contrat M8 → M9 des définitions versionnées est dans ``preuves_definition`` (preuve propre à chaque observation).
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Mapping

from . import catalogue_producteurs as cat
from . import charges_producteurs

ORIGINE_EXTRAPOLATION = "tendance_extrapolee"
_DECIMAL = re.compile(r"[0-9]{1,12}(?:\.[0-9]{1,4})?")  # quantités et montants dépensés : jamais négatifs
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_IDENTIFIANT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}")
# Catégories fermées de signaux de plainte de M1 (``opsys.taxonomie.CATEGORIES_SIGNAL_PLAINTE``) ; un test compare.
CATEGORIES_PLAINTE = frozenset({"insatisfaction", "degat", "garantie", "avocat", "securite"})
COUVERTURES = frozenset({"COMPLETE", "PARTIELLE", "INCONNUE"})


# Genres de champ : decimal (texte exact), date, identifiant, entier, booleen, couverture, categorie, textes.
CONTRATS: dict[str, dict] = {
    "capacite_equipe": {
        "proprietaire": "m04-field-ops",
        "lecture_id": "m4.capacite_equipe",
        "outil_attendu": "m4_lire_capacite_equipe",
        "racine": {"semaine_debut": "date", "calculable": "booleen", "manque": "textes"},
        "liste": (
            "equipes",
            {"equipe_id": "identifiant", "heures_disponibles": "decimal", "heures_planifiees": "decimal"},
        ),
        "limite": "M9 ne déduit aucune capacité des interventions planifiées : seul M4 sait ce qu'une équipe peut "
        "faire.",
    },
    "depenses_marketing": {
        "proprietaire": "m07-marketing",
        "lecture_id": "m7.depenses_marketing",
        "outil_attendu": "m7_lire_depenses_marketing",
        "reel": {"enveloppe_accepte": False},
        "limite": "Branché sur le contrat réel de M7 (schéma opsys.m7.depenses_marketing/v1) : un total n'existe que "
        "statut CONNUE ; NON_BRANCHEE ne donne aucun montant. M7 n'a encore aucune ingestion ni saisie réelle de "
        "relevés : tant qu'aucun relevé n'est inscrit, la lecture dit NON_BRANCHEE.",
    },
    "plaintes_structurees": {
        "proprietaire": "m01-front-office",
        "lecture_id": "m1.plaintes_structurees",
        "outil_attendu": "m1_lire_plaintes_structurees",
        "racine": {"debut": "date", "fin": "date", "ouvertes_total": "entier", "manque": "textes"},
        "liste": ("categories", {"categorie": "categorie", "ouvertes": "entier"}),
        "limite": "Jamais le texte d'un message ni une identité : des comptes par catégorie fermée. Sans cette "
        "lecture, M9 ne crée aucun risque de réputation.",
    },
}


def etat(domaine: str) -> str:
    """``PUBLIE`` si la lecture attendue figure au catalogue de M9 ; sinon ``ABSENT_CHEZ_LE_PROPRIETAIRE``."""
    contrat = CONTRATS[domaine]
    return "PUBLIE" if contrat["lecture_id"] in cat.PAR_ID else "ABSENT_CHEZ_LE_PROPRIETAIRE"


def _valide(genre: str, valeur: object) -> bool:
    if genre == "decimal":
        return type(valeur) is str and _DECIMAL.fullmatch(valeur) is not None
    if genre == "date":
        return _date(valeur) is not None
    if genre == "identifiant":
        return type(valeur) is str and _IDENTIFIANT.fullmatch(valeur) is not None
    if genre == "entier":
        return type(valeur) is int and valeur >= 0
    if genre == "booleen":
        return type(valeur) is bool
    if genre == "couverture":
        return type(valeur) is str and valeur in COUVERTURES
    if genre == "categorie":
        return type(valeur) is str and valeur in CATEGORIES_PLAINTE
    if genre == "textes":
        return type(valeur) is list and all(type(t) is str and t.strip() for t in valeur)
    return False


def _date(valeur: object) -> dt.date | None:
    """Date civile réelle ``AAAA-MM-JJ`` (``2026-99-99`` est refusée), sinon ``None``."""
    if type(valeur) is not str or _DATE.fullmatch(valeur) is None:
        return None
    try:
        return dt.date.fromisoformat(valeur)
    except ValueError:
        return None


def _coherence(domaine: str, charge: Mapping) -> list[str]:
    """Règles entre champs d'une charge dont chaque champ a déjà la bonne forme. Rien n'est corrigé : tout écart est
    rendu nommé."""
    erreurs: list[str] = []
    debut, fin = _date(charge.get("debut")), _date(charge.get("fin"))
    if debut is not None and fin is not None and fin < debut:
        erreurs.append("fin antérieure au début")
    if domaine == "capacite_equipe":
        if charge["calculable"] is False and not charge["manque"]:
            erreurs.append("calculable faux sans manque nommé")
        ids = [ligne["equipe_id"] for ligne in charge["equipes"]]
        if len(set(ids)) != len(ids):
            erreurs.append("equipe_id en double")
    elif domaine == "plaintes_structurees":
        categories = [ligne["categorie"] for ligne in charge["categories"]]
        if len(set(categories)) != len(categories):
            erreurs.append("catégorie en double")
        elif sum(ligne["ouvertes"] for ligne in charge["categories"]) != charge["ouvertes_total"]:
            erreurs.append("ouvertes_total différent de la somme des catégories")
    return sorted(set(erreurs))


def valider_charge(domaine: str, charge: object, arguments: Mapping | None = None) -> dict:
    """Conformité d'une charge candidate. ``manques`` = champs absents ; ``erreurs`` = champs présents mais invalides,
    puis, si la forme est bonne, les incohérences entre champs (période inversée, doublons, total différent de la
    somme, calcul impossible ou couverture partielle sans manque nommé).

    Rien n'est complété : un champ absent reste absent et nommé. ``conforme`` n'est vrai que sans manque ni erreur ;
    une charge non objet n'est jamais conforme."""
    contrat = CONTRATS[domaine]
    manques: list[str] = []
    erreurs: list[str] = []
    if not isinstance(charge, Mapping):
        return {"domaine": domaine, "conforme": False, "manques": ["charge"], "erreurs": ["charge non objet"]}
    if "reel" in contrat:
        # Contrat publié : la validation est celle que la capture applique à la réponse du producteur.
        enveloppe = contrat["reel"]["enveloppe_accepte"]
        page = {"resultat": {"accepte": True, "resultat": charge}} if enveloppe else {"resultat": charge}
        erreurs = charges_producteurs.valider(contrat["lecture_id"], page, arguments)
        return {"domaine": domaine, "conforme": not erreurs, "manques": [], "erreurs": erreurs}
    for champ, genre in contrat["racine"].items():
        if champ not in charge:
            manques.append(champ)
        elif not _valide(genre, charge[champ]):
            erreurs.append(f"{champ} : {genre} attendu")
    nom_liste, champs_ligne = contrat["liste"]
    lignes = charge.get(nom_liste)
    if lignes is None:
        manques.append(nom_liste)
    elif not isinstance(lignes, list):
        erreurs.append(f"{nom_liste} : liste attendue")
    else:
        for i, ligne in enumerate(lignes):
            if not isinstance(ligne, Mapping):
                erreurs.append(f"{nom_liste}[{i}] : objet attendu")
                continue
            for champ, genre in champs_ligne.items():
                if champ not in ligne:
                    manques.append(f"{nom_liste}[{i}].{champ}")
                elif not _valide(genre, ligne[champ]):
                    erreurs.append(f"{nom_liste}[{i}].{champ} : {genre} attendu")
    if not manques and not erreurs:
        erreurs = _coherence(domaine, charge)
    return {"domaine": domaine, "conforme": not manques and not erreurs, "manques": manques, "erreurs": erreurs}


def refuser_extrapolation(charge: object, *, presentee_comme_prevision_de_proprietaire: bool) -> None:
    """Refuse qu'une tendance extrapolée par M9 soit présentée comme la prévision d'un propriétaire."""
    if (
        presentee_comme_prevision_de_proprietaire
        and isinstance(charge, Mapping)
        and charge.get("origine") == ORIGINE_EXTRAPOLATION
    ):
        raise ValueError("REJ-CONTRAT-EXTRAPOLATION : une tendance extrapolée n'est pas une prévision de propriétaire")


def resume() -> list[dict]:
    """Contrats attendus avec leur état, pour la documentation et les tests (aucune lecture, aucune valeur)."""
    return [
        {
            "domaine": domaine,
            "proprietaire": contrat["proprietaire"],
            "lecture_id": contrat["lecture_id"],
            "outil_attendu": contrat["outil_attendu"],
            "etat": etat(domaine),
            "limite": contrat["limite"],
        }
        for domaine, contrat in CONTRATS.items()
    ]
