"""Lecture privée de la référence durable Fusion vers l'état courant M5."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import LargeBinary, cast, func, select
from sqlalchemy.exc import SQLAlchemyError

from opsys import fusion_ap, fusion_pdf, idempotence, identite
from opsys.stockage import codec
from opsys.stockage.schema import APPROBATIONS, FUSION_AP_SAISIES, MUTATIONS_APPLIQUEES

from . import fusion_ap_m5, fusion_ap_m5_saisie

_OUTIL = "m5_saisir_facture_fournisseur"
_SOURCE_KEYS = frozenset({
    "revision_pdf", "revision_ap", "source_sha256", "configuration_sha256",
    "proposition_sha256", "registre", "taux_sha256",
})
_OCR_SOURCE_KEYS = _SOURCE_KEYS | frozenset({
    "source_type", "ocr_run_id", "revision_run", "ocr_configuration_sha256", "ocr_profil_id",
})
_PREUVE_KEYS = frozenset({
    "schema", "source", "snapshot_id", "mapping_sha256", "arguments_sha256",
    "pre_registre_sha256", "preuve_mutation_sha256", "commande_sha256", "facture_id",
    "maillon_id", "rang_maillon", "preuve_sha256",
})
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MAX_PREUVE = 4_096
_MAX_APPROBATION_JSON = 32 * 1_024
_MAX_RECU = 4_096
_MAX_CORRECTIONS = 10_000
_MAX_TAXES = 16


def _erreur() -> fusion_ap.FusionAPErreur:
    return fusion_pdf._erreur("M5_REFERENCE_INDISPONIBLE", 503)


def _json(valeur: Any) -> str:
    return json.dumps(valeur, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sha(valeur: Any) -> str:
    return hashlib.sha256(_json(valeur).encode("utf-8")).hexdigest()


def _est_sha(valeur: Any) -> bool:
    return isinstance(valeur, str) and _SHA.fullmatch(valeur) is not None


def _preuve_valide(lot_id: str, ligne: Mapping[str, Any], preuve: Any) -> dict[str, Any]:
    if (
        not isinstance(preuve, dict) or set(preuve) != _PREUVE_KEYS
        or type(preuve.get("schema")) is not int or preuve["schema"] != 1
    ):
        raise _erreur()
    if any(not _est_sha(preuve.get(cle)) for cle in (
        "snapshot_id", "mapping_sha256", "arguments_sha256", "pre_registre_sha256",
        "preuve_mutation_sha256", "commande_sha256", "maillon_id", "preuve_sha256",
    )):
        raise _erreur()
    if (
        preuve["commande_sha256"] != ligne["commande_sha256"]
        or preuve["facture_id"] != ligne["facture_id"]
        or preuve["maillon_id"] != ligne["maillon_id"]
        or type(preuve["rang_maillon"]) is not int
        or preuve["rang_maillon"] < 0
        or preuve["rang_maillon"] != ligne["rang_maillon"]
    ):
        raise _erreur()
    source = preuve["source"]
    if not isinstance(source, dict) or frozenset(source) not in {_SOURCE_KEYS, _OCR_SOURCE_KEYS}:
        raise _erreur()
    if (
        type(source["revision_pdf"]) is not int or source["revision_pdf"] < 1
        or type(source["revision_ap"]) is not int or source["revision_ap"] < 1
        or any(not _est_sha(source.get(cle)) for cle in (
            "source_sha256", "configuration_sha256", "proposition_sha256", "taux_sha256",
        ))
    ):
        raise _erreur()
    if set(source) == _OCR_SOURCE_KEYS:
        run_id = source["ocr_run_id"]
        try:
            run_uuid = uuid.UUID(run_id) if isinstance(run_id, str) else None
        except (ValueError, AttributeError):
            run_uuid = None
        if (
            source["source_type"] != "OCR_CANDIDAT"
            or run_uuid is None or str(run_uuid) != run_id
            or type(source["revision_run"]) is not int or source["revision_run"] < 1
            or not _est_sha(source["ocr_configuration_sha256"])
            or source["ocr_profil_id"] != "ocr-scan-2"
        ):
            raise _erreur()
    registre = source["registre"]
    if (
        not isinstance(registre, dict) or set(registre) != {"taille", "tete"}
        or type(registre["taille"]) is not int or not 0 <= registre["taille"] <= fusion_ap_m5._MAX_ROWS
        or (registre["tete"] is not None and not _est_sha(registre["tete"]))
    ):
        raise _erreur()
    snapshot = _sha({"schema": 1, "lot_id": lot_id, "source": source})
    if snapshot != preuve["snapshot_id"]:
        raise _erreur()
    if _sha({cle: preuve[cle] for cle in (
        "schema", "source", "snapshot_id", "mapping_sha256", "arguments_sha256", "pre_registre_sha256",
    )}) != preuve["preuve_mutation_sha256"]:
        raise _erreur()
    if _sha({cle: valeur for cle, valeur in preuve.items() if cle != "preuve_sha256"}) != preuve["preuve_sha256"]:
        raise _erreur()
    return preuve


def _arguments(
    approbation: Mapping[str, Any], preuve: Mapping[str, Any], lot_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    brut = approbation["arguments"]
    if not isinstance(brut, str) or len(brut.encode("utf-8")) > _MAX_APPROBATION_JSON:
        raise _erreur()
    args = json.loads(brut)
    attendus = {
        "po_id", "fournisseur_id", "numero_facture", "date_facture",
        "montant_avant_taxes", "total_facture", "horodatage",
    }
    if not isinstance(args, dict) or set(args) != attendus:
        raise _erreur()
    six = {cle: args[cle] for cle in attendus if cle != "horodatage"}
    if any(not isinstance(valeur, str) or not valeur for valeur in six.values()):
        raise _erreur()
    if not isinstance(args["horodatage"], str) or not args["horodatage"]:
        raise _erreur()
    mapping_sha = _sha({"po_id": six["po_id"], "fournisseur_id": six["fournisseur_id"]})
    if mapping_sha != preuve["mapping_sha256"]:
        raise _erreur()
    if idempotence.empreinte_arguments(six) != preuve["arguments_sha256"]:
        raise _erreur()
    # La commande a été empreintée par la saisie avec l'encodeur JSON par défaut
    # (ensure_ascii=True); les autres empreintes de preuve gardent ensure_ascii=False.
    commande = hashlib.sha256(json.dumps({
        "snapshot_id": preuve["snapshot_id"],
        "po_id": six["po_id"],
        "fournisseur_id": six["fournisseur_id"],
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    if commande != preuve["commande_sha256"]:
        raise _erreur()
    clepreuve = _sha({cle: preuve[cle] for cle in (
        "schema", "source", "snapshot_id", "mapping_sha256", "arguments_sha256", "pre_registre_sha256",
    )})
    idem_args = {"lot_id": lot_id, "commande_sha256": commande, "preuve_sha256": clepreuve}
    return args, idem_args


def _longueurs_approbation(cnx: Any, ident: str) -> tuple[int, int]:
    tailles = cnx.execute(select(
        func.length(cast(APPROBATIONS.c.arguments, LargeBinary)),
        func.length(cast(APPROBATIONS.c.resultat, LargeBinary)),
    ).where(APPROBATIONS.c.id == ident)).one_or_none()
    if tailles is None or tailles[0] is None or tailles[1] is None:
        raise _erreur()
    if tailles[0] > _MAX_APPROBATION_JSON or tailles[1] > _MAX_APPROBATION_JSON:
        raise _erreur()
    return int(tailles[0]), int(tailles[1])


def _approbation(
    approbation: Mapping[str, Any], ligne: Mapping[str, Any], args: Mapping[str, Any],
) -> dict[str, Any]:
    if (
        approbation is None or approbation["statut"] != "executee"
        or approbation["outil"] != _OUTIL or approbation["departement"] != "m05-financecore"
        or approbation["niveau"] != "N3" or approbation["decide_par"] != ligne["acteur"]
        or approbation["decide_role"] not in {"finance", "nathan_owner"}
    ):
        raise _erreur()
    if approbation["arguments"] != _json(dict(args)):
        # La chaîne sérialisée peut garder un ordre historique différent; l'égalité JSON reste exacte.
        try:
            if json.loads(approbation["arguments"]) != dict(args):
                raise _erreur()
        except (TypeError, ValueError) as exc:
            raise _erreur() from exc
    brut = approbation["resultat"]
    if not isinstance(brut, str) or len(brut.encode("utf-8")) > _MAX_APPROBATION_JSON:
        raise _erreur()
    resultat = json.loads(brut)
    if (
        not isinstance(resultat, dict) or resultat.get("ok") is not True
        or not isinstance(resultat.get("resultat"), dict)
        or resultat["resultat"].get("accepte") is not True
        or not isinstance(resultat["resultat"].get("resultat"), dict)
    ):
        raise _erreur()
    return resultat


def _calcul_historique(args: Mapping[str, Any], facture: Mapping[str, Any]) -> dict[str, Any]:
    montant_brut = args["montant_avant_taxes"]
    total_brut = args["total_facture"]
    if (
        not isinstance(montant_brut, str) or not fusion_ap_m5._MONTANT.fullmatch(montant_brut)
        or not isinstance(total_brut, str) or not fusion_ap_m5._MONTANT.fullmatch(total_brut)
    ):
        raise _erreur()
    try:
        avant, apres = Decimal(montant_brut), Decimal(total_brut)
        taxes_lues = facture["taxes"]
        if not avant.is_finite() or not apres.is_finite() or not isinstance(taxes_lues, list):
            raise _erreur()
        if not 1 <= len(taxes_lues) <= _MAX_TAXES:
            raise _erreur()
        taxes: list[dict[str, Any]] = []
        total_taxes = Decimal("0")
        for taxe in taxes_lues:
            if (
                not isinstance(taxe, dict) or not isinstance(taxe.get("id"), str) or not taxe["id"]
                or not isinstance(taxe.get("version"), str) or not taxe["version"]
                or not isinstance(taxe.get("montant"), str)
                or not fusion_ap_m5._MONTANT.fullmatch(taxe["montant"])
            ):
                raise _erreur()
            valeur = Decimal(taxe["montant"])
            if not valeur.is_finite() or valeur < 0:
                raise _erreur()
            total_taxes += valeur
            taxes.append({"id": taxe["id"], "version": taxe["version"], "montant": valeur})
        if (
            total_taxes != apres - avant
            or Decimal(str(facture["montant_avant_taxes"])) != avant
            or Decimal(str(facture["total_taxes"])) != total_taxes
            or Decimal(str(facture["montant_apres_taxes"])) != apres
        ):
            raise _erreur()
    except (KeyError, TypeError, ValueError, InvalidOperation, ArithmeticError) as exc:
        raise _erreur() from exc
    return {
        "montant_avant_taxes": avant, "total_taxes": total_taxes,
        "montant_apres_taxes": apres, "taxes": taxes,
    }


def _recu(
    cnx: Any, ligne: Mapping[str, Any], commande: str, idem_args: Mapping[str, Any],
) -> None:
    appareil = f"console:{ligne['acteur']}"
    mutation = ligne["mutation_id"]
    taille = cnx.execute(select(func.length(cast(MUTATIONS_APPLIQUEES.c.reponse, LargeBinary))).where(
        (MUTATIONS_APPLIQUEES.c.appareil == appareil)
        & (MUTATIONS_APPLIQUEES.c.cle_idempotence == mutation)
    )).scalar_one_or_none()
    if taille is None or taille > _MAX_RECU:
        raise _erreur()
    recu = cnx.execute(select(MUTATIONS_APPLIQUEES).where(
        (MUTATIONS_APPLIQUEES.c.appareil == appareil)
        & (MUTATIONS_APPLIQUEES.c.cle_idempotence == mutation)
    )).mappings().one_or_none()
    if recu is None or recu["outil"] != _OUTIL:
        raise _erreur()
    if idempotence.empreinte_arguments(idem_args) != recu["empreinte_arguments"]:
        raise _erreur()
    brut = recu["reponse"]
    if not isinstance(brut, str) or len(brut.encode("utf-8")) > _MAX_RECU:
        raise _erreur()
    receipt = codec.decoder(brut)
    attendu = {
        "statut": "SAISIE_M5_REFERENCEE", "facture_id": ligne["facture_id"],
        "approbation_id": ligne["approbation_id"], "commande_sha256": commande, "rejoue": False,
    }
    if receipt != attendu:
        raise _erreur()


def lire(
    fabrique: fusion_pdf.FabriqueConnexion, acteur: str, lot_id: str,
) -> dict[str, Any] | None:
    """Lit l'identifiant historique et l'état courant, sans relire PDF ni taux ni écrire."""
    try:
        with fusion_pdf._transaction(fabrique, acteur) as cnx:
            fusion_ap_m5._finance(cnx, acteur)
            ligne = cnx.execute(select(FUSION_AP_SAISIES).where(
                FUSION_AP_SAISIES.c.lot_id == lot_id,
            )).mappings().one_or_none()
            if ligne is None:
                personne = identite.personne_active(cnx, acteur)
                if personne is None or not (
                    "nathan_owner" in personne.roles or {"admin", "finance"} <= personne.roles
                ):
                    raise PermissionError("autorité de consultation AP révoquée")
                return None
            brut_preuve = ligne["preuve_json"]
            if not isinstance(brut_preuve, str) or len(brut_preuve.encode("utf-8")) > _MAX_PREUVE:
                raise _erreur()
            preuve = _preuve_valide(lot_id, ligne, json.loads(brut_preuve))
            _longueurs_approbation(cnx, ligne["approbation_id"])
            approbation_brute = cnx.execute(select(APPROBATIONS).where(
                APPROBATIONS.c.id == ligne["approbation_id"],
            )).mappings().one_or_none()
            if approbation_brute is None:
                raise _erreur()
            args, idem_args = _arguments(approbation_brute, preuve, lot_id)
            resultat_approval = _approbation(approbation_brute, ligne, args)
            commande = preuve["commande_sha256"]
            _recu(cnx, ligne, commande, idem_args)

            maillons, _ = fusion_ap_m5._maillons(cnx)
            rang = preuve["rang_maillon"]
            if rang >= len(maillons):
                raise _erreur()
            maillon = maillons[rang]
            if (
                maillon.get("ligne_id") != ligne["maillon_id"]
                or maillon.get("facture_fournisseur_id") != ligne["facture_id"]
                or preuve["source"]["registre"]["taille"] != rang
                or preuve["source"]["registre"]["tete"] != (
                    maillons[rang - 1].get("ligne_id") if rang else None
                )
            ):
                raise _erreur()
            sortie = resultat_approval["resultat"]["resultat"]
            facture = sortie["facture"]
            calcul = _calcul_historique(args, facture)
            fusion_ap_m5_saisie._verifier_recu(
                cnx, ligne, preuve, preuve["source"],
                {cle: args[cle] for cle in (
                    "po_id", "fournisseur_id", "numero_facture", "date_facture",
                    "montant_avant_taxes", "total_facture",
                )},
                calcul,
            )
            courant = fusion_ap_m5.comptes_a_payer._etats_factures(maillons).get(ligne["facture_id"])
            if courant is None:
                raise _erreur()
            statut = courant.get("statut")
            corrections = courant.get("corrections")
            if (
                statut not in {"SAISIE", "CORRIGEE", "ANNULEE"}
                or type(corrections) is not int or not 0 <= corrections <= _MAX_CORRECTIONS
            ):
                raise _erreur()
            fusion_ap_m5._finance(cnx, acteur)
            personne = identite.personne_active(cnx, acteur)
            if personne is None or not (
                "nathan_owner" in personne.roles or {"admin", "finance"} <= personne.roles
            ):
                raise PermissionError("autorité de consultation AP révoquée")
            return {
                "facture_id": ligne["facture_id"], "approbation_id": ligne["approbation_id"],
                "statut_m5": statut, "corrections": corrections,
            }
    except (fusion_ap.FusionAPErreur, PermissionError):
        raise
    except (OSError, ValueError, TypeError, KeyError, ArithmeticError, SQLAlchemyError, RuntimeError) as exc:
        raise _erreur() from exc
