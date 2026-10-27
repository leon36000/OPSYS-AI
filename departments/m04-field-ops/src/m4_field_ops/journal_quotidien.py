"""CRM-16 : projection privée d'une journée, sans horloge, GPS, RH ni calcul de paie.

Prévisions historiques et faits horodatés restent distincts. L'adaptateur doit encore
fournir le snapshot canonique et contrôler l'admin : ce lecteur n'est pas une API exposée.
"""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from . import annotations_calendrier as annotations
from . import calendrier_civil as calendrier
from . import cedule_tournees, encodage, etats, horodatage, pointage
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


def _faits(maillons, jour):
    lignes = []
    inscriptions = {}
    for rang, m in enumerate(maillons):
        if m['type_entree'] == etats.TYPE_INSCRIPTION:
            inscriptions.setdefault(_texte(m['intervention_id']), []).append(rang)
    for rang, m in enumerate(maillons):
        typ = m['type_entree']
        if typ not in {pointage.TYPE_POINTAGE, etats.TYPE_TRANSITION}:
            continue
        origines = inscriptions.get(m['intervention_id'], [])
        if len(origines) != 1 or origines[0] >= rang:
            raise ValueError('inscription unique antérieure requise pour chaque fait')
        horodatage.valider_horodatage(m['horodatage'])
        instant = datetime.fromisoformat(m['horodatage']).astimezone(ZoneInfo(calendrier.FUSEAU))
        if instant.date().isoformat() != jour:
            continue
        ligne = {'type': 'pointage' if typ == pointage.TYPE_POINTAGE else 'etat',
                 'source_ligne_id': _texte(m['ligne_id']), 'intervention_id': _texte(m['intervention_id']),
                 'instant': instant.isoformat(), 'origine_heure': horodatage.origine(m),
                 'ancre_visite': None}
        if typ == pointage.TYPE_POINTAGE:
            if m['action'] not in pointage.ACTIONS:
                raise ValueError('action de pointage invalide')
            ligne.update(action=m['action'], technicien_id=_texte(m['technicien_id']))
        else:
            if m['statut'] not in etats.ETATS:
                raise ValueError('état invalide')
            ligne['statut'] = m['statut']
            if m['statut'] == 'reportee':
                if m['motif'] not in etats.MOTIFS_REPORT:
                    raise ValueError('motif de report invalide')
                ligne['motif'] = m['motif']
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
        lignes = _previsions(sources, maillons, jour) + _faits(maillons, jour)
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
