"""ASGI boundary tests and final real SQLite/CAS cases; no Core Gateway or phone proof."""
import hashlib
import json
import random
import struct
import zlib
from importlib import import_module
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import anyio
import pytest

from opsys import contexte
from opsys.stockage.schema import META as SCHEMA_META

# Schéma courant déclaré : toutes les lignes, y compris la file F4 et Alembic.
TABLES_SQLITE = set(SCHEMA_META.tables) | {"alembic_version"}

JETON = 'BRIDGE-FICTIF-distinct-01234567890123456789'
SELECTION = {'wct_id': 'WCT-FICTIF', 'preuve': {'index': 0, 'hash_maillon': 'a' * 64}, 'position_photo': 0}
IDENTITE = {'personne': 'admin.fictif', 'role': 'admin'}
BODY = {'selection': SELECTION, 'identite': IDENTITE, 'appareil_id': 'DEVICE-FICTIF'}
def png_fictif(largeur=400, hauteur=256, pixels=None):
    def chunk(nom, data):
        return struct.pack('>I', len(data)) + nom + data + struct.pack('>I', zlib.crc32(nom + data))
    raw = pixels if pixels is not None else b''.join(
        b'\0' + random.Random(1000 + y).randbytes(largeur * 3) for y in range(hauteur)
    )
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', largeur, hauteur, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


OCTETS = png_fictif()


def factory(**kwargs):
    return import_module('opsys.preuves_photo_bridge').creer_pont_photos_preuves(JETON, **kwargs)


def executer(app, body=None, headers=None, apres_envoi=None, chemin="/mcp/fichiers/m6-preuves"):
    messages = []
    corps = json.dumps(BODY if body is None else body).encode() if not isinstance(body, bytes) else body
    entetes = [(b'authorization', ('Bearer ' + JETON).encode())] if headers is None else headers
    scope = {'type': 'http', 'method': 'POST', 'path': chemin, 'headers': entetes}

    async def run():
        premier = True
        async def receive():
            nonlocal premier
            if premier:
                premier = False
                return {'type': 'http.request', 'body': corps, 'more_body': False}
            await anyio.sleep_forever()
        async def send(message):
            messages.append(message)
            if apres_envoi:
                apres_envoi(message)
        await app(scope, receive, send)
    anyio.run(run)
    return messages


def collaborateurs():
    lectures, validations = [], []
    def lire(*args):
        lectures.append((args, contexte.identite_appelante()))
        return {'accepte': True, 'reference': 'fichier:sha256:' + hashlib.sha256(OCTETS).hexdigest(),
                'empreinte_sha256': hashlib.sha256(OCTETS).hexdigest(), 'type_mime': 'image/png',
                'taille_octets': len(OCTETS), 'octets': OCTETS}
    def revalider(*args):
        validations.append((args, contexte.identite_appelante()))
        return {'accepte': True}
    return lire, revalider, lectures, validations


def test_flux_binaire_sha_exact_et_contexte_stable_sans_relecture_cas_par_fragment():
    lire, revalider, lectures, validations = collaborateurs()
    messages = executer(factory(lecteur=lire, revalider=revalider))
    start = messages[0]
    assert start['status'] == 200
    entetes = dict(start['headers'])
    assert entetes[b'content-type'] == b'image/png' and entetes[b'cache-control'] == b'no-store'
    assert entetes[b'x-content-type-options'] == b'nosniff'
    assert int(entetes[b'content-length']) == len(OCTETS)
    assert entetes[b'x-opsys-sha256'].decode() == hashlib.sha256(OCTETS).hexdigest()
    bodies = [m['body'] for m in messages if m['type'] == 'http.response.body']
    assert b''.join(bodies) == OCTETS and max(map(len, bodies)) <= 65536
    assert len(lectures) == 1 and len(validations) >= 3
    for args, identity in lectures + validations:
        assert args == ('WCT-FICTIF', {'index': 0, 'hash_maillon': 'a' * 64}, 0)
        assert identity == contexte.IdentiteAppelante('admin.fictif', 'admin', source='appareil')
    assert contexte.identite_appelante() is None


@pytest.mark.parametrize('headers', [[], [(b'authorization', b'Bearer MCP-PUBLIC-FICTIF')],
    [(b'authorization', ('Bearer ' + JETON).encode()), (b'authorization', ('Bearer ' + JETON).encode())]],
    ids=['absent', 'public', 'duplicate'])
def test_credential_bridge_seul_et_unique_avant_toute_source(headers):
    lire, revalider, lectures, validations = collaborateurs()
    result = executer(factory(lecteur=lire, revalider=revalider), headers=headers)
    assert result[0]['status'] == 401 and not lectures and not validations


@pytest.mark.parametrize('body', [
    BODY | {'agentId': 'FORGE'}, BODY | {'identite': IDENTITE | {'source': 'console'}},
    BODY | {'selection': SELECTION | {'reference': 'fichier:sha256:' + 'a' * 64}},
    BODY | {'selection': SELECTION | {'position_photo': True}},
    BODY | {'identite': {'personne': ' ', 'role': 'admin'}},
    b'{"selection":null,"selection":null}', b' ' * 16385,
], ids=['unknown', 'source', 'hash', 'boolean', 'blank', 'duplicate', 'oversized'])
def test_corps_ferme_duplique_borne_avant_source(body):
    lire, revalider, lectures, validations = collaborateurs()
    result = executer(factory(lecteur=lire, revalider=revalider), body=body)
    assert result[0]['status'] in {400, 413} and not lectures and not validations


def test_blob_corrompu_refuse_avant_headers_image():
    _, revalider, _, validations = collaborateurs()
    def lire(*args):
        return {'accepte': True, 'reference': 'fichier:sha256:' + 'a' * 64, 'empreinte_sha256': 'a' * 64,
                'type_mime': 'image/png', 'taille_octets': len(OCTETS), 'octets': OCTETS}
    result = executer(factory(lecteur=lire, revalider=revalider))
    assert result[0]['status'] == 409 and dict(result[0]['headers'])[b'content-type'] == b'application/json'
    assert not validations


def test_retrait_autorite_interrompt_avant_octets_suivants_sans_json_dans_image():
    lire, _, lectures, _ = collaborateurs()
    validations = []
    retire = False
    def revalider(*args):
        validations.append(args)
        return {'accepte': not retire}
    messages = []
    def observer(message):
        nonlocal retire
        messages.append(message)
        if message['type'] == 'http.response.body' and message.get('body'):
            retire = True
    with pytest.raises(ExceptionGroup) as erreur:
        executer(factory(lecteur=lire, revalider=revalider), apres_envoi=observer)
    assert any(isinstance(e, import_module('opsys.preuves_photo_bridge').AutoritePhotoRetiree)
               for e in erreur.value.exceptions)
    assert messages[0]['status'] == 200 and len(lectures) == 1
    bodies = [m['body'] for m in messages if m['type'] == 'http.response.body']
    assert 0 < sum(map(len, bodies)) < len(OCTETS) and b''.join(bodies) == OCTETS[:len(b''.join(bodies))]
    assert contexte.identite_appelante() is None


def test_disconnect_avant_lecture_ne_produit_aucun_header_ni_pixel():
    lire, revalider, _, _ = collaborateurs()
    app = factory(lecteur=lire, revalider=revalider)
    messages = []
    async def run():
        premier = True
        async def receive():
            nonlocal premier
            if premier:
                premier = False
                return {'type': 'http.request', 'body': json.dumps(BODY).encode(), 'more_body': False}
            return {'type': 'http.disconnect'}
        async def send(message):
            messages.append(message)
        await app({'type': 'http', 'method': 'POST', 'path': '/mcp/fichiers/m6-preuves',
                   'headers': [(b'authorization', ('Bearer ' + JETON).encode())]}, receive, send)
    anyio.run(run)
    assert messages == []


def test_autorite_retiree_avant_headers_reste_refus_json_sans_pixels():
    lire, _, lectures, _ = collaborateurs()
    messages = executer(factory(lecteur=lire, revalider=lambda *args: {'accepte': False}))
    assert len(lectures) == 1 and messages[0]['status'] == 403
    assert dict(messages[0]['headers'])[b'content-type'] == b'application/json'
    assert b''.join(m['body'] for m in messages if m['type'] == 'http.response.body') != OCTETS


def test_attribution_changee_par_helper_refuse_avant_emission():
    lire, _, _, _ = collaborateurs()
    verdict = {'accepte': True, 'autorite': {'personne': 'autre.fictif', 'role': 'admin', 'source': 'appareil'}}
    messages = executer(factory(lecteur=lire, revalider=lambda *args: verdict))
    assert messages[0]['status'] == 403


def test_route_departements_desactivee_par_defaut_refuse_meme_jeton_public(departements_demo, session, monkeypatch):
    from opsys.serveur_mcp import application_http_departements
    monkeypatch.delenv('OPSYS_M6_PREUVES_BRIDGE_JETON', raising=False)
    app = application_http_departements(departements_demo, session, JETON)
    assert executer(app)[0]['status'] == 404


@pytest.mark.parametrize('autre', ['public', 'context', 'short'], ids=['public', 'context', 'short'])
def test_configuration_photo_refuse_credential_publique_ou_courte(departements_demo, session, monkeypatch, autre):
    from opsys.serveur_mcp import application_http_departements
    public, contexte_prive = 'MCP-PUBLIC-FICTIF-0123456789012345', 'MCP-CONTEXT-FICTIF-0123456789012345'
    token = public if autre == 'public' else contexte_prive if autre == 'context' else 'court'
    monkeypatch.setenv('OPSYS_M6_PREUVES_BRIDGE_JETON', token)
    with pytest.raises(ValueError, match='photo'):
        application_http_departements(departements_demo, session, public, jeton_contexte=contexte_prive)


def test_route_departements_photo_autorisee_par_bridge_distinct(departements_demo, session, monkeypatch):
    from pathlib import Path

    from m6_material_control import outils

    from opsys import stockage
    from opsys.departements import charger_departements
    from opsys.serveur_mcp import application_http_departements
    lire, revalider, lectures, validations = collaborateurs()
    connexions = []
    def avec_factory(callback):
        def executer_callback(*args, cnx_factory):
            with cnx_factory() as cnx:
                connexions.append((cnx.engine.url, stockage.connexion_courante() is cnx))
            return callback(*args)
        return executer_callback
    monkeypatch.setattr(outils, 'autoriser_et_lire_photo', avec_factory(lire))
    monkeypatch.setattr(outils, 'revalider_autorite_photo', avec_factory(revalider))
    monkeypatch.setenv('OPSYS_M6_PREUVES_BRIDGE_JETON', JETON)
    deps = charger_departements(Path(__file__).parents[1] / 'departments')
    app = application_http_departements(deps, session, 'MCP-PUBLIC-FICTIF-0123456789012345')
    messages = executer(app)
    assert messages[0]['status'] == 200
    assert len(lectures) == 1 and validations and all(lie for _, lie in connexions)
    assert b''.join(m['body'] for m in messages if m['type'] == 'http.response.body') == OCTETS
    assert executer(app, headers=[(b'authorization', b'Bearer MCP-PUBLIC-FICTIF-0123456789012345')])[0]['status'] == 401


def test_endpoint_revalidation_ne_lit_aucun_pixel_et_retourne_metadata_liees():
    lire, _, lectures, _ = collaborateurs()
    def revalider(*args):
        return {'accepte': True, 'reference': 'fichier:sha256:' + hashlib.sha256(OCTETS).hexdigest(),
                'empreinte_sha256': hashlib.sha256(OCTETS).hexdigest(), 'type_mime': 'image/png',
                'taille_octets': len(OCTETS), 'autorite': IDENTITE | {'source': 'appareil'}}
    messages = executer(factory(lecteur=lire, revalider=revalider), chemin='/mcp/fichiers/m6-preuves/revalider')
    assert messages[0]['status'] == 200 and not lectures
    body = json.loads(b''.join(m['body'] for m in messages if m['type'] == 'http.response.body'))
    assert body == {'ok': True, 'resultat': revalider()}
    assert dict(messages[0]['headers'])[b'cache-control'] == b'no-store'


def test_endpoint_revalidation_refuse_role_retire_sans_lecture_cas():
    lire, _, lectures, _ = collaborateurs()
    messages = executer(factory(lecteur=lire, revalider=lambda *args: {'accepte': False}),
                        chemin='/mcp/fichiers/m6-preuves/revalider')
    assert messages[0]['status'] == 403 and not lectures


@pytest.mark.parametrize('octets', [b'\x89PNG\r\n\x1a\nFICTIF-imposteur', OCTETS[:70],
    png_fictif(9000, 2, b'\0'), png_fictif(8192, 8192, b'\0')],
    ids=['magic-only', 'truncated', 'dimension', 'pixel-budget'])
def test_image_non_decodable_ou_dimension_hors_budget_refuse_avant_flux(octets):
    _, revalider, _, validations = collaborateurs()
    def lire(*args):
        return {'accepte': True, 'reference': 'fichier:sha256:' + hashlib.sha256(octets).hexdigest(),
                'empreinte_sha256': hashlib.sha256(octets).hexdigest(), 'type_mime': 'image/png',
                'taille_octets': len(octets), 'octets': octets}
    result = executer(factory(lecteur=lire, revalider=revalider))
    assert result[0]['status'] == 409 and not validations
    assert dict(result[0]['headers'])[b'content-type'] == b'application/json'


@pytest.mark.parametrize('phase', ['initial', 'revalidation'], ids=['initial', 'revalidation'])
def test_panne_helper_fermee_sans_detail_interne_dans_reponse(phase):
    lire, revalider, _, _ = collaborateurs()
    def panne(*args):
        raise RuntimeError('CANARY-INTERNE-FICTIF-NE-DOIT-PAS-SORTIR')
    messages = executer(factory(lecteur=panne if phase == 'initial' else lire,
                               revalider=panne if phase == 'revalidation' else revalider))
    assert messages[0]['status'] == 503
    body = b''.join(m['body'] for m in messages if m['type'] == 'http.response.body')
    assert b'CANARY' not in body and json.loads(body)['erreur'] == 'photo_service_indisponible'


def test_delai_borne_refus_avant_headers_sans_attente_reelle(monkeypatch):
    from contextlib import contextmanager
    @contextmanager
    def delai_expire(secondes):
        assert secondes == 120
        raise TimeoutError('FICTIF-clock-boundary')
        yield  # pragma: no cover -- contextmanager protocol, never reached
    monkeypatch.setattr(anyio, 'fail_after', delai_expire)
    lire, revalider, lectures, _ = collaborateurs()
    messages = executer(factory(lecteur=lire, revalider=revalider))
    assert messages[0]['status'] == 504 and not lectures


# These following tests use actual M4/M6/SQLite/CAS collaborators, with fictional data.

_sql_spec = spec_from_file_location('fixture_pont_photo_sql', Path(__file__).parents[1]
    / 'departments/m06-material-control/tests/test_preuves_pertes_bris_appareil.py')
_sql = module_from_spec(_sql_spec)
_sql_spec.loader.exec_module(_sql)
monde = _sql.monde


def preparer_photo_sql():
    a = _sql.preparer(n=1)
    import base64

    from opsys import fichiers, stockage
    empreinte = hashlib.sha256(OCTETS).hexdigest()
    nombre = -(-len(OCTETS) // fichiers.TAILLE_BLOC_OCTETS)
    with stockage.transaction() as cnx:
        for index in range(nombre):
            bloc = OCTETS[index * fichiers.TAILLE_BLOC_OCTETS:(index + 1) * fichiers.TAILLE_BLOC_OCTETS]
            recu = fichiers.deposer_bloc(cnx, empreinte, len(OCTETS), 'image/png', index, nombre,
                                        base64.b64encode(bloc).decode())
            assert recu.accepte, recu
    a['preuves_lignes'][0]['photos'] = [fichiers.reference_pour(empreinte)]
    r = _sql.executer(a)
    assert r['ok'] and r['resultat']['accepte'], r
    ref = r['resultat']['resultat']['preuves'][0]['reference_preuve']
    return {'selection': {'wct_id': a['wct_id'], 'preuve': {'index': ref['index'], 'hash_maillon': ref['hash_maillon']},
                         'position_photo': 0},
            'identite': {'personne': _sql.ADMIN.personne, 'role': 'admin'}, 'appareil_id': 'APP-PHOTO-FICTIF'}


def test_asgi_sql_cas_pixels_decodes_lecture_unique_et49tables_inchangees(monde):
    from m6_material_control import outils
    body = preparer_photo_sql()
    calls = []
    original = outils.fichiers.lire_blob_verifie
    def observe(*args):
        calls.append(args)
        return original(*args)
    monde[1].setattr(outils.fichiers, 'lire_blob_verifie', observe)
    avant = _sql.fx._tables()
    messages = executer(factory(), body=body)
    assert messages[0]['status'] == 200
    assert b''.join(m['body'] for m in messages if m['type'] == 'http.response.body') == OCTETS
    assert len(calls) == 1 and set(avant) == TABLES_SQLITE and avant == _sql.fx._tables()
    validation = executer(factory(), body=body, chemin='/mcp/fichiers/m6-preuves/revalider')
    assert validation[0]['status'] == 200 and len(calls) == 1 and avant == _sql.fx._tables()


def test_asgi_sql_retrait_admin_apres_fragment_interrompt_sans_cas_supplementaire(monde):
    from opsys import identite, stockage
    body = preparer_photo_sql()
    messages = []
    retire = False
    def observer(message):
        nonlocal retire
        messages.append(message)
        if message['type'] == 'http.response.body' and message.get('body') and not retire:
            with stockage.transaction() as cnx:
                identite.retirer_role(cnx, _sql.ADMIN.personne, 'admin')
            retire = True
    with pytest.raises(ExceptionGroup) as erreur:
        executer(factory(), body=body, apres_envoi=observer)
    assert any(isinstance(e, import_module('opsys.preuves_photo_bridge').AutoritePhotoRetiree)
               for e in erreur.value.exceptions)
    recu = b''.join(m['body'] for m in messages if m['type'] == 'http.response.body')
    assert 0 < len(recu) < len(OCTETS) and recu == OCTETS[:len(recu)]
    avant = _sql.fx._tables()
    refuse = executer(factory(), body=body, chemin='/mcp/fichiers/m6-preuves/revalider')
    assert refuse[0]['status'] == 403 and avant == _sql.fx._tables()


def test_factory_application_foreign_base_refuse_avant_sources(session, monkeypatch, tmp_path):
    from contextlib import contextmanager

    from opsys import stockage
    from opsys.departements import charger_departements
    from opsys.serveur_mcp import application_http_departements
    monkeypatch.setenv('OPSYS_M6_PREUVES_BRIDGE_JETON', JETON)
    @contextmanager
    def etrangere():
        with stockage.transaction('sqlite:///' + str(tmp_path / 'FOREIGN-FICTIF.sqlite')) as cnx:
            yield cnx
    with pytest.raises(ValueError, match='base canonique'):
        application_http_departements(charger_departements(), etrangere, 'PUBLIC-FICTIF-01234567890123456789')


def test_route_configuree_jeton_prive_revoque_interrompt_avant_fragment_suivant(monde):
    from opsys import stockage
    from opsys.departements import charger_departements
    from opsys.serveur_mcp import application_http_departements
    body = preparer_photo_sql()
    patch = monde[1]
    patch.setenv('OPSYS_M6_PREUVES_BRIDGE_JETON', JETON)
    app = application_http_departements(charger_departements(), stockage.transaction,
                                       'PUBLIC-FICTIF-01234567890123456789')
    messages = []
    def observer(message):
        messages.append(message)
        if message['type'] == 'http.response.body' and message.get('body'):
            patch.delenv('OPSYS_M6_PREUVES_BRIDGE_JETON', raising=False)
    avant = _sql.fx._tables()
    with pytest.raises(ExceptionGroup) as erreur:
        executer(app, body=body, apres_envoi=observer)
    assert any(isinstance(e, import_module('opsys.preuves_photo_bridge').AutoritePhotoRetiree)
               for e in erreur.value.exceptions)
    recu = b''.join(m['body'] for m in messages if m['type'] == 'http.response.body')
    assert 0 < len(recu) < len(OCTETS) and recu == OCTETS[:len(recu)] and avant == _sql.fx._tables()
