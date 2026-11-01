"""Registre de fournisseurs (capacité « courriel »), console d'administration en lecture, journal append-only et
migration 0040 (SQLite et PostgreSQL éphémère si Docker est disponible)."""

from __future__ import annotations

import json
import sqlite3

import courriel_doubles as dbl
import courriel_qa as qa
import pytest
from alembic import command
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from opsys import stockage
from opsys.console import courriel_ui
from opsys.console.securite import Session
from opsys.courriel_connecteurs import comptes
from opsys.courriel_connecteurs.erreurs import ErreurCourriel
from opsys.courriel_connecteurs.ingestion import IngestionCourriel
from opsys.fournisseurs import catalogue, politique, registre
from opsys.fournisseurs.modele import CAPACITES
from opsys.fournisseurs.registre import RegistreErreur

FICTIF = True


@pytest.fixture
def monde(tmp_path, monkeypatch):
    return qa.preparer(tmp_path, monkeypatch)


# -- registre de fournisseurs
# --------------------------------------------------------------------------------------------
def test_la_capacite_courriel_est_au_catalogue_avec_des_sources():
    assert "courriel" in CAPACITES
    entrees = {f.identifiant: f for f in catalogue.CATALOGUE if f.capacite == "courriel"}
    assert set(entrees) == {
        "courriel.gmail.api",
        "courriel.graph.api",
        "courriel.imap.generique",
        "courriel.mbox.local",
    }
    for f in entrees.values():
        assert (
            f.licence.source.startswith("recherche/R3")
            and f.qualification == "a_mesurer"
            and f.reference_secret is None
        )
    assert entrees["courriel.gmail.api"].mode == "api" and entrees["courriel.gmail.api"].point_acces.startswith(
        "https://"
    )


def test_activation_gmail_refusee_sans_contrat_ni_efvp_puis_acceptee(monde):
    with stockage.transaction() as cnx:
        registre.configurer(cnx, acteur="nathan", identifiant="courriel.gmail.api")
        decision = registre.activer(cnx, acteur="nathan", identifiant="courriel.gmail.api")
    assert not decision.conforme and set(decision.codes) == {politique.CONTRAT_REQUIS, politique.EFVP_REQUISE}
    with stockage.transaction() as cnx:
        registre.configurer(
            cnx,
            acteur="nathan",
            identifiant="courriel.gmail.api",
            revision_attendue=1,
            modifications={
                "contrat_ref": "Entente Google Workspace du client (fictive)",
                "efvp_ref": "EFVP-2026-014 (fictive)",
            },
        )
        assert registre.activer(cnx, acteur="nathan", identifiant="courriel.gmail.api").conforme
        registre.selectionner(cnx, acteur="nathan", capacite="courriel", identifiant="courriel.gmail.api")
        assert registre.resoudre(cnx, "courriel").fournisseur.identifiant == "courriel.gmail.api"
        vue = registre.vue(cnx, "courriel.gmail.api")
    assert vue["actif"] and vue["qualification"] == "a_mesurer"  # jamais « qualifié » : aucune mesure réelle


def test_imap_et_mbox_sont_conformes_sans_contrat(monde):
    with stockage.transaction() as cnx:
        for identifiant in ("courriel.imap.generique", "courriel.mbox.local"):
            registre.configurer(cnx, acteur="nathan", identifiant=identifiant)
            assert registre.activer(cnx, acteur="nathan", identifiant=identifiant).conforme


def test_un_employe_ne_configure_pas_un_connecteur_courriel(monde):
    from opsys import identite

    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "employe", "Employé fictif", "mot-de-passe-employe-1234", ["employee"])
        with pytest.raises(RegistreErreur):
            registre.configurer(cnx, acteur="employe", identifiant="courriel.gmail.api")


# -- état visible côté admin
# ---------------------------------------------------------------------------------------------------
def _application(administrateur: bool):
    session = Session(
        utilisateur="nathan" if administrateur else "employe",
        roles=frozenset({"nathan_owner"}),
        csrf="c" * 32,
        expire=2**40,
    )

    def session_page(_request, **_):
        return session

    app = FastAPI()
    app.include_router(
        courriel_ui.creer_router(
            session_page=session_page, session_api=session_page, cnx_factory=stockage.transaction, prefixe=""
        )
    )
    return TestClient(app)


def test_la_console_montre_etat_synchro_et_erreurs_typees_sans_secret_ni_contenu(monde):
    qa.creer_compte(monde)
    qa.connecter_oauth(monde)
    monde.gmail.ajouter(dbl.courriel_brut(objet="Sujet confidentiel QQQ", corps="Corps confidentiel RRR"))
    ing = IngestionCourriel(stockage.transaction, acteur="nathan", signaler=monde.service.signaler_erreur)
    ing.synchroniser("gmail-paul", monde.service.fournisseur("gmail-paul"), "INBOX")
    monde.oauth_google.invalid_grant = True
    monde.horloge.t += 4000
    ing.synchroniser("gmail-paul", monde.service.fournisseur("gmail-paul"), "INBOX")
    acces = monde.oauth_google.dernier_acces
    client = _application(True)
    page = client.get("/courriel")
    assert page.status_code == 200 and "gmail-paul" in page.text and "Reconnexion requise" in page.text
    assert "REJ-COURRIEL-JETON-REVOQUE" in page.text and page.headers["cache-control"] == "no-store"
    detail = client.get("/courriel/comptes/gmail-paul")
    assert detail.status_code == 200 and "Consentement (Loi 25)" in detail.text and "gmail.readonly" in detail.text
    api = client.get("/api/courriel/comptes/gmail-paul").json()
    assert api["etat"] == "reconnexion_requise" and api["derniere_erreur_code"] == "REJ-COURRIEL-JETON-REVOQUE"
    assert api["messages_total"] == 1 and any(j["evenement"] == "synchro" for j in api["journal"])
    for sortie in (page.text, detail.text, json.dumps(api), json.dumps(client.get("/api/courriel/comptes").json())):
        assert "QQQ" not in sortie and "RRR" not in sortie and acces not in sortie and "refresh-fictif" not in sortie
    assert client.get("/courriel/comptes/inconnu").status_code == 404
    assert client.get("/courriel/comptes/../x").status_code in {404, 422}
    assert client.get("/courriel/comptes/A%20B").status_code == 422


def test_la_console_refuse_un_non_administrateur_relu_en_base(monde):
    qa.creer_compte(monde)
    from opsys import identite

    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "employe", "Employé fictif", "mot-de-passe-employe-1234", ["employee"])
    client = _application(False)  # la session prétend « nathan_owner » ; la base dit « employee »
    for url in (
        "/courriel",
        "/api/courriel/comptes",
        "/courriel/comptes/gmail-paul",
        "/api/courriel/comptes/gmail-paul",
    ):
        assert client.get(url).status_code in {403, 500}, url


def test_la_page_est_aussi_sous_garde_de_session(monde):
    session = Session(utilisateur="nathan", roles=frozenset(), csrf="c" * 32, expire=0)

    def refuse(_request, **_):
        raise HTTPException(401, "session requise")

    app = FastAPI()
    app.include_router(
        courriel_ui.creer_router(session_page=refuse, session_api=refuse, cnx_factory=stockage.transaction, prefixe="")
    )
    assert TestClient(app).get("/courriel").status_code == 401 and session


def test_erreur_typee_et_reconnexion_visibles_via_le_service(monde):
    qa.creer_compte(monde, "gmail-paul")
    exc = ErreurCourriel("REJ-COURRIEL-LIMITE-DEBIT", "limite", 429, reprenable=True, reessayer_apres_s=60)
    monde.service.signaler_erreur("gmail-paul", exc)
    with stockage.transaction() as cnx:
        vue = comptes.lire(cnx, "gmail-paul")
    assert (
        vue["derniere_erreur_code"] == "REJ-COURRIEL-LIMITE-DEBIT" and vue["etat"] == "non_connecte"
    )  # pas de reconnexion pour un 429


def test_codes_d_erreur_hors_catalogue_impossibles():
    with pytest.raises(ValueError):
        ErreurCourriel("REJ-COURRIEL-INVENTE")
    assert (
        ErreurCourriel("REJ-COURRIEL-RESEAU", "jeton Bearer abcdefghijklmnop1234").detail
        == "jeton ••• abcdefghijklmnop1234"
        or "abcdefghijklmnop1234" not in ErreurCourriel("REJ-COURRIEL-RESEAU", "Bearer abcdefghijklmnop1234").detail
    )


def test_consentement_et_creation_exigent_l_administration(monde):
    from opsys import identite

    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "employe", "Employé fictif", "mot-de-passe-employe-1234", ["employee"])
        for appel in (
            lambda: comptes.creer_compte(
                cnx,
                "employe",
                compte_id="x1",
                fournisseur="gmail",
                adresse="a@example.test",
                usage="lecture",
                finalite="f",
                retention_jours=30,
            ),
            lambda: comptes.enregistrer_consentement(cnx, "employe", "x1"),
            lambda: comptes.creer_compte(
                cnx,
                "inconnu",
                compte_id="x1",
                fournisseur="gmail",
                adresse="a@example.test",
                usage="lecture",
                finalite="f",
                retention_jours=30,
            ),
        ):
            with pytest.raises(ErreurCourriel) as exc:
                appel()
            assert exc.value.code == "REJ-COURRIEL-ADMIN-REQUIS"


@pytest.mark.parametrize(
    "champs, code",
    [
        ({"compte_id": "A B"}, "REJ-COURRIEL-ARGUMENT-INVALIDE"),
        ({"compte_id": "x" * 65}, "REJ-COURRIEL-ARGUMENT-INVALIDE"),
        ({"fournisseur": "yahoo"}, "REJ-COURRIEL-FOURNISSEUR-INCONNU"),
        ({"adresse": "pas-une-adresse"}, "REJ-COURRIEL-ARGUMENT-INVALIDE"),
        ({"usage": "ecriture"}, "REJ-COURRIEL-ARGUMENT-INVALIDE"),
        ({"finalite": "  "}, "REJ-COURRIEL-ARGUMENT-INVALIDE"),
        ({"retention_jours": 0}, "REJ-COURRIEL-ARGUMENT-INVALIDE"),
        ({"retention_jours": 3651}, "REJ-COURRIEL-ARGUMENT-INVALIDE"),
        ({"retention_jours": "30"}, "REJ-COURRIEL-ARGUMENT-INVALIDE"),
        ({"configuration": {"mot_de_passe": "secret"}}, "REJ-COURRIEL-ARGUMENT-INVALIDE"),
        ({"configuration": {"client_secret": "x"}}, "REJ-COURRIEL-ARGUMENT-INVALIDE"),
        ({"dossiers_suivis": ()}, "REJ-COURRIEL-ARGUMENT-INVALIDE"),
        ({"dossiers_suivis": ("a\nb",)}, "REJ-COURRIEL-ARGUMENT-INVALIDE"),
    ],
)
def test_creation_de_compte_validee(monde, champs, code):
    base = dict(
        compte_id="x1",
        fournisseur="gmail",
        adresse="a@example.test",
        usage="lecture",
        finalite="Onboarding",
        retention_jours=30,
    )
    with pytest.raises(ErreurCourriel) as exc, stockage.transaction() as cnx:
        comptes.creer_compte(cnx, "nathan", **{**base, **champs})
    assert exc.value.code == code


def test_compte_en_double_et_etat_connecte_sans_consentement_impossible_en_base(monde):
    qa.creer_compte(monde, consentement=False)
    with pytest.raises(ErreurCourriel) as exc, stockage.transaction() as cnx:
        comptes.creer_compte(
            cnx,
            "nathan",
            compte_id="gmail-paul",
            fournisseur="gmail",
            adresse="a@example.test",
            usage="lecture",
            finalite="f",
            retention_jours=30,
        )
    assert exc.value.code == "REJ-COURRIEL-COMPTE-EXISTE"
    with pytest.raises(IntegrityError), stockage.transaction() as cnx:  # la contrainte de base protège aussi
        cnx.execute(comptes.COURRIEL_COMPTES.update().values(etat="connecte", secret_nom="courriel.x.g1"))
    with pytest.raises(ErreurCourriel) as exc, stockage.transaction() as cnx:
        comptes.marquer_connecte(
            cnx, "gmail-paul", "nathan", secret_nom="courriel.x.g1", generation=1, portees=frozenset()
        )
    assert exc.value.code == "REJ-COURRIEL-CONSENTEMENT-ABSENT"


# -- migration 0040 -------------------------------------------------------------------------------
def test_migration_0040_montee_descendue_et_refus_avec_donnees(tmp_path):
    from alembic.script import ScriptDirectory

    cfg = stockage._config()
    assert ScriptDirectory.from_config(cfg).get_heads() == ["0040"]
    url = "sqlite:///" + str(tmp_path / "m.db")
    with stockage.moteur(url).begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, "0040")
        noms = {r[0] for r in cnx.exec_driver_sql("SELECT name FROM sqlite_master WHERE name LIKE 'courriel_%'")}
        assert {
            "courriel_comptes",
            "courriel_etats_oauth",
            "courriel_messages",
            "courriel_refs",
            "courriel_brouillons",
            "courriel_journal",
            "courriel_journal_no_update",
            "courriel_journal_no_delete",
        } <= noms
        cnx.execute(
            text(
                "INSERT INTO fournisseurs_configurations (identifiant, capacite, definition, actif, revision, "
                "modifie_le, modifie_par) VALUES ('courriel.x', 'courriel', '{}', 0, 1, 't', 'p')"
            )
        )
        with pytest.raises(IntegrityError):
            cnx.execute(
                text(
                    "INSERT INTO fournisseurs_configurations (identifiant, capacite, definition, actif, revision, "
                    "modifie_le, modifie_par) VALUES ('inconnu.x', 'telepathie', '{}', 0, 1, 't', 'p')"
                )
            )
    with stockage.moteur(url).begin() as cnx:
        cfg.attributes["connection"] = cnx
        with pytest.raises(RuntimeError, match="fournisseur « courriel » est configuré"):
            command.downgrade(cfg, "0039")
    vide = "sqlite:///" + str(tmp_path / "vide.db")
    with stockage.moteur(vide).begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, "0040")
        command.downgrade(cfg, "0039")
        assert cnx.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "0039"
        command.upgrade(cfg, "0040")  # remontable
    noms = {
        r[0]
        for r in sqlite3.connect(str(tmp_path / "vide.db")).execute(
            "SELECT name FROM sqlite_master WHERE name LIKE 'courriel_%'"
        )
    }
    assert "courriel_comptes" in noms


def test_migration_0040_descente_refusee_avec_une_ligne_de_journal(tmp_path):
    cfg = stockage._config()
    url = "sqlite:///" + str(tmp_path / "j.db")
    with stockage.moteur(url).begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, "0040")
        cnx.execute(
            text(
                "INSERT INTO courriel_journal (quand, compte_id, evenement, acteur, details) "
                "VALUES ('t', 'c', 'e', 'a', '{}')"
            )
        )
        with pytest.raises(RuntimeError, match="rétrogradation refusée : courriel_journal"):
            command.downgrade(cfg, "0039")


def test_journal_append_only_sqlite(monde):
    qa.creer_compte(monde)
    for requete in ("UPDATE courriel_journal SET code = 'x'", "DELETE FROM courriel_journal"):
        with pytest.raises(DBAPIError, match="journal courriel immuable"), stockage.transaction() as cnx:
            cnx.execute(text(requete))


def _raison_sans_docker():
    try:
        from memoire.doubles import raison_sans_docker
    except ImportError as exc:  # pragma: no cover
        return str(exc)
    return raison_sans_docker()


@pytest.mark.skipif(_raison_sans_docker() is not None, reason=str(_raison_sans_docker()))
def test_migration_0040_sur_postgresql(monkeypatch, tmp_path):
    from memoire.doubles import postgres_ephemere

    with postgres_ephemere() as url_pg:
        url = url_pg.replace("postgresql://", "postgresql+psycopg://", 1)
        monkeypatch.setenv(stockage.ENV_URL, url)
        try:
            stockage.migrer(url)
            assert stockage.moteur(url).dialect.name == "postgresql" and stockage.revision_courante(url) == "0040"
            with stockage.transaction() as cnx:
                cnx.execute(
                    text(
                        "INSERT INTO courriel_journal (quand, compte_id, evenement, acteur, details) "
                        "VALUES ('t', 'c', 'e', 'a', '{}')"
                    )
                )
            for requete in ("UPDATE courriel_journal SET code = 'x'", "DELETE FROM courriel_journal"):
                with pytest.raises(DBAPIError, match="journal courriel immuable"), stockage.transaction() as cnx:
                    cnx.execute(text(requete))
            with stockage.transaction() as cnx:
                cnx.execute(
                    text(
                        "INSERT INTO fournisseurs_configurations (identifiant, capacite, definition, actif, revision, "
                        "modifie_le, modifie_par) VALUES ('courriel.x', 'courriel', '{}', false, 1, 't', 'p')"
                    )
                )
            with pytest.raises(DBAPIError), stockage.transaction() as cnx:
                cnx.execute(
                    text(
                        "INSERT INTO fournisseurs_configurations (identifiant, capacite, definition, actif, "
                        "revision, modifie_le, modifie_par) VALUES ('x.y', 'telepathie', '{}', false, 1, 't', 'p')"
                    )
                )
            cfg = stockage._config()
            with pytest.raises(RuntimeError, match="rétrogradation refusée"), stockage.moteur(url).begin() as cnx:
                cfg.attributes["connection"] = cnx
                command.downgrade(cfg, "0039")
        finally:
            stockage.liberer()


def test_l_application_reelle_sert_la_page_courriel_aux_administrateurs_seulement(monde):
    from opsys import identite
    from opsys.console import application
    from opsys.console.securite import Configuration
    from opsys.departements import charger_departements

    mot_de_passe = "mot-de-passe-console-courriel-fictif-2026"
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "proprio_fictif", "Propriétaire fictif", mot_de_passe, ["nathan_owner"])
        identite.creer_personne(cnx, "employe_fictif", "Employé fictif", mot_de_passe, ["employee"])
    qa.creer_compte(monde)
    app = application.creer_application(
        Configuration("secret-session-courriel-fictif-" + "x" * 32), charger_departements(), stockage.transaction)
    with TestClient(app, base_url="https://testserver/opsys") as client:
        assert client.get("/courriel", follow_redirects=False).status_code in {303, 401, 403}  # sans session
        reponse = client.post("/connexion", data={"identifiant": "proprio_fictif", "mot_de_passe": mot_de_passe},
                              follow_redirects=False)
        assert reponse.status_code == 303
        page = client.get("/courriel")
        assert page.status_code == 200 and "gmail-paul" in page.text
        assert client.get("/api/courriel/comptes").json()["comptes"][0]["compte_id"] == "gmail-paul"
    with TestClient(app, base_url="https://testserver/opsys") as client:
        client.post("/connexion", data={"identifiant": "employe_fictif", "mot_de_passe": mot_de_passe},
                    follow_redirects=False)
        assert client.get("/courriel", follow_redirects=False).status_code in {303, 401, 403}
        assert client.get("/api/courriel/comptes").status_code in {401, 403}
