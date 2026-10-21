"""Consultation privée de références AP historiques, données intégralement fictives."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest
from m5_financecore import comptes_a_payer, registre, taux_fiscaux
from sqlalchemy import event, select, update

from opsys import fusion_ap, idempotence, identite, stockage
from opsys.console import fusion_ap_m5_reference as service
from opsys.stockage import codec
from opsys.stockage.schema import (
    APPROBATIONS,
    FUSION_AP_SAISIES,
    FUSION_PDF_LOTS,
    MUTATIONS_APPLIQUEES,
    REGISTRES,
)

FICTIF = True
_SPEC = importlib.util.spec_from_file_location(
    "fixtures_reference_ap", Path(__file__).with_name("test_fusion_ap_m5_saisie.py"),
)
assert _SPEC is not None and _SPEC.loader is not None
_BASE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_BASE)


@pytest.fixture
def ap_reference(request, monkeypatch, tmp_path):
    return _BASE.ap_m5_saisie.__wrapped__(request, monkeypatch, tmp_path)


def _saisie(ctx):
    resultat = _BASE._resultat(ctx)
    return _BASE._saisir(ctx, resultat)


def _lire(ctx, acteur=None):
    return service.lire(stockage.transaction, acteur or ctx["acteur"], ctx["pdf"]["lot_id"])


@pytest.mark.parametrize("action,statut,corrections", [
    ("aucune", "SAISIE", 0), ("corriger", "CORRIGEE", 1), ("annuler", "ANNULEE", 0),
])
def test_reference_reconnectee_lit_etat_courant_sans_relire_taux(ap_reference, action, statut, corrections):
    ctx = ap_reference
    before = _BASE._FIXTURE._tables()
    if action == "aucune":
        assert _lire(ctx) is None
        assert _BASE._FIXTURE._tables() == before
    receipt = _saisie(ctx)
    if action != "aucune":
        lue = _lire(ctx)
        assert (lue["statut_m5"], lue["corrections"]) == ("SAISIE", 0), "la révision lue avant le geste"
        with stockage.transaction():
            reg = registre.Registre(maillons=stockage.maillons("m05-financecore", "comptes_a_payer"))
            args = {
                "facture_fournisseur_id": receipt["facture_id"],
                "motif": "modification fictive de vérification", "role": "nathan_owner",
                "voie": "appareil", "horodatage": "2026-10-04T12:00:00+00:00", "registre_cible": reg,
                "revision_attendue": lue["corrections"],
            }
            if action == "annuler":
                resultat, verdict = comptes_a_payer.annuler_facture_fournisseur(
                    **args, annule_par=ctx["acteur"],
                )
            else:
                dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(ctx["taux"])
                assert erreurs == []
                resultat, verdict = comptes_a_payer.corriger_facture_fournisseur(
                    **args, corrige_par=ctx["acteur"], numero_facture="NUMERO-CORRIGE-FICTIF",
                    date_facture=None, montant_avant_taxes=None, total_facture=None,
                    dictionnaire_taux=dictionnaire,
                )
            assert verdict is None
    ctx["taux"].write_bytes(b"schema_version: [")
    before_read = _BASE._FIXTURE._tables()
    attendu = {
        "facture_id": receipt["facture_id"], "approbation_id": receipt["approbation_id"],
        "statut_m5": statut, "corrections": corrections,
    }
    assert _lire(ctx) == attendu
    assert _lire(ctx) == attendu  # reprise/reconnexion; le résultat ne dépend pas du fichier de taux courant
    assert _BASE._FIXTURE._tables() == before_read


def test_intersection_owner_ou_admin_finance_et_autorite_reverifiee(ap_reference):
    ctx = ap_reference
    _saisie(ctx)
    with stockage.transaction() as cnx:
        identite.creer_personne(
            cnx, "admin-finance-fictif", "Admin Finance fictif", "mot-de-passe-fictif-123456",
            ["admin", "finance"],
        )
        identite.creer_personne(
            cnx, "finance-seul-fictif", "Finance seul fictif", "mot-de-passe-fictif-123456", ["finance"],
        )
        identite.creer_personne(
            cnx, "admin-seul-fictif", "Admin seul fictif", "mot-de-passe-fictif-123456", ["admin"],
        )
    attendu = _lire(ctx)
    assert _lire(ctx, "admin-finance-fictif") == attendu
    before = _BASE._FIXTURE._tables()
    for acteur in ("finance-seul-fictif", "admin-seul-fictif"):
        with pytest.raises(PermissionError):
            _lire(ctx, acteur)
    assert _BASE._FIXTURE._tables() == before


def test_retrait_role_pendant_consultation_annule_le_rendu_et_la_transaction(ap_reference, monkeypatch):
    ctx = ap_reference
    _saisie(ctx)
    before = _BASE._FIXTURE._tables()
    original = service.fusion_ap_m5._finance
    appels = 0

    def retirer_avant_garde_finale(cnx, acteur):
        nonlocal appels
        appels += 1
        if appels == 2:
            identite.retirer_role(cnx, acteur, "nathan_owner")
        return original(cnx, acteur)

    monkeypatch.setattr(service.fusion_ap_m5, "_finance", retirer_avant_garde_finale)
    with pytest.raises(PermissionError):
        _lire(ctx)
    assert appels == 2
    assert _BASE._FIXTURE._tables() == before


def test_statut_du_recu_idempotent_ne_remplace_pas_son_corps_canonique(ap_reference):
    ctx = ap_reference
    receipt = _saisie(ctx)
    with stockage.transaction() as cnx:
        cnx.execute(update(MUTATIONS_APPLIQUEES).where(
            MUTATIONS_APPLIQUEES.c.appareil == f"console:{ctx['acteur']}",
        ).values(statut="refus_metier"))
    before = _BASE._FIXTURE._tables()
    assert _lire(ctx) == {
        "facture_id": receipt["facture_id"], "approbation_id": receipt["approbation_id"],
        "statut_m5": "SAISIE", "corrections": 0,
    }
    assert _BASE._FIXTURE._tables() == before


def test_reference_persiste_si_pdf_historique_devient_indisponible(ap_reference):
    ctx = ap_reference
    receipt = _saisie(ctx)
    with stockage.transaction() as cnx:
        cnx.execute(update(FUSION_PDF_LOTS).where(
            FUSION_PDF_LOTS.c.lot_id == ctx["pdf"]["lot_id"],
        ).values(source_cipher="!"))
    before = _BASE._FIXTURE._tables()
    assert _lire(ctx) == {
        "facture_id": receipt["facture_id"], "approbation_id": receipt["approbation_id"],
        "statut_m5": "SAISIE", "corrections": 0,
    }
    assert _BASE._FIXTURE._tables() == before


@pytest.mark.parametrize("cible", ["preuve", "approbation", "corps_approbation", "recu", "maillon"])
def test_corruption_historique_refusee_sans_ecriture(ap_reference, cible):
    ctx = ap_reference
    receipt = _saisie(ctx)
    with stockage.transaction() as cnx:
        if cible == "preuve":
            cnx.execute(update(FUSION_AP_SAISIES).where(
                FUSION_AP_SAISIES.c.lot_id == ctx["pdf"]["lot_id"],
            ).values(preuve_json="{}"))
        elif cible == "approbation":
            cnx.execute(update(APPROBATIONS).where(
                APPROBATIONS.c.id == receipt["approbation_id"],
            ).values(niveau="N2"))
        elif cible == "corps_approbation":
            approbation = cnx.execute(select(APPROBATIONS).where(
                APPROBATIONS.c.id == receipt["approbation_id"],
            )).mappings().one()
            contenu = json.loads(approbation["resultat"])
            contenu["resultat"]["resultat"]["facture"]["montant_apres_taxes"] = "999.99"
            cnx.execute(update(APPROBATIONS).where(
                APPROBATIONS.c.id == receipt["approbation_id"],
            ).values(resultat=json.dumps(contenu, ensure_ascii=False)))
        elif cible == "recu":
            cnx.execute(update(MUTATIONS_APPLIQUEES).where(
                (MUTATIONS_APPLIQUEES.c.appareil == f"console:{ctx['acteur']}")
                & (MUTATIONS_APPLIQUEES.c.cle_idempotence == "fusion-ap-saisie-1"),
            ).values(reponse=codec.encoder({"statut": "SAISIE_M5_REFERENCEE", "facture_id": "autre"})))
        else:
            rang = cnx.execute(select(FUSION_AP_SAISIES.c.rang_maillon).where(
                FUSION_AP_SAISIES.c.lot_id == ctx["pdf"]["lot_id"],
            )).scalar_one()
            maillon = cnx.execute(select(REGISTRES.c.maillon).where(
                (REGISTRES.c.departement == "m05-financecore")
                & (REGISTRES.c.registre == "comptes_a_payer")
                & (REGISTRES.c.rang == rang),
            )).scalar_one()
            entree = codec.decoder(maillon)
            entree["montant_apres_taxes"] = "999.99"
            cnx.execute(update(REGISTRES).where(
                (REGISTRES.c.departement == "m05-financecore")
                & (REGISTRES.c.registre == "comptes_a_payer")
                & (REGISTRES.c.rang == rang),
            ).values(maillon=codec.encoder(entree)))
    before = _BASE._FIXTURE._tables()
    with pytest.raises(fusion_ap.FusionAPErreur) as refuse:
        _lire(ctx)
    assert refuse.value.statut_http == 503
    assert _BASE._FIXTURE._tables() == before


def test_source_historique_est_bornee_et_rang_lie_au_snapshot(ap_reference):
    ctx = ap_reference
    _saisie(ctx)
    with stockage.transaction() as cnx:
        row = cnx.execute(select(FUSION_AP_SAISIES).where(
            FUSION_AP_SAISIES.c.lot_id == ctx["pdf"]["lot_id"],
        )).mappings().one()
        preuve = copy.deepcopy(json.loads(row["preuve_json"]))
        preuve["rang_maillon"] += 1
        cnx.execute(update(FUSION_AP_SAISIES).where(
            FUSION_AP_SAISIES.c.lot_id == ctx["pdf"]["lot_id"],
        ).values(preuve_json=json.dumps(preuve, ensure_ascii=False)))
    before = _BASE._FIXTURE._tables()
    with pytest.raises(fusion_ap.FusionAPErreur):
        _lire(ctx)
    assert _BASE._FIXTURE._tables() == before


def test_approbation_hors_borne_est_refusee_avant_son_decodage(ap_reference, monkeypatch):
    ctx = ap_reference
    _saisie(ctx)
    monkeypatch.setattr(service, "_MAX_APPROBATION_JSON", 1)
    monkeypatch.setattr(service, "_arguments", lambda *_: pytest.fail("JSON d'approbation chargé hors borne"))
    before = _BASE._FIXTURE._tables()
    with pytest.raises(fusion_ap.FusionAPErreur) as refuse:
        _lire(ctx)
    assert refuse.value.statut_http == 503
    assert _BASE._FIXTURE._tables() == before


@pytest.mark.parametrize("cible", ["rang", "schema", "prefixe"])
def test_preuve_rehashée_ne_valide_pas_un_faux_lien_historique(ap_reference, cible):
    ctx = ap_reference
    _saisie(ctx)
    lot_id = ctx["pdf"]["lot_id"]
    with stockage.transaction() as cnx:
        ligne = cnx.execute(select(FUSION_AP_SAISIES).where(
            FUSION_AP_SAISIES.c.lot_id == lot_id,
        )).mappings().one()
        preuve = json.loads(ligne["preuve_json"])
        changement = {}
        if cible == "rang":
            assert ligne["rang_maillon"] > 0
            preuve["rang_maillon"] = 0
            changement["rang_maillon"] = 0
        elif cible == "schema":
            preuve["schema"] = True
        else:
            preuve["pre_registre_sha256"] = "0" * 64
        preuve["preuve_mutation_sha256"] = service._sha({cle: preuve[cle] for cle in (
            "schema", "source", "snapshot_id", "mapping_sha256", "arguments_sha256", "pre_registre_sha256",
        )})
        preuve["preuve_sha256"] = service._sha({
            cle: valeur for cle, valeur in preuve.items() if cle != "preuve_sha256"
        })
        cnx.execute(update(FUSION_AP_SAISIES).where(FUSION_AP_SAISIES.c.lot_id == lot_id).values(
            preuve_json=json.dumps(preuve, ensure_ascii=False), **changement,
        ))
        cnx.execute(update(MUTATIONS_APPLIQUEES).where(
            (MUTATIONS_APPLIQUEES.c.appareil == f"console:{ctx['acteur']}")
            & (MUTATIONS_APPLIQUEES.c.cle_idempotence == ligne["mutation_id"])
        ).values(empreinte_arguments=idempotence.empreinte_arguments({
            "lot_id": lot_id, "commande_sha256": ligne["commande_sha256"],
            "preuve_sha256": preuve["preuve_mutation_sha256"],
        })))
    avant = _BASE._FIXTURE._tables()
    with pytest.raises(fusion_ap.FusionAPErreur) as refus:
        _lire(ctx)
    assert refus.value.statut_http == 503
    assert _BASE._FIXTURE._tables() == avant


@pytest.mark.parametrize("cible", ["arguments", "resultat", "reponse"])
def test_payload_hors_borne_n_est_pas_selectionne_en_entier(ap_reference, cible):
    ctx = ap_reference
    receipt = _saisie(ctx)
    with stockage.transaction() as cnx:
        if cible == "reponse":
            table = MUTATIONS_APPLIQUEES
            cnx.execute(update(table).where(
                table.c.appareil == f"console:{ctx['acteur']}",
            ).values(reponse="x" * 4097))
        else:
            table = APPROBATIONS
            cnx.execute(update(table).where(table.c.id == receipt["approbation_id"]).values(
                **{cible: "x" * 32769},
            ))
    avant = _BASE._FIXTURE._tables()
    mesures = []

    def verifier_projection(_cnx, _curseur, statement, _parameters, _context, _many):
        projection = statement.lower().split("from", 1)[0]
        colonne = f"{table.name}.{cible}"
        if projection.lstrip().startswith("select") and colonne in projection:
            if "length(" not in projection:
                pytest.fail("payload hors borne sélectionné en entier")
            mesures.append(colonne)

    moteur = stockage.moteur()
    event.listen(moteur, "before_cursor_execute", verifier_projection)
    try:
        with pytest.raises(fusion_ap.FusionAPErreur) as refus:
            _lire(ctx)
        assert refus.value.statut_http == 503 and mesures
    finally:
        event.remove(moteur, "before_cursor_execute", verifier_projection)
    assert _BASE._FIXTURE._tables() == avant


@pytest.mark.parametrize("non_fini", ["NaN", "Infinity"])
def test_taxes_historiques_non_finies_refusees(ap_reference, non_fini):
    ctx = ap_reference
    receipt = _saisie(ctx)
    with stockage.transaction() as cnx:
        contenu = json.loads(cnx.execute(select(APPROBATIONS.c.resultat).where(
            APPROBATIONS.c.id == receipt["approbation_id"],
        )).scalar_one())
        contenu["resultat"]["resultat"]["facture"]["taxes"][0]["montant"] = non_fini
        cnx.execute(update(APPROBATIONS).where(APPROBATIONS.c.id == receipt["approbation_id"]).values(
            resultat=json.dumps(contenu),
        ))
    avant = _BASE._FIXTURE._tables()
    with pytest.raises(fusion_ap.FusionAPErreur) as refus:
        _lire(ctx)
    assert refus.value.statut_http == 503
    assert _BASE._FIXTURE._tables() == avant


def test_admin_revoque_avec_finance_sur_chemin_sans_liaison(ap_reference, monkeypatch):
    ctx = ap_reference
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "lecteur-fictif", "Lecteur fictif", "mot-de-passe-fictif-123456",
                               ["admin", "finance"])
    avant = _BASE._FIXTURE._tables()
    finance = service.fusion_ap_m5._finance

    def retirer_admin(cnx, acteur):
        finance(cnx, acteur)
        identite.retirer_role(cnx, acteur, "admin")

    monkeypatch.setattr(service.fusion_ap_m5, "_finance", retirer_admin)
    with pytest.raises(PermissionError):
        _lire(ctx, "lecteur-fictif")
    assert _BASE._FIXTURE._tables() == avant
