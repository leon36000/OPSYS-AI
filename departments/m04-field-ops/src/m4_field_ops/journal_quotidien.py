"""CRM-16 : projection privée d'une journée, sans horloge, GPS, RH ni calcul de paie.

Prévisions historiques et faits horodatés restent distincts. L'adaptateur doit encore
fournir le snapshot canonique et contrôler l'admin : ce lecteur n'est pas une API exposée.
"""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from . import annotations_calendrier as annotations
from . import calendrier_civil as calendrier
from . import cedule_tournees, ecarts, encodage, etats, horodatage, outbox, pointage
from .registre import Registre, VerificationError

MAX_SOURCES = 10000
MAX_OCTETS = 8 * 1024 * 1024
MAX_PREVISIONS = 1000
AVERTISSEMENTS = [
    'Prévision datée ne signifie pas présence ou travaux réalisés.',
    'Absence de pointage ne signifie pas absence du salarié.',
    'Le technicien pointé ne prouve pas la composition historique de son équipe.',
    'Aucune association de pointage à une visite précise ni durée quotidienne calculée.',
    'Textes des notes, extras détaillés, absences et composition historique non inclus dans cette projection.',
]


def _texte(v):
    if not isinstance(v, str) or not v.strip():
        raise ValueError('identifiant source invalide')
    return v


def _capture(reg):
    if reg.taille() > MAX_SOURCES:
        raise ValueError('sources trop volumineuses')
    maillons = reg.lire()
    if len(maillons) > MAX_SOURCES or len(json.dumps(maillons, ensure_ascii=False).encode()) > MAX_OCTETS:
        raise ValueError('sources trop volumineuses')
    copie = Registre(maillons)
    copie.assert_chaine()
    return copie, maillons


def _previsions(sources, maillons, jour):
    par_id, courantes = sources
    propositions = {m['plan_id']: m for m in maillons if m['type_entree'] == cedule_tournees.TYPE_PROPOSEE}
    dates = [m for m in maillons if m['type_entree'] == calendrier.TYPE_DATEE]
    suivantes, derniere = {}, {}
    for m in reversed(dates):
        suivantes[m['ligne_id']] = derniere.get(m['plan_id'])
        derniere[m['plan_id']] = m['ligne_id']
    lignes = []
    for m in dates:
        # Une ancienne date ne devient jamais la dernière date du plan.
        if jour not in m['calendrier'].values():
            continue
        proposition = propositions[m['plan_id']]
        for route, visite in calendrier._visites(proposition):
            if m['calendrier'][str(route['jour'])] != jour:
                continue
            if len(lignes) >= MAX_PREVISIONS:
                raise ValueError('prévisions du jour trop volumineuses')
            ancre = {'plan_id': m['plan_id'], 'intervention_id': visite['chantier'],
                     'source_ligne_id': m['ligne_id'], 'source_application_id': m['source_application_id']}
            creneau = annotations._creneau((par_id, {}), ancre)
            courante = courantes.get(annotations._cle(ancre))
            lignes.append({'type': 'prevision', **ancre, 'revision': creneau['revision_calendrier'],
                           'equipe_planifiee': creneau['equipe_id'], 'debut': creneau['debut'],
                           'fin': creneau['fin'], 'remplace_par': suivantes[m['ligne_id']],
                           'source_courante': courante is not None,
                           'validite': courante['validite'] if courante is not None else 'historique',
                           'instant': creneau['debut']})
    return lignes


def _inscriptions(maillons):
    inscriptions = {}
    for rang, m in enumerate(maillons):
        if m['type_entree'] == etats.TYPE_INSCRIPTION:
            inscriptions.setdefault(_texte(m['intervention_id']), []).append(rang)
    return inscriptions


def _verifier_inscription(m, rang, inscriptions):
    origines = inscriptions.get(m['intervention_id'], [])
    if len(origines) != 1 or origines[0] >= rang:
        raise ValueError('inscription unique antérieure requise pour chaque fait')


def _faits(maillons, jour):
    lignes, inscriptions = [], _inscriptions(maillons)
    for rang, m in enumerate(maillons):
        typ = m['type_entree']
        if typ not in {pointage.TYPE_POINTAGE, etats.TYPE_TRANSITION, etats.TYPE_ASSIGNATION}:
            continue
        _verifier_inscription(m, rang, inscriptions)
        horodatage.valider_horodatage(m['horodatage'])
        assignee = typ == etats.TYPE_ASSIGNATION or (typ == etats.TYPE_TRANSITION and m.get('statut') == 'en_route')
        if assignee:
            # Contrat historique des deux writers : chaîne différente de vide, sans normalisation.
            if not isinstance(m['technicien_id'], str) or m['technicien_id'] == '':
                raise ValueError('technicien assigné invalide')
            avant = etats.statut_courant(cedule_tournees._Instantane(maillons[:rang]), m['intervention_id'])
            if avant is None or avant in etats.ETATS_TERMINAUX:
                raise ValueError('assignation hors état non terminal')
            if typ == etats.TYPE_TRANSITION and (avant != 'planifiee' or m['statut_precedent'] != avant):
                raise ValueError('départ sans préfixe planifié cohérent')
        instant = datetime.fromisoformat(m['horodatage']).astimezone(ZoneInfo(calendrier.FUSEAU))
        if instant.date().isoformat() != jour:
            continue
        types = {pointage.TYPE_POINTAGE: 'pointage', etats.TYPE_TRANSITION: 'etat',
                 etats.TYPE_ASSIGNATION: 'assignation'}
        ligne = {'type': types[typ],
                 'source_ligne_id': _texte(m['ligne_id']), 'intervention_id': _texte(m['intervention_id']),
                 'instant': instant.isoformat(), 'origine_heure': horodatage.origine(m),
                 'ancre_visite': None}
        if assignee:
            ligne['technicien_assigne'] = m['technicien_id']
        if typ == pointage.TYPE_POINTAGE:
            if m['action'] not in pointage.ACTIONS:
                raise ValueError('action de pointage invalide')
            ligne.update(action=m['action'], technicien_id=_texte(m['technicien_id']))
        elif typ == etats.TYPE_TRANSITION:
            if m['statut'] not in etats.ETATS:
                raise ValueError('état invalide')
            ligne['statut'] = m['statut']
            if m['statut'] == 'reportee':
                if m['motif'] not in etats.MOTIFS_REPORT:
                    raise ValueError('motif de report invalide')
                ligne['motif'] = m['motif']
        lignes.append(ligne)
    return lignes


def _demandes(maillons):
    demandes, inscriptions = {}, _inscriptions(maillons)
    for rang, m in enumerate(maillons):
        if m['type_entree'] != pointage.TYPE_DEMANDE_REVUE:
            continue
        ident = _texte(m['demande_id'])
        if ident in demandes:
            raise ValueError('demande unique requise, y compris entre types')
        _verifier_inscription(m, rang, inscriptions)
        horodatage.valider_horodatage(m['horodatage'])
        if (m['type_demande'] not in ecarts.TYPES_DEMANDE
                or ident != encodage.empreinte('demande_revue', m['intervention_id'], m['horodatage'])):
            raise ValueError('identifiant ou type de demande invalide')
        if m['type_demande'] == 'ecart_metier':
            statut = etats.statut_courant(cedule_tournees._Instantane(maillons[:rang]), m['intervention_id'])
            if statut is None or statut in etats.ETATS_TERMINAUX:
                raise ValueError('déclaration hors état opérationnel non terminal')
            ecarts._valider_version(m['version_prevue'])
            ecarts._valider_version(m['version_declaree'])
            if m['version_prevue'] == m['version_declaree'] or m['statut_arbitrage'] != 'en_attente':
                raise ValueError('déclaration sans écart ou état initial invalide')
        demandes[ident] = (rang, m)
    return demandes, inscriptions


def _verifier_transition_ecart(maillons, rang, resolution):
    if rang < 1:
        raise ValueError('transition de résolution absente')
    compagnon = maillons[rang - 1]
    avant = etats.statut_courant(cedule_tournees._Instantane(maillons[:rang - 1]), resolution['intervention_id'])
    cible = 'annulee' if resolution['decision'] == 'rejetee' else 'completed_pending_review'
    if (compagnon['type_entree'] != etats.TYPE_TRANSITION
            or compagnon.get('intervention_id') != resolution['intervention_id']
            or compagnon.get('horodatage') != resolution['horodatage']
            or compagnon.get('statut') != cible or compagnon.get('statut_precedent') != avant
            or (avant, cible) not in etats.TRANSITIONS_AUTORISEES):
        raise ValueError('transition propriétaire de résolution incohérente')
    if resolution['decision'] == 'rejetee':
        if outbox.CLE_WCT in compagnon:
            raise ValueError('rejet portant une complétion incohérente')
        return
    valide, _ = outbox.verifier_invariants_outbox(cedule_tournees._Instantane([compagnon]))
    wct = compagnon.get(outbox.CLE_WCT, {})
    if not valide or wct.get('revue_id') != resolution['demande_id'] or wct.get('ecart_signale') is not True:
        raise ValueError('preuve de complétion de l’écart incohérente')


def _ecarts(maillons, jour):
    demandes, inscriptions = _demandes(maillons)
    lignes, resolues = [], set()
    for rang, m in enumerate(maillons):
        typ = m['type_entree']
        if typ not in {pointage.TYPE_DEMANDE_REVUE, ecarts.TYPE_RESOLUTION}:
            continue
        ident = m['demande_id']
        if ident not in demandes:
            raise ValueError('résolution sans demande')
        rang_demande, demande = demandes[ident]
        if typ == ecarts.TYPE_RESOLUTION:
            _verifier_inscription(m, rang, inscriptions)
            horodatage.valider_horodatage(m['horodatage'])
            if (rang_demande >= rang or demande['intervention_id'] != m['intervention_id'] or ident in resolues
                    or m['decision'] not in ecarts.DECISIONS or m['statut_arbitrage'] != m['decision']
                    or m['resolution_id'] != encodage.empreinte('resolution_revue', ident, m['horodatage'])):
                raise ValueError('liaison ou décision de résolution invalide')
            resolues.add(ident)
            if demande['type_demande'] == 'ecart_metier':
                _verifier_transition_ecart(maillons, rang, m)
        if demande['type_demande'] != 'ecart_metier':
            continue
        instant = datetime.fromisoformat(m['horodatage']).astimezone(ZoneInfo(calendrier.FUSEAU))
        if instant.date().isoformat() != jour:
            continue
        dimensions = [k for k in sorted(ecarts.CLES_VERSION)
                      if demande['version_prevue'][k] != demande['version_declaree'][k]]
        ligne = {'type': 'ecart_declare' if typ == pointage.TYPE_DEMANDE_REVUE else 'ecart_arbitre',
                 'intervention_id': m['intervention_id'], 'source_ligne_id': m['ligne_id'],
                 'instant': instant.isoformat(), 'origine_heure': horodatage.origine(m), 'ancre_visite': None,
                 'demande_id': ident, 'source_demande_id': demande['ligne_id'],
                 'statut_arbitrage': m['statut_arbitrage'], 'dimensions_modifiees': dimensions}
        if typ == ecarts.TYPE_RESOLUTION:
            ligne['resolution_id'] = m['resolution_id']
        lignes.append(ligne)
    return lignes


def lire(reg, jour, *, debut=0, limite=50, source_attendue=None):
    """Page déterministe d'un snapshot validé; continuation interdite si sa tête change.

    Les sources SQL durables seront bornées avant décodage par le futur adaptateur.
    Aucun lecteur ou conteneur brut du registre n'est retourné.
    """
    jour = calendrier._date(jour).isoformat()
    if type(debut) is not int or debut < 0 or type(limite) is not int or not 1 <= limite <= 100:
        raise ValueError('pagination invalide')
    try:
        copie, maillons = _capture(reg)
        sources = annotations._sources(copie)
        source = encodage.empreinte('journal_quotidien_v1', copie.tete(), jour)
        if (debut and source_attendue is None) or (source_attendue is not None and source_attendue != source):
            raise ValueError('source périmée : relire la première page')
        lignes = _previsions(sources, maillons, jour) + _faits(maillons, jour) + _ecarts(maillons, jour)
        lignes.sort(key=lambda x: (datetime.fromisoformat(x['instant']), sources[0][x['source_ligne_id']][0],
                                   x['type'], x['intervention_id']))
        if debut > len(lignes):
            raise ValueError('pagination hors journal')
        fin = min(debut + limite, len(lignes))
        return {'jour': jour, 'fuseau': calendrier.FUSEAU, 'source': source, 'lignes': lignes[debut:fin],
                'total': len(lignes), 'debut': debut, 'suivant': fin if fin < len(lignes) else None,
                'avertissements': list(AVERTISSEMENTS)}
    except (VerificationError, annotations.Refus, KeyError, TypeError, AttributeError, IndexError) as exc:
        raise ValueError('source du journal invalide') from exc
