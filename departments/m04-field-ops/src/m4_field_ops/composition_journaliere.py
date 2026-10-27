"""CRM-16 : composition journalière déclarée, sans présence ni autorité d'accès déduite.

Fondation pure : auteur est une charge à contrôler par le futur adaptateur SQL/admin.
Aucun profil courant, identité, appareil, horloge, paie ou réseau n'est lu ici.
"""
import json
from copy import deepcopy
from datetime import datetime

from . import annotations_calendrier as validations
from . import calendrier_civil as calendrier
from . import encodage
from .registre import Registre, VerificationError

REGISTRE = 'compositions_journalieres'
TYPE = 'composition_journaliere'
MAX_SOURCES = 10000
MAX_OCTETS = 8 * 1024 * 1024
MAX_MEMBRES = 50
BORNE_SORTIE = 65536
Refus = validations.Refus


def _identifiant(v):
    # Forme de transport minimale seulement; l'adaptateur devra résoudre les identités canoniques.
    if not validations._texte(v, 64) or v != v.strip():
        raise Refus('IDENTIFIANT-INVALIDE')
    return v


def _jour(v):
    try:
        return calendrier._date(v).isoformat()
    except (ValueError, TypeError):
        raise Refus('JOUR-INVALIDE') from None


def _arguments(jour, equipe_id, membres, revision_attendue, statut_declaration):
    if not validations._entier(revision_attendue, MAX_SOURCES):
        raise Refus('REVISION-INVALIDE')
    if type(statut_declaration) is not str or statut_declaration not in {'declaree', 'retiree'}:
        raise Refus('STATUT-INVALIDE')
    if statut_declaration == 'retiree':
        if membres is not None:
            raise Refus('MEMBRES-INVALIDES')
        propres = None
    else:
        if type(membres) is not list or len(membres) > MAX_MEMBRES:
            raise Refus('MEMBRES-INVALIDES')
        propres = [_identifiant(v) for v in membres]
        if len(set(propres)) != len(propres):
            raise Refus('MEMBRES-DOUBLES')
        propres.sort()
    return dict(jour=_jour(jour), equipe_id=_identifiant(equipe_id), membres=propres,
                revision_attendue=revision_attendue, statut_declaration=statut_declaration)


def _cle(m):
    return m['jour'], m['equipe_id']


def _octets(objet):
    return len(json.dumps(objet, ensure_ascii=False).encode('utf-8'))


def _borne(reponse, limite):
    if type(limite) is not int or limite < 1:
        raise Refus('SORTIE-TROP-VOLUMINEUSE')
    if any(_octets({'ok': True, 'resultat': reponse, 'rejoue': r}) > min(limite, BORNE_SORTIE)
           for r in (False, True)):
        raise Refus('SORTIE-TROP-VOLUMINEUSE')


def _succession(m, precedente):
    if (m['revision'] != (precedente['revision'] + 1 if precedente else 1)
            or m['revision_precedente'] != (precedente['ligne_id'] if precedente else None)):
        raise Refus('REVISION-INCOHERENTE')
    if m['statut_declaration'] == 'retiree' and (precedente is None or precedente['statut_declaration'] == 'retiree'):
        raise Refus('RETRAIT-SANS-DECLARATION')
    if precedente and datetime.fromisoformat(m['horodatage']) < datetime.fromisoformat(precedente['horodatage']):
        raise Refus('HORODATAGE-ANTERIEUR')


def _charger(reg):
    if reg.taille() > MAX_SOURCES:
        raise Refus('SOURCES-TROP-VOLUMINEUSES')
    maillons = reg.lire()
    if len(maillons) > MAX_SOURCES or _octets(maillons) > MAX_OCTETS:
        raise Refus('SOURCES-TROP-VOLUMINEUSES')
    try:
        copie = Registre(maillons)
        copie.assert_chaine()
        precedentes, mutations = {}, {}
        cles = {'type_entree', 'jour', 'equipe_id', 'membres', 'statut_declaration', 'revision',
                'revision_precedente', 'auteur', 'mutation', 'horodatage', 'ligne_id', 'precedent_ligne_id'}
        for m in maillons:
            if type(m) is not dict or set(m) != cles or m['type_entree'] != TYPE:
                raise Refus('REGISTRE-INVALIDE')
            if type(m['revision']) is not int or not 1 <= m['revision'] <= MAX_SOURCES:
                raise Refus('REVISION-INVALIDE')
            args = _arguments(m['jour'], m['equipe_id'], m['membres'], m['revision'] - 1, m['statut_declaration'])
            if args['membres'] != m['membres']:
                raise Refus('MEMBRES-NON-CANONIQUES')
            validations._auteur(m['auteur'])
            validations._instant(m['horodatage'])
            validations._mutation(m['mutation'], args)
            _succession(m, precedentes.get(_cle(m)))
            intention = m['mutation']['appareil'], m['mutation']['cle']
            if intention in mutations:
                raise Refus('MUTATION-DOUBLE')
            mutations[intention] = m
            precedentes[_cle(m)] = m
        return copie, maillons, precedentes, mutations
    except (VerificationError, ValueError, TypeError, KeyError, UnicodeError):
        raise Refus('REGISTRE-INVALIDE') from None


def _accuse(m, rejoue=False):
    return {'accepte': True, 'rejoue': rejoue, 'resultat': {
        'declaration_id': m['ligne_id'], 'jour': m['jour'], 'equipe_id': m['equipe_id'],
        'revision': m['revision'], 'statut_declaration': m['statut_declaration'], 'horodatage': m['horodatage']}}


def declarer(reg, *, jour, equipe_id, membres, revision_attendue, statut_declaration, auteur, mutation, horodatage,
             limite_sortie=BORNE_SORTIE):
    args = _arguments(jour, equipe_id, membres, revision_attendue, statut_declaration)
    validations._auteur(auteur)
    validations._mutation(mutation, args)
    validations._instant(horodatage)
    copie, maillons, precedentes, mutations = _charger(reg)
    ancien = mutations.get((mutation['appareil'], mutation['cle']))
    if ancien is not None:
        if ancien['mutation'] != mutation or ancien['auteur'] != auteur:
            raise Refus('MUTATION-CONFLIT')
        reponse = _accuse(ancien, rejoue=True)
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


def lire(reg, jour, equipe_id, *, debut=0, limite=50, source_attendue=None, limite_sortie=BORNE_SORTIE):
    jour, equipe_id = _jour(jour), _identifiant(equipe_id)
    if (type(debut) is not int or debut < 0 or type(limite) is not int or not 1 <= limite <= 100):
        raise Refus('PAGINATION-INVALIDE')
    copie, maillons, precedentes, _ = _charger(reg)
    source = encodage.empreinte('composition_journaliere_v1', copie.tete(), jour, equipe_id)
    if (debut and source_attendue is None) or (source_attendue is not None and source_attendue != source):
        raise Refus('SOURCE-PERIMEE')
    lignes = [m for m in maillons if _cle(m) == (jour, equipe_id)]
    if debut > len(lignes):
        raise Refus('PAGINATION-HORS-HISTORIQUE')
    derniere = precedentes.get((jour, equipe_id))
    connue = derniere is not None and derniere['statut_declaration'] == 'declaree'
    fin = min(debut + limite, len(lignes))
    reponse = {'jour': jour, 'equipe_id': equipe_id, 'source': source, 'composition_connue': connue,
        'membres': deepcopy(derniere['membres']) if connue else None,
        'revision': derniere['revision'] if derniere else 0, 'total': len(lignes), 'debut': debut,
        'suivant': fin if fin < len(lignes) else None, 'lignes': [
            {'source_ligne_id': m['ligne_id'], 'jour': m['jour'], 'equipe_id': m['equipe_id'],
             'membres': deepcopy(m['membres']), 'statut_declaration': m['statut_declaration'],
             'revision': m['revision'], 'revision_precedente': m['revision_precedente'],
             'auteur': deepcopy(m['auteur']), 'horodatage': m['horodatage'],
             'courante': m['ligne_id'] == derniere['ligne_id']} for m in lignes[debut:fin]],
        'avertissements': ['Composition déclarée pour ce jour; aucune présence terrain ni autorité actuelle prouvée.',
            'L’horodatage indique l’enregistrement, qui peut être postérieur au jour déclaré.']}
    _borne(reponse, limite_sortie)
    return reponse
