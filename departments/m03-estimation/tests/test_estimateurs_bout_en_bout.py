"""Bout en bout M3.8b : barème et mesures DÉCLARÉS, quatre services, reçu, révision et rejeu — vrais outils.

SQLite migrée, horloge injectée, données FICTIVES. Aucun prix réel, aucun envoi, aucune écriture hors déclarations
humaines : le calcul par service est une lecture.
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
from m3_estimation import estimateurs_service  # noqa: E402
from m3_estimation import outils as outils_m3  # noqa: E402

from opsys import contexte, horloge, identite, stockage  # noqa: E402
from opsys.outils import executer_atomique  # noqa: E402

_MOT_DE_PASSE = "un-mot-de-passe-suffisamment-long"
PROPRIO = ("proprio.un", "admin")
ADMIN = ("admin.un", "admin")


def _appeler(nom, arguments, *, qui):
    outil = next(o for o in outils_m3.outils() if o.nom == nom)
    with contexte.appele_par_appareil(contexte.IdentiteAppelante(personne=qui[0], role=qui[1])):
        reponse = executer_atomique(outil, arguments)
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


@pytest.fixture
def instance(tmp_path, monkeypatch, declarer_services):
    url = f"sqlite:///{tmp_path / 'opsys-estimateurs-e2e.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    monkeypatch.setattr(horloge, "maintenant", lambda: ce.MAINTENANT)
    declarer_services()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "proprio.un", "Proprio Un", _MOT_DE_PASSE, roles=["admin"])
        identite.creer_personne(cnx, "admin.un", "Admin Un", _MOT_DE_PASSE, roles=["admin"])
    yield monkeypatch
    stockage.liberer()


def _declarer(definition, mesure_id, grandeur, valeur, unite, basse, haute, *, revision=0, service=None,
              lead_id=ce.LEAD):
    resultat = _appeler("m3_declarer_mesure", {
        "mesure_id": mesure_id, "revision_attendue": revision, "lead_id": lead_id, "service": service or definition,
        "grandeur": grandeur, "valeur": valeur, "unite": unite, "borne_basse": basse, "borne_haute": haute,
        "methode": "releve_sur_place", "confiance": "elevee", "mesure_le": "2026-11-02T09:00:00+00:00",
        "pieces": [f"{mesure_id}-photo"]}, qui=ADMIN)
    assert resultat["accepte"] is True, resultat
    return resultat["resultat"]


def _calculer(service, refs, *, lead_id=ce.LEAD):
    return _appeler("m3_calculer_estimation_service", {
        "lead_id": lead_id, "service": service,
        "bareme_ref": {"bareme_id": "bareme-estimateurs-fictif", "version": 1}, "mesures_ref": refs}, qui=ADMIN)


def test_quatre_services_sont_chiffres_par_le_code_puis_rejoues_apres_revision(instance):
    # 1. le propriétaire déclare le barème et ses quatre estimateurs (aucune valeur du code)
    declare = _appeler("m3_declarer_bareme", {
        "bareme_id": "bareme-estimateurs-fictif", "version_attendue": 0, "lignes": ce.lignes(),
        "date_effet": ce.JOUR_EFFET, "parametres": ce.parametres(), "soumission": deepcopy(cb.SOUMISSION)},
        qui=PROPRIO)
    assert declare["accepte"] is True, declare

    # 2. les mesures de chaque composante, déclarées par une personne
    _declarer(ce.GOUTTIERES, "mes-gouttiere", "longueur_gouttiere", "100", "pi.lin", "98", "102")
    _declarer(ce.GOUTTIERES, "mes-descente", "longueur_descente", "40", "pi.lin", "39", "41")
    _declarer(ce.GOUTTIERES, "mes-coin", "coin", "6", "unite", "6", "6")
    _declarer(ce.REVETEMENT, "mes-surface", "surface_brute", "1200", "pi2", "1150", "1250")
    _declarer(ce.REVETEMENT, "mes-ouverture", "ouverture", "100", "pi2", "95", "105")
    _declarer(ce.SOFFITE, "mes-soffite", "longueur_soffite", "80", "pi.lin", "80", "80")
    _declarer(ce.SOFFITE, "mes-fascia", "longueur_fascia", "80", "pi.lin", "80", "80")
    _declarer(ce.REPARATION, "mes-reparation", "heures_reparation", "1", "heure", "1", "1")

    # 3. chaque service est composé et chiffré par le code, avec un reçu vérifiable
    gouttieres = _calculer(ce.GOUTTIERES, [
        {"mesure_id": "mes-gouttiere"}, {"mesure_id": "mes-descente"}, {"mesure_id": "mes-coin"}])["resultat"]
    assert gouttieres["quantite"] == {"basse": "152", "retenue": "155", "haute": "158", "unite": "pi.lin"}
    assert gouttieres["couts"] == {
        "min_cad": "1444.00", "probable_cad": "1705.00", "max_cad": "2054.00",
        "unite_monetaire": "CAD", "arrondi": "ROUND_HALF_UP"}
    assert gouttieres["prix_recommande_cad"] == "2216.50"
    assert estimateurs_service.verifier_recu(gouttieres["recu"]) == (True, None)

    revetement = _calculer(ce.REVETEMENT, [{"mesure_id": "mes-surface"}, {"mesure_id": "mes-ouverture"}])["resultat"]
    assert revetement["quantite"]["retenue"] == "1100" and revetement["statut"] == "a_revoir"
    assert estimateurs_service.verifier_recu(revetement["recu"]) == (True, None)

    soffite = _calculer(ce.SOFFITE, [{"mesure_id": "mes-soffite"}, {"mesure_id": "mes-fascia"}])["resultat"]
    assert soffite["quantite"]["retenue"] == "160"
    assert soffite["couts"]["probable_cad"] == "1440.00"  # 160 x 9,00 (mode fictif)

    reparation = _calculer(ce.REPARATION, [{"mesure_id": "mes-reparation"}])["resultat"]
    assert reparation["quantite"]["retenue"] == "1.5"
    assert reparation["recu"]["quantite"]["minimum_applique"] is True
    assert reparation["duree_minutes"] == "90"

    # 4. une révision de mesure n'écrase pas la précédente : le reçu avec la révision 1 reste rejouable
    _declarer(ce.GOUTTIERES, "mes-gouttiere", "longueur_gouttiere", "110", "pi.lin", "110", "110", revision=1)
    ancien = _calculer(ce.GOUTTIERES, [
        {"mesure_id": "mes-gouttiere", "revision": 1}, {"mesure_id": "mes-descente"},
        {"mesure_id": "mes-coin"}])["resultat"]
    assert ancien["quantite"]["retenue"] == "155" and ancien["recu"]["composantes"][0]["revision"] == 1
    nouveau = _calculer(ce.GOUTTIERES, [
        {"mesure_id": "mes-gouttiere"}, {"mesure_id": "mes-descente"}, {"mesure_id": "mes-coin"}])["resultat"]
    assert nouveau["quantite"]["retenue"] == "165" and nouveau["recu"]["composantes"][0]["revision"] == 2
    assert nouveau["recu"]["empreinte"] != ancien["recu"]["empreinte"]

    # 5. une mesure d'un autre chantier ne se prête pas
    autre = _calculer(ce.GOUTTIERES, [
        {"mesure_id": "mes-gouttiere"}, {"mesure_id": "mes-descente"}, {"mesure_id": "mes-coin"}],
        lead_id="lead-autre")
    assert autre["accepte"] is False and autre["verdict"]["code"] == "REJ-MESURE-AUTRE-LEAD"

    # 6. un service sans estimateur déclaré refuse en disant la clé, jamais en chiffrant
    sans = _appliquer({"mesure_id": "mes-gouttiere"}, "ravalement")
    assert sans["accepte"] is False and sans["verdict"]["code"] == "REJ-ESTIMATEUR-NON-DECLARE"
    assert "parametres.estimateurs.ravalement" in sans["verdict"]["detail"]

    # 7. le reçu altéré est détecté ; aucun montant n'est corrigé en silence
    falsifie = deepcopy(gouttieres["recu"])
    falsifie["couts"]["probable_cad"] = "1.00"
    intact, verdict = estimateurs_service.verifier_recu(falsifie)
    assert intact is False and verdict["code"] == "REJ-ESTIMATEUR-RECU-ALTERE"


def _appliquer(mesure_ref, service):
    return _appeler("m3_calculer_estimation_service", {
        "lead_id": ce.LEAD, "service": service,
        "bareme_ref": {"bareme_id": "bareme-estimateurs-fictif", "version": 1},
        "mesures_ref": [mesure_ref]}, qui=ADMIN)
