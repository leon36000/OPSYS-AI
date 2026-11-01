"""Adaptateur Microsoft Graph contre `FauxGraph` : delta par dossier (nextLink puis deltaLink), suppressions `@removed`,
410 périmé, liens hostiles, identifiants immuables, lecture MIME. NON testé contre le vrai Graph."""

from __future__ import annotations

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
    qa.creer_compte(m, "graph-paul", "graph")
    qa.connecter_oauth(m, "graph-paul")
    return m


@pytest.fixture
def graph(monde):
    return monde.service.fournisseur("graph-paul")


def _tout(graph, dossier="inbox", curseur=None, limite=3):
    ajouts, supp, pages = [], [], 0
    while True:
        page = graph.synchroniser(dossier, curseur, limite=limite)
        ajouts += [r.ref for r in page.ajouts]
        supp += list(page.suppressions)
        curseur, pages = page.curseur, pages + 1
        if page.termine:
            return ajouts, supp, curseur, pages


def test_boites_et_dossiers(graph):
    assert graph.lister_boites()[0].adresse == "paul.fictif@example.test"
    assert {d.id: d.nom for d in graph.lister_dossiers()}["inbox"] == "Boîte de réception"


def test_delta_pagine_puis_incremental(monde, graph):
    monde.graph.page = 3
    ids = [monde.graph.ajouter(dbl.courriel_brut(objet=f"m{i}")) for i in range(7)]
    ajouts, supp, curseur, pages = _tout(graph)
    assert ajouts == ids and supp == [] and pages == 3
    assert decoder_curseur("graph", curseur)["k"] == "d"  # on termine sur un deltaLink
    nouveau = monde.graph.ajouter(dbl.courriel_brut(objet="n"))
    monde.graph.supprimer(ids[2])
    ajouts2, supp2, curseur2, _ = _tout(graph, curseur=curseur)
    assert ajouts2 == [nouveau] and supp2 == [ids[2]]
    assert _tout(graph, curseur=curseur2)[:2] == ([], [])


def test_chaque_dossier_a_son_delta(monde, graph):
    a = monde.graph.ajouter(dbl.courriel_brut(objet="a"), dossier="inbox")
    b = monde.graph.ajouter(dbl.courriel_brut(objet="b"), dossier="AAMkFOLDER1=")
    assert _tout(graph, "inbox")[0] == [a]
    assert _tout(graph, "AAMkFOLDER1=")[0] == [b]


def test_curseur_d_un_autre_dossier_refuse(monde, graph):
    monde.graph.ajouter(dbl.courriel_brut())
    _, _, curseur, _ = _tout(graph, "inbox")
    with pytest.raises(ErreurCourriel) as exc:
        graph.synchroniser("AAMkFOLDER1=", curseur)
    assert exc.value.code == "REJ-COURRIEL-CURSEUR-INVALIDE"


def test_delta_link_perime_410(monde, graph):
    monde.graph.ajouter(dbl.courriel_brut())
    _, _, curseur, _ = _tout(graph)
    monde.graph.delta_expire = True
    with pytest.raises(ErreurCourriel) as exc:
        graph.synchroniser("inbox", curseur)
    assert exc.value.code == "REJ-COURRIEL-CURSEUR-EXPIRE" and exc.value.reprenable


@pytest.mark.parametrize(
    "lien",
    [
        "https://evil.example.test/v1.0/me/mailFolders/inbox/messages/delta?$skiptoken=x",
        "https://graph.microsoft.com.evil.example.test/v1.0/me/mailFolders/inbox/messages/delta",
        "http://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta?$skiptoken=x",
        "https://graph.microsoft.com/v1.0/me/drive/root/children",
        "https://graph.microsoft.com/v1.0/users/autre@example.test/messages",
        "https://graph.microsoft.com@evil.example.test/v1.0/me/mailFolders/inbox/messages/delta",
    ],
)
def test_lien_hostile_rendu_par_le_serveur_jamais_suivi_et_jeton_jamais_envoye(monde, graph, lien):
    monde.graph.ajouter(dbl.courriel_brut())
    monde.graph.page = 1
    monde.graph.ajouter(dbl.courriel_brut(objet="deux"))
    monde.graph.liens_forces["nextLink"] = lien
    page_ok = None
    with pytest.raises(ErreurCourriel) as exc:
        page_ok = graph.synchroniser("inbox", None, limite=1)
    assert exc.value.code == "REJ-COURRIEL-LIEN-NON-AUTORISE" and page_ok is None
    assert all("evil.example.test" not in r.url for r in monde.transport.requetes)


def test_curseur_falsifie_en_base_vers_une_autre_zone_graph_refuse(monde, graph):
    for url in (
        "https://graph.microsoft.com/v1.0/me/messages",
        "https://evil.example.test/v1.0/me/mailFolders/inbox/messages/delta",
    ):
        with pytest.raises(ErreurCourriel) as exc:
            graph.synchroniser("inbox", encoder_curseur("graph", {"k": "d", "u": url}))
        assert exc.value.code == "REJ-COURRIEL-LIEN-NON-AUTORISE"
    for donnees in ({"k": "x", "u": "https://graph.microsoft.com/"}, {"k": "d"}, {"k": "d", "u": 5}):
        with pytest.raises(ErreurCourriel) as exc:
            graph.synchroniser("inbox", encoder_curseur("graph", donnees))
        assert exc.value.code == "REJ-COURRIEL-CURSEUR-INVALIDE"


def test_identifiants_immuables_demandes(monde, graph):
    monde.graph.ajouter(dbl.courriel_brut())
    _tout(graph)
    delta = [r for r in monde.transport.requetes if "/delta" in r.url][0]
    assert 'IdType="ImmutableId"' in delta.entetes["Prefer"] and "odata.maxpagesize=3" in delta.entetes["Prefer"]


def test_lecture_mime_fil_et_date(monde, graph):
    brut = dbl.courriel_brut(objet="Soumission", corps="Bonjour")
    identifiant = monde.graph.ajouter(brut)
    m = graph.lire_message(RefMessage(identifiant, "inbox"))
    assert m.octets == brut and m.fil_fournisseur == monde.graph.messages[identifiant]["conv"]
    assert m.recu_le == "2026-10-30T18:00:00Z"
    appels = [r for r in monde.transport.requetes if "/messages/" in r.url]
    assert all('IdType="ImmutableId"' in r.entetes["Prefer"] for r in appels)


def test_message_disparu_introuvable_et_id_hostile(monde, graph):
    with pytest.raises(ErreurCourriel) as exc:
        graph.lire_message(RefMessage("AAMkinconnu=", "inbox"))
    assert exc.value.code == "REJ-COURRIEL-INTROUVABLE"
    for ref in ("../drive", "a b", "x?$select=body", "", "é"):
        with pytest.raises(ErreurCourriel) as exc:
            graph.lire_message(RefMessage(ref, "inbox"))
        assert exc.value.code == "REJ-COURRIEL-REPONSE-INVALIDE"


def test_reponse_delta_sans_lien_de_suite_refusee(monde, graph):
    monde.graph.scripter(dbl._json(200, {"value": []}))
    with pytest.raises(ErreurCourriel) as exc:
        graph.synchroniser("inbox", None)
    assert exc.value.code == "REJ-COURRIEL-REPONSE-INVALIDE"


def test_429_graph_attente_puis_reprise(monde, graph):
    monde.graph.ajouter(dbl.courriel_brut())
    monde.graph.scripter(dbl.reponse_429("5"))
    assert len(graph.synchroniser("inbox", None).ajouts) == 1
    assert monde.horloge.sommeils == [5.0]


def test_dossier_invalide(graph):
    for dossier in ("../x", "a b", "", "inbox/../../me"):
        with pytest.raises(ErreurCourriel):
            graph.synchroniser(dossier, None)
