"""Adaptateur SQLite transactionnel privé des prévisions explicitement ancrées."""
import json

from sqlalchemy import LargeBinary, cast, func, select

from opsys import stockage
from opsys.etat import journaliser
from opsys.stockage.maillons import copier_maillons_avec_metadonnees
from opsys.stockage.schema import REGISTRES

from . import journal_durable
from . import visites_durables as domaine
from .registre import Registre

DEPARTEMENT = 'm04-field-ops'


def capturer_visites(cnx):
    if cnx is None or cnx is not stockage.connexion_courante() or cnx.dialect.name != 'sqlite':
        raise domaine.Refus('INSTANCE-NON-QUALIFIEE')
    condition = (REGISTRES.c.departement == DEPARTEMENT) & (REGISTRES.c.registre == domaine.REGISTRE)
    nombre, octets = cnx.execute(select(func.count(), func.sum(func.length(cast(REGISTRES.c.maillon, LargeBinary))))
                                .select_from(REGISTRES).where(condition)).one()
    if nombre > domaine.MAX_SOURCES or (octets or 0) > domaine.MAX_OCTETS:
        raise domaine.Refus('SOURCES-TROP-VOLUMINEUSES')
    return copier_maillons_avec_metadonnees(cnx, departement=DEPARTEMENT, registre=domaine.REGISTRE)


def _autorite(autoriser, auteur):
    if autoriser() != auteur:
        raise domaine.Refus('IDENTITE')


def enregistrer(cnx, arguments, auteur, mutation, horodatage, autoriser, limite_sortie=65536):
    """Appel depuis une transaction SQLite ; l'autorité est réévaluée après append."""
    principal = journal_durable.capturer(cnx)
    source = capturer_visites(cnx)
    copie_principal = Registre([r.maillon for r in principal.lignes])
    copie = Registre([r.maillon for r in source.lignes])
    from . import annotations_calendrier as notes
    notes._mutation(mutation, arguments)
    intention = mutation['appareil'], mutation['cle']
    if any(isinstance(r.maillon.get('mutation'), dict)
           and (r.maillon['mutation'].get('appareil'), r.maillon['mutation'].get('cle')) == intention
           for r in principal.lignes):
        raise domaine.Refus('MUTATION-CONFLIT')
    attendu = domaine.prevoir(copie_principal, copie, **arguments, auteur=auteur,
                               mutation=mutation, horodatage=horodatage)
    if type(limite_sortie) is not int or limite_sortie <= 0 or len(
            json.dumps({'ok': True, 'resultat': attendu}, ensure_ascii=False).encode()) > min(limite_sortie, 65536):
        raise domaine.Refus('SORTIE-TROP-VOLUMINEUSE')
    if attendu['rejoue']:
        _autorite(autoriser, auteur)
        if (journal_durable.capturer(cnx).empreinte_snapshot_calculee != principal.empreinte_snapshot_calculee
                or capturer_visites(cnx).empreinte_snapshot_calculee != source.empreinte_snapshot_calculee):
            raise domaine.Refus('SOURCE-MODIFIEE')
        return attendu
    prepare = copie.lire()[-1]
    with cnx.begin_nested():
        _autorite(autoriser, auteur)
        if (journal_durable.capturer(cnx).empreinte_snapshot_calculee != principal.empreinte_snapshot_calculee
                or capturer_visites(cnx).empreinte_snapshot_calculee != source.empreinte_snapshot_calculee):
            raise domaine.Refus('SOURCE-MODIFIEE')
        resultat = domaine.prevoir(Registre(stockage.maillons(DEPARTEMENT, 'principal')),
                                   Registre(stockage.maillons(DEPARTEMENT, domaine.REGISTRE)),
                                   **arguments, auteur=auteur, mutation=mutation, horodatage=horodatage)
        if resultat != attendu:
            raise domaine.Refus('SOURCE-MODIFIEE')
        journaliser(cnx, auteur['personne'], 'm4.visite_prevue', resultat['visite_id'],
                    {'intervention_id': arguments['ancre']['intervention_id'],
                     'revision': resultat['revision'], 'empreinte_arguments': mutation['empreinte_arguments']})
        apres = capturer_visites(cnx)
        if (len(apres.lignes) != len(source.lignes) + 1 or apres.lignes[:-1] != source.lignes
                or apres.lignes[-1].maillon != prepare
                or journal_durable.capturer(cnx).empreinte_snapshot_calculee != principal.empreinte_snapshot_calculee):
            raise domaine.Refus('SOURCE-MODIFIEE')
        _autorite(autoriser, auteur)
        return resultat


def empreinte_sources(cnx):
    from . import encodage
    principal = journal_durable.capturer(cnx)
    visites = capturer_visites(cnx)
    return encodage.empreinte('visites_sql_v1', principal.empreinte_snapshot_calculee,
                              visites.empreinte_snapshot_calculee)


def executer_evenement(cnx, arguments, auteur, mutation, horodatage, autoriser, limite_sortie=65536):
    """Ouverture ou fermeture sur deux snapshots, audit et savepoint SQLite."""
    from . import annotations_calendrier as notes
    from . import visites_chantier

    if (type(arguments) is not dict or set(arguments) != {'operation', 'visite_id', 'source_attendue'}
            or arguments['operation'] not in ('ouvrir', 'fermer')):
        raise domaine.Refus('ARGUMENTS')
    notes._auteur(auteur)
    notes._mutation(mutation, arguments)
    notes._instant(horodatage)
    principal = journal_durable.capturer(cnx)
    source = capturer_visites(cnx)
    source_actuelle = empreinte_sources(cnx)
    copie_principal = Registre([r.maillon for r in principal.lignes])
    copie_visites = Registre([r.maillon for r in source.lignes])
    domaine._charger(copie_principal, copie_visites)
    intention = (mutation['appareil'], mutation['cle'])
    toutes = [r.maillon for r in principal.lignes] + [r.maillon for r in source.lignes]
    anciennes = [m for m in toutes if isinstance(m.get('mutation'), dict)
                 and (m['mutation'].get('appareil'), m['mutation'].get('cle')) == intention]
    if anciennes:
        if len(anciennes) != 1 or anciennes[0].get('mutation') != mutation or anciennes[0].get('auteur') != auteur:
            raise domaine.Refus('MUTATION-CONFLIT')
        ancien = anciennes[0]
        attendu_type = 'visite_ouverte' if arguments['operation'] == 'ouvrir' else 'visite_fermee'
        if ancien.get('type_entree') != attendu_type or ancien.get('visite_id') != arguments['visite_id']:
            raise domaine.Refus('MUTATION-CONFLIT')
        try:
            visites_chantier._provenance({'auteur': ancien['auteur'], 'mutation': ancien['mutation'],
                                          'source_attendue': ancien['source_attendue']},
                                         arguments['operation'], arguments['visite_id'])
        except (KeyError, ValueError) as exc:
            raise domaine.Refus('SOURCE-INVALIDE') from exc
        if ancien['source_attendue'] != arguments['source_attendue']:
            raise domaine.Refus('MUTATION-CONFLIT')
        _autorite(autoriser, auteur)
        if empreinte_sources(cnx) != source_actuelle:
            raise domaine.Refus('SOURCE-MODIFIEE')
        cle = 'ouverture_id' if arguments['operation'] == 'ouvrir' else 'fermeture_id'
        reponse = {'rejoue': True, 'resultat': {'visite_id': ancien['visite_id'], cle: ancien['ligne_id']}}
        _verifier_sortie(reponse, limite_sortie)
        return reponse
    if arguments['source_attendue'] != source_actuelle:
        raise domaine.Refus('SOURCE-PERIMEE')
    provenance = {'auteur': auteur, 'mutation': mutation, 'source_attendue': source_actuelle}
    operation = visites_chantier.ouvrir if arguments['operation'] == 'ouvrir' else visites_chantier.fermer
    try:
        attendu = operation(copie_principal, copie_visites, arguments['visite_id'], horodatage, provenance=provenance)
    except ValueError as exc:
        raise domaine.Refus('EVENEMENT-INVALIDE') from exc
    reponse = {'rejoue': False, 'resultat': attendu}
    _verifier_sortie(reponse, limite_sortie)
    prepare = copie_principal.lire()[-1]
    with cnx.begin_nested():
        _autorite(autoriser, auteur)
        if empreinte_sources(cnx) != source_actuelle:
            raise domaine.Refus('SOURCE-MODIFIEE')
        try:
            resultat = operation(Registre(stockage.maillons(DEPARTEMENT, 'principal')),
                                 Registre(stockage.maillons(DEPARTEMENT, domaine.REGISTRE)),
                                 arguments['visite_id'], horodatage, provenance=provenance)
        except ValueError as exc:
            raise domaine.Refus('EVENEMENT-INVALIDE') from exc
        if resultat != attendu:
            raise domaine.Refus('SOURCE-MODIFIEE')
        ident = resultat['ouverture_id' if arguments['operation'] == 'ouvrir' else 'fermeture_id']
        journaliser(cnx, auteur['personne'], 'm4.visite_' + arguments['operation'], ident,
                    {'visite_id': arguments['visite_id'], 'empreinte_arguments': mutation['empreinte_arguments']})
        apres = journal_durable.capturer(cnx)
        if (len(apres.lignes) != len(principal.lignes) + 1 or apres.lignes[:-1] != principal.lignes
                or apres.lignes[-1].maillon != prepare
                or capturer_visites(cnx).empreinte_snapshot_calculee != source.empreinte_snapshot_calculee):
            raise domaine.Refus('SOURCE-MODIFIEE')
        _autorite(autoriser, auteur)
        return reponse


def _verifier_sortie(reponse, limite_sortie):
    if (type(limite_sortie) is not int or limite_sortie <= 0
            or len(json.dumps({'ok': True, 'resultat': reponse}, ensure_ascii=False).encode())
            > min(limite_sortie, 65536)):
        raise domaine.Refus('SORTIE-TROP-VOLUMINEUSE')
