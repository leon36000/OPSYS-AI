"""Candidats purs issus de lignes explicitement mappées; aucune extraction ou application."""
import hashlib
import json
import math
import re
from collections import Counter
from datetime import date
from decimal import Decimal

from . import catalogue_materiaux, livre_prix
from .tarif_soumission import _texte

VERSION = 'm6-import-tarifs-candidats-v1'
MAX_LIGNES = 50
MAX_SOURCE = 1048576
MAX_MAPPING = 262144
MAX_CELLULE = 4096
MAX_SORTIE = 65536
CHAMPS_LIGNE = {'numero_ligne', 'materiau_id', 'unite', 'prix_unitaire_decimal', 'devise', 'date_effet'}
_AVERTISSEMENTS = ('EXTRACTION_NON_VERIFIEE', 'CATALOGUE_NON_VERIFIE',
                  'FOURNISSEUR_NON_VERIFIE', 'AUCUN_PRIX_APPLIQUE')


class Refus(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _encoder(valeur):
    return json.dumps(valeur, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def _sha(valeur):
    return hashlib.sha256(_encoder(valeur)).hexdigest()


def _jour(valeur):
    if type(valeur) is not str or len(valeur) != 10:
        return None
    try:
        jour = date.fromisoformat(valeur)
        return jour if jour.isoformat() == valeur else None
    except ValueError:
        return None


def _mapping(lignes):
    if type(lignes) is not list or not lignes:
        raise Refus('MAPPING_INVALIDE')
    if len(lignes) > MAX_LIGNES:
        raise Refus('MAPPING_TROP_VOLUMINEUX')
    taille, copie = 0, []
    for originale in tuple(lignes):
        if type(originale) is not dict or len(originale) != len(CHAMPS_LIGNE):
            raise Refus('MAPPING_INVALIDE')
        ligne = originale.copy()
        if set(ligne) != CHAMPS_LIGNE:
            raise Refus('MAPPING_INVALIDE')
        for valeur in ligne.values():
            if type(valeur) not in (str, int, float, bool, type(None)):
                raise Refus('MAPPING_INVALIDE')
            if type(valeur) is str:
                if len(valeur) > MAX_CELLULE:
                    raise Refus('MAPPING_TROP_VOLUMINEUX')
                try:
                    taille += len(valeur.encode('utf-8'))
                except UnicodeError:
                    raise Refus('MAPPING_INVALIDE') from None
            elif type(valeur) is int and valeur.bit_length() > 256:
                raise Refus('MAPPING_TROP_VOLUMINEUX')
            elif type(valeur) is float and not math.isfinite(valeur):
                raise Refus('MAPPING_INVALIDE')
            if taille > MAX_MAPPING:
                raise Refus('MAPPING_TROP_VOLUMINEUX')
        copie.append(ligne)
    brut = _encoder(copie)
    if len(brut) > MAX_MAPPING:
        raise Refus('MAPPING_TROP_VOLUMINEUX')
    return copie, hashlib.sha256(brut).hexdigest()


def _montant(valeur):
    if type(valeur) is not str or re.fullmatch(r'[0-9]{1,9}(\.[0-9]{1,6})?', valeur) is None:
        return None
    montant = Decimal(valeur)
    if montant <= 0 or Decimal(str(float(montant))) != montant:
        return None
    return format(montant, 'f')


def _numero(valeur):
    return type(valeur) is int and 1 <= valeur <= 50000


def _ligne(ligne, position, fournisseur_id, document, jour, numeros, materiaux):
    erreurs = []
    numero = ligne['numero_ligne']
    materiau = ligne['materiau_id']
    if not _numero(numero):
        erreurs.append('NUMERO_LIGNE_INVALIDE')
    elif numeros[numero] > 1:
        erreurs.append('DOUBLON_LIGNE')
    if not catalogue_materiaux._identite(materiau):
        erreurs.append('MATERIAU_INVALIDE')
    elif materiaux[materiau] > 1:
        erreurs.append('DOUBLON_MATERIAU')
    if not catalogue_materiaux._texte(ligne['unite'], 40):
        erreurs.append('UNITE_INVALIDE')
    if ligne['devise'] != 'CAD' or type(ligne['devise']) is not str:
        erreurs.append('DEVISE_NON_SUPPORTEE')
    montant = _montant(ligne['prix_unitaire_decimal'])
    if montant is None:
        erreurs.append('MONTANT_INVALIDE')
    effet = _jour(ligne['date_effet'])
    if effet is None:
        erreurs.append('DATE_INVALIDE')
    elif effet > jour:
        erreurs.append('DATE_FUTURE')
    candidat = None
    if not erreurs:
        # Réutiliser la validation du livre sur une liste locale, jamais le registre de l’instance.
        _, refus = livre_prix.enregistrer_prix(materiau, fournisseur_id, float(montant), 'CAD',
            ligne['date_effet'], [], source_document=document, unite=ligne['unite'])
        if refus is not None:
            erreurs.append('ENTREE_PRIX_REFUSEE')
        else:
            candidat = dict(materiau_id=materiau, fournisseur_id=fournisseur_id,
                            prix_unitaire_decimal=montant, unite=ligne['unite'], devise='CAD',
                            date_effet=ligne['date_effet'], source_document=document)
    return dict(position=position, numero_ligne=numero if _numero(numero) else None,
                statut='A_CORRIGER' if erreurs else 'PRET_POUR_REVUE', erreurs=erreurs, candidat=candidat)


def preparer(lignes, *, fournisseur_id, source_document, source_octets, jour_reference, limite_sortie=65536):
    jour = _jour(jour_reference)
    if (not _texte(fournisseur_id, 200) or jour is None
            or type(limite_sortie) is not int or limite_sortie < 1):
        raise Refus('ARGUMENTS')
    if not _texte(source_document, 1000) or type(source_octets) is not bytes or not source_octets:
        raise Refus('SOURCE_INVALIDE')
    if len(source_octets) > MAX_SOURCE:
        raise Refus('SOURCE_TROP_VOLUMINEUSE')
    lignes, mapping = _mapping(lignes)
    source = hashlib.sha256(source_octets).hexdigest()
    identite = dict(version=VERSION, fournisseur_id=fournisseur_id, source_document=source_document,
                    source_sha256=source, mapping_sha256=mapping, jour_reference=jour_reference)
    numeros = Counter(entree['numero_ligne'] for entree in lignes if _numero(entree['numero_ligne']))
    materiaux = Counter(entree['materiau_id'] for entree in lignes
                        if catalogue_materiaux._identite(entree['materiau_id']))
    resultat = [_ligne(entree, i + 1, fournisseur_id, source_document, jour, numeros, materiaux)
                for i, entree in enumerate(lignes)]
    prets = sum(entree['statut'] == 'PRET_POUR_REVUE' for entree in resultat)
    vue = dict(**identite, lot_sha256=_sha(identite), statut='A_REVOIR' if prets == len(lignes) else 'A_CORRIGER',
               total_lignes=len(lignes), candidats_prets=prets, lignes_a_corriger=len(lignes) - prets,
               lignes=resultat, avertissements=list(_AVERTISSEMENTS))
    if len(_encoder(vue)) > min(MAX_SORTIE, limite_sortie):
        raise Refus('SORTIE_TROP_VOLUMINEUSE')
    return vue
