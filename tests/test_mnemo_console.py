"""Console « Plateforme > Mnémo » et CLI `opsys-metier mnemo …` : lecture seule, protégée, sans donnée personnelle.

Données fictives. La page dit ce qui ATTEND une décision humaine ; elle n'offre aucun formulaire.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opsys import cli, identite
from opsys.console import application
from opsys.console.securite import Configuration
from opsys.departements import charger_departements
from opsys.mnemo import lecons, registres, service, soi
from opsys.mnemo.graphe import DemandeArete, GrapheSql, NoeudRef

FICTIF = True
RACINE = Path(__file__).resolve().parents[1]
_MDP = "mot-de-passe-console-mnemo-fictif-2026"
CORPUS = RACINE / "departments/m10-memoire/evals/soi-graphe.v1.yaml"
T = "2026-10-01T09:00:00+00:00"
MAINTENANT = dt.datetime(2026, 11, 1, 12, tzinfo=dt.UTC)
CLIENT = hashlib.sha256(b"client-console").hexdigest()
PROPRIETE = hashlib.sha256(b"propriete-console").hexdigest()
HUMAIN = soi.Acteur("direction.fictive", "admin", "approbation")


@pytest.fixture(autouse=True)
def _horloge(monkeypatch):
    monkeypatch.setattr(service, "maintenant", lambda: MAINTENANT)


@pytest.fixture
def donnees(session):
    with session() as cnx:
        registre = registres.soi()
        src = {"type": "onboarding", "ref": "entreprise:services:abc12345", "observe_le": T}
        a = soi.proposer(
            registre,
            dimension="services",
            cle="calfeutrage",
            valeur={"libelle": "Calfeutrage <b>gras</b>"},
            sources=[src],
            par="agent:m10",
            horodatage=T,
            verificateur=lambda s: True,
        )["enonce"]["enonce_id"]
        soi.confirmer(registre, a, acteur=HUMAIN, motif="Confirmé avec la direction", horodatage=T)
        soi.proposer(
            registre,
            dimension="services",
            cle="calfeutrage",
            valeur={"libelle": "Calfeutrage et scellants"},
            sources=[{**src, "ref": "entreprise:services:nouveau9"}],
            par="agent:m10",
            horodatage=T,
            verificateur=lambda s: True,
        )
        soi.proposer(
            registre,
            dimension="zones",
            cle="zone_desservie",
            valeur={"villes": ["Laval"]},
            sources=[{**src, "ref": "entreprise:zone_desservie:zzz12345"}],
            par="agent:m10",
            horodatage=T,
            verificateur=lambda s: True,
        )
        g = GrapheSql(cnx)
        g.proposer_arete(
            DemandeArete(
                type="possede",
                de=NoeudRef("client", CLIENT),
                vers=NoeudRef("propriete", PROPRIETE),
                valide_de="2026-09-01",
                origine="bus",
                source_type="bus:m2.profil_propriete_confirme",
                source_ref="bus:m2.profil_propriete_confirme:" + "f" * 64,
            ),
            par="systeme:x",
            quand=T,
        )
        reg_lecons = registres.lecons()
        ecarts = [
            lecons.Ecart(
                f"W-{i:03d}",
                "mat-a",
                __import__("decimal").Decimal(10 + i),
                (__import__("decimal").Decimal(10 + i) * __import__("decimal").Decimal("1.15")).quantize(
                    __import__("decimal").Decimal("0.01")
                ),
                f"{i + 1:064x}",
                T,
            )
            for i in range(15)
        ]
        lecons.extraire(
            reg_lecons, ecarts_mat=ecarts, ecarts_mar=[], refus=[], rejets=[], par="agent:m10", horodatage=T
        )


def _sortie(capsys, *args) -> str:
    assert cli.main(["mnemo", *args]) == 0
    return capsys.readouterr().out


# -- CLI
# ----------------------------------------------------------------------------------------------------------------------
def test_cli_etat_resume_le_soi_le_graphe_et_les_lecons(session, donnees, capsys):
    sortie = _sortie(capsys, "etat")
    assert "modèle de soi : 3 énoncé(s), 1 révision(s) en attente" in sortie
    assert "1 sensible(s) en attente d'une personne" in sortie and "proposee" in sortie
    vue = json.loads(_sortie(capsys, "etat", "--json"))
    assert vue["soi"]["revisions_en_attente"] == 1 and "ton_marque" in vue["soi"]["dimensions_inconnues"]
    assert vue["graphe"]["aretes_sensibles_en_attente"] == 1 and vue["lecons"]["par_etat"] == {"proposee": 1}
    assert CLIENT not in json.dumps(vue)


def test_cli_etat_sur_une_instance_vide(session, capsys):
    sortie = _sortie(capsys, "etat")
    assert "0 énoncé(s)" in sortie and "aucune" in sortie


def test_cli_mesurer_ne_touche_pas_l_instance_et_ecrit_un_rapport_jamais_ecrase(session, donnees, capsys, tmp_path):
    avant = json.loads(_sortie(capsys, "etat", "--json"))
    sortie = _sortie(capsys, "mesurer", "--corpus", str(CORPUS))
    assert "Aucun modèle de langage" in sortie and "concordants : **oui**" in sortie
    dossier = tmp_path / "rapports"
    assert cli.main(["mnemo", "mesurer", "--corpus", str(CORPUS), "--sortie", str(dossier)]) == 0
    fichiers = sorted(p.name for p in dossier.iterdir())
    assert len(fichiers) == 2 and all(f.startswith("mnemo-mesure-mnemo-v1-") for f in fichiers)
    rapport = json.loads(next(dossier.glob("*.json")).read_text(encoding="utf-8"))
    assert rapport["modele_reel"] is False and rapport["graphe"]["moteurs_concordent"] is True
    assert "simulee" in rapport["garde_gabarit"]
    capsys.readouterr()
    assert cli.main(["mnemo", "mesurer", "--corpus", str(CORPUS), "--sortie", str(dossier)]) == 2  # jamais écrasé
    assert "REJ-MNEMO-SORTIE-EXISTANTE" in capsys.readouterr().err
    assert json.loads(_sortie(capsys, "etat", "--json")) == avant


def test_cli_mesurer_refuse_un_corpus_illisible_ou_non_fictif(session, tmp_path, capsys):
    assert cli.main(["mnemo", "mesurer", "--corpus", str(tmp_path / "absent.yaml")]) == 2
    reel = tmp_path / "reel.yaml"
    reel.write_text(
        "schema: opsys.mnemo.corpus/v1\nfictif: false\ngraphe: {}\nquestions: []\nlecons: []\n", encoding="utf-8"
    )
    assert cli.main(["mnemo", "mesurer", "--corpus", str(reel)]) == 2
    assert "corpus" in capsys.readouterr().err


def test_cli_garde_lecon_refuse_une_lecon_inconnue(session, capsys):
    assert cli.main(["mnemo", "garde-lecon", "--lecon", "lc-inconnue", "--par", "operateur.fictif"]) == 1
    assert "REJ-MNEMO-LECON-INCONNUE" in capsys.readouterr().err


def test_cli_ne_peut_rien_decider(session):
    for sous in (["confirmer", "x"], ["promouvoir", "x"], ["declarer", "x"]):
        with pytest.raises(SystemExit) as sortie:
            cli.main(["mnemo", *sous])
        assert sortie.value.code == 2


def test_la_commande_est_declaree_au_core_et_au_faux_core():
    assert '"mnemo",' in (RACINE / "core/src/cli/opsys-metier-argv.ts").read_text(encoding="utf-8")
    assert '"mnemo"' in (RACINE / "tests/installateur/faux_core.py").read_text(encoding="utf-8")


# -- console
# --------------------------------------------------------------------------------------------------------------------
@pytest.fixture
def client(session):
    with session() as cnx:
        identite.creer_personne(cnx, "owner_fictif", "Owner fictif", _MDP, ["nathan_owner"])
        identite.creer_personne(cnx, "vendeur_fictif", "Vendeur fictif", _MDP, ["seller"])
    app = application.creer_application(
        Configuration("secret-session-mnemo-fictif-" + "x" * 32), charger_departements(), session
    )
    with TestClient(app, base_url="https://testserver/opsys") as c:
        yield c


def _connexion(client, user="owner_fictif"):
    assert (
        client.post("/connexion", data={"identifiant": user, "mot_de_passe": _MDP}, follow_redirects=False).status_code
        == 303
    )


def test_console_pages_protegees_session_et_role(client, donnees):
    assert client.get("/plateforme/mnemo", follow_redirects=False).status_code == 303
    assert client.get("/api/plateforme/mnemo").status_code == 401
    _connexion(client, "vendeur_fictif")
    for chemin in ("/plateforme/mnemo", "/api/plateforme/mnemo"):
        r = client.get(chemin, follow_redirects=False)
        assert r.status_code == 403 and "Calfeutrage" not in r.text


def test_console_dit_ce_qui_attend_une_decision_sans_formulaire(client, donnees):
    _connexion(client)
    page = client.get("/plateforme/mnemo")
    assert page.status_code == 200 and page.headers["cache-control"] == "no-store"
    texte = page.text
    assert "Révisions à trancher" in texte and "Calfeutrage et scellants" in texte and "à la place de" in texte
    assert "En attente de la confirmation d" in texte and "possede" in texte and "client·" in texte
    assert "à confirmer" in texte and "inconnu" in texte and "ton_marque" in texte
    assert "Lecture seule" in texte and "À valider auprès d" in texte and "Aucun modèle de langage" in texte
    assert "ecart_materiau" in texte and "non faite" in texte
    assert CLIENT not in texte and PROPRIETE not in texte  # seulement les pseudonymes courts
    corps = texte.split("</nav>")[-1].replace('<form method="post" action="/opsys/deconnexion"', "")
    assert "<form" not in corps
    for methode in (client.post, client.put, client.delete):
        assert methode("/plateforme/mnemo").status_code in (403, 404, 405, 422)
    assert 'href="/opsys/plateforme/mnemo"' in client.get("/plateforme/connaissances").text


def test_console_echappe_les_libelles(client, donnees):
    _connexion(client)
    page = client.get("/plateforme/mnemo").text
    assert "<b>gras</b>" not in page and "&lt;b&gt;gras&lt;/b&gt;" in page


def test_api_json_est_complete_et_sans_pseudonyme_complet(client, donnees):
    _connexion(client)
    api = client.get("/api/plateforme/mnemo").json()
    assert {"soi", "graphe", "lecons", "mention_professionnelle"} <= set(api)
    assert api["graphe"]["aretes_sensibles_en_attente"] == 1 and len(api["soi"]["revisions_en_attente"]) == 1
    assert CLIENT not in json.dumps(api) and PROPRIETE not in json.dumps(api)
    assert api["lecons"]["lecons"][0]["etat"] == "proposee"
