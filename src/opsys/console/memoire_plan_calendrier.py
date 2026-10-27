"""Contexte civil privé : inscriptions M4 exactes, affaires M10 dédupliquées, aucune écriture."""
from datetime import UTC, datetime

from .. import idempotence, stockage
from . import cedule_plan_ui
from . import memoire_chantier as memoire
from . import preparation_chantier as lecture


def lire(cnx, deps, session, plan_id):
    from m4_field_ops import calendrier_civil, cedule_tournees, etats, registre
    from m10_memoire import affaire, etapes

    memoire._admin(cnx, session)
    if type(plan_id) is not str or cedule_plan_ui.PLAN_ID.fullmatch(plan_id) is None:
        raise lecture.Refus('INTROUVABLE')
    lecture._borner(cnx, lecture.M4, 'principal')
    vue = lecture._sortie(lecture._appel(deps, session.utilisateur, lecture.M4,
        'm4_lire_calendrier_plan', dict(plan_id=plan_id)))
    permis = cedule_plan_ui.valider(vue, plan_id)
    if vue['tronque']:
        raise lecture.Refus('PLAN-INCOMPLET')
    chaine = registre.Registre(stockage.maillons(lecture.M4, 'principal'))
    try:
        if calendrier_civil.lire_plan(chaine, plan_id) != vue:
            raise lecture.Refus('SOURCE-MODIFIEE')
    except registre.VerificationError:
        raise lecture.Refus('SOURCE-INCOHERENTE') from None
    tete_m4 = chaine.tete()
    lignes = chaine.lire()
    proposition = next(m for m in lignes if m['type_entree'] == cedule_tournees.TYPE_PROPOSEE
                       and m['plan_id'] == plan_id)
    inscriptions, etats_plan = {}, {}
    for m in lignes:
        if m['type_entree'] == etats.TYPE_INSCRIPTION:
            inscriptions.setdefault(m['intervention_id'], []).append(m)
    for m in proposition['etat']:
        etats_plan.setdefault(m['intervention_id'], []).append(m)
    sources_m10 = memoire._sources(cnx)
    tetes_m10 = {k: r.tete() for k, r in sources_m10.items()}
    faits_devis = {}
    for m in sources_m10['evenements'].lire():
        if m.get('type_evenement') == etapes.TYPE_DEVIS_ACCEPTE:
            faits_devis.setdefault(m.get('devis_id'), []).append(m)
    liaisons, contextes, vus = [], {}, set()
    horodatage = datetime.now(UTC).isoformat()
    for v in vue['visites']:
        iid = v['intervention_id']
        candidates, etat = inscriptions.get(iid, []), etats_plan.get(iid, [])
        if (iid in vus or len(candidates) != 1 or len(etat) != 1
                or candidates[0].get('lead_id') != etat[0].get('lead_id')):
            raise lecture.Refus('SOURCE-INCOHERENTE')
        vus.add(iid)
        inscription = candidates[0]
        cle, travaux = etats.travaux_de(inscription)
        if (etat[0].get(cle) != travaux
                or etat[0].get('urgence_declaree') is not inscription.get('urgence_declaree')):
            raise lecture.Refus('SOURCE-INCOHERENTE')
        lead = inscription['lead_id']
        if type(lead) is not str or not lead or inscription.get('source') not in (None, etats.SOURCE_DEVIS_ACCEPTE):
            raise lecture.Refus('SOURCE-INCOHERENTE')
        representable = affaire.valide(lead)
        lien = dict(intervention_id=iid, lead_id=lead, devis_id=None,
                    devis_declare=inscription.get('devis_id'), origine='manuelle',
                    reference_devis=None, ancre_bus_complete=False,
                    lien_m10='CONTEXTE_AFFAIRE_SANS_DEVIS_VERIFIE' if representable else 'NON_REPRESENTABLE')
        if inscription.get('source') == etats.SOURCE_DEVIS_ACCEPTE:
            devis = inscription.get('devis_id')
            if type(devis) is not str or not devis:
                raise lecture.Refus('SOURCE-INCOHERENTE')
            amont = lecture.lire(cnx, deps, session, lead, devis)
            if amont['intervention'] is None or amont['intervention']['intervention_id'] != iid:
                raise lecture.Refus('SOURCE-INCOHERENTE')
            reference = memoire._reference_devis(cnx, devis, faits_devis.get(devis, [])) if representable else None
            statut = ('LIE' if reference else 'DEVIS_NON_MEMORISE') if representable else 'NON_REPRESENTABLE'
            lien.update(origine='devis_accepte', devis_id=devis, reference_devis=reference,
                        ancre_bus_complete=amont['ancre_complete'], lien_m10=statut)
        liaisons.append(lien)
        if lead not in contextes:
            paquet = None
            if representable:
                paquet = memoire._paquet(deps, session, lead, horodatage)
                memoire._valider(paquet, lead, horodatage)
                if paquet.get('source_registres') != tetes_m10:
                    raise lecture.Refus('SOURCE-MODIFIEE')
            contextes[lead] = dict(lead_id=lead, affaire_id=lead if representable else None,
                                  etat='CONTEXTE_AFFAIRE' if representable else 'NON_REPRESENTABLE', paquet=paquet)
        # Ne jamais ouvrir le prochain paquet si la réponse complète a déjà dépassé son budget.
        lecture._sortie(dict(vue=vue, liaisons=liaisons, affaires=list(contextes.values())))
    memoire._admin(cnx, session)
    lecture._borner(cnx, lecture.M4, 'principal')
    if (registre.Registre(stockage.maillons(lecture.M4, 'principal')).tete() != tete_m4
            or {k: r.tete() for k, r in memoire._sources(cnx).items()} != tetes_m10):
        raise lecture.Refus('SOURCE-MODIFIEE')
    affaires = list(contextes.values())
    preuve_memoire = dict(liaisons=liaisons, sources=tetes_m10, affaires=[
        {**a, 'paquet': None if a['paquet'] is None else
         {k: valeur for k, valeur in a['paquet'].items() if k != 'horodatage'}} for a in affaires])
    return lecture._sortie(dict(vue=vue, permis=permis, liaisons=liaisons, affaires=affaires,
        source_m4=tete_m4, sources_m10=tetes_m10,
        empreinte_plan=idempotence.empreinte_arguments(dict(vue=vue, source_m4=tete_m4)),
        empreinte_memoire=idempotence.empreinte_arguments(preuve_memoire)))



def contenu(contexte):
    from . import pages

    corps = ('<section><h2>Mémoire avant les dates internes</h2>'
             '<p>Contexte actuel M10 par affaire. Cette consultation ne confirme pas le chantier '
             'et ne clôture aucun signal.</p>')
    for lien in contexte['liaisons']:
        corps += (f'<p>Intervention {pages.e(lien["intervention_id"])} · Affaire {pages.e(lien["lead_id"])} · '
            f'{pages.e(lien["origine"])} · {pages.e(lien["lien_m10"])}<br>'
            f'Devis vérifié : {pages.e(lien["devis_id"] or "Aucun")} · '
            f'Devis déclaré : {pages.e(lien["devis_declare"] or "Aucun")}</p>')
    for affaire in contexte['affaires']:
        corps += f'<details open><summary>Affaire {pages.e(affaire["lead_id"])}</summary>'
        if affaire['paquet'] is None:
            corps += '<p role="alert">Identifiant non représentable dans M10; aucun contexte substitué.</p>'
        else:
            situation = affaire['paquet']['affaire']
            if situation['connue'] is not True:
                corps += '<p role="alert">Mémoire d’affaire inconnue : aucun fait reçu pour cette affaire.</p>'
            elif situation['origine_recue'] is not True:
                corps += '<p role="alert">Origine de l’affaire non reçue : le contexte amont est incomplet.</p>'
            corps += memoire.contenu_paquet(affaire['paquet'])
            consolidation = affaire['paquet']['consolidation']
            jours = consolidation['a_consolider']
            corps += (f'<p>Jours à consolider : {pages.e(consolidation["nb_a_consolider"])} · '
                      f'Détail inclus : {len(jours)}.</p>')
            corps += ''.join(f'<p>{pages.e(jour["jour"])}</p>' for jour in jours)
        corps += '</details>'
    return corps + '</section>'
