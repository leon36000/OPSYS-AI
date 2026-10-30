"""Port privé M4 : pointage et déclaration d'équipe typée dans une transaction."""
import json
import re

from opsys import equipes, stockage
from opsys.etat import journaliser
from opsys.outils import executer

from . import encodage, journal_durable, visites_chantier, visites_ecriture
from .registre import Registre

TYPE = 'pointage_equipe_v3'


class Refus(ValueError):
    """Une provenance ne peut être produite à partir d'une source insuffisante."""


def _profil():
    profil, erreur = equipes.charger_equipes()
    if erreur is not None or not isinstance(profil, dict):
        raise Refus('PROFIL-INDISPONIBLE')
    return profil


def empreinte_sources(cnx):
    """CAS sur le journal, les prévisions et le profil d'équipe courant."""
    principal = journal_durable.capturer(cnx)
    visites = visites_ecriture.capturer_visites(cnx)
    return encodage.empreinte('m4.pointage_equipe.cas.v3', principal.empreinte_snapshot_calculee,
                              visites.empreinte_snapshot_calculee, equipes.empreinte_equipes(_profil()))


def enregistrer(cnx, arguments, visite_id, equipe_id, mutation_id, source_attendue):
    """Enregistre une déclaration de sujet équipe, jamais une présence individuelle."""
    from .outils import _autoriser_annotation, _reception_console, outils

    if cnx is not stockage.connexion_courante() or cnx is None or not cnx.in_transaction():
        raise Refus('INSTANCE-NON-QUALIFIEE')
    auteur = _autoriser_annotation()
    reception = _reception_console(auteur)
    if (not isinstance(arguments, dict) or not isinstance(visite_id, str) or not visite_id
            or not isinstance(equipe_id, str) or not equipe_id or not isinstance(mutation_id, str)
            or not mutation_id.strip() or len(mutation_id) > 200 or len(equipe_id) > 256
            or not re.fullmatch('[0-9a-f]{64}', visite_id)
            or not isinstance(source_attendue, str) or not re.fullmatch('[0-9a-f]{64}', source_attendue)
            or arguments.get('technicien_id') != equipe_id):
        raise Refus('ARGUMENTS')
    try:
        taille_arguments = len(json.dumps(arguments, ensure_ascii=False, allow_nan=False).encode())
    except (TypeError, ValueError) as exc:
        raise Refus('ARGUMENTS') from exc
    if taille_arguments > 65536:
        raise Refus('ARGUMENTS-TROP-VOLUMINEUX')
    intention = encodage.empreinte('m4.pointage_equipe.intention.v3', arguments, visite_id, equipe_id,
                                   mutation_id, source_attendue)
    principal = Registre(stockage.maillons('m04-field-ops', 'principal'))
    principal.assert_chaine()
    anciennes = [m for m in principal.lire() if m.get('type_entree') == TYPE
                 and m.get('mutation_id') == mutation_id and m.get('auteur') == auteur]
    if anciennes:
        if len(anciennes) != 1 or anciennes[0]['intention'] != intention:
            raise Refus('MUTATION-CONFLIT')
        from .temps_certifies_v3 import _audits

        preuve = anciennes[0]
        faits = [m for m in principal.lire() if m.get('ligne_id') == preuve.get('pointage_id')]
        if (len(faits) != 1 or faits[0].get('type_entree') != 'pointage'
                or faits[0].get('visite_id') != visite_id or faits[0].get('action') != arguments.get('action')
                or faits[0].get('technicien_id') != equipe_id or preuve.get('visite_id') != visite_id
                or preuve.get('sujet') != {'type': 'equipe', 'id': equipe_id}):
            raise Refus('PREUVE-INVALIDE')
        source_principal = journal_durable.capturer(cnx)
        source_visites = visites_ecriture.capturer_visites(cnx)
        audit = _audits(cnx, preuve)
        if _autoriser_annotation() != auteur:
            raise Refus('IDENTITE')
        if (journal_durable.capturer(cnx) != source_principal
                or visites_ecriture.capturer_visites(cnx) != source_visites or _audits(cnx, preuve) != audit):
            raise Refus('SOURCE-MODIFIEE')
        return {'pointage_id': anciennes[0]['pointage_id'], 'preuve_id': anciennes[0]['ligne_id'], 'rejoue': True}
    profil = _profil()
    capture_principal = journal_durable.capturer(cnx)
    capture_visites = visites_ecriture.capturer_visites(cnx)
    if sum(e.get('id') == equipe_id for e in profil.get('liste', [])) != 1:
        raise Refus('EQUIPE-INCONNUE')
    if source_attendue != empreinte_sources(cnx):
        raise Refus('SOURCE-PERIMEE')
    active = visites_chantier.visite_active(principal, arguments.get('intervention_id'))
    if active is None or active['visite_id'] != visite_id:
        raise Refus('VISITE-INACTIVE')
    outil = next(o for o in outils() if o.nom == 'm4_pointer')
    avant = principal.lire()
    empreinte_profil = equipes.empreinte_equipes(profil)
    snapshot_visites = visites_ecriture.capturer_visites(cnx)
    if (journal_durable.capturer(cnx) != capture_principal or snapshot_visites != capture_visites
            or _profil() != profil):
        raise Refus('SOURCE-MODIFIEE')
    with cnx.begin_nested():
        resultat = executer(outil, arguments)
        detail = resultat.get('resultat') if resultat.get('ok') else None
        if not isinstance(detail, dict) or detail.get('accepte') is not True:
            raise Refus('POINTAGE-REFUSE')
        pointe_id = detail['resultat']['ligne_id']
        apres = principal.lire()
        pointes = [m for m in apres[len(avant):]
                   if m.get('ligne_id') == pointe_id and m.get('type_entree') == 'pointage']
        if (apres[:len(avant)] != avant or len(pointes) != 1 or pointes[0].get('visite_id') != visite_id
                or pointes[0].get('technicien_id') != equipe_id or _profil() != profil
                or visites_ecriture.capturer_visites(cnx) != snapshot_visites):
            raise Refus('SOURCE-MODIFIEE')
        preuve_id = principal.ajouter({'type_entree': TYPE, 'intervention_id': arguments['intervention_id'],
            'visite_id': visite_id, 'pointage_id': pointe_id, 'sujet': {'type': 'equipe', 'id': equipe_id},
            'auteur': auteur, 'profil_empreinte': empreinte_profil, 'mutation_id': mutation_id,
            'intention': intention, 'source_attendue': source_attendue,
            'source_rangs': {'principal': len(capture_principal.lignes), 'visites': len(capture_visites.lignes)},
            'horodatage': reception.recu_le.isoformat()})
        journaliser(cnx, auteur['personne'], 'm4.pointage_equipe_v3', preuve_id,
                    {'visite_id': visite_id, 'pointage_id': pointe_id, 'equipe_id': equipe_id,
                     'profil_empreinte': empreinte_profil, 'role': auteur['role'],
                     'source_attendue': source_attendue,
                     'source_rangs': {'principal': len(capture_principal.lignes),
                                      'visites': len(capture_visites.lignes)}})
        capture_finale = journal_durable.capturer(cnx)
        attendu = apres + [principal.lire()[-1]]
        if ([r.maillon for r in capture_finale.lignes] != attendu
                or visites_ecriture.capturer_visites(cnx) != snapshot_visites):
            raise Refus('SOURCE-MODIFIEE')
        if _autoriser_annotation() != auteur or _profil() != profil:
            raise Refus('IDENTITE-OU-PROFIL-MODIFIE')
        if (journal_durable.capturer(cnx) != capture_finale
                or visites_ecriture.capturer_visites(cnx) != snapshot_visites):
            raise Refus('SOURCE-MODIFIEE')
        return {'pointage_id': pointe_id, 'preuve_id': preuve_id, 'rejoue': False}
