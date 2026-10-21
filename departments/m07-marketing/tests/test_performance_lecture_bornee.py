"""Lecture privée M7 : données fictives, bornes avant décodage et temporalité explicite."""

import json
from datetime import date, datetime

import pytest
from m7_marketing import outils
from m7_marketing import performance_campagnes as performance
from sqlalchemy import select, update
from sqlalchemy.dialects import postgresql, sqlite

from opsys import contexte, identite, stockage
from opsys.stockage.schema import REGISTRES


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'fictif.db'}")
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home-fictif"))
    stockage.migrer()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin fictif", "mot-de-passe-fictif-123", ["admin"])
    yield
    stockage.liberer()


def _fait(campagne="fictif"):
    return {"type": "m2.client_associe", "charge": {
        "lead_id": "lead-fictif", "client_id": "client-fictif",
        "source": "source-fictive", "campagne": campagne,
        "horodatage_association": "2026-09-10T12:00:00Z",
    }}


def _lecture():
    with stockage.transaction(), contexte.appele_par_appareil(
        contexte.IdentiteAppelante("admin.fictif", "admin", "console")
    ):
        return outils.lire_performance_campagnes("2026-09-01", "2026-09-30")


def _brut(texte):
    with stockage.transaction() as cnx:
        cnx.execute(REGISTRES.insert().values(
            departement=performance.REGISTRE[0], registre=performance.REGISTRE[1], rang=0, maillon=texte,
        ))


def test_historique_valide_non_scelle_et_lecture_sans_ecriture(base):
    performance.enregistrer_fait(**dict(type_evenement=_fait()["type"], charge=_fait()["charge"]))
    with stockage.transaction() as cnx:
        avant = cnx.execute(select(REGISTRES)).all()
    resultat = _lecture()
    observation = resultat["observation_source"]
    assert observation["integrite"] == "historique_non_scelle"
    assert observation["definition_temps"] == "dates_metier_faits_disponibles_a_la_lecture"
    assert observation["lignes_lues"] == 1 and observation["rang_max"] == 0
    assert len(observation["empreinte_lecture_sha256"]) == 64
    assert datetime.fromisoformat(observation["lue_le"]).utcoffset() is not None
    assert observation["dernier_cree_le_sql"] is not None
    with stockage.transaction() as cnx:
        assert cnx.execute(select(REGISTRES)).all() == avant


def test_octets_utf8_trop_grands_refuses_avant_decoder(base, monkeypatch):
    _brut(json.dumps({"fictif": "é" * 40}, ensure_ascii=False))
    monkeypatch.setattr(performance, "MAX_OCTETS_LIGNE", 70, raising=False)
    with pytest.raises(ValueError, match="PERFORMANCE_BORNE_OCTETS"):
        _lecture()


def test_somme_octets_et_nombre_refuses_sans_tronquer(base, monkeypatch):
    performance.enregistrer_fait(_fait()["type"], _fait()["charge"])
    monkeypatch.setattr(performance, "MAX_OCTETS_TOTAL", 32, raising=False)
    with pytest.raises(ValueError, match="PERFORMANCE_BORNE_OCTETS"):
        _lecture()
    monkeypatch.setattr(performance, "MAX_OCTETS_TOTAL", 8192)
    monkeypatch.setattr(performance, "MAX_LIGNES", 0, raising=False)
    with pytest.raises(ValueError, match="PERFORMANCE_BORNE_LIGNES"):
        _lecture()


@pytest.mark.parametrize("charge", [
    {"__opsys__": "dict", "v": None}, {"__opsys__": "bytes", "v": None},
    {"__opsys__": "decimal", "v": "invalide"},
    {"type": "m2.client_associe", "charge": {"horodatage_association": "1999-01-01T00:00:00Z"}},
    {"type": "m2.client_associe", "charge": {"valeur": float("nan")}},
])
def test_codec_et_forme_invalides_refusent_meme_hors_periode(base, charge):
    _brut(json.dumps(charge))
    with pytest.raises(ValueError, match="PERFORMANCE_FAIT_INVALIDE"):
        _lecture()


def test_profondeur_bornee_avant_restauration(base):
    _brut('[' * 30 + '0' + ']' * 30)
    with pytest.raises(ValueError, match="PERFORMANCE_JSON_BORNE"):
        _lecture()


def test_rangs_discontinus_refusent_un_prefixe_faussement_complet(base):
    performance.enregistrer_fait(_fait()["type"], _fait()["charge"])
    with stockage.transaction() as cnx:
        cnx.execute(update(REGISTRES).values(rang=1))
    with pytest.raises(ValueError, match="PERFORMANCE_PREFIXE_INVALIDE"):
        _lecture()


def test_correction_tardive_garde_date_metier_et_marge_plus_recente(base):
    performance.enregistrer_fait(_fait()["type"], _fait()["charge"])
    performance.enregistrer_fait("m3.devis_accepte", {
        "devis_id": "devis-fictif", "lead_id": "lead-fictif", "chantier_id": "chantier-fictif",
        "horodatage_acceptation": "2026-09-11T12:00:00Z",
    })
    # Toutes les dates SQL de cette chronologie fictive doivent être contrôlées :
    # les deux premières lignes ne peuvent pas garder le now() réel du runner.
    with stockage.transaction() as cnx:
        cnx.execute(update(REGISTRES).where(
            REGISTRES.c.departement == performance.REGISTRE[0],
            REGISTRES.c.registre == performance.REGISTRE[1],
            REGISTRES.c.rang < 2,
        ).values(cree_le=datetime(2026, 10, 1, 12)))
    for sequence, marge, jour in [(1, "1250.00", 12), (2, "990.00", 20)]:
        performance.enregistrer_fait("m5.rentabilite_chantier", {
            "evenement_id": f"evt-fictif-{sequence}", "devis_id": "devis-fictif",
            "chantier_id": "chantier-fictif", "wct_id": "wct-fictif", "sequence": sequence,
            "version_entrees": str(sequence) * 64, "horodatage_completion": "2026-09-12T12:00:00Z",
            "verdict": "CALCULEE", "devise": "CAD", "cout_reel_complet": True,
            "cout_reel_cad": "800.00", "cout_connu_cad": "800.00", "marge_reelle_cad": marge, "manque": [],
        })
        with stockage.transaction() as cnx:
            cnx.execute(update(REGISTRES).where(REGISTRES.c.rang == sequence + 1).values(
                cree_le=datetime(2026, 10, jour, 12),
            ))
    resultat = _lecture()
    assert resultat["campagnes"][0]["marge_constatee_M5_cad"] == "990.00"
    assert resultat["campagnes"][0]["roi"] is None
    assert resultat["observation_source"]["dernier_cree_le_sql"].startswith("2026-10-20")


def test_retrait_role_apres_lecture_refuse_le_retour(base, monkeypatch):
    original = performance.construire_performance

    def retirer(*args, **kwargs):
        resultat = original(*args, **kwargs)
        identite.retirer_role(stockage.connexion_courante(), "admin.fictif", "admin")
        return resultat

    monkeypatch.setattr(performance, "construire_performance", retirer)
    with pytest.raises(ValueError, match="REJ-IDENTITE"):
        _lecture()


def test_periode_et_dialecte_refuses_explicitement(base):
    with stockage.transaction(), pytest.raises(ValueError, match="PERIODE_TROP_LONGUE"):
        performance.lire_performance(date(2024, 1, 1), date(2026, 1, 1))
    with pytest.raises(ValueError, match="PERFORMANCE_DIALECTE_NON_PRIS_EN_CHARGE"):
        performance._longueur_octets("inconnu")


def test_noeuds_bornes_avant_restauration(base):
    _brut(json.dumps([0] * 2049))
    with pytest.raises(ValueError, match="PERFORMANCE_JSON_BORNE"):
        _lecture()


def test_expressions_sql_mesurent_des_octets_utf8_pas_des_caracteres():
    sqlite_sql = str(performance._longueur_octets("sqlite").compile(dialect=sqlite.dialect()))
    pg_sql = str(performance._longueur_octets("postgresql").compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True},
    ))
    assert "length(CAST(" in sqlite_sql and "AS BLOB" in sqlite_sql
    assert "octet_length(convert_to(" in pg_sql and "'UTF8'" in pg_sql


def test_conflit_historique_hors_periode_refuse_aussi(base):
    premier = performance._normaliser(_fait()["type"], _fait()["charge"])
    premier["charge"]["horodatage_association"] = "1999-01-01T00:00:00Z"
    deuxieme = json.loads(json.dumps(premier))
    deuxieme["charge"]["campagne"] = "autre-fictif"
    with stockage.transaction() as cnx:
        for rang, fait in enumerate((premier, deuxieme)):
            cnx.execute(REGISTRES.insert().values(departement=performance.REGISTRE[0], registre=performance.REGISTRE[1],
                                                  rang=rang, maillon=json.dumps(fait)))
    with pytest.raises(ValueError, match="PERFORMANCE_FAITS_CONFLICTUELS"):
        _lecture()


def test_attribution_vide_et_chantier_absent_valides_restent_inconnus(base):
    fait = _fait(campagne="")
    performance.enregistrer_fait(fait["type"], fait["charge"])
    performance.enregistrer_fait("m3.devis_accepte", {
        "devis_id": "devis-fictif", "lead_id": "lead-fictif", "chantier_id": None,
        "horodatage_acceptation": "2026-09-11T12:00:00Z",
    })
    resultat = _lecture()
    assert resultat["campagnes"][0]["campagne"] is None
    assert resultat["campagnes"][0]["marge_constatee_M5_cad"] is None


def test_alteration_de_forme_valide_n_est_pas_authentifiee_par_empreinte(base):
    performance.enregistrer_fait(_fait()["type"], _fait()["charge"])
    premier = _lecture()["observation_source"]
    with stockage.transaction() as cnx:
        texte = cnx.execute(select(REGISTRES.c.maillon)).scalar_one()
        fait = json.loads(texte)
        fait["charge"]["campagne"] = "autre-campagne-fictive"
        cnx.execute(update(REGISTRES).values(maillon=json.dumps(fait)))
    second = _lecture()["observation_source"]
    assert premier["empreinte_lecture_sha256"] != second["empreinte_lecture_sha256"]
    assert premier["integrite"] == second["integrite"] == "historique_non_scelle"
