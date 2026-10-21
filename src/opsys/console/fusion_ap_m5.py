"""Observation privée des contrôles AP M5; aucun appel de saisie ni écriture."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from m5_financecore import comptes_a_payer, outils, registre, taux_fiscaux
from sqlalchemy import LargeBinary, cast, func, select
from sqlalchemy.exc import SQLAlchemyError

from opsys import fusion_ap, fusion_pdf, identite
from opsys.stockage import codec
from opsys.stockage.schema import REGISTRES

_MONTANT = re.compile(r"[0-9]{1,12}(?:\.[0-9]{1,2})?\Z")
_MAX_ROWS = 10_000
_MAX_BYTES = 8 * 1024 * 1024
_MAX_ROW_BYTES = 64 * 1024
_MAX_TAUX_BYTES = 64 * 1024


def _erreur(code: str, status: int = 409) -> fusion_ap.FusionAPErreur:
    return fusion_pdf._erreur(code, status)


def _finance(cnx: Any, acteur: str) -> None:
    personne = identite.personne_active(cnx, acteur)
    if personne is None or not personne.roles.intersection({"finance", "nathan_owner"}):
        raise PermissionError("accès financier privé requis")


def _taux_octets() -> bytes:
    with Path(outils._CHEMIN_TAUX_FISCAUX).open("rb") as flux:
        raw = flux.read(_MAX_TAUX_BYTES + 1)
    if len(raw) > _MAX_TAUX_BYTES:
        raise _erreur("M5_TAUX_INDISPONIBLES", 503)
    return raw


def _maillons(cnx: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    filt = (REGISTRES.c.departement == "m05-financecore") & (REGISTRES.c.registre == "comptes_a_payer")
    size = func.length(cast(REGISTRES.c.maillon, LargeBinary))
    count, total, largest, first, last = cnx.execute(select(
        func.count(), func.coalesce(func.sum(size), 0), func.coalesce(func.max(size), 0),
        func.min(REGISTRES.c.rang), func.max(REGISTRES.c.rang),
    ).where(filt)).one()
    if (count > _MAX_ROWS or total > _MAX_BYTES or largest > _MAX_ROW_BYTES
            or (count and (first != 0 or last != count - 1))):
        raise _erreur("M5_REGISTRE_INDISPONIBLE", 503)
    rows = [codec.decoder(row[0]) for row in cnx.execute(
        select(REGISTRES.c.maillon).where(filt).order_by(REGISTRES.c.rang)
    )]
    chaine = registre.Registre(maillons=rows)
    if not chaine.valider_chaine()[0]:
        raise _erreur("M5_REGISTRE_INDISPONIBLE", 503)
    return rows, {"taille": count, "tete": chaine.tete()}


def _sources(cnx: Any, acteur: str, lot_id: str, revision_pdf: int, revision_ap: int) -> tuple[dict, dict, list, bytes]:
    _finance(cnx, acteur)
    if type(revision_ap) is not int or revision_ap < 1:
        raise _erreur("REVISION_AP_INVALIDE", 400)
    lot = fusion_pdf._lot(cnx, lot_id)
    fusion_pdf._compatible(lot)
    source_ocr = fusion_ap._source_ocr_enregistree(cnx, lot)
    if source_ocr is None:
        # Garder le chemin natif historique inchangé, y compris sa validation du PDF chiffré.
        lot, resultat = fusion_ap._verifier_pdf(cnx, lot_id, revision_pdf)
        fusion_pdf._source(lot)
        brouillon, proposition = fusion_ap._lire_brouillon(cnx, lot, resultat)
        provenance: dict[str, Any] = {}
    else:
        # Le lot OCR est volontairement REFUSE côté parseur natif. Le lecteur OCR
        # vérifie dans cette transaction run, PDF courant, chiffrement/AAD et citations.
        if type(revision_pdf) is not int or revision_pdf < 1 or lot["revision"] != revision_pdf:
            raise _erreur("CONFLIT_REVISION_PDF")
        provenance, _ = source_ocr
        brouillon, proposition = fusion_ap._lire_brouillon(
            cnx, lot, dechiffrer_ocr=True,
        )
    if brouillon["revision"] != revision_ap:
        raise _erreur("CONFLIT_REVISION")
    if proposition is None:
        raise _erreur("BROUILLON_INDISPONIBLE", 503)
    rows, refs = _maillons(cnx)
    raw = _taux_octets()
    source = {
        "revision_pdf": revision_pdf, "revision_ap": revision_ap,
        "source_sha256": brouillon["source_sha256"],
        "configuration_sha256": brouillon["configuration_sha256"],
        "proposition_sha256": hashlib.sha256(json.dumps(
            proposition, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        ).encode("utf-8")).hexdigest(),
        "registre": refs, "taux_sha256": hashlib.sha256(raw).hexdigest(),
    } | provenance
    return source, proposition["champs"], rows, raw


def _identifiant(valeur: Any) -> str:
    if (not isinstance(valeur, str) or not valeur.strip() or valeur != valeur.strip()
            or len(valeur) > 64 or not valeur.isprintable()):
        raise _erreur("IDENTIFIANT_M5_INVALIDE", 400)
    return valeur


def _montant(champs: Mapping[str, str], cle: str) -> str:
    valeur = champs.get(cle)
    if not isinstance(valeur, str) or not _MONTANT.fullmatch(valeur):
        raise _erreur("AP_MONTANTS_A_REVOIR")
    return valeur


def _verifier_cnx(
    cnx: Any, acteur: str, lot_id: str, *, revision_pdf: int, revision_ap: int,
    po_id: str, fournisseur_id: str, correspondance_confirmee: bool,
) -> tuple[dict[str, Any], dict[str, str], bytes]:
    """Contrôle pur dans la transaction du pont; arguments/bytes restent côté serveur."""
    _finance(cnx, acteur)
    po_id, fournisseur_id = _identifiant(po_id), _identifiant(fournisseur_id)
    if correspondance_confirmee is not True:
        raise _erreur("AP_CORRESPONDANCE_A_REVOIR", 400)
    source, champs, rows, raw = _sources(cnx, acteur, lot_id, revision_pdf, revision_ap)
    if not champs["fournisseur"].strip() or not champs["po"].strip():
        raise _erreur("AP_CORRESPONDANCE_A_REVOIR")
    if champs["devise"] != "CAD":
        raise _erreur("REJ-AP-DEVISE-NON-CAD")
    montant = _montant(champs, "sous_total_imprime")
    total = _montant(champs, "total_imprime")
    taxes_imprimees = _montant(champs, "taxe_imprimee")
    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(
        outils._CHEMIN_TAUX_FISCAUX, contenu_octets=raw,
    )
    if erreurs:
        raise _erreur("M5_TAUX_INDISPONIBLES", 503)
    observe_le = datetime.now(UTC).isoformat(timespec="seconds")
    calcul, verdict = comptes_a_payer.verifier_facture_fournisseur(
        po_id=po_id, fournisseur_id=fournisseur_id, numero_facture=champs["numero"],
        date_facture=champs["date"], montant_avant_taxes=montant, total_facture=total,
        saisi_par=acteur, voie="appareil", horodatage=observe_le,
        dictionnaire_taux=dictionnaire, maillons=rows,
    )
    if verdict is not None:
        raise _erreur(verdict["code"])
    if calcul is None:
        raise _erreur("M5_CALCUL_INDISPONIBLE", 503)
    if Decimal(taxes_imprimees) != calcul["total_taxes"]:
        raise _erreur("AP_TAXES_IMPRIMEES_INCOHERENTES")
    current, _, _, _ = _sources(cnx, acteur, lot_id, revision_pdf, revision_ap)
    if current != source:
        raise _erreur("AP_SOURCES_MODIFIEES")
    snapshot_id = hashlib.sha256(json.dumps(
        {"schema": 1, "lot_id": lot_id, "source": source}, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    resultat = {
        "statut": "CONTROLES_M5_COMPATIBLES", "source": source,
        "snapshot_id": snapshot_id, "observe_le": observe_le,
        "calcul": {
            cle: format(calcul[cle], ".2f")
            for cle in ("montant_avant_taxes", "total_taxes", "montant_apres_taxes")
        } | {"taxes": [
            {cle: ligne[cle] for cle in ("id", "version")}
            | {"source": dictionnaire[ligne["id"]]["source"],
               "montant": format(ligne["montant"], ".2f")}
            for ligne in calcul["taxes"]
        ]},
        "avertissements": calcul["avertissements"],
    }
    resultat["commande_sha256"] = hashlib.sha256(json.dumps(
        {"snapshot_id": snapshot_id, "po_id": po_id, "fournisseur_id": fournisseur_id},
        sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    arguments = {"po_id": po_id, "fournisseur_id": fournisseur_id,
                 "numero_facture": champs["numero"], "date_facture": champs["date"],
                 "montant_avant_taxes": montant, "total_facture": total}
    return resultat, arguments, raw


def verifier(
    fabrique: fusion_pdf.FabriqueConnexion, acteur: str, lot_id: str, *,
    revision_pdf: int, revision_ap: int, po_id: str, fournisseur_id: str,
    correspondance_confirmee: bool,
) -> dict[str, Any]:
    """Lit le snapshot courant, contrôle puis le relit. Rien n'est confirmé ou conservé."""
    try:
        with fusion_pdf._transaction(fabrique, acteur) as cnx:
            resultat, _, _ = _verifier_cnx(
                cnx, acteur, lot_id, revision_pdf=revision_pdf, revision_ap=revision_ap,
                po_id=po_id, fournisseur_id=fournisseur_id,
                correspondance_confirmee=correspondance_confirmee,
            )
            return resultat

    except (fusion_ap.FusionAPErreur, PermissionError):
        raise
    except (OSError, ValueError, TypeError, KeyError, ArithmeticError, SQLAlchemyError, yaml.YAMLError) as exc:
        raise _erreur("M5_VERIFICATION_INDISPONIBLE", 503) from exc


def confirmer_sources(
    fabrique: fusion_pdf.FabriqueConnexion, acteur: str, lot_id: str, resultat: Mapping[str, Any],
) -> None:
    """Garde terminale, sans jeton d'autorisation ni stockage du verdict préparatoire."""
    try:
        with fusion_pdf._transaction(fabrique, acteur) as cnx:
            source = resultat["source"]
            current, _, _, _ = _sources(cnx, acteur, lot_id, source["revision_pdf"], source["revision_ap"])
            if current != source:
                raise _erreur("AP_SOURCES_MODIFIEES")
    except (fusion_ap.FusionAPErreur, PermissionError):
        raise
    except (OSError, ValueError, TypeError, KeyError, ArithmeticError, SQLAlchemyError, yaml.YAMLError) as exc:
        raise _erreur("M5_VERIFICATION_INDISPONIBLE", 503) from exc
