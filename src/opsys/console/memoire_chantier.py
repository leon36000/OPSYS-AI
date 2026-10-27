"""Paquet M10 restrictif du devis exact : lecture privée, aucune décision ou mémoire copiée."""
import json
from datetime import UTC, datetime

from .. import contexte, idempotence, identite, stockage
from ..outils import Autonomie, executer
from . import pages
from . import preparation_chantier as lecture

M10 = 'm10-memoire'
MODULE = 'm10_memoire.outils'
NOM = 'm10_lire_paquet_affaire_appareil'


def _admin(cnx, session):
    if cnx is not stockage.connexion_courante() or cnx.dialect.name != 'sqlite':
        raise lecture.Refus('INSTANCE-NON-QUALIFIEE')
    personne = identite.personne_active(cnx, session.utilisateur)
    if (personne is None or 'admin' not in personne.roles
            or session.expire <= datetime.now(UTC).timestamp()):
        raise PermissionError('admin actif requis')


def _sources(cnx):
    from m10_memoire import registre

    for nom in ('evenements', 'affaires'):
        lecture._borner(cnx, M10, nom)
    sources = {}
    for nom in ('evenements', 'affaires'):
        chaine = registre.Registre(stockage.maillons(M10, nom))
        valide, _ = chaine.valider_chaine()
        if not valide:
            raise lecture.Refus('MEMOIRE-SOURCE-INCOHERENTE')
        sources[nom] = chaine
    return sources


def _paquet(deps, session, affaire_id, horodatage):
    dep = deps.get(M10)
    if dep is None or dep.module_outils != MODULE:
        raise lecture.Refus('MEMOIRE-INDISPONIBLE')
    outil = next((o for o in dep.charger_outils() if o.nom == NOM), None)
    if outil is None or outil.autonomie != Autonomie.T0:
        raise lecture.Refus('MEMOIRE-INDISPONIBLE')
    with (contexte.appele_par_appareil(contexte.IdentiteAppelante(session.utilisateur, 'admin', source='console')),
          contexte.appeler_en_tant_que(M10, origine='console')):
        reponse = executer(outil, dict(affaire_id=affaire_id, horodatage=horodatage))
    if not isinstance(reponse, dict) or reponse.get('ok') is not True:
        raise lecture.Refus('MEMOIRE-INDISPONIBLE')
    return lecture._sortie(reponse.get('resultat'))


def _valider(paquet, affaire_id, horodatage):
    from m10_memoire import confidentialite, paquets

    if (not isinstance(paquet, dict) or paquet.get('affaire_id') != affaire_id
            or paquet.get('horodatage') != horodatage
            or paquet.get('confidentialite', {}).get('agent', 'absent') is not None
            or not isinstance(paquet.get('couches'), list) or len(paquet['couches']) != 4):
        raise lecture.Refus('MEMOIRE-REPONSE-INCOHERENTE')
    for couche, nom in zip(paquet['couches'], paquets._COUCHES_ORDRE, strict=True):
        if (couche.get('nom') != nom or not isinstance(couche.get('faits'), list)
                or any(type(couche.get(k)) is not int or couche[k] < 0 for k in ('nb_total', 'nb_inclus', 'nb_omis'))
                or couche['nb_inclus'] != len(couche['faits'])
                or couche['nb_total'] != couche['nb_inclus'] + couche['nb_omis']
                or couche.get('tronque') is not (couche['nb_omis'] > 0)
                or couche.get('vide') is not (couche['nb_inclus'] == 0)):
            raise lecture.Refus('MEMOIRE-REPONSE-INCOHERENTE')
        if any(f.get('confidentialite') not in confidentialite.niveaux_admis(nom, None) for f in couche['faits']):
            raise lecture.Refus('MEMOIRE-REPONSE-INCOHERENTE')
    if any(type(paquet.get('signaux', {}).get(k)) is not int or paquet['signaux'][k] < 0
           for k in ('nb_ouverts', 'nb_pris_en_compte', 'nb_clos')):
        raise lecture.Refus('MEMOIRE-REPONSE-INCOHERENTE')
    if not isinstance(paquet.get('affaire'), dict) or not isinstance(paquet.get('consolidation'), dict):
        raise lecture.Refus('MEMOIRE-REPONSE-INCOHERENTE')


def _reference_devis(cnx, devis_id, faits):
    """Comparer un fait déjà sélectionné à la même projection canonique M3, sans lire un paquet."""
    from m10_memoire import amont, etapes

    charge = lecture._publication(cnx, 'm3-devis-accepte-' + devis_id, etapes.TYPE_DEVIS_ACCEPTE, lecture.M3)
    attendu = None
    if charge is not None:
        etape = etapes.etape(etapes.TYPE_DEVIS_ACCEPTE)
        attendu = amont._entree(etape.type_evenement, etape.niveau, etape.extraire(charge))
    if (len(faits) > 1 or any({k: v for k, v in m.items() if k not in ('ligne_id', 'precedent_ligne_id')}
                             != attendu for m in faits)):
        raise lecture.Refus('MEMOIRE-ANCRE-INCOHERENTE')
    return faits[0]['ligne_id'] if faits else None


def lire(cnx, deps, session, lead_id, devis_id):
    """Ancrage M3/M4 et vrai lecteur M10. Les absences restent visibles, jamais un feu vert."""
    from m10_memoire import affaire, etapes

    _admin(cnx, session)
    lecture.lire(cnx, deps, session, lead_id, devis_id)
    sources = _sources(cnx)
    tetes = {k: r.tete() for k, r in sources.items()}
    resultat = dict(etat='NON_REPRESENTABLE', affaire_id=None, devis_id=devis_id,
                    reference_devis=None, sources=tetes, paquet=None)
    if affaire.valide(lead_id):
        faits = [m for m in sources['evenements'].lire()
                 if m.get('type_evenement') == etapes.TYPE_DEVIS_ACCEPTE and m.get('devis_id') == devis_id]
        reference = _reference_devis(cnx, devis_id, faits)
        horodatage = datetime.now(UTC).isoformat()
        paquet = _paquet(deps, session, lead_id, horodatage)
        _valider(paquet, lead_id, horodatage)
        if paquet.get('source_registres') != tetes:
            raise lecture.Refus('SOURCE-MODIFIEE')
        resultat.update(etat='LIE' if faits else 'DEVIS_NON_MEMORISE', affaire_id=lead_id,
                        reference_devis=reference, paquet=paquet)
    _admin(cnx, session)
    if {k: r.tete() for k, r in _sources(cnx).items()} != tetes:
        raise lecture.Refus('SOURCE-MODIFIEE')
    # L'heure de consultation n'est pas un changement de mémoire ni une nouvelle intention.
    preuve = {**resultat, 'paquet': None if resultat['paquet'] is None else
              {k: v for k, v in resultat['paquet'].items() if k != 'horodatage'}}
    resultat['empreinte'] = idempotence.empreinte_arguments(preuve)
    return lecture._sortie(resultat)


def contenu(memoire):
    """Projection humaine du paquet déjà validé; jamais un indicateur d'autorisation."""
    titres = {'regles_entreprise': 'Règles de l’entreprise', 'faits_affaire': 'Faits de l’affaire',
              'evenements_recents': 'Événements récents', 'signaux_non_resolus': 'Signaux non résolus'}
    corps = ('<section><h2>Mémoire de l’affaire</h2><p>Contexte actuel M10, vue restrictive. '
        'Cette lecture ne vaut ni validation du chantier ni clôture de ses signaux.</p>'
        f'<p>Liaison du devis : {pages.e(memoire["etat"])}.</p>')
    paquet = memoire['paquet']
    if paquet is None:
        return corps + '<p role="alert">Identifiant non représentable dans M10; aucun contexte substitué.</p></section>'
    if memoire['etat'] != 'LIE':
        corps += '<p role="alert">Le fait du devis exact manque dans M10. La mémoire est incomplète.</p>'
    s = paquet['signaux']
    corps += (f'<p>Signaux ouverts : {s["nb_ouverts"]} · Pris en compte : {s["nb_pris_en_compte"]} · '
              f'Clos : {s["nb_clos"]}</p>')
    if s['nb_ouverts']:
        corps += '<p role="alert">Signaux à examiner humainement, y compris ceux omis du détail ci-dessous.</p>'
    for couche in paquet['couches']:
        corps += (f'<h3>{pages.e(titres[couche["nom"]])}</h3>'
            f'<p>Inclus : {couche["nb_inclus"]} · Total : {couche["nb_total"]} · Omis : {couche["nb_omis"]}</p>')
        if couche['tronque']:
            corps += '<p role="alert">Couche partielle : le détail ne contient pas tous les faits.</p>'
        for fait in couche['faits']:
            corps += (f'<p>{pages.e(fait["resume"])}<br>Source : {pages.e(fait["source"])} · '
                f'{pages.e(fait["identifiant"])} · {pages.e(fait["horodatage"])}</p>')
    corps += '<details><summary>Origine, consolidation et références de lecture</summary>'
    for nom, valeur in [('Affaire', paquet['affaire']), ('Consolidation', paquet['consolidation']),
                        ('Sources', memoire['sources']), ('Référence du devis', memoire['reference_devis'])]:
        corps += f'<p>{nom} : {pages.e(json.dumps(valeur, ensure_ascii=False))}</p>'
    return corps + '</details></section>'
