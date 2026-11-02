"""Profil des équipes de l'entreprise : qui intervient, d'où l'on part, quand, et pour combien de temps (PLAN T4.12).

M4 (Field Ops) recopiait les équipes, le dépôt, les quarts et les durées à chaque cédule (limite de T4.1-d : « tout est
argument »). Ils sont maintenant DÉCLARÉS par l'entreprise, dans le même fichier que ses services et sa zone desservie :
`$OPSYS_HOME/entreprise.yaml`, clé `equipes` (même mécanisme que `opsys.taxonomie` : lu à la demande, écrit avec un nom
signé au journal d'audit). Le module est pur (fichier YAML et journal d'audit seulement) : il ne connaît pas M4.

Forme de la clé `equipes` (chaque sous-clé est facultative à la déclaration ; ce qui manque, M4 le dit au moment d'en
avoir besoin) ::

    equipes:
      liste:                          # les équipes ; l'id d'une équipe EST le technicien_id de son assignation
        - id: eq-repentigny
          membres: [alice, bruno]     # identifiants de PERSONNES OPSYS (opsys-metier personnes lister), rien d'autre
          competences: [service_a, service_b]
          depot: {id: depot-repentigny, latitude_microdegres: 45735000, longitude_microdegres: -73455000}
          quarts: [{jour: 0, debut_min: 480, fin_min: 1020}]     # jour : numéro de journée de la cédule
      services:                       # par code de service déclaré (`services`), durée et compétences requises
        service_a: {duree_min: 90, competences: [service_a]}
      cedule:                         # réglages de la cédule par tournées, tous obligatoires (graine facultative)
        {facteur_detour_milliemes: 1300, vitesse_moyenne_kmh: 50, marge_par_trajet_secondes: 600,
         iterations: 500, cout_non_cedule_m: 500000,
         multijours: {visite_max_minutes: 480, jours_consecutifs: false}}   # multijours : facultatif, voir plus bas
      fenetre_par_defaut:             # fenêtre offerte à un chantier dont le client n'en a donné aucune
        {jours: [0], debut_min: 480, fin_min: 1020}

Chantiers de PLUSIEURS JOURS (P4-02), ``cedule.multijours`` facultatif : ``visite_max_minutes`` (durée maximale d'une
visite, une journée de travail de l'équipe : un chantier plus long se découpe en visites presque égales) et
``jours_consecutifs`` (les visites tombent-elles sur des jours d'activité consécutifs ?). Les deux sont obligatoires dès
que le bloc existe ; sans le bloc, M4 ne cédule pas un chantier plus long qu'un quart et dit quoi déclarer. Un
chantier découpé reste confié à UNE équipe (l'assignation et la date civile sont par intervention). Ce ne sont pas des
valeurs d'OPSYS : c'est une décision de l'entreprise.

Capacité des semaines futures (DECISIONS-ARCHITECTE-r1 §3, effectif planifié : r3), cinq ajouts FACULTATIFS : un profil
qui ne les porte pas reste valide et se lit, s'écrit et s'empreinte exactement comme avant ::

    equipes:
      liste:
        - id: eq-repentigny
          ...
          semaine_type:                 # quarts par JOUR DE SEMAINE, heures locales (texte "HH:MM", entre guillemets)
            fuseau: America/Montreal    # obligatoire ; le seul fuseau admis
            lundi: [{debut: "07:00", fin: "12:00"}, {debut: "12:30", fin: "15:30"}]  # plages sans chevauchement
            samedi: []                  # jour FERMÉ : zéro déclaré ; fin "24:00" admise
            # un jour absent n'est pas fermé : il est INCONNU (M4 ne calcule pas la semaine)
          effectif_planifie: 2          # personnes PRÉVUES par jour de quart (entier 1 à 50) : capacité prévisionnelle
                                        # déclarée, jamais une présence constatée ; ni lue ni déduite de `membres`
      conges:                         # congés/absences planifiés au niveau de l'ÉQUIPE (jamais d'une personne)
        - {equipes: [eq-repentigny], du: "2030-07-22", au: "2030-08-02", motif: conge, libelle: "texte libre"}
      feries:                         # jours fériés DÉCLARÉS (aucune liste n'est fournie par OPSYS)
        annees: [2030]                # années dont la liste ci-dessous est COMPLÈTE
        jours: [{date: "2030-06-24", libelle: "texte libre"}]
      duree_jour_personne_minutes: 480   # conversion explicite heures déclarées -> jours-personnes, jamais supposée

`motif` est fermé (`conge`, `ferie`, `formation`, `autre`) ; `libelle` est un texte libre facultatif, gardé au profil,
jamais recopié dans une sortie de M4 ni au journal d'audit. Un férié s'applique à toutes les équipes ; un congé aux
équipes qu'il nomme, qui doivent être déclarées dans `liste`. Aucune de ces données ne décrit une personne.

`effectif_planifie` (DECISIONS-ARCHITECTE-r3) est un NOMBRE PRÉVU que le propriétaire déclare pour l'équipe, pas une
liste de personnes ni un compte de ses `membres` : une équipe de trois membres peut planifier deux personnes par quart,
et un membre déclaré n'est pas présent pour autant (déclaration d'équipe ≠ présence individuelle). Aucun code ne le
déduit des membres, des pointages ni des absences ; absent, il n'est jamais supposé (M4 dit qu'il n'est pas déclaré).

Ce que le profil n'est pas : aucune donnée de ressources humaines ni de santé, aucune évaluation, aucun classement
d'employé (DEFINITION-PRODUIT M4, garde-fous humains). Un membre est un identifiant de personne OPSYS, pas une fiche.
Une compétence est un code que le propriétaire choisit (« service_a »), pas une certification d'employé.

Fail-closed (AGENTS.md) : sans profil, aucune équipe, aucun dépôt, aucun quart ni aucune durée n'est inventé ; le
verdict dit quoi déclarer et comment. Un profil invalide n'est jamais lu comme absent (`REJ-PROFIL-INVALIDE`). La
déclaration REMPLACE la clé entière : pour modifier, `opsys-metier equipes lister`, éditer, puis redéclarer.

Les bornes des réglages de la cédule (détour, vitesse, marge, itérations, coût) sont celles du solveur : M4 les vérifie
au moment de s'en servir et son verdict les cite ; ce module n'exige que des entiers du bon signe.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable, Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

from . import identite
from .taxonomie import (
    _FORME_CODE,
    VERDICT_PROFIL_INVALIDE,
    ProfilInvalide,
    _ecrire_cle_du_profil,
    _valeur_du_profil,
    _valider_code,
    _verdict,
    fichier_profil,
)

CLE_EQUIPES = "equipes"
CLE_LISTE = "liste"
CLE_SERVICES_EQUIPES = "services"
CLE_CEDULE = "cedule"
CLE_FENETRE_PAR_DEFAUT = "fenetre_par_defaut"
CLES_PROFIL = (CLE_LISTE, CLE_SERVICES_EQUIPES, CLE_CEDULE, CLE_FENETRE_PAR_DEFAUT)
# Capacité des semaines futures (facultatif ; absent = comportement d'avant, empreinte comprise)
CLE_CONGES = "conges"
CLE_FERIES = "feries"
CLE_DUREE_JOUR_PERSONNE = "duree_jour_personne_minutes"
CLES_PROFIL_CAPACITE = (CLE_CONGES, CLE_FERIES, CLE_DUREE_JOUR_PERSONNE)
_CLES_ADMISES = CLES_PROFIL + CLES_PROFIL_CAPACITE

CLES_EQUIPE = ("id", "membres", "competences", "depot", "quarts")
CLE_SEMAINE_TYPE = "semaine_type"
CLE_EFFECTIF_PLANIFIE = "effectif_planifie"
CLES_EQUIPE_OPTIONNELLES = (CLE_SEMAINE_TYPE, CLE_EFFECTIF_PLANIFIE)
JOURS_SEMAINE = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")  # index = date.weekday()
FUSEAU_SEMAINE_TYPE = "America/Montreal"
CLES_PLAGE = ("debut", "fin")
CLES_CONGE = ("equipes", "du", "au", "motif")
CLES_CONGE_OPTIONNELLES = ("libelle",)
MOTIFS_CONGE = ("conge", "ferie", "formation", "autre")
CLES_FERIES = ("annees", "jours")
CLES_JOUR_FERIE = ("date",)
CLES_JOUR_FERIE_OPTIONNELLES = ("libelle",)
CLES_DEPOT = ("id", "latitude_microdegres", "longitude_microdegres")
CLES_QUART = ("jour", "debut_min", "fin_min")
CLES_SERVICE = ("duree_min", "competences")
CLES_CEDULE_REQUISES = (
    "facteur_detour_milliemes", "vitesse_moyenne_kmh", "marge_par_trajet_secondes", "iterations", "cout_non_cedule_m",
)
CLE_MULTIJOURS = "multijours"
CLES_MULTIJOURS = ("visite_max_minutes", "jours_consecutifs")
CLES_CEDULE_OPTIONNELLES = ("graine", CLE_MULTIJOURS)
CLES_FENETRE = ("jours", "debut_min", "fin_min")

VERDICT_EQUIPES_NON_CONFIGUREES = "REJ-EQUIPES-NON-CONFIGUREES"

MINUTES_PAR_JOUR = 1440
JOUR_MAX = 9999
GRAINE_MAX = 2**32 - 1
_EQUIPES_MAX = 100
_MEMBRES_MAX = 50
EFFECTIF_PLANIFIE_MAX = 50  # borne raisonnable d'une équipe de chantier ; indépendante du nombre de membres
_COMPETENCES_MAX = 50
_SERVICES_MAX = 100
_QUARTS_MAX = 400
_JOURS_MAX = 400
_LATITUDE_MAX = 90_000_000
_LONGITUDE_MAX = 180_000_000
_PLAGES_PAR_JOUR_MAX = 8
_CONGES_MAX = 500
_CONGE_JOURS_MAX = 366
_FERIES_ANNEES_MAX = 50
_FERIES_JOURS_MAX = 50 * 30
_LIBELLE_MAX = 120
_ANNEE_MIN, _ANNEE_MAX = 1900, 2199  # mêmes bornes que les dates civiles de M4
_HEURE = re.compile(r"([01][0-9]|2[0-3]):([0-5][0-9])|24:00")
_CONTROLE = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")


# ---------------------------------------------------------------------------
# Validation : une seule règle par champ, un message qui dit quoi corriger
# ---------------------------------------------------------------------------
def _entier(valeur: Any, chemin: str, minimum: int, maximum: int | None = None) -> int:
    if isinstance(valeur, bool) or not isinstance(valeur, int):
        raise ProfilInvalide(f"{chemin} : un entier est attendu (reçu {valeur!r})")
    if valeur < minimum or (maximum is not None and valeur > maximum):
        borne = f"au moins {minimum}" if maximum is None else f"entre {minimum} et {maximum}"
        raise ProfilInvalide(f"{chemin} : {borne} (reçu {valeur})")
    return valeur


def _objet(valeur: Any, chemin: str, requises: tuple[str, ...], optionnelles: tuple[str, ...] = ()) -> Mapping:
    if not isinstance(valeur, Mapping):
        raise ProfilInvalide(f"{chemin} : un objet est attendu ({', '.join(requises)})")
    inconnues = sorted(str(cle) for cle in set(valeur) - set(requises) - set(optionnelles))
    if inconnues:
        raise ProfilInvalide(f"{chemin} : clés inconnues {inconnues} (attendu : {', '.join(requises + optionnelles)})")
    manquantes = [cle for cle in requises if cle not in valeur]
    if manquantes:
        raise ProfilInvalide(f"{chemin} : clés manquantes {manquantes}")
    return valeur


def _liste(valeur: Any, chemin: str, maximum: int, *, non_vide: bool) -> list[Any]:
    if isinstance(valeur, (str, bytes, Mapping)) or not isinstance(valeur, Iterable):
        raise ProfilInvalide(f"{chemin} : une liste est attendue")
    elements = list(valeur)
    if non_vide and not elements:
        raise ProfilInvalide(f"{chemin} est vide : déclare au moins un élément")
    if len(elements) > maximum:
        raise ProfilInvalide(f"{chemin} : {maximum} éléments au plus (reçu {len(elements)})")
    return elements


def _forme_code(valeur: object) -> bool:
    return isinstance(valeur, str) and _FORME_CODE.match(valeur) is not None


def _textes(
    valeur: Any, chemin: str, valide: Callable[[object], bool], maximum: int, *, non_vide: bool, decrire: str,
) -> list[str]:
    """Liste triée de textes qui passent `valide`, sans doublon."""
    elements = _liste(valeur, chemin, maximum, non_vide=non_vide)
    for position, element in enumerate(elements):
        if not valide(element):
            raise ProfilInvalide(f"{chemin}[{position}] : {decrire} (reçu {element!r})")
    doublons = sorted({e for e in elements if elements.count(e) > 1})
    if doublons:
        raise ProfilInvalide(f"{chemin} : éléments en double {doublons}")
    return sorted(elements)


def _identifiant(valeur: Any, chemin: str, decrire: str) -> str:
    # Même règle que les personnes OPSYS : l'id d'une équipe est aussi un technicien_id.
    if not identite.identifiant_valide(valeur):
        raise ProfilInvalide(
            f"{chemin} : {decrire} (minuscules, chiffres, '.', '_', '-', commence par une lettre, 2 à 64 caractères ; "
            f"reçu {valeur!r})"
        )
    return valeur


def _normaliser_depot(brut: Any, chemin: str) -> dict[str, Any]:
    objet = _objet(brut, chemin, CLES_DEPOT)
    return {
        "id": _identifiant(objet["id"], f"{chemin}.id", "identifiant du dépôt"),
        "latitude_microdegres": _entier(
            objet["latitude_microdegres"], f"{chemin}.latitude_microdegres", -_LATITUDE_MAX, _LATITUDE_MAX),
        "longitude_microdegres": _entier(
            objet["longitude_microdegres"], f"{chemin}.longitude_microdegres", -_LONGITUDE_MAX, _LONGITUDE_MAX),
    }


def _plage(objet: Mapping, chemin: str) -> tuple[int, int]:
    debut = _entier(objet["debut_min"], f"{chemin}.debut_min", 0, MINUTES_PAR_JOUR - 1)
    fin = _entier(objet["fin_min"], f"{chemin}.fin_min", 1, MINUTES_PAR_JOUR)
    if debut >= fin:
        raise ProfilInvalide(f"{chemin} : debut_min ({debut}) doit précéder fin_min ({fin})")
    return debut, fin


def _normaliser_quarts(brut: Any, chemin: str) -> list[dict[str, int]]:
    quarts: dict[int, dict[str, int]] = {}
    for position, quart in enumerate(_liste(brut, chemin, _QUARTS_MAX, non_vide=True)):
        cible = f"{chemin}[{position}]"
        objet = _objet(quart, cible, CLES_QUART)
        jour = _entier(objet["jour"], f"{cible}.jour", 0, JOUR_MAX)
        if jour in quarts:
            raise ProfilInvalide(f"{cible} : deux quarts le jour {jour}")
        debut, fin = _plage(objet, cible)
        quarts[jour] = {"jour": jour, "debut_min": debut, "fin_min": fin}
    return [quarts[jour] for jour in sorted(quarts)]


def _minute_de(valeur: Any, chemin: str) -> int:
    if not isinstance(valeur, str):
        raise ProfilInvalide(
            f"{chemin} : une heure locale \"HH:MM\" en texte est attendue, ENTRE GUILLEMETS dans le YAML (reçu "
            f"{valeur!r} ; sans guillemets, YAML lit 12:30 comme le nombre 750)"
        )
    if _HEURE.fullmatch(valeur) is None:
        raise ProfilInvalide(f"{chemin} : heure \"HH:MM\" de 00:00 à 23:59, ou 24:00 en fin de plage (reçu {valeur!r})")
    heures, minutes = valeur.split(":")
    return int(heures) * 60 + int(minutes)


def _normaliser_plages(brut: Any, chemin: str) -> list[dict[str, str]]:
    """Plages d'un jour de semaine, triées ; `[]` = jour FERMÉ (zéro déclaré). Refuse le chevauchement."""
    plages: list[tuple[int, int, dict[str, str]]] = []
    for position, plage in enumerate(_liste(brut, chemin, _PLAGES_PAR_JOUR_MAX, non_vide=False)):
        cible = f"{chemin}[{position}]"
        objet = _objet(plage, cible, CLES_PLAGE)
        debut, fin = _minute_de(objet["debut"], f"{cible}.debut"), _minute_de(objet["fin"], f"{cible}.fin")
        if debut == MINUTES_PAR_JOUR:
            raise ProfilInvalide(f"{cible}.debut : 24:00 n'est admis qu'en fin de plage")
        if debut >= fin:
            raise ProfilInvalide(f"{cible} : debut ({objet['debut']}) doit précéder fin ({objet['fin']}) le même jour")
        plages.append((debut, fin, {"debut": objet["debut"], "fin": objet["fin"]}))
    plages.sort(key=lambda plage: (plage[0], plage[1]))
    for avant, apres in zip(plages, plages[1:], strict=False):
        if apres[0] < avant[1]:
            raise ProfilInvalide(
                f"{chemin} : les plages {avant[2]['debut']}-{avant[2]['fin']} et {apres[2]['debut']}-{apres[2]['fin']} "
                "se chevauchent"
            )
    return [plage[2] for plage in plages]


def _normaliser_semaine_type(brut: Any, chemin: str) -> dict[str, Any]:
    """Semaine type d'une équipe : `fuseau` (America/Montreal seulement) et, par jour de semaine nommé, ses plages.
    Un jour absent reste INCONNU (jamais lu comme fermé) : M4 le dit au lieu de calculer."""
    objet = _objet(brut, chemin, ("fuseau",), JOURS_SEMAINE)
    if objet["fuseau"] != FUSEAU_SEMAINE_TYPE:
        raise ProfilInvalide(
            f"{chemin}.fuseau : seul {FUSEAU_SEMAINE_TYPE!r} est admis (heures locales du Québec ; reçu "
            f"{objet['fuseau']!r})"
        )
    propre: dict[str, Any] = {"fuseau": FUSEAU_SEMAINE_TYPE}
    for jour in JOURS_SEMAINE:
        if jour in objet:
            propre[jour] = _normaliser_plages(objet[jour], f"{chemin}.{jour}")
    if len(propre) == 1:
        raise ProfilInvalide(f"{chemin} : déclare au moins un jour ({', '.join(JOURS_SEMAINE)}) ; [] = jour fermé")
    return propre


def _normaliser_equipe(brut: Any, chemin: str) -> dict[str, Any]:
    objet = _objet(brut, chemin, CLES_EQUIPE, CLES_EQUIPE_OPTIONNELLES)
    propre = {
        "id": _identifiant(objet["id"], f"{chemin}.id", "identifiant d'équipe"),
        "membres": _textes(
            objet["membres"], f"{chemin}.membres", identite.identifiant_valide, _MEMBRES_MAX, non_vide=True,
            decrire="un membre est l'identifiant d'une personne OPSYS",
        ),
        "competences": _textes(
            objet["competences"], f"{chemin}.competences", _forme_code, _COMPETENCES_MAX, non_vide=False,
            decrire="une compétence est un code (minuscules, chiffres et _, commence par une lettre)",
        ),
        "depot": _normaliser_depot(objet["depot"], f"{chemin}.depot"),
        "quarts": _normaliser_quarts(objet["quarts"], f"{chemin}.quarts"),
    }
    if CLE_SEMAINE_TYPE in objet:
        propre[CLE_SEMAINE_TYPE] = _normaliser_semaine_type(objet[CLE_SEMAINE_TYPE], f"{chemin}.{CLE_SEMAINE_TYPE}")
    if CLE_EFFECTIF_PLANIFIE in objet:
        # Déclaré tel quel, jamais comparé ni ramené au nombre de `membres` : c'est une prévision, pas une présence.
        propre[CLE_EFFECTIF_PLANIFIE] = _entier(
            objet[CLE_EFFECTIF_PLANIFIE], f"{chemin}.{CLE_EFFECTIF_PLANIFIE}", 1, EFFECTIF_PLANIFIE_MAX)
    return propre


def _normaliser_liste(brut: Any) -> list[dict[str, Any]]:
    chemin = f"{CLE_EQUIPES}.{CLE_LISTE}"
    equipes = [
        _normaliser_equipe(equipe, f"{chemin}[{position}]")
        for position, equipe in enumerate(_liste(brut, chemin, _EQUIPES_MAX, non_vide=True))
    ]
    identifiants = [equipe["id"] for equipe in equipes]
    doublons = sorted({i for i in identifiants if identifiants.count(i) > 1})
    if doublons:
        raise ProfilInvalide(f"{chemin} : équipes déclarées en double {doublons}")
    equipe_de: dict[str, str] = {}
    for equipe in equipes:
        for membre in equipe["membres"]:
            if membre in equipe_de:
                raise ProfilInvalide(
                    f"{chemin} : {membre!r} est membre de deux équipes ({equipe_de[membre]!r} et {equipe['id']!r}) ; "
                    "une personne ne fait partie que d'une équipe : les quarts d'une équipe la rendent indisponible "
                    "aux autres"
                )
            equipe_de[membre] = equipe["id"]
    for equipe in equipes:
        proprietaire = equipe_de.get(equipe["id"])
        if proprietaire is not None and proprietaire != equipe["id"]:
            raise ProfilInvalide(
                f"{chemin} : l'identifiant de l'équipe {equipe['id']!r} est celui d'une personne qui est membre de "
                f"l'équipe {proprietaire!r} ; l'identifiant d'une équipe sert de technicien_id : cette personne "
                "verrait les chantiers d'une autre équipe"
            )
    depots: dict[str, dict[str, Any]] = {}
    for equipe in equipes:
        depot = equipe["depot"]
        if depots.setdefault(depot["id"], depot) != depot:
            raise ProfilInvalide(f"{chemin} : le dépôt {depot['id']!r} a deux positions différentes")
    return sorted(equipes, key=lambda equipe: equipe["id"])


def _normaliser_services(brut: Any) -> dict[str, dict[str, Any]]:
    chemin = f"{CLE_EQUIPES}.{CLE_SERVICES_EQUIPES}"
    if not isinstance(brut, Mapping):
        raise ProfilInvalide(f"'{chemin}' doit être un objet {{code_du_service: {{duree_min, competences}}}}")
    if not brut:
        raise ProfilInvalide(f"'{chemin}' est vide : déclare au moins un service")
    if len(brut) > _SERVICES_MAX:
        raise ProfilInvalide(f"'{chemin}' : {_SERVICES_MAX} services au plus")
    services: dict[str, dict[str, Any]] = {}
    for code, entree in brut.items():
        cible = f"{chemin}[{code!r}]"
        _valider_code(code, cible)
        objet = _objet(entree, cible, CLES_SERVICE)
        services[code] = {
            "duree_min": _entier(objet["duree_min"], f"{cible}.duree_min", 1, MINUTES_PAR_JOUR),
            "competences": _textes(
                objet["competences"], f"{cible}.competences", _forme_code, _COMPETENCES_MAX, non_vide=False,
                decrire="une compétence est un code (minuscules, chiffres et _, commence par une lettre)",
            ),
        }
    return {code: services[code] for code in sorted(services)}


def _normaliser_cedule(brut: Any) -> dict[str, int]:
    chemin = f"{CLE_EQUIPES}.{CLE_CEDULE}"
    objet = _objet(brut, chemin, CLES_CEDULE_REQUISES, CLES_CEDULE_OPTIONNELLES)
    reglages = {
        "facteur_detour_milliemes": _entier(objet["facteur_detour_milliemes"], f"{chemin}.facteur_detour_milliemes", 1),
        "vitesse_moyenne_kmh": _entier(objet["vitesse_moyenne_kmh"], f"{chemin}.vitesse_moyenne_kmh", 1),
        "marge_par_trajet_secondes": _entier(
            objet["marge_par_trajet_secondes"], f"{chemin}.marge_par_trajet_secondes", 0),
        "iterations": _entier(objet["iterations"], f"{chemin}.iterations", 1),
        "cout_non_cedule_m": _entier(objet["cout_non_cedule_m"], f"{chemin}.cout_non_cedule_m", 1),
    }
    if "graine" in objet:
        reglages["graine"] = _entier(objet["graine"], f"{chemin}.graine", 0, GRAINE_MAX)
    if CLE_MULTIJOURS in objet:
        reglages[CLE_MULTIJOURS] = _normaliser_multijours(objet[CLE_MULTIJOURS], f"{chemin}.{CLE_MULTIJOURS}")
    return reglages


def _normaliser_multijours(brut: Any, chemin: str) -> dict[str, Any]:
    """Règles des chantiers de PLUSIEURS JOURS (P4-02), facultatives : sans elles, un chantier plus long qu'une
    journée n'est pas cédulé et M4 le dit. Les deux clés sont obligatoires dès que le bloc existe : aucune valeur par
    défaut n'est jamais supposée (c'est une décision de l'entreprise)."""
    objet = _objet(brut, chemin, CLES_MULTIJOURS)
    consecutifs = objet["jours_consecutifs"]
    if not isinstance(consecutifs, bool):
        raise ProfilInvalide(f"{chemin}.jours_consecutifs : un booléen est attendu (reçu {consecutifs!r})")
    return {
        "visite_max_minutes": _entier(objet["visite_max_minutes"], f"{chemin}.visite_max_minutes", 1, MINUTES_PAR_JOUR),
        "jours_consecutifs": consecutifs,
    }


def _normaliser_fenetre(brut: Any) -> dict[str, Any]:
    chemin = f"{CLE_EQUIPES}.{CLE_FENETRE_PAR_DEFAUT}"
    objet = _objet(brut, chemin, CLES_FENETRE)
    jours = [
        _entier(jour, f"{chemin}.jours[{position}]", 0, JOUR_MAX)
        for position, jour in enumerate(_liste(objet["jours"], f"{chemin}.jours", _JOURS_MAX, non_vide=True))
    ]
    if len(set(jours)) != len(jours):
        raise ProfilInvalide(f"{chemin}.jours : jours en double")
    debut, fin = _plage(objet, chemin)
    return {"jours": sorted(jours), "debut_min": debut, "fin_min": fin}


def _date_civile(valeur: Any, chemin: str) -> date:
    """Date civile : texte AAAA-MM-JJ (ou date YAML non guillemetée), jamais un instant ; rendue en texte ISO."""
    if isinstance(valeur, date) and not isinstance(valeur, datetime):
        jour = valeur
    elif isinstance(valeur, str):
        try:
            jour = date.fromisoformat(valeur)
        except ValueError:
            jour = None
        if jour is None or jour.isoformat() != valeur:
            raise ProfilInvalide(f"{chemin} : date AAAA-MM-JJ attendue (reçu {valeur!r})")
    else:
        raise ProfilInvalide(f"{chemin} : date AAAA-MM-JJ attendue (reçu {valeur!r})")
    if not _ANNEE_MIN <= jour.year <= _ANNEE_MAX:
        raise ProfilInvalide(f"{chemin} : année entre {_ANNEE_MIN} et {_ANNEE_MAX} (reçu {jour.year})")
    return jour


def _libelle(valeur: Any, chemin: str) -> str:
    """Texte libre du propriétaire : borné, sans caractère de contrôle. Gardé au profil, jamais recopié par M4."""
    if not isinstance(valeur, str) or not valeur.strip() or len(valeur) > _LIBELLE_MAX or _CONTROLE.search(valeur):
        raise ProfilInvalide(
            f"{chemin} : texte d'une ligne, 1 à {_LIBELLE_MAX} caractères, sans caractère de contrôle"
        )
    return valeur


def _normaliser_conges(brut: Any, equipes_declarees: set[str] | None) -> list[dict[str, Any]]:
    chemin = f"{CLE_EQUIPES}.{CLE_CONGES}"
    if equipes_declarees is None:
        raise ProfilInvalide(f"{chemin} : un congé nomme des équipes ; déclare d'abord {CLE_EQUIPES}.{CLE_LISTE}")
    conges: list[dict[str, Any]] = []
    for position, conge in enumerate(_liste(brut, chemin, _CONGES_MAX, non_vide=True)):
        cible = f"{chemin}[{position}]"
        objet = _objet(conge, cible, CLES_CONGE, CLES_CONGE_OPTIONNELLES)
        nommees = _textes(
            objet["equipes"], f"{cible}.equipes", identite.identifiant_valide, _EQUIPES_MAX, non_vide=True,
            decrire="identifiant d'une équipe déclarée",
        )
        inconnues = sorted(set(nommees) - equipes_declarees)
        if inconnues:
            raise ProfilInvalide(f"{cible}.equipes : équipes non déclarées dans {CLE_EQUIPES}.{CLE_LISTE} {inconnues}")
        du, au = _date_civile(objet["du"], f"{cible}.du"), _date_civile(objet["au"], f"{cible}.au")
        if au < du:
            raise ProfilInvalide(f"{cible} : au ({au.isoformat()}) précède du ({du.isoformat()})")
        if (au - du).days + 1 > _CONGE_JOURS_MAX:
            raise ProfilInvalide(f"{cible} : {_CONGE_JOURS_MAX} jours au plus par congé (découpe la plage)")
        if objet["motif"] not in MOTIFS_CONGE:
            raise ProfilInvalide(f"{cible}.motif : un de {', '.join(MOTIFS_CONGE)} (reçu {objet['motif']!r})")
        propre = {"equipes": nommees, "du": du.isoformat(), "au": au.isoformat(), "motif": objet["motif"]}
        if "libelle" in objet:
            propre["libelle"] = _libelle(objet["libelle"], f"{cible}.libelle")
        conges.append(propre)
    canon = sorted(conges, key=lambda c: (c["du"], c["au"], c["equipes"], c["motif"], c.get("libelle", "")))
    if any(avant == apres for avant, apres in zip(canon, canon[1:], strict=False)):
        raise ProfilInvalide(f"{chemin} : congé déclaré en double")
    return canon


def _normaliser_feries(brut: Any) -> dict[str, Any]:
    chemin = f"{CLE_EQUIPES}.{CLE_FERIES}"
    objet = _objet(brut, chemin, CLES_FERIES)
    brutes = _liste(objet["annees"], f"{chemin}.annees", _FERIES_ANNEES_MAX, non_vide=True)
    annees = [
        _entier(annee, f"{chemin}.annees[{position}]", _ANNEE_MIN, _ANNEE_MAX) for position, annee in enumerate(brutes)
    ]
    if len(set(annees)) != len(annees):
        raise ProfilInvalide(f"{chemin}.annees : années en double")
    jours: dict[str, dict[str, str]] = {}
    for position, jour in enumerate(_liste(objet["jours"], f"{chemin}.jours", _FERIES_JOURS_MAX, non_vide=False)):
        cible = f"{chemin}.jours[{position}]"
        entree = _objet(jour, cible, CLES_JOUR_FERIE, CLES_JOUR_FERIE_OPTIONNELLES)
        civil = _date_civile(entree["date"], f"{cible}.date")
        if civil.year not in annees:
            raise ProfilInvalide(
                f"{cible}.date : {civil.isoformat()} hors des années déclarées complètes {sorted(annees)} ; "
                f"ajoute {civil.year} à {chemin}.annees"
            )
        if civil.isoformat() in jours:
            raise ProfilInvalide(f"{cible}.date : {civil.isoformat()} déclaré deux fois")
        propre = {"date": civil.isoformat()}
        if "libelle" in entree:
            propre["libelle"] = _libelle(entree["libelle"], f"{cible}.libelle")
        jours[civil.isoformat()] = propre
    return {"annees": sorted(annees), "jours": [jours[cle] for cle in sorted(jours)]}


def normaliser_equipes(brut: Any) -> dict[str, Any]:
    """Valide une déclaration d'équipes et la rend CANONIQUE (équipes, membres, compétences, quarts et services triés ;
    listes et dictionnaires simples, sérialisables en YAML). Refuse la déclaration vide, la clé inconnue, l'équipe sans
    membre, dépôt, quart ou compétence bien formée, le doublon, la personne dans deux équipes : une déclaration vide
    n'est pas un profil, et rien n'est jamais arrondi ni deviné."""
    if not isinstance(brut, Mapping):
        raise ProfilInvalide(f"'{CLE_EQUIPES}' doit être un objet (clés : {', '.join(CLES_PROFIL)})")
    if not brut:
        raise ProfilInvalide(f"'{CLE_EQUIPES}' est vide : déclare au moins une des clés {', '.join(CLES_PROFIL)}")
    inconnues = sorted(str(cle) for cle in set(brut) - set(_CLES_ADMISES))
    if inconnues:
        raise ProfilInvalide(f"'{CLE_EQUIPES}' : clés inconnues {inconnues} (attendu : {', '.join(_CLES_ADMISES)})")
    propre: dict[str, Any] = {}
    if CLE_LISTE in brut:
        propre[CLE_LISTE] = _normaliser_liste(brut[CLE_LISTE])
    if CLE_SERVICES_EQUIPES in brut:
        propre[CLE_SERVICES_EQUIPES] = _normaliser_services(brut[CLE_SERVICES_EQUIPES])
    if CLE_CEDULE in brut:
        propre[CLE_CEDULE] = _normaliser_cedule(brut[CLE_CEDULE])
    if CLE_FENETRE_PAR_DEFAUT in brut:
        propre[CLE_FENETRE_PAR_DEFAUT] = _normaliser_fenetre(brut[CLE_FENETRE_PAR_DEFAUT])
    if CLE_CONGES in brut:
        declarees = {equipe["id"] for equipe in propre[CLE_LISTE]} if CLE_LISTE in propre else None
        propre[CLE_CONGES] = _normaliser_conges(brut[CLE_CONGES], declarees)
    if CLE_FERIES in brut:
        propre[CLE_FERIES] = _normaliser_feries(brut[CLE_FERIES])
    if CLE_DUREE_JOUR_PERSONNE in brut:
        propre[CLE_DUREE_JOUR_PERSONNE] = _entier(
            brut[CLE_DUREE_JOUR_PERSONNE], f"{CLE_EQUIPES}.{CLE_DUREE_JOUR_PERSONNE}", 1, MINUTES_PAR_JOUR)
    return propre


# ---------------------------------------------------------------------------
# Lecture, écriture signée, empreinte
# ---------------------------------------------------------------------------
def lire_equipes(chemin: Path | None = None) -> dict[str, Any] | None:
    """Profil canonique déclaré par l'instance ; `None` si le fichier ou la clé est absent ou vide.

    Lève `ProfilInvalide` si la clé existe mais ne respecte pas le schéma (même règle que la zone : une valeur cassée
    n'est jamais lue comme absente)."""
    fichier = chemin or fichier_profil()
    valeur = _valeur_du_profil(CLE_EQUIPES, fichier)
    if valeur is None or valeur == {}:
        return None
    try:
        return normaliser_equipes(valeur)
    except ProfilInvalide as exc:
        raise ProfilInvalide(f"{fichier} : {exc}") from exc


def _consigne_declaration(chemin: Path) -> str:
    return (
        "déclare les équipes de l'entreprise : écris un fichier YAML (clés "
        f"{', '.join(CLES_PROFIL)}) puis `opsys-metier equipes declarer --depuis <fichier> --par <ton nom>` ; "
        f"le profil est écrit dans {chemin} (clé '{CLE_EQUIPES}'), voir docs/architecture/TAXONOMIE.md"
    )


def charger_equipes() -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """`(profil, None)` si l'instance déclare ses équipes, sinon `(None, verdict)` qui dit quoi déclarer et comment.

    Ne lève jamais : un profil illisible ou invalide est un verdict `REJ-PROFIL-INVALIDE`, distinct de l'absence
    (`REJ-EQUIPES-NON-CONFIGUREES`), que l'appelant ne confond jamais avec un profil vide. Le profil rendu peut être
    partiel : ce qu'il ne dit pas, `a_declarer` le liste."""
    chemin = fichier_profil()
    try:
        profil = lire_equipes(chemin)
    except ProfilInvalide as exc:
        return None, _verdict(VERDICT_PROFIL_INVALIDE, f"profil d'entreprise invalide : {exc}")
    if profil is None:
        return None, _verdict(
            VERDICT_EQUIPES_NON_CONFIGUREES,
            f"aucun profil des équipes déclaré pour cette entreprise : {_consigne_declaration(chemin)} ; "
            "aucune équipe, aucun dépôt, aucun quart et aucune durée n'est jamais inventé",
        )
    return profil, None


def empreinte_equipes(profil: Mapping[str, Any]) -> str:
    """SHA-256 du profil canonique : ce qu'une cédule proposée a lu, pour refuser de l'appliquer s'il a changé."""
    octets = json.dumps(profil, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(octets).hexdigest()


def enregistrer_equipes(profil: Any, chemin: Path | None = None, par: str | None = None) -> Path:
    """Écrit le profil validé (remplace la clé `equipes`), sans toucher aux autres clés du fichier.

    Signé par `par`, le changement est inscrit au journal d'audit : les identifiants d'équipe, le nombre de membres de
    chacune, les services et l'empreinte du profil, jamais le nom d'un membre."""
    propre = normaliser_equipes(profil)
    equipes = propre.get(CLE_LISTE, [])
    details: dict[str, Any] = {
        "equipes": [equipe["id"] for equipe in equipes],
        "membres_par_equipe": {equipe["id"]: len(equipe["membres"]) for equipe in equipes},
        "services": sorted(propre.get(CLE_SERVICES_EQUIPES, {})),
        "cedule_declaree": CLE_CEDULE in propre,
        "empreinte": empreinte_equipes(propre),
    }
    # Capacité (facultatif) : écrit seulement si déclaré, pour qu'un profil d'avant garde un journal identique.
    # Ni libellé de congé ou de férié, ni date : des comptes et des identifiants d'équipe.
    semaine_type = [equipe["id"] for equipe in equipes if CLE_SEMAINE_TYPE in equipe]
    if semaine_type:
        details["semaine_type_equipes"] = semaine_type
    effectifs = {equipe["id"]: equipe[CLE_EFFECTIF_PLANIFIE] for equipe in equipes if CLE_EFFECTIF_PLANIFIE in equipe}
    if effectifs:
        details["effectif_planifie_par_equipe"] = effectifs
    if CLE_CONGES in propre:
        details["conges_declares"] = len(propre[CLE_CONGES])
    if CLE_FERIES in propre:
        details["feries_annees"] = list(propre[CLE_FERIES]["annees"])
        details["feries_declares"] = len(propre[CLE_FERIES]["jours"])
    if CLE_DUREE_JOUR_PERSONNE in propre:
        details[CLE_DUREE_JOUR_PERSONNE] = propre[CLE_DUREE_JOUR_PERSONNE]
    return _ecrire_cle_du_profil(CLE_EQUIPES, propre, chemin, par, "entreprise.equipes", details)


# ---------------------------------------------------------------------------
# Ce que le profil dit, et ce qui lui manque
# ---------------------------------------------------------------------------
def equipes_de(profil: Mapping[str, Any] | None, personne: str) -> tuple[str, ...]:
    """Identifiants des équipes dont `personne` est membre (`()` sans profil) : lu dans le profil, jamais deviné."""
    if not isinstance(profil, Mapping):
        return ()
    return tuple(sorted(equipe["id"] for equipe in profil.get(CLE_LISTE, ()) if personne in equipe["membres"]))


def a_declarer(profil: Mapping[str, Any] | None, services_declares: Iterable[str] = ()) -> list[str]:
    """Ce qu'il reste à déclarer pour que M4 puisse céduler, une phrase par manque ; `[]` si rien ne manque.

    `services_declares` : les codes du profil de services (`opsys.taxonomie`) : chacun a besoin d'une durée et de ses
    compétences. La fenêtre par défaut est facultative (le client peut donner la sienne) : jamais un manque."""
    if profil is None:
        return [f"le profil des équipes : {', '.join(CLES_PROFIL)} (`opsys-metier equipes declarer`)"]
    manques: list[str] = []
    if CLE_LISTE not in profil:
        manques.append(f"les équipes (clé {CLE_EQUIPES}.{CLE_LISTE}) : membres, compétences, dépôt et quarts")
    services = profil.get(CLE_SERVICES_EQUIPES)
    if services is None:
        manques.append(f"la durée et les compétences par service (clé {CLE_EQUIPES}.{CLE_SERVICES_EQUIPES})")
    else:
        for code in sorted(set(services_declares) - set(services)):
            manques.append(
                f"la durée et les compétences du service {code!r} (clé {CLE_EQUIPES}.{CLE_SERVICES_EQUIPES})"
            )
    if CLE_CEDULE not in profil:
        manques.append(
            f"les réglages de la cédule (clé {CLE_EQUIPES}.{CLE_CEDULE}) : "
            f"{', '.join(CLES_CEDULE_REQUISES)}"
        )
    return manques


def verifier_personnes(profil: Mapping[str, Any], cnx: Any) -> list[str]:
    """Contrôle du profil contre les personnes OPSYS de la base (`opsys-metier equipes declarer`) : une ligne par
    problème.

    Un membre doit être une personne existante et active (`opsys-metier personnes lister`). L'identifiant d'une équipe
    qui est aussi celui d'une personne exige que cette personne en soit membre : sinon elle verrait, par son propre
    identifiant, les chantiers de l'équipe (l'accès d'un employé se décide sur le technicien assigné)."""
    problemes: list[str] = []
    for equipe in profil.get(CLE_LISTE, ()):
        for membre in equipe["membres"]:
            trouvee = identite.personne(cnx, membre)
            if trouvee is None:
                problemes.append(
                    f"équipe {equipe['id']!r} : personne inconnue {membre!r} (opsys-metier personnes creer)"
                )
            elif not trouvee.actif:
                problemes.append(f"équipe {equipe['id']!r} : la personne {membre!r} est désactivée")
        homonyme = identite.personne(cnx, equipe["id"])
        if homonyme is not None and equipe["id"] not in equipe["membres"]:
            problemes.append(
                f"équipe {equipe['id']!r} : cet identifiant est celui d'une personne qui n'en est pas membre ; "
                "choisis un autre identifiant d'équipe, ou ajoute la personne à ses membres"
            )
    return problemes


def verifier_profil() -> list[str]:
    """`opsys-metier verifier` : un profil des équipes présent doit être valide, et ne parler que de services
    déclarés. Un profil absent n'est pas une erreur (l'instance n'a simplement pas encore déclaré ses équipes)."""
    from . import taxonomie

    try:
        profil = lire_equipes()
    except ProfilInvalide as exc:
        return [str(exc)]
    if profil is None:
        return []
    try:
        declares = {service.code for service in taxonomie.lire_services()}
    except ProfilInvalide:
        return []  # déjà signalé par `taxonomie.verifier_profil`
    if not declares:
        return []
    return [
        f"{fichier_profil()} : '{CLE_EQUIPES}.{CLE_SERVICES_EQUIPES}' porte une durée pour '{code}', que l'entreprise "
        f"ne déclare pas (services déclarés : {', '.join(sorted(declares))})"
        for code in sorted(set(profil.get(CLE_SERVICES_EQUIPES, {})) - declares)
    ]
