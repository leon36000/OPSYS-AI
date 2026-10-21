"""Projection pure du contexte/prévu d'un WCT admis, sur copies validées."""

from __future__ import annotations

import hashlib
import json
import math
import re
from decimal import Decimal

from . import acces, besoins_materiaux_recus, besoins_prevus, pertes_appareil, validation

PLAFOND_LIGNES = 10000
_DETAILS = {
    "ARGUMENTS-INVALIDES": "les arguments sortent du contrat de lecture du contexte matériaux",
    "IDENTITE-INVALIDE": "cette lecture exige une personne active et un rôle terrain confirmé",
    "INTERVENTION-NON-ASSIGNEE": "cette intervention n’est pas accessible à la personne authentifiée",
    "WCT-INCONNU": "aucun WCT publié admissible ne correspond à cette cible",
    "LIAISON-INCOHERENTE": "les sources du contexte ne concordent pas avec la cible choisie",
    "SOURCE-INVALIDE": "une source requise ne satisfait pas son contrat d’intégrité",
    "BORNE-SOURCES": "les copies requises dépassent la borne de traitement de 10000 lignes",
    "SORTIE-TROP-VOLUMINEUSE": "le contexte dépasse la borne de sortie ; aucun détail partiel n’est transmis",
}


class Refus(ValueError):
    def __init__(self, suffixe):
        self.suffixe = suffixe


def refuser(suffixe):
    return {"accepte": False, "verdict": {"code": "REJ-M6-CONTEXTE-" + suffixe, "detail": _DETAILS[suffixe]}}


def texte(v):
    return pertes_appareil.texte(v, 256)


def arguments_valides(i, w, d, limite):
    return texte(i) and texte(w) and type(d) is int and 0 <= d <= 10000 and type(limite) is int and 1 <= limite <= 8


def empreinte_snapshot(v):
    return hashlib.sha256(
        json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _hash(v):
    return isinstance(v, str) and re.fullmatch("[0-9a-f]{64}", v) is not None


def _entier(v):
    return type(v) is int and 0 <= v <= 9007199254740991


def _date(v):
    try:
        pertes_appareil._instant(v)
    except pertes_appareil.Refus:
        raise Refus("SOURCE-INVALIDE") from None


def _quantite(v, texte_source=False):
    if texte_source:
        if not isinstance(v, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", v):
            raise Refus("SOURCE-INVALIDE")
    elif type(v) not in (int, float) or (type(v) is float and not math.isfinite(v)):
        raise Refus("SOURCE-INVALIDE")
    d = Decimal(str(v))
    if not d.is_finite() or d <= 0:
        raise Refus("SOURCE-INVALIDE")
    return v if texte_source else format(d, "f")


def _previsions(rows, devis):
    maillons = []
    for pos, row in enumerate(rows):
        if (
            not isinstance(row, dict)
            or set(row) != {"rang", "maillon"}
            or type(row["rang"]) is not int
            or row["rang"] != pos
            or not isinstance(row["maillon"], dict)
        ):
            raise Refus("SOURCE-INVALIDE")
        maillons.append(row["maillon"])
    chosen = besoins_prevus.pour_devis(devis, maillons)
    if chosen is None:
        return None, None
    rank = next(i for i, m in enumerate(maillons) if m is chosen)
    provisional = chosen.get("source") == besoins_prevus.SOURCE_ESTIMATION_M3
    base = {"chantier_id", "devis_id", "lignes"}
    extras = {
        "source",
        "estimation_id",
        "rang_registre",
        "lead_id",
        "bareme_version",
        "niveau_confiance",
        "detail_lignes",
        "facteurs_perte_absents",
    }
    if set(chosen) != (base | extras if provisional else base):
        raise Refus("SOURCE-INVALIDE")
    if isinstance(chosen["lignes"], list) and len(chosen["lignes"]) > PLAFOND_LIGNES:
        raise Refus("BORNE-SOURCES")
    ok, _ = validation.valider_besoins_estimes_chantier(chosen["lignes"])
    if (
        not ok
        or chosen["devis_id"] != devis
        or (chosen["chantier_id"] is not None and not texte(chosen["chantier_id"]))
    ):
        raise Refus("SOURCE-INVALIDE")
    if provisional:
        if (
            chosen["chantier_id"] is not None
            or not _entier(chosen["rang_registre"])
            or not texte(chosen["bareme_version"])
        ):
            raise Refus("SOURCE-INVALIDE")
        details = chosen["detail_lignes"]
        if not isinstance(details, list) or any(not isinstance(x, dict) or "materiau_id" not in x for x in details):
            raise Refus("SOURCE-INVALIDE")
        charge = {
            k: chosen[k]
            for k in (
                "devis_id",
                "lead_id",
                "estimation_id",
                "rang_registre",
                "bareme_version",
                "niveau_confiance",
                "facteurs_perte_absents",
            )
        }
        charge["lignes"] = [{k: v for k, v in x.items() if k != "materiau_id"} for x in details]
        if (
            not besoins_materiaux_recus.valider(charge)[0]
            or besoins_materiaux_recus.lignes_detaillees(charge) != details
            or besoins_materiaux_recus.lignes_prevues(charge) != chosen["lignes"]
        ):
            raise Refus("SOURCE-INVALIDE")
    return rank, chosen


def _provenance(chosen, pubs):
    provisional = chosen.get("source") == besoins_prevus.SOURCE_ESTIMATION_M3
    type_ = "m3.besoins_materiaux" if provisional else "m3.devis_accepte"
    candidats = []
    for row in pubs:
        if not isinstance(row, dict) or not isinstance(row.get("charge"), dict):
            raise Refus("SOURCE-INVALIDE")
        c = row["charge"]
        if row.get("type") != type_ or c.get("devis_id") != chosen["devis_id"]:
            continue
        if provisional and c.get("estimation_id") != chosen["estimation_id"]:
            continue
        if (
            row.get("producteur") != "m03-estimation"
            or row.get("catalogue_valide") is not True
            or not texte(row.get("evenement_id"))
        ):
            raise Refus("SOURCE-INVALIDE")
        candidats.append(row)
    if not candidats:
        return None, None, None
    if len(candidats) != 1:
        raise Refus("LIAISON-INCOHERENTE")
    row = candidats[0]
    c = row["charge"]
    if provisional:
        ok, _ = besoins_materiaux_recus.valider(c)
        if (
            not ok
            or c["rang_registre"] != chosen["rang_registre"]
            or c["bareme_version"] != chosen["bareme_version"]
            or besoins_materiaux_recus.lignes_prevues(c) != chosen["lignes"]
            or besoins_materiaux_recus.lignes_detaillees(c) != chosen["detail_lignes"]
        ):
            raise Refus("LIAISON-INCOHERENTE")
        originals = [
            {
                "materiau_id": besoins_materiaux_recus.identite_materiau(x),
                "quantite": x["quantite_estimee"],
                "unite": x["unite"],
            }
            for x in c["lignes"]
        ]
        date = None
    else:
        originals = [
            {"materiau_id": x["reference_besoin_materiau"], "quantite": x["quantite"], "unite": x["unite"]}
            for x in c["lignes"]
            if x.get("reference_besoin_materiau") is not None
        ]
        mapped = [
            {"materiau_id": x["materiau_id"], "quantite_estimee": float(x["quantite"]), "unite": x["unite"]}
            for x in originals
        ]
        if mapped != chosen["lignes"] or c["chantier_id"] != chosen["chantier_id"]:
            raise Refus("LIAISON-INCOHERENTE")
        date = c["horodatage_acceptation"]
        _date(date)
    for x in originals:
        _quantite(x["quantite"], True)
    return {"type": type_, "evenement_id": row["evenement_id"]}, date, originals


def lire(sources, i, w, acteur, decalage, limite):
    try:
        if not arguments_valides(i, w, decalage, limite):
            raise Refus("ARGUMENTS-INVALIDES")
        rows = sources["prevus"]
        pubs = sources["m3"]
        row = sources["wct"]
        if not isinstance(rows, list) or not isinstance(pubs, list):
            raise Refus("SOURCE-INVALIDE")
        if len(rows) + len(pubs) + sources["admission_lignes"] + 1 > PLAFOND_LIGNES:
            raise Refus("BORNE-SOURCES")
        if row is None:
            raise Refus("WCT-INCONNU")
        if (
            row["type"] != "m4.travaux_termines"
            or row["producteur"] != "m04-field-ops"
            or row["catalogue_valide"] is not True
        ):
            raise Refus("SOURCE-INVALIDE")
        c = row["charge"]
        if c != sources["completion"] or c["wct_id"] != w or c["intervention_id"] != i or row["evenement_id"] != w:
            raise Refus("LIAISON-INCOHERENTE")
        if acteur.role == "employee" and c["technicien_id"] != acteur.personne:
            raise Refus("INTERVENTION-NON-ASSIGNEE")
        if not _hash(c["hash_maillon"]) or (c["devis_id"] is not None and not texte(c["devis_id"])):
            raise Refus("SOURCE-INVALIDE")
        _date(c["horodatage_completion"])
        rank, chosen = _previsions(rows, c["devis_id"])
        cible = acces.chantier_attendu(c, chosen, acteur)
        origin = (
            "prevu_m6"
            if chosen is not None and chosen["chantier_id"] is not None
            else "intervention_employee"
            if acteur.role == "employee"
            else "absent_admin"
        )
        manques = []
        if c["devis_id"] is None:
            manques.append("devis_absent")
        if chosen is None:
            manques.append("prevu_absent")
        if cible is None:
            manques.append("chantier_source_absent")
        source = None
        lines = []
        status = "absent"
        if chosen is not None:
            reference, date, originals = _provenance(chosen, pubs)
            provisional = chosen.get("source") == besoins_prevus.SOURCE_ESTIMATION_M3
            status = "provisoire_estimation_m3" if provisional else "definitif"
            source = {
                "registre": "besoins_prevus",
                "rang": rank,
                "empreinte_snapshot": empreinte_snapshot(chosen),
                "estimation_id": chosen["estimation_id"] if provisional else None,
                "rang_m3": chosen["rang_registre"] if provisional else None,
                "bareme_version": chosen["bareme_version"] if provisional else None,
                "horodatage": date,
                "reference_m3": reference,
            }
            if date is None:
                manques.append("horodatage_prevu_absent")
            if reference is None:
                manques.append("provenance_m3_absente")
            for pos, line in enumerate(chosen["lignes"]):
                if not texte(line["materiau_id"]) or not texte(line["unite"]):
                    raise Refus("SOURCE-INVALIDE")
                quantity = _quantite(line["quantite_estimee"])
                quantity_source = "nombre_m6_persiste"
                if originals is not None and Decimal(originals[pos]["quantite"]) == Decimal(quantity):
                    quantity = originals[pos]["quantite"]
                    quantity_source = "texte_m3_verifie"
                lines.append(
                    {
                        "position_source": pos,
                        "materiau_id": line["materiau_id"],
                        "unite": line["unite"],
                        "quantite_estimee": quantity,
                        "origine_quantite": quantity_source,
                    }
                )
        dto = {
            "wct": {
                "wct_id": w,
                "intervention_id": i,
                "devis_id": c["devis_id"],
                "horodatage_completion": c["horodatage_completion"],
                "hash_maillon": c["hash_maillon"],
                "reference_bus": {"type": "m4.travaux_termines", "evenement_id": w},
            },
            "chantier": {"chantier_id": cible, "origine": origin},
            "prevu": {"statut": status, "source": source},
            "lignes": [],
            "manques": manques,
            "couverture": {
                "objet": "contexte_et_prevu_du_wct",
                "quantite_reelle": "non_renseignee",
                "pages": "courantes",
                "plafond_lignes": 10000,
            },
            "borne_caracteres": 5400,
        }
        return pertes_appareil._page(dto, "lignes", lines, decalage, limite)
    except Refus as exc:
        return refuser(exc.suffixe)
    except pertes_appareil.Refus:
        return refuser("SORTIE-TROP-VOLUMINEUSE")
    except (KeyError, TypeError, ValueError, OverflowError):
        return refuser("SOURCE-INVALIDE")
