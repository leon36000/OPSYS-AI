"""Revue explicite du lot CSV et reçu historique; transaction jusqu’au dernier contrôle de rendu."""
import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from m6_material_control import import_tarifs_confirmation as port

from .. import idempotence, stockage
from ..stockage import codec
from . import import_tarifs_ui as apercu
from . import memoire_chantier as autorite
from . import metier, pages, prefill_ui
from . import preparation_chantier as lecture

ROUTE = apercu.ROUTE + '/confirmer'
CHAMPS = apercu._CHAMPS | {'preparation_attendue', 'mutation_id', 'approbation'}


def formulaire(session, prefixe, arguments, vue):
    if vue['statut'] != 'A_REVOIR' or vue['candidats_revalides'] != vue['total_lignes']:
        return ''
    valeurs = dict(csrf=session.csrf, mutation_id=str(uuid.uuid4()), source_attendue=vue['source'],
        preparation_attendue=vue['preparation_sha256'], fournisseur_id=arguments['fournisseur_id'],
        source_document=arguments['source_document'], separateur=arguments['separateur'])
    valeurs.update({'mapping_' + k: v for k, v in arguments['mapping_colonnes'].items()})
    return ('<h3>Confirmer les versions tarifaires revues</h3>'
            f'<form method="post" enctype="multipart/form-data" action="{pages.e(prefixe + ROUTE)}" class="pile">'
            + prefill_ui.caches(valeurs)
            + '<p>Vérifier les lignes ci-dessus, puis sélectionner à nouveau exactement le même CSV. '
            'La confirmation ajoute toutes les versions tarifaires ou aucune. Conserver ce formulaire et '
            'le même fichier pour réessayer en cas de réponse perdue.</p>'
            '<label>Même CSV UTF-8 (1 Mio maximum)'
            '<input name="source_csv" type="file" accept=".csv,text/csv" required></label>'
            '<button name="approbation" value="confirmer">Confirmer les tarifs revus</button></form>')


def arguments(champs, source):
    if (champs['approbation'] != 'confirmer'
            or re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}',
                            champs['mutation_id']) is None
            or any(re.fullmatch('[0-9a-f]{64}', champs[k]) is None
                   for k in ('source_attendue', 'preparation_attendue'))):
        raise HTTPException(400, 'Confirmation explicite ou référence invalide')
    return dict(source_csv_utf8=source, mapping_colonnes={k: champs['mapping_' + k] for k in apercu._MAPPING},
        separateur=champs['separateur'], fournisseur_id=champs['fournisseur_id'],
        source_document=champs['source_document'],
        source_attendue=champs['source_attendue'], preparation_attendue=champs['preparation_attendue'])


def relire(cnx, session, args, mutation_id):
    autorite._admin(cnx, session)
    meta = idempotence.Meta(mutation_id, 'console:' + session.utilisateur, datetime.now(UTC).isoformat())
    durable = port._mutation(cnx, meta)
    if (durable is None or durable['outil'] != port.NOM
            or durable['empreinte_arguments'] != idempotence.empreinte_arguments(args)):
        raise lecture.Refus('SOURCE-REPONSE-INCOHERENTE')
    # Relecture historique indépendante du retour du dispatcher, sans réclamer ni réécrire.
    recu = port._rejouer(cnx, meta, idempotence.Reclamation(True, codec.decoder(durable['reponse'])), args)
    lecture._sortie(recu)
    autorite._admin(cnx, session)
    return recu


def contenu(recu, prefixe):
    corps = ('<h2>Reçu de confirmation des tarifs</h2><p>Versions historiques confirmées pour ce lot. '
             'Les prix courants peuvent avoir changé depuis. Aucun achat ni envoi fournisseur.</p>'
             f'<p>Référence déclarée : {pages.e(recu["source_document"])}</p>'
             f'<p>Fournisseur : {pages.e(recu["fournisseur_id"])} · {recu["nombre_tarifs"]} version(s).</p>'
             '<table><thead><tr><th>Ligne</th><th>Matériau</th><th>Prix confirmé</th><th>Version et preuve</th>'
             '</tr></thead><tbody>')
    for ligne in recu['tarifs']:
        valeurs = [ligne['numero_ligne'], ligne['materiau_id'],
            ligne['prix_unitaire_decimal'] + ' ' + ligne['devise'] + ' / ' + ligne['unite'],
            str(ligne['tarif_rang']) + ' · ' + ligne['tarif_source_sha256']]
        corps += '<tr>' + ''.join('<td>' + pages.e(v) + '</td>' for v in valeurs) + '</tr>'
    corps += '</tbody></table><details><summary>Preuves du lot</summary>'
    for cle in ('lot_id', 'source', 'source_sha256', 'preparation_sha256', 'preuve_lot_sha256', 'jour_reference'):
        corps += f'<p>{pages.e(cle)} : {pages.e(recu[cle])}</p>'
    return corps + f'</details><p><a href="{pages.e(prefixe + apercu.ROUTE)}">Préparer une autre liste</a></p>'


def creer_router(*, session_page, cnx_factory, deps, prefixe, verifier_formulaire, rendre):
    router = APIRouter()

    @router.post(ROUTE)
    async def confirmer(request: Request):
        session = session_page(request)
        try:
            with cnx_factory() as cnx, stockage.transaction():
                autorite._admin(cnx, session)
                champs, source = await apercu.extraire(request, champs_attendus=CHAMPS)
                verifier_formulaire(champs, session)
                args = arguments(champs, source)
                brut = metier.executer(cnx, deps, session, port.NOM, args, mutation_id=champs['mutation_id'])
                lecture._sortie(brut)
                r = brut.get('resultat') if type(brut) is dict and brut.get('ok') is True else None
                if type(r) is not dict or r.get('accepte') is not True:
                    code = r.get('raison') if type(r) is dict else None
                    if code in {'IDENTITE', 'RECEPTION-ABSENTE'}:
                        raise PermissionError
                    if code in {'SOURCE-PERIMEE', 'SOURCE-MODIFIEE', 'MUTATION-CONFLIT'}:
                        raise HTTPException(409, 'Intention ou sources modifiées; préparer à nouveau la liste')
                    if code in {'SOURCE_TROP_VOLUMINEUSE', 'CSV_TROP_VOLUMINEUX', 'MAPPING_TROP_VOLUMINEUX'}:
                        raise HTTPException(413, 'Liste de prix supérieure aux limites autorisées')
                    if code in {'ARGUMENTS', 'LOT-A-CORRIGER', 'CSV_INVALIDE', 'MAPPING_COLONNES_INVALIDE',
                                'MAPPING_INVALIDE', 'SOURCE_INVALIDE', 'ENTETES_INVALIDES', 'CSV_LIGNE_INVALIDE'}:
                        raise HTTPException(400, 'Vérifier le CSV, les colonnes et les champs déclarés')
                    raise lecture.Refus('SOURCE-INDISPONIBLE')
                attendu = relire(cnx, session, args, champs['mutation_id'])
                if apercu._encoder(r) != apercu._encoder(attendu):
                    raise lecture.Refus('SOURCE-REPONSE-INCOHERENTE')
                reponse = rendre(session, 'Reçu de confirmation des tarifs', contenu(attendu['resultat'], prefixe))
                if len(reponse.body) > 131072:
                    raise lecture.Refus('SORTIE-TROP-VOLUMINEUSE')
                if apercu._encoder(relire(cnx, session, args, champs['mutation_id'])) != apercu._encoder(attendu):
                    raise lecture.Refus('SOURCE-MODIFIEE')
                autorite._admin(cnx, session)
                return reponse
        except PermissionError:
            raise HTTPException(403, 'Accès admin requis') from None
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
            raise HTTPException(503, 'Confirmation indisponible; vérifier les sources') from None

    return router
