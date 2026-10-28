"""Lecture privée M3→M5, calcul propriétaire et sources consommées, aucun effet financier."""
import copy
import hashlib
import json

from m5_financecore import encodage
from sqlalchemy import LargeBinary, cast, func, select

from .. import contexte
from ..outils import Autonomie, executer
from ..stockage import codec
from ..stockage.maillons import copier_maillons_avec_metadonnees
from ..stockage.schema import EVENEMENTS_RECUS
from . import memoire_chantier as autorite
from . import preparation_chantier as lecture

M5, M6 = 'm05-financecore', 'm06-material-control'
CATALOGUE = ((lecture.M2, 'principal'), (lecture.M3, 'devis'), (lecture.M3, 'principal'),
    *((M5, nom) for nom in ('devis_recus', 'wct_recus', 'variance_recue', 'factures', 'rentabilite')),
    (M6, 'livre_prix'))
MAX_CONFIGURATION = 1048576


def _capture(cnx):
    # Toutes les bornes avant le premier décodage des sources financières.
    for dep, nom in CATALOGUE:
        lecture._borner(cnx, dep, nom)
    return {(dep, nom): copier_maillons_avec_metadonnees(cnx, departement=dep, registre=nom)
            for dep, nom in CATALOGUE}


def _references(captures):
    return {dep + '/' + nom: s.empreinte_snapshot_calculee for (dep, nom), s in captures.items()}


def _lignes(captures, dep, nom):
    return [ligne.maillon for ligne in captures[(dep, nom)].lignes]


def _configuration(m5):
    try:
        with m5._MANIFESTE.open('rb') as f:
            raw = f.read(MAX_CONFIGURATION + 1)
    except OSError:
        return None, None
    if len(raw) > MAX_CONFIGURATION:
        raise lecture.Refus('CONFIGURATION-TROP-VOLUMINEUSE')
    return hashlib.sha256(raw).hexdigest(), raw


def _ancre(cnx, deps, session, lead_id, devis_id):
    from m3_estimation import devis_durable, estime_vs_reel
    from m3_estimation import outils as m3

    lecture._appel(deps, session.utilisateur, lecture.M2, 'm2_trouver_client_de_lead', dict(lead_id=lead_id))
    devis, verdict = devis_durable.lire_devis(m3.registre_devis_production(), devis_id)
    if verdict is not None or devis.get('lead_id') != lead_id:
        raise lecture.Refus('INTROUVABLE')
    if devis.get('statut') != 'accepte':
        raise lecture.Refus('DEVIS-NON-ACCEPTE')
    charge = lecture._publication(cnx, 'm3-devis-accepte-' + devis_id, 'm3.devis_accepte', lecture.M3)
    if charge is None:
        return None
    attendu = devis_durable.charge_evenement_devis_accepte(devis)
    if m3._source_estimation_exacte(devis.get('estimation_source_hash'), devis_id, lead_id) is not None:
        attendu = estime_vs_reel.avec_duree_estimee(
            attendu, devis_id, m3.registre_devis_production(), m3.registre_production().lire())
    if charge != attendu:
        raise lecture.Refus('SOURCE-INCOHERENTE')
    return charge


def _reception(cnx, devis_id):
    condition = ((EVENEMENTS_RECUS.c.evenement_id == 'm3-devis-accepte-' + devis_id)
                 & (EVENEMENTS_RECUS.c.consommateur == M5))
    taille = cnx.execute(select(func.length(cast(EVENEMENTS_RECUS.c.resultat, LargeBinary)))
                        .where(condition)).scalar_one_or_none()
    if taille is not None and taille > lecture.MAX_SORTIE_OCTETS:
        raise lecture.Refus('SOURCE-TROP-VOLUMINEUSE')
    ligne = cnx.execute(select(EVENEMENTS_RECUS).where(condition)).mappings().one_or_none()
    if ligne is None:
        return 'EN_ATTENTE', None
    reference = encodage.empreinte(dict(ligne))
    if ligne['statut'] in ('echec', 'quarantaine'):
        return ('ECHEC_LIVRAISON' if ligne['statut'] == 'echec' else 'QUARANTAINE'), reference
    resultat = codec.decoder(ligne['resultat']) if ligne['resultat'] is not None else None
    if (ligne['statut'] != 'traite' or not isinstance(resultat, dict)
            or resultat.get('traite') is not True or resultat.get('devis_id') != devis_id):
        raise lecture.Refus('SOURCE-INCOHERENTE')
    return 'TRAITE', reference


def _m5(deps, session, devis_id):
    dep = deps.get(M5)
    if dep is None or dep.module_outils != 'm5_financecore.outils':
        raise lecture.Refus('SOURCE-INDISPONIBLE')
    outil = next((o for o in dep.charger_outils() if o.nom == 'm5_lire_rentabilite_chantier'), None)
    if outil is None or outil.autonomie != Autonomie.T0:
        raise lecture.Refus('SOURCE-INDISPONIBLE')
    with (contexte.appele_par_appareil(contexte.IdentiteAppelante(session.utilisateur, 'admin', source='console')),
          contexte.appeler_en_tant_que(M5, origine='console')):
        r = executer(outil, dict(devis_id=devis_id, limite=1))
    res = r.get('resultat') if r.get('ok') is True else None
    if not isinstance(res, dict) or res.get('accepte') is not True or not isinstance(res.get('resultat'), dict):
        raise lecture.Refus('SOURCE-INDISPONIBLE')
    return lecture._sortie(res['resultat'])


def lire(cnx, deps, session, lead_id, devis_id):
    from m5_financecore import devis_recus
    from m5_financecore import outils as m5

    autorite._admin(cnx, session)
    if any(type(i) is not str or lecture.IDENTIFIANT.fullmatch(i) is None or i in {'.', '..'}
           for i in (lead_id, devis_id)):
        raise lecture.Refus('INTROUVABLE')
    captures = _capture(cnx)
    refs, config = _references(captures), _configuration(m5)
    charge = _ancre(cnx, deps, session, lead_id, devis_id)
    statut, recu = _reception(cnx, devis_id) if charge is not None else ('NON_PUBLIE', None)
    resultat = dict(lead_id=lead_id, devis_id=devis_id, reception_m5=statut, chantier=None,
                    source_calculee=None)
    recus = [m for m in _lignes(captures, M5, 'devis_recus') if m.get('devis_id') == devis_id]
    if statut != 'TRAITE':
        if recus:
            raise lecture.Refus('SOURCE-INCOHERENTE')
    else:
        attendu = devis_recus.construire(**{k: charge[k] for k in ('devis_id', 'lead_id', 'chantier_id', 'lignes',
            'prix_total', 'horodatage_acceptation', 'cout_total', 'taux_marge')})
        if recus != [attendu]:
            raise lecture.Refus('SOURCE-INCOHERENTE')
        try:
            sources = m5._sources_cout_reel_depuis(dict(
                devis=_lignes(captures, M5, 'devis_recus'), wct=_lignes(captures, M5, 'wct_recus'),
                variance=_lignes(captures, M5, 'variance_recue'),
                factures=m5.registre_module.Registre(maillons=_lignes(captures, M5, 'factures')),
                rentabilite=_lignes(captures, M5, 'rentabilite'),
                livre=tuple(_lignes(captures, M6, 'livre_prix')), taux=m5._taux_horaire_depuis_octets(config[1])))
        except (ValueError, KeyError, TypeError):
            raise lecture.Refus('SOURCE-INCOHERENTE') from None
        etat = m5._etat_chantier(devis_id, sources)
        attendu_vue = lecture._sortie(m5._vue_chantier(etat, sources, True, detail=True))
        vue = _m5(deps, session, devis_id)
        if (vue.get('mention') != m5.analyse.MENTION_ANALYSE_PREPARATOIRE or vue.get('role') != 'admin'
                or (vue.get('nombre'), vue.get('affichees'), vue.get('reste')) != (1, 1, 0)
                or vue.get('chantiers') != [attendu_vue]):
            raise lecture.Refus('SOURCE-REPONSE-INCOHERENTE')
        resultat['chantier'] = attendu_vue
    autorite._admin(cnx, session)
    if (_references(_capture(cnx)) != refs or _configuration(m5) != config
            or _ancre(cnx, deps, session, lead_id, devis_id) != charge
            or (charge is not None and _reception(cnx, devis_id) != (statut, recu))):
        raise lecture.Refus('SOURCE-MODIFIEE')
    resultat['source_calculee'] = encodage.empreinte(dict(registres=refs, configuration=config[0],
        acceptation=charge, reception=recu))
    autorite._admin(cnx, session)
    return lecture._sortie(m5.analyse.avec_mention(resultat))


def contenu(vue, prefixe):
    from . import pages

    vue = _vue_sans_zero_invente(vue)

    def valeur(v):
        return 'Non disponible' if v is None else pages.e(v)

    base = (f'{prefixe}/crm/lead/{pages._segment(vue["lead_id"])}/soumissions/'
            f'{pages._segment(vue["devis_id"])}')
    export = base + '/couts-travaux/export.json'
    corps = (f'<p><a href="{pages.e(base)}">Retour à la soumission</a></p><section><h2>Coûts des travaux</h2>'
        f'<p><a href="{pages.e(export)}">Télécharger les coûts et leurs sources (JSON)</a></p>'
        '<p>Source : M5, devis accepté M3, temps et matériaux reçus par M5. '
        'Prix et taux actuels, sans attestation de dépense payée ou de coût historiquement figé.</p>'
        f'<p>{pages.e(vue["mention"])}</p>'
        '<p>Consultation seule. Les extras et dépenses hors du contrat actuel M5 ne sont pas inventés.</p>')
    etat = vue['chantier']
    if etat is None:
        receptions = {'NON_PUBLIE': 'Acceptation sans publication vers M5', 'EN_ATTENTE': 'Réception M5 en attente',
            'QUARANTAINE': 'Réception M5 en quarantaine', 'ECHEC_LIVRAISON': 'Réception M5 en échec'}
        return corps + f'<p>{pages.e(receptions[vue["reception_m5"]])}</p></section>'
    if etat['statut'] != 'calculee':
        attentes = {'en_attente_travaux_termines': 'En attente des travaux terminés',
                    'en_attente_devis_accepte': 'En attente du devis accepté dans M5'}
        return corps + f'<p>{pages.e(attentes[etat["statut"]])}</p></section>'
    r = etat['rentabilite']
    cout, materiaux = r['cout_reel'], r['cout_reel']['materiaux']
    corps += (f'<h3>{"Coût complet selon M5" if cout["complet"] else "Coût partiel"}</h3>'
              f'<p>Devise : {valeur(cout["devise"])} · Facture : {valeur(r["statut_facture"])}</p>')
    if not r['prix_definitif']:
        corps += '<p role="alert">Prix non définitif : facture absente ou brouillon selon M5.</p>'
    corps += ('<p>Trace de calcul à jour</p>' if etat['trace']['a_jour'] else
              '<p role="alert">Trace de calcul antérieure : le calcul actuel n’a pas réécrit cette trace.</p>')
    chiffres = [('Coût prévu du devis', r['cout_prevu']), ('Prix prévu du devis', r['prix_prevu']),
        ('Coût total calculé', cout['cout_total']), ('Coût total connu', cout['cout_total_connu']),
        ('Matériaux connus', materiaux['cout_connu']), ('Main-d’œuvre', cout['main_d_oeuvre']['cout']),
        ('Prix de facture', r['prix_facture']), ('Marge prévue', r['marge_prevue']),
        ('Marge réelle calculée', r['marge_reelle']), ('Écart de marge', r['ecart_marge'])]
    corps += '<table><thead><tr><th>Mesure</th><th>Valeur M5</th></tr></thead><tbody>'
    corps += ''.join(f'<tr><th>{pages.e(nom)}</th><td>{valeur(v)}</td></tr>' for nom, v in chiffres)
    corps += '</tbody></table><h3>Matériaux reçus dans le calcul M5</h3>'
    corps += '<table><thead><tr><th>Matériau</th><th>Quantité réelle</th><th>Unité</th>'
    corps += '<th>Prix unitaire</th><th>Coût</th><th>État M5</th></tr></thead><tbody>'
    for ligne in materiaux['lignes']:
        corps += '<tr>' + ''.join(f'<td>{valeur(ligne[cle])}</td>' for cle in
            ('materiau', 'quantite_reelle', 'unite', 'prix_unitaire', 'cout', 'statut')) + '</tr>'
    corps += '</tbody></table><h3>Sources des prix M6 utilisées par M5</h3><ul>'
    for ligne in materiaux['lignes']:
        for source in ligne['sources_prix']:
            corps += '<li>' + ' · '.join(valeur(source.get(k)) for k in
                ('fournisseur_id', 'date_effet', 'source_document')) + '</li>'
    corps += '</ul><h3>Main-d’œuvre M5</h3>'
    mo = cout['main_d_oeuvre']
    corps += (f'<p>État : {valeur(mo["statut"])} · Minutes : {valeur(mo["minutes"])} · '
              f'Taux horaire : {valeur(mo["taux_horaire"])}</p><h3>Manques M5</h3><ul>')
    for manque in cout['manque'] + r['manque']:
        corps += f'<li>{pages.e(manque.get("code"))} : {pages.e(manque.get("detail"))}</li>'
    corps += '</ul><h3>Hypothèses M5</h3><ul>'
    corps += ''.join(f'<li>{pages.e(h)}</li>' for h in cout['hypotheses'])
    corps += (f'</ul><p>Arrondi M5 : {pages.e(cout["arrondi"])}</p><details><summary>Source de consultation</summary>'
              f'<p>Empreinte calculée : {pages.e(vue["source_calculee"])}</p></details></section>')
    return corps


def _vue_sans_zero_invente(vue):
    """Copie la vue pour distinguer une absence de coût d'un zéro attesté."""
    copie = copy.deepcopy(vue)
    etat = copie.get('chantier')
    if isinstance(etat, dict) and etat.get('statut') == 'calculee':
        rentabilite = etat['rentabilite']
        cout = rentabilite['cout_reel']
        materiaux, main = cout['materiaux'], cout['main_d_oeuvre']
        materiaux_connus = (materiaux['statut'] == 'complet'
                            or any(ligne.get('cout') is not None for ligne in materiaux['lignes']))
        if not materiaux_connus:
            materiaux['cout_connu'] = None
        if not materiaux_connus and main.get('cout') is None and main.get('cout_connu') is None:
            cout['cout_total_connu'] = None
            rentabilite['marge_partielle_plafond'] = None
            rentabilite['marge_partielle_plafond_pct_du_prix'] = None
    return copie


def _exporter(vue):
    """Encode la lecture vérifiée, sans convertir une absence de composante en coût nul."""
    document = {
        'format': 'opsys.couts-travaux.export.v1',
        'mention': 'Export préparatoire pour revue ; aucune écriture comptable, facture envoyée ou paiement.',
        'vue': _vue_sans_zero_invente(vue),
    }
    return json.dumps(document, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')


def creer_router(*, session_page, cnx_factory, deps, prefixe, rendre):
    from fastapi import APIRouter, HTTPException, Request
    from fastapi.responses import Response

    router = APIRouter()

    @router.get('/crm/lead/{lead_id}/soumissions/{devis_id}/couts-travaux')
    def page(lead_id: str, devis_id: str, request: Request):
        session = session_page(request)
        if request.query_params:
            raise HTTPException(400, 'Paramètres de consultation invalides')
        try:
            with cnx_factory() as cnx:
                vue = lire(cnx, deps, session, lead_id, devis_id)
                try:
                    reponse = rendre(session, 'Coûts des travaux', contenu(vue, prefixe))
                except (ValueError, KeyError, TypeError):
                    raise HTTPException(503, 'Présentation des coûts indisponible') from None
                if len(reponse.body) > 131072:
                    raise HTTPException(503, 'Présentation des coûts trop volumineuse')
                autorite._admin(cnx, session)
        except PermissionError:
            raise HTTPException(403, 'Accès admin requis') from None
        except lecture.Refus as exc:
            code = {'INTROUVABLE': 404, 'DEVIS-NON-ACCEPTE': 409}.get(exc.code, 503)
            raise HTTPException(code, 'Coûts indisponibles : ' + exc.code) from None
        except (ValueError, KeyError, TypeError):
            raise HTTPException(503, 'Sources de coûts indisponibles') from None
        return reponse

    @router.get('/crm/lead/{lead_id}/soumissions/{devis_id}/couts-travaux/export.json')
    def export(lead_id: str, devis_id: str, request: Request):
        session = session_page(request)
        if request.query_params:
            raise HTTPException(400, 'Paramètres de consultation invalides')
        try:
            with cnx_factory() as cnx:
                vue = lire(cnx, deps, session, lead_id, devis_id)
                donnees = _exporter(vue)
                if len(donnees) > 131072:
                    raise lecture.Refus('SORTIE-TROP-VOLUMINEUSE')
                reponse = Response(donnees, media_type='application/json', headers={
                    'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                    'Content-Security-Policy': "default-src 'none'; frame-ancestors 'none'; sandbox",
                    'Content-Disposition': 'attachment; filename="couts-travaux.json"',
                })
                if lire(cnx, deps, session, lead_id, devis_id) != vue:
                    raise lecture.Refus('SOURCE-MODIFIEE')
                autorite._admin(cnx, session)
        except PermissionError:
            raise HTTPException(403, 'Accès admin requis') from None
        except lecture.Refus as exc:
            code = {'INTROUVABLE': 404, 'DEVIS-NON-ACCEPTE': 409}.get(exc.code, 503)
            raise HTTPException(code, 'Coûts indisponibles : ' + exc.code) from None
        except (ValueError, KeyError, TypeError, OverflowError):
            raise HTTPException(503, 'Sources de coûts indisponibles') from None
        return reponse

    return router
