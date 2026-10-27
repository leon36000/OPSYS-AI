"""Choix explicite par fiche M6 active; garde de source sous la transaction d'écriture M3."""
import re
import uuid
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from . import catalogue_materiaux_ui as catalogue
from . import modeles_soumission_ui as modeles
from . import pages, prefill_ui

CHAMPS = prefill_ui.ANCRE | {'csrf', 'mutation_id', 'revision_attendue'} | {
    f'{k}_{i}' for i in range(20) for k in ('ligne_id', 'description', 'selection')}


def selection(fiche):
    return f'{fiche["materiau_id"]}@{fiche["revision"]}@{fiche["source_id"]}'


def creer_router(*, session_page, cnx_factory, deps, prefixe, verifier_formulaire, rendre, appeler):
    router = APIRouter()
    route = '/crm/modeles-soumission/{modele_id}/lignes/catalogue'

    def materiau(session, nom, args):
        return catalogue.appeler(cnx_factory, deps, session, nom, args)

    def contexte_modele(session, p, modele_id):
        if modele_id != p['modele_id']:
            raise HTTPException(400, 'Modèle incohérent')
        m = appeler(session, 'm3_lire_modele_soumission',
                    dict(modele_id=modele_id, version=modeles.entier(p['modele_revision'])))
        if m['source_id'] != p['modele_source']:
            raise HTTPException(409, 'Version du modèle à relire')
        return m

    @router.get(route)
    def choisir(modele_id: str, request: Request):
        session = session_page(request)
        p = request.query_params
        if (set(p) - (prefill_ui.ANCRE | {'debut'}) or not set(p) >= prefill_ui.ANCRE
                or any(len(p.getlist(k)) != 1 for k in p)):
            raise HTTPException(400, 'Version exacte requise')
        with cnx_factory():
            m = contexte_modele(session, p, modele_id)
            try:
                jeu = appeler(session, 'm3_lire_lignes_modele', {**prefill_ui.ancre(p), 'version_lignes': 0})
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
                jeu = {'revision': 0, 'lignes': []}
            debut = catalogue.entier(p.get('debut', '0'))
            page = materiau(session, 'm6_lister_materiaux_console',
                            dict(debut=debut, limite=25, actifs_seulement=True))
            choix = {f['materiau_id']: f for f in page['materiaux']}
            # Les lignes existantes hors de cette page restent choisissables si leur fiche est active.
            for ligne in jeu['lignes']:
                if re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}', ligne['materiau_id']) is None:
                    continue  # référence historique affichée comme indisponible, jamais normalisée
                if ligne['materiau_id'] not in choix:
                    try:
                        f = materiau(session, 'm6_lire_materiau_console',
                                     dict(materiau_id=ligne['materiau_id'], revision=0))
                    except HTTPException as exc:
                        if exc.status_code != 404:
                            raise
                    else:
                        if f['actif']:
                            choix[f['materiau_id']] = f
        base = prefixe + '/crm/modeles-soumission/' + pages._segment(modele_id) + '/lignes/catalogue'
        corps = (f'<h2>Matériaux du modèle — {pages.e(m["titre"])}</h2>'
                 f'<p><a href="{pages.e(prefixe + catalogue.BASE)}">Gérer les matériaux</a></p>'
                 '<p>Choisir le nom et l’unité officiels. Les quantités et fournisseurs seront choisis dans le devis. '
                 'Changer de page recharge le formulaire : enregistrer les choix avant de changer de page.</p>')
        for offset, label in [(max(0, debut - 25) if debut else None, 'Matériaux précédents'),
                              (page['suivant'], 'Matériaux suivants')]:
            if offset is not None:
                lien = base + '?' + urlencode({**{k: p[k] for k in prefill_ui.ANCRE}, 'debut': offset})
                corps += f'<p><a href="{pages.e(lien)}">{label}</a></p>'
        corps += (f'<form method="post" action="{pages.e(base)}" class="pile">'
                  + prefill_ui.caches({**{k: p[k] for k in prefill_ui.ANCRE}, 'csrf': session.csrf,
                                       'mutation_id': str(uuid.uuid4()), 'revision_attendue': jeu['revision']}))
        for i in range(20):
            ligne = jeu['lignes'][i] if i < len(jeu['lignes']) else dict(ligne_id=str(uuid.uuid4()))
            corps += (f'<fieldset><legend>Ligne {i + 1}</legend>'
                      + prefill_ui.caches({f'ligne_id_{i}': ligne['ligne_id']})
                      + f'<label>Description<textarea name="description_{i}" maxlength="500">'
                      f'\n{pages.e(ligne.get("description", ""))}</textarea></label>'
                      f'<label>Matériau et unité<select name="selection_{i}">'
                      '<option value="">Choisir un matériau</option>')
            for f in choix.values():
                selected = (' selected' if (f['materiau_id'], f['unite']) ==
                            (ligne.get('materiau_id'), ligne.get('unite')) else '')
                corps += (f'<option value="{pages.e(selection(f))}"{selected}>'
                          f'{pages.e(f["nom"])} · {pages.e(f["unite"])} · {pages.e(f["materiau_id"])}</option>')
            if ligne.get('materiau_id') and not any(
                    (f['materiau_id'], f['unite']) == (ligne['materiau_id'], ligne['unite']) for f in choix.values()):
                corps += '<option value="" disabled>Ancienne référence indisponible : choisir une fiche active</option>'
            corps += '</select></label></fieldset>'
        return rendre(session, 'Choisir les matériaux', corps + '<button>Enregistrer les lignes</button></form>')

    @router.post(route)
    async def enregistrer(modele_id: str, request: Request):
        session = session_page(request)
        p = await prefill_ui.extraire(request, CHAMPS)
        verifier_formulaire(p, session)
        # BEGIN IMMEDIATE englobe les lectures M6 et l'écriture M3 : pas de changement de fiche entre les deux.
        with cnx_factory():
            contexte_modele(session, p, modele_id)
            lignes, fiches = [], {}
            for i in range(20):
                texte, choix = p[f'description_{i}'], p[f'selection_{i}']
                if not texte and not choix:
                    continue
                if not texte or re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}@[0-9]{1,5}@[0-9a-f]{64}', choix) is None:
                    raise HTTPException(400, 'Description et matériau explicites requis')
                identifiant, revision, source = choix.split('@')
                if identifiant not in fiches:
                    fiches[identifiant] = materiau(session, 'm6_lire_materiau_console',
                                                  dict(materiau_id=identifiant, revision=0))
                f = fiches[identifiant]
                if not f['actif'] or f['revision'] != int(revision) or f['source_id'] != source:
                    raise HTTPException(409, 'La fiche matériau a changé : relire les choix')
                lignes.append(dict(ligne_id=p[f'ligne_id_{i}'], description=texte,
                                   materiau_id=f['materiau_id'], unite=f['unite']))
            appeler(session, 'm3_enregistrer_lignes_modele',
                    {**prefill_ui.ancre(p), 'lignes': lignes,
                     'revision_attendue': modeles.entier(p['revision_attendue'])}, p['mutation_id'])
        lien = prefixe + '/crm/modeles-soumission/' + pages._segment(modele_id) + '/lignes/catalogue?'
        return RedirectResponse(lien + urlencode({k: p[k] for k in prefill_ui.ANCRE}), 303)

    return router
