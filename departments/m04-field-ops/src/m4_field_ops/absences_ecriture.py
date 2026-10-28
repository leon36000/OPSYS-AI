"""Signalement humain privé : identité initiale confirmée, aucune présence ou paie produite."""
from sqlalchemy import select

from opsys import identite, stockage
from opsys.etat import journaliser
from opsys.stockage.schema import PERSONNES, ROLES_PERSONNES

from . import absences_durables as durable
from . import absences_journalieres as domaine
from . import encodage
from .registre import Registre

ROLES_INTERNES = frozenset({'employee', 'seller', 'manager', 'finance', 'admin', 'nathan_owner'})


def _cible_initiale(cnx, personne_id):
    if not identite.identifiant_valide(personne_id):
        raise domaine.Refus('CIBLE-NON-CONFIRMEE')
    personne = cnx.execute(select(PERSONNES.c.identifiant, PERSONNES.c.actif)
                           .where(PERSONNES.c.identifiant == personne_id)).mappings().one_or_none()
    if personne is None:
        raise domaine.Refus('CIBLE-NON-CONFIRMEE')
    roles = frozenset(cnx.execute(select(ROLES_PERSONNES.c.role)
        .where(ROLES_PERSONNES.c.identifiant == personne_id).limit(len(identite.ROLES) + 1)).scalars())
    if not roles <= identite.ROLES or 'system_agent' in roles or not roles & ROLES_INTERNES:
        raise domaine.Refus('CIBLE-NON-CONFIRMEE')
    # Compte désactivé admis pour l'histoire; le nom et le hash secret ne sont pas sélectionnés.
    return dict(identifiant=personne['identifiant'], actif=bool(personne['actif']), roles=sorted(roles))


def _cible_inchangee(cnx, personne_id, attendue):
    try:
        courante = _cible_initiale(cnx, personne_id)
    except domaine.Refus:
        raise domaine.Refus('SOURCE-MODIFIEE') from None
    if courante != attendue:
        raise domaine.Refus('SOURCE-MODIFIEE')


def _autorite(autoriser, auteur):
    if autoriser() != auteur:
        raise domaine.Refus('IDENTITE')


def enregistrer(cnx, arguments, auteur, mutation, horodatage, autoriser, limite_sortie=65536):
    source = durable.capturer(cnx)
    copie = Registre([r.maillon for r in source.lignes])
    prepares = domaine._arguments(**arguments)
    attendu = domaine.declarer(copie, **prepares, auteur=auteur, mutation=mutation,
                               horodatage=horodatage, limite_sortie=limite_sortie)
    if attendu['rejoue']:
        if durable.capturer(cnx).empreinte_snapshot_calculee != source.empreinte_snapshot_calculee:
            raise domaine.Refus('SOURCE-MODIFIEE')
        _autorite(autoriser, auteur)
        return attendu
    maillon_prepare = copie.lire()[-1]
    connue = any((r.maillon['jour'], r.maillon['personne_id']) == (prepares['jour'], prepares['personne_id'])
                 for r in source.lignes)
    cible = None if connue else _cible_initiale(cnx, prepares['personne_id'])
    # Tout échec doit sortir de ce savepoint avant conversion en refus; pas de rejet après commit.
    with cnx.begin_nested():
        if cible is not None:
            _cible_inchangee(cnx, prepares['personne_id'], cible)
        _autorite(autoriser, auteur)
        if durable.capturer(cnx).empreinte_snapshot_calculee != source.empreinte_snapshot_calculee:
            raise domaine.Refus('SOURCE-MODIFIEE')
        resultat = domaine.declarer(Registre(stockage.maillons(durable.DEPARTEMENT, domaine.REGISTRE)),
            **prepares, auteur=auteur, mutation=mutation, horodatage=horodatage, limite_sortie=limite_sortie)
        if resultat != attendu:
            raise domaine.Refus('SOURCE-MODIFIEE')
        r = resultat['resultat']
        journaliser(cnx, auteur['personne'], 'm4.absence_journaliere', r['declaration_id'],
            {'jour': r['jour'], 'revision': r['revision'], 'statut_declaration': r['statut_declaration'],
             'empreinte_arguments': mutation['empreinte_arguments'], 'validation_cible_initiale': cible is not None,
             'empreinte_cible_initiale': encodage.empreinte(cible) if cible is not None else None})
        apres = durable.capturer(cnx)
        if (len(apres.lignes) != len(source.lignes) + 1 or apres.lignes[:-1] != source.lignes
                or apres.lignes[-1].maillon != maillon_prepare):
            raise domaine.Refus('SOURCE-MODIFIEE')
        if cible is not None:
            _cible_inchangee(cnx, prepares['personne_id'], cible)
        _autorite(autoriser, auteur)
        return resultat
