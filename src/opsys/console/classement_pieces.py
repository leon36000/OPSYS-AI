"""Classement administratif manuel, distinct de l’original et des classes d’accès M10."""
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import LargeBinary, cast, func, select

from .. import etat, idempotence
from ..stockage.schema import PIECES_CLASSEMENTS as CLASSEMENTS
from . import pieces_projet as pieces

CATEGORIES = {'non_classee': 'Non classée', 'plan': 'Plan', 'photo': 'Photo',
              'correspondance': 'Correspondance', 'devis_contrat': 'Devis / contrat',
              'materiaux': 'Matériaux', 'autre': 'Autre'}
MOTIFS = {'organisation_dossier': 'Organiser le dossier', 'correction_erreur': 'Corriger une erreur'}
MAX_REVISIONS = 32
MAX_LIGNES = 4096
MAX_OCTETS = 4194304
PAGE = 20
ZERO = '0' * 64
Refus = pieces.Refus
_LIMITES = dict(piece_id=32, lead_id=800, categorie=24, avant=24, motif=24, auteur=800,
                mutation_id=32, empreinte=64, source_sha256=64, horodatage=40, precedent=64, chaine=64)


def _arguments(lead, piece, categorie, revision, motif):
    if (type(lead) is not str or re.fullmatch(r'[\w.:@~\-]{1,200}', lead) is None
            or type(piece) is not str or re.fullmatch('[0-9a-f]{32}', piece) is None
            or type(categorie) is not str or categorie not in CATEGORIES
            or type(revision) is not int or not 0 <= revision <= MAX_REVISIONS
            or type(motif) is not str or motif not in MOTIFS):
        raise Refus('CLASSEMENT-ARGUMENTS')
    return dict(lead_id=lead, piece_id=piece, categorie=categorie, revision_attendue=revision, motif=motif)


def _borner(cnx):
    longueurs = [func.length(cast(CLASSEMENTS.c[n], LargeBinary)) for n in _LIMITES]
    mesures = cnx.execute(select(func.count(), func.sum(sum(longueurs)),
                                *[func.max(v) for v in longueurs]).select_from(CLASSEMENTS)).one()
    if (mesures[0] > MAX_LIGNES or (mesures[1] or 0) > MAX_OCTETS
            or any((taille or 0) > maximum for taille, maximum in
                   zip(mesures[2:], _LIMITES.values(), strict=True))):
        raise Refus('QUOTA-CLASSEMENTS')


def _hash(ligne):
    return idempotence.empreinte_arguments({k: v for k, v in ligne.items() if k != 'chaine'})


def _charger(cnx):
    _borner(cnx)
    lignes = [dict(r) for r in cnx.execute(select(CLASSEMENTS).order_by(
        CLASSEMENTS.c.piece_id, CLASSEMENTS.c.revision)).mappings()]
    parents = {r.piece_id: (r.lead_id, r.source_sha256) for r in cnx.execute(select(
        pieces.PIECES.c.piece_id, pieces.PIECES.c.lead_id, pieces.PIECES.c.source_sha256))}
    precedentes, mutations = {}, set()
    try:
        for ligne in lignes:
            args = _arguments(ligne['lead_id'], ligne['piece_id'], ligne['categorie'],
                              ligne['revision'] - 1, ligne['motif'])
            avant = precedentes.get(ligne['piece_id'])
            if (type(ligne['revision']) is not int or not 1 <= ligne['revision'] <= MAX_REVISIONS
                    or ligne['revision'] != (avant['revision'] + 1 if avant else 1)
                    or ligne['avant'] != (avant['categorie'] if avant else 'non_classee')
                    or ligne['avant'] == ligne['categorie']
                    or ligne['precedent'] != (avant['chaine'] if avant else ZERO)
                    or parents.get(ligne['piece_id']) != (ligne['lead_id'], ligne['source_sha256'])
                    or type(ligne['auteur']) is not str or not 1 <= len(ligne['auteur']) <= 200
                    or any(ord(c) < 32 for c in ligne['auteur'])
                    or re.fullmatch('[0-9a-f]{32}', ligne['mutation_id']) is None
                    or re.fullmatch('[0-9a-f]{64}', ligne['source_sha256']) is None
                    or idempotence.empreinte_arguments(args) != ligne['empreinte']
                    or _hash(ligne) != ligne['chaine']):
                raise Refus('CLASSEMENT-INCOHERENT')
            instant = datetime.fromisoformat(ligne['horodatage'])
            if instant.tzinfo is None or instant.utcoffset() != timedelta(0):
                raise Refus('CLASSEMENT-INCOHERENT')
            mutation = (ligne['auteur'], ligne['mutation_id'])
            if mutation in mutations:
                raise Refus('CLASSEMENT-INCOHERENT')
            mutations.add(mutation)
            precedentes[ligne['piece_id']] = ligne
    except (ValueError, TypeError, KeyError, ArithmeticError):
        raise Refus('CLASSEMENT-INCOHERENT') from None
    return lignes


def _debut(cnx, deps, session, lead, piece, cle):
    pieces.autorite._admin(cnx, session)
    meta, _ = pieces.lire(cnx, deps, session, lead, piece, cle=cle)
    return meta, pieces._ancre(cnx, deps, session, lead)


def _fermer(cnx, deps, session, lead, piece, cle, meta, ancre):
    pieces._fermer(cnx, deps, session, lead, ancre)
    if pieces.lire(cnx, deps, session, lead, piece, cle=cle)[0] != meta:
        raise Refus('SOURCE-MODIFIEE')
    pieces.autorite._admin(cnx, session)


def lire(cnx, deps, session, lead_id, piece_id, *, cle, decalage=0, revision_max=None):
    meta, ancre = _debut(cnx, deps, session, lead_id, piece_id, cle)
    if (type(decalage) is not int or not 0 <= decalage < MAX_REVISIONS or decalage % PAGE
            or (revision_max is not None and
                (type(revision_max) is not int or not 0 <= revision_max <= MAX_REVISIONS))):
        raise Refus('PAGINATION-INVALIDE')
    toutes = _charger(cnx)
    histoire = [r for r in toutes if r['piece_id'] == piece_id]
    courante = histoire[-1] if histoire else None
    revision = courante['revision'] if courante else 0
    plafond = revision if revision_max is None else revision_max
    if plafond > revision:
        raise Refus('REVISION-PERIMEE')
    selection = [r for r in histoire if r['revision'] <= plafond]
    if decalage and decalage >= len(selection):
        raise Refus('INTROUVABLE')
    resultat = dict(piece=meta, revision_courante=revision,
        categorie_courante=courante['categorie'] if courante else 'non_classee',
        revision_max=plafond, decalage=decalage, historique=selection[decalage:decalage + PAGE],
        suivant=decalage + PAGE if decalage + PAGE < len(selection) else None)
    _fermer(cnx, deps, session, lead_id, piece_id, cle, meta, ancre)
    if _charger(cnx) != toutes:
        raise Refus('SOURCE-MODIFIEE')
    pieces.autorite._admin(cnx, session)
    return pieces.lecture._sortie(resultat)


def classer(cnx, deps, session, lead_id, piece_id, *, cle, categorie, revision_attendue, mutation_id, motif):
    pieces.autorite._admin(cnx, session)
    args = _arguments(lead_id, piece_id, categorie, revision_attendue, motif)
    if type(mutation_id) is not str or re.fullmatch('[0-9a-f]{32}', mutation_id) is None:
        raise Refus('SAISIE-INVALIDE')
    empreinte = idempotence.empreinte_arguments(args)
    with cnx.begin_nested():
        meta, ancre = _debut(cnx, deps, session, lead_id, piece_id, cle)
        toutes = _charger(cnx)
        ancien = next((r for r in toutes if (r['auteur'], r['mutation_id']) ==
                       (session.utilisateur, mutation_id)), None)
        if ancien is not None:
            if ancien['empreinte'] != empreinte:
                raise Refus('SAISIE-CONFLIT')
            _fermer(cnx, deps, session, lead_id, piece_id, cle, meta, ancre)
            if _charger(cnx) != toutes:
                raise Refus('SOURCE-MODIFIEE')
            pieces.autorite._admin(cnx, session)
            return dict(recu=ancien, rejoue=True)
        histoire = [r for r in toutes if r['piece_id'] == piece_id]
        courante = histoire[-1] if histoire else None
        if revision_attendue != (courante['revision'] if courante else 0):
            raise Refus('REVISION-PERIMEE')
        avant = courante['categorie'] if courante else 'non_classee'
        if categorie == avant:
            raise Refus('CLASSEMENT-INCHANGE')
        if len(toutes) >= MAX_LIGNES or revision_attendue >= MAX_REVISIONS:
            raise Refus('QUOTA-CLASSEMENTS')
        ligne = dict(piece_id=piece_id, lead_id=lead_id, revision=revision_attendue + 1, categorie=categorie,
            avant=avant, motif=motif, auteur=session.utilisateur, mutation_id=mutation_id, empreinte=empreinte,
            source_sha256=meta['source_sha256'], horodatage=datetime.now(UTC).isoformat(),
            precedent=courante['chaine'] if courante else ZERO)
        ligne['chaine'] = _hash(ligne)
        cnx.execute(CLASSEMENTS.insert().values(**ligne))
        etat.journaliser(cnx, session.utilisateur, 'crm.piece_classee', piece_id,
                         dict(lead_id=lead_id, revision=ligne['revision'], avant=avant,
                              categorie=categorie, motif=motif, chaine=ligne['chaine']))
        _fermer(cnx, deps, session, lead_id, piece_id, cle, meta, ancre)
        attendues = sorted([*toutes, ligne], key=lambda r: (r['piece_id'], r['revision']))
        if _charger(cnx) != attendues:  # Source et quotas après écriture, avant libération du savepoint.
            raise Refus('SOURCE-MODIFIEE')
        pieces.autorite._admin(cnx, session)
        return dict(recu=ligne, rejoue=False)


def _sources_liste(cnx, lead_id):
    # Bornes avant toute sélection : les originaux restent dans SQL (seules leurs longueurs sont mesurées).
    pieces._borner(cnx)
    metas = [dict(r) for r in cnx.execute(select(*pieces._METADATA).where(
        pieces.PIECES.c.lead_id == lead_id).order_by(pieces.PIECES.c.recu_le, pieces.PIECES.c.piece_id)).mappings()]
    classements = [r for r in _charger(cnx) if r['lead_id'] == lead_id]
    return metas, classements


def lister_projet(cnx, deps, session, lead_id, *, cle, categorie=None, decalage=0, source_attendue=''):
    """Métadonnées authentifiées et filtre avant pagination; aucun original sélectionné ou déchiffré."""
    pieces.autorite._admin(cnx, session)
    pieces._cle(cle)
    if (categorie is not None and (type(categorie) is not str or categorie not in CATEGORIES)
            or type(decalage) is not int or not 0 <= decalage < pieces.MAX_PIECES or decalage % pieces.PAGE
            or type(source_attendue) is not str
            or (source_attendue and re.fullmatch('[0-9a-f]{64}', source_attendue) is None)
            or (decalage and not source_attendue)):
        raise Refus('PAGINATION-INVALIDE')
    ancre = pieces._ancre(cnx, deps, session, lead_id)
    metas, classements = _sources_liste(cnx, lead_id)
    if any(r['client_id'] != ancre['client_id'] for r in metas):
        raise Refus('SOURCE-INCOHERENTE')
    # Le titre porte l’AAD du manifeste original : authentifier les métadonnées du projet seulement.
    recus = [pieces._recu(r, cle) for r in metas]
    courants = {r['piece_id']: r for r in classements}
    enrichis = []
    for recu in recus:
        courant = courants.get(recu['piece_id'])
        if courant is not None and (courant['lead_id'], courant['source_sha256']) != (
                lead_id, recu['source_sha256']):
            raise Refus('CLASSEMENT-INCOHERENT')
        enrichis.append({**recu,
            'categorie_courante': courant['categorie'] if courant else 'non_classee',
            'revision_classement': courant['revision'] if courant else 0})
    source = idempotence.empreinte_arguments(dict(lead_id=lead_id, categorie=categorie,
        ancre=ancre, metadonnees=metas, classements=classements))
    if source_attendue and source_attendue != source:
        raise Refus('LISTE-PERIMEE')
    selection = [r for r in enrichis if categorie is None or r['categorie_courante'] == categorie]
    nombre = len(selection)
    if decalage and decalage >= nombre:
        raise Refus('INTROUVABLE')
    resultat = dict(lead_id=lead_id, pieces=selection[decalage:decalage + pieces.PAGE],
        categorie=categorie, nombre=nombre, nombre_total=len(enrichis), decalage=decalage,
        suivant=decalage + pieces.PAGE if decalage + pieces.PAGE < nombre else None, source_calculee=source)
    pieces._fermer(cnx, deps, session, lead_id, ancre)
    if _sources_liste(cnx, lead_id) != (metas, classements):
        raise Refus('SOURCE-MODIFIEE')
    pieces.autorite._admin(cnx, session)
    return pieces.lecture._sortie(resultat)
