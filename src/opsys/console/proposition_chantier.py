"""Port console privé : proposition M4 exacte depuis devis, sans application ni date."""
import re
from datetime import UTC, datetime

from sqlalchemy import LargeBinary, cast, func, select

from .. import contexte, equipes, idempotence, meteo, stockage
from ..etat import journaliser
from ..outils import Autonomie, Niveau, executer_atomique
from ..stockage.schema import MUTATIONS_APPLIQUEES
from . import preparation_chantier as lecture

NOM = 'm4_proposer_cedule'
EMPREINTE = re.compile(r'[0-9a-f]{64}')


def _profils():
    profil, erreur_equipes = equipes.charger_equipes()
    regles, erreur_meteo = meteo.charger_meteo()
    return dict(equipes=profil, meteo=regles, erreur_equipes=erreur_equipes, erreur_meteo=erreur_meteo)


def _verifier_proposition(proposition, intervention_id, horodatage_appareil=None):
    """Le reçu historique ne remplace pas le plan réel et son intervention exacte."""
    from m4_field_ops import cedule_tournees, registre

    if (not isinstance(proposition, dict) or type(proposition.get('plan_id')) is not str
            or EMPREINTE.fullmatch(proposition['plan_id']) is None
            or type(proposition.get('deja_proposee')) is not bool):
        raise lecture.Refus('SOURCE-INCOHERENTE')
    chaine = registre.Registre(stockage.maillons(lecture.M4, 'principal'))
    entree = cedule_tournees.plan_propose(cedule_tournees.instantane_du_registre(chaine), proposition['plan_id'])
    if (entree is None or len(entree['etat']) != 1
            or entree['etat'][0]['intervention_id'] != intervention_id):
        raise lecture.Refus('SOURCE-INCOHERENTE')
    attendu = cedule_tournees._resultat_proposition(entree, proposition['deja_proposee'], entree['provenance'], [])
    propre = dict(proposition)
    if horodatage_appareil is not None and propre.pop('horodatage_appareil', None) != horodatage_appareil:
        raise lecture.Refus('SOURCE-INCOHERENTE')
    if propre != attendu:
        raise lecture.Refus('SOURCE-INCOHERENTE')
    return entree, attendu


def preparer(cnx, deps, session, lead_id, devis_id):
    """Lecture sans effet; l'empreinte inclut profils courants et tête M4, sans les exposer."""
    from m4_field_ops import encodage, registre

    vue = lecture.lire(cnx, deps, session, lead_id, devis_id)
    profils = _profils()
    chaine = registre.Registre(stockage.maillons(lecture.M4, 'principal'))
    source = dict(vue=vue, profils=profils, tete_m4=chaine.tete())
    return lecture._sortie(dict(vue=vue, empreinte=idempotence.empreinte_arguments(source),
        profils_source=idempotence.empreinte_arguments(profils),
        equipes_source=encodage.empreinte('profil-equipes', profils['equipes'])))


def proposer(cnx, deps, session, lead_id, devis_id, empreinte_attendue, mutation_id):
    """L'appelant fournit seulement son intention sur la lecture; auteur/heure/cible sont relus."""
    with cnx.begin_nested():
        courant = preparer(cnx, deps, session, lead_id, devis_id)
        if (type(empreinte_attendue) is not str or EMPREINTE.fullmatch(empreinte_attendue) is None
                or type(mutation_id) is not str or not 1 <= len(mutation_id) <= 200 or not mutation_id.strip()):
            raise lecture.Refus('ARGUMENTS')
        maintenant = datetime.now(UTC)
        meta = idempotence.Meta(mutation_id, 'console:' + session.utilisateur, maintenant.isoformat())
        intention = dict(lead_id=lead_id, devis_id=devis_id, empreinte=empreinte_attendue)
        condition = ((MUTATIONS_APPLIQUEES.c.appareil == meta.appareil)
                     & (MUTATIONS_APPLIQUEES.c.cle_idempotence == meta.cle))
        precedent = cnx.execute(select(MUTATIONS_APPLIQUEES.c.statut,
            func.length(cast(MUTATIONS_APPLIQUEES.c.reponse, LargeBinary))).where(condition)).one_or_none()
        if precedent is not None and (precedent[0] != 'ok' or precedent[1] > lecture.MAX_SORTIE_OCTETS):
            raise lecture.Refus('RECU-INDISPONIBLE')
        try:
            recu = idempotence.reclamer(cnx, meta, NOM, intention, maintenant)
        except idempotence.MutationConflit:
            raise lecture.Refus('MUTATION-CONFLIT') from None
        if recu.rejouee:
            if (not isinstance(recu.reponse, dict)
                    or set(recu.reponse) != {'ok', 'proposition', 'rejoue', 'historique'}
                    or recu.reponse.get('ok') is not True or recu.reponse.get('rejoue') is not False
                    or recu.reponse.get('historique') is not False or courant['vue']['intervention'] is None):
                raise lecture.Refus('RECU-INDISPONIBLE')
            _, projection = _verifier_proposition(recu.reponse.get('proposition'),
                                                  courant['vue']['intervention']['intervention_id'])
            return lecture._sortie(dict(ok=True, proposition=projection, rejoue=True, historique=True))
        if courant['empreinte'] != empreinte_attendue:
            raise lecture.Refus('SOURCE-MODIFIEE')
        vue = courant['vue']
        if (vue['ancre_complete'] is not True or vue['intervention'] is None
                or vue['intervention']['statut'] != 'a_planifier' or vue['preparation'] is None
                or vue['preparation']['pret'] is not True):
            raise lecture.Refus('PREPARATION-NON-PRETE')
        dep = deps.get(lecture.M4)
        if dep is None or dep.module_outils != lecture.MODULES[lecture.M4]:
            raise lecture.Refus('SOURCE-INDISPONIBLE')
        outil = next((o for o in dep.charger_outils() if o.nom == NOM), None)
        if outil is None or outil.autonomie != Autonomie.T1 or outil.niveau_effectif != Niveau.N1:
            raise lecture.Refus('SOURCE-INDISPONIBLE')
        arguments = dict(intervention_ids=[vue['intervention']['intervention_id']],
                          moteur='auto', horodatage=maintenant.isoformat())
        with (contexte.appele_par_appareil(contexte.IdentiteAppelante(
                session.utilisateur, 'admin', source='console')),
              contexte.appeler_en_tant_que(lecture.M4, origine='console'),
              contexte.receptionne_de(contexte.HorodatageAppareil(meta.appareil, maintenant, maintenant))):
            reponse = executer_atomique(outil, arguments)
        res = reponse.get('resultat') if reponse.get('ok') is True else None
        if not isinstance(res, dict) or res.get('accepte') is not True or not isinstance(res.get('resultat'), dict):
            code = res.get('verdict', {}).get('code') if isinstance(res, dict) else None
            raise lecture.Refus(code or 'PROPOSITION-INDISPONIBLE')
        entree, projection = _verifier_proposition(res['resultat'], arguments['intervention_ids'][0],
                                                   maintenant.isoformat())
        if (entree['empreinte_profil'] != courant['equipes_source']
                or entree['etat'][0].get('preparation') != vue['preparation']['empreinte']
                or idempotence.empreinte_arguments(_profils()) != courant['profils_source']):
            raise lecture.Refus('SOURCE-MODIFIEE')
        resultat = lecture._sortie(dict(ok=True, proposition=projection, rejoue=False, historique=False))
        journaliser(cnx, session.utilisateur, 'console.action_interne', NOM,
                    dict(plan_id=resultat['proposition']['plan_id'], devis_id=devis_id,
                         intervention_id=arguments['intervention_ids'][0], mutation_id=mutation_id))
        idempotence.finaliser(cnx, meta, resultat)
        return resultat
