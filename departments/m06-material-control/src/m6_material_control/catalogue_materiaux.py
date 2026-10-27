"""Fiches matériaux versionnées, sans prix ni stock; l'adaptateur authentifie l'auteur.

Patron append-only des journaux M6 et CAS des modèles M3, sans import interdépartement.
Aucune horloge ni E/S. Une empreinte n'authentifie pas une réécriture cohérente du journal.
"""
import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime

REGISTRE = 'catalogue_materiaux'
MAX_SOURCES = 10000
TYPE = 'materiau_version'
_CLES = {'type_entree', 'materiau_id', 'nom', 'unite', 'actif', 'raison', 'auteur', 'horodatage',
         'revision', 'rang', 'precedent', 'source_id'}


class CatalogueRefuse(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _texte(valeur, maximum):
    return (type(valeur) is str and 0 < len(valeur) <= maximum and valeur == valeur.strip()
            and all(c.isprintable() for c in valeur))


def _identite(valeur):
    return (type(valeur) is str and valeur not in {'.', '..'}
            and re.fullmatch(r'[a-zA-Z0-9_.:-]{1,100}', valeur) is not None)


def _fiche(m):
    if (not _identite(m['materiau_id']) or not _texte(m['nom'], 200) or not _texte(m['unite'], 40)
            or type(m['actif']) is not bool or not _texte(m['raison'], 500) or not _texte(m['auteur'], 200)
            or not _texte(m['horodatage'], 50)):
        raise CatalogueRefuse('ARGUMENTS')
    try:
        date = datetime.fromisoformat(m['horodatage'])
        if date.utcoffset() is None:
            raise ValueError('timezone')
    except ValueError:
        raise CatalogueRefuse('ARGUMENTS') from None


def _empreinte(m):
    contenu = {k: v for k, v in m.items() if k != 'source_id'}
    return hashlib.sha256(json.dumps(contenu, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _charger(journal):
    if len(journal) > MAX_SOURCES:
        raise CatalogueRefuse('SOURCES-TROP-VOLUMINEUSES')
    maillons = list(journal)
    if len(maillons) > MAX_SOURCES:
        raise CatalogueRefuse('SOURCES-TROP-VOLUMINEUSES')
    courants, precedent = {}, None
    for rang, m in enumerate(maillons):
        try:
            if type(m) is not dict or set(m) != _CLES:
                raise CatalogueRefuse('SOURCE-INVALIDE')
            _fiche(m)
            ancien = courants.get(m['materiau_id'])
            if (m['type_entree'] != TYPE or type(m['rang']) is not int or m['rang'] != rang
                    or type(m['revision']) is not int or m['revision'] != (ancien['revision'] + 1 if ancien else 1)
                    or m['precedent'] != precedent or m['source_id'] != _empreinte(m)
                    or (ancien and m['unite'] != ancien['unite'])):
                raise CatalogueRefuse('SOURCE-INVALIDE')
        except (CatalogueRefuse, KeyError, TypeError, ValueError):
            raise CatalogueRefuse('SOURCE-INVALIDE') from None
        courants[m['materiau_id']] = m
        precedent = m['source_id']
    return maillons, courants, precedent


def enregistrer(journal, *, materiau_id, nom, unite, actif, raison, auteur, horodatage, revision_attendue):
    """Ajoute une révision entière; transaction, autorité et reçu relèvent de l'adaptateur."""
    candidat = dict(materiau_id=materiau_id, nom=nom, unite=unite, actif=actif,
                    raison=raison, auteur=auteur, horodatage=horodatage)
    _fiche(candidat)
    if type(revision_attendue) is not int or not 0 <= revision_attendue < MAX_SOURCES:
        raise CatalogueRefuse('ARGUMENTS')
    maillons, courants, precedent = _charger(journal)
    ancien = courants.get(materiau_id)
    if revision_attendue != (ancien['revision'] if ancien else 0):
        raise CatalogueRefuse('REVISION-PERIMEE')
    if ancien and unite != ancien['unite']:
        raise CatalogueRefuse('UNITE-IMMUABLE')
    if len(maillons) >= MAX_SOURCES:
        raise CatalogueRefuse('SOURCES-TROP-VOLUMINEUSES')
    candidat.update(type_entree=TYPE, revision=revision_attendue + 1, rang=len(maillons), precedent=precedent)
    candidat['source_id'] = _empreinte(candidat)
    journal.append(deepcopy(candidat))
    return deepcopy(candidat)


def lire(journal, materiau_id, *, revision=0):
    if not _identite(materiau_id) or type(revision) is not int or not 0 <= revision <= MAX_SOURCES:
        raise CatalogueRefuse('ARGUMENTS')
    maillons, courants, _ = _charger(journal)
    choisi = (courants.get(materiau_id) if revision == 0 else next(
        (m for m in maillons if m['materiau_id'] == materiau_id and m['revision'] == revision), None))
    if choisi is None:
        raise CatalogueRefuse('INTROUVABLE')
    return deepcopy(choisi)


def lister(journal, *, debut=0, limite=50, actifs_seulement=True):
    if (type(debut) is not int or not 0 <= debut <= MAX_SOURCES
            or type(limite) is not int or not 1 <= limite <= 50 or type(actifs_seulement) is not bool):
        raise CatalogueRefuse('ARGUMENTS')
    _, courants, _ = _charger(journal)
    choix = [m for _, m in sorted(courants.items()) if m['actif'] or not actifs_seulement]
    page = choix[debut:debut + limite]
    return {'materiaux': deepcopy(page), 'total': len(choix),
            'suivant': debut + len(page) if debut + len(page) < len(choix) else None}
