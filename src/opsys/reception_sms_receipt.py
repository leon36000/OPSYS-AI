"""Réception SMS interne : P SQL actuelle, pipeline M1 et reçu historique atomiques.

Ni endpoint ni preuve HMAC : le host de confiance demeure responsable de l'origine.
La connexion canonique et le module M1 sont fournis par l'appelant interne.
"""
from __future__ import annotations

import json
import re

from sqlalchemy import Connection
from sqlalchemy.exc import SQLAlchemyError

from opsys import agents, canaux, stockage
from opsys.reception_sms_runtime import valider_commande

_RECEVOIR = 'opsys_runtime_recevoir_sms'
_LIRE = 'opsys_runtime_lire_reception_sms'
_OPERATIONS = {_RECEVOIR: 'recevoir', _LIRE: 'lire'}
_TYPE_RECU = 'reception_hote_sms_v1'
_R = {'source', 'compte_id', 'account_sid', 'message_sid', 'agent_id', 'session_key',
      'signal_id', 'signal_ligne_id', 'decision', 'lead_ligne_id', 'transfert_id'}
_P = {'profil_id', 'revision_profil', 'outil_m1'}
_MAIL = {'type_entree', 'horodatage', 'intention_id', 'commande_sha256', 'arguments_sha256',
         'permission', 'recu', 'ligne_id', 'precedent_ligne_id'}
_DECISIONS = {'DEMANDER_PRECISIONS', 'TRANSMETTRE_M2', 'CONVERSATION_DEJA_QUALIFIEE',
              'RETRAIT_CONSENTEMENT', 'ESCALADE_PLAINTE', 'ESCALADE_URGENCE', 'TRANSFERT_EN_COURS'}
_ERREURS = {'refus': 'REJ-M1-SMS-AUTORITE-REFUSEE', 'revision_perimee': 'REJ-M1-SMS-REVISION-PERIMEE',
            'conflit': 'REJ-M1-SMS-PROVENANCE-CONFLICTUELLE', 'forme_invalide': 'REJ-M1-SMS-FORME-INVALIDE',
            'inconnu': 'M1-SMS-INCONNU'}
_QUOTA_ACK = 8192


class _Refus(Exception):
    def __init__(self, etat):
        self.etat = etat


def _exiger(condition, etat='inconnu'):
    if not condition:
        raise _Refus(etat)


def _hex(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


def _format(value, pattern):
    return type(value) is str and re.fullmatch(pattern, value, flags=re.ASCII) is not None


def _autoriser(cnx, cmd):
    """P originale relue avant contenu R, puis après les écritures avant ACK."""
    _exiger(cnx is stockage.connexion_courante() and not cnx.closed and cnx.in_transaction()
            and cnx.engine.url == stockage.moteur().url)
    p, c = cmd.permission, cmd.commande
    profile = agents.obtenir(cnx, p['profil_id'], inclure_supprime=True)
    _exiger(profile is not None, 'refus')
    _exiger(type(profile['revision']) is int and profile['revision'] == p['revision_profil'], 'revision_perimee')
    _exiger(profile['actif'] is True and profile['supprime'] is False
            and profile['departement'] == 'm01-front-office'
            and type(profile['outils']) is list and all(type(x) is str for x in profile['outils'])
            and 'm1_recevoir_message_canal' in profile['outils'], 'refus')
    decls = profile['declencheurs']
    _exiger(type(decls) is list and len(decls) == 1, 'refus')
    d = decls[0]
    _exiger(type(d) is dict and set(d) == {'type', 'version', 'canal', 'compte_id', 'account_sid'}, 'refus')
    _exiger(d['type'] == 'canal' and type(d['version']) is int and d['version'] == 1
            and d['canal'] == 'sms' and d['compte_id'] == c['compte_id']
            and d['account_sid'] == c['account_sid'], 'refus')
    # La configuration canonique est unique par compte_id actif, jamais par SID global.
    actifs = agents.lister(cnx)
    porteurs = [a['id'] for a in actifs if any(
        x.get('type') == 'canal' and x.get('canal') == 'sms' and x.get('compte_id') == c['compte_id']
        for x in a['declencheurs'])]
    _exiger(porteurs == [p['profil_id']], 'refus')


def _snapshot(m1):
    _reg, rows = m1.registre_sms_hote()
    ids = [r.get('ligne_id') for r in rows]
    _exiger(all(_hex(i) for i in ids) and len(set(ids)) == len(ids))
    intentions = set()
    for row in rows:
        if row.get('type_entree') != _TYPE_RECU:
            continue
        _exiger(type(row) is dict and set(row) == _MAIL)
        _exiger(type(row['intention_id']) is str and re.fullmatch('sms-v1:[0-9a-f]{64}', row['intention_id']))
        _exiger(_hex(row['commande_sha256']) and _hex(row['arguments_sha256']))
        _exiger(row['intention_id'] not in intentions, 'conflit')
        intentions.add(row['intention_id'])
        p, r = row['permission'], row['recu']
        _exiger(type(p) is dict and set(p) == _P and type(p['revision_profil']) is int
                and 1 <= p['revision_profil'] <= 9007199254740991
                and _format(p['profil_id'], '[a-z][a-z0-9-]{1,63}')
                and p['outil_m1'] == 'opsys_m1__m1_recevoir_message_canal')
        _exiger(_format(row['horodatage'], r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z'))
        m1.horodatage.valider_horodatage(row['horodatage'])
        _exiger(type(r) is dict and set(r) == _R and r['source'] == 'sms:twilio')
        _exiger(all(type(r[k]) is str for k in _R - {'lead_ligne_id', 'transfert_id'}))
        _exiger(_format(r['compte_id'], '[a-z0-9][a-z0-9_-]{0,63}')
                and r['compte_id'] not in {'prototype', 'constructor', '__proto__'}
                and _format(r['account_sid'], 'AC[0-9a-fA-F]{32}')
                and _format(r['message_sid'], 'SM[0-9a-fA-F]{32}')
                and r['agent_id'] == 'opsys-agent-' + p['profil_id']
                and r['signal_id'] == 'sms:' + r['message_sid'])
        prefix = 'agent:' + r['agent_id'] + ':sms:direct:'
        _exiger(r['session_key'].startswith(prefix))
        peer = r['session_key'][len(prefix):]
        _exiger(_format(peer, r'\+[1-9][0-9]{6,14}')
                and r['session_key'] == canaux.cle_session(r['agent_id'], 'sms', peer))
        _exiger(r['decision'] in _DECISIONS and _hex(r['signal_ligne_id']))
        _exiger(r['lead_ligne_id'] is None or _hex(r['lead_ligne_id']))
        _exiger(r['transfert_id'] is None or (type(r['transfert_id']) is str
                and re.fullmatch('tr-[0-9a-f]{20}', r['transfert_id'])))
    return rows


def _references(r, rows, cmd, m1, *, maillon=None):
    """Liens historiques : ni nouveau signal sur l'ancien lead ni transfert encore ouvert requis."""
    c = cmd.commande
    _exiger(type(r) is dict and set(r) == _R)
    _exiger(r['source'] == 'sms:twilio' and r['decision'] in _DECISIONS)
    _exiger(all(r[k] == c[k] for k in ('compte_id', 'account_sid', 'message_sid', 'agent_id', 'session_key')))
    _exiger(r['signal_id'] == 'sms:' + c['message_sid'])
    _exiger(sum(row.get('type_entree') == 'signal' and row.get('signal_id') == r['signal_id']
                for row in rows) == 1, 'conflit')
    by_id = {row['ligne_id']: row for row in rows}
    sig = by_id.get(r['signal_ligne_id'])
    conv = m1.reception.identifiant_de_conversation('sms', c['expediteur'])
    filtered, sane = m1.provenance.filtrer(c['texte'])
    _exiger(sig is not None and sig.get('type_entree') == 'signal' and sig.get('source') == 'sms'
            and sig.get('canal') == 'texte' and sig.get('conversation_id') == conv
            and sig.get('signal_id') == r['signal_id'] and sig.get('horodatage') == c['recu_le']
            and sig.get('contenu_filtre') == filtered and sig.get('provenance_saine') == sane, 'conflit')
    lead_id, transfer_id, decision = r['lead_ligne_id'], r['transfert_id'], r['decision']
    positions = {row['ligne_id']: i for i, row in enumerate(rows)}
    references = [r['signal_ligne_id']]
    if decision in {'TRANSMETTRE_M2', 'CONVERSATION_DEJA_QUALIFIEE'}:
        lead = by_id.get(lead_id)
        _exiger(lead is not None and transfer_id is None and lead.get('type_entree') == 'lead_emis'
                and lead.get('conversation_id') == conv and type(lead.get('lead')) is dict
                and lead['lead'].get('conversation_id') == conv and lead['lead'].get('source') == 'sms'
                and sig.get(m1.transferts.MARQUE) is None, 'conflit')
        if decision == 'TRANSMETTRE_M2':
            _exiger(lead.get('signal_id') == r['signal_id'] and lead.get('cle_session') == c['session_key']
                    and positions[lead_id] > positions[r['signal_ligne_id']], 'conflit')
        else:
            _exiger(sig.get('rattache_au_lead') == lead['lead'].get('lead_id')
                    and positions[lead_id] < positions[r['signal_ligne_id']], 'conflit')
        references.append(lead_id)
    elif decision in {'ESCALADE_PLAINTE', 'ESCALADE_URGENCE', 'TRANSFERT_EN_COURS'}:
        opens = [row for row in rows if row.get('type_entree') == m1.transferts.TYPE_ENTREE
                 and row.get('evenement') == m1.transferts.EVT_OUVERT and row.get('transfert_id') == transfer_id]
        _exiger(lead_id is None and transfer_id is not None and len(opens) == 1
                and sig.get(m1.transferts.MARQUE) == transfer_id
                and opens[0].get('conversation_id') == conv, 'conflit')
        opening = opens[0]
        references.append(opening['ligne_id'])
        if decision != 'TRANSFERT_EN_COURS':
            _exiger(opening.get('signal_id') == r['signal_id'] and opening.get('type_transfert') == (
                'urgence' if decision == 'ESCALADE_URGENCE' else 'plainte'), 'conflit')
        else:
            _exiger(opening.get('signal_id') != r['signal_id']
                    and positions[opening['ligne_id']] < positions[r['signal_ligne_id']], 'conflit')
    else:
        _exiger(lead_id is None and transfer_id is None and sig.get(m1.transferts.MARQUE) is None
                and sig.get('rattache_au_lead') is None, 'conflit')
        alerts = [row for row in rows if row.get('type_entree') == 'alerte'
                  and row.get('marqueur') == 'retrait_consentement' and row.get('signal_id') == r['signal_id']
                  and row.get('conversation_id') == conv]
        _exiger((len(alerts) == 1) if decision == 'RETRAIT_CONSENTEMENT' else not alerts, 'conflit')
        references.extend(row['ligne_id'] for row in alerts)
        _exiger(not any(row.get('type_entree') == 'lead_emis' and row.get('signal_id') == r['signal_id']
                        for row in rows), 'conflit')
    if maillon is not None:
        _exiger(all(positions[ref] < positions[maillon['ligne_id']] for ref in references), 'conflit')


def _valider_maillon(row, cmd):
    captured = {'version': 1, 'commande': dict(cmd.commande), 'permission': dict(cmd.permission)}
    initial = valider_commande(captured, operation=_RECEVOIR)
    _exiger(row['commande_sha256'] == cmd.commande_sha256 and row['permission'] == dict(cmd.permission)
            and row['arguments_sha256'] == initial.arguments_sha256
            and row['horodatage'] == cmd.commande['recu_le'], 'conflit')


def _ack(cmd, recu):
    ack = {'version': 1, 'operation': _OPERATIONS[cmd.operation], 'ok': True,
           'etat': 'absent' if recu is None else 'recu', 'intention_id': cmd.intention_id,
           'commande_sha256': cmd.commande_sha256, 'arguments_sha256': cmd.arguments_sha256,
           'permission': dict(cmd.permission), 'recu': recu}
    data = json.dumps(ack, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
    _exiger(len(data) <= _QUOTA_ACK)
    return ack


def _executer(cnx, args, cmd, m1):
    _autoriser(cnx, cmd)
    rows = _snapshot(m1)
    found = [r for r in rows if r.get('type_entree') == _TYPE_RECU and r['intention_id'] == cmd.intention_id]
    if found:
        row = found[0]
        _valider_maillon(row, cmd)
        _references(row['recu'], rows, cmd, m1, maillon=row)
        _autoriser(cnx, cmd)
        return _ack(cmd, row['recu'])
    _exiger(not any(r.get('type_entree') == 'signal' and r.get('signal_id') == 'sms:' + cmd.commande['message_sid']
                    for r in rows), 'conflit')
    if cmd.operation == _LIRE:
        _autoriser(cnx, cmd)
        return _ack(cmd, None)
    c = cmd.commande
    response = m1.recevoir_sms_hote(expediteur=c['expediteur'], message_id=c['message_sid'], recu_le=c['recu_le'],
                                  texte=c['texte'], cle_session=c['session_key'])
    _exiger(type(response) is dict and response.get('accepte') is True and response.get('decision') in _DECISIONS)
    transfer = response.get('transfert')
    bindings = ('compte_id', 'account_sid', 'message_sid', 'agent_id', 'session_key')
    recu = {'source': 'sms:twilio', **{k: c[k] for k in bindings},
            'signal_id': 'sms:' + c['message_sid'], 'signal_ligne_id': response.get('signal_ligne_id'),
            'decision': response['decision'], 'lead_ligne_id': response.get('lead_ligne_id'),
            'transfert_id': transfer.get('transfert_id') if type(transfer) is dict else None}
    rows = _snapshot(m1)
    _references(recu, rows, cmd, m1)
    m1.inscrire_recu_sms_hote({'type_entree': _TYPE_RECU, 'horodatage': c['recu_le'],
        'intention_id': cmd.intention_id, 'commande_sha256': cmd.commande_sha256,
        'arguments_sha256': cmd.arguments_sha256, 'permission': dict(cmd.permission), 'recu': recu})
    rows = _snapshot(m1)
    appended = [r for r in rows if r.get('type_entree') == _TYPE_RECU and r['intention_id'] == cmd.intention_id]
    _exiger(len(appended) == 1 and appended[0]['recu'] == recu)
    _valider_maillon(appended[0], cmd)
    _references(recu, rows, cmd, m1, maillon=appended[0])
    _autoriser(cnx, cmd)
    return _ack(cmd, recu)


def executer(cnx, arguments, *, operation, m1):
    """ACK fermé ; tout refus/panne après écriture sort seulement après rollback du savepoint."""
    if type(operation) is not str or operation not in _OPERATIONS:
        return {'version': 1, 'operation': 'recevoir', 'ok': False,
                'etat': 'forme_invalide', 'code': _ERREURS['forme_invalide']}
    try:
        try:
            cmd = valider_commande(arguments, operation=operation)
        except (ValueError, TypeError, RecursionError):
            raise _Refus('forme_invalide') from None
        _exiger(isinstance(cnx, Connection) and cnx is stockage.connexion_courante()
                and not cnx.closed and cnx.in_transaction() and cnx.dialect.name == 'sqlite'
                and cnx.engine.url == stockage.moteur().url)
        with cnx.begin_nested():
            return _executer(cnx, arguments, cmd, m1)
    except _Refus as refusal:
        etat = refusal.etat
    except (ValueError, TypeError, KeyError, AttributeError, ArithmeticError,
            RecursionError, RuntimeError, OSError, SQLAlchemyError):
        etat = 'inconnu'
    return {'version': 1, 'operation': _OPERATIONS[operation], 'ok': False, 'etat': etat, 'code': _ERREURS[etat]}
