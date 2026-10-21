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
          competences: [gouttieres, revetement]
          depot: {id: depot-repentigny, latitude_microdegres: 45735000, longitude_microdegres: -73455000}
          quarts: [{jour: 0, debut_min: 480, fin_min: 1020}]     # jour : numéro de journée de la cédule
      services:                       # par code de service déclaré (`services`), durée et compétences requises
        gouttieres: {duree_min: 90, competences: [gouttieres]}
      cedule:                         # réglages de la cédule par tournées, tous obligatoires (graine facultative)
        {facteur_detour_milliemes: 1300, vitesse_moyenne_kmh: 50, marge_par_trajet_secondes: 600,
         iterations: 500, cout_non_cedule_m: 500000}
      fenetre_par_defaut:             # fenêtre offerte à un chantier dont le client n'en a donné aucune
        {jours: [0], debut_min: 480, fin_min: 1020}

Ce que le profil n'est pas : aucune donnée de ressources humaines ni de santé, aucune évaluation, aucun classement
d'employé (DEFINITION-PRODUIT M4, garde-fous humains). Un membre est un identifiant de personne OPSYS, pas une fiche.
Une compétence est un code que le propriétaire choisit (« gouttieres »), pas une certification d'employé.

Fail-closed (AGENTS.md) : sans profil, aucune équipe, aucun dépôt, aucun quart ni aucune durée n'est inventé ; le
verdict dit quoi déclarer et comment. Un profil invalide n'est jamais lu comme absent (`REJ-PROFIL-INVALIDE`). La
déclaration REMPLACE la clé entière : pour modifier, `opsys-metier equipes lister`, éditer, puis redéclarer.

Les bornes des réglages de la cédule (détour, vitesse, marge, itérations, coût) sont celles du solveur : M4 les vérifie
au moment de s'en servir et son verdict les cite ; ce module n'exige que des entiers du bon signe.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
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

CLES_EQUIPE = ("id", "membres", "competences", "depot", "quarts")
CLES_DEPOT = ("id", "latitude_microdegres", "longitude_microdegres")
CLES_QUART = ("jour", "debut_min", "fin_min")
CLES_SERVICE = ("duree_min", "competences")
CLES_CEDULE_REQUISES = (
    "facteur_detour_milliemes", "vitesse_moyenne_kmh", "marge_par_trajet_secondes", "iterations", "cout_non_cedule_m",
)
CLES_CEDULE_OPTIONNELLES = ("graine",)
CLES_FENETRE = ("jours", "debut_min", "fin_min")

VERDICT_EQUIPES_NON_CONFIGUREES = "REJ-EQUIPES-NON-CONFIGUREES"

MINUTES_PAR_JOUR = 1440
JOUR_MAX = 9999
GRAINE_MAX = 2**32 - 1
_EQUIPES_MAX = 100
_MEMBRES_MAX = 50
_COMPETENCES_MAX = 50
_SERVICES_MAX = 100
_QUARTS_MAX = 400
_JOURS_MAX = 400
_LATITUDE_MAX = 90_000_000
_LONGITUDE_MAX = 180_000_000


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


def _normaliser_equipe(brut: Any, chemin: str) -> dict[str, Any]:
    objet = _objet(brut, chemin, CLES_EQUIPE)
    return {
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
    return reglages


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


def normaliser_equipes(brut: Any) -> dict[str, Any]:
    """Valide une déclaration d'équipes et la rend CANONIQUE (équipes, membres, compétences, quarts et services triés ;
    listes et dictionnaires simples, sérialisables en YAML). Refuse la déclaration vide, la clé inconnue, l'équipe sans
    membre, dépôt, quart ou compétence bien formée, le doublon, la personne dans deux équipes : une déclaration vide
    n'est pas un profil, et rien n'est jamais arrondi ni deviné."""
    if not isinstance(brut, Mapping):
        raise ProfilInvalide(f"'{CLE_EQUIPES}' doit être un objet (clés : {', '.join(CLES_PROFIL)})")
    if not brut:
        raise ProfilInvalide(f"'{CLE_EQUIPES}' est vide : déclare au moins une des clés {', '.join(CLES_PROFIL)}")
    inconnues = sorted(str(cle) for cle in set(brut) - set(CLES_PROFIL))
    if inconnues:
        raise ProfilInvalide(f"'{CLE_EQUIPES}' : clés inconnues {inconnues} (attendu : {', '.join(CLES_PROFIL)})")
    propre: dict[str, Any] = {}
    if CLE_LISTE in brut:
        propre[CLE_LISTE] = _normaliser_liste(brut[CLE_LISTE])
    if CLE_SERVICES_EQUIPES in brut:
        propre[CLE_SERVICES_EQUIPES] = _normaliser_services(brut[CLE_SERVICES_EQUIPES])
    if CLE_CEDULE in brut:
        propre[CLE_CEDULE] = _normaliser_cedule(brut[CLE_CEDULE])
    if CLE_FENETRE_PAR_DEFAUT in brut:
        propre[CLE_FENETRE_PAR_DEFAUT] = _normaliser_fenetre(brut[CLE_FENETRE_PAR_DEFAUT])
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
    return _ecrire_cle_du_profil(
        CLE_EQUIPES, propre, chemin, par, "entreprise.equipes",
        {
            "equipes": [equipe["id"] for equipe in equipes],
            "membres_par_equipe": {equipe["id"]: len(equipe["membres"]) for equipe in equipes},
            "services": sorted(propre.get(CLE_SERVICES_EQUIPES, {})),
            "cedule_declaree": CLE_CEDULE in propre,
            "empreinte": empreinte_equipes(propre),
        },
    )


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
