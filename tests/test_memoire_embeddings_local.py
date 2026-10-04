"""Contrat HTTP borné du provider local, sans charger le modèle dans les tests unitaires."""

import importlib.util
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager

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

    def test_refuse_batch_superieur_a_un_et_modele_inconnu():
        with _serveur(_Moteur()) as base:
            for payload in ({"model": MODELE, "input": ["a", "b"]}, {"model": "autre", "input": "texte fictif"}):
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
