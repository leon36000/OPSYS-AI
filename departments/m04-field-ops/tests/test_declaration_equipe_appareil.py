"""D4 : la déclaration d'équipe V3 devient une surface réelle (appareil d'un membre, console admin).

Tout est fictif (`fictif: true`) : personnes, équipes, chantier. Aucune présence individuelle n'est écrite ni déduite.
"""
import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from m4_field_ops import (
    calendrier_civil,
    cedule_tournees,
    ecarts,
    equipes_pointees_v3,
    etats,
    outbox,
    temps_certifies_v3,
    visites_chantier,
)
from m4_field_ops import outils as m4_outils
from m4_field_ops.registre import Registre

from opsys import contexte, equipes, idempotence, identite, stockage
from opsys.outils import executer

FICTIF = True
_spec = importlib.util.spec_from_file_location('fixture_v2_equipe',
                                               Path(__file__).with_name('test_temps_certifies_v2.py'))
_v2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_v2)
domaine = _v2._base

CHEF, MEMBRE, ETRANGER, AUTRE = 'chef.fictif', 'membre.fictif', 'etranger.fictif', 'autre.fictif'
JOUR = datetime(2030, 6, 3, 13, tzinfo=UTC)  # 09:00 à Repentigny (-04:00), le jour de l'ouverture


def _outil(nom):
    return next(o for o in m4_outils.outils() if o.nom == nom)


def _appareil(personne, role, instant, *, decalage_appareil=timedelta(minutes=-7)):
    """Un appel d'appareil appairé : identité du jeton (jamais du corps), heure de réception du serveur."""
    return (contexte.appele_par_appareil(contexte.IdentiteAppelante(personne, role)),
            contexte.appeler_en_tant_que('m04-field-ops'),
            contexte.receptionne_de(contexte.HorodatageAppareil(
                f'appareil-{personne}', instant + decalage_appareil, instant)))


def _console(instant, cle):
    meta = idempotence.Meta(cle, 'console:admin.fictif', instant.isoformat())
    return (contexte.appele_par_appareil(contexte.IdentiteAppelante('admin.fictif', 'admin', source='console')),
            contexte.appeler_en_tant_que('m04-field-ops', origine='console'),
            contexte.receptionne_de(contexte.HorodatageAppareil('console:admin.fictif', instant, instant)),
            m4_outils.contexte_annotation_calendrier(meta))


def _appeler(nom, contextes, arguments):
    a, b, c, *d = contextes
    with a, b, c, (d[0] if d else _rien()):
        return executer(_outil(nom), arguments)


class _rien:
    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False


def _metier(reponse):
    assert reponse['ok'] is True, reponse
    return reponse['resultat']


def _code(reponse):
    resultat = _metier(reponse)
    assert resultat['accepte'] is False, resultat
    return resultat['verdict']['code']


@pytest.fixture
def chantier_equipe(base_durable, tmp_path, monkeypatch):
    """Une intervention de l'équipe A (CHEF, MEMBRE), sa visite ouverte, en route sous l'équipe ; l'équipe B (AUTRE).
    ETRANGER est un employé actif, membre d'aucune équipe."""
    monkeypatch.setenv('OPSYS_HOME', str(tmp_path / 'opsys'))
    initial, ids, positions = domaine.fixture.pur._monde(leads=('ch-01',))
    modeles = domaine.fixture.pur._aide._equipes()
    with stockage.transaction(base_durable) as cnx:
        identite.creer_personne(cnx, 'admin.fictif', 'Admin fictif', 'Fictif#12345678', roles=['admin'])
        principal = Registre(stockage.maillons('m04-field-ops', 'principal'))
        for maillon in initial.lire():
            principal.ajouter({k: v for k, v in maillon.items() if k not in {'ligne_id', 'precedent_ligne_id'}})
        plan = domaine.fixture.pur._reussi(domaine.fixture.pur._proposer(principal, ids, positions))['plan_id']
        domaine.fixture.pur._reussi(cedule_tournees.appliquer(principal, plan, positions,
                                                             domaine.fixture.pur.HORODATAGE, 'admin.fictif'))
        calendrier_civil.confirmer(principal, plan, {'0': '2030-06-03'}, 0, 'admin.fictif',
                                   '2030-06-02T09:00:00+00:00')
        ligne = calendrier_civil.lire_semaine(principal, '2030-06-03')['interventions'][0]
        ancre = {k: ligne[k] for k in domaine.fixture.CHAMPS_ANCRE}
        iid, equipe = ancre['intervention_id'], ligne['equipe_id']
        autre = next(e['id'] for e in modeles if e['id'] != equipe)
        membres = {equipe: [CHEF, MEMBRE], autre: [AUTRE]}
        equipes.enregistrer_equipes({'liste': [{**e, 'membres': membres.get(e['id'], [e['id'] + '.x.fictif'])}
                                               for e in modeles]})
        for personne in (CHEF, MEMBRE, ETRANGER, AUTRE):
            identite.creer_personne(cnx, personne, 'Employé fictif', 'Fictif#12345678', roles=['employee'])
        visites = Registre(stockage.maillons('m04-field-ops', 'visites_chantier'))
        prev = domaine.ecrire(principal, visites, ancre, heure='2030-06-03T07:30:00-04:00')
        visites_chantier.ouvrir(principal, visites, prev['visite_id'], '2030-06-03T08:00:00-04:00')
        assert etats.transitionner(iid, 'en_route', principal, '2030-06-03T08:30:00-04:00',
                                   assignation={'intervention_id': iid, 'technicien_id': equipe})[1] is None
    yield {'url': base_durable, 'iid': iid, 'equipe': equipe, 'autre': autre, 'visite_id': prev['visite_id']}
    stockage.liberer()


def _demande(cas, action, mutation_id, **autres):
    return {'intervention_id': cas['iid'], 'visite_id': cas['visite_id'], 'equipe_id': cas['equipe'],
            'action': action, 'mutation_id': mutation_id, **autres}


def _principal():
    return Registre(stockage.maillons('m04-field-ops', 'principal'))


def test_membre_declare_arrivee_depart_et_la_projection_identifie_l_equipe(chantier_equipe):
    cas = chantier_equipe
    with stockage.transaction(cas['url']) as cnx:
        recu = _metier(_appeler('m4_declarer_pointage_equipe_appareil', _appareil(CHEF, 'employee', JOUR),
                                _demande(cas, 'arrivee', 'mut-arrivee')))
        assert recu['accepte'] is True, recu
        arrivee = recu['resultat']
        maillons = {m['ligne_id']: m for m in _principal().lire()}
        pointe, preuve = maillons[arrivee['pointage_id']], maillons[arrivee['preuve_id']]
        # Le sujet est l'ÉQUIPE ; la personne est l'auteur nommé, jamais une présence.
        assert pointe['technicien_id'] == cas['equipe'] and pointe['visite_id'] == cas['visite_id']
        assert preuve['sujet'] == {'type': 'equipe', 'id': cas['equipe']}
        assert preuve['auteur'] == {'personne': CHEF, 'role': equipes_pointees_v3.ROLE_MEMBRE}
        assert arrivee['presence_individuelle'] == 'inconnue'
        # Heure de réception du serveur, jamais l'horloge de l'appareil (à côté, pour l'affichage).
        assert pointe['horodatage'] == preuve['horodatage'] == JOUR.isoformat() == arrivee['horodatage']
        assert arrivee['horodatage_appareil'] == (JOUR - timedelta(minutes=7)).isoformat()
        assert pointe.get('latitude') is None and pointe.get('position_chiffree') is None
        demande = next(m for m in maillons.values() if m.get('type_entree') == 'demande_revue'
                       and m.get('pointage_ligne_id') == arrivee['pointage_id'])
        assert ecarts.resoudre_demande(demande['demande_id'], 'validee', '2030-06-03T09:01:00-04:00',
                                       _principal())[1] is None
        # Un autre membre (non « chef ») peut déclarer le départ : tout membre déclaré de l'équipe déclare.
        depart = _metier(_appeler('m4_declarer_pointage_equipe_appareil',
                                  _appareil(MEMBRE, 'employee', JOUR + timedelta(hours=3)),
                                  _demande(cas, 'depart', 'mut-depart')))
        assert depart['accepte'] is True, depart
        maillons = {m['ligne_id']: m for m in _principal().lire()}
        assert maillons[depart['resultat']['preuve_id']]['auteur'] == {'personne': MEMBRE, 'role': 'membre_equipe'}
        demande = next(m for m in maillons.values() if m.get('type_entree') == 'demande_revue'
                       and m.get('pointage_ligne_id') == depart['resultat']['pointage_id'])
        assert ecarts.resoudre_demande(demande['demande_id'], 'validee', '2030-06-03T12:01:00-04:00',
                                       _principal())[1] is None
        visites = Registre(stockage.maillons('m04-field-ops', 'visites_chantier'))
        visites_chantier.fermer(_principal(), visites, cas['visite_id'], '2030-06-03T12:02:00-04:00')
        wct, erreur = outbox.completer_intervention(cas['iid'], '2030-06-03T12:03:00-04:00', _principal(),
                                                    ecart_detecte=False, verification_en_attente=True,
                                                    registre_visites=visites)
        assert erreur is None, erreur
        revue, erreur = outbox.resoudre_revue_completion(cas['iid'], 'verifiee', '2030-06-03T12:04:00-04:00',
                                                         _principal(), motif='Revue fictive')
        assert erreur is None and revue['statut'] == 'completed_verified'
        with (contexte.appele_par_appareil(contexte.IdentiteAppelante('admin.fictif', 'admin', source='console')),
              contexte.appeler_en_tant_que('m04-field-ops', origine='console')):
            projection = temps_certifies_v3.projeter(cnx, cas['iid'], wct['wct_id'])['projection']
        (visite,) = projection['visites']
        assert visite['equipe_pointee']['statut'] == 'identifiee'
        assert visite['equipe_pointee']['identifiant'] == cas['equipe']
        assert [p['auteur'] for p in visite['equipe_pointee']['preuves']] == [
            {'personne': CHEF, 'role': 'membre_equipe'}, {'personne': MEMBRE, 'role': 'membre_equipe'}]
        assert visite['presence_individuelle'] == {'statut': 'inconnue'}
        assert visite['minutes']['travail'] == 180


def test_rejeu_idempotent_et_mutation_divergente_refusee(chantier_equipe):
    cas = chantier_equipe
    with stockage.transaction(cas['url']):
        premier = _metier(_appeler('m4_declarer_pointage_equipe_appareil', _appareil(CHEF, 'employee', JOUR),
                                   _demande(cas, 'arrivee', 'mut-1')))
        taille = _principal().taille()
        rejeu = _metier(_appeler('m4_declarer_pointage_equipe_appareil',
                                 _appareil(CHEF, 'employee', JOUR + timedelta(minutes=2)),
                                 _demande(cas, 'arrivee', 'mut-1')))
        assert rejeu['accepte'] is True and rejeu['rejoue'] is True
        assert {k: rejeu['resultat'][k] for k in ('pointage_id', 'preuve_id')} == {
            k: premier['resultat'][k] for k in ('pointage_id', 'preuve_id')}
        assert _principal().taille() == taille
        conflit = _appeler('m4_declarer_pointage_equipe_appareil',
                           _appareil(CHEF, 'employee', JOUR + timedelta(minutes=3)),
                           _demande(cas, 'depart', 'mut-1'))
        assert _code(conflit) == 'REJ-EQUIPE-MUTATION-CONFLIT'
        assert _principal().taille() == taille
        # La même clé d'une AUTRE personne est une autre intention : jamais la preuve de quelqu'un d'autre.
        demande = next(m for m in _principal().lire() if m.get('type_entree') == 'demande_revue'
                       and m.get('pointage_ligne_id') == premier['resultat']['pointage_id'])
        assert ecarts.resoudre_demande(demande['demande_id'], 'validee', '2030-06-03T09:01:00-04:00',
                                       _principal())[1] is None
        autre = _metier(_appeler('m4_declarer_pointage_equipe_appareil',
                                 _appareil(MEMBRE, 'employee', JOUR + timedelta(minutes=4)),
                                 _demande(cas, 'pause_debut', 'mut-1')))
        assert autre['accepte'] is True and autre['rejoue'] is False


@pytest.mark.parametrize(('personne', 'equipe_cle', 'code'), [
    (ETRANGER, 'equipe', 'REJ-EQUIPE-NON-MEMBRE'),       # employé d'aucune équipe
    (AUTRE, 'equipe', 'REJ-EQUIPE-NON-MEMBRE'),          # membre d'une autre équipe, pour l'équipe A
    (AUTRE, 'autre', 'REJ-EQUIPE-VISITE-AUTRE-EQUIPE'),  # membre de B, pour B, sur la visite de A
])
def test_non_membre_et_visite_d_une_autre_equipe_refuses_sans_ecriture(chantier_equipe, personne, equipe_cle, code):
    cas = chantier_equipe
    with stockage.transaction(cas['url']):
        avant = _principal().lire()
        reponse = _appeler('m4_declarer_pointage_equipe_appareil', _appareil(personne, 'employee', JOUR),
                           _demande(cas, 'arrivee', 'mut-x', equipe_id=cas[equipe_cle]))
        assert _code(reponse) == code
        assert _principal().lire() == avant


def test_aucun_agent_ni_identite_non_confirmee_ne_declare_pour_un_humain(chantier_equipe):
    cas = chantier_equipe
    with stockage.transaction(cas['url']) as cnx:
        avant = _principal().lire()
        # Agent (aucun jeton d'appareil) : même avec l'heure posée, refusé.
        with (contexte.appeler_en_tant_que('m04-field-ops'),
              contexte.receptionne_de(contexte.HorodatageAppareil('appareil-x', JOUR, JOUR))):
            assert _code(executer(_outil('m4_declarer_pointage_equipe_appareil'),
                                  _demande(cas, 'arrivee', 'agent'))) == 'REJ-EQUIPE-IDENTITE'
        # Un corps qui nommerait une personne n'est pas lu : le schéma est fermé.
        assert executer(_outil('m4_declarer_pointage_equipe_appareil'),
                        _demande(cas, 'arrivee', 'corps', personne=CHEF))['erreur'] == 'arguments_invalides'
        # Rôle retiré depuis l'appairage : le jeton ne suffit plus.
        identite.retirer_role(cnx, CHEF, 'employee')
        assert _code(_appeler('m4_declarer_pointage_equipe_appareil', _appareil(CHEF, 'employee', JOUR),
                              _demande(cas, 'arrivee', 'retire'))) == 'REJ-EQUIPE-IDENTITE'
        # Console admin : pas par l'outil d'appareil (identité de console refusée).
        assert _code(_appeler('m4_declarer_pointage_equipe_appareil', _console(JOUR, 'console-sur-appareil'),
                              _demande(cas, 'arrivee', 'console'))) == 'REJ-EQUIPE-IDENTITE'
        assert _principal().lire() == avant


def test_pointage_individuel_jamais_requalifie_en_equipe(chantier_equipe):
    cas = chantier_equipe
    contexte_pointage = {'horodatage': JOUR.isoformat(), 'fix_gps': None,
                         'attestation': {'fictif': True, 'appareil_id': 'appareil-membre'},
                         'fenetre_travail': {'debut': '2030-06-03T00:00:00-04:00', 'fin': '2030-06-03T23:59:59-04:00'},
                         'referentiel_villes': {}, 'ville': 'x', 'sel': 'y'}
    with stockage.transaction(cas['url']):
        avant = _principal().lire()
        # Hors du port, un membre ne pointe pas sous l'identifiant de l'équipe...
        reponse = _appeler('m4_pointer', _appareil(MEMBRE, 'employee', JOUR), {
            'intervention_id': cas['iid'], 'technicien_id': cas['equipe'], 'action': 'arrivee', **contexte_pointage})
        assert _code(reponse) == 'REJ-IDENTITE-FOURNIE-DIFFERENTE'
        # ... et son pointage individuel sur une intervention en route sous l'équipe est refusé, jamais converti.
        reponse = _appeler('m4_pointer', _appareil(MEMBRE, 'employee', JOUR), {
            'intervention_id': cas['iid'], 'technicien_id': MEMBRE, 'action': 'arrivee', **contexte_pointage})
        assert _metier(reponse)['accepte'] is False
        assert _principal().lire() == avant
        # La déclaration d'équipe ne réécrit rien d'antérieur : elle ajoute le pointage, sa demande de revue, sa preuve.
        _metier(_appeler('m4_declarer_pointage_equipe_appareil', _appareil(MEMBRE, 'employee', JOUR),
                         _demande(cas, 'arrivee', 'mut-a')))
        apres = _principal().lire()
        assert apres[:len(avant)] == avant
        assert [m['type_entree'] for m in apres[len(avant):]].count(equipes_pointees_v3.TYPE) == 1
        assert not [m for m in apres[len(avant):] if m.get('type_entree') == 'pointage'
                    and m.get('technicien_id') != cas['equipe']]


def test_rejeu_d_appareil_refuse_apres_retrait_du_profil(chantier_equipe):
    cas = chantier_equipe
    with stockage.transaction(cas['url']):
        _metier(_appeler('m4_declarer_pointage_equipe_appareil', _appareil(MEMBRE, 'employee', JOUR),
                         _demande(cas, 'arrivee', 'mut-r')))
        profil = equipes.lire_equipes()
        equipes.enregistrer_equipes({**profil, 'liste': [
            {**e, 'membres': [m for m in e['membres'] if m != MEMBRE]} for e in profil['liste']]})
        a, b, c = _appareil(MEMBRE, 'employee', JOUR)
        with a, b, c:
            refus = m4_outils.verifier_identite_rejeu_equipe_appareil({'equipe_id': cas['equipe']})
        assert refus['verdict']['code'] == 'REJ-EQUIPE-NON-MEMBRE'
        assert _code(_appeler('m4_declarer_pointage_equipe_appareil', _appareil(MEMBRE, 'employee', JOUR),
                              _demande(cas, 'arrivee', 'mut-r'))) == 'REJ-EQUIPE-NON-MEMBRE'
        with _appareil(CHEF, 'employee', JOUR)[0], _appareil(CHEF, 'employee', JOUR)[1]:
            assert m4_outils.verifier_identite_rejeu_equipe_appareil({'equipe_id': cas['equipe']}) is None


def test_console_admin_declare_avec_cas_de_page_et_rejoue_sans_doublon(chantier_equipe):
    cas = chantier_equipe
    demande = {k: v for k, v in _demande(cas, 'arrivee', '').items() if k != 'mutation_id'}
    with stockage.transaction(cas['url']) as cnx:
        source = equipes_pointees_v3.empreinte_sources(cnx)
        perime = _appeler('m4_declarer_pointage_equipe_console', _console(JOUR, 'form-0'),
                          {**demande, 'source_attendue': 'f' * 64})
        assert _code(perime) == 'REJ-EQUIPE-SOURCE-PERIMEE'
        recu = _metier(_appeler('m4_declarer_pointage_equipe_console', _console(JOUR, 'form-1'),
                                {**demande, 'source_attendue': source}))
        assert recu['accepte'] is True, recu
        preuve = next(m for m in _principal().lire() if m['ligne_id'] == recu['resultat']['preuve_id'])
        assert preuve['auteur'] == {'personne': 'admin.fictif', 'role': 'admin'}
        taille = _principal().taille()
        # Double envoi du même formulaire, plus tard : même preuve, rien d'écrit.
        rejeu = _metier(_appeler('m4_declarer_pointage_equipe_console', _console(JOUR + timedelta(minutes=1), 'form-1'),
                                 {**demande, 'source_attendue': source}))
        assert rejeu['rejoue'] is True and rejeu['resultat']['preuve_id'] == recu['resultat']['preuve_id']
        assert _principal().taille() == taille
        conflit = _appeler('m4_declarer_pointage_equipe_console', _console(JOUR, 'form-1'),
                           {**demande, 'action': 'depart', 'source_attendue': source})
        assert _code(conflit) == 'REJ-EQUIPE-MUTATION-CONFLIT'
        # Visite d'une autre équipe refusée aussi pour l'admin.
        autre = _appeler('m4_declarer_pointage_equipe_console', _console(JOUR, 'form-2'),
                         {**demande, 'equipe_id': cas['autre'],
                          'source_attendue': equipes_pointees_v3.empreinte_sources(cnx)})
        assert _code(autre) == 'REJ-EQUIPE-VISITE-AUTRE-EQUIPE'
        # Hors console (MCP, appareil employé) : refusé.
        refus = _appeler('m4_declarer_pointage_equipe_console', _appareil(CHEF, 'employee', JOUR),
                         {**demande, 'source_attendue': source})
        assert _code(refus) in {'REJ-EQUIPE-MUTATION-ABSENTE', 'REJ-EQUIPE-IDENTITE'}
        assert _principal().taille() == taille


def test_visite_null_designe_la_visite_active_et_le_rejeu_survit_a_sa_fermeture(chantier_equipe):
    cas = chantier_equipe
    with stockage.transaction(cas['url']):
        recu = _metier(_appeler('m4_declarer_pointage_equipe_appareil', _appareil(MEMBRE, 'employee', JOUR),
                                _demande(cas, 'arrivee', 'mut-null', visite_id=None)))
        assert recu['accepte'] is True and recu['resultat']['visite_id'] == cas['visite_id']
        demande = next(m for m in _principal().lire() if m.get('type_entree') == 'demande_revue'
                       and m.get('pointage_ligne_id') == recu['resultat']['pointage_id'])
        assert ecarts.resoudre_demande(demande['demande_id'], 'validee', '2030-06-03T09:01:00-04:00',
                                       _principal())[1] is None
        depart = _metier(_appeler('m4_declarer_pointage_equipe_appareil',
                                  _appareil(MEMBRE, 'employee', JOUR + timedelta(hours=1)),
                                  _demande(cas, 'depart', 'mut-null-depart', visite_id=None)))
        assert depart['accepte'] is True
        demande = next(m for m in _principal().lire() if m.get('type_entree') == 'demande_revue'
                       and m.get('pointage_ligne_id') == depart['resultat']['pointage_id'])
        assert ecarts.resoudre_demande(demande['demande_id'], 'validee', '2030-06-03T10:01:00-04:00',
                                       _principal())[1] is None
        visites = Registre(stockage.maillons('m04-field-ops', 'visites_chantier'))
        visites_chantier.fermer(_principal(), visites, cas['visite_id'], '2030-06-03T10:30:00-04:00')
        taille = _principal().taille()
        # Visite fermée : une nouvelle déclaration est refusée, le rejeu de la même clé rend la même preuve.
        apres = _appeler('m4_declarer_pointage_equipe_appareil',
                         _appareil(MEMBRE, 'employee', JOUR + timedelta(hours=2)),
                         _demande(cas, 'pause_debut', 'mut-apres', visite_id=None))
        assert _code(apres) == 'REJ-EQUIPE-VISITE-INACTIVE'
        rejeu = _metier(_appeler('m4_declarer_pointage_equipe_appareil',
                                 _appareil(MEMBRE, 'employee', JOUR + timedelta(hours=2)),
                                 _demande(cas, 'arrivee', 'mut-null', visite_id=None)))
        assert rejeu['rejoue'] is True and rejeu['resultat']['preuve_id'] == recu['resultat']['preuve_id']
        assert _principal().taille() == taille


@pytest.mark.parametrize('microsecond', [500000, 999999])
def test_arrivee_equipe_acceptee_dans_la_derniere_fraction_de_seconde_du_jour(chantier_equipe, microsecond):
    """L'heure serveur fractionnaire avant minuit reste dans le jour civil de la visite."""
    cas = chantier_equipe
    reception = datetime(2030, 6, 4, 3, 59, 59, microsecond, tzinfo=UTC)  # dernier instant du jour à -04:00
    with stockage.transaction(cas['url']):
        reponse = _appeler('m4_declarer_pointage_equipe_appareil', _appareil(MEMBRE, 'employee', reception),
                           _demande(cas, 'arrivee', 'mut-dernier-instant'))
        resultat = _metier(reponse)
        assert resultat['accepte'] is True, resultat
        assert resultat['resultat']['horodatage'] == reception.isoformat()


def test_arrivee_equipe_refusee_a_minuit_le_jour_suivant(chantier_equipe):
    """La correction de la borne de fin n'étend pas la fenêtre au jour suivant."""
    cas = chantier_equipe
    reception = datetime(2030, 6, 4, 4, 0, 0, tzinfo=UTC)  # minuit à -04:00
    with stockage.transaction(cas['url']):
        taille_avant = _principal().taille()
        reponse = _appeler('m4_declarer_pointage_equipe_appareil', _appareil(MEMBRE, 'employee', reception),
                           _demande(cas, 'arrivee', 'mut-minuit-suivant'))
        resultat = _metier(reponse)
        assert resultat['accepte'] is False, resultat
        assert resultat['verdict']['code'] == 'REJ-EQUIPE-POINTAGE-REFUSE'
        assert _principal().taille() == taille_avant
