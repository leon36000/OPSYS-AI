"""Liaison privée tarif/réception durable; le livre de prix conserve son contrat historique."""
import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal

from sqlalchemy import LargeBinary, cast, func, select

from . import idempotence, stockage
from .stockage import codec
from .stockage.schema import MUTATIONS_APPLIQUEES, REGISTRES

DEPARTEMENT = 'm06-material-control'
REGISTRE = 'receptions_tarifs'
OUTIL = 'm6_confirmer_tarif_console'
MAX_SOURCES = 10000
MAX_OCTETS = 8388608
CHAMPS_LIAISON = {'tarif_rang', 'tarif_empreinte', 'appareil', 'cle_idempotence',
                  'empreinte_arguments', 'recu_le', 'preuve_sha256'}


def _refuser():
    raise ValueError('Provenance de réception tarif indisponible')


def _sha(valeur):
    return hashlib.sha256(json.dumps(valeur, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def _connexion(cnx):
    if cnx is None or cnx is not stockage.connexion_courante() or cnx.dialect.name != 'sqlite':
        _refuser()


def _rang(rang):
    if type(rang) is not int or not 0 <= rang < MAX_SOURCES:
        _refuser()


def _date(valeur):
    if type(valeur) is not str or len(valeur) > 50:
        _refuser()
    try:
        instant = datetime.fromisoformat(valeur)
        if instant.utcoffset() is None:
            _refuser()
    except ValueError:
        _refuser()


def _liaisons(cnx):
    condition = (REGISTRES.c.departement == DEPARTEMENT) & (REGISTRES.c.registre == REGISTRE)
    if cnx.execute(select(func.count()).select_from(REGISTRES).where(condition)).scalar_one() > MAX_SOURCES:
        _refuser()
    resultat, taille, vus = [], 0, set()
    for ligne in cnx.execute(select(REGISTRES.c.rang, REGISTRES.c.maillon).where(condition).order_by(REGISTRES.c.rang)):
        taille += len(ligne.maillon.encode('utf-8'))
        if ligne.rang != len(resultat) or taille > MAX_OCTETS:
            _refuser()
        liaison = codec.decoder(ligne.maillon)
        if type(liaison) is not dict or set(liaison) != CHAMPS_LIAISON:
            _refuser()
        _rang(liaison['tarif_rang'])
        _date(liaison['recu_le'])
        for cle in ('appareil', 'cle_idempotence'):
            if type(liaison[cle]) is not str or not liaison[cle].strip() or len(liaison[cle]) > 200:
                _refuser()
        for cle in ('tarif_empreinte', 'empreinte_arguments', 'preuve_sha256'):
            if type(liaison[cle]) is not str or re.fullmatch(r'[0-9a-f]{64}', liaison[cle]) is None:
                _refuser()
        if (liaison['tarif_rang'] in vus
                or liaison['preuve_sha256'] != _sha({k: v for k, v in liaison.items() if k != 'preuve_sha256'})):
            _refuser()
        vus.add(liaison['tarif_rang'])
        resultat.append(liaison)
    return resultat


def _prix(cnx, rang):
    from m6_material_control import contrats, livre_prix

    _rang(rang)
    condition = ((REGISTRES.c.departement == DEPARTEMENT) & (REGISTRES.c.registre == 'livre_prix')
                 & (REGISTRES.c.rang == rang))
    octets = cnx.execute(select(func.length(cast(REGISTRES.c.maillon, LargeBinary)))
                        .where(condition)).scalar_one_or_none()
    if octets is None or octets > 8192:
        _refuser()
    maillon = codec.decoder(cnx.execute(select(REGISTRES.c.maillon).where(condition)).scalar_one())
    permis = contrats.CHAMPS_ENTREE_PRIX_REQUIS | {'source_document', 'unite'}
    if type(maillon) is not dict or set(maillon) - permis or not set(maillon) >= contrats.CHAMPS_ENTREE_PRIX_REQUIS:
        _refuser()
    _, refus = livre_prix.enregistrer_prix(
        maillon['materiau_id'], maillon['fournisseur_id'], maillon['prix_unitaire'], maillon['devise'],
        maillon['date_effet'], [], source_document=maillon.get('source_document'), unite=maillon.get('unite'))
    if refus is not None or maillon['devise'] != 'CAD' or type(maillon.get('unite')) is not str:
        _refuser()
    return maillon, _sha(dict(rang=rang, maillon=maillon))


def _recu(cnx, appareil, cle):
    condition = ((MUTATIONS_APPLIQUEES.c.appareil == appareil)
                 & (MUTATIONS_APPLIQUEES.c.cle_idempotence == cle))
    octets = cnx.execute(select(func.length(cast(MUTATIONS_APPLIQUEES.c.reponse, LargeBinary)))
                        .where(condition)).scalar_one_or_none()
    if octets is None or octets > 65536:
        _refuser()
    recu = cnx.execute(select(MUTATIONS_APPLIQUEES).where(condition)).mappings().one()
    if recu['outil'] != OUTIL:
        _refuser()
    _date(recu['recu_le'])
    return recu


def enregistrer(cnx, meta, arguments, tarif_rang):
    """Appelé après append du tarif et avant finalisation, dans le savepoint du port privé."""
    _connexion(cnx)
    if not isinstance(meta, idempotence.Meta):
        _refuser()
    recu = _recu(cnx, meta.appareil, meta.cle)
    if recu['statut'] != 'en_cours' or recu['empreinte_arguments'] != idempotence.empreinte_arguments(arguments):
        _refuser()
    maillon, empreinte = _prix(cnx, tarif_rang)
    if (any(maillon.get(k) != arguments.get(k) for k in
            ('materiau_id', 'fournisseur_id', 'date_effet', 'source_document'))
            or Decimal(str(maillon['prix_unitaire'])) != Decimal(arguments['prix_unitaire'])):
        _refuser()
    liaisons = _liaisons(cnx)
    if len(liaisons) >= MAX_SOURCES or any(liaison['tarif_rang'] == tarif_rang for liaison in liaisons):
        _refuser()
    liaison = dict(tarif_rang=tarif_rang, tarif_empreinte=empreinte, appareil=meta.appareil,
                   cle_idempotence=meta.cle, empreinte_arguments=recu['empreinte_arguments'], recu_le=recu['recu_le'])
    liaison['preuve_sha256'] = _sha(liaison)
    stockage.maillons(DEPARTEMENT, REGISTRE).append(liaison, rang_attendu=len(liaisons))
    return empreinte, len(liaisons)


def lire(cnx, tarif_rang):
    """None signifie sans liaison prouvée; une liaison contradictoire est toujours refusée."""
    from m6_material_control.livre_prix import marquage_source_document

    _connexion(cnx)
    _rang(tarif_rang)
    liaison = next((liaison for liaison in _liaisons(cnx) if liaison['tarif_rang'] == tarif_rang), None)
    if liaison is None:
        return None
    maillon, empreinte = _prix(cnx, tarif_rang)
    recu = _recu(cnx, liaison['appareil'], liaison['cle_idempotence'])
    if (empreinte != liaison['tarif_empreinte'] or recu['statut'] != 'ok'
            or recu['empreinte_arguments'] != liaison['empreinte_arguments'] or recu['recu_le'] != liaison['recu_le']):
        _refuser()
    reponse = codec.decoder(recu['reponse'])
    if type(reponse) is not dict or set(reponse) != {'ok', 'resultat'}:
        _refuser()
    attendu = dict(tarif_rang=tarif_rang, prix_unitaire_decimal=maillon['prix_unitaire'],
                   tarif_source_sha256=empreinte,
                   unite=maillon['unite'], devise='CAD', marquage_source=marquage_source_document(
                       maillon.get('source_document')))
    r = reponse.get('resultat')
    if type(r) is not dict or set(r) != {'accepte', 'resultat'}:
        _refuser()
    donnees = r.get('resultat')
    if (reponse.get('ok') is not True or r.get('accepte') is not True
            or type(donnees) is not dict or set(donnees) != set(attendu)
            or type(donnees['tarif_rang']) is not int or type(donnees['prix_unitaire_decimal']) is not str):
        _refuser()
    try:
        valide = Decimal(donnees['prix_unitaire_decimal']) == Decimal(str(maillon['prix_unitaire']))
    except (ValueError, TypeError, ArithmeticError):
        _refuser()
    if not valide or any(donnees[k] != attendu[k] for k in attendu if k != 'prix_unitaire_decimal'):
        _refuser()
    return dict(liaison)


def projeter(cnx, rang_reception):
    """Référence sans contenu; revision est l'ordinal SQL du prix, pas une version commerciale."""
    _connexion(cnx)
    _rang(rang_reception)
    liaisons = _liaisons(cnx)
    if rang_reception >= len(liaisons):
        _refuser()
    original = liaisons[rang_reception]
    liaison = lire(cnx, original['tarif_rang'])
    if liaison != original:
        _refuser()
    return dict(source_id=liaison['preuve_sha256'], revision=liaison['tarif_rang'] + 1,
                horodatage=liaison['recu_le'])
