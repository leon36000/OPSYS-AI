"""Prévisions de visite ancrées : registre append-only privé, sans pointage inféré.

Ces fonctions pures exigent un adaptateur transactionnel et une autorité vérifiée.
"""
import json
from copy import deepcopy
from datetime import datetime

from . import annotations_calendrier as notes
from . import encodage
from .registre import Registre, VerificationError

TYPE = 'visite_prevue'
REGISTRE = 'visites_chantier'
MAX_SOURCES = 10000
MAX_OCTETS = 8 * 1024 * 1024
Refus = notes.Refus


def _charger(principal, visites):
    if principal is visites or visites.taille() > MAX_SOURCES:
        raise Refus('REGISTRE-INVALIDE')
    sources = notes._sources(principal)
    lignes = visites.lire()
    if len(lignes) > MAX_SOURCES or len(json.dumps(lignes, ensure_ascii=False).encode()) > MAX_OCTETS:
        raise Refus('SOURCES-TROP-VOLUMINEUSES')
    try:
        copie = Registre(lignes)
        copie.assert_chaine()
        precedentes, ancres, mutations = {}, set(), {}
        champs = {'type_entree', 'ancre', 'creneau', 'revision', 'revision_precedente',
                  'auteur', 'mutation', 'horodatage', 'ligne_id', 'precedent_ligne_id'}
        for m in lignes:
            if type(m) is not dict or set(m) != champs or m['type_entree'] != TYPE:
                raise Refus('REGISTRE-INVALIDE')
            ancre = m['ancre']
            notes._ancre(ancre)
            revision = m['revision']
            if type(revision) is not int or not 1 <= revision <= MAX_SOURCES:
                raise Refus('REVISION-INVALIDE')
            args = {'ancre': ancre, 'revision_attendue': revision - 1}
            notes._auteur(m['auteur'])
            notes._mutation(m['mutation'], args)
            notes._instant(m['horodatage'])
            iid = ancre['intervention_id']
            precedente = precedentes.get(iid)
            if (revision != (precedente['revision'] + 1 if precedente else 1)
                    or m['revision_precedente'] != (precedente['ligne_id'] if precedente else None)
                    or (precedente and datetime.fromisoformat(m['horodatage']) <
                        datetime.fromisoformat(precedente['horodatage']))):
                raise Refus('REVISION-INCOHERENTE')
            cle = notes._cle(ancre)
            if cle in ancres or m['creneau'] != notes._creneau(sources, ancre):
                raise Refus('ANCRE-INCOHERENTE')
            source_datee = sources[0][ancre['source_ligne_id']][1]
            notes._instant(source_datee['horodatage'])
            if datetime.fromisoformat(m['horodatage']) < datetime.fromisoformat(source_datee['horodatage']):
                raise Refus('HORODATAGE-ANTERIEUR')
            intention = m['mutation']['appareil'], m['mutation']['cle']
            if intention in mutations:
                raise Refus('MUTATION-DOUBLE')
            ancres.add(cle)
            mutations[intention] = m
            precedentes[iid] = m
        return copie, lignes, sources, precedentes, ancres, mutations
    except (VerificationError, KeyError, TypeError, ValueError, UnicodeError):
        raise Refus('REGISTRE-INVALIDE') from None


def prevoir(principal, visites, ancre, revision_attendue, auteur, mutation, horodatage):
    notes._ancre(ancre)
    if not notes._entier(revision_attendue):
        raise Refus('REVISION-INVALIDE')
    args = {'ancre': deepcopy(ancre), 'revision_attendue': revision_attendue}
    notes._auteur(auteur)
    notes._mutation(mutation, args)
    notes._instant(horodatage)
    tete_principal = principal.tete()
    copie, lignes, sources, precedentes, ancres, mutations = _charger(principal, visites)
    intention = mutation['appareil'], mutation['cle']
    ancien = mutations.get(intention)
    if ancien:
        if ancien['mutation'] != mutation or ancien['auteur'] != auteur:
            raise Refus('MUTATION-CONFLIT')
        return {'visite_id': ancien['ligne_id'], 'revision': ancien['revision'], 'rejoue': True}
    precedente = precedentes.get(ancre['intervention_id'])
    if revision_attendue != (precedente['revision'] if precedente else 0):
        raise Refus('REVISION-PERIMEE')
    cle = notes._cle(ancre)
    if cle in ancres or cle not in sources[1] or sources[1][cle]['validite'] != 'date_confirmee':
        raise Refus('SOURCE-REMPLACEE')
    creneau = notes._creneau(sources, ancre)
    source_datee = sources[0][ancre['source_ligne_id']][1]
    notes._instant(source_datee['horodatage'])
    if datetime.fromisoformat(horodatage) < datetime.fromisoformat(source_datee['horodatage']):
        raise Refus('HORODATAGE-ANTERIEUR')
    if precedente and datetime.fromisoformat(horodatage) < datetime.fromisoformat(precedente['horodatage']):
        raise Refus('HORODATAGE-ANTERIEUR')
    if len(lignes) >= MAX_SOURCES:
        raise Refus('SOURCES-TROP-VOLUMINEUSES')
    maillon = {'type_entree': TYPE, 'ancre': deepcopy(ancre), 'creneau': creneau,
               'revision': revision_attendue + 1,
               'revision_precedente': precedente['ligne_id'] if precedente else None,
               'auteur': deepcopy(auteur), 'mutation': deepcopy(mutation), 'horodatage': horodatage}
    if len(json.dumps(lignes + [maillon], ensure_ascii=False).encode()) > MAX_OCTETS:
        raise Refus('SOURCES-TROP-VOLUMINEUSES')
    if principal.tete() != tete_principal or visites.tete() != copie.tete():
        raise Refus('SOURCE-MODIFIEE')
    ligne_id = visites.ajouter(maillon)
    return {'visite_id': ligne_id, 'revision': maillon['revision'], 'rejoue': False}


def lire(principal, visites, intervention_id, *, debut=0, limite=50, source_attendue=None):
    if not notes._texte(intervention_id):
        raise Refus('INTERVENTION-INVALIDE')
    if type(debut) is not int or debut < 0 or type(limite) is not int or not 1 <= limite <= 100:
        raise Refus('PAGINATION-INVALIDE')
    tete_principal = principal.tete()
    copie, lignes, _, _, _, _ = _charger(principal, visites)
    source = encodage.empreinte('visites_prevues_v1', tete_principal, copie.tete(), intervention_id)
    if (debut and source_attendue is None) or (source_attendue is not None and source_attendue != source):
        raise Refus('SOURCE-PERIMEE')
    filtres = [m for m in lignes if m['ancre']['intervention_id'] == intervention_id]
    if debut > len(filtres):
        raise Refus('PAGINATION-INVALIDE')
    fin = min(debut + limite, len(filtres))
    resultat = {'source': source, 'debut': debut, 'suivant': fin if fin < len(filtres) else None,
                'total': len(filtres), 'visites': [
                    {'visite_id': m['ligne_id'], 'ancre': deepcopy(m['ancre']),
                     'creneau': deepcopy(m['creneau']), 'revision': m['revision']}
                    for m in filtres[debut:fin]]}
    if len(json.dumps(resultat, ensure_ascii=False).encode()) > 65536:
        raise Refus('SORTIE-TROP-VOLUMINEUSE')
    if principal.tete() != tete_principal or visites.tete() != copie.tete():
        raise Refus('SOURCE-MODIFIEE')
    return resultat
