"""Signalement administratif d'absence : domaine pur, aucune présence ou paie déduite.

Auteur et identifiants sont des charges de transport; seul un futur adaptateur SQL privé
pourra vérifier l'autorité, les comptes et l'heure serveur. Aucun outil ou écran n'est exposé ici.
"""
import json
from copy import deepcopy
from datetime import datetime

from . import annotations_calendrier as validations
from . import calendrier_civil, encodage
from .composition_journaliere import _identifiant
from .registre import Registre, VerificationError

REGISTRE = 'absences_journalieres_declarees'
TYPE = 'absence_journaliere_declaree'
MAX_SOURCES = 10000
MAX_OCTETS = 8 * 1024 * 1024
BORNE_SORTIE = 65536
Refus = validations.Refus


def _jour(jour):
    try:
        return calendrier_civil._date(jour).isoformat()
    except (ValueError, TypeError):
        raise Refus('JOUR-INVALIDE') from None


def _arguments(jour, personne_id, statut_declaration, revision_attendue):
    if type(statut_declaration) is not str or statut_declaration not in {'signalee', 'retiree'}:
        raise Refus('STATUT-INVALIDE')
    if not validations._entier(revision_attendue, MAX_SOURCES):
        raise Refus('REVISION-INVALIDE')
    return dict(jour=_jour(jour), personne_id=_identifiant(personne_id),
                statut_declaration=statut_declaration, revision_attendue=revision_attendue)


def _cle(m):
    return m['jour'], m['personne_id']


def _octets(objet):
    return len(json.dumps(objet, ensure_ascii=False).encode('utf-8'))


def _borne(reponse, limite):
    if type(limite) is not int or limite < 1 or any(
            _octets({'ok': True, 'resultat': reponse, 'rejoue': r}) > min(limite, BORNE_SORTIE)
            for r in (False, True)):
        raise Refus('SORTIE-TROP-VOLUMINEUSE')


def _succession(m, precedente):
    if (m['revision'] != (precedente['revision'] + 1 if precedente else 1)
            or m['revision_precedente'] != (precedente['ligne_id'] if precedente else None)):
        raise Refus('REVISION-INCOHERENTE')
    if m['statut_declaration'] == 'retiree' and (precedente is None or precedente['statut_declaration'] == 'retiree'):
        raise Refus('RETRAIT-SANS-SIGNALEMENT')
    if precedente and datetime.fromisoformat(m['horodatage']) < datetime.fromisoformat(precedente['horodatage']):
        raise Refus('HORODATAGE-ANTERIEUR')


def _charger(reg):
    if reg.taille() > MAX_SOURCES:
        raise Refus('SOURCES-TROP-VOLUMINEUSES')
    try:
        maillons = reg.lire()
        if len(maillons) > MAX_SOURCES or _octets(maillons) > MAX_OCTETS:
            raise Refus('SOURCES-TROP-VOLUMINEUSES')
        copie = Registre(maillons)
        copie.assert_chaine()
        precedentes, intentions = {}, {}
        cles = {'type_entree', 'jour', 'personne_id', 'statut_declaration', 'revision',
                'revision_precedente', 'auteur', 'mutation', 'horodatage', 'ligne_id', 'precedent_ligne_id'}
        for m in maillons:
            if type(m) is not dict or set(m) != cles or m['type_entree'] != TYPE:
                raise Refus('REGISTRE-INVALIDE')
            if type(m['revision']) is not int or not 1 <= m['revision'] <= MAX_SOURCES:
                raise Refus('REVISION-INVALIDE')
            args = _arguments(m['jour'], m['personne_id'], m['statut_declaration'], m['revision'] - 1)
            validations._auteur(m['auteur'])
            validations._mutation(m['mutation'], args)
            validations._instant(m['horodatage'])
            _succession(m, precedentes.get(_cle(m)))
            intention = m['mutation']['appareil'], m['mutation']['cle']
            if intention in intentions:
                raise Refus('MUTATION-DOUBLE')
            intentions[intention], precedentes[_cle(m)] = m, m
        return copie, maillons, precedentes, intentions
    except (VerificationError, ValueError, TypeError, KeyError, UnicodeError):
        raise Refus('REGISTRE-INVALIDE') from None


def _accuse(m, rejoue=False):
    return {'accepte': True, 'rejoue': rejoue, 'resultat': {
        'declaration_id': m['ligne_id'], 'jour': m['jour'], 'revision': m['revision'],
        'statut_declaration': m['statut_declaration'], 'horodatage': m['horodatage']}}


def declarer(reg, *, jour, personne_id, statut_declaration, revision_attendue, auteur, mutation, horodatage,
             limite_sortie=BORNE_SORTIE):
    args = _arguments(jour, personne_id, statut_declaration, revision_attendue)
    validations._auteur(auteur)
    validations._mutation(mutation, args)
    validations._instant(horodatage)
    copie, maillons, precedentes, intentions = _charger(reg)
    ancien = intentions.get((mutation['appareil'], mutation['cle']))
    if ancien is not None:
        if ancien['mutation'] != mutation or ancien['auteur'] != auteur:
            raise Refus('MUTATION-CONFLIT')
        reponse = _accuse(ancien, True)
        _borne(reponse, limite_sortie)
        return reponse
    precedente = precedentes.get(_cle(args))
    if revision_attendue != (precedente['revision'] if precedente else 0):
        raise Refus('REVISION-PERIMEE')
    if len(maillons) >= MAX_SOURCES:
        raise Refus('SOURCES-TROP-VOLUMINEUSES')
    m = {'type_entree': TYPE, **args, 'revision': revision_attendue + 1,
         'revision_precedente': precedente['ligne_id'] if precedente else None,
         'auteur': deepcopy(auteur), 'mutation': deepcopy(mutation), 'horodatage': horodatage}
    del m['revision_attendue']
    _succession(m, precedente)
    preview = {**m, 'ligne_id': encodage.empreinte(m, copie.tete()), 'precedent_ligne_id': copie.tete()}
    reponse = _accuse(preview)
    _borne(reponse, limite_sortie)
    if _octets(maillons + [preview]) > MAX_OCTETS:
        raise Refus('SOURCES-TROP-VOLUMINEUSES')
    if reg.tete() != copie.tete():
        raise Refus('SOURCE-MODIFIEE')
    reg.ajouter(m)
    return reponse


def lire(reg, jour, personne_id, *, debut=0, limite=50, source_attendue=None, limite_sortie=BORNE_SORTIE):
    jour, personne_id = _jour(jour), _identifiant(personne_id)
    if type(debut) is not int or debut < 0 or type(limite) is not int or not 1 <= limite <= 100:
        raise Refus('PAGINATION-INVALIDE')
    copie, maillons, precedentes, _ = _charger(reg)
    source = encodage.empreinte('absence_journaliere_declaree_v1', copie.tete(), jour, personne_id)
    if (debut and source_attendue is None) or (source_attendue is not None and source_attendue != source):
        raise Refus('SOURCE-PERIMEE')
    lignes = [m for m in maillons if _cle(m) == (jour, personne_id)]
    if debut > len(lignes):
        raise Refus('PAGINATION-HORS-HISTORIQUE')
    derniere = precedentes.get((jour, personne_id))
    fin = min(debut + limite, len(lignes))
    reponse = {'jour': jour, 'personne_id': personne_id, 'source': source,
        'etat_declaration': derniere['statut_declaration'] if derniere else 'aucun_signalement',
        'revision': derniere['revision'] if derniere else 0, 'total': len(lignes), 'debut': debut,
        'suivant': fin if fin < len(lignes) else None, 'lignes': [
            {'source_ligne_id': m['ligne_id'], 'jour': m['jour'], 'personne_id': m['personne_id'],
             'statut_declaration': m['statut_declaration'], 'revision': m['revision'],
             'revision_precedente': m['revision_precedente'], 'auteur': deepcopy(m['auteur']),
             'horodatage': m['horodatage'], 'courante': m['ligne_id'] == derniere['ligne_id']}
            for m in lignes[debut:fin]],
        'avertissements': ['Absence signalée par un administrateur; déclaration seulement.',
            'L’absence de signalement ou le retrait ne prouve aucune présence.',
            'Aucune présence, heure travaillée ou paie déduite.',
            'L’instant d’enregistrement peut être postérieur au jour déclaré.']}
    _borne(reponse, limite_sortie)
    return reponse
