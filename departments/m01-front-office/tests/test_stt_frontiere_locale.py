"""Régressions de consentement : endpoints fictifs, transport intercepté sans réseau."""

from io import BytesIO
from unittest.mock import Mock

import pytest
from m1_front_office import voicemail_stt as stt

FICTIF = True


@pytest.mark.parametrize("url", [
    "http://stt-externe.example/v1", "https://stt-externe.example/v1",
    "http://192.168.1.20/v1", "http://10.0.0.1/v1", "http://169.254.169.254/v1",
    "http://localhost.externe.example/v1", "http://127.0.0.1.externe.example/v1",
])
def test_local_ne_peut_pas_declarer_un_hote_hors_machine(url, monkeypatch):
    transport = Mock()
    monkeypatch.setattr(stt, "_ouvrir", transport)
    with pytest.raises(stt.ErreurVoicemail, match="REJ-STT-CONFIG"):
        stt.ConfigurationSTT(url, "modele-fictif", local=True)
    transport.assert_not_called()


@pytest.mark.parametrize("url", ["http://127.0.0.1:8912/v1", "http://[::1]:8912/v1"])
def test_boucle_locale_reste_compatible(url, monkeypatch):
    transport = Mock(return_value=BytesIO(b'{"text":"message fictif"}'))
    monkeypatch.setattr(stt, "_ouvrir", transport)
    config = stt.ConfigurationSTT(url, "modele-fictif", local=True)
    assert config._transcrire(b"audio-fictif", ".wav") == "message fictif"
    assert transport.call_count == 1


def test_endpoint_distant_reste_soumis_au_consentement(monkeypatch):
    transport = Mock()
    monkeypatch.setattr(stt, "_ouvrir", transport)
    resultat = stt.transcrire_et_importer(
        b"audio-fictif", suffixe=".wav", source="audit-fictif",
        evenement_id="event-fictif", appel_id="appel-fictif", recu_le="2026-10-20T10:00:00Z",
        telephone="+15145550123", consentement_enregistrement="accorde",
        configuration=stt.ConfigurationSTT("https://stt-externe.example/v1", "modele-fictif", cle_api="fictif"),
        importeur=lambda arguments: {"ok": True},
    )
    assert resultat["code"] == "REJ-CONSENTEMENT-TRANSFERT"
    transport.assert_not_called()


def test_localhost_est_fixe_sur_la_boucle_locale_sans_resolution_dns():
    config = stt.ConfigurationSTT("http://localhost:8912/v1", "modele-fictif", local=True)
    assert config.base_url == "http://127.0.0.1:8912/v1"


def test_transport_local_ignore_les_proxys_externes(monkeypatch):
    handlers = []
    opener = Mock()
    monkeypatch.setattr(stt.urllib.request, "build_opener", lambda *args: handlers.extend(args) or opener)
    monkeypatch.setenv("http_proxy", "http://proxy-fictif.externe.example:3128")
    requete = stt.urllib.request.Request("http://127.0.0.1:8912/v1")
    stt._ouvrir(requete, 2)
    assert any(isinstance(handler, stt.urllib.request.ProxyHandler) and handler.proxies == {} for handler in handlers)
    opener.open.assert_called_once_with(requete, timeout=2)
