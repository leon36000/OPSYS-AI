"""Lecture privée M7 : données fictives, bornes avant décodage et temporalité explicite."""

import hashlib
import importlib.util
import json
import sys
import threading
from datetime import date, datetime
from pathlib import Path

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
    _brut_rang(0, texte)


def _brut_rang(rang, texte):
    with stockage.transaction() as cnx:
        cnx.execute(REGISTRES.insert().values(
            departement=performance.REGISTRE[0], registre=performance.REGISTRE[1], rang=rang, maillon=texte,
        ))


@pytest.mark.parametrize("dialecte", [sqlite.dialect(), postgresql.dialect()])
def test_precontrole_capacite_sql_est_borne_et_ne_projette_pas_les_charges(base, monkeypatch, dialecte):
    monkeypatch.setattr(performance, "MAX_LIGNES", 2)
    requete = performance._requete_capacite_bornee(dialecte.name)
    sql = str(requete.compile(dialect=dialecte, compile_kwargs={"literal_binds": True}))
    projection = sql.split(" FROM ", 1)[0]
    assert "LIMIT 3" in sql
    assert "COUNT(" not in sql.upper() and "SUM(" not in sql.upper() and "MAX(" not in sql.upper()
    assert " AS rang" in projection and " AS octets" in projection
    assert list(requete.selected_columns.keys()) == ["rang", "octets"]


def test_saturation_lignes_refuse_avant_decode_et_lit_seulement_la_borne_plus_un(base, monkeypatch):
    monkeypatch.setattr(performance, "MAX_LIGNES", 2)
    for rang in range(3):
        _brut_rang(rang, "pas-du-json" * 20)
    monkeypatch.setattr(
        performance, "_decoder_fait",
        lambda _texte: (_ for _ in ()).throw(AssertionError("charge décodée avant contrôle de capacité")),
    )
    with pytest.raises(ValueError, match="PERFORMANCE_BORNE_LIGNES"):
        _lecture()


def test_saturation_octets_refuse_avant_decode(base, monkeypatch):
    monkeypatch.setattr(performance, "MAX_LIGNES", 3)
    monkeypatch.setattr(performance, "MAX_OCTETS_TOTAL", 30)
    _brut_rang(0, "x" * 20)
    _brut_rang(1, "y" * 20)
    monkeypatch.setattr(
        performance, "_decoder_fait",
        lambda _texte: (_ for _ in ()).throw(AssertionError("charge décodée avant contrôle de capacité")),
    )
    with pytest.raises(ValueError, match="PERFORMANCE_BORNE_OCTETS"):
        _lecture()


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


@pytest.mark.parametrize(
    ("type_evenement", "charge"),
    [
        ("m2.client_associe", {"lead_id": "lead-fictif"}),
        ("m3.devis_accepte", {"devis_id": "devis-fictif"}),
        ("m5.rentabilite_chantier", {
            "evenement_id": "evt-fictif", "devis_id": "devis-fictif", "wct_id": "wct-fictif", "sequence": 1,
        }),
    ],
)
def test_enregistrer_refuse_les_faits_que_le_lecteur_refuserait_avant_ecriture(base, type_evenement, charge):
    before = list(stockage.maillons(*performance.REGISTRE))
    with pytest.raises(ValueError, match="PERFORMANCE_FAIT_INVALIDE"):
        performance.enregistrer_fait(type_evenement, charge)
    assert list(stockage.maillons(*performance.REGISTRE)) == before == []


def test_rejeu_du_handler_m7_malforme_est_refuse_sans_ecriture(base):
    from m7_marketing import outils

    recevoir = outils.consommateurs()["m3.devis_accepte"]
    with pytest.raises(ValueError, match="PERFORMANCE_FAIT_INVALIDE"):
        recevoir({"devis_id": "devis-rejeu-fictif"})
    assert list(stockage.maillons(*performance.REGISTRE)) == []


def test_cle_metier_absente_garde_son_code_historique(base):
    with pytest.raises(ValueError, match="CLE_METIER_ABSENTE:m3.devis_accepte"):
        performance.enregistrer_fait("m3.devis_accepte", {})
    assert list(stockage.maillons(*performance.REGISTRE)) == []


@pytest.mark.parametrize(
    ("type_evenement", "charge"),
    [
        ("m2.client_associe", {
            "lead_id": "lead-valide-fictif", "client_id": "client-hache-fictif",
            "utm": {"utm_source": "source-fictive", "utm_campaign": "campagne-fictive"},
            "horodatage_association": "2026-09-10T12:00:00Z",
        }),
        ("m3.devis_accepte", {
            "devis_id": "devis-valide-fictif", "lead_id": "lead-valide-fictif",
            "chantier_id": "chantier-valide-fictif", "lignes": [{
                "reference_ligne": "devis-valide-fictif-L1", "description": "travail fictif",
                "quantite": "1", "unite": "forfait", "prix_unitaire": "100.00", "prix_ligne": "100.00",
                "reference_besoin_materiau": None,
            }],
            "cout_total": "80.00", "prix_total": "100.00", "taux_marge": "0.25",
            "horodatage_acceptation": "2026-09-11T12:00:00Z",
        }),
        ("m5.rentabilite_chantier", {
            "evenement_id": "evt-valide-fictif", "devis_id": "devis-valide-fictif",
            "chantier_id": "chantier-valide-fictif", "wct_id": "wct-valide-fictif", "sequence": 1,
            "version_entrees": "a" * 64, "horodatage_completion": "2026-09-12T12:00:00Z",
            "verdict": "CALCULEE", "devise": "CAD", "prix_definitif": True, "cout_reel_complet": True,
            "cout_reel_cad": "800.00", "cout_connu_cad": "800.00", "marge_reelle_cad": "200.00", "manque": [],
            "marge_prevue_cad": "250.00", "ecart_marge_cad": "-50.00",
        }),
    ],
)
def test_faits_valides_des_trois_producteurs_restent_idempotents(base, type_evenement, charge):
    from opsys.evenements.schemas import erreurs_charge

    assert erreurs_charge(type_evenement, charge) == []
    premier = performance.enregistrer_fait(type_evenement, charge)
    second = performance.enregistrer_fait(type_evenement, charge)
    faits = stockage.maillons(*performance.REGISTRE)
    assert premier == {"accepte": True, "deja_present": False}
    assert second == {"accepte": True, "deja_present": True}
    assert len(faits) == 1
    assert performance._decoder_fait(json.dumps(faits[0], ensure_ascii=False)) == faits[0]


def test_conflit_m5_valide_garde_son_code_historique(base):
    charge = {
        "evenement_id": "evt-premier-fictif", "devis_id": "devis-fictif", "chantier_id": "chantier-fictif",
        "wct_id": "wct-fictif", "sequence": 1, "version_entrees": "b" * 64,
        "horodatage_completion": "2026-09-12T12:00:00Z", "verdict": "CALCULEE", "devise": "CAD",
        "cout_reel_complet": True, "cout_reel_cad": "800.00", "cout_connu_cad": "800.00",
        "marge_reelle_cad": "200.00", "manque": [],
    }
    performance.enregistrer_fait("m5.rentabilite_chantier", charge)
    conflit = {**charge, "evenement_id": "evt-second-fictif", "marge_reelle_cad": "201.00"}
    with pytest.raises(ValueError, match="CONFLIT_RENTABILITE_M5"):
        performance.enregistrer_fait("m5.rentabilite_chantier", conflit)
    assert len(list(stockage.maillons(*performance.REGISTRE))) == 1


def _charge_m5_fictive(*, manque=None, sequence=1):
    return {
        "evenement_id": f"evt-borne-{sequence}-fictif", "devis_id": "devis-borne-fictif",
        "chantier_id": None, "wct_id": "wct-borne-fictif", "sequence": sequence,
        "version_entrees": "c" * 64, "horodatage_completion": "2026-09-12T12:00:00Z",
        "verdict": "PARTIELLE", "devise": "CAD", "cout_reel_complet": False,
        "cout_reel_cad": None, "cout_connu_cad": "0.00", "marge_reelle_cad": None,
        "marge_prevue_cad": None, "ecart_marge_cad": None,
        "manque": [] if manque is None else manque,
    }


def test_fait_m5_32_codes_valide_passe_ecriture_et_lecture_sans_troncature(base):
    from opsys.evenements.schemas import erreurs_charge
    from opsys.stockage import codec

    charge = _charge_m5_fictive(manque=[f"REJ-{i:02d}" + "A" * 2042 for i in range(32)])
    assert erreurs_charge("m5.rentabilite_chantier", charge) == []
    fait = performance._normaliser("m5.rentabilite_chantier", charge)
    taille_octets = len(codec.encoder(fait).encode("utf-8"))
    assert taille_octets > 64 * 1024
    assert taille_octets <= performance.MAX_OCTETS_TOTAL

    assert performance.enregistrer_fait("m5.rentabilite_chantier", charge) == {
        "accepte": True, "deja_present": False,
    }
    obtenu = _lecture()
    assert obtenu["observation_source"]["lignes_lues"] == 1
    assert list(stockage.maillons(*performance.REGISTRE))[0]["charge"]["manque"] == charge["manque"]


def test_fait_m5_33_codes_depasse_le_contrat_et_ne_peut_pas_empoisonner_lecture(base):
    from opsys.evenements.schemas import erreurs_charge

    charge = _charge_m5_fictive(manque=[f"REJ-{i:02d}" for i in range(33)])
    assert erreurs_charge("m5.rentabilite_chantier", charge)
    charge["manque"][0] = "historique-sans-rej"
    fait_historique = performance._normaliser("m5.rentabilite_chantier", charge)
    _brut(json.dumps(fait_historique, ensure_ascii=False, separators=(",", ":")))
    # M7 avait historiquement accepté jusqu'à 128 chaînes non vides sans exiger le motif REJ.
    assert _lecture()["observation_source"]["lignes_lues"] == 1
    assert list(stockage.maillons(*performance.REGISTRE))[0]["charge"]["manque"] == charge["manque"]


def test_code_m5_valide_superieur_a_2048_octets_passe_ecriture_et_lecture(base):
    from opsys.evenements.schemas import erreurs_charge
    from opsys.stockage import codec

    code = "REJ-" + "A" * 2045
    charge = _charge_m5_fictive(manque=[code])
    assert len(code.encode("utf-8")) > 2048
    assert erreurs_charge("m5.rentabilite_chantier", charge) == []
    fait = performance._normaliser("m5.rentabilite_chantier", charge)
    taille = len(codec.encoder(fait).encode("utf-8"))
    assert taille <= performance.MAX_OCTETS_TOTAL

    assert performance.enregistrer_fait("m5.rentabilite_chantier", charge) == {
        "accepte": True, "deja_present": False,
    }
    resultat = _lecture()
    assert resultat["observation_source"]["lignes_lues"] == 1
    assert list(stockage.maillons(*performance.REGISTRE))[0]["charge"]["manque"] == [code]


def test_encodage_utf8_et_echappements_json_sont_dans_la_borne_reelle(base, monkeypatch):
    from opsys.stockage import codec

    charge = _charge_m5_fictive()
    charge["evenement_id"] = '"\\é' * 512
    fait = performance._normaliser("m5.rentabilite_chantier", charge)
    taille = len(codec.encoder(fait).encode("utf-8"))
    assert taille > len(charge["evenement_id"].encode("utf-8"))
    assert taille <= performance.MAX_OCTETS_TOTAL

    monkeypatch.setattr(performance, "MAX_OCTETS_TOTAL", taille - 1)
    with pytest.raises(ValueError, match="PERFORMANCE_BORNE_OCTETS"):
        performance.enregistrer_fait("m5.rentabilite_chantier", charge)
    assert list(stockage.maillons(*performance.REGISTRE)) == []

    monkeypatch.setattr(performance, "MAX_OCTETS_TOTAL", taille)
    assert performance.enregistrer_fait("m5.rentabilite_chantier", charge) == {
        "accepte": True, "deja_present": False,
    }
    assert _lecture()["observation_source"]["lignes_lues"] == 1


def test_bornes_cumulees_et_idempotence_sont_verifiees_avant_append(base, monkeypatch):
    charge = _charge_m5_fictive()
    premier = performance.enregistrer_fait("m5.rentabilite_chantier", charge)
    assert premier == {"accepte": True, "deja_present": False}
    monkeypatch.setattr(performance, "MAX_LIGNES", 1)
    assert performance.enregistrer_fait("m5.rentabilite_chantier", charge) == {
        "accepte": True, "deja_present": True,
    }
    with pytest.raises(ValueError, match="PERFORMANCE_BORNE_LIGNES"):
        performance.enregistrer_fait("m2.client_associe", {
            "lead_id": "lead-borne-fictif", "client_id": "client-borne-fictif",
            "horodatage_association": "2026-09-10T12:00:00Z",
        })
    assert len(list(stockage.maillons(*performance.REGISTRE))) == 1


def test_borne_octets_cumules_refuse_une_nouvelle_ligne_sans_tronquer(base, monkeypatch):
    from opsys.stockage import codec

    existant = _fait()
    performance.enregistrer_fait(existant["type"], existant["charge"])
    autre = {"lead_id": "lead-autre-borne-fictif", "client_id": "client-autre-borne-fictif",
             "horodatage_association": "2026-09-10T12:00:00Z"}
    octets_existants = len(codec.encoder(list(stockage.maillons(*performance.REGISTRE))[0]).encode("utf-8"))
    fait_a_ajouter = performance._normaliser("m2.client_associe", autre)
    octets_nouveaux = len(codec.encoder(fait_a_ajouter).encode("utf-8"))
    monkeypatch.setattr(performance, "MAX_OCTETS_TOTAL", octets_existants + octets_nouveaux - 1)
    with pytest.raises(ValueError, match="PERFORMANCE_BORNE_OCTETS"):
        performance.enregistrer_fait("m2.client_associe", autre)
    assert len(list(stockage.maillons(*performance.REGISTRE))) == 1


def test_rejeu_m5_meme_sequence_ignore_borne_ligne_apres_identite(base, monkeypatch):
    from opsys.stockage import codec

    charge = _charge_m5_fictive()
    performance.enregistrer_fait("m5.rentabilite_chantier", charge)
    rejeu = {**charge, "evenement_id": "evt-republication-" + "x" * 1500}
    fait_rejeu = performance._normaliser("m5.rentabilite_chantier", rejeu)
    taille = len(codec.encoder(fait_rejeu).encode("utf-8"))
    monkeypatch.setattr(performance, "MAX_OCTETS_LIGNE", taille - 1)

    assert performance.enregistrer_fait("m5.rentabilite_chantier", rejeu) == {
        "accepte": True, "deja_present": True,
    }
    assert len(list(stockage.maillons(*performance.REGISTRE))) == 1

    nouveau = _charge_m5_fictive(sequence=2)
    nouveau["evenement_id"] = rejeu["evenement_id"]
    with pytest.raises(ValueError, match="PERFORMANCE_BORNE_OCTETS"):
        performance.enregistrer_fait("m5.rentabilite_chantier", nouveau)
    assert len(list(stockage.maillons(*performance.REGISTRE))) == 1


def test_append_concurrent_entre_prevol_et_ecriture_est_refuse_au_rang_attendu(base, monkeypatch):
    performance.enregistrer_fait(_fait()["type"], _fait()["charge"])
    original = type(stockage.maillons(*performance.REGISTRE)).append
    concurrent = {"type": "m3.devis_accepte", "charge": {
        "devis_id": "devis-concurrent-fictif", "lead_id": "lead-concurrent-fictif",
        "chantier_id": None, "horodatage_acceptation": "2026-09-11T12:00:00Z",
    }}
    injected = False

    def append_avec_commit_intercale(registre, fait, *, rang_attendu=None):
        nonlocal injected
        if not injected:
            injected = True
            original(registre, concurrent, rang_attendu=rang_attendu)
        return original(registre, fait, rang_attendu=rang_attendu)

    monkeypatch.setattr(type(stockage.maillons(*performance.REGISTRE)), "append", append_avec_commit_intercale)
    with pytest.raises(stockage.EcritureConcurrente):
        performance.enregistrer_fait("m3.devis_accepte", {
            "devis_id": "devis-candidat-fictif", "lead_id": "lead-candidat-fictif",
            "chantier_id": None, "horodatage_acceptation": "2026-09-11T12:00:00Z",
        })
    # L'append simulé fait partie de la même transaction et est annulé avec la course ; aucun demi-effet ne persiste.
    faits = list(stockage.maillons(*performance.REGISTRE))
    assert len(faits) == 1 and faits[0]["type"] == "m2.client_associe"


def test_consommateur_postgresql_serialise_scan_identite_et_append(base, monkeypatch):
    chemin_doubles = Path(stockage.__file__).resolve().parents[3] / "tests/fixtures/memoire/doubles.py"
    nom_module = "_m7_postgres_doubles_" + hashlib.sha256(str(chemin_doubles).encode()).hexdigest()[:16]
    module = sys.modules.get(nom_module)
    if module is None:
        spec = importlib.util.spec_from_file_location(nom_module, chemin_doubles)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[nom_module] = module
        spec.loader.exec_module(module)
    raison = module.raison_sans_docker()
    if raison is not None:
        pytest.skip(raison)

    with module.postgres_ephemere(stockage_en_memoire=True) as url:
        monkeypatch.setenv(stockage.ENV_URL, url)
        stockage.migrer(url)
        charge = _charge_m5_fictive()
        recevoir = outils.consommateurs()["m5.rentabilite_chantier"]
        premiere_verrouillee = threading.Event()
        seconde_en_attente = threading.Event()
        liberer_premiere = threading.Event()
        terminee_b = threading.Event()
        erreurs = []
        resultats = {}
        verrou_origine = performance.verrou_consultatif

        def verrou_observe(cnx, nom, *, partage=False):
            nom_thread = threading.current_thread().name
            if nom_thread == "m7-fait-a":
                verrou_origine(cnx, nom, partage=partage)
                premiere_verrouillee.set()
                if not liberer_premiere.wait(30):
                    raise TimeoutError("le test n'a pas libéré le premier consommateur")
                return
            if nom_thread == "m7-fait-b":
                seconde_en_attente.set()
            verrou_origine(cnx, nom, partage=partage)

        def livrer(cle):
            try:
                with stockage.transaction(url):
                    resultats[cle] = recevoir(charge)
            except BaseException as exc:  # transmettre toute erreur de thread au test principal
                erreurs.append(exc)
            finally:
                if cle == "b":
                    terminee_b.set()

        monkeypatch.setattr(performance, "verrou_consultatif", verrou_observe)
        a = threading.Thread(target=livrer, args=("a",), name="m7-fait-a", daemon=True)
        b = threading.Thread(target=livrer, args=("b",), name="m7-fait-b", daemon=True)
        a.start()
        try:
            assert premiere_verrouillee.wait(30), "le premier consommateur n'a pas pris le verrou"
            b.start()
            assert seconde_en_attente.wait(30), "le second consommateur n'a pas tenté le verrou"
            assert not terminee_b.is_set(), "le second a scanné/écrit avant le déverrouillage"
            with stockage.transaction(url):
                assert list(stockage.maillons(*performance.REGISTRE)) == []
        finally:
            liberer_premiere.set()
            a.join(30)
            if b.ident is not None:
                b.join(30)
            stockage.liberer(url)
        assert not a.is_alive() and not b.is_alive(), "threads bloqués"
        assert not erreurs, erreurs
        assert resultats == {
            "a": {"accepte": True, "deja_present": False},
            "b": {"accepte": True, "deja_present": True},
        }
        faits = list(stockage.maillons(*performance.REGISTRE))
        assert len(faits) == 1 and faits[0]["type"] == "m5.rentabilite_chantier"
