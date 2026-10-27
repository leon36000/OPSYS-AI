"""Aperçu privé des temps pointés du jour : vrai calcul M4, sans validation de paie."""
import hashlib
import json
import re
from datetime import datetime
from urllib.parse import urlencode

from m4_field_ops import absences_ecriture, absences_journalieres, heures_regulieres, journal_durable
from m4_field_ops.registre import Registre, VerificationError
from starlette.datastructures import QueryParams

from opsys import contexte, stockage
from opsys.outils import Autonomie, executer

from . import absences_personnes, pages
from . import memoire_chantier as autorite
from . import preparation_chantier as lecture

M4 = 'm04-field-ops'
NOM = 'm4_previsualiser_heures_regulieres'
FUSEAU = 'America/Montreal'
REFUS_METIER = frozenset({
    'REJ-SOURCES-ABSENTES', 'REJ-POINTAGES-AMBIGUS', 'REJ-INTERVENTION-AMBIGUE',
    'REJ-TECHNICIEN-AMBIGU', 'REJ-INTERVALLE-HORS-PERIODE', 'REJ-PAUSE-INCOMPLETE',
    'REJ-PAUSE-AMBIGUE', 'REJ-INTERVENTIONS-CHEVAUCHEES', 'REJ-PRECISION-MINUTE',
    'REJ-POINTAGE-INCONNU', 'REJ-PERIODE-INVALIDE',
})


def _encoder(valeur):
    return json.dumps(valeur, sort_keys=True, ensure_ascii=False, allow_nan=False).encode('utf-8')


def _cible(cnx, personne_id):
    if cnx is None or cnx is not stockage.connexion_courante() or cnx.dialect.name != 'sqlite':
        raise lecture.Refus('INSTANCE-NON-QUALIFIEE')
    try:
        cible = absences_ecriture._cible_initiale(cnx, personne_id)
    except absences_journalieres.Refus:
        raise lecture.Refus('CIBLE-NON-ADMISSIBLE') from None
    if not cible['actif'] or 'employee' not in cible['roles']:
        raise lecture.Refus('CIBLE-NON-ADMISSIBLE')
    return cible


def _t0(deps, session, arguments):
    dep = deps.get(M4)
    if dep is None or dep.module_outils != 'm4_field_ops.outils':
        raise lecture.Refus('SOURCE-INDISPONIBLE')
    outil = next((o for o in dep.charger_outils() if o.nom == NOM), None)
    if outil is None or outil.autonomie != Autonomie.T0:
        raise lecture.Refus('SOURCE-INDISPONIBLE')
    with (contexte.appele_par_appareil(contexte.IdentiteAppelante(session.utilisateur, 'admin', source='console')),
          contexte.appeler_en_tant_que(M4, origine='console')):
        reponse = executer(outil, arguments)
    if not isinstance(reponse, dict) or reponse.get('ok') is not True:
        raise lecture.Refus('SOURCE-INDISPONIBLE')
    return reponse.get('resultat')


def arguments(params):
    if set(params) != {'jour', 'personne_id'}:
        raise ValueError('jour et personne explicites requis')
    args = absences_personnes.arguments(params)
    personne = args['personne_id']
    from opsys import identite

    if not identite.identifiant_valide(personne) or personne.strip() != personne:
        raise ValueError('identifiant canonique requis')
    return dict(jour=args['jour'], personne_id=personne)


def verifier_courant(cnx, session, vue):
    autorite._admin(cnx, session)
    source = journal_durable.capturer(cnx)
    try:
        cible = _cible(cnx, vue['personne_id'])
    except lecture.Refus as exc:
        if exc.code == 'CIBLE-NON-ADMISSIBLE':
            raise lecture.Refus('SOURCE-MODIFIEE') from None
        raise
    if (source.empreinte_snapshot_calculee != vue['source_snapshot']
            or hashlib.sha256(_encoder(cible)).hexdigest() != vue['source_identite']):
        raise lecture.Refus('SOURCE-MODIFIEE')
    autorite._admin(cnx, session)


def _valider_proposition(proposition, args):
    # Le domaine et son T0 partagent du code : leur égalité ne remplace pas un schéma de sortie.
    def ref(valeur):
        return isinstance(valeur, str) and re.fullmatch('[0-9a-f]{64}', valeur) is not None

    def refs(valeur):
        return isinstance(valeur, list) and bool(valeur) and all(ref(v) for v in valeur)

    def minutes(valeur):
        return type(valeur) is int and valeur >= 0

    def intervalle(valeur, travail=False):
        cles = {'debut', 'fin', 'sources'} | ({'minutes_net_apres_pauses'} if travail else set())
        if not isinstance(valeur, dict) or set(valeur) != cles or not refs(valeur['sources']):
            return False
        for cle in ('debut', 'fin'):
            brut = valeur[cle]
            if not isinstance(brut, str) or len(brut) > 40:
                return False
            try:
                if datetime.fromisoformat(brut).tzinfo is None:
                    return False
            except ValueError:
                return False
        return not travail or minutes(valeur['minutes_net_apres_pauses'])

    try:
        if (not isinstance(proposition, dict) or set(proposition) != {
                'technicien_id', 'periode', 'categories_minutes', 'details_intervalles', 'sources',
                'empreinte_sources', 'validation_precedente'}
                or proposition['technicien_id'] != args['personne_id']
                or proposition['periode'] != dict(debut=args['jour'], fin=args['jour'], fuseau=FUSEAU)
                or not refs(proposition['sources']) or not ref(proposition['empreinte_sources'])):
            raise ValueError
        categories = proposition['categories_minutes']
        if (not isinstance(categories, dict) or set(categories) != {'travail', 'deplacement', 'pause'}
                or not all(minutes(v) for v in categories.values())):
            raise ValueError
        precedente = proposition['validation_precedente']
        if precedente is not None and (not isinstance(precedente, dict)
                or set(precedente) != {'revision', 'ligne_id'}
                or not minutes(precedente['revision']) or precedente['revision'] < 1
                or not ref(precedente['ligne_id'])):
            raise ValueError
        details = proposition['details_intervalles']
        if not isinstance(details, list) or not details:
            raise ValueError
        for detail in details:
            if (not isinstance(detail, dict) or set(detail) != {'intervention_id', 'travail', 'deplacement', 'pauses'}
                    or not isinstance(detail['intervention_id'], str) or not detail['intervention_id'].strip()
                    or len(detail['intervention_id']) > 200 or not intervalle(detail['travail'], travail=True)
                    or not intervalle(detail['deplacement']) or not isinstance(detail['pauses'], list)
                    or not all(intervalle(p) for p in detail['pauses'])):
                raise ValueError
    except (KeyError, TypeError, ValueError):
        raise lecture.Refus('SOURCE-REPONSE-INCOHERENTE') from None


def lire(cnx, deps, session, jour, personne_id):
    autorite._admin(cnx, session)
    args = arguments(QueryParams(dict(jour=jour, personne_id=personne_id)))
    cible = _cible(cnx, args['personne_id'])
    source = journal_durable.capturer(cnx)
    copie = Registre([r.maillon for r in source.lignes])
    try:
        copie.assert_chaine()
        attendu = heures_regulieres.previsualiser(copie.lire(), args['personne_id'], args['jour'], args['jour'], FUSEAU)
    except (VerificationError, KeyError, TypeError, ValueError, UnicodeError):
        raise lecture.Refus('SOURCE-INVALIDE') from None
    if attendu['accepte'] is True:
        _valider_proposition(attendu['resultat'], args)
    lecture._sortie(attendu)
    if attendu['accepte'] is not True and attendu.get('verdict', {}).get('code') not in REFUS_METIER:
        raise lecture.Refus('SOURCE-INVALIDE')
    appel = dict(technicien_id=args['personne_id'], debut=args['jour'], fin=args['jour'], fuseau=FUSEAU)
    reel = _t0(deps, session, appel)
    try:
        if (not isinstance(reel, dict) or type(reel.get('accepte')) is not bool
                or _encoder(reel) != _encoder(attendu)):
            raise lecture.Refus('SOURCE-REPONSE-INCOHERENTE')
    except (TypeError, UnicodeError):
        raise lecture.Refus('SOURCE-REPONSE-INCOHERENTE') from None
    vue = dict(**args, fuseau=FUSEAU, source_snapshot=source.empreinte_snapshot_calculee,
               source_identite=hashlib.sha256(_encoder(cible)).hexdigest())
    if attendu['accepte']:
        vue.update(etat='calcul_disponible', proposition=attendu['resultat'])
    else:
        # Le détail libre d'un refus n'est jamais transmis à l'écran.
        vue.update(etat='indisponible', code=attendu['verdict']['code'])
    vue = lecture._sortie(vue)
    verifier_courant(cnx, session, vue)
    return vue


def url_jour_personne(jour, personne_id, prefixe):
    from opsys import identite

    if not identite.identifiant_valide(personne_id) or personne_id.strip() != personne_id:
        return None
    return prefixe + '/crm/journal-equipes/temps?' + urlencode(dict(jour=jour, personne_id=personne_id))


def contenu(vue, prefixe):
    retour = prefixe + '/crm/journal-equipes?' + urlencode(dict(jour=vue['jour']))
    corps = (f'<p><a href="{pages.e(retour)}">Retour au journal</a></p>'
             '<h2>Aperçu des temps pointés — calcul M4</h2>'
             f'<p>Jour : {pages.e(vue["jour"])} · Personne : {pages.e(vue["personne_id"])} · '
             f'Fuseau : {pages.e(vue["fuseau"])}</p>'
             '<p>Proposition calculée depuis les pointages, sans validation de paie. '
             'Elle ne prouve ni journée complète, ni présence de toute l’équipe, ni heures payables. '
             'Aucun taux ou montant appliqué.</p>')
    if vue['etat'] == 'indisponible':
        corps += ('<p>Calcul indisponible. Aucun total déduit : '
                  f'{pages.e(vue["code"])}. Vérifier les sources de pointage M4.</p>')
    else:
        proposition = vue['proposition']
        categories = proposition['categories_minutes']
        corps += ('<dl>' + ''.join(f'<dt>{titre}</dt><dd>{categories[cle]}</dd>' for cle, titre in (
            ('travail', 'Minutes de travail net après pauses'), ('deplacement', 'Minutes de déplacement'),
            ('pause', 'Minutes de pause'))) + '</dl>'
            '<table><thead><tr><th>Intervention</th><th>Catégorie</th><th>Début local</th><th>Fin locale</th>'
            '<th>Références source</th></tr></thead><tbody>')
        for detail in proposition['details_intervalles']:
            for categorie, intervalle in [('Travail sur site avant déduction des pauses', detail['travail']),
                                         ('Déplacement', detail['deplacement']),
                                         *[('Pause', p) for p in detail['pauses']]]:
                valeurs = [detail['intervention_id'], categorie, intervalle['debut'], intervalle['fin'],
                           ', '.join(intervalle['sources'])]
                corps += '<tr>' + ''.join(f'<td>{pages.e(v)}</td>' for v in valeurs) + '</tr>'
        corps += ('</tbody></table><p>Ces intervalles sur site incluent les pauses; le total travail ci-dessus '
                  'les déduit. Aucun cumul entre ces deux présentations.</p>')
    corps += ('<details><summary>Sources de consultation</summary>'
              f'<p>Snapshot M4 : {pages.e(vue["source_snapshot"])}</p>'
              f'<p>Admissibilité actuelle : {pages.e(vue["source_identite"])}</p></details>')
    return corps + absences_personnes.formulaire_consultation(vue['jour'], prefixe)


def creer_router(*, session_page, cnx_factory, deps, prefixe, rendre):
    from fastapi import APIRouter, HTTPException, Request

    router = APIRouter()

    @router.get('/crm/journal-equipes/temps')
    def page(request: Request):
        session = session_page(request)
        try:
            args = arguments(request.query_params)
        except (ValueError, TypeError):
            raise HTTPException(400, 'Choisir un jour et un identifiant valides') from None
        try:
            with cnx_factory() as cnx:
                vue = lire(cnx, deps, session, **args)
                reponse = rendre(session, 'Temps pointés du jour', contenu(vue, prefixe))
                if len(reponse.body) > 131072:
                    raise HTTPException(503, 'Journée trop volumineuse pour cette consultation')
                verifier_courant(cnx, session, vue)
        except PermissionError:
            raise HTTPException(403, 'Accès admin requis') from None
        except (ValueError, KeyError, TypeError, UnicodeError):
            raise HTTPException(503, 'Temps indisponibles; vérifier les sources et le compte employee actif') from None
        return reponse

    return router
