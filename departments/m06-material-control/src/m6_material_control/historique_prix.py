"""Historique pur de prix déclarés : rangs d’écriture, aucune sélection ou conversion de coût."""
import hashlib
import json
import re
from datetime import date
from decimal import Decimal

from . import livre_prix
from .tarif_soumission import _texte

MAX_SOURCES = 10000
MAX_OCTETS = 8 * 1024 * 1024
MAX_SORTIE = 65536
VERSION = 'historique-prix-v1'
_AVERTISSEMENTS = [
    'Ordre des écritures du couple exact; date commerciale déclarée, pas date de réception.',
    'Dernière écriture ne signifie pas prix utilisable pour un devis ou un achat.',
    'Référence documentaire déclarée, sans authentification; aucune conversion de devise ou unité.',
]


class Refus(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _encoder(valeur):
    return json.dumps(valeur, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def _empreinte(valeur):
    return hashlib.sha256(_encoder(valeur)).hexdigest()


def _valider(entree):
    requis = {'materiau_id', 'fournisseur_id', 'prix_unitaire', 'devise', 'date_effet'}
    if (type(entree) is not dict or not requis <= set(entree)
            or set(entree) - requis - {'source_document', 'unite'}):
        raise Refus('SOURCE-INVALIDE')
    for cle, maximum in [('materiau_id', 200), ('fournisseur_id', 200), ('devise', 40), ('date_effet', 100)]:
        if not _texte(entree[cle], maximum):
            raise Refus('SOURCE-INVALIDE')
    for cle, maximum in [('unite', 40), ('source_document', 1000)]:
        if entree.get(cle) is not None and not _texte(entree[cle], maximum):
            raise Refus('SOURCE-INVALIDE')
    # Validation métier existante sur une liste privée; aucun journal du propriétaire modifié.
    _, refus = livre_prix.enregistrer_prix(
        entree['materiau_id'], entree['fournisseur_id'], entree['prix_unitaire'], entree['devise'],
        entree['date_effet'], [], source_document=entree.get('source_document'), unite=entree.get('unite'))
    if refus is not None:
        raise Refus('SOURCE-INVALIDE')


def _capturer(lignes):
    if type(lignes) not in (list, tuple):
        raise Refus('SOURCE-INVALIDE')
    if len(lignes) > MAX_SOURCES:
        raise Refus('SOURCES-TROP-VOLUMINEUSES')
    try:
        brut = _encoder(lignes)
        if len(brut) > MAX_OCTETS:
            raise Refus('SOURCES-TROP-VOLUMINEUSES')
        copie = json.loads(brut)
        for attendu, paire in enumerate(copie):
            if (type(paire) is not list or len(paire) != 2 or type(paire[0]) is not int or paire[0] != attendu):
                raise Refus('SOURCE-INVALIDE')
            _valider(paire[1])
    except Refus:
        raise
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise Refus('SOURCE-INVALIDE') from None
    return copie, hashlib.sha256(brut).hexdigest()


def _montant(prix):
    # Borner avant formatage d’un entier immense ou d’un très petit exposant; jamais arrondir.
    if type(prix) is int and prix.bit_length() > 214:
        return None
    nombre = Decimal(str(prix))
    if not -62 <= nombre.adjusted() <= 63:
        return None
    resultat = format(nombre, 'f')
    return resultat if len(resultat) <= 64 else None


def _ligne(rang, entree, version, derniere):
    avertissements = []
    montant = _montant(entree['prix_unitaire'])
    if montant is None:
        avertissements.append('PRIX_NON_REPRESENTABLE')
    unite = entree.get('unite')
    if unite is None:
        avertissements.append('UNITE_NON_DOCUMENTEE')
    try:
        if date.fromisoformat(entree['date_effet']).isoformat() != entree['date_effet']:
            raise ValueError
    except ValueError:
        avertissements.append('DATE_NON_ISO_DECLAREE')
    document = entree.get('source_document')
    return dict(rang_sql=rang, version_du_couple=version, derniere_ecriture=derniere,
                materiau_id=entree['materiau_id'], fournisseur_id=entree['fournisseur_id'],
                prix_unitaire_decimal=montant, devise=entree['devise'], unite=unite,
                date_effet=entree['date_effet'], source_document=document,
                marquage_source=livre_prix.marquage_source_document(document),
                source_entree=_empreinte(dict(rang=rang, entree=entree)), avertissements=avertissements)


def lire(lignes, materiau_id, fournisseur_id, *, debut=0, limite=25, source_attendue=None, limite_sortie=65536):
    if (not _texte(materiau_id, 200) or not _texte(fournisseur_id, 200)
            or type(debut) is not int or not 0 <= debut <= MAX_SOURCES
            or type(limite) is not int or not 1 <= limite <= 50
            or type(limite_sortie) is not int or limite_sortie < 1
            or (source_attendue is not None and (type(source_attendue) is not str
                or re.fullmatch('[0-9a-f]{64}', source_attendue) is None))
            or (debut and source_attendue is None)):
        raise Refus('ARGUMENTS')
    copie, empreinte = _capturer(lignes)
    source = _empreinte([VERSION, materiau_id, fournisseur_id, empreinte])
    if source_attendue is not None and source_attendue != source:
        raise Refus('SOURCE-PERIMEE')
    choisies = [(rang, entree) for rang, entree in copie
                if entree['materiau_id'] == materiau_id and entree['fournisseur_id'] == fournisseur_id]
    total = len(choisies)
    page = [_ligne(rang, entree, debut + index + 1, debut + index + 1 == total)
            for index, (rang, entree) in enumerate(choisies[debut:debut + limite])]
    resultat = dict(materiau_id=materiau_id, fournisseur_id=fournisseur_id, debut=debut, total=total,
                    suivant=debut + len(page) if debut + len(page) < total else None,
                    source=source, source_snapshot=empreinte, lignes=page, avertissements=list(_AVERTISSEMENTS))
    if len(_encoder(resultat)) > min(MAX_SORTIE, limite_sortie):
        raise Refus('SORTIE-TROP-VOLUMINEUSE')
    return resultat
