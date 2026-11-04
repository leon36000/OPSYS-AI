"""Outils réels des estimateurs par service (M3.8b) : barème et mesures déclarés, SQLite migrée, agents.

Vrais outils (``executer_atomique``), vraie base SQLite, vraie horloge injectée, données FICTIVES. Un agent lit et
calcule ; les déclarations restent humaines (outils M3-C1/M3-C2, inchangés).
"""

from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
_SRC = Path(__file__).resolve().parents[1] / "src"  # la source de CE département (la copie jetable des mutations)
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import _commun_bareme as cb  # noqa: E402
import _commun_estimateurs as ce  # noqa: E402
from m3_estimation import estimateurs_service, outils_bareme  # noqa: E402
from m3_estimation import outils as outils_m3  # noqa: E402

from opsys import contexte, horloge, identite, stockage  # noqa: E402
from opsys.outils import executer_atomique  # noqa: E402

_MOT_DE_PASSE = "un-mot-de-passe-suffisamment-long"


def _appeler(nom, arguments, *, qui=None):
    outil = next(o for o in outils_m3.outils() if o.nom == nom)

    def appel():
        return executer_atomique(outil, arguments)

    if qui is None:
        reponse = appel()
    else:
        with contexte.appele_par_appareil(contexte.IdentiteAppelante(personne=qui[0], role=qui[1])):
            reponse = appel()
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


PROPRIO = ("proprio.un", "admin")
ADMIN = ("admin.un", "admin")


@pytest.fixture
def instance(tmp_path, monkeypatch, declarer_services):
    url = f"sqlite:///{tmp_path / 'opsys-estimateurs.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    monkeypatch.setattr(horloge, "maintenant", lambda: ce.MAINTENANT)
    declarer_services()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "proprio.un", "Proprio Un", _MOT_DE_PASSE, roles=["admin"])
        identite.creer_personne(cnx, "admin.un", "Admin Un", _MOT_DE_PASSE, roles=["admin"])
    yield monkeypatch
    stockage.liberer()


def _declarer_bareme(parametres=None, lignes=None):
    resultat = _appeler("m3_declarer_bareme", {
        "bareme_id": "bareme-estimateurs-fictif", "version_attendue": 0,
        "lignes": lignes if lignes is not None else ce.lignes(), "date_effet": ce.JOUR_EFFET,
        "parametres": parametres if parametres is not None else ce.parametres(),
        "soumission": deepcopy(cb.SOUMISSION)}, qui=PROPRIO)
    assert resultat["accepte"] is True, resultat
    return resultat["resultat"]


def _declarer_mesures(service, definitions):
    for definition in definitions:
        resultat = _appeler("m3_declarer_mesure", {
            "mesure_id": definition["mesure_id"], "revision_attendue": 0, "lead_id": ce.LEAD, "service": service,
            "grandeur": definition["grandeur"], "valeur": definition["valeur"], "unite": definition["unite"],
            "borne_basse": definition["borne_basse"], "borne_haute": definition["borne_haute"],
            "methode": "releve_sur_place", "confiance": "elevee",
            "mesure_le": "2026-11-02T09:00:00+00:00",
            "pieces": [definition["mesure_id"] + "-photo"]}, qui=ADMIN)
        assert resultat["accepte"] is True, resultat


def _definitions_gouttieres():
    return [
        {"mesure_id": "mes-gouttiere", "grandeur": "longueur_gouttiere", "valeur": "100", "unite": "pi.lin",
         "borne_basse": "98", "borne_haute": "102"},
        {"mesure_id": "mes-descente", "grandeur": "longueur_descente", "valeur": "40", "unite": "pi.lin",
         "borne_basse": "39", "borne_haute": "41"},
        {"mesure_id": "mes-coin", "grandeur": "coin", "valeur": "6", "unite": "unite",
         "borne_basse": "6", "borne_haute": "6"},
    ]


def _calculer(bareme_ref, mesures_ref, *, service=ce.GOUTTIERES, lead_id=ce.LEAD):
    return _appeler("m3_calculer_estimation_service", {
        "lead_id": lead_id, "service": service, "bareme_ref": bareme_ref, "mesures_ref": mesures_ref})


def test_l_outil_calcule_l_estimation_du_service_avec_les_vrais_registres(instance):
    version = _declarer_bareme()
    assert version["rejoue"] is False
    assert version["services_avec_estimateur"] == [ce.GOUTTIERES, ce.REPARATION, ce.REVETEMENT, ce.SOFFITE]
    _declarer_mesures(ce.GOUTTIERES, _definitions_gouttieres())
    refs = [{"mesure_id": "mes-gouttiere"}, {"mesure_id": "mes-descente"}, {"mesure_id": "mes-coin"}]
    reponse = _calculer({"bareme_id": "bareme-estimateurs-fictif", "version": 1}, refs)
    assert reponse["accepte"] is True
    resultat = reponse["resultat"]
    assert resultat["quantite"]["retenue"] == "155"
    assert resultat["couts"]["probable_cad"] == "1705.00"
    assert resultat["recu"]["bareme_ref"]["empreinte"] == version["bareme_ref"]["empreinte"]
    assert resultat["recu"]["service"] == ce.GOUTTIERES and resultat["recu"]["lead_id"] == ce.LEAD


def test_le_meme_appel_rejoue_donne_le_meme_recu_et_n_ecrit_rien(instance):
    _declarer_bareme()
    _declarer_mesures(ce.GOUTTIERES, _definitions_gouttieres())
    refs = [{"mesure_id": "mes-gouttiere"}, {"mesure_id": "mes-descente"}, {"mesure_id": "mes-coin"}]
    premier = _calculer({"bareme_id": "bareme-estimateurs-fictif", "version": 1}, refs)
    second = _calculer({"bareme_id": "bareme-estimateurs-fictif", "version": 1}, refs)
    assert premier == second
    assert premier["resultat"]["recu"]["empreinte"] == second["resultat"]["recu"]["empreinte"]
    from m3_estimation import mesure_declaree, outils_bareme

    assert len(outils_bareme.journal_bareme()) == 1
    assert len(mesure_declaree._charger(outils_bareme.journal_mesures())[0]) == 3


def test_un_bareme_sans_estimateur_dit_la_cle_a_declarer_au_lieu_de_chiffrer(instance):
    _appeler("m3_declarer_bareme", {
        "bareme_id": "bareme-sans-estimateur", "version_attendue": 0, "lignes": [
            {"service": ce.GOUTTIERES, "genre": "ouvrage", "element": "gouttière fictive", "unite": "pi.lin",
             "cout_unitaire_min": "9.50", "cout_unitaire_max": "13.00",
             "source_ecrite": "Feuille fictive (essai)"}],
        "date_effet": ce.JOUR_EFFET, "parametres": {"plancher_rentable_cad": "1000"},
        "soumission": {}}, qui=PROPRIO)
    reponse = _calculer({"bareme_id": "bareme-sans-estimateur", "version": 1}, [{"mesure_id": "x"}])
    assert reponse["accepte"] is False
    assert reponse["verdict"]["code"] == "REJ-ESTIMATEUR-NON-DECLARE"
    assert "parametres.estimateurs.gouttieres" in reponse["verdict"]["detail"]


def test_une_mesure_inconnue_est_refusee_avant_tout_calcul(instance):
    _declarer_bareme()
    _declarer_mesures(ce.GOUTTIERES, _definitions_gouttieres())
    reponse = _calculer({"bareme_id": "bareme-estimateurs-fictif", "version": 1},
                        [{"mesure_id": "mes-absente"}])
    assert reponse["accepte"] is False
    assert reponse["verdict"]["code"] == "REJ-MESURE-INTROUVABLE"
    assert "m3_declarer_mesure" in reponse["verdict"]["detail"]


def test_un_bareme_hors_vigueur_est_refuse_avec_la_version_a_referencer(instance):
    _declarer_bareme()
    reponse = _calculer({"bareme_id": "bareme-estimateurs-fictif", "version": 2}, [])
    assert reponse["accepte"] is False
    assert reponse["verdict"]["code"] == "REJ-BAREME-VERSION-INCONNUE"
    detail = reponse["verdict"]["detail"]
    assert "version 1" in detail or "dernière version déclarée : 1" in detail


def test_une_mesure_d_un_autre_lead_est_refusee_par_l_outil(instance):
    _declarer_bareme()
    _declarer_mesures(ce.GOUTTIERES, _definitions_gouttieres())
    reponse = _calculer({"bareme_id": "bareme-estimateurs-fictif", "version": 1},
                        [{"mesure_id": "mes-gouttiere"}], lead_id="lead-autre")
    assert reponse["accepte"] is False
    assert reponse["verdict"]["code"] == "REJ-MESURE-AUTRE-LEAD"
    assert "autre lead" in reponse["verdict"]["detail"]


def test_le_refus_d_une_grandeur_hostile_ne_recopie_pas_le_texte(instance):
    _declarer_bareme()
    _declarer_mesures(ce.GOUTTIERES, _definitions_gouttieres())
    _appeler("m3_declarer_mesure", {
        "mesure_id": "mes-hostile", "revision_attendue": 0, "lead_id": ce.LEAD, "service": ce.GOUTTIERES,
        "grandeur": "<img src=x onerror=alert(1)>", "valeur": "1", "unite": "pi.lin", "borne_basse": "1",
        "borne_haute": "1", "methode": "releve_sur_place", "confiance": "elevee",
        "mesure_le": "2026-11-02T09:00:00+00:00", "pieces": ["p"]}, qui=ADMIN)
    reponse = _calculer({"bareme_id": "bareme-estimateurs-fictif", "version": 1},
                        [{"mesure_id": "mes-gouttiere"}, {"mesure_id": "mes-hostile"}])
    assert reponse["accepte"] is False
    assert reponse["verdict"]["code"] == "REJ-ESTIMATEUR-MESURE-NON-PREVUE"
    assert "<img" not in reponse["verdict"]["detail"]


def test_l_outil_est_un_t0_de_lecture_ferme_aux_appareils_et_decrit_ses_entrees():
    outil = next(o for o in outils_m3.outils() if o.nom == "m3_calculer_estimation_service")
    assert outil.autonomie.value == "T0"
    assert outil.roles_appareil == frozenset()
    assert outil.parametres["required"] == ["lead_id", "service", "bareme_ref", "mesures_ref"]
    assert "Decimal" in outil.description or "reçu" in outil.description


def test_l_outil_ne_calcule_pas_un_prix_sans_mode_ni_taux_declares(instance):
    parametres = ce.parametres()
    parametres.pop("taux_marge")
    lignes = ce.lignes()
    for ligne in lignes:
        if ligne["service"] == ce.GOUTTIERES:
            ligne.pop("cout_unitaire_mode")
    _declarer_bareme(parametres=parametres, lignes=lignes)
    _declarer_mesures(ce.GOUTTIERES, _definitions_gouttieres())
    reponse = _calculer({"bareme_id": "bareme-estimateurs-fictif", "version": 1},
                        [{"mesure_id": "mes-gouttiere"}, {"mesure_id": "mes-descente"},
                         {"mesure_id": "mes-coin"}])
    assert reponse["accepte"] is True
    assert reponse["resultat"]["couts"]["probable_cad"] is None
    assert reponse["resultat"]["prix_recommande_cad"] is None
    assert any("cout_unitaire_mode" in manque for manque in reponse["resultat"]["elements_manquants"])
    assert any("taux_marge.normal" in manque for manque in reponse["resultat"]["elements_manquants"])


def test_le_resume_dit_quand_aucun_plancher_n_est_declare(instance):
    resultat = _appeler("m3_declarer_bareme", {
        "bareme_id": "sans-plancher", "version_attendue": 0, "lignes": [
            {"service": ce.GOUTTIERES, "genre": "ouvrage", "element": "fictif", "unite": "pi.lin",
             "cout_unitaire_min": "1", "cout_unitaire_max": "2", "source_ecrite": "fictif"}],
        "date_effet": ce.JOUR_EFFET,
        "parametres": {"estimateurs": {ce.GOUTTIERES: ce.estimateurs()[ce.GOUTTIERES]}},
        "soumission": {}}, qui=PROPRIO)
    assert resultat["accepte"] is True, resultat
    assert resultat["resultat"]["plancher_rentable_declare"] is False


def test_une_liste_de_mesures_vide_ou_non_liste_est_refusee_par_l_outil(instance):
    _declarer_bareme()
    for mesures_ref in ([], {"mesure_id": "mes-gouttiere"}):
        reponse = outils_bareme.calculer_estimation_service(
            ce.LEAD, ce.GOUTTIERES, {"bareme_id": "bareme-estimateurs-fictif", "version": 1}, mesures_ref)
        assert reponse["accepte"] is False
        assert reponse["verdict"]["code"] == "REJ-ESTIMATEUR-INVALIDE"
        assert "mesures_ref" in reponse["verdict"]["detail"]


def test_le_schema_de_l_outil_ferme_les_cles_et_exige_une_mesure():
    outil = next(o for o in outils_m3.outils() if o.nom == "m3_calculer_estimation_service")
    assert outil.parametres["additionalProperties"] is False
    mesures = outil.parametres["properties"]["mesures_ref"]
    assert mesures["minItems"] == 1 and mesures["maxItems"] == estimateurs_service.MAX_COMPOSANTES
    bareme = outil.parametres["properties"]["bareme_ref"]
    assert bareme["additionalProperties"] is False
