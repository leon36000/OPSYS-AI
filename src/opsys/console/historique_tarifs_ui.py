"""Consultation privée des prix déclarés, sources bornées et relues après rendu."""
import json
import re
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from m6_material_control import (
    fournisseurs,
    fournisseurs_console,
    historique_prix,
    historique_prix_console,
    tarif_soumission,
)

from opsys.stockage.maillons import copier_maillons_avec_metadonnees

from . import catalogue_materiaux_ui as catalogue
from . import fournisseurs_ui, metier, pages
from . import memoire_chantier as autorite
from . import preparation_chantier as lecture

M6 = 'm06-material-control'
CHAMPS = {'fournisseur_id', 'debut', 'limite', 'source_attendue'}


def _encoder(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True, allow_nan=False).encode('utf-8')


def arguments(materiau_id, params):
    if (re.fullmatch(r'[a-zA-Z0-9_.:\-]{1,100}', materiau_id) is None
            or set(params) - CHAMPS or any(len(params.getlist(k)) != 1 for k in params)):
        raise ValueError('paramètres invalides')
    if 'fournisseur_id' not in params:
        if params:
            raise ValueError('fournisseur explicite requis')
        return None
    fournisseur_id = params['fournisseur_id']
    if not tarif_soumission._texte(fournisseur_id, 200):
        raise ValueError('fournisseur invalide')
    debut = catalogue.entier(params.get('debut', '0'))
    limite = catalogue.entier(params.get('limite', '25'))
    source = params.get('source_attendue')
    if (not 1 <= limite <= 50 or (debut and source is None)
            or (source is not None and re.fullmatch('[0-9a-f]{64}', source) is None)):
        raise ValueError('pagination invalide')
    return dict(materiau_id=materiau_id, fournisseur_id=fournisseur_id,
                debut=debut, limite=limite, source_attendue=source)


def _fournisseurs(cnx):
    lecture._borner(cnx, M6, 'fournisseurs')
    return copier_maillons_avec_metadonnees(cnx, departement=M6, registre='fournisseurs')


def _appel(cnx, deps, session, nom, args):
    brut = metier.executer(cnx, deps, session, nom, args)
    lecture._sortie(brut)
    r = brut.get('resultat') if type(brut) is dict and brut.get('ok') is True else None
    if type(r) is not dict or type(r.get('accepte')) is not bool:
        raise lecture.Refus('SOURCE-REPONSE-INCOHERENTE')
    if r['accepte'] is False:
        raise lecture.Refus('SOURCE-INDISPONIBLE')
    if set(r) != {'accepte', 'resultat'} or type(r['resultat']) is not dict:
        raise lecture.Refus('SOURCE-REPONSE-INCOHERENTE')
    return r['resultat']


def verifier_courant(cnx, session, vue):
    autorite._admin(cnx, session)
    if _fournisseurs(cnx).empreinte_snapshot_calculee != vue['source_fournisseurs']:
        raise lecture.Refus('SOURCE-MODIFIEE')
    if (vue['historique'] is not None and historique_prix_console.capturer(cnx).empreinte_snapshot_calculee
            != vue['historique']['source_sql']):
        raise lecture.Refus('SOURCE-MODIFIEE')
    autorite._admin(cnx, session)


def lire(cnx, deps, session, materiau_id, args):
    autorite._admin(cnx, session)
    source = _fournisseurs(cnx)
    lignes = []
    for i, ligne in enumerate(source.lignes):
        if type(ligne.rang) is not int or ligne.rang != i:
            raise lecture.Refus('SOURCE-INVALIDE')
        lignes.append(ligne.maillon)
    tarif_soumission.verifier_journal_fournisseurs(lignes)
    fiches = fournisseurs.lister_fournisseurs(lignes)
    # Le lecteur historique préserve les noms valides anciens au-delà de la borne de saisie actuelle.
    page = [fournisseurs_console._projection(f) for f in fiches[:25]]
    attendu = dict(fournisseurs=[dict(fournisseur_id=f['fournisseur_id'], nom=f['nom']) for f in page],
                   total=len(fiches), suivant=25 if len(fiches) > 25 else None)
    reel = _appel(cnx, deps, session, 'm6_lister_fournisseurs_console', dict(debut=0, limite=25))
    if _encoder(reel) != _encoder(attendu):
        raise lecture.Refus('SOURCE-REPONSE-INCOHERENTE')
    historique = None
    if args is not None:
        snapshot = historique_prix_console.capturer(cnx)
        historique = historique_prix_console.projeter(snapshot, args)
        lecture._sortie(historique)
        reel = _appel(cnx, deps, session, historique_prix_console.NOM, args)
        if _encoder(reel) != _encoder(historique):
            raise lecture.Refus('SOURCE-REPONSE-INCOHERENTE')
    vue = dict(materiau_id=materiau_id, fournisseurs=attendu, historique=historique,
               source_fournisseurs=source.empreinte_snapshot_calculee)
    lecture._sortie(vue)
    verifier_courant(cnx, session, vue)
    return vue


def contenu(vue, prefixe, args):
    base = prefixe + catalogue.BASE + '/' + pages._segment(vue['materiau_id'])
    route = base + '/tarifs/historique'
    corps = (f'<p><a href="{pages.e(base)}">Fiche matériau</a></p>'
             '<h2>Historique des tarifs déclarés</h2>'
             f'<p>Matériau exact : {pages.e(vue["materiau_id"])}</p>'
             '<p>Choisir explicitement un fournisseur. Les 25 premiers noms actuels du répertoire sont proposés; '
             'saisir l’identifiant exact pour un autre fournisseur ou une référence historique.</p>'
             f'<p><a href="{pages.e(prefixe + fournisseurs_ui.BASE)}">Répertoire complet des fournisseurs</a></p>'
             f'<form method="get" action="{pages.e(route)}">'
             '<label>Identifiant fournisseur<input name="fournisseur_id" list="fournisseurs-historique" '
             f'maxlength="200" required value="{pages.e(args["fournisseur_id"] if args else "")}"></label>'
             '<datalist id="fournisseurs-historique">')
    for f in vue['fournisseurs']['fournisseurs']:
        corps += f'<option value="{pages.e(f["fournisseur_id"])}">{pages.e(f["nom"])}</option>'
    corps += '</datalist><button>Consulter l’historique</button></form>'
    h = vue['historique']
    if h is None:
        return corps + '<p>Aucun fournisseur choisi; aucun livre de prix consulté.</p>'
    corps += f'<p>Fournisseur exact : {pages.e(h["fournisseur_id"])}</p>'
    for avertissement in h['avertissements']:
        corps += f'<p>{pages.e(avertissement)}</p>'
    corps += (f'<p>{h["total"]} version(s) du couple exact.</p>'
              f'<p>Source du couple : {pages.e(h["source"])}</p>'
              f'<p>Snapshot du livre : {pages.e(h["source_snapshot"])}</p>'
              f'<p>Métadonnées SQL : {pages.e(h["source_sql"])}</p>'
              '<p>Les empreintes détectent un changement relu; elles n’authentifient pas la base ou un document.</p>')
    if not h['lignes']:
        corps += ('<p>Aucun tarif enregistré pour ce couple exact.</p>' if h['total'] == 0
                  else '<p>Fin des versions pour cette page.</p>')
    else:
        corps += ('<table><thead><tr><th>Version / rang SQL</th><th>Prix déclaré / devise</th><th>Unité déclarée</th>'
                  '<th>Date commerciale déclarée</th><th>Document déclaré / qualité</th>'
                  '<th>Dernière écriture</th><th>Source de la ligne</th></tr></thead><tbody>')
        for ligne in h['lignes']:
            corps += '<tr>'
            valeurs = [str(ligne['version_du_couple']) + ' / ' + str(ligne['rang_sql']),
                       (ligne['prix_unitaire_decimal'] or 'PRIX_NON_REPRESENTABLE') + ' ' + ligne['devise'],
                       ligne['unite'] if ligne['unite'] is not None else 'UNITE_NON_DOCUMENTEE',
                       ligne['date_effet'], (ligne['source_document'] or 'Sans document source')
                       + ' / ' + ligne['marquage_source'] + ' / ' + ', '.join(ligne['avertissements']),
                       'Oui (pas un prix utilisable confirmé)' if ligne['derniere_ecriture'] else 'Non',
                       ligne['source_entree']]
            corps += ''.join(f'<td>{pages.e(v)}</td>' for v in valeurs) + '</tr>'
        corps += '</tbody></table>'
    for offset, label in [(max(0, h['debut'] - args['limite']) if h['debut'] else None, 'Page précédente'),
                          (h['suivant'], 'Page suivante')]:
        if offset is not None:
            query = dict(fournisseur_id=h['fournisseur_id'], debut=offset,
                         limite=args['limite'], source_attendue=h['source'])
            corps += f'<p><a href="{pages.e(route + "?" + urlencode(query))}">{label}</a></p>'
    return corps


def creer_router(*, session_page, cnx_factory, deps, prefixe, rendre):
    router = APIRouter()

    @router.get(catalogue.BASE + '/{materiau_id}/tarifs/historique')
    def page(materiau_id: str, request: Request):
        session = session_page(request)
        try:
            args = arguments(materiau_id, request.query_params)
        except (TypeError, ValueError):
            raise HTTPException(400, 'Choisir un matériau, un fournisseur et une pagination valides') from None
        try:
            with cnx_factory() as cnx:
                vue = lire(cnx, deps, session, materiau_id, args)
                reponse = rendre(session, 'Historique des tarifs', contenu(vue, prefixe, args))
                if len(reponse.body) > 131072:
                    raise lecture.Refus('SORTIE-TROP-VOLUMINEUSE')
                verifier_courant(cnx, session, vue)
        except PermissionError:
            raise HTTPException(403, 'Accès admin requis') from None
        except historique_prix.Refus as exc:
            if exc.code == 'SOURCE-PERIMEE':
                raise HTTPException(409, 'Source périmée. Recommencer depuis la fiche matériau.') from None
            raise HTTPException(503, 'Historique indisponible; vérifier les sources') from None
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
            raise HTTPException(503, 'Historique indisponible; vérifier les sources') from None
        return reponse

    return router
