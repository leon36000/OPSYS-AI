"""Plan pur de preuves : positions finales, notes et références CAS déclarées.

Le caller valide auparavant le formulaire canonique et son WCT avec validation.py.
Ce module ne lit ni CAS, identité, horloge, prix ou stock. Une référence syntaxiquement
valide ne prouve pas l'existence du fichier, son contenu ou l'authenticité d'une photo.
"""
import re
import unicodedata

from . import contrats

MAX_LIGNES = 24
MAX_PREUVES = 8
MAX_PHOTOS_PAR_PREUVE = 3
MAX_NOTE_POINTS = 500
CHAMPS_PREUVE = frozenset({'position_ligne', 'note', 'photos'})
REFERENCE_CAS = re.compile(r'fichier:sha256:[0-9a-f]{64}\Z')


def _refus(suffixe):
    return None, 'REJ-M6-PREUVES-' + suffixe


def _objet(v):
    return type(v) is dict and all(type(k) is str for k in v)


def _note(v):
    return (
        type(v) is str
        and 1 <= len(v) <= MAX_NOTE_POINTS
        and bool(v.strip())
        and all(unicodedata.category(c) not in {'Cc', 'Cs'} or c in '\t\r\n' for c in v)
    )


def valider_preuves_lignes(lignes, preuves):
    """Copie le plan fourni, sans réordonner ni réparer une donnée de saisie.

    Relation seulement : la validation métier des quantités/unités et l'autorité
    restent le formulaire existant et la future façade transactionnelle.
    """
    if type(lignes) is not list or not lignes or type(preuves) is not list:
        return _refus('ARGUMENTS-INVALIDES')
    if len(lignes) > MAX_LIGNES or len(preuves) > MAX_PREUVES:
        return _refus('BORNE-DEPASSEE')
    attendues = set()
    for position, ligne in enumerate(lignes):
        if not _objet(ligne):
            return _refus('ARGUMENTS-INVALIDES')
        type_ligne = ligne.get('type_ligne')
        if type(type_ligne) is not str or type_ligne not in contrats.TYPES_LIGNE_MATERIAUX_UTILISES:
            return _refus('ARGUMENTS-INVALIDES')
        if type_ligne == 'achat_terrain':
            return _refus('ACHAT-TERRAIN-HORS-PERIMETRE')
        if type_ligne in {'perte', 'bris'}:
            attendues.add(position)
    vues = set()
    resultat = []
    for p in preuves:
        if not _objet(p) or set(p) != CHAMPS_PREUVE:
            return _refus('ARGUMENTS-INVALIDES')
        position = p['position_ligne']
        if type(position) is not int or position not in attendues or position in vues:
            return _refus('POSITION-INVALIDE')
        if not _note(p['note']):
            return _refus('NOTE-INVALIDE')
        photos = p['photos']
        if (
            type(photos) is not list
            or len(photos) > MAX_PHOTOS_PAR_PREUVE
            or any(type(x) is not str or REFERENCE_CAS.fullmatch(x) is None for x in photos)
            or len(set(photos)) != len(photos)
        ):
            return _refus('PHOTOS-INVALIDES')
        vues.add(position)
        resultat.append({'position_ligne': position, 'note': p['note'], 'photos': photos.copy()})
    if vues != attendues:
        return _refus('PREUVE-MANQUANTE')
    return resultat, None
