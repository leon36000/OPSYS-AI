"""Lectures M6 appareil pures : références natives, pertes/bris et faits publiés.

Les snapshots et la validation catalogue sont fournis par l'adaptateur outils. Aucun accès
stockage, aucune écriture, aucune horloge ; la borne s'applique après les copies des sources.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from datetime import datetime
from decimal import Decimal
from typing import Any

from . import encodage, registre

PLAFOND_LIGNES = 10000
BORNE_CARACTERES = 5400
# Ordre de présentation des quatre publications existantes, sans nouvelle taxonomie.
_ORDRE_HISTORIQUE = ("seuil_absent", "prevu_absent", "declaration_absente", "evaluee")
_DECLARATION = frozenset({"CONSOMMATION", "RETOUR", "PERTE", "BRIS"})
_HASH = re.compile(r"[0-9a-f]{64}")
_INSTANT = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:[.,][0-9]+)?(?:Z|[+-]([0-9]{2}):([0-9]{2}))"
)
_DETAILS = {
    "ARGUMENTS-INVALIDES": "les arguments sortent du contrat de lecture M6 appareil",
    "REGISTRE-INVALIDE": "un snapshot métier ne satisfait pas son contrat d’intégrité",
    "SOURCE-INVALIDE": "une publication ou une source reçue ne satisfait pas le contrat",
    "SOURCE-PUBLIEE-ABSENTE": "un WCT reçu ne possède pas sa publication M4 canonique",
    "EMPREINTE-RECUE-ABSENTE": "un reçu ancien sans empreinte complète ne permet pas une sélection certifiée",
    "LIAISON-INCOHERENTE": "les sources ne concordent pas pour le WCT sélectionné",
    "WCT-INCONNU": "aucune publication M4 canonique ne correspond au WCT demandé",
    "WCT-NON-RECU-M6": "le WCT publié par M4 n’a pas été reçu par M6",
    "BORNE-SOURCES": "les snapshots copiés dépassent la borne de traitement de 10000 lignes",
    "SORTIE-TROP-VOLUMINEUSE": "la lecture dépasse la borne de sortie ; aucun détail partiel n’est transmis",
}


class Refus(ValueError):
    def __init__(self, suffixe: str):
        self.suffixe = suffixe


def statuts_historique() -> tuple[str, ...]:
    return _ORDRE_HISTORIQUE


def refuser(prefixe: str, suffixe: str) -> dict:
    return {"accepte": False, "verdict": {"code": prefixe + suffixe, "detail": _DETAILS[suffixe]}}


def texte(valeur: Any, maximum: int = 256) -> bool:
    return (
        isinstance(valeur, str)
        and bool(valeur.strip())
        and len(valeur) <= maximum
        and not any(unicodedata.category(c) in {"Cc", "Cs"} for c in valeur)
    )


def arguments_valides(decalage: Any, limite: Any, wct_id: Any = None) -> bool:
    return (
        type(decalage) is int
        and 0 <= decalage <= PLAFOND_LIGNES
        and type(limite) is int
        and 1 <= limite <= 8
        and (wct_id is None or texte(wct_id))
    )


def _instant(valeur: Any) -> datetime:
    if not texte(valeur, 64):
        raise Refus("SOURCE-INVALIDE")
    match = _INSTANT.fullmatch(valeur)
    if match is None or (match[1] is not None and (int(match[1]) >= 24 or int(match[2]) >= 60)):
        raise Refus("SOURCE-INVALIDE")
    try:
        return datetime.fromisoformat(valeur)
    except ValueError:
        raise Refus("SOURCE-INVALIDE") from None


def _nombre(valeur: Any) -> bool:
    try:
        return type(valeur) in (int, float) and math.isfinite(valeur)
    except OverflowError:
        return False


def _seuil_projectable(valeur: Any) -> bool:
    # Le DTO numérique partagé refuse les entiers hors du domaine exact JavaScript.
    return _nombre(valeur) and (abs(valeur) <= 2**53 - 1 or valeur != math.trunc(valeur))


def _quantite_signee(valeur: int | float) -> str:
    # Pas normalize() sous le contexte Decimal de précision28 : un grand entier source
    # ne doit jamais être arrondi lors de sa projection. Retirer les seuls zéros fractionnels.
    brut = format(Decimal(str(valeur)), "f")
    return brut.rstrip("0").rstrip(".") if "." in brut else brut


def _snapshots(sources: dict) -> tuple[list, list, list]:
    try:
        rec, pub, mov = sources["recus"], sources["publications"], sources["mouvements"]
        if not all(isinstance(rows, list) for rows in (rec, pub, mov)):
            raise Refus("REGISTRE-INVALIDE")
        if len(rec) + len(pub) + len(mov) > PLAFOND_LIGNES:
            raise Refus("BORNE-SOURCES")
        return rec, pub, mov
    except (KeyError, TypeError):
        raise Refus("REGISTRE-INVALIDE") from None


def _recus(rec: list) -> dict[str, dict]:
    result = {}
    for position, ligne in enumerate(rec):
        if not isinstance(ligne, dict) or set(ligne) != {"rang", "maillon"} or type(ligne["rang"]) is not int:
            raise Refus("REGISTRE-INVALIDE")
        if ligne["rang"] != position:  # Vérification du rang durable, jamais construction d’une référence.
            raise Refus("REGISTRE-INVALIDE")
        m = ligne["maillon"]
        if not isinstance(m, dict):
            raise Refus("REGISTRE-INVALIDE")
        if m.get("empreinte_contenu") is None:
            raise Refus("EMPREINTE-RECUE-ABSENTE")
        if (
            set(m) != {"wct_id", "intervention_id", "devis_id", "horodatage_completion", "empreinte_contenu"}
            or not texte(m["wct_id"])
            or not texte(m["intervention_id"])
            or (m["devis_id"] is not None and not texte(m["devis_id"]))
            or not isinstance(m["empreinte_contenu"], str)
            or not _HASH.fullmatch(m["empreinte_contenu"])
        ):
            raise Refus("SOURCE-INVALIDE")
        _instant(m["horodatage_completion"])
        if m["wct_id"] in result:
            raise Refus("REGISTRE-INVALIDE")
        result[m["wct_id"]] = ligne
    return result


def _publications(pub: list) -> dict[str, dict]:
    result = {}
    for p in pub:
        if (
            not isinstance(p, dict)
            or not texte(p.get("evenement_id"), 300 if p.get("type") == "m6.variance_chantier" else 256)
            or p.get("catalogue_valide") is not True
            or not isinstance(p.get("charge"), dict)
        ):
            raise Refus("SOURCE-INVALIDE")
        if p["evenement_id"] in result:
            raise Refus("SOURCE-INVALIDE")
        result[p["evenement_id"]] = p
    return result


def _publication(pub: dict, id_: str, type_: str, producteur: str) -> dict:
    p = pub[id_]
    if p.get("type") != type_ or p.get("producteur") != producteur:
        raise Refus("SOURCE-INVALIDE")
    return p["charge"]


def _wct(ligne: dict, pubs: dict) -> dict:
    m = ligne["maillon"]
    id_ = m["wct_id"]
    if id_ not in pubs:
        raise Refus("SOURCE-PUBLIEE-ABSENTE")
    charge = _publication(pubs, id_, "m4.travaux_termines", "m04-field-ops")
    if (
        charge.get("wct_id") != id_
        or charge.get("intervention_id") != m["intervention_id"]
        or charge.get("devis_id") != m["devis_id"]
        or charge.get("horodatage_completion") != m["horodatage_completion"]
        or encodage.empreinte(charge) != m["empreinte_contenu"]
    ):
        raise Refus("LIAISON-INCOHERENTE")
    return {
        **{k: m[k] for k in ("wct_id", "intervention_id", "devis_id", "horodatage_completion")},
        "reference_recu": {"registre": "wct_recus", "rang": ligne["rang"], "empreinte_contenu": m["empreinte_contenu"]},
        "reference_bus": {"type": "m4.travaux_termines", "evenement_id": pubs[id_]["evenement_id"]},
    }


def _mouvements(mov: list) -> None:
    requis = {
        "index",
        "type_mouvement",
        "chantier_id",
        "materiau_id",
        "quantite",
        "cout_unitaire",
        "hash_precedent",
        "hash_maillon",
    }
    for position, m in enumerate(mov):
        if (
            not isinstance(m, dict)
            or not requis <= set(m) <= requis | {"wct_id"}
            or type(m["index"]) is not int
            or m["index"] != position
            or m["type_mouvement"] not in registre.TYPES_MOUVEMENT_VALIDES
            or not texte(m["chantier_id"])
            or not texte(m["materiau_id"])
            or ("wct_id" in m and not texte(m["wct_id"]))
            or not _nombre(m["quantite"])
            or (m["cout_unitaire"] is not None and not _nombre(m["cout_unitaire"]))
            or not isinstance(m["hash_maillon"], str)
            or not _HASH.fullmatch(m["hash_maillon"])
        ):
            raise Refus("REGISTRE-INVALIDE")
        if (m["type_mouvement"] in {"CONSOMMATION", "PERTE", "BRIS"} and m["quantite"] >= 0) or (
            m["type_mouvement"] in {"RECEPTION", "RETOUR"} and m["quantite"] <= 0
        ):
            raise Refus("REGISTRE-INVALIDE")
    if not registre.Registre(maillons=mov).valider_chaine()[0]:
        raise Refus("REGISTRE-INVALIDE")


def _historique(wct: dict, pubs: dict) -> list[dict]:
    slots = []
    for statut in _ORDRE_HISTORIQUE:
        id_ = f"m6-variance-{wct['wct_id']}-{statut}"
        p = None
        if id_ in pubs:
            charge = _publication(pubs, id_, "m6.variance_chantier", "m06-material-control")
            if (
                charge.get("evenement_id") != id_
                or charge.get("wct_id") != wct["wct_id"]
                or charge.get("intervention_id") != wct["intervention_id"]
                or charge.get("horodatage_completion") != wct["horodatage_completion"]
                or charge.get("statut_variance") != statut
            ):
                raise Refus("LIAISON-INCOHERENTE")
            chantier = charge.get("chantier_id")
            seuil = charge.get("seuil_pourcentage")
            if (
                (chantier is not None and not texte(chantier))
                or (statut == "seuil_absent" and seuil is not None)
                or (statut != "seuil_absent" and (not _seuil_projectable(seuil) or seuil <= 0))
                or (
                    statut != "evaluee"
                    and (charge.get("signal_critique") is not None or charge.get("lignes") is not None)
                )
                or (
                    statut == "evaluee"
                    and (type(charge.get("signal_critique")) is not bool or not isinstance(charge.get("lignes"), list))
                )
            ):
                raise Refus("SOURCE-INVALIDE")
            p = {
                "reference_bus": {"type": "m6.variance_chantier", "evenement_id": pubs[id_]["evenement_id"]},
                "chantier_id": chantier,
                "signal_critique": charge["signal_critique"],
                "seuil_pourcentage": seuil,
                "horodatage_completion": charge["horodatage_completion"],
                "horodatage_publication": None,
            }
        slots.append({"statut": statut, "presente": p is not None, "publication": p})
    return slots


def _page(dto: dict, cle: str, candidats: list, decalage: int, limite: int) -> dict:
    total = len(candidats)
    page = candidats[decalage : decalage + limite]
    dto[cle] = page
    while True:
        affichees = len(page)
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
        dto["taille_caracteres"] = 0
        while True:
            taille = len(json.dumps({"ok": True, "resultat": dto}, ensure_ascii=False))
            if taille == dto["taille_caracteres"]:
                break
            dto["taille_caracteres"] = taille
        if taille <= BORNE_CARACTERES:
            return dto
        if len(page) <= 1:
            raise Refus("SORTIE-TROP-VOLUMINEUSE")
        page.pop()


def _executer(prefixe: str, fonction: Any) -> dict:
    try:
        return fonction()
    except Refus as r:
        return refuser(prefixe, r.suffixe)
    except (KeyError, TypeError, ValueError, OverflowError):
        return refuser(prefixe, "REGISTRE-INVALIDE")


def lister(sources: dict, decalage: int, limite: int) -> dict:
    def calcul():
        if not arguments_valides(decalage, limite):
            raise Refus("ARGUMENTS-INVALIDES")
        rec, pub, _ = _snapshots(sources)
        recus, publications = _recus(rec), _publications(pub)
        candidats = [
            _wct(ligne, publications) for ligne in sorted(recus.values(), key=lambda r: r["rang"], reverse=True)
        ]
        return _page(
            {
                "wcts": [],
                "pagination": {},
                "couverture": {"wcts": "recus_m6_rapproches_m4", "plafond_lignes": PLAFOND_LIGNES},
                "borne_caracteres": BORNE_CARACTERES,
                "taille_caracteres": 0,
            },
            "wcts",
            candidats,
            decalage,
            limite,
        )

    return _executer("REJ-M6-WCT-", calcul)


def lire(sources: dict, wct_id: str, decalage: int, limite: int) -> dict:
    def calcul():
        if not texte(wct_id) or not arguments_valides(decalage, limite, wct_id):
            raise Refus("ARGUMENTS-INVALIDES")
        rec, pub, mov = _snapshots(sources)
        recus, publications = _recus(rec), _publications(pub)
        if wct_id not in publications:
            raise Refus("WCT-INCONNU")
        _publication(publications, wct_id, "m4.travaux_termines", "m04-field-ops")
        if wct_id not in recus:
            raise Refus("WCT-NON-RECU-M6")
        wct = _wct(recus[wct_id], publications)
        _mouvements(mov)
        lies = [m for m in mov if m.get("wct_id") == wct_id]
        if any(m["type_mouvement"] not in _DECLARATION for m in lies):
            raise Refus("LIAISON-INCOHERENTE")
        historique = _historique(wct, publications)
        if historique[3]["presente"] and not lies:
            raise Refus("LIAISON-INCOHERENTE")
        chantiers = {m["chantier_id"] for m in lies}
        chantiers |= {
            x["publication"]["chantier_id"]
            for x in historique
            if x["presente"] and x["publication"]["chantier_id"] is not None
        }
        if len(chantiers) > 1:
            raise Refus("LIAISON-INCOHERENTE")
        candidats = [
            {
                "type_mouvement": m["type_mouvement"],
                "chantier_id": m["chantier_id"],
                "materiau_id": m["materiau_id"],
                "quantite_signee": _quantite_signee(m["quantite"]),
                "unite": None,
                "horodatage": None,
                "reference": {"registre": "principal", "index": m["index"], "hash_maillon": m["hash_maillon"]},
            }
            for m in lies
            if m["type_mouvement"] in {"PERTE", "BRIS"}
        ]
        return _page(
            {
                "wct": wct,
                "chantier_id": next(iter(chantiers)) if chantiers else None,
                "declaration_presente": bool(lies),
                "pertes_bris": [],
                "historique_variance": historique,
                "evaluee_terminal": historique[3]["presente"],
                "pagination": {},
                "couverture": {
                    "mouvements": "PERTE_BRIS_WCT_exact",
                    "variances": "quatre_statuts_publies_ordre_fixe_sans_chronologie",
                    "hors_corpus": [
                        "stock_courant",
                        "reapprovisionnement",
                        "couts",
                        "responsables",
                        "preuves_photos",
                        "unites_reelles",
                        "dates_perte_bris",
                    ],
                    "plafond_lignes": PLAFOND_LIGNES,
                },
                "borne_caracteres": BORNE_CARACTERES,
                "taille_caracteres": 0,
            },
            "pertes_bris",
            candidats,
            decalage,
            limite,
        )

    return _executer("REJ-M6-PERTES-", calcul)
