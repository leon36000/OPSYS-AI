"""Dates civiles sous mémoire courante; seuls les reçus exacts sont historiques."""
from sqlalchemy import LargeBinary, cast, func, select

from .. import idempotence, stockage
from ..etat import journaliser
from ..stockage import codec
from ..stockage.schema import MUTATIONS_APPLIQUEES
from . import cedule_plan_ui, memoire_chantier, memoire_plan_calendrier, metier
from . import preparation_chantier as lecture

NOM = 'm4_confirmer_dates_cedule'


def empreinte(contexte):
    return idempotence.empreinte_arguments({k: contexte[k] for k in ('empreinte_plan', 'empreinte_memoire')})


def _resultat(reponse):
    sortie = reponse.get('resultat') if isinstance(reponse, dict) and reponse.get('ok') is True else None
    if (not isinstance(sortie, dict) or sortie.get('accepte') is not True
            or not isinstance(sortie.get('resultat'), dict)):
        raise lecture.Refus('CONFIRMATION-REFUSEE')
    return lecture._sortie(sortie['resultat'])


def _recu(cnx, session, mutation, args, preuve):
    condition = ((MUTATIONS_APPLIQUEES.c.appareil == 'console:' + session.utilisateur)
                 & (MUTATIONS_APPLIQUEES.c.cle_idempotence == mutation))
    meta = cnx.execute(select(MUTATIONS_APPLIQUEES.c.outil, MUTATIONS_APPLIQUEES.c.empreinte_arguments,
        MUTATIONS_APPLIQUEES.c.statut, func.length(cast(MUTATIONS_APPLIQUEES.c.reponse, LargeBinary)))
        .where(condition)).one_or_none()
    if meta is None:
        return False
    intention = args if preuve is None else dict(arguments=args, preuve_commande=preuve)
    if meta[0] != NOM or meta[1] != idempotence.empreinte_arguments(intention):
        raise lecture.Refus('MUTATION-CONFLIT')
    if meta[2] != 'ok' or meta[3] is None or not 0 < meta[3] <= lecture.MAX_SORTIE_OCTETS:
        raise lecture.Refus('RECU-INDISPONIBLE')
    # Le reçu borné doit aussi être une réponse métier acceptée avant le chemin générique de rejeu.
    brut = cnx.execute(select(MUTATIONS_APPLIQUEES.c.reponse).where(condition)).scalar_one()
    try:
        _resultat(codec.decoder(brut))
    except (ValueError, TypeError, KeyError):
        raise lecture.Refus('RECU-INCOHERENT') from None
    return True


def _historique(args, resultat, acteur, application_id):
    from m4_field_ops import calendrier_civil, registre

    chaine = registre.Registre(stockage.maillons(lecture.M4, 'principal'))
    chaine.assert_chaine()
    lignes = [m for m in chaine.lire() if m.get('ligne_id') == resultat.get('ligne_id')]
    if len(lignes) != 1:
        raise lecture.Refus('RECU-INCOHERENT')
    m = lignes[0]
    if (m.get('type_entree') != calendrier_civil.TYPE_DATEE or m.get('confirme_par') != acteur
            or m.get('source_application_id') != application_id
            or any(m.get(k) != args[k] for k in ('plan_id', 'calendrier'))
            or type(resultat.get('revision')) is not int
            or resultat['revision'] != args['revision_attendue'] + 1
            or any(resultat.get(k) != m.get(k) for k in ('plan_id', 'revision', 'calendrier', 'fuseau'))):
        raise lecture.Refus('RECU-INCOHERENT')


def confirmer(cnx, deps, session, plan_id, champs):
    with cnx.begin_nested():
        memoire_chantier._admin(cnx, session)
        if type(plan_id) is not str or cedule_plan_ui.PLAN_ID.fullmatch(plan_id) is None:
            raise lecture.Refus('INTROUVABLE')
        lecture._borner(cnx, lecture.M4, 'principal')
        vue = _resultat(metier.executer(cnx, deps, session, 'm4_lire_calendrier_plan', dict(plan_id=plan_id)))
        try:
            permis = cedule_plan_ui.valider(vue, plan_id)
        except (ValueError, TypeError, KeyError):
            raise lecture.Refus('SOURCE-INCOHERENTE') from None
        arguments, mutation = cedule_plan_ui.arguments(champs, vue['jours'])
        args = dict(plan_id=plan_id, **arguments)
        attendu = champs.get('empreinte_memoire_attendue')
        if attendu is not None and (type(attendu) is not str or cedule_plan_ui.PLAN_ID.fullmatch(attendu) is None):
            raise ValueError('empreinte illisible')
        preuve = None if attendu is None else dict(empreinte=attendu)
        ancien = _recu(cnx, session, mutation, args, preuve)
        if ancien:
            reponse = metier.executer(cnx, deps, session, NOM, args, mutation_id=mutation, preuve_commande=preuve)
            if reponse.get('rejoue') is not True:
                raise lecture.Refus('RECU-INCOHERENT')
            _historique(args, _resultat(reponse), session.utilisateur, vue['source_application_id'])
            memoire_chantier._admin(cnx, session)
            return dict(historique=True)
        if attendu is None:
            raise lecture.Refus('MEMOIRE-PREUVE-REQUISE')
        if not permis:
            raise lecture.Refus('PLAN-BLOQUE')
        contexte = memoire_plan_calendrier.lire(cnx, deps, session, plan_id)
        if empreinte(contexte) != attendu or not contexte['permis']:
            raise lecture.Refus('SOURCE-MODIFIEE')
        reponse = metier.executer(cnx, deps, session, NOM, args, mutation_id=mutation, preuve_commande=preuve)
        _resultat(reponse)
        apres = memoire_plan_calendrier.lire(cnx, deps, session, plan_id)
        if apres['empreinte_memoire'] != contexte['empreinte_memoire']:
            raise lecture.Refus('SOURCE-MODIFIEE')
        memoire_chantier._admin(cnx, session)
        journaliser(cnx, session.utilisateur, 'console.contexte_dates', NOM,
            dict(plan_id=plan_id, mutation_id=mutation, empreinte=attendu,
                 memoire_empreinte=contexte['empreinte_memoire'], sources_m10=contexte['sources_m10']))
        return dict(historique=False)
