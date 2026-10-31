"""Port M4 : pointage et déclaration d'équipe typée dans une transaction.

Trois entrées, une seule écriture (`_ecrire`) :

- `enregistrer` : le port historique de la console admin (arguments `m4_pointer` complets, CAS fourni). Inchangé.
- `declarer_console` : la route console admin (D4, E3) ; champs fermés, heure serveur, CAS de la page relue.
- `declarer_appareil` : l'app terrain (D4). La personne vient du jeton d'appareil appairé, revérifiée en base, jamais
  du corps de la requête. Un ``employee`` ne déclare que pour l'équipe DÉCLARÉE de la visite active, et seulement s'il
  en est membre selon le profil des équipes ; un ``admin`` d'appareil dispatche (toute équipe déclarée de la visite).

Règles communes (DÉCISIONS-ARCHITECTE r1 §2, D4) : une déclaration d'équipe n'est jamais une présence individuelle ;
aucun pointage individuel n'est converti en pointage d'équipe (le sujet est l'équipe, la ligne `pointage` est écrite
par `m4_pointer` avec `technicien_id` = l'équipe, en route sous l'équipe) ; un historique sans preuve reste inconnu ;
l'heure qui fait foi est celle de réception du serveur ; le rejeu d'une même clé de mutation rend la même preuve, une
clé réutilisée pour une autre intention est refusée (`MUTATION-CONFLIT`).

Qui déclare sur l'appareil : TOUT membre déclaré de l'équipe, pas un « chef ». Le profil des équipes
(`opsys.equipes`, schéma fermé) ne porte aucune désignation de chef ; en inventer une ailleurs créerait une seconde
autorité de composition. La déclaration nomme la personne (preuve et journal d'audit) et reste soumise à la revue de
l'admin (pointage sans GPS en revue, revue finale de complétion). Le jour où le profil désigne un chef, la restriction
tient dans `_auteur_appareil`.
"""
import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime

from opsys import approbations, contexte, equipes, stockage
from opsys.etat import journaliser
from opsys.outils import executer

from . import cedule, encodage, journal_durable, pointage, visites_chantier, visites_ecriture
from .registre import Registre

TYPE = 'pointage_equipe_v3'
ROLE_ADMIN = 'admin'
# Rôle porté par la preuve d'un membre déclaré de l'équipe (appareil employee) : distinct de `employee`, il dit
# l'autorité sous laquelle la déclaration a été acceptée (membre de l'équipe déclarée de la visite).
ROLE_MEMBRE = 'membre_equipe'
ROLES_AUTEUR = frozenset({ROLE_ADMIN, ROLE_MEMBRE})
ACTIONS = pointage.ACTIONS

# Contexte de pointage sans GPS : une déclaration d'équipe ne porte jamais la position d'une personne. Sans fix, la
# cohérence est indéterminée et le pointage part en revue (`demande_revue`), que l'admin résout ; le référentiel n'y
# décide rien et n'est pas une donnée de chantier.
_SEL_SANS_GPS = 'pointage-equipe-v3-sans-gps'
_VILLE_SANS_GPS = 'sans-gps'
_REFERENTIEL_SANS_GPS = {'latitude': 0.0, 'longitude': 0.0, 'rayon_km': 20000.0}
_HEX = re.compile('[0-9a-f]{64}')

# (personne, équipe) dont le pointage d'équipe est en cours d'écriture par ce port : seul `_ecrire` le pose, autour de
# l'appel interne à `m4_pointer`. Jamais lu dans un argument : un employé n'obtient pas ainsi un `technicien_id`
# d'équipe sur `m4_pointer` appelé directement.
_POINTAGE_ATTESTE = ContextVar('m4_pointage_equipe_v3_atteste', default=None)


class Refus(ValueError):
    """Une provenance ne peut être produite à partir d'une source insuffisante."""

    @property
    def code(self):
        return self.args[0] if self.args else 'REFUS'


@contextmanager
def _attester(auteur, equipe_id):
    jeton = _POINTAGE_ATTESTE.set((auteur['personne'], equipe_id) if auteur['role'] == ROLE_MEMBRE else None)
    try:
        yield
    finally:
        _POINTAGE_ATTESTE.reset(jeton)


def pointage_atteste(acteur, technicien_id):
    """Vrai seulement pendant l'écriture d'une déclaration d'équipe acceptée par ce port, pour CETTE personne et
    CETTE équipe, dont l'acteur confirmé est membre selon le profil (``acteur.equipes``)."""
    return (acteur is not None and acteur.role == 'employee' and technicien_id in acteur.equipes
            and _POINTAGE_ATTESTE.get() == (acteur.personne, technicien_id))


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


def _transaction(cnx):
    if cnx is not stockage.connexion_courante() or cnx is None or not cnx.in_transaction():
        raise Refus('INSTANCE-NON-QUALIFIEE')


def _valider(arguments, visite_id, equipe_id, mutation_id, source_attendue):
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


def enregistrer(cnx, arguments, visite_id, equipe_id, mutation_id, source_attendue):
    """Enregistre une déclaration de sujet équipe, jamais une présence individuelle (port console historique)."""
    from .outils import _autoriser_annotation, _reception_console

    _transaction(cnx)
    auteur = _autoriser_annotation()
    reception = _reception_console(auteur)
    _valider(arguments, visite_id, equipe_id, mutation_id, source_attendue)
    intention = encodage.empreinte('m4.pointage_equipe.intention.v3', arguments, visite_id, equipe_id,
                                   mutation_id, source_attendue)
    return _ecrire(cnx, arguments, visite_id, equipe_id, mutation_id, source_attendue, auteur, reception,
                   intention, _autoriser_annotation)


# -- surface réelle (D4) ----------------------------------------------------------------------------------------
def _demande(demande, *, visite_optionnelle=False):
    """Champs fermés : intervention, visite, équipe, action. Rien d'autre (ni heure, ni GPS, ni personne). Sur
    l'appareil, ``visite_id`` peut être ``null`` : la visite ACTIVE de l'intervention est alors celle déclarée."""
    if (not isinstance(demande, dict) or set(demande) != {'intervention_id', 'visite_id', 'equipe_id', 'action'}
            or not all(isinstance(demande[k], str) and demande[k] for k in ('intervention_id', 'equipe_id', 'action'))
            or len(demande['intervention_id']) > 200 or len(demande['equipe_id']) > 256
            or demande['action'] not in ACTIONS
            or not ((visite_optionnelle and demande['visite_id'] is None)
                    or (isinstance(demande['visite_id'], str) and _HEX.fullmatch(demande['visite_id'])))):
        raise Refus('ARGUMENTS')
    return dict(demande)


def _preuve_existante(mutation_id, auteur):
    """La preuve déjà écrite sous cette clé de mutation par ce même auteur, s'il en existe une (rejeu)."""
    principal = Registre(stockage.maillons('m04-field-ops', 'principal'))
    anciennes = [m for m in principal.lire() if m.get('type_entree') == TYPE
                 and m.get('mutation_id') == mutation_id and m.get('auteur') == auteur]
    return anciennes[0] if len(anciennes) == 1 else None


def _mutation(mutation_id):
    if not isinstance(mutation_id, str) or not mutation_id.strip() or len(mutation_id) > 200:
        raise Refus('ARGUMENTS')
    return mutation_id


def _visite_de_l_equipe(demande):
    """La visite active de l'intervention doit être celle demandée, ouverte pour l'équipe demandée."""
    principal = Registre(stockage.maillons('m04-field-ops', 'principal'))
    try:
        active = visites_chantier.visite_active(principal, demande['intervention_id'])
    except ValueError as exc:
        raise Refus('VISITE-INACTIVE') from exc
    if active is None or demande['visite_id'] not in (None, active['visite_id']):
        raise Refus('VISITE-INACTIVE')
    if active.get('equipe_id') != demande['equipe_id']:
        raise Refus('VISITE-AUTRE-EQUIPE')
    return active


def _fenetre_du_jour(ouverture):
    """Le jour civil de l'ouverture de la visite, dans son propre décalage : une visite d'équipe se pointe le jour où
    elle a été ouverte (une seule date civile par visite, règle de M5), jamais un autre."""
    instant = datetime.fromisoformat(ouverture['horodatage'])
    if instant.utcoffset() is None:
        raise Refus('VISITE-INACTIVE')
    debut = instant.replace(hour=0, minute=0, second=0, microsecond=0)
    fin = instant.replace(hour=23, minute=59, second=59, microsecond=0)
    return {'debut': debut.isoformat(), 'fin': fin.isoformat()}


def _arguments_pointage(demande, reception, ouverture):
    """Les arguments de `m4_pointer` construits par le serveur : heure de réception, aucun GPS, équipe pour sujet."""
    return {'intervention_id': demande['intervention_id'], 'technicien_id': demande['equipe_id'],
            'action': demande['action'], 'horodatage': reception.recu_le.isoformat(), 'fix_gps': None,
            'attestation': {'fictif': True, 'appareil_id': reception.appareil},
            'fenetre_travail': _fenetre_du_jour(ouverture),
            'referentiel_villes': {cedule.tokeniser_ville(_SEL_SANS_GPS, _VILLE_SANS_GPS): dict(_REFERENTIEL_SANS_GPS)},
            'ville': _VILLE_SANS_GPS, 'sel': _SEL_SANS_GPS}


def _reception_appareil():
    reception = contexte.horodatage_reception()
    if (not isinstance(reception, contexte.HorodatageAppareil) or not isinstance(reception.appareil, str)
            or not reception.appareil or reception.appareil.startswith('console:')
            or not isinstance(reception.recu_le, datetime) or not isinstance(reception.horodatage_appareil, datetime)
            or reception.recu_le.utcoffset() is None or reception.horodatage_appareil.utcoffset() is None):
        raise Refus('HORODATAGE-SERVEUR-REQUIS')
    return reception


def _auteur_appareil(equipe_id):
    """La personne du jeton d'appareil, confirmée en base à chaque appel ; ``employee`` membre déclaré de l'équipe
    (profil courant), ou ``admin``. Aucun agent, aucune exécution approuvée hors appareil, aucun argument lu."""
    cnx, appelante = stockage.connexion_courante(), contexte.identite_appelante()
    if cnx is None or appelante is None or appelante.source != 'appareil':
        raise Refus('IDENTITE')
    confirmee = approbations.signataire_valide(cnx, appelante)
    if confirmee is None or confirmee.role not in ('employee', ROLE_ADMIN):
        raise Refus('IDENTITE')
    if confirmee.role == ROLE_ADMIN:
        return {'personne': confirmee.personne, 'role': ROLE_ADMIN}
    declarees = [e for e in _profil().get('liste', []) if e.get('id') == equipe_id]
    if len(declarees) != 1 or confirmee.personne not in declarees[0].get('membres', ()):
        raise Refus('NON-MEMBRE')
    return {'personne': confirmee.personne, 'role': ROLE_MEMBRE}


def declarer_appareil(cnx, demande, mutation_id):
    """Déclaration d'équipe depuis l'app terrain (D4). Identité : le jeton d'appareil, jamais le corps."""
    _transaction(cnx)
    demande, mutation_id = _demande(demande, visite_optionnelle=True), _mutation(mutation_id)
    auteur = _auteur_appareil(demande['equipe_id'])
    reception = _reception_appareil()
    intention = encodage.empreinte('m4.pointage_equipe.intention.appareil.v1', demande, mutation_id)

    def reautoriser():
        return _auteur_appareil(demande['equipe_id'])

    ancienne = _preuve_existante(mutation_id, auteur)
    if ancienne is not None:
        # Rejeu d'une même clé, même après la fermeture de la visite : la preuve écrite, revérifiée, jamais une autre.
        return _ecrire(cnx, {'intervention_id': demande['intervention_id'], 'action': demande['action']},
                       ancienne.get('visite_id'), demande['equipe_id'], mutation_id, None, auteur, reception,
                       intention, reautoriser)
    ouverture = _visite_de_l_equipe(demande)
    # Le CAS est pris par le serveur dans la transaction de l'appel : l'appareil ne relit pas le journal M4.
    source = empreinte_sources(cnx)
    return _ecrire(cnx, _arguments_pointage(demande, reception, ouverture), ouverture['visite_id'],
                   demande['equipe_id'], mutation_id, source, auteur, reception, intention, reautoriser)


def declarer_console(cnx, demande, mutation_id, source_attendue):
    """Déclaration d'équipe depuis la console admin (E3) : admin console relu en base, CAS de la page."""
    from .outils import _autoriser_annotation, _reception_console

    _transaction(cnx)
    demande, mutation_id = _demande(demande), _mutation(mutation_id)
    if not isinstance(source_attendue, str) or not _HEX.fullmatch(source_attendue):
        raise Refus('ARGUMENTS')
    auteur = _autoriser_annotation()
    reception = _reception_console(auteur)
    intention = encodage.empreinte('m4.pointage_equipe.intention.console.v1', demande, mutation_id, source_attendue)
    if _preuve_existante(mutation_id, auteur) is not None:
        return _ecrire(cnx, {'intervention_id': demande['intervention_id'], 'action': demande['action']},
                       demande['visite_id'], demande['equipe_id'], mutation_id, source_attendue, auteur, reception,
                       intention, _autoriser_annotation)
    ouverture = _visite_de_l_equipe(demande)
    return _ecrire(cnx, _arguments_pointage(demande, reception, ouverture), demande['visite_id'],
                   demande['equipe_id'], mutation_id, source_attendue, auteur, reception, intention,
                   _autoriser_annotation)


# -- l'écriture commune ------------------------------------------------------------------------------------------
def _ecrire(cnx, arguments, visite_id, equipe_id, mutation_id, source_attendue, auteur, reception, intention,
            reautoriser):
    from .outils import outils

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
        if reautoriser() != auteur:
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
        with _attester(auteur, equipe_id):
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
        if reautoriser() != auteur or _profil() != profil:
            raise Refus('IDENTITE-OU-PROFIL-MODIFIE')
        if (journal_durable.capturer(cnx) != capture_finale
                or visites_ecriture.capturer_visites(cnx) != snapshot_visites):
            raise Refus('SOURCE-MODIFIEE')
        return {'pointage_id': pointe_id, 'preuve_id': preuve_id, 'rejoue': False}
