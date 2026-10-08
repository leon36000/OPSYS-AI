"""Recherche littérale bornée des projections métier visibles d'une affaire.

Module pur : deux snapshots par lecture, aucune écriture, aucun agent fourni par l'appelant.
La borne de sources s'applique après la copie, pas à l'allocation de Registre.lire.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from datetime import date, datetime
from typing import Any

from . import affaire, amont, classification, confidentialite, contexte, etapes, paquets, registre, validation

PLAFOND_LIGNES = 10000
BORNE_CARACTERES = 5400
_TYPES = frozenset(etapes.types_consommes()) | {classification.TYPE_WCT, classification.TYPE_VARIANCE}
_NIVEAUX = frozenset({"PUBLIC_INTERNAL", "INTERNAL"})
_HASH = re.compile(r"[0-9a-f]{64}")
_INSTANT = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:[.,][0-9]+)?(?:Z|[+-]([0-9]{2}):([0-9]{2}))"
)
_DETAILS = {
    "ARGUMENTS-INVALIDES": "les arguments sortent du contrat de recherche par affaire",
    "REGISTRE-INVALIDE": "un registre métier ne satisfait pas son contrat d'intégrité",
    "BORNE-SOURCES": "les snapshots métier dépassent la borne de traitement de 10000 lignes",
    "PROJECTION-INVALIDE": "une projection métier ou sa provenance ne satisfait pas le contrat",
    "SORTIE-TROP-VOLUMINEUSE": "la page dépasse la borne de sortie ; aucun détail partiel n'est transmis",
}


class _Refus(ValueError):
    def __init__(self, suffixe: str):
        self.suffixe = suffixe


def _texte(valeur: Any, maximum: int, *, vide: bool = False) -> bool:
    return (
        isinstance(valeur, str)
        and (vide or bool(valeur))
        and len(valeur) <= maximum
        and not any(unicodedata.category(c) in {"Cc", "Cs"} for c in valeur)
    )


def _instant(valeur: Any) -> datetime:
    if not _texte(valeur, 64):
        raise ValueError("instant")
    forme = _INSTANT.fullmatch(valeur)
    if forme is None or (forme[1] is not None and (int(forme[1]) >= 24 or int(forme[2]) >= 60)):
        raise ValueError("forme partagée avec le lecteur")
    instant = datetime.fromisoformat(valeur)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("fuseau")
    return instant


def _valider_snapshot(maillons: Any) -> None:
    try:
        if not isinstance(maillons, list):
            raise ValueError("snapshot")
        ids = set()
        for m in maillons:
            if not isinstance(m, dict) or not isinstance(m.get("ligne_id"), str) or not _HASH.fullmatch(m["ligne_id"]):
                raise ValueError("identifiant")
            if m["ligne_id"] in ids or m.get("type_entree") not in registre._TYPE_ENTREE_VALIDES:
                raise ValueError("type ou doublon")
            ids.add(m["ligne_id"])
            _instant(m.get("horodatage"))
        if not registre.Registre(maillons=maillons).valider_chaine()[0]:
            raise ValueError("chaine")
    except (KeyError, TypeError, ValueError, OverflowError):
        raise _Refus("REGISTRE-INVALIDE") from None


def _dans_corpus(m: dict) -> bool:
    # Exclusion avant classification : une charge hybride ne peut masquer le financier
    # derrière le discriminant variance/WCT, ni derrière un marquage manquant.
    type_declare = m.get("type_evenement")
    if (
        "marge_reelle_cad" in m
        or type_declare == classification.TYPE_RENTABILITE
        or (isinstance(type_declare, str) and type_declare.endswith(etapes.SUFFIXE_MONTANTS))
    ):
        return False
    return classification.type_evenement(m) in _TYPES


def _valider_evenement(m: dict) -> None:
    """Les champs utilisés par l'index et la projection, pas la charge brute complète."""
    identifiant = classification.identifiant(m)
    if not _texte(identifiant, 256):
        raise _Refus("PROJECTION-INVALIDE")
    type_ = classification.type_evenement(m)
    if type_ != classification.TYPE_VARIANCE and not affaire.valide(m.get("lead_id")):
        raise _Refus("PROJECTION-INVALIDE")
    if type_ == classification.TYPE_WCT:
        duree = m.get("duree_reelle_minutes")
        if type(duree) not in (int, float) or not math.isfinite(duree) or duree < 0:
            raise _Refus("PROJECTION-INVALIDE")
        if "ecart_signale" in m and type(m["ecart_signale"]) is not bool:
            raise _Refus("PROJECTION-INVALIDE")
    elif type_ == classification.TYPE_VARIANCE:
        if not _texte(m.get("wct_id"), 256) or not _texte(m.get("statut_variance"), 256):
            raise _Refus("PROJECTION-INVALIDE")
        if "signal_critique" in m and type(m["signal_critique"]) is not bool:
            raise _Refus("PROJECTION-INVALIDE")
    else:
        # Seuls ces champs entrent dans les résumés canoniques d'étape.
        champs = {
            etapes.TYPE_LEAD_QUALIFIE: ("service", "canal"),
            etapes.TYPE_CLIENT_ASSOCIE: ("client_id",),
            etapes.TYPE_DEVIS_ENVOYE: ("devis_id",),
            etapes.TYPE_DEVIS_ACCEPTE: ("devis_id",),
            etapes.TYPE_DEVIS_SANS_REPONSE: ("devis_id", "statut", "depuis"),
        }[type_]
        if any(not _texte(m.get(c), 256) for c in champs):
            raise _Refus("PROJECTION-INVALIDE")
        if m.get("chantier_id") is not None and not _texte(m["chantier_id"], 256):
            raise _Refus("PROJECTION-INVALIDE")
        if type_ == etapes.TYPE_LEAD_QUALIFIE and type(m.get("urgence_declaree")) is not bool:
            raise _Refus("PROJECTION-INVALIDE")
        if type_ == etapes.TYPE_DEVIS_SANS_REPONSE:
            _instant(m["depuis"])
            if type(m.get("delai_relance_jours")) is not int or m["delai_relance_jours"] < 1:
                raise _Refus("PROJECTION-INVALIDE")


def _dernieres_consolidations(affaire_id: str, maillons: list[dict]) -> list[dict]:
    derniers = {}
    for m in maillons:
        if m["type_entree"] != "fait_consolide" or m.get("affaire_id") != affaire_id:
            continue
        jour = m.get("jour")
        if (
            not _texte(jour, 10)
            or date.fromisoformat(jour).isoformat() != jour
            or m.get("cle_consolidation") != f"{affaire_id}:{jour}"
        ):
            raise _Refus("PROJECTION-INVALIDE")
        derniers[m["cle_consolidation"]] = m
    return list(derniers.values())


def _consolidations_admises(
    affaire_id: str, derniers: list[dict], evenements: list[dict], visibles: list[dict]
) -> list[dict]:
    par_id = {m["ligne_id"]: m for m in evenements}
    ids_corpus_visible = {m["ligne_id"] for m in visibles}
    ids_visibles = {m["ligne_id"] for m in classification.evenements_de_laffaire(affaire_id, visibles)}
    index_visible = classification.index_lead_id_par_wct_id(visibles)
    admis = []
    for m in derniers:
        sources = m.get("sources")
        if not isinstance(sources, list) or not sources:
            raise _Refus("PROJECTION-INVALIDE")
        toute_visible = True
        ids = set()
        for source in sources:
            if not isinstance(source, dict) or set(source) != {"registre", "ligne_id", "type_evenement", "identifiant"}:
                raise _Refus("PROJECTION-INVALIDE")
            ligne_id = source["ligne_id"]
            if (
                source["registre"] != "evenements"
                or not isinstance(ligne_id, str)
                or ligne_id not in par_id
                or ligne_id in ids
            ):
                raise _Refus("PROJECTION-INVALIDE")
            ids.add(ligne_id)
            evenement = par_id[ligne_id]
            if source["type_evenement"] != classification.type_evenement(evenement) or source[
                "identifiant"
            ] != classification.identifiant(evenement):
                raise _Refus("PROJECTION-INVALIDE")
            if ligne_id in ids_corpus_visible and classification.lead_id(evenement, index_visible) != affaire_id:
                raise _Refus("PROJECTION-INVALIDE")
            toute_visible = toute_visible and ligne_id in ids_visibles
        if confidentialite.niveau_de(m) in _NIVEAUX and toute_visible:
            if not _texte(m.get("resume"), 10000, vide=True):
                raise _Refus("PROJECTION-INVALIDE")
            admis.append(m)
    return admis


def _projection(fait: dict, maillon: dict, genre: str, affaire_id: str) -> dict:
    if (
        not _texte(fait.get("identifiant"), 256)
        or not _texte(fait.get("source"), 256)
        or not _texte(fait.get("resume"), 200, vide=True)
        or fait.get("confidentialite") not in _NIVEAUX
    ):
        raise _Refus("PROJECTION-INVALIDE")
    return {
        "genre": genre,
        "affaire_id": affaire_id,
        **{c: fait[c] for c in ("identifiant", "horodatage", "source", "resume", "confidentialite")},
        "reference": {
            "ligne_id": maillon["ligne_id"],
            "registre": "evenements" if genre == "evenement" else "affaires",
            "hash_tete": maillon["ligne_id"],
        },
    }


def _mesurer(dto: dict) -> int:
    dto["taille_caracteres"] = 0
    while True:
        taille = len(json.dumps({"ok": True, "resultat": dto}, ensure_ascii=False))
        if taille == dto["taille_caracteres"]:
            return taille
        dto["taille_caracteres"] = taille


def rechercher(
    affaire_id: str, requete: str, limite: int, decalage: int, registre_evenements: Any, registre_affaires: Any
) -> dict[str, Any]:
    """Enveloppe DIRECTE métier ; les références citent la tête de leur préfixe réel."""
    try:
        if (
            not affaire.valide(affaire_id)
            or not _texte(requete, 200, vide=True)
            or type(limite) is not int
            or not 1 <= limite <= 8
            or type(decalage) is not int
            or not 0 <= decalage <= PLAFOND_LIGNES
        ):
            raise _Refus("ARGUMENTS-INVALIDES")
        requete = unicodedata.normalize("NFC", requete)
        # Copie des deux registres une fois, même si la première source dépasse la borne.
        try:
            evenements, affaires = registre_evenements.lire(), registre_affaires.lire()
        except Exception:
            # Une erreur de copie/JSON du stockage ne publie jamais son texte source.
            raise _Refus("REGISTRE-INVALIDE") from None
        if not isinstance(evenements, list) or not isinstance(affaires, list):
            raise _Refus("REGISTRE-INVALIDE")
        if len(evenements) + len(affaires) > PLAFOND_LIGNES:
            raise _Refus("BORNE-SOURCES")
        _valider_snapshot(evenements)
        _valider_snapshot(affaires)
        try:
            visibles = [m for m in evenements if _dans_corpus(m) and confidentialite.niveau_de(m) in _NIVEAUX]
            for m in visibles:
                _valider_evenement(m)
            de_l_affaire = classification.evenements_de_laffaire(affaire_id, visibles)
            consolides = _consolidations_admises(
                affaire_id, _dernieres_consolidations(affaire_id, affaires), evenements, visibles
            )
            par_id_affaires = {m["ligne_id"]: m for m in consolides}
            projections = [_projection(paquets._fait_evenement(m), m, "evenement", affaire_id) for m in de_l_affaire]
            projections += [
                _projection(f, par_id_affaires[f["identifiant"]], "fait_consolide", affaire_id)
                for f in paquets._candidats_faits_affaire(affaire_id, consolides)
            ]
        except (KeyError, TypeError, ValueError, OverflowError) as erreur:
            if isinstance(erreur, _Refus):
                raise
            raise _Refus("PROJECTION-INVALIDE") from None
        situation = amont.situation(affaire_id, visibles)
        if consolides and not situation["connue"]:
            situation.update(connue=True, verdict=amont.AMONT_ORIGINE_NON_RECUE)
        needle = requete.casefold()
        matches = [
            p
            for p in projections
            if any(needle in unicodedata.normalize("NFC", p[c]).casefold() for c in ("identifiant", "source", "resume"))
        ]
        matches.sort(key=lambda p: (p["genre"], p["reference"]["ligne_id"]))
        matches.sort(key=lambda p: _instant(p["horodatage"]), reverse=True)
        total = len(matches)
        resultats = matches[decalage : decalage + limite]
        dto = {
            "affaire_id": affaire_id,
            "requete": requete,
            "mode": "litteral_nfc_casefold_v1",
            "corpus": "evenements_et_consolidations_affaire_v1",
            "resultats": resultats,
            "affaire": situation,
            "pagination": {},
            "couverture": {
                "projections": "resume_200_caracteres",
                "sources_parcourues": "completes",
                "historique_consolidations": "derniere_version_par_cle",
                "hors_corpus": [
                    "decisions_globales",
                    "revisions",
                    "signaux_traitements",
                    "developpement",
                    "documents_generiques",
                ],
                "plafond_lignes": PLAFOND_LIGNES,
            },
            "confidentialite": {"agent": None, "regle": "v1", "niveaux": ["PUBLIC_INTERNAL", "INTERNAL"]},
            "borne_caracteres": BORNE_CARACTERES,
            "taille_caracteres": 0,
        }
        while True:
            affichees = len(resultats)
            reste = max(0, total - decalage - affichees)
            dto["pagination"] = {
                "decalage": decalage,
                "limite": limite,
                "affichees": affichees,
                "total": total,
                "suivant": decalage + affichees if reste else None,
                "reste": reste,
                "courante": True,
            }
            if _mesurer(dto) <= BORNE_CARACTERES:
                # Seules les citations de la page construisent leur préfixe ; la tête
                # globale peut contenir des lignes privées et n'est jamais publiée.
                snapshots = {"evenements": evenements, "affaires": affaires}
                positions = {nom: {m["ligne_id"]: i for i, m in enumerate(ms)} for nom, ms in snapshots.items()}
                for p in resultats:
                    nom = p["reference"]["registre"]
                    i = positions[nom][p["reference"]["ligne_id"]]
                    p["reference"] = contexte.construire_reference(
                        snapshots[nom][i], nom, registre.Registre(maillons=snapshots[nom][: i + 1])
                    )
                return dto
            if not resultats or len(resultats) == 1:
                raise _Refus("SORTIE-TROP-VOLUMINEUSE")
            resultats.pop()
    except _Refus as refus:
        return {
            "accepte": False,
            "verdict": validation.construire_verdict("REJ-RECHERCHE-AFFAIRE-" + refus.suffixe, _DETAILS[refus.suffixe]),
        }
