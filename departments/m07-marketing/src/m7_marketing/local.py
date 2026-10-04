"""Dossiers marketing locaux, consentement de référence et approbation de budget."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from typing import Any
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import LargeBinary, cast, func, select

from opsys import stockage
from opsys.stockage.schema import REGISTRES

from .utm import utm_engine

REGISTRE = ("m07-marketing", "local_campaigns")
TYPES = frozenset({"camion", "pancarte", "flyer", "partenaire", "evenement", "reference", "voisinage"})


def _fp(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def enregistrer_consentement(
    consentement_id: str,
    personne_ref: str,
    texte_consentement: str,
    source_preuve: str,
    horodatage: str,
    saisi_par: str,
) -> dict[str, Any]:
    if not all(
        isinstance(x, str) and x.strip()
        for x in (consentement_id, personne_ref, texte_consentement, source_preuve, horodatage, saisi_par)
    ):
        return {"statut": "consentement_invalide", "motif": "personne, texte, preuve et horodatage requis"}
    payload = {
        "consentement_id": consentement_id,
        "personne_ref": personne_ref,
        "texte_consentement": texte_consentement,
        "source_preuve": source_preuve,
        "horodatage": horodatage,
        "saisi_par": saisi_par,
    }
    registre = stockage.maillons(*REGISTRE)
    existant = next(
        (m for m in registre if m.get("type") == "consentement_reference" and m["consentement_id"] == consentement_id),
        None,
    )
    fp = _fp(payload)
    if existant:
        return {"statut": "deja_enregistre" if existant["empreinte"] == fp else "conflit", "consentement": existant}
    maillon = {"type": "consentement_reference", **payload, "empreinte": fp}
    registre.append(maillon)
    return {"statut": "consentement_enregistre", "consentement": maillon}


def proposer(
    campagne_id: str,
    type_campagne: str,
    nom: str,
    periode_debut: str,
    periode_fin: str,
    budget_cad: float,
    url_base: str,
    utm_source: str,
    utm_medium: str,
    lead_ref: str | None = None,
    consentement_id: str | None = None,
) -> dict[str, Any]:
    if type_campagne not in TYPES:
        return {"statut": "campagne_invalide", "motif": f"type parmi {sorted(TYPES)} requis"}
    champs = (campagne_id, nom, periode_debut, periode_fin, url_base, utm_source, utm_medium)
    if not all(isinstance(v, str) and v.strip() for v in champs):
        return {"statut": "campagne_invalide", "motif": "id, nom, période, URL, source et medium requis"}
    try:
        debut_date = dt.date.fromisoformat(periode_debut)
        fin_date = dt.date.fromisoformat(periode_fin)
    except (TypeError, ValueError):
        return {"statut": "campagne_invalide", "motif": "périodes ISO 8601 (AAAA-MM-JJ) requises"}
    if fin_date < debut_date:
        return {"statut": "campagne_invalide", "motif": "fin de campagne antérieure au début"}
    if not 2020 <= debut_date.year <= 2099:
        return {"statut": "campagne_invalide", "motif": "année hors contrat UTM (2020–2099)"}
    if (
        isinstance(budget_cad, bool)
        or not isinstance(budget_cad, (int, float))
        or not math.isfinite(budget_cad)
        or budget_cad < 0
    ):
        return {"statut": "campagne_invalide", "motif": "budget CAD fini et positif ou nul requis"}
    registre = stockage.maillons(*REGISTRE)
    if type_campagne == "reference":
        preuve = next(
            (
                m
                for m in registre
                if m.get("type") == "consentement_reference" and m.get("consentement_id") == consentement_id
            ),
            None,
        )
        if preuve is None:
            return {"statut": "consentement_requis", "motif": "référence exige un consentement enregistré"}
    utm_campaign = utm_engine.construire_campaign("workflow", f"{campagne_id}-{type_campagne}", debut_date.year)
    lien = utm_engine.generer_lien_utm(url_base, utm_source, utm_medium, utm_campaign, None)
    echecs = [motif for _regle, verdict, motif in utm_engine.valider_lien_utm(lien) if verdict == "fail"]
    if echecs:
        return {"statut": "utm_invalide", "motifs": echecs}
    payload = {
        "type": "campagne_locale",
        "campagne_id": campagne_id,
        "revision": 1,
        "type_campagne": type_campagne,
        "nom": nom,
        "periode": {"debut": periode_debut, "fin": periode_fin},
        "budget_cad": float(budget_cad),
        "budget_statut": "brouillon",
        "lien_utm": lien,
        "lead_ref": lead_ref,
        "lead_statut": "CRM_non_verifie" if lead_ref else "absent",
        "consentement_id": consentement_id if type_campagne == "reference" else None,
    }
    empreinte = _fp(payload)
    existant = next(
        (m for m in registre if m.get("type") == "campagne_locale" and m.get("campagne_id") == campagne_id), None
    )
    if existant:
        if existant["empreinte"] == empreinte:
            return {"statut": "deja_proposee", "campagne": existant}
        return {"statut": "conflit", "motif": "campagne_id existant avec des paramètres différents"}
    maillon = {**payload, "empreinte": empreinte}
    registre.append(maillon)
    return {
        "statut": "brouillon_propose",
        "campagne": maillon,
        "note": "aucun paiement, envoi ou publication; UTM calculé sans validation CRM",
    }


def approuver_budget(campagne_id: str, revision: int, plafond_cad: float, acteur: dict[str, str]) -> dict[str, Any]:
    registre = stockage.maillons(*REGISTRE)
    propositions = [m for m in registre if m.get("type") == "campagne_locale" and m.get("campagne_id") == campagne_id]
    if not propositions:
        return {"statut": "campagne_inconnue"}
    campagne = propositions[-1]
    if campagne["revision"] != revision:
        return {"statut": "revision_perimee", "revision_courante": campagne["revision"]}
    decision_existante = next(
        (
            m
            for m in reversed(list(registre))
            if m.get("type") == "approbation_budget"
            and m.get("campagne_id") == campagne_id
            and m.get("revision") == revision
            and m.get("empreinte_campagne") == campagne["empreinte"]
        ),
        None,
    )
    if decision_existante:
        return {"statut": "deja_tranche", "decision": decision_existante}
    if (
        not isinstance(plafond_cad, (int, float))
        or isinstance(plafond_cad, bool)
        or not math.isfinite(plafond_cad)
        or plafond_cad < campagne["budget_cad"]
    ):
        return {"statut": "plafond_insuffisant", "budget_cad": campagne["budget_cad"]}
    decision = {
        "type": "approbation_budget",
        "campagne_id": campagne_id,
        "revision": revision,
        "empreinte_campagne": campagne["empreinte"],
        "budget_cad": campagne["budget_cad"],
        "plafond_cad": float(plafond_cad),
        "par": acteur["par"],
        "role": acteur["role"],
        "source": acteur["source"],
    }
    registre.append(decision)
    return {
        "statut": "budget_approuve",
        "decision": decision,
        "note": "approbation de plafond seulement; aucun paiement effectué",
    }


def lire(campagne_id: str) -> dict[str, Any]:
    cnx = stockage.connexion_courante()
    if cnx is None:
        with stockage.transaction():
            return lire(campagne_id)
    maillons = _lire_local_borne(cnx)
    campagne = next(
        (m for m in reversed(maillons) if m.get("type") == "campagne_locale" and m.get("campagne_id") == campagne_id),
        None,
    )
    if campagne is None:
        return {"statut": "campagne_inconnue"}
    decision = next(
        (
            m
            for m in reversed(maillons)
            if m.get("type") == "approbation_budget"
            and m.get("campagne_id") == campagne_id
            and m.get("revision") == campagne["revision"]
            and m.get("empreinte_campagne") == campagne["empreinte"]
        ),
        None,
    )
    return {
        "statut": "ok",
        "campagne": campagne,
        "approbation_budget": decision,
        "crm_statut": campagne["lead_statut"],
        "lien_utm": campagne["lien_utm"],
        "source_couts": _source_couts(campagne),
    }


def _source_couts(campagne: dict[str, Any]) -> dict[str, Any]:
    try:
        champs = {
            "type", "campagne_id", "revision", "type_campagne", "nom", "periode", "budget_cad",
            "budget_statut", "lien_utm", "lead_ref", "lead_statut", "consentement_id", "empreinte",
        }
        if (set(campagne) != champs or campagne["type_campagne"] not in TYPES
                or campagne["budget_statut"] != "brouillon"):
            raise ValueError
        corps = {k: v for k, v in campagne.items() if k != "empreinte"}
        if _fp(corps) != campagne["empreinte"]:
            raise ValueError
        if type(campagne["revision"]) is not int or campagne["revision"] < 1:
            raise ValueError
        if not isinstance(campagne["nom"], str) or not campagne["nom"].strip() or len(campagne["nom"]) > 2048:
            raise ValueError
        if not isinstance(campagne["campagne_id"], str) or not 1 <= len(campagne["campagne_id"]) <= 128:
            raise ValueError
        p = campagne["periode"]
        if not isinstance(p, dict) or set(p) != {"debut", "fin"}:
            raise ValueError
        a, b = dt.date.fromisoformat(p["debut"]), dt.date.fromisoformat(p["fin"])
        if a.isoformat() != p["debut"] or b.isoformat() != p["fin"] or a > b:
            raise ValueError
        budget = campagne["budget_cad"]
        if isinstance(budget, bool) or not isinstance(budget, (int, float)) or not math.isfinite(budget) or budget < 0:
            raise ValueError
        if any(v[1] == "fail" for v in utm_engine.valider_lien_utm(campagne["lien_utm"])):
            raise ValueError
        lien = parse_qs(urlsplit(campagne["lien_utm"]).query, keep_blank_values=True)
        if any(len(lien.get(k, [])) != 1 or not lien[k][0] or len(lien[k][0]) > 128
               for k in ("utm_source", "utm_campaign")):
            raise ValueError
        attendu = utm_engine.construire_campaign(
            "workflow", f"{campagne['campagne_id']}-{campagne['type_campagne']}", a.year,
        )
        if lien["utm_campaign"][0] != attendu:
            raise ValueError
        return {k: campagne[k] for k in ("campagne_id", "revision", "empreinte", "nom", "periode")} | {
            "utm_source": lien["utm_source"][0], "utm_campaign": lien["utm_campaign"][0],
        }
    except (ArithmeticError, AttributeError, KeyError, TypeError, ValueError, RecursionError):
        raise ValueError("LOCAL-SOURCE-CAMPAGNE-INVALIDE") from None


def _lire_local_borne(cnx) -> list[dict[str, Any]]:
    filtre = (REGISTRES.c.departement == REGISTRE[0]) & (REGISTRES.c.registre == REGISTRE[1])
    if cnx.dialect.name == "sqlite":
        octets = func.length(cast(REGISTRES.c.maillon, LargeBinary))
    elif cnx.dialect.name == "postgresql":
        octets = func.octet_length(func.convert_to(REGISTRES.c.maillon, "UTF8"))
    else:
        raise ValueError("LOCAL-BACKEND-NON-PRIS-EN-CHARGE")
    nombre, premier, dernier, total, maximum = cnx.execute(select(
        func.count(), func.min(REGISTRES.c.rang), func.max(REGISTRES.c.rang),
        func.coalesce(func.sum(octets), 0), func.coalesce(func.max(octets), 0),
    ).where(filtre)).one()
    if nombre > 1000 or total > 1024 * 1024 or maximum > 64 * 1024:
        raise ValueError("LOCAL-BORNE-SOURCE")
    if nombre and (premier != 0 or dernier != nombre - 1):
        raise ValueError("LOCAL-PREFIXE-INVALIDE")
    lignes = cnx.execute(select(REGISTRES.c.rang, REGISTRES.c.maillon).where(filtre).order_by(
        REGISTRES.c.rang).limit(1001)).all()
    if len(lignes) != nombre:
        raise ValueError("LOCAL-PREFIXE-INVALIDE")

    def objet(paires):
        resultat = {}
        for cle, valeur in paires:
            if cle in resultat:
                raise ValueError("clé répétée")
            resultat[cle] = valeur
        return resultat

    def constante(_valeur):
        raise ValueError("constante non finie")

    maillons, total_noeuds = [], 0
    try:
        for rang, ligne in enumerate(lignes):
            if ligne.rang != rang:
                raise ValueError
            maillon = json.loads(ligne.maillon, parse_constant=constante, object_pairs_hook=objet)
            pile, noeuds = [(maillon, 0)], 0
            while pile:
                valeur, profondeur = pile.pop()
                noeuds += 1
                total_noeuds += 1
                if profondeur > 16 or noeuds > 2048 or total_noeuds > 500_000:
                    raise ValueError
                if isinstance(valeur, float) and not math.isfinite(valeur):
                    raise ValueError
                if isinstance(valeur, dict):
                    if "__opsys__" in valeur:
                        raise ValueError
                    pile.extend((v, profondeur + 1) for v in valeur.values())
                elif isinstance(valeur, list):
                    pile.extend((v, profondeur + 1) for v in valeur)
            if not isinstance(maillon, dict):
                raise ValueError
            type_ = maillon.get("type")
            if type_ == "campagne_locale":
                _source_couts(maillon)
            elif type_ == "consentement_reference":
                if set(maillon) != {"type", "consentement_id", "personne_ref", "texte_consentement", "source_preuve",
                                    "horodatage", "saisi_par", "empreinte"}:
                    raise ValueError
                if _fp({k: v for k, v in maillon.items() if k not in {"type", "empreinte"}}) != maillon["empreinte"]:
                    raise ValueError
            elif type_ == "approbation_budget":
                # Historique non scellé : cette décision de plafond n'est jamais une preuve de dépense.
                if set(maillon) != {"type", "campagne_id", "revision", "empreinte_campagne", "budget_cad",
                                    "plafond_cad", "par", "role", "source"}:
                    raise ValueError
            else:
                raise ValueError
            maillons.append(maillon)
    except (ArithmeticError, AttributeError, KeyError, TypeError, ValueError, RecursionError):
        raise ValueError("LOCAL-REGISTRE-INVALIDE") from None
    return maillons
