"""Registre de BARÈME déclaré, versionné et chaîné (M3-C1, ANALYSE-M3 « défaut grave »).

Avant ce module, le barème (coûts unitaires, durée par unité), la quantité et le plancher rentable étaient des
ARGUMENTS D'APPEL de ``m3_estimer_projet`` : rien ne les reliait à une source, et la règle « aucun chiffre produit par
un modèle » ne tenait que pour l'arithmétique, pas pour les entrées. Un barème est maintenant une DÉCLARATION écrite de
l'entreprise :

- un ensemble de LIGNES (service, ouvrage ou matériau, unité, coût unitaire min / probable / max, temps par unité,
  taux de perte, SOURCE ÉCRITE de chaque ligne) ;
- des PARAMÈTRES déclarés avec lui : plancher rentable, taux de marge des trois scénarios, seuils de revue d'un devis,
  seuils de la revue d'une mesure à bornes larges ;
- les textes de soumission déclarés (exclusions, hypothèses, validité) ;
- sa date d'effet, son auteur (une personne, jamais un modèle) et son horodatage.

Aucune valeur n'est écrite ici : ce module ne contient AUCUN coût, AUCUN taux, AUCUN seuil par défaut. Une valeur de
départ éventuelle vient d'une source écrite de l'entreprise (soumissions passées, onboarding) et se déclare
``a_valider`` : tant que le propriétaire ne l'a pas validée (``valider_version``), elle n'est pas utilisable.

Le registre est APPEND-ONLY et CHAÎNÉ (chaque maillon porte l'empreinte du précédent) : une révision ajoute une version,
elle n'écrase jamais l'ancienne. Une estimation faite avec la version 1 reste donc rejouable avec la version 1 après la
version 2 (``resoudre(..., exiger_en_vigueur=False)``). Limite assumée, la même que ``registre.py`` : la chaîne détecte
l'altération d'un maillon suivi d'un autre et rejoue chaque invariant à la lecture, mais elle ne prouve pas
l'authenticité d'une chaîne entièrement réécrite par quelqu'un qui peut recalculer les empreintes.

Une version est EN VIGUEUR à l'instant t si elle est validée, que sa date d'effet est passée, qu'aucune version plus
récente (validée, en effet) ne la remplace et qu'elle n'a pas atteint sa fin de validité déclarée. L'estimation EXIGE
une référence ``{bareme_id, version}`` (``empreinte`` facultative, vérifiée si elle est donnée) qui existe et qui est en
vigueur : sinon un refus nomme ce qu'il faut déclarer ou corriger. L'écriture passe par UNE seule fonction
(``declarer_version``) : c'est le point d'accroche de la saisie par le propriétaire (réglages de direction, CFG-1).

Module pur (ADR-0009) : aucun import ``opsys``, aucune horloge (l'instant est un paramètre), aucun accès réseau.
"""

from __future__ import annotations

import copy
import re
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from . import hierarchie_echelle, revue_devis, verdicts
from .devis_durable import _ajouter
from .registre import _encoder_canonique

__all__ = [
    "MAX_COMPOSANTES",
    "MAX_ESTIMATEURS",
    "MAX_LIGNES",
    "MAX_MAILLONS",
    "REGISTRE",
    "ROLES_AUTEUR",
    "SEMANTIQUE_TEMPS_QUALIFIEE",
    "compiler",
    "declarer_version",
    "lire_version",
    "lister",
    "parametres_de",
    "reference_de",
    "resoudre",
    "valider_version",
    "verifier_chaine",
]

REGISTRE = "bareme"
TYPE_VERSION = "bareme_version"
TYPE_VALIDATION = "bareme_validation"
MAX_MAILLONS = 2000
MAX_LIGNES = 200
MAX_TEXTES = 30
MAX_ESTIMATEURS = 20
MAX_COMPOSANTES = 16

# Qui peut signer un barème : le propriétaire ou un administrateur. Les rôles d'agent et de client n'y sont jamais.
ROLES_AUTEUR = frozenset({"nathan_owner", "admin"})

_GENRES = ("ouvrage", "materiau")
_ID_BAREME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,39}")
_CODE = re.compile(r"[A-Za-z0-9_.-]{1,64}")
_IDENTIFIANT = re.compile(r"[A-Za-z0-9_.:@-]{1,200}")
_DECIMAL = re.compile(r"[0-9]{1,9}(?:\.[0-9]{1,6})?")
# Un coefficient d'estimateur peut être NÉGATIF : c'est une soustraction déclarée (ouvertures, surface déduite).
# Zéro est refusé : un terme qui ne contribue à rien est une déclaration trompeuse, pas une simplification.
_DECIMAL_SIGNE = re.compile(r"-?[0-9]{1,9}(?:\.[0-9]{1,6})?")
_DATE = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})"
)
_SOURCE_ID = re.compile(r"[0-9a-f]{64}")

_CLES_LIGNE_COMMUNES = ("service", "genre", "element", "unite", "source_ecrite")
_CLES_OUVRAGE = (
    "cout_unitaire_min", "cout_unitaire_max", "cout_unitaire_mode", "duree_minutes_par_unite", "semantique_temps",
)
# Seule valeur qui qualifie les minutes d'un poste comme temps écoulé sur site (pauses et déplacement exclus) pour la
# trace de temps de l'apprentissage ; doit rester égale à `trace_calibration_temps._SEMANTIQUE_TEMPS_QUALIFIEE`
# (un test le garde). Absente, la durée reste « non qualifiée » : jamais une qualification devinée.
SEMANTIQUE_TEMPS_QUALIFIEE = "duree_ecoulee_intervention"
_CLES_OUVRAGE_REQUISES = ("cout_unitaire_min", "cout_unitaire_max")
_CLES_MATERIAU = ("quantite_par_unite", "taux_perte", "sku")
_CLES_MATERIAU_REQUISES = ("quantite_par_unite",)
_CLES_PARAMETRES = ("plancher_rentable_cad", "taux_marge", "seuils_revue", "mesure", "estimateurs")
_SCENARIOS = ("prudent", "normal", "agressif")
_CLES_MESURE = ("largeur_relative_revue", "largeur_relative_max_prix", "validite_jours")
_CLES_ESTIMATEUR = ("unite_ouvrage", "composantes", "quantite_minimum", "temps_minimum_minutes")
_CLES_COMPOSANTE = ("grandeur", "unite", "coefficient", "facteur_conversion", "source_ecrite")
_CLES_SOUMISSION = ("exclusions", "hypotheses", "validite_jours")
_CLES_MAILLON_VERSION = frozenset({
    "type_entree", "rang", "precedent", "bareme_id", "version", "lignes", "parametres", "soumission",
    "date_effet", "valide_jusqu_au", "a_valider", "auteur", "horodatage", "source_id",
})
_CLES_MAILLON_VALIDATION = frozenset({
    "type_entree", "rang", "precedent", "bareme_id", "version", "auteur", "horodatage", "source_id",
})
_CLES_CONTENU = (
    "bareme_id", "lignes", "parametres", "soumission", "date_effet", "valide_jusqu_au", "a_valider",
)


class _Refus(Exception):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code} : {detail}")

    def verdict(self) -> dict:
        return verdicts.construire_verdict(self.code, detail=self.detail)


def _invalide(detail: str) -> _Refus:
    return _Refus("REJ-BAREME-INVALIDE", detail)


# -- validation des champs ---------------------------------------------------------------------------------------
def _texte(valeur: Any, maximum: int, *, multiligne: bool = False) -> bool:
    return (
        type(valeur) is str
        and 0 < len(valeur) <= maximum
        and valeur == valeur.strip()
        and not any(
            unicodedata.category(c) in {"Cc", "Cf", "Cs"} and not (multiligne and c in "\n")
            for c in valeur
        )
    )


def _decimal(valeur: Any, champ: str, *, strict_positif: bool = False) -> Decimal:
    """Un texte décimal (jamais un nombre JSON : un flottant arrondirait en silence) lu en ``Decimal``."""
    if type(valeur) is not str or _DECIMAL.fullmatch(valeur) is None:
        raise _invalide(
            f"{champ} : un texte décimal est attendu (ex. \"12.50\", jusqu'à 6 décimales), jamais un nombre"
        )
    lu = Decimal(valeur)
    if strict_positif and lu <= 0:
        raise _invalide(f"{champ} : une valeur strictement positive est attendue")
    return lu


def _instant(valeur: Any, champ: str) -> datetime:
    if type(valeur) is not str or _DATE.fullmatch(valeur) is None:
        raise _invalide(f"{champ} : un horodatage ISO 8601 avec fuseau est attendu (ex. 2026-11-02T00:00:00-05:00)")
    try:
        lu = datetime.fromisoformat(valeur)
    except ValueError:
        raise _invalide(f"{champ} : horodatage illisible") from None
    if lu.utcoffset() is None:
        raise _invalide(f"{champ} : le fuseau horaire est obligatoire")
    return lu


def _fermer(cles_recues: Any, autorisees: tuple[str, ...], requises: tuple[str, ...], etiquette: str) -> None:
    if type(cles_recues) is not dict:
        raise _invalide(f"{etiquette} : un objet est attendu")
    inconnues = sorted(set(cles_recues) - set(autorisees), key=str)
    manquantes = [cle for cle in requises if cle not in cles_recues]
    if inconnues or manquantes:
        raise _invalide(f"{etiquette} : clés inconnues {inconnues}, clés manquantes {manquantes}")


def _valider_ligne(index: int, ligne: Any) -> None:
    etiquette = f"lignes[{index}]"
    if type(ligne) is not dict:
        raise _invalide(f"{etiquette} : un objet est attendu")
    genre = ligne.get("genre")
    if genre not in _GENRES:
        raise _invalide(f"{etiquette} : genre doit être l'un de {list(_GENRES)}")
    specifiques = _CLES_OUVRAGE if genre == "ouvrage" else _CLES_MATERIAU
    requises = _CLES_OUVRAGE_REQUISES if genre == "ouvrage" else _CLES_MATERIAU_REQUISES
    _fermer(ligne, _CLES_LIGNE_COMMUNES + specifiques, _CLES_LIGNE_COMMUNES + requises, etiquette)
    if type(ligne["service"]) is not str or _CODE.fullmatch(ligne["service"]) is None:
        raise _invalide(f"{etiquette} : service doit être un code de service (lettres, chiffres, _ . -)")
    for champ, maximum in (("element", 120), ("unite", 24), ("source_ecrite", 300)):
        if not _texte(ligne[champ], maximum):
            raise _invalide(
                f"{etiquette} : {champ} doit être un texte non vide de {maximum} caractères au plus, sans espace "
                "en tête ni en queue"
                + (" (la source écrite : nom du document, date, auteur)" if champ == "source_ecrite" else "")
            )
    if genre == "ouvrage":
        minimum = _decimal(ligne["cout_unitaire_min"], f"{etiquette}.cout_unitaire_min", strict_positif=True)
        maximum = _decimal(ligne["cout_unitaire_max"], f"{etiquette}.cout_unitaire_max", strict_positif=True)
        if minimum > maximum:
            raise _invalide(f"{etiquette} : cout_unitaire_min dépasse cout_unitaire_max")
        if "cout_unitaire_mode" in ligne:
            mode = _decimal(ligne["cout_unitaire_mode"], f"{etiquette}.cout_unitaire_mode", strict_positif=True)
            if not minimum <= mode <= maximum:
                raise _invalide(f"{etiquette} : cout_unitaire_mode doit se situer entre le minimum et le maximum")
        if "duree_minutes_par_unite" in ligne:
            _decimal(ligne["duree_minutes_par_unite"], f"{etiquette}.duree_minutes_par_unite", strict_positif=True)
        if "semantique_temps" in ligne and ligne["semantique_temps"] != SEMANTIQUE_TEMPS_QUALIFIEE:
            raise _invalide(
                f"{etiquette}.semantique_temps : seule la valeur {SEMANTIQUE_TEMPS_QUALIFIEE!r} est admise "
                "(minutes d'intervention écoulées par unité, pauses et déplacements exclus), ou l'absence"
            )
        return
    _decimal(ligne["quantite_par_unite"], f"{etiquette}.quantite_par_unite", strict_positif=True)
    if "taux_perte" in ligne:
        perte = _decimal(ligne["taux_perte"], f"{etiquette}.taux_perte")
        if perte >= 1:
            raise _invalide(f"{etiquette} : taux_perte doit être inférieur à 1 (0.10 pour 10 %, jamais 10)")
    if "sku" in ligne and not _texte(ligne["sku"], 80):
        raise _invalide(f"{etiquette} : sku doit être un texte non vide s'il est fourni")


def _valider_lignes(lignes: Any) -> None:
    if type(lignes) is not list or not 0 < len(lignes) <= MAX_LIGNES:
        raise _invalide(f"lignes : une liste de 1 à {MAX_LIGNES} lignes est attendue")
    ouvrages: set[str] = set()
    materiaux: set[tuple[str, str]] = set()
    for index, ligne in enumerate(lignes):
        _valider_ligne(index, ligne)
        if ligne["genre"] == "ouvrage":
            if ligne["service"] in ouvrages:
                raise _invalide(
                    f"lignes[{index}] : le service {ligne['service']!r} a déjà une ligne d'ouvrage "
                    "(un seul coût unitaire par service dans une version)"
                )
            ouvrages.add(ligne["service"])
        else:
            cle = (ligne["service"], ligne.get("sku", ligne["element"]))
            if cle in materiaux:
                raise _invalide(f"lignes[{index}] : matériau {cle[1]!r} en double pour le service {cle[0]!r}")
            materiaux.add(cle)
    orphelins = sorted({s for s, _ in materiaux} - ouvrages)
    if orphelins:
        raise _invalide(f"matériaux sans ligne d'ouvrage pour le service : {orphelins}")


def _decimal_signe(valeur: Any, champ: str) -> Decimal:
    """Un coefficient SIGNÉ : positif (ajout) ou négatif (soustraction déclarée), jamais zéro."""
    if type(valeur) is not str or _DECIMAL_SIGNE.fullmatch(valeur) is None:
        raise _invalide(
            f"{champ} : un texte décimal signé est attendu (ex. \"1\" ou \"-1\", jusqu'à 6 décimales), jamais un nombre"
        )
    lu = Decimal(valeur)
    if lu == 0:
        raise _invalide(f"{champ} : un coefficient nul ne contribue à rien ; le retirer de la déclaration")
    return lu


def _valider_composante(etiquette: str, composante: Any, unite_ouvrage: str) -> None:
    _fermer(composante, _CLES_COMPOSANTE, ("grandeur", "unite", "coefficient", "source_ecrite"), etiquette)
    if type(composante["grandeur"]) is not str or _CODE.fullmatch(composante["grandeur"]) is None:
        raise _invalide(
            f"{etiquette}.grandeur : un code de grandeur est attendu (lettres, chiffres, _ . -), jamais un texte libre"
        )
    if not _texte(composante["unite"], 24):
        raise _invalide(f"{etiquette}.unite : un texte non vide de 24 caractères au plus est attendu")
    _decimal_signe(composante["coefficient"], f"{etiquette}.coefficient")
    if not _texte(composante["source_ecrite"], 300):
        raise _invalide(
            f"{etiquette}.source_ecrite : la source écrite du coefficient est obligatoire (nom du document, date, "
            "auteur)"
        )
    if composante["unite"] != unite_ouvrage:
        if "facteur_conversion" not in composante:
            raise _invalide(
                f"{etiquette} ({composante['grandeur']!r}) : la composante se mesure en {composante['unite']!r}, "
                f"l'ouvrage en {unite_ouvrage!r} ; un facteur_conversion déclaré est obligatoire (aucune conversion "
                "n'est devinée)"
            )
        _decimal(composante["facteur_conversion"], f"{etiquette}.facteur_conversion", strict_positif=True)
    elif "facteur_conversion" in composante:
        raise _invalide(
            f"{etiquette} ({composante['grandeur']!r}) : facteur_conversion est interdit quand la composante et "
            "l'ouvrage partagent la même unité (la conversion serait ambiguë)"
        )


def _valider_estimateurs(estimateurs: Any) -> None:
    """Les estimateurs par service : des coefficients DÉCLARÉS, chacun avec sa source écrite.

    Aucune formule ni aucun coefficient n'est écrit dans le code. La structure est fermée : une clé inconnue, une
    grandeur en double, une conversion implicite ou un coefficient nul sont refusés à la déclaration."""
    if type(estimateurs) is not dict or len(estimateurs) > MAX_ESTIMATEURS:
        raise _invalide(f"parametres.estimateurs : un objet d'au plus {MAX_ESTIMATEURS} services est attendu")
    for service, estimateur in estimateurs.items():
        if type(service) is not str or _CODE.fullmatch(service) is None:
            raise _invalide("parametres.estimateurs : chaque clé doit être un code de service")
        etiquette = f"parametres.estimateurs.{service}"
        _fermer(estimateur, _CLES_ESTIMATEUR, ("unite_ouvrage", "composantes"), etiquette)
        if not _texte(estimateur["unite_ouvrage"], 24):
            raise _invalide(f"{etiquette}.unite_ouvrage : un texte non vide de 24 caractères au plus est attendu")
        composantes = estimateur["composantes"]
        if (
            type(composantes) is not list or not 0 < len(composantes) <= MAX_COMPOSANTES
        ):
            raise _invalide(
                f"{etiquette}.composantes : une liste de 1 à {MAX_COMPOSANTES} composantes est attendue"
            )
        grandeurs: set[str] = set()
        for index, composante in enumerate(composantes):
            sous_etiquette = f"{etiquette}.composantes[{index}]"
            _valider_composante(sous_etiquette, composante, estimateur["unite_ouvrage"])
            if composante["grandeur"] in grandeurs:
                raise _invalide(
                    f"{sous_etiquette}.grandeur : la grandeur {composante['grandeur']!r} est déclarée en double "
                    "(une seule mesure par grandeur)"
                )
            grandeurs.add(composante["grandeur"])
        for nom in ("quantite_minimum", "temps_minimum_minutes"):
            if nom in estimateur:
                _decimal(estimateur[nom], f"{etiquette}.{nom}", strict_positif=True)


def _verifier_estimateurs_avec_lignes(lignes: Any, parametres: Any) -> None:
    """Un estimateur ne peut chiffrer que le service dont le barème porte une ligne d'ouvrage, dans SON unité."""
    estimateurs = parametres.get("estimateurs") if isinstance(parametres, dict) else None
    if not isinstance(estimateurs, dict):
        return
    ouvrages = {ligne["service"]: ligne for ligne in lignes if ligne.get("genre") == "ouvrage"}
    for service, estimateur in estimateurs.items():
        ligne = ouvrages.get(service)
        if ligne is None:
            raise _invalide(
                f"parametres.estimateurs.{service} : aucune ligne d'ouvrage pour ce service dans la même version ; "
                "l'estimateur ne pourrait chiffrer aucun coût"
            )
        if estimateur["unite_ouvrage"] != ligne["unite"]:
            raise _invalide(
                f"parametres.estimateurs.{service}.unite_ouvrage : {estimateur['unite_ouvrage']!r} diffère de l'unité "
                f"de la ligne d'ouvrage ({ligne['unite']!r}) ; les deux doivent être identiques"
            )



def _valider_parametres(parametres: Any) -> None:
    _fermer(parametres, _CLES_PARAMETRES, (), "parametres")
    if "plancher_rentable_cad" in parametres:
        _decimal(parametres["plancher_rentable_cad"], "parametres.plancher_rentable_cad")
    if "taux_marge" in parametres:
        taux = parametres["taux_marge"]
        _fermer(taux, _SCENARIOS, (), "parametres.taux_marge")
        for nom, brut in taux.items():
            if _decimal(brut, f"parametres.taux_marge.{nom}") > 10:
                raise _invalide(
                    f"parametres.taux_marge.{nom} : un taux décimal de 10 ou moins est attendu (0.35 pour 35 %)"
                )
    if "seuils_revue" in parametres:
        seuils = parametres["seuils_revue"]
        _fermer(seuils, tuple(revue_devis.CHAMPS_SEUILS), (), "parametres.seuils_revue")
        for nom, brut in seuils.items():
            if nom == "confiance_minimale":
                if brut not in hierarchie_echelle.NIVEAUX_CONFIANCE[:3]:
                    raise _invalide(
                        "parametres.seuils_revue.confiance_minimale : l'un de "
                        f"{list(hierarchie_echelle.NIVEAUX_CONFIANCE[:3])}"
                    )
            else:
                _decimal(brut, f"parametres.seuils_revue.{nom}", strict_positif=nom != "marge_minimale")
    if "mesure" in parametres:
        mesure = parametres["mesure"]
        _fermer(mesure, _CLES_MESURE, (), "parametres.mesure")
        largeurs = {}
        for nom in ("largeur_relative_revue", "largeur_relative_max_prix"):
            if nom in mesure:
                largeurs[nom] = _decimal(mesure[nom], f"parametres.mesure.{nom}", strict_positif=True)
        if (
            len(largeurs) == 2
            and largeurs["largeur_relative_revue"] > largeurs["largeur_relative_max_prix"]
        ):
            raise _invalide(
                "parametres.mesure : le seuil de revue ne peut pas dépasser le seuil au-delà duquel "
                "aucun prix n'est donné"
            )
        if "validite_jours" in mesure and (
            type(mesure["validite_jours"]) is not int or not 0 < mesure["validite_jours"] <= 3650
        ):
            raise _invalide("parametres.mesure.validite_jours : un nombre entier de jours entre 1 et 3650 est attendu")
    if "estimateurs" in parametres:
        _valider_estimateurs(parametres["estimateurs"])


def _valider_soumission(soumission: Any) -> None:
    _fermer(soumission, _CLES_SOUMISSION, (), "soumission")
    for nom in ("exclusions", "hypotheses"):
        if nom not in soumission:
            continue
        textes = soumission[nom]
        if type(textes) is not list or len(textes) > MAX_TEXTES:
            raise _invalide(f"soumission.{nom} : une liste d'au plus {MAX_TEXTES} textes est attendue")
        for index, texte in enumerate(textes):
            if not _texte(texte, 500, multiligne=True):
                raise _invalide(f"soumission.{nom}[{index}] : un texte non vide de 500 caractères au plus est attendu")
    if "validite_jours" in soumission and (
        type(soumission["validite_jours"]) is not int or not 0 < soumission["validite_jours"] <= 365
    ):
        raise _invalide("soumission.validite_jours : un nombre entier de jours entre 1 et 365 est attendu")


def _valider_auteur(auteur: Any) -> None:
    if (
        type(auteur) is not dict
        or set(auteur) != {"personne", "role"}
        or type(auteur["personne"]) is not str
        or _IDENTIFIANT.fullmatch(auteur["personne"]) is None
        or auteur["role"] not in ROLES_AUTEUR
    ):
        raise _Refus(
            "REJ-BAREME-IDENTITE",
            "un barème est déclaré par une personne (propriétaire ou administrateur), jamais par un agent : "
            "{personne, role} attendu avec role dans " + str(sorted(ROLES_AUTEUR)),
        )


def _valider_contenu(contenu: dict[str, Any]) -> tuple[datetime, datetime | None]:
    if type(contenu["bareme_id"]) is not str or _ID_BAREME.fullmatch(contenu["bareme_id"]) is None:
        raise _invalide(
            "bareme_id : 1 à 40 caractères (lettres, chiffres, _ . -), commençant par une lettre ou un chiffre"
        )
    _valider_lignes(contenu["lignes"])
    _valider_parametres(contenu["parametres"])
    _verifier_estimateurs_avec_lignes(contenu["lignes"], contenu["parametres"])
    _valider_soumission(contenu["soumission"])
    if type(contenu["a_valider"]) is not bool:
        raise _invalide("a_valider : un booléen est attendu")
    effet = _instant(contenu["date_effet"], "date_effet")
    fin = None
    if contenu["valide_jusqu_au"] is not None:
        fin = _instant(contenu["valide_jusqu_au"], "valide_jusqu_au")
        if fin <= effet:
            raise _invalide("valide_jusqu_au doit suivre date_effet")
    return effet, fin


# -- chaîne ------------------------------------------------------------------------------------------------------
def _sceller(maillon: dict[str, Any]) -> str:
    return _encoder_canonique({cle: valeur for cle, valeur in maillon.items() if cle != "source_id"})


_Chargement = tuple[
    list[Any], dict[str, list[dict[str, Any]]], dict[tuple[str, int], dict[str, Any]], "str | None"
]


def _charger(journal: Any) -> _Chargement:
    """Relit TOUTE la chaîne et rejoue chaque invariant. Rend (maillons, versions par id, validations, tête)."""
    maillons = list(journal)
    if len(maillons) > MAX_MAILLONS:
        raise _Refus("REJ-BAREME-ALTERE", f"le registre de barèmes dépasse {MAX_MAILLONS} maillons")
    versions: dict[str, list[dict[str, Any]]] = {}
    validations: dict[tuple[str, int], dict[str, Any]] = {}
    precedent: str | None = None
    for rang, maillon in enumerate(maillons):
        try:
            _verifier_maillon(maillon, rang, precedent, versions, validations)
        except (_Refus, KeyError, TypeError, ValueError, InvalidOperation, RecursionError):
            raise _Refus(
                "REJ-BAREME-ALTERE",
                f"le registre de barèmes est altéré ou incohérent au maillon {rang} : ne pas s'en servir "
                "avant vérification",
            ) from None
        precedent = maillon["source_id"]
    return maillons, versions, validations, precedent


def _verifier_maillon(
    maillon: Any, rang: int, precedent: str | None, versions: dict[str, list[dict[str, Any]]],
    validations: dict[tuple[str, int], dict[str, Any]],
) -> None:
    if type(maillon) is not dict:
        raise _invalide("maillon illisible")
    type_entree = maillon.get("type_entree")
    cles = _CLES_MAILLON_VERSION if type_entree == TYPE_VERSION else _CLES_MAILLON_VALIDATION
    if type_entree not in (TYPE_VERSION, TYPE_VALIDATION) or set(maillon) != cles:
        raise _invalide("maillon aux clés inattendues")
    if (
        type(maillon["rang"]) is not int or maillon["rang"] != rang or maillon["precedent"] != precedent
        or type(maillon["source_id"]) is not str or _SOURCE_ID.fullmatch(maillon["source_id"]) is None
        or maillon["source_id"] != _sceller(maillon)
    ):
        raise _invalide("chaînage rompu")
    _valider_auteur(maillon["auteur"])
    _instant(maillon["horodatage"], "horodatage")
    identifiant = maillon["bareme_id"]
    deja = versions.get(identifiant, [])
    if type_entree == TYPE_VALIDATION:
        cible = maillon["version"]
        if (
            type(cible) is not int or not 1 <= cible <= len(deja) or not deja[cible - 1]["a_valider"]
            or (identifiant, cible) in validations
        ):
            raise _invalide("validation sans version à valider")
        validations[(identifiant, cible)] = maillon
        return
    if type(maillon["version"]) is not int or maillon["version"] != len(deja) + 1:
        raise _invalide("numéro de version hors séquence")
    effet, _ = _valider_contenu({cle: maillon[cle] for cle in _CLES_CONTENU})
    if deja and effet < _instant(deja[-1]["date_effet"], "date_effet"):
        raise _invalide("date d'effet antérieure à celle de la version précédente")
    versions.setdefault(identifiant, []).append(maillon)


def verifier_chaine(journal: Any) -> tuple[bool, str]:
    """``(True, "")`` si la chaîne est intacte, sinon ``(False, raison)`` (convention de ``registre.Registre``)."""
    try:
        _charger(journal)
    except _Refus as refus:
        return False, refus.detail
    return True, ""


# -- vue publique ------------------------------------------------------------------------------------------------
def _est_valide(version: dict[str, Any], validations: dict[tuple[str, int], dict[str, Any]]) -> bool:
    return not version["a_valider"] or (version["bareme_id"], version["version"]) in validations


def _public(version: dict[str, Any], validations: dict[tuple[str, int], dict[str, Any]]) -> dict[str, Any]:
    validation = validations.get((version["bareme_id"], version["version"]))
    vue = {cle: copy.deepcopy(version[cle]) for cle in (
        "bareme_id", "version", "lignes", "parametres", "soumission", "date_effet", "valide_jusqu_au",
        "a_valider", "auteur", "horodatage",
    )}
    vue["empreinte"] = version["source_id"]
    vue["valide"] = _est_valide(version, validations)
    vue["validee_par"] = copy.deepcopy(validation["auteur"]) if validation is not None else None
    vue["validee_le"] = validation["horodatage"] if validation is not None else None
    return vue


def reference_de(version_publique: dict[str, Any]) -> dict[str, Any]:
    """La référence EXACTE d'une version : ce que l'estimation rappelle pour que son calcul soit rejouable."""
    return {
        "bareme_id": version_publique["bareme_id"],
        "version": version_publique["version"],
        "empreinte": version_publique["empreinte"],
    }


def parametres_de(version_publique: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(version_publique["parametres"])


def lire_version(journal: Any, bareme_id: Any, version: Any = 0) -> tuple[dict[str, Any] | None, dict | None]:
    """Une version (0 = la dernière déclarée), avec son empreinte et son état de validation."""
    try:
        _, versions, validations, _ = _charger(journal)
        if type(bareme_id) is not str or bareme_id not in versions:
            raise _Refus(
                "REJ-BAREME-INTROUVABLE",
                f"aucun barème {bareme_id!r} n'est déclaré ; déclarer le barème de l'entreprise (m3_declarer_bareme)",
            )
        liste = versions[bareme_id]
        if type(version) is not int or isinstance(version, bool) or not 0 <= version <= len(liste):
            raise _Refus(
                "REJ-BAREME-VERSION-INCONNUE",
                f"le barème {bareme_id!r} n'a pas de version {version!r} (dernière version : {len(liste)})",
            )
        choisie = liste[-1] if version == 0 else liste[version - 1]
        return _public(choisie, validations), None
    except _Refus as refus:
        return None, refus.verdict()


def lister(journal: Any, maintenant: datetime | None = None) -> tuple[list[dict[str, Any]] | None, dict | None]:
    """Les barèmes déclarés : leurs versions (sans les lignes) et, si ``maintenant`` est fourni, celle en vigueur."""
    try:
        _, versions, validations, _ = _charger(journal)
    except _Refus as refus:
        return None, refus.verdict()
    resultat = []
    for identifiant in sorted(versions):
        liste = versions[identifiant]
        courante = _en_vigueur(liste, validations, maintenant) if maintenant is not None else None
        resultat.append({
            "bareme_id": identifiant,
            "derniere_version": len(liste),
            "version_en_vigueur": courante["version"] if courante is not None else None,
            "versions": [
                {
                    "version": v["version"], "date_effet": v["date_effet"], "valide_jusqu_au": v["valide_jusqu_au"],
                    "valide": _est_valide(v, validations), "empreinte": v["source_id"],
                }
                for v in liste
            ],
        })
    return resultat, None


# -- écriture (UNE fonction par geste) ---------------------------------------------------------------------------
def _contenu_declare(
    bareme_id: Any, lignes: Any, parametres: Any, soumission: Any, date_effet: Any, valide_jusqu_au: Any,
    a_valider: Any,
) -> dict[str, Any]:
    return {
        "bareme_id": bareme_id,
        "lignes": lignes,
        "parametres": {} if parametres is None else parametres,
        "soumission": {} if soumission is None else soumission,
        "date_effet": date_effet,
        "valide_jusqu_au": valide_jusqu_au,
        "a_valider": a_valider,
    }


def declarer_version(
    journal: Any, *, bareme_id: Any, version_attendue: Any, lignes: Any, parametres: Any = None,
    soumission: Any = None, date_effet: Any, valide_jusqu_au: Any = None, a_valider: Any = False, auteur: Any,
    horodatage: Any,
) -> tuple[dict[str, Any] | None, dict | None]:
    """DÉCLARE une version de barème : la seule fonction qui écrit une version (accroche de la saisie par la direction).

    ``version_attendue`` : la version que l'auteur a sous les yeux (0 pour créer le barème). Une autre écriture
    entre-temps donne ``REJ-BAREME-REVISION-PERIMEE`` (relire avant de réviser) ; le même appel rejoué après son succès
    rend la version déjà écrite (``rejoue``), sans second maillon. ``auteur`` et ``horodatage`` viennent du serveur ;
    l'adaptateur revérifie la personne. Rend ``({"version", "rejoue"}, None)`` ou ``(None, verdict)``."""
    try:
        contenu = _contenu_declare(bareme_id, lignes, parametres, soumission, date_effet, valide_jusqu_au, a_valider)
        effet, _ = _valider_contenu(contenu)
        _valider_auteur(auteur)
        _instant(horodatage, "horodatage")
        if type(version_attendue) is not int or isinstance(version_attendue, bool) or version_attendue < 0:
            raise _invalide("version_attendue : un entier, 0 pour créer le barème")
        maillons, versions, validations, tete = _charger(journal)
        deja = versions.get(bareme_id, [])
        if version_attendue != len(deja):
            suivante = deja[version_attendue] if version_attendue < len(deja) else None
            if suivante is not None and all(suivante[cle] == contenu[cle] for cle in _CLES_CONTENU) \
                    and suivante["auteur"] == auteur:
                return {"version": _public(suivante, validations), "rejoue": True}, None
            raise _Refus(
                "REJ-BAREME-REVISION-PERIMEE",
                f"le barème {bareme_id!r} est à la version {len(deja)} (la déclaration part de la version "
                f"{version_attendue}) : relire la version courante avant de la réviser",
            )
        if deja and effet < _instant(deja[-1]["date_effet"], "date_effet"):
            raise _invalide(
                f"date_effet : une révision prend effet à la date de la version précédente ({deja[-1]['date_effet']}) "
                "ou après, jamais avant"
            )
        if len(maillons) >= MAX_MAILLONS:
            raise _Refus("REJ-BAREME-ALTERE", f"le registre de barèmes est plein ({MAX_MAILLONS} maillons)")
        maillon: dict[str, Any] = {
            "type_entree": TYPE_VERSION, "rang": len(maillons), "precedent": tete, "bareme_id": bareme_id,
            "version": len(deja) + 1, **{cle: contenu[cle] for cle in _CLES_CONTENU if cle != "bareme_id"},
            "auteur": copy.deepcopy(auteur), "horodatage": horodatage,
        }
        maillon["source_id"] = _sceller(maillon)
        _ajouter(maillon, journal, len(maillons))
        _, versions, validations, _ = _charger(journal)
        return {"version": _public(versions[bareme_id][-1], validations), "rejoue": False}, None
    except _Refus as refus:
        return None, refus.verdict()


def valider_version(
    journal: Any, *, bareme_id: Any, version: Any, auteur: Any, horodatage: Any,
) -> tuple[dict[str, Any] | None, dict | None]:
    """Le propriétaire VALIDE une version déclarée ``a_valider`` (valeur de départ tirée d'une source écrite).

    Sans cette validation la version n'est pas utilisable. Valider deux fois rend la première (``rejoue``)."""
    try:
        _valider_auteur(auteur)
        _instant(horodatage, "horodatage")
        maillons, versions, validations, tete = _charger(journal)
        liste = versions.get(bareme_id)
        if liste is None:
            raise _Refus("REJ-BAREME-INTROUVABLE", f"aucun barème {bareme_id!r} n'est déclaré")
        if type(version) is not int or isinstance(version, bool) or not 1 <= version <= len(liste):
            raise _Refus("REJ-BAREME-VERSION-INCONNUE", f"le barème {bareme_id!r} n'a pas de version {version!r}")
        cible = liste[version - 1]
        if not cible["a_valider"]:
            raise _invalide(f"la version {version} du barème {bareme_id!r} a été déclarée valide : rien à valider")
        if (bareme_id, version) in validations:
            return {"version": _public(cible, validations), "rejoue": True}, None
        if len(maillons) >= MAX_MAILLONS:
            raise _Refus("REJ-BAREME-ALTERE", f"le registre de barèmes est plein ({MAX_MAILLONS} maillons)")
        maillon = {
            "type_entree": TYPE_VALIDATION, "rang": len(maillons), "precedent": tete, "bareme_id": bareme_id,
            "version": version, "auteur": copy.deepcopy(auteur), "horodatage": horodatage,
        }
        maillon["source_id"] = _sceller(maillon)
        _ajouter(maillon, journal, len(maillons))
        _, versions, validations, _ = _charger(journal)
        return {"version": _public(versions[bareme_id][version - 1], validations), "rejoue": False}, None
    except _Refus as refus:
        return None, refus.verdict()


# -- résolution d'une référence ----------------------------------------------------------------------------------
def _en_vigueur(
    liste: list[dict[str, Any]], validations: dict[tuple[str, int], dict[str, Any]], maintenant: datetime,
) -> dict[str, Any] | None:
    """La version en vigueur à ``maintenant`` : la plus récente des versions validées déjà en effet (sauf fin)."""
    actives = [
        v for v in liste
        if _est_valide(v, validations) and _instant(v["date_effet"], "date_effet") <= maintenant
    ]
    if not actives:
        return None
    courante = max(actives, key=lambda v: v["version"])
    fin = courante["valide_jusqu_au"]
    if fin is not None and maintenant >= _instant(fin, "valide_jusqu_au"):
        return None
    return courante


def _lire_reference(reference: Any) -> tuple[str, int, str | None]:
    if (
        type(reference) is not dict
        or not {"bareme_id", "version"} <= set(reference)
        or not set(reference) <= {"bareme_id", "version", "empreinte"}
        or type(reference["bareme_id"]) is not str
        or type(reference["version"]) is not int or isinstance(reference["version"], bool)
        or reference["version"] < 1
        or reference.get("empreinte") is not None and (
            type(reference["empreinte"]) is not str or _SOURCE_ID.fullmatch(reference["empreinte"]) is None
        )
    ):
        raise _Refus(
            "REJ-BAREME-REFERENCE-REQUISE",
            "bareme_ref doit être {bareme_id, version} (et éventuellement empreinte) : l'identifiant du barème "
            "déclaré et le numéro de version en vigueur (m3_lister_baremes les donne)",
        )
    return reference["bareme_id"], reference["version"], reference.get("empreinte")


def resoudre(
    journal: Any, reference: Any, maintenant: datetime, *, exiger_en_vigueur: bool = True,
) -> tuple[dict[str, Any] | None, dict | None]:
    """Résout ``bareme_ref`` en une version de barème utilisable, ou refuse en disant quoi déclarer / corriger.

    ``exiger_en_vigueur=False`` : le REJEU d'une estimation ancienne (la version 1 reste lisible après la version 2) ;
    la version doit alors seulement exister, être validée et correspondre à l'empreinte donnée."""
    try:
        if maintenant.tzinfo is None:
            raise _invalide("l'instant de référence doit porter un fuseau horaire")
        identifiant, numero, empreinte = _lire_reference(reference)
        _, versions, validations, _ = _charger(journal)
        liste = versions.get(identifiant)
        if liste is None:
            raise _Refus(
                "REJ-BAREME-INTROUVABLE",
                f"aucun barème {identifiant!r} n'est déclaré. À faire : le propriétaire déclare le barème de "
                "l'entreprise (m3_declarer_bareme), puis l'estimation le référence par bareme_ref {bareme_id, version}",
            )
        if numero > len(liste):
            raise _Refus(
                "REJ-BAREME-VERSION-INCONNUE",
                f"le barème {identifiant!r} n'a pas de version {numero} (dernière version déclarée : {len(liste)}). "
                "À faire : référencer une version existante, ou déclarer la révision",
            )
        version = liste[numero - 1]
        if empreinte is not None and empreinte != version["source_id"]:
            raise _Refus(
                "REJ-BAREME-EMPREINTE-DIFFERENTE",
                f"l'empreinte donnée ne correspond pas à la version {numero} du barème {identifiant!r} : la référence "
                "vient d'une autre version ou d'un contenu modifié ; relire la version (m3_lire_bareme)",
            )
        if not _est_valide(version, validations):
            raise _Refus(
                "REJ-BAREME-A-VALIDER",
                f"la version {numero} du barème {identifiant!r} est une valeur de départ « à valider » : le "
                "propriétaire doit la valider (m3_valider_bareme) avant qu'une estimation s'en serve",
            )
        if exiger_en_vigueur:
            _exiger_en_vigueur(identifiant, version, liste, validations, maintenant)
        return _public(version, validations), None
    except _Refus as refus:
        return None, refus.verdict()


def _exiger_en_vigueur(
    identifiant: str, version: dict[str, Any], liste: list[dict[str, Any]],
    validations: dict[tuple[str, int], dict[str, Any]], maintenant: datetime,
) -> None:
    numero = version["version"]
    if _instant(version["date_effet"], "date_effet") > maintenant:
        raise _Refus(
            "REJ-BAREME-HORS-VIGUEUR",
            f"la version {numero} du barème {identifiant!r} ne prend effet que le {version['date_effet']} : pas encore "
            "en vigueur. À faire : utiliser la version en vigueur aujourd'hui",
        )
    courante = _en_vigueur(liste, validations, maintenant)
    if courante is None:
        raise _Refus(
            "REJ-BAREME-HORS-VIGUEUR",
            f"le barème {identifiant!r} n'a plus de version en vigueur (fin de validité atteinte). À faire : le "
            "propriétaire déclare une révision à jour (m3_declarer_bareme)",
        )
    if courante["version"] != numero:
        raise _Refus(
            "REJ-BAREME-PERIME",
            f"la version {numero} du barème {identifiant!r} est périmée : la version {courante['version']} est en "
            f"vigueur depuis le {courante['date_effet']}. À faire : référencer la version {courante['version']} "
            "(le calcul d'une ancienne estimation se rejoue avec m3_rejouer_estimation)",
        )


# -- compilation vers le barème du moteur ------------------------------------------------------------------------
def compiler(version_publique: dict[str, Any], service: Any) -> tuple[dict[str, Any] | None, dict | None]:
    """Le barème au format du moteur d'estimation (``monte_carlo``, ``besoins_materiaux``) pour UN service.

    Le moteur n'est pas réécrit : il lit ce dictionnaire comme il lisait l'argument libre. ``version`` devient
    ``<bareme_id>@v<n>`` : c'est elle qui entre dans la graine, dans l'empreinte du barème que la trace de temps
    garde et dans ``bareme_version`` des contrats — le point d'accroche d'une calibration qui doit se référer à une
    version de barème."""
    lignes = [ligne for ligne in version_publique["lignes"] if ligne["service"] == service]
    ouvrage = next((ligne for ligne in lignes if ligne["genre"] == "ouvrage"), None)
    identifiant, numero = version_publique["bareme_id"], version_publique["version"]
    if ouvrage is None:
        services = sorted({ligne["service"] for ligne in version_publique["lignes"] if ligne["genre"] == "ouvrage"})
        return None, verdicts.construire_verdict(
            "REJ-BAREME-INCOMPLET",
            detail=(
                f"la version {numero} du barème {identifiant!r} ne couvre pas le service {service!r} "
                f"(services couverts : {services}). À faire : le propriétaire déclare une ligne d'ouvrage pour ce "
                "service dans une révision du barème (m3_declarer_bareme)"
            ),
        )
    poste: dict[str, Any] = {
        "cout_unitaire_min": float(Decimal(ouvrage["cout_unitaire_min"])),
        "cout_unitaire_max": float(Decimal(ouvrage["cout_unitaire_max"])),
    }
    if "cout_unitaire_mode" in ouvrage:
        poste["cout_unitaire_mode"] = float(Decimal(ouvrage["cout_unitaire_mode"]))
    if "duree_minutes_par_unite" in ouvrage:
        poste["duree_minutes_par_unite"] = Decimal(ouvrage["duree_minutes_par_unite"])
    materiaux = []
    for ligne in lignes:
        if ligne["genre"] != "materiau":
            continue
        entree: dict[str, Any] = {
            "materiau": ligne["element"], "quantite_par_unite": ligne["quantite_par_unite"], "unite": ligne["unite"],
        }
        if "sku" in ligne:
            entree["sku"] = ligne["sku"]
        if "taux_perte" in ligne:
            entree["facteur_perte"] = ligne["taux_perte"]
        materiaux.append(entree)
    if materiaux:
        poste["materiaux"] = materiaux
    bareme: dict[str, Any] = {
        "version": f"{identifiant}@v{numero}", "unite": ouvrage["unite"], "postes": {service: poste},
    }
    if "semantique_temps" in ouvrage:
        bareme["semantique_temps"] = ouvrage["semantique_temps"]
    return bareme, None
