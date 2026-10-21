"""Idempotence des mutations d'appareil (T1.4-b). Contrat : docs/architecture/IDEMPOTENCE.md."""

from __future__ import annotations

import datetime as dt
import json
import threading

import anyio
import demo_outils
import pytest
from mcp import Client
from memoire.doubles import postgres_ephemere, raison_sans_docker
from sqlalchemy import select

from opsys import approbations, contexte, idempotence, stockage
from opsys.capacites import Capacites
from opsys.serveur_mcp import creer_serveur
from opsys.stockage.schema import MUTATIONS_APPLIQUEES

FICTIF = True  # tout appareil/identifiant ci-dessous est fictif (AGENTS.md)


def _meta(cle: str = "mut-1", appareil: str = "appareil-fictif-1",
         horodatage: str = "2026-09-28T10:15:00-04:00") -> idempotence.Meta:
    return idempotence.Meta(cle=cle, appareil=appareil, horodatage_appareil=horodatage)


@pytest.fixture
def capacites(departements_demo, session):
    demo_outils.JOURNAL.clear()
    demo_outils.COMPTEUR_PANNE.clear()
    demo_outils.HORODATAGES_VUS.clear()
    return Capacites(departements_demo, session, limite_sortie=800)


def _lignes(session) -> list[dict]:
    with session() as cnx:
        return [dict(r) for r in cnx.execute(select(MUTATIONS_APPLIQUEES)).mappings().all()]


# -- contrat pur : depuis_meta_mcp, empreinte_arguments -----------------------------------------
def test_depuis_meta_mcp_sans_cle_rend_none():
    assert idempotence.depuis_meta_mcp(None) is None
    assert idempotence.depuis_meta_mcp({}) is None
    assert idempotence.depuis_meta_mcp({"progress_token": "x"}) is None


def test_depuis_meta_mcp_exige_appareil_et_horodatage_avec_fuseau():
    with pytest.raises(ValueError, match="opsys/appareil"):
        idempotence.depuis_meta_mcp({"opsys/idempotencyKey": "k"})
    with pytest.raises(ValueError, match="RFC 3339"):
        idempotence.depuis_meta_mcp({
            "opsys/idempotencyKey": "k", "opsys/appareil": "a",
            "opsys/horodatageAppareil": "2026-09-28T10:00:00",  # pas de fuseau
        })
    with pytest.raises(ValueError, match="RFC 3339"):
        idempotence.depuis_meta_mcp({
            "opsys/idempotencyKey": "k", "opsys/appareil": "a",
            "opsys/horodatageAppareil": "n'importe quoi",
        })


def test_depuis_meta_mcp_valide():
    meta = idempotence.depuis_meta_mcp({
        "opsys/idempotencyKey": "mut-42", "opsys/appareil": "tel-9",
        "opsys/horodatageAppareil": "2026-09-28T10:15:00-04:00",
    })
    assert meta == idempotence.Meta("mut-42", "tel-9", "2026-09-28T10:15:00-04:00")


def test_empreinte_arguments_ignore_l_ordre_des_cles():
    a = idempotence.empreinte_arguments({"a": 1, "b": {"x": 1, "y": 2}})
    b = idempotence.empreinte_arguments({"b": {"y": 2, "x": 1}, "a": 1})
    assert a == b
    assert a != idempotence.empreinte_arguments({"a": 1, "b": {"x": 1, "y": 3}})


# -- renvoi après réponse perdue : même réponse, une seule écriture métier ----------------------
def test_renvoi_rejoue_la_meme_reponse_sans_reexecuter(capacites, session):
    meta = _meta(cle="mut-renvoi")
    premiere = capacites.appeler("m9_pointer", {"appareil": "cam-12"}, meta)
    assert premiere["ok"] is True and premiere["rejoue"] is False
    assert premiere["resultat"] == {"pointe": True, "appareil": "cam-12"}
    assert demo_outils.JOURNAL == [{"pointage": "cam-12"}]

    renvoi = capacites.appeler("m9_pointer", {"appareil": "cam-12"}, meta)
    assert renvoi["rejoue"] is True
    assert renvoi["ok"] is True and renvoi["resultat"] == premiere["resultat"]
    assert demo_outils.JOURNAL == [{"pointage": "cam-12"}]  # une seule écriture métier, pas deux

    lignes = _lignes(session)
    assert len(lignes) == 1
    assert lignes[0]["appareil"] == "appareil-fictif-1" and lignes[0]["cle_idempotence"] == "mut-renvoi"
    assert lignes[0]["outil"] == "m9_pointer" and lignes[0]["statut"] == "ok"


def test_renvoi_apres_refus_metier_rejoue_le_refus(capacites, session):
    meta = _meta(cle="mut-refus")
    premiere = capacites.appeler("m9_refuser_si_negatif", {"valeur": -1}, meta)
    assert premiere["ok"] is False and premiere["erreur"] == "refus_metier" and premiere["rejoue"] is False
    renvoi = capacites.appeler("m9_refuser_si_negatif", {"valeur": -1}, meta)
    assert renvoi["rejoue"] is True and renvoi["erreur"] == "refus_metier"
    assert _lignes(session)[0]["statut"] == "refus_metier"


# -- refus passagers et budget de jetons ----------------------------------------------------------
def test_refus_passager_n_est_pas_enregistre_et_se_reessaie(capacites, session):
    """`outil_inconnu` dépend de l'état de l'instance (ex. mise à jour en cours), pas de la mutation :
    le renvoi doit réessayer, jamais rejouer un refus figé sous la même clé."""
    meta = _meta(cle="mut-outil-absent")
    premiere = capacites.appeler("m9_outil_absent", {}, meta)
    assert premiere["ok"] is False and premiere["erreur"] == "outil_inconnu"
    assert _lignes(session) == []
    renvoi = capacites.appeler("m9_outil_absent", {}, meta)
    assert renvoi["erreur"] == "outil_inconnu" and renvoi["rejoue"] is False
    assert _lignes(session) == []


def test_appel_d_appareil_n_est_pas_bloque_par_le_budget_de_jetons_du_modele(capacites, session):
    """Le budget de jetons borne la dépense de modèle d'un département ; un pointage d'appareil n'en
    consomme aucun et ne doit pas être refusé pour autant. L'appel d'agent, lui, reste borné."""
    from opsys import jetons

    with session() as cnx:
        jetons.enregistrer_usage(cnx, "m09-demo", "modele-fictif", {"input_tokens": 10_000_000})
    sans_meta = capacites.appeler("m9_pointer", {"appareil": "cam-7"})
    assert sans_meta["ok"] is False and sans_meta["erreur"] == "budget_epuise"

    avec_meta = capacites.appeler("m9_pointer", {"appareil": "cam-7"}, _meta(cle="mut-budget"))
    assert avec_meta["ok"] is True and avec_meta["rejoue"] is False
    assert demo_outils.JOURNAL == [{"pointage": "cam-7"}]


# -- conflit : même clé, outil ou arguments différents -------------------------------------------
def test_meme_cle_outil_different_est_un_conflit_nomme(capacites):
    meta = _meta(cle="mut-conflit-outil")
    capacites.appeler("m9_pointer", {"appareil": "cam-1"}, meta)
    conflit = capacites.appeler("m9_additionner", {"a": 1, "b": 2}, meta)
    assert conflit == {"ok": False, "erreur": "mutation_conflit", "details": conflit["details"]}
    assert demo_outils.JOURNAL == [{"pointage": "cam-1"}]  # rien exécuté pour le second appel


def test_memes_cle_et_outil_arguments_differents_est_un_conflit_nomme(capacites):
    meta = _meta(cle="mut-conflit-args")
    capacites.appeler("m9_pointer", {"appareil": "cam-1"}, meta)
    conflit = capacites.appeler("m9_pointer", {"appareil": "cam-2"}, meta)
    assert conflit["ok"] is False and conflit["erreur"] == "mutation_conflit"
    assert demo_outils.JOURNAL == [{"pointage": "cam-1"}]


# -- approbation jamais dupliquée ----------------------------------------------------------------
def test_renvoi_ne_duplique_pas_la_demande_d_approbation(capacites, session):
    meta = _meta(cle="mut-approbation")
    premiere = capacites.appeler("m9_payer", {"montant": 100}, meta)
    assert premiere["ok"] is True and premiere["statut"] == "en_attente_approbation"
    assert premiere["rejoue"] is False
    demande_id = premiere["demande_id"]

    renvoi = capacites.appeler("m9_payer", {"montant": 100}, meta)
    assert renvoi["rejoue"] is True
    assert renvoi["statut"] == "en_attente_approbation" and renvoi["demande_id"] == demande_id

    with session() as cnx:
        assert len(approbations.lister(cnx)) == 1  # une seule demande, malgré les deux appels
    assert demo_outils.JOURNAL == []  # rien exécuté : ni au premier appel, ni au renvoi
    assert _lignes(session)[0]["statut"] == "en_attente_approbation"


# -- panne interne jamais enregistrée -------------------------------------------------------------
def test_panne_interne_non_enregistree_puis_reussite_au_renvoi(capacites, session):
    meta = _meta(cle="mut-panne")
    with pytest.raises(RuntimeError, match="panne interne simulée"):
        capacites.appeler("m9_echouer_puis_reussir", {"cle": "x"}, meta)
    assert _lignes(session) == []  # la réclamation a été annulée avec toute la transaction

    renvoi = capacites.appeler("m9_echouer_puis_reussir", {"cle": "x"}, meta)
    assert renvoi["ok"] is True and renvoi["resultat"] == {"tentative": 2} and renvoi["rejoue"] is False
    assert len(_lignes(session)) == 1


# -- concurrence : deux fils, même clé → une seule exécution --------------------------------------
def test_reclamation_concurrente_une_seule_execution(capacites):
    meta = _meta(cle="mut-concurrence")
    barriere = threading.Barrier(2)
    reponses: list[dict] = []
    verrou = threading.Lock()

    def appeler() -> None:
        barriere.wait(timeout=5)
        reponse = capacites.appeler("m9_pointer", {"appareil": "cam-9"}, meta)
        with verrou:
            reponses.append(reponse)

    fils = [threading.Thread(target=appeler) for _ in range(2)]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(timeout=10)

    assert len(reponses) == 2
    assert demo_outils.JOURNAL == [{"pointage": "cam-9"}]  # une seule exécution malgré 2 appels
    assert sorted(r["rejoue"] for r in reponses) == [False, True]
    for reponse in reponses:
        assert reponse["ok"] is True and reponse["resultat"] == {"pointe": True, "appareil": "cam-9"}


# -- heure de réception exposée à l'outil pendant l'appel -----------------------------------------
def test_horodatage_reception_expose_pendant_l_appel_et_efface_apres(capacites):
    meta = _meta(cle="mut-horodatage", appareil="appareil-9", horodatage="2026-09-28T08:00:00-04:00")
    avant = dt.datetime.now(dt.UTC)
    reponse = capacites.appeler("m9_voir_horodatage", {}, meta)
    apres = dt.datetime.now(dt.UTC)

    assert reponse["ok"] is True
    assert contexte.horodatage_reception() is None  # nettoyé après l'appel (pas de fuite de contexte)
    assert len(demo_outils.HORODATAGES_VUS) == 1
    vu = demo_outils.HORODATAGES_VUS[0]
    assert vu is not None
    assert vu.appareil == "appareil-9"
    assert vu.horodatage_appareil == dt.datetime.fromisoformat("2026-09-28T08:00:00-04:00")
    assert avant <= vu.recu_le <= apres  # l'heure SERVEUR, pas celle (dérivable) de l'appareil


# -- sans _meta : comportement strictement inchangé ------------------------------------------------
def test_sans_meta_comportement_inchange(capacites, session):
    r1 = capacites.appeler("m9_pointer", {"appareil": "cam-7"})
    r2 = capacites.appeler("m9_pointer", {"appareil": "cam-7"}, None)
    assert "rejoue" not in r1 and "rejoue" not in r2
    assert demo_outils.JOURNAL == [{"pointage": "cam-7"}, {"pointage": "cam-7"}]  # exécuté 2 fois
    assert _lignes(session) == []  # aucune table d'idempotence touchée
    assert contexte.horodatage_reception() is None


# -- appel MCP de bout en bout avec _meta -----------------------------------------------------------
def test_appel_mcp_bout_en_bout_avec_meta(departements_demo, session):
    demo_outils.JOURNAL.clear()
    serveur = creer_serveur(Capacites(departements_demo, session))
    meta_mcp = {
        "opsys/idempotencyKey": "mut-mcp-1",
        "opsys/appareil": "telephone-fictif-1",
        "opsys/horodatageAppareil": "2026-09-28T10:15:00-04:00",
    }

    async def scenario() -> None:
        async with Client(serveur) as client:
            premier = await client.call_tool("m9_pointer", {"appareil": "cam-3"}, meta=meta_mcp)
            donnees1 = json.loads(premier.content[0].text)
            assert premier.is_error is False
            assert donnees1["ok"] is True and donnees1["rejoue"] is False

            renvoi = await client.call_tool("m9_pointer", {"appareil": "cam-3"}, meta=meta_mcp)
            donnees2 = json.loads(renvoi.content[0].text)
            assert donnees2["rejoue"] is True and donnees2["resultat"] == donnees1["resultat"]

            conflit = await client.call_tool("m9_additionner", {"a": 1, "b": 2}, meta=meta_mcp)
            donnees3 = json.loads(conflit.content[0].text)
            assert conflit.is_error is True and donnees3["erreur"] == "mutation_conflit"

    anyio.run(scenario)
    assert demo_outils.JOURNAL == [{"pointage": "cam-3"}]  # une seule exécution malgré 3 appels MCP


def test_appel_mcp_meta_invalide_est_un_refus_propre(departements_demo, session):
    serveur = creer_serveur(Capacites(departements_demo, session))
    meta_mcp = {"opsys/idempotencyKey": "mut-mcp-invalide"}  # opsys/appareil manquant

    async def scenario() -> dict:
        async with Client(serveur) as client:
            resultat = await client.call_tool("m9_additionner", {"a": 1, "b": 2}, meta=meta_mcp)
            assert resultat.is_error is True
            return json.loads(resultat.content[0].text)

    donnees = anyio.run(scenario)
    assert donnees["erreur"] == "meta_invalide"


# -- PostgreSQL en option : même comportement (reprend le mécanisme de test_stockage.py) -----------
@pytest.mark.skipif(raison_sans_docker() is not None, reason=str(raison_sans_docker()))
def test_postgresql_reclamation_et_renvoi(monkeypatch, departements_demo):
    with postgres_ephemere() as url_pg:
        url = url_pg.replace("postgresql://", "postgresql+psycopg://", 1)
        monkeypatch.setenv(stockage.ENV_URL, url)
        try:
            stockage.migrer(url)
            demo_outils.JOURNAL.clear()
            cap = Capacites(departements_demo, stockage.transaction, limite_sortie=800)
            meta = _meta(cle="mut-pg")

            premiere = cap.appeler("m9_pointer", {"appareil": "cam-pg"}, meta)
            assert premiere["ok"] is True and premiere["rejoue"] is False
            renvoi = cap.appeler("m9_pointer", {"appareil": "cam-pg"}, meta)
            assert renvoi["rejoue"] is True
            assert demo_outils.JOURNAL == [{"pointage": "cam-pg"}]

            conflit = cap.appeler("m9_additionner", {"a": 1, "b": 2}, meta)
            assert conflit["erreur"] == "mutation_conflit"
        finally:
            stockage.liberer()
