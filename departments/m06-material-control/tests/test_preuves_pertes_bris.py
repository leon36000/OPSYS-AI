"""Pure proof plan: explicit positions/notes/references, never a CAS or actor claim."""
from copy import deepcopy
from importlib import import_module

import pytest


def lire(lignes, preuves):
    return import_module('m6_material_control.preuves_pertes_bris').valider_preuves_lignes(lignes, preuves)


def ligne(type_ligne='perte'):
    return {'type_ligne': type_ligne, 'materiau_id': 'MAT-FICTIF', 'quantite': 1, 'unite': 'pi'}


def preuve(position=0, note='Perte déclarée FICTIVE.', photos=None):
    return {'position_ligne': position, 'note': note, 'photos': [] if photos is None else photos}


def test_note_seule_preserve_verbatim_et_ne_mutate_pas_les_sources():
    lignes = [ligne()]
    preuves = [preuve(note='  note FICTIVE\n\tconservée  ')]
    before = deepcopy((lignes, preuves))
    obtenu, code = lire(lignes, preuves)
    assert code is None and obtenu == preuves and (lignes, preuves) == before
    assert obtenu is not preuves and obtenu[0] is not preuves[0]
    assert obtenu[0]['photos'] is not preuves[0]['photos']
    assert not any(k in obtenu[0] for k in ('acteur', 'photo_verifiee', 'horodatage_capture', 'cause'))


def test_deux_pertes_identiques_restant_deux_positions_et_ordre_fourni():
    preuves = [preuve(1, 'Deuxième FICTIVE.'), preuve(0, 'Première FICTIVE.')]
    assert lire([ligne(), ligne()], preuves) == (preuves, None)


def test_photo_reference_ne_prouve_pas_son_existence():
    references = ['fichier:sha256:' + x * 64 for x in ('a', 'b', 'c')]
    assert lire([ligne('bris')], [preuve(photos=references)]) == ([preuve(photos=references)], None)


def test_autres_lignes_canoniques_sans_preuve_et_positions_finales_distinctes():
    lignes = [ligne('non_prevu'), ligne('bris'), ligne('retour'), ligne('perte')]
    preuves = [preuve(3), preuve(1)]
    assert lire(lignes, preuves) == (preuves, None)
    assert lire([ligne('retour')], []) == ([], None)


@pytest.mark.parametrize('preuves', [
    None, {}, (), [None], [True],
    [{'position_ligne': 0, 'note': 'FICTIF', 'photos': [], 'auteur': 'imposteur'}],
])
def test_structure_fermee(preuves):
    assert lire([ligne()], preuves) == (None, 'REJ-M6-PREUVES-ARGUMENTS-INVALIDES')


@pytest.mark.parametrize('position', [True, -1, 1, 0.0, '0'])
def test_position_entier_exact_dans_le_formulaire(position):
    assert lire([ligne()], [preuve(position)]) == (None, 'REJ-M6-PREUVES-POSITION-INVALIDE')


def test_absence_doublon_et_preuve_sur_consommation_refuses():
    assert lire([ligne()], []) == (None, 'REJ-M6-PREUVES-PREUVE-MANQUANTE')
    assert lire([ligne()], [preuve(), preuve()]) == (None, 'REJ-M6-PREUVES-POSITION-INVALIDE')
    assert lire([ligne('non_prevu')], [preuve()]) == (None, 'REJ-M6-PREUVES-POSITION-INVALIDE')


@pytest.mark.parametrize('note', ['', ' \n\t\r', 'x' * 501, '\ud800', 'nul\x00', 'contrôle\x85', None, True])
def test_note_bornee_non_blanche_et_sans_surrogate_controle(note):
    assert lire([ligne()], [preuve(note=note)]) == (None, 'REJ-M6-PREUVES-NOTE-INVALIDE')


def test_note_500_points_unicode_et_tabs_cr_lf_valides():
    assert lire([ligne()], [preuve(note='💥' * 500)]) == ([preuve(note='💥' * 500)], None)
    assert lire([ligne()], [preuve(note='FICTIF\t\r\n')]) == ([preuve(note='FICTIF\t\r\n')], None)


@pytest.mark.parametrize('photos', [
    None, (), ['fichier:sha256:' + 'A' * 64], ['https://photo.invalid/x'],
    ['fichier:sha256:' + 'a' * 63], ['fichier:sha256:' + 'a' * 64] * 2,
    ['fichier:sha256:' + 'a' * 64] * 4, [True],
])
def test_references_cas_fermees_et_uniques_par_position(photos):
    assert lire([ligne()], [preuve(photos=[]) | {'photos': photos}]) == (None, 'REJ-M6-PREUVES-PHOTOS-INVALIDES')


def test_meme_photo_sur_deux_positions_est_une_association_declaree():
    photo = 'fichier:sha256:' + 'a' * 64
    preuves = [preuve(0, photos=[photo]), preuve(1, photos=[photo])]
    assert lire([ligne(), ligne()], preuves) == (preuves, None)


def test_bornes_lignes_et_nombre_preuves():
    assert lire([ligne('non_prevu')] * 24, []) == ([], None)
    assert lire([ligne('non_prevu')] * 25, []) == (None, 'REJ-M6-PREUVES-BORNE-DEPASSEE')
    assert lire([ligne()] * 8, [preuve(i) for i in range(8)])[1] is None
    assert lire([ligne()] * 9, [preuve(i) for i in range(9)]) == (None, 'REJ-M6-PREUVES-BORNE-DEPASSEE')


def test_achat_terrain_reste_son_contrat_historique_separe():
    assert lire([ligne('achat_terrain')], []) == (None, 'REJ-M6-PREUVES-ACHAT-TERRAIN-HORS-PERIMETRE')


@pytest.mark.parametrize('lignes', [None, {}, (), [], [None], [{'type_ligne': 'inconnu'}]])
def test_relation_exige_liste_de_lignes_canoniques(lignes):
    assert lire(lignes, []) == (None, 'REJ-M6-PREUVES-ARGUMENTS-INVALIDES')
