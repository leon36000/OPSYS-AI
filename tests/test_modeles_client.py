"""Client compatible OpenAI : bornes, redirections, erreurs sans secret, coûts du catalogue (transport injecté)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from opsys.roles_modeles import client
from opsys.roles_modeles.client import ClientOpenAI, ErreurAppel

FICTIF = True
CLE = "cle-fictive-client-0123456789-ABCDEFGH"


def _reponse(statut, corps):
    octets = corps if isinstance(corps, bytes) else json.dumps(corps).encode()
    return lambda requete, delai: (statut, octets)


def test_racines_api_et_admin():
    assert client.racine_api("http://h:4000") == "http://h:4000/v1" == client.racine_api("http://h:4000/v1/")
    assert client.racine_admin("http://h:4000/v1") == "http://h:4000" == client.racine_admin("http://h:4000/")


def test_en_tetes_delai_borne_et_cle_seulement_en_autorisation():
    vus = []

    def ouvrir(requete, delai):
        vus.append((requete.full_url, requete.get_method(), dict(requete.header_items()), delai, requete.data))
        return 200, json.dumps(
            {
                "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 1},
            }
        ).encode()

    c = ClientOpenAI("http://h:4000", CLE, delai_s=999, ouvrir=ouvrir)
    r = c.chat("m", [{"role": "user", "content": "x"}], 8)
    url, methode, entetes, delai, donnees = vus[0]
    assert url == "http://h:4000/v1/chat/completions" and methode == "POST" and delai == client.DELAI_MAX_S
    assert entetes["Authorization"] == f"Bearer {CLE}" and CLE.encode() not in donnees
    assert json.loads(donnees) == {
        "model": "m",
        "messages": [{"role": "user", "content": "x"}],
        "max_tokens": 8,
        "stream": False,
    }
    assert r["contenu"] == "OK" and r["usage"] == {"entree": 3, "sortie": 1}
    ClientOpenAI("http://h", None, ouvrir=ouvrir).chat("m", [], 1)
    assert "Authorization" not in vus[-1][2]


@pytest.mark.parametrize(
    "statut,retentable",
    [(429, True), (500, True), (503, True), (400, False), (404, False), (401, False), (403, False), (302, False)],
)
def test_classement_des_erreurs_http(statut, retentable):
    c = ClientOpenAI("http://h", CLE, ouvrir=_reponse(statut, {"error": {"message": f"echo {CLE} Bearer abcdefghij"}}))
    with pytest.raises(ErreurAppel) as exc:
        c.chat("m", [], 1)
    assert exc.value.retentable is retentable and exc.value.statut == statut
    assert CLE not in str(exc.value) and "abcdefghij" not in str(exc.value)  # l'écho d'une clé est masqué


def test_pannes_reseau_sont_retentables_sans_detail_technique():
    def refuse(requete, delai):
        raise urllib.error.URLError(ConnectionRefusedError("secret-interne"))

    def delai(requete, delai):
        raise TimeoutError

    for ouvrir in (refuse, delai, lambda r, d: (_ for _ in ()).throw(OSError("x"))):
        with pytest.raises(ErreurAppel) as exc:
            ClientOpenAI("http://h", CLE, ouvrir=ouvrir).modeles()
        assert exc.value.retentable is True and "secret-interne" not in str(exc.value)


def test_reponses_invalides_sont_typees_et_non_retentables():
    for corps in (b"pas du json", {"choices": []}, {"choices": [{"message": {"content": 5}}]}, {}, []):
        with pytest.raises(ErreurAppel) as exc:
            ClientOpenAI("http://h", None, ouvrir=_reponse(200, corps)).chat("m", [], 1)
        assert exc.value.code == "REJ-MODELES-REPONSE-INVALIDE" and exc.value.retentable is False
    with pytest.raises(ErreurAppel):
        ClientOpenAI("http://h", None, ouvrir=_reponse(200, {"data": [{"index": 0, "embedding": [1]}]})).embeddings(
            "m", ["a", "b"]
        )  # un vecteur par texte
    with pytest.raises(ErreurAppel):
        ClientOpenAI("http://h", None, ouvrir=_reponse(200, {"results": [{"index": 9, "relevance_score": 1}]})).rerank(
            "m", "q", ["a"]
        )


def test_reponse_et_requete_bornees():
    enorme = b"x" * (client.REPONSE_MAX_OCTETS + 1)
    with pytest.raises(ErreurAppel) as exc:
        ClientOpenAI("http://h", None, ouvrir=_reponse(200, enorme)).modeles()
    assert "volumineuse" in exc.value.detail
    with pytest.raises(ErreurAppel) as exc:
        ClientOpenAI("http://h", None, ouvrir=_reponse(200, {})).chat(
            "m", [{"c": "x" * (client.CORPS_MAX_OCTETS + 1)}], 1
        )
    assert exc.value.retentable is False


def test_la_redirection_n_est_jamais_suivie():
    gestionnaire = client._SansRedirection()
    requete = urllib.request.Request("http://h/a", headers={"Authorization": "Bearer x"})
    assert gestionnaire.redirect_request(requete, None, 302, "Found", {}, "http://autre/b") is None


def test_info_modeles_indisponible_n_est_pas_une_erreur():
    assert ClientOpenAI("http://h", None, ouvrir=_reponse(404, {})).info_modeles() is None
    with pytest.raises(ErreurAppel):
        ClientOpenAI("http://h", None, ouvrir=_reponse(500, {})).info_modeles()


@pytest.mark.parametrize(
    "valeur,attendu",
    [
        (0, None),
        (None, None),
        ("x", None),
        (-1, None),
        (0.000001, "1"),
        (0.000015, "15"),
        (0.0000005, "0.5"),
        (float("nan"), None),
        (float("inf"), None),
    ],
)
def test_cout_par_million(valeur, attendu):
    assert client.cout_par_million(valeur) == attendu
