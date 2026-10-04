"""Lecteur borné des observations Growth déclarées, sans plan ni mutation."""

from __future__ import annotations

import datetime as dt
import hashlib
import math
import re
from typing import Any

from sqlalchemy import Connection, func, select

from opsys.stockage import codec
from opsys.stockage.schema import REGISTRES

from . import growth

DEPARTEMENT = "m07-marketing"
REGISTRE = "growth"
LIMITE_MAILLONS = 1000
LIMITE_CARACTERES = 1024 * 1024
LIMITE_PAR_MAILLON = 32 * 1024
LIMITE_JOURS_PERIODE = 366
LIMITE_PAGE = 100
LIMITE_DECALAGE = 1000

_ORDRE_CHAMPS_CHARGE = (
    "observation_id", "metrique", "valeur", "unite", "periode", "plateforme", "campagne", "source", "preuve",
    "confiance",
)
_CHAMPS_CHARGE = frozenset(_ORDRE_CHAMPS_CHARGE)
_LONGUEURS_CHAMPS = {
    "observation_id": 128,
    "metrique": 128,
    "unite": 64,
    "plateforme": 64,
    "campagne": 128,
    "source": 2048,
    "preuve": 2048,
}
_LIMITES = [
    "Les observations restent déclarées et non vérifiées à l’extérieur; l'auteur historique est inconnu.",
    "Une provenance console identifie la personne ayant saisi la déclaration, sans authentifier sa source.",
    "La preuve est une référence textuelle seulement; aucun accès réseau ni CAS ne la vérifie.",
    "La confiance affichée est déclarée; coûts, conversions, projections et ROI restent inconnus et non calculés.",
    "Les observations sont incluses seulement si leur période entière est dans le filtre fermé inclusif.",
    "Les anciens plans de 30 jours sont ignorés; aucune recommandation n’est générée.",
]
_MESSAGE_VIDE = "aucune observation enregistrée pour ce filtre; pas preuve de zéro activité"


class GrowthLectureErreur(ValueError):
    """Refus nommé d'une lecture Growth invalide, corrompue ou hors budget."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def lire(
    cnx: Connection,
    *,
    debut: str,
    fin: str,
    decalage: int = 0,
    limite: int = 25,
) -> dict[str, Any]:
    """Lit les observations dont la période est entièrement contenue dans `[debut, fin]`.

    La base est bornée en SQL avant le décodage des maillons. Chaque observation et son empreinte sont
    validées, y compris les observations hors période, avant le calcul des comptes et la pagination.
    """
    date_debut = _date_iso(debut, "debut")
    date_fin = _date_iso(fin, "fin")
    if date_fin < date_debut:
        raise GrowthLectureErreur("GROWTH-PERIODE-INVALIDE", "fin doit être égale ou postérieure à debut")
    if (date_fin - date_debut).days + 1 > LIMITE_JOURS_PERIODE:
        raise GrowthLectureErreur("GROWTH-PERIODE-TROP-LONGUE", "la période demandée dépasse 366 jours")
    if type(decalage) is not int or not 0 <= decalage <= LIMITE_DECALAGE:
        raise GrowthLectureErreur("GROWTH-PAGINATION-INVALIDE", "decalage doit être un entier de 0 à 1000")
    if type(limite) is not int or not 1 <= limite <= LIMITE_PAGE:
        raise GrowthLectureErreur("GROWTH-PAGINATION-INVALIDE", "limite doit être un entier de 1 à 100")

    textes, tete = lire_prefixe(cnx)

    toutes = decoder_prefixe(textes)
    observations = []
    hors_periode = 0
    for observation in toutes:
        obs_debut, obs_fin = _date_periode(observation["periode"])
        if obs_debut < date_debut or obs_fin > date_fin:
            hors_periode += 1
        else:
            observations.append(observation)

    total_periode = len(observations)
    page = observations[decalage : decalage + limite]
    suivant = decalage + len(page) if decalage + len(page) < total_periode else None
    return {
        "statut": "OBSERVATIONS_DECLAREES",
        "message": None if total_periode else _MESSAGE_VIDE,
        "periode": {"debut": debut, "fin": fin},
        "observations": page,
        "total_observations": len(toutes),
        "tete": tete,
        "total_periode": total_periode,
        "hors_periode": hors_periode,
        "decalage": decalage,
        "limite": limite,
        "suivant": suivant,
        "tronque": suivant is not None,
        "limites": list(_LIMITES),
    }


def lire_prefixe(cnx: Connection) -> tuple[list[str], dict[str, Any]]:
    """Bornes SQL avant transfert; tête du préfixe brut, sans cache ni instantané multipages."""
    filtre = (REGISTRES.c.departement == DEPARTEMENT) & (REGISTRES.c.registre == REGISTRE)
    stats = cnx.execute(
        select(
            func.count().label("nombre"),
            func.coalesce(func.sum(func.length(REGISTRES.c.maillon)), 0).label("caracteres"),
            func.coalesce(func.max(func.length(REGISTRES.c.maillon)), 0).label("max_maillon"),
            func.max(REGISTRES.c.rang).label("rang_max"),
        ).where(filtre)
    ).one()
    _verifier_bornes_sql(stats.nombre, stats.caracteres, stats.max_maillon)
    if stats.rang_max is not None and stats.rang_max != stats.nombre - 1:
        raise GrowthLectureErreur("GROWTH-RANGS-INVALIDES", "préfixe canonique non contigu")

    # Le rang maximal fige le préfixe observé; SUBSTR borne chaque charge transférée avant son décodage.
    textes = [] if stats.rang_max is None else cnx.execute(
        select(func.substr(REGISTRES.c.maillon, 1, LIMITE_PAR_MAILLON + 1))
        .where(filtre & (REGISTRES.c.rang <= stats.rang_max))
        .order_by(REGISTRES.c.rang)
        .limit(LIMITE_MAILLONS + 1)
    ).scalars().all()
    if len(textes) != stats.nombre:
        raise GrowthLectureErreur("GROWTH-REGISTRE-CHANGE", "le registre a changé pendant la lecture bornée")
    caracteres_lus = 0
    for texte in textes:
        if not isinstance(texte, str):
            raise GrowthLectureErreur("GROWTH-MAILLON-INVALIDE", "un maillon n'est pas un texte JSON")
        taille = len(texte)
        if taille > LIMITE_PAR_MAILLON:
            raise GrowthLectureErreur("GROWTH-LIMITE-MAILLON", "un maillon dépasse 32 Ki caractères")
        caracteres_lus += taille
    if caracteres_lus > LIMITE_CARACTERES:
        raise GrowthLectureErreur("GROWTH-LIMITE-REGISTRE", "le registre dépasse 1 Mi caractères")

    digest = hashlib.sha256()
    for texte in textes:
        octets = texte.encode("utf-8")
        digest.update(len(octets).to_bytes(8, "big"))
        digest.update(octets)
    return textes, {"rang": stats.nombre, "empreinte": digest.hexdigest()}


def decoder_prefixe(textes: list[str]) -> list[dict[str, Any]]:
    """Valide tous les maillons, plans historiques compris, avant tout filtre ou ajout."""
    ids_vus: set[str] = set()
    observations = []
    for texte in textes:
        try:
            maillon = codec.decoder(texte)
        except (TypeError, ValueError, UnicodeError, ArithmeticError, AttributeError, RecursionError) as exc:
            raise GrowthLectureErreur("GROWTH-MAILLON-INVALIDE", "un maillon JSON est illisible") from exc
        if not isinstance(maillon, dict):
            raise GrowthLectureErreur("GROWTH-MAILLON-INVALIDE", "un maillon décodé n'est pas un objet")
        if maillon.get("type") == "plan_growth_30j":
            if set(maillon) != {"type", "horizon_debut", "recommandations", "donnees_manquantes", "limites"}:
                raise GrowthLectureErreur("GROWTH-PLAN-INVALIDE", "forme de plan historique inattendue")
            continue
        if maillon.get("type") != "observation":
            raise GrowthLectureErreur("GROWTH-MAILLON-INCONNU", "type de maillon Growth non pris en charge")
        charge = _valider_observation(maillon)
        observation_id = charge["observation_id"]
        if observation_id in ids_vus:
            raise GrowthLectureErreur("GROWTH-ID-DUPLIQUE", "un observation_id apparaît plusieurs fois")
        ids_vus.add(observation_id)
        provenance = charge.get("provenance")
        observations.append({
            **charge,
            "empreinte": maillon["empreinte"],
            "statut_source": "DECLAREE_NON_VERIFIEE",
            "auteur": provenance["auteur"] if provenance is not None else None,
            "verification_externe": None,
        })
    return observations


def _verifier_bornes_sql(nombre: int, caracteres: int, max_maillon: int) -> None:
    if nombre > LIMITE_MAILLONS:
        raise GrowthLectureErreur("GROWTH-LIMITE-NOMBRE", "le registre dépasse 1000 maillons")
    if caracteres > LIMITE_CARACTERES:
        raise GrowthLectureErreur("GROWTH-LIMITE-REGISTRE", "le registre dépasse 1 Mi caractères")
    if max_maillon > LIMITE_PAR_MAILLON:
        raise GrowthLectureErreur("GROWTH-LIMITE-MAILLON", "un maillon dépasse 32 Ki caractères")


def _date_iso(valeur: Any, nom: str) -> dt.date:
    if not isinstance(valeur, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", valeur) is None:
        raise GrowthLectureErreur("GROWTH-DATE-INVALIDE", f"{nom} doit suivre AAAA-MM-JJ")
    try:
        date = dt.date.fromisoformat(valeur)
    except ValueError as exc:
        raise GrowthLectureErreur("GROWTH-DATE-INVALIDE", f"{nom} n'est pas une date civile valide") from exc
    if date.isoformat() != valeur:
        raise GrowthLectureErreur("GROWTH-DATE-INVALIDE", f"{nom} doit être canonique")
    return date


def _date_periode(periode: Any) -> tuple[dt.date, dt.date]:
    if not isinstance(periode, dict) or set(periode) != {"debut", "fin"}:
        raise GrowthLectureErreur("GROWTH-OBSERVATION-INVALIDE", "periode doit contenir debut et fin")
    debut = _date_iso(periode.get("debut"), "periode.debut")
    fin = _date_iso(periode.get("fin"), "periode.fin")
    if fin < debut:
        raise GrowthLectureErreur("GROWTH-OBSERVATION-INVALIDE", "fin de période antérieure à debut")
    return debut, fin


def _valider_observation(maillon: dict[str, Any]) -> dict[str, Any]:
    champs_v1 = _CHAMPS_CHARGE | {"type", "empreinte"}
    version2 = set(maillon) == champs_v1 | {"schema_version", "provenance"}
    if set(maillon) != champs_v1 and not version2:
        raise GrowthLectureErreur("GROWTH-OBSERVATION-INVALIDE", "champs d'observation inattendus ou absents")
    charge = {cle: maillon[cle] for cle in _ORDRE_CHAMPS_CHARGE}
    if version2:
        provenance = maillon["provenance"]
        if (type(maillon["schema_version"]) is not int or maillon["schema_version"] != 2
                or not isinstance(provenance, dict)
                or set(provenance) != {"mode", "auteur", "role", "horodatage"}
                or provenance.get("mode") != "saisie_humaine_console"
                or not isinstance(provenance.get("role"), str)
                or provenance["role"] not in {"admin", "nathan_owner"}
                or not isinstance(provenance.get("auteur"), str)
                or not 1 <= len(provenance["auteur"]) <= 64 or not provenance["auteur"].strip()):
            raise GrowthLectureErreur("GROWTH-PROVENANCE-INVALIDE", "forme de provenance humaine invalide")
        try:
            horodatage = dt.datetime.fromisoformat(provenance["horodatage"])
            if horodatage.tzinfo is None or horodatage.utcoffset() != dt.timedelta(0):
                raise ValueError
        except (TypeError, ValueError, KeyError) as exc:
            raise GrowthLectureErreur("GROWTH-PROVENANCE-INVALIDE", "horodatage serveur UTC requis") from exc
        charge.update(schema_version=2, provenance=dict(provenance))
    for champ, maximum in _LONGUEURS_CHAMPS.items():
        valeur = charge.get(champ)
        if not isinstance(valeur, str) or not valeur.strip() or len(valeur) > maximum:
            raise GrowthLectureErreur("GROWTH-OBSERVATION-INVALIDE", f"champ {champ} absent ou mal formé")
    valeur = charge.get("valeur")
    if type(valeur) not in {int, float} or (type(valeur) is float and not math.isfinite(valeur)):
        raise GrowthLectureErreur("GROWTH-OBSERVATION-INVALIDE", "valeur doit être un nombre fini")
    confiance = charge.get("confiance")
    if (
        type(confiance) not in {int, float}
        or (type(confiance) is float and not math.isfinite(confiance))
        or not 0 <= confiance <= 1
    ):
        raise GrowthLectureErreur(
            "GROWTH-OBSERVATION-INVALIDE",
            "confiance déclarée doit être finie et comprise entre 0 et 1",
        )
    _date_periode(charge.get("periode"))
    empreinte = maillon.get("empreinte")
    if not isinstance(empreinte, str):
        raise GrowthLectureErreur("GROWTH-EMPREINTE-INVALIDE", "empreinte absente")
    try:
        empreinte_attendue = growth._empreinte(charge)
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        raise GrowthLectureErreur("GROWTH-OBSERVATION-INVALIDE", "charge non canonique") from exc
    if empreinte != empreinte_attendue:
        raise GrowthLectureErreur("GROWTH-EMPREINTE-INVALIDE", "empreinte de charge divergente")
    return charge
