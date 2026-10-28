"""fictif: true — préconditions du harnais, sans installateur, core natif ni service hôte."""
import importlib.util
import json
from types import SimpleNamespace

import pytest
from tests import test_installateur_bout_en_bout as poste


def faux_core():
    spec = importlib.util.spec_from_file_location('faux_gateway_fixture', poste.FAUX_CORE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ports_choisis_simultanement_distincts_et_prises_liberees(tmp_path, monkeypatch):
    occupes = set()

    class Prise:
        def __enter__(self):
            self.port = None
            return self

        def bind(self, adresse):
            assert adresse == ('127.0.0.1', 0)
            self.port = next(p for p in (41001, 41002) if p not in occupes)
            occupes.add(self.port)

        def getsockname(self):
            return ('127.0.0.1', self.port)

        def __exit__(self, *_):
            occupes.discard(self.port)

    monkeypatch.setattr(poste.socket, 'socket', Prise)
    valeur = poste.Poste(tmp_path, macos=False)
    assert valeur.port_gateway != valeur.port_moteur
    assert (valeur.port_gateway, valeur.port_moteur) == (41001, 41002)
    assert occupes == set()


@pytest.mark.parametrize('arret_demande,attendu', [(False, 17), (True, 0)])
def test_gateway_factice_propage_echec_enfant_mais_arret_demande_reste_normal(tmp_path, monkeypatch,
                                                                          arret_demande, attendu):
    core = faux_core()
    (tmp_path / 'opsys').mkdir()
    (tmp_path / 'opsys/metier.json').write_text(json.dumps(dict(actif=True, commande=['enfant-FICTIF'],
                                                               dossier=str(tmp_path))))
    actions, signaux = [], {}

    class Enfant:
        stdout = ()
        code = None

        def poll(self):
            return self.code

        def terminate(self):
            actions.append('terminate')
            self.code = 0

        def wait(self, timeout):
            assert timeout == 15
            return self.code

    enfant = Enfant()

    class Serveur:
        def __init__(self, adresse, handler):
            assert adresse == ('127.0.0.1', 41001) and handler is core.Sondes

        def serve_forever(self):
            raise AssertionError('aucun thread réseau dans ce test unitaire')

        def shutdown(self):
            actions.append('shutdown')

    class Thread:
        def __init__(self, **kwargs):
            assert kwargs['daemon'] is True

        def start(self):
            actions.append('thread')

    def attendre(_):
        if arret_demande:
            signaux[core.signal.SIGTERM]()
        else:
            enfant.code = 17

    monkeypatch.setattr(core, 'ThreadingHTTPServer', Serveur)
    monkeypatch.setattr(core.threading, 'Thread', Thread)
    monkeypatch.setattr(core.signal, 'signal', lambda signal, action: signaux.setdefault(signal, action))
    monkeypatch.setattr(core.subprocess, 'Popen', lambda *a, **kw: enfant)
    monkeypatch.setattr(core.time, 'sleep', attendre)
    assert core.gateway_au_premier_plan(SimpleNamespace(etat=tmp_path, profil='opsys'), 41001) == attendu
    assert actions.count('thread') == 2 and actions.count('shutdown') == 1
    assert ('terminate' in actions) is arret_demande
