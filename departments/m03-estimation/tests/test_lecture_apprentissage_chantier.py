"""Lecture jointe d'un seul chantier : read-only, admin confirmé et preuves sourcées."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation import outils  # noqa: E402

from opsys.outils import Autonomie  # noqa: E402

WCT = "WCT-FICTIF-1"
DEVIS = "DEVIS-FICTIF-1"
VERSION = "a" * 64
COUPURE = "2026-10-01T00:00:00Z"


class _RegistreLisant:
    """Contrat utilisé par le lecteur : la taille vient de la copie .lire()."""

    def lire(self):
        return []


def _observation_m3():
    return {
        "wct_id": WCT, "devis_id": DEVIS, "horodatage_completion": "2026-09-29T12:00:00Z",
        "duree_estimee_minutes": 100, "duree_reelle_minutes": 110,
        "type_service": "gouttieres", "quantite": 10, "unite_quantite": "pi_lin",
        "taux_minutes_par_unite": 10, "bareme_version": "2026.1",
        "calibration_version_id": "b" * 64,
        "preuve": {"m3_source_hash": "c" * 64, "m4_wct_hash": "d" * 64,
                   "semantique_reel": "duree_ecoulee_intervention", "unite_duree_reelle": "minute"},
    }


def _m5(rentabilite=None, a_jour=True, version=VERSION):
    contenu = dict(rentabilite or {
        "verdict": "CALCULEE", "marge_reelle_cad": "90.00", "prix_definitif": True,
        "cout_reel_complet": True,
    })
    detail = {
        "verdict": contenu.get("verdict"), "prix_definitif": contenu.get("prix_definitif"),
        "cout_reel": {"complet": contenu.get("cout_reel_complet")},
        "marge_reelle": contenu.get("marge_reelle_cad"),
    }
    return {"ok": True, "resultat": {"accepte": True, "resultat": {
        "nombre": 1, "affichees": 1, "reste": 0, "chantiers": [{
        "devis_id": DEVIS,
        "rentabilite": detail,
        "trace": {"version_entrees": version, "a_jour": a_jour},
    }]}}}


def _m8(
    version=VERSION, variance_unit="pourcentage", unite_materiau="pi", variance_value="25.00",
    variance_definition="definition-fictive-1",
):
    return {"ok": True, "resultat": {"mesures": [
        {"metric_id": "m8_marge_reelle_cad", "statut": "calculee", "valeur": "90.00",
         "entrees": {"version_entrees": version}},
        {"metric_id": "m8_ecart_materiaux_max_pct", "statut": "calculee", "valeur": variance_value,
         "unite": variance_unit, "entrees": {"unite": unite_materiau},
         "version_definition": variance_definition},
    ]}}


def _installer(
    monkeypatch, *, admin=True, roles=None, m4=None, m5=None, m8=None, m5_apres=None, m8_apres=None,
    rapport_m3=None,
):
    appareil = SimpleNamespace(personne="admin-fictif", role="admin", source="appareil") if admin else None
    monkeypatch.setattr(outils.contexte, "identite_appelante", lambda: appareil)
    monkeypatch.setattr(outils.stockage, "connexion_courante", lambda: object())
    monkeypatch.setattr(
        outils.identite, "personne_active",
        lambda _cnx, _personne: SimpleNamespace(roles=set(roles if roles is not None else {"admin"})),
    )
    projection = m4 if m4 is not None else {
        "observations": [{"wct": {"wct_id": WCT}}], "refus": [],
    }
    premiere = m5 if m5 is not None else _m5()
    seconde = m5_apres if m5_apres is not None else premiere
    appels_m5 = 0
    premiere_m8 = m8 if m8 is not None else _m8()
    seconde_m8 = m8_apres if m8_apres is not None else premiere_m8
    appels_m8 = 0

    class FauxCapacites:
        def __init__(self, *_args, **_kwargs):
            pass

        def appeler(self, nom, _arguments):
            nonlocal appels_m5, appels_m8
            if nom == "m4_lire_faits_calibration_m3":
                return {"ok": True, "resultat": projection}
            if nom == "m5_lire_rentabilite_chantier":
                appels_m5 += 1
                return premiere if appels_m5 == 1 else seconde
            if nom == "m8_lire_mesures_chantier":
                appels_m8 += 1
                return premiere_m8 if appels_m8 == 1 else seconde_m8
            raise AssertionError(f"appel non prévu: {nom}")

    import opsys.capacites
    import opsys.departements

    monkeypatch.setattr(opsys.capacites, "Capacites", FauxCapacites)
    monkeypatch.setattr(opsys.departements, "charger_departements", lambda: {
        nom: nom for nom in ("m03-estimation", "m04-field-ops", "m05-financecore", "m08-analytics")
    })
    monkeypatch.setattr(outils, "registre_production", _RegistreLisant)
    monkeypatch.setattr(outils, "registre_devis_production", lambda: [])
    rapport_defaut = {
        "statut": "insuffisant", "_observations_qualifiees": [_observation_m3()], "refus_jointure_m3": {},
        "provenance_observations": [{
            "wct_id": WCT, "m3_source_hash": "c" * 64, "m4_wct_hash": "d" * 64, "partition": "train",
        }],
        "exclusions": [],
    }
    monkeypatch.setattr(outils.calibration_raccord, "construire_rapport", lambda **_kw: rapport_m3 or rapport_defaut)


def test_outil_est_t0_et_borne_a_admin_wct_et_coupure_utc():
    outil = next(o for o in outils.outils() if o.nom == "m3_lire_apprentissage_chantier")
    assert outil.autonomie == Autonomie.T0
    assert outil.roles_appareil == frozenset({"admin"})
    assert set(outil.parametres["properties"]) == {"wct_id", "coupure_utc"}
    assert outil.parametres["required"] == ["wct_id", "coupure_utc"]
    assert outil.parametres["additionalProperties"] is False


def test_rapport_joint_conserve_provenance_et_n_affirme_pas_de_cause(monkeypatch):
    _installer(monkeypatch)

    rapport = outils.lire_apprentissage_chantier(WCT, COUPURE)

    assert rapport["statut"] == "observee"
    assert rapport["coupure_utc"] == COUPURE
    assert rapport["sources"] == {
        "wct_id": WCT, "devis_id": DEVIS, "estimation_hash": "c" * 64,
        "wct_hash": "d" * 64, "version_calibration": "b" * 64,
        "horodatage_completion_utc": "2026-09-29T12:00:00Z", "partition_calibration": "train",
    }
    assert rapport["temps"]["ecoule_reel_minutes"] == 110
    assert rapport["temps"]["paie_heures_personnes"] == "non mesurees par ces sources"
    assert rapport["rentabilite"]["montant_marge_reelle_cad"] == "90.00"
    assert rapport["rentabilite"]["version_entrees_m8"] == rapport["rentabilite"]["version_entrees_m5"]
    assert rapport["rentabilite"]["trace_m5_a_jour"] is True
    assert rapport["variance_materiaux"]["valeur"] == "25.00"
    assert rapport["variance_materiaux"]["cause"] is None and rapport["cause"] is None


@pytest.mark.parametrize("roles", [{"employee"}, set()])
def test_identite_admin_revoquee_ou_sans_role_est_refusee(monkeypatch, roles):
    _installer(monkeypatch, roles=roles)
    assert outils.lire_apprentissage_chantier(WCT, COUPURE) == {
        "statut": "refuse", "raison": "identite_admin_authentifiee_requise",
    }


def test_appel_agent_sans_appareil_admin_est_refuse_avant_les_lectures(monkeypatch):
    _installer(monkeypatch, admin=False)
    assert outils.lire_apprentissage_chantier(WCT, COUPURE)["statut"] == "refuse"


def test_wct_m4_duplique_est_exclu_sans_jointure_arbitraire(monkeypatch):
    _installer(monkeypatch, m4={"observations": [{"wct": {"wct_id": WCT}}] * 2, "refus": []})
    rapport = outils.lire_apprentissage_chantier(WCT, COUPURE)
    assert rapport["statut"] == "exclu"
    assert "wct_m4_ambigu" in rapport["exclusions"]
    assert rapport["cause"] is None


@pytest.mark.parametrize(
    ("rapport_m3", "raison"),
    [
        ({"statut": "insuffisant", "observations_qualifiees": [],
          "refus_jointure_m3": {"source_estimation_hash_absent_ou_ambigu": 1}},
         "jointure_m3:source_estimation_hash_absent_ou_ambigu"),
        ({"statut": "insuffisant", "observations_qualifiees": [_observation_m3(), _observation_m3()],
          "refus_jointure_m3": {}}, "jointure_m3_absente_ou_ambigu"),
    ],
)
def test_jointure_m3_absente_ou_ambigue_est_exclue(monkeypatch, rapport_m3, raison):
    _installer(monkeypatch, rapport_m3=rapport_m3)
    rapport = outils.lire_apprentissage_chantier(WCT, COUPURE)
    assert rapport["statut"] == "exclu"
    assert raison in rapport["exclusions"]
    assert rapport["cause"] is None


def test_absence_de_rentabilite_m5_est_nomme_et_sans_marge(monkeypatch):
    absent = {"ok": True, "resultat": {"accepte": True, "resultat": {"chantiers": []}}}
    _installer(monkeypatch, m5=absent)
    rapport = outils.lire_apprentissage_chantier(WCT, COUPURE)
    assert rapport["statut"] == "exclu"
    assert "rentabilite_m5_absente_ou_ambiguite_devis" in rapport["exclusions"]
    assert "montant_marge_reelle_cad" not in rapport


def test_lecture_m8_absente_est_nommee(monkeypatch):
    absent = {"ok": True, "resultat": {"mesures": []}}
    _installer(monkeypatch, m8=absent)
    rapport = outils.lire_apprentissage_chantier(WCT, COUPURE)
    assert rapport["statut"] == "observee"
    assert rapport["rentabilite"]["statut"] == "exclue"
    assert "version_entrees_m8_absente" in rapport["rentabilite"]["exclusions"]
    assert rapport["rentabilite"]["montant_marge_reelle_cad"] is None


@pytest.mark.parametrize(
    ("rentabilite", "a_jour", "version_m5", "version_m8", "raison"),
    [
        ({"verdict": "CALCULEE", "marge_reelle_cad": "90.00", "prix_definitif": False,
          "cout_reel_complet": True}, True, VERSION, VERSION,
         "facture_brouillon_ou_prix_non_definitif"),
        ({"verdict": "CALCULEE", "marge_reelle_cad": "90.00", "prix_definitif": True,
          "cout_reel_complet": False}, True, VERSION, VERSION,
         "cout_reel_incomplet_ou_inconnu"),
        ({"verdict": "CALCULEE", "marge_reelle_cad": "90.00", "prix_definitif": True,
          "cout_reel_complet": True}, False, VERSION, VERSION, "trace_m5_non_a_jour"),
        ({"verdict": "CALCULEE", "marge_reelle_cad": "90.00", "prix_definitif": True,
          "cout_reel_complet": True}, True, VERSION, "e" * 64,
         "version_entrees_m8_divergente_de_m5"),
        ({"verdict": "CALCULEE", "marge_reelle_cad": "90.00", "prix_definitif": True,
          "cout_reel_complet": True}, True, None, None, "version_entrees_m5_absente"),
    ],
)
def test_finalite_cout_fraicheur_et_versions_invalides_excluent_le_montant(
    monkeypatch, rentabilite, a_jour, version_m5, version_m8, raison,
):
    _installer(monkeypatch, m5=_m5(rentabilite, a_jour, version_m5), m8=_m8(version_m8))
    rapport = outils.lire_apprentissage_chantier(WCT, COUPURE)
    assert rapport["rentabilite"]["statut"] == "exclue"
    assert rapport["rentabilite"]["montant_marge_reelle_cad"] is None
    assert raison in rapport["rentabilite"]["exclusions"]


def test_version_m5_changee_pendant_lecture_refuse_le_rapport(monkeypatch):
    premiere = _m5()
    apres = _m5(version="f" * 64)
    _installer(monkeypatch, m5=premiere, m5_apres=apres)

    rapport = outils.lire_apprentissage_chantier(WCT, COUPURE)

    assert rapport["statut"] == "refuse"
    assert rapport["raison"] == "version_ou_trace_m5_changee_pendant_lecture"


def test_version_m8_changee_pendant_lecture_refuse_le_rapport(monkeypatch):
    _installer(monkeypatch, m8=_m8(), m8_apres=_m8(version="f" * 64))

    rapport = outils.lire_apprentissage_chantier(WCT, COUPURE)

    assert rapport["statut"] == "refuse"
    assert rapport["raison"] == "version_ou_mesure_m8_changee_pendant_lecture"


def test_variance_m8_changee_pendant_lecture_refuse_le_rapport(monkeypatch):
    _installer(monkeypatch, m8=_m8(), m8_apres=_m8(variance_value="30.00"))

    rapport = outils.lire_apprentissage_chantier(WCT, COUPURE)

    assert rapport["statut"] == "refuse"
    assert rapport["raison"] == "variance_m8_changee_pendant_lecture"


def test_unite_variance_inconnue_exclut_la_valeur_et_nomme_la_raison(monkeypatch):
    _installer(monkeypatch, m8=_m8(unite_materiau=None))

    rapport = outils.lire_apprentissage_chantier(WCT, COUPURE)

    assert rapport["variance_materiaux"]["statut"] == "exclue"
    assert rapport["variance_materiaux"]["valeur"] is None
    assert rapport["variance_materiaux"]["exclusions"] == ["unite_materiau_absente_ou_inconnue"]
    assert rapport["variance_materiaux"]["cause"] is None


def test_role_admin_revoque_avant_sortie_refuse_le_rapport(monkeypatch):
    _installer(monkeypatch)
    appels = 0

    def personne_active(_cnx, _personne):
        nonlocal appels
        appels += 1
        return SimpleNamespace(roles={"admin"}) if appels == 1 else None

    monkeypatch.setattr(outils.identite, "personne_active", personne_active)
    assert outils.lire_apprentissage_chantier(WCT, COUPURE) == {
        "statut": "refuse", "raison": "identite_admin_revoquee_pendant_lecture",
    }
    assert appels == 2


def test_vue_evenement_m5_ne_remplace_pas_le_contrat_detail_filtre(monkeypatch):
    faux_detail = _m5()
    faux_detail["resultat"]["resultat"]["chantiers"][0]["rentabilite"] = {
        "verdict": "CALCULEE", "prix_definitif": True,
        "cout_reel_complet": True, "marge_reelle_cad": "90.00",
    }
    _installer(monkeypatch, m5=faux_detail)
    rapport = outils.lire_apprentissage_chantier(WCT, COUPURE)
    assert rapport["rentabilite"]["statut"] == "exclue"
    assert rapport["rentabilite"]["montant_marge_reelle_cad"] is None
    assert "cout_reel_incomplet_ou_inconnu" in rapport["rentabilite"]["exclusions"]


@pytest.mark.parametrize("coupure", ["2026-10-01T00:00:00", "2026-10-01T00:00:00+01:00", "invalide"])
def test_coupure_sans_utc_est_refusee(monkeypatch, coupure):
    _installer(monkeypatch)
    assert outils.lire_apprentissage_chantier(WCT, coupure) == {
        "statut": "refuse", "raison": "coupure_utc_invalide",
    }
