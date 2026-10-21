"""Profil météo de l'entreprise : règles par service, fournisseur ouvert et fuseau (PLAN T4.13, M4.10).

M4 (Field Ops) juge un créneau contre la météo (`m4_verifier_meteo_creneau`). Les SEUILS ne sont pas ceux du code : ils
sont ceux de l'entreprise, par service (un revêtement ne craint pas le vent comme une gouttière), et se DÉCLARENT dans
le même fichier que ses services et ses équipes : `$OPSYS_HOME/entreprise.yaml`, clé `meteo` (même mécanisme que
`opsys.equipes` : lu à la demande, écrit avec un nom signé au journal d'audit). Le module est pur (fichier YAML et
journal d'audit seulement) : il ne connaît pas M4 et n'ouvre aucune connexion.

Forme de la clé `meteo` (chaque sous-clé est facultative à la déclaration ; ce qui manque, M4 le dit au moment d'en
avoir besoin : « seuil à configurer ») ::

    meteo:
      fuseau: America/Toronto             # fuseau des créneaux ; requis dès qu'un fournisseur est ouvert
      fournisseur: msc_geomet             # msc_geomet ou open_meteo ; absent : prévision saisie à la main SEULEMENT
      open_meteo:                         # requis seulement avec fournisseur: open_meteo (décision du propriétaire)
        forfait: commercial
        cle_env: OPSYS_OPEN_METEO_CLE     # NOM d'une variable d'environnement : la clé n'entre jamais dans ce fichier
      services:                           # par code de service déclaré
        revetement:
          seuils:                         # mesure -> {validation, blocage} ; au moins l'un des deux
            vent_kmh: {validation: 30, blocage: 45}            # vent moyen horaire, >= seuil
            rafales_kmh: {validation: 50, blocage: 65}         # rafales horaires, >= seuil
            pluie_mm_h: {validation: 1, blocage: 3}            # précipitations horaires (mm), >= seuil
            pluie_probabilite_pct: {validation: 40, blocage: 70}   # probabilité de précipitations, >= seuil
            gel_c: {validation: 2, blocage: 0}                 # température minimale, <= seuil
            verglas: {blocage: true}                           # précipitations verglaçantes prévues
            chaleur_c: {validation: 30, blocage: 35}           # température maximale, >= seuil
          sans_objet: []                  # risques que l'entreprise déclare SANS OBJET pour ce service

Cinq risques (vent, pluie, gel, verglas, chaleur). Pour chaque service, chacun doit être JUGÉ (au moins une mesure du
risque dans `seuils`) ou déclaré `sans_objet` : un risque sans décision n'est jamais « sans risque », M4 le dit
« seuil à configurer » et le verdict du créneau reste « inconnu ». Aucun seuil n'a de valeur par défaut.

Le fournisseur est FERMÉ par défaut : sans clé `fournisseur`, aucune requête réseau ne part jamais et la prévision se
saisit à la main. Les conditions des deux fournisseurs ont été lues le 2026-09-29 (docs/research/INGREDIENTS.md) :

    * MSC GeoMet (Environnement et Changement climatique Canada) : licence de données ECCC v2.1.1, usage commercial
      permis, attribution obligatoire ;
    * Open-Meteo : l'API gratuite est réservée à un usage NON commercial. Une entreprise ne peut l'ouvrir qu'avec un
      forfait commercial (décision du propriétaire) : le seul forfait accepté ici est `commercial`.

Les valeurs sont des entiers (aucun flottant) : vent et rafales en km/h, précipitations en mm par heure, probabilité en
pour cent, températures en degrés Celsius.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .taxonomie import (
    VERDICT_PROFIL_INVALIDE,
    ProfilInvalide,
    _ecrire_cle_du_profil,
    _valeur_du_profil,
    _valider_code,
    _verdict,
    fichier_profil,
)

CLE_METEO = "meteo"
CLE_FUSEAU = "fuseau"
CLE_FOURNISSEUR = "fournisseur"
CLE_OPEN_METEO = "open_meteo"
CLE_SERVICES_METEO = "services"
CLES_PROFIL = (CLE_FUSEAU, CLE_FOURNISSEUR, CLE_OPEN_METEO, CLE_SERVICES_METEO)
CLE_SEUILS = "seuils"
CLE_SANS_OBJET = "sans_objet"
CLES_SERVICE = (CLE_SEUILS, CLE_SANS_OBJET)
CLES_OPEN_METEO = ("forfait", "cle_env")

FOURNISSEUR_MSC_GEOMET = "msc_geomet"
FOURNISSEUR_OPEN_METEO = "open_meteo"
FOURNISSEURS = (FOURNISSEUR_MSC_GEOMET, FOURNISSEUR_OPEN_METEO)
FORFAIT_COMMERCIAL = "commercial"

RISQUES = ("vent", "pluie", "gel", "verglas", "chaleur")
# mesure -> (risque, sens de la comparaison avec le seuil, bornes acceptées ; None pour un booléen)
MESURES: dict[str, tuple[str, str, tuple[int, int] | None]] = {
    "vent_kmh": ("vent", ">=", (0, 300)),
    "rafales_kmh": ("vent", ">=", (0, 400)),
    "pluie_mm_h": ("pluie", ">=", (0, 500)),
    "pluie_probabilite_pct": ("pluie", ">=", (0, 100)),
    "gel_c": ("gel", "<=", (-60, 40)),
    "verglas": ("verglas", "presence", None),
    "chaleur_c": ("chaleur", ">=", (-20, 60)),
}
NIVEAUX = ("validation", "blocage")

VERDICT_METEO_NON_CONFIGUREE = "REJ-METEO-NON-CONFIGUREE"

_SERVICES_MAX = 100
_FORME_FUSEAU = re.compile(r"^(UTC|[A-Za-z]+(/[A-Za-z0-9_+-]+){1,2})$")
_FORME_VARIABLE = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")


# ---------------------------------------------------------------------------
# Validation : une seule règle par champ, un message qui dit quoi corriger
# ---------------------------------------------------------------------------
def _entier(valeur: Any, chemin: str, minimum: int, maximum: int) -> int:
    if isinstance(valeur, bool) or not isinstance(valeur, int):
        raise ProfilInvalide(f"{chemin} : un entier est attendu (reçu {valeur!r})")
    if not minimum <= valeur <= maximum:
        raise ProfilInvalide(f"{chemin} : entre {minimum} et {maximum} (reçu {valeur})")
    return valeur


def _objet(valeur: Any, chemin: str, permises: tuple[str, ...]) -> Mapping:
    if not isinstance(valeur, Mapping):
        raise ProfilInvalide(f"{chemin} : un objet est attendu ({', '.join(permises)})")
    inconnues = sorted(str(cle) for cle in set(valeur) - set(permises))
    if inconnues:
        raise ProfilInvalide(f"{chemin} : clés inconnues {inconnues} (attendu : {', '.join(permises)})")
    return valeur


def _normaliser_seuil(mesure: str, brut: Any, chemin: str) -> dict[str, Any]:
    _, sens, bornes = MESURES[mesure]
    objet = _objet(brut, chemin, NIVEAUX)
    if not objet:
        raise ProfilInvalide(f"{chemin} : au moins un niveau ({' ou '.join(NIVEAUX)})")
    seuil: dict[str, Any] = {}
    for niveau in NIVEAUX:
        if niveau not in objet:
            continue
        if bornes is None:
            if not isinstance(objet[niveau], bool):
                raise ProfilInvalide(f"{chemin}.{niveau} : true ou false (reçu {objet[niveau]!r})")
            seuil[niveau] = objet[niveau]
        else:
            seuil[niveau] = _entier(objet[niveau], f"{chemin}.{niveau}", bornes[0], bornes[1])
    if bornes is None:
        if not any(seuil.values()):
            raise ProfilInvalide(
                f"{chemin} : au moins un niveau doit valoir true ; pour ne pas juger ce risque, déclare-le "
                f"dans '{CLE_SANS_OBJET}'"
            )
        return seuil
    if len(seuil) == 2:
        # Le niveau « validation » se déclenche AVANT le blocage : plus tôt dans le sens de la mesure.
        if sens == ">=" and seuil["validation"] > seuil["blocage"]:
            raise ProfilInvalide(
                f"{chemin} : validation ({seuil['validation']}) doit être au plus égale au blocage "
                f"({seuil['blocage']}) : la validation se déclenche avant le blocage"
            )
        if sens == "<=" and seuil["validation"] < seuil["blocage"]:
            raise ProfilInvalide(
                f"{chemin} : validation ({seuil['validation']}) doit être au moins égale au blocage "
                f"({seuil['blocage']}) : la validation se déclenche avant le blocage (le gel se mesure vers le bas)"
            )
    return seuil


def _normaliser_service(brut: Any, chemin: str) -> dict[str, Any]:
    objet = _objet(brut, chemin, CLES_SERVICE)
    if not objet:
        raise ProfilInvalide(
            f"{chemin} est vide : déclare des '{CLE_SEUILS}' (un seuil par mesure jugée) et, pour un risque que "
            f"l'entreprise ne juge pas, '{CLE_SANS_OBJET}'"
        )
    propre: dict[str, Any] = {}
    couverts: set[str] = set()
    if CLE_SEUILS in objet:
        seuils = objet[CLE_SEUILS]
        if not isinstance(seuils, Mapping) or not seuils:
            raise ProfilInvalide(f"{chemin}.{CLE_SEUILS} : un objet non vide {{mesure: {{validation, blocage}}}}")
        inconnues = sorted(str(cle) for cle in set(seuils) - set(MESURES))
        if inconnues:
            raise ProfilInvalide(
                f"{chemin}.{CLE_SEUILS} : mesures inconnues {inconnues} (attendu : {', '.join(MESURES)})"
            )
        propre[CLE_SEUILS] = {}
        for mesure in MESURES:  # ordre canonique
            if mesure in seuils:
                propre[CLE_SEUILS][mesure] = _normaliser_seuil(
                    mesure, seuils[mesure], f"{chemin}.{CLE_SEUILS}.{mesure}"
                )
                couverts.add(MESURES[mesure][0])
    if CLE_SANS_OBJET in objet:
        sans_objet = objet[CLE_SANS_OBJET]
        if isinstance(sans_objet, (str, bytes, Mapping)) or not isinstance(sans_objet, Iterable):
            raise ProfilInvalide(f"{chemin}.{CLE_SANS_OBJET} : une liste de risques ({', '.join(RISQUES)})")
        liste = list(sans_objet)
        for position, risque in enumerate(liste):
            if risque not in RISQUES:
                raise ProfilInvalide(
                    f"{chemin}.{CLE_SANS_OBJET}[{position}] : risque inconnu {risque!r} "
                    f"(attendu : {', '.join(RISQUES)})"
                )
        if len(set(liste)) != len(liste):
            raise ProfilInvalide(f"{chemin}.{CLE_SANS_OBJET} : risques en double")
        contradictoires = sorted(set(liste) & couverts)
        if contradictoires:
            raise ProfilInvalide(
                f"{chemin} : {contradictoires} sont à la fois jugés (dans '{CLE_SEUILS}') et déclarés sans objet"
            )
        propre[CLE_SANS_OBJET] = [risque for risque in RISQUES if risque in liste]
    return propre


def _normaliser_services(brut: Any) -> dict[str, dict[str, Any]]:
    chemin = f"{CLE_METEO}.{CLE_SERVICES_METEO}"
    if not isinstance(brut, Mapping):
        raise ProfilInvalide(f"'{chemin}' doit être un objet {{code_du_service: {{seuils, sans_objet}}}}")
    if not brut:
        raise ProfilInvalide(f"'{chemin}' est vide : déclare au moins un service")
    if len(brut) > _SERVICES_MAX:
        raise ProfilInvalide(f"'{chemin}' : {_SERVICES_MAX} services au plus")
    services: dict[str, dict[str, Any]] = {}
    for code, entree in brut.items():
        cible = f"{chemin}[{code!r}]"
        _valider_code(code, cible)
        services[code] = _normaliser_service(entree, cible)
    return {code: services[code] for code in sorted(services)}


def _normaliser_open_meteo(brut: Any) -> dict[str, str]:
    chemin = f"{CLE_METEO}.{CLE_OPEN_METEO}"
    objet = _objet(brut, chemin, CLES_OPEN_METEO)
    manquantes = [cle for cle in CLES_OPEN_METEO if cle not in objet]
    if manquantes:
        raise ProfilInvalide(f"{chemin} : clés manquantes {manquantes}")
    if objet["forfait"] != FORFAIT_COMMERCIAL:
        raise ProfilInvalide(
            f"{chemin}.forfait : {FORFAIT_COMMERCIAL!r} seulement (reçu {objet['forfait']!r}) : l'API gratuite "
            "d'Open-Meteo est réservée à un usage non commercial (conditions lues le 2026-09-29) ; ouvrir ce "
            "fournisseur est une décision du propriétaire, avec un forfait commercial"
        )
    cle_env = objet["cle_env"]
    if not isinstance(cle_env, str) or _FORME_VARIABLE.match(cle_env) is None:
        raise ProfilInvalide(
            f"{chemin}.cle_env : le NOM d'une variable d'environnement (majuscules, chiffres et _, 3 à 64 "
            f"caractères) qui porte la clé d'API ; la clé n'entre jamais dans ce fichier (reçu {cle_env!r})"
        )
    return {"forfait": FORFAIT_COMMERCIAL, "cle_env": cle_env}


def normaliser_meteo(brut: Any) -> dict[str, Any]:
    """Valide une déclaration météo et la rend CANONIQUE (services, seuils et risques triés ; listes et dictionnaires
    simples, sérialisables en YAML). Refuse la déclaration vide, la clé inconnue, le seuil mal ordonné, le risque à la
    fois jugé et sans objet, le fournisseur sans fuseau, Open-Meteo sans forfait commercial : rien n'est arrondi ni
    deviné."""
    if not isinstance(brut, Mapping):
        raise ProfilInvalide(f"'{CLE_METEO}' doit être un objet (clés : {', '.join(CLES_PROFIL)})")
    if not brut:
        raise ProfilInvalide(f"'{CLE_METEO}' est vide : déclare au moins une des clés {', '.join(CLES_PROFIL)}")
    inconnues = sorted(str(cle) for cle in set(brut) - set(CLES_PROFIL))
    if inconnues:
        raise ProfilInvalide(f"'{CLE_METEO}' : clés inconnues {inconnues} (attendu : {', '.join(CLES_PROFIL)})")
    propre: dict[str, Any] = {}
    if CLE_FUSEAU in brut:
        fuseau = brut[CLE_FUSEAU]
        if not isinstance(fuseau, str) or _FORME_FUSEAU.match(fuseau) is None:
            raise ProfilInvalide(
                f"'{CLE_METEO}.{CLE_FUSEAU}' : un nom de la base des fuseaux (ex. America/Toronto) (reçu {fuseau!r})"
            )
        propre[CLE_FUSEAU] = fuseau
    if CLE_FOURNISSEUR in brut:
        fournisseur = brut[CLE_FOURNISSEUR]
        if fournisseur not in FOURNISSEURS:
            raise ProfilInvalide(
                f"'{CLE_METEO}.{CLE_FOURNISSEUR}' : {' ou '.join(FOURNISSEURS)} (reçu {fournisseur!r}) ; sans "
                "fournisseur, aucune requête réseau ne part : la prévision se saisit à la main"
            )
        if CLE_FUSEAU not in propre:
            raise ProfilInvalide(
                f"'{CLE_METEO}.{CLE_FOURNISSEUR}' exige '{CLE_METEO}.{CLE_FUSEAU}' : les créneaux se jugent à "
                "l'heure locale du chantier"
            )
        propre[CLE_FOURNISSEUR] = fournisseur
    if CLE_OPEN_METEO in brut:
        if brut.get(CLE_FOURNISSEUR) != FOURNISSEUR_OPEN_METEO:
            raise ProfilInvalide(
                f"'{CLE_METEO}.{CLE_OPEN_METEO}' n'a de sens qu'avec {CLE_FOURNISSEUR}: {FOURNISSEUR_OPEN_METEO}"
            )
        propre[CLE_OPEN_METEO] = _normaliser_open_meteo(brut[CLE_OPEN_METEO])
    elif brut.get(CLE_FOURNISSEUR) == FOURNISSEUR_OPEN_METEO:
        raise ProfilInvalide(
            f"'{CLE_METEO}.{CLE_FOURNISSEUR}: {FOURNISSEUR_OPEN_METEO}' exige '{CLE_METEO}.{CLE_OPEN_METEO}' "
            f"(forfait: {FORFAIT_COMMERCIAL}, cle_env) : l'API gratuite est non commerciale"
        )
    if CLE_SERVICES_METEO in brut:
        propre[CLE_SERVICES_METEO] = _normaliser_services(brut[CLE_SERVICES_METEO])
    return propre


# ---------------------------------------------------------------------------
# Lecture, écriture signée, empreinte
# ---------------------------------------------------------------------------
def lire_meteo(chemin: Path | None = None) -> dict[str, Any] | None:
    """Profil canonique déclaré par l'instance ; `None` si le fichier ou la clé est absent ou vide.

    Lève `ProfilInvalide` si la clé existe mais ne respecte pas le schéma (une valeur cassée n'est jamais lue comme
    absente)."""
    fichier = chemin or fichier_profil()
    valeur = _valeur_du_profil(CLE_METEO, fichier)
    if valeur is None or valeur == {}:
        return None
    try:
        return normaliser_meteo(valeur)
    except ProfilInvalide as exc:
        raise ProfilInvalide(f"{fichier} : {exc}") from exc


def _consigne_declaration(chemin: Path) -> str:
    return (
        "déclare les règles météo de l'entreprise : écris un fichier YAML (clés "
        f"{', '.join(CLES_PROFIL)}) puis `opsys-metier meteo declarer --depuis <fichier> --par <ton nom>` ; "
        f"le profil est écrit dans {chemin} (clé '{CLE_METEO}'), voir docs/architecture/TAXONOMIE.md"
    )


def charger_meteo() -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """`(profil, None)` si l'instance déclare sa météo, sinon `(None, verdict)` qui dit quoi déclarer et comment.

    Ne lève jamais : un profil illisible ou invalide est un verdict `REJ-PROFIL-INVALIDE`, distinct de l'absence
    (`REJ-METEO-NON-CONFIGUREE`). Le profil rendu peut être partiel : ce qu'il ne dit pas, `a_declarer` le liste."""
    chemin = fichier_profil()
    try:
        profil = lire_meteo(chemin)
    except ProfilInvalide as exc:
        return None, _verdict(VERDICT_PROFIL_INVALIDE, f"profil d'entreprise invalide : {exc}")
    if profil is None:
        return None, _verdict(
            VERDICT_METEO_NON_CONFIGUREE,
            f"aucune règle météo déclarée pour cette entreprise : {_consigne_declaration(chemin)} ; aucun seuil "
            "n'est jamais inventé (seuil à configurer)",
        )
    return profil, None


def empreinte_meteo(profil: Mapping[str, Any]) -> str:
    """SHA-256 du profil canonique : ce qu'une vérification a lu."""
    octets = json.dumps(profil, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(octets).hexdigest()


def enregistrer_meteo(profil: Any, chemin: Path | None = None, par: str | None = None) -> Path:
    """Écrit le profil validé (remplace la clé `meteo`), sans toucher aux autres clés du fichier.

    Signé par `par`, le changement est inscrit au journal d'audit : le fournisseur ouvert, le fuseau, les services
    jugés et l'empreinte du profil. Le NOM de la variable d'environnement de la clé d'API n'y figure pas."""
    propre = normaliser_meteo(profil)
    return _ecrire_cle_du_profil(
        CLE_METEO,
        propre,
        chemin,
        par,
        "entreprise.meteo",
        {
            "fournisseur": propre.get(CLE_FOURNISSEUR),
            "forfait": propre.get(CLE_OPEN_METEO, {}).get("forfait"),
            "fuseau": propre.get(CLE_FUSEAU),
            "services": sorted(propre.get(CLE_SERVICES_METEO, {})),
            "empreinte": empreinte_meteo(propre),
        },
    )


# ---------------------------------------------------------------------------
# Ce que le profil dit, et ce qui lui manque
# ---------------------------------------------------------------------------
def risques_a_decider(regles_du_service: Mapping[str, Any] | None) -> list[str]:
    """Les risques qu'un service n'a ni jugés (aucune mesure dans `seuils`) ni déclarés sans objet, dans l'ordre
    canonique. Sans règles (`None`), les cinq."""
    if not regles_du_service:
        return list(RISQUES)
    jugees = {MESURES[mesure][0] for mesure in regles_du_service.get(CLE_SEUILS, {})}
    sans_objet = set(regles_du_service.get(CLE_SANS_OBJET, ()))
    return [risque for risque in RISQUES if risque not in jugees and risque not in sans_objet]


def a_declarer(profil: Mapping[str, Any] | None, services_declares: Iterable[str] = ()) -> list[str]:
    """Ce qu'il reste à déclarer pour que M4 puisse juger la météo, une phrase par manque ; `[]` si rien ne manque.

    `services_declares` : les codes du profil de services (`opsys.taxonomie`) : chacun a besoin de ses seuils. Le
    fournisseur est facultatif (sans lui, la prévision se saisit à la main) : jamais un manque."""
    if profil is None:
        return [f"le profil météo : {', '.join(CLES_PROFIL)} (`opsys-metier meteo declarer`)"]
    services = profil.get(CLE_SERVICES_METEO, {})
    manques: list[str] = []
    if not services and not list(services_declares):
        manques.append(f"les seuils par service (clé {CLE_METEO}.{CLE_SERVICES_METEO})")
    for code in sorted(set(services_declares) | set(services)):
        a_decider = risques_a_decider(services.get(code))
        if a_decider:
            manques.append(
                f"le service {code!r} : seuil à configurer ou risque sans objet pour {', '.join(a_decider)} "
                f"(clé {CLE_METEO}.{CLE_SERVICES_METEO}.{code})"
            )
    return manques


def verifier_profil() -> list[str]:
    """`opsys-metier verifier` : un profil météo présent doit être valide, et ne parler que de services déclarés. Un
    profil absent n'est pas une erreur (l'instance n'a simplement pas encore déclaré sa météo)."""
    from . import taxonomie

    try:
        profil = lire_meteo()
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
        f"{fichier_profil()} : '{CLE_METEO}.{CLE_SERVICES_METEO}' porte des seuils pour '{code}', que l'entreprise "
        f"ne déclare pas (services déclarés : {', '.join(sorted(declares))})"
        for code in sorted(set(profil.get(CLE_SERVICES_METEO, {})) - declares)
    ]
