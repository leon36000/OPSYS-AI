"""Publication humaine d'une référence M6 minimale ; jamais de texte libre dans M10."""
from __future__ import annotations

import hashlib

from sqlalchemy import select

from . import contexte, evenements, stockage
from . import notes_commande_affaire as liaison
from .etat import journaliser
from .stockage import codec
from .stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS

TYPE = "m6.note_commande_referencee"
PRODUCTEUR = "m06-material-control"


class ReferenceRefusee(ValueError):
    """Code fermé, sans charge ni renseignement personnel."""


def _attendue(note_id, revision, devis_id, lead_id, source_hash):
    lien = liaison.resoudre(note_id, revision, devis_id, lead_id)
    if lien['statut'] != 'VERIFIE':
        raise ReferenceRefusee(lien['code'])
    if lien['source_hash'] != source_hash:
        raise ReferenceRefusee('SOURCE-MODIFIEE')
    note = liaison._lire(PRODUCTEUR, 'notes_commande')[lien['source_index']]
    cle = f"m6-note-v1:{lead_id}:{lien['source_index']}:{revision}:{source_hash}"
    return {'fait_id': hashlib.sha256(cle.encode('utf-8')).hexdigest(), 'lead_id': lead_id,
            'source_index': lien['source_index'], 'source_hash': source_hash, 'revision': revision,
            'horodatage': note['enregistree_le']}


def _decoder(texte):
    try:
        return codec.decoder(texte)
    except (ValueError, TypeError):
        return None


def _etat(attendu):
    cnx = stockage.connexion_courante()
    eid = 'm6-note-'+attendu['fait_id']
    pub = cnx.execute(select(EVENEMENTS_SORTANTS).where(
        EVENEMENTS_SORTANTS.c.evenement_id == eid)).mappings().one_or_none()
    recu = cnx.execute(select(EVENEMENTS_RECUS).where(
        (EVENEMENTS_RECUS.c.evenement_id == eid) &
        (EVENEMENTS_RECUS.c.consommateur == 'm10-memoire'))).mappings().one_or_none()
    memoires = [m for m in liaison._lire('m10-memoire', 'evenements')
                if m.get('type_evenement') == TYPE and m.get('fait_id') == attendu['fait_id']]
    conforme = len(memoires) == 1 and all(memoires[0].get(k) == v for k, v in attendu.items()) and (
        memoires[0].get('confidentialite') == 'CLIENT_PRIVATE' and
        memoires[0].get('type_entree') == 'evenement_memorise')
    conflit = bool(memoires) and not conforme
    if pub:
        conflit |= pub['producteur'] != PRODUCTEUR or pub['type_evenement'] != TYPE or (
            _decoder(pub['charge']) != attendu)
    resultat = _decoder(recu['resultat']) if recu and recu['resultat'] else None
    livre = False
    if recu and recu['statut'] == 'traite':
        livre = (conforme and isinstance(resultat, dict) and resultat.get('memorise') is True
                 and resultat.get('identique') is True and all(resultat.get(k) == v for k, v in {
            'type_evenement': TYPE,
            'identifiant': attendu['fait_id'], 'lead_id': attendu['lead_id'],
            'producteur': PRODUCTEUR, 'ligne_id': memoires[0]['ligne_id'] if conforme else None,
        }.items()))
        conflit |= not livre
    if pub is None and (recu or memoires):
        conflit = True
    if conflit:
        etat = 'CONFLIT'
    elif pub is None:
        etat = 'NON_PUBLIE'
    elif livre:
        etat = 'MEMORISE'
    else:
        etat = {'echec': 'ECHEC_LIVRAISON', 'quarantaine': 'QUARANTAINE'}.get(
            recu['statut'] if recu else None, 'EN_ATTENTE')
    return {'etat': etat, 'fait_id': attendu['fait_id'], 'revision': attendu['revision']}


def consulter(note_id, revision, devis_id, lead_id, source_hash):
    """Lecture avec autorité et sources fraîches ; un fait sans reçu n'est pas livré."""
    return _etat(_attendue(note_id, revision, devis_id, lead_id, source_hash))


def publier(note_id, revision, devis_id, lead_id, source_hash):
    """Même transaction SQLite que l'autorité, le rattachement, l'outbox et l'audit."""
    appelante = contexte.identite_appelante()
    if appelante is None or appelante.source != 'console':
        raise ReferenceRefusee('HUMAIN-CONSOLE-REQUIS')
    attendu = _attendue(note_id, revision, devis_id, lead_id, source_hash)
    etat = _etat(attendu)
    if etat['etat'] == 'CONFLIT':
        raise ReferenceRefusee('REFERENCE-CONTRADICTOIRE')
    if etat['etat'] != 'NON_PUBLIE':
        return etat
    eid = 'm6-note-'+attendu['fait_id']
    evenements.publier(TYPE, PRODUCTEUR, attendu, evenement_id=eid)
    journaliser(stockage.connexion_courante(), appelante.personne, 'console.reference_note_m6', eid,
                {'revision': revision, 'source_hash': source_hash})
    return _etat(attendu)
