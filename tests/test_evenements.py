"""Bus d'événements du socle (ADR-0009 §3, PLAN T1.2-a) : `publier`, `repartir`, `etat`, catalogue,
cohérence des déclarations `department.yaml`. Aucun département réel n'est impliqué (T1.2-b à
T1.2-d) : les départements de démonstration de `tests/fixtures/departements` et des consommateurs
en mémoire (`dataclasses.replace`, patron déjà utilisé par `test_tableau_de_bord.py`) en tiennent
lieu, sans jamais toucher au manifeste partagé sur disque.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import shutil

import demo_consommateur_echec
import demo_consommateur_ok
import pytest
import yaml
from sqlalchemy import func, select

from opsys import evenements, stockage
from opsys.outils import Outil, executer_atomique
from opsys.stockage.schema import EVENEMENTS_SORTANTS

_SCHEMA_ECHOUER = {"type": "object", "properties": {"echouer": {"type": "boolean"}}, "required": ["echouer"]}


@pytest.fixture(autouse=True)
def _reset_consommateurs_demo():
    demo_consommateur_ok.APPELS.clear()
    demo_consommateur_echec.TENTATIVES.clear()
    yield


@pytest.fixture
def deps_succes(departements_demo):
    base = departements_demo["m09-demo"]
    dep = dataclasses.replace(
        base, module_outils="demo_consommateur_ok",
        evenements_publie=("opsys.demo_complete",), evenements_consomme=("opsys.demo_complete",),
    )
    return {dep.id: dep}


@pytest.fixture
def deps_bus(departements_demo):
    """Deux consommateurs abonnés à `opsys.demo_complete` : un qui réussit toujours, un qui échoue
    toujours — pour vérifier qu'un consommateur en échec n'en bloque jamais un autre."""
    base = departements_demo["m09-demo"]
    succes = dataclasses.replace(
        base, module_outils="demo_consommateur_ok",
        evenements_publie=("opsys.demo_complete",), evenements_consomme=("opsys.demo_complete",),
    )
    echec = dataclasses.replace(
        base, id="m09-demo-echec", module_outils="demo_consommateur_echec",
        evenements_consomme=("opsys.demo_complete",),
    )
    return {succes.id: succes, echec.id: echec}


def _compte_sortants(where=None) -> int:
    requete = select(func.count()).select_from(EVENEMENTS_SORTANTS)
    if where is not None:
        requete = requete.where(where)
    with stockage.transaction() as cnx:
        return cnx.execute(requete).scalar_one()


# -- atomicité : écriture métier + événement, une seule transaction ----------------------------
def _ecrire_et_publier(echouer: bool) -> dict:
    stockage.maillons("m-demo-atomicite", "principal").append({"ecrit": True})
    evenements.publier("opsys.demo_complete", "m-demo-atomicite", {"message": "x"})
    if echouer:
        raise ValueError("refus métier après écriture et publication")
    return {"ok": True}


def test_atomicite_ecriture_et_evenement_annulees_ensemble(session):
    outil = Outil("m9_atomicite_demo", "Écrit un maillon et publie un événement, échoue au besoin.",
                  _SCHEMA_ECHOUER, _ecrire_et_publier)

    reponse = executer_atomique(outil, {"echouer": True})
    assert reponse["ok"] is False
    assert len(stockage.maillons("m-demo-atomicite", "principal")) == 0
    assert _compte_sortants() == 0

    reponse_ok = executer_atomique(outil, {"echouer": False})
    assert reponse_ok["ok"] is True
    assert len(stockage.maillons("m-demo-atomicite", "principal")) == 1
    assert _compte_sortants() == 1


# -- catalogue : type inconnu et charge invalide, aucune écriture ------------------------------
def test_catalogue_type_inconnu_rejete_sans_ecriture(session):
    with pytest.raises(evenements.TypeEvenementInconnu):
        evenements.publier("type.qui.nexiste.pas", "test", {"message": "x"})
    assert _compte_sortants() == 0


def test_catalogue_charge_invalide_rejetee_sans_ecriture(session):
    with pytest.raises(evenements.ChargeInvalide):
        evenements.publier("opsys.demo_complete", "test", {})  # "message" manquant
    assert _compte_sortants() == 0


# -- catalogue m4.travaux_termines : le WCT réel de M4 (outbox.py::CHAMPS_WCT), plus les champs
# optionnels M5/M7 (audits) -- voir src/opsys/evenements/catalogue/m4.travaux_termines.json.
def _wct_exemple(**overrides) -> dict:
    base = {
        "wct_id": "wct-abc123",
        "intervention_id": "int-1",
        "lead_id": "lead-1",
        "technicien_id": "tech-1",
        "horodatage_completion": "2026-09-28T14:00:00-04:00",
        "fix_gps_completion": {"latitude": 45.75, "longitude": -73.5},
        "duree_reelle_minutes": 120,
        "ecart_signale": False,
        "revue_id": None,
        "hash_maillon": "deadbeef",
        "consommateurs_cibles": ["M6", "M5", "M2", "M7", "M8", "M10"],
        "devis_id": "devis-1",
        "statut": "completed_verified",
    }
    base.update(overrides)
    return base


def test_catalogue_m4_travaux_termines_accepte_un_wct_valide(session):
    assert evenements.publier("m4.travaux_termines", "m04-field-ops", _wct_exemple())


def test_catalogue_m4_travaux_termines_accepte_les_champs_optionnels_m7(session):
    charge = _wct_exemple(
        ville="Repentigny", type_travaux="gouttières", photos=["chantier-1.jpg"],
        description_factuelle="Installation de gouttières en aluminium.",
        consentement_marketing=True, client_satisfait=True,
    )
    assert evenements.publier("m4.travaux_termines", "m04-field-ops", charge)


def test_catalogue_m4_travaux_termines_accepte_devis_et_revue_absents(session):
    # devis_id et revue_id sont requis mais nullables (outbox.py : None si sans devis / sans écart).
    assert evenements.publier("m4.travaux_termines", "m04-field-ops", _wct_exemple(devis_id=None, revue_id="rev-1"))


@pytest.mark.parametrize(
    "modification",
    [
        lambda c: c.pop("duree_reelle_minutes"),
        lambda c: c.pop("devis_id"),  # requis (même si nullable) : absent, pas seulement null
        lambda c: c.update(statut="termine"),  # ancien statut, remplacé par T1.1-b
        lambda c: c.update(champ_invente="x"),
    ],
)
def test_catalogue_m4_travaux_termines_rejette_un_wct_invalide(session, modification):
    charge = _wct_exemple()
    modification(charge)
    with pytest.raises(evenements.ChargeInvalide):
        evenements.publier("m4.travaux_termines", "m04-field-ops", charge)
    assert _compte_sortants() == 0


# -- idempotence -----------------------------------------------------------------------------
def test_idempotence_evenement_id_fourni_deux_fois(session):
    id1 = evenements.publier("opsys.demo_complete", "test", {"message": "a"}, evenement_id="fixe-1")
    id2 = evenements.publier("opsys.demo_complete", "test", {"message": "a"}, evenement_id="fixe-1")
    assert id1 == id2 == "fixe-1"
    assert _compte_sortants(EVENEMENTS_SORTANTS.c.evenement_id == "fixe-1") == 1


def test_idempotence_evenement_id_par_defaut_est_unique(session):
    id1 = evenements.publier("opsys.demo_complete", "test", {"message": "a"})
    id2 = evenements.publier("opsys.demo_complete", "test", {"message": "b"})
    assert id1 != id2
    assert _compte_sortants() == 2


def test_redelivery_ne_reexecute_jamais_un_evenement_traite(session, deps_succes):
    evenements.publier("opsys.demo_complete", "test", {"message": "une-fois"})

    resume1 = evenements.repartir(deps_succes, maintenant="2026-09-28T00:00:00+00:00")
    assert resume1 == {"livres": 1, "traites": 1, "echecs": 0, "quarantaines": 0, "ignores": 0}
    assert demo_consommateur_ok.APPELS == ["une-fois"]

    resume2 = evenements.repartir(deps_succes, maintenant="2026-09-28T01:00:00+00:00")
    assert resume2 == {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
    assert demo_consommateur_ok.APPELS == ["une-fois"]  # jamais rejoué

    etat = evenements.etat()
    assert etat["comptes"] == {"traite": 1}
    assert etat["quarantaine"] == []


# -- consommateur en échec : réessais espacés, quarantaine, isolation --------------------------
def test_consommateur_en_echec_reessais_espaces_puis_quarantaine(session, deps_bus):
    evenements.publier("opsys.demo_complete", "test", {"message": "echoue"})
    t0 = dt.datetime(2026, 9, 28, tzinfo=dt.UTC)

    # tentative 1 : le consommateur qui réussit est traité malgré l'échec de l'autre (isolation)
    resume = evenements.repartir(deps_bus, maintenant=t0.isoformat())
    assert resume == {"livres": 2, "traites": 1, "echecs": 1, "quarantaines": 0, "ignores": 0}
    assert demo_consommateur_ok.APPELS == ["echoue"]
    assert len(demo_consommateur_echec.TENTATIVES) == 1

    # relivraison immédiate : le second n'est pas encore dû (backoff), rien de neuf à faire
    resume_immediat = evenements.repartir(deps_bus, maintenant=t0.isoformat())
    assert resume_immediat == {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}

    # tentatives 2 à 4 : toujours en échec, jamais bloquantes pour le reste
    t = t0
    for _ in range(3):
        t += dt.timedelta(seconds=100)  # au-delà du plus grand backoff possible (2**4 = 16 s)
        r = evenements.repartir(deps_bus, maintenant=t.isoformat())
        assert r == {"livres": 1, "traites": 0, "echecs": 1, "quarantaines": 0, "ignores": 0}

    # tentative 5 : quarantaine
    t += dt.timedelta(seconds=100)
    r5 = evenements.repartir(deps_bus, maintenant=t.isoformat())
    assert r5 == {"livres": 1, "traites": 0, "echecs": 0, "quarantaines": 1, "ignores": 0}
    assert len(demo_consommateur_echec.TENTATIVES) == 5

    # plus aucune relivraison automatique une fois en quarantaine
    t += dt.timedelta(seconds=10_000)
    r_apres = evenements.repartir(deps_bus, maintenant=t.isoformat())
    assert r_apres == {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
    assert len(demo_consommateur_echec.TENTATIVES) == 5  # pas de 6e appel

    # les écritures du consommateur en échec sont annulées à CHAQUE tentative
    assert len(stockage.maillons("m-demo-evenements-echec", "recus")) == 0
    # le consommateur qui réussit, lui, reste acquis (une seule fois)
    assert len(stockage.maillons("m-demo-evenements-ok", "recus")) == 1

    etat = evenements.etat()
    assert etat["comptes"] == {"traite": 1, "quarantaine": 1}
    assert len(etat["quarantaine"]) == 1
    ligne = etat["quarantaine"][0]
    assert ligne["consommateur"] == "m09-demo-echec"
    assert ligne["tentatives"] == 5
    assert "RuntimeError" in ligne["derniere_erreur"]


# -- verifier_coherence : cohérence des déclarations department.yaml/evenements ----------------
def test_verifier_coherence_type_absent_du_catalogue(departements_demo):
    base = departements_demo["m09-demo"]
    dep = dataclasses.replace(base, evenements_consomme=("type.bidon",), module_outils="demo_consommateur_ok")
    problemes = evenements.verifier_coherence({dep.id: dep})
    assert any("absent du catalogue" in p for p in problemes)


def test_verifier_coherence_type_consomme_sans_fonction(departements_demo):
    base = departements_demo["m09-demo"]
    # demo_consommateur_ok ne fournit une fonction que pour "opsys.demo_complete" : déclarer aussi
    # "m4.travaux_termines" (un type réel du catalogue) sans fonction assortie doit être détecté,
    # distinctement d'un type absent du catalogue.
    dep = dataclasses.replace(
        base, module_outils="demo_consommateur_ok",
        evenements_consomme=("opsys.demo_complete", "m4.travaux_termines"),
    )
    problemes = evenements.verifier_coherence({dep.id: dep})
    assert any("m4.travaux_termines" in p and "sans fonction" in p for p in problemes)
    assert not any("absent du catalogue" in p for p in problemes)


def test_verifier_coherence_fonction_orpheline(departements_demo):
    base = departements_demo["m09-demo"]
    dep = dataclasses.replace(
        base, module_outils="demo_consommateur_ok",
        evenements_publie=("opsys.demo_complete",), evenements_consomme=(),
    )
    problemes = evenements.verifier_coherence({dep.id: dep})
    assert any("orpheline" in p for p in problemes)


def test_verifier_coherence_declaration_coherente_ne_signale_rien(departements_demo):
    base = departements_demo["m09-demo"]
    dep = dataclasses.replace(
        base, module_outils="demo_consommateur_ok",
        evenements_publie=("opsys.demo_complete",), evenements_consomme=("opsys.demo_complete",),
    )
    assert evenements.verifier_coherence({dep.id: dep}) == []


def test_verifier_coherence_ignore_departement_hors_du_bus(departements_demo):
    base = departements_demo["m09-demo"]
    assert evenements.verifier_coherence({base.id: base}) == []


# -- CLI : opsys verifier et opsys evenements etat|repartir -------------------------------------
def _manifeste_avec_evenements(racine_demo, tmp_path, evenements_section: dict):
    cible = tmp_path / "departements"
    shutil.copytree(racine_demo, cible)
    manifeste = cible / "m09-demo" / "department.yaml"
    donnees = yaml.safe_load(manifeste.read_text(encoding="utf-8"))
    donnees["evenements"] = evenements_section
    manifeste.write_text(yaml.safe_dump(donnees, allow_unicode=True), encoding="utf-8")
    return cible


def test_cli_verifier_detecte_une_declaration_incoherente(racine_demo, tmp_path, monkeypatch, capsys):
    from opsys import cli

    cible = _manifeste_avec_evenements(racine_demo, tmp_path, {"consomme": ["type.bidon.inexistant"]})
    monkeypatch.setenv("OPSYS_DEPARTMENTS", str(cible))
    assert cli.main(["verifier"]) == 1
    assert "absent du catalogue" in capsys.readouterr().err


def test_cli_verifier_accepte_une_declaration_coherente(racine_demo, tmp_path, monkeypatch, capsys):
    from opsys import cli

    cible = _manifeste_avec_evenements(
        racine_demo, tmp_path, {"publie": ["opsys.demo_complete"], "consomme": ["opsys.demo_complete"]}
    )
    monkeypatch.setenv("OPSYS_DEPARTMENTS", str(cible))
    assert cli.main(["verifier"]) == 0
    assert "OK" in capsys.readouterr().out


def test_cli_evenements_etat_et_repartir(opsys_home, racine_demo, monkeypatch, capsys):
    import json

    from opsys import cli
    from opsys import stockage as stockage_cli

    # m09-demo, non modifié : evenements.consomme est vide, donc rien n'y est abonné ici.
    monkeypatch.setenv("OPSYS_DEPARTMENTS", str(racine_demo))
    stockage_cli.migrer()
    try:
        evenements.publier("opsys.demo_complete", "test", {"message": "cli"})
        assert cli.main(["evenements", "etat"]) == 0
        etat_initial = json.loads(capsys.readouterr().out)
        assert etat_initial == {"comptes": {}, "quarantaine": []}  # aucun département n'y est abonné ici

        assert cli.main(["evenements", "repartir"]) == 0
        resume = json.loads(capsys.readouterr().out)
        assert resume == {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
    finally:
        stockage_cli.liberer()


# -- serveur : boucle de fond, arrêt propre, désactivable -------------------------------------
_JETON_TEST = "jeton-de-test-suffisamment-long-0123456789"


def test_serveur_boucle_repartiteur_appelle_repartir_et_s_arrete_proprement(departements_demo, session, monkeypatch):
    import time

    from starlette.testclient import TestClient

    from opsys.serveur_mcp import application_http_departements

    appels: list[int] = []
    monkeypatch.setattr(evenements, "repartir", lambda deps: appels.append(1) or {})
    monkeypatch.delenv("OPSYS_EVENEMENTS_REPARTITEUR", raising=False)

    app = application_http_departements(departements_demo, session, _JETON_TEST, hote="127.0.0.1")
    with TestClient(app):
        for _ in range(100):
            if appels:
                break
            time.sleep(0.02)
    assert appels  # au moins un tour avant même le premier sommeil de 3 s (arrêt propre : pas de blocage)


def test_serveur_boucle_repartiteur_desactivable_par_variable_environnement(departements_demo, session, monkeypatch):
    import time

    from starlette.testclient import TestClient

    from opsys.serveur_mcp import application_http_departements

    appels: list[int] = []
    monkeypatch.setattr(evenements, "repartir", lambda deps: appels.append(1) or {})
    monkeypatch.setenv("OPSYS_EVENEMENTS_REPARTITEUR", "0")

    app = application_http_departements(departements_demo, session, _JETON_TEST, hote="127.0.0.1")
    with TestClient(app):
        time.sleep(0.3)  # bien en deçà de l'intervalle de 3 s : rien ne doit s'être produit
    assert appels == []


# -- parité PostgreSQL -----------------------------------------------------------------------
def test_postgresql_bus_evenements_se_comporte_comme_sqlite(monkeypatch, deps_bus):
    from memoire.doubles import postgres_ephemere, raison_sans_docker

    raison = raison_sans_docker()
    if raison is not None:
        pytest.skip(raison)

    with postgres_ephemere() as url_pg:
        url = url_pg.replace("postgresql://", "postgresql+psycopg://", 1)
        monkeypatch.setenv(stockage.ENV_URL, url)
        try:
            stockage.migrer(url)

            id1 = evenements.publier("opsys.demo_complete", "test", {"message": "pg"}, evenement_id="pg-1")
            id2 = evenements.publier("opsys.demo_complete", "test", {"message": "pg"}, evenement_id="pg-1")
            assert id1 == id2 == "pg-1"
            assert _compte_sortants(EVENEMENTS_SORTANTS.c.evenement_id == "pg-1") == 1

            with pytest.raises(evenements.TypeEvenementInconnu):
                evenements.publier("type.bidon", "test", {})
            with pytest.raises(evenements.ChargeInvalide):
                evenements.publier("opsys.demo_complete", "test", {})

            t0 = dt.datetime(2026, 9, 28, tzinfo=dt.UTC)
            resume = evenements.repartir(deps_bus, maintenant=t0.isoformat())
            assert resume == {"livres": 2, "traites": 1, "echecs": 1, "quarantaines": 0, "ignores": 0}
            resume_immediat = evenements.repartir(deps_bus, maintenant=t0.isoformat())
            assert resume_immediat == {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
            assert demo_consommateur_ok.APPELS == ["pg"]
            assert len(stockage.maillons("m-demo-evenements-echec", "recus")) == 0

            etat = evenements.etat()
            assert etat["comptes"] == {"traite": 1, "echec": 1}
        finally:
            stockage.liberer()
