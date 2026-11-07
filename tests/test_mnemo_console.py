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
from m10_memoire import contradictions as journal_contradictions
from m10_memoire import contradictions_outils, verite

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
                "u",
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


def _seed_contradictions(session):
    ordre = verite.charger()
    entrees = (
        ("affaires", "decision_proprietaire", "journal", "humain:nathan", "agent:m10-memoire"),
        ("developpement", "constitution", "documentation", "fichier:AGENTS.md", "fichier:docs/architecture/fictive.md"),
    )
    with session():
        for domaine, classe_a, classe_b, emetteur_a, emetteur_b in entrees:
            base = {
                "domaine": domaine,
                "sujet": "regle:consolefictive",
                "attribut": "gate_humain",
                "ref": "projet:source-fictive@" + "a" * 64,
                "horodatage": T,
            }
            contradictions_outils._REGISTRE_AFFIRMATIONS.ajouter({
                **base,
                "type_entree": "affirmation_enregistree",
                "valeur": "ValeurPriveeFictiveA",
                "classe": classe_a,
                "emetteur": emetteur_a,
            })
            contradictions_outils._REGISTRE_AFFIRMATIONS.ajouter({
                **base,
                "type_entree": "affirmation_enregistree",
                "valeur": "ValeurPriveeFictiveB",
                "classe": classe_b,
                "emetteur": emetteur_b,
            })
        actives = journal_contradictions.actives(
            journal_contradictions.affirmations(contradictions_outils._REGISTRE_AFFIRMATIONS.lire())
        )
        detections = journal_contradictions.detecter(
            actives, set(), ordre, T
        )
        for detection in detections:
            for entree in journal_contradictions.entrees_detection(detection):
                contradictions_outils._REGISTRE_CONTRADICTIONS.ajouter(entree)
    assert len(detections) == 2


def _tailles_registres_contradictions(session):
    with session():
        return (
            len(contradictions_outils._REGISTRE_AFFIRMATIONS.lire()),
            len(contradictions_outils._REGISTRE_CONTRADICTIONS.lire()),
        )


def test_console_pages_protegees_session_et_role(client, donnees, monkeypatch):
    assert client.get("/plateforme/mnemo", follow_redirects=False).status_code == 303
    assert client.get("/api/plateforme/mnemo").status_code == 401

    def lecture_interdite(*args, **kwargs):
        pytest.fail("le lecteur de contradictions ne doit pas être appelé avant la garde admin")

    monkeypatch.setattr(contradictions_outils, "lire_contradictions", lecture_interdite)
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


def test_console_affiche_les_contradictions_separees_sans_valeurs_ni_ecriture(client, donnees, session):
    _seed_contradictions(session)
    avant = _tailles_registres_contradictions(session)
    _connexion(client)

    page = client.get("/plateforme/mnemo")
    api = client.get("/api/plateforme/mnemo")
    assert page.status_code == 200 and page.headers["cache-control"] == "no-store"
    assert api.status_code == 200 and api.headers["cache-control"] == "no-store"
    assert "Contradictions à traiter" in page.text
    assert "Mémoire d’affaires" in page.text and "Mémoire de développement" in page.text
    assert "À valider par une personne" in page.text and "maximum 10" in page.text
    for valeur_privee in ("ValeurPriveeFictiveA", "ValeurPriveeFictiveB", "consolefictive", "fichier:AGENTS.md"):
        assert valeur_privee not in page.text
        assert valeur_privee not in api.text

    vues = api.json()["contradictions"]
    assert set(vues) == {"affaires", "developpement"}
    for vue in vues.values():
        assert vue["statut"] == "disponible"
        assert vue["total"] == vue["affichees"] == 1 and vue["limite"] == 10
        assert len(vue["elements"]) == 1
        element = vue["elements"][0]
        assert len(element["identifiant"]) == 12 and element["critique"] is True
        assert element["statut"] == "en_attente_humain"
        assert set(element) == {
            "identifiant", "statut", "critique", "source_a", "source_b", "proposition", "demande_en_attente"
        }
    assert _tailles_registres_contradictions(session) == avant


def test_console_signale_une_file_indisponible_si_le_lecteur_m10_echoue(client, donnees, monkeypatch):
    _connexion(client)

    def lecture_en_echec(*args, **kwargs):
        raise RuntimeError("détail interne non destiné à la console")

    monkeypatch.setattr(contradictions_outils, "lire_contradictions", lecture_en_echec)
    page = client.get("/plateforme/mnemo")
    api = client.get("/api/plateforme/mnemo")

    assert page.status_code == 200 and page.headers["cache-control"] == "no-store"
    assert page.text.count("File indisponible.") == 2
    assert "détail interne" not in page.text
    assert api.status_code == 200 and api.headers["cache-control"] == "no-store"
    assert {d: v["statut"] for d, v in api.json()["contradictions"].items()} == {
        "affaires": "indisponible",
        "developpement": "indisponible",
    }
    assert "détail interne" not in api.text


def test_api_json_est_complete_et_sans_pseudonyme_complet(client, donnees):
    _connexion(client)
    api = client.get("/api/plateforme/mnemo").json()
    assert {"soi", "graphe", "lecons", "mention_professionnelle"} <= set(api)
    assert api["graphe"]["aretes_sensibles_en_attente"] == 1 and len(api["soi"]["revisions_en_attente"]) == 1
    assert CLIENT not in json.dumps(api) and PROPRIETE not in json.dumps(api)
    assert api["lecons"]["lecons"][0]["etat"] == "proposee"
