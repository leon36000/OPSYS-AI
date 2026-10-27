"""Mémoire privée des versions de configuration métier, sans affaire ni contenu source."""
import hashlib
import re
from copy import deepcopy
from datetime import datetime

from .registre import Registre

REGISTRE = 'references_configuration'
MAX_SOURCES = 10000
SOURCES = {
    'm3_modeles': ('m03-estimation', 'modeles_soumission', 'm3.catalogue_reference'),
    'm3_lignes': ('m03-estimation', 'modeles_lignes_soumission', 'm3.catalogue_reference'),
    'm6_materiaux': ('m06-material-control', 'catalogue_materiaux', 'm6.catalogue_reference'),
    'm6_fournisseurs': ('m06-material-control', 'fournisseurs', 'm6.catalogue_reference'),
}
CHAMPS_REFERENCE = {'fait_id', 'source_genre', 'source_rang', 'source_revision', 'source_sha256', 'horodatage'}


def valider(charge):
    if type(charge) is not dict or set(charge) != CHAMPS_REFERENCE:
        raise ValueError('Forme de référence configuration invalide')
    genre, rang, revision, empreinte = (charge[k] for k in
                                      ('source_genre', 'source_rang', 'source_revision', 'source_sha256'))
    if (type(genre) is not str or genre not in SOURCES or type(rang) is not int or not 0 <= rang < MAX_SOURCES
            or type(revision) is not int or not 1 <= revision <= MAX_SOURCES
            or type(empreinte) is not str or re.fullmatch(r'[0-9a-f]{64}', empreinte) is None
            or type(charge['horodatage']) is not str or len(charge['horodatage']) > 50):
        raise ValueError('Valeur de référence configuration invalide')
    try:
        date = datetime.fromisoformat(charge['horodatage'])
        if date.utcoffset() is None:
            raise ValueError('fuseau')
    except ValueError:
        raise ValueError('Horodatage de référence configuration invalide') from None
    attendu = hashlib.sha256(f'catalogue-reference-v1:{genre}:{rang}:{revision}:{empreinte}'.encode()).hexdigest()
    if charge['fait_id'] != attendu:
        raise ValueError('Identité de référence configuration invalide')
    return deepcopy(charge)


def _charger(maillons):
    if len(maillons) > MAX_SOURCES:
        raise ValueError('Mémoire de configuration hors borne')
    snapshot = list(maillons)
    chaine = Registre(list(snapshot))
    try:
        valide, _ = chaine.valider_chaine()
        if not valide:
            raise ValueError('chaîne')
        vus = set()
        for m in snapshot:
            if (set(m) != CHAMPS_REFERENCE | {'type_entree', 'confidentialite', 'ligne_id', 'precedent_ligne_id'}
                    or m['type_entree'] != 'evenement_memorise' or m['confidentialite'] != 'SENSITIVE'):
                raise ValueError('forme')
            valider({k: m[k] for k in CHAMPS_REFERENCE})
            cle = (m['source_genre'], m['source_rang'])
            if cle in vus:
                raise ValueError('doublon')
            vus.add(cle)
    except (KeyError, TypeError, ValueError):
        raise ValueError('Mémoire de configuration invalide') from None
    return snapshot


def lire(maillons, fait_id):
    if type(fait_id) is not str or re.fullmatch(r'[0-9a-f]{64}', fait_id) is None:
        raise ValueError('Identité de référence configuration invalide')
    snapshot = _charger(maillons)
    return deepcopy(next((m for m in snapshot if m['fait_id'] == fait_id), None))


def memoriser(maillons, charge):
    source = valider(charge)
    snapshot = _charger(maillons)
    chaine = Registre(list(snapshot))
    existant = next((m for m in snapshot if (m['source_genre'], m['source_rang']) ==
                     (source['source_genre'], source['source_rang'])), None)
    if existant is not None:
        if any(existant[k] != source[k] for k in CHAMPS_REFERENCE):
            raise ValueError('Référence configuration contradictoire')
        return {'memorise': True, 'identique': True, 'ligne_id': existant['ligne_id'], 'fait_id': source['fait_id']}
    if len(snapshot) == MAX_SOURCES:
        raise ValueError('Mémoire de configuration hors borne')
    chaine.ajouter(dict(source, type_entree='evenement_memorise', confidentialite='SENSITIVE'))
    m = chaine.lire()[-1]
    maillons.append(deepcopy(m), rang_attendu=len(snapshot))
    return {'memorise': True, 'identique': False, 'ligne_id': m['ligne_id'], 'fait_id': source['fait_id']}
