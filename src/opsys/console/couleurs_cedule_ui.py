"""Repères de présentation administratifs, indépendants des états opérationnels M4."""
import uuid
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from . import annotations_cedule_ui as notes
from . import pages


def palette():
    # Dépendance chargée seulement sur cette surface M4, pas au démarrage de toute la console.
    from m4_field_ops.couleurs_calendrier import PALETTE

    return dict(PALETTE)


def url(ancre, prefixe):
    return f'{prefixe}/crm/cedule/couleurs?'+urlencode(ancre)


def badges(cnx_factory, deps, session, vue):
    ancres = [notes.ancre_de(ligne) for ligne in vue['interventions']]
    if not ancres:
        return
    resultat = notes.appeler(cnx_factory, deps, session, 'm4_resumer_couleurs_calendrier', {'ancres': ancres})
    items = resultat.get('couleurs')
    if not isinstance(items, list) or len(items) != len(ancres):
        raise HTTPException(503, 'Repères couleur indisponibles')
    for ligne, ancre, item in zip(vue['interventions'], ancres, items, strict=True):
        if (item.get('ancre') != ancre or item.get('source_courante') is not True
                or item.get('validite') != ligne['validite']):
            raise HTTPException(409, 'La cédule a changé : recharger la semaine.')
        if item.get('couleur') not in palette():
            raise HTTPException(503, 'Repère couleur invalide')
        ligne['couleur'] = item['couleur']


def marqueur(couleur):
    choix = palette()
    if type(couleur) is not str or couleur not in choix:
        raise ValueError('repère couleur invalide')
    return (f'<span class="cedule-repere repere-{couleur}"><span aria-hidden="true" '
            f'class="repere-echantillon"></span>Repère : {pages.e(choix[couleur])}</span>')


def creer_router(*, session_page, cnx_factory, deps, prefixe, verifier_formulaire, rendre):
    router = APIRouter()

    def agir(session, nom, args, mutation=None):
        return notes.appeler(cnx_factory, deps, session, nom, args, mutation)

    @router.get('/crm/cedule/couleurs')
    def detail(request: Request):
        session = session_page(request)
        ancre = notes._parametres(request)
        decalage = notes._entier(request.query_params.get('decalage', '0'))
        plafond = (notes._entier(request.query_params['revision_max'])
                   if 'revision_max' in request.query_params else None)
        b = agir(session, 'm4_resumer_couleurs_calendrier', {'ancres': [ancre]})['couleurs'][0]
        if b['ancre'] != ancre:
            raise HTTPException(503, 'Source indisponible')
        vue = agir(session, 'm4_lire_couleurs_calendrier', {'intervention_id': ancre['intervention_id'],
                   'limite': 10, 'decalage': decalage, 'revision_max': plafond})
        if vue['revision_courante'] != b['revision_courante']:
            raise HTTPException(409, 'Les repères ont changé : recharger.')
        chemin, c = url(ancre, prefixe), b['creneau']
        corps = ('<section class="carte"><h2>Couleur du chantier sur ce créneau</h2>'
                 f'<p>Intervention : {pages.e(ancre["intervention_id"])}</p>'
                 f'<p>Équipe {pages.e(c["equipe_id"])} · {pages.e(c["debut"])} → {pages.e(c["fin"])}</p>'
                 f'<p>État du créneau : {pages.e(b["validite"])}. Révision civile {c["revision_calendrier"]}.</p>'
                 f'<p>{marqueur(b["couleur"])}</p>'
                 '<p>Repère visuel choisi par l’administration. Il ne confirme ni date, ni fin des travaux, '
                 'ni disponibilité. Aucun changement de statut, de paie ou de notification.</p>'
                 '<p>Une nouvelle date conserve son propre repère; la couleur historique reste sur son créneau.</p>'
                 f'<p><a href="{pages.e(prefixe)}/crm/cedule">Retour à la cédule</a></p>')
        if b['source_courante'] and notes.ecriture_qualifiee(cnx_factory):
            options = ''.join(f'<option value="{k}"'+(' selected' if k == b['couleur'] else '')+
                              f'>{pages.e(v)}</option>' for k, v in palette().items())
            corps += (f'<form method="post" action="{pages.e(chemin)}" class="pile">'
                f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">'
                f'<input type="hidden" name="revision_attendue" value="{b["revision_courante"]}">'
                f'<input type="hidden" name="mutation_id" value="{uuid.uuid4()}">'
                f'<label>Repère de ce créneau<select name="couleur" required>{options}</select></label>'
                '<p>Sans repère retire le marquage. Les versions précédentes restent consultables.</p>'
                '<button type="submit">Enregistrer la couleur</button></form>')
        elif b['source_courante']:
            corps += '<p>Lecture seule : saisie des couleurs indisponible sur ce backend.</p>'
        else:
            corps += '<p>Ancien créneau : historique conservé. Ouvrir la carte actuelle pour changer sa couleur.</p>'
        corps += '<h3>Historique des couleurs de cette intervention</h3>'
        for item in vue['couleurs']:
            meme = item['ancre'] == ancre
            corps += (f'<article class="carte"><h4>Révision {item["revision"]} — '
                      f'{"ce créneau" if meme else "autre créneau historique"}</h4>'
                      f'<p>{marqueur(item["couleur"])}</p>'
                      f'<p>{pages.e(item["auteur"]["personne"])} · {pages.e(item["horodatage"])}</p>'
                      f'<p>Source : {pages.e(item["couleur_id"])}</p>'
                      f'<p><a href="{pages.e(url(item["ancre"], prefixe))}">Voir le créneau source</a></p></article>')
        corps += f'<p>{len(vue["couleurs"])} version(s) affichée(s) sur {vue["total"]}.</p>'
        for cible, label in [(max(0, decalage-10) if decalage else None, 'Précédentes'), (vue['suivant'], 'Suivantes')]:
            if cible is not None:
                lien = chemin+'&'+urlencode({'decalage': cible, 'revision_max': vue['revision_max']})
                corps += f'<a href="{pages.e(lien)}">{label}</a> '
        return rendre(session, 'Couleurs de cédule', corps+'</section>')

    @router.post('/crm/cedule/couleurs')
    async def enregistrer(request: Request):
        session = session_page(request)
        ancre = notes._parametres(request, historique=False)
        champs = await notes._formulaire(request, champ='couleur')
        verifier_formulaire(champs, session)
        agir(session, 'm4_definir_couleur_calendrier', {'ancre': ancre,
             'couleur': champs['couleur'], 'revision_attendue': notes._entier(champs['revision_attendue'])},
             champs['mutation_id'])
        return RedirectResponse(url(ancre, prefixe), status_code=303)

    return router
