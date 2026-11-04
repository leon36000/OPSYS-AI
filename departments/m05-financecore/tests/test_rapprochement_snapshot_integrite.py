"""Contrats publics du rapprochement : snapshot et refus des chaînes financières altérées."""
from __future__ import annotations

from contextlib import suppress

import pytest
from sqlalchemy import select, update

from opsys import stockage
from opsys.stockage.codec import decoder, encoder
from opsys.stockage.schema import REGISTRES


@pytest.fixture
def m5_public(tmp_path, monkeypatch, m5_test_helpers):
    gl_helpers = m5_test_helpers
    fixture = gl_helpers.base_durable._fixture_function(tmp_path, monkeypatch)
    url = next(fixture)
    gl_helpers.declare._fixture_function(tmp_path, monkeypatch)({"categories_depense_sans_po": ["carburant"]})
    tools = {outil.nom: outil for outil in gl_helpers.m5_outils.outils()}
    try:
        yield tools, url, gl_helpers
    finally:
        with suppress(StopIteration):
            next(fixture)
        stockage.liberer(url)


def _refus_chaine(tools, code, gl_helpers):
    response = gl_helpers._appeler(tools, "m5_rapprocher_grand_livre", gl_helpers.OCTOBRE)
    assert response["ok"] is True
    assert response["resultat"]["accepte"] is False, response
    assert response["resultat"]["verdict"]["code"] == code
    return response["resultat"]["verdict"]


def _alterer(url, nom_registre, alteration):
    with stockage.transaction(url) as cnx:
        texte = cnx.execute(select(REGISTRES.c.maillon).where(
            REGISTRES.c.departement == "m05-financecore", REGISTRES.c.registre == nom_registre,
            REGISTRES.c.rang == 0,
        )).scalar_one()
        maillon = decoder(texte)
        maillon = alteration(maillon)
        cnx.execute(update(REGISTRES).where(
            REGISTRES.c.departement == "m05-financecore", REGISTRES.c.registre == nom_registre,
            REGISTRES.c.rang == 0,
        ).values(maillon=encoder(maillon)))


def _facture_fournisseur(tools, gl_helpers):
    response = gl_helpers._appeler(tools, "m5_saisir_facture_sans_po", {
        "fournisseur_id": "fournisseur-fictif", "categorie": "carburant", "numero_facture": "AP-FICTIF",
        "date_facture": "2026-10-01", "montant_avant_taxes": "100.00", "total_facture": None,
        "horodatage": gl_helpers.SAISIE,
    }, gl_helpers.COMPTABLE)
    assert response["ok"] and response["resultat"]["accepte"], response
    return response["resultat"]["resultat"]["facture"]["facture_fournisseur_id"]


def _note_credit_fournisseur(tools, gl_helpers):
    facture_id = _facture_fournisseur(tools, gl_helpers)
    finance = gl_helpers.lire_manifeste(gl_helpers._RACINE_M5)
    generated = gl_helpers._appeler(tools, "m5_generer_brouillons_comptables", {"horodatage": gl_helpers.H})
    draft = generated["resultat"]["resultat"]["brouillons_crees"][0]
    gl_helpers._valider_par_la_file(finance, draft["ecriture_id"])
    note = gl_helpers._appeler(tools, "m5_proposer_note_credit", {
        "genre": "fournisseur", "facture_id": facture_id, "reference": "NC-OPS-FICTIF",
        "montant_avant_taxes": "50.00", "date_effet": "2026-10-02", "motif": "motif fictif",
        "horodatage": gl_helpers.H,
    })
    assert note["ok"] and note["resultat"]["accepte"], note


def _rehacher_operation(url, modification, gl_helpers):
    operations = gl_helpers.m5_outils.operations_registre
    with stockage.transaction(url) as cnx:
        texte = cnx.execute(select(REGISTRES.c.maillon).where(
            REGISTRES.c.departement == "m05-financecore", REGISTRES.c.registre == "operations_comptables",
            REGISTRES.c.rang == 0,
        )).scalar_one()
        maillon = modification(decoder(texte))
        maillon["empreinte_contenu"] = operations._empreinte_contenu(
            maillon["type_entree"], operations._corps(maillon)
        )
        body = {key: value for key, value in maillon.items() if key not in ("ligne_id", "precedent_ligne_id")}
        chain = gl_helpers.m5_outils.registre_module.Registre()
        chain.ajouter(body)
        cnx.execute(update(REGISTRES).where(
            REGISTRES.c.departement == "m05-financecore", REGISTRES.c.registre == "operations_comptables",
            REGISTRES.c.rang == 0,
        ).values(maillon=encoder(chain.lire()[0])))


def test_refuse_chaine_grand_livre_alteree(m5_public):
    tools, url, gl_helpers = m5_public
    response = gl_helpers._appeler(tools, "m5_proposer_ecriture_comptable", {
        "date_effet": "2026-10-03", "libelle": "Reçu fictif", "piece_type": "recu",
        "piece_reference": "REC-FICTIF", "horodatage": gl_helpers.H,
        "lignes": [{"compte": "5990", "debit": "10.00", "credit": None},
                   {"compte": "1010", "debit": None, "credit": "10.00"}],
    })
    assert response["ok"] and response["resultat"]["accepte"], response
    _alterer(url, "grand_livre", lambda maillon: {**maillon, "libelle": "altération fictive"})
    _refus_chaine(tools, "REJ-GL-CHAINE-INVALIDE", gl_helpers)


def test_refuse_chaine_factures_alteree(m5_public):
    tools, url, gl_helpers = m5_public
    response = gl_helpers._appeler(tools, "m5_creer_facture_brouillon", {
        "facture_id": "FACTURE-FICTIVE", "chantier_id": "CHANTIER-FICTIF", "devis_id": "DEVIS-FICTIF",
        "client_id": "CLIENT-FICTIF",
        "lignes": [{"description": "travail fictif", "quantite": "1", "unite": "forfait",
                    "prix_unitaire": "100.00", "reference_ligne_devis": "L1"}],
        "horodatage": gl_helpers.H,
    })
    assert response["ok"] and response["resultat"]["accepte"], response
    _alterer(url, "factures", lambda maillon: {**maillon, "client_id": "CLIENT-ALTERE-FICTIF"})
    _refus_chaine(tools, "REJ-CFO-CHAINE-INVALIDE", gl_helpers)


def test_refuse_chaine_comptes_a_payer_alteree(m5_public):
    tools, url, gl_helpers = m5_public
    _facture_fournisseur(tools, gl_helpers)
    _alterer(url, "comptes_a_payer", lambda maillon: {**maillon, "montant_avant_taxes": "900.00"})
    _refus_chaine(tools, "REJ-CFO-CHAINE-INVALIDE", gl_helpers)


def test_refuse_empreinte_interne_ops_alteree_meme_si_chaine_generique_est_valide(m5_public):
    tools, url, gl_helpers = m5_public
    _facture_fournisseur(tools, gl_helpers)
    finance = gl_helpers.lire_manifeste(gl_helpers._RACINE_M5)
    generated = gl_helpers._appeler(tools, "m5_generer_brouillons_comptables", {"horodatage": gl_helpers.H})
    draft = generated["resultat"]["resultat"]["brouillons_crees"][0]
    gl_helpers._valider_par_la_file(finance, draft["ecriture_id"])
    invoice = gl_helpers.m5_outils._factures_fournisseurs_vivantes()[0]
    note = gl_helpers._appeler(tools, "m5_proposer_note_credit", {
        "genre": "fournisseur", "facture_id": invoice["facture_fournisseur_id"],
        "reference": "NC-FICTIF", "montant_avant_taxes": "50.00", "date_effet": "2026-10-02",
        "motif": "motif fictif", "horodatage": gl_helpers.H,
    })
    assert note["ok"] and note["resultat"]["accepte"], note
    gl_helpers._valider_par_la_file(finance, note["resultat"]["resultat"]["ecriture_id"])

    with stockage.transaction(url) as cnx:
        texte = cnx.execute(select(REGISTRES.c.maillon).where(
            REGISTRES.c.departement == "m05-financecore", REGISTRES.c.registre == "operations_comptables",
            REGISTRES.c.rang == 0,
        )).scalar_one()
        altered = decoder(texte)
        altered["motif"] = "motif fictif altéré"
        body = {key: value for key, value in altered.items() if key not in ("ligne_id", "precedent_ligne_id")}
        rechained = gl_helpers.m5_outils.registre_module.Registre()
        rechained.ajouter(body)  # chaîne SQL valide, empreinte de contenu Ops volontairement obsolète
        cnx.execute(update(REGISTRES).where(
            REGISTRES.c.departement == "m05-financecore", REGISTRES.c.registre == "operations_comptables",
            REGISTRES.c.rang == 0,
        ).values(maillon=encoder(rechained.lire()[0])))
    with stockage.transaction(url):
        assert gl_helpers.m5_outils._registre_operations().valider_chaine()[0] is True
    _refus_chaine(tools, "REJ-OPS-CHAINE-INVALIDE", gl_helpers)


def test_refuse_date_ops_reemprentee_illisible_au_lieu_de_l_ignorer(m5_public):
    tools, url, gl_helpers = m5_public
    _note_credit_fournisseur(tools, gl_helpers)
    _rehacher_operation(url, lambda maillon: {**maillon, "date_effet": "DATE-ILLISIBLE-FICTIVE"}, gl_helpers)
    _refus_chaine(tools, "REJ-OPS-CHAINE-INVALIDE", gl_helpers)


@pytest.mark.parametrize(
    "taxes",
    [None, {"tps_cti": "MONTANT-INVALIDE-FICTIF"}],
)
def test_refuse_taxes_ops_reemprentees_malformees_sans_exception_brute(m5_public, taxes):
    tools, url, gl_helpers = m5_public
    _note_credit_fournisseur(tools, gl_helpers)
    _rehacher_operation(url, lambda maillon: {**maillon, "taxes": taxes}, gl_helpers)
    _refus_chaine(tools, "REJ-OPS-CHAINE-INVALIDE", gl_helpers)


def test_rapprochement_refuse_sans_stockage_durable(m5_public):
    tools, _url, gl_helpers = m5_public
    gl_helpers.m5_outils.reinitialiser_stockage_mouvements()
    try:
        response = gl_helpers._appeler(tools, "m5_rapprocher_grand_livre", gl_helpers.OCTOBRE)
        assert response["ok"] is True
        assert response["resultat"]["accepte"] is False
        assert response["resultat"]["verdict"]["code"] == "REJ-GL-STOCKAGE-NON-DURABLE"
    finally:
        gl_helpers.m5_outils.utiliser_stockage_durable()


def test_plan_invalide_precede_lecture_et_chaine_des_registres(m5_public, tmp_path, monkeypatch):
    tools, url, gl_helpers = m5_public
    _facture_fournisseur(tools, gl_helpers)
    _alterer(url, "comptes_a_payer", lambda maillon: {**maillon, "montant_avant_taxes": "900.00"})
    gl_helpers.declare._fixture_function(tmp_path, monkeypatch)({
        "grand_livre": {"comptes_desactives": ["0000"]},
    })
    monkeypatch.setattr(stockage, "lire_instantane_maillons", lambda *_args, **_kwargs: pytest.fail(
        "aucun snapshot ne doit être lu si le plan échoue, selon l'ordre historique"
    ))
    response = gl_helpers._appeler(tools, "m5_rapprocher_grand_livre", gl_helpers.OCTOBRE)
    assert response["ok"] is True and response["resultat"]["accepte"] is False
    assert response["resultat"]["verdict"]["code"] == "REJ-GL-PLAN-INVALIDE"
