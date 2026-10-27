"""fictif: true — signalement administratif pur, jamais une preuve de présence ou de paie."""
import importlib
import json
from copy import deepcopy

import pytest
from m4_field_ops import encodage
from m4_field_ops.registre import Registre

FICTIF = True
JOUR = '2030-06-03'
AUTEUR = {'personne': 'admin.fictif', 'role': 'admin'}


def domaine():
    return importlib.import_module('m4_field_ops.absences_journalieres')


def arguments(**changements):
    return dict(dict(jour=JOUR, personne_id='employe.fictif', statut_declaration='signalee',
                     revision_attendue=0), **changements)


def ecrire(reg, *, args=None, cle='intention-1', auteur=None, heure='2030-06-10T12:00:00+00:00', **options):
    args = arguments() if args is None else args
    mutation = dict(appareil='console-fictive', cle=cle, empreinte_arguments=encodage.empreinte(args))
    return domaine().declarer(reg, **args, auteur=AUTEUR if auteur is None else auteur,
                             mutation=mutation, horodatage=heure, **options)


def lire(reg, **options):
    return domaine().lire(reg, JOUR, 'employe.fictif', **options)


def test_signalement_retrait_et_nouveau_signalement_ne_creent_jamais_presence():
    reg = Registre()
    assert lire(reg)['etat_declaration'] == 'aucun_signalement'
    premier = ecrire(reg)
    assert premier['accepte'] is True and premier['rejoue'] is False
    assert 'personne_id' not in premier['resultat']
    assert lire(reg)['etat_declaration'] == 'signalee'
    original = deepcopy(reg.lire())
    ecrire(reg, args=arguments(statut_declaration='retiree', revision_attendue=1), cle='m-2')
    assert lire(reg)['etat_declaration'] == 'retiree'
    assert reg.lire()[:1] == original
    ecrire(reg, args=arguments(revision_attendue=2), cle='m-3')
    vue = lire(reg)
    assert vue['etat_declaration'] == 'signalee' and vue['revision'] == 3
    assert [ligne['courante'] for ligne in vue['lignes']] == [False, False, True]
    assert vue['lignes'][0]['jour'] == JOUR and vue['lignes'][0]['horodatage'].startswith('2030-06-10')
    assert all('mutation' not in ligne for ligne in vue['lignes'])
    assert 'Aucune présence, heure travaillée ou paie déduite.' in vue['avertissements']


def test_rejeu_original_apres_retrait_et_paires_independantes():
    reg = Registre()
    premier = ecrire(reg)
    ecrire(reg, args=arguments(statut_declaration='retiree', revision_attendue=1), cle='m-2')
    ecrire(reg, args=arguments(jour='2030-06-07'), cle='m-3')
    ecrire(reg, args=arguments(personne_id='autre.fictif'), cle='m-4')
    avant = reg.lire()
    rejoue = ecrire(reg, heure='2030-06-20T12:00:00+00:00')
    assert rejoue['resultat'] == premier['resultat'] and rejoue['rejoue'] is True
    assert lire(reg)['etat_declaration'] == 'retiree' and reg.lire() == avant
    with pytest.raises(domaine().Refus, match='MUTATION-CONFLIT'):
        ecrire(reg, args=arguments(personne_id='autre.fictif'))
    with pytest.raises(domaine().Refus, match='REVISION-PERIMEE'):
        ecrire(reg, cle='m-5')
    assert reg.lire() == avant


@pytest.mark.parametrize('options', [dict(jour='20300603'), dict(personne_id=''), dict(personne_id=' employe'),
    dict(personne_id='nom\nlibre'), dict(revision_attendue=True), dict(statut_declaration='present'),
    dict(statut_declaration='maladie'), dict(statut_declaration='retiree')])
def test_entrees_et_retrait_initial_refuses_sans_append(options):
    reg = Registre()
    with pytest.raises(domaine().Refus):
        ecrire(reg, args=arguments(**options))
    assert reg.taille() == 0


def test_auteur_invalide_double_retrait_et_instant_anterieur_refuses():
    reg = Registre()
    with pytest.raises(domaine().Refus):
        ecrire(reg, auteur={'personne': 'employe.fictif', 'role': 'employee'})
    with pytest.raises(domaine().Refus):
        ecrire(reg, heure='2030-06-10T12:00:00')
    ecrire(reg)
    avant = reg.lire()
    with pytest.raises(domaine().Refus):
        ecrire(reg, args=arguments(revision_attendue=1), cle='m-2', heure='2030-06-01T12:00:00+00:00')
    assert reg.lire() == avant
    ecrire(reg, args=arguments(statut_declaration='retiree', revision_attendue=1), cle='m-2')
    avant = reg.lire()
    with pytest.raises(domaine().Refus):
        ecrire(reg, args=arguments(statut_declaration='retiree', revision_attendue=2), cle='m-3')
    assert reg.lire() == avant


@pytest.mark.parametrize('champ,valeur', [('motif', 'information fictive interdite'), ('minutes_payees', 480),
    ('revision', 3), ('revision_precedente', 'fausse'), ('personne_id', 'autre.fictif')])
def test_maillon_rehache_ne_masque_pas_motif_paie_ou_histoire_invalide(champ, valeur):
    reg = Registre()
    ecrire(reg)
    ecrire(reg, args=arguments(statut_declaration='retiree', revision_attendue=1), cle='m-2')
    bruts = reg.lire()
    bruts[-1][champ] = valeur
    rechaine = Registre()
    for m in bruts:
        rechaine.ajouter({k: v for k, v in m.items() if k not in {'ligne_id', 'precedent_ligne_id'}})
    with pytest.raises(domaine().Refus):
        lire(rechaine)


def test_pagination_liee_a_source_pair_et_copies_sans_mutation():
    reg = Registre()
    ecrire(reg)
    ecrire(reg, args=arguments(statut_declaration='retiree', revision_attendue=1), cle='m-2')
    p1 = lire(reg, limite=1)
    p2 = lire(reg, debut=p1['suivant'], limite=1, source_attendue=p1['source'])
    assert p1['lignes'] + p2['lignes'] == lire(reg)['lignes']
    p1['lignes'][0]['auteur']['personne'] = 'autre.fictif'
    assert lire(reg)['lignes'][0]['auteur'] == AUTEUR
    with pytest.raises(domaine().Refus):
        lire(reg, debut=1)
    with pytest.raises(domaine().Refus):
        domaine().lire(reg, JOUR, 'autre.fictif', source_attendue=p1['source'])
    ecrire(reg, args=arguments(jour='2030-06-07'), cle='m-3')
    with pytest.raises(domaine().Refus):
        lire(reg, debut=1, source_attendue=p1['source'])


def test_quotas_avant_lecture_et_append_et_accuse_borne(monkeypatch):
    m = domaine()

    class TropGrand:
        def taille(self):
            return m.MAX_SOURCES + 1

        def lire(self):
            raise AssertionError('ne pas décoder après quota')

    with pytest.raises(m.Refus):
        lire(TropGrand())
    reg = Registre()
    with pytest.raises(m.Refus, match='SORTIE'):
        ecrire(reg, limite_sortie=10)
    assert reg.taille() == 0
    ecrire(reg)
    avant = reg.lire()
    with pytest.raises(m.Refus):
        lire(reg, limite_sortie=10)
    monkeypatch.setattr(m, 'MAX_OCTETS', len(json.dumps(avant, ensure_ascii=False).encode('utf-8')) + 5)
    with pytest.raises(m.Refus):
        ecrire(reg, args=arguments(revision_attendue=1), cle='m-2')
    assert reg.lire() == avant


@pytest.mark.parametrize('cas', ['surrogate_rehache', 'charge_non_json'])
def test_source_non_encodable_devient_refus_metier_et_non_exception_brute(cas):
    reg = Registre()
    ecrire(reg)
    bruts = reg.lire()
    if cas == 'surrogate_rehache':
        bruts[0]['personne_id'] = '\ud800'
        reg = Registre()
        reg.ajouter({k: v for k, v in bruts[0].items() if k not in {'ligne_id', 'precedent_ligne_id'}})
    else:
        class SourceNonJson:
            def taille(self):
                return 1

            def lire(self):
                return [{**bruts[0], 'champ_interdit': object()}]

        reg = SourceNonJson()
    with pytest.raises(domaine().Refus):
        lire(reg)
