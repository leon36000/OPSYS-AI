"""fictif: true — journaux d'accès d'un serveur privé sur loopback isolé."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('fixture_console_logs_visites',
    Path(__file__).with_name('test_console_visites_chantier.py'))
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
client_crm, planning = f.client_crm, f.planning


def test_serveur_http_access_log_sans_cookie_ni_csrf(client_crm, planning, monkeypatch):
    import logging
    import socket
    import threading
    import time
    from dataclasses import replace
    from datetime import UTC, datetime
    from html.parser import HTMLParser

    import httpx
    import uvicorn

    from opsys.console import metier, securite

    class HorlogeFictive(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2030, 6, 3, 12, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(metier, 'datetime', HorlogeFictive)

    class Formulaires(HTMLParser):
        def __init__(self):
            super().__init__()
            self.forms, self.courant = [], None

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == 'form':
                self.courant = {}
                self.forms.append(self.courant)
            elif tag == 'input' and self.courant is not None and 'name' in attrs:
                self.courant[attrs['name']] = attrs.get('value', '')

        def handle_endtag(self, tag):
            if tag == 'form':
                self.courant = None

    class Capture(logging.Handler):
        def __init__(self):
            super().__init__()
            self.messages = []

        def emit(self, record):
            self.messages.append(record.getMessage())

    f.f.base._connecter(client_crm, 'admin.fictif')
    cookie = next(c for c in client_crm.cookies.jar if c.name == securite.NOM_COOKIE)
    session_fictive = securite.lire_session(cookie.value, f.f.base.SECRET)
    cookie.value = securite.signer_session(replace(session_fictive, expire=4102444800), f.f.base.SECRET)
    cookies = dict(client_crm.cookies)
    assert cookies and all(cookies.values())
    logger = logging.getLogger('uvicorn.access')
    capture = Capture()
    ancien_niveau = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(capture)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('127.0.0.1', 0))
    sock.listen(16)
    port = sock.getsockname()[1]
    serveur = uvicorn.Server(uvicorn.Config(client_crm.app, log_config=None, access_log=True,
                                             lifespan='off', timeout_graceful_shutdown=2))
    thread = threading.Thread(target=serveur.run, kwargs={'sockets': [sock]}, daemon=True)
    thread.start()
    try:
        limite = time.monotonic() + 5
        while not serveur.started and thread.is_alive() and time.monotonic() < limite:
            time.sleep(0.01)
        assert serveur.started
        iid = planning[1]['lead-fictif-001']
        route = '/crm/visites?intervention_id=' + iid
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', cookies=cookies, timeout=5,
                          trust_env=False, follow_redirects=False) as client:
            page = client.get(route)
            assert page.status_code == 200
            forms = Formulaires()
            forms.feed(page.text)
            prevoir = next(x for x in forms.forms if x.get('operation') == 'prevoir')
            assert prevoir['csrf']
            faux_csrf = 'csrf-secret-fictif-dans-corps'
            assert client.post(route, data={**prevoir, 'csrf': faux_csrf}).status_code == 403
            reponse = client.post(route, data=prevoir)
            assert reponse.status_code == 303
            assert client.get(route).status_code == 200
            assert client.get('/crm/visites/reprise?intervention_id=' + iid).status_code == 409
        messages = '\n'.join(capture.messages)
        assert len(capture.messages) >= 3 and 'GET ' in messages and 'POST ' in messages
        assert iid in messages  # Les identifiants de route restent visibles dans l'accès serveur.
        assert prevoir['csrf'] not in messages
        assert faux_csrf not in messages
        assert all(cookie not in messages for cookie in cookies.values())
    finally:
        serveur.should_exit = True
        thread.join(timeout=5)
        sock.close()
        logger.removeHandler(capture)
        logger.setLevel(ancien_niveau)
    assert not thread.is_alive()
