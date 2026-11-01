"""M8.14 — Pont vers les outils BI externes : exports EN LECTURE SEULE, jeton de lecture dédié, quotas, PII, journal.

Prouve (données fictives, vraie base migrée, vrai coffre chiffré, vrai routeur FastAPI) :
- l'émission est un geste de personne (admin/propriétaire) ; le secret n'est rendu qu'une fois, n'est jamais dans la
base,
  les journaux ni les réponses ; la révocation est immédiate ; un jeton absent, mal formé, inconnu, expiré, révoqué ou
  au
  mauvais secret reçoit le même 401 ;
- les jetons ne s'acceptent jamais dans l'URL ; seul GET existe ; tout verbe d'écriture est refusé 405, journalisé, et
  l'entrepôt reste identique ;
- le CSV neutralise les formules, le JSON Lines et l'OData sont fidèles ; la portée financière retire colonnes et
lignes ;
- un renseignement personnel glissé dans un texte libre OU dans un identifiant est masqué ; sans masqueur, refus ;
- les quotas de requêtes et de lignes refusent 429 avant toute donnée ; le journal d'accès est append-only et sans
secret ;
- l'OData refuse ce qu'il ne fait pas ($filter…) au lieu de l'ignorer.
"""

from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from m8_analytics import catalogue_mesures, entrepot_stockage, jeux_fictifs
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError

from opsys import identite, stockage
from opsys.observabilite.pii import MasqueurMotifs
from opsys.pont_bi import formats, http, jeux, service
from opsys.secrets_coffre import cle_maitresse, coffre
from opsys.stockage import schema

FICTIF = True
MOT_DE_PASSE = "mot-de-passe-pont-fictif-2026"
MAINTENANT = 1_800_000_000.0  # un instant fixe ; l'horloge du routeur est injectée
_INSTANT_CONSTRUCTION = "2026-10-30T20:00:00-04:00"


@pytest.fixture
def cle(tmp_path, monkeypatch):
    dossier = tmp_path / "cles"
    dossier.mkdir(mode=0o700)
    chemin = dossier / "coffre.cle"
    cle_maitresse.generer_fichier(chemin)
    monkeypatch.setenv(cle_maitresse.ENV_FICHIER, str(chemin))
    monkeypatch.delenv(cle_maitresse.ENV_CLE, raising=False)
    return cle_maitresse.charger()


@pytest.fixture
def base(session, cle):
    with session() as cnx:
        identite.creer_personne(cnx, "admin_fictif", "Admin fictif", MOT_DE_PASSE, ["admin"])
        identite.creer_personne(cnx, "employe_fictif", "Employé fictif", MOT_DE_PASSE, ["employee"])
        catalogue = catalogue_mesures.charger()
        entrepot_stockage.reconstruire(cnx, jeux_fictifs.registres_fictifs(), catalogue, _INSTANT_CONSTRUCTION)
    return session


class Horloge:
    def __init__(self):
        self.maintenant = MAINTENANT

    def __call__(self):
        return self.maintenant


@pytest.fixture
def horloge():
    return Horloge()


@pytest.fixture
def masqueur():
    return MasqueurMotifs(b"k" * 32)


@pytest.fixture
def client(base, horloge, masqueur, cle):
    app = FastAPI()
    app.include_router(
        http.creer_router(cnx_factory=stockage.transaction, masqueur=lambda: masqueur, cle=lambda: cle, horloge=horloge)
    )
    return TestClient(app)


def _emettre(base, cle, horloge, **kw):
    arguments = {
        "acteur": "admin_fictif",
        "libelle": "Metabase fictif",
        "jeux": ["mesures_courantes", "chantiers"],
        **kw,
    }
    with base() as cnx:
        return service.emettre(cnx, cle=cle, maintenant=horloge.maintenant, **arguments)


def _en_tete(jeton):
    return {"Authorization": f"Bearer {jeton['jeton']}"}


# ---------------------------------------------------------------------------
# Émission, révocation, secret
# ---------------------------------------------------------------------------
def test_emission_geste_de_personne_le_secret_n_est_rendu_qu_une_fois_et_jamais_stocke(base, cle, horloge):
    jeton = _emettre(base, cle, horloge)
    secret = jeton["jeton"].split(".", 1)[1]
    assert jeton["jeton"].startswith("opsys-bi:v1:") and jeton["financier"] is False
    with base() as cnx:
        lignes = service.lister(cnx, maintenant=horloge.maintenant)
        brut = json.dumps([dict(r) for r in cnx.execute(select(schema.PONT_BI_JETONS)).mappings()], default=str)
        journal = json.dumps([dict(r) for r in cnx.execute(select(schema.JOURNAL)).mappings()], default=str)
        acces_coffre = json.dumps(coffre.journal(cnx), default=str)
    assert lignes[0]["etat"] == "actif" and "jeton" not in lignes[0]
    for texte in (brut, journal, acces_coffre, json.dumps(lignes)):
        assert secret not in texte and jeton["jeton"] not in texte
    assert "pont_bi.jeton_emis" in journal


@pytest.mark.parametrize("acteur", ["employe_fictif", "inconnu", ""])
def test_seule_une_personne_admin_ou_proprietaire_emet(base, cle, horloge, acteur):
    with pytest.raises(service.RefusPontBI) as exc, base() as cnx:
        service.emettre(cnx, acteur=acteur, libelle="Metabase fictif", jeux=["chantiers"], cle=cle)
    assert exc.value.statut == 403
    with base() as cnx:
        assert service.lister(cnx) == []


@pytest.mark.parametrize(
    "mutation",
    [
        {"libelle": "ab"},
        {"libelle": "x" * 121},
        {"jeux": []},
        {"jeux": ["inconnu"]},
        {"jeux": ["chantiers", "chantiers"]},
        {"jeux": "chantiers"},
        {"financier": "oui"},
        {"quota_requetes_heure": 0},
        {"quota_requetes_heure": True},
        {"quota_lignes_jour": 10**8},
        {"duree_s": 59},
        {"duree_s": 400 * 86400},
        {"duree_s": 3600.5},
    ],
)
def test_une_emission_invalide_est_refusee_sans_rien_ecrire(base, cle, horloge, mutation):
    with pytest.raises(service.RefusPontBI) as exc:
        _emettre(base, cle, horloge, **mutation)
    assert exc.value.statut == 422
    with base() as cnx:
        assert service.lister(cnx) == [] and coffre.lister(cnx) == []


def test_la_revocation_est_immediate_et_coupe_le_coffre(base, cle, horloge, client):
    jeton = _emettre(base, cle, horloge)
    assert client.get("/pont-bi/v1/jeux", headers=_en_tete(jeton)).status_code == 200
    with base() as cnx:
        service.revoquer(cnx, acteur="admin_fictif", jeton_id=jeton["jeton_id"], maintenant=horloge.maintenant)
        assert coffre.metadonnees(cnx, f"pont-bi.{jeton['jeton_id']}")["etat"] == "revoque"
        assert service.lister(cnx, maintenant=horloge.maintenant)[0]["etat"] == "revoque"
    assert client.get("/pont-bi/v1/jeux", headers=_en_tete(jeton)).status_code == 401
    with pytest.raises(service.RefusPontBI) as exc, base() as cnx:
        service.revoquer(cnx, acteur="employe_fictif", jeton_id=jeton["jeton_id"])
    assert exc.value.statut == 403


# ---------------------------------------------------------------------------
# Authentification : un seul 401, pas d'oracle
# ---------------------------------------------------------------------------
def test_tout_echec_d_authentification_est_le_meme_401(base, cle, horloge, client):
    jeton = _emettre(base, cle, horloge)
    identifiant, secret = jeton["jeton"][len("opsys-bi:v1:") :].split(".")
    faux = [
        {},
        {"Authorization": "Basic abc"},
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer x"},
        {"Authorization": f"Bearer opsys-bi:v1:{identifiant}.{'A' * 43}"},  # mauvais secret
        {"Authorization": f"Bearer opsys-bi:v1:{'0' * 32}.{secret}"},  # jeton inconnu
        {"Authorization": f"Bearer opsys-bi:v1:{identifiant}.{secret}x"},  # secret trop long
        {"Authorization": f"bearer opsys-bi:v1:{identifiant}.{secret}"},  # casse
        {"Authorization": "Bearer opsys-jeton:v1:" + "A" * 43},  # jeton d'agent du coffre
    ]
    corps = set()
    for entetes in faux:
        reponse = client.get("/pont-bi/v1/jeux", headers=entetes)
        assert reponse.status_code == 401, entetes
        corps.add(json.dumps(reponse.json(), sort_keys=True))
    assert len(corps) == 1  # même message : rien n'indique ce qui a échoué


def test_un_jeton_expire_est_refuse(base, cle, horloge, client):
    jeton = _emettre(base, cle, horloge, duree_s=3600)
    assert client.get("/pont-bi/v1/jeux", headers=_en_tete(jeton)).status_code == 200
    horloge.maintenant += 3600  # exactement à l'expiration : refusé (borne exclusive)
    assert client.get("/pont-bi/v1/jeux", headers=_en_tete(jeton)).status_code == 401


def test_le_jeton_dans_l_url_est_refuse_meme_s_il_est_valide(base, cle, horloge, client):
    jeton = _emettre(base, cle, horloge)
    secret_url = jeton["jeton"]
    for param in ("access_token", "token", "jeton", "API_KEY"):
        reponse = client.get(f"/pont-bi/v1/jeux/chantiers.csv?{param}={secret_url}", headers=_en_tete(jeton))
        assert reponse.status_code == 400 and reponse.json()["erreur"] == "jeton_dans_l_url"
        assert secret_url not in reponse.text


def test_un_jeton_non_active_pour_ce_jeu_est_refuse(base, cle, horloge, client):
    jeton = _emettre(base, cle, horloge, jeux=["chantiers"])
    assert client.get("/pont-bi/v1/jeux/mesures_courantes.csv", headers=_en_tete(jeton)).status_code == 403
    assert client.get("/pont-bi/v1/jeux/chantiers.csv", headers=_en_tete(jeton)).status_code == 200


# ---------------------------------------------------------------------------
# Lecture seule
# ---------------------------------------------------------------------------
def _instantane(base):
    with base() as cnx:
        return {
            nom: [dict(r) for r in cnx.execute(select(table)).mappings()]
            for nom, table in entrepot_stockage.tables().items()
        }


@pytest.mark.parametrize("verbe", ["post", "put", "patch", "delete"])
@pytest.mark.parametrize(
    "chemin",
    ["/pont-bi/v1/jeux/chantiers.csv", "/pont-bi/odata/Chantiers", "/pont-bi/v1/jeux", "/pont-bi/n-importe-quoi"],
)
def test_tout_verbe_d_ecriture_est_refuse_405_et_l_entrepot_reste_identique(base, cle, horloge, client, verbe, chemin):
    jeton = _emettre(base, cle, horloge)
    avant = _instantane(base)
    reponse = client.request(verbe.upper(), chemin, headers=_en_tete(jeton), json={"valeur": "pirate"})
    assert reponse.status_code == 405 and reponse.headers["allow"] == "GET"
    assert reponse.json()["erreur"] == "lecture_seule"
    assert _instantane(base) == avant
    with base() as cnx:
        derniere = service.acces_recents(cnx, 1)[0]
    assert derniere["code"] == "lecture_seule" and derniere["jeton_id"] == jeton["jeton_id"]


def test_un_verbe_d_ecriture_sans_jeton_est_aussi_refuse(client):
    assert client.post("/pont-bi/v1/jeux/chantiers.csv").status_code == 405


def test_la_transaction_de_lecture_refuse_toute_ecriture(base):
    with base() as cnx, service.lecture_seule(cnx):
        with pytest.raises(DBAPIError):
            cnx.execute(update(schema.M8_ENT_DIM_CHANTIER).values(devis_id="pirate"))
        with pytest.raises(DBAPIError):
            cnx.execute(text("DELETE FROM m8_ent_mesures_courantes"))
    with base() as cnx:  # le mode est rendu : une écriture ordinaire redevient possible hors du bloc
        cnx.execute(
            update(schema.M8_ENT_DIM_CHANTIER)
            .values(devis_id="devis-fictif-001")
            .where(schema.M8_ENT_DIM_CHANTIER.c.wct_id == "wct-fictif-001")
        )


def test_une_route_get_inconnue_est_un_404_pas_un_405(client):
    assert client.get("/pont-bi/n-importe-quoi").status_code == 404
    assert client.get("/pont-bi/v1/jeux/inconnu.csv").status_code == 404
    assert client.get("/pont-bi/v1/jeux/chantiers.xlsx").status_code == 404


# ---------------------------------------------------------------------------
# Les formats
# ---------------------------------------------------------------------------
def test_le_csv_est_fidele_a_l_entrepot_avec_provenance_en_en_tetes(base, cle, horloge, client):
    jeton = _emettre(base, cle, horloge, jeux=["mesures_courantes"])
    reponse = client.get("/pont-bi/v1/jeux/mesures_courantes.csv", headers=_en_tete(jeton))
    assert reponse.status_code == 200 and reponse.headers["content-type"].startswith("text/csv")
    lignes = reponse.text.split("\r\n")
    assert lignes[0].startswith("metric_id,construction_id,nom,") and lignes[-1] == ""
    assert any(ligne.startswith("m8_taux_acceptation_pct,") and ",50.00," in ligne for ligne in lignes)
    assert reponse.headers["cache-control"] == "no-store" and reponse.headers["x-opsys-lecture-seule"] == "oui"
    assert reponse.headers["x-opsys-entrepot-construit-le"] == _INSTANT_CONSTRUCTION
    assert len(reponse.headers["x-opsys-entrepot-construction"]) == 64


def test_le_jsonl_est_une_ligne_json_par_enregistrement_null_pour_l_absent(base, cle, horloge, client):
    jeton = _emettre(base, cle, horloge, jeux=["mesures_courantes"])
    reponse = client.get("/pont-bi/v1/jeux/mesures_courantes.jsonl", headers=_en_tete(jeton))
    enregistrements = [json.loads(ligne) for ligne in reponse.text.splitlines()]
    par_id = {e["metric_id"]: e for e in enregistrements}
    assert par_id["m8_clics_par_contenu"]["valeur"] is None  # jamais un zéro
    assert par_id["m8_clics_par_contenu"]["statut"] == "non_calculable"
    assert par_id["m8_chantiers_termines"]["fraicheur_terminale"] is True


def test_la_portee_financiere_retire_colonnes_et_lignes(base, cle, horloge, client):
    sans = _emettre(base, cle, horloge, jeux=["mesures_courantes", "mesures_historique", "chantiers", "devis"])
    avec = _emettre(
        base,
        cle,
        horloge,
        jeux=["mesures_courantes", "mesures_historique", "chantiers", "devis"],
        financier=True,
        libelle="Metabase financier fictif",
    )

    def lire(jeton, jeu):
        return [
            json.loads(ligne)
            for ligne in client.get(f"/pont-bi/v1/jeux/{jeu}.jsonl", headers=_en_tete(jeton)).text.splitlines()
        ]

    for jeu, interdit in (("chantiers", "marge_reelle_cad"), ("devis", "prix_total_cad")):
        assert interdit not in lire(sans, jeu)[0] and interdit in lire(avec, jeu)[0]
    assert "verdict_marge" not in lire(sans, "chantiers")[0]
    for jeu in ("mesures_courantes", "mesures_historique"):
        ids_sans = {e["metric_id"] for e in lire(sans, jeu)}
        ids_avec = {e["metric_id"] for e in lire(avec, jeu)}
        assert not ids_sans & {"m8_cash_libre_cad", "m8_carnet_signe_cad"}
        assert {"m8_cash_libre_cad", "m8_carnet_signe_cad"} <= ids_avec
    assert next(e for e in lire(avec, "chantiers"))["marge_reelle_cad"] == "3000.00"
    description = client.get("/pont-bi/v1/jeux", headers=_en_tete(sans)).json()["jeux"]
    colonnes = {c["nom"] for jeu in description if jeu["jeu"] == "chantiers" for c in jeu["colonnes"]}
    assert "marge_reelle_cad" not in colonnes


def test_la_pagination_est_bornee_et_cumulative(base, cle, horloge, client):
    jeton = _emettre(base, cle, horloge, jeux=["mesures_courantes"])
    page1 = client.get("/pont-bi/v1/jeux/mesures_courantes.jsonl?limite=5&depart=0", headers=_en_tete(jeton))
    page2 = client.get("/pont-bi/v1/jeux/mesures_courantes.jsonl?limite=5&depart=5", headers=_en_tete(jeton))
    ids = [json.loads(ligne)["metric_id"] for ligne in (page1.text + page2.text).splitlines()]
    assert len(ids) == 10 and len(set(ids)) == 10
    assert page1.headers["x-opsys-total-lignes"] == "41"  # 56 mesures moins les 15 financières
    for requete in ("limite=0", "limite=5001", "limite=abc", "depart=-1", "inconnu=1", "limite=1&limite=2"):
        assert (
            client.get(f"/pont-bi/v1/jeux/mesures_courantes.csv?{requete}", headers=_en_tete(jeton)).status_code == 400
        )


# ---------------------------------------------------------------------------
# CSV : formules de tableur
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("brut", "attendu"),
    [
        ("=SOMME(A1:A9)", "'=SOMME(A1:A9)"),
        ("+1+1", "'+1+1"),
        ("-2+3", "'-2+3"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("\tcmd", "'\tcmd"),
        ("\rcmd", "'\rcmd"),
        ("-1500.00", "-1500.00"),
        ("12.5", "12.5"),
        ("texte normal", "texte normal"),
        ("=", "'="),
        ("-", "'-"),
        ("1e5", "1e5"),
    ],
)
def test_neutralisation_des_formules(brut, attendu):
    assert formats.neutraliser_cellule(brut) == attendu


def test_une_formule_glissee_dans_une_donnee_sort_neutralisee_en_csv(base, cle, horloge, client):
    with base() as cnx:
        cnx.execute(
            update(schema.M8_ENT_MESURES_COURANTES)
            .values(detail='=HYPERLINK("http://x.test","cliquez")')
            .where(schema.M8_ENT_MESURES_COURANTES.c.metric_id == "m8_clics_par_contenu")
        )
    jeton = _emettre(base, cle, horloge, jeux=["mesures_courantes"])
    csv_texte = client.get("/pont-bi/v1/jeux/mesures_courantes.csv", headers=_en_tete(jeton)).text
    assert "'=HYPERLINK" in csv_texte
    assert ",=HYPERLINK" not in csv_texte and "\r\n=HYPERLINK" not in csv_texte and ',"=HYPERLINK' not in csv_texte


# ---------------------------------------------------------------------------
# Minimisation PII
# ---------------------------------------------------------------------------
def test_un_renseignement_personnel_glisse_dans_un_texte_libre_est_masque(base, cle, horloge, client):
    with base() as cnx:
        cnx.execute(
            update(schema.M8_ENT_MESURES_COURANTES)
            .values(detail="écrire à jean.tremblay@example.test ou au 514-555-0199")
            .where(schema.M8_ENT_MESURES_COURANTES.c.metric_id == "m8_clics_par_contenu")
        )
    jeton = _emettre(base, cle, horloge, jeux=["mesures_courantes"])
    reponse = client.get("/pont-bi/v1/jeux/mesures_courantes.jsonl", headers=_en_tete(jeton))
    assert "jean.tremblay" not in reponse.text and "514-555-0199" not in reponse.text
    assert "[[COURRIEL:" in reponse.text and int(reponse.headers["x-opsys-cellules-masquees"]) >= 1


def test_un_renseignement_personnel_dans_un_identifiant_est_masque_pas_sorti(base, cle, horloge, client):
    with base() as cnx:
        cnx.execute(
            update(schema.M8_ENT_DIM_CHANTIER)
            .values(devis_id="marie.roy@example.test")
            .where(schema.M8_ENT_DIM_CHANTIER.c.wct_id == "wct-fictif-001")
        )
    jeton = _emettre(base, cle, horloge, jeux=["chantiers"])
    texte = client.get("/pont-bi/v1/jeux/chantiers.csv", headers=_en_tete(jeton)).text
    assert "marie.roy" not in texte and "[[COURRIEL:" in texte
    assert "wct-fictif-001" in texte  # les identifiants conformes ne sont pas altérés


def test_sans_masqueur_un_export_qui_en_a_besoin_est_refuse(base, cle, horloge):
    with base() as cnx:
        cnx.execute(
            update(schema.M8_ENT_MESURES_COURANTES)
            .values(detail="texte libre")
            .where(schema.M8_ENT_MESURES_COURANTES.c.metric_id == "m8_clics_par_contenu")
        )
    app = FastAPI()
    app.include_router(
        http.creer_router(cnx_factory=stockage.transaction, masqueur=None, cle=lambda: cle, horloge=horloge)
    )
    reponse = TestClient(app).get(
        "/pont-bi/v1/jeux/mesures_courantes.csv",
        headers=_en_tete(_emettre(base, cle, horloge, jeux=["mesures_courantes"])),
    )
    assert reponse.status_code == 500 and reponse.json()["erreur"] == "masqueur_indisponible"
    assert "texte libre" not in reponse.text


def test_les_jeux_ne_declarent_aucune_colonne_de_personne_et_correspondent_aux_tables():
    assert jeux.verifier_coherence() == []
    for jeu in jeux.JEUX.values():
        for colonne in jeu.colonnes:
            assert not any(
                mot in colonne.nom for mot in ("technicien", "client", "courriel", "telephone", "adresse", "nom_")
            )
    assert "technicien_id" not in {c.name for t in entrepot_stockage.tables().values() for c in t.columns}


# ---------------------------------------------------------------------------
# Quotas et journal
# ---------------------------------------------------------------------------
def test_le_quota_de_requetes_refuse_429_avant_toute_donnee_et_se_libere_apres_une_heure(base, cle, horloge, client):
    jeton = _emettre(base, cle, horloge, quota_requetes_heure=2)
    url = "/pont-bi/v1/jeux/chantiers.csv"
    assert client.get(url, headers=_en_tete(jeton)).status_code == 200
    assert client.get(url, headers=_en_tete(jeton)).status_code == 200
    refus = client.get(url, headers=_en_tete(jeton))
    assert refus.status_code == 429 and refus.headers["retry-after"] == "3600"
    assert "wct-fictif" not in refus.text and refus.json()["erreur"] == "quota_requetes"
    horloge.maintenant += 3601
    assert client.get(url, headers=_en_tete(jeton)).status_code == 200


def test_le_quota_de_lignes_refuse_sans_rien_remettre(base, cle, horloge, client):
    jeton = _emettre(base, cle, horloge, jeux=["mesures_courantes"], quota_lignes_jour=45)
    url = "/pont-bi/v1/jeux/mesures_courantes.csv"
    assert client.get(url, headers=_en_tete(jeton)).status_code == 200  # 41 lignes remises (sans les financières)
    refus = client.get(url, headers=_en_tete(jeton))  # 41 + 41 > 45
    assert refus.status_code == 429 and refus.json()["erreur"] == "quota_lignes"
    assert "m8_leads_recus" not in refus.text
    petit = client.get(url + "?limite=4", headers=_en_tete(jeton))  # 41 + 4 = 45 : permis, pile
    assert petit.status_code == 200
    assert client.get(url + "?limite=1", headers=_en_tete(jeton)).status_code == 429  # 46 > 45
    horloge.maintenant += 86401
    assert client.get(url, headers=_en_tete(jeton)).status_code == 200


def test_les_quotas_sont_par_jeton(base, cle, horloge, client):
    a = _emettre(base, cle, horloge, quota_requetes_heure=1, libelle="Jeton A fictif")
    b = _emettre(base, cle, horloge, quota_requetes_heure=1, libelle="Jeton B fictif")
    assert client.get("/pont-bi/v1/jeux/chantiers.csv", headers=_en_tete(a)).status_code == 200
    assert client.get("/pont-bi/v1/jeux/chantiers.csv", headers=_en_tete(a)).status_code == 429
    assert client.get("/pont-bi/v1/jeux/chantiers.csv", headers=_en_tete(b)).status_code == 200


def test_un_refus_avant_authentification_ne_consomme_pas_le_quota_d_un_autre(base, cle, horloge, client):
    jeton = _emettre(base, cle, horloge, quota_requetes_heure=1)
    for _ in range(5):
        assert client.get("/pont-bi/v1/jeux/chantiers.csv", headers={"Authorization": "Bearer x"}).status_code == 401
    assert client.get("/pont-bi/v1/jeux/chantiers.csv", headers=_en_tete(jeton)).status_code == 200


def test_le_journal_dit_qui_quoi_combien_et_jamais_le_secret_ni_le_contenu(base, cle, horloge, client, caplog):
    caplog.set_level(logging.DEBUG)
    jeton = _emettre(base, cle, horloge)
    secret = jeton["jeton"].split(".", 1)[1]
    client.get("/pont-bi/v1/jeux/chantiers.csv", headers=_en_tete(jeton))
    client.get(
        "/pont-bi/v1/jeux/mesures_courantes.csv", headers={"Authorization": f"Bearer opsys-bi:v1:{'0' * 32}.{secret}"}
    )
    client.get("/pont-bi/odata/Chantiers?$filter=a eq 1", headers=_en_tete(jeton))
    with base() as cnx:
        journal = service.acces_recents(cnx, 20)
        bloc = json.dumps(journal, default=str)
    fins = [j for j in journal if j["phase"] == "fin" and j["jeu"] == "chantiers"]
    assert (
        fins and fins[0]["lignes"] == 4 and fins[0]["statut"] == "termine" and fins[0]["jeton_id"] == jeton["jeton_id"]
    )
    assert any(j["statut"] == "refuse" and j["code"] == "non_authentifie" for j in journal)
    assert secret not in bloc and "wct-fictif" not in bloc
    assert secret not in caplog.text and jeton["jeton"] not in caplog.text


def test_le_journal_d_acces_est_append_only(base, cle, horloge, client):
    jeton = _emettre(base, cle, horloge)
    client.get("/pont-bi/v1/jeux/chantiers.csv", headers=_en_tete(jeton))
    for requete in ("UPDATE pont_bi_acces SET statut = 'refuse'", "DELETE FROM pont_bi_acces"):
        with pytest.raises(DBAPIError, match="immuable"), base() as cnx:
            cnx.execute(text(requete))
    with base() as cnx:
        assert service.acces_recents(cnx, 5)


# ---------------------------------------------------------------------------
# OData v4 minimal
# ---------------------------------------------------------------------------
def test_odata_document_de_service_et_metadata(base, cle, horloge, client):
    jeton = _emettre(base, cle, horloge, jeux=["chantiers", "devis"])
    service_doc = client.get("/pont-bi/odata/", headers=_en_tete(jeton)).json()
    assert [v["name"] for v in service_doc["value"]] == ["Chantiers", "Devis"]
    reponse = client.get("/pont-bi/odata/$metadata", headers=_en_tete(jeton))
    assert reponse.headers["odata-version"] == "4.0" and reponse.headers["content-type"].startswith("application/xml")
    racine = ET.fromstring(reponse.text)
    types = {e.get("Name"): e for e in racine.iter("{http://docs.oasis-open.org/odata/ns/edm}EntityType")}
    assert set(types) == {"Chantiers", "Devis"}
    proprietes = {p.get("Name") for p in types["Chantiers"].iter("{http://docs.oasis-open.org/odata/ns/edm}Property")}
    assert "wct_id" in proprietes and "marge_reelle_cad" not in proprietes  # la portée financière s'y applique aussi
    cle_ref = [k.get("Name") for k in types["Chantiers"].iter("{http://docs.oasis-open.org/odata/ns/edm}PropertyRef")]
    assert cle_ref == ["wct_id"]


def test_odata_collection_top_skip_count_select_et_lien_suivant(base, cle, horloge, client):
    jeton = _emettre(base, cle, horloge)
    reponse = client.get(
        "/pont-bi/odata/Chantiers?$top=2&$skip=1&$count=true&$select=wct_id,devis_id", headers=_en_tete(jeton)
    )
    corps = reponse.json()
    assert reponse.status_code == 200 and corps["@odata.count"] == 4 and len(corps["value"]) == 2
    assert set(corps["value"][0]) == {"wct_id", "devis_id"} and corps["@odata.context"].endswith("$metadata#Chantiers")
    assert corps["@odata.nextLink"].endswith("/pont-bi/odata/Chantiers?$top=2&$skip=3")
    fin = client.get("/pont-bi/odata/Chantiers?$top=2&$skip=3", headers=_en_tete(jeton)).json()
    assert len(fin["value"]) == 1 and "@odata.nextLink" not in fin and "@odata.count" not in fin


@pytest.mark.parametrize(
    "option",
    ["$filter=wct_id eq 'x'", "$orderby=wct_id", "$expand=x", "$search=a", "$apply=x", "$skiptoken=1", "$format=json"],
)
def test_odata_refuse_ce_qu_il_ne_fait_pas_au_lieu_de_l_ignorer(base, cle, horloge, client, option):
    jeton = _emettre(base, cle, horloge)
    reponse = client.get(f"/pont-bi/odata/Chantiers?{option}", headers=_en_tete(jeton))
    assert reponse.status_code == 501 and reponse.json()["error"]["code"] == "option_non_prise_en_charge"
    assert "wct-fictif" not in reponse.text


@pytest.mark.parametrize(
    "requete",
    [
        "$top=0",
        "$top=5001",
        "$top=abc",
        "$skip=-1",
        "$count=oui",
        "$select=inconnue",
        "$select=marge_reelle_cad",
        "$select=wct_id,wct_id",
        "x=1",
        "$top=1&$top=2",
    ],
)
def test_odata_refuse_les_valeurs_illisibles_et_les_colonnes_hors_portee(base, cle, horloge, client, requete):
    jeton = _emettre(base, cle, horloge)
    reponse = client.get(f"/pont-bi/odata/Chantiers?{requete}", headers=_en_tete(jeton))
    assert reponse.status_code == 400 and "error" in reponse.json()


def test_odata_entite_inconnue_et_jeu_non_permis(base, cle, horloge, client):
    jeton = _emettre(base, cle, horloge, jeux=["chantiers"])
    assert client.get("/pont-bi/odata/Inconnue", headers=_en_tete(jeton)).status_code == 404
    refus = client.get("/pont-bi/odata/Devis", headers=_en_tete(jeton))
    assert refus.status_code == 403 and "error" in refus.json()
    assert client.get("/pont-bi/odata/Chantiers").status_code == 401


def test_la_ligne_du_jeton_revoque_suffit_meme_si_le_coffre_n_etait_pas_revoque(base, cle, horloge, client):
    jeton = _emettre(base, cle, horloge)
    assert client.get("/pont-bi/v1/jeux", headers=_en_tete(jeton)).status_code == 200
    with base() as cnx:  # seule la table est touchée : le secret du coffre reste actif
        cnx.execute(update(schema.PONT_BI_JETONS).values(revoque=True).where(
            schema.PONT_BI_JETONS.c.jeton_id == jeton["jeton_id"]))
        assert coffre.metadonnees(cnx, f"pont-bi.{jeton['jeton_id']}")["etat"] == "actif"
    assert client.get("/pont-bi/v1/jeux", headers=_en_tete(jeton)).status_code == 401


def _lecture_seule_active(cnx) -> bool:
    """SQLite : `PRAGMA query_only` ; PostgreSQL : mode d'accès de la transaction courante."""
    if cnx.dialect.name == "postgresql":
        return cnx.exec_driver_sql("SHOW transaction_read_only").scalar_one() == "on"
    return bool(cnx.exec_driver_sql("PRAGMA query_only").scalar_one())


def test_chaque_export_se_lit_dans_une_transaction_en_lecture_seule(base, cle, horloge, client, monkeypatch):
    ouvertures = []
    original = service.lecture_seule

    def espion(cnx):
        ouvertures.append(_lecture_seule_active(cnx))  # avant le bloc : OFF
        contexte = original(cnx)
        return contexte

    monkeypatch.setattr(service, "lecture_seule", espion)
    jeton = _emettre(base, cle, horloge)
    for chemin in ("/pont-bi/v1/jeux/chantiers.csv", "/pont-bi/v1/jeux/chantiers.jsonl", "/pont-bi/odata/Chantiers"):
        assert client.get(chemin, headers=_en_tete(jeton)).status_code == 200
    assert ouvertures == [False, False, False]  # trois exports, trois ouvertures du mode lecture seule


def test_pendant_un_export_le_moteur_refuse_toute_ecriture(base, cle, horloge, client, monkeypatch):
    essais = []
    original = service.lire_jeu

    def lire_et_tenter_d_ecrire(cnx, *args, **kwargs):
        try:
            with cnx.begin_nested():  # point de sauvegarde : PostgreSQL annule toute la transaction sur une erreur
                cnx.execute(update(schema.M8_ENT_DIM_CHANTIER).values(devis_id="pirate"))
            essais.append("ECRITURE-PERMISE")
        except DBAPIError:
            essais.append("refusee")
        return original(cnx, *args, **kwargs)

    monkeypatch.setattr(service, "lire_jeu", lire_et_tenter_d_ecrire)
    jeton = _emettre(base, cle, horloge)
    assert client.get("/pont-bi/v1/jeux/chantiers.csv", headers=_en_tete(jeton)).status_code == 200
    assert essais == ["refusee"]
