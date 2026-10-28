"""fictif: true — index pur comparé aux paquets ordinaires, aucune autorité ni donnée réelle."""
import copy
import importlib.util
from pathlib import Path

import pytest
from m10_memoire import amont, consolidation, decisions, etapes, paquets, registre, signaux, variance, wct

FICTIF = True
HEURE = '2026-10-01T08:00:00-04:00'


def _fixture(nom):
    spec = importlib.util.spec_from_file_location('preparation_fixture_' + nom,
        Path(__file__).with_name('test_' + nom + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


p, c, a, r = (_fixture(nom) for nom in ('paquets', 'confidentialite', 'paquet_affaire', 'rentabilite'))
PROFILS = (None, *c.DEPARTEMENTS)
LEADS = ('LEAD-1', 'LEAD-2', 'LEAD-B-1', 'LEAD-B-1~opp~WCT-B-9', 'LEAD-INCONNU')


def _jeu(genre):
    e, f = registre.Registre(), registre.Registre()
    if genre == 'vide':
        return e, f
    for lead in LEADS[:4]:
        cle = lead.replace('~', '-')
        if lead != 'LEAD-2':
            typ = etapes.TYPE_CLIENT_ASSOCIE if '~opp~' in lead else etapes.TYPE_LEAD_QUALIFIE
            charge = a._client(lead) if '~opp~' in lead else a._lead(lead)
            assert amont.memoriser(typ, charge, e)[1] is None
        for i in range(1, 9):
            assert amont.memoriser(etapes.TYPE_DEVIS_ACCEPTE, a._accepte(
                f'DEVIS-{cle}-{i}', lead, a._jour(i)), e)[1] is None
        assert wct.memoriser_wct(p._wct(wct_id='WCT-' + cle, lead_id=lead), e)[1] is None
        for i in range(7):
            assert variance.memoriser_variance(p._variance(evenement_id=f'VAR-{cle}-{i}',
                wct_id='WCT-' + cle), e)[1] is None
        assert r.rentabilite.memoriser_rentabilite(r._rentabilite(wct_id='WCT-' + cle), e)[1] is None
    # Variance orpheline : ne pas deviner son affaire.
    assert variance.memoriser_variance(p._variance(evenement_id='VAR-ORPHELINE', wct_id='WCT-ABSENT'), e)[1] is None
    for niveau in sorted(c.confidentialite.niveaux_connus()):
        for lead in LEADS[:4]:
            f.ajouter(c._fait_consolide(niveau, resume='Note fictive ' + niveau, affaire=lead))
        assert decisions.enregistrer_decision(p._decision('DEC-' + niveau, 'validee'), f, HEURE,
            niveau_confidentialite=niveau)[1] is None
    for statut in ('validee', 'remplacee'):
        assert decisions.enregistrer_decision(p._decision('DEC-REMPLACEE', statut), f, HEURE)[1] is None
    if genre == 'consolide':
        for jour in ('2026-09-01', '2026-09-02'):
            assert consolidation.consolider_affaire('LEAD-1', jour, HEURE, e, f)['verdict'] is None
        # Une nouvelle source tardive doit rouvrir les jours effectivement omis.
        assert amont.memoriser(etapes.TYPE_DEVIS_ACCEPTE,
            a._accepte('DEVIS-TARDIF', 'LEAD-1', a._jour(2, '17:00:00')), e)[1] is None
    elif genre == 'cles_contradictoires':
        assert consolidation.consolider_affaire('LEAD-1', '2026-09-02', HEURE, e, f)['verdict'] is None
        ligne = next(m for m in reversed(f.lire()) if m.get('cle_consolidation') == 'LEAD-1:2026-09-02')
        ligne['affaire_id'] = 'LEAD-2'
        ligne['sources'] = []
        f.ajouter(ligne)
    elif genre == 'wct_duplique':
        ligne = next(m for m in e.lire() if m.get('wct_id') == 'WCT-LEAD-1' and 'duree_reelle_minutes' in m)
        ligne['lead_id'] = 'LEAD-2'
        e.ajouter(ligne)
    elif genre == 'cycle_signaux':
        for action in (signaux.ACTION_PRISE_EN_COMPTE, signaux.ACTION_CLOTURE):
            assert signaux.traiter_signal(action, 'VAR-LEAD-1-0', 'admin.fictif', 'admin', 'appareil',
                'Explication fictive documentée pour ce contrôle', HEURE, e, f)[1] is None
        ligne = next(m for m in e.lire() if m.get('evenement_id') == 'VAR-LEAD-1-1')
        ligne['wct_id'] = 'WCT-LEAD-2'
        e.ajouter(ligne)  # la première occurrence globale reste la seule source du signal
        for heure in ('2026-09-15T10:00:00-04:00', '2026-09-15T14:00:00+00:00'):
            f.ajouter(dict(type_entree='decision_enregistree', decision_id='DEC-OFFSET-' + heure,
                raison='Fictif ordre stable', statut='validee', options_ecartees='', horodatage=heure))
        assert variance.memoriser_variance(p._variance(evenement_id='VAR-REEVALUEE',
            wct_id='WCT-LEAD-2', signal_critique=False), e)[1] is None
    assert e.valider_chaine()[0] and f.valider_chaine()[0]
    return e, f


def test_projection_vide_identique():
    e, f = _jeu('vide')
    preparation = paquets.preparer_paquets(e, f)
    assert preparation.assembler('LEAD-1', HEURE) == paquets.assembler_paquet_contexte('LEAD-1', HEURE, e, f)


@pytest.mark.parametrize('genre', ['riche', 'consolide', 'cles_contradictoires', 'wct_duplique', 'cycle_signaux'])
def test_differentiel_complet_profils_budgets_et_affaires(genre):
    e, f = _jeu(genre)
    avant = e.lire(), f.lire()
    preparation = paquets.preparer_paquets(e, f)
    for lead in LEADS:
        for profil in PROFILS:
            for budget, maximum in ((1, 1), (4000, 5), (40000, 30)):
                options = dict(agent=profil, budget_caracteres=budget, n_faits_max_par_couche=maximum)
                attendu = paquets.assembler_paquet_contexte(lead, HEURE, e, f, **options)
                assert preparation.assembler(lead, HEURE, **options) == attendu, (genre, lead, profil, budget)
    assert (e.lire(), f.lire()) == avant


def test_preparation_snapshot_et_sorties_sans_alias():
    e, f = _jeu('riche')
    attendu = paquets.assembler_paquet_contexte('LEAD-1', HEURE, e, f)
    preparation = paquets.preparer_paquets(e, f)
    sortie = preparation.assembler('LEAD-1', HEURE)
    sortie['affaire'].clear()
    sortie['consolidation']['a_consolider'].clear()
    sortie['consolidation']['nb_a_consolider'] = 999
    sortie['couches'][0]['faits'].clear()
    e.ajouter(dict(type_entree='evenement_memorise', horodatage=HEURE))
    f.ajouter(c._fait_consolide('INTERNAL', resume='Nouvelle source fictive', affaire='LEAD-1'))
    assert preparation.assembler('LEAD-1', HEURE) == attendu
    autre_heure = '2026-10-02T08:00:00-04:00'
    assert preparation.assembler('LEAD-1', autre_heure) == {**attendu, 'horodatage': autre_heure}


@pytest.mark.parametrize('options', [dict(budget_caracteres=True), dict(budget_caracteres=0),
    dict(n_faits_max_par_couche=False), dict(n_faits_max_par_couche=-1), dict(agent='autre'), dict(affaire_id='é')])
def test_validation_par_requete_identique(options):
    e, f = _jeu('vide')
    preparation = paquets.preparer_paquets(e, f)
    args = dict(affaire_id='LEAD-1', horodatage=HEURE) | options
    with pytest.raises(ValueError) as ordinaire:
        paquets.assembler_paquet_contexte(registre_evenements=e, registre_affaires=f, **args)
    with pytest.raises(ValueError) as preparee:
        preparation.assembler(**args)
    assert str(preparee.value) == str(ordinaire.value)


def test_lecteurs_fournis_ne_peuvent_modifier_snapshot():
    e, f = _jeu('riche')
    attendu = paquets.assembler_paquet_contexte('LEAD-1', HEURE, e, f)

    class LecteurAlias:
        def __init__(self, lignes):
            self.lignes = lignes

        def lire(self):
            return self.lignes

    le, lf = LecteurAlias(e.lire()), LecteurAlias(f.lire())
    preparation = paquets.preparer_paquets(le, lf)
    le.lignes.clear()
    lf.lignes[0].clear()
    reponse = preparation.assembler('LEAD-1', HEURE)
    assert reponse == attendu
    assert copy.deepcopy(reponse) == preparation.assembler('LEAD-1', HEURE)
