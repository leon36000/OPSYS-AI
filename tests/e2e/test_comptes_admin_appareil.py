"""T4.22 : lectures M5 HTTP/SQLite fictives ; porte Core simulée Python, pas téléphone natif."""
from __future__ import annotations

import pytest
from m5_financecore import facturation, taux_fiscaux
from m5_financecore import outils as m5
from tests.e2e.test_briefing_admin_appareil import empreinte_tables
from tests.e2e.test_comptes_a_payer_appareil import _livraison, _livrer_le_bus, _preparer_po

from opsys import identite, stockage

FICTIF = True
JOUR = "2026-09-15"
SQLITE = pytest.mark.parametrize("moteur", ["sqlite"], indirect=True)
LECTURES = (
    ("m5_lire_comptes_a_recevoir", {"aujourd_hui": JOUR}),
    ("m5_lister_comptes_a_payer", {"depart": 0}),
    ("m5_lister_comptes_a_payer", {"sans_po": True, "depart": 0}),
    ("m5_lister_attentes_facturation", {}),
)


@SQLITE
def test_admin_comptes_riches_lectures_sans_mutation(moteur, equipe, monkeypatch):
    admin = equipe["admin"]
    _preparer_po(moteur)
    recu = _livraison(moteur, admin, 60.0, 0.0, cle="reception-comptes-fictive")
    assert recu.ok and recu.metier["accepte"] is True
    _livrer_le_bus(moteur)
    taux, erreurs = taux_fiscaux.charger_taux_fiscaux(m5._CHEMIN_TAUX_FISCAUX)
    assert erreurs == []
    # État financier fictif de fixture, sans qualification d'un envoi officiel ou N4.
    with stockage.transaction():
        registre = m5._registre_factures(None)
        _, verdict = facturation.creer_facture_brouillon(
            "FACT-COMPTES-FICTIVE", "CH-FICTIF", "D-FICTIF", "CLIENT-FICTIF",
            [{"description": "travaux fictifs", "quantite": "1", "unite": "forfait",
              "prix_unitaire": "100.00", "reference_ligne_devis": "L-FICTIVE"}],
            "2026-09-14T10:00:00-04:00", taux, registre,
        )
        assert verdict is None
        assert facturation.envoyer_facture(
            "FACT-COMPTES-FICTIVE", "2026-09-14T11:00:00-04:00", registre,
        )[1] is None
    monkeypatch.setattr(m5, "_categories_depense_sans_po", lambda: ["carburant"])
    saisie = admin.appeler("m5_saisir_facture_sans_po", {
        "fournisseur_id": "Petro (fictif)", "categorie": "carburant", "numero_facture": "C-FICTIVE",
        "date_facture": "2026-09-14", "montant_avant_taxes": "100.00", "total_facture": "114.98",
        "horodatage": moteur.horloge.maintenant.isoformat(),
    }, cle="facture-comptes-fictive", horodatage_appareil=moteur.horloge.maintenant.isoformat())
    assert saisie.ok and saisie.metier["accepte"] is True, saisie.corps
    valeurs = []
    for nom, args in LECTURES:
        avant = empreinte_tables()
        reponse = admin.appeler(nom, args)
        assert reponse.ok and reponse.enveloppe["ok"] is True, reponse.corps
        assert not reponse.mesure.tronque
        assert empreinte_tables() == avant
        valeurs.append(reponse.resultat)
    creances, po, sans_po, attentes = valeurs
    assert creances["total_a_recevoir"] == "114.98" and creances["total_complet"] is True
    assert creances["age"]["tranches"]["0-30"][0]["age_jours"] == 1
    assert po["comptes"][0]["a_payer_apres_taxes"] == "344.93"
    assert po["totaux"]["a_payer_apres_taxes"] == "459.91", "le total inclut la facture sans PO"
    assert sans_po["factures"][0]["apres_taxes"] == "114.98"
    assert sans_po["type"] == "COMPTES_A_PAYER_SANS_PO"
    assert set(attentes) == {"attentes_devis", "attentes_wct_sans_devis_id"}


@SQLITE
@pytest.mark.parametrize("role", ["employee", "seller"])
def test_comptes_autres_roles_refuses(moteur, monkeypatch, role):
    personne = f"comptes-{role}-fictif"
    moteur.creer_personne(personne, f"Profil {role} fictif", [role], monkeypatch)
    porte = moteur.appairer(personne, role)
    avant = empreinte_tables()
    for nom, args in LECTURES:
        assert porte.appeler(nom, args).statut == 403
        assert empreinte_tables() == avant


@SQLITE
def test_comptes_identite_revoquee_ne_lit_plus(moteur, equipe):
    admin = equipe["admin"]
    assert admin.appeler(LECTURES[0][0], LECTURES[0][1]).ok
    with stockage.transaction() as cnx:
        identite.activer(cnx, "nathan", False)
    avant = empreinte_tables()
    for nom, args in LECTURES:
        reponse = admin.appeler(nom, args)
        assert reponse.ok
        assert reponse.enveloppe["resultat"]["accepte"] is False, reponse.corps
        assert reponse.enveloppe["resultat"]["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
        assert empreinte_tables() == avant
