"""fictif: true — personnes ayant un signalement, pas un décompte d'absences observées."""
from copy import deepcopy

import pytest
from m4_field_ops import absences_journalieres as d
from m4_field_ops import encodage
from m4_field_ops.registre import Registre

FICTIF = True
JOUR = '2030-06-03'


def ajouter(reg, personne='charlie.fictif', jour=JOUR, revision=0, statut='signalee', auteur='admin.fictif'):
    args = dict(jour=jour, personne_id=personne, revision_attendue=revision, statut_declaration=statut)
    return d.declarer(reg, **args, auteur=dict(personne=auteur, role='admin'),
        mutation=dict(appareil='console-fictive', cle='m-' + str(reg.taille()),
                      empreinte_arguments=encodage.empreinte(args)), horodatage='2030-06-10T12:00:00+00:00')


def test_derniere_revision_par_personne_retraits_compris_pas_somme_des_revisions():
    reg = Registre()
    ajouter(reg)
    ajouter(reg, 'alice.fictive')
    ajouter(reg, 'bruno.fictif')
    retirer = ajouter(reg, 'alice.fictive', revision=1, statut='retiree')
    dernier = ajouter(reg, revision=1)
    ajouter(reg, 'autre.fictif', jour='2030-06-07')
    avant = reg.lire()
    r = d.lire_jour(reg, JOUR)
    assert r['total'] == 3 and r['suivant'] is None and len(r['lignes']) == 3
    assert [x['personne_id'] for x in r['lignes']] == ['alice.fictive', 'bruno.fictif', 'charlie.fictif']
    assert r['lignes'][0]['etat_declaration'] == 'retiree' and r['lignes'][0]['revision'] == 2
    assert r['lignes'][0]['source_ligne_id'] == retirer['resultat']['declaration_id']
    assert r['lignes'][2]['source_ligne_id'] == dernier['resultat']['declaration_id']
    assert r['lignes'][0]['jour'] == JOUR and r['lignes'][0]['horodatage'].startswith('2030-06-10')
    assert all('mutation' not in ligne and 'membres' not in ligne for ligne in r['lignes'])
    assert reg.lire() == avant


def test_jour_sans_signalement_et_retrait_ne_prouvent_aucune_presence():
    reg = Registre()
    assert d.lire_jour(reg, JOUR)['total'] == 0
    ajouter(reg, jour='2030-06-07')
    r = d.lire_jour(reg, JOUR)
    assert r['total'] == 0 and r['lignes'] == []
    assert 'Aucune présence, heure travaillée ou paie déduite.' in r['avertissements']
    ajouter(reg)
    ajouter(reg, revision=1, statut='retiree')
    r = d.lire_jour(reg, JOUR)
    assert r['total'] == 1 and r['lignes'][0]['etat_declaration'] == 'retiree'


def test_pages_stables_fin_vide_et_copies_independantes():
    reg = Registre()
    for personne in ['charlie.fictif', 'alice.fictive', 'bruno.fictif']:
        ajouter(reg, personne)
    tout = d.lire_jour(reg, JOUR)
    a = d.lire_jour(reg, JOUR, limite=2)
    b = d.lire_jour(reg, JOUR, debut=a['suivant'], limite=2, source_attendue=a['source'])
    assert a['lignes'] + b['lignes'] == tout['lignes'] and b['suivant'] is None
    fin = d.lire_jour(reg, JOUR, debut=3, source_attendue=a['source'])
    assert fin['total'] == 3 and fin['lignes'] == []
    a['lignes'][0]['auteur']['personne'] = 'faux.fictif'
    assert d.lire_jour(reg, JOUR)['lignes'][0]['auteur']['personne'] == 'admin.fictif'


def test_source_du_jour_obligatoire_et_perimee_apres_nouvelle_revision():
    reg = Registre()
    ajouter(reg)
    source = d.lire_jour(reg, JOUR)['source']
    for jour, options in [('2030-06-07', dict(source_attendue=source)), (JOUR, dict(debut=1))]:
        with pytest.raises(d.Refus):
            d.lire_jour(reg, jour, **options)
    ajouter(reg, revision=1, statut='retiree')
    with pytest.raises(d.Refus, match='SOURCE-PERIMEE'):
        d.lire_jour(reg, JOUR, debut=1, source_attendue=source)


@pytest.mark.parametrize('options', [dict(debut=True), dict(debut=-1), dict(limite=0), dict(limite=101),
    dict(limite=True), dict(source_attendue='fausse')])
def test_pagination_invalide_refuse_sans_mutation(options):
    reg = Registre()
    ajouter(reg)
    avant = reg.lire()
    with pytest.raises(d.Refus):
        d.lire_jour(reg, JOUR, **options)
    assert reg.lire() == avant


def test_autre_jour_corrompu_meme_rehache_nest_pas_ignore():
    reg = Registre()
    ajouter(reg)
    ajouter(reg, jour='2030-06-07')
    bruts = reg.lire()
    bruts[-1]['motif'] = 'information fictive interdite'
    rechaine = Registre()
    for m in bruts:
        rechaine.ajouter({k: v for k, v in m.items() if k not in {'ligne_id', 'precedent_ligne_id'}})
    with pytest.raises(d.Refus):
        d.lire_jour(rechaine, JOUR)


def test_quotas_avant_lecture_et_retour_sans_mutation():
    class TropGrand:
        def taille(self):
            return d.MAX_SOURCES + 1

        def lire(self):
            raise AssertionError('ne pas décoder après quota')

    with pytest.raises(d.Refus):
        d.lire_jour(TropGrand(), JOUR)
    reg = Registre()
    ajouter(reg)
    avant = deepcopy(reg.lire())
    with pytest.raises(d.Refus, match='SORTIE'):
        d.lire_jour(reg, JOUR, limite_sortie=10)
    assert reg.lire() == avant


def test_page_valide_trop_grande_reste_consultable_par_petites_pages():
    reg = Registre()
    for i in range(100):
        ajouter(reg, personne='personne.fictive.' + str(i).zfill(3), auteur='é' * 200)
    avant = reg.lire()
    with pytest.raises(d.Refus, match='SORTIE'):
        d.lire_jour(reg, JOUR, limite=100)
    petit = d.lire_jour(reg, JOUR, limite=10)
    assert len(petit['lignes']) == 10 and petit['total'] == 100 and reg.lire() == avant
