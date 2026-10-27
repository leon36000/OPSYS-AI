"""Annotations privées de la cédule : rendu sans effet sur les opérations M4."""
import re
import uuid
from urllib.parse import parse_qs, urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from . import metier, pages

CLES = ('intervention_id', 'plan_id', 'source_application_id', 'source_ligne_id')


def ancre_de(ligne):
    return {k: ligne[k] for k in CLES}


def url(ancre, prefixe):
    return f'{prefixe}/crm/cedule/annotations?'+urlencode(ancre)


def extraire(reponse):
    r = reponse.get('resultat') if isinstance(reponse, dict) and reponse.get('ok') is True else None
    if not isinstance(r, dict):
        raise HTTPException(503, 'Annotations temporairement indisponibles')
    if r.get('accepte') is True and isinstance(r.get('resultat'), dict):
        return r['resultat']
    suffixe = r.get('verdict', {}).get('code', '')
    for prefix in ('REJ-ANNOTATION-CALENDRIER-', 'REJ-COULEUR-CALENDRIER-'):
        suffixe = suffixe.removeprefix(prefix)
    if suffixe == 'IDENTITE':
        raise HTTPException(403, 'Accès refusé')
    if suffixe in {'REVISION-PERIMEE', 'SOURCE-PERIMEE', 'SOURCE-REMPLACEE', 'MUTATION-CONFLIT'}:
        raise HTTPException(409, 'Repère non enregistré : relire le créneau et sa dernière révision.')
    if suffixe in {'ARGUMENTS', 'ANCRE-INVALIDE', 'MUTATION-INVALIDE'}:
        raise HTTPException(400, 'Annotation invalide')
    raise HTTPException(503, 'Source ou historique indisponible : aucune nouvelle note confirmée.')


def appeler(cnx_factory, deps, session, nom, arguments, mutation=None):
    try:
        with cnx_factory() as cnx:
            return extraire(metier.executer(cnx, deps, session, nom, arguments, mutation_id=mutation))
    except PermissionError:
        raise HTTPException(403, 'Accès refusé') from None
    except KeyError:
        raise HTTPException(503, 'Annotations indisponibles') from None
    except ValueError:
        raise HTTPException(400, 'Annotation invalide') from None


def badges(cnx_factory, deps, session, vue):
    ancres = [ancre_de(ligne) for ligne in vue['interventions']]
    if not ancres:
        return
    resultat = appeler(cnx_factory, deps, session, 'm4_resumer_annotations_calendrier', {'ancres': ancres})
    items = resultat.get('annotations')
    if not isinstance(items, list) or len(items) != len(ancres):
        raise HTTPException(503, 'Annotations indisponibles')
    for ligne, ancre, item in zip(vue['interventions'], ancres, items, strict=True):
        if (item.get('ancre') != ancre or item.get('source_courante') is not True
                or item.get('validite') != ligne['validite']):
            raise HTTPException(409, 'La cédule a changé : recharger la semaine.')
        ligne['annotation'] = {'total_ancre': item['total_ancre'], 'total_historique': item['total_historique']}


def _entier(brut):
    if not re.fullmatch(r'0|[1-9][0-9]{0,4}', brut) or int(brut) > 10000:
        raise HTTPException(400, 'Révision ou pagination invalide')
    return int(brut)


def _parametres(request, historique=True):
    p = request.query_params
    if set(p) - (set(CLES) | ({'decalage', 'revision_max'} if historique else set())):
        raise HTTPException(400, 'Paramètres invalides')
    if not set(CLES) <= set(p) or any(len(p.getlist(k)) != 1 for k in p):
        raise HTTPException(400, 'Référence invalide')
    a = {k: p[k] for k in CLES}
    if any(not a[k] or len(a[k]) > 200 for k in CLES):
        raise HTTPException(400, 'Référence invalide')
    return a


async def _formulaire(request, champ="texte_libre"):
    if request.headers.get('content-type', '').split(';')[0] != 'application/x-www-form-urlencoded':
        raise HTTPException(415, 'Formulaire requis')
    corps = bytearray()
    async for bloc in request.stream():
        corps.extend(bloc)
        if len(corps) > 30000:
            raise HTTPException(413, 'Formulaire trop volumineux')
    try:
        p = parse_qs(corps.decode('utf-8'), keep_blank_values=True, strict_parsing=True,
                     max_num_fields=4, errors='strict')
        if (set(p) != {'csrf', champ, 'revision_attendue', 'mutation_id'}
                or any(len(v) != 1 for v in p.values())):
            raise ValueError('champs invalides')
        return {k: v[0] for k, v in p.items()}
    except (ValueError, UnicodeError):
        raise HTTPException(400, 'Formulaire invalide') from None


def ecriture_qualifiee(cnx_factory):
    """Même frontière que le writer; aucun formulaire trompeur sur un backend fermé."""
    with cnx_factory() as cnx:
        return cnx.dialect.name == "sqlite"


def creer_router(*, session_page, cnx_factory, deps, prefixe, verifier_formulaire, rendre):
    router = APIRouter()

    def agir(session, nom, args, mutation=None):
        return appeler(cnx_factory, deps, session, nom, args, mutation)

    @router.get('/crm/cedule/annotations')
    def detail(request: Request):
        session = session_page(request)
        ancre = _parametres(request)
        decalage = _entier(request.query_params.get('decalage', '0'))
        plafond = _entier(request.query_params['revision_max']) if 'revision_max' in request.query_params else None
        b = agir(session, 'm4_resumer_annotations_calendrier', {'ancres': [ancre]})['annotations'][0]
        if b['ancre'] != ancre:
            raise HTTPException(503, 'Source indisponible')
        vue = agir(session, 'm4_lire_annotations_calendrier', {'intervention_id': ancre['intervention_id'],
                   'limite': 10, 'decalage': decalage, 'revision_max': plafond})
        if vue['revision_courante'] != b['revision_courante']:
            raise HTTPException(409, 'Les annotations ont changé : recharger.')
        chemin, c = url(ancre, prefixe), b['creneau']
        corps = ('<section class="carte"><h2>Note rapide du créneau</h2>'
                 f'<p>Intervention : {pages.e(ancre["intervention_id"])}</p>'
                 f'<p>Équipe {pages.e(c["equipe_id"])} · {pages.e(c["debut"])} → {pages.e(c["fin"])}</p>'
                 f'<p>État du créneau : {pages.e(b["validite"])}. Révision civile {c["revision_calendrier"]}.</p>'
                 '<p>Note interne administrative. Ne change ni la cédule, ni le temps, ni la paie; '
                 'aucun message client envoyé.</p>'
                 f'<p><a href="{pages.e(prefixe)}/crm/cedule">Retour à la cédule</a></p>')
        if b['source_courante'] and ecriture_qualifiee(cnx_factory):
            corps += (f'<form method="post" action="{pages.e(chemin)}" class="pile">'
                f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">'
                f'<input type="hidden" name="revision_attendue" value="{b["revision_courante"]}">'
                f'<input type="hidden" name="mutation_id" value="{uuid.uuid4()}">'
                '<label>Nouvelle note ou correction<textarea name="texte_libre" rows="4" maxlength="2000" '
                'required></textarea></label><p>2 000 caractères maximum; chaque version reste dans l’historique. '
                'Saisir uniquement des informations utiles au chantier, sans données de santé.</p>'
                '<button type="submit">Enregistrer la note</button></form>')
        elif b['source_courante']:
            corps += '<p>Lecture seule : saisie des notes indisponible sur ce backend.</p>'
        else:
            corps += '<p>Ancien créneau : historique conservé. Ouvrir la carte actuelle pour une nouvelle note.</p>'
        corps += '<h3>Historique des notes de cette intervention</h3>'
        for note in vue['annotations']:
            meme = note['ancre'] == ancre
            corps += (f'<article class="carte"><h4>Révision {note["revision"]} — '
                      f'{"ce créneau" if meme else "autre créneau historique"}</h4>'
                      f'<p>{pages.e(note["auteur"]["personne"])} · {pages.e(note["horodatage"])}</p>'
                      f'<pre>{pages.e(note["texte_libre"])}</pre>'
                      f'<p>Source : {pages.e(note["annotation_id"])}</p>'
                      f'<p><a href="{pages.e(url(note["ancre"], prefixe))}">Voir le créneau source</a></p></article>')
        corps += f'<p>{len(vue["annotations"])} version(s) affichée(s) sur {vue["total"]}.</p>'
        for cible, label in [(max(0, decalage-10) if decalage else None, 'Précédentes'), (vue['suivant'], 'Suivantes')]:
            if cible is not None:
                lien = chemin+'&'+urlencode({'decalage': cible, 'revision_max': vue['revision_max']})
                corps += f'<a href="{pages.e(lien)}">{label}</a> '
        return rendre(session, 'Annotations de cédule', corps+'</section>')

    @router.post('/crm/cedule/annotations')
    async def enregistrer(request: Request):
        session = session_page(request)
        ancre = _parametres(request, historique=False)
        champs = await _formulaire(request)
        verifier_formulaire(champs, session)
        agir(session, 'm4_enregistrer_annotation_calendrier', {'ancre': ancre,
             'texte_libre': champs['texte_libre'], 'revision_attendue': _entier(champs['revision_attendue'])},
             champs['mutation_id'])
        return RedirectResponse(url(ancre, prefixe), status_code=303)

    return router
