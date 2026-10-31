"""E3 : la route console admin de déclaration d'équipe V3 (CSRF, rôle relu en base, rejeu idempotent). Fictif."""
import importlib.util
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

FICTIF = True
_spec = importlib.util.spec_from_file_location('visites_cedule_fixture_equipe',
                                               Path(__file__).with_name('test_console_cedule.py'))
f = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(f)
client_crm, planning = f.client_crm, f.planning


class _Formulaires(HTMLParser):
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


def _formulaire(html, operation):
    lecteur = _Formulaires()
    lecteur.feed(html)
    trouves = [x for x in lecteur.forms if x.get('operation') == operation]
    return trouves[0] if trouves else None


def _preuves(session):
    from m4_field_ops import equipes_pointees_v3
    from m4_field_ops.registre import Registre

    from opsys import stockage
    with session():
        return [m for m in Registre(stockage.maillons('m04-field-ops', 'principal')).lire()
                if m.get('type_entree') == equipes_pointees_v3.TYPE]


def test_console_admin_declare_l_equipe_csrf_rejeu_et_refus(client_crm, planning, session, monkeypatch):
    from dataclasses import replace

    from m4_field_ops import calendrier_civil, etats
    from m4_field_ops.registre import Registre

    from opsys import equipes, identite, stockage
    from opsys.console import metier, securite

    class HorlogeFictive(datetime):
        instant = datetime(2030, 6, 3, 12, 0, 0, tzinfo=UTC)

        @classmethod
        def now(cls, tz=None):
            return cls.instant.astimezone(tz)
    monkeypatch.setattr(metier, 'datetime', HorlogeFictive)
    _, ids, _, _ = planning
    iid = ids['lead-fictif-001']
    chemin = '/crm/visites?intervention_id=' + iid
    f.base._connecter(client_crm, 'admin.fictif')
    cookie = next(c for c in client_crm.cookies.jar if c.name == securite.NOM_COOKIE)
    sess = securite.lire_session(cookie.value, f.base.SECRET)
    cookie.value = securite.signer_session(replace(sess, expire=4102444800), f.base.SECRET)
    assert client_crm.post(chemin, data=_formulaire(client_crm.get(chemin).text, 'prevoir'),
                           follow_redirects=False).status_code == 303
    ouvrir = _formulaire(client_crm.get(chemin).text, 'ouvrir')
    assert client_crm.post(chemin, data=ouvrir, follow_redirects=False).status_code == 303
    with session():
        reg = Registre(stockage.maillons('m04-field-ops', 'principal'))
        ligne = next(x for x in calendrier_civil.lire_semaine(reg, '2030-06-03')['interventions']
                     if x['intervention_id'] == iid)
        equipe = ligne['equipe_id']
        assert etats.transitionner(iid, 'en_route', reg, '2030-06-03T08:30:00-04:00',
                                   assignation={'intervention_id': iid, 'technicien_id': equipe})[1] is None
    # Sans profil des équipes, aucune déclaration n'est proposée (jamais une équipe devinée).
    assert _formulaire(client_crm.get(chemin).text, 'pointer_equipe') is None
    modele = {'membres': ['employe'], 'competences': ['gouttieres'],
              'depot': {'id': 'depot-fictif', 'latitude_microdegres': 45735000, 'longitude_microdegres': -73455000},
              'quarts': [{'jour': 0, 'debut_min': 480, 'fin_min': 1020}]}
    equipes.enregistrer_equipes({'liste': [{'id': equipe, **modele},
                                           {'id': 'eq-autre-fictive', **modele, 'membres': ['nathan']}]})
    HorlogeFictive.instant = datetime(2030, 6, 3, 13, 0, 0, tzinfo=UTC)
    page = client_crm.get(chemin)
    assert 'ne prouve aucune présence individuelle' in page.text
    declarer = {**_formulaire(page.text, 'pointer_equipe'), 'action': 'arrivee'}
    assert declarer['equipe_id'] == equipe and declarer['visite_id'] == ouvrir['visite_id']
    # CSRF incorrect, équipe d'une autre visite, champ inconnu : rien d'écrit.
    assert client_crm.post(chemin, data={**declarer, 'csrf': 'csrf-incorrect-fictif'},
                           follow_redirects=False).status_code == 403
    assert client_crm.post(chemin, data={**declarer, 'equipe_id': 'eq-autre-fictive'},
                           follow_redirects=False).status_code == 409
    assert client_crm.post(chemin, data={**declarer, 'personne': 'employe'},
                           follow_redirects=False).status_code == 400
    assert client_crm.post(chemin, data={**declarer, 'action': 'presence'},
                           follow_redirects=False).status_code == 400
    assert _preuves(session) == []
    assert client_crm.post(chemin, data=declarer, follow_redirects=False).status_code == 303
    (preuve,) = _preuves(session)
    assert preuve['auteur'] == {'personne': 'admin.fictif', 'role': 'admin'}
    assert preuve['sujet'] == {'type': 'equipe', 'id': equipe}
    assert preuve['horodatage'] == HorlogeFictive.instant.isoformat()
    # Double envoi du même formulaire : rejeu, aucune seconde preuve ; même clé pour une autre action : conflit.
    HorlogeFictive.instant = datetime(2030, 6, 3, 13, 1, 0, tzinfo=UTC)
    assert client_crm.post(chemin, data=declarer, follow_redirects=False).status_code == 303
    assert client_crm.post(chemin, data={**declarer, 'action': 'depart'},
                           follow_redirects=False).status_code == 409
    assert len(_preuves(session)) == 1
    # Rôle admin retiré en base : la session ne suffit plus.
    with session() as cnx:
        identite.retirer_role(cnx, 'admin.fictif', 'admin')
    nouveau = {**declarer, 'mutation_id': '00000000-0000-4000-8000-000000000001', 'action': 'pause_debut'}
    assert client_crm.post(chemin, data=nouveau, follow_redirects=False).status_code in {303, 403}
    assert len(_preuves(session)) == 1
