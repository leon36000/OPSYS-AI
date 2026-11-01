"""Transport HTTP de production (`TransportUrllib`) testé avec un `ouvrir` injecté : HTTPS seulement, aucune
redirection suivie, erreurs sans fuite d'URL ni d'en-tête, corps borné. Aucun socket : le comportement réseau réel
n'est PAS éprouvé ici."""

from __future__ import annotations

import io
import urllib.error
import urllib.request

import pytest

from opsys.courriel_connecteurs import transport as t
from opsys.courriel_connecteurs.transport import ErreurTransport, ReponseHttp, RequeteHttp, TransportUrllib

FICTIF = True


class Reponse:
    def __init__(self, statut=200, entetes=None, corps=b"{}"):
        self.status, self.headers, self._corps, self.fermee = (
            statut,
            entetes or {"Content-Type": "application/json"},
            corps,
            False,
        )

    def read(self, n=-1):
        return self._corps if n < 0 else self._corps[:n]

    def close(self):
        self.fermee = True


def _requete(url="https://gmail.googleapis.com/gmail/v1/users/me/profile", **options):
    return RequeteHttp(
        "GET", url, {"Authorization": "Bearer jeton-fictif-0123456789", "Accept": "application/json"}, **options
    )


def test_requete_reussie_en_tetes_normalises_et_reponse_fermee():
    vues = []
    reponse = Reponse(200, {"Retry-After": "3", "Content-Type": "application/json"}, b'{"ok":true}')

    def ouvrir(brute, delai):
        vues.append((brute.full_url, brute.get_method(), dict(brute.header_items()), delai))
        return reponse

    resultat = TransportUrllib(ouvrir).envoyer(_requete(delai_s=12))
    assert resultat == ReponseHttp(200, {"retry-after": "3", "content-type": "application/json"}, b'{"ok":true}')
    assert resultat.entete("Retry-After") == "3" and reponse.fermee
    assert vues[0][1] == "GET" and vues[0][3] == 12 and vues[0][2]["Authorization"].startswith("Bearer ")


@pytest.mark.parametrize(
    "url", ["http://gmail.googleapis.com/x", "ftp://x.example.test/", "file:///etc/passwd", "//x/y", ""]
)
def test_https_seulement_aucun_appel_sinon(url):
    appels = []
    with pytest.raises(ErreurTransport):
        TransportUrllib(lambda *a: appels.append(a)).envoyer(_requete(url))
    assert appels == []


def test_delai_borne_entre_1_et_120_secondes():
    delais = []
    TransportUrllib(lambda b, d: delais.append(d) or Reponse()).envoyer(_requete(delai_s=0.01))
    TransportUrllib(lambda b, d: delais.append(d) or Reponse()).envoyer(_requete(delai_s=9999))
    assert delais == [1.0, 120.0]


def test_erreur_http_rendue_comme_reponse_avec_son_corps_et_ses_entetes():
    def ouvrir(brute, delai):
        raise urllib.error.HTTPError(brute.full_url, 429, "Too Many", {"Retry-After": "9"}, io.BytesIO(b'{"e":1}'))

    resultat = TransportUrllib(ouvrir).envoyer(_requete())
    assert (resultat.statut, resultat.entete("retry-after"), resultat.corps) == (429, "9", b'{"e":1}')


@pytest.mark.parametrize(
    "exception, nature",
    [
        (TimeoutError("délai https://x/?token=SECRET123"), "delai"),
        (urllib.error.URLError("échec https://x/?token=SECRET123"), "connexion"),
        (ConnectionResetError("reset Bearer SECRET123"), "connexion"),
    ],
)
def test_pannes_de_transport_sans_fuite_du_message_d_origine(exception, nature):
    def ouvrir(brute, delai):
        raise exception

    with pytest.raises(ErreurTransport) as exc:
        TransportUrllib(ouvrir).envoyer(_requete())
    assert exc.value.nature == nature and "SECRET123" not in str(exc.value) and exc.value.__cause__ is None


def test_lecture_interrompue_et_corps_demesure(monkeypatch):
    class Cassee(Reponse):
        def read(self, n=-1):
            raise ConnectionResetError("coupure")

    with pytest.raises(ErreurTransport) as exc:
        TransportUrllib(lambda b, d: Cassee()).envoyer(_requete())
    assert exc.value.nature == "lecture"
    monkeypatch.setattr(t, "CORPS_REPONSE_MAX", 10)
    with pytest.raises(ErreurTransport) as exc:
        TransportUrllib(lambda b, d: Reponse(corps=b"x" * 11)).envoyer(_requete())
    assert exc.value.nature == "reponse_trop_grosse"


def test_aucune_redirection_suivie_par_le_gestionnaire_reel():
    gestionnaire = t._SansRedirection()
    requete = urllib.request.Request("https://gmail.googleapis.com/x", headers={"Authorization": "Bearer jeton"})
    assert gestionnaire.redirect_request(requete, None, 302, "Found", {}, "https://evil.example.test/") is None


def test_repr_de_la_requete_sans_en_tete_sensible_ni_requete():
    r = RequeteHttp(
        "POST",
        "https://x.example.test/p?access_token=SECRET123",
        {"Authorization": "Bearer SECRET123", "Cookie": "sid=SECRET456", "Accept": "a/b"},
        b"corps secret SECRET789",
    )
    texte = repr(r) + str(r)
    for secret in ("SECRET123", "SECRET456", "SECRET789"):
        assert secret not in texte
    assert "Accept" in texte and "•••" in texte
