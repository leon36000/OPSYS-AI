"""Couverture des identités de publication M4/reçus M3 : SQLite réel, données fictives.

La présence d'une identité ne vérifie pas sa charge ou la qualité d'une mesure.
Les corruptions sont injectées directement pour exercer les refus du lecteur.
"""

from __future__ import annotations

import json
from contextlib import contextmanager

import pytest
from m3_estimation import outils
from sqlalchemy import event, select

from opsys import contexte, identite, stockage
from opsys.outils import Autonomie, executer_atomique
from opsys.stockage.schema import EVENEMENTS_SORTANTS

FICTIF = True
DEP = "m03-estimation"


@pytest.fixture
def base(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'couverture-fictive.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin-couverture", "Admin fictif", "mot-de-passe-fixture-long", ["admin"])
    yield
    stockage.liberer()


def _publier(*ids, producteur="m04-field-ops", charge="PAYLOAD-FICTIF-NE-PAS-LIRE"):
    with stockage.transaction() as cnx:
        cnx.execute(EVENEMENTS_SORTANTS.insert(), [
            {"evenement_id": i, "type_evenement": "m4.travaux_termines", "producteur": producteur,
             "charge": charge, "cree_le": "2026-10-01T12:00:00Z"} for i in ids
        ])


def _recevoir(*ids):
    with stockage.transaction():
        journal = stockage.maillons(DEP, "estime_vs_reel")
        for ident in ids:
            journal.append({
                "type_entree": "wct_recu", "wct_id": ident, "devis_id": "DEVIS-FICTIF",
                "lead_id": "LEAD-FICTIF", "intervention_id": "INTERVENTION-FICTIVE",
                "horodatage_completion": "2026-10-01T12:00:00Z", "main_doeuvre": {},
                "materiaux": None, "horodatage": "2026-10-01T12:00:00Z",
            })


@contextmanager
def _admin(role="admin", source="appareil"):
    with contexte.appele_par_appareil(contexte.IdentiteAppelante("admin-couverture", role, source=source)):
        yield


def _outil():
    return next(o for o in outils.outils() if o.nom == "m3_auditer_couverture_apprentissage")


def _rapport():
    with _admin():
        resultat = executer_atomique(_outil(), {})
    assert resultat["ok"]
    return resultat["resultat"]


def _snapshot():
    with stockage.transaction() as cnx:
        return (
            list(cnx.execute(select(EVENEMENTS_SORTANTS).order_by(EVENEMENTS_SORTANTS.c.evenement_id))),
            list(stockage.maillons(DEP, "estime_vs_reel")),
            list(stockage.maillons(DEP, "calibration_versions")),
        )


def test_contrat_ferme_t0_admin_sans_donnees_declarees_par_modele():
    outil = _outil()
    assert outil.autonomie == Autonomie.T0
    assert outil.roles_appareil == frozenset({"admin"})
    assert outil.parametres == {"type": "object", "properties": {}, "additionalProperties": False}


def test_sqlite_joint_les_identites_et_ne_mutera_pas_les_sources(base):
    _publier("WCT-FICTIF-C", "WCT-FICTIF-A", "WCT-FICTIF-B")
    _recevoir("WCT-FICTIF-A", "WCT-FICTIF-ORPHELIN")
    avant = _snapshot()
    rapport = _rapport()
    assert rapport["statut"] == "ecarts"
    assert rapport["compteurs"] == {"publications_m4": 3, "recus_m3": 2, "recoupes": 1,
                                     "manquants_m3": 2, "hors_univers_m4": 1}
    assert rapport["manquants_m3"] == {"exemples": ["WCT-FICTIF-B", "WCT-FICTIF-C"], "omis": 0}
    assert rapport["hors_univers_m4"] == {"exemples": ["WCT-FICTIF-ORPHELIN"], "omis": 0}
    assert rapport["completude_corpus_m4"] == "non_prouvee"
    assert rapport["candidate_active"] is False
    assert len(json.dumps(rapport)) < 6000
    assert _rapport() == rapport
    assert _snapshot() == avant


def test_identites_recues_ne_certifient_pas_les_charges_ou_la_calibration(base):
    _publier("WCT-FICTIF-A", charge="MALFORME-FICTIF")
    _recevoir("WCT-FICTIF-A")
    rapport = _rapport()
    assert rapport["statut"] == "identites_recues"
    assert rapport["univers"] == "identites_publications_m4_instance"
    assert rapport["contenu_wct_verifie"] is False
    assert rapport["completude_corpus_m4"] == "non_prouvee"
    assert rapport["candidate_active"] is False


def test_aucune_publication_est_un_univers_vide_pas_un_apprentissage_qualifie(base):
    rapport = _rapport()
    assert rapport["statut"] == "univers_vide"
    assert set(rapport["compteurs"].values()) == {0}
    assert rapport["candidate_active"] is False


def test_echantillon_borne_dix_et_counts_independants_de_m3(base):
    _publier(*(f"WCT-FICTIF-{i:03}" for i in range(30)))
    rapport = _rapport()
    assert rapport["compteurs"]["manquants_m3"] == 30
    assert rapport["manquants_m3"]["exemples"] == [f"WCT-FICTIF-{i:03}" for i in range(10)]
    assert rapport["manquants_m3"]["omis"] == 20


@pytest.mark.parametrize("role,source", [("seller", "appareil"), ("admin", "console"), ("admin", "agent")])
def test_voie_directe_refuse_role_ou_source_non_appareil(base, role, source):
    with stockage.transaction(), _admin(role, source):
        rapport = outils.auditer_couverture_apprentissage()
    assert rapport["statut"] == "refuse"
    assert rapport["raison"] == "identite_admin_authentifiee_requise"
    assert "compteurs" not in rapport


def test_appel_sans_identite_ou_transaction_ne_cree_pas_une_base():
    assert outils.auditer_couverture_apprentissage()["statut"] == "refuse"


def test_sqlite_retrait_role_admin_refuse_avant_lecture(base):
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, "admin-couverture", "admin")
    rapport = _rapport()
    assert rapport["statut"] == "refuse"
    assert rapport["raison"] == "identite_admin_authentifiee_requise"


@pytest.mark.parametrize("ident", ["X" * 129, "WCT-\nFICTIF", "WCT-é-fictif"])
def test_identites_sql_non_conformes_ne_sont_pas_tues_en_silence(base, ident):
    _publier(ident)
    rapport = _rapport()
    assert rapport["statut"] == "refuse"
    assert rapport["raison"] == "identite_publication_m4_invalide"
    assert "compteurs" not in rapport


def test_producteur_divergent_refuse_sans_reveler_sa_valeur(base):
    _publier("WCT-FICTIF-A", producteur="AUTRE-PRODUCTEUR-FICTIF")
    rapport = _rapport()
    assert rapport["raison"] == "producteur_publication_m4_invalide"
    assert "AUTRE-PRODUCTEUR-FICTIF" not in json.dumps(rapport)


def test_quota_sql_2001_refuse_sans_declarer_corpus_tronque_complet(base):
    _publier(*(f"WCT-FICTIF-{i:04}" for i in range(2001)))
    rapport = _rapport()
    assert rapport["statut"] == "refuse"
    assert rapport["raison"] == "limite_publications_m4_depassee"
    assert "compteurs" not in rapport


def test_recu_m3_duplique_refuse_au_lieu_de_dedoublonner(base):
    _recevoir("WCT-FICTIF-A", "WCT-FICTIF-A")
    rapport = _rapport()
    assert rapport["raison"] == "prefixe_reception_m3_invalide"


def test_recu_m3_id_non_borne_refuse(base):
    _recevoir("X" * 129)
    assert _rapport()["raison"] == "identite_reception_m3_invalide"


def test_projection_sql_ne_selectionne_jamais_la_charge(base):
    _publier("WCT-FICTIF-A", charge="DONNEES-PRIVEES-FICTIVES" * 10000)
    requetes = []
    with stockage.transaction() as cnx:
        def capturer(_cnx, _cursor, statement, _params, _context, _executemany):
            if "evenements_sortants" in statement and statement.lstrip().upper().startswith("SELECT"):
                requetes.append(statement)
        event.listen(cnx, "before_cursor_execute", capturer)
        try:
            with _admin():
                rapport = outils.auditer_couverture_apprentissage()
        finally:
            event.remove(cnx, "before_cursor_execute", capturer)
    assert rapport["statut"] == "ecarts"
    assert requetes and all(".charge" not in q for q in requetes)
    assert all("LIMIT" in q.upper() for q in requetes)
    assert "DONNEES-PRIVEES-FICTIVES" not in json.dumps(rapport)


def test_recu_m3_trop_volumineux_refuse_avant_decodage(base, monkeypatch):
    from opsys.evenements import inventaire_calibration
    _recevoir("WCT-FICTIF-A")
    with stockage.transaction():
        stockage.maillons(DEP, "estime_vs_reel").append({"type_entree": "variance_recue", "charge": "X" * 65537})
        monkeypatch.setattr(inventaire_calibration.stockage, "maillons", lambda *_args: pytest.fail("decode interdit"))
        with _admin():
            rapport = outils.auditer_couverture_apprentissage()
    assert rapport["raison"] == "limite_reception_m3_depassee"


def test_retrait_role_pendant_lecture_refuse_sortie(base, monkeypatch):
    from opsys.evenements import inventaire_calibration
    lire = inventaire_calibration.lire_publications_m4
    appels = 0
    def retirer():
        nonlocal appels
        resultat = lire()
        appels += 1
        if appels == 2:
            identite.retirer_role(stockage.connexion_courante(), "admin-couverture", "admin")
        return resultat
    monkeypatch.setattr(inventaire_calibration, "lire_publications_m4", retirer)
    rapport = _rapport()
    assert rapport["raison"] == "identite_admin_authentifiee_requise"
    assert "compteurs" not in rapport


def test_modification_bus_entre_relectures_refuse(base, monkeypatch):
    from opsys.evenements import inventaire_calibration
    _publier("WCT-FICTIF-A")
    lire = inventaire_calibration.lire_publications_m4
    appels = 0
    def lire_et_changer():
        nonlocal appels
        resultat = lire()
        appels += 1
        if appels == 1:
            _publier("WCT-FICTIF-B")  # Injection fictive dans la transaction de ce test.
        return resultat
    monkeypatch.setattr(inventaire_calibration, "lire_publications_m4", lire_et_changer)
    assert _rapport()["raison"] == "sources_modifiees_pendant_lecture"


def test_modification_reception_m3_entre_relectures_refuse(base, monkeypatch):
    from opsys.evenements import inventaire_calibration
    lire = inventaire_calibration.lire_receptions_m3
    appels = 0
    def lire_et_changer():
        nonlocal appels
        resultat = lire()
        appels += 1
        if appels == 1:
            _recevoir("WCT-FICTIF-A")
        return resultat
    monkeypatch.setattr(inventaire_calibration, "lire_receptions_m3", lire_et_changer)
    assert _rapport()["raison"] == "sources_modifiees_pendant_lecture"


def test_absence_table_bus_refuse_sans_creer_ou_migrer(base):
    with stockage.transaction() as cnx:
        EVENEMENTS_SORTANTS.drop(cnx)
    assert _rapport()["raison"] == "sources_lecture_indisponibles"


def test_borne_inclusive_2000_et_autres_types_hors_univers(base):
    _publier(*(f"WCT-FICTIF-{i:04}" for i in range(2000)))
    with stockage.transaction() as cnx:
        cnx.execute(EVENEMENTS_SORTANTS.insert(), {
            "evenement_id": "AUTRE-FICTIF", "type_evenement": "opsys.demo_complete",
            "producteur": "demo-fictif", "charge": "MALFORME-FICTIF", "cree_le": "2026-10-01T12:00:00Z",
        })
    rapport = _rapport()
    assert rapport["compteurs"]["publications_m4"] == 2000
    assert rapport["manquants_m3"]["omis"] == 1990


def test_backend_non_qualifie_refuse(monkeypatch):
    from types import SimpleNamespace

    from opsys.evenements import inventaire_calibration
    cnx = SimpleNamespace(in_transaction=lambda: True, dialect=SimpleNamespace(name="postgresql"))
    monkeypatch.setattr(inventaire_calibration.stockage, "connexion_courante", lambda: cnx)
    with pytest.raises(inventaire_calibration.InventaireRefuse, match="backend_source_non_qualifie"):
        inventaire_calibration.lire_publications_m4()
