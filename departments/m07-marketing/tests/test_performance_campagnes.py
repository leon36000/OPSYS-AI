from datetime import date
from decimal import Decimal

import pytest
from m7_marketing import outils
from m7_marketing.performance_campagnes import construire_performance, enregistrer_fait

from opsys import contexte, identite, stockage


def _faits(*, attribution=True, marge="1250.00", sequence=1):
    lead = {
        "lead_id": "lead-opaque-1",
        "client_id": "client-opaque-1",
        "horodatage_association": "2026-09-10T12:00:00Z",
    }
    if attribution:
        lead.update(source="google", campagne="automne", utm={"utm_source": "google", "utm_campaign": "automne"})
    return [
        {"type": "m2.client_associe", "charge": lead},
        {
            "type": "m3.devis_accepte",
            "charge": {
                "devis_id": "devis-opaque-1", "lead_id": "lead-opaque-1",
                "chantier_id": "chantier-opaque-1", "horodatage_acceptation": "2026-09-11T12:00:00Z",
            },
        },
        {
            "type": "m5.rentabilite_chantier",
            "charge": {
                "evenement_id": "evt-opaque-1", "devis_id": "devis-opaque-1",
                "chantier_id": "chantier-opaque-1", "wct_id": "wct-opaque-1", "sequence": sequence,
                "version_entrees": f"{'a' if sequence == 1 else 'b'}" * 64,
                "horodatage_completion": "2026-09-12T12:00:00Z", "verdict": "CALCULEE",
                "devise": "CAD", "cout_reel_complet": True, "cout_reel_cad": "800.00",
                "cout_connu_cad": "800.00", "marge_reelle_cad": marge,
                "marge_prevue_cad": None, "ecart_marge_cad": None, "manque": [],
            },
        },
    ]


@pytest.fixture
def registre_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "opsys-home"))
    stockage.migrer(url)
    yield url
    stockage.liberer()


def test_jointure_canonique_n_expose_qu_un_compte_et_marge_m5_sans_roi():
    resultat = construire_performance(_faits(), date(2026, 9, 1), date(2026, 9, 30))

    campagne = resultat["campagnes"][0]
    assert campagne["leads_associes_observes"] == 1
    assert campagne["devis_acceptes"] == 1
    assert campagne["chantiers_marge_constatee"] == 1
    assert campagne["marge_constatee_M5_cad"] == "1250.00"
    assert isinstance(Decimal(campagne["marge_constatee_M5_cad"]), Decimal)
    assert campagne["statut_financier"] == "INCONNU"
    assert campagne["cout_ads_cad"] is None
    assert campagne["cout_par_lead_cad"] is None
    assert campagne["roi"] is None
    assert campagne["couverture"] == "PARTIELLE"
    assert resultat["source_refs"]


def test_absence_attribution_ne_devient_pas_campagne_ni_zero_roi():
    resultat = construire_performance(_faits(attribution=False), date(2026, 9, 1), date(2026, 9, 30))

    assert resultat["couverture"] == "PARTIELLE"
    campagne = resultat["campagnes"][0]
    assert campagne["campagne"] is None
    assert campagne["leads_associes_observes"] == 1
    assert campagne["couverture"] == "INCONNUE"
    assert "ATTRIBUTION_ABSENTE" in campagne["manque"]


def test_marge_m5_partielle_ne_compte_pas_comme_marge_constatee():
    faits = _faits(marge=None)
    faits[-1]["charge"].update(
        verdict="PARTIELLE", cout_reel_complet=False, cout_reel_cad=None, marge_reelle_cad=None,
        manque=["REJ-COUT-PIECE-MANQUANTE"],
    )
    resultat = construire_performance(faits, date(2026, 9, 1), date(2026, 9, 30))

    campagne = resultat["campagnes"][0]
    assert campagne["marge_constatee_M5_cad"] is None
    assert campagne["chantiers_marge_constatee"] == 0
    assert campagne["couverture"] == "PARTIELLE"


def test_sequence_m5_la_plus_recente_remplace_les_anciennes_sans_double_compter():
    faits = _faits()
    ancien = dict(faits[-1]["charge"])
    recent = dict(
        ancien, evenement_id="evt-opaque-2", wct_id="wct-opaque-2", sequence=2,
        version_entrees="b" * 64, marge_reelle_cad="990.00",
    )
    faits.append({"type": "m5.rentabilite_chantier", "charge": recent})
    resultat = construire_performance(faits, date(2026, 9, 1), date(2026, 9, 30))

    campagne = resultat["campagnes"][0]
    assert campagne["chantiers_marge_constatee"] == 1
    assert campagne["marge_constatee_M5_cad"] == "990.00"


def test_attribution_conflictuelle_reste_exclue_meme_si_une_valeur_reapparait():
    faits = _faits()
    premiere = dict(faits[0]["charge"])
    conflictuelle = dict(premiere, utm={"utm_source": "meta", "utm_campaign": "automne"})
    faits.extend([
        {"type": "m2.client_associe", "charge": conflictuelle},
        {"type": "m2.client_associe", "charge": premiere},
    ])

    resultat = construire_performance(faits, date(2026, 9, 1), date(2026, 9, 30))

    assert resultat["campagnes"] == []
    assert resultat["couverture"] == "INCONNUE"
    assert resultat["exclusions"]["attribution_conflictuelle"] == 1
    assert "ATTRIBUTION_CONFLICTUELLE" in resultat["manque"]


def test_meme_sequence_avec_payload_different_est_refusee():
    faits = _faits()
    conflit = dict(faits[-1]["charge"], evenement_id="evt-opaque-different", marge_reelle_cad="999.00")
    faits.append({"type": "m5.rentabilite_chantier", "charge": conflit})

    with pytest.raises(ValueError, match="CONFLIT_RENTABILITE_M5"):
        construire_performance(faits, date(2026, 9, 1), date(2026, 9, 30))


def test_cohorte_associe_m2_et_exclut_lead_hors_periode_et_evenements_futurs():
    faits = _faits()
    faits[0]["charge"]["horodatage_association"] = "2026-08-31T23:59:59Z"
    faits[1]["charge"]["horodatage_acceptation"] = "2026-10-01T00:00:00Z"
    faits[2]["charge"]["horodatage_completion"] = "2026-10-01T00:00:00Z"
    resultat = construire_performance(faits, date(2026, 9, 1), date(2026, 9, 30))

    assert resultat["couverture"] == "INCONNUE"
    assert resultat["campagnes"] == []
    assert resultat["exclusions"]["associations_hors_cohorte"] == 1


def test_devis_sans_observation_m5_est_explicitement_sans_marge():
    faits = _faits()[:2]
    resultat = construire_performance(faits, date(2026, 9, 1), date(2026, 9, 30))

    campagne = resultat["campagnes"][0]
    assert campagne["devis_acceptes"] == 1
    assert campagne["chantiers_marge_constatee"] == 0
    assert campagne["marge_constatee_M5_cad"] is None
    assert "MARGE_M5_NON_OBSERVEE" in campagne["manque"]


def test_lead_hors_cohorte_est_nomme_comme_tel_et_non_comme_inconnu():
    faits = _faits()
    faits[0]["charge"]["horodatage_association"] = "2026-08-31T23:59:59Z"
    resultat = construire_performance(faits, date(2026, 9, 1), date(2026, 9, 30))

    assert resultat["exclusions"]["lead_hors_cohorte"] == 1
    assert resultat["exclusions"]["lead_inconnu"] == 0


def test_chantier_m3_m5_contradictoire_ne_contribue_pas_a_la_marge():
    faits = _faits()
    faits[-1]["charge"]["chantier_id"] = "chantier-autre"
    resultat = construire_performance(faits, date(2026, 9, 1), date(2026, 9, 30))

    campagne = resultat["campagnes"][0]
    assert campagne["chantiers_marge_constatee"] == 0
    assert campagne["marge_constatee_M5_cad"] is None
    assert "CHANTIER_M3_M5_CONTRADICTOIRE" in campagne["manque"]


def test_livraison_durable_m5_puis_m3_puis_m2_et_rejeu_est_idempotent(registre_durable):
    faits = _faits()
    evenement_m5 = faits[2]["charge"]
    evenement_m3 = faits[1]["charge"]
    evenement_m2 = faits[0]["charge"]

    assert enregistrer_fait("m5.rentabilite_chantier", evenement_m5) == {"accepte": True, "deja_present": False}
    assert enregistrer_fait("m3.devis_accepte", evenement_m3) == {"accepte": True, "deja_present": False}
    assert enregistrer_fait("m2.client_associe", evenement_m2) == {"accepte": True, "deja_present": False}
    assert enregistrer_fait("m5.rentabilite_chantier", evenement_m5) == {"accepte": True, "deja_present": True}
    stockage.liberer()
    stockage.migrer(registre_durable)
    with stockage.transaction():
        stockes = list(stockage.maillons("m07-marketing", "performance_campagnes"))

    assert [f["type"] for f in stockes] == [
        "m5.rentabilite_chantier", "m3.devis_accepte", "m2.client_associe"
    ]
    resultat = construire_performance(stockes, date(2026, 9, 1), date(2026, 9, 30))
    assert resultat["campagnes"][0]["marge_constatee_M5_cad"] == "1250.00"


@pytest.mark.parametrize("horodatage", ["2026-09-01T00:15:00+02:00", "2026-08-31T23:15:00-02:00"])
def test_horodatages_sont_comparés_apres_conversion_utc(horodatage):
    faits = _faits()
    faits[0]["charge"]["horodatage_association"] = horodatage
    resultat = construire_performance(faits, date(2026, 8, 31), date(2026, 9, 30))

    assert resultat["campagnes"]


def test_horodatage_naif_est_rejete():
    faits = _faits()
    faits[0]["charge"]["horodatage_association"] = "2026-09-01T00:00:00"

    with pytest.raises(ValueError, match="HORODATAGE_INVALIDE"):
        construire_performance(faits, date(2026, 9, 1), date(2026, 9, 30))


def test_admin_console_actif_est_accepte_puis_revoque_refuse_avant_lecture(registre_durable, monkeypatch):
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "gestionnaire", "Gestionnaire test", "mot-de-passe-de-test-1234", ["admin"])
    appelante = contexte.IdentiteAppelante("gestionnaire", "admin", source="console")
    with contexte.appele_par_appareil(appelante), stockage.transaction():
        resultat = outils.lire_performance_campagnes("2026-09-01", "2026-09-30")
    assert resultat["couverture"] == "INCONNUE"

    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, "gestionnaire", "admin")

    def ne_pas_lire(*args):
        raise AssertionError("le rôle révoqué doit être refusé avant le registre de performance")

    monkeypatch.setattr(stockage, "maillons", ne_pas_lire)
    with contexte.appele_par_appareil(appelante), stockage.transaction(), pytest.raises(
        ValueError, match="REJ-IDENTITE-APPAREIL-INVALIDE"
    ):
        outils.lire_performance_campagnes("2026-09-01", "2026-09-30")
