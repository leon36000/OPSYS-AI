"""Lecture admin exacte devis accepté → réception M4 → préparation, sans mutation."""
import json
import re
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import LargeBinary, cast, func, select

from .. import cles_chiffrement, contexte, identite, stockage
from ..evenements.schemas import erreurs_charge
from ..outils import Autonomie, executer, vers_json
from ..stockage import codec
from ..stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS, REGISTRES
from . import pages

M2, M3, M4 = 'm02-revenue-crm', 'm03-estimation', 'm04-field-ops'
MODULES = {M2: 'm2_revenue_crm.outils', M3: 'm3_estimation.outils', M4: 'm4_field_ops.outils'}
IDENTIFIANT = re.compile(r'[\w.:@\-]{1,200}')
MAX_SOURCES = 10000
MAX_SOURCE_OCTETS = 8388608
MAX_SORTIE_OCTETS = 65536


class Refus(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _borner(cnx, departement, registre):
    condition = (REGISTRES.c.departement == departement) & (REGISTRES.c.registre == registre)
    n, taille = cnx.execute(select(func.count(), func.sum(func.length(cast(REGISTRES.c.maillon, LargeBinary))))
                           .select_from(REGISTRES).where(condition)).one()
    if n > MAX_SOURCES or (taille or 0) > MAX_SOURCE_OCTETS:
        raise Refus('SOURCE-TROP-VOLUMINEUSE')


def _sortie(resultat):
    resultat = vers_json(resultat)
    quota = contexte.limite_sortie()
    maximum = min(MAX_SORTIE_OCTETS, quota) if quota is not None else MAX_SORTIE_OCTETS
    if len(json.dumps(resultat, ensure_ascii=False, allow_nan=False).encode('utf-8')) > maximum:
        raise Refus('SORTIE-TROP-VOLUMINEUSE')
    return resultat


def _appel(deps, utilisateur, departement, nom, args):
    dep = deps.get(departement)
    if dep is None or dep.module_outils != MODULES[departement]:
        raise Refus('SOURCE-INDISPONIBLE')
    outil = next((o for o in dep.charger_outils() if o.nom == nom), None)
    if outil is None or outil.autonomie != Autonomie.T0:
        raise Refus('SOURCE-INDISPONIBLE')
    with (contexte.appele_par_appareil(contexte.IdentiteAppelante(utilisateur, 'admin', source='console')),
          contexte.appeler_en_tant_que(departement, origine='console')):
        reponse = executer(outil, args)
    res = reponse.get('resultat') if reponse.get('ok') is True else None
    if not isinstance(res, dict) or res.get('accepte') is not True or not isinstance(res.get('resultat'), dict):
        code = res.get('verdict', {}).get('code') if isinstance(res, dict) else None
        if code in {'REJ-LEAD-INCONNU', 'REJ-DEVIS-INTROUVABLE'}:
            raise Refus('INTROUVABLE')
        raise Refus('SOURCE-INDISPONIBLE')
    return res['resultat']


def _publication(cnx, ident, typ, producteur):
    condition = EVENEMENTS_SORTANTS.c.evenement_id == ident
    taille = cnx.execute(select(func.length(cast(EVENEMENTS_SORTANTS.c.charge, LargeBinary)))
                        .where(condition)).scalar_one_or_none()
    if taille is None:
        return None
    if taille > MAX_SORTIE_OCTETS:
        raise Refus('SOURCE-TROP-VOLUMINEUSE')
    ligne = cnx.execute(select(EVENEMENTS_SORTANTS).where(condition)).mappings().one()
    charge = codec.decoder(ligne['charge'])
    if ligne['type_evenement'] != typ or ligne['producteur'] != producteur or erreurs_charge(typ, charge):
        raise Refus('SOURCE-INCOHERENTE')
    return charge


def _reception(cnx, evenement_id, lead_id, devis_id, intervention):
    condition = ((EVENEMENTS_RECUS.c.evenement_id == evenement_id) & (EVENEMENTS_RECUS.c.consommateur == M4))
    taille = cnx.execute(select(func.length(cast(EVENEMENTS_RECUS.c.resultat, LargeBinary)))
                        .where(condition)).scalar_one_or_none()
    # Un reçu d'échec peut légitimement n'avoir aucun résultat. Ne jamais afficher son erreur libre.
    if taille is not None and taille > MAX_SORTIE_OCTETS:
        raise Refus('SOURCE-TROP-VOLUMINEUSE')
    recu = cnx.execute(select(EVENEMENTS_RECUS.c.statut, EVENEMENTS_RECUS.c.resultat)
                      .where(condition)).mappings().one_or_none()
    if recu is None:
        return 'EN_ATTENTE'
    if recu['statut'] in {'echec', 'quarantaine'}:
        return 'ECHEC_LIVRAISON' if recu['statut'] == 'echec' else 'QUARANTAINE'
    resultat = codec.decoder(recu['resultat']) if recu['resultat'] is not None else None
    if (recu['statut'] != 'traite' or not isinstance(resultat, dict) or resultat.get('traite') is not True
            or resultat.get('lead_id') != lead_id or resultat.get('devis_id') != devis_id
            or intervention is None or resultat.get('intervention_id') != intervention['intervention_id']):
        raise Refus('SOURCE-INCOHERENTE')
    return 'TRAITE'


def lire(cnx, deps, session, lead_id, devis_id):
    """Port privé console; aucune fonction d'acceptation, de dispatch ou d'écriture appelée."""
    from m3_estimation import devis_durable, estime_vs_reel
    from m3_estimation import outils as m3
    from m4_field_ops import cedule, etats, preparation, registre
    from m4_field_ops import outils as m4

    if cnx is not stockage.connexion_courante() or cnx.dialect.name != 'sqlite':
        raise Refus('INSTANCE-NON-QUALIFIEE')
    personne = identite.personne_active(cnx, session.utilisateur)
    if (personne is None or 'admin' not in personne.roles
            or session.expire <= datetime.now(UTC).timestamp()):
        raise PermissionError('admin actif requis')
    if any(type(i) is not str or IDENTIFIANT.fullmatch(i) is None or i in {'.', '..'} for i in (lead_id, devis_id)):
        raise Refus('INTROUVABLE')
    for dep, reg in [(M2, 'principal'), (M3, 'devis'), (M3, 'principal'), (M4, 'principal')]:
        _borner(cnx, dep, reg)
    _appel(deps, personne.identifiant, M2, 'm2_trouver_client_de_lead', dict(lead_id=lead_id))
    devis, verdict = devis_durable.lire_devis(m3.registre_devis_production(), devis_id)
    if verdict is not None or devis.get('lead_id') != lead_id:
        raise Refus('INTROUVABLE')
    if devis['statut'] != 'accepte':
        raise Refus('DEVIS-NON-ACCEPTE')
    projection, verdict = devis_durable.projeter_devis(devis, 'employe')
    if verdict is not None:
        raise Refus('SOURCE-INCOHERENTE')
    source_m1 = _publication(cnx, f'm1-lead-qualifie-{lead_id}', 'm1.lead_qualifie', 'm01-front-office')
    if source_m1 is not None and source_m1.get('lead', {}).get('lead_id') != lead_id:
        raise Refus('SOURCE-INCOHERENTE')
    resultat = dict(lead_id=lead_id, devis_id=devis_id, horodatage_acceptation=projection['horodatage'],
                    lignes=projection['lignes'], source_m1='PRESENTE' if source_m1 is not None else 'ABSENTE',
                    reception_m4='NON_PUBLIE', intervention=None, intervention_recherchee=False,
                    preparation=None, ancre_complete=False)
    evenement_id = f'm3-devis-accepte-{devis_id}'
    charge = _publication(cnx, evenement_id, 'm3.devis_accepte', M3)
    if charge is None:
        return _sortie(resultat)
    attendu = devis_durable.charge_evenement_devis_accepte(devis)
    source = m3._source_estimation_exacte(devis.get('estimation_source_hash'), devis_id, lead_id)
    if source is not None:
        attendu = estime_vs_reel.avec_duree_estimee(
            attendu, devis_id, m3.registre_devis_production(), m3.registre_production().lire())
    if charge != attendu:
        raise Refus('SOURCE-INCOHERENTE')
    chaine = registre.Registre(stockage.maillons(M4, 'principal'))
    try:
        chaine.assert_chaine()
    except registre.VerificationError:
        raise Refus('SOURCE-INCOHERENTE') from None
    ident = etats.intervention_du_devis(chaine, devis_id)
    inscriptions = [i for i in chaine.lire() if i['type_entree'] == etats.TYPE_INSCRIPTION
                    and i.get('devis_id') == devis_id]
    if (len(inscriptions) > 1 or (ident is None) != (len(inscriptions) == 0)
            or (inscriptions and (inscriptions[0]['intervention_id'] != ident
                                  or inscriptions[0]['lead_id'] != lead_id))):
        raise Refus('SOURCE-INCOHERENTE')
    intervention = None
    ancre_bus = False
    if inscriptions:
        inscription = inscriptions[0]
        cle, valeur = etats.travaux_de(inscription)
        intervention = dict(intervention_id=ident, lead_id=lead_id, devis_id=devis_id,
                            statut=etats.statut_courant(chaine, ident), **{cle: valeur})
        if inscription.get('source') == etats.SOURCE_DEVIS_ACCEPTE:
            if inscription.get('horodatage') != charge['horodatage_acceptation']:
                raise Refus('SOURCE-INCOHERENTE')
            if source_m1 is not None:
                lead = source_m1['lead']
                sel = cles_chiffrement.lire(cnx, m4._PORTEE_SEL_VILLE, m4._IDENTIFIANT_SEL_VILLE)
                if (any(inscription.get(c) != lead[c] for c in ('schema_version', 'service', 'urgence_declaree'))
                        or sel is None or inscription.get('ville_tokenisee') != cedule.tokeniser_ville(
                            sel.hex(), lead['ville'])):
                    raise Refus('SOURCE-INCOHERENTE')
                ancre_bus = True
    resultat.update(intervention=intervention, intervention_recherchee=True,
                    reception_m4=_reception(cnx, evenement_id, lead_id, devis_id, intervention))
    if intervention is not None and intervention['statut'] in preparation.STATUTS_PREPARABLES:
        resultat['preparation'] = _appel(deps, personne.identifiant, M4, 'm4_verifier_preparation',
                                        dict(intervention_id=ident))
    resultat['ancre_complete'] = (resultat['reception_m4'] == 'TRAITE' and resultat['source_m1'] == 'PRESENTE'
                                  and ancre_bus)
    return _sortie(resultat)


def contenu(vue, prefixe):
    reception = {'NON_PUBLIE': 'Acceptation sans publication vers M4', 'EN_ATTENTE': 'Réception M4 en attente',
                 'ECHEC_LIVRAISON': 'Réception M4 en échec', 'QUARANTAINE': 'Réception M4 en quarantaine',
                 'TRAITE': 'Réception M4 confirmée'}
    base = f'{prefixe}/crm/lead/{pages._segment(vue["lead_id"])}/soumissions/{pages._segment(vue["devis_id"])}'
    corps = (f'<p><a href="{pages.e(base)}">Retour à la soumission</a></p><h2>Préparer la planification</h2>'
             f'<p>Devis accepté : {pages.e(vue["devis_id"])} · {pages.e(vue["horodatage_acceptation"])}</p>'
             f'<p data-reception-m4="{vue["reception_m4"]}">{reception[vue["reception_m4"]]}</p>'
             '<p>' + ('Source M1 vérifiée' if vue['source_m1'] == 'PRESENTE' else 'Source M1 absente') + '</p>'
             '<p>Lecture seulement. Aucune date ni disponibilité promise par cet écran. '
             'Les règles météo ne constituent pas une prévision du créneau.</p>')
    if not vue['ancre_complete']:
        corps += '<p role="alert">Les preuves de transfert sont incomplètes; aucun créneau n’est confirmé.</p>'
    i = vue['intervention']
    if i is None:
        corps += ('<p>Aucune intervention M4 trouvée pour ce devis; la vue n’en crée pas.</p>'
                  if vue['intervention_recherchee'] else '<p>Intervention non vérifiée : publication absente.</p>')
    else:
        corps += f'<p>Intervention : {pages.e(i["intervention_id"])} · état : {pages.e(i["statut"])}</p>'
        corps += f'<p>Service : {pages.e(i.get("service", i.get("type_travaux")))}</p>'
    corps += '<h3>Travaux et matériaux du devis</h3><ul>'
    for ligne in vue['lignes']:
        corps += (f'<li>{pages.e(ligne["description"])} · {pages.e(ligne["quantite"])} '
                  f'{pages.e(ligne["unite"])} · référence : {pages.e(ligne.get("reference_besoin_materiau"))}</li>')
    corps += '</ul>'
    p = vue['preparation']
    if p is not None:
        corps += f'<h3>Préparation M4 : {pages.e(p["statut"])}</h3><dl>'
        for nom, volet in p['volets'].items():
            corps += (f'<dt>{pages.e(nom)} : {pages.e(volet["statut"])}</dt>'
                      f'<dd>{pages.e(volet.get("manque") or volet.get("detail") or "")}</dd>')
        corps += '</dl>'
    elif i is not None:
        corps += '<p>Préparation sans objet pour l’état courant de l’intervention.</p>'
    return corps


def creer_router(*, session_page, cnx_factory, deps, prefixe, rendre):
    router = APIRouter()

    @router.get('/crm/lead/{lead_id}/soumissions/{devis_id}/preparation-chantier')
    def page(lead_id: str, devis_id: str, request: Request):
        session = session_page(request)
        if request.query_params:
            raise HTTPException(400, 'Paramètres invalides')
        try:
            with cnx_factory() as cnx:
                vue = lire(cnx, deps, session, lead_id, devis_id)
        except PermissionError:
            raise HTTPException(403, 'Accès admin requis') from None
        except Refus as exc:
            statut = {'INTROUVABLE': 404, 'DEVIS-NON-ACCEPTE': 409}.get(exc.code, 503)
            raise HTTPException(statut, 'Préparation indisponible : ' + exc.code) from None
        except (ValueError, KeyError, TypeError):
            raise HTTPException(503, 'Sources de préparation indisponibles') from None
        reponse = rendre(session, 'Préparation du chantier', contenu(vue, prefixe))
        if len(reponse.body) > 131072:
            raise HTTPException(503, 'Préparation trop volumineuse')
        return reponse

    return router
