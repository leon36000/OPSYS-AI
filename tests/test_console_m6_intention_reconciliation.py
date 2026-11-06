"""Réconciliation admin M6 : fixtures synthétiques, aucune donnée d'exploitation."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, select

from opsys import identite
from opsys.console import application
from opsys.console.securite import Configuration
from opsys.departements import charger_departements
from opsys.stockage import codec
from opsys.stockage.schema import MUTATIONS_APPLIQUEES

FICTIF = True
MOT_DE_PASSE = "mot-de-passe-reconciliation-fictif-2026"
APPAREIL = "appareil-reconciliation-fictif"
OUTIL = "m6_declarer_materiaux_utilises"


@pytest.fixture
def monde(session):
    with session() as cnx:
        identite.creer_personne(cnx, "admin.reconciliation.fictif", "Admin fictif", MOT_DE_PASSE, ["admin"])
        identite.creer_personne(cnx, "employe.reconciliation.fictif", "Employé fictif", MOT_DE_PASSE, ["employee"])
    app = application.creer_application(
        Configuration("secret-session-reconciliation-fictif-" + "x" * 32, cookie_securise=False),
        charger_departements(), session,
    )
    with TestClient(app, base_url="https://testserver/opsys") as client:
        yield client


def _connecter(client: TestClient, personne: str = "admin.reconciliation.fictif") -> str:
    reponse = client.post(
        "/connexion", data={"identifiant": personne, "mot_de_passe": MOT_DE_PASSE}, follow_redirects=False,
    )
    assert reponse.status_code == 303
    return client.get("/api/session").json()["csrf"]


def _claim(session, cle: str, *, outil: str = OUTIL, statut: str = "ok", reponse=None, auteur=None) -> None:
    with session() as cnx:
        cnx.execute(insert(MUTATIONS_APPLIQUEES).values(
            appareil=APPAREIL,
            cle_idempotence=cle,
            outil=outil,
            empreinte_arguments="a" * 64,
            reponse=codec.encoder(reponse),
            horodatage_appareil="2026-11-06T12:00:00+00:00",
            recu_le="2026-11-06T12:00:01+00:00",
            statut=statut,
            personne_origine=auteur,
        ))


def _etat(client: TestClient, csrf: str, cle: str, *, appareil: str = APPAREIL, corps=None):
    corps = corps if corps is not None else {"appareil": appareil, "cle_idempotence": cle}
    return client.post(
        "/api/m6/intention/etat", json=corps, headers={"X-CSRF-Token": csrf},
    )


def _accepte():
    return {
        "ok": True,
        "resultat": {
            "accepte": True,
            "resultat": {
                "wct_id": "wct-fictif-sensible",
                "lignes": [{"cout_unitaire": "987.65", "hash_maillon": "h" * 64}],
                "personne": "personne-fictive-sensible",
            },
            "registre": {"taille": 3, "hash_tete": "f" * 64},
        },
    }


@pytest.mark.parametrize(
    ("statut", "reponse", "attendu"),
    [
        ("ok", _accepte(), "acceptee"),
        ("ok", {"ok": True, "resultat": {"accepte": False, "verdict": {"code": "REJ-WCT-INCONNU"}}}, "refusee"),
        ("refus_metier", {"ok": False, "erreur": "refus_metier", "details": "détail fictif"}, "refusee"),
        ("ok", {"ok": False, "erreur": "refus_metier", "details": "incohérent"}, "indeterminee"),
        ("refus_metier", {"ok": False, "erreur": [], "details": []}, "indeterminee"),
        ("en_attente_approbation", {"ok": True, "statut": "en_attente_approbation"}, "indeterminee"),
        ("en_cours", None, "indeterminee"),
    ],
)
def test_mapping_ferme_et_sans_detail(monde, session, statut, reponse, attendu):
    csrf = _connecter(monde)
    cle = f"intention-reconciliation-{attendu}-{statut}"
    _claim(session, cle, statut=statut, reponse=reponse, auteur=None)  # ancien ACK sans auteur conservé

    response = _etat(monde, csrf, cle)

    assert response.status_code == 200
    assert response.json() == {"etat": attendu}
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "987.65" not in response.text
    assert "wct-fictif-sensible" not in response.text
    assert "personne-fictive-sensible" not in response.text
    assert "hash_maillon" not in response.text and "hash_tete" not in response.text


@pytest.mark.parametrize(
    ("outil", "statut", "reponse"),
    [
        ("m6_lire_contexte_materiaux_appareil", "ok", _accepte()),
        (OUTIL, "ok", {"ok": True, "resultat": {"accepte": True}}),
        (OUTIL, "ok", "{JSON invalide"),
        (OUTIL, "ok", {"ok": True, "resultat": {"accepte": True}, "trop_grand": "x" * 17_000}),
    ],
)
def test_absence_outil_inattendu_et_reponse_invalide_sont_indetermines(monde, session, outil, statut, reponse):
    csrf = _connecter(monde)
    cle = "intention-reconciliation-inconnue"
    _claim(session, cle, outil=outil, statut=statut, reponse=reponse)

    assert _etat(monde, csrf, cle).json() == {"etat": "indeterminee"}
    assert _etat(monde, csrf, "intention-absente").json() == {"etat": "indeterminee"}


def test_la_cle_seule_ne_designe_jamais_un_autre_appareil(monde, session):
    csrf = _connecter(monde)
    cle = "intention-reconciliation-paire-exacte"
    _claim(session, cle, reponse=_accepte())

    assert _etat(monde, csrf, cle, appareil="autre-appareil-fictif").json() == {"etat": "indeterminee"}
    assert _etat(monde, csrf, cle).json() == {"etat": "acceptee"}


def test_corps_ferme_csrf_et_methode_sans_identifiants_dans_url(monde):
    csrf = _connecter(monde)
    assert _etat(monde, csrf, "intention-invalide", corps={
        "appareil": APPAREIL, "cle_idempotence": "intention-invalide", "outil": OUTIL,
    }).json() == {"etat": "indeterminee"}
    assert monde.post(
        "/api/m6/intention/etat", json={"appareil": APPAREIL, "cle_idempotence": "cle-fictive"},
    ).status_code == 403
    assert _etat(monde, csrf, "intention-query-interdite").json() == {"etat": "indeterminee"}
    assert monde.post(
        "/api/m6/intention/etat?appareil=appareil-fictif&cle_idempotence=cle-fictive",
        json={"appareil": APPAREIL, "cle_idempotence": "cle-fictive"},
        headers={"X-CSRF-Token": csrf},
    ).json() == {"etat": "indeterminee"}
    assert monde.get("/api/m6/intention/etat?appareil=appareil-fictif&cle_idempotence=cle-fictive").status_code == 405


def test_json_trop_profond_est_un_400_borne(monde):
    csrf = _connecter(monde)
    profond = "[" * 2000 + "0" + "]" * 2000
    response = monde.post(
        "/api/m6/intention/etat", content=profond,
        headers={"Content-Type": "application/json", "X-CSRF-Token": csrf},
    )
    assert response.status_code == 400


def test_session_absente_non_admin_et_admin_revoque_sont_refuses(monde, session):
    corps = {"appareil": APPAREIL, "cle_idempotence": "intention-absence-session"}
    assert monde.post("/api/m6/intention/etat", json=corps).status_code == 401

    csrf = _connecter(monde, "employe.reconciliation.fictif")
    assert _etat(monde, csrf, "intention-non-admin").status_code == 403
    csrf_admin = _connecter(monde)
    with session() as cnx:
        identite.retirer_role(cnx, "admin.reconciliation.fictif", "admin")
    assert _etat(monde, csrf=csrf_admin, cle="intention-admin-revoque").status_code == 403


def test_endpoint_ne_change_pas_le_claim(monde, session):
    csrf = _connecter(monde)
    cle = "intention-reconciliation-lecture-seule"
    _claim(session, cle, reponse=_accepte(), auteur=None)
    with session() as cnx:
        avant = [dict(ligne) for ligne in cnx.execute(select(MUTATIONS_APPLIQUEES)).mappings().all()]

    assert _etat(monde, csrf, cle).json() == {"etat": "acceptee"}

    with session() as cnx:
        apres = [dict(ligne) for ligne in cnx.execute(select(MUTATIONS_APPLIQUEES)).mappings().all()]
    assert apres == avant
