"""Réglages de direction (CFG-1) : le magasin, la lecture et le geste de la console sur SQLite ET sur un vrai
PostgreSQL 17 éphémère (ignorés avec la raison exacte sans Docker, jamais un faux vert).

Prouve sur les deux moteurs : une adoption écrit un maillon chaîné et se relit ; l'idempotence ; le retour arrière ;
la chaîne falsifiée n'est plus servie ; une base sans le registre ne casse pas la transaction (point de sauvegarde) ;
une écriture concurrente au même rang est refusée ; le geste complet de la console passe par le sas (verrou
d'écriture de console compris). Données fictives, aucun réseau.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pg_parite import base_pg, serveur_pg, url_base  # noqa: F401  (fixtures pytest)
from sqlalchemy import select, text, update

from opsys import identite, stockage
from opsys.console import application
from opsys.console.securite import Configuration
from opsys.departements import charger_departements
from opsys.reglages import lecture, magasin
from opsys.reglages.declaration import ReglageRefuse
from opsys.stockage.schema import REGISTRES

_spec = importlib.util.spec_from_file_location("reglages_aide", Path(__file__).with_name("reglages_aide.py"))
aide = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(aide)

FICTIF = True
QUAND = "2026-11-02T15:00:00+00:00"
CLE = "m2.jours_entre_relances"


@pytest.fixture
def instance(url_base, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv(stockage.ENV_URL, url_base)
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home"))
    stockage.liberer(url_base)
    with stockage.transaction(url_base) as cnx:
        identite.creer_personne(cnx, aide.PROPRIETAIRE, "Propriétaire fictif", aide.MOT_DE_PASSE,
                                ["nathan_owner", "admin"])
    yield url_base, charger_departements()
    stockage.liberer(url_base)


def _reglage(deps, cle=CLE):
    return next(r for d in deps.values() for r in d.reglages if r.cle == cle)


def _gestes(deps, url):
    with stockage.transaction(url) as cnx:
        reglage = _reglage(deps)
        parametres = {"par": aide.PROPRIETAIRE, "role": "nathan_owner", "approbation_id": "d1",
                      "raison": "Décision de départ", "quand": QUAND}
        premier = magasin.adopter(cnx, reglage, 7, **parametres)
        idempotent = magasin.adopter(cnx, reglage, 7, **parametres)
        second = magasin.adopter(cnx, reglage, 10, **parametres)
        retour = magasin.revenir(cnx, reglage, **parametres)
        return premier, idempotent, second, retour


def test_adoption_idempotence_et_retour_arriere_sur_les_deux_moteurs(instance):
    url, deps = instance
    premier, idempotent, second, retour = _gestes(deps, url)
    assert (premier["statut"], idempotent["statut"]) == ("adopte", "deja_adopte")
    assert (second["version"], retour["valeur"]) == (2, 7)
    with stockage.transaction(url):
        chaine = magasin.lire_chaine()
        assert [m["type"] for m in chaine] == ["adoption", "adoption", "retour_arriere"]
        assert magasin.valeur_en_vigueur(magasin.rejouer(chaine), CLE) == 7
        assert lecture.adoptees().valeurs == {CLE: 7}


def test_la_chaine_falsifiee_n_est_plus_servie_sur_les_deux_moteurs(instance):
    url, deps = instance
    _gestes(deps, url)
    with stockage.transaction(url) as cnx:
        ligne = cnx.execute(select(REGISTRES.c.maillon).where(
            (REGISTRES.c.departement == magasin.DEPARTEMENT_STOCKAGE) & (REGISTRES.c.rang == 0))).scalar_one()
        maillon = json.loads(ligne)
        maillon["raison"] = "falsifiée"
        cnx.execute(update(REGISTRES).where(
            (REGISTRES.c.departement == magasin.DEPARTEMENT_STOCKAGE) & (REGISTRES.c.rang == 0)
        ).values(maillon=json.dumps(maillon, ensure_ascii=False, separators=(",", ":"))))
        lues = lecture.adoptees()
        assert lues.chaine_valide is False and lues.valeurs == {}
        with pytest.raises(ReglageRefuse) as exc:
            magasin.adopter(cnx, _reglage(deps), 14, par="p", role="nathan_owner", approbation_id="d2",
                            raison="Après falsification", quand=QUAND)
        assert exc.value.code == "REJ-REGLAGE-CHAINE-INVALIDE"


def test_une_ecriture_concurrente_au_meme_rang_est_refusee_sur_les_deux_moteurs(instance):
    url, deps = instance
    with stockage.transaction(url):
        parametres = {"par": aide.PROPRIETAIRE, "role": "nathan_owner", "approbation_id": "d1",
                      "raison": "Décision de départ", "quand": QUAND}
        magasin.adopter(stockage.connexion_courante(), _reglage(deps), 7, **parametres)
        ancienne = magasin.lire_chaine()
        magasin.adopter(stockage.connexion_courante(), _reglage(deps), 10, **parametres)
        with pytest.raises(ReglageRefuse) as exc:
            magasin._ajouter(ancienne, {
                "type": "adoption", "cle": CLE, "departement": "m02-revenue-crm", "version": 2, "ancienne_valeur": 7,
                "nouvelle_valeur": 14, "origine": "saisie", "par": "p", "role": "nathan_owner", "approbation_id": "a",
                "raison": "perdant", "quand": QUAND})
        assert exc.value.code == "REJ-REGLAGE-CONCURRENCE"
        assert magasin.valeur_en_vigueur(magasin.chaine_verifiee()[1], CLE) == 10


def test_deux_adoptions_simultanees_de_la_meme_valeur_n_ecrivent_qu_un_maillon_sur_les_deux_moteurs(instance):
    """SQLite sérialise les écrivains (la seconde voit « déjà adopté ») ; PostgreSQL les laisse courir et la clé de rang
    refuse la seconde (`REJ-REGLAGE-CONCURRENCE`, à rejouer) : dans les deux cas un seul maillon, jamais deux."""
    import threading

    url, deps = instance
    reglage = _reglage(deps)
    barriere = threading.Barrier(2)
    issues = []

    def adopter(numero):
        try:
            barriere.wait(timeout=20)
            with stockage.transaction(url) as cnx:
                issues.append(magasin.adopter(
                    cnx, reglage, 7, par=aide.PROPRIETAIRE, role="nathan_owner", approbation_id=f"d{numero}",
                    raison="Décision simultanée", quand=QUAND)["statut"])
        except ReglageRefuse as exc:
            issues.append(exc.code)
        except Exception as exc:  # noqa: BLE001 - une autre exception est une défaillance du test
            issues.append(f"ERREUR {type(exc).__name__}: {exc}")

    fils = [threading.Thread(target=adopter, args=(n,)) for n in (1, 2)]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(timeout=60)
    assert issues.count("adopte") == 1, issues
    assert all(i in {"adopte", "deja_adopte", "REJ-REGLAGE-CONCURRENCE"} for i in issues), issues
    with stockage.transaction(url):
        assert len(magasin.lire_chaine()) == 1


def test_une_base_sans_le_registre_ne_casse_pas_la_transaction_sur_les_deux_moteurs(instance):
    url, _ = instance
    with stockage.transaction(url) as cnx:
        cnx.execute(text("ALTER TABLE registres_maillons RENAME TO registres_maillons_ecartee"))
        lues = lecture.adoptees()
        assert lues.lisible is False and lues.valeurs == {} and "non migrée" in lues.detail
        assert cnx.execute(text("select 1")).scalar_one() == 1, "la transaction de l'appelant reste utilisable"
        cnx.execute(text("ALTER TABLE registres_maillons_ecartee RENAME TO registres_maillons"))


def test_le_geste_complet_de_la_console_sur_les_deux_moteurs(instance):
    url, deps = instance
    app = application.creer_application(
        Configuration("secret-reglages-pg-" + "x" * 40, cookie_securise=False, prefixe="/opsys"), deps,
        stockage.transaction)
    with TestClient(app, base_url="https://testserver/opsys") as client:
        r = client.post("/connexion", data={"identifiant": aide.PROPRIETAIRE, "mot_de_passe": aide.MOT_DE_PASSE},
                        follow_redirects=False)
        assert r.status_code == 303
        csrf = client.get("/api/session").json()["csrf"]
        champs = {"csrf": csrf, "action": "adopter", "cle": CLE, "saisie": "7", "raison": "Point de départ discuté",
                  "version_attendue": "0"}
        assert client.post("/reglages/geste", data=champs, follow_redirects=False).status_code == 303
        assert "deja_adopte" in client.post("/reglages/geste", data=champs, follow_redirects=False).headers["location"]
        refus = client.post("/reglages/geste", data={**champs, "saisie": "0", "version_attendue": "1"},
                            follow_redirects=False)
        assert refus.status_code == 400 and "HORS-BORNES" in refus.text
        vue = client.get("/api/reglages").json()
        assert vue["manquants"] == 9 and vue["chaine"]["valide"] is True
        champs["action"] = "revenir"
        champs["version_attendue"] = "1"
        assert client.post("/reglages/geste", data=champs, follow_redirects=False).status_code == 303
        assert client.get("/api/reglages").json()["manquants"] == 10
    with stockage.transaction(url):
        assert [m["type"] for m in magasin.lire_chaine()] == ["adoption", "retour_arriere"]
