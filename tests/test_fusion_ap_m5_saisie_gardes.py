"""Garde financière : pannes après append, ABA et reçus historiques; fixtures fictives."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest
from m5_financecore import comptes_a_payer, outils, registre, taux_fiscaux
from sqlalchemy import select, update

from opsys import fusion_ap, identite, stockage
from opsys.console import fusion_ap_m5_saisie as service
from opsys.stockage import codec
from opsys.stockage.schema import APPROBATIONS, FUSION_AP_SAISIES, MUTATIONS_APPLIQUEES

FICTIF = True
_SPEC = importlib.util.spec_from_file_location(
    "fixtures_saisie_gardes", Path(__file__).with_name("test_fusion_ap_m5_saisie.py"),
)
assert _SPEC is not None and _SPEC.loader is not None
_BASE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_BASE)
ap_m5_saisie = _BASE.ap_m5_saisie


def test_saisie_ne_modifie_que_les_registres_et_traces_prevus(ap_m5_saisie):
    before = _BASE._FIXTURE._tables()
    resultat = _BASE._resultat(ap_m5_saisie)
    receipt = _BASE._saisir(ap_m5_saisie, resultat)
    after = _BASE._FIXTURE._tables()
    assert {t for t in after if after[t] != before[t]} == {
        "registres_maillons", "approbations", "mutations_appliquees", "journal", "fusion_ap_saisies",
    }
    approval = next(r for r in after["approbations"] if r["id"] == receipt["approbation_id"])
    args = json.loads(approval["arguments"])
    assert set(args) == {"po_id", "fournisseur_id", "numero_facture", "date_facture",
                         "montant_avant_taxes", "total_facture", "horodatage"}
    assert args["total_facture"] == "114.98" and args["po_id"] == "PO-FICTIF-7"
    assert approval["decide_par"] == ap_m5_saisie["acteur"] and approval["niveau"] == "N3"
    assert after["fusion_ap_brouillons"] == before["fusion_ap_brouillons"]


def test_admin_et_finance_peuvent_traiter_lot_prepare_par_autre_humain(ap_m5_saisie):
    with stockage.transaction() as cnx:
        identite.creer_personne(
            cnx, "finance-fictive", "Finance fictive", "mot-de-passe-fictif-123456", ["admin", "finance"],
        )
    ctx = {**ap_m5_saisie, "acteur": "finance-fictive"}
    observation = _BASE._resultat(ctx)
    receipt = _BASE._saisir(ctx, observation)
    with stockage.transaction() as cnx:
        approval = cnx.execute(
            select(APPROBATIONS).where(APPROBATIONS.c.id == receipt["approbation_id"])
        ).mappings().one()
    assert approval["decide_par"] == "finance-fictive" and approval["statut"] == "executee"


@pytest.mark.parametrize("cible", ["taux", "autorite", "insertion", "append_extra"])
def test_panne_apres_saisie_annule_aussi_approbation_recu_et_dette(ap_m5_saisie, monkeypatch, cible):
    observation = _BASE._resultat(ap_m5_saisie)
    before = _BASE._FIXTURE._tables()
    original = outils.saisir_facture_fournisseur

    def apres(**kwargs):
        result = original(**kwargs)
        assert result["accepte"] is True
        if cible == "taux":
            ap_m5_saisie["taux"].write_bytes(ap_m5_saisie["taux"].read_bytes() + b"\n# changement fictif\n")
        elif cible == "autorite":
            identite.retirer_role(stockage.connexion_courante(), ap_m5_saisie["acteur"], "nathan_owner")
        elif cible == "append_extra":
            reg = outils._registre_comptes_a_payer()
            maillon = copy.deepcopy(reg.lire()[-1])
            maillon["numero_facture"] += "-EXTRA-FICTIF"
            reg.ajouter(maillon)
        return result

    monkeypatch.setattr(outils, "saisir_facture_fournisseur", apres)
    if cible == "insertion":
        initial = service.insert

        def panne(table):
            if table is FUSION_AP_SAISIES:
                raise OSError("panne de stockage fictive")
            return initial(table)

        monkeypatch.setattr(service, "insert", panne)
    with pytest.raises((fusion_ap.FusionAPErreur, PermissionError)):
        _BASE._saisir(ap_m5_saisie, observation)
    assert _BASE._FIXTURE._tables() == before


def test_retour_du_texte_initial_avec_revision_avancee_refuse_snapshot_ancien(ap_m5_saisie):
    observation = _BASE._resultat(ap_m5_saisie)
    ctx = ap_m5_saisie
    modifie = copy.deepcopy(ctx["payload"])
    modifie["champs"]["numero"] += "-ABA-FICTIF"
    for version, payload in enumerate([modifie, ctx["payload"]], 1):
        fusion_ap.enregistrer(stockage.transaction, ctx["acteur"], ctx["pdf"]["lot_id"],
                             mutation_id=f"aba-fictif-{version}", revision_pdf_attendue=ctx["pdf"]["revision"],
                             revision_attendue=version, proposition=payload)
    before = _BASE._FIXTURE._tables()
    with pytest.raises(fusion_ap.FusionAPErreur):
        _BASE._saisir(ctx, observation)
    assert _BASE._FIXTURE._tables() == before


@pytest.mark.parametrize("action", ["corriger", "annuler"])
def test_rejeu_conserve_correction_ou_annulation_posterieure(ap_m5_saisie, action):
    observation = _BASE._resultat(ap_m5_saisie)
    receipt = _BASE._saisir(ap_m5_saisie, observation)
    with stockage.transaction():
        reg = registre.Registre(maillons=stockage.maillons("m05-financecore", "comptes_a_payer"))
        (lue,) = [f for f in comptes_a_payer.factures_saisies(reg)
                  if f["facture_fournisseur_id"] == receipt["facture_id"]]
        common = {"facture_fournisseur_id": receipt["facture_id"], "motif": "vérification fictive ultérieure",
                  "role": "nathan_owner", "voie": "appareil", "horodatage": "2026-10-04T12:00:00+00:00",
                  "registre_cible": reg, "revision_attendue": lue["corrections"]}
        if action == "annuler":
            resultat, verdict = comptes_a_payer.annuler_facture_fournisseur(**common, annule_par=ap_m5_saisie["acteur"])
        else:
            dictionnaire, errors = taux_fiscaux.charger_taux_fiscaux(ap_m5_saisie["taux"])
            assert errors == []
            resultat, verdict = comptes_a_payer.corriger_facture_fournisseur(
                **common, corrige_par=ap_m5_saisie["acteur"], numero_facture="NUMERO-CORRIGE-FICTIF",
                date_facture=None, montant_avant_taxes=None, total_facture=None, dictionnaire_taux=dictionnaire,
            )
        assert verdict is None and resultat["facture"]["statut"] == ("ANNULEE" if action == "annuler" else "CORRIGEE")
    before = _BASE._FIXTURE._tables()
    assert _BASE._saisir(ap_m5_saisie, observation) == {**receipt, "rejoue": True}
    assert _BASE._FIXTURE._tables() == before


@pytest.mark.parametrize("cible", ["preuve", "approbation", "recu", "rang"])
def test_recu_corrompu_ne_sert_jamais_d_autorisation_de_rejeu(ap_m5_saisie, cible):
    observation = _BASE._resultat(ap_m5_saisie)
    receipt = _BASE._saisir(ap_m5_saisie, observation)
    with stockage.transaction() as cnx:
        if cible == "preuve":
            cnx.execute(update(FUSION_AP_SAISIES).values(preuve_json="{}"))
        elif cible == "approbation":
            cnx.execute(
                update(APPROBATIONS).where(APPROBATIONS.c.id == receipt["approbation_id"]).values(statut="echec")
            )
        elif cible == "rang":
            cnx.execute(update(FUSION_AP_SAISIES).values(rang_maillon=999))
        else:
            cnx.execute(
                update(MUTATIONS_APPLIQUEES).values(
                    reponse=codec.encoder({**receipt, "facture_id": "autre-fictive"})
                )
            )
        assert cnx.execute(select(FUSION_AP_SAISIES)).first() is not None
    before = _BASE._FIXTURE._tables()
    with pytest.raises(fusion_ap.FusionAPErreur):
        _BASE._saisir(ap_m5_saisie, observation)
    assert _BASE._FIXTURE._tables() == before
