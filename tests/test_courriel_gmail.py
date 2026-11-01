"""Adaptateur Gmail contre `FauxGmail` : amorçage paginé, incrémental par historyId, suppressions, curseurs périmés ou
falsifiés, lecture brute, ids hostiles. NON testé contre le vrai Gmail."""

from __future__ import annotations

import base64
import json

import courriel_doubles as dbl
import courriel_qa as qa
import pytest

from opsys.courriel_connecteurs.erreurs import ErreurCourriel
from opsys.courriel_connecteurs.modele import RefMessage
from opsys.courriel_connecteurs.port import decoder_curseur, encoder_curseur

FICTIF = True


@pytest.fixture
def monde(tmp_path, monkeypatch):
    m = qa.preparer(tmp_path, monkeypatch)
    qa.creer_compte(m)
    qa.connecter_oauth(m)
    return m


@pytest.fixture
def gmail(monde):
    return monde.service.fournisseur("gmail-paul")


def _tout_lire(gmail, dossier="INBOX", curseur=None, limite=3):
    ajouts, suppressions, pages = [], [], 0
    while True:
        page = gmail.synchroniser(dossier, curseur, limite=limite)
        ajouts += [r.ref for r in page.ajouts]
        suppressions += list(page.suppressions)
        curseur, pages = page.curseur, pages + 1
        if page.termine:
            return ajouts, suppressions, curseur, pages


def test_boites_et_dossiers(gmail):
    (boite,) = gmail.lister_boites()
    assert (boite.adresse, boite.fournisseur) == ("paul.fictif@example.test", "gmail")
    dossiers = {d.id: d for d in gmail.lister_dossiers()}
    assert (
        dossiers["INBOX"].role == "INBOX" and dossiers["Label_1"].role is None and dossiers["Label_1"].nom == "Clients"
    )


def test_amorcage_pagine_puis_incremental_sans_doublon_ni_perte(monde, gmail):
    ids = [monde.gmail.ajouter(dbl.courriel_brut(objet=f"m{i}", corps=f"c{i}")) for i in range(7)]
    monde.gmail.ajouter(dbl.courriel_brut(objet="autre étiquette"), labels=("Label_1",))
    ajouts, supp, curseur, pages = _tout_lire(gmail)
    assert ajouts == ids and supp == [] and pages == 3  # 3 + 3 + 1, l'étiquette Label_1 est exclue
    # incrémental : deux arrivées, une suppression
    nouveaux = [monde.gmail.ajouter(dbl.courriel_brut(objet=f"n{i}")) for i in range(2)]
    monde.gmail.supprimer(ids[0])
    ajouts2, supp2, curseur2, _ = _tout_lire(gmail, curseur=curseur)
    assert ajouts2 == nouveaux and supp2 == [ids[0]]
    # rien de neuf : page vide, curseur stable
    ajouts3, supp3, curseur3, _ = _tout_lire(gmail, curseur=curseur2)
    assert ajouts3 == [] and supp3 == [] and curseur3 == curseur2


def test_incremental_pagine(monde, gmail):
    monde.gmail.ajouter(dbl.courriel_brut(objet="a"))
    _, _, curseur, _ = _tout_lire(gmail)
    nouveaux = [monde.gmail.ajouter(dbl.courriel_brut(objet=f"x{i}")) for i in range(5)]
    ajouts, _, curseur2, pages = _tout_lire(gmail, curseur=curseur, limite=2)
    assert ajouts == nouveaux and pages == 3
    assert decoder_curseur("gmail", curseur2)["h"] == str(monde.gmail.history_id)


def test_message_ajoute_puis_supprime_dans_la_meme_fenetre_n_est_pas_a_lire(monde, gmail):
    monde.gmail.ajouter(dbl.courriel_brut(objet="base"))
    _, _, curseur, _ = _tout_lire(gmail)
    ephemere = monde.gmail.ajouter(dbl.courriel_brut(objet="éphémère"))
    monde.gmail.supprimer(ephemere)
    ajouts, supp, _, _ = _tout_lire(gmail, curseur=curseur)
    assert ajouts == [] and supp == [ephemere]


def test_curseur_persistable_reprise_apres_interruption_au_milieu_de_l_amorcage(monde, gmail):
    ids = [monde.gmail.ajouter(dbl.courriel_brut(objet=f"m{i}")) for i in range(6)]
    premiere = gmail.synchroniser("INBOX", None, limite=2)
    assert not premiere.termine
    # « arrêt » : seul le curseur survit ; un nouvel objet reprend où le premier s'est arrêté
    autre = qa_service_frais(monde)
    reste, _, curseur, _ = _tout_lire(autre, curseur=premiere.curseur, limite=2)
    assert [r.ref for r in premiere.ajouts] + reste == ids


def qa_service_frais(monde):
    return monde.service.fournisseur("gmail-paul")


def test_arrivee_pendant_l_amorcage_rattrapee_par_l_incremental(monde, gmail):
    """L'historyId est lu AVANT la liste : un message arrivé pendant l'amorçage ressort à l'incrémental (doublon permis,
    perte jamais)."""
    for i in range(4):
        monde.gmail.ajouter(dbl.courriel_brut(objet=f"m{i}"))
    page = gmail.synchroniser("INBOX", None, limite=2)
    tardif = monde.gmail.ajouter(dbl.courriel_brut(objet="tardif"))
    ajouts, _, curseur, _ = _tout_lire(gmail, curseur=page.curseur, limite=2)
    ajouts2, _, _, _ = _tout_lire(gmail, curseur=curseur, limite=2)
    assert tardif in ajouts + ajouts2


def test_history_id_perime_donne_curseur_expire(monde, gmail):
    monde.gmail.ajouter(dbl.courriel_brut())
    _, _, curseur, _ = _tout_lire(gmail)
    monde.gmail.ajouter(dbl.courriel_brut(objet="après"))
    monde.gmail.purger_historique()
    with pytest.raises(ErreurCourriel) as exc:
        gmail.synchroniser("INBOX", curseur)
    assert exc.value.code == "REJ-COURRIEL-CURSEUR-EXPIRE" and exc.value.reprenable


def test_lecture_brute_fil_et_date_recue(monde, gmail):
    brut = dbl.courriel_brut(objet="À lire", corps="Texte avec accents : é à ç")
    identifiant = monde.gmail.ajouter(brut)
    m = gmail.lire_message(RefMessage(identifiant, "INBOX"))
    assert m.octets == brut and m.fil_fournisseur == monde.gmail.messages[identifiant]["thread"]
    assert m.recu_le.endswith("Z") and m.ref == identifiant


def test_lecture_message_disparu_introuvable(monde, gmail):
    with pytest.raises(ErreurCourriel) as exc:
        gmail.lire_message(RefMessage("00000000deadbeef", "INBOX"))
    assert exc.value.code == "REJ-COURRIEL-INTROUVABLE"


@pytest.mark.parametrize("ref", ["../../../drafts", "a/b", "a b", "x?format=full", "", "é" * 3, "a" * 65])
def test_identifiant_de_message_hostile_refuse_avant_toute_requete(monde, gmail, ref):
    avant = len(monde.transport.requetes)
    with pytest.raises(ErreurCourriel) as exc:
        gmail.lire_message(RefMessage(ref, "INBOX"))
    assert exc.value.code == "REJ-COURRIEL-REPONSE-INVALIDE" and len(monde.transport.requetes) == avant


def test_identifiant_hostile_dans_une_reponse_du_serveur_refuse(monde, gmail):
    monde.gmail.scripter(dbl._json(200, {"messages": [{"id": "../../admin"}]}))
    with pytest.raises(ErreurCourriel) as exc:
        gmail.synchroniser("INBOX", None)
    assert exc.value.code == "REJ-COURRIEL-REPONSE-INVALIDE"


@pytest.mark.parametrize(
    "curseur",
    [
        "n'importe quoi",
        "graph:v1:e30",
        "gmail:v2:e30",
        "gmail:v1:%%%",
        "gmail:v1:" + "A" * 5000,
        encoder_curseur("gmail", {"p": "z", "h": "1"}),
        encoder_curseur("gmail", {"p": "h", "h": "abc"}),
        encoder_curseur("gmail", {"p": "h", "h": "12", "t": "a b&pageToken=evil"}),
        encoder_curseur("gmail", {"p": "h"}),
        encoder_curseur("imap", {"d": "INBOX"}),
    ],
)
def test_curseur_falsifie_refuse(gmail, curseur):
    with pytest.raises(ErreurCourriel) as exc:
        gmail.synchroniser("INBOX", curseur)
    assert exc.value.code == "REJ-COURRIEL-CURSEUR-INVALIDE"


@pytest.mark.parametrize("limite", [0, -1, 501, "10", None, 1.5, True])
def test_limite_de_page_validee(gmail, limite):
    with pytest.raises(ErreurCourriel) as exc:
        gmail.synchroniser("INBOX", None, limite=limite)
    assert exc.value.code == "REJ-COURRIEL-ARGUMENT-INVALIDE"


@pytest.mark.parametrize("dossier", ["", "../x", "INBOX&labelIds=SENT", "a\nb", "x" * 101])
def test_dossier_invalide(gmail, dossier):
    with pytest.raises(ErreurCourriel):
        gmail.synchroniser(dossier, None)


def test_base64_mal_forme_ou_demesure(monde, gmail):
    monde.gmail.scripter(dbl._json(200, {"id": "a", "raw": "!!! pas du base64 !!!"}))
    with pytest.raises(ErreurCourriel) as exc:
        gmail.lire_message(RefMessage("abc", "INBOX"))
    assert exc.value.code == "REJ-COURRIEL-REPONSE-INVALIDE"
    monde.gmail.scripter(dbl._json(200, {"id": "a", "raw": "A" * (50 * 1024 * 1024)}))
    with pytest.raises(ErreurCourriel) as exc:
        gmail.lire_message(RefMessage("abc", "INBOX"))
    assert exc.value.code == "REJ-COURRIEL-MESSAGE-TROP-GROS"


def test_historique_page_suivante_ne_recule_jamais(monde, gmail):
    for i in range(4):
        monde.gmail.ajouter(dbl.courriel_brut(objet=f"m{i}"))
    _, _, curseur, _ = _tout_lire(gmail)
    h = int(decoder_curseur("gmail", curseur)["h"])
    # une réponse tardive d'un historyId plus ancien ne fait pas reculer le curseur
    monde.gmail.scripter(dbl._json(200, {"historyId": str(h - 100)}))
    page = gmail.synchroniser("INBOX", curseur)
    assert int(decoder_curseur("gmail", page.curseur)["h"]) == h
    assert json.loads(base64.urlsafe_b64decode(page.curseur.split(":", 2)[2] + "==="))["p"] == "h"


def test_incremental_filtre_par_etiquette(monde, gmail):
    monde.gmail.ajouter(dbl.courriel_brut(objet="base"))
    _, _, curseur, _ = _tout_lire(gmail)
    monde.gmail.ajouter(dbl.courriel_brut(objet="ailleurs"), labels=("Label_1",))
    dans_inbox = monde.gmail.ajouter(dbl.courriel_brut(objet="ici"))
    ajouts, _, _, _ = _tout_lire(gmail, curseur=curseur)
    assert ajouts == [dans_inbox]
