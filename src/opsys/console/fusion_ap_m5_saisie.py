"""Saisie AP M5 à partir d'un lot Fusion, liée et rejouable sans dupliquer la facture."""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.exc import SQLAlchemyError

from opsys import approbations, contexte, fusion_ap, fusion_pdf, idempotence, identite
from opsys.outils import Autonomie, Niveau, Outil
from opsys.stockage.schema import APPROBATIONS, FUSION_AP_SAISIES

from . import fusion_ap_m5

_OUTIL = "m5_saisir_facture_fournisseur"
_MODULE_M5 = "m5_financecore.outils"
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MUTATION = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")


def _erreur(code: str, statut: int = 409) -> fusion_ap.FusionAPErreur:
    return fusion_pdf._erreur(code, statut)


def _json(valeur: Any) -> str:
    return json.dumps(valeur, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sha(valeur: Any) -> str:
    return hashlib.sha256(_json(valeur).encode("utf-8")).hexdigest()


def _lire_registre(cnx: Any) -> list[dict[str, Any]]:
    return fusion_ap_m5._maillons(cnx)[0]


def _empreinte_registre(maillons: list[Mapping[str, Any]]) -> str:
    return _sha([maillon.get("ligne_id") for maillon in maillons])


def _sans_registre(source: Mapping[str, Any]) -> dict[str, Any]:
    return {cle: valeur for cle, valeur in source.items() if cle != "registre"}


def _calculer_taxes(arguments: Mapping[str, str], raw_taux: bytes) -> dict[str, Any]:
    from m5_financecore import taxes

    dictionnaire, erreurs = fusion_ap_m5.taux_fiscaux.charger_taux_fiscaux(
        fusion_ap_m5.outils._CHEMIN_TAUX_FISCAUX, contenu_octets=raw_taux,
    )
    if erreurs:
        raise _erreur("M5_TAUX_INDISPONIBLES", 503)
    calcul, verdict = taxes.calculer_taxes(fusion_ap_m5.Decimal(arguments["montant_avant_taxes"]), dictionnaire)
    if verdict is not None or calcul is None:
        raise _erreur(verdict["code"] if verdict else "M5_CALCUL_INDISPONIBLE", 503)
    if arguments["total_facture"] is not None and fusion_ap_m5.Decimal(arguments["total_facture"]) != calcul[
        "montant_apres_taxes"
    ]:
        raise _erreur("AP_TAXES_IMPRIMEES_INCOHERENTES")
    return calcul


def _verifier_corps_facture(
    maillon: Mapping[str, Any], facture: Mapping[str, Any], arguments: Mapping[str, str], acteur: str,
    horodatage: str, calcul: Mapping[str, Any], facture_id: str,
) -> None:
    champs = ("po_id", "fournisseur_id", "numero_facture", "date_facture")
    if any(maillon.get(champ) != arguments.get(champ) or facture.get(champ) != arguments.get(champ)
           for champ in champs):
        raise _erreur("AP_RECU_INVALIDE", 503)
    if (
        maillon.get("type_entree") != "facture_fournisseur_saisie"
        or maillon.get("facture_fournisseur_id") != facture_id
        or facture.get("facture_fournisseur_id") != facture_id
        or maillon.get("statut") != "SAISIE" or facture.get("statut") != "SAISIE"
        or maillon.get("saisi_par") != acteur or facture.get("saisi_par") != acteur
        or maillon.get("voie") != "approbation" or facture.get("voie") != "approbation"
        or maillon.get("horodatage") != horodatage or facture.get("horodatage") != horodatage
        or maillon.get("avertissements") != facture.get("avertissements")
    ):
        raise _erreur("AP_RECU_INVALIDE", 503)
    for cle in ("montant_avant_taxes", "total_taxes", "montant_apres_taxes"):
        if (
            fusion_ap_m5.Decimal(str(maillon[cle])) != fusion_ap_m5.Decimal(str(facture[cle]))
            or fusion_ap_m5.Decimal(str(maillon[cle])) != fusion_ap_m5.Decimal(str(calcul[cle]))
        ):
            raise _erreur("AP_RECU_INVALIDE", 503)
    taxes_maillon, taxes_facture, taxes_calcul = maillon["taxes"], facture["taxes"], calcul["taxes"]
    if len(taxes_maillon) != len(taxes_facture) or len(taxes_maillon) != len(taxes_calcul):
        raise _erreur("AP_RECU_INVALIDE", 503)
    for ligne, sortie, attendue in zip(taxes_maillon, taxes_facture, taxes_calcul, strict=True):
        if (
            ligne.get("id") != sortie.get("id") or ligne.get("version") != sortie.get("version")
            or ligne.get("id") != attendue.get("id") or ligne.get("version") != attendue.get("version")
            or fusion_ap_m5.Decimal(str(ligne.get("montant")))
            != fusion_ap_m5.Decimal(str(sortie.get("montant")))
            or fusion_ap_m5.Decimal(str(ligne.get("montant")))
            != fusion_ap_m5.Decimal(str(attendue.get("montant")))
        ):
            raise _erreur("AP_RECU_INVALIDE", 503)


def _preuve_actuelle(
    cnx: Any, acteur: str, lot_id: str, revision_pdf: int, revision_ap: int,
    po_id: str, fournisseur_id: str,
) -> tuple[dict[str, Any], dict[str, str], bytes, dict[str, Any]]:
    source, champs, maillons, taux = fusion_ap_m5._sources(
        cnx, acteur, lot_id, revision_pdf, revision_ap,
    )
    if (
        champs.get("devise") != "CAD" or not champs.get("po", "").strip()
        or not champs.get("fournisseur", "").strip()
    ):
        raise _erreur("AP_CORRESPONDANCE_A_REVOIR")
    arguments = {
        "po_id": fusion_ap_m5._identifiant(po_id),
        "fournisseur_id": fusion_ap_m5._identifiant(fournisseur_id),
        "numero_facture": champs.get("numero"),
        "date_facture": champs.get("date"),
        "montant_avant_taxes": fusion_ap_m5._montant(champs, "sous_total_imprime"),
        "total_facture": fusion_ap_m5._montant(champs, "total_imprime"),
    }
    if not isinstance(arguments["numero_facture"], str) or not isinstance(arguments["date_facture"], str):
        raise _erreur("AP_MONTANTS_A_REVOIR")
    taxes_imprimees = fusion_ap_m5._montant(champs, "taxe_imprimee")
    calcul_taxes = _calculer_taxes(arguments, taux)
    if fusion_ap_m5.Decimal(taxes_imprimees) != calcul_taxes["total_taxes"]:
        raise _erreur("AP_TAXES_IMPRIMEES_INCOHERENTES")
    del maillons
    return source, arguments, taux, calcul_taxes


def _charger_outil(deps: Mapping[str, Any], raw_taux: bytes) -> Outil:
    dep = deps.get("m05-financecore") if isinstance(deps, Mapping) else None
    if dep is None or getattr(dep, "module_outils", None) != _MODULE_M5:
        raise _erreur("M5_OUTIL_INDISPONIBLE", 503)
    try:
        import importlib

        module = importlib.import_module(_MODULE_M5)
        outils = dep.charger_outils()
    except (ImportError, AttributeError, TypeError, ValueError) as exc:
        raise _erreur("M5_OUTIL_INDISPONIBLE", 503) from exc
    if module.__name__ != _MODULE_M5:
        raise _erreur("M5_OUTIL_INDISPONIBLE", 503)
    cible = [outil for outil in outils if outil.nom == _OUTIL]
    if len(cible) != 1:
        raise _erreur("M5_OUTIL_INDISPONIBLE", 503)
    outil = cible[0]
    if outil.autonomie is not Autonomie.T1 or outil.niveau_effectif is not Niveau.N3:
        raise _erreur("M5_OUTIL_INDISPONIBLE", 503)

    def saisir_avec_taux(**arguments: Any) -> Any:
        return module.saisir_facture_fournisseur(**arguments, contenu_taux=raw_taux)

    return dataclasses.replace(outil, fonction=saisir_avec_taux)


def _receipt(ligne: Mapping[str, Any], *, rejoue: bool) -> dict[str, Any]:
    return {
        "statut": "SAISIE_M5_REFERENCEE", "facture_id": ligne["facture_id"],
        "approbation_id": ligne["approbation_id"], "commande_sha256": ligne["commande_sha256"],
        "rejoue": rejoue,
    }


def _verifier_recu(
    cnx: Any, ligne: Mapping[str, Any], preuve: Mapping[str, Any], source: Mapping[str, Any],
    arguments_courants: Mapping[str, str], calcul: Mapping[str, Any],
) -> None:
    if (
        ligne["commande_sha256"] != preuve.get("commande_sha256")
        or ligne["facture_id"] != preuve.get("facture_id")
        or ligne["maillon_id"] != preuve.get("maillon_id")
        or _sha({cle: valeur for cle, valeur in preuve.items() if cle != "preuve_sha256"})
        != preuve.get("preuve_sha256")
    ):
        raise _erreur("AP_RECU_INVALIDE", 503)
    if _sans_registre(source) != _sans_registre(preuve["source"]):
        raise _erreur("AP_SOURCES_MODIFIEES")
    rang = ligne["rang_maillon"]
    maillons = _lire_registre(cnx)
    if type(rang) is not int or rang < 0 or rang >= len(maillons):
        raise _erreur("AP_RECU_INVALIDE", 503)
    maillon = maillons[rang]
    if _empreinte_registre(maillons[:rang]) != preuve.get("pre_registre_sha256"):
        raise _erreur("AP_RECU_INVALIDE", 503)
    if (
        maillon.get("ligne_id") != ligne["maillon_id"]
        or maillon.get("facture_fournisseur_id") != ligne["facture_id"]
    ):
        raise _erreur("AP_RECU_INVALIDE", 503)
    approval = cnx.execute(
        select(APPROBATIONS).where(APPROBATIONS.c.id == ligne["approbation_id"])
    ).mappings().one_or_none()
    if (
        approval is None or approval["statut"] != "executee" or approval["outil"] != _OUTIL
        or approval["departement"] != "m05-financecore"
        or approval["decide_par"] != ligne["acteur"]
    ):
        raise _erreur("AP_RECU_INVALIDE", 503)
    try:
        arguments_approval = json.loads(approval["arguments"])
    except (TypeError, ValueError) as exc:
        raise _erreur("AP_RECU_INVALIDE", 503) from exc
    arguments_approval.pop("horodatage", None)
    if idempotence.empreinte_arguments(arguments_approval) != preuve.get("arguments_sha256"):
        raise _erreur("AP_RECU_INVALIDE", 503)
    if any(arguments_approval.get(cle) != valeur for cle, valeur in arguments_courants.items()):
        raise _erreur("AP_RECU_INVALIDE", 503)
    arguments_approval = json.loads(approval["arguments"])
    try:
        resultat = json.loads(approval["resultat"])
        facture = resultat["resultat"]["resultat"]["facture"]
    except (TypeError, ValueError, KeyError) as exc:
        raise _erreur("AP_RECU_INVALIDE", 503) from exc
    _verifier_corps_facture(
        maillon, facture, arguments_approval, ligne["acteur"], arguments_approval["horodatage"],
        calcul, ligne["facture_id"],
    )


def saisir(
    fabrique: fusion_pdf.FabriqueConnexion, acteur: str, lot_id: str, *, deps: Mapping[str, Any],
    revision_pdf: int, revision_ap: int, po_id: str, fournisseur_id: str,
    correspondance_confirmee: bool, saisie_confirmee: bool, snapshot_attendu: str, mutation_id: str,
) -> dict[str, Any]:
    """Exécute la saisie confirmée sous approbation N3 et lie son reçu à la source Fusion."""
    if correspondance_confirmee is not True or saisie_confirmee is not True:
        raise _erreur("AP_CONFIRMATION_REQUISE", 400)
    if not isinstance(snapshot_attendu, str) or not _SHA.fullmatch(snapshot_attendu):
        raise _erreur("AP_SNAPSHOT_INVALIDE", 400)
    if not isinstance(mutation_id, str) or not _MUTATION.fullmatch(mutation_id):
        raise _erreur("MUTATION_INVALIDE", 400)
    try:
        with fusion_pdf._transaction(fabrique, acteur) as cnx:
            fusion_ap_m5._finance(cnx, acteur)
            po_id = fusion_ap_m5._identifiant(po_id)
            fournisseur_id = fusion_ap_m5._identifiant(fournisseur_id)
            ancien = cnx.execute(select(FUSION_AP_SAISIES).where(
                FUSION_AP_SAISIES.c.lot_id == lot_id,
            )).mappings().one_or_none()
            source, args6, raw_taux, calcul_actuel = _preuve_actuelle(
                cnx, acteur, lot_id, revision_pdf, revision_ap, po_id, fournisseur_id,
            )
            mapping_sha = _sha({"po_id": po_id, "fournisseur_id": fournisseur_id})
            hash_args = idempotence.empreinte_arguments(args6)
            maintenant = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
            meta = idempotence.Meta(mutation_id, f"console:{acteur}", maintenant)

            if ancien is not None:
                preuve = json.loads(ancien["preuve_json"])
                if ancien["acteur"] != acteur or ancien["mutation_id"] != mutation_id:
                    raise _erreur("AP_LOT_DEJA_SAISI")
                if (preuve.get("mapping_sha256") != mapping_sha or preuve.get("arguments_sha256") != hash_args
                        or ancien["commande_sha256"] != snapshot_attendu):
                    raise _erreur("CONFLIT_MUTATION")
                commande_attendue = hashlib.sha256(json.dumps({
                    "snapshot_id": preuve.get("snapshot_id"), "po_id": po_id, "fournisseur_id": fournisseur_id,
                }, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
                if commande_attendue != ancien["commande_sha256"]:
                    raise _erreur("CONFLIT_MUTATION")
                _verifier_recu(cnx, ancien, preuve, source, args6, calcul_actuel)
                prepreuve = {cle: preuve[cle] for cle in (
                    "schema", "source", "snapshot_id", "mapping_sha256", "arguments_sha256", "pre_registre_sha256",
                )}
                clepreuve = _sha(prepreuve)
                if clepreuve != preuve.get("preuve_mutation_sha256"):
                    raise _erreur("AP_RECU_INVALIDE", 503)
                reclamation = idempotence.reclamer(cnx, meta, _OUTIL, {
                    "lot_id": lot_id, "commande_sha256": commande_attendue, "preuve_sha256": clepreuve,
                }, dt.datetime.now(dt.UTC))
                if not reclamation.rejouee or not isinstance(reclamation.reponse, Mapping):
                    raise _erreur("AP_RECU_INVALIDE", 503)
                attendu = _receipt(ancien, rejoue=False)
                if dict(reclamation.reponse) != attendu:
                    raise _erreur("AP_RECU_INVALIDE", 503)
                fusion_ap_m5._finance(cnx, acteur)
                personne = identite.personne_active(cnx, acteur)
                if personne is None or not ("nathan_owner" in personne.roles or {"admin", "finance"} <= personne.roles):
                    raise PermissionError("autorité de saisie AP révoquée")
                return {**dict(reclamation.reponse), "rejoue": True}

            resultat, args6_verifies, raw_taux = fusion_ap_m5._verifier_cnx(
                cnx, acteur, lot_id, revision_pdf=revision_pdf, revision_ap=revision_ap,
                po_id=po_id, fournisseur_id=fournisseur_id, correspondance_confirmee=True,
            )
            if resultat.get("commande_sha256") != snapshot_attendu:
                raise _erreur("AP_SNAPSHOT_MODIFIE")
            if args6_verifies != args6:
                raise _erreur("AP_SOURCES_MODIFIEES")
            if _sans_registre(source) != _sans_registre(resultat["source"]):
                raise _erreur("AP_SOURCES_MODIFIEES")
            outil = _charger_outil(deps, raw_taux)
            rows_avant = _lire_registre(cnx)
            snapshot_id = resultat["snapshot_id"]
            commande = resultat["commande_sha256"]
            preuve: dict[str, Any] = {
                "schema": 1, "source": resultat["source"], "snapshot_id": snapshot_id,
                "mapping_sha256": mapping_sha, "arguments_sha256": hash_args,
                "pre_registre_sha256": _empreinte_registre(rows_avant),
            }
            preuve_sha = _sha(preuve)
            preuve_mutation = {"lot_id": lot_id, "commande_sha256": commande, "preuve_sha256": preuve_sha}
            reclamation = idempotence.reclamer(cnx, meta, _OUTIL, preuve_mutation, dt.datetime.now(dt.UTC))
            if reclamation.rejouee:
                raise _erreur("AP_RECU_INVALIDE", 503)

            args_outil = dict(args6_verifies)
            args_outil["horodatage"] = maintenant
            approbation_id = approbations.creer_demande(
                cnx, "m05-financecore", _OUTIL, args_outil, niveau=Niveau.N3,
                motif="Saisie AP explicitement confirmée depuis Fusion; facture interne SAISIE seulement.",
            )
            with contexte.appele_par_appareil(None):
                resultat_approbation = approbations.decider(
                    cnx, approbation_id, True, acteur, {_OUTIL: outil}, deps,
                    motif="Confirmation humaine Fusion AP; aucun paiement ni écriture finale.",
                )
            if resultat_approbation.get("statut") != "executee":
                raise _erreur("M5_SAISIE_REFUSEE")
            execution = resultat_approbation.get("reponse")
            sortie = execution.get("resultat") if isinstance(execution, Mapping) else None
            facture = sortie.get("resultat", {}).get("facture") if isinstance(sortie, Mapping) else None
            if (
                not isinstance(execution, Mapping) or execution.get("ok") is not True
                or not isinstance(sortie, Mapping) or sortie.get("accepte") is not True
                or not isinstance(facture, Mapping) or facture.get("statut") != "SAISIE"
                or facture.get("po_id") != po_id or facture.get("fournisseur_id") != fournisseur_id
                or facture.get("numero_facture") != args6_verifies["numero_facture"]
                or facture.get("date_facture") != args6_verifies["date_facture"]
                or facture.get("saisi_par") != acteur or facture.get("voie") != "approbation"
                or facture.get("horodatage") != args_outil["horodatage"]
                or facture.get("avertissements") != resultat["avertissements"]
            ):
                raise _erreur("M5_SAISIE_INCOHERENTE", 503)
            try:
                for cle, champ_facture in (
                    ("montant_avant_taxes", "montant_avant_taxes"),
                    ("total_taxes", "total_taxes"),
                    ("montant_apres_taxes", "montant_apres_taxes"),
                ):
                    valeur_facture = fusion_ap_m5.Decimal(str(facture[champ_facture]))
                    valeur_attendue = fusion_ap_m5.Decimal(resultat["calcul"][cle])
                    if valeur_facture != valeur_attendue:
                        raise _erreur("M5_SAISIE_INCOHERENTE", 503)
                taxes_facture = facture["taxes"]
                taxes_attendues = resultat["calcul"]["taxes"]
                if len(taxes_facture) != len(taxes_attendues) or any(
                    taxe.get("id") != attendu.get("id") or taxe.get("version") != attendu.get("version")
                    or fusion_ap_m5.Decimal(str(taxe.get("montant")))
                    != fusion_ap_m5.Decimal(attendu["montant"])
                    for taxe, attendu in zip(taxes_facture, taxes_attendues, strict=True)
                ):
                    raise _erreur("M5_SAISIE_INCOHERENTE", 503)
            except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
                raise _erreur("M5_SAISIE_INCOHERENTE", 503) from exc
            facture_id = facture.get("facture_fournisseur_id")
            if not isinstance(facture_id, str) or not facture_id:
                raise _erreur("M5_SAISIE_INCOHERENTE", 503)
            rows_apres = _lire_registre(cnx)
            if len(rows_apres) != len(rows_avant) + 1 or rows_apres[:-1] != rows_avant:
                raise _erreur("M5_APPEND_INATTENDU", 503)
            maillon = rows_apres[-1]
            if (
                maillon.get("type_entree") != "facture_fournisseur_saisie"
                or maillon.get("facture_fournisseur_id") != facture_id
            ):
                raise _erreur("M5_APPEND_INATTENDU", 503)
            if (
                maillon.get("saisi_par") != acteur or maillon.get("voie") != "approbation"
                or maillon.get("po_id") != po_id or maillon.get("fournisseur_id") != fournisseur_id
            ):
                raise _erreur("M5_APPEND_INATTENDU", 503)
            _verifier_corps_facture(
                maillon, facture, args_outil, acteur, args_outil["horodatage"],
                resultat["calcul"], facture_id,
            )
            ligne_registre = len(rows_apres) - 1
            preuve.update({"preuve_mutation_sha256": preuve_sha, "commande_sha256": commande, "facture_id": facture_id,
                           "maillon_id": maillon["ligne_id"], "rang_maillon": ligne_registre})
            preuve["preuve_sha256"] = _sha(preuve)
            # Les secrets/source en clair ne sont jamais recopiés; le document AP reste chiffré dans son propriétaire.
            preuve_json = _json({cle: preuve[cle] for cle in (
                "schema", "source", "snapshot_id", "mapping_sha256", "arguments_sha256",
                "pre_registre_sha256", "preuve_mutation_sha256", "commande_sha256", "facture_id",
                "maillon_id", "rang_maillon", "preuve_sha256",
            )})
            if len(preuve_json.encode("utf-8")) > 4096:
                raise _erreur("AP_PREUVE_TROP_LONGUE", 503)
            lien = {
                "lot_id": lot_id, "acteur": acteur, "mutation_id": mutation_id,
                "commande_sha256": commande, "preuve_json": preuve_json,
                "approbation_id": approbation_id, "facture_id": facture_id,
                "maillon_id": maillon["ligne_id"], "rang_maillon": ligne_registre,
                "cree_le": maintenant,
            }
            cnx.execute(insert(FUSION_AP_SAISIES).values(**lien))
            terminal, _, _, _ = fusion_ap_m5._sources(cnx, acteur, lot_id, revision_pdf, revision_ap)
            if _sans_registre(terminal) != _sans_registre(resultat["source"]):
                raise _erreur("AP_SOURCES_MODIFIEES")
            fusion_ap_m5._finance(cnx, acteur)
            personne = identite.personne_active(cnx, acteur)
            if personne is None or not ("nathan_owner" in personne.roles or {"admin", "finance"} <= personne.roles):
                raise PermissionError("autorité de saisie AP révoquée")
            receipt = {
                "statut": "SAISIE_M5_REFERENCEE", "facture_id": facture_id,
                "approbation_id": approbation_id, "commande_sha256": commande, "rejoue": False,
            }
            idempotence.finaliser(cnx, meta, receipt)
            if _lire_registre(cnx) != rows_apres:
                raise _erreur("M5_APPEND_INATTENDU", 503)
            return receipt
    except (fusion_ap.FusionAPErreur, PermissionError):
        raise
    except (OSError, ValueError, TypeError, KeyError, ArithmeticError, SQLAlchemyError) as exc:
        raise _erreur("M5_SAISIE_INDISPONIBLE", 503) from exc
