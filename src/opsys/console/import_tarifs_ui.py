"""Aperçu privé d’une liste CSV : vrai T0 comparé aux sources, aucun prix appliqué."""
import json
import re
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from m6_material_control import import_tarifs, import_tarifs_console, import_tarifs_csv
from starlette.datastructures import UploadFile
from starlette.requests import Request as RequeteBrute

from . import catalogue_materiaux_ui as catalogue
from . import fournisseurs_ui, metier, pages, prefill_ui
from . import memoire_chantier as autorite
from . import preparation_chantier as lecture
from .memoire_ingestion_ui import _corps_borne, _media

ROUTE = catalogue.BASE + '/tarifs/importer'
_MAPPING = ('materiau_id', 'unite', 'prix_unitaire_decimal', 'devise', 'date_effet')
_CHAMPS = {'csrf', 'fournisseur_id', 'source_document', 'separateur', 'source_attendue'} | {
    'mapping_' + k for k in _MAPPING}


async def extraire(request, *, champs_attendus=None):
    champs_attendus = _CHAMPS if champs_attendus is None else champs_attendus
    if request.query_params:
        raise HTTPException(400, 'Paramètres invalides')
    media, boundary = _media(request)
    if media != 'multipart/form-data' or type(boundary) is not str or not 1 <= len(boundary) <= 70:
        raise HTTPException(415, 'Formulaire multipart requis')
    brut = await _corps_borne(request, maximum=import_tarifs.MAX_SOURCE + 65536)
    recu = False

    async def recevoir():
        nonlocal recu
        if recu:
            return {'type': 'http.disconnect'}
        recu = True
        return {'type': 'http.request', 'body': brut, 'more_body': False}

    clone = RequeteBrute(request.scope, receive=recevoir)
    form = None
    try:
        form = await clone.form(max_files=1, max_fields=len(champs_attendus), max_part_size=16384)
        items = form.multi_items()
        noms = [k for k, _ in items]
        valeurs = dict(items)
        if len(noms) != len(set(noms)) or set(noms) != champs_attendus | {'source_csv'}:
            raise HTTPException(400, 'Champs multipart invalides')
        if any(type(valeurs[k]) is not str for k in champs_attendus):
            raise HTTPException(400, 'Champs texte requis')
        fichier = valeurs['source_csv']
        if not isinstance(fichier, UploadFile) or not fichier.filename:
            raise HTTPException(400, 'Fichier CSV requis')
        source = await fichier.read(import_tarifs.MAX_SOURCE + 1)
        if len(source) > import_tarifs.MAX_SOURCE:
            raise HTTPException(413, 'CSV supérieur à 1 Mio')
        return {k: valeurs[k] for k in champs_attendus}, source.decode('utf-8')
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(400, 'CSV ou formulaire invalide') from None
    finally:
        if form is not None:
            await form.close()


def _encoder(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True, allow_nan=False).encode('utf-8')


def verifier_courant(cnx, session, vue):
    autorite._admin(cnx, session)
    if import_tarifs_console._sources(import_tarifs_console.capturer(cnx)) != vue['sources_sql']:
        raise lecture.Refus('SOURCE-MODIFIEE')
    autorite._admin(cnx, session)


def lire(cnx, deps, session, args):
    autorite._admin(cnx, session)
    if args['source_attendue'] is not None and (type(args['source_attendue']) is not str
            or re.fullmatch('[0-9a-f]{64}', args['source_attendue']) is None):
        raise HTTPException(400, 'Référence de source invalide')
    jour = datetime.now(UTC).date().isoformat()
    preparation = import_tarifs_csv.preparer(args['source_csv_utf8'].encode('utf-8'),
        mapping_colonnes=args['mapping_colonnes'], separateur=args['separateur'],
        fournisseur_id=args['fournisseur_id'], source_document=args['source_document'], jour_reference=jour)
    attendu = import_tarifs_console.projeter(import_tarifs_console.capturer(cnx), preparation, jour)
    lecture._sortie(attendu)
    if args['source_attendue'] is not None and args['source_attendue'] != attendu['source']:
        raise HTTPException(409, 'Les sources ont changé; préparer à nouveau la liste')
    brut = metier.executer(cnx, deps, session, import_tarifs_console.NOM, args)
    lecture._sortie(brut)
    r = brut.get('resultat') if type(brut) is dict and brut.get('ok') is True else None
    if type(r) is not dict or r.get('accepte') is not True or type(r.get('resultat')) is not dict:
        code = r.get('raison') if type(r) is dict else None
        if code == 'IDENTITE':
            raise PermissionError
        if code == 'SOURCE-PERIMEE':
            raise HTTPException(409, 'Les sources ont changé; préparer à nouveau la liste')
        raise lecture.Refus('SOURCE-INDISPONIBLE')
    if _encoder(r['resultat']) != _encoder(attendu):
        raise lecture.Refus('SOURCE-REPONSE-INCOHERENTE')
    verifier_courant(cnx, session, attendu)
    return attendu


def formulaire(session, prefixe, fournisseur_id):
    corps = (f'<p><a href="{pages.e(prefixe + catalogue.BASE)}">Matériaux et tarifs</a> · '
             f'<a href="{pages.e(prefixe + fournisseurs_ui.BASE)}">Répertoire des fournisseurs</a></p>'
             '<h2>Préparer une liste de prix CSV</h2><p>Aucun prix appliqué. Sélectionner un CSV UTF-8 '
             'de 50 lignes au plus et nommer explicitement les colonnes. Les identifiants doivent '
             'correspondre aux fiches internes; aucune correspondance fournisseur n’est devinée.</p>'
             f'<form method="post" enctype="multipart/form-data" action="{pages.e(prefixe + ROUTE)}" class="pile">'
             + prefill_ui.caches(dict(csrf=session.csrf, source_attendue=''))
             + '<label>Identifiant fournisseur exact<input name="fournisseur_id" maxlength="200" required '
             f'value="{pages.e(fournisseur_id)}"></label>'
             '<label>Référence documentaire déclarée<input name="source_document" maxlength="1000" required></label>'
             '<label>CSV UTF-8 (1 Mio maximum)<input name="source_csv" type="file" accept=".csv,text/csv" required>'
             '</label><label>Séparateur<select name="separateur" required>'
             '<option value="">Choisir explicitement</option><option value=";">Point-virgule</option>'
             '<option value=",">Virgule</option></select></label>')
    for champ, libelle in [('materiau_id', 'Identifiant matériau'), ('unite', 'Unité'),
                          ('prix_unitaire_decimal', 'Prix unitaire'), ('devise', 'Devise'),
                          ('date_effet', 'Date effective')]:
        corps += (f'<label>Nom exact de la colonne — {libelle}'
                  f'<input name="mapping_{champ}" maxlength="200" required></label>')
    return corps + '<button>Préparer pour revue</button></form>'


def contenu(vue, prefixe, document):
    corps = (f'<p><a href="{pages.e(prefixe + ROUTE)}">Préparer une autre liste</a></p>'
             '<h2>Aperçu de la liste de prix</h2><p>Aucun prix appliqué à cette étape de revue.</p>'
             f'<p>Référence déclarée : {pages.e(document)}</p><p>État : {pages.e(vue["statut"])} · '
             f'{vue["candidats_revalides"]} candidat(s) revalidé(s) sur {vue["total_lignes"]}.</p>'
             '<p>Les noms et le prix précédent proviennent des sources courantes. '
             'Une référence documentaire ne prouve pas l’authenticité du tarif.</p>'
             '<table><thead><tr><th>Ligne</th><th>Matériau / fournisseur actuels</th><th>Prix fourni</th>'
             '<th>Prix précédent</th><th>État / erreurs</th></tr></thead><tbody>')
    for ligne in vue['lignes']:
        candidat, saisie = ligne['candidat'], ligne['preparation_saisie']
        fourni = (candidat['prix_unitaire_decimal'] + ' ' + candidat['devise'] + ' / ' + candidat['unite']
                  + ' · ' + candidat['date_effet']) if candidat is not None else 'Candidat invalide'
        noms = ((saisie['materiau_nom'] + ' / ' + saisie['fournisseur_nom']) if saisie is not None
                else candidat['materiau_id'] if candidat is not None else 'À corriger dans le CSV')
        ancien = saisie['ancien_tarif'] if saisie is not None else None
        precedent = (ancien['cout_unitaire_decimal'] + ' ' + ancien['devise'] + ' / ' + ancien['unite']
                     + ' · ' + ancien['date_effet']) if ancien is not None else 'Aucun prix précédent utilisable'
        if saisie is not None and saisie['ancien_indisponible']:
            precedent += ' · ' + saisie['ancien_indisponible']
        valeurs = [ligne['numero_ligne'], noms, fourni, precedent,
                   ligne['statut'] + ' · ' + ', '.join(ligne['erreurs'])]
        corps += '<tr>' + ''.join(f'<td>{pages.e(v)}</td>' for v in valeurs) + '</tr>'
    corps += '</tbody></table><details><summary>Sources et contrôles</summary>'
    for cle in ('source', 'source_sha256', 'mapping_sha256', 'preparation_sha256', 'jour_reference'):
        corps += f'<p>{pages.e(cle)} : {pages.e(vue[cle])}</p>'
    for cle, valeur in vue['sources_sql'].items():
        corps += f'<p>{pages.e(cle)} : {pages.e(valeur)}</p>'
    return corps + '</details>'


def creer_router(*, session_page, cnx_factory, deps, prefixe, verifier_formulaire, rendre):
    router = APIRouter()

    def fini(cnx, session, corps, vue=None):
        reponse = rendre(session, 'Préparation des tarifs', corps)
        if len(reponse.body) > 131072:
            raise lecture.Refus('SORTIE-TROP-VOLUMINEUSE')
        if vue is not None:
            verifier_courant(cnx, session, vue)
        autorite._admin(cnx, session)
        return reponse

    @router.get(ROUTE)
    def nouveau(request: Request):
        session = session_page(request)
        p = request.query_params
        if set(p) - {'fournisseur_id'} or any(len(p.getlist(k)) != 1 for k in p):
            raise HTTPException(400, 'Paramètres invalides')
        fournisseur_id = p.get('fournisseur_id', '')
        if len(fournisseur_id) > 200 or any(not c.isprintable() for c in fournisseur_id):
            raise HTTPException(400, 'Identifiant fournisseur invalide')
        try:
            with cnx_factory() as cnx:
                autorite._admin(cnx, session)
                return fini(cnx, session, formulaire(session, prefixe, fournisseur_id))
        except PermissionError:
            raise HTTPException(403, 'Accès admin requis') from None
        except (ValueError, TypeError, KeyError, UnicodeError):
            raise HTTPException(503, 'Formulaire indisponible; vérifier les sources') from None

    @router.post(ROUTE)
    async def preparer(request: Request):
        session = session_page(request)
        try:
            with cnx_factory() as cnx:
                autorite._admin(cnx, session)
                champs, source = await extraire(request)
                verifier_formulaire(champs, session)
                args = dict(source_csv_utf8=source, mapping_colonnes={k: champs['mapping_' + k] for k in _MAPPING},
                            separateur=champs['separateur'], fournisseur_id=champs['fournisseur_id'],
                            source_document=champs['source_document'],
                            source_attendue=champs['source_attendue'] or None)
                vue = lire(cnx, deps, session, args)
                from . import import_tarifs_confirmation_ui as confirmation

                corps = (contenu(vue, prefixe, args['source_document'])
                         + confirmation.formulaire(session, prefixe, args, vue))
                return fini(cnx, session, corps, vue)
        except PermissionError:
            raise HTTPException(403, 'Accès admin requis') from None
        except import_tarifs.Refus:
            raise HTTPException(400, 'Vérifier le CSV, les colonnes et les champs déclarés') from None
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
            raise HTTPException(503, 'Préparation indisponible; vérifier les sources') from None

    from . import import_tarifs_confirmation_ui

    router.include_router(import_tarifs_confirmation_ui.creer_router(
        session_page=session_page, cnx_factory=cnx_factory, deps=deps, prefixe=prefixe,
        verifier_formulaire=verifier_formulaire, rendre=rendre))
    return router
