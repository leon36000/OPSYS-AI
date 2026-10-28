"""Écriture humaine privée de la composition déclarée, sans changement d'accès ou de profil."""
from opsys import equipes as equipes_entreprise
from opsys import identite, stockage
from opsys.etat import journaliser

from . import composition_durable as durable
from . import composition_journaliere as domaine
from .registre import Registre


def _profil():
    chemin = equipes_entreprise.fichier_profil()
    if not chemin.is_file() or chemin.stat().st_size > domaine.MAX_OCTETS:
        raise domaine.Refus('IDENTITES-NON-CONFIRMEES')
    profil, verdict = equipes_entreprise.charger_equipes()
    if verdict is not None or profil is None:
        raise domaine.Refus('IDENTITES-NON-CONFIRMEES')
    return profil, equipes_entreprise.empreinte_equipes(profil)


def _identites(cnx, arguments, deja_historisee):
    if arguments['statut_declaration'] == 'retiree':
        return None
    if not identite.identifiant_valide(arguments['equipe_id']):
        raise domaine.Refus('IDENTITES-NON-CONFIRMEES')
    empreinte = None
    if not deja_historisee:
        profil, empreinte = _profil()
        if arguments['equipe_id'] not in {e['id'] for e in profil.get('liste', [])}:
            raise domaine.Refus('IDENTITES-NON-CONFIRMEES')
    for membre in arguments['membres']:
        # Une identité historique désactivée reste déclarable, sans réactivation ni droit conféré.
        if not identite.identifiant_valide(membre) or identite.personne(cnx, membre) is None:
            raise domaine.Refus('IDENTITES-NON-CONFIRMEES')
    return empreinte


def _autorite(autoriser, auteur):
    if autoriser() != auteur:
        raise domaine.Refus('IDENTITE')


def enregistrer(cnx, arguments, auteur, mutation, horodatage, autoriser, limite_sortie=65536):
    source = durable.capturer(cnx)
    copie = Registre([r.maillon for r in source.lignes])
    prepares = domaine._arguments(**arguments)
    # Valide aussi CAS, rejeu, maillons et enveloppe avant le moindre append durable.
    attendu = domaine.declarer(copie, **prepares, auteur=auteur, mutation=mutation,
                               horodatage=horodatage, limite_sortie=limite_sortie)
    if attendu['rejoue']:
        if durable.capturer(cnx).empreinte_snapshot_calculee != source.empreinte_snapshot_calculee:
            raise domaine.Refus('SOURCE-MODIFIEE')
        _autorite(autoriser, auteur)
        return attendu
    maillon_prepare = copie.lire()[-1]
    connue = any((r.maillon['jour'], r.maillon['equipe_id']) == (prepares['jour'], prepares['equipe_id'])
                 for r in source.lignes)
    empreinte_profil = _identites(cnx, prepares, connue)
    # Les exceptions doivent sortir du savepoint avant d'être transformées en refus technique.
    with cnx.begin_nested():
        if empreinte_profil is not None and _profil()[1] != empreinte_profil:
            raise domaine.Refus('SOURCE-MODIFIEE')
        _autorite(autoriser, auteur)
        if durable.capturer(cnx).empreinte_snapshot_calculee != source.empreinte_snapshot_calculee:
            raise domaine.Refus('SOURCE-MODIFIEE')
        resultat = domaine.declarer(Registre(stockage.maillons(durable.DEPARTEMENT, domaine.REGISTRE)),
            **prepares, auteur=auteur, mutation=mutation, horodatage=horodatage, limite_sortie=limite_sortie)
        if resultat != attendu:
            raise domaine.Refus('SOURCE-MODIFIEE')
        r = resultat['resultat']
        journaliser(cnx, auteur['personne'], 'm4.composition_journaliere', r['declaration_id'],
            {'jour': r['jour'], 'equipe_id': r['equipe_id'], 'revision': r['revision'],
             'statut_declaration': r['statut_declaration'], 'empreinte_arguments': mutation['empreinte_arguments'],
             'nombre_membres': len(prepares['membres']) if prepares['membres'] is not None else None,
             'source_equipe': empreinte_profil if empreinte_profil is not None else 'historique'})
        apres = durable.capturer(cnx)
        if (len(apres.lignes) != len(source.lignes) + 1 or apres.lignes[:-1] != source.lignes
                or apres.lignes[-1].maillon != maillon_prepare):
            raise domaine.Refus('SOURCE-MODIFIEE')
        if empreinte_profil is not None and _profil()[1] != empreinte_profil:
            raise domaine.Refus('SOURCE-MODIFIEE')
        _autorite(autoriser, auteur)
        return resultat
