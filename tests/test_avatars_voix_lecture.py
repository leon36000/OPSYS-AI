"""Lecture admin des avatars : CLI `opsys-metier avatars …` et pages « Plateforme > Avatars » de la console.

Lecture seule ; aucun droit d'appareil n'est élargi ; aucun outil de département n'est ajouté (les compteurs de ROLES.md
sont inchangés). Données fictives.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import avatars_voix_aide as aide
import pytest
import yaml
from fastapi.testclient import TestClient

from opsys import avatars, cli, identite, taxonomie
from opsys.avatars_voix import registre
from opsys.console import application
from opsys.console.securite import Configuration
from opsys.departements import charger_departements

FICTIF = True
RACINE = Path(__file__).resolve().parents[1]
_MDP = "mot-de-passe-console-avatars-fictif-2026"
LIGNE = re.compile(r"^(M\d+)\s+(\S+)\s+messagerie=(\S+)\s+voix=(\S+)\s+audiovisuel=(\S+)\s*(\S*)$")


def _sortie(capsys, *args) -> str:
    assert cli.main(["avatars", *args]) == 0
    return capsys.readouterr().out


# --- CLI ---------------------------------------------------------------------------------------------------------
def test_cli_etat_les_dix_avatars_messagerie_disponible_voix_et_audiovisuel_prevus(session, capsys):
    sortie = _sortie(capsys, "etat")
    lignes = [LIGNE.match(ligne) for ligne in sortie.splitlines()[:-1]]
    assert all(lignes) and [m.group(2) for m in lignes] == ["Léa", "Victor", "Mathis", "Gabriel", "Sophie", "Rosalie",
                                                           "Chloé", "Olivier", "Athéna", "Mnémo"]
    assert {(m.group(3), m.group(4), m.group(5)) for m in lignes} == {("disponible", "prevu", "prevu")}
    assert "REJ-AVATAR-CANAL-NON-REALISE" in lignes[0].group(6) or "REJ-AVATAR-" in lignes[0].group(6)
    assert "pas prouvée de bout en bout" in sortie.splitlines()[-1]


def test_cli_etat_json_un_departement_et_departement_inconnu(session, capsys):
    vue = json.loads(_sortie(capsys, "etat", "--json", "--departement", "m01-front-office"))
    assert [a["departement"] for a in vue["avatars"]] == ["m01-front-office"] and vue["registre"] == []
    assert vue["avatars"][0]["canaux"]["messagerie"]["etat"] == "disponible"
    assert cli.main(["avatars", "etat", "--departement", "m42-inexistant"]) == 2
    assert "département inconnu" in capsys.readouterr().err


def test_cli_registre_vide_puis_rempli_sans_donnee_sensible(session, capsys):
    assert "aucune entrée" in _sortie(capsys, "registre")
    scenario = aide.monter(session)
    texte = _sortie(capsys, "registre")
    assert scenario.voix in texte and "qualifie" in texte and aide.TTS in texte
    contenu = json.loads(_sortie(capsys, "registre", "--json"))
    assert {e["identifiant"] for e in contenu} == {scenario.voix, scenario.visage}
    assert all(e["derniere_qualification"]["nature"] == "reel" for e in contenu)
    vue = json.loads(_sortie(capsys, "etat", "--json", "--departement", aide.DEPARTEMENT))
    assert vue["avatars"][0]["canaux"]["voix"]["etat"] == "qualifie"
    assert vue["avatars"][0]["canaux"]["audiovisuel"]["etat"] == "qualifie"
    assert vue["avatars"][0]["canaux"]["voix"]["codes"] == ["REJ-AVATAR-CANAL-NON-REALISE"]


def test_cli_ne_peut_rien_ecrire(session):
    for sous in (["etat", "--par", "nathan"], ["registre", "inscrire", "voix.a.b"], ["declarer", "voix"]):
        with pytest.raises(SystemExit) as sortie:
            cli.main(["avatars", *sous])
        assert sortie.value.code == 2


def test_cli_profil_d_entreprise_invalide_ne_montre_rien(session, capsys):
    fichier = taxonomie.fichier_profil()
    fichier.parent.mkdir(parents=True, exist_ok=True)
    fichier.write_text(yaml.safe_dump({"avatars": {"m01-front-office": {"nom": "Ju1ie<script>"}}}), encoding="utf-8")
    assert cli.main(["avatars", "etat"]) == 1
    erreur = capsys.readouterr()
    assert "invalides" in erreur.err and "Léa" not in erreur.out and str(fichier.parent) not in erreur.out


def test_la_commande_est_declaree_au_core_et_au_faux_core():
    ts = (RACINE / "core/src/cli/opsys-metier-argv.ts").read_text(encoding="utf-8")
    assert '"avatars",' in ts
    faux = (RACINE / "tests/installateur/faux_core.py").read_text(encoding="utf-8")
    assert '"avatars"' in faux


def test_les_canaux_du_manifeste_et_la_projection_des_identites_sont_inchanges():
    deps = charger_departements()
    identites = avatars.resoudre_identites(deps)
    for identite_ in identites.values():
        assert dict(identite_.canaux) == {"messagerie": "disponible", "voix": "prevu", "audiovisuel": "prevu"}
        assert identite_.voix.startswith("voix.") and identite_.voix.endswith(".defaut")
        assert identite_.visage.startswith("visage.") and identite_.visage.endswith(".defaut")
        assert identite_.sources == {"nom": "manifeste", "voix": "manifeste", "visage": "manifeste"}
    assert identites["m01-front-office"].voix == "voix.lea.defaut"


# --- console -----------------------------------------------------------------------------------------------------
@pytest.fixture
def client(session):
    with session() as cnx:
        identite.creer_personne(cnx, "owner_fictif", "Owner fictif", _MDP, ["nathan_owner"])
        identite.creer_personne(cnx, "vendeur_fictif", "Vendeur fictif", _MDP, ["seller"])
    app = application.creer_application(Configuration("secret-session-avatars-fictif-" + "x" * 32),
                                        charger_departements(), session)
    with TestClient(app, base_url="https://testserver/opsys") as c:
        yield c


def _connexion(client, user="owner_fictif"):
    assert client.post("/connexion", data={"identifiant": user, "mot_de_passe": _MDP},
                       follow_redirects=False).status_code == 303


def test_console_pages_protegees_session_et_role(client):
    assert client.get("/plateforme/avatars", follow_redirects=False).status_code == 303
    assert client.get("/api/plateforme/avatars").status_code == 401
    _connexion(client, "vendeur_fictif")
    for chemin in ("/plateforme/avatars", "/api/plateforme/avatars"):
        r = client.get(chemin, follow_redirects=False)
        assert r.status_code == 403 and "Léa" not in r.text


def test_console_montre_les_dix_avatars_en_lecture_seule_sans_aucun_formulaire(client):
    _connexion(client)
    page = client.get("/plateforme/avatars")
    assert page.status_code == 200 and page.headers["cache-control"] == "no-store"
    for nom in ("Léa", "Victor", "Mathis", "Gabriel", "Sophie", "Rosalie", "Chloé", "Olivier", "Athéna", "Mnémo"):
        assert nom in page.text
    assert "pas prouvée de bout en bout" in page.text and "REJ-AVATAR-CANAL-NON-REALISE" in page.text
    corps = page.text.split("<main", 1)[-1]
    assert "<form" not in corps.split("</nav>")[-1].replace('<form method="post" action="/opsys/deconnexion"', "")
    api = client.get("/api/plateforme/avatars").json()
    assert api["statut"] == "ok" and len(api["avatars"]) == 10 and api["registre"] == []
    assert api["avatars"][0]["canaux"]["voix"]["etat"] == "prevu"
    # aucune écriture n'existe sous cette route
    for methode in (client.post, client.put, client.delete):
        assert methode("/plateforme/avatars").status_code in (403, 404, 405, 422)
    assert 'href="/opsys/plateforme/avatars"' in client.get("/plateforme/fournisseurs").text


def test_console_registre_et_etat_apres_qualification(client, session):
    scenario = aide.monter(session)
    _connexion(client)
    api = client.get("/api/plateforme/avatars").json()
    leas = [a for a in api["avatars"] if a["departement"] == aide.DEPARTEMENT][0]
    assert leas["canaux"]["voix"]["etat"] == "qualifie"
    assert leas["entrees"]["voix"]["fournisseur"]["identifiant"] == aide.TTS
    assert {e["identifiant"] for e in api["registre"]} == {scenario.voix, scenario.visage}
    page = client.get("/plateforme/avatars").text
    assert scenario.voix in page and "reel · succes" in page and "Qualifié (connexion)" in page


def test_console_echappe_les_valeurs_et_ne_fuit_ni_locuteur_ni_chemin(client, session):
    scenario = aide.monter(session)
    with session() as cnx:
        registre.inscrire_entree(cnx, acteur=aide.ADMIN, identifiant="voix.lea.quebec", origine="clonee")
        registre.enregistrer_consentement(
            cnx, acteur=aide.ADMIN, identifiant="voix.lea.quebec", locuteur_ref="comedien-secret-42",
            portee=["clonage", "synthese"], document_ref="<b>contrat</b>.pdf", document_sha256=aide.SHA,
            signe_le="2026-10-01")
    _connexion(client)
    page = client.get("/plateforme/avatars").text
    brut = client.get("/api/plateforme/avatars").text
    assert "comedien-secret-42" not in page + brut and "<b>contrat</b>" not in page
    assert scenario.voix in page


def test_console_profil_invalide_ne_montre_aucune_identite(client):
    fichier = taxonomie.fichier_profil()
    fichier.parent.mkdir(parents=True, exist_ok=True)
    fichier.write_text(yaml.safe_dump({"avatars": {"m42-inexistant": {"nom": "Zoé"}}}), encoding="utf-8")
    _connexion(client)
    api = client.get("/api/plateforme/avatars")
    assert api.json() == {"statut": "profil_invalide"}
    page = client.get("/plateforme/avatars")
    assert page.status_code == 200 and "Léa" not in page.text and str(fichier.parent) not in page.text
