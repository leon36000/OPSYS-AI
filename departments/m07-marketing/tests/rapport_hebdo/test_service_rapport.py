"""Un rapport par semaine : persistance, tâches, observations annoncées dans la même transaction (M7-RAPPORT-HEBDO)."""

from __future__ import annotations

import copy
import json

import pytest
from m7_marketing import outils, rapport_outils
from m7_marketing.rapport_hebdo import memoire, service
from sqlalchemy import func, select

from opsys import contexte, evenements, stockage
from opsys.outils import executer_atomique
from opsys.stockage.schema import EVENEMENTS_SORTANTS

FICTIF = True
LUNDI = "2026-10-26"
INSTANT = "2026-11-02T08:00:00-05:00"


@pytest.fixture
def base(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'r.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home"))
    stockage.migrer(url)
    yield url
    stockage.liberer()


def constater(entrees, debut=LUNDI, instant=INSTANT):
    with stockage.transaction():
        return service.constater(entrees, debut, instant)


def compte(nom):
    with stockage.transaction():
        return len(list(stockage.maillons("m07-marketing", nom)))


def sortants():
    with stockage.transaction() as cnx:
        return cnx.execute(
            select(func.count())
            .select_from(EVENEMENTS_SORTANTS)
            .where(EVENEMENTS_SORTANTS.c.type_evenement == memoire.TYPE_EVENEMENT)
        ).scalar_one()


def test_le_rapport_ses_taches_et_ses_observations_sont_ecrits_ensemble(base, entrees):
    r = constater(entrees)
    assert r["statut"] == "enregistre" and r["semaine"] == LUNDI
    assert r["taches"] == 5 and r["observations_annoncees"] == 6
    assert compte("rapports_hebdomadaires") == 1 and compte("taches_marketing") == 5 and sortants() == 6


def test_le_rapport_est_idempotent_par_semaine(base, entrees):
    premier = constater(entrees)
    second = constater(entrees, instant="2026-11-03T08:00:00-05:00")
    assert second == {"statut": "deja_present", "semaine": LUNDI, "empreinte": premier["empreinte"]}
    assert compte("rapports_hebdomadaires") == 1 and compte("taches_marketing") == 5 and sortants() == 6


def test_le_premier_rapport_de_la_semaine_fait_foi_meme_si_les_entrees_changent(base, entrees):
    premier = constater(entrees)
    autre = copy.deepcopy(entrees)
    autre["performance"] = {"campagnes": []}
    assert constater(autre)["empreinte"] == premier["empreinte"]
    assert compte("rapports_hebdomadaires") == 1


def test_une_autre_semaine_est_un_autre_rapport_et_les_taches_ne_survivent_pas(base, entrees):
    constater(entrees)
    avant = {t["tache_id"] for t in _taches()}
    r2 = constater(entrees, debut="2026-11-02", instant="2026-11-09T08:00:00-05:00")
    assert r2["statut"] == "enregistre" and compte("rapports_hebdomadaires") == 2
    apres = _taches()
    assert {t["semaine"] for t in apres} == {"2026-11-02"} and not avant & {t["tache_id"] for t in apres}


def _taches():
    with stockage.transaction():
        return service.taches_courantes()


def test_les_taches_sont_internes_de_niveau_bas_et_apparaissent_dans_a_voir(base, entrees):
    constater(entrees)
    taches = _taches()
    assert len(taches) == 5 and all(t["niveau"] == "N1" for t in taches)
    assert [t["priorite"] for t in taches] == sorted((t["priorite"] for t in taches), reverse=True)
    with stockage.transaction():
        attentes = outils.attentes()
    mes = [a for a in attentes if a["type"] == "tache_marketing"]
    assert len(mes) == 5 and all(a["niveau"] == "N1" and "rien ne s'exécute seul" in a["action_proposee"] for a in mes)
    assert {a["id"] for a in mes} == {t["tache_id"] for t in taches}
    assert set(mes[0]) == {"type", "id", "resume", "niveau", "depuis", "action_proposee"}


def test_une_semaine_invalide_est_refusee_sans_rien_ecrire(base, entrees):
    r = constater(entrees, debut="2026-10-27")
    assert r["statut"] == "refuse" and r["code"] == "REJ-RAPPORT-SEMAINE-INVALIDE"
    assert compte("rapports_hebdomadaires") == 0 and sortants() == 0


def test_la_panne_d_une_annonce_annule_tout_le_rapport(base, entrees, monkeypatch):
    def echec(*a, **k):
        raise ConnectionError("bus indisponible")

    with monkeypatch.context() as m:
        m.setattr(evenements, "publier", echec)
        with pytest.raises(ConnectionError):
            constater(entrees)
    assert compte("rapports_hebdomadaires") == 0 and compte("taches_marketing") == 0  # rien de demi-écrit
    assert constater(entrees)["statut"] == "enregistre"  # la reprise écrit une fois


def test_un_rapport_hors_borne_est_refuse(base, entrees, monkeypatch):
    monkeypatch.setattr(service, "RAPPORT_MAX_OCTETS", 500)
    r = constater(entrees)
    assert r["statut"] == "refuse" and r["code"] == "REJ-RAPPORT-TROP-GROS" and compte("rapports_hebdomadaires") == 0


def test_aucun_effet_externe_le_seul_evenement_publie_est_l_apprentissage(base, entrees):
    constater(entrees)
    with stockage.transaction() as cnx:
        types = {t for (t,) in cnx.execute(select(EVENEMENTS_SORTANTS.c.type_evenement).distinct())}
    assert types == {memoire.TYPE_EVENEMENT}  # ni publication, ni courriel, ni dépense


def test_le_rapport_ranger_ne_contient_aucun_texte_de_client(base, entrees):
    constater(entrees)
    with stockage.transaction():
        lu = service.lire()
    texte = json.dumps(lu, ensure_ascii=False)
    assert lu["statut"] == "rapport" and "@" not in texte and "jean" not in texte


# -- l'outil de lecture -----------------------------------------------------------------------------------------------
def appeler(nom="m7_lire_rapport_hebdomadaire", appareil=None, **arguments):
    outil = next(o for o in outils.outils() if o.nom == nom)
    if appareil is None:
        return executer_atomique(outil, arguments)
    with contexte.appele_par_appareil(contexte.IdentiteAppelante(*appareil)):
        return executer_atomique(outil, arguments)


def test_lire_sans_rapport_le_dit_sans_rien_inventer(base):
    r = appeler()["resultat"]
    assert r["statut"] == "aucun_rapport" and "n'invente" in r["lecture"] or "Rien n'est inventé" in r["lecture"]


def test_lire_donne_une_vue_bornee_priorisee_et_sourcee(base, entrees):
    constater(entrees)
    r = appeler()["resultat"]
    assert (
        r["statut"] == "rapport" and r["semaine"]["debut"] == LUNDI and len(json.dumps(r, ensure_ascii=False)) <= 6000
    )
    assert r["recommandations"] and all(x["sources"] or x["hypothese"] for x in r["recommandations"])
    assert [x["priorite"] for x in r["recommandations"]] == sorted(
        (x["priorite"] for x in r["recommandations"]), reverse=True
    )
    assert r["synthese"]["roi"] == "donnees_insuffisantes"
    section = appeler(section="contenus")["resultat"]
    assert section["statut"] == "section" and section["contenu"]["meilleurs"]
    assert appeler(semaine="2025-01-06")["resultat"]["statut"] == "aucun_rapport"
    assert appeler(section="inconnue")["ok"] is False


def test_lire_par_un_appareil_non_admin_est_refuse(base, entrees):
    with stockage.transaction() as cnx:
        from opsys import identite

        identite.creer_personne(cnx, "etienne", "Étienne fictif", "mot-de-passe-de-test-1234", ["employee"])
    constater(entrees)
    r = appeler(appareil=("etienne", "employee"))
    assert r["ok"] is True and r["resultat"]["accepte"] is False
    assert r["resultat"]["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"


def test_la_vue_retire_des_recommandations_entieres_si_elle_depasse_la_borne(base, entrees, monkeypatch):
    constater(entrees)
    monkeypatch.setattr(rapport_outils, "BUDGET_SORTIE", 1800)
    r = appeler()["resultat"]
    assert r["recommandations_omises"] > 0 and len(r["recommandations"]) + r["recommandations_omises"] == 12
