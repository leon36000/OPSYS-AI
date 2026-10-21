"""Import réputation fictif : conflit natif, rollback et reprise humaine via HTTP."""

from __future__ import annotations

import pytest
import yaml
from fastapi.testclient import TestClient
from m7_marketing import outils
from m7_marketing.brand import profil_client
from sqlalchemy import select

from opsys import contexte, identite, stockage
from opsys.console import application
from opsys.console.securite import Configuration
from opsys.outils import executer_atomique
from opsys.stockage.maillons import MaillonsDurables
from opsys.stockage.schema import MUTATIONS_APPLIQUEES

FICTIF = True
PASSWORD = "mot-de-passe-import-avis-fictif-1234"
AVIS = {
    "plateforme": "google_business_profile",
    "avis_source_id": "avis-import-concurrent-fictif",
    "date_avis": "2026-09-28",
    "note": 5,
    "texte": "Excellent travail, équipe ponctuelle et soignée.",
    "source_url": "https://business.google.com/reviews/avis-import-concurrent-fictif",
}


@pytest.fixture
def console(session, tmp_path, monkeypatch):
    # Précondition historique explicite : charger le vrai YAML, sans modifier la source
    # ni remplacer la fonction métier. La migration du profil UI reste un autre lot.
    profil = tmp_path / "marque-fictive.yaml"
    profil.write_text(yaml.safe_dump({
        "name": "Entreprise FICTIF", "tagline": "Travaux extérieurs",
        "tone": "professionnel", "colors": ["#123456"], "langue": "fr",
    }))
    monkeypatch.setattr(profil_client, "_PROFIL_PAR_DEFAUT", profil)
    with session() as cnx:
        identite.creer_personne(cnx, "owner-fictif", "Propriétaire FICTIF", PASSWORD,
                                ["nathan_owner"])
    app = application.creer_application(
        Configuration("secret-import-avis-fictif-" + "x" * 64,
                      cookie_securise=False, prefixe="/opsys"), None, session,
    )
    with TestClient(app, base_url="https://testserver/opsys",
                    raise_server_exceptions=False) as client:
        login = client.post("/connexion", data={
            "identifiant": "owner-fictif", "mot_de_passe": PASSWORD,
        }, follow_redirects=False)
        assert login.status_code == 303
        yield client, client.get("/api/session").json()["csrf"]


def _envoyer(console, transport, cle="mutation-import-avis-fictive", csrf_valide=True):
    client, csrf = console
    commande = {"action": "importer", "mutation_id": cle, **AVIS}
    if transport == "api":
        headers = {"x-csrf-token": csrf} if csrf_valide else {}
        return client.post("/api/marketing/avis", json=commande, headers=headers)
    return client.post("/marketing", data={**commande, "csrf": csrf if csrf_valide else ""},
                       follow_redirects=False)


def _persistes(session):
    with session() as cnx:
        return (
            list(stockage.maillons("m07-marketing", "reputation_avis")),
            [dict(x) for x in cnx.execute(select(MUTATIONS_APPLIQUEES)).mappings()],
        )


@pytest.mark.parametrize("transport", ["api", "formulaire"])
def test_import_legitime_et_rejeu_sans_doublon(console, session, transport):
    premiere = _envoyer(console, transport)
    assert premiere.status_code == (200 if transport == "api" else 303), premiere.text
    avant = _persistes(session)
    assert len(avant[0]) == len(avant[1]) == 1
    rejouee = _envoyer(console, transport)
    assert rejouee.status_code == premiere.status_code
    assert _persistes(session) == avant


@pytest.mark.parametrize("transport", ["api", "formulaire"])
def test_conflit_natif_refuse_puis_reprise_explicite_sans_faux_recu(
    console, session, monkeypatch, transport,
):
    original = MaillonsDurables.append
    interposes = []
    arme = True
    outil = next(o for o in outils.outils() if o.nom == "m7_importer_avis_manuel")

    def interposer(self, maillon, *, rang_attendu=None):
        nonlocal arme
        if arme and (self.departement, self.registre) == ("m07-marketing", "reputation_avis"):
            arme = False
            cnx = stockage.connexion_courante()
            with contexte.appele_par_appareil(contexte.IdentiteAppelante(
                "owner-fictif", "nathan_owner", source="console",
            )):
                b = executer_atomique(outil, AVIS)
            assert b["ok"] is True and b["resultat"]["accepte"] is True
            assert stockage.connexion_courante() is cnx
            assert len(list(stockage.maillons("m07-marketing", "reputation_avis"))) == 1
            interposes.append(b)
        return original(self, maillon, rang_attendu=rang_attendu)

    monkeypatch.setattr(MaillonsDurables, "append", interposer)
    refusee = _envoyer(console, transport)
    assert len(interposes) == 1
    assert _persistes(session) == ([], [])  # Transaction réelle entièrement annulée.
    assert refusee.status_code == 409, refusee.text
    assert refusee.headers.get("cache-control") == "no-store"
    if transport == "api":
        assert refusee.json()["ok"] is False
        assert refusee.json()["erreur"]["code"] == "CONFLIT_CONCURRENT"
    assert "Rechargez" in refusee.text
    assert "reputation_avis" not in refusee.text  # Aucun détail SQL interne dans le message.

    # Le hook est désarmé, pas le propriétaire. Aucun rejeu automatique : une nouvelle
    # requête explicite avec la même clé peut réussir, puis être rejouée sans doublon.
    reprise = _envoyer(console, transport)
    assert reprise.status_code == (200 if transport == "api" else 303), reprise.text
    apres = _persistes(session)
    assert len(apres[0]) == len(apres[1]) == 1
    assert _envoyer(console, transport).status_code == reprise.status_code
    assert _persistes(session) == apres


@pytest.mark.parametrize("transport", ["api", "formulaire"])
def test_erreur_runtime_inattendue_ne_devient_pas_un_conflit(console, session, monkeypatch, transport):
    original = MaillonsDurables.append

    def panne(self, maillon, *, rang_attendu=None):
        original(self, maillon, rang_attendu=rang_attendu)
        if (self.departement, self.registre) == ("m07-marketing", "reputation_avis"):
            raise RuntimeError("detail-interne-fictif-a-ne-pas-exposer")

    monkeypatch.setattr(MaillonsDurables, "append", panne)
    response = _envoyer(console, transport)
    assert response.status_code == 500
    assert "detail-interne-fictif" not in response.text
    assert _persistes(session) == ([], [])


@pytest.mark.parametrize("transport", ["api", "formulaire"])
def test_import_csrf_et_retrait_autorite_restent_refuses(console, session, transport):
    assert _envoyer(console, transport, csrf_valide=False).status_code == 403
    assert _persistes(session) == ([], [])
    with session() as cnx:
        identite.retirer_role(cnx, "owner-fictif", "nathan_owner")
    assert _envoyer(console, transport).status_code == 403
    assert _persistes(session) == ([], [])
