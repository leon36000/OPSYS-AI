"""Wallboards en direct (M8.8) : définitions DÉCLARATIVES de tableaux de bord et leur évaluation, en lecture.

Module PUR (ADR-0009) : aucun import d'``opsys``, aucune horloge (``maintenant`` vient de l'appelant). Une définition
(``wallboards/*.v1.yaml``) nomme des mesures du CATALOGUE FERMÉ, des seuils d'affichage et le rythme de
rafraîchissement ;
elle ne calcule rien. L'évaluation lit les mesures par ``moteur_mesures`` et leur fraîcheur par ``fraicheur_mesures`` :
c'est la même valeur et la même règle que partout ailleurs.

Garanties :

* UNE MESURE PÉRIMÉE N'EST JAMAIS MONTRÉE COMME À JOUR. Une tuile dont la fraîcheur n'est pas ``a_jour`` ou
  ``non_applicable`` porte ``perimee: true``, un libellé d'état en toutes lettres (jamais seulement une couleur) et son
  âge ; son seuil est ``indetermine`` (on ne colore pas, on n'alerte pas sur une valeur dont on ignore l'âge) ; la
  bannière d'alerte le dit.
* SANS DONNÉE PERSONNELLE. Une tuile porte une mesure d'entreprise (compte, durée, montant agrégé) ; aucune personne,
  aucun technicien, aucun client, aucun contact. ``donnees_personnelles`` vaut toujours ``false``.
* SEUILS DÉCLARÉS, JAMAIS INVENTÉS. Sans ``seuils`` la tuile n'a ni couleur ni alerte (``sans_seuil``). Les seuils sont
  comparés en ``Decimal`` ; un seuil mal formé refuse la définition entière.
* RÔLE RELU. ``roles`` dit qui peut voir le wallboard ; la console relit le rôle en base avant ET après la lecture.
* RAFRAÎCHISSEMENT BORNÉ. ``intervalle_s`` de 5 à 3600 secondes et ``flux_max`` de 1 à 1000 envois par flux (le flux se
  ferme de lui-même, le client se reconnecte) : aucun flux ne reste ouvert sans fin.

Les montants et les nombres sont mis en forme à partir de leur TEXTE exact (``formater_valeur``), jamais par un
flottant.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from . import catalogue_mesures, encodage, entonnoir, fraicheur_mesures, nombres

SCHEMA = "opsys.m8.wallboard/v1"
_DOSSIER = Path(__file__).resolve().parents[2] / "wallboards"

_CLES_RACINE = frozenset(
    {"schema", "id", "version", "titre", "description", "roles", "rafraichissement", "rotation", "tuiles"}
)
_CLES_TUILE = frozenset({"id", "mesure", "titre", "page", "seuils"})
_CLES_SEUILS = frozenset({"sens", "attention", "critique"})
_ROLES_PERMIS = frozenset({"admin", "nathan_owner"})
_IDENTIFIANT = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_TUILES_MAX = 12
_PAGES_MAX = 6
_TITRE_MAX = 80
INTERVALLE_MIN_S, INTERVALLE_MAX_S = 5, 3600
FLUX_MIN, FLUX_MAX = 1, 1000

ETAT_NORMAL = "normal"
ETAT_ATTENTION = "attention"
ETAT_CRITIQUE = "critique"
ETAT_INDETERMINE = "indetermine"
ETAT_SANS_SEUIL = "sans_seuil"

REJ_WALLBOARD_INVALIDE = "REJ-WALLBOARD-INVALIDE"
REJ_WALLBOARD_ILLISIBLE = "REJ-WALLBOARD-ILLISIBLE"
REJ_WALLBOARD_INCONNU = "REJ-WALLBOARD-INCONNU"
REJ_WALLBOARD_ROLE = "REJ-WALLBOARD-ROLE-REFUSE"


class WallboardRefuse(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code} : {detail}")
        self.code = code
        self.detail = detail


def _refus(detail: str) -> WallboardRefuse:
    return WallboardRefuse(REJ_WALLBOARD_INVALIDE, detail)


def _entier_borne(valeur: Any, minimum: int, maximum: int, nom: str) -> int:
    if isinstance(valeur, bool) or not isinstance(valeur, int) or not minimum <= valeur <= maximum:
        raise _refus(f"{nom} : entier de {minimum} à {maximum} attendu")
    return valeur


def _valider_seuils(tuile_id: str, brut: Any) -> dict[str, Any] | None:
    if brut is None:
        return None
    if not isinstance(brut, dict) or set(brut) != _CLES_SEUILS:
        raise _refus(f"{tuile_id} : seuils = {{sens, attention, critique}} exactement")
    if brut["sens"] not in (nombres.SENS_AU_DESSUS, nombres.SENS_AU_DESSOUS):
        raise _refus(f"{tuile_id} : seuils.sens : au_dessus ou au_dessous")
    lus = {}
    for cle in ("attention", "critique"):
        if not isinstance(brut[cle], str):
            raise _refus(f"{tuile_id} : seuils.{cle} : un texte décimal est attendu (jamais un flottant)")
        lu = nombres.decimal_lu(brut[cle])
        if lu is None:
            raise _refus(f"{tuile_id} : seuils.{cle} : nombre décimal illisible")
        lus[cle] = lu
    ordre_ok = (
        lus["critique"] >= lus["attention"]
        if brut["sens"] == nombres.SENS_AU_DESSUS
        else lus["critique"] <= lus["attention"]
    )
    if not ordre_ok:
        raise _refus(f"{tuile_id} : le seuil critique doit être plus sévère que le seuil d'attention")
    return {
        "sens": brut["sens"],
        "attention": lus["attention"],
        "critique": lus["critique"],
        "texte": {"attention": brut["attention"], "critique": brut["critique"]},
    }


def valider(brut: Any, catalogue: dict[str, Any]) -> dict[str, Any]:
    """Une définition validée (fail-closed : une clé de plus, une mesure hors catalogue, un identifiant en double, un
    seuil mal formé ou un rythme hors bornes refuse la définition entière)."""
    if not isinstance(brut, dict) or brut.get("schema") != SCHEMA:
        raise _refus(f"schema attendu : {SCHEMA}")
    inconnues = set(brut) - _CLES_RACINE
    if inconnues:
        raise _refus(f"clés inconnues : {sorted(inconnues)}")
    manquantes = {"id", "version", "titre", "roles", "rafraichissement", "tuiles"} - set(brut)
    if manquantes:
        raise _refus(f"clés manquantes : {sorted(manquantes)}")
    wallboard_id = brut["id"]
    if not isinstance(wallboard_id, str) or not _IDENTIFIANT.fullmatch(wallboard_id):
        raise _refus("id : minuscules, chiffres et tirets (40 caractères au plus)")
    _entier_borne(brut["version"], 1, 10**6, "version")
    titre = brut["titre"]
    if not isinstance(titre, str) or not 1 <= len(titre) <= _TITRE_MAX:
        raise _refus(f"titre : 1 à {_TITRE_MAX} caractères")
    roles = brut["roles"]
    if (
        not isinstance(roles, list)
        or not roles
        or not all(isinstance(r, str) for r in roles)
        or set(roles) - _ROLES_PERMIS
    ):
        raise _refus(f"roles : sous-ensemble non vide de {sorted(_ROLES_PERMIS)}")
    rafraichissement = brut["rafraichissement"]
    if not isinstance(rafraichissement, dict) or set(rafraichissement) != {"intervalle_s", "flux_max"}:
        raise _refus("rafraichissement = {intervalle_s, flux_max} exactement")
    intervalle = _entier_borne(
        rafraichissement["intervalle_s"], INTERVALLE_MIN_S, INTERVALLE_MAX_S, "rafraichissement.intervalle_s"
    )
    flux_max = _entier_borne(rafraichissement["flux_max"], FLUX_MIN, FLUX_MAX, "rafraichissement.flux_max")
    rotation = brut.get("rotation", {"actif": False, "intervalle_s": 20})
    if (
        not isinstance(rotation, dict)
        or set(rotation) != {"actif", "intervalle_s"}
        or not isinstance(rotation["actif"], bool)
    ):
        raise _refus("rotation = {actif: booléen, intervalle_s} exactement")
    _entier_borne(rotation["intervalle_s"], 5, 300, "rotation.intervalle_s")
    tuiles_brutes = brut["tuiles"]
    if not isinstance(tuiles_brutes, list) or not 1 <= len(tuiles_brutes) <= _TUILES_MAX:
        raise _refus(f"tuiles : 1 à {_TUILES_MAX} tuiles")
    entrees = catalogue_mesures.par_identifiant(catalogue)
    tuiles: list[dict[str, Any]] = []
    vus: set[str] = set()
    for tuile in tuiles_brutes:
        if not isinstance(tuile, dict) or set(tuile) - _CLES_TUILE or not {"id", "mesure", "titre"} <= set(tuile):
            raise _refus("chaque tuile = {id, mesure, titre, [page], [seuils]}")
        tuile_id = tuile["id"]
        if not isinstance(tuile_id, str) or not _IDENTIFIANT.fullmatch(tuile_id) or tuile_id in vus:
            raise _refus(f"tuile : identifiant illisible ou en double ({tuile_id!r})")
        vus.add(tuile_id)
        if tuile["mesure"] not in entrees:
            raise _refus(f"{tuile_id} : la mesure {tuile['mesure']!r} n'est pas au catalogue fermé")
        if not isinstance(tuile["titre"], str) or not 1 <= len(tuile["titre"]) <= _TITRE_MAX:
            raise _refus(f"{tuile_id} : titre : 1 à {_TITRE_MAX} caractères")
        page = _entier_borne(tuile.get("page", 1), 1, _PAGES_MAX, f"{tuile_id} : page")
        tuiles.append(
            {
                "id": tuile_id,
                "mesure": tuile["mesure"],
                "titre": tuile["titre"],
                "page": page,
                "seuils": _valider_seuils(tuile_id, tuile.get("seuils")),
            }
        )
    forme = {
        "id": wallboard_id,
        "version": brut["version"],
        "titre": titre,
        "description": brut.get("description", ""),
        "roles": list(roles),
        "intervalle_s": intervalle,
        "flux_max": flux_max,
        "rotation": dict(rotation),
        "tuiles": tuiles,
    }
    forme["empreinte"] = encodage.empreinte(
        {
            **{cle: valeur for cle, valeur in forme.items() if cle != "tuiles"},
            "tuiles": [
                {**t, "seuils": None if t["seuils"] is None else t["seuils"]["texte"] | {"sens": t["seuils"]["sens"]}}
                for t in tuiles
            ],
        }
    )
    return forme


def charger(catalogue: dict[str, Any], dossier: str | Path | None = None) -> dict[str, dict[str, Any]]:
    """Tous les wallboards du dossier (``*.v1.yaml``), ``{id: définition}``. Le nom du fichier est celui de l'id : un
    fichier dont l'id diffère est refusé. Un seul fichier invalide refuse l'ensemble (jamais un tableau de bord
    partiel)."""
    racine = Path(dossier) if dossier is not None else _DOSSIER
    resultat: dict[str, dict[str, Any]] = {}
    fichiers = sorted(racine.glob("*.v1.yaml"))
    if not fichiers:
        raise WallboardRefuse(REJ_WALLBOARD_ILLISIBLE, f"aucun wallboard dans {racine}")
    for fichier in fichiers:
        try:
            brut = yaml.safe_load(fichier.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as erreur:
            raise WallboardRefuse(REJ_WALLBOARD_ILLISIBLE, f"{fichier.name} ({erreur})") from erreur
        definition = valider(brut, catalogue)
        if fichier.name != f"{definition['id']}.v1.yaml":
            raise _refus(f"{fichier.name} : le nom du fichier doit être {definition['id']}.v1.yaml")
        if definition["id"] in resultat:
            raise _refus(f"wallboard {definition['id']} défini deux fois")
        resultat[definition["id"]] = definition
    return resultat


def resume(definition: dict[str, Any]) -> dict[str, Any]:
    """L'essentiel d'une définition pour une liste (sans tuiles ni seuils)."""
    return {
        "id": definition["id"],
        "titre": definition["titre"],
        "description": definition["description"],
        "version": definition["version"],
        "nb_tuiles": len(definition["tuiles"]),
        "intervalle_s": definition["intervalle_s"],
        "empreinte": definition["empreinte"],
    }


def role_permis(definition: dict[str, Any], roles: Any) -> bool:
    """Vrai si l'un des ``roles`` (ensemble de rôles relus en base) est permis par la définition. Fail-closed."""
    try:
        return bool(set(roles) & set(definition["roles"]))
    except TypeError:
        return False


# ---------------------------------------------------------------------------
# Mise en forme : à partir du TEXTE exact, jamais d'un flottant
# ---------------------------------------------------------------------------
_ESPACE_INSECABLE = " "


def _groupes_de_trois(chiffres: str) -> str:
    morceaux = []
    while len(chiffres) > 3:
        morceaux.insert(0, chiffres[-3:])
        chiffres = chiffres[:-3]
    morceaux.insert(0, chiffres)
    return _ESPACE_INSECABLE.join(morceaux)


def formater_valeur(valeur: str | None, unite: str) -> str:
    """La valeur en français québécois : espace insécable entre les milliers, virgule décimale, unité à la suite
    (``25 000,00 $``, ``50,00 %``, ``20 leads``). ``None`` : « non calculable » — jamais un zéro."""
    if valeur is None:
        return "non calculable"
    signe = "-" if valeur.startswith("-") else ""
    entiere, _, decimale = valeur.lstrip("-").partition(".")
    nombre = signe + _groupes_de_trois(entiere) + ("," + decimale if decimale else "")
    if unite == "CAD":
        return f"{nombre}{_ESPACE_INSECABLE}$"
    if unite == "pourcentage":
        return f"{nombre}{_ESPACE_INSECABLE}%"
    return f"{nombre}{_ESPACE_INSECABLE}{unite}"


def _etat_seuil(seuils: dict[str, Any] | None, valeur: str | None, fraiche: bool) -> str:
    if seuils is None:
        return ETAT_SANS_SEUIL
    lue = nombres.decimal_lu(valeur)
    if not fraiche or lue is None:
        return ETAT_INDETERMINE
    au_dessus = seuils["sens"] == nombres.SENS_AU_DESSUS
    for etat in (ETAT_CRITIQUE, ETAT_ATTENTION):
        borne: Decimal = seuils[etat]
        if (lue >= borne) if au_dessus else (lue <= borne):
            return etat
    return ETAT_NORMAL


_LIBELLE_FRAICHEUR = {
    fraicheur_mesures.STATUT_A_JOUR: "À jour",
    fraicheur_mesures.STATUT_NON_APPLICABLE: "Cumul de chantiers terminés",
    fraicheur_mesures.STATUT_PERIME: "PÉRIMÉE",
    fraicheur_mesures.STATUT_INCONNU: "Fraîcheur inconnue",
    fraicheur_mesures.STATUT_MANQUANT: "Non calculable",
}
_LIBELLE_SEUIL = {
    ETAT_NORMAL: "dans la cible",
    ETAT_ATTENTION: "à surveiller",
    ETAT_CRITIQUE: "critique",
    ETAT_INDETERMINE: "seuil non évalué",
    ETAT_SANS_SEUIL: "sans seuil",
}


def evaluer(
    definition: dict[str, Any],
    mesures: list[dict[str, Any]],
    *,
    maintenant: str,
    entrepot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """L'état d'un wallboard à l'instant ``maintenant`` : une tuile par mesure déclarée, la bannière d'alerte, la
    provenance. ``mesures`` est la sortie de ``fraicheur_mesures.lire_mesures_avec_fraicheur`` (chaque mesure porte sa
    ``fraicheur``). Lecture pure."""
    par_id = {mesure["metric_id"]: mesure for mesure in mesures}
    tuiles: list[dict[str, Any]] = []
    for tuile in definition["tuiles"]:
        mesure = par_id.get(tuile["mesure"])
        if mesure is None:  # garde : la validation exige la mesure au catalogue
            raise WallboardRefuse(REJ_WALLBOARD_INVALIDE, f"mesure absente de la lecture : {tuile['mesure']}")
        fraicheur = mesure["fraicheur"]
        fiable = fraicheur["peut_etre_montree_comme_a_jour"]
        etat_seuil = _etat_seuil(tuile["seuils"], mesure["valeur"], fiable)
        tuiles.append(
            {
                "id": tuile["id"],
                "titre": tuile["titre"],
                "page": tuile["page"],
                "metric_id": mesure["metric_id"],
                "nom": mesure["nom"],
                "unite": mesure["unite"],
                "valeur": mesure["valeur"],
                "valeur_affichee": formater_valeur(mesure["valeur"], mesure["unite"]),
                "statut_mesure": mesure["statut"],
                "detail": mesure["detail"],
                "fraicheur": fraicheur["statut"],
                "age_s": fraicheur["age_s"],
                "age_affiche": None
                if fraicheur["age_s"] is None
                else fraicheur_mesures.formater_duree(fraicheur["age_s"]),
                "fenetre_s": fraicheur["fenetre_s"],
                "motif_fraicheur": fraicheur["motif"],
                "perimee": fraicheur["statut"] == fraicheur_mesures.STATUT_PERIME,
                "a_jour": fiable and mesure["statut"] == entonnoir.STATUT_CALCULEE,
                "libelle_fraicheur": _LIBELLE_FRAICHEUR[fraicheur["statut"]],
                "etat_seuil": etat_seuil,
                "libelle_seuil": _LIBELLE_SEUIL[etat_seuil],
                "seuils": None
                if tuile["seuils"] is None
                else {"sens": tuile["seuils"]["sens"], **tuile["seuils"]["texte"]},
                "source": mesure["source"],
                "proprietaire": mesure["proprietaire"],
                "version_definition": mesure["version_definition"],
                "dernier_fait_le": mesure["dernier_fait_le"],
            }
        )
    return {
        "wallboard": resume(definition),
        "maintenant": maintenant,
        "tuiles": tuiles,
        "banniere": banniere(tuiles),
        "rotation": definition["rotation"],
        "rafraichissement": {"intervalle_s": definition["intervalle_s"], "flux_max": definition["flux_max"]},
        "entrepot": entrepot,
        "donnees_personnelles": False,
    }


def banniere(tuiles: list[dict[str, Any]]) -> dict[str, Any]:
    """La bannière d'alerte : ce qui est critique, ce qui est périmé ou de fraîcheur inconnue, ce qui est à surveiller.
    ``niveau`` vaut ``critique``, ``attention`` ou ``ok`` ; ``ok`` seulement si AUCUNE tuile n'est périmée, inconnue ou
    en alerte (un wallboard dont les données sont périmées n'affiche jamais un état « tout va bien »)."""
    critiques = [t["id"] for t in tuiles if t["etat_seuil"] == ETAT_CRITIQUE]
    attention = [t["id"] for t in tuiles if t["etat_seuil"] == ETAT_ATTENTION]
    perimees = [
        t["id"] for t in tuiles if t["fraicheur"] in (fraicheur_mesures.STATUT_PERIME, fraicheur_mesures.STATUT_INCONNU)
    ]
    manquantes = [t["id"] for t in tuiles if t["fraicheur"] == fraicheur_mesures.STATUT_MANQUANT]
    messages = []
    if critiques:
        messages.append(f"{len(critiques)} mesure(s) en état critique.")
    if attention:
        messages.append(f"{len(attention)} mesure(s) à surveiller.")
    if perimees:
        messages.append(f"{len(perimees)} mesure(s) périmée(s) ou de fraîcheur inconnue : ne pas s'y fier.")
    if manquantes:
        messages.append(f"{len(manquantes)} mesure(s) non calculable(s) (donnée manquante).")
    niveau = "critique" if critiques else "attention" if (attention or perimees) else "ok"
    if niveau == "ok" and manquantes:
        niveau = "attention"
    if not messages:
        messages.append("Toutes les mesures affichées sont à jour et dans leurs seuils.")
    return {
        "niveau": niveau,
        "messages": messages,
        "critiques": critiques,
        "a_surveiller": attention,
        "perimees": perimees,
        "non_calculables": manquantes,
    }


__all__ = [
    "ETAT_ATTENTION",
    "ETAT_CRITIQUE",
    "ETAT_INDETERMINE",
    "ETAT_NORMAL",
    "ETAT_SANS_SEUIL",
    "FLUX_MAX",
    "INTERVALLE_MAX_S",
    "INTERVALLE_MIN_S",
    "REJ_WALLBOARD_ILLISIBLE",
    "REJ_WALLBOARD_INCONNU",
    "REJ_WALLBOARD_INVALIDE",
    "REJ_WALLBOARD_ROLE",
    "SCHEMA",
    "WallboardRefuse",
    "banniere",
    "charger",
    "evaluer",
    "formater_valeur",
    "resume",
    "role_permis",
    "valider",
]
