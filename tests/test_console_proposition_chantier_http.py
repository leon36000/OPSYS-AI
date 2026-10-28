"""fictif: true — proposer depuis la fiche devis, relire le brouillon réel, sans affecter."""
import importlib.util
from html.parser import HTMLParser
from pathlib import Path

from m4_field_ops import registre
from sqlalchemy import select, update

from opsys import contexte, equipes, identite, stockage
from opsys.capacites import Capacites
from opsys.stockage import codec
from opsys.stockage.schema import REGISTRES

spec = importlib.util.spec_from_file_location('crm08_proposition_http_fixture',
                                            Path(__file__).with_name('test_console_proposition_chantier.py'))
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
pret, affaire, catalogue, client_crm = p.pret, p.affaire, p.catalogue, p.client_crm


class Formulaire(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.champs, self.actif, self.action = {}, False, None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'form':
            self.actif = a.get('action', '').endswith('/propositions-chantier')
            if self.actif:
                self.action = a['action']
        if tag == 'input' and self.actif and 'name' in a:
            assert a['name'] not in self.champs
            self.champs[a['name']] = a.get('value', '')

    def handle_endtag(self, tag):
        if tag == 'form':
            self.actif = False


def test_devis_pret_proposition_reelle_et_revue_http_sans_affectation(pret, catalogue, session):
    avant = p.m.base._instantane_base(session)
    page = catalogue.get(pret['route'])
    assert page.status_code == 200, page.text
    form = Formulaire(page.text)
    assert form.action is not None, page.text
    assert set(form.champs) == {'csrf', 'empreinte_attendue', 'mutation_id'}
    assert p.m.base._instantane_base(session) == avant
    route = pret['route'].removesuffix('/preparation-chantier') + '/propositions-chantier'
    reponse = catalogue.post(route, data=form.champs, follow_redirects=False)
    assert reponse.status_code == 303, reponse.text
    assert reponse.headers['location'].startswith(p.m.base.PREFIXE + route + '/')
    apres = p.m.base._instantane_base(session)
    revue = catalogue.get(reponse.headers['location'].removeprefix(p.m.base.PREFIXE))
    assert revue.status_code == 200, revue.text
    assert 'Proposition enregistrée' in revue.text
    assert 'eq-fictive' in revue.text and 'approximatives' in revue.text
    assert 'a_planifier' in revue.text and 'Jour 1 du plan' in revue.text
    assert 'Aucune affectation' in revue.text
    for prive in ('600.00', 'taux_marge', p.b.NUMERO):
        assert prive not in revue.text
    assert revue.headers['cache-control'] == 'no-store'
    assert p.m.base._instantane_base(session) == apres
    rejoue = catalogue.post(route, data=form.champs, follow_redirects=False)
    assert rejoue.status_code == 303 and rejoue.headers['location'] == reponse.headers['location']
    assert p.m.base._instantane_base(session) == apres
    with session() as cnx:
        lignes = [codec.decoder(i) for i in cnx.execute(select(REGISTRES.c.maillon).where(
            (REGISTRES.c.departement == 'm04-field-ops') & (REGISTRES.c.registre == 'principal'))).scalars()]
    assert len([i for i in lignes if i['type_entree'] == 'cedule_proposee']) == 1
    assert not any(i['type_entree'] in {'cedule_appliquee', 'assignation_technicien', 'cedule_datee'} for i in lignes)



def test_plan_rechaine_avec_sortie_incoherente_est_refuse(pret, catalogue, session):
    route = pret['route'].removesuffix('/preparation-chantier') + '/propositions-chantier'
    champs = Formulaire(catalogue.get(pret['route']).text).champs
    reponse = catalogue.post(route, data=champs, follow_redirects=False)
    assert reponse.status_code == 303
    with session() as cnx:
        chaine = registre.Registre(stockage.maillons('m04-field-ops', 'principal'))
        nouvelle = registre.Registre()
        for ligne in chaine.lire():
            if ligne['type_entree'] == 'cedule_proposee':
                ligne['sortie']['plan'][0]['equipe'] = 'equipe-inexistante-fictive'
            nouvelle.ajouter(ligne)
        nouvelle.assert_chaine()
        for rang, ligne in enumerate(nouvelle.lire()):
            cnx.execute(update(REGISTRES).where((REGISTRES.c.departement == 'm04-field-ops')
                & (REGISTRES.c.registre == 'principal') & (REGISTRES.c.rang == rang)).values(
                    maillon=codec.encoder(ligne)))
    avant = p.m.base._instantane_base(session)
    page = catalogue.get(reponse.headers['location'].removeprefix(p.m.base.PREFIXE))
    assert page.status_code == 503, page.text
    assert 'equipe-inexistante-fictive' not in page.text
    assert p.m.base._instantane_base(session) == avant



def _creer(pret, catalogue):
    route = pret['route'].removesuffix('/preparation-chantier') + '/propositions-chantier'
    form = Formulaire(catalogue.get(pret['route']).text)
    reponse = catalogue.post(route, data=form.champs, follow_redirects=False)
    assert reponse.status_code == 303, reponse.text
    return route, form.champs, reponse.headers['location'].removeprefix(p.m.base.PREFIXE)


def test_csrf_formulaire_ferme_borne_et_sans_effets(pret, catalogue, session):
    from urllib.parse import urlencode

    route = pret['route'].removesuffix('/preparation-chantier') + '/propositions-chantier'
    champs = Formulaire(catalogue.get(pret['route']).text).champs
    avant = p.m.base._instantane_base(session)
    assert catalogue.post(route, data={**champs, 'csrf': 'faux'}).status_code == 403
    for ajout in ({'confirme_par': 'usurpe'}, {'intervention_ids': 'etranger'}, {'horodatage': p.b.ACCEPTE_LE},
                  {'mutation_id': ''}, {'mutation_id': 'x' * 201}):
        assert catalogue.post(route, data={**champs, **ajout}).status_code == 400
    assert catalogue.post(route, content=urlencode(champs)+'&mutation_id=dup-fictif',
        headers={'content-type': 'application/x-www-form-urlencoded'}).status_code == 400
    assert catalogue.post(route, content=b'x' * 9000,
        headers={'content-type': 'application/x-www-form-urlencoded'}).status_code == 413
    assert catalogue.post(route, json=champs).status_code == 415
    assert catalogue.post(route+'?moteur=autre', data=champs).status_code == 400
    assert p.m.base._instantane_base(session) == avant


def test_not_ready_sans_bouton_et_post_refuse(affaire, catalogue, session):
    from opsys.console import proposition_chantier as port

    avant = p.m.base._instantane_base(session)
    page = catalogue.get(affaire['route'])
    assert page.status_code == 200 and 'Proposer une cédule' not in page.text
    with session() as cnx:
        apercu = port.preparer(cnx, affaire['deps'], p.AUTH, affaire['lead'], p.DEVIS)
    champs = dict(csrf=catalogue.get('/api/session').json()['csrf'],
                  empreinte_attendue=apercu['empreinte'], mutation_id='bloque-fictif')
    route = affaire['route'].removesuffix('/preparation-chantier') + '/propositions-chantier'
    assert catalogue.post(route, data=champs).status_code == 409
    assert p.m.base._instantane_base(session) == avant


def test_source_retiree_apres_affichage_refuse_http(pret, catalogue, session):
    route = pret['route'].removesuffix('/preparation-chantier') + '/propositions-chantier'
    champs = Formulaire(catalogue.get(pret['route']).text).champs
    outil = p.b._outils(pret['deps'], 'm06-material-control')['m6_liberer_reservation']
    with contexte.appele_par_appareil(contexte.IdentiteAppelante(p.AUTH.utilisateur, 'admin', source='console')):
        p.b._ok(p.executer_atomique(outil, dict(devis_id=p.DEVIS, motif='Retrait FICTIF', horodatage=p.b.ACCEPTE_LE)))
    assert p.b._drainer(pret['deps'], p.b.DEBUT)['quarantaines'] == 0
    avant = p.m.base._instantane_base(session)
    assert catalogue.post(route, data=champs).status_code == 409
    assert 'Proposer une cédule' not in catalogue.get(pret['route']).text
    assert p.m.base._instantane_base(session) == avant


def test_revue_historique_signale_profil_change_et_rejeu_sans_action(pret, catalogue, session):
    route, champs, revue = _creer(pret, catalogue)
    profil, erreur = equipes.charger_equipes()
    assert erreur is None
    profil['services']['gouttieres']['duree_min'] = 120
    equipes.enregistrer_equipes(profil)
    avant = p.m.base._instantane_base(session)
    page = catalogue.get(revue)
    assert page.status_code == 200 and 'modifiés depuis la proposition' in page.text
    assert catalogue.post(route, data=champs, follow_redirects=False).status_code == 303
    assert p.m.base._instantane_base(session) == avant
    assert catalogue.post(route, data={**champs, 'empreinte_attendue': '0' * 64}).status_code == 409
    assert p.m.base._instantane_base(session) == avant


def test_plan_etranger_non_devine_et_parametres_refuses(pret, catalogue, session):
    _, _, revue = _creer(pret, catalogue)
    autre = 'DEVIS-AUTRE-FICTIF'
    nouveau = Capacites(pret['deps'], stockage.transaction, filtre={'m01-front-office'}, memoire=False).appeler(
        'm1_recevoir_message_canal', dict(p.b.SMS, expediteur='+15145550143', message_id='SMcrm08autrefictif'))
    assert nouveau['ok'] and nouveau['resultat']['decision'] == 'TRANSMETTRE_M2', nouveau
    autre_lead = nouveau['resultat']['lead']['lead_id']
    assert p.b._drainer(pret['deps'], p.b.DEBUT)['quarantaines'] == 0
    p.b._qualifier(pret['deps'], autre_lead)
    p.b._devis_accepte(pret['deps'], autre_lead, autre)
    assert p.b._drainer(pret['deps'], p.b.DEBUT)['quarantaines'] == 0
    avant = p.m.base._instantane_base(session)
    assert catalogue.get(revue.replace(p.DEVIS, autre).replace(pret['lead'], autre_lead)).status_code == 404
    assert catalogue.get(revue.replace(pret['lead'], 'lead-fictif-001')).status_code == 404
    assert catalogue.get(revue.rsplit('/', 1)[0] + '/' + 'f' * 64).status_code == 404
    assert catalogue.get(revue+'?confirme_par=autre').status_code == 400
    assert catalogue.post(revue, data={}).status_code == 405
    assert p.m.base._instantane_base(session) == avant


def test_revue_et_rejeu_refuses_aux_non_admin_et_revoques(pret, catalogue, client_crm, session):
    route, champs, revue = _creer(pret, catalogue)
    for utilisateur in ('employe', 'nathan'):
        p.m.base._connecter(client_crm, utilisateur)
        avant = p.m.base._instantane_base(session)
        assert client_crm.get(revue).status_code == 403
        nouveau_csrf = client_crm.get('/api/session').json()['csrf']
        assert client_crm.post(route, data={**champs, 'csrf': nouveau_csrf}).status_code == 403
        assert p.m.base._instantane_base(session) == avant
    p.m.base._connecter(client_crm, 'admin.fictif')
    with session() as cnx:
        identite.ajouter_role(cnx, p.AUTH.utilisateur, 'nathan_owner')
        identite.retirer_role(cnx, p.AUTH.utilisateur, 'admin')
    avant = p.m.base._instantane_base(session)
    nouveau_csrf = client_crm.get('/api/session').json()['csrf']
    assert client_crm.get(revue).status_code == 403
    assert client_crm.post(route, data={**champs, 'csrf': nouveau_csrf}).status_code == 403
    assert p.m.base._instantane_base(session) == avant


def test_rendu_revue_echappe_textes_et_borne_html(pret, catalogue, session, monkeypatch):
    from opsys.console import proposition_chantier as port
    from opsys.console import proposition_chantier_ui as ui

    _, _, revue = _creer(pret, catalogue)
    plan_id = revue.rsplit('/', 1)[1]
    with session() as cnx:
        vue = port.lire(cnx, pret['deps'], p.AUTH, pret['lead'], p.DEVIS, plan_id)
    vue['proposition']['propose_par'] = '<script>MARQUEUR-FICTIF</script>'
    html = ui.contenu(vue, p.m.base.PREFIXE)
    assert '<script>' not in html and '&lt;script&gt;MARQUEUR-FICTIF' in html
    original = ui.contenu
    monkeypatch.setattr(ui, 'contenu', lambda *a: original(*a) + 'x' * 131073)
    avant = p.m.base._instantane_base(session)
    assert catalogue.get(revue).status_code == 503
    assert p.m.base._instantane_base(session) == avant
