"""Cédule par tournées : proposition stockée, puis application sous approbation (PLAN T4.1-d, R15 §4).

Module pur (stdlib ; aucun import ``opsys``, aucune horloge, aucun aléa, aucun flottant, aucun accès réseau ;
un test le vérifie par analyse du code). Il assemble l'entrée du solveur de tournées (``tournees.py``) à partir
de ce que M4 SAIT, le fait résoudre, et range le plan PROPOSÉ au registre. Le solveur propose, il n'écrit pas la
vérité : seule ``appliquer`` fait assigner des techniciens, par ``etats.assigner_technicien``.

Ce que M4 sait (lu au registre, jamais fourni par l'appelant)
    * les interventions à planifier : celles au statut ``planifiee`` (``etats.statut_courant``), et celles au statut
      ``a_planifier`` dont le verdict de préparation est « prêt » (``preparation.evaluer``, T4.12) ; leur nature de
      travaux (``type_travaux`` d'un lead v1 ou ``service`` d'un lead v2, jamais l'un déduit de l'autre :
      ``etats.travaux_de``), leur ``lead_id``, leur ``urgence_declaree``, le technicien déjà assigné ;
    * les coordonnées CONFIRMÉES de chaque chantier (maillon ``localisation_chantier``, lues par
      ``lire_position``, que l'adaptateur relie à ``outils.lire_localisation_confirmee``).

Ce que M4 lit dans le PROFIL DES ÉQUIPES de l'entreprise (T4.12 ; ``lire_equipes()``, que l'adaptateur relie à
``opsys.equipes.charger_equipes``)
    équipes (compétences, dépôt, quarts), durée et compétences requises par service (leads v2), réglages de la
    cédule (détour, vitesse, marge, itérations, coût de non-cédule), et la fenêtre offerte à un chantier dont le
    client n'en a donné aucune. Chaque valeur du profil est REMPLACÉE par l'argument de même nom quand l'appelant en
    donne un : c'est une SURCHARGE, et le maillon du plan garde la provenance de chaque valeur (``provenance`` :
    ``profil`` ou ``surcharge``) et l'empreinte du profil lu.

Ce que M4 ne sait pas (ARGUMENT explicite de l'appelant, ou un verdict « à fournir » qui liste tout)
    durée et compétences requises par type de travaux (leads v1, gelés : le profil est par service), fenêtre du client
    et créneau déjà confirmé au client pour chaque intervention ``planifiee`` (le profil ne connaît que la fenêtre
    par défaut d'un chantier ``a_planifier``, où aucun créneau n'a pu être promis : ``creneau_fige`` y vaut null),
    et tout ce que le profil ne déclare pas. Aucune valeur par défaut : un champ absent est un verdict, qui dit aussi
    comment le déclarer une fois pour toutes (``opsys equipes declarer``).
    Seule exception, technique et non métier : la ``graine`` du solveur, ``GRAINE_TECHNIQUE`` si elle est
    omise (PyVRP est de toute façon amorcé par l'empreinte de l'entrée, ``tournees._graine_derivee``).

L'urgence (``urgence_depuis_declaration``) : ``urgence_declaree`` est un booléen ; le solveur veut un entier
de 0 à 3. La règle est écrite ci-dessous (``REGLE_URGENCE``), pas devinée.

Ce qui rend une application sûre
    1. ``cedule_proposee`` garde le plan complet, l'entrée du solveur SANS la matrice (aucune coordonnée de
       chantier n'est jamais copiée : les positions se relisent chiffrées), l'état des interventions au moment
       de la proposition et trois empreintes : entrée, sortie, état.
    2. ``appliquer`` relit l'état ACTUEL des mêmes interventions (statut, type, urgence, technicien assigné,
       version de la localisation, et pour une intervention ``a_planifier`` l'empreinte de son verdict de préparation)
       et refuse tout écart (``REJ-CEDULE-ENTREE-CHANGEE``) ; refuse aussi un plan lu dans un profil des équipes qui a
       changé depuis ; puis reconstruit l'entrée du solveur avec les coordonnées d'AUJOURD'HUI et refuse si son
       empreinte n'est plus celle de la proposition ; puis repasse ``tournees.verifier_plan`` (créneaux figés, fenêtres,
       quarts, compétences) et refuse un plan qui échoue (``REJ-TOURNEES-PLAN-INVALIDE``).
    3. Toutes les vérifications précèdent la première écriture. Appliquer deux fois le même plan n'écrit rien
       de plus (``deja_appliquee``) ; un technicien déjà assigné à la bonne intervention n'est pas ré-assigné.

SORTIE DE ``a_planifier`` (T4.12) : appliquer un plan fait passer ``a_planifier -> planifiee`` chaque intervention
qu'il place, par ``etats.transitionner`` et le verdict de préparation « prêt » recalculé au moment de l'application
(la porte d'empreinte de T4.10 : aucun verdict truqué ni périmé ne passe), puis l'assigne. Une intervention non prête
n'entre jamais dans le plan ; elle est rendue avec ce qui lui manque (``non_pretes``). Une intervention que le plan
laisse de côté reste ``a_planifier``. Les volets matériel (T4.14-b, ``m6.materiel_pret``) et météo (T4.13, règles du
service dans le profil météo) se lisent à leur source : une intervention n'est prête que si M6 la dit prête et si
l'entreprise
a décidé ses règles météo pour son service ; sinon la porte reste fermée, et le refus dit ce qui manque.

Limites : ``jour`` est un numéro choisi par l'appelant (M4 ne tient pas encore de calendrier) ; le jour et
l'heure d'une visite restent dans le maillon du plan, ils ne sont pas encore lus par l'écran « chantiers du
jour » ; une intervention non cédulée garde l'assignation qu'elle avait (aucun outil de désassignation) ; une
adresse modifiée après la confirmation des coordonnées n'est pas vue ici (M4 ne connaît pas l'adresse).
"""

from __future__ import annotations

import copy

from . import admissibilite, cedule, distances, encodage, etats, horodatage, localisation, tournees, verdicts
from . import preparation as preparation_intervention

# ---------------------------------------------------------------------------
# Constantes publiques
# ---------------------------------------------------------------------------
TYPE_PROPOSEE = "cedule_proposee"
TYPE_APPLIQUEE = "cedule_appliquee"
VERSION_PROPOSITION = "cedule-proposee-v1"

STATUT_PLANIFIABLE = "planifiee"
STATUT_A_PLANIFIER = "a_planifier"
GRAINE_TECHNIQUE = 0

SOURCE_PROFIL = "profil"
SOURCE_SURCHARGE = "surcharge"
TRANSITION_SORTIE_A_PLANIFIER = "a_planifier->planifiee"

EFFET_ASSIGNEE = "assignee"
EFFET_DEJA_ASSIGNEE = "deja_assignee"

# Règle de conversion de l'urgence (PLAN T4.1-d ; l'échelle du solveur est ``tournees.BORNE_URGENCE``).
URGENCE_NORMALE = 0
URGENCE_DECLAREE = 1
REGLE_URGENCE = (
    "urgence_declaree (booléen du LeadQualifie, conservé tel quel à l'inscription) vaut 1 s'il est vrai et 0 "
    "sinon. Le solveur mesure l'urgence par le coût d'un chantier laissé de côté, cout_non_cedule_m x "
    "(1 + urgence) : un chantier urgent coûte le double à laisser. Un booléen ne distingue que deux cas, donc "
    "on prend le premier cran au-dessus de la normale ; les crans 2 et 3 restent libres pour une source plus "
    "fine (score d'urgence de M1, M2.4), jamais inventés. Sources : DEFINITION-PRODUIT M4.7 (l'urgence est un "
    "critère de la cédule), audit M4 risque 10 (champ mort avant T4.1-d), contrats.py (booléen strict), "
    "R15 §4 (urgence, entrée du solveur), tournees.py (échelle 0 à 3, coût x (1 + urgence))."
)

AVERTISSEMENT_MODE_BRIDE = (
    "mode bridé : distances approximatives (ligne droite x détour), pas des routes réelles"
)

CLES_PARAMETRES_DISTANCE = tuple(distances.BORNES_PARAMETRES)
CLES_PARAMETRES_SOLVEUR = ("iterations", "cout_non_cedule_m")
CLES_PARAMETRES_REQUISES = CLES_PARAMETRES_DISTANCE + CLES_PARAMETRES_SOLVEUR
CLES_PARAMETRES_OPTIONNELLES = ("graine",)

__all__ = [
    "TYPE_PROPOSEE",
    "TYPE_APPLIQUEE",
    "VERSION_PROPOSITION",
    "STATUT_PLANIFIABLE",
    "STATUT_A_PLANIFIER",
    "GRAINE_TECHNIQUE",
    "SOURCE_PROFIL",
    "SOURCE_SURCHARGE",
    "TRANSITION_SORTIE_A_PLANIFIER",
    "EFFET_ASSIGNEE",
    "EFFET_DEJA_ASSIGNEE",
    "URGENCE_NORMALE",
    "URGENCE_DECLAREE",
    "REGLE_URGENCE",
    "AVERTISSEMENT_MODE_BRIDE",
    "CLES_PARAMETRES_REQUISES",
    "urgence_depuis_declaration",
    "instantane_du_registre",
    "plan_propose",
    "inscriptions_du_registre",
    "proposer",
    "appliquer",
]

# Arguments de la proposition, dans l'ordre où l'absence de chacun est rapportée (celui d'avant T0.13-b
# pour un lot de leads v1). Les tables par nature de travaux ne sont exigées que pour la version présente
# dans le lot (T0.13-b) : v1 -> `_CLES_ARGUMENTS_V1`, v2 -> `_CLES_ARGUMENTS_V2`.
_CLES_ARGUMENTS_COMMUNES = ("equipes", "chantiers", "parametres")
_CLES_ARGUMENTS_V1 = ("durees_par_type_travaux", "competences_par_type_travaux")
_CLES_ARGUMENTS_V2 = ("durees_par_service", "competences_par_service")
_CLES_ARGUMENTS = (
    "equipes", "durees_par_type_travaux", "competences_par_type_travaux",
    "durees_par_service", "competences_par_service", "chantiers", "parametres",
)
_CLES_ARGUMENTS_OPTIONNELLES = ("intervention_ids",)
_CLES_EQUIPE = ("id", "competences", "depot", "quarts")
_CLES_DEPOT = ("id", "latitude_microdegres", "longitude_microdegres")
_CLES_CHANTIER = ("intervention_id", "fenetre", "creneau_fige")

_AIDE = {
    "equipes": "liste des équipes (id, competences, depot, quarts) ; l'id de l'équipe EST le technicien_id "
               "de l'assignation",
    "durees_par_type_travaux": "durée en minutes entières de chaque type de travaux à planifier, fournie par "
                               "l'entreprise",
    "competences_par_type_travaux": "compétences requises par chaque type de travaux à planifier, liste vide "
                                    "s'il n'y en a aucune",
    "durees_par_service": "durée en minutes entières de chaque service à planifier (interventions issues d'un "
                          "lead v2), fournie par l'entreprise",
    "competences_par_service": "compétences requises par chaque service à planifier (interventions issues d'un "
                               "lead v2), liste vide s'il n'y en a aucune",
    "chantiers": "une entrée par intervention à planifier : intervention_id, fenetre du client "
                 "(jours, debut_min, fin_min) et creneau_fige (null, ou {equipe, jour, debut_min} si le créneau "
                 "est déjà confirmé au client) ; une intervention a_planifier sans entrée prend la fenetre_par_defaut "
                 "du profil des équipes, et aucun créneau figé",
    "parametres": "paramètres d'entreprise : facteur_detour_milliemes, vitesse_moyenne_kmh, "
                  "marge_par_trajet_secondes, iterations, cout_non_cedule_m",
    "id": "identifiant non vide",
    "competences": "compétences de l'équipe, liste vide s'il n'y en a aucune",
    "depot": "lieu de l'entreprise où l'équipe commence et finit sa journée : id, latitude_microdegres, "
             "longitude_microdegres (degrés x 1 000 000, entiers)",
    "quarts": "quarts de l'équipe (jour, debut_min, fin_min), au moins un",
    "latitude_microdegres": "latitude en degrés x 1 000 000, entier",
    "longitude_microdegres": "longitude en degrés x 1 000 000, entier",
    "intervention_id": "identifiant de l'intervention",
    "fenetre": "fenêtre du client : jours (liste d'entiers), debut_min, fin_min (minutes depuis minuit)",
    "creneau_fige": "null si aucun créneau n'est confirmé au client, sinon {equipe, jour, debut_min}",
}
_MAX_PROBLEMES = 20


# ---------------------------------------------------------------------------
# Règle de l'urgence
# ---------------------------------------------------------------------------
def urgence_depuis_declaration(urgence_declaree):
    """Niveau d'urgence du solveur pour ``urgence_declaree`` : ``(niveau, None)`` ou ``(None, verdict)``.

    Vrai vaut ``URGENCE_DECLAREE`` (1), faux ``URGENCE_NORMALE`` (0) : voir ``REGLE_URGENCE``. Une source
    absente (``None``) ou qui n'est pas un booléen strict est un verdict, jamais un 0 supposé."""
    if urgence_declaree is True:
        return URGENCE_DECLAREE, None
    if urgence_declaree is False:
        return URGENCE_NORMALE, None
    if urgence_declaree is None:
        return None, verdicts.construire_verdict(
            "REJ-CHAMP-MANQUANT",
            detail="urgence_declaree absente du registre : le niveau d'urgence ne se devine pas",
        )
    return None, verdicts.construire_verdict(
        "REJ-CONTRAT-INVALIDE",
        detail=f"urgence_declaree : booléen attendu, type reçu {type(urgence_declaree).__name__}",
    )


# ---------------------------------------------------------------------------
# Lecture du registre (une seule copie profonde pour tout le calcul)
# ---------------------------------------------------------------------------
class _Instantane:
    """Copie de lecture du registre : ``lire()`` rend toujours la même liste, sans recopier la chaîne."""

    def __init__(self, maillons):
        self._maillons = maillons

    def lire(self, depuis=None):
        return self._maillons


def instantane_du_registre(registre_cible):
    """Copie de lecture du registre (une seule lecture pour tout le calcul), pour les modules qui jugent un plan
    proposé sans le modifier (``meteo_creneaux``). Ne modifie jamais le registre."""
    return _Instantane(registre_cible.lire())


def plan_propose(instantane, plan_id):
    """Le maillon ``cedule_proposee`` de ce plan (appliqué ou non), ou ``None``. Lecture seule."""
    return _maillon_du_plan(instantane, TYPE_PROPOSEE, plan_id)


def inscriptions_du_registre(instantane):
    """``{intervention_id: maillon d'inscription}`` d'un instantané (voir ``instantane_du_registre``)."""
    return _inscriptions(instantane)


def _inscriptions(instantane):
    """``{intervention_id: maillon d'inscription}`` (la première inscription fait foi, comme ``etats``)."""
    resultat = {}
    for maillon in instantane.lire():
        if maillon["type_entree"] == etats.TYPE_INSCRIPTION:
            resultat.setdefault(maillon["intervention_id"], maillon)
    return resultat


def _reference_localisation(instantane, lead_id):
    """Version, action et ``ligne_id`` de la dernière localisation du chantier (jamais une coordonnée)."""
    resume = localisation.confirmation_courante(instantane, lead_id)
    if resume is None:
        return None
    return {"version": resume["version"], "action": resume["action"], "ligne_id": resume["ligne_id"]}


def _etat_intervention(instantane, inscription, preparations):
    """Ce dont la validité d'un plan dépend, pour une intervention, sans donnée personnelle.

    Une intervention ``a_planifier`` porte aussi l'empreinte de son verdict de préparation (``preparations`` :
    ``{intervention_id: verdict}``) : un plan proposé sur un verdict « prêt » ne s'applique plus si ce verdict a bougé.
    Les autres statuts n'ont pas cette clé : les plans d'avant T4.12 gardent leurs octets."""
    identifiant = inscription["intervention_id"]
    cle_travaux, valeur_travaux = etats.travaux_de(inscription)
    statut = etats.statut_courant(instantane, identifiant)
    etat = {
        "intervention_id": identifiant,
        "lead_id": inscription["lead_id"],
        cle_travaux: valeur_travaux,
        "urgence_declaree": inscription.get("urgence_declaree"),
        "statut": statut,
        "technicien_assigne": etats.technicien_assigne(instantane, identifiant),
        "localisation": _reference_localisation(instantane, inscription["lead_id"]),
    }
    if statut == STATUT_A_PLANIFIER:
        verdict_preparation = preparations.get(identifiant)
        etat["preparation"] = None if verdict_preparation is None else verdict_preparation["empreinte"]
    return etat


def _verdict(code, detail):
    return verdicts.construire_verdict(code, detail=detail)


def _non_prete(identifiant, verdict_preparation):
    """Ligne « pas prête » d'une intervention ``a_planifier`` : ce qui lui manque, sans coordonnée ni contact."""
    return {
        "intervention_id": identifiant,
        "statut_preparation": verdict_preparation["statut"],
        "a_fournir": copy.deepcopy(verdict_preparation["a_fournir"]),
    }


# Volets qui ne dépendent pas d'un chantier : leur « à fournir » est le même pour toutes les interventions, on ne le dit
# qu'une fois (l'adresse, la soumission et, depuis T4.14-b, le matériel, propres à un chantier ou à un devis, sont
# seulement nommés : m4_verifier_preparation dit ce qui manque, lignes de matériel comprises).
_VOLETS_D_ENTREPRISE = ("equipe", "meteo")


def _resume_non_pretes(non_pretes):
    """Une ligne par intervention non prête (ses volets manquants), puis ce que l'entreprise doit fournir, une fois."""
    lignes = " ; ".join(
        f"{ligne['intervention_id']!r} ({', '.join(f['volet'] for f in ligne['a_fournir'])})" for ligne in non_pretes
    )
    a_fournir = sorted({
        f"{f['volet']} : {f['manque']}" for ligne in non_pretes for f in ligne["a_fournir"]
        if f["volet"] in _VOLETS_D_ENTREPRISE
    })
    return lignes + (" ; à fournir : " + " ; ".join(a_fournir) if a_fournir else "")


def _evaluer(instantane, identifiant, lire_position, lire_equipes, lire_meteo=None):
    verdict_preparation, refus = preparation_intervention.evaluer(
        instantane, identifiant, lire_position, lire_equipes, lire_meteo,
    )
    if refus is not None:
        # Statut préparable vérifié juste avant : un refus ici trahirait une incohérence interne.
        raise RuntimeError(f"préparation refusée pour une intervention a_planifier : {refus['code']}")
    return verdict_preparation


def _interventions_a_planifier(instantane, inscriptions, demandees, lire_position, lire_equipes, lire_meteo=None):
    """Interventions à céduler : ``(sélection, None)`` ou ``(None, verdict)``.

    La sélection porte ``inscriptions`` (triées), ``preparations`` (le verdict de préparation de chaque intervention
    ``a_planifier`` retenue) et ``non_pretes`` (les ``a_planifier`` laissées de côté, avec ce qui leur manque). Une
    intervention ``planifiee`` est retenue comme avant T4.12 ; une ``a_planifier`` l'est SEULEMENT si son verdict est
    « prêt » (jamais présumé)."""
    statuts = {iid: etats.statut_courant(instantane, iid) for iid in inscriptions}
    preparations = {}
    non_pretes = []

    def preparer(iid):
        verdict_preparation = _evaluer(instantane, iid, lire_position, lire_equipes, lire_meteo)
        if verdict_preparation["pret"]:
            preparations[iid] = verdict_preparation
            return True
        non_pretes.append(_non_prete(iid, verdict_preparation))
        return False

    if demandees is None:
        identifiants = [
            iid for iid in sorted(inscriptions)
            if statuts[iid] == STATUT_PLANIFIABLE or (statuts[iid] == STATUT_A_PLANIFIER and preparer(iid))
        ]
    else:
        if (
            not isinstance(demandees, list)
            or not demandees
            or not all(isinstance(iid, str) and iid for iid in demandees)
        ):
            return None, _verdict(
                "REJ-CONTRAT-INVALIDE",
                "intervention_ids : liste non vide d'identifiants non vides, ou absent pour toutes les "
                "interventions planifiees et prêtes",
            )
        if len(set(demandees)) != len(demandees):
            return None, _verdict("REJ-CONTRAT-INVALIDE", "intervention_ids : identifiant en double")
        refusees = [
            iid for iid in sorted(demandees)
            if iid not in inscriptions or statuts[iid] not in (STATUT_PLANIFIABLE, STATUT_A_PLANIFIER)
        ]
        if refusees:
            return None, _verdict(
                "REJ-CEDULE-INTERVENTION-NON-PLANIFIABLE",
                "intervention inconnue ou plus au statut planifiee (ni a_planifier) : "
                + ", ".join(repr(iid) for iid in refusees),
            )
        identifiants = sorted(demandees)
        for iid in identifiants:
            if statuts[iid] == STATUT_A_PLANIFIER:
                preparer(iid)
        if non_pretes:
            return None, _verdict(
                "REJ-CEDULE-PREPARATION-NON-PRETE",
                "intervention a_planifier dont la préparation n'est pas prête : " + _resume_non_pretes(non_pretes)
                + " (m4_verifier_preparation dit ce qui manque)",
            )
    if not identifiants:
        detail = "aucune intervention planifiee ni a_planifier prête : rien à céduler"
        if non_pretes:
            detail += " ; a_planifier non prêtes : " + _resume_non_pretes(non_pretes) + " (m4_verifier_preparation)"
        return None, _verdict("REJ-CEDULE-RIEN-A-PLANIFIER", detail)
    return {
        "inscriptions": [inscriptions[iid] for iid in identifiants],
        "preparations": preparations,
        "non_pretes": non_pretes,
    }, None


# ---------------------------------------------------------------------------
# Lecture des arguments : tout ce que M4 ne sait pas encore
# ---------------------------------------------------------------------------
class _Problemes:
    """Problèmes d'arguments, rapportés TOUS ensemble : le verdict dit tout ce qu'il faut fournir."""

    def __init__(self):
        self.absents = []
        self.invalides = []

    def verdict(self):
        tous = self.absents + self.invalides
        if not tous:
            return None
        detail = " ; ".join(tous[:_MAX_PROBLEMES])
        if len(tous) > _MAX_PROBLEMES:
            detail += f" ; … et {len(tous) - _MAX_PROBLEMES} autres"
        return _verdict("REJ-CHAMP-MANQUANT" if self.absents else "REJ-CONTRAT-INVALIDE", detail)


def _est_entier(valeur):
    return type(valeur) is int


def _objet(valeur, chemin, cles, problemes, nullables=()):
    """L'objet si toutes ses clés y sont (sinon ``None``) ; clés absentes et inconnues rapportées."""
    if not isinstance(valeur, dict):
        problemes.invalides.append(f"{chemin} : un objet est attendu ({', '.join(cles)})")
        return None
    manquantes = [cle for cle in cles if cle not in valeur or (valeur[cle] is None and cle not in nullables)]
    for cle in manquantes:
        problemes.absents.append(f"{chemin}.{cle} manquant : {_AIDE[cle]}")
    en_trop = sorted(str(cle) for cle in valeur if cle not in cles)
    if en_trop:
        problemes.invalides.append(f"{chemin} : clés inconnues : {', '.join(en_trop)}")
    return None if manquantes else valeur


def _lire_depot(brut, chemin, problemes):
    """``(id, latitude, longitude)`` du dépôt, ou ``None`` (problèmes rapportés)."""
    objet = _objet(brut, chemin, _CLES_DEPOT, problemes)
    if objet is None:
        return None
    bon = True
    if not isinstance(objet["id"], str) or not objet["id"]:
        problemes.invalides.append(f"{chemin}.id : chaîne non vide requise")
        bon = False
    for cle in ("latitude_microdegres", "longitude_microdegres"):
        if not _est_entier(objet[cle]):
            problemes.invalides.append(
                f"{chemin}.{cle} : entier requis ({_AIDE[cle]}), type reçu {type(objet[cle]).__name__}",
            )
            bon = False
    if not bon:
        return None
    return objet["id"], objet["latitude_microdegres"], objet["longitude_microdegres"]


def _lire_equipes(brut, problemes):
    """``(équipes du solveur, dépôts {id: (lat, lon)})`` ; ``None`` si l'argument est inutilisable."""
    if not isinstance(brut, list):
        problemes.invalides.append("equipes : une liste est attendue")
        return None
    if not brut:
        problemes.absents.append(f"equipes manquantes : fournir au moins une équipe, {_AIDE['equipes']}")
        return None
    equipes = []
    depots = {}
    bon = True
    for position, equipe in enumerate(brut):
        identifiant = equipe.get("id") if isinstance(equipe, dict) else None
        nom = f"equipes[{position}] {identifiant!r}" if isinstance(identifiant, str) and identifiant \
            else f"equipes[{position}]"
        objet = _objet(equipe, nom, _CLES_EQUIPE, problemes)
        if objet is None:
            bon = False
            continue
        depot = _lire_depot(objet["depot"], f"{nom}.depot", problemes)
        if depot is None:
            bon = False
            continue
        depot_id, latitude, longitude = depot
        if depots.setdefault(depot_id, (latitude, longitude)) != (latitude, longitude):
            problemes.invalides.append(f"{nom}.depot : le dépôt {depot_id!r} a deux positions différentes")
            bon = False
            continue
        equipes.append({
            "id": objet["id"], "competences": copy.deepcopy(objet["competences"]),
            "depot": depot_id, "quarts": copy.deepcopy(objet["quarts"]),
        })
    return (equipes, depots) if bon else None


def _lire_par_cle(brut, cle, requis, connus, libelle_connus, valeur_valide, aide_valeur, problemes):
    """``{clé: valeur}`` pour les clés requises ; les clés inconnues ou absentes sont rapportées.

    ``connus`` : les clés admises (types de travaux v1, ou services déclarés v2) ; ``libelle_connus`` : la
    phrase qui les décrit dans le verdict."""
    if not isinstance(brut, dict):
        problemes.invalides.append(f"{cle} : un objet est attendu (une clé par nature de travaux)")
        return None
    inconnus = sorted(str(nature) for nature in brut if nature not in connus)
    if inconnus:
        problemes.invalides.append(f"{cle} : {libelle_connus[0]} : {', '.join(inconnus)} ({libelle_connus[1]})")
    resultat = {}
    for nature in requis:
        valeur = brut.get(nature)
        if valeur is None:
            problemes.absents.append(f"{cle}.{nature} manquant : {aide_valeur}")
        elif not valeur_valide(valeur):
            problemes.invalides.append(f"{cle}.{nature} : {aide_valeur}")
        else:
            resultat[nature] = valeur
    return resultat


def _lire_par_type(brut, cle, types_requis, valeur_valide, aide_valeur, problemes):
    """``{type_travaux: valeur}`` (leads v1) pour les types requis ; inconnus ou absents rapportés."""
    return _lire_par_cle(
        brut, cle, types_requis, cedule.TYPES_TRAVAUX,
        ("types de travaux inconnus", f"attendus : {', '.join(cedule.TYPES_TRAVAUX)}"),
        valeur_valide, aide_valeur, problemes,
    )


def _lire_par_service(brut, cle, services_requis, valeur_valide, aide_valeur, problemes):
    """``{service: valeur}`` (leads v2) pour les services requis ; les clés qui ne sont pas des services
    déclarés par le profil d'entreprise (taxonomie du socle), ou qui manquent, sont rapportées."""
    declares, verdict = cedule.services_declares()
    if verdict is not None:
        problemes.invalides.append(f"{cle} : {verdict['code']} : {verdict['detail']}")
        return None
    return _lire_par_cle(
        brut, cle, services_requis, declares,
        ("services inconnus", f"déclarés : {', '.join(declares)}"),
        valeur_valide, aide_valeur, problemes,
    )


def _liste_de_textes(valeur):
    return isinstance(valeur, list) and all(isinstance(element, str) and element for element in valeur)


def _lire_chantiers(brut, identifiants_requis, problemes):
    """``{intervention_id: entrée}`` : une entrée complète par intervention à planifier."""
    if not isinstance(brut, list):
        problemes.invalides.append("chantiers : une liste est attendue")
        return None
    par_id = {}
    mentionnes = set()
    for position, entree in enumerate(brut):
        identifiant = entree.get("intervention_id") if isinstance(entree, dict) else None
        nom = f"chantiers[{position}] {identifiant!r}" if isinstance(identifiant, str) and identifiant \
            else f"chantiers[{position}]"
        objet = _objet(entree, nom, _CLES_CHANTIER, problemes, nullables=("creneau_fige",))
        if isinstance(identifiant, str) and identifiant:
            if identifiant in mentionnes:
                problemes.invalides.append(f"{nom} : intervention en double")
                continue
            mentionnes.add(identifiant)
            if identifiant not in identifiants_requis:
                problemes.invalides.append(
                    f"{nom} : intervention inconnue, plus au statut planifiee, ou hors de intervention_ids",
                )
                continue
        elif objet is not None:
            problemes.invalides.append(f"{nom}.intervention_id : chaîne non vide requise")
            continue
        if objet is not None:
            par_id[identifiant] = objet
    for identifiant in identifiants_requis:
        if identifiant not in mentionnes:
            problemes.absents.append(
                f"chantiers : entrée de l'intervention {identifiant!r} manquante ({_AIDE['chantiers']})",
            )
    return par_id


def _lire_parametres(brut, problemes):
    """``(paramètres de distance, paramètres du solveur)`` ; ``None`` si l'argument est inutilisable."""
    if not isinstance(brut, dict):
        problemes.invalides.append("parametres : un objet est attendu")
        return None
    bon = True
    for cle in CLES_PARAMETRES_REQUISES:
        if brut.get(cle) is None:
            aide = distances.BORNES_PARAMETRES.get(cle)
            precision = f", entre {aide[0]} et {aide[1]}" if aide is not None else ""
            problemes.absents.append(f"parametres.{cle} manquant : paramètre d'entreprise{precision}")
            bon = False
    connues = CLES_PARAMETRES_REQUISES + CLES_PARAMETRES_OPTIONNELLES
    en_trop = sorted(str(cle) for cle in brut if cle not in connues)
    if en_trop:
        problemes.invalides.append(f"parametres : clés inconnues : {', '.join(en_trop)}")
        bon = False
    if not bon:
        return None
    distance = {cle: brut[cle] for cle in CLES_PARAMETRES_DISTANCE}
    solveur = {
        "graine": GRAINE_TECHNIQUE if brut.get("graine") is None else brut["graine"],
        "iterations": brut["iterations"],
        "cout_non_cedule_m": brut["cout_non_cedule_m"],
    }
    return distance, solveur


_CLES_EQUIPE_SOLVEUR = ("id", "competences", "depot", "quarts")


def _equipes_du_profil(profil):
    """Les équipes du profil au format du solveur : ``membres`` n'y entre pas (il sert à l'accès, pas aux tournées)."""
    return [{cle: copy.deepcopy(equipe[cle]) for cle in _CLES_EQUIPE_SOLVEUR} for equipe in profil["liste"]]


def _completer_par_le_profil(arguments, selection, lire_equipes):
    """Les arguments EFFECTIFS : ceux de l'appelant, complétés par le profil des équipes pour ce qu'il n'a pas donné.

    Rend ``(effectifs, provenance, empreinte_profil, verdict_profil)``. Un argument donné (non ``null``) REMPLACE la
    clé entière du profil : c'est une surcharge, jamais une fusion. ``provenance`` dit, pour chaque clé utilisée,
    ``profil`` ou ``surcharge`` (pour ``chantiers`` : une source par intervention). ``empreinte_profil`` n'est posée
    que si au moins une valeur vient du profil. ``verdict_profil`` est le verdict de la lecture du profil (absent,
    invalide) ou ``None`` : il sert à dire quoi déclarer quand des valeurs manquent, jamais à en inventer.
    Sans ``lire_equipes``, rien n'est complété (comportement d'avant T4.12)."""
    profil, verdict_profil = (None, None) if lire_equipes is None else lire_equipes()
    natures = [etats.travaux_de(inscription) for inscription in selection["inscriptions"]]
    services_requis = sorted({valeur for cle, valeur in natures if cle == etats.CLE_SERVICE})
    types_requis = bool([valeur for cle, valeur in natures if cle == etats.CLE_TYPE_TRAVAUX])
    effectifs = dict(arguments)
    provenance = {}

    def donne(cle):
        return arguments.get(cle) is not None

    if donne("equipes"):
        provenance["equipes"] = SOURCE_SURCHARGE
    elif profil is not None and "liste" in profil:
        effectifs["equipes"] = _equipes_du_profil(profil)
        provenance["equipes"] = SOURCE_PROFIL
    if donne("parametres"):
        provenance["parametres"] = SOURCE_SURCHARGE
    elif profil is not None and "cedule" in profil:
        effectifs["parametres"] = copy.deepcopy(profil["cedule"])
        provenance["parametres"] = SOURCE_PROFIL
    if services_requis:
        for cle, champ in (("durees_par_service", "duree_min"), ("competences_par_service", "competences")):
            services = None if profil is None else profil.get("services")
            if donne(cle):
                provenance[cle] = SOURCE_SURCHARGE
            elif isinstance(services, dict) and any(service in services for service in services_requis):
                effectifs[cle] = {
                    service: copy.deepcopy(services[service][champ])
                    for service in services_requis if service in services
                }
                provenance[cle] = SOURCE_PROFIL
    if types_requis:  # leads v1 (gelés) : le profil est par service, ces tables restent des arguments
        for cle in ("durees_par_type_travaux", "competences_par_type_travaux"):
            if donne(cle):
                provenance[cle] = SOURCE_SURCHARGE

    # Chantiers : l'entrée donnée par l'appelant fait foi ; une intervention a_planifier qui n'en a pas prend la
    # fenêtre par défaut du profil et AUCUN créneau figé (avant toute cédule, aucun créneau n'a pu être promis).
    donnes = arguments.get("chantiers")
    sources = {}
    if isinstance(donnes, list):
        for entree in donnes:
            if isinstance(entree, dict) and isinstance(entree.get("intervention_id"), str):
                sources[entree["intervention_id"]] = SOURCE_SURCHARGE
    fenetre = None if profil is None else profil.get("fenetre_par_defaut")
    if fenetre is not None and (donnes is None or isinstance(donnes, list)):
        generes = [
            {"intervention_id": identifiant, "fenetre": copy.deepcopy(fenetre), "creneau_fige": None}
            for identifiant in sorted(selection["preparations"]) if identifiant not in sources
        ]
        if generes:
            effectifs["chantiers"] = list(donnes or []) + generes
            sources.update({entree["intervention_id"]: SOURCE_PROFIL for entree in generes})
    if sources:
        provenance["chantiers"] = dict(sorted(sources.items()))

    utilise_le_profil = SOURCE_PROFIL in provenance.get("chantiers", {}).values() or any(
        source == SOURCE_PROFIL for cle, source in provenance.items() if cle != "chantiers"
    )
    empreinte_profil = encodage.empreinte("profil-equipes", profil) if utilise_le_profil else None
    return effectifs, provenance, empreinte_profil, verdict_profil


_INVITATION_PROFIL = (
    "à défaut d'argument, ces valeurs se déclarent une fois pour toutes dans le profil des équipes de l'entreprise "
    "(`opsys equipes declarer`)"
)


def _verdict_avec_le_profil(verdict, verdict_profil, lire_equipes):
    """Quand des valeurs manquent, le verdict dit aussi où les déclarer ; un profil invalide garde son code."""
    if lire_equipes is None or verdict["code"] != "REJ-CHAMP-MANQUANT":
        return verdict
    if verdict_profil is None:
        return _verdict(verdict["code"], f"{verdict['detail']} ; {_INVITATION_PROFIL}")
    code = "REJ-PROFIL-INVALIDE" if verdict_profil["code"] == "REJ-PROFIL-INVALIDE" else verdict["code"]
    return _verdict(code, f"{verdict['detail']} ; {verdict_profil['detail']}")


def _lire_arguments(arguments, inscriptions_a_planifier):
    """Assemble les chantiers et les équipes du solveur. ``(dict, None)`` ou ``(None, verdict)``."""
    problemes = _Problemes()
    en_trop = sorted(
        str(cle) for cle in arguments if cle not in _CLES_ARGUMENTS + _CLES_ARGUMENTS_OPTIONNELLES
    )
    if en_trop:
        problemes.invalides.append(f"arguments : clés inconnues : {', '.join(en_trop)}")
    # La nature des travaux de chaque intervention vient du registre (v1 : type_travaux, v2 : service). Les
    # tables de durées et de compétences ne sont exigées que pour la version présente dans le lot ; celle
    # d'une version absente est acceptée si elle est fournie (et validée), jamais exigée.
    identifiants = [inscription["intervention_id"] for inscription in inscriptions_a_planifier]
    natures = [etats.travaux_de(inscription) for inscription in inscriptions_a_planifier]
    types_requis = sorted({valeur for cle, valeur in natures if cle == etats.CLE_TYPE_TRAVAUX})
    services_requis = sorted({valeur for cle, valeur in natures if cle == etats.CLE_SERVICE})
    requises = _CLES_ARGUMENTS_COMMUNES + (_CLES_ARGUMENTS_V1 if types_requis else ()) + (
        _CLES_ARGUMENTS_V2 if services_requis else ())
    presents = {}
    for cle in _CLES_ARGUMENTS:
        if arguments.get(cle) is None:
            if cle in requises:
                problemes.absents.append(f"{cle} manquant : {_AIDE[cle]}")
        else:
            presents[cle] = arguments[cle]

    equipes = _lire_equipes(presents["equipes"], problemes) if "equipes" in presents else None
    durees = competences = durees_service = competences_service = fiches = parametres = None
    if "durees_par_type_travaux" in presents:
        durees = _lire_par_type(
            presents["durees_par_type_travaux"], "durees_par_type_travaux", types_requis, _est_entier,
            _AIDE["durees_par_type_travaux"], problemes,
        )
    if "competences_par_type_travaux" in presents:
        competences = _lire_par_type(
            presents["competences_par_type_travaux"], "competences_par_type_travaux", types_requis,
            _liste_de_textes, _AIDE["competences_par_type_travaux"], problemes,
        )
    if "durees_par_service" in presents:
        durees_service = _lire_par_service(
            presents["durees_par_service"], "durees_par_service", services_requis, _est_entier,
            _AIDE["durees_par_service"], problemes,
        )
    if "competences_par_service" in presents:
        competences_service = _lire_par_service(
            presents["competences_par_service"], "competences_par_service", services_requis,
            _liste_de_textes, _AIDE["competences_par_service"], problemes,
        )
    if "chantiers" in presents:
        fiches = _lire_chantiers(presents["chantiers"], set(identifiants), problemes)
    if "parametres" in presents:
        parametres = _lire_parametres(presents["parametres"], problemes)
    verdict = problemes.verdict()
    if verdict is not None:
        return None, verdict

    chantiers = []
    urgences = {}
    for inscription in inscriptions_a_planifier:
        identifiant = inscription["intervention_id"]
        urgence, verdict = urgence_depuis_declaration(inscription.get("urgence_declaree"))
        if verdict is not None:
            return None, _verdict(verdict["code"], f"intervention {identifiant!r} : {verdict['detail']}")
        urgences[identifiant] = urgence
        fiche = fiches[identifiant]
        cle_travaux, nature = etats.travaux_de(inscription)
        if cle_travaux == etats.CLE_SERVICE:
            duree, requises_competences = durees_service[nature], competences_service[nature]
        else:
            duree, requises_competences = durees[nature], competences[nature]
        chantiers.append({
            "id": identifiant,
            "duree_min": duree,
            "fenetre": copy.deepcopy(fiche["fenetre"]),
            "competences_requises": list(requises_competences),
            "urgence": urgence,
            "creneau_fige": copy.deepcopy(fiche["creneau_fige"]),
        })
    equipes_solveur, depots = equipes
    parametres_distance, parametres_solveur = parametres
    return {
        "equipes": equipes_solveur, "depots": depots, "chantiers": chantiers, "urgences": urgences,
        "parametres_distance": parametres_distance, "parametres_solveur": parametres_solveur,
    }, None


# ---------------------------------------------------------------------------
# Entrée du solveur
# ---------------------------------------------------------------------------
def _entree_solveur(preparation, leads, instantane, lire_position, fournisseur):
    """Entrée complète du solveur avec les coordonnées CONFIRMÉES d'aujourd'hui.

    ``preparation`` : équipes, dépôts (``{id: (latitude, longitude)}``), chantiers du solveur, paramètres.
    ``leads`` : ``{intervention_id: lead_id}``. Un chantier sans position lisible (jamais confirmée, retirée,
    clé détruite) n'entre pas dans la matrice : le solveur le rend « coordonnées manquantes : à confirmer »,
    jamais placé au centre d'une ville."""
    positions = {}
    for lead_id in sorted(set(leads.values())):
        position, verdict = lire_position(instantane, lead_id)
        positions[lead_id] = position if verdict is None else None
    points = [
        {"id": depot_id, "latitude_microdeg": latitude, "longitude_microdeg": longitude}
        for depot_id, (latitude, longitude) in sorted(preparation["depots"].items())
    ]
    for chantier in preparation["chantiers"]:
        position = positions[leads[chantier["id"]]]
        if position is not None:
            points.append({
                "id": chantier["id"],
                "latitude_microdeg": position["latitude_microdegres"],
                "longitude_microdeg": position["longitude_microdegres"],
            })
    matrice, verdict = distances.obtenir_matrice(points, preparation["parametres_distance"], fournisseur)
    if verdict is not None:
        return None, verdict
    return {
        "version": tournees.VERSION_ENTREE,
        "equipes": copy.deepcopy(preparation["equipes"]),
        "chantiers": copy.deepcopy(preparation["chantiers"]),
        "matrice": matrice,
        "parametres": dict(preparation["parametres_solveur"]),
    }, None


def _preparation_depuis_maillon(proposee):
    """Reconstruit ``preparation`` à partir de l'entrée sans matrice rangée dans le maillon du plan."""
    entree = proposee["entree"]
    equipes = []
    depots = {}
    for equipe in entree["equipes"]:
        depot = equipe["depot"]
        depots[depot["id"]] = (depot["latitude_microdegres"], depot["longitude_microdegres"])
        equipes.append({
            "id": equipe["id"], "competences": copy.deepcopy(equipe["competences"]),
            "depot": depot["id"], "quarts": copy.deepcopy(equipe["quarts"]),
        })
    return {
        "equipes": equipes, "depots": depots, "chantiers": copy.deepcopy(entree["chantiers"]),
        "parametres_distance": dict(entree["parametres_distance"]),
        "parametres_solveur": dict(entree["parametres"]),
    }


def _entree_stockee(preparation):
    """Ce que le maillon du plan garde de l'entrée : tout sauf la matrice (donc aucune coordonnée de chantier)."""
    equipes = []
    for equipe in preparation["equipes"]:
        latitude, longitude = preparation["depots"][equipe["depot"]]
        equipes.append({
            "id": equipe["id"], "competences": copy.deepcopy(equipe["competences"]),
            "depot": {"id": equipe["depot"], "latitude_microdegres": latitude, "longitude_microdegres": longitude},
            "quarts": copy.deepcopy(equipe["quarts"]),
        })
    return {
        "equipes": equipes,
        "chantiers": copy.deepcopy(preparation["chantiers"]),
        "parametres_distance": dict(preparation["parametres_distance"]),
        "parametres": dict(preparation["parametres_solveur"]),
    }


# ---------------------------------------------------------------------------
# Maillons du plan
# ---------------------------------------------------------------------------
def _maillon_du_plan(instantane, type_entree, plan_id):
    for maillon in instantane.lire():
        if maillon["type_entree"] == type_entree and maillon.get("plan_id") == plan_id:
            return maillon
    return None


def _avertissement(mode_bride):
    return AVERTISSEMENT_MODE_BRIDE if mode_bride else None


def _resultat_proposition(maillon, deja, provenance, non_pretes):
    """Le plan rangé, tel que le maillon le garde ; ``provenance`` (d'où vient chaque valeur) et ``non_pretes`` (les
    interventions a_planifier laissées de côté) sont ceux de CET appel, pas ceux d'un appel antérieur."""
    sortie = maillon["sortie"]
    meta = sortie["meta"]
    return {
        "plan_id": maillon["plan_id"],
        "deja_proposee": deja,
        "mode_distance": meta["mode_distance"],
        "mode_bride": meta["mode_bride"],
        "avertissement": _avertissement(meta["mode_bride"]),
        "solveur": meta["solveur"],
        "version_solveur": meta["version_solveur"],
        "empreinte_entree": maillon["empreinte_entree"],
        "empreinte_sortie": maillon["empreinte_sortie"],
        "empreinte_etat": maillon["empreinte_etat"],
        "urgences": {chantier["id"]: chantier["urgence"] for chantier in maillon["entree"]["chantiers"]},
        "regle_urgence": REGLE_URGENCE,
        "totaux": copy.deepcopy(sortie["totaux"]),
        "plan": copy.deepcopy(sortie["plan"]),
        "non_cedulees": copy.deepcopy(sortie["non_cedulees"]),
        "horodatage": maillon["horodatage"],
        "propose_par": maillon["propose_par"],
        "provenance": copy.deepcopy(provenance),
        "non_pretes": copy.deepcopy(non_pretes),
        "a_appliquer_par": "m4_appliquer_cedule (N3, admin) avec ce plan_id ; rien n'est assigné avant",
    }


def proposer(
    registre_cible, arguments, lire_position, horodatage_arg, propose_par=None, fournisseur=None, moteur="auto",
    lire_equipes=None, lire_meteo=None,
):
    """Propose un plan de tournées et le range au registre. Retourne ``(résultat, None)`` ou ``(None, verdict)``.

    Aucune vérité n'est écrite : le maillon ``cedule_proposee`` est un brouillon que ``appliquer`` peut
    transformer en assignations. Les arguments (``equipes``, ``durees_par_type_travaux``,
    ``competences_par_type_travaux``, ``durees_par_service``, ``competences_par_service``, ``chantiers``,
    ``parametres``, ``intervention_ids`` optionnel) sont décrits dans l'en-tête du module ; tout ce qui manque est
    rapporté en UN verdict. ``lire_position(registre, lead_id)`` rend ``(position, None)`` ou ``(None, verdict)``
    comme ``outils.lire_localisation_confirmee``. ``lire_equipes()`` rend ``(profil, None)`` ou ``(None, verdict)``
    (``opsys.equipes.charger_equipes``) : ce que le profil des équipes déclare complète les arguments absents, et un
    argument donné le REMPLACE (surcharge, tracée dans ``provenance``). ``fournisseur`` : port
    ``distances.FournisseurMatrice`` ou ``None`` (palier 0). Même entrées : même plan, même ``plan_id``, que les
    valeurs viennent du profil ou d'arguments identiques ; une proposition identique n'écrit rien de plus.
    ``lire_meteo()`` rend ``(profil météo, None)`` ou ``(None, verdict)`` (``opsys.meteo.charger_meteo``) : le volet
    météo de la préparation (T4.13) : les règles du service ; sans cette lecture, ce volet reste « non vérifiable » et
    aucune
    intervention a_planifier n'est prête."""
    try:
        horodatage.valider_horodatage(horodatage_arg)
    except ValueError:
        return None, verdicts.construire_verdict("REJ-HORODATAGE-INVALIDE")
    if not isinstance(arguments, dict):
        return None, _verdict("REJ-CONTRAT-INVALIDE", "arguments : un objet est attendu")
    if propose_par is not None and (not isinstance(propose_par, str) or not propose_par):
        return None, _verdict("REJ-CONTRAT-INVALIDE", "propose_par : chaîne non vide ou null")

    instantane = _Instantane(registre_cible.lire())
    inscriptions = _inscriptions(instantane)
    selection, verdict = _interventions_a_planifier(
        instantane, inscriptions, arguments.get("intervention_ids"), lire_position, lire_equipes, lire_meteo,
    )
    if verdict is not None:
        return None, verdict
    a_planifier = selection["inscriptions"]
    effectifs, provenance, empreinte_profil, verdict_profil = _completer_par_le_profil(
        arguments, selection, lire_equipes,
    )
    preparation, verdict = _lire_arguments(effectifs, a_planifier)
    if verdict is not None:
        return None, _verdict_avec_le_profil(verdict, verdict_profil, lire_equipes)
    leads = {inscription["intervention_id"]: inscription["lead_id"] for inscription in a_planifier}
    entree, verdict = _entree_solveur(preparation, leads, instantane, lire_position, fournisseur)
    if verdict is not None:
        return None, verdict
    sortie, verdict = tournees.resoudre(entree, moteur)
    if verdict is not None:
        return None, verdict

    etat = [_etat_intervention(instantane, inscription, selection["preparations"]) for inscription in a_planifier]
    meta = sortie["meta"]
    empreinte_etat = encodage.empreinte(etat)
    plan_id = encodage.empreinte(
        VERSION_PROPOSITION, meta["empreinte_entree"], meta["empreinte_sortie"], empreinte_etat,
    )
    existant = _maillon_du_plan(instantane, TYPE_PROPOSEE, plan_id)
    if existant is not None:
        return _resultat_proposition(existant, True, provenance, selection["non_pretes"]), None

    maillon = {
        "type_entree": TYPE_PROPOSEE,
        "horodatage": horodatage_arg,
        "version": VERSION_PROPOSITION,
        "plan_id": plan_id,
        "propose_par": propose_par,
        "moteur": moteur,
        "entree": _entree_stockee(preparation),
        "etat": etat,
        "provenance": provenance,
        "empreinte_profil": empreinte_profil,
        "empreinte_entree": meta["empreinte_entree"],
        "empreinte_sortie": meta["empreinte_sortie"],
        "empreinte_etat": empreinte_etat,
        "sortie": sortie,
    }
    registre_cible.ajouter(maillon)
    return _resultat_proposition(maillon, False, provenance, selection["non_pretes"]), None


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
def _differences(avant, apres):
    """Ce qui a changé entre l'état de la proposition et l'état actuel, une phrase par écart."""
    lignes = []
    for ancien, actuel in zip(avant, apres, strict=True):
        if ancien == actuel:
            continue
        champs = sorted(cle for cle in ancien if ancien[cle] != actuel.get(cle))
        details = ", ".join(f"{cle} : {ancien[cle]!r} devenu {actuel.get(cle)!r}" for cle in champs)
        lignes.append(f"intervention {ancien['intervention_id']!r} : {details}")
    return lignes


def _resultat_application(marqueur, proposee, deja):
    meta = proposee["sortie"]["meta"]
    conservees = {ligne["chantier"]: ligne["technicien_assigne"] for ligne in marqueur["non_cedulees"]}
    return {
        "plan_id": marqueur["plan_id"],
        "deja_appliquee": deja,
        "appliquee_par": marqueur["appliquee_par"],
        "horodatage": marqueur["horodatage"],
        "mode_distance": meta["mode_distance"],
        "mode_bride": meta["mode_bride"],
        "avertissement": _avertissement(meta["mode_bride"]),
        "assignations": copy.deepcopy(marqueur["assignations"]),
        "non_cedulees": [
            {**ligne, "assignation_conservee": conservees.get(ligne["chantier"])}
            for ligne in proposee["sortie"]["non_cedulees"]
        ],
    }


def _equipes_admissibles_pour_les_sorties(instantane, inscriptions, visites, preparations, lire_equipes):
    """``None`` ou un verdict : l'équipe qui reçoit une intervention SORTANT de ``a_planifier`` est admissible selon le
    profil des équipes (``admissibilite.py``), même si le plan a été proposé avec des équipes en surcharge.

    Le volet équipe de la préparation certifie qu'une équipe du PROFIL peut faire le service ; sans ce contrôle, un plan
    proposé avec d'autres équipes ferait sortir l'intervention sur un « prêt » qui ne parle pas de l'équipe assignée."""
    sortantes = [(chantier, equipe) for chantier, equipe in visites if chantier in preparations]
    if not sortantes:
        return None
    profil, verdict_profil = (None, None) if lire_equipes is None else lire_equipes()
    refus = []
    for chantier, equipe in sortantes:
        _, service = etats.travaux_de(inscriptions[chantier])
        if profil is None:
            raison = "profil des équipes illisible" + ("" if verdict_profil is None else f" ({verdict_profil['code']})")
        else:
            resultat, verdict = admissibilite.equipes_admissibles(profil, service)
            if verdict is not None:
                raison = verdict["detail"]
            elif equipe in resultat["admissibles"]:
                continue
            else:
                raison = f"admissibles : {', '.join(resultat['admissibles']) or 'aucune'}"
        refus.append(f"{chantier!r} ({service}) confiée à {equipe!r} : {raison}")
    if not refus:
        return None
    return _verdict(
        "REJ-TOURNEES-PLAN-INVALIDE",
        "l'équipe assignée à une intervention qui sort de a_planifier n'est pas admissible selon le profil des "
        "équipes : " + " ; ".join(refus[:_MAX_PROBLEMES]),
    )


def appliquer(
    registre_cible, plan_id, lire_position, horodatage_arg, appliquee_par, fournisseur=None, lire_equipes=None,
    lire_meteo=None,
):
    """Applique un plan PROPOSÉ : assigne les techniciens. Retourne ``(résultat, None)`` ou ``(None, verdict)``.

    Une intervention ``a_planifier`` que le plan place passe d'abord à ``planifiee`` (``etats.transitionner``, avec le
    verdict de préparation « prêt » recalculé ICI : la porte d'empreinte de T4.10), puis reçoit son équipe.

    Refus, sans rien écrire : plan inconnu (``REJ-CEDULE-PLAN-INTROUVABLE``) ; intervention ``a_planifier`` dont la
    préparation n'est plus prête (``REJ-CEDULE-PREPARATION-NON-PRETE``) ; état des interventions, profil des équipes
    ou entrée du solveur changés depuis la proposition (``REJ-CEDULE-ENTREE-CHANGEE``) ; plan qui échoue à
    ``tournees.verifier_plan`` (``REJ-TOURNEES-PLAN-INVALIDE``) ; plan sans visite
    (``REJ-CEDULE-RIEN-A-PLANIFIER``). Un plan déjà appliqué rend son application enregistrée
    (``deja_appliquee``) sans rien écrire. Un créneau figé qui ne serait pas tenu est un plan invalide : il
    n'est jamais déplacé. ``appliquee_par`` : la personne qui applique (nommément)."""
    try:
        horodatage.valider_horodatage(horodatage_arg)
    except ValueError:
        return None, verdicts.construire_verdict("REJ-HORODATAGE-INVALIDE")
    if not isinstance(plan_id, str) or not plan_id:
        return None, _verdict("REJ-CHAMP-VIDE", "plan_id : identifiant du plan proposé requis")
    if not isinstance(appliquee_par, str) or not appliquee_par:
        return None, _verdict("REJ-CHAMP-VIDE", "appliquee_par : nom de la personne qui applique requis")

    instantane = _Instantane(registre_cible.lire())
    proposee = _maillon_du_plan(instantane, TYPE_PROPOSEE, plan_id)
    if proposee is None:
        return None, _verdict("REJ-CEDULE-PLAN-INTROUVABLE", f"aucun plan proposé sous l'identifiant {plan_id!r}")
    deja = _maillon_du_plan(instantane, TYPE_APPLIQUEE, plan_id)
    if deja is not None:
        return _resultat_application(deja, proposee, True), None

    inscriptions = _inscriptions(instantane)
    avant = proposee["etat"]
    # Le verdict de préparation d'AUJOURD'HUI de chaque intervention encore a_planifier : c'est lui, et lui seul, qui
    # ouvre la porte a_planifier -> planifiee. Une préparation devenue non prête refuse tout, sans rien écrire.
    preparations = {}
    for ligne in avant:
        identifiant = ligne["intervention_id"]
        if etats.statut_courant(instantane, identifiant) == STATUT_A_PLANIFIER:
            preparations[identifiant] = _evaluer(instantane, identifiant, lire_position, lire_equipes, lire_meteo)
    non_pretes = [_non_prete(iid, v) for iid, v in sorted(preparations.items()) if not v["pret"]]
    if non_pretes:
        return None, _verdict(
            "REJ-CEDULE-PREPARATION-NON-PRETE",
            "intervention a_planifier dont la préparation n'est plus prête : " + _resume_non_pretes(non_pretes)
            + " (m4_verifier_preparation dit ce qui manque)",
        )
    apres = [_etat_intervention(instantane, inscriptions[ligne["intervention_id"]], preparations) for ligne in avant]
    if apres != avant:
        return None, _verdict(
            "REJ-CEDULE-ENTREE-CHANGEE",
            "l'état des interventions a changé depuis la proposition, proposer de nouveau : "
            + " ; ".join(_differences(avant, apres)[:_MAX_PROBLEMES]),
        )
    if proposee.get("empreinte_profil") is not None:
        profil, verdict_profil = (None, None) if lire_equipes is None else lire_equipes()
        if profil is None or encodage.empreinte("profil-equipes", profil) != proposee["empreinte_profil"]:
            detail = "" if verdict_profil is None else f" ({verdict_profil['detail']})"
            return None, _verdict(
                "REJ-CEDULE-ENTREE-CHANGEE",
                "le profil des équipes a changé depuis la proposition, ou n'est plus lisible : proposer de nouveau"
                + detail,
            )

    preparation = _preparation_depuis_maillon(proposee)
    leads = {ligne["intervention_id"]: ligne["lead_id"] for ligne in avant}
    entree, verdict = _entree_solveur(preparation, leads, instantane, lire_position, fournisseur)
    if verdict is not None:
        return None, verdict
    empreinte, verdict = tournees.empreinte_entree(entree)
    if verdict is not None:
        return None, verdict
    sortie = proposee["sortie"]
    if empreinte != proposee["empreinte_entree"]:
        return None, _verdict(
            "REJ-CEDULE-ENTREE-CHANGEE",
            "les coordonnées confirmées, les distances ou les équipes ne donnent plus la même entrée du "
            "solveur que lors de la proposition : proposer de nouveau",
        )
    if sortie["meta"]["empreinte_sortie"] != proposee["empreinte_sortie"]:
        return None, _verdict(
            "REJ-TOURNEES-PLAN-INVALIDE", "l'empreinte de sortie du maillon ne correspond pas au plan qu'il porte",
        )
    valide, violations = tournees.verifier_plan(entree, sortie)
    if not valide:
        return None, tournees.verdict_tournees(
            tournees.CODE_PLAN_INVALIDE, " ; ".join(violations[:_MAX_PROBLEMES]),
        )

    visites = [
        (visite["chantier"], route["equipe"]) for route in sortie["plan"] for visite in route["visites"]
    ]
    if not visites:
        return None, _verdict(
            "REJ-CEDULE-RIEN-A-PLANIFIER", "le plan ne place aucun chantier : rien à appliquer",
        )
    verdict = _equipes_admissibles_pour_les_sorties(instantane, inscriptions, visites, preparations, lire_equipes)
    if verdict is not None:
        return None, verdict

    assignations = []
    for chantier, equipe in visites:
        transition = None
        if chantier in preparations:
            _, verdict = etats.transitionner(
                chantier, "planifiee", registre_cible, horodatage_arg, preparation=preparations[chantier],
            )
            if verdict is not None:
                # Verdict « prêt » recalculé plus haut, statut a_planifier relu : un refus trahirait une
                # incohérence interne. On lève pour que l'appel atomique annule tout ce qui a été écrit.
                raise RuntimeError(f"sortie de a_planifier refusée après un contrôle valide : {verdict['code']}")
            transition = TRANSITION_SORTIE_A_PLANIFIER
        if etats.technicien_assigne(instantane, chantier) == equipe:
            effet = EFFET_DEJA_ASSIGNEE
        else:
            _, verdict = etats.assigner_technicien(chantier, equipe, registre_cible, horodatage_arg)
            if verdict is not None:
                # Contrôlé plus haut (statut, technicien non vide) : un refus trahirait une incohérence
                # interne. On lève pour que l'appel atomique annule les assignations déjà écrites.
                raise RuntimeError(f"assignation refusée après un contrôle valide : {verdict['code']}")
            effet = EFFET_ASSIGNEE
        assignations.append({
            "intervention_id": chantier, "technicien_id": equipe, "effet": effet, "transition": transition,
        })
    conservees = {ligne["intervention_id"]: ligne["technicien_assigne"] for ligne in avant}
    marqueur = {
        "type_entree": TYPE_APPLIQUEE,
        "horodatage": horodatage_arg,
        "plan_id": plan_id,
        "appliquee_par": appliquee_par,
        "empreinte_entree": proposee["empreinte_entree"],
        "empreinte_sortie": proposee["empreinte_sortie"],
        "assignations": assignations,
        "non_cedulees": [
            {"chantier": ligne["chantier"], "technicien_assigne": conservees[ligne["chantier"]]}
            for ligne in sortie["non_cedulees"]
        ],
    }
    registre_cible.ajouter(marqueur)
    return _resultat_application(marqueur, proposee, False), None
