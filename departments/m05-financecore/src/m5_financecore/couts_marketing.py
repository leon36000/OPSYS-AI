"""Affectations analytiques humaines AP→campagne ; aucun paiement ou calcul de ROI.

Module pur M5 : les adaptateurs fournissent snapshots vérifiés et signataire DB.
Les fonctions AP existantes restent l'unique dérivation des factures fournisseur.
"""

from __future__ import annotations

import copy
import re
from collections import Counter
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from . import comptes_a_payer as ap
from . import encodage, registre

REGISTRE = "couts_marketing_affectes"
TYPE_ENREGISTRE = "affectation_cout_marketing_enregistree"
TYPE_RETIRE = "affectation_cout_marketing_retiree"
_MONTANT = re.compile(r"^(?:0|[1-9][0-9]{0,11})\.[0-9]{2}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_TYPES_AP = {
    "reception_recue", "facture_fournisseur_saisie", "correction_facture_fournisseur", "annulation_facture_fournisseur",
}


class CoutErreur(ValueError):
    """Diagnostic fermé ; ne transporte jamais le registre ou les montants bruts."""

    def __init__(self, code: str):
        self.code = "REJ-COUT-MARKETING-" + code
        super().__init__(self.code)


def _texte(valeur: Any, maximum: int = 128) -> str:
    if not isinstance(valeur, str) or not valeur.strip() or len(valeur) > maximum or not valeur.isprintable():
        raise CoutErreur("TEXTE-INVALIDE")
    return valeur


def periode(debut: str, fin: str) -> dict[str, str]:
    try:
        if not all(isinstance(v, str) and _DATE.fullmatch(v) for v in (debut, fin)):
            raise ValueError
        a, b = date.fromisoformat(debut), date.fromisoformat(fin)
        if not 0 <= (b - a).days <= 365:
            raise ValueError
    except (TypeError, ValueError):
        raise CoutErreur("PERIODE-INVALIDE") from None
    return {"debut": debut, "fin": fin}


def montant(valeur: Any) -> Decimal:
    if not isinstance(valeur, str) or not _MONTANT.fullmatch(valeur) or Decimal(valeur) <= 0:
        raise CoutErreur("MONTANT-INVALIDE")
    return Decimal(valeur)


def _source_montant(valeur: Any) -> Decimal:
    if (not isinstance(valeur, Decimal) or not valeur.is_finite() or valeur < 0
            or valeur != valeur.quantize(Decimal(".01"), rounding=ROUND_HALF_UP)):
        raise CoutErreur("SOURCE-MONTANT-INVALIDE")
    return valeur


def snapshot(maillons: list[dict]) -> dict[str, Any]:
    try:
        if not registre.Registre(maillons=maillons).valider_chaine()[0]:
            raise ValueError
        return {"nombre": len(maillons), "tete": maillons[-1]["ligne_id"] if maillons else None}
    except (ArithmeticError, AttributeError, KeyError, TypeError, ValueError, RecursionError):
        raise CoutErreur("CHAINE-INVALIDE") from None


def _reference_identique(fournie: Any, attendue: Any) -> bool:
    """Une version JSON doit aussi porter le type exact : True n'est jamais le rang 1."""
    if type(fournie) is not type(attendue):
        return False
    if isinstance(attendue, dict):
        return set(fournie) == set(attendue) and all(
            _reference_identique(fournie[k], valeur) for k, valeur in attendue.items()
        )
    return fournie == attendue


def etats_ap(maillons: list[dict]) -> dict[str, dict]:
    snapshot(maillons)
    try:
        if any(m.get("type_entree") not in _TYPES_AP for m in maillons):
            raise ValueError
        etats = ap._etats_factures(maillons)
        for etat in etats.values():
            _texte(etat["facture_fournisseur_id"])
            ht, taxes, ttc = (_source_montant(etat[k]) for k in (
                "montant_avant_taxes", "total_taxes", "montant_apres_taxes",
            ))
            details = etat["taxes"]
            if not isinstance(details, list) or len(details) > 32 or ht + taxes != ttc:
                raise ValueError
            if sum((_source_montant(t["montant"]) for t in details), Decimal(0)) != taxes:
                raise ValueError
            if etat["statut"] not in {"SAISIE", "CORRIGEE", "ANNULEE"}:
                raise ValueError
        return etats
    except (ArithmeticError, AttributeError, KeyError, TypeError, ValueError, RuntimeError, RecursionError):
        raise CoutErreur("SOURCE-AP-INVALIDE") from None


def empreinte_etat(etat: dict) -> str:
    # Les avertissements de doublon sont dérivés des autres pièces, pas une nouvelle version de celle-ci.
    vue = ap.vue_facture(etat)
    vue.pop("avertissements", None)
    return encodage.empreinte(vue)


def campagne_valide(campagne: Any) -> dict:
    champs = {"campagne_id", "revision", "empreinte", "nom", "periode", "utm_source", "utm_campaign"}
    if not isinstance(campagne, dict) or set(campagne) != champs:
        raise CoutErreur("CAMPAGNE-INVALIDE")
    for cle in ("campagne_id", "utm_source", "utm_campaign"):
        _texte(campagne[cle])
    _texte(campagne["nom"], 2048)
    if type(campagne["revision"]) is not int or campagne["revision"] < 1:
        raise CoutErreur("CAMPAGNE-INVALIDE")
    if not isinstance(campagne["empreinte"], str) or not _HASH.fullmatch(campagne["empreinte"]):
        raise CoutErreur("CAMPAGNE-INVALIDE")
    p = campagne["periode"]
    if not isinstance(p, dict) or set(p) != {"debut", "fin"}:
        raise CoutErreur("CAMPAGNE-INVALIDE")
    # Les campagnes existantes peuvent durer plus d'un an ; seule la période du rapport est bornée à 366 jours.
    try:
        if any(not isinstance(v, str) or not _DATE.fullmatch(v) for v in p.values()):
            raise ValueError
        if date.fromisoformat(p["debut"]) > date.fromisoformat(p["fin"]):
            raise ValueError
    except ValueError:
        raise CoutErreur("CAMPAGNE-INVALIDE") from None
    return campagne


def etats_affectations(maillons: list[dict]) -> dict[str, dict]:
    snapshot(maillons)
    etats: dict[str, dict] = {}
    champs = {
        "type_entree", "affectation_id", "version", "facture_fournisseur_id", "campagne_id", "periode",
        "base", "devise", "montant_alloue_cad", "motif", "valide_par", "voie", "horodatage",
        "source_ap", "source_campagne", "ligne_id", "precedent_ligne_id",
    }
    try:
        for m in maillons:
            if set(m) != champs or m["type_entree"] not in {TYPE_ENREGISTRE, TYPE_RETIRE}:
                raise ValueError
            ident = _texte(m["affectation_id"])
            _texte(m["facture_fournisseur_id"])
            _texte(m["campagne_id"])
            _texte(m["valide_par"])
            _texte(m["motif"], 300)
            if m["voie"] != "approbation" or datetime.fromisoformat(m["horodatage"]).tzinfo is None:
                raise ValueError
            periode(**m["periode"])
            montant(m["montant_alloue_cad"])
            if m["base"] not in {"HT", "TTC"} or m["devise"] != "CAD":
                raise ValueError
            source = m["source_ap"]
            if set(source) != {"nombre", "tete", "etat_sha256"} or type(source["nombre"]) is not int:
                raise ValueError
            if (source["nombre"] < 1 or not _HASH.fullmatch(source["tete"])
                    or not _HASH.fullmatch(source["etat_sha256"])):
                raise ValueError
            campagne_valide(m["source_campagne"])
            if m["source_campagne"]["campagne_id"] != m["campagne_id"]:
                raise ValueError
            avant = etats.get(ident)
            if type(m["version"]) is not int or m["version"] != (avant["version"] + 1 if avant else 1):
                raise ValueError
            if avant and (avant["type_entree"] == TYPE_RETIRE or any(
                avant[k] != m[k] for k in ("facture_fournisseur_id", "campagne_id")
            )):
                raise ValueError
            if m["type_entree"] == TYPE_RETIRE and (avant is None or any(
                avant[k] != m[k] for k in (
                    "periode", "base", "devise", "montant_alloue_cad", "source_ap", "source_campagne",
                )
            )):
                raise ValueError
            etats[ident] = m
    except (ArithmeticError, AttributeError, KeyError, TypeError, ValueError, RecursionError):
        raise CoutErreur("AFFECTATIONS-INVALIDES") from None
    return etats


def references(ap_maillons: list[dict], affectations: list[dict], campagne: dict,
               facture_id: str, affectation_id: str | None = None) -> dict:
    etat = etats_ap(ap_maillons).get(facture_id)
    if etat is None:
        raise CoutErreur("PIECE-INCONNUE")
    campagne_valide(campagne)
    courant = etats_affectations(affectations).get(affectation_id)
    return _references(etat, snapshot(ap_maillons), snapshot(affectations), campagne,
                       courant["version"] if courant else 0)


def _references(etat: dict, source_ap: dict, source_affectations: dict, campagne: dict, version: int) -> dict:
    return {
        "ap": {**source_ap, "etat_sha256": empreinte_etat(etat)},
        "campagne": {k: campagne[k] for k in ("revision", "empreinte")},
        "affectations": {**source_affectations, "version": version},
    }


def preparer_affectation(ap_maillons: list[dict], affectations: list[dict], campagne: dict, arguments: dict,
                        *, auteur: str, horodatage: str, nouvel_id: str) -> dict:
    etats, parts = etats_ap(ap_maillons), etats_affectations(affectations)
    campagne_valide(campagne)
    facture_id = _texte(arguments["facture_fournisseur_id"])
    etat = etats.get(facture_id)
    if etat is None:
        raise CoutErreur("PIECE-INCONNUE")
    if etat["po_id"] is not None or etat["statut"] == "ANNULEE":
        raise CoutErreur("PIECE-NON-ELIGIBLE")
    if arguments["campagne_id"] != campagne["campagne_id"]:
        raise CoutErreur("CAMPAGNE-DIFFERENTE")
    ident = arguments.get("affectation_id")
    avant = parts.get(ident)
    if ident is None and nouvel_id in parts:
        raise CoutErreur("IDENTIFIANT-EXISTANT")
    if ident is not None and (avant is None or avant["type_entree"] == TYPE_RETIRE):
        raise CoutErreur("AFFECTATION-INCONNUE")
    if avant and any(avant[k] != arguments[k] for k in ("facture_fournisseur_id", "campagne_id")):
        raise CoutErreur("CIBLE-DIFFERENTE")
    attendu = references(ap_maillons, affectations, campagne, facture_id, ident)
    if not _reference_identique(arguments["sources_attendues"], attendu):
        raise CoutErreur("SNAPSHOT-PERIME")
    p = periode(arguments["debut"], arguments["fin"])
    part = montant(arguments["montant_alloue_cad"])
    base = arguments["base"]
    if base not in {"HT", "TTC"}:
        raise CoutErreur("BASE-INVALIDE")
    if arguments["devise"] != "CAD":
        raise CoutErreur("DEVISE-INVALIDE")
    autres = [m for k, m in parts.items() if k != ident and m["facture_fournisseur_id"] == facture_id
              and m["type_entree"] != TYPE_RETIRE]
    if any(m["base"] != base for m in autres):
        raise CoutErreur("BASE-DIFFERENTE")
    if part + sum((montant(m["montant_alloue_cad"]) for m in autres), Decimal(0)) > etat[
        "montant_avant_taxes" if base == "HT" else "montant_apres_taxes"
    ]:
        raise CoutErreur("CAPACITE-DEPASSEE")
    return {
        "type_entree": TYPE_ENREGISTRE, "affectation_id": _texte(ident or nouvel_id),
        "version": avant["version"] + 1 if avant else 1, "facture_fournisseur_id": facture_id,
        "campagne_id": campagne["campagne_id"], "periode": p, "base": base, "devise": "CAD",
        "montant_alloue_cad": str(part), "motif": _texte(arguments["motif"], 300),
        "valide_par": _texte(auteur), "voie": "approbation", "horodatage": horodatage,
        "source_ap": attendu["ap"], "source_campagne": copy.deepcopy(campagne),
    }


def preparer_retrait(affectations: list[dict], ident: str, version: int, snapshot_attendu: dict, motif: str,
                    *, auteur: str, horodatage: str) -> dict:
    courant = etats_affectations(affectations).get(_texte(ident))
    if courant is None or courant["type_entree"] == TYPE_RETIRE:
        raise CoutErreur("AFFECTATION-INCONNUE")
    if type(version) is not int or version != courant["version"] or not _reference_identique(
        snapshot_attendu, snapshot(affectations),
    ):
        raise CoutErreur("SNAPSHOT-PERIME")
    return {k: v for k, v in {**courant, "type_entree": TYPE_RETIRE, "version": version + 1,
            "motif": _texte(motif, 300), "valide_par": _texte(auteur), "horodatage": horodatage}.items()
            if k not in {"ligne_id", "precedent_ligne_id"}}


def projeter(ap_maillons: list[dict], affectations: list[dict], campagne: dict, *, debut: str, fin: str,
             offset_affectations: int = 0, offset_pieces: int = 0, snapshot_attendu: dict | None = None) -> dict:
    p = periode(debut, fin)
    etats, parts = etats_ap(ap_maillons), etats_affectations(affectations)
    campagne_valide(campagne)
    observation = {"ap": snapshot(ap_maillons), "affectations": snapshot(affectations),
                   "campagne": {k: campagne[k] for k in ("revision", "empreinte")}}
    if snapshot_attendu is not None and not _reference_identique(snapshot_attendu, observation):
        raise CoutErreur("PAGE-PERIMEE")
    lignes, candidats, exclusions = [], [], Counter()
    totaux: dict[str, Decimal | None] = {"HT": None, "TTC": None}
    for m in sorted(parts.values(), key=lambda ligne: ligne["affectation_id"]):
        if m["campagne_id"] != campagne["campagne_id"]:
            continue
        etat = etats.get(m["facture_fournisseur_id"])
        if etat is None:
            raise CoutErreur("SOURCE-AP-INVALIDE")
        statut = "RETIREE" if m["type_entree"] == TYPE_RETIRE else "COURANTE"
        if statut != "RETIREE":
            if etat["statut"] == "ANNULEE" or empreinte_etat(etat) != m["source_ap"]["etat_sha256"]:
                statut = "PERIMEE_SOURCE_AP"
            elif campagne != m["source_campagne"]:
                statut = "PERIMEE_SOURCE_CAMPAGNE"
        raison = None if statut == "COURANTE" else statut
        if raison is None and (m["periode"]["fin"] < debut or m["periode"]["debut"] > fin):
            raison = "HORS_PERIODE"
        elif raison is None and not (debut <= m["periode"]["debut"] <= m["periode"]["fin"] <= fin):
            raison = "CHEVAUCHEMENT_PARTIEL"
        if raison:
            exclusions[raison] += 1
        else:
            totaux[m["base"]] = (totaux[m["base"]] or Decimal(0)) + montant(m["montant_alloue_cad"])
        lignes.append({k: copy.deepcopy(v) for k, v in m.items() if k not in {
            "ligne_id", "precedent_ligne_id", "type_entree",
        }} | {"statut": statut, "exclusion": raison, "piece_statut": etat["statut"],
              "sources_courantes": _references(etat, observation["ap"], observation["affectations"], campagne,
                                               m["version"])})
    par_facture: dict[str, list[dict]] = {}
    for m in parts.values():
        if m["type_entree"] != TYPE_RETIRE:
            par_facture.setdefault(m["facture_fournisseur_id"], []).append(m)
    for ident, etat in sorted(etats.items()):
        if etat["po_id"] is not None or etat["statut"] == "ANNULEE":
            continue
        actives = par_facture.get(ident, [])
        reserve = sum((montant(m["montant_alloue_cad"]) for m in actives), Decimal(0))
        candidats.append({
            "facture_fournisseur_id": ident, "date_facture": etat["date_facture"],
            "categorie_depense": etat["categorie_depense"], "piece_statut": etat["statut"],
            "montant_avant_taxes": str(etat["montant_avant_taxes"]), "total_taxes": str(etat["total_taxes"]),
            "montant_apres_taxes": str(etat["montant_apres_taxes"]), "devise_source": None,
            "base_reservee": actives[0]["base"] if actives else None, "reserve_cad": f"{reserve:.2f}",
            "avertissements": list(etat["avertissements"]),
            "sources_attendues": _references(etat, observation["ap"], observation["affectations"], campagne, 0),
        })

    def page(liste, offset):
        if type(offset) is not int or not 0 <= offset <= len(liste):
            raise CoutErreur("PAGE-INVALIDE")
        valeurs = liste[offset:offset + 10]
        suivant = offset + len(valeurs)
        return valeurs, {"offset": offset, "total": len(liste), "affichees": len(valeurs),
                         "reste": len(liste) - suivant, "suivant": suivant if suivant < len(liste) else None}

    lignes, pagination = page(lignes, offset_affectations)
    candidats, pagination_pieces = page(candidats, offset_pieces)
    return {
        "type": "COUTS_MARKETING_AFFECTES_V1", "campagne": copy.deepcopy(campagne), "periode": p,
        "observation_source": observation, "affectations": lignes, "pieces_eligibles": candidats,
        "totaux_par_base": {k: f"{v:.2f}" if v is not None else None for k, v in totaux.items()},
        "couverture": "PARTIELLE" if any(v is not None for v in totaux.values()) else "INCONNUE",
        "paiement_cad": None, "taxes_non_recuperables_cad": None, "cout_economique_cad": None, "roi": None,
        "inconnues": ["PAIEMENTS_NON_LIES", "TAXES_NON_RECUPERABLES_INCONNUES", "EXHAUSTIVITE_NON_DECLAREE",
                      "AUTHENTICITE_FACTURE_EXTERNE_NON_VERIFIEE"],
        "exclusions": dict(exclusions), "pagination": pagination, "pagination_pieces": pagination_pieces,
    }
