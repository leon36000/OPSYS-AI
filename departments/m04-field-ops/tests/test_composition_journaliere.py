"""fictif: true — histoire déclarative, aucune preuve de présence ni autorité SQL."""
import importlib
import json
from copy import deepcopy

import pytest
from m4_field_ops import encodage
from m4_field_ops.registre import Registre

FICTIF = True
D, AUTRE_JOUR = '2030-06-03', '2030-06-07'
AUTEUR = {'personne': 'admin.fictif', 'role': 'admin'}


def module():
    return importlib.import_module('m4_field_ops.composition_journaliere')


def arguments(*, jour=D, equipe_id='eq-a', membres=None, revision_attendue=0, statut_declaration='declaree'):
    return dict(jour=jour, equipe_id=equipe_id, membres=['alice.fictive', 'bruno.fictif'] if membres is None
        and statut_declaration == 'declaree' else membres, revision_attendue=revision_attendue,
        statut_declaration=statut_declaration)


def mutation(args, cle='m-1'):
    propres = deepcopy(args)
    if type(propres['membres']) is list and all(isinstance(v, str) for v in propres['membres']):
        propres['membres'].sort()
    return {'appareil': 'console-fictive', 'cle': cle, 'empreinte_arguments': encodage.empreinte(propres)}


def ecrire(reg, args=None, *, cle='m-1', auteur=None, heure='2030-06-10T12:00:00+00:00', limite_sortie=65536):
    args = arguments() if args is None else args
    return module().declarer(reg, **args, auteur=AUTEUR if auteur is None else auteur,
        mutation=mutation(args, cle), horodatage=heure, limite_sortie=limite_sortie)


def test_composition_declaree_corrigee_retiree_et_redeclaree_sans_reecriture():
    reg = Registre()
    initiale = ecrire(reg, arguments(membres=['bruno.fictif', 'alice.fictive']))
    assert initiale['accepte'] is True and initiale['rejoue'] is False
    assert 'membres' not in json.dumps(initiale)
    original = deepcopy(reg.lire())
    ecrire(reg, arguments(membres=['charlie.fictif'], revision_attendue=1), cle='m-2',
        heure='2030-06-11T12:00:00+00:00')
    ecrire(reg, arguments(membres=None, statut_declaration='retiree', revision_attendue=2), cle='m-3',
        heure='2030-06-12T12:00:00+00:00')
    r = module().lire(reg, D, 'eq-a')
    assert r['composition_connue'] is False and r['membres'] is None
    assert [x['revision'] for x in r['lignes']] == [1, 2, 3]
    assert [x['courante'] for x in r['lignes']] == [False, False, True]
    assert r['lignes'][0]['membres'] == ['alice.fictive', 'bruno.fictif']
    assert r['lignes'][0]['jour'] == D and r['lignes'][0]['horodatage'].startswith('2030-06-10')
    ecrire(reg, arguments(membres=[], revision_attendue=3), cle='m-4', heure='2030-06-13T12:00:00+00:00')
    r = module().lire(reg, D, 'eq-a')
    assert r['composition_connue'] is True and r['membres'] == []
    assert reg.lire()[:1] == original and reg.taille() == 4
    assert all('mutation' not in x for x in r['lignes'])


def test_jour_et_equipe_independants_et_inconnu_distinct_liste_vide():
    reg = Registre()
    assert module().lire(reg, D, 'eq-a')['composition_connue'] is False
    ecrire(reg, arguments(membres=[]))
    ecrire(reg, arguments(jour=AUTRE_JOUR, membres=['charlie.fictif']), cle='m-2')
    ecrire(reg, arguments(equipe_id='eq-b', membres=['alice.fictive']), cle='m-3')
    assert module().lire(reg, D, 'eq-a')['membres'] == []
    assert module().lire(reg, AUTRE_JOUR, 'eq-a')['membres'] == ['charlie.fictif']
    assert module().lire(reg, D, 'eq-b')['membres'] == ['alice.fictive']
    assert module().lire(reg, AUTRE_JOUR, 'eq-b')['membres'] is None


def test_rejeu_ancien_apres_correction_ne_revient_pas_en_arriere_et_cas_sans_ecriture():
    reg = Registre()
    premier = ecrire(reg)
    ecrire(reg, arguments(membres=['charlie.fictif'], revision_attendue=1), cle='m-2')
    avant = reg.lire()
    rejoue = ecrire(reg, heure='2030-06-20T12:00:00+00:00')
    assert rejoue['resultat'] == premier['resultat'] and rejoue['rejoue'] is True
    assert module().lire(reg, D, 'eq-a')['membres'] == ['charlie.fictif']
    with pytest.raises(module().Refus, match='REVISION'):
        ecrire(reg, arguments(revision_attendue=0), cle='m-3')
    with pytest.raises(module().Refus, match='MUTATION-CONFLIT'):
        ecrire(reg, arguments(membres=['charlie.fictif']))
    with pytest.raises(module().Refus, match='MUTATION-CONFLIT'):
        ecrire(reg, auteur={'personne': 'autre.admin', 'role': 'admin'})
    assert reg.lire() == avant


@pytest.mark.parametrize('changement', [dict(jour='20300603'), dict(equipe_id=''), dict(equipe_id=' eq-a'),
    dict(membres=['alice.fictive', 'alice.fictive']), dict(membres=['nom\nlibre']),
    dict(membres='alice.fictive'), dict(membres=list(range(51))), dict(revision_attendue=True),
    dict(statut_declaration='invente'), dict(statut_declaration='retiree', membres=[])])
def test_arguments_invalides_refuses_sans_ecriture(changement):
    reg = Registre()
    args = arguments()
    args.update(changement)
    with pytest.raises(module().Refus):
        ecrire(reg, args)
    assert reg.taille() == 0


def test_auteur_horodatage_et_retrait_sans_declaration_refuses():
    reg = Registre()
    for auteur in [{'personne': 'employee.fictif', 'role': 'employee'}, {'personne': '', 'role': 'admin'}]:
        with pytest.raises(module().Refus):
            ecrire(reg, auteur=auteur)
    with pytest.raises(module().Refus):
        ecrire(reg, heure='2030-06-10T12:00:00')
    with pytest.raises(module().Refus):
        ecrire(reg, arguments(membres=None, statut_declaration='retiree'))
    assert reg.taille() == 0


def test_anciennete_par_paire_et_retrait_double_refuses_sans_ecriture():
    reg = Registre()
    ecrire(reg)
    avant = reg.lire()
    with pytest.raises(module().Refus, match='HORODATAGE'):
        ecrire(reg, arguments(revision_attendue=1), cle='m-2', heure='2030-06-01T12:00:00+00:00')
    assert reg.lire() == avant
    ecrire(reg, arguments(membres=None, statut_declaration='retiree', revision_attendue=1), cle='m-2')
    avant = reg.lire()
    with pytest.raises(module().Refus, match='RETRAIT'):
        ecrire(reg, arguments(membres=None, statut_declaration='retiree', revision_attendue=2), cle='m-3')
    assert reg.lire() == avant


def test_pagination_source_et_copies_independantes():
    reg = Registre()
    ecrire(reg)
    ecrire(reg, arguments(membres=[], revision_attendue=1), cle='m-2')
    tout = module().lire(reg, D, 'eq-a')
    p1 = module().lire(reg, D, 'eq-a', limite=1)
    p2 = module().lire(reg, D, 'eq-a', debut=p1['suivant'], limite=1, source_attendue=p1['source'])
    assert p1['lignes'] + p2['lignes'] == tout['lignes'] and p2['suivant'] is None
    tout['lignes'][0]['membres'].clear()
    tout['lignes'][0]['auteur']['personne'] = 'mutation.fictive'
    assert module().lire(reg, D, 'eq-a')['lignes'][0]['membres']
    with pytest.raises(module().Refus):
        module().lire(reg, D, 'eq-a', debut=1)
    with pytest.raises(module().Refus):
        module().lire(reg, D, 'eq-b', source_attendue=p1['source'])
    ecrire(reg, arguments(jour=AUTRE_JOUR), cle='m-3')
    with pytest.raises(module().Refus):
        module().lire(reg, D, 'eq-a', debut=1, source_attendue=p1['source'])


def rechaine(maillons):
    r = Registre()
    for m in maillons:
        r.ajouter({k: v for k, v in m.items() if k not in {'ligne_id', 'precedent_ligne_id'}})
    return r


@pytest.mark.parametrize('champ,valeur', [('revision', 3), ('revision_precedente', 'fausse'),
    ('equipe_id', 'eq-b'), ('extra_prive', 'nom-fictif-interdit')])
def test_chaine_et_semantique_fermees_meme_apres_rechainage(champ, valeur):
    reg = Registre()
    ecrire(reg)
    ecrire(reg, arguments(membres=[], revision_attendue=1), cle='m-2')
    bruts = reg.lire()
    bruts[-1][champ] = valeur
    for invalide in (Registre(bruts), rechaine(bruts)):
        with pytest.raises(module().Refus):
            module().lire(invalide, D, 'eq-a')


def test_quotas_sources_et_octets_avant_append_et_sortie(monkeypatch):
    m = module()

    class TropGrand:
        def taille(self):
            return m.MAX_SOURCES + 1

        def lire(self):
            raise AssertionError('lecture après quota interdite')

    with pytest.raises(m.Refus):
        m.lire(TropGrand(), D, 'eq-a')
    reg = Registre()
    with pytest.raises(m.Refus, match='SORTIE'):
        ecrire(reg, limite_sortie=10)
    assert reg.taille() == 0
    monkeypatch.setattr(m, 'MAX_OCTETS', 20)
    with pytest.raises(m.Refus, match='SOURCES'):
        ecrire(reg)
    assert reg.taille() == 0



def test_enveloppes_utf8_multioctets_refusees_avant_append_et_retour():
    args = arguments(equipe_id='é' * 64, membres=['à' * 64])
    reg = Registre()
    accuse = ecrire(reg, args)
    caracteres = max(len(json.dumps({'ok': True, 'resultat': accuse, 'rejoue': r}, ensure_ascii=False))
                     for r in (False, True))
    autre = Registre()
    with pytest.raises(module().Refus, match='SORTIE'):
        ecrire(autre, args, limite_sortie=caracteres)
    assert autre.taille() == 0
    vue = module().lire(reg, D, 'é' * 64)
    caracteres = max(len(json.dumps({'ok': True, 'resultat': vue, 'rejoue': r}, ensure_ascii=False))
                     for r in (False, True))
    avant = reg.lire()
    with pytest.raises(module().Refus, match='SORTIE'):
        module().lire(reg, D, 'é' * 64, limite_sortie=caracteres)
    assert reg.lire() == avant


def test_mutation_requise_empreinte_et_unicite_globale_entre_equipes():
    reg = Registre()
    args = arguments()
    fausse = mutation(args)
    fausse['empreinte_arguments'] = 'faux'
    with pytest.raises(module().Refus, match='MUTATION'):
        module().declarer(reg, **args, auteur=AUTEUR, mutation=fausse, horodatage='2030-06-10T12:00:00+00:00')
    assert reg.taille() == 0
    ecrire(reg)
    ecrire(reg, arguments(equipe_id='eq-b'), cle='m-2')
    bruts = reg.lire()
    bruts[-1]['mutation']['cle'] = 'm-1'
    with pytest.raises(module().Refus, match='MUTATION'):
        module().lire(rechaine(bruts), D, 'eq-a')
    avant = reg.lire()
    with pytest.raises(module().Refus, match='MUTATION-CONFLIT'):
        ecrire(reg, arguments(equipe_id='eq-b'))
    assert reg.lire() == avant


def test_rejeu_au_plafond_sources_sans_nouveau_maillon(monkeypatch):
    reg = Registre()
    ecrire(reg)
    monkeypatch.setattr(module(), 'MAX_SOURCES', 1)
    assert ecrire(reg)['rejoue'] is True
    with pytest.raises(module().Refus, match='SOURCES'):
        ecrire(reg, arguments(equipe_id='eq-b'), cle='m-2')
    assert reg.taille() == 1


@pytest.mark.parametrize('options', [{'debut': True}, {'debut': -1}, {'limite': 0}, {'limite': 101},
    {'limite': True}, {'debut': 100, 'source_attendue': 'faux'}])
def test_options_lecture_invalides_sans_mutation(options):
    reg = Registre()
    ecrire(reg)
    avant = reg.lire()
    with pytest.raises(module().Refus):
        module().lire(reg, D, 'eq-a', **options)
    assert reg.lire() == avant
