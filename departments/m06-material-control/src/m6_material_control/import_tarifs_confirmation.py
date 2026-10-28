"""Confirmation privée tout-ou-rien; les writers de tarifs restent seuls propriétaires."""
import re

from sqlalchemy import LargeBinary, cast, func, select

from opsys import idempotence, receptions_tarifs, stockage
from opsys.outils import Autonomie, Outil, valider_arguments
from opsys.stockage import codec
from opsys.stockage.schema import MUTATIONS_APPLIQUEES, REGISTRES

from . import catalogue_console as acces
from . import (
    catalogue_materiaux,
    historique_prix,
    historique_prix_console,
    import_tarifs,
    import_tarifs_console,
    import_tarifs_csv,
    prix_console,
)
from .tarif_soumission import _texte

NOM = 'm6_confirmer_import_tarifs_console'
VERSION = 'm6-import-tarifs-recu-v1'
CHAMPS_RECU = {'version', 'statut', 'lot_id', 'source', 'preparation_sha256', 'source_sha256',
               'jour_reference', 'fournisseur_id', 'source_document', 'nombre_tarifs', 'tarifs', 'preuve_lot_sha256'}
CHAMPS_TARIF = {'position', 'numero_ligne', 'materiau_id', 'tarif_rang', 'tarif_source_sha256',
                'prix_unitaire_decimal', 'unite', 'devise', 'marquage_source', 'arguments_sha256'}


def _refuser(code='RECU-INVALIDE'):
    raise catalogue_materiaux.CatalogueRefuse(code)


def schema():
    champs = dict(import_tarifs_console.schema()['properties'])
    champs.update({cle: {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}
                   for cle in ('source_attendue', 'preparation_attendue')})
    return prix_console.schema(champs)


def _empreinte(valeur):
    return import_tarifs._sha(valeur)


def _hex(valeur):
    return type(valeur) is str and re.fullmatch('[0-9a-f]{64}', valeur) is not None


def _enfant(meta, position):
    cle = 'm6-import-tarifs-ligne-v1:' + _empreinte([VERSION, meta.appareil, meta.cle, position])
    return idempotence.Meta(cle, meta.appareil, meta.horodatage_appareil)


def _lot_id(meta):
    return _empreinte([NOM, meta.appareil, meta.cle])


def _preparer(arguments, jour):
    return import_tarifs_csv.preparer(arguments['source_csv_utf8'].encode('utf-8'),
        mapping_colonnes=arguments['mapping_colonnes'], separateur=arguments['separateur'],
        fournisseur_id=arguments['fournisseur_id'], source_document=arguments['source_document'], jour_reference=jour)


def _mutation(cnx, meta):
    # La lecture commune décode la réponse au rejeu; borner ses octets SQL avant ce décodage.
    condition = ((MUTATIONS_APPLIQUEES.c.appareil == meta.appareil)
                 & (MUTATIONS_APPLIQUEES.c.cle_idempotence == meta.cle))
    taille = cnx.execute(select(func.length(cast(MUTATIONS_APPLIQUEES.c.reponse, LargeBinary)))
                        .where(condition)).scalar_one_or_none()
    if taille is not None and taille > 65536:
        _refuser()
    return idempotence._lire(cnx, meta)


def _enfant_recu(cnx, meta, ligne):
    enfant = _mutation(cnx, _enfant(meta, ligne['position']))
    if (enfant is None or enfant['statut'] != 'ok' or enfant['outil'] != 'm6_confirmer_tarif_console'
            or not _hex(ligne['arguments_sha256']) or enfant['empreinte_arguments'] != ligne['arguments_sha256']):
        _refuser()
    reponse = codec.decoder(enfant['reponse'])
    detail = {k: v for k, v in ligne.items()
              if k not in {'position', 'numero_ligne', 'materiau_id', 'arguments_sha256'}}
    # Fermer aussi les enveloppes : ni ok=1 ni un résultat enrichi/corrompu ne valent un reçu.
    if (type(reponse) is not dict or set(reponse) != {'ok', 'resultat'} or reponse['ok'] is not True
            or type(reponse['resultat']) is not dict or set(reponse['resultat']) != {'accepte', 'resultat'}
            or reponse['resultat']['accepte'] is not True
            or type(reponse['resultat']['resultat']) is not dict
            or _empreinte(reponse['resultat']['resultat']) != _empreinte(detail)):
        _refuser()


def _rejouer(cnx, meta, reclamation, arguments):
    # La réclamation commune vérifie nom/hash, pas son statut ni le contrat de son reçu.
    durable = _mutation(cnx, meta)
    enveloppe = reclamation.reponse
    if (durable['statut'] != 'ok' or type(enveloppe) is not dict
            or set(enveloppe) != {'ok', 'resultat'} or enveloppe['ok'] is not True):
        _refuser()
    resultat = enveloppe['resultat']
    if type(resultat) is not dict or set(resultat) != {'accepte', 'resultat'} or resultat['accepte'] is not True:
        _refuser()
    recu = resultat['resultat']
    if (type(recu) is not dict or set(recu) != CHAMPS_RECU or recu['version'] != VERSION
            or recu['statut'] != 'LOT_TARIFS_CONFIRME' or recu['lot_id'] != _lot_id(meta)
            or recu['source'] != arguments['source_attendue']
            or recu['preparation_sha256'] != arguments['preparation_attendue']
            or recu['fournisseur_id'] != arguments['fournisseur_id']
            or recu['source_document'] != arguments['source_document']
            or type(recu['nombre_tarifs']) is not int or not 1 <= recu['nombre_tarifs'] <= import_tarifs.MAX_LIGNES
            or type(recu['tarifs']) is not list or len(recu['tarifs']) != recu['nombre_tarifs']
            or not _hex(recu['preuve_lot_sha256'])
            or recu['preuve_lot_sha256'] != _empreinte({k: v for k, v in recu.items() if k != 'preuve_lot_sha256'})):
        _refuser()
    # Reparser avec le JOUR ORIGINAL : un rejeu historique ne prétend pas fraîcheur actuelle.
    preparation = _preparer(arguments, recu['jour_reference'])
    if (preparation['preparation_sha256'] != recu['preparation_sha256']
            or preparation['lot']['source_sha256'] != recu['source_sha256']
            or len(preparation['lot']['lignes']) != recu['nombre_tarifs']):
        _refuser()
    precedent = None
    for ligne, preparee in zip(recu['tarifs'], preparation['lot']['lignes'], strict=True):
        candidat = preparee['candidat']
        if (type(ligne) is not dict or set(ligne) != CHAMPS_TARIF or candidat is None
                or type(ligne['tarif_rang']) is not int or not 0 <= ligne['tarif_rang'] < 10000
                or (precedent is not None and ligne['tarif_rang'] != precedent + 1)
                or type(ligne['position']) is not int or ligne['position'] != preparee['position']
                or type(ligne['numero_ligne']) is not int or ligne['numero_ligne'] != preparee['numero_ligne']
                or any(ligne[k] != candidat[k] for k in ('materiau_id', 'prix_unitaire_decimal', 'unite', 'devise'))
                or not _hex(ligne['tarif_source_sha256'])
                or ligne['marquage_source'] !=
                    prix_console.livre_prix.marquage_source_document(arguments['source_document'])):
            _refuser()
        _enfant_recu(cnx, meta, ligne)
        precedent = ligne['tarif_rang']
    return acces._borner(resultat)


def _prefixe(cnx, nombre):
    # Même représentation brute que copier_maillons_avec_metadonnees, sans recoder les JSON.
    lignes = cnx.execute(select(REGISTRES.c.rang, REGISTRES.c.cree_le, REGISTRES.c.maillon).where(
        REGISTRES.c.departement == acces.DEPARTEMENT, REGISTRES.c.registre == 'livre_prix',
        REGISTRES.c.rang < nombre).order_by(REGISTRES.c.rang))
    return _empreinte([dict(rang=r.rang, cree_le=r.cree_le.isoformat(), maillon=r.maillon) for r in lignes])


def _verifier_sources(cnx, snapshots, tarifs, arguments):
    # Reborner toutes les familles après les writers, avant le premier décodage de contrôle.
    # Le livre peut maintenant avoir EXACTEMENT 10000 entrées, contrairement à l'aperçu.
    for registre in ('catalogue_materiaux', 'fournisseurs', 'livre_prix'):
        condition = ((REGISTRES.c.departement == acces.DEPARTEMENT) & (REGISTRES.c.registre == registre))
        n, octets = cnx.execute(select(func.count(), func.sum(func.length(cast(REGISTRES.c.maillon, LargeBinary))))
                               .select_from(REGISTRES).where(condition)).one()
        if n > import_tarifs_console.MAX_SOURCES or (octets or 0) > import_tarifs_console.MAX_OCTETS:
            _refuser('SOURCES-TROP-VOLUMINEUSES')
    for registre in ('catalogue_materiaux', 'fournisseurs'):
        courant = import_tarifs_console.copier_maillons_avec_metadonnees(cnx,
            departement=acces.DEPARTEMENT, registre=registre)
        if courant.empreinte_snapshot_calculee != snapshots[registre].empreinte_snapshot_calculee:
            _refuser('SOURCE-MODIFIEE')
    livre = historique_prix_console.capturer(cnx)
    n = len(snapshots['livre_prix'].lignes)
    if (len(livre.lignes) != n + len(tarifs)
            or _prefixe(cnx, n) != snapshots['livre_prix'].empreinte_snapshot_calculee):
        _refuser('SOURCE-MODIFIEE')
    historique_prix._capturer([(x.rang, x.maillon) for x in livre.lignes])
    for ligne in tarifs:
        maillon, preuve = receptions_tarifs._prix(cnx, ligne['tarif_rang'])
        if (preuve != ligne['tarif_source_sha256'] or maillon['materiau_id'] != ligne['materiau_id']
                or maillon['fournisseur_id'] != arguments['fournisseur_id']
                or maillon.get('source_document') != arguments['source_document']):
            _refuser('SOURCE-MODIFIEE')


def _confirmer_frais(cnx, auteur, reception, meta, arguments):
    jour = reception.recu_le.date().isoformat()
    preparation = _preparer(arguments, jour)
    snapshots = import_tarifs_console.capturer(cnx)
    vue = import_tarifs_console.projeter(snapshots, preparation, jour)
    if vue['source'] != arguments['source_attendue'] or vue['preparation_sha256'] != arguments['preparation_attendue']:
        _refuser('SOURCE-PERIMEE')
    if vue['statut'] != 'A_REVOIR' or any(x['preparation_saisie'] is None for x in vue['lignes']):
        _refuser('LOT-A-CORRIGER')
    n = len(snapshots['livre_prix'].lignes)
    if n + len(vue['lignes']) > import_tarifs_console.MAX_SOURCES:
        _refuser('SOURCES-TROP-VOLUMINEUSES')
    enfants = [_enfant(meta, ligne['position']) for ligne in vue['lignes']]
    if any(_mutation(cnx, enfant) is not None for enfant in enfants):
        _refuser('MUTATION-CONFLIT')
    tarifs = []
    for ligne, enfant in zip(vue['lignes'], enfants, strict=True):
        candidat, saisie = ligne['candidat'], ligne['preparation_saisie']
        charge = dict(materiau_id=candidat['materiau_id'], fournisseur_id=arguments['fournisseur_id'],
            prix_unitaire=candidat['prix_unitaire_decimal'], date_effet=candidat['date_effet'],
            source_document=arguments['source_document'], **{k: saisie[k] for k in prix_console._ANCRE})
        with acces.contexte_mutation(enfant):
            resultat = prix_console.confirmer(**charge)
        if type(resultat) is not dict or resultat.get('accepte') is not True:
            _refuser(resultat.get('raison', 'RECU-INVALIDE') if type(resultat) is dict else 'RECU-INVALIDE')
        detail = resultat['resultat']
        if (set(detail) != CHAMPS_TARIF - {'position', 'numero_ligne', 'materiau_id', 'arguments_sha256'}
                or type(detail['tarif_rang']) is not int or detail['tarif_rang'] != n + len(tarifs)
                or any(detail[k] != candidat[k] for k in ('prix_unitaire_decimal', 'unite', 'devise'))):
            _refuser()
        tarifs.append(dict(position=ligne['position'], numero_ligne=ligne['numero_ligne'],
                           arguments_sha256=idempotence.empreinte_arguments(charge),
                           materiau_id=candidat['materiau_id'], **detail))
    for ligne in tarifs:
        _enfant_recu(cnx, meta, ligne)
    _verifier_sources(cnx, snapshots, tarifs, arguments)
    recu = dict(version=VERSION, statut='LOT_TARIFS_CONFIRME', lot_id=_lot_id(meta), source=vue['source'],
        preparation_sha256=vue['preparation_sha256'], source_sha256=vue['source_sha256'], jour_reference=jour,
        fournisseur_id=arguments['fournisseur_id'], source_document=arguments['source_document'],
        nombre_tarifs=len(tarifs), tarifs=tarifs)
    recu['preuve_lot_sha256'] = _empreinte(recu)
    resultat = acces._borner(dict(accepte=True, resultat=recu))
    import_tarifs_console._autorite(cnx, auteur)
    idempotence.finaliser(cnx, meta, dict(ok=True, resultat=resultat))
    import_tarifs_console._autorite(cnx, auteur)
    return resultat


def confirmer(source_csv_utf8, mapping_colonnes, separateur, fournisseur_id, source_document,
              source_attendue, preparation_attendue):
    try:
        cnx, auteur, reception = acces._autoriser()
        if (type(source_csv_utf8) is not str or not _hex(source_attendue) or not _hex(preparation_attendue)
                or not _texte(fournisseur_id, 200) or not _texte(source_document, 1000)
                or type(separateur) is not str or separateur not in {',', ';'}):
            _refuser('ARGUMENTS')
        if (len(source_csv_utf8) > import_tarifs.MAX_SOURCE
                or len(source_csv_utf8.encode('utf-8')) > import_tarifs.MAX_SOURCE):
            _refuser('SOURCE_TROP_VOLUMINEUSE')
        arguments = dict(source_csv_utf8=source_csv_utf8,
            mapping_colonnes=import_tarifs_csv._correspondances(mapping_colonnes),
            separateur=separateur, fournisseur_id=fournisseur_id, source_document=source_document,
            source_attendue=source_attendue, preparation_attendue=preparation_attendue)
        if valider_arguments(schema(), arguments):
            _refuser('ARGUMENTS')
        meta = acces._META.get()
        if (not isinstance(meta, idempotence.Meta) or meta.appareil != 'console:' + auteur
                or type(meta.cle) is not str or not meta.cle.strip() or len(meta.cle) > 200):
            _refuser('MUTATION-ABSENTE')
        # Tout refus devient exception avant de sortir de cette transaction/callback scope.
        with stockage.transaction():
            _mutation(cnx, meta)
            reclamation = idempotence.reclamer(cnx, meta, NOM, arguments, reception.recu_le)
            if reclamation.rejouee:
                resultat = _rejouer(cnx, meta, reclamation, arguments)
                import_tarifs_console._autorite(cnx, auteur)
                return resultat
            return _confirmer_frais(cnx, auteur, reception, meta, arguments)
    except idempotence.MutationConflit:
        return dict(accepte=False, raison='MUTATION-CONFLIT')
    except (catalogue_materiaux.CatalogueRefuse, historique_prix.Refus, import_tarifs.Refus) as exc:
        return dict(accepte=False, raison=exc.code)
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        return dict(accepte=False, raison='SOURCE-INVALIDE')


def outil():
    return Outil(nom=NOM, description='Console admin privée : confirmer toutes les lignes d’un aperçu CSV approuvé.',
                 parametres=schema(), fonction=confirmer, autonomie=Autonomie.T1)
