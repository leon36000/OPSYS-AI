"""CSV UTF-8 explicitement mappé vers candidats M6; aucun sniffing ni écriture."""
import csv
import io

from . import import_tarifs
from .tarif_soumission import _texte

VERSION = 'm6-import-tarifs-csv-v1'
_CHAMPS = {'materiau_id', 'unite', 'prix_unitaire_decimal', 'devise', 'date_effet'}
MAX_COLONNES = 50


def _correspondances(mapping):
    if type(mapping) is not dict or len(mapping) != len(_CHAMPS):
        raise import_tarifs.Refus('MAPPING_COLONNES_INVALIDE')
    copie = mapping.copy()
    if (set(copie) != _CHAMPS or any(not _texte(v, 200) for v in copie.values())
            or len(set(copie.values())) != len(_CHAMPS)):
        raise import_tarifs.Refus('MAPPING_COLONNES_INVALIDE')
    return copie


def _lignes(source, mapping, separateur):
    try:
        texte = source.decode('utf-8-sig')
        if '\x00' in texte:
            raise import_tarifs.Refus('CSV_INVALIDE')
        lecteur = csv.reader(io.StringIO(texte, newline=''), delimiter=separateur, strict=True)
        try:
            entetes = next(lecteur)
        except StopIteration:
            raise import_tarifs.Refus('CSV_INVALIDE') from None
        if len(entetes) > MAX_COLONNES:
            raise import_tarifs.Refus('CSV_TROP_VOLUMINEUX')
        if (not entetes or any(not _texte(v, 200) for v in entetes)
                or len(set(entetes)) != len(entetes)):
            raise import_tarifs.Refus('ENTETES_INVALIDES')
        if not set(mapping.values()) <= set(entetes):
            raise import_tarifs.Refus('MAPPING_COLONNES_INVALIDE')
        indices = {champ: entetes.index(colonne) for champ, colonne in mapping.items()}
        lignes = []
        while True:
            debut = lecteur.line_num + 1
            try:
                cellules = next(lecteur)
            except StopIteration:
                break
            if len(lignes) >= import_tarifs.MAX_LIGNES:
                raise import_tarifs.Refus('CSV_TROP_VOLUMINEUX')
            if len(cellules) != len(entetes):
                raise import_tarifs.Refus('CSV_LIGNE_INVALIDE')
            if any(len(v) > import_tarifs.MAX_CELLULE for v in cellules):
                raise import_tarifs.Refus('CSV_TROP_VOLUMINEUX')
            lignes.append(dict(numero_ligne=debut, **{champ: cellules[i] for champ, i in indices.items()}))
        return lignes, len(entetes)
    except (UnicodeError, csv.Error):
        raise import_tarifs.Refus('CSV_INVALIDE') from None


def preparer(source_octets, *, mapping_colonnes, separateur, fournisseur_id, source_document,
             jour_reference, limite_sortie=65536):
    if (type(separateur) is not str or separateur not in {',', ';'}
            or type(limite_sortie) is not int or limite_sortie < 1):
        raise import_tarifs.Refus('ARGUMENTS')
    if type(source_octets) is not bytes or not source_octets:
        raise import_tarifs.Refus('SOURCE_INVALIDE')
    if len(source_octets) > import_tarifs.MAX_SOURCE:
        raise import_tarifs.Refus('SOURCE_TROP_VOLUMINEUSE')
    mapping = _correspondances(mapping_colonnes)
    lignes, colonnes = _lignes(source_octets, mapping, separateur)
    lot = import_tarifs.preparer(lignes, fournisseur_id=fournisseur_id, source_document=source_document,
                                 source_octets=source_octets, jour_reference=jour_reference,
                                 limite_sortie=limite_sortie)
    extraction = dict(encodage='UTF-8', separateur=separateur, mapping_colonnes=mapping,
                      mapping_colonnes_sha256=import_tarifs._sha(mapping),
                      nombre_colonnes_source=colonnes, enregistrements_lus=len(lignes))
    vue = dict(version=VERSION, extraction=extraction, lot=lot)
    # La configuration reste distincte du mapping sémantique porté par le lot propriétaire.
    vue['preparation_sha256'] = import_tarifs._sha(vue)
    if len(import_tarifs._encoder(vue)) > min(import_tarifs.MAX_SORTIE, limite_sortie):
        raise import_tarifs.Refus('SORTIE_TROP_VOLUMINEUSE')
    return vue
