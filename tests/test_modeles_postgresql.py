"""Rôles de modèles sur un VRAI PostgreSQL 17 éphémère (Docker ; ignoré avec la raison exacte sinon).

Prouve : la migration 0086 (tables, journal immuable par déclencheur PostgreSQL, descente refusée avec données), puis le
parcours service → affectation → appel routé → plafond → repli → raisonnement → retour arrière avec un faux serveur
compatible OpenAI. Données fictives. Ne prouve PAS la charge, la concurrence ni la restauration.
"""

from __future__ import annotations

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from faux_litellm import CLE_FICTIVE, FauxLiteLLM
from modeles_aide import ALIAS, AMONT, CLE_AMONT, MOT_DE_PASSE, PROPRIETAIRE
from pg_parite import base_pg, serveur_pg  # noqa: F401  (fixtures pytest)
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from opsys import identite, stockage
from opsys.fournisseurs import registre
from opsys.roles_modeles import appel, decouverte, passerelle_fournisseur, service
from opsys.roles_modeles.appel import Escalade
from opsys.secrets_coffre import coffre

FICTIF = True
MESSAGES = [{"role": "user", "content": "x"}]


def test_0086_sur_postgresql_tables_declencheur_et_descente(serveur_pg):  # noqa: F811
    nom, url = serveur_pg.nouvelle_base(depuis_gabarit=False)
    try:
        cfg = stockage._config()
        with stockage.moteur(url).begin() as cnx:
            cfg.attributes["connection"] = cnx
            command.upgrade(cfg, "0086")
            tables = {r[0] for r in cnx.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'"))}
            assert {"modeles_roles", "modeles_reglages", "modeles_historique", "modeles_usage"} <= tables
            assert ScriptDirectory.from_config(cfg).get_revision("0086").down_revision == "0058"
            cnx.execute(text("INSERT INTO modeles_historique (quand, cible, action, acteur, niveau) "
                             "VALUES ('t', 'passerelle', 'x', 'a', 'N3')"))
        for instruction in ("UPDATE modeles_historique SET acteur = 'b'", "DELETE FROM modeles_historique"):
            with pytest.raises(DBAPIError, match="immuable"), stockage.moteur(url).begin() as cnx:
                cnx.execute(text(instruction))
        with pytest.raises(Exception, match="rétrogradation refusée"), stockage.moteur(url).begin() as cnx:
            cfg.attributes["connection"] = cnx
            command.downgrade(cfg, "0058")
    finally:
        stockage.liberer(url)
        serveur_pg.supprimer(nom)


def test_0086_descente_a_vide_puis_remontee_sur_postgresql(serveur_pg):  # noqa: F811
    nom, url = serveur_pg.nouvelle_base(depuis_gabarit=False)
    try:
        cfg = stockage._config()
        with stockage.moteur(url).begin() as cnx:
            cfg.attributes["connection"] = cnx
            command.upgrade(cfg, "0086")
            command.downgrade(cfg, "0058")
            assert not {r[0] for r in cnx.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'"))
                        } & {"modeles_roles", "modeles_historique"}
            assert not cnx.execute(text("SELECT 1 FROM pg_proc WHERE proname = 'modeles_historique_immuable'")).first()
            command.upgrade(cfg, "0086")
    finally:
        stockage.liberer(url)
        serveur_pg.supprimer(nom)


def test_parcours_complet_sur_postgresql(base_pg, tmp_path, monkeypatch):  # noqa: F811
    from opsys.secrets_coffre import cle_maitresse

    dossier = tmp_path / "cles"
    dossier.mkdir(mode=0o700)
    cle_maitresse.generer_fichier(dossier / "coffre.cle")
    monkeypatch.setenv(cle_maitresse.ENV_FICHIER, str(dossier / "coffre.cle"))

    def fabrique():
        return stockage.transaction(base_pg)

    with FauxLiteLLM() as faux:
        with fabrique() as cnx:
            identite.creer_personne(cnx, PROPRIETAIRE, "Propriétaire fictif", MOT_DE_PASSE, ["nathan_owner"])
            registre.declarer_profil(cnx, acteur=PROPRIETAIRE, usage_commercial=True, revenu_annuel_usd=500_000,
                                     territoires=["CA"], heberge_pour_tiers=False, revision_attendue=0)
            coffre.definir(cnx, acteur=PROPRIETAIRE, nom="passerelle.cle", service="fournisseur_modele",
                           valeur=CLE_FICTIVE)
            coffre.definir(cnx, acteur=PROPRIETAIRE, nom="passerelle.openrouter", service="fournisseur_modele",
                           valeur=CLE_AMONT)
            service.appliquer(cnx, acteur=PROPRIETAIRE, operation=service.OP_PASSERELLE_CONFIGURER,
                              niveau_confirme="N3", parametres={
                                  "mode": "integree", "url_base": faux.url, "secret_cle": "passerelle.cle",
                                  "secrets_amont": {"openrouter": "passerelle.openrouter"}})
        assert decouverte.decouvrir(fabrique, acteur=PROPRIETAIRE)["statut"] == "succes"
        for role in ("llm_rapide", "llm_raisonnement"):
            with fabrique() as cnx:
                d = passerelle_fournisseur.declarer(cnx, acteur=PROPRIETAIRE, role=role, alias=ALIAS[role],
                                                    secret_cle="passerelle.cle", efvp_ref="EFVP-1", contrat_ref="C-1")
                assert d["active"]
                service.appliquer(cnx, acteur=PROPRIETAIRE, operation=service.OP_ROLE_AFFECTER, niveau_confirme="N3",
                                  parametres={"role": role, "fournisseur_id": d["identifiant"],
                                              "modele_appel": ALIAS[role], "amont": AMONT[role]})
        assert appel.tester_role(fabrique, acteur=PROPRIETAIRE, role="llm_rapide")["statut"] == "succes"
        r = appel.completer(fabrique, classe="classification", messages=MESSAGES, max_tokens=8)
        assert r["modele"] == "opsys-haiku-5-5" and r["usage"]["cout_micro_usd"] == 22  # coût lu du catalogue
        with fabrique() as cnx:
            service.appliquer(cnx, acteur=PROPRIETAIRE, operation=service.OP_ROLE_PLAFONDS,
                              parametres={"role": "llm_rapide", "plafond_jetons_jour": 20})
            assert service.usage(cnx, "llm_rapide")["appels"] == 2
        with pytest.raises(Exception, match="PLAFOND-ATTEINT"):
            appel.completer(fabrique, classe="classification", messages=MESSAGES, max_tokens=8)
        demande = Escalade(PROPRIETAIRE, "Analyse contractuelle complexe du dossier fictif")
        with pytest.raises(Exception, match="RAISONNEMENT-INACTIF"):
            appel.completer(fabrique, classe="escalade_raisonnement", messages=MESSAGES, escalade=demande)
        with fabrique() as cnx:
            service.appliquer(cnx, acteur=PROPRIETAIRE, operation=service.OP_RAISONNEMENT_ACTIVER,
                              niveau_confirme="N3", parametres={}, motif="Analyse contractuelle complexe du dossier")
        assert appel.completer(fabrique, classe="escalade_raisonnement", messages=MESSAGES, max_tokens=8,
                               escalade=demande)["modele"] == "opsys-opus-5-5"
        with fabrique() as cnx:
            service.appliquer(cnx, acteur=PROPRIETAIRE, operation=service.OP_REVENIR, niveau_confirme="N3",
                              parametres={"cible": "raisonnement"})
            assert service.raisonnement_actif(cnx) is False
            histo = service.historique(cnx, "raisonnement")
            assert [h["action"] for h in histo] == ["revenir", "raisonnement.activer"]
            valeurs = "".join(str(list(ligne)) for t in ("journal", "modeles_historique", "modeles_reglages",
                                                         "modeles_roles", "coffre_acces")
                              for ligne in cnx.execute(text(f"SELECT * FROM {t}")))
            assert CLE_FICTIVE not in valeurs and CLE_AMONT not in valeurs
