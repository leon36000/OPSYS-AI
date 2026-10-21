"""Composition privée entre la console et le moteur pur de relevés M5."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import Connection

from .. import etat, identite, stockage
from ..departements import Departement
from .securite import Session

_M5 = "m05-financecore"
_ID_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_COMPTE_INTERNE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,63}\Z")


class RapprochementErreur(ValueError):
    """Refus métier stable, mappable en HTTP 409 sans inspecter le texte."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail

    def verdict(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}


FabriqueConnexion = Callable[[], AbstractContextManager[Connection]]


def comptes_configures(deps: Mapping[str, Departement]) -> tuple[str, ...]:
    """Allowlist déclarée de comptes internes ; aucun numéro bancaire n'est accepté ici."""
    departement = deps.get(_M5)
    if departement is None:
        return ()
    chemin: Path = departement.racine / "department.yaml"
    try:
        manifeste = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return ()
    configuration = manifeste.get("configuration") if isinstance(manifeste, Mapping) else None
    banque = configuration.get("banque_csv") if isinstance(configuration, Mapping) else None
    comptes = banque.get("comptes_internes") if isinstance(banque, Mapping) else None
    if not isinstance(comptes, list) or any(
        not isinstance(compte, str) or not _COMPTE_INTERNE.fullmatch(compte) for compte in comptes
    ):
        return ()
    return tuple(sorted(set(comptes)))


def autoriser_page(cnx_factory: FabriqueConnexion, session: Session) -> None:
    """Autorise l'accès préparatoire uniquement après relecture du rôle courant."""
    with cnx_factory() as cnx:
        _exiger_personne(cnx, session.utilisateur)


def _exiger_personne(cnx: Connection, identifiant: str):
    personne = identite.personne_active(cnx, identifiant)
    if personne is None or not personne.roles.intersection({"nathan_owner", "admin"}):
        raise PermissionError("administrateur actif requis")
    return personne


def _lire_factures(registre_module, facturation):
    # Une matérialisation sert à valider la chaîne et à calculer la vue sur le même contenu.
    try:
        maillons = list(stockage.maillons(_M5, "factures"))
        registre = registre_module.Registre(maillons=maillons)
        valide, _ = registre.valider_chaine()
    except (AttributeError, KeyError, TypeError, ValueError):
        raise RapprochementErreur("CHAINE_FACTURES_INVALIDE", "chaîne de factures invalide") from None
    if not valide:
        raise RapprochementErreur("CHAINE_FACTURES_INVALIDE", "chaîne de factures invalide")
    try:
        vue, verdict = facturation.comptes_a_recevoir(registre)
    except (AttributeError, KeyError, TypeError, ValueError):
        raise RapprochementErreur("VUE_FACTURES_INDISPONIBLE", "vue complète des créances indisponible") from None
    if (
        verdict is not None
        or not isinstance(vue, Mapping)
        or not isinstance(vue.get("factures"), list)
        or any(not isinstance(facture, Mapping) for facture in vue["factures"])
    ):
        raise RapprochementErreur("VUE_FACTURES_INDISPONIBLE", "vue complète des créances indisponible")
    snapshot = {
        "version": len(maillons),
        "empreinte": registre.tete(),
        "total_complet": vue.get("total_complet") is True,
        "factures": [
            {"facture_id": facture.get("facture_id"), "montant_apres_taxes": facture.get("montant_apres_taxes")}
            for facture in vue["factures"]
        ],
    }
    return maillons, snapshot


def _revalider_factures(registre_module, facturation, version: int, empreinte: str | None) -> None:
    courant, snapshot = _lire_factures(registre_module, facturation)
    if len(courant) != version or snapshot["empreinte"] != empreinte:
        raise RapprochementErreur("SNAPSHOT_FACTURES_PERIME", "snapshot de factures périmé")


def _reponse_refus(verdict: Mapping[str, Any]) -> dict[str, Any]:
    return {"ok": True, "resultat": {"accepte": False, "verdict": dict(verdict)}}


def previsualiser(
    cnx_factory: FabriqueConnexion,
    deps: Mapping[str, Departement],
    session: Session,
    demande: Mapping[str, Any],
) -> dict[str, Any]:
    """Lit un snapshot M5, calcule une projection pure, puis ajoute une piste distincte append-only."""
    from m5_financecore import encodage, facturation, reconciliation_bancaire_csv
    from m5_financecore import registre as registre_module

    from .. import idempotence

    try:
        contenu = demande["csv_utf8"].encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        raise RapprochementErreur("CSV_UTF8_INVALIDE", "le relevé doit être encodable en UTF-8") from None
    if len(contenu) > 1_048_576:
        raise RapprochementErreur("CSV_TROP_GROS", "relevé hors limite")
    mapping = dict(demande["mapping_colonnes"])
    sha_csv = hashlib.sha256(contenu).hexdigest()
    mapping_json = json.dumps(mapping, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    sha_mapping = hashlib.sha256(mapping_json.encode("utf-8")).hexdigest()

    with cnx_factory() as cnx:
        personne = _exiger_personne(cnx, session.utilisateur)  # après corps, avant tout registre/idempotence
        comptes = comptes_configures(deps)
        if not comptes:
            raise RapprochementErreur("COMPTES_NON_CONFIGURES", "allowlist des comptes internes absente")
        compte_id = demande["compte_interne_id"]
        if compte_id not in comptes:
            raise RapprochementErreur("COMPTE_NON_CONFIGURE", "compte interne non configuré")

        maintenant = datetime.now(UTC)
        meta = idempotence.Meta(
            demande["mutation_id"], f"console:{personne.identifiant}", maintenant.isoformat(timespec="microseconds")
        )
        args_idempotence = {
            "compte_interne_id": compte_id,
            "devise": demande["devise"],
            "sha256_csv": sha_csv,
            "sha256_mapping": sha_mapping,
        }
        try:
            reclamation = idempotence.reclamer(
                cnx, meta, "console_rapprochement_bancaire", args_idempotence, maintenant
            )
        except idempotence.MutationConflit as exc:
            raise RapprochementErreur("CONFLIT_MUTATION", "identifiant de mutation déjà utilisé") from exc
        if reclamation.rejouee:
            _exiger_personne(cnx, session.utilisateur)
            return {**(reclamation.reponse or {}), "rejoue": True}

        _maillons_factures, snapshot = _lire_factures(registre_module, facturation)
        resultat, verdict = reconciliation_bancaire_csv.previsualiser_releve_csv(
            contenu,
            compte_interne_id=compte_id,
            devise=demande["devise"],
            mapping_colonnes=mapping,
            snapshot_factures=snapshot,
        )
        # Revalider l'identité après calcul même lorsque le moteur rend un refus.
        personne = _exiger_personne(cnx, session.utilisateur)
        if verdict is not None or not isinstance(resultat, Mapping):
            reponse = _reponse_refus(verdict or {"code": "REJ-M53", "detail": "relevé refusé"})
            idempotence.finaliser(cnx, meta, reponse)
            return reponse

        lot_id = resultat.get("lot_id")
        if not isinstance(lot_id, str) or not _ID_SHA256.fullmatch(lot_id):
            raise RapprochementErreur("LOT_INVALIDE", "identifiant de lot invalide")
        _revalider_factures(registre_module, facturation, snapshot["version"], snapshot["empreinte"])
        personne = _exiger_personne(cnx, session.utilisateur)

        propositions_store = list(stockage.maillons(_M5, "rapprochements_bancaires_proposes"))
        propositions_registre = registre_module.Registre(maillons=propositions_store)
        try:
            valide, _ = propositions_registre.valider_chaine()
        except (AttributeError, KeyError, TypeError, ValueError):
            raise RapprochementErreur("CHAINE_PROPOSITIONS_INVALIDE", "chaîne des propositions invalide") from None
        if not valide:
            raise RapprochementErreur("CHAINE_PROPOSITIONS_INVALIDE", "chaîne des propositions invalide")
        existant = next(
            (
                ligne for ligne in propositions_store
                if ligne.get("type_entree") == "rapprochement_bancaire_propose" and ligne.get("lot_id") == lot_id
            ),
            None,
        )
        if existant is not None:
            projection = existant.get("resultat")
            if not isinstance(projection, Mapping):
                raise RapprochementErreur("PROJECTION_INVALIDE", "projection de lot invalide")
            _exiger_personne(cnx, session.utilisateur)
            reponse = {"ok": True, "resultat": {"accepte": True, "resultat": dict(projection)}, "rejoue": True}
            idempotence.finaliser(cnx, meta, reponse)
            return reponse

        # Contrôle final juste avant append : rôle et snapshot restent vivants après la vérification des registres.
        personne = _exiger_personne(cnx, session.utilisateur)
        _revalider_factures(registre_module, facturation, snapshot["version"], snapshot["empreinte"])
        resultat_epure = dict(resultat)
        corps = {
            "type_entree": "rapprochement_bancaire_propose",
            "lot_id": lot_id,
            "auteur": personne.identifiant,
            "cree_le": maintenant.isoformat(timespec="seconds"),
            "sha256_mapping": sha_mapping,
            "resultat": resultat_epure,
        }
        precedent = propositions_store[-1].get("ligne_id") if propositions_store else None
        maillon = {
            **corps,
            "ligne_id": encodage.empreinte(corps, precedent),
            "precedent_ligne_id": precedent,
        }
        try:
            stockage.maillons(_M5, "rapprochements_bancaires_proposes").append(
                maillon, rang_attendu=len(propositions_store)
            )
        except stockage.EcritureConcurrente as exc:
            raise RapprochementErreur(
                "CONFLIT_CONCURRENT", "écriture concurrente; rechargez et réessayez"
            ) from exc
        etat.journaliser(
            cnx,
            personne.identifiant,
            "console.rapprochement_bancaire.propose",
            lot_id,
            {
                "sha256_csv": sha_csv,
                "sha256_mapping": sha_mapping,
                "empreinte_factures": resultat_epure.get("source_factures", {}).get("empreinte"),
                "empreinte_vue": resultat_epure.get("source_factures", {}).get("empreinte_vue"),
                "lignes": resultat_epure.get("source_csv", {}).get("lignes"),
                "propositions": len(resultat_epure.get("propositions", [])),
            },
        )
        reponse = {"ok": True, "resultat": {"accepte": True, "resultat": resultat_epure}}
        idempotence.finaliser(cnx, meta, reponse)
        return reponse
