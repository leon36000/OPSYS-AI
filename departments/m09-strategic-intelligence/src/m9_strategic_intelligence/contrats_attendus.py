"""Contrats attendus des propriétaires : ce que M9 sait lire le jour où ils publient, sans rien fabriquer d'ici là.

Module pur. Pour chaque donnée qui manque aujourd'hui à M9 (capacité d'équipe M4, dépenses marketing M7, plaintes
structurées M1, liaison de versions de métriques M8), ce module fixe la FORME que le propriétaire devra publier et
valide une charge candidate contre elle. Il ne produit aucune valeur : une charge incomplète est rendue avec la liste
de ce qui manque, jamais complétée ; un nombre doit arriver en TEXTE décimal exact (un flottant est refusé) ; une
valeur hors de l'énuméré fermé est refusée.

L'état d'un contrat se lit sur le catalogue des lectures de M9 (``catalogue_producteurs``) : tant que la lecture
attendue n'y figure pas, le contrat est ``ABSENT_CHEZ_LE_PROPRIETAIRE`` et M9 le dit. Une extrapolation de M9
(``origine == "tendance_extrapolee"``) n'est jamais une prévision de propriétaire : ``refuser_extrapolation`` la refuse
si elle est présentée comme telle.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Mapping

from . import catalogue_producteurs as cat

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
        "racine": {"debut": "date", "fin": "date", "couverture": "couverture", "manque": "textes"},
        "liste": (
            "lignes",
            {"canal": "identifiant", "montant_cad": "decimal", "constate_le": "date", "source_ref": "identifiant"},
        ),
        "limite": "Sans dépense publiée par M7, M9 ne calcule ni coût par lead ni ROI : il nomme "
        "DEPENSES_NON_BRANCHEES.",
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
    "liaisons_versions": {
        "champ_de_lecture_existante": True,
        "proprietaire": "m08-analytics",
        "lecture_id": "m8.definitions_metriques",
        "outil_attendu": "m8_lister_definitions_metriques",
        "racine": {},
        "liste": (
            "liaisons_versions",
            {"metric_id": "identifiant", "revision": "entier_positif", "empreinte": "empreinte"},
        ),
        "limite": "La révision entière du registre et l'empreinte de la définition restent deux informations "
        "distinctes ; une mesure historique sans liaison fiable reste non comparable.",
    },
}


def etat(domaine: str) -> str:
    """``PUBLIE`` si la lecture attendue figure au catalogue de M9 ; sinon ``ABSENT_CHEZ_LE_PROPRIETAIRE``.

    Le contrat d'un CHAMP dans une lecture qui existe déjà (``champ_de_lecture_existante``) ne peut pas être jugé
    publié par le seul catalogue : il reste ``CHAMP_NON_VERIFIE_CHEZ_LE_PROPRIETAIRE`` tant qu'un test sur le vrai
    producteur ne l'a pas constaté."""
    contrat = CONTRATS[domaine]
    if contrat.get("champ_de_lecture_existante"):
        return "CHAMP_NON_VERIFIE_CHEZ_LE_PROPRIETAIRE"
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
    if genre == "entier_positif":
        return type(valeur) is int and valeur >= 1
    if genre == "booleen":
        return type(valeur) is bool
    if genre == "couverture":
        return type(valeur) is str and valeur in COUVERTURES
    if genre == "categorie":
        return type(valeur) is str and valeur in CATEGORIES_PLAINTE
    if genre == "empreinte":
        return type(valeur) is str and re.fullmatch(r"[0-9a-f]{64}", valeur) is not None
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
    elif domaine == "depenses_marketing":
        for i, ligne in enumerate(charge["lignes"]):
            jour = _date(ligne["constate_le"])
            if debut is not None and fin is not None and jour is not None and not debut <= jour <= fin:
                erreurs.append(f"lignes[{i}].constate_le hors de la période")
        if charge["couverture"] != "COMPLETE" and not charge["manque"]:
            erreurs.append("couverture non complète sans manque nommé")
    elif domaine == "plaintes_structurees":
        categories = [ligne["categorie"] for ligne in charge["categories"]]
        if len(set(categories)) != len(categories):
            erreurs.append("catégorie en double")
        elif sum(ligne["ouvertes"] for ligne in charge["categories"]) != charge["ouvertes_total"]:
            erreurs.append("ouvertes_total différent de la somme des catégories")
    elif domaine == "liaisons_versions":
        par_empreinte: dict[tuple, int] = {}
        par_revision: dict[tuple, str] = {}
        for ligne in charge["liaisons_versions"]:
            metrique, revision, empreinte = ligne["metric_id"], ligne["revision"], ligne["empreinte"]
            if par_empreinte.setdefault((metrique, empreinte), revision) != revision:
                erreurs.append(f"{metrique} : une même empreinte pour deux révisions")
            if par_revision.setdefault((metrique, revision), empreinte) != empreinte:
                erreurs.append(f"{metrique} : deux empreintes pour la révision {revision}")
    return sorted(set(erreurs))


def valider_charge(domaine: str, charge: object) -> dict:
    """Conformité d'une charge candidate. ``manques`` = champs absents ; ``erreurs`` = champs présents mais invalides,
    puis, si la forme est bonne, les incohérences entre champs (période inversée, doublons, total différent de la
    somme, liaisons contradictoires, calcul impossible ou couverture partielle sans manque nommé).

    Rien n'est complété : un champ absent reste absent et nommé. ``conforme`` n'est vrai que sans manque ni erreur ;
    une charge non objet n'est jamais conforme."""
    contrat = CONTRATS[domaine]
    manques: list[str] = []
    erreurs: list[str] = []
    if not isinstance(charge, Mapping):
        return {"domaine": domaine, "conforme": False, "manques": ["charge"], "erreurs": ["charge non objet"]}
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
