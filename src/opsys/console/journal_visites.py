"""Liens privés du journal vers les seules visites identifiées par des faits vérifiés."""
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from m4_field_ops import (
    composition_durable,
    encodage,
    etats,
    pointage,
    visites_chantier,
    visites_durables,
    visites_ecriture,
)
from m4_field_ops.registre import Registre

from . import preparation_chantier as lecture


def capturer_sources(cnx):
    return visites_ecriture.capturer_visites(cnx), composition_durable.capturer(cnx)


def source_journal(source, visites, composition, jour):
    # Sans prévision explicite, aucun lien ne dépend d'une composition : une
    # déclaration ne doit pas invalider le journal historique non enrichi.
    source_composition = composition.empreinte_snapshot_calculee if visites.lignes else None
    return encodage.empreinte('journal_console_v2', source.empreinte_snapshot_calculee,
                             visites.empreinte_snapshot_calculee, source_composition, jour)


def enrichir(cnx, source, journal, snapshot, composition):
    """Décore la projection T0 après comparaison ; ne modifie pas son contrat partagé."""
    principal = Registre([r.maillon for r in source.lignes])
    from .visites_chantier import source_consultation
    visites = Registre([r.maillon for r in snapshot.lignes])
    _, previsions, _, _, _, _ = visites_durables._charger(principal, visites)
    maillons = principal.lire()
    indices = {m['ligne_id']: n for n, m in enumerate(maillons)}
    par_id = {m['ligne_id']: m for m in previsions}
    ancres = {tuple(m['ancre'][k] for k in ('intervention_id', 'plan_id', 'source_application_id',
                                               'source_ligne_id')): m for m in previsions}
    par_intervention = {}
    for p in previsions:
        par_intervention.setdefault(p['ancre']['intervention_id'], []).append(p)
    ouvertures = {}
    for n, m in enumerate(maillons):
        if m.get('type_entree') == 'visite_ouverte':
            ident = m.get('visite_id')
            if ident in ouvertures:
                raise lecture.Refus('SOURCE-VISITE-INVALIDE')
            ouvertures[ident] = (n, m)
    sources_lien, ouvertures_validees = {}, set()
    for ligne in journal['lignes']:
        iid = ligne['intervention_id']
        if ligne['type'] == 'prevision':
            ancre = tuple(ligne[k] for k in ('intervention_id', 'plan_id', 'source_application_id', 'source_ligne_id'))
            prevision = ancres.get(ancre)
            ident = prevision['ligne_id'] if prevision else None
        else:
            rang = indices[ligne['source_ligne_id']]
            fait = maillons[rang]
            ident = fait.get('visite_id')
            if ident is None:
                continue  # ancien fait : jamais attribué par proximité
            prevision = par_id.get(ident)
            if prevision is None or prevision['ancre']['intervention_id'] != iid or ident not in ouvertures:
                raise lecture.Refus('SOURCE-VISITE-INVALIDE')
            rang_ouverture, ouverture = ouvertures[ident]
            ancre, creneau = prevision['ancre'], prevision['creneau']
            if (rang_ouverture >= rang or ouverture['intervention_id'] != iid
                    or ouverture.get('source_calendrier') != ancre['source_ligne_id']
                    or ouverture.get('source_application') != ancre['source_application_id']
                    or ouverture.get('equipe_id') != creneau['equipe_id']
                    or visites_chantier._instant(ouverture['horodatage']) <
                       visites_chantier._instant(prevision['horodatage'])
                    or visites_chantier._instant(ouverture['horodatage']).astimezone(
                        ZoneInfo('America/Montreal')).date().isoformat() != creneau['debut'][:10]):
                raise lecture.Refus('SOURCE-VISITE-INVALIDE')
            if ident not in ouvertures_validees:
                visites_chantier.verifier_ouverture_courante(Registre(maillons[:rang_ouverture]), ouverture)
                ouvertures_validees.add(ident)
            if visites_chantier._instant(fait['horodatage']) < visites_chantier._instant(ouverture['horodatage']):
                raise lecture.Refus('SOURCE-VISITE-INVALIDE')
            if fait.get('type_entree') == etats.TYPE_TRANSITION and fait.get('statut') == 'reportee':
                fermeture_id = fait.get('source_fermeture')
                rang_fermeture = indices.get(fermeture_id, -1)
                if not rang_ouverture < rang_fermeture < rang:
                    raise lecture.Refus('SOURCE-VISITE-INVALIDE')
                fermeture = maillons[rang_fermeture]
                rang_depart = indices.get(fermeture.get('source_depart'), -1)
                if (fermeture.get('type_entree') != 'visite_fermee' or fermeture.get('visite_id') != ident
                        or fermeture.get('ouverture_id') != ouverture['ligne_id']
                        or not rang_ouverture < rang_depart < rang_fermeture
                        or maillons[rang_depart].get('type_entree') != pointage.TYPE_POINTAGE
                        or maillons[rang_depart].get('action') != 'depart'
                        or maillons[rang_depart].get('visite_id') != ident
                        or maillons[rang_depart].get('intervention_id') != iid):
                    raise lecture.Refus('SOURCE-VISITE-INVALIDE')
            elif (fait.get('type_entree') == pointage.TYPE_POINTAGE or
                  (fait.get('type_entree') == etats.TYPE_TRANSITION and fait.get('statut') == 'en_route')):
                active = visites_chantier.visite_active(Registre(maillons[:rang]), iid)
                if active is None or active['ligne_id'] != ouverture['ligne_id']:
                    raise lecture.Refus('SOURCE-VISITE-INVALIDE')
                if fait.get('type_entree') == etats.TYPE_TRANSITION:
                    visites_chantier.verifier_ouverture_courante(Registre(maillons[:rang]), ouverture)
                else:
                    routes = [m for m in maillons[rang_ouverture + 1:rang]
                              if m.get('type_entree') == etats.TYPE_TRANSITION and m.get('statut') == 'en_route'
                              and m.get('intervention_id') == iid and m.get('visite_id') == ident]
                    if len(routes) != 1 or routes[0].get('technicien_id') != fait.get('technicien_id'):
                        raise lecture.Refus('SOURCE-VISITE-INVALIDE')
            else:
                raise lecture.Refus('SOURCE-VISITE-INVALIDE')
        if ident is None:
            continue
        if iid not in sources_lien:
            sources_lien[iid] = source_consultation(source, snapshot, composition, iid)
        positions = [p['ligne_id'] for p in par_intervention[iid]]
        index = positions.index(ident)
        params = {'intervention_id': iid}
        if index >= 50:
            params.update(debut=(index // 50) * 50, limite=50, source_attendue=sources_lien[iid])
        ligne['visite_consultation'] = {'visite_id': ident, 'query': urlencode(params)}
    if any('visite_consultation' in ligne for ligne in journal['lignes']):
        journal['avertissements'] = [
            ('Liens de visite seulement si les sources explicites sont vérifiées ; aucune durée quotidienne calculée.'
             if a == 'Aucune association de pointage à une visite précise ni durée quotidienne calculée.' else a)
            for a in journal['avertissements']]
    comp_final = composition_durable.capturer(cnx)
    if (visites_ecriture.capturer_visites(cnx).empreinte_snapshot_calculee != snapshot.empreinte_snapshot_calculee
            or comp_final.empreinte_snapshot_calculee != composition.empreinte_snapshot_calculee):
        raise lecture.Refus('SOURCE-MODIFIEE')
    return journal
