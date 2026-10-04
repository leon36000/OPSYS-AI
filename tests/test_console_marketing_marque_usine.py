"""R44a : vraie configuration HTTP, SQLite et usine ; aucune fixture de chargeur marque."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from m7_marketing import outils as outils_m7
from m7_marketing.brand import registre as brand_registre
from m7_marketing.usine import service
from sqlalchemy import update

from opsys import contexte, identite, stockage
from opsys.console import application
from opsys.console.securite import Configuration
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import REGISTRES

PASSWORD = "mot-de-passe-r44-fictif-123456"


@pytest.fixture(autouse=True)
def _base_isolee(monkeypatch):
    monkeypatch.delenv(stockage.ENV_URL, raising=False)


@pytest.fixture
def client(session):
    with session() as cnx:
        identite.creer_personne(cnx, "owner-r44", "Propriétaire fictif", PASSWORD, ["admin", "nathan_owner"])
        identite.creer_personne(cnx, "admin-r44", "Admin fictif", PASSWORD, ["admin"])
        stockage.maillons(*service.REGISTRE_WCT_RECUS).append(
            {
                "wct_id": "wct-r44-fictif",
                "intervention_id": "intervention-r44-fictif",
                "lead_id": "lead-r44-fictif",
                "technicien_id": "tech-r44-fictif",
                "devis_id": "devis-r44-fictif",
                "hash_maillon": "ab" * 32,
                "horodatage_completion": "2026-10-01T15:00:00-04:00",
                "statut": "completed_verified",
                "ville": "Repentigny",
                "type_travaux": "gouttières",
                "photos": [],
                "client_satisfait": True,
                "consentement_marketing": True,
                "consentement_recueilli_par": "tech-r44-fictif",
                "consentement_recueilli_le": "2026-10-01T19:00:00+00:00",
                "consentement_version_texte": "fr-v1",
            }
        )
    app = application.creer_application(
        Configuration("secret-r44-fictif-" + "x" * 64, cookie_securise=False, prefixe="/opsys"), None, session
    )
    with TestClient(app, base_url="https://testserver/opsys") as testclient:
        yield testclient


def _login(client, personne="owner-r44"):
    r = client.post("/connexion", data={"identifiant": personne, "mot_de_passe": PASSWORD}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return client.get("/api/session").json()["csrf"]


def _marque(client, csrf, nom="Marque fictive R44", *, revision_attendue=0, **options):
    return client.post(
        "/api/marketing/marque",
        headers={"x-csrf-token": csrf},
        json={
            "mutation_id": "marque-" + nom,
            "revision_attendue": revision_attendue,
            "profil": {
                "name": nom,
                "tagline": "Travaux avec soin",
                "tone": "professionnel et factuel",
                "colors": ["#123456"],
                "langue": "fr",
                **options,
            },
        },
    )


def _action(client, csrf, action, mutation=None, **arguments):
    return client.post(
        "/api/marketing/calendrier",
        headers={"x-csrf-token": csrf},
        json={"action": action, "mutation_id": mutation or action + str(arguments), **arguments},
    )


def _resultat(r):
    assert r.status_code == 200 and r.json()["ok"], r.text
    v = r.json()["resultat"]
    while isinstance(v, dict) and "resultat" in v:
        v = v["resultat"]
    return v


def _contenus(client):
    contenus, decalage = [], 0
    while True:
        r = client.get("/api/marketing/calendrier", params={"decalage": decalage})
        assert r.status_code == 200, r.text
        valeur = r.json()["resultat"]
        contenus.extend(valeur["contenus"])
        decalage = valeur["pagination"]["suivant"]
        if decalage is None:
            return contenus


def _proposer(client, csrf, mutation="proposer-r44"):
    _resultat(_action(client, csrf, "proposer_contenus", mutation, wct_id="wct-r44-fictif"))
    return _contenus(client)


def _creneau(client, csrf, contenu):
    cid = contenu["contenu_id"]
    _resultat(_action(client, csrf, "decider_contenu", "decision-" + cid, contenu_id=cid, decision="approuver"))
    slot = _resultat(
        _action(
            client,
            csrf,
            "proposer_creneau",
            "slot-" + cid,
            contenu_id=cid,
            planifie_le=(datetime.now(UTC) + timedelta(days=3)).isoformat(),
        )
    )
    _resultat(
        _action(
            client, csrf, "decider_creneau", "decision-slot-" + cid, creneau_id=slot["creneau_id"], decision="approuver"
        )
    )
    return slot


def _registre(nom):
    with stockage.transaction():
        return list(stockage.maillons("m07-marketing", nom))


def test_post_marque_wct_cinq_brouillons_decisions_et_export_reels(client):
    csrf = _login(client)
    _resultat(_marque(client, csrf))
    contenus = _proposer(client, csrf)
    assert len(contenus) == 5
    for contenu in contenus:
        assert contenu["marque_source"]["source"] == "brand_profiles"
        assert contenu["marque_source"]["revision"] == 1
        assert contenu["fraicheur_marque"] == "courante"
        assert "Marque fictive R44" in contenu["texte"]
        slot = _creneau(client, csrf, contenu)
        export = _resultat(
            _action(client, csrf, "exporter_creneau", "export-" + contenu["contenu_id"], creneau_id=slot["creneau_id"])
        )
        assert "paquet" in export
        assert export["paquet"]["marque_source"] == contenu["marque_source"]
    assert len(_registre("contenus_chantier")) == 5
    assert len(_registre("decisions_contenu")) == 5
    assert len(_registre("exports_paquet")) == 5


@pytest.mark.parametrize("apres_export", [False, True])
def test_changement_marque_refuse_export_et_rejeu_puis_revision_explicite(client, apres_export):
    csrf = _login(client)
    _resultat(_marque(client, csrf))
    contenus = _proposer(client, csrf)
    propositions_initiales = _registre("contenus_chantier")
    contenu = next(c for c in contenus if c["plateforme"] == "facebook")
    slot = _creneau(client, csrf, contenu)
    if apres_export:
        _resultat(_action(client, csrf, "exporter_creneau", "export-r44", creneau_id=slot["creneau_id"]))
    avant = {nom: _registre(nom) for nom in ("decisions_contenu", "exports_paquet", "exports_calendrier")}
    _resultat(_marque(client, csrf, "Nouvelle marque fictive", revision_attendue=1))
    refuse = _action(client, csrf, "exporter_creneau", "export-r44", creneau_id=slot["creneau_id"])
    assert refuse.status_code == 409, refuse.text
    assert {nom: _registre(nom) for nom in avant} == avant
    nouvelles = _proposer(client, csrf, "reproposer-r44")
    assert len(nouvelles) == 5
    assert all(c["revision"] == 2 and c["approval_status"] == "PROPOSE" for c in nouvelles)
    assert all(c["marque_source"]["revision"] == 2 for c in nouvelles)
    assert len(_registre("contenus_chantier")) == 10
    assert _registre("contenus_chantier")[:5] == propositions_initiales


def test_options_metier_typées_et_idempotence(client):
    csrf = _login(client)
    options = {
        "site_url": "https://exemple-fictif.ca/",
        "hashtags": ["#Travaux"],
        "mentions": [],
        "garanties_validees": [],
        "heures_publication": {"facebook": "18:30"},
    }
    premiere = _marque(client, csrf, **options)
    _resultat(premiere)
    _resultat(_marque(client, csrf, **options))
    assert len(_registre("brand_profiles")) == 1
    assert _registre("brand_profiles")[0]["profil"]["site_url"] == options["site_url"]
    _resultat(_action(client, csrf, "proposer_contenus", "cle-stable", wct_id="wct-r44-fictif"))
    _resultat(_action(client, csrf, "proposer_contenus", "cle-stable", wct_id="wct-r44-fictif"))
    assert len(_registre("contenus_chantier")) == 5
    conflit = _action(client, csrf, "proposer_contenus", "cle-stable", wct_id="autre-wct-fictif")
    assert conflit.status_code == 409


def test_cas_options_historiques_replay_et_conflit_de_preuve(client, session):
    csrf = _login(client)
    with session():
        profil = {
            "name": "Ancienne marque fictive",
            "tagline": "Travaux avec soin",
            "tone": "factuel",
            "colors": ["#123456"],
            "langue": "fr",
            "site_url": "https://exemple-fictif.ca/",
            "option_historique": {"zones": ["Repentigny"]},
        }
        assert brand_registre.enregistrer(profil, "owner-r44", "2026-10-02T12:00:00+00:00")["statut"] == "configure"
    commande = {
        "mutation_id": "cas-r44",
        "revision_attendue": 1,
        "profil": {k: v for k, v in profil.items() if k in {"name", "tagline", "tone", "colors", "langue"}},
    }
    commande["profil"]["tagline"] = "Nouvelle signature fictive"

    def envoyer(payload):
        return client.post("/api/marketing/marque", json=payload, headers={"x-csrf-token": csrf})

    sans_revision = {k: v for k, v in commande.items() if k != "revision_attendue"}
    assert envoyer({**sans_revision, "mutation_id": "cas-absent"}).status_code == 409
    assert envoyer({**commande, "revision_attendue": True, "mutation_id": "cas-invalide"}).status_code == 400
    assert len(_registre("brand_profiles")) == 1
    _resultat(envoyer(commande))
    courant = _registre("brand_profiles")[-1]["profil"]
    assert courant["option_historique"] == profil["option_historique"]
    assert courant["site_url"] == profil["site_url"]
    assert courant["tagline"] == "Nouvelle signature fictive"
    _resultat(envoyer(commande))
    assert envoyer({**commande, "revision_attendue": 2}).status_code == 409
    assert envoyer({**commande, "mutation_id": "cas-perime"}).status_code == 409
    assert len(_registre("brand_profiles")) == 2


def test_marque_changee_avant_approbation_puis_rejet_motive_sans_promouvoir(client):
    csrf = _login(client)
    _resultat(_marque(client, csrf))
    contenu = next(c for c in _proposer(client, csrf) if c["plateforme"] == "facebook")
    _resultat(_marque(client, csrf, "Nouvelle marque fictive", revision_attendue=1))
    refus = _action(
        client, csrf, "decider_contenu", "approve-stale", contenu_id=contenu["contenu_id"], decision="approuver"
    )
    assert refus.status_code == 409
    assert _registre("decisions_contenu") == []
    _resultat(
        _action(
            client,
            csrf,
            "decider_contenu",
            "reject-stale",
            contenu_id=contenu["contenu_id"],
            decision="rejeter",
            motif="La marque a changé, texte à reprendre.",
        )
    )
    assert _registre("decisions_contenu")[0]["decision"] == "REJECTED"
    assert _registre("exports_paquet") == []
    page = client.get("/marketing/calendrier")
    assert "Reproposer avec la marque courante" in page.text


@pytest.mark.parametrize("ancien_approuve", [False, True])
def test_ancien_contenu_sans_preuve_pas_de_nouvelle_approbation_ni_export(client, session, ancien_approuve):
    csrf = _login(client)
    _resultat(_marque(client, csrf))
    contenu = next(c for c in _proposer(client, csrf) if c["plateforme"] == "facebook")
    slot = _creneau(client, csrf, contenu) if ancien_approuve else None
    with session() as cnx:
        propositions = list(stockage.maillons(*service.REGISTRE_CONTENUS_CHANTIER))
        rang = next(i for i, p in enumerate(propositions) if p["contenu_id"] == contenu["contenu_id"])
        propositions[rang].pop("marque_source")  # fixture historique explicite, pas une nouvelle attribution
        cnx.execute(
            update(REGISTRES)
            .where(
                REGISTRES.c.departement == "m07-marketing",
                REGISTRES.c.registre == "contenus_chantier",
                REGISTRES.c.rang == rang,
            )
            .values(maillon=codec.encoder(propositions[rang]))
        )
    historique = _registre("contenus_chantier")
    decisions = _registre("decisions_contenu")
    if slot is not None:
        refus = _action(client, csrf, "exporter_creneau", "export-legacy", creneau_id=slot["creneau_id"])
    else:
        refus = _action(
            client, csrf, "decider_contenu", "approve-legacy", contenu_id=contenu["contenu_id"], decision="approuver"
        )
    assert refus.status_code == 409
    assert _registre("decisions_contenu") == decisions
    assert _registre("exports_paquet") == []
    repris = _proposer(client, csrf, "reprendre-legacy")
    facebook = next(c for c in repris if c["plateforme"] == "facebook")
    assert facebook["revision"] == 2 and facebook["approval_status"] == "PROPOSE"
    assert _registre("contenus_chantier")[:5] == historique


@pytest.mark.parametrize("retrait", ["role", "consentement"])
def test_rejeu_export_revalide_role_et_consentement(client, session, retrait):
    csrf = _login(client)
    _resultat(_marque(client, csrf))
    contenu = next(c for c in _proposer(client, csrf) if c["plateforme"] == "facebook")
    slot = _creneau(client, csrf, contenu)
    _resultat(_action(client, csrf, "exporter_creneau", "export-cache", creneau_id=slot["creneau_id"]))
    avant = {nom: _registre(nom) for nom in ("decisions_contenu", "exports_paquet", "exports_calendrier")}
    if retrait == "role":
        with session() as cnx:
            identite.retirer_role(cnx, "owner-r44", "nathan_owner")
    else:
        outil = next(o for o in outils_m7.outils() if o.nom == "m7_enregistrer_retrait_consentement_marketing")
        with contexte.appele_par_appareil(contexte.IdentiteAppelante("owner-r44", "admin")):
            r = executer_atomique(
                outil, {"wct_id": "wct-r44-fictif", "canal": "courriel", "horodatage": "2026-10-02T12:00:00+00:00"}
            )
        assert r["ok"] and r["resultat"]["accepte"], r
    refuse = _action(client, csrf, "exporter_creneau", "export-cache", creneau_id=slot["creneau_id"])
    assert refuse.status_code == (403 if retrait == "role" else 409), refuse.text
    assert {nom: _registre(nom) for nom in avant} == avant


def test_csrf_et_admin_non_proprietaire_ne_changent_pas_marque(client):
    csrf = _login(client, "admin-r44")
    avant = _registre("brand_profiles")
    assert _marque(client, csrf).status_code == 403
    _login(client)
    assert _marque(client, "csrf-invalide").status_code == 403
    assert _registre("brand_profiles") == avant


def test_recu_mcp_generique_historique_ne_revalide_pas_la_marque(client, session):
    """Limite SDK existante : reçu rejoué ≠ nouveau travail ni refus métier actualisé."""
    from pathlib import Path

    from opsys import idempotence
    from opsys.capacites import Capacites
    from opsys.departements import lire_manifeste

    csrf = _login(client)
    _resultat(_marque(client, csrf))
    dept = lire_manifeste(Path("departments/m07-marketing"))
    cap = Capacites({dept.id: dept}, session, memoire=False, limite_sortie=10000)
    meta = idempotence.Meta("proposition-mcp-r44", "appareil-fictif-r44", "2026-10-02T12:00:00+00:00")
    with contexte.appele_par_appareil(contexte.IdentiteAppelante("owner-r44", "admin")):
        initial = cap.appeler("m7_proposer_contenus_chantier", {"wct_id": "wct-r44-fictif"}, meta)
    assert initial["ok"] and initial["resultat"]["contenus"], initial
    historique = _registre("contenus_chantier")
    _resultat(_marque(client, csrf, "Nouvelle marque fictive", revision_attendue=1))
    with contexte.appele_par_appareil(contexte.IdentiteAppelante("owner-r44", "admin")):
        replay = cap.appeler("m7_proposer_contenus_chantier", {"wct_id": "wct-r44-fictif"}, meta)
    assert replay["rejoue"] is True and replay["resultat"] == initial["resultat"]
    assert _registre("contenus_chantier") == historique
    assert all(c["fraicheur_marque"] == "perimee" for c in _contenus(client))


@pytest.mark.parametrize("nom", ["", "   "])
def test_nom_vide_est_un_diagnostic_metier_pas_une_erreur_interne(client, nom):
    csrf = _login(client)
    r = _marque(client, csrf, nom)
    assert r.status_code in {400, 409}
    assert _registre("brand_profiles") == []


def test_deux_ecritures_concurrentes_meme_cas_une_seule_revision(client):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    csrf = _login(client)
    _resultat(_marque(client, csrf))
    depart = Barrier(2)

    def soumettre(nom):
        depart.wait(timeout=5)
        return _marque(client, csrf, nom, revision_attendue=1).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        resultats = list(pool.map(soumettre, ["Marque concurrente fictive A", "Marque concurrente fictive B"]))
    assert sorted(resultats) == [200, 409]
    assert [p["revision"] for p in _registre("brand_profiles")] == [1, 2]


def test_premiere_ligne_hors_budget_refuse_sans_texte_tronque(client, session):
    csrf = _login(client)
    _resultat(_marque(client, csrf))
    _proposer(client, csrf)
    with session() as cnx:
        propositions = list(stockage.maillons(*service.REGISTRE_CONTENUS_CHANTIER))
        propositions[-1]["mots_clics"] = ["#ancien-mot-clic-fictif" * 100] * 10
        cnx.execute(
            update(REGISTRES)
            .where(
                REGISTRES.c.departement == "m07-marketing",
                REGISTRES.c.registre == "contenus_chantier",
                REGISTRES.c.rang == 4,
            )
            .values(maillon=codec.encoder(propositions[-1]))
        )
    historique = _registre("contenus_chantier")
    refuse = client.get("/api/marketing/calendrier")
    assert refuse.status_code == 409, refuse.text
    assert _registre("contenus_chantier") == historique
    assert _registre("decisions_contenu") == []


def test_snapshot_media_refuse_nouvelle_revision_meme_profil(client, session):
    import base64
    import hashlib
    import struct
    import zlib

    from opsys import fichiers

    def bloc(nom, valeur):
        charge = nom + valeur
        return struct.pack(">I", len(valeur)) + charge + struct.pack(">I", zlib.crc32(charge))

    png = (
        b"\x89PNG\r\n\x1a\n"
        + bloc(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + bloc(b"IDAT", zlib.compress(b"\x00\x11\x22\x33"))
        + bloc(b"IEND", b"")
    )
    sha = hashlib.sha256(png).hexdigest()
    with session() as cnx:
        depot = fichiers.deposer_bloc(cnx, sha, len(png), "image/png", 0, 1, base64.b64encode(png).decode("ascii"))
        assert depot.accepte and depot.complet
        wct = list(stockage.maillons(*service.REGISTRE_WCT_RECUS))[0]
        wct["photos"] = [fichiers.reference_pour(sha)]
        cnx.execute(
            update(REGISTRES)
            .where(REGISTRES.c.departement == "m07-marketing", REGISTRES.c.registre == "wct_recus")
            .values(maillon=codec.encoder(wct))
        )
    csrf = _login(client)
    _resultat(_marque(client, csrf))
    contenu = next(c for c in _proposer(client, csrf) if c["plateforme"] == "facebook")
    url = f"/api/marketing/calendrier/medias/{contenu['contenu_id']}"
    metadata = client.get(url)
    assert metadata.status_code == 200 and metadata.json()["ok"], metadata.text
    assert metadata.json()["resultat"]["resultat"]["sources"][0]["source_sha256"] == sha
    profil = _registre("brand_profiles")[0]["profil"]
    nouveau = client.post(
        "/api/marketing/marque",
        headers={"x-csrf-token": csrf},
        json={"profil": profil, "revision_attendue": 1, "mutation_id": "meme-marque-revision2"},
    )
    _resultat(nouveau)
    assert _registre("brand_profiles")[-1]["profil"] == profil
    refuse = client.get(url)
    assert refuse.status_code == 409 and not refuse.json()["ok"]
    assert _registre("dossiers_medias") == []
