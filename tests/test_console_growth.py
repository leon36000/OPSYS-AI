"""Parcours HTTP de la consultation Growth, données synthétiques uniquement."""

from __future__ import annotations

import copy
import html
import importlib

import pytest
from fastapi.testclient import TestClient
from m7_marketing import growth
from sqlalchemy import select, update

from opsys import identite, stockage
from opsys.console import application
from opsys.console.securite import Configuration
from opsys.stockage import codec
from opsys.stockage.schema import APPROBATIONS, EVENEMENTS_SORTANTS, REGISTRES

_SECRET = "secret-growth-console-fictif-2026-" + "x" * 32
_PREFIXE = "/opsys"
_MOT_DE_PASSE = "mot-de-passe-growth-fictif-2026"
_DEPARTEMENT = "m07-marketing"
_REGISTRE = "growth"
_PERIODE = {"debut": "2026-01-01", "fin": "2026-01-31"}


@pytest.fixture
def growth_app(tmp_path, monkeypatch):
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "opsys-home"))
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'growth.sqlite3'}")
    stockage.liberer()
    stockage.migrer()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "owner_growth", "Owner Growth fictif", _MOT_DE_PASSE, ["nathan_owner"])
        identite.creer_personne(cnx, "admin_growth", "Admin Growth fictif", _MOT_DE_PASSE, ["admin"])
        identite.creer_personne(cnx, "client_growth", "Client Growth fictif", _MOT_DE_PASSE, ["client"])
        identite.creer_personne(cnx, "seller_growth", "Vendeur Growth fictif", _MOT_DE_PASSE, ["seller"])
        identite.creer_personne(cnx, "employee_growth", "Employé Growth fictif", _MOT_DE_PASSE, ["employee"])
    app = application.creer_application(
        Configuration(_SECRET, cookie_securise=False, prefixe=_PREFIXE), None, stockage.transaction
    )
    yield app
    stockage.liberer()


@pytest.fixture
def client(growth_app):
    with TestClient(growth_app, base_url=f"https://testserver{_PREFIXE}") as test_client:
        yield test_client


def _connecter(client: TestClient, utilisateur: str = "owner_growth") -> None:
    connexion = client.post(
        "/connexion", data={"identifiant": utilisateur, "mot_de_passe": _MOT_DE_PASSE}, follow_redirects=False
    )
    assert connexion.status_code == 303, connexion.text


def _enregistrer(
    observation_id: str,
    debut: str,
    fin: str,
    *,
    source: str = "source fictive", preuve: str = "preuve-fictive", campagne: str = "campagne-fictive",
):
    resultat = growth.enregistrer_observation(
        observation_id, "clics", 12.5, "clic", debut, fin, "google", campagne,
        source, preuve, 0.7,
    )
    assert resultat["statut"] == "enregistre"
    return resultat["observation"]


def _etat_lecture() -> tuple[list[dict], list[dict], list[dict]]:
    with stockage.transaction() as cnx:
        registres = [dict(row) for row in cnx.execute(select(REGISTRES)).mappings()]
        approbations = [dict(row) for row in cnx.execute(select(APPROBATIONS)).mappings()]
        evenements = [dict(row) for row in cnx.execute(select(EVENEMENTS_SORTANTS)).mappings()]
    return registres, approbations, evenements


def test_api_lecture_inclusive_paginee_headers_et_aucune_ecriture(client):
    _connecter(client)
    with stockage.transaction():
        _enregistrer("obs-a-fictive", "2026-01-01", "2026-01-03")
        _enregistrer("obs-b-fictive", "2026-01-15", "2026-01-31")
        _enregistrer("obs-chevauche-fictive", "2025-12-31", "2026-01-02")
        _enregistrer("obs-hors-fictive", "2026-02-01", "2026-02-03")
    avant = _etat_lecture()

    premiere = client.get("/api/marketing/growth", params={**_PERIODE, "limite": 1})
    seconde = client.get("/api/marketing/growth", params={**_PERIODE, "decalage": 1, "limite": 1})

    assert premiere.status_code == seconde.status_code == 200
    assert premiere.headers["cache-control"] == "no-store"
    assert premiere.headers["x-content-type-options"] == "nosniff"
    assert premiere.headers["pragma"] == "no-cache"
    resultat1, resultat2 = premiere.json()["resultat"], seconde.json()["resultat"]
    assert resultat1["statut"] == "OBSERVATIONS_DECLAREES"
    assert resultat1["periode"] == _PERIODE
    assert resultat1["total_observations"] == 4
    assert resultat1["total_periode"] == 2
    assert resultat1["hors_periode"] == 2
    assert len(resultat1["observations"]) == len(resultat2["observations"]) == 1
    assert resultat1["suivant"] == 1
    assert resultat2["suivant"] is None
    assert resultat1["observations"][0]["observation_id"] != resultat2["observations"][0]["observation_id"]
    assert _etat_lecture() == avant


def test_page_sans_periode_ne_lit_pas_le_registre_et_post_est_refuse(client, monkeypatch):
    _connecter(client)
    lecteur = importlib.import_module("m7_marketing.growth_lecture")
    appels = []

    def interdit(*args, **kwargs):
        appels.append((args, kwargs))
        raise AssertionError("la page vide ne doit pas appeler le lecteur")

    monkeypatch.setattr(lecteur, "lire", interdit)
    avant = _etat_lecture()
    page = client.get("/marketing/growth")
    post = client.post("/api/marketing/growth", json={"debut": _PERIODE["debut"], "fin": _PERIODE["fin"]})
    assert page.status_code == 200
    assert page.headers["cache-control"] == "no-store"
    assert page.headers["x-content-type-options"] == "nosniff"
    assert appels == []
    assert post.status_code == 405
    assert _etat_lecture() == avant


@pytest.mark.parametrize(
    ("utilisateur", "attendu"),
    [
        ("owner_growth", 200),
        ("admin_growth", 200),
        ("client_growth", 403),
        ("seller_growth", 403),
        ("employee_growth", 403),
    ],
)
def test_roles_actifs_owner_admin_seulement(growth_app, utilisateur, attendu):
    with TestClient(growth_app, base_url=f"https://testserver{_PREFIXE}") as test_client:
        _connecter(test_client, utilisateur)
        reponse = test_client.get("/api/marketing/growth", params=_PERIODE)
    assert reponse.status_code == attendu, reponse.text
    if attendu == 200:
        assert reponse.json()["resultat"]["statut"] == "OBSERVATIONS_DECLAREES"
    else:
        assert "OBSERVATIONS_DECLAREES" not in reponse.text


def test_session_absente_est_refusee(client):
    reponse = client.get("/api/marketing/growth", params=_PERIODE)
    assert reponse.status_code == 401


def test_limites_hautes_periode_366_jours_et_pagination_sont_acceptees(client):
    _connecter(client)
    reponse = client.get(
        "/api/marketing/growth",
        params={"debut": "2024-01-01", "fin": "2024-12-31", "decalage": 1000, "limite": 100},
    )
    assert reponse.status_code == 200, reponse.text
    resultat = reponse.json()["resultat"]
    assert resultat["periode"] == {"debut": "2024-01-01", "fin": "2024-12-31"}
    assert resultat["decalage"] == 1000
    assert resultat["limite"] == 100


@pytest.mark.parametrize(
    "query",
    [
        "fin=2026-01-31",
        "debut=2026-01-01",
        "debut=2026-01-01&fin=2026-01-31&autre=1",
        "debut=2026-01-01&debut=2026-01-02&fin=2026-01-31",
        "debut=20260101&fin=2026-01-31",
        "debut=2026-02-30&fin=2026-03-01",
        "debut=2026-02-01&fin=2026-01-31",
        "debut=2026-01-01&fin=2027-01-02",
        "debut=2026-01-01&fin=2026-01-31&decalage=-1",
        "debut=2026-01-01&fin=2026-01-31&decalage=1001",
        "debut=2026-01-01&fin=2026-01-31&limite=0",
        "debut=2026-01-01&fin=2026-01-31&limite=101",
    ],
)
def test_dates_bornes_et_parametres_malformes_sont_refuses(client, query):
    _connecter(client)
    reponse = client.get(f"/api/marketing/growth?{query}")
    assert reponse.status_code == 400
    assert "source fictive" not in reponse.text


def test_retrait_du_role_pendant_lecture_bloque_la_reponse(client, monkeypatch):
    _connecter(client)
    with stockage.transaction():
        _enregistrer("obs-revocation-fictive", "2026-01-03", "2026-01-04")
    lecteur = importlib.import_module("m7_marketing.growth_lecture")
    original = lecteur.lire

    def lire_puis_retirer(cnx, **kwargs):
        resultat = original(cnx, **kwargs)
        identite.retirer_role(cnx, "owner_growth", "nathan_owner")
        return resultat

    monkeypatch.setattr(lecteur, "lire", lire_puis_retirer)
    reponse = client.get("/api/marketing/growth", params=_PERIODE)
    assert reponse.status_code == 403
    assert "obs-revocation-fictive" not in reponse.text
    with stockage.transaction() as cnx:
        assert "nathan_owner" not in identite.personne(cnx, "owner_growth").roles


def test_desactivation_pendant_lecture_bloque_la_reponse_sans_payload(client, monkeypatch):
    _connecter(client)
    with stockage.transaction():
        _enregistrer("obs-desactivation-fictive", "2026-01-03", "2026-01-04")
    lecteur = importlib.import_module("m7_marketing.growth_lecture")
    original = lecteur.lire

    def lire_puis_desactiver(cnx, **kwargs):
        resultat = original(cnx, **kwargs)
        identite.activer(cnx, "owner_growth", False)
        return resultat

    monkeypatch.setattr(lecteur, "lire", lire_puis_desactiver)
    reponse = client.get("/api/marketing/growth", params=_PERIODE)
    assert reponse.status_code == 401
    assert "obs-desactivation-fictive" not in reponse.text
    with stockage.transaction() as cnx:
        assert identite.personne(cnx, "owner_growth").actif is False


def test_retrait_role_avant_lecture_n_appelle_pas_le_reader(growth_app, monkeypatch):
    with TestClient(growth_app, base_url=f"https://testserver{_PREFIXE}") as client:
        _connecter(client)
        with stockage.transaction() as cnx:
            identite.retirer_role(cnx, "owner_growth", "nathan_owner")
        lecteur = importlib.import_module("m7_marketing.growth_lecture")
        appels = []

        def espion(*args, **kwargs):
            appels.append((args, kwargs))
            raise AssertionError("le lecteur ne doit pas être appelé après retrait du rôle")

        monkeypatch.setattr(lecteur, "lire", espion)
        reponse = client.get("/api/marketing/growth", params=_PERIODE)
    assert reponse.status_code == 403
    assert appels == []
    assert "OBSERVATIONS_DECLAREES" not in reponse.text


def test_donnees_source_et_preuve_sont_echappees_dans_html(client):
    _connecter(client)
    hostile = '<script>alert("growth-fictif")</script><img src=x onerror="alert(1)">'
    with stockage.transaction():
        _enregistrer("obs-html-fictive", "2026-01-10", "2026-01-10", source=hostile, preuve=hostile)
    avant = _etat_lecture()
    page = client.get("/marketing/growth", params=_PERIODE)
    assert page.status_code == 200
    assert html.escape(hostile) in page.text
    assert hostile not in page.text
    assert "no-store" in page.headers["cache-control"]
    assert _etat_lecture() == avant


def test_corruption_hors_periode_refuse_la_lecture_sans_ecriture(client):
    _connecter(client)
    with stockage.transaction() as cnx:
        observation = _enregistrer("obs-corrompue-hors-periode", "2024-01-01", "2024-01-02")
        rang = cnx.execute(
            select(REGISTRES.c.rang).where(
                REGISTRES.c.departement == _DEPARTEMENT, REGISTRES.c.registre == _REGISTRE,
            )
        ).scalar_one()
        corrompue = copy.deepcopy(observation)
        corrompue["source"] = "secret-corrompu-fictif"
        cnx.execute(
            update(REGISTRES).where(
                REGISTRES.c.departement == _DEPARTEMENT,
                REGISTRES.c.registre == _REGISTRE,
                REGISTRES.c.rang == rang,
            ).values(maillon=codec.encoder(corrompue))
        )
    avant = _etat_lecture()
    reponse = client.get("/api/marketing/growth", params=_PERIODE)
    assert reponse.status_code == 409
    assert "secret-corrompu-fictif" not in reponse.text
    assert _etat_lecture() == avant


def test_lecture_ne_declenche_pas_plan_et_survit_a_une_reouverture_sqlite(client, monkeypatch):
    _connecter(client)
    with stockage.transaction():
        _enregistrer("obs-persistante-fictive", "2026-01-08", "2026-01-09")
    monkeypatch.setattr(growth, "plan_30j", lambda *_args, **_kwargs: pytest.fail("plan_30j appelé par une lecture"))
    avant = _etat_lecture()
    premiere = client.get("/api/marketing/growth", params=_PERIODE)
    stockage.liberer()
    with stockage.transaction():
        persiste = list(stockage.maillons(_DEPARTEMENT, _REGISTRE))
    seconde = client.get("/api/marketing/growth", params=_PERIODE)
    assert premiere.status_code == seconde.status_code == 200
    assert premiere.json()["resultat"]["decalage"] == 0
    assert premiere.json()["resultat"]["limite"] == 25
    assert any(item.get("observation_id") == "obs-persistante-fictive" for item in persiste)
    assert _etat_lecture() == avant


@pytest.mark.parametrize("brut", [
    '{"__opsys__":"dict","v":null}',
    '{"__opsys__":"bytes","v":null}',
    '{"__opsys__":"decimal","v":"montant-invalide-fictif"}',
])
def test_etiquette_codec_corrompue_http_409_sans_fuite_ni_ecriture(growth_app, brut):
    from sqlalchemy import insert

    with stockage.transaction() as cnx:
        cnx.execute(insert(REGISTRES).values(
            departement=_DEPARTEMENT, registre=_REGISTRE, rang=0, maillon=brut,
        ))
    avant = _etat_lecture()
    with TestClient(growth_app, base_url=f"https://testserver{_PREFIXE}", raise_server_exceptions=False) as client:
        _connecter(client)
        reponse = client.get("/api/marketing/growth", params=_PERIODE)
    assert reponse.status_code == 409
    assert brut not in reponse.text
    assert "montant-invalide-fictif" not in reponse.text
    assert _etat_lecture() == avant


def test_observation_retypee_plan_http_409_sans_ecriture(client):
    _connecter(client)
    with stockage.transaction() as cnx:
        observation = _enregistrer("obs-pseudo-plan-fictive", "2025-01-01", "2025-01-02")
        observation["type"] = "plan_growth_30j"
        cnx.execute(update(REGISTRES).where(
            REGISTRES.c.departement == _DEPARTEMENT, REGISTRES.c.registre == _REGISTRE,
        ).values(maillon=codec.encoder(observation)))
    avant = _etat_lecture()
    reponse = client.get("/api/marketing/growth", params=_PERIODE)
    assert reponse.status_code == 409
    assert "obs-pseudo-plan-fictive" not in reponse.text
    assert _etat_lecture() == avant


# Phase humaine : ajouts indépendants; les oracles de lecture historiques ci-dessus sont conservés.
def _csrf_growth(client):
    return client.get("/api/session").json()["csrf"]


def _commande_growth(client, *, observation_id="humaine-fictive", mutation_id="growth-humaine-fictive"):
    resultat = client.get("/api/marketing/growth", params=_PERIODE)
    assert resultat.status_code == 200, resultat.text
    tete = resultat.json()["resultat"]["tete"]
    return {"observation_id": observation_id, "metrique": "clics", "valeur": 12.5, "unite": "clic",
            "debut": "2026-01-01", "fin": "2026-01-31", "plateforme": "google", "campagne": "fictive",
            "source": "export manuel fictif", "preuve": "rapport:fictif", "confiance": 0.7,
            "mutation_id": mutation_id, "rang_attendu": tete["rang"], "empreinte_attendue": tete["empreinte"]}


def _post_growth(client, commande, csrf=None):
    return client.post("/api/marketing/growth/observations", json=commande,
                       headers={"x-csrf-token": csrf or _csrf_growth(client)})


def _etat_growth_humain():
    from opsys.stockage.schema import MUTATIONS_APPLIQUEES

    with stockage.transaction() as cnx:
        return (cnx.execute(select(REGISTRES)).all(), cnx.execute(select(MUTATIONS_APPLIQUEES)).all(),
                cnx.execute(select(EVENEMENTS_SORTANTS)).all(), cnx.execute(select(APPROBATIONS)).all())


@pytest.mark.parametrize("utilisateur", ["owner_growth", "admin_growth"])
def test_saisie_growth_http_reel_provenance_rejeu_et_reouverture(client, utilisateur):
    _connecter(client, utilisateur)
    commande = _commande_growth(client)
    premier = _post_growth(client, commande)
    assert premier.status_code == 200, premier.text
    observation = premier.json()["resultat"]["observation"]
    assert observation["schema_version"] == 2
    assert observation["provenance"]["auteur"] == utilisateur
    assert observation["provenance"]["mode"] == "saisie_humaine_console"
    assert observation["provenance"]["horodatage"].endswith("+00:00")
    assert premier.json()["resultat"]["statut_source"] == "DECLAREE_NON_VERIFIEE"
    avant_rejeu = _etat_growth_humain()
    stockage.liberer()
    second = _post_growth(client, commande)
    assert second.status_code == 200
    assert second.json()["resultat"]["rejoue"] is True
    assert second.json()["resultat"]["observation"] == observation
    assert _etat_growth_humain() == avant_rejeu
    lecture = client.get("/api/marketing/growth", params=_PERIODE).json()["resultat"]
    assert lecture["observations"][0]["auteur"] == utilisateur
    assert lecture["observations"][0]["verification_externe"] is None
    assert lecture["tete"]["rang"] == 1


@pytest.mark.parametrize("champ", ["auteur", "horodatage", "provenance", "phase_humaine", "schema_version"])
def test_saisie_growth_refuse_champs_provenance_forges_sans_effet(client, champ):
    _connecter(client)
    commande = {**_commande_growth(client), champ: "valeur-fictive-forgee"}
    avant = _etat_growth_humain()
    assert _post_growth(client, commande).status_code == 400
    assert _etat_growth_humain() == avant


@pytest.mark.parametrize("utilisateur", ["client_growth", "seller_growth", "employee_growth"])
def test_saisie_growth_roles_interdits(client, utilisateur):
    _connecter(client)
    commande = _commande_growth(client)
    _connecter(client, utilisateur)
    avant = _etat_growth_humain()
    assert _post_growth(client, commande).status_code == 403
    assert _etat_growth_humain() == avant


def test_saisie_growth_csrf_absent_ou_invalide_sans_effet(client):
    _connecter(client)
    commande = _commande_growth(client)
    avant = _etat_growth_humain()
    assert client.post("/api/marketing/growth/observations", json=commande).status_code == 403
    assert _post_growth(client, commande, "csrf-invalide").status_code == 403
    assert _etat_growth_humain() == avant


def test_saisie_growth_html_csrf_formulaire_et_post_threadpool(client, monkeypatch):
    import re
    import threading

    module = importlib.import_module("opsys.console.marketing_growth_ui")
    metier = importlib.import_module("opsys.console.metier")
    boucle = []
    original_corps, original_executer = module._corps_borne, metier.executer

    async def corps(request):
        boucle.append(threading.get_ident())
        return await original_corps(request)

    def executer(*args, **kwargs):
        assert threading.get_ident() != boucle[-1], "le métier ne doit pas bloquer la boucle ASGI"
        return original_executer(*args, **kwargs)

    monkeypatch.setattr(module, "_corps_borne", corps)
    monkeypatch.setattr(metier, "executer", executer)
    _connecter(client)
    page = client.get("/marketing/growth", params=_PERIODE)
    assert page.status_code == 200 and page.headers["cache-control"] == "no-store"
    champs = dict(re.findall(r'name="(csrf|mutation_id|rang_attendu|empreinte_attendue)" value="([^"]*)"', page.text))
    assert set(champs) == {"csrf", "mutation_id", "rang_attendu", "empreinte_attendue"}
    commande = _commande_growth(client)
    commande.update(champs)
    refuse = client.post("/marketing/growth/observations", data={**commande, "csrf": "faux"})
    assert refuse.status_code == 403
    accepte = client.post("/marketing/growth/observations", data=commande, follow_redirects=False)
    assert accepte.status_code == 303 and accepte.headers["cache-control"] == "no-store"
    commande_api = _commande_growth(client, observation_id="seconde-fictive", mutation_id="seconde-fictive")
    assert _post_growth(client, commande_api).status_code == 200
    assert len(boucle) == 3


def test_saisie_growth_head_et_mutation_changed_refuses_sans_append(client):
    _connecter(client)
    commande = _commande_growth(client)
    assert _post_growth(client, commande).status_code == 200
    avant = _etat_growth_humain()
    changee = {**commande, "valeur": 13}
    assert _post_growth(client, changee).status_code == 409
    perimee = {**commande, "mutation_id": "autre-fictive", "observation_id": "autre-fictive"}
    assert _post_growth(client, perimee).status_code == 409
    assert _etat_growth_humain() == avant


def test_saisie_growth_retrait_role_avant_append_annule_reclamation(client, monkeypatch):
    _connecter(client)
    commande = _commande_growth(client)
    lecteur = importlib.import_module("m7_marketing.growth_lecture")
    original = lecteur.decoder_prefixe

    def retirer(textes):
        resultat = original(textes)
        identite.retirer_role(stockage.connexion_courante(), "owner_growth", "nathan_owner")
        return resultat

    monkeypatch.setattr(lecteur, "decoder_prefixe", retirer)
    avant = _etat_growth_humain()
    assert _post_growth(client, commande).status_code == 403
    assert _etat_growth_humain() == avant


def test_saisie_growth_exception_apres_append_annule_registre_et_receipt(client, monkeypatch):
    from opsys.stockage.maillons import MaillonsDurables

    _connecter(client)
    commande = _commande_growth(client)
    original = MaillonsDurables.append

    def panne(self, maillon, **kwargs):
        original(self, maillon, **kwargs)
        raise RuntimeError("panne-fictive-apres-append")

    monkeypatch.setattr(MaillonsDurables, "append", panne)
    avant = _etat_growth_humain()
    with pytest.raises(RuntimeError, match="panne-fictive-apres-append"):
        _post_growth(client, commande)
    assert _etat_growth_humain() == avant


def test_saisie_growth_concurrence_cas_et_derniere_place_du_quota(client):
    from concurrent.futures import ThreadPoolExecutor

    from sqlalchemy import insert

    _connecter(client)
    plan = codec.encoder({"type": "plan_growth_30j", "horizon_debut": "2026-01-01",
                          "recommandations": [], "donnees_manquantes": [], "limites": []})
    with stockage.transaction() as cnx:
        cnx.execute(insert(REGISTRES), [{"departement": _DEPARTEMENT, "registre": _REGISTRE,
                                       "rang": rang, "maillon": plan} for rang in range(999)])
    commande = _commande_growth(client)
    autre = {**commande, "observation_id": "concurrente-fictive", "mutation_id": "concurrente-fictive"}
    csrf = _csrf_growth(client)
    with ThreadPoolExecutor(max_workers=2) as executants:
        retours = list(executants.map(lambda c: _post_growth(client, c, csrf), [commande, autre]))
    assert sorted(r.status_code for r in retours) == [200, 409]
    etat = _etat_growth_humain()
    assert len(etat[0]) == 1000 and len(etat[1]) == 1


def test_saisie_growth_corruption_hors_periode_refuse_sans_receipt(client):
    _connecter(client)
    commande = _commande_growth(client)
    with stockage.transaction():
        _enregistrer("hors-periode-corrompue", "2025-01-01", "2025-01-02")
    with stockage.transaction() as cnx:
        ligne = cnx.execute(select(REGISTRES)).mappings().one()
        maillon = codec.decoder(ligne["maillon"])
        maillon["valeur"] = 999
        cnx.execute(update(REGISTRES).values(maillon=codec.encoder(maillon)))
    avant = _etat_growth_humain()
    assert _post_growth(client, commande).status_code == 409
    assert _etat_growth_humain() == avant


def test_saisie_growth_rejeu_apres_revocation_ne_revele_pas_receipt(client):
    _connecter(client)
    commande = _commande_growth(client)
    assert _post_growth(client, commande).status_code == 200
    csrf = _csrf_growth(client)
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, "owner_growth", "nathan_owner")
    avant = _etat_growth_humain()
    reponse = _post_growth(client, commande, csrf)
    assert reponse.status_code == 403 and "export manuel fictif" not in reponse.text
    assert _etat_growth_humain() == avant


def test_saisie_growth_payload_borne_et_doublons_json(client):
    import json

    _connecter(client)
    commande = _commande_growth(client)
    csrf = _csrf_growth(client)
    avant = _etat_growth_humain()
    doublon = json.dumps(commande)[:-1] + ', "mutation_id": "autre"}'
    assert client.post("/api/marketing/growth/observations", content=doublon,
                       headers={"x-csrf-token": csrf, "content-type": "application/json"}).status_code == 400
    assert client.post("/api/marketing/growth/observations", content=b"x" * (32 * 1024 + 1),
                       headers={"x-csrf-token": csrf}).status_code == 413
    assert _etat_growth_humain() == avant


@pytest.mark.parametrize("changement", [
    {"valeur": True}, {"confiance": True}, {"confiance": 1.1},
    {"debut": "2026-01-01", "fin": "2027-01-02"}, {"source": ""}, {"preuve": "x" * 2049},
])
def test_saisie_growth_donnees_invalides_refusees_sans_effet(client, changement):
    _connecter(client)
    commande = {**_commande_growth(client), **changement}
    avant = _etat_growth_humain()
    assert _post_growth(client, commande).status_code == 409
    assert _etat_growth_humain() == avant


def test_saisie_growth_numerique_non_fini_refuse_sans_effet(client):
    import json

    _connecter(client)
    commande = _commande_growth(client)
    avant = _etat_growth_humain()
    charge = json.dumps(commande).replace('"valeur": 12.5', '"valeur": NaN')
    reponse = client.post("/api/marketing/growth/observations", content=charge,
                         headers={"x-csrf-token": _csrf_growth(client), "content-type": "application/json"})
    assert reponse.status_code == 409
    assert _etat_growth_humain() == avant


def test_saisie_growth_reference_xss_echappee_et_source_non_verifiee(client):
    _connecter(client)
    commande = {**_commande_growth(client), "source": '<script>alert("fictif")</script>'}
    assert _post_growth(client, commande).status_code == 200
    page = client.get("/marketing/growth", params=_PERIODE)
    assert '<script>alert("fictif")</script>' not in page.text
    assert "&lt;script&gt;" in page.text
    reponse = client.get("/api/marketing/growth", params=_PERIODE).json()["resultat"]
    assert reponse["observations"][0]["statut_source"] == "DECLAREE_NON_VERIFIEE"
    assert reponse["observations"][0]["verification_externe"] is None


def test_saisie_growth_json_profond_refuse_sans_effet(client):
    _connecter(client)
    avant = _etat_growth_humain()
    reponse = client.post(
        "/api/marketing/growth/observations", content="[" * 1500 + "0" + "]" * 1500,
        headers={"x-csrf-token": _csrf_growth(client), "content-type": "application/json"},
    )
    assert reponse.status_code == 400
    assert _etat_growth_humain() == avant
