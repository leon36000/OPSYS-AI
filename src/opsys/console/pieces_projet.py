"""Originaux reçus, privés et immuables, ancrés au projet M2 avant la fin des travaux.

Port console SQLite uniquement. La clé externe est fournie par l'appelant privé, jamais persistée.
Aucune analyse de contenu, signature, copie M10, permission DEVICE ou référence CAS n'est induite.
"""
import base64
import hashlib
import json
import re
import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import LargeBinary, cast, func, select

from .. import etat, idempotence
from ..stockage.maillons import copier_maillons_avec_metadonnees
from ..stockage.schema import PIECES_PROJET as PIECES
from . import memoire_chantier as autorite
from . import preparation_chantier as lecture

MAX_ORIGINAL = 1048576
MAX_PIECES = 128
MAX_TOTAL = 32 * 1048576  # Octets UTF-8 des chiffrés base64, titre compris.
MAX_CHIFFRE = 4 * ((MAX_ORIGINAL + 16 + 2) // 3)
MAX_TITRE_CHIFFRE = 4 * ((640 + 16 + 2) // 3)
PAGE = 20
Refus = lecture.Refus
_METADATA = tuple(c for c in PIECES.c if c.name != 'chiffre')
_AAD = ('piece_id', 'lead_id', 'client_id', 'auteur', 'mutation_id', 'empreinte',
        'source_sha256', 'type_mime', 'taille_octets', 'recu_le', 'version_format')
_LIMITES = dict(piece_id=32, lead_id=200, client_id=200, auteur=200, mutation_id=32, empreinte=64,
                source_sha256=64, type_mime=32, recu_le=40, nonce=24, titre_nonce=24,
                titre_chiffre=MAX_TITRE_CHIFFRE, chiffre=MAX_CHIFFRE)


def _cle(cle):
    if type(cle) is not bytes or len(cle) != 32:
        raise Refus('CLE-INDISPONIBLE')


def _aesgcm(cle):
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        raise Refus('CHIFFREMENT-INDISPONIBLE') from None
    return AESGCM(cle)


def _aad(ligne, nature):
    valeurs = {k: ligne[k] for k in _AAD}
    return ('opsys-pieces-projet:v1:' + nature + ':' +
            json.dumps(valeurs, sort_keys=True, ensure_ascii=False, separators=(',', ':'))).encode('utf-8')


def _chiffrer(cle, ligne, nature, contenu):
    nonce = secrets.token_bytes(12)
    return (base64.b64encode(nonce).decode('ascii'),
            base64.b64encode(_aesgcm(cle).encrypt(nonce, contenu, _aad(ligne, nature))).decode('ascii'))


def _dechiffrer(cle, ligne, nature):
    try:
        from cryptography.exceptions import InvalidTag
    except ImportError:
        raise Refus('CHIFFREMENT-INDISPONIBLE') from None

    prefixe = 'titre_' if nature == 'titre' else ''
    try:
        nonce = base64.b64decode(ligne[prefixe + 'nonce'], validate=True)
        chiffre = base64.b64decode(ligne[prefixe + 'chiffre'], validate=True)
        if len(nonce) != 12:
            raise ValueError('nonce')
        return _aesgcm(cle).decrypt(nonce, chiffre, _aad(ligne, nature))
    except (InvalidTag, ValueError, TypeError, UnicodeError):
        raise Refus('PIECE-CORROMPUE') from None


def _borner(cnx):
    mesures = cnx.execute(select(func.count(), func.sum(
        func.length(cast(PIECES.c.chiffre, LargeBinary)) +
        func.length(cast(PIECES.c.titre_chiffre, LargeBinary))),
        *[func.max(func.length(cast(PIECES.c[nom], LargeBinary))) for nom in _LIMITES]
    ).select_from(PIECES)).one()
    # Les champs textuels identifiants peuvent être UTF-8, jusqu'à quatre octets par caractère.
    if (mesures[0] > MAX_PIECES or (mesures[1] or 0) > MAX_TOTAL
            or any((n or 0) > limite * (4 if nom in {'lead_id', 'client_id', 'auteur'} else 1)
                   for (nom, limite), n in zip(_LIMITES.items(), mesures[2:], strict=True))):
        raise Refus('QUOTA-PIECES')


def _ancre(cnx, deps, session, lead_id):
    from m2_revenue_crm import clients, registre

    if type(lead_id) is not str or re.fullmatch(r'[\w.:@~\-]{1,200}', lead_id) is None:
        raise Refus('INTROUVABLE')
    lecture._borner(cnx, lecture.M2, 'principal')
    source = copier_maillons_avec_metadonnees(cnx, departement=lecture.M2, registre='principal')
    chaine = registre.Registre([m.maillon for m in source.lignes])
    try:
        chaine.assert_chaine()
    except registre.VerificationError:
        raise Refus('SOURCE-INCOHERENTE') from None
    canonique = clients.client_de_lead(chaine, lead_id)
    if canonique is None:
        raise Refus('INTROUVABLE')
    lien = lecture._appel(deps, session.utilisateur, lecture.M2, 'm2_trouver_client_de_lead', {'lead_id': lead_id})
    if (lien.get('lead_id') != lead_id or lien.get('client_id') != canonique
            or type(lien.get('client_id')) is not str
            or not 1 <= len(lien['client_id']) <= 200):
        raise Refus('SOURCE-INCOHERENTE')
    return dict(client_id=lien['client_id'], source=source.empreinte_snapshot_calculee)


def _fermer(cnx, deps, session, lead_id, ancre):
    autorite._admin(cnx, session)
    if _ancre(cnx, deps, session, lead_id) != ancre:
        raise Refus('SOURCE-MODIFIEE')
    _borner(cnx)
    autorite._admin(cnx, session)


def _titre(titre):
    if (type(titre) is not str or not 1 <= len(titre) <= 160 or titre != titre.strip()
            or any(ord(c) < 32 or ord(c) == 127 for c in titre)):
        raise Refus('TITRE-INVALIDE')
    try:
        return titre.encode('utf-8', errors='strict')
    except UnicodeError:
        raise Refus('TITRE-INVALIDE') from None


def _original(contenu, type_mime):
    if type(contenu) is not bytes or not 1 <= len(contenu) <= MAX_ORIGINAL:
        raise Refus('TAILLE-INVALIDE')
    signatures = {'application/pdf': b'%PDF-', 'image/png': b'\x89PNG\r\n\x1a\n', 'image/jpeg': b'\xff\xd8\xff'}
    if type(type_mime) is not str or type_mime not in signatures or not contenu.startswith(signatures[type_mime]):
        raise Refus('TYPE-INVALIDE')


def _recu(ligne, cle):
    try:
        titre = _dechiffrer(cle, ligne, 'titre').decode('utf-8', errors='strict')
    except UnicodeError:
        raise Refus('PIECE-CORROMPUE') from None
    _titre(titre)
    return dict(piece_id=ligne['piece_id'], lead_id=ligne['lead_id'], titre=titre, auteur=ligne['auteur'],
                recu_le=ligne['recu_le'], type_mime=ligne['type_mime'], taille_octets=ligne['taille_octets'],
                source_sha256=ligne['source_sha256'], statut='NON_ANALYSE')


def _ligne(cnx, lead_id, piece_id):
    if type(piece_id) is not str or re.fullmatch('[0-9a-f]{32}', piece_id) is None:
        raise Refus('INTROUVABLE')
    ligne = cnx.execute(select(PIECES).where(
        (PIECES.c.lead_id == lead_id) & (PIECES.c.piece_id == piece_id))).mappings().one_or_none()
    if ligne is None:
        raise Refus('INTROUVABLE')
    return dict(ligne)


def lire(cnx, deps, session, lead_id, piece_id, *, cle):
    autorite._admin(cnx, session)
    _cle(cle)
    ancre = _ancre(cnx, deps, session, lead_id)
    _borner(cnx)
    ligne = _ligne(cnx, lead_id, piece_id)
    if ligne['client_id'] != ancre['client_id']:
        raise Refus('SOURCE-INCOHERENTE')
    meta = _recu(ligne, cle)
    original = _dechiffrer(cle, ligne, 'original')
    _original(original, ligne['type_mime'])
    if len(original) != ligne['taille_octets'] or hashlib.sha256(original).hexdigest() != ligne['source_sha256']:
        raise Refus('PIECE-CORROMPUE')
    _fermer(cnx, deps, session, lead_id, ancre)
    if _ligne(cnx, lead_id, piece_id) != ligne:
        raise Refus('SOURCE-MODIFIEE')
    autorite._admin(cnx, session)
    return meta, original


def _page(cnx, lead_id, decalage):
    return [dict(r) for r in cnx.execute(select(*_METADATA).where(PIECES.c.lead_id == lead_id)
            .order_by(PIECES.c.recu_le, PIECES.c.piece_id).limit(PAGE).offset(decalage)).mappings()]


def lister(cnx, deps, session, lead_id, *, cle, decalage=0):
    autorite._admin(cnx, session)
    _cle(cle)
    if type(decalage) is not int or not 0 <= decalage < MAX_PIECES or decalage % PAGE:
        raise Refus('PAGINATION-INVALIDE')
    ancre = _ancre(cnx, deps, session, lead_id)
    _borner(cnx)
    nombre = cnx.execute(select(func.count()).select_from(PIECES).where(PIECES.c.lead_id == lead_id)).scalar_one()
    if decalage and decalage >= nombre:
        raise Refus('INTROUVABLE')
    lignes = _page(cnx, lead_id, decalage)
    if any(r['client_id'] != ancre['client_id'] for r in lignes):
        raise Refus('SOURCE-INCOHERENTE')
    pieces = [_recu(r, cle) for r in lignes]
    _fermer(cnx, deps, session, lead_id, ancre)
    if _page(cnx, lead_id, decalage) != lignes:
        raise Refus('SOURCE-MODIFIEE')
    autorite._admin(cnx, session)
    return dict(lead_id=lead_id, pieces=pieces, nombre=nombre, decalage=decalage,
                suivant=decalage + PAGE if decalage + PAGE < nombre else None)


def deposer(cnx, deps, session, lead_id, *, mutation_id, titre, type_mime, contenu, cle):
    autorite._admin(cnx, session)
    _cle(cle)
    titre_octets = _titre(titre)
    _original(contenu, type_mime)
    if type(mutation_id) is not str or re.fullmatch('[0-9a-f]{32}', mutation_id) is None:
        raise Refus('SAISIE-INVALIDE')
    if type(lead_id) is not str or re.fullmatch(r'[\w.:@~\-]{1,200}', lead_id) is None:
        raise Refus('INTROUVABLE')
    source_sha = hashlib.sha256(contenu).hexdigest()
    empreinte = idempotence.empreinte_arguments(dict(lead_id=lead_id, titre=titre, type_mime=type_mime,
                                                   taille_octets=len(contenu), source_sha256=source_sha))
    with cnx.begin_nested():
        ancre = _ancre(cnx, deps, session, lead_id)
        _borner(cnx)
        ancienne = cnx.execute(select(PIECES.c.piece_id, PIECES.c.lead_id, PIECES.c.empreinte).where(
            (PIECES.c.auteur == session.utilisateur) & (PIECES.c.mutation_id == mutation_id))).mappings().one_or_none()
        if ancienne is not None:
            if ancienne['empreinte'] != empreinte or ancienne['lead_id'] != lead_id:
                raise Refus('SAISIE-CONFLIT')
            return lire(cnx, deps, session, lead_id, ancienne['piece_id'], cle=cle)[0]
        ligne = dict(piece_id=uuid.uuid4().hex, lead_id=lead_id, client_id=ancre['client_id'],
                     auteur=session.utilisateur, mutation_id=mutation_id, empreinte=empreinte,
                     source_sha256=source_sha, type_mime=type_mime, taille_octets=len(contenu),
                     recu_le=datetime.now(UTC).isoformat(), version_format=1)
        ligne['titre_nonce'], ligne['titre_chiffre'] = _chiffrer(cle, ligne, 'titre', titre_octets)
        ligne['nonce'], ligne['chiffre'] = _chiffrer(cle, ligne, 'original', contenu)
        cnx.execute(PIECES.insert().values(**ligne))
        etat.journaliser(cnx, session.utilisateur, 'crm.piece_recue', ligne['piece_id'],
                         dict(lead_id=lead_id, source_sha256=source_sha, taille_octets=len(contenu),
                              type_mime=type_mime, mutation_id=mutation_id))
        _fermer(cnx, deps, session, lead_id, ancre)
        # La même lecture vérifiée sert aussi à produire le reçu initial.
        return lire(cnx, deps, session, lead_id, ligne['piece_id'], cle=cle)[0]
