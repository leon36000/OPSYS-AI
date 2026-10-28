"""Projection privée V2 de faits M4 vérifiés, sans calcul de présence ni de coût."""
import json
import re

from sqlalchemy import select

from opsys import contexte, stockage
from opsys.stockage.schema import OPSYS_INSTANCE

from . import (
    annotations_calendrier,
    composition_durable,
    composition_journaliere,
    encodage,
    etats,
    journal_durable,
    outbox,
    visites_chantier,
    visites_durables,
    visites_ecriture,
)
from .registre import Registre, VerificationError

VERSION = 'opsys.m4.temps_certifies.v2'
DOMAINE_EMPREINTE = 'm4.temps_certifies.v2'
DOMAINE_SOURCE = 'm4.temps_certifies.cas.v2'


class Refus(ValueError):
    """La projection ne doit pas présenter une source incomplète comme certifiée."""


def _autoriser(cnx):
    # Réutilise exactement la frontière existante : admin SQL actif, origine
    # console, source console et transport non MCP. Aucun rôle global ajouté.
    from .outils import _autoriser_annotation

    if cnx is not stockage.connexion_courante() or cnx is None or not cnx.in_transaction():
        raise Refus('INSTANCE-NON-QUALIFIEE')
    try:
        return _autoriser_annotation()
    except annotations_calendrier.Refus as exc:
        raise Refus('IDENTITE') from exc


def _sources(cnx):
    return (journal_durable.capturer(cnx), visites_ecriture.capturer_visites(cnx),
            composition_durable.capturer(cnx))


def _registre(snapshot):
    return Registre([ligne.maillon for ligne in snapshot.lignes])


def _source(snapshot):
    return {'tete': _registre(snapshot).tete(), 'empreinte_snapshot': snapshot.empreinte_snapshot_calculee}


def _cas(instance_id, wct_id, captures):
    return encodage.empreinte(DOMAINE_SOURCE, instance_id, wct_id,
                              *(x.empreinte_snapshot_calculee for x in captures))


def _revue_gps(maillons, fait):
    if fait['type_entree'] != 'pointage' or fait['action'] not in ('arrivee', 'depart'):
        return None
    if fait.get('gps_coherent') is True:
        return {'statut': 'coherent', 'demande_ligne_id': None, 'resolution_ligne_id': None}
    if not visites_chantier._anomalie_validee(maillons, fait):
        raise Refus('ANOMALIE-NON-VALIDEE')
    demande = next(m for m in maillons if m.get('type_entree') == 'demande_revue'
                   and m.get('type_demande') == 'anomalie_pointage'
                   and m.get('pointage_ligne_id') == fait['ligne_id'])
    resolution = next(m for m in maillons if m.get('type_entree') == 'resolution_revue'
                      and m.get('demande_id') == demande['demande_id'])
    return {'statut': 'validee', 'demande_ligne_id': demande['ligne_id'],
            'resolution_ligne_id': resolution['ligne_id']}


def _declaration(precedentes, jour, equipe):
    ligne = precedentes.get((jour, equipe))
    if ligne is None:
        return {'statut': 'inconnue', 'jour': jour, 'equipe_id': equipe, 'source_ligne_id': None,
                'revision': None, 'horodatage': None, 'membres': None}
    return {'statut': ligne['statut_declaration'], 'jour': jour, 'equipe_id': equipe,
            'source_ligne_id': ligne['ligne_id'], 'revision': ligne['revision'],
            'horodatage': ligne['horodatage'], 'membres': ligne['membres']}


def _projection(instance_id, intervention_id, wct_id, captures):
    principal, visites, compositions = map(_registre, captures)
    principal.assert_chaine()
    visites.assert_chaine()
    _, _, precedentes, _ = composition_journaliere._charger(compositions)
    valide, _ = outbox.verifier_invariants_outbox(principal)
    if not valide:
        raise Refus('WCT-INVALIDE')
    maillons = principal.lire()
    wcts = [m for m in maillons if m.get('intervention_id') == intervention_id and outbox.CLE_WCT in m]
    if len(wcts) != 1 or wcts[0][outbox.CLE_WCT].get('wct_id') != wct_id:
        raise Refus('WCT-ABSENT-OU-AMBIGU')
    maillon_wct, wct = wcts[0], wcts[0][outbox.CLE_WCT]
    depart = outbox._dernier_depart(principal, intervention_id)
    if (wct_id != encodage.empreinte('wct', intervention_id, maillon_wct['horodatage'])
            or wct['lead_id'] != outbox._extraire_lead_id(principal, intervention_id)
            or type(wct['duree_reelle_minutes']) is not int or wct['duree_reelle_minutes'] < 0
            or depart is None or (wct['technicien_id'], wct['horodatage_completion']) != depart[:2]):
        raise Refus('WCT-INVALIDE')
    certifie = visites_chantier.calculer_faits_certifies(principal, visites, intervention_id)
    if certifie['travail_minutes'] != wct['duree_reelle_minutes']:
        raise Refus('DUREE-INCOHERENTE')
    _, previsions, _, _, _, _ = visites_durables._charger(principal, visites)
    par_prevision = {m['ligne_id']: m for m in previsions}
    par_ligne = {m['ligne_id']: m for m in maillons}
    inconnus = [{'code': 'chantier_id_indisponible', 'visite_id': None}]
    sorties = []
    for calcul in certifie['visites']:
        visite_id = calcul['visite_id']
        prev = par_prevision[visite_id]
        ouvertures = [m for m in maillons if m.get('type_entree') == 'visite_ouverte'
                      and m.get('visite_id') == visite_id and m.get('intervention_id') == intervention_id]
        fermetures = [m for m in maillons if m.get('type_entree') == 'visite_fermee'
                      and m.get('visite_id') == visite_id and m.get('intervention_id') == intervention_id]
        if len(ouvertures) != 1 or len(fermetures) != 1:
            raise Refus('VISITE-AMBIGUE')
        if (visites_chantier._instant(fermetures[0]['horodatage'])
                > visites_chantier._instant(maillon_wct['horodatage'])):
            raise Refus('WCT-ANTERIEUR-A-VISITE')
        faits = [par_ligne[ident] for ident in calcul['sources']]
        routes = [m for m in faits if m.get('type_entree') == 'transition_statut' and m.get('statut') == 'en_route']
        if len(routes) != 1:
            raise Refus('ROUTE-AMBIGUE')
        technicien, equipe = routes[0]['technicien_id'], prev['creneau']['equipe_id']
        equipe_identifiee = technicien == equipe
        declaration = _declaration(precedentes, prev['creneau']['debut'][:10], equipe)
        inconnus.append({'code': 'presence_individuelle_non_observee', 'visite_id': visite_id})
        if declaration['statut'] != 'declaree':
            inconnus.append({'code': 'composition_indisponible', 'visite_id': visite_id})
        if not equipe_identifiee:
            inconnus.append({'code': 'equipe_pointee_indeterminee', 'visite_id': visite_id})
        evenements = []
        for fait in faits:
            typ = fait['statut'] if fait['type_entree'] == 'transition_statut' else fait['action']
            evenements.append({'type': typ, 'source_ligne_id': fait['ligne_id'],
                               'horodatage': fait['horodatage'], 'revue_gps': _revue_gps(maillons, fait)})
        sorties.append({'visite_id': visite_id, 'ancre': prev['ancre'], 'equipe_planifiee_id': equipe,
            'equipe_pointee': {'statut': 'identifiee' if equipe_identifiee else 'inconnue',
                               'identifiant': equipe if equipe_identifiee else None,
                               'justification': 'egalite_route_et_prevision' if equipe_identifiee else 'indeterminee'},
            'identifiant_pointe': technicien,
            'ouverture': {'source_ligne_id': ouvertures[0]['ligne_id'], 'horodatage': ouvertures[0]['horodatage']},
            'evenements': evenements,
            'fermeture': {'source_ligne_id': fermetures[0]['ligne_id'], 'horodatage': fermetures[0]['horodatage']},
            'composition_declaree': declaration, 'presence_individuelle': {'statut': 'inconnue'},
            'minutes': {'travail': calcul['travail_minutes'], 'pause': calcul['pause_minutes'],
                        'deplacement': calcul['deplacement_minutes']}})
    transitions = [m for m in maillons if m.get('intervention_id') == intervention_id
                   and m.get('type_entree') == etats.TYPE_TRANSITION and m.get('statut') in outbox.STATUTS_COMPLETION]
    if not transitions or transitions[-1]['statut'] != etats.statut_courant(principal, intervention_id):
        raise Refus('REVUE-INCOHERENTE')
    statut = transitions[-1]['statut']
    projection = {'version': VERSION, 'instance_id': instance_id, 'chantier_id': None,
        'intervention_id': intervention_id, 'lead_id': wct['lead_id'],
        'wct': {'wct_id': wct_id, 'source_ligne_id': maillon_wct['ligne_id'], 'hash_maillon': wct['hash_maillon'],
                'horodatage_transition': maillon_wct['horodatage'],
                'horodatage_completion': wct['horodatage_completion'],
                'statut': wct['statut'], 'duree_reelle_minutes': wct['duree_reelle_minutes']},
        'sources': dict(zip(('principal', 'visites', 'compositions'), map(_source, captures), strict=True)),
        'visites': sorties,
        'totaux': {'travail': certifie['travail_minutes'], 'pause': certifie['pause_minutes'],
                   'deplacement': certifie['deplacement_minutes']},
        'revue_chantier': {'statut': 'verifiee' if statut == 'completed_verified' else 'en_attente',
                           'source_ligne_id': transitions[-1]['ligne_id']},
        'inconnus': inconnus}
    projection['empreinte'] = encodage.empreinte(DOMAINE_EMPREINTE, projection)
    return projection


def projeter(cnx, intervention_id, wct_id, *, source_attendue=None):
    """Lit une projection bornée dans la transaction canonique et revalide l'admin courant."""
    auteur = _autoriser(cnx)
    if (not isinstance(intervention_id, str) or not intervention_id or len(intervention_id) > 256
            or not isinstance(wct_id, str) or re.fullmatch('[0-9a-f]{64}', wct_id) is None
            or (source_attendue is not None and (not isinstance(source_attendue, str)
                or re.fullmatch('[0-9a-f]{64}', source_attendue) is None))):
        raise Refus('ARGUMENTS')
    try:
        requete_instance = select(OPSYS_INSTANCE.c.instance_id).where(OPSYS_INSTANCE.c.id == 1)
        instance_id = cnx.execute(requete_instance).scalar_one_or_none()
        if not isinstance(instance_id, str) or not instance_id:
            raise Refus('INSTANCE-NON-QUALIFIEE')
        captures = _sources(cnx)
        source = _cas(instance_id, wct_id, captures)
        if source_attendue is not None and source_attendue != source:
            raise Refus('SOURCE-PERIMEE')
        projection = _projection(instance_id, intervention_id, wct_id, captures)
        resultat = {'source': source, 'projection': projection}
        borne = contexte.limite_sortie()
        if len(json.dumps(resultat, ensure_ascii=False, allow_nan=False).encode('utf-8')) > min(
                borne if borne is not None else 65536, 65536):
            raise Refus('SORTIE-TROP-VOLUMINEUSE')
        instance_finale = cnx.execute(requete_instance).scalar_one_or_none()
        if _autoriser(cnx) != auteur or _sources(cnx) != captures or instance_finale != instance_id:
            raise Refus('SOURCE-MODIFIEE')
        return resultat
    except Refus:
        raise
    except (annotations_calendrier.Refus, ValueError, KeyError, TypeError, StopIteration, VerificationError) as exc:
        raise Refus('SOURCE-INVALIDE') from exc
