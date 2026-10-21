"""PLAN T4.13 : le transport HTTP des adaptateurs météo, SANS réseau (sockets bloqués, transport fictif).

Toute panne est un verdict, jamais un « ok » ; aucun verdict ne cite l'URL (elle porte le lieu et la clé d'API) ni un
message d'exception ; l'hôte est d'une liste fermée. Réponses FICTIVES (`fictif: true`).
"""

from __future__ import annotations

import ast
import http.client
import json
import socket
import urllib.error
import urllib.request
from pathlib import Path

import m4_field_ops
import pytest
from m4_field_ops import meteo, meteo_http

FICTIF = True
CLE = "CLE-FICTIVE-SECRETE-0123"
URL = f"https://api.weather.gc.ca/x?apikey={CLE}&latitude=45.800000"


@pytest.fixture(autouse=True)
def _sans_reseau(sockets_bloques):
    """Ce module n'ouvre jamais un socket."""


def _transport(corps=b"{}", entetes=None):
    appels = []

    def transport(url, delai):
        appels.append((url, delai))
        return corps, {"Date": "Mon, 05 Oct 2026 12:00:00 GMT"} if entetes is None else entetes

    transport.appels = appels
    return transport


def _qui_leve(exception):
    def transport(url, delai):
        raise exception

    return transport


def _lire(transport, url=URL, delai=5):
    return meteo_http.lire_json(transport, url, delai, "Fournisseur Fictif")


def _texte(verdict):
    return json.dumps(verdict, ensure_ascii=False)


class TestLireJson:
    def test_une_reponse_json_est_lue_avec_ses_entetes_en_minuscules(self):
        donnees, entetes, verdict = _lire(_transport(b'{"a": [1, 2]}'))
        assert verdict is None and donnees == {"a": [1, 2]} and entetes == {"date": "Mon, 05 Oct 2026 12:00:00 GMT"}

    def test_le_transport_recoit_l_url_et_le_delai(self):
        transport = _transport()
        _lire(transport, URL, 7)
        assert transport.appels == [(URL, 7)]

    def test_les_decimaux_sont_lus_en_decimal_exact_jamais_en_flottant(self):
        from decimal import Decimal

        donnees, _, _ = _lire(_transport(b'{"vent": 12.50, "entier": 3, "tab": [0.1, 2]}'))
        assert donnees["vent"] == Decimal("12.50") and isinstance(donnees["vent"], Decimal)
        assert donnees["entier"] == 3 and isinstance(donnees["entier"], int)
        assert donnees["tab"][0] == Decimal("0.1")

    @pytest.mark.parametrize(
        ("exception", "morceau"),
        [
            (urllib.error.HTTPError(URL, 503, "indisponible", {}, None), "HTTP 503"),
            (urllib.error.HTTPError(URL, 403, "refusé", {}, None), "HTTP 403"),
            (urllib.error.HTTPError(URL, 302, "redirigé", {}, None), "HTTP 302"),
            (urllib.error.URLError(TimeoutError()), "délai dépassé"),
            (TimeoutError(), "délai dépassé"),
            (urllib.error.URLError(socket.gaierror(-2, "nom inconnu")), "injoignable (gaierror)"),
            (urllib.error.URLError(ConnectionRefusedError()), "injoignable (ConnectionRefusedError)"),
            (ConnectionResetError(), "échec de la requête à Fournisseur Fictif (ConnectionResetError)"),
            (OSError("secret"), "(OSError)"),
            (http.client.RemoteDisconnected(), "(RemoteDisconnected)"),
            (http.client.IncompleteRead(b"x"), "(IncompleteRead)"),
            (ValueError("hôte refusé"), "(ValueError)"),
        ],
    )
    def test_une_panne_du_fournisseur_est_un_verdict_indisponible_jamais_un_ok(self, exception, morceau):
        donnees, entetes, verdict = _lire(_qui_leve(exception))
        assert donnees is None and entetes is None
        assert verdict["code"] == meteo.CODE_FOURNISSEUR_INDISPONIBLE and morceau in verdict["detail"]

    def test_un_verdict_ne_cite_jamais_l_url_ni_la_cle_ni_le_message_de_l_exception(self):
        for exception in (
            urllib.error.HTTPError(URL, 500, "message-secret", {}, None),
            urllib.error.URLError("message-secret"),
            OSError("message-secret"),
            ValueError(f"échec sur {URL}"),
        ):
            _, _, verdict = _lire(_qui_leve(exception))
            texte = _texte(verdict)
            assert CLE not in texte and "apikey" not in texte and "45.8" not in texte and "message-secret" not in texte

    @pytest.mark.parametrize(
        "corps",
        [b"pas du json", b"", b"{'a': 1}", b"\xff\xfe", b'{"a": NaN}', b'{"a": Infinity}', b"[" * 5000 + b"]" * 5000],
    )
    def test_un_corps_illisible_est_un_verdict_reponse_invalide(self, corps):
        donnees, _, verdict = _lire(_transport(corps))
        assert donnees is None and verdict["code"] == meteo.CODE_REPONSE_INVALIDE
        assert "JSON invalide" in verdict["detail"] and CLE not in _texte(verdict)

    def test_la_profondeur_maximale_exacte_passe_et_un_niveau_de_plus_est_refuse(self):
        limite = meteo_http.PROFONDEUR_MAX_JSON
        donnees, _, verdict = _lire(_transport(b"[" * limite + b"]" * limite))
        assert verdict is None and donnees is not None
        donnees, _, verdict = _lire(_transport(b"[" * (limite + 1) + b"]" * (limite + 1)))
        assert donnees is None and verdict["code"] == meteo.CODE_REPONSE_INVALIDE
        assert f"plus de {limite} niveaux" in verdict["detail"]

    def test_les_crochets_d_une_chaine_ne_comptent_pas_dans_la_profondeur(self):
        chaine = "[{" * (meteo_http.PROFONDEUR_MAX_JSON + 10) + '\\"'  # finit par un guillemet échappé
        corps = ('{"a": "' + chaine + '"}').encode()
        donnees, _, verdict = _lire(_transport(corps))
        assert verdict is None and donnees["a"] == "[{" * (meteo_http.PROFONDEUR_MAX_JSON + 10) + '"'

    def test_une_reponse_trop_grosse_est_refusee(self):
        gros = b" " * (meteo_http.TAILLE_MAX_REPONSE + 1)
        _, _, verdict = _lire(_transport(gros))
        assert verdict["code"] == meteo.CODE_REPONSE_INVALIDE and "octets" in verdict["detail"]

    def test_la_taille_maximale_exacte_passe_la_limite(self):
        corps = b'{"a": 1}' + b" " * (meteo_http.TAILLE_MAX_REPONSE - 8)
        donnees, _, verdict = _lire(_transport(corps))
        assert verdict is None and donnees == {"a": 1}

    @pytest.mark.parametrize("retour", [("texte", {}), (b"{}", ["Date"]), (b"{}", None), None, b"{}"])
    def test_un_transport_qui_ne_rend_pas_octets_et_entetes_est_refuse_sans_lever(self, retour):
        def transport(url, delai):
            return retour

        try:
            donnees, entetes, verdict = _lire(transport)
        except (TypeError, ValueError):
            pytest.fail("lire_json ne doit rien lever")
        assert (
            donnees is None
            and entetes is None
            and verdict["code"] in (meteo.CODE_REPONSE_INVALIDE, meteo.CODE_FOURNISSEUR_INDISPONIBLE)
        )


class TestTransportParDefaut:
    """Le vrai transport, sous sockets bloqués : il ne sort jamais, et refuse les hôtes hors de la liste fermée."""

    @pytest.mark.parametrize(
        "url",
        [
            "http://api.weather.gc.ca/collections/x",  # pas HTTPS
            "https://api.open-meteo.com/v1/forecast?latitude=45.8",  # l'API gratuite (non commerciale) n'y est pas
            "https://exemple.org/x",
            "https://api.weather.gc.ca.exemple.org/x",
            "https://evil.test/api.weather.gc.ca",
            "https://user@api.weather.gc.ca@evil.test/",
            "ftp://api.weather.gc.ca/x",
            "file:///etc/passwd",
            "",
        ],
    )
    def test_un_hote_hors_de_la_liste_fermee_est_refuse_avant_toute_connexion(self, url):
        with pytest.raises(ValueError, match="liste fermée"):
            meteo_http.transport_http(url, 5)

    def test_une_redirection_n_est_jamais_suivie_l_appelant_recoit_l_erreur_http(self):
        gestionnaire = meteo_http._SansRedirection()
        requete = urllib.request.Request("https://api.weather.gc.ca/x")
        for code in (301, 302, 303, 307, 308):
            suite = gestionnaire.redirect_request(requete, None, code, "Redirection", {}, "https://ailleurs.example/x")
            assert suite is None, code
        assert any(isinstance(h, meteo_http._SansRedirection) for h in meteo_http._OUVREUR.handlers)

    def test_la_liste_fermee_ne_contient_que_geomet_et_l_api_commerciale_d_open_meteo(self):
        assert frozenset({"api.weather.gc.ca", "customer-api.open-meteo.com"}) == meteo_http.HOTES_PERMIS
        assert "api.open-meteo.com" not in meteo_http.HOTES_PERMIS

    def test_un_hote_permis_atteint_le_reseau_bloque_et_la_panne_devient_un_verdict(self, monkeypatch):
        def introuvable(*_args, **_kwargs):
            raise socket.gaierror(-2, "nom inconnu")

        monkeypatch.setattr(socket, "create_connection", introuvable)
        donnees, _, verdict = _lire(meteo_http.transport_http, "https://api.weather.gc.ca/collections/x")
        assert donnees is None and verdict["code"] == meteo.CODE_FOURNISSEUR_INDISPONIBLE
        assert "injoignable (gaierror)" in verdict["detail"]

    def test_le_blocage_des_sockets_est_reel(self):
        with pytest.raises(AssertionError, match="accès réseau interdit"):
            meteo_http.transport_http("https://api.weather.gc.ca/collections/x", 5)


class TestOutils:
    @pytest.mark.parametrize(
        ("delai", "valide"),
        [
            (1, True),
            (5, True),
            (30, True),
            (0, False),
            (31, False),
            (-1, False),
            (2.5, False),
            (True, False),
            ("5", False),
            (None, False),
        ],
    )
    def test_delai_valide(self, delai, valide):
        assert meteo_http.delai_valide(delai) is valide

    @pytest.mark.parametrize(
        ("microdegres", "texte"),
        [
            (45_800_000, "45.800000"),
            (-73_400_000, "-73.400000"),
            (0, "0.000000"),
            (-50_000, "-0.050000"),
            (1, "0.000001"),
            (-1, "-0.000001"),
            (180_000_000, "180.000000"),
        ],
    )
    def test_degres_en_texte_exact_sans_flottant(self, microdegres, texte):
        assert meteo_http.degres(microdegres) == texte


def test_aucun_module_de_m4_hors_le_transport_et_le_routage_n_ouvre_de_connexion():
    """Seuls `distances_osrm.py` (sidecar local) et `meteo_http.py` (fournisseur ouvert par la configuration) importent
    de quoi ouvrir une connexion ; les autres modules de M4 restent sans entrée-sortie réseau."""
    interdits = ("socket", "ssl", "requests", "httpx", "aiohttp", "urllib.request", "http.client", "smtplib", "ftplib")
    autorises = {"distances_osrm.py", "meteo_http.py"}
    racine = Path(m4_field_ops.__file__).parent
    for chemin in sorted(racine.glob("*.py")):
        if chemin.name in autorises:
            continue
        for noeud in ast.walk(ast.parse(chemin.read_text(encoding="utf-8"))):
            noms = []
            if isinstance(noeud, ast.Import):
                noms = [a.name for a in noeud.names]
            elif isinstance(noeud, ast.ImportFrom):
                noms = [noeud.module or ""]
            for nom in noms:
                assert nom not in interdits, (chemin.name, nom)
