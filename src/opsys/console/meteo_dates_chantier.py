"""Consultation explicite du vrai T0 météo sur les dates internes, sans confirmation."""
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Request

from .. import idempotence, identite, meteo, stockage
from . import cedule_plan_ui, pages
from . import preparation_chantier as lecture

STATUTS = {'ok', 'inconnu', 'bloquant', 'validation_requise'}


def preparer(cnx, deps, session, plan_id):
    """Aucune prévision chargée : la tête, les dates et le profil seuls lient le formulaire."""
    from m4_field_ops import annotations_calendrier, registre

    if cnx is not stockage.connexion_courante() or cnx.dialect.name != 'sqlite':
        raise lecture.Refus('INSTANCE-NON-QUALIFIEE')
    personne = identite.personne_active(cnx, session.utilisateur)
    if (personne is None or 'admin' not in personne.roles
            or session.expire <= datetime.now(UTC).timestamp()):
        raise PermissionError('admin actif requis')
    if type(plan_id) is not str or cedule_plan_ui.PLAN_ID.fullmatch(plan_id) is None:
        raise lecture.Refus('INTROUVABLE')
    lecture._borner(cnx, lecture.M4, 'principal')
    chaine = registre.Registre(stockage.maillons(lecture.M4, 'principal'))
    try:
        chaine.assert_chaine()
    except registre.VerificationError:
        raise lecture.Refus('SOURCE-INCOHERENTE') from None
    vue = lecture._sortie(lecture._appel(deps, session.utilisateur, lecture.M4,
                                       'm4_lire_calendrier_plan', dict(plan_id=plan_id)))
    complet = cedule_plan_ui.valider(vue, plan_id) and vue['revision'] > 0
    if complet:
        try:
            sources = annotations_calendrier._sources(chaine)
            for v in vue['visites']:
                ancre = dict(intervention_id=v['intervention_id'], plan_id=plan_id,
                    source_application_id=vue['source_application_id'], source_ligne_id=vue['source_ligne_id'])
                preuve = annotations_calendrier._creneau(sources, ancre)
                if (any(preuve[k] != v[k] for k in ('equipe_id', 'jour', 'debut_min', 'fin_min'))
                        or preuve['revision_calendrier'] != vue['revision']
                        or preuve['source_proposition_id'] != vue['source_proposition_id']
                        or not preuve['debut'].startswith(vue['calendrier'][str(v['jour'])] + 'T')):
                    raise lecture.Refus('SOURCE-INCOHERENTE')
        except annotations_calendrier.Refus:
            raise lecture.Refus('SOURCE-INCOHERENTE') from None
    profil, erreur = meteo.charger_meteo()
    source = dict(vue=vue, profil=profil, erreur=erreur, tete=chaine.tete())
    return dict(vue=vue, profil=profil, erreur=erreur, permis=complet,
                empreinte=idempotence.empreinte_arguments(source))


def _fuseau(profil, vue):
    try:
        zone = ZoneInfo(profil['fuseau'])
        local = ZoneInfo(cedule_plan_ui.FUSEAU)
        for v in vue['visites']:
            debut = datetime.fromisoformat(vue['calendrier'][str(v['jour'])])
            # Comparer chaque minute du créneau, y compris un éventuel changement d'heure.
            for minute in range(v['debut_min'], v['fin_min'] + 1):
                h = debut + timedelta(minutes=minute)
                if h.replace(tzinfo=zone).utcoffset() != h.replace(tzinfo=local).utcoffset():
                    raise lecture.Refus('FUSEAU-INCOMPATIBLE')
    except (KeyError, TypeError, ZoneInfoNotFoundError):
        raise lecture.Refus('FUSEAU-INCOMPATIBLE') from None


def verifier(cnx, deps, session, plan_id, empreinte_attendue):
    courant = preparer(cnx, deps, session, plan_id)
    if type(empreinte_attendue) is not str or empreinte_attendue != courant['empreinte']:
        raise lecture.Refus('SOURCE-MODIFIEE')
    if not courant['permis']:
        raise lecture.Refus('PLAN-NON-DATE-OU-BLOQUE')
    if courant['erreur'] is not None or courant['profil'] is None:
        raise lecture.Refus('PROFIL-METEO-INDISPONIBLE')
    vue = courant['vue']
    _fuseau(courant['profil'], vue)
    res = lecture._sortie(lecture._appel(deps, session.utilisateur, lecture.M4,
        'm4_verifier_meteo_creneau', dict(plan_id=plan_id, calendrier=vue['calendrier'])))
    attendu_profil = dict(empreinte=meteo.empreinte_meteo(courant['profil']),
                           fuseau=courant['profil'].get('fuseau'))
    if res.get('profil_meteo_source') != attendu_profil:
        raise lecture.Refus('SOURCE-MODIFIEE')
    if (res.get('plan_id') != plan_id or res.get('statut') not in STATUTS
            or any(k in res for k in ('detail_reduit', 'ok_resume', 'perimes'))
            or not isinstance(res.get('creneaux'), list)):
        raise lecture.Refus('CONTROLE-METEO-INCOMPLET')
    attendus = {(v['intervention_id'], v['equipe_id'], v['jour'],
                 vue['calendrier'][str(v['jour'])], v['debut_min'], v['fin_min']) for v in vue['visites']}
    recus = []
    for c in res['creneaux']:
        if (c.get('plan_perime') is not False or c.get('statut') not in STATUTS
                or not isinstance(c.get('regles'), list)):
            raise lecture.Refus('CONTROLE-METEO-INCOMPLET')
        recus.append((c['intervention_id'], c['equipe'], c['jour'], c['date'], c['debut_min'], c['fin_min']))
    if len(recus) != len(attendus) or set(recus) != attendus:
        raise lecture.Refus('CONTROLE-METEO-INCOMPLET')
    # Le réseau éventuel n'est jamais une nouvelle source de dates ou de permissions.
    apres = preparer(cnx, deps, session, plan_id)
    if apres['empreinte'] != courant['empreinte']:
        raise lecture.Refus('SOURCE-MODIFIEE')
    return lecture._sortie(dict(plan_id=plan_id, revision=vue['revision'], empreinte=courant['empreinte'],
        statut=res['statut'], creneaux=res['creneaux'], attributions=res['attributions']))


def formulaire(apercu, csrf, prefixe):
    if not apercu['permis']:
        return ''
    return (f'<form method="post" action="{pages.e(prefixe)}/crm/cedule/plan/'
        f'{pages._segment(apercu["vue"]["plan_id"])}/meteo" class="pile">'
        f'<input type="hidden" name="csrf" value="{pages.e(csrf)}">'
        f'<input type="hidden" name="empreinte_attendue" value="{pages.e(apercu["empreinte"])}">'
        '<p>Vérifier les dates déjà enregistrées avec le fournisseur météo configuré. '
        'Cette consultation peut charger une prévision; elle ne modifie pas les dates.</p>'
        '<button type="submit">Vérifier la météo des dates internes</button></form>')


def contenu(res):
    corps = ('<h2>Météo des dates internes — consultation</h2>'
        '<p role="alert">Fraîcheur non qualifiée : aucun âge maximal de prévision n’est imposé par le moteur. '
        'Un résultat ok indique seulement des seuils respectés dans la source citée. '
        'Il ne confirme ni disponibilité globale, ni dispatch, ni rendez-vous client.</p>'
        f'<p>Verdict : {pages.e(res["statut"])} · Révision civile {res["revision"]}</p>')
    for c in res['creneaux']:
        corps += (f'<section><h3>{pages.e(c["intervention_id"])}</h3>'
            f'<p>{pages.e(c["date"])} · {pages.e(c["equipe"])} · {pages.e(c["statut"])}</p>')
        if c.get('cause'):
            corps += f'<p>{pages.e(c["cause"])}</p>'
        for r in c['regles']:
            corps += f'<p>{pages.e(r["risque"])} : {pages.e(r["statut"])} — {pages.e(r["detail"])}</p>'
        for k in ('a_configurer', 'sans_objet'):
            if c.get(k):
                corps += f'<p>{pages.e(k)} : {pages.e(c[k])}</p>'
        if c['prevision'] is None:
            corps += '<p>Aucune prévision citée.</p>'
        else:
            corps += '<dl>'
            for k in ('source', 'heure_type', 'emise_le', 'saisi_par', 'reference'):
                if k in c['prevision']:
                    corps += f'<dt>{pages.e(k)}</dt><dd>{pages.e(c["prevision"][k])}</dd>'
            corps += '</dl>'
        corps += '</section>'
    for attribution in res['attributions']:
        corps += f'<p>{pages.e(attribution)}</p>'
    return corps


def creer_router(*, session_page, cnx_factory, deps, prefixe, rendre, verifier_formulaire):
    router = APIRouter()

    @router.post('/crm/cedule/plan/{plan_id}/meteo')
    async def controler(plan_id: str, request: Request):
        session = session_page(request)
        if request.query_params:
            raise HTTPException(400, 'Paramètres invalides')
        champs = await cedule_plan_ui.formulaire(request)
        verifier_formulaire(champs, session)
        if set(champs) != {'csrf', 'empreinte_attendue'}:
            raise HTTPException(400, 'Formulaire invalide')
        try:
            with cnx_factory() as cnx:
                res = verifier(cnx, deps, session, plan_id, champs['empreinte_attendue'])
            reponse = rendre(session, 'Météo des dates internes', contenu(res))
            if len(reponse.body) > 131072:
                raise lecture.Refus('SORTIE-TROP-VOLUMINEUSE')
            return reponse
        except PermissionError:
            raise HTTPException(403, 'Accès admin requis') from None
        except lecture.Refus as exc:
            status = 409 if exc.code in {'SOURCE-MODIFIEE', 'PLAN-NON-DATE-OU-BLOQUE'} else 503
            if exc.code == 'INTROUVABLE':
                status = 404
            raise HTTPException(status, 'Contrôle météo indisponible : ' + exc.code) from None
        except (ValueError, KeyError, TypeError):
            raise HTTPException(503, 'Sources météo indisponibles') from None

    return router
