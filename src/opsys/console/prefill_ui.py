"""Formulaires admin de lignes réutilisables et devis avec tarif M6 choisi."""
import re
import uuid
from urllib.parse import parse_qs, urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from . import modeles_soumission_ui as modeles
from . import pages

ANCRE = {'modele_id', 'modele_revision', 'modele_source'}
LIGNES = ANCRE | {'csrf', 'mutation_id', 'revision_attendue'} | {
    f'{k}_{i}' for i in range(20) for k in ('ligne_id', 'description', 'materiau_id', 'unite')}
CHOIX = ANCRE | {'csrf', 'mutation_id', 'devis_id', 'chantier_id', 'taux_marge',
                 'lignes_revision', 'lignes_source', 'nombre_lignes'} | {
    f'{k}_{i}' for i in range(20) for k in ('ligne_modele_id', 'quantite', 'fournisseur_id')}
CONFIRMER = CHOIX | {f'{k}_{i}' for i in range(20) for k in ('tarif_rang', 'tarif_empreinte')}


async def extraire(request, attendus):
    if request.query_params:
        raise HTTPException(400, 'Paramètres invalides')
    if request.headers.get('content-type', '').split(';')[0] != 'application/x-www-form-urlencoded':
        raise HTTPException(415, 'Formulaire requis')
    corps = bytearray()
    async for bloc in request.stream():
        corps.extend(bloc)
        if len(corps) > 131072:
            raise HTTPException(413, 'Formulaire trop volumineux')
    try:
        p = parse_qs(corps.decode('utf-8'), keep_blank_values=True, strict_parsing=True,
                     max_num_fields=len(attendus), errors='strict')
        if set(p) != attendus or any(len(v) != 1 for v in p.values()):
            raise ValueError('champs')
        return {k: v[0] for k, v in p.items()}
    except (ValueError, UnicodeError):
        raise HTTPException(400, 'Formulaire invalide') from None


def caches(valeurs):
    return ''.join(f'<input type="hidden" name="{pages.e(k)}" value="{pages.e(v)}">'
                   for k, v in valeurs.items())


def ancre(p):
    return {'modele_id': p['modele_id'], 'modele_revision': modeles.entier(p['modele_revision']),
            'modele_source': p['modele_source']}


def selections(p, tarifs=False):
    nombre = modeles.entier(p['nombre_lignes'])
    if not 1 <= nombre <= 20:
        raise HTTPException(400, 'Nombre de lignes invalide')
    resultat = []
    noms = ('ligne_modele_id', 'quantite', 'fournisseur_id') + (('tarif_rang', 'tarif_empreinte') if tarifs else ())
    for i in range(20):
        ligne = {k: p[f'{k}_{i}'] for k in noms}
        if i >= nombre:
            if any(ligne.values()):
                raise HTTPException(400, 'Ligne supplémentaire invalide')
            continue
        if (not ligne['fournisseur_id'].strip() or len(ligne['fournisseur_id']) > 200
                or re.fullmatch(r'[0-9]{1,9}(\.[0-9]{1,6})?', ligne['quantite']) is None):
            raise HTTPException(400, 'Fournisseur et quantité explicites requis')
        if tarifs:
            if re.fullmatch(r'[0-9]{1,10}', ligne['tarif_rang']) is None:
                raise HTTPException(400, 'Référence tarif invalide')
            ligne['tarif_rang'] = int(ligne['tarif_rang'])
        resultat.append(ligne)
    return resultat


def creer_router(*, session_page, cnx_factory, prefixe, verifier_formulaire, verifier_lead, rendre, appeler):
    router = APIRouter()
    edition = '/crm/modeles-soumission/{modele_id}/lignes'
    creation = '/crm/lead/{lead_id}/soumission-preremplie'

    def modele_exact(session, p):
        m = appeler(session, 'm3_lire_modele_soumission',
                    {'modele_id': p['modele_id'], 'version': modeles.entier(p['modele_revision'])})
        if m['revision'] != modeles.entier(p['modele_revision']) or m['source_id'] != p['modele_source']:
            raise HTTPException(409, 'Modèle modifié : reprendre la sélection')
        return m

    def lire_jeu(session, p, version):
        return appeler(session, 'm3_lire_lignes_modele', {**ancre(p), 'version_lignes': version})

    def lecture(request, modele_id=None):
        session = session_page(request)
        p = request.query_params
        if set(p) != {'modele_id', 'modele_revision', 'modele_source'} or any(len(p.getlist(k)) != 1 for k in p):
            raise HTTPException(400, 'Version exacte requise')
        if modele_id is not None and modele_id != p['modele_id']:
            raise HTTPException(400, 'Modèle incohérent')
        m = modele_exact(session, p)  # vérifie aussi l'admin SQL actif
        with cnx_factory() as cnx:
            if cnx.dialect.name != 'sqlite':
                raise HTTPException(503, 'Écriture non qualifiée sur cette instance')
        return session, p, m

    @router.get(edition)
    def lignes(modele_id: str, request: Request):
        session, p, m = lecture(request, modele_id)
        try:
            jeu = lire_jeu(session, p, 0)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            jeu = {'revision': 0, 'lignes': []}
        action = prefixe + '/crm/modeles-soumission/' + pages._segment(modele_id) + '/lignes'
        corps = (f'<h2>Lignes — {pages.e(m["titre"])} (version {m["revision"]})</h2>'
                 '<p>Descriptions et références matériaux réutilisables. Quantités et fournisseur seront choisis '
                 'pour chaque soumission. Aucun prix ni quantité par défaut. Une révision du texte conserve '
                 'ses propres lignes; elle ne reprend pas automatiquement celles d’une autre version.</p>'
                 f'<form method="post" action="{pages.e(action)}" class="pile">'
                 + caches({**dict(p), 'csrf': session.csrf, 'mutation_id': str(uuid.uuid4()),
                           'revision_attendue': jeu['revision']}))
        for i in range(20):
            ligne = jeu['lignes'][i] if i < len(jeu['lignes']) else {'ligne_id': str(uuid.uuid4())}
            corps += f'<fieldset><legend>Ligne {i+1}</legend>' + caches({f'ligne_id_{i}': ligne['ligne_id']})
            for k, titre, taille in [('description', 'Description', 500), ('materiau_id', 'Référence matériau M6', 200),
                                      ('unite', 'Unité exacte du tarif', 40)]:
                if k == 'description':
                    corps += (f'<label>{titre}<textarea name="{k}_{i}" maxlength="{taille}">'
                              f'\n{pages.e(ligne.get(k, ""))}</textarea></label>')
                else:
                    corps += (f'<label>{titre}<input name="{k}_{i}" maxlength="{taille}" '
                              f'value="{pages.e(ligne.get(k, ""))}"></label>')
            corps += '</fieldset>'
        corps += '<button type="submit">Enregistrer les lignes</button></form>'
        return rendre(session, 'Lignes réutilisables', corps)

    @router.post(edition)
    async def enregistrer(modele_id: str, request: Request):
        session = session_page(request)
        p = await extraire(request, LIGNES)
        verifier_formulaire(p, session)
        if modele_id != p['modele_id']:
            raise HTTPException(400, 'Modèle incohérent')
        lignes = []
        for i in range(20):
            ligne = {k: p[f'{k}_{i}'] for k in ('ligne_id', 'description', 'materiau_id', 'unite')}
            if any(ligne[k] for k in ('description', 'materiau_id', 'unite')):
                lignes.append(ligne)
        appeler(session, 'm3_enregistrer_lignes_modele',
                {**ancre(p), 'lignes': lignes, 'revision_attendue': modeles.entier(p['revision_attendue'])},
                p['mutation_id'])
        lien = prefixe + '/crm/modeles-soumission/' + pages._segment(modele_id) + '/lignes?'
        return RedirectResponse(lien + urlencode({k: p[k] for k in ANCRE}), 303)

    @router.get(creation)
    def choisir(lead_id: str, request: Request):
        session, p, m = lecture(request)
        verifier_lead(session, lead_id)
        jeu = lire_jeu(session, p, 0)
        valeurs = {k: '' for k in CHOIX}
        valeurs.update(dict(p), csrf=session.csrf, mutation_id=str(uuid.uuid4()), devis_id=str(uuid.uuid4()),
                       lignes_revision=jeu['revision'], lignes_source=jeu['source_id'],
                       nombre_lignes=len(jeu['lignes']))
        visibles = {f'{k}_{i}' for i in range(len(jeu['lignes'])) for k in ('quantite', 'fournisseur_id')}
        for i, ligne in enumerate(jeu['lignes']):
            valeurs[f'ligne_modele_id_{i}'] = ligne['ligne_id']
        action = prefixe + '/crm/lead/' + pages._segment(lead_id) + '/soumission-preremplie/preparer'
        corps = (f'<h2>{pages.e(m["titre"])}</h2><p>Choisir quantité et référence fournisseur pour chaque matériau. '
                 'Les coûts seront relus dans M6 avant confirmation.</p>'
                 f'<form method="post" action="{pages.e(action)}" class="pile">'
                 + caches({k: v for k, v in valeurs.items() if k not in visibles | {'taux_marge', 'chantier_id'}})
                 + '<label>Chantier (facultatif)<input name="chantier_id" maxlength="100"></label>'
                 '<label>Majoration sur coût (0.35 = 35 %)<input name="taux_marge" maxlength="24" required></label>')
        for i, ligne in enumerate(jeu['lignes']):
            corps += (f'<fieldset><legend>{pages.e(ligne["description"])}</legend>'
                      f'<p>Matériau : {pages.e(ligne["materiau_id"])} · unité : {pages.e(ligne["unite"])}</p>'
                      f'<label>Quantité<input name="quantite_{i}" maxlength="24" required></label>'
                      f'<label>Référence fournisseur M6<input name="fournisseur_id_{i}" '
                      'maxlength="200" required></label>'
                      '</fieldset>')
        return rendre(session, 'Préremplir la soumission', corps + '<button>Vérifier les tarifs</button></form>')

    @router.post(creation + '/preparer')
    async def preparer(lead_id: str, request: Request):
        session = session_page(request)
        verifier_lead(session, lead_id)
        p = await extraire(request, CHOIX)
        verifier_formulaire(p, session)
        modele_exact(session, p)
        jeu = lire_jeu(session, p, modeles.entier(p['lignes_revision']))
        choix = selections(p)
        if (jeu['source_id'] != p['lignes_source']
                or [c['ligne_modele_id'] for c in choix] != [ligne['ligne_id'] for ligne in jeu['lignes']]):
            raise HTTPException(409, 'Lignes modifiées : reprendre la sélection')
        valeurs = {k: '' for k in CONFIRMER}
        valeurs.update(p)
        corps = '<h2>Vérifier les coûts sélectionnés</h2><p>Coûts privés admin, en CAD. Aucun envoi.</p><ul>'
        for i, (ligne, choix_ligne) in enumerate(zip(jeu['lignes'], choix, strict=True)):
            tarif = appeler(session, 'm3_lire_tarif_modele', dict(materiau_id=ligne['materiau_id'],
                            fournisseur_id=choix_ligne['fournisseur_id'], unite=ligne['unite']))
            valeurs[f'tarif_rang_{i}'] = tarif['tarif_rang']
            valeurs[f'tarif_empreinte_{i}'] = tarif['tarif_empreinte']
            corps += (f'<li>{pages.e(ligne["description"])} : {pages.e(choix_ligne["quantite"])} '
                      f'{pages.e(ligne["unite"])} × {pages.e(tarif["cout_unitaire_decimal"])} CAD · '
                      f'fournisseur {pages.e(choix_ligne["fournisseur_id"])} · '
                      f'{pages.e(tarif["marquage_source"])} · {pages.e(tarif["source_document"] or "Sans document")} '
                      f'· date {pages.e(tarif["date_effet"])}</li>')
        action = prefixe + '/crm/lead/' + pages._segment(lead_id) + '/soumission-preremplie'
        corps += ('</ul>' + f'<form method="post" action="{pages.e(action)}">' + caches(valeurs)
                  + '<button>Créer le brouillon avec ces tarifs</button></form>')
        return rendre(session, 'Confirmer la soumission', corps)

    @router.post(creation)
    async def creer(lead_id: str, request: Request):
        session = session_page(request)
        verifier_lead(session, lead_id)
        p = await extraire(request, CONFIRMER)
        verifier_formulaire(p, session)
        r = appeler(session, 'm3_creer_devis_prefill', {
            **ancre(p), 'devis_id': p['devis_id'], 'lead_id': lead_id, 'chantier_id': p['chantier_id'] or None,
            'taux_marge': p['taux_marge'], 'lignes_revision': modeles.entier(p['lignes_revision']),
            'lignes_source': p['lignes_source'], 'selections': selections(p, tarifs=True)}, p['mutation_id'])
        lien = prefixe + '/crm/lead/' + pages._segment(lead_id) + '/soumissions/' + pages._segment(r['devis_id'])
        return RedirectResponse(lien, 303)

    return router
