"""Réconciliation admin M6 : fixtures synthétiques, aucune donnée d'exploitation."""

from __future__ import annotations

from urllib.parse import urlencode

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


def _formulaire(client, csrf: str, *, appareil: str = APPAREIL, cle: str = "intention-formulaire-fictive"):
    return client.post(
        "/materiaux/intention",
        data={"csrf": csrf, "appareil": appareil, "cle_idempotence": cle},
    )


def test_formulaire_admin_est_post_csrf_no_store_et_sans_identifiants_url(monde):
    csrf = _connecter(monde)
    response = monde.get("/materiaux/intention")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert 'method="post"' in response.text
    assert 'action="/opsys/materiaux/intention"' in response.text
    assert 'name="csrf"' in response.text and csrf in response.text
    assert 'name="appareil"' in response.text
    assert 'name="cle_idempotence"' in response.text
    assert "appareil-fictif" not in str(response.url) and "intention-fictive" not in str(response.url)


def test_formulaire_legacy_accepte_et_redaction_complete(monde, session):
    csrf = _connecter(monde)
    cle = "intention-formulaire-legacy-fictive"
    _claim(session, cle, reponse=_accepte(), auteur=None)
    with session() as cnx:
        avant = dict(cnx.execute(select(MUTATIONS_APPLIQUEES).where(
            MUTATIONS_APPLIQUEES.c.appareil == APPAREIL,
            MUTATIONS_APPLIQUEES.c.cle_idempotence == cle,
        )).mappings().one())

    response = _formulaire(monde, csrf, cle=cle)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "Résultat : Acceptée" in response.text
    assert "Cette vérification n’a rien rejoué." in response.text
    for sensible in ("987.65", "wct-fictif-sensible", "personne-fictive-sensible",
                     "hash_maillon", "hash_tete", APPAREIL, cle):
        assert sensible not in response.text
    with session() as cnx:
        apres = dict(cnx.execute(select(MUTATIONS_APPLIQUEES).where(
            MUTATIONS_APPLIQUEES.c.appareil == APPAREIL,
            MUTATIONS_APPLIQUEES.c.cle_idempotence == cle,
        )).mappings().one())
    assert apres == avant


def test_formulaire_absence_et_recu_legacy_invalide_sont_indetermines(monde, session):
    csrf = _connecter(monde)
    legacy = "intention-formulaire-legacy-invalide"
    _claim(session, legacy, statut="en_cours", reponse={"ok": True}, auteur=None)

    absent = _formulaire(monde, csrf, cle="intention-formulaire-absente")
    ancien = _formulaire(monde, csrf, cle=legacy)

    assert "Résultat : Indéterminée" in absent.text
    assert "Résultat : Indéterminée" in ancien.text
    assert absent.text.count("Le reçu est absent ou ne permet pas") == 1
    assert ancien.text.count("Le reçu est absent ou ne permet pas") == 1
    assert "intention-formulaire-absente" not in absent.text
    assert legacy not in ancien.text


def test_formulaire_refuse_n_expose_ni_verdict_ni_detail(monde, session):
    csrf = _connecter(monde)
    cle = "intention-formulaire-refus-fictive"
    _claim(session, cle, reponse={
        "ok": True,
        "resultat": {
            "accepte": False,
            "verdict": {"code": "REJ-WCT-INCONNU", "detail": "détail-fictif-confidentiel"},
        },
    })

    response = _formulaire(monde, csrf, cle=cle)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "Résultat : Refusée" in response.text
    assert "REJ-WCT-INCONNU" not in response.text
    assert "détail-fictif-confidentiel" not in response.text
    assert APPAREIL not in response.text and cle not in response.text


def test_formulaire_refuse_non_admin_csrf_invalide_url_et_role_revoque(monde, session):
    csrf_employe = _connecter(monde, "employe.reconciliation.fictif")
    assert monde.get("/materiaux/intention").status_code == 403
    assert _formulaire(monde, csrf_employe).status_code == 403

    csrf_admin = _connecter(monde, "admin.reconciliation.fictif")
    assert monde.post(
        "/materiaux/intention",
        data={"csrf": "faux", "appareil": APPAREIL, "cle_idempotence": "cle-fictive"},
    ).status_code == 403
    assert monde.post(
        "/materiaux/intention?appareil=appareil-fictif&cle_idempotence=cle-fictive",
        data={"csrf": csrf_admin, "appareil": APPAREIL, "cle_idempotence": "cle-fictive"},
    ).status_code == 400
    assert monde.get("/materiaux/intention?appareil=appareil-fictif").status_code == 400
    with session() as cnx:
        identite.retirer_role(cnx, "admin.reconciliation.fictif", "admin")
    assert _formulaire(monde, csrf_admin).status_code == 403


def test_formulaire_refuse_champs_ouverts_et_doublons(monde):
    csrf = _connecter(monde)
    contenu = urlencode([
        ("csrf", csrf), ("appareil", APPAREIL), ("appareil", "autre-appareil-fictif"),
        ("cle_idempotence", "cle-fictive"),
    ])
    response = monde.post(
        "/materiaux/intention", content=contenu,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 400

    response = monde.post(
        "/materiaux/intention",
        data={"csrf": csrf, "appareil": APPAREIL, "cle_idempotence": "cle-fictive", "outil": OUTIL},
    )
    assert response.status_code == 400


def test_lien_reconciliation_est_discretement_dans_les_commandes():
    from opsys.console.commandes_ui import rendre_liste

    html = rendre_liste(
        {"comptes": {}, "pos": [], "total": 0, "suivant": None},
        "/opsys", None, False, 0,
    )
    assert 'href="/opsys/materiaux/intention"' in html
    assert "Vérifier une intention de matériaux" in html


def test_identifiants_incompatibles_postgresql_sont_indetermines(monde):
    from unittest.mock import Mock

    from opsys.console.m6_intention_reconciliation import lire_etat

    connexion = Mock()
    assert lire_etat(connexion, "appareil\x00fictif", "cle-fictive") == "indeterminee"
    assert lire_etat(connexion, APPAREIL, "cle\x00fictive") == "indeterminee"
    assert lire_etat(connexion, "appareil\ud800", "cle-fictive") == "indeterminee"
    connexion.execute.assert_not_called()

    csrf = _connecter(monde)
    for invalide in ("appareil\x00fictif", "cle\x00fictive", "cle\navec-controle"):
        assert _etat(monde, csrf, "intention-sans-requete", appareil=invalide).json() == {
            "etat": "indeterminee",
        }
    api = monde.post(
        "/api/m6/intention/etat",
        json={"appareil": APPAREIL, "cle_idempotence": "cle\x00fictive"},
        headers={"X-CSRF-Token": csrf},
    )
    form = _formulaire(monde, csrf, cle="cle\x00fictive")
    assert api.json() == {"etat": "indeterminee"}
    assert form.status_code == 200
    assert "Résultat : Indéterminée" in form.text
