"""Contrat HTTP borné du provider local, sans charger le modèle dans les tests unitaires."""

import http.client
import importlib.util
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager, suppress

import pytest

_MODULE = "opsys.memoire.serveur_embeddings_local"
_MODULE_SPEC = importlib.util.find_spec(_MODULE)


def test_provider_local_borne_est_present():
    assert _MODULE_SPEC is not None, "le provider local compatible /v1/embeddings doit exister"


if _MODULE_SPEC is not None:
    from opsys.memoire.serveur_embeddings_local import (
        ErreurRequete,
        ServeurEmbeddingsLocal,
        _inference_avec_watchdog,
        encoder_entree,
    )

    CLE = "k" * 32
    MODELE = "BAAI/bge-m3"

    class _Moteur:
        def __init__(self, bloquer=False):
            self.bloquer = bloquer
            self.commence = threading.Event()
            self.continuer = threading.Event()

        def embed_one(self, texte, delai_s):
            self.commence.set()
            if self.bloquer:
                self.continuer.wait(2)
            return [1.0] + [0.0] * 1023, 7

    @contextmanager
    def _serveur(moteur):
        serveur = ServeurEmbeddingsLocal(("127.0.0.1", 0), cle=CLE, moteur=moteur, delai_s=1.0)
        thread = threading.Thread(target=serveur.serve_forever, daemon=True)
        thread.start()
        try:
            hote, port = serveur.server_address
            yield f"http://{hote}:{port}/v1"
        finally:
            serveur.shutdown()
            serveur.server_close()
            thread.join(2)

    def _post(base, token, payload):
        req = urllib.request.Request(
            f"{base}/embeddings",
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        return urllib.request.urlopen(req, timeout=2)

    def _post_octets(base, token, brut, content_type="application/json"):
        req = urllib.request.Request(
            f"{base}/embeddings",
            data=brut,
            headers={"Authorization": f"Bearer {token}", "Content-Type": content_type},
            method="POST",
        )
        return urllib.request.urlopen(req, timeout=2)

    def test_http_openai_authentifie_et_renvoie_un_vecteur_dans_le_format_client():
        with _serveur(_Moteur()) as base, _post(base, CLE, {"model": MODELE, "input": "texte fictif"}) as response:
            body = json.loads(response.read())
        assert body["model"] == MODELE
        assert body["data"][0]["index"] == 0
        assert len(body["data"][0]["embedding"]) == 1024
        assert body["usage"]["prompt_tokens"] == 7

    def test_auth_bearer_obligatoire_et_erreur_ne_revele_ni_cle_ni_texte():
        texte = "contenu-confidentiel-test"
        with _serveur(_Moteur()) as base:
            with pytest.raises(urllib.error.HTTPError) as erreur:
                _post(base, "x" * 32, {"model": MODELE, "input": texte})
            corps = erreur.value.read().decode()
        assert erreur.value.code == 401
        assert CLE not in corps and texte not in corps and "x" * 32 not in corps

    @pytest.mark.parametrize("payload", [
        {"model": MODELE, "input": ["a", "b"]},
        {"model": "autre", "input": "texte fictif"},
    ], ids=["batch", "modele"])
    def test_refuse_batch_superieur_a_un_et_modele_inconnu(payload):
        with _serveur(_Moteur()) as base:
            with pytest.raises(urllib.error.HTTPError) as erreur:
                _post(base, CLE, payload)
            assert erreur.value.code == 422

    @pytest.mark.parametrize(
        ("brut", "content_type", "statut"),
        [
            (b'{"model":"BAAI/bge-m3","input":"x","input":"y"}', "application/json", 400),
            (b'{"model":"BAAI/bge-m3","input":"\\ud800"}', "application/json", 422),
            (b'{"model":"BAAI/bge-m3","input":"x"}', "application/json; charset=iso-8859-1", 415),
            (b'{"model":"BAAI/bge-m3","input":"\xff"}', "application/json", 400),
        ],
    )
    def test_json_duplique_surrogate_charset_et_octets_invalides_refuses(brut, content_type, statut):
        with _serveur(_Moteur()) as base, pytest.raises(urllib.error.HTTPError) as erreur:
            _post_octets(base, CLE, brut, content_type)
        assert erreur.value.code == statut

    class _TokeniseurFictif:
        def __init__(self, compte):
            self.compte = compte

        def encode(self, texte, add_special_tokens=True):
            return type("Encodage", (), {"ids": list(range(self.compte)), "attention_mask": [1] * self.compte})()

    def test_limite_tokens_refuse_avant_inference_sans_tronquer():
        assert len(encoder_entree(_TokeniseurFictif(512), "fictif")[0]) == 512
        with pytest.raises(ErreurRequete, match="512"):
            encoder_entree(_TokeniseurFictif(513), "fictif")

    def test_runtime_refuse_python_non_qualifie_avec_diagnostic(monkeypatch):
        from opsys.memoire import serveur_embeddings_local as module

        monkeypatch.setattr(module.sys, "version_info", (3, 11, 9))
        with pytest.raises(RuntimeError, match="Python 3.12"):
            module._charger_dependances_runtime()

    def test_runtime_signale_extra_optionnel_absent_sans_traceback_brut(monkeypatch):
        import builtins

        from opsys.memoire import serveur_embeddings_local as module

        monkeypatch.setattr(module.sys, "version_info", (3, 12, 0))
        vrai_import = builtins.__import__

        def import_bloque(nom, *args, **kwargs):
            if nom == "numpy":
                raise ModuleNotFoundError("numpy absent")
            return vrai_import(nom, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", import_bloque)
        with pytest.raises(RuntimeError, match=r"\.\[embeddings-local\].*Python 3\.12"):
            module._charger_dependances_runtime()

    class _RunOptions:
        terminate = False

    class _OrtFake:
        RunOptions = _RunOptions

    class _SessionAnnulable:
        def __init__(self):
            self.sorti = threading.Event()
            self.options = None

        def run(self, noms, entrees, run_options=None):
            self.options = run_options
            while not run_options.terminate:
                time.sleep(0.002)
            self.sorti.set()
            raise RuntimeError("annule")

    def test_watchdog_annule_execution_et_attend_retour_avant_de_rendre_la_main():
        session = _SessionAnnulable()
        with pytest.raises(TimeoutError):
            _inference_avec_watchdog(session, {}, _OrtFake, delai_s=0.04)
        assert session.options.terminate is True
        assert session.sorti.is_set()

    def test_saturation_retourne_503_sans_creer_deuxieme_inference():
        moteur = _Moteur(bloquer=True)
        with _serveur(moteur) as base:
            premier = {}

            def premier_appel():
                try:
                    _post(base, CLE, {"model": MODELE, "input": "premier"})
                except urllib.error.HTTPError as exc:
                    premier["status"] = exc.code

            thread = threading.Thread(target=premier_appel)
            thread.start()
            assert moteur.commence.wait(1)
            with pytest.raises(urllib.error.HTTPError) as erreur:
                _post(base, CLE, {"model": MODELE, "input": "second"})
            assert erreur.value.code == 503
            moteur.continuer.set()
            thread.join(2)
            assert premier.get("status") is None

    def test_deadline_absolue_ferme_entetes_lents_et_libere_le_seul_thread(monkeypatch):
        from opsys.memoire import serveur_embeddings_local as module

        monkeypatch.setattr(module, "DELAI_ENTETES_CORPS_S", 0.08)
        with _serveur(_Moteur()) as base:
            _, port = base.removeprefix("http://").removesuffix("/v1").split(":")
            with socket.create_connection(("127.0.0.1", int(port)), timeout=1) as lent:
                lent.sendall(b"GET /healthz HTTP/1.1\r\nHost: local\r\nX-Slow:")
                time.sleep(0.2)
                assert lent.recv(1) == b""
            with urllib.request.urlopen(
                urllib.request.Request(
                    f"{base.replace('/v1', '')}/healthz", headers={"Authorization": f"Bearer {CLE}"}
                ),
                timeout=2,
            ) as response:
                assert response.status == 200

    class _MoteurCompte(_Moteur):
        def __init__(self):
            super().__init__(bloquer=True)
            self.appels = 0

        def embed_one(self, texte, delai_s):
            self.appels += 1
            return super().embed_one(texte, delai_s)

    class _ServeurObserve(ServeurEmbeddingsLocal):
        """Observe les fermetures réelles, sans remplacer socket ou traitement."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.rejet_ferme = threading.Event()
            self.threads_requete = set()

        def close_request(self, request):
            super().close_request(request)
            if self.moteur.commence.is_set() and not self.moteur.continuer.is_set():
                self.rejet_ferme.set()

        def process_request_thread(self, request, client_address):
            self.threads_requete.add(threading.get_ident())
            super().process_request_thread(request, client_address)

    @contextmanager
    def _inference_occupee():
        moteur = _MoteurCompte()
        serveur = _ServeurObserve(("127.0.0.1", 0), cle=CLE, moteur=moteur, delai_s=1.0)
        service = threading.Thread(target=serveur.serve_forever, kwargs={"poll_interval": 0.01})
        service.start()
        base = f"http://127.0.0.1:{serveur.server_address[1]}/v1"
        resultat = {}

        def premier_appel():
            try:
                with _post(base, CLE, {"model": MODELE, "input": "premier fictif"}) as response:
                    response.read()
                    resultat["status"] = response.status
            except Exception as exc:
                resultat["erreur"] = type(exc).__name__

        premier = threading.Thread(target=premier_appel)
        premier.start()
        try:
            assert moteur.commence.wait(1)
            yield serveur, moteur, base
        finally:
            moteur.continuer.set()
            premier.join(2)
            serveur.shutdown()
            serveur.server_close()
            service.join(2)
            assert not premier.is_alive() and not service.is_alive()
            assert resultat == {"status": 200}

    def _rejet_brut(serveur):
        client = socket.create_connection(serveur.server_address, timeout=2)
        # Le 503 arrive avant toute requête ; le laisser en attente ne simule
        # aucune socket/exception et permet de contrôler les écritures du client.
        prefixe = client.recv(4096, socket.MSG_PEEK)
        assert prefixe.startswith(b"HTTP/1.1 503 Service Unavailable\r\n")
        assert CLE.encode() not in prefixe
        return client

    def test_saturation_503_reste_lisible_entre_entetes_et_corps_retardes():
        class ClientRetarde(http.client.HTTPConnection):
            def connect(self):
                super().connect()
                assert self.sock.recv(4096, socket.MSG_PEEK).startswith(b"HTTP/1.1 503 ")

            def send(self, data):
                super().send(data)
                if isinstance(data, bytes) and data.startswith(b"POST "):
                    time.sleep(0.03)

        class HandlerRetarde(urllib.request.HTTPHandler):
            def http_open(self, req):
                return self.do_open(ClientRetarde, req)

        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), HandlerRetarde())
        with _inference_occupee() as (serveur, moteur, base):
            req = urllib.request.Request(
                f"{base}/embeddings", data=json.dumps({"model": MODELE, "input": "second fictif"}).encode(),
                headers={"Authorization": f"Bearer {CLE}", "Content-Type": "application/json"}, method="POST",
            )
            with pytest.raises(urllib.error.HTTPError) as erreur:
                opener.open(req, timeout=2)
            assert erreur.value.code == 503
            assert erreur.value.read() == b""
            assert moteur.appels == 1 and len(serveur.threads_requete) == 1

    def test_rejet_sans_entetes_ferme_dans_la_borne_absolue():
        with _inference_occupee() as (serveur, moteur, _), _rejet_brut(serveur) as client:
            debut = time.monotonic()
            assert serveur.rejet_ferme.wait(0.3)
            assert time.monotonic() - debut < 0.3
            assert client.recv(4096).startswith(b"HTTP/1.1 503 ")
            assert moteur.appels == 1 and len(serveur.threads_requete) == 1

    def test_octet_periodique_ne_reinitialise_pas_deadline_rejet():
        with _inference_occupee() as (serveur, moteur, _), _rejet_brut(serveur) as client:
            fin = time.monotonic() + 0.25
            def envoyer_lentement():
                while time.monotonic() < fin:
                    try:
                        client.sendall(b"x")
                    except OSError:
                        break
                    time.sleep(0.02)

            lent = threading.Thread(target=envoyer_lentement)
            lent.start()
            try:
                assert serveur.rejet_ferme.wait(0.2)
            finally:
                lent.join(1)
            assert not lent.is_alive()
            assert moteur.appels == 1 and len(serveur.threads_requete) == 1

    def test_eof_rejet_libere_accept_sans_attendre_deadline(monkeypatch):
        from opsys.memoire import serveur_embeddings_local as module

        # Étire seulement le budget de temps pour isoler la sortie sur EOF.
        monkeypatch.setattr(module, "DELAI_DRAIN_REJET_S", 1.0, raising=False)
        with _inference_occupee() as (serveur, moteur, _), _rejet_brut(serveur) as client:
            client.shutdown(socket.SHUT_WR)
            assert serveur.rejet_ferme.wait(0.3)
            assert moteur.appels == 1

    def test_cap_octets_rejet_libere_accept_independamment_du_temps(monkeypatch):
        from opsys.memoire import serveur_embeddings_local as module

        monkeypatch.setattr(module, "DELAI_DRAIN_REJET_S", 1.0, raising=False)
        with _inference_occupee() as (serveur, moteur, _), _rejet_brut(serveur) as client:
            # Contrat : 128KiB corps + 8KiB entêtes, et un octet de dépassement.
            # Au-delà du cap, le refus interprétable n'est pas garanti.
            with suppress(OSError):
                client.sendall(b"x" * (139_264 + 1))
            assert serveur.rejet_ferme.wait(0.3)
            assert moteur.appels == 1 and len(serveur.threads_requete) == 1

    def test_trois_rejets_bornent_accept_et_recuperent_sans_threads_supplementaires():
        clients = []
        with _inference_occupee() as (serveur, moteur, base):
            debut = time.monotonic()
            try:
                for _ in range(3):
                    clients.append(_rejet_brut(serveur))
                assert time.monotonic() - debut < 0.6
                assert moteur.appels == 1 and len(serveur.threads_requete) == 1
                moteur.continuer.set()
                req = urllib.request.Request(
                    base.replace("/v1", "") + "/healthz", headers={"Authorization": f"Bearer {CLE}"},
                )
                with urllib.request.urlopen(req, timeout=2) as response:
                    assert response.status == 200
                assert time.monotonic() - debut < 0.8
            finally:
                for client in clients:
                    client.close()
