"""Alertes MÉTIER de M8 (M8.9, chantier C3 de l'analyse M8) : des règles déclaratives, un cycle de vie, une action
proposée.

Module PUR (ADR-0009) : aucun import d'``opsys``, aucune horloge (``maintenant`` vient de l'appelant), aucun registre
ouvert ici (``outils.py`` passe le contenu du registre et range ce que ce module décide). Déterministe.

Ce que ce module est et n'est pas. M8 mesure, il ne décide pas (c'est M9) et n'agit jamais sur un autre département. Une
alerte :

* DIT ce qui est franchi : la valeur courante et la référence qu'elle franchit (un seuil que la DIRECTION a déclaré), ou
  « périmée », ou « bloquée par le contrôle de qualité » ;
* PROPOSE une action choisie dans un gabarit FERMÉ du fichier de règles (rien n'est généré) ;
* NOMME le département propriétaire de la mesure, tel que le catalogue le déclare (jamais un autre) ;
* liste les mesures à consulter ;
* ne porte JAMAIS de « cause » : M8 ne sait pas pourquoi une valeur a changé (la garde statique du paquet interdit
même la clé).

Les règles (``definitions/m8-alertes.v1.yaml``) sont d'un ensemble FERMÉ de genres :

* ``seuil`` : le seuil vient de la configuration de la direction (``configuration.alertes.seuils.<reglage>``, adopté
  depuis la console). Sans seuil, ou avec un seuil illisible, la règle est « non évaluée » et le dit ; aucune alerte
  n'est jamais ouverte sur un seuil deviné. Une valeur périmée, de fraîcheur inconnue, non calculable ou bloquée par la
  qualité n'alerte jamais sur sa valeur ;
* ``peremption`` : une mesure DÉJÀ calculée est devenue périmée ;
* ``qualite`` : le contrôle de qualité (``qualite_mesures``) a bloqué une mesure.

Cycle de vie d'un ÉPISODE (du premier franchissement au retour dans la cible), dans un registre APPEND-ONLY dont ce
module ne fait que lire le contenu et fabriquer les entrées : ``alerte_ouverte`` (une seule par épisode),
``alerte_accusee``, ``alerte_reportee`` (jusqu'à un instant), ``alerte_resolue`` (retour dans la cible constaté sur
une valeur à jour). L'état EFFECTIF se déduit des entrées et de ``maintenant`` (un report échu redonne « ouverte »
sans qu'aucune entrée soit écrite). Une ouverture ne se répète pas tant que l'épisode dure ; le nombre d'ouvertures
par 24 h est borné.
"""

from __future__ import annotations

import re
import string
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from . import entonnoir, fraicheur_mesures, nombres, qualite_mesures, wallboards

SCHEMA = "opsys.m8.alertes_metier/v1"
_CHEMIN = Path(__file__).resolve().parents[2] / "definitions" / "m8-alertes.v1.yaml"

NOM_REGISTRE = "alertes_metier"
EVENEMENT = "m8.alerte_proposee"

TYPE_OUVERTE = "alerte_ouverte"
TYPE_ACCUSEE = "alerte_accusee"
TYPE_REPORTEE = "alerte_reportee"
TYPE_RESOLUE = "alerte_resolue"

STATUT_OUVERTE = "ouverte"
STATUT_ACCUSEE = "accusee"
STATUT_REPORTEE = "reportee"
STATUT_RESOLUE = "resolue"

ETAT_FRANCHI = "franchi"
ETAT_DANS_LA_CIBLE = "dans_la_cible"
ETAT_NON_EVALUEE = "non_evaluee"

RAISON_SEUIL_A_CONFIGURER = "seuil_a_configurer"
RAISON_SEUIL_INVALIDE = "seuil_invalide"
RAISON_MESURE_NON_CALCULABLE = "mesure_non_calculable"
RAISON_QUALITE_ECHEC = "qualite_en_echec"
RAISON_MESURE_PERIMEE = "mesure_perimee"
RAISON_FRAICHEUR_INCONNUE = "fraicheur_inconnue"
RAISON_AUCUN_CONTROLE = "aucun_controle_possible"

REJ_ALERTES_ILLISIBLES = "REJ-ALERTES-REGLES-ILLISIBLES"
REJ_ALERTES_INVALIDES = "REJ-ALERTES-REGLES-INVALIDES"
REJ_ALERTE_INCONNUE = "REJ-ALERTE-INCONNUE"
REJ_ALERTE_IDENTIFIANT = "REJ-ALERTE-IDENTIFIANT-INVALIDE"
REJ_ALERTE_RESOLUE = "REJ-ALERTE-DEJA-RESOLUE"
REJ_ALERTE_REPORT = "REJ-ALERTE-REPORT-INVALIDE"

OUVERTURES_PAR_JOUR_MAX = 30
REPORT_MAX_JOURS = 30
MESURES_LIEES_MAX = 8

_TYPES_ALERTE = {
    "seuil": "METIER-SEUIL-FRANCHI",
    "peremption": "METIER-DONNEE-PERIMEE",
    "qualite": "METIER-QUALITE-ECHEC",
}
_CLES_RACINE = frozenset({"schema", "version", "actions", "regles"})
_CLES_COMMUNES = frozenset({"id", "genre", "gravite", "action", "libelle"})
_CLES_PAR_GENRE = {
    "seuil": _CLES_COMMUNES | {"mesure", "sens", "reglage", "mesures_liees"},
    "peremption": _CLES_COMMUNES | {"mesures"},
    "qualite": _CLES_COMMUNES,
}
_OBLIGATOIRES = {
    "seuil": _CLES_COMMUNES | {"mesure", "sens", "reglage"},
    "peremption": _CLES_COMMUNES | {"mesures"},
    "qualite": _CLES_COMMUNES,
}
_GRAVITES = frozenset({"attention", "critique"})
_SENS = frozenset({nombres.SENS_AU_DESSUS, nombres.SENS_AU_DESSOUS})
_CHAMPS_GABARIT = frozenset({"departement", "mesure"})
_IDENTIFIANT_REGLE = re.compile(r"^ALERTE-[A-Z0-9]+(?:-[A-Z0-9]+){1,8}$")
_REGLAGE = re.compile(r"^[a-z][a-z0-9_]{2,60}$")
_ID_ALERTE = re.compile(r"^(ALERTE-[A-Z0-9]+(?:-[A-Z0-9]+){1,8}):(m8_[a-z0-9_]{1,76}):([1-9][0-9]{0,5})$")
_TEXTE_MAX = 600


class AlertesRefusees(ValueError):
    """Le fichier de règles est refusé (``code`` = verdict, ``detail`` = la règle fautive), ou un geste sur une
    alerte l'est
    (``REJ-ALERTE-…``)."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code} : {detail}")
        self.code = code
        self.detail = detail


def _refus(detail: str) -> AlertesRefusees:
    return AlertesRefusees(REJ_ALERTES_INVALIDES, detail)


# ---------------------------------------------------------------------------
# Le fichier de règles
# ---------------------------------------------------------------------------
def _texte(brut: Any, regle: str, cle: str) -> str:
    if not isinstance(brut, str) or not brut.strip() or len(brut) > _TEXTE_MAX:
        raise _refus(f"{regle} : {cle} : un texte de 1 à {_TEXTE_MAX} caractères")
    return " ".join(brut.split())


def _gabarit(identifiant: str, brut: Any) -> str:
    texte = _texte(brut, f"action {identifiant}", "texte")
    try:
        champs = {nom for _, nom, _, _ in string.Formatter().parse(texte) if nom is not None}
    except ValueError as erreur:
        raise _refus(f"action {identifiant} : gabarit illisible ({erreur})") from erreur
    inconnus = champs - _CHAMPS_GABARIT
    if inconnus:
        raise _refus(f"action {identifiant} : champs de gabarit inconnus {sorted(inconnus)}")
    return texte


def _mesures(brut: Any, connues: set[str], regle: str, cle: str, *, maximum: int) -> list[str]:
    if not isinstance(brut, list) or not brut or not all(isinstance(m, str) for m in brut):
        raise _refus(f"{regle} : {cle} : une liste non vide de mesures du catalogue")
    if len(set(brut)) != len(brut) or len(brut) > maximum:
        raise _refus(f"{regle} : {cle} : au plus {maximum} mesures, sans doublon")
    inconnues = sorted(set(brut) - connues)
    if inconnues:
        raise _refus(f"{regle} : {cle} : mesure(s) hors du catalogue fermé : {inconnues}")
    return list(brut)


def _valider_regle(brut: Any, connues: set[str], actions: dict[str, str]) -> dict[str, Any]:
    if not isinstance(brut, dict):
        raise _refus("chaque règle est un objet")
    identifiant = brut.get("id")
    if not isinstance(identifiant, str) or not _IDENTIFIANT_REGLE.fullmatch(identifiant):
        raise _refus("une règle sans identifiant « ALERTE-… »")
    genre = brut.get("genre")
    if genre not in _CLES_PAR_GENRE:
        raise _refus(f"{identifiant} : genre : {sorted(_CLES_PAR_GENRE)} attendu")
    inconnues = set(brut) - _CLES_PAR_GENRE[genre]
    manquantes = _OBLIGATOIRES[genre] - set(brut)
    if inconnues or manquantes:
        raise _refus(f"{identifiant} : clés inconnues {sorted(inconnues)} ou manquantes {sorted(manquantes)}")
    if brut["gravite"] not in _GRAVITES:
        raise _refus(f"{identifiant} : gravite : {sorted(_GRAVITES)} attendu")
    if brut["action"] not in actions:
        raise _refus(f"{identifiant} : action : {brut['action']!r} n'est pas un gabarit du fichier")
    regle: dict[str, Any] = {
        "id": identifiant,
        "genre": genre,
        "gravite": brut["gravite"],
        "action": brut["action"],
        "libelle": _texte(brut["libelle"], identifiant, "libelle"),
    }
    if genre == "seuil":
        regle["mesure"] = _mesures([brut["mesure"]], connues, identifiant, "mesure", maximum=1)[0]
        if brut["sens"] not in _SENS:
            raise _refus(f"{identifiant} : sens : {sorted(_SENS)} attendu")
        regle["sens"] = brut["sens"]
        if not isinstance(brut["reglage"], str) or not _REGLAGE.fullmatch(brut["reglage"]):
            raise _refus(f"{identifiant} : reglage : un nom de seuil en minuscules")
        regle["reglage"] = brut["reglage"]
        liees = _mesures(brut.get("mesures_liees", []), connues, identifiant, "mesures_liees",
                         maximum=MESURES_LIEES_MAX) if brut.get("mesures_liees") else []
        if regle["mesure"] in liees:
            raise _refus(f"{identifiant} : mesures_liees ne reprend pas la mesure surveillée")
        regle["mesures_liees"] = liees
    elif genre == "peremption":
        regle["mesures"] = _mesures(brut["mesures"], connues, identifiant, "mesures", maximum=60)
    return regle


def _signature(regle: dict[str, Any]) -> tuple[Any, ...]:
    if regle["genre"] == "seuil":
        return ("seuil", regle["mesure"])
    if regle["genre"] == "peremption":
        return ("peremption", tuple(sorted(regle["mesures"])))
    return ("qualite",)


def valider(brut: Any, catalogue: dict[str, Any]) -> dict[str, Any]:
    """Le fichier de règles validé (fail-closed : une clé de plus, une mesure hors catalogue, un gabarit d'action
    inconnu, un champ de gabarit inconnu, un identifiant en double, deux règles du même genre sur la même mesure,
    deux règles pour
    un même seuil refusent le fichier entier)."""
    if not isinstance(brut, dict) or brut.get("schema") != SCHEMA:
        raise _refus(f"schema attendu : {SCHEMA}")
    inconnues = set(brut) - _CLES_RACINE
    if inconnues or _CLES_RACINE - set(brut):
        raise _refus(f"clés inconnues {sorted(inconnues)} ou manquantes {sorted(_CLES_RACINE - set(brut))}")
    if type(brut["version"]) is not int or brut["version"] < 1:
        raise _refus("version : entier ≥ 1")
    if not isinstance(brut["actions"], dict) or not brut["actions"]:
        raise _refus("actions : un dictionnaire de gabarits non vide")
    actions = {str(nom): _gabarit(str(nom), texte) for nom, texte in brut["actions"].items()}
    if not isinstance(brut["regles"], list) or not 1 <= len(brut["regles"]) <= 60:
        raise _refus("regles : 1 à 60 règles")
    connues = {entree["metric_id"] for entree in catalogue["mesures"]}
    regles, identifiants, signatures, reglages = [], set(), set(), set()
    for element in brut["regles"]:
        regle = _valider_regle(element, connues, actions)
        if regle["id"] in identifiants:
            raise _refus(f"{regle['id']} : identifiant défini deux fois")
        signature = _signature(regle)
        if signature in signatures:
            raise _refus(f"{regle['id']} : règle déclarée en double")
        if regle["genre"] == "seuil":
            if regle["reglage"] in reglages:
                raise _refus(f"{regle['id']} : le seuil {regle['reglage']} sert déjà une autre règle")
            reglages.add(regle["reglage"])
        identifiants.add(regle["id"])
        signatures.add(signature)
        regles.append(regle)
    return {"version": brut["version"], "actions": actions, "regles": regles}


def charger(catalogue: dict[str, Any], chemin: str | Path | None = None) -> dict[str, Any]:
    """Les règles de ``definitions/m8-alertes.v1.yaml``, validées contre le catalogue fermé."""
    fichier = Path(chemin) if chemin is not None else _CHEMIN
    try:
        brut = yaml.safe_load(fichier.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as erreur:
        raise AlertesRefusees(REJ_ALERTES_ILLISIBLES, f"{fichier.name} ({erreur})") from erreur
    return valider(brut, catalogue)


def reglages_declares(regles: dict[str, Any]) -> list[str]:
    """Les noms des seuils que les règles ``seuil`` attendent de la direction
    (``configuration.alertes.seuils.<nom>``)."""
    return [r["reglage"] for r in regles["regles"] if r["genre"] == "seuil"]


# ---------------------------------------------------------------------------
# Les seuils de la direction
# ---------------------------------------------------------------------------
def lire_seuils(configuration: Any, regles: dict[str, Any]) -> dict[str, Any]:
    """Les seuils lus de ``configuration.alertes.seuils`` : ``{seuils, invalides, ignores}``. Un seuil illisible
    (booléen, texte non décimal, hors de l'ordre de grandeur lisible) est REFUSÉ et dit : la règle est alors « non
    évaluée », jamais
    évaluée sur une valeur corrigée. Une clé qui n'est le seuil d'aucune règle est dite (faute de frappe)."""
    attendus = set(reglages_declares(regles))
    seuils: dict[str, Decimal] = {}
    invalides: list[str] = []
    ignores: list[str] = []
    brut = configuration.get("seuils") if isinstance(configuration, dict) else None
    if isinstance(brut, dict):
        for nom, valeur in brut.items():
            if nom not in attendus:
                ignores.append(str(nom))
                continue
            lu = None if isinstance(valeur, (bool, float)) else nombres.decimal_lu(valeur)
            if lu is None:
                invalides.append(nom)
            else:
                seuils[nom] = lu
    elif brut is not None:
        invalides.extend(sorted(attendus))
    return {"seuils": seuils, "invalides": sorted(invalides), "ignores": sorted(ignores)}


# ---------------------------------------------------------------------------
# L'évaluation des règles (sur les mesures lues AVEC fraîcheur, qualité et pastille)
# ---------------------------------------------------------------------------
def _verdict(regle: dict[str, Any], mesure: dict[str, Any], etat: str, **extra: Any) -> dict[str, Any]:
    return {"regle": regle["id"], "genre": regle["genre"], "metric_id": mesure["metric_id"], "etat": etat, **extra}


def _evaluable(mesure: dict[str, Any]) -> str | None:
    """La raison pour laquelle une valeur ne peut pas servir à alerter, ou ``None`` si elle le peut."""
    if qualite_mesures.en_echec(mesure):
        return RAISON_QUALITE_ECHEC
    if mesure["statut"] != entonnoir.STATUT_CALCULEE:
        return RAISON_MESURE_NON_CALCULABLE
    statut = mesure["fraicheur"]["statut"]
    if statut == fraicheur_mesures.STATUT_PERIME:
        return RAISON_MESURE_PERIMEE
    if not mesure["fraicheur"]["peut_etre_montree_comme_a_jour"]:
        return RAISON_FRAICHEUR_INCONNUE
    return None


def franchit(valeur: Decimal, sens: str, seuil: Decimal) -> bool:
    """Vrai si ``valeur`` franchit ``seuil`` : ``au_dessus`` = l'atteint ou le dépasse, ``au_dessous`` = l'atteint ou
    passe sous. La borne elle-même franchit (comme les seuils des autres surfaces de M8)."""
    return valeur >= seuil if sens == nombres.SENS_AU_DESSUS else valeur <= seuil


def evaluer(regles: dict[str, Any], mesures: list[dict[str, Any]], seuils_lus: dict[str, Any]) -> list[dict[str, Any]]:
    """Le verdict de chaque règle sur chaque mesure qu'elle vise : ``franchi``, ``dans_la_cible`` ou ``non_evaluee``
    (avec sa raison : seuil à configurer ou invalide, mesure non calculable, périmée, de fraîcheur inconnue, bloquée
    par la
    qualité). Lecture pure, ordre du fichier."""
    par_id = {m["metric_id"]: m for m in mesures}
    verdicts: list[dict[str, Any]] = []
    for regle in regles["regles"]:
        if regle["genre"] == "seuil":
            mesure = par_id.get(regle["mesure"])
            if mesure is None:
                continue
            seuil = seuils_lus["seuils"].get(regle["reglage"])
            if seuil is None:
                raison = RAISON_SEUIL_INVALIDE if regle["reglage"] in seuils_lus["invalides"] else (
                    RAISON_SEUIL_A_CONFIGURER)
                verdicts.append(_verdict(regle, mesure, ETAT_NON_EVALUEE, raison=raison))
                continue
            inutilisable = _evaluable(mesure)
            if inutilisable is not None:
                verdicts.append(_verdict(regle, mesure, ETAT_NON_EVALUEE, raison=inutilisable, seuil=seuil))
                continue
            valeur = nombres.decimal_lu(mesure["valeur"])
            if valeur is None:
                verdicts.append(_verdict(regle, mesure, ETAT_NON_EVALUEE, raison=RAISON_MESURE_NON_CALCULABLE,
                                         seuil=seuil))
                continue
            etat = ETAT_FRANCHI if franchit(valeur, regle["sens"], seuil) else ETAT_DANS_LA_CIBLE
            verdicts.append(_verdict(regle, mesure, etat, valeur=mesure["valeur"], seuil=seuil))
        elif regle["genre"] == "peremption":
            for metric_id in regle["mesures"]:
                mesure = par_id.get(metric_id)
                if mesure is None:
                    continue
                if qualite_mesures.en_echec(mesure) or mesure["statut"] != entonnoir.STATUT_CALCULEE:
                    verdicts.append(_verdict(regle, mesure, ETAT_NON_EVALUEE, raison=RAISON_MESURE_NON_CALCULABLE))
                elif mesure["fraicheur"]["statut"] == fraicheur_mesures.STATUT_PERIME:
                    verdicts.append(_verdict(regle, mesure, ETAT_FRANCHI))
                elif mesure["fraicheur"]["peut_etre_montree_comme_a_jour"]:
                    verdicts.append(_verdict(regle, mesure, ETAT_DANS_LA_CIBLE))
                else:
                    verdicts.append(_verdict(regle, mesure, ETAT_NON_EVALUEE, raison=RAISON_FRAICHEUR_INCONNUE))
        else:
            for mesure in mesures:
                statut = (mesure.get("qualite") or {}).get("statut")
                if statut == qualite_mesures.STATUT_ECHEC:
                    verdicts.append(_verdict(regle, mesure, ETAT_FRANCHI))
                elif statut == qualite_mesures.STATUT_OK:
                    verdicts.append(_verdict(regle, mesure, ETAT_DANS_LA_CIBLE))
                else:
                    verdicts.append(_verdict(regle, mesure, ETAT_NON_EVALUEE, raison=RAISON_AUCUN_CONTROLE))
    return verdicts


# ---------------------------------------------------------------------------
# Le registre du cycle de vie (lecture) : les épisodes et leur état effectif
# ---------------------------------------------------------------------------
def _instant(texte: Any):
    return entonnoir.instant_lu(texte)


def episodes(registre: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Les épisodes du registre, ``{alerte_id: épisode}`` : l'ouverture (entrée complète) puis l'état tiré des gestes
    qui suivent, DANS L'ORDRE du registre. Un accusé note « vu » et lève un report en cours ; un report note la date
    jusqu'à laquelle l'alerte est cachée et efface l'accusé (« rappelez-le-moi ») ; une résolution ferme l'épisode.
    Une entrée
    qui nomme un épisode inconnu est ignorée (jamais inventée)."""
    resultat: dict[str, dict[str, Any]] = {}
    for entree in registre:
        genre = entree.get("type_entree")
        identifiant = entree.get("alerte_id")
        if genre == TYPE_OUVERTE:
            resultat[identifiant] = {
                **entree, "accusee_le": None, "reporte_jusqu_au": None, "resolue_le": None, "gestes": [],
            }
            continue
        episode = resultat.get(identifiant)
        if episode is None or episode["resolue_le"] is not None:
            continue
        if genre == TYPE_ACCUSEE:
            episode.update(accusee_le=entree["accusee_le"], reporte_jusqu_au=None)
            episode["gestes"].append({"geste": "accusee", "le": entree["accusee_le"], "par": entree.get("par")})
        elif genre == TYPE_REPORTEE:
            episode.update(accusee_le=None, reporte_jusqu_au=entree["jusqu_au"])
            episode["gestes"].append({"geste": "reportee", "le": entree["reportee_le"], "par": entree.get("par"),
                                      "jusqu_au": entree["jusqu_au"]})
        elif genre == TYPE_RESOLUE:
            episode.update(resolue_le=entree["resolue_le"], motif_resolution=entree.get("motif"))
            episode["gestes"].append({"geste": "resolue", "le": entree["resolue_le"], "motif": entree.get("motif")})
    return resultat


def statut_effectif(episode: dict[str, Any], maintenant: str) -> str:
    """``resolue``, ``reportee`` (le report n'est pas échu), ``accusee`` ou ``ouverte``. Un report échu redonne
    ``ouverte`` : elle redevient visible sans qu'aucune entrée ne soit écrite. Un instant illisible compte comme échu
    (une
    alerte ne se cache jamais sur une date qu'on ne sait pas lire)."""
    if episode["resolue_le"] is not None:
        return STATUT_RESOLUE
    jusqu_au, instant = _instant(episode["reporte_jusqu_au"]), _instant(maintenant)
    if jusqu_au is not None and instant is not None and instant < jusqu_au:
        return STATUT_REPORTEE
    return STATUT_ACCUSEE if episode["accusee_le"] is not None else STATUT_OUVERTE


def episodes_en_cours(tous: dict[str, dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """L'épisode NON résolu de chaque couple (règle, mesure), ou rien : il y en a au plus un (une ouverture ne se répète
    pas tant que l'épisode dure)."""
    return {(e["regle"], e["metric_id"]): e for e in tous.values() if e["resolue_le"] is None}


def _prochain_episode(tous: dict[str, dict[str, Any]], regle: str, metric_id: str) -> int:
    return 1 + max((e["episode"] for e in tous.values() if e["regle"] == regle and e["metric_id"] == metric_id),
                   default=0)


# ---------------------------------------------------------------------------
# L'ouverture et la résolution : ce que l'évaluation écrit
# ---------------------------------------------------------------------------
def _action(regles: dict[str, Any], regle: dict[str, Any], entree: dict[str, Any]) -> str:
    return regles["actions"][regle["action"]].format(departement=entree["proprietaire"], mesure=entree["nom"])


def _quoi_pourquoi(regle: dict[str, Any], mesure: dict[str, Any], verdict: dict[str, Any]) -> tuple[str, str]:
    nom = mesure["nom"]
    if regle["genre"] == "seuil":
        sens = "atteint ou passe sous" if regle["sens"] == nombres.SENS_AU_DESSOUS else "atteint ou dépasse"
        courant = wallboards.formater_valeur(verdict["valeur"], mesure["unite"])
        seuil = wallboards.formater_valeur(nombres.texte_decimal(verdict["seuil"]), mesure["unite"])
        return (
            f"{nom} franchit le seuil déclaré par la direction.",
            f"valeur courante {courant} {sens} le seuil déclaré {seuil}.",
        )
    if regle["genre"] == "peremption":
        return (
            f"{nom} est périmée.",
            "la dernière valeur connue sort de la fenêtre de fraîcheur du catalogue : elle ne doit plus guider une "
            "décision.",
        )
    return (
        f"{nom} est bloquée par le contrôle de qualité des données.",
        "une règle de qualité échoue sur la donnée reçue à la source : aucune valeur n'est montrée.",
    )


def _entree_ouverte(
    regles: dict[str, Any], regle: dict[str, Any], mesure: dict[str, Any], verdict: dict[str, Any], numero: int,
    maintenant: str,
) -> dict[str, Any]:
    quoi, pourquoi = _quoi_pourquoi(regle, mesure, verdict)
    seuil = verdict.get("seuil")
    liees = (regle.get("mesures_liees") or []) if regle["genre"] == "seuil" else []
    type_alerte = _TYPES_ALERTE[regle["genre"]]
    return {
        "type_entree": TYPE_OUVERTE,
        "alerte_id": f"{regle['id']}:{mesure['metric_id']}:{numero}",
        "regle": regle["id"],
        "metric_id": mesure["metric_id"],
        "episode": numero,
        "genre": regle["genre"],
        "type_alerte": type_alerte,
        "gravite": regle["gravite"],
        "departement": mesure["proprietaire"],
        "action_id": regle["action"],
        "action": _action(regles, regle, mesure),
        "mesures_liees": list(liees),
        "courant": verdict.get("valeur"),
        "unite": mesure["unite"],
        "sens": regle.get("sens"),
        "seuil": None if seuil is None else nombres.texte_decimal(seuil),
        "quoi": quoi,
        "pourquoi": pourquoi,
        "source": mesure["source"],
        "ouverte_le": maintenant,
        "evenement_id": f"m8-alerte-{mesure['metric_id']}-{type_alerte}-{maintenant}",
    }


def charge_evenement(entree: dict[str, Any]) -> dict[str, Any]:
    """La charge de ``m8.alerte_proposee`` pour une ouverture (extension ADDITIVE du schéma : trois types, une forme de
    preuve, trois champs facultatifs). M8 NOMME le destinataire et PROPOSE l'action ; il n'exécute rien."""
    return {
        "evenement_id": entree["evenement_id"],
        "metric_id": entree["metric_id"],
        "type_alerte": entree["type_alerte"],
        "quoi": entree["quoi"],
        "a_qui": entree["departement"],
        "pourquoi": entree["pourquoi"],
        "preuve": {
            "regle": entree["regle"],
            "metric_id": entree["metric_id"],
            "episode": entree["episode"],
            "courant": entree["courant"],
            "unite": entree["unite"],
            "sens": entree["sens"],
            "seuil": entree["seuil"],
            "departement": entree["departement"],
        },
        "action_proposee": entree["action"],
        "source": entree["source"],
        "horodatage_reference": entree["ouverte_le"],
        "gravite": entree["gravite"],
        "alerte_id": entree["alerte_id"],
        "mesures_liees": list(entree["mesures_liees"]),
    }


def planifier(
    regles: dict[str, Any],
    verdicts: list[dict[str, Any]],
    mesures: list[dict[str, Any]],
    registre: list[dict[str, Any]],
    maintenant: str,
) -> dict[str, Any]:
    """Ce qu'une évaluation DOIT écrire : ``{ouvertures, resolutions, bornees, inchangees}``. Une ouverture par épisode
    (jamais deux tant que l'épisode dure, qu'il soit accusé ou reporté), une résolution quand la valeur, à jour, est
    revenue dans la cible. Une règle « non évaluée » ne change RIEN (ni ouverture, ni résolution : on ne ferme pas un
    épisode sur une valeur qu'on ne peut pas juger). Les ouvertures sont bornées à ``OUVERTURES_PAR_JOUR_MAX`` par 24
    h :
    le surplus n'est pas ouvert (il est compté dans ``bornees`` et reviendra à la prochaine évaluation)."""
    instant = _instant(maintenant)
    if instant is None:
        raise ValueError(f"{fraicheur_mesures.REJ_MAINTENANT_INVALIDE} : maintenant illisible ({maintenant!r})")
    tous = episodes(registre)
    en_cours = episodes_en_cours(tous)
    par_regle = {r["id"]: r for r in regles["regles"]}
    par_mesure = {m["metric_id"]: m for m in mesures}
    depuis = instant - timedelta(hours=24)
    deja = sum(1 for e in tous.values() if (o := _instant(e["ouverte_le"])) is not None and o > depuis)
    ouvertures: list[dict[str, Any]] = []
    resolutions: list[dict[str, Any]] = []
    bornees = inchangees = 0
    for verdict in verdicts:
        cle = (verdict["regle"], verdict["metric_id"])
        courant = en_cours.get(cle)
        if verdict["etat"] == ETAT_FRANCHI and courant is None:
            if deja + len(ouvertures) >= OUVERTURES_PAR_JOUR_MAX:
                bornees += 1
                continue
            regle, mesure = par_regle[verdict["regle"]], par_mesure[verdict["metric_id"]]
            numero = _prochain_episode(tous, *cle)
            ouvertures.append(_entree_ouverte(regles, regle, mesure, verdict, numero, maintenant))
            # un épisode ouvert dans CETTE évaluation compte pour la suite (deux verdicts d'une même clé ne se voient
            # pas)
            tous[ouvertures[-1]["alerte_id"]] = {**ouvertures[-1], "resolue_le": None}
            en_cours[cle] = tous[ouvertures[-1]["alerte_id"]]
        elif verdict["etat"] == ETAT_DANS_LA_CIBLE and courant is not None:
            resolutions.append({
                "type_entree": TYPE_RESOLUE, "alerte_id": courant["alerte_id"], "resolue_le": maintenant,
                "motif": "retour_dans_la_cible",
            })
            tous[courant["alerte_id"]]["resolue_le"] = maintenant
            del en_cours[cle]
        else:
            inchangees += 1
    return {"ouvertures": ouvertures, "resolutions": resolutions, "bornees": bornees, "inchangees": inchangees}


# ---------------------------------------------------------------------------
# Les gestes : accuser, reporter
# ---------------------------------------------------------------------------
def lire_identifiant(brut: Any) -> str:
    """Un identifiant d'alerte lu, ou un refus nommé : ``ALERTE-…:m8_…:N`` (jamais un chemin, jamais du texte libre)."""
    if not isinstance(brut, str) or _ID_ALERTE.fullmatch(brut) is None:
        raise AlertesRefusees(REJ_ALERTE_IDENTIFIANT, "ALERTE-…:m8_…:N attendu")
    return brut


def _episode_vivant(registre: list[dict[str, Any]], alerte_id: str) -> dict[str, Any]:
    episode = episodes(registre).get(alerte_id)
    if episode is None:
        raise AlertesRefusees(REJ_ALERTE_INCONNUE, "aucune alerte de cet identifiant au registre")
    if episode["resolue_le"] is not None:
        raise AlertesRefusees(
            REJ_ALERTE_RESOLUE, "cette alerte est résolue : il n'y a plus rien à accuser ni à reporter"
        )
    return episode


def accuser(registre: list[dict[str, Any]], alerte_id: str, maintenant: str, par: str) -> dict[str, Any] | None:
    """L'entrée ``alerte_accusee`` à ranger, ou ``None`` si l'alerte est déjà accusée (un double accusé n'écrit rien).
    L'accusé dit « vu » : l'alerte sort de « À voir » mais l'épisode reste ouvert jusqu'au retour dans la cible."""
    identifiant = lire_identifiant(alerte_id)
    if _instant(maintenant) is None:
        raise ValueError(f"{fraicheur_mesures.REJ_MAINTENANT_INVALIDE} : maintenant illisible ({maintenant!r})")
    episode = _episode_vivant(registre, identifiant)
    if statut_effectif(episode, maintenant) == STATUT_ACCUSEE:
        return None
    return {"type_entree": TYPE_ACCUSEE, "alerte_id": identifiant, "accusee_le": maintenant, "par": par}


def reporter(
    registre: list[dict[str, Any]], alerte_id: str, maintenant: str, jusqu_au: Any, par: str
) -> dict[str, Any]:
    """L'entrée ``alerte_reportee`` à ranger : l'alerte est cachée jusqu'à ``jusqu_au`` (un instant RFC 3339 avec
    fuseau, dans le futur, au plus ``REPORT_MAX_JOURS`` jours) puis redevient visible. Un report plus lointain, passé
    ou illisible
    est refusé, jamais corrigé."""
    identifiant = lire_identifiant(alerte_id)
    instant = _instant(maintenant)
    if instant is None:
        raise ValueError(f"{fraicheur_mesures.REJ_MAINTENANT_INVALIDE} : maintenant illisible ({maintenant!r})")
    episode = _episode_vivant(registre, identifiant)
    fin = _instant(jusqu_au)
    if fin is None or not instant < fin <= instant + timedelta(days=REPORT_MAX_JOURS):
        raise AlertesRefusees(
            REJ_ALERTE_REPORT, f"jusqu_au : un instant avec fuseau, dans le futur, au plus {REPORT_MAX_JOURS} jours"
        )
    del episode
    return {"type_entree": TYPE_REPORTEE, "alerte_id": identifiant, "reportee_le": maintenant, "jusqu_au": jusqu_au,
            "par": par}


# ---------------------------------------------------------------------------
# Les lectures : l'état des règles, la liste des alertes, « À voir »
# ---------------------------------------------------------------------------
def etat_des_regles(
    regles: dict[str, Any], verdicts: list[dict[str, Any]], seuils_lus: dict[str, Any]
) -> list[dict[str, Any]]:
    """Une ligne par règle : combien de mesures franchies, dans la cible, non évaluées (avec les raisons), et si le
    seuil attendu de la direction est déclaré, à configurer ou invalide. Aucune valeur de mesure."""
    lignes = []
    for regle in regles["regles"]:
        propres = [v for v in verdicts if v["regle"] == regle["id"]]
        raisons = sorted({v["raison"] for v in propres if v["etat"] == ETAT_NON_EVALUEE})
        ligne: dict[str, Any] = {
            "regle": regle["id"],
            "genre": regle["genre"],
            "gravite": regle["gravite"],
            "libelle": regle["libelle"],
            "franchies": sum(1 for v in propres if v["etat"] == ETAT_FRANCHI),
            "dans_la_cible": sum(1 for v in propres if v["etat"] == ETAT_DANS_LA_CIBLE),
            "non_evaluees": sum(1 for v in propres if v["etat"] == ETAT_NON_EVALUEE),
            "raisons_non_evaluee": raisons,
        }
        if regle["genre"] == "seuil":
            nom = regle["reglage"]
            ligne["mesure"] = regle["mesure"]
            ligne["sens"] = regle["sens"]
            ligne["seuil"] = (
                "declare" if nom in seuils_lus["seuils"] else
                "invalide" if nom in seuils_lus["invalides"] else "a_configurer"
            )
            ligne["reglage"] = f"configuration.alertes.seuils.{nom}"
        lignes.append(ligne)
    return lignes


def vue_episode(episode: dict[str, Any], maintenant: str) -> dict[str, Any]:
    """Un épisode tel que la lecture le rend : l'alerte (courant, référence, action, département, mesures liées),
    son état effectif et ses gestes. Aucune clé de cause."""
    return {
        "alerte_id": episode["alerte_id"],
        "statut": statut_effectif(episode, maintenant),
        "regle": episode["regle"],
        "metric_id": episode["metric_id"],
        "episode": episode["episode"],
        "gravite": episode["gravite"],
        "type_alerte": episode["type_alerte"],
        "quoi": episode["quoi"],
        "pourquoi": episode["pourquoi"],
        "courant": {"valeur": episode["courant"], "unite": episode["unite"]},
        "reference": {"sens": episode["sens"], "seuil": episode["seuil"], "unite": episode["unite"]},
        "action_recommandee": episode["action"],
        "departement_proprietaire": episode["departement"],
        "mesures_liees": list(episode["mesures_liees"]),
        "ouverte_le": episode["ouverte_le"],
        "reporte_jusqu_au": episode["reporte_jusqu_au"],
        "resolue_le": episode["resolue_le"],
        "gestes": list(episode["gestes"]),
    }


def attentes(registre: list[dict[str, Any]], maintenant: str) -> list[dict[str, Any]]:
    """Les alertes à mettre dans « À voir » du propriétaire (``approbations.CHAMPS_ATTENTE``) : celles qui sont
    OUVERTES (ni accusées, ni reportées, ni résolues). Le résumé ne porte aucun montant : la valeur se lit dans la
    lecture des alertes.
    Niveau N3 pour une alerte critique, N2 sinon ; rien ne sort de l'application."""
    items = []
    for episode in episodes(registre).values():
        if statut_effectif(episode, maintenant) != STATUT_OUVERTE:
            continue
        items.append(
            {
                "type": "alerte_metier",
                "id": episode["alerte_id"],
                "resume": f"{episode['quoi']} Propriétaire : {episode['departement']}.",
                "niveau": "N3" if episode["gravite"] == "critique" else "N2",
                "depuis": episode["ouverte_le"],
                "action_proposee": "examiner",
            }
        )
    return items


__all__ = [
    "ETAT_DANS_LA_CIBLE",
    "ETAT_FRANCHI",
    "ETAT_NON_EVALUEE",
    "EVENEMENT",
    "NOM_REGISTRE",
    "OUVERTURES_PAR_JOUR_MAX",
    "REJ_ALERTE_IDENTIFIANT",
    "REJ_ALERTE_INCONNUE",
    "REJ_ALERTE_REPORT",
    "REJ_ALERTE_RESOLUE",
    "REJ_ALERTES_ILLISIBLES",
    "REJ_ALERTES_INVALIDES",
    "REPORT_MAX_JOURS",
    "SCHEMA",
    "STATUT_ACCUSEE",
    "STATUT_OUVERTE",
    "STATUT_REPORTEE",
    "STATUT_RESOLUE",
    "AlertesRefusees",
    "accuser",
    "attentes",
    "charge_evenement",
    "charger",
    "episodes",
    "etat_des_regles",
    "evaluer",
    "franchit",
    "lire_identifiant",
    "lire_seuils",
    "planifier",
    "reglages_declares",
    "reporter",
    "statut_effectif",
    "valider",
    "vue_episode",
]
