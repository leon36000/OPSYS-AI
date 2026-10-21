"""Solveur de tournées et validateur de plan (PLAN T4.1-c, R15 §1 et §4).

Le solveur PROPOSE ; il n'écrit pas la vérité. ``resoudre(entree)`` reçoit des équipes, des chantiers et
la matrice FIGÉE de T4.1-b (``distances.obtenir_matrice``), et rend un plan canonique : entiers seulement,
triés, hachés. Le plan n'est jamais cru sur parole : ``verifier_plan`` le contrôle sans rien reprendre du
solveur, et ``resoudre`` refuse de rendre un plan qui échoue à ce contrôle.

Deux moteurs derrière la même interface (``moteur`` : ``"auto"``, ``"pyvrp"`` ou ``"dp"``) :

    * PyVRP 0.14.0 (MIT), import PARESSEUX, extra ``tournees`` de ``pyproject.toml``. ``MaxIterations``
      seulement : jamais de limite de temps (elle lirait l'horloge). Graine DÉRIVÉE de l'empreinte de
      l'entrée. Compétences et jours permis par profils de matrice : un profil par ensemble de chantiers
      admissibles, arêtes interdites vers les autres (le « vehicle-client compatibility » natif est réservé
      à PyVRP Enterprise, R15 §1).
    * Programmation dynamique EXACTE, bibliothèque standard : repli sans dépendance jusqu'à
      ``MAX_CHANTIERS_DP`` chantiers, et oracle des tests (écart 0 exigé de PyVRP sur les petites
      instances).

Sans PyVRP (absent, ou version autre que l'épinglée) : le DP si le nombre de chantiers entrés au solveur
est au plus ``MAX_CHANTIERS_DP``, sinon un verdict « solveur de tournées non installé : installer l'extra
tournees ».

Modèle (tout est entier ; les temps sont des minutes depuis minuit, les distances des mètres)
    * Un véhicule est un couple (équipe, jour) : un quart ``[debut_min, fin_min]``, un dépôt de départ et de
      retour. Le temps de trajet est le plafond en minutes de ``secondes`` de la matrice (marge incluse) :
      on ne sous-estime jamais un trajet.
    * La fenêtre du client dit les JOURS permis et l'intervalle de la journée où le chantier doit être
      ENTIÈREMENT réalisé : début >= ``debut_min`` et début + durée <= ``fin_min``.
    * Une équipe ne reçoit un chantier que si elle possède TOUTES ses compétences requises.
    * Un créneau figé (déjà confirmé au client) fixe équipe, jour et heure de début : il est tenu, ou
      l'entrée est refusée. Il n'est jamais déplacé par le solveur.
    * Objectif : mètres parcourus (dépôt, chantiers, dépôt) + coût de non-cédule de chaque chantier laissé de
      côté, soit ``cout_non_cedule_m`` x (1 + urgence). L'urgence rend un chantier plus coûteux à laisser.

Fail-closed : la durée, la fenêtre, les compétences, le dépôt, les quarts, la graine, les itérations et le
coût de non-cédule sont des ENTRÉES. Absents, ils donnent un verdict qui dit tout ce qu'il faut fournir,
jamais une valeur par défaut. Un chantier sans coordonnées confirmées (absent de la matrice) n'entre pas au
solveur : il sort en ``non_cedulees`` avec « coordonnées manquantes : à confirmer ». Les raisons de
non-cédule sont calculées ICI, après la résolution (``_diagnostiquer``), jamais reprises du solveur.

Déterminisme : entrées triées par identifiant, entiers, aucune horloge, aucun ``random``, aucun flottant
(gardes par analyse du code dans ``tests/test_tournees.py``). Même entrée, mêmes octets, quel que soit
``PYTHONHASHSEED``. Les coordonnées et les adresses ne figurent jamais dans un verdict ni dans un plan :
seuls des identifiants opaques.
"""

from __future__ import annotations

from importlib import import_module, metadata

from . import distances, encodage, verdicts

# ---------------------------------------------------------------------------
# Constantes publiques
# ---------------------------------------------------------------------------
VERSION_ENTREE = "tournees-entree-v1"
VERSION_SORTIE = "tournees-sortie-v1"

SOLVEUR_PYVRP = "pyvrp"
VERSION_PYVRP = "0.14.0"  # épinglée : l'API de PyVRP bouge d'une version à l'autre (R15 §1)
SOLVEUR_DP = "dp-exact"
VERSION_DP = "dp-exact-v1"
MAX_CHANTIERS_DP = 12
MOTEURS = ("auto", "pyvrp", "dp")

MINUTES_PAR_JOUR = 1440
BORNE_JOUR = (0, 9999)
BORNE_URGENCE = (0, 3)
BORNE_GRAINE = (0, 2**32 - 1)
BORNE_ITERATIONS = (1, 100_000)
BORNE_COUT_NON_CEDULE_M = (1, 10**9)

# Verdicts propres aux tournées, inscrits au catalogue de ``verdicts.py`` par T4.1-d (un test le
# vérifie). Même forme que ``verdicts.construire_verdict``.
CODE_SOLVEUR_ABSENT = "REJ-TOURNEES-SOLVEUR-ABSENT"
CODE_TAILLE_DP = "REJ-TOURNEES-DP-TROP-GRAND"
CODE_CRENEAU_FIGE = "REJ-TOURNEES-CRENEAU-FIGE-INCOMPATIBLE"
CODE_SOLVEUR_ECHEC = "REJ-TOURNEES-SOLVEUR-ECHEC"
CODE_PLAN_INVALIDE = "REJ-TOURNEES-PLAN-INVALIDE"
CODES_TOURNEES = (
    CODE_SOLVEUR_ABSENT, CODE_TAILLE_DP, CODE_CRENEAU_FIGE, CODE_SOLVEUR_ECHEC, CODE_PLAN_INVALIDE,
)

# Raisons de non-cédule (calculées par ce module).
RAISON_COORDONNEES = "coordonnees_manquantes"
RAISON_COMPETENCE = "competence_indisponible"
RAISON_DUREE = "duree_trop_longue"
RAISON_FENETRE = "fenetre_inatteignable"
RAISON_JOURNEES_PLEINES = "journees_pleines"
RAISON_COUT = "cout_superieur_au_cout_non_cedule"
RAISON_INSERTION = "insertion_possible_non_retenue"
RAISONS_NON_CEDULE = (
    RAISON_COORDONNEES, RAISON_COMPETENCE, RAISON_DUREE, RAISON_FENETRE,
    RAISON_JOURNEES_PLEINES, RAISON_COUT, RAISON_INSERTION,
)

TEXTE_SOLVEUR_ABSENT = "solveur de tournées non installé : installer l'extra tournees"

__all__ = [
    "VERSION_ENTREE",
    "VERSION_SORTIE",
    "SOLVEUR_PYVRP",
    "VERSION_PYVRP",
    "SOLVEUR_DP",
    "VERSION_DP",
    "MAX_CHANTIERS_DP",
    "MOTEURS",
    "CODE_SOLVEUR_ABSENT",
    "CODE_TAILLE_DP",
    "CODE_CRENEAU_FIGE",
    "CODE_SOLVEUR_ECHEC",
    "CODE_PLAN_INVALIDE",
    "CODES_TOURNEES",
    "RAISONS_NON_CEDULE",
    "TEXTE_SOLVEUR_ABSENT",
    "verdict_tournees",
    "pyvrp_installe",
    "empreinte_entree",
    "resoudre",
    "verifier_plan",
]

_CLES_ENTREE = ("version", "equipes", "chantiers", "matrice", "parametres")
_CLES_EQUIPE = ("id", "competences", "depot", "quarts")
_CLES_QUART = ("jour", "debut_min", "fin_min")
_CLES_CHANTIER = ("id", "duree_min", "fenetre", "competences_requises", "urgence", "creneau_fige")
_CLES_FENETRE = ("jours", "debut_min", "fin_min")
_CLES_FIGE = ("equipe", "jour", "debut_min")
_CLES_PARAMETRES = ("graine", "iterations", "cout_non_cedule_m")
_CLES_SORTIE = ("version", "plan", "non_cedulees", "totaux", "meta")
_CLES_ROUTE = ("equipe", "jour", "depot", "depart_min", "retour_min", "distance_m", "visites")
_CLES_VISITE = ("chantier", "arrivee_min", "debut_min", "fin_min")
_CLES_NON_CEDULEE = ("chantier", "code", "raison", "action")
_CLES_TOTAUX = ("distance_m", "cout_non_cedule_m", "cout_total_m", "chantiers_cedules", "chantiers_non_cedules")
_CLES_META = (
    "solveur", "version_solveur", "graine", "iterations", "empreinte_entree", "empreinte_sortie",
    "mode_distance", "mode_bride", "empreinte_matrice",
)

_AIDE = {
    "version": f"{VERSION_ENTREE!r}",
    "equipes": "liste des équipes (id, competences, depot, quarts)",
    "chantiers": "liste des chantiers (id, duree_min, fenetre, competences_requises, urgence, creneau_fige)",
    "matrice": "matrice de trajets fournie par distances.obtenir_matrice",
    "parametres": "graine, iterations, cout_non_cedule_m",
    "id": "identifiant non vide",
    "competences": "compétences de l'équipe, liste vide s'il n'y en a aucune",
    "depot": "identifiant du point de départ et de retour de l'équipe dans la matrice",
    "quarts": "quarts de l'équipe (jour, debut_min, fin_min), au moins un",
    "jour": "numéro de jour entier",
    "debut_min": "minutes depuis minuit, entier",
    "fin_min": "minutes depuis minuit, entier",
    "duree_min": "durée du chantier en minutes entières, selon le type de travaux (à fournir par l'entreprise)",
    "fenetre": "fenêtre du client (jours, debut_min, fin_min)",
    "jours": "jours permis par le client, liste d'entiers non vide",
    "competences_requises": "compétences requises par le chantier, liste vide s'il n'y en a aucune",
    "urgence": f"entier de {BORNE_URGENCE[0]} (normale) à {BORNE_URGENCE[1]}",
    "creneau_fige": "null, ou {equipe, jour, debut_min} si le créneau est déjà confirmé au client",
    "equipe": "identifiant de l'équipe",
    "graine": f"entier de {BORNE_GRAINE[0]} à {BORNE_GRAINE[1]}",
    "iterations": f"nombre d'itérations du solveur, entier de {BORNE_ITERATIONS[0]} à {BORNE_ITERATIONS[1]}",
    "cout_non_cedule_m": "coût, en mètres équivalents, d'un chantier laissé de côté (multiplié par 1 + urgence)",
}

_MAX_PROBLEMES = 20


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------
def verdict_tournees(code, detail=""):
    """Verdict propre aux tournées (code de ``CODES_TOURNEES``), même forme que les verdicts M4."""
    if code not in CODES_TOURNEES:
        raise verdicts.CodeVerdictInconnu(f"Code verdict de tournées invalide : {code!r}")
    return {"code": code, "statut": "", "detail": detail}


def _rejet(code, detail):
    return verdicts.construire_verdict(code, detail=detail)


def _est_entier(valeur):
    """Entier Python strict : ni booléen, ni flottant."""
    return type(valeur) is int


def _minutes_plafond(secondes):
    """Plafond en minutes entières (on ne sous-estime jamais un trajet)."""
    return -(-secondes // 60)


# ---------------------------------------------------------------------------
# Lecture et validation de l'entrée
# ---------------------------------------------------------------------------
class _Collecte:
    """Problèmes d'entrée, rapportés TOUS ensemble : le verdict dit tout ce qu'il faut fournir."""

    def __init__(self):
        self.absents = []
        self.vides = []
        self.invalides = []

    def verdict(self):
        tous = self.absents + self.vides + self.invalides
        if not tous:
            return None
        detail = " ; ".join(tous[:_MAX_PROBLEMES])
        if len(tous) > _MAX_PROBLEMES:
            detail += f" ; … et {len(tous) - _MAX_PROBLEMES} autres"
        if self.absents:
            return _rejet("REJ-CHAMP-MANQUANT", detail)
        if self.vides:
            return _rejet("REJ-CHAMP-VIDE", detail)
        return _rejet("REJ-CONTRAT-INVALIDE", detail)


def _nom(section, indice, objet):
    identifiant = objet.get("id") if isinstance(objet, dict) else None
    if isinstance(identifiant, str) and identifiant:
        return f"{section}[{indice}] {identifiant!r}"
    return f"{section}[{indice}]"


def _objet(valeur, chemin, cles, collecte, nullables=()):
    """L'objet si toutes ses clés sont là (sinon None) ; clés absentes et inconnues rapportées."""
    if not isinstance(valeur, dict):
        collecte.invalides.append(f"{chemin} : un objet est attendu ({', '.join(cles)})")
        return None
    manquantes = [cle for cle in cles if cle not in valeur or (valeur[cle] is None and cle not in nullables)]
    for cle in manquantes:
        collecte.absents.append(f"{chemin}.{cle} manquant : {_AIDE[cle]}")
    en_trop = sorted(str(cle) for cle in valeur if cle not in cles)
    if en_trop:
        collecte.invalides.append(f"{chemin} : clés inconnues : {', '.join(en_trop)}")
    return None if manquantes else valeur


def _entier(valeur, chemin, borne, collecte):
    minimum, maximum = borne
    if not _est_entier(valeur):
        collecte.invalides.append(f"{chemin} : entier requis, type reçu {type(valeur).__name__}")
        return None
    if not minimum <= valeur <= maximum:
        collecte.invalides.append(f"{chemin} : {valeur} hors bornes, attendu entre {minimum} et {maximum}")
        return None
    return valeur


def _texte(valeur, chemin, collecte):
    if not isinstance(valeur, str) or not valeur:
        collecte.invalides.append(f"{chemin} : chaîne non vide requise")
        return None
    return valeur


def _liste_textes(valeur, chemin, collecte):
    """Liste triée sans doublon de chaînes non vides (peut être vide), ou None."""
    if not isinstance(valeur, list):
        collecte.invalides.append(f"{chemin} : une liste est attendue")
        return None
    if not all(isinstance(element, str) and element for element in valeur):
        collecte.invalides.append(f"{chemin} : chaînes non vides attendues")
        return None
    return sorted(set(valeur))


def _lire_quarts(brut, nom, collecte):
    chemin = f"{nom}.quarts"
    if not isinstance(brut, list):
        collecte.invalides.append(f"{chemin} : une liste est attendue")
        return None
    if not brut:
        collecte.absents.append(f"{chemin} manquants : {_AIDE['quarts']}")
        return None
    quarts = {}
    bon = True
    for position, quart in enumerate(brut):
        chemin_quart = f"{chemin}[{position}]"
        objet = _objet(quart, chemin_quart, _CLES_QUART, collecte)
        if objet is None:
            bon = False
            continue
        jour = _entier(objet["jour"], f"{chemin_quart}.jour", BORNE_JOUR, collecte)
        debut = _entier(objet["debut_min"], f"{chemin_quart}.debut_min", (0, MINUTES_PAR_JOUR - 1), collecte)
        fin = _entier(objet["fin_min"], f"{chemin_quart}.fin_min", (1, MINUTES_PAR_JOUR), collecte)
        if jour is None or debut is None or fin is None:
            bon = False
        elif debut >= fin:
            collecte.invalides.append(f"{chemin_quart} : debut_min doit précéder fin_min")
            bon = False
        elif jour in quarts:
            collecte.invalides.append(f"{chemin_quart} : deux quarts le jour {jour}")
            bon = False
        else:
            quarts[jour] = (debut, fin)
    if not bon:
        return None
    return [{"jour": jour, "debut_min": d, "fin_min": f} for jour, (d, f) in sorted(quarts.items())]


def _lire_equipes(brut, collecte):
    if not isinstance(brut, list):
        collecte.invalides.append("equipes : une liste est attendue")
        return []
    if not brut:
        collecte.absents.append(f"equipes manquantes : fournir au moins une équipe, {_AIDE['equipes']}")
        return []
    equipes = []
    vus = set()
    for position, equipe in enumerate(brut):
        nom = _nom("equipes", position, equipe)
        objet = _objet(equipe, nom, _CLES_EQUIPE, collecte)
        if objet is None:
            continue
        identifiant = _texte(objet["id"], f"{nom}.id", collecte)
        if identifiant is not None:
            if identifiant in vus:
                collecte.invalides.append(f"{nom} : identifiant d'équipe en double")
                identifiant = None
            else:
                vus.add(identifiant)
        competences = _liste_textes(objet["competences"], f"{nom}.competences", collecte)
        depot = _texte(objet["depot"], f"{nom}.depot", collecte)
        quarts = _lire_quarts(objet["quarts"], nom, collecte)
        if identifiant is not None and competences is not None and depot is not None and quarts is not None:
            equipes.append({"id": identifiant, "competences": competences, "depot": depot, "quarts": quarts})
    return sorted(equipes, key=lambda e: e["id"])


def _lire_fenetre(brut, nom, collecte):
    chemin = f"{nom}.fenetre"
    objet = _objet(brut, chemin, _CLES_FENETRE, collecte)
    if objet is None:
        return None
    jours_bruts = objet["jours"]
    jours = None
    if not isinstance(jours_bruts, list):
        collecte.invalides.append(f"{chemin}.jours : une liste est attendue")
    elif not jours_bruts:
        collecte.absents.append(f"{chemin}.jours manquants : {_AIDE['jours']}")
    else:
        lus = [_entier(jour, f"{chemin}.jours", BORNE_JOUR, collecte) for jour in jours_bruts]
        if None not in lus:
            jours = sorted(set(lus))
    debut = _entier(objet["debut_min"], f"{chemin}.debut_min", (0, MINUTES_PAR_JOUR - 1), collecte)
    fin = _entier(objet["fin_min"], f"{chemin}.fin_min", (1, MINUTES_PAR_JOUR), collecte)
    if jours is None or debut is None or fin is None:
        return None
    if debut >= fin:
        collecte.invalides.append(f"{chemin} : debut_min doit précéder fin_min")
        return None
    return {"jours": jours, "debut_min": debut, "fin_min": fin}


def _lire_fige(brut, nom, collecte):
    """``(True, None)`` : pas de créneau figé ; ``(True, dict)`` : figé ; ``(False, None)`` : invalide."""
    if brut is None:
        return True, None
    chemin = f"{nom}.creneau_fige"
    objet = _objet(brut, chemin, _CLES_FIGE, collecte)
    if objet is None:
        return False, None
    equipe = _texte(objet["equipe"], f"{chemin}.equipe", collecte)
    jour = _entier(objet["jour"], f"{chemin}.jour", BORNE_JOUR, collecte)
    debut = _entier(objet["debut_min"], f"{chemin}.debut_min", (0, MINUTES_PAR_JOUR - 1), collecte)
    if equipe is None or jour is None or debut is None:
        return False, None
    return True, {"equipe": equipe, "jour": jour, "debut_min": debut}


def _lire_chantiers(brut, collecte):
    if not isinstance(brut, list):
        collecte.invalides.append("chantiers : une liste est attendue")
        return []
    if not brut:
        collecte.vides.append(f"chantiers : aucun chantier à céduler, fournir au moins un, {_AIDE['chantiers']}")
        return []
    chantiers = []
    vus = set()
    for position, chantier in enumerate(brut):
        nom = _nom("chantiers", position, chantier)
        objet = _objet(chantier, nom, _CLES_CHANTIER, collecte, nullables=("creneau_fige",))
        if objet is None:
            continue
        identifiant = _texte(objet["id"], f"{nom}.id", collecte)
        if identifiant is not None:
            if identifiant in vus:
                collecte.invalides.append(f"{nom} : identifiant de chantier en double")
                identifiant = None
            else:
                vus.add(identifiant)
        duree = _entier(objet["duree_min"], f"{nom}.duree_min", (1, MINUTES_PAR_JOUR), collecte)
        fenetre = _lire_fenetre(objet["fenetre"], nom, collecte)
        competences = _liste_textes(objet["competences_requises"], f"{nom}.competences_requises", collecte)
        urgence = _entier(objet["urgence"], f"{nom}.urgence", BORNE_URGENCE, collecte)
        fige_valide, fige = _lire_fige(objet["creneau_fige"], nom, collecte)
        if (
            identifiant is not None and duree is not None and fenetre is not None
            and competences is not None and urgence is not None and fige_valide
        ):
            chantiers.append({
                "id": identifiant, "duree_min": duree, "fenetre": fenetre,
                "competences_requises": competences, "urgence": urgence, "creneau_fige": fige,
            })
    return sorted(chantiers, key=lambda c: c["id"])


def _lire_parametres(brut, collecte):
    objet = _objet(brut, "parametres", _CLES_PARAMETRES, collecte)
    if objet is None:
        return None
    graine = _entier(objet["graine"], "parametres.graine", BORNE_GRAINE, collecte)
    iterations = _entier(objet["iterations"], "parametres.iterations", BORNE_ITERATIONS, collecte)
    cout = _entier(objet["cout_non_cedule_m"], "parametres.cout_non_cedule_m", BORNE_COUT_NON_CEDULE_M, collecte)
    if graine is None or iterations is None or cout is None:
        return None
    return {"graine": graine, "iterations": iterations, "cout_non_cedule_m": cout}


def _preparer(entree):
    """Valide l'entrée et construit le problème. Retourne (problème, None) ou (None, verdict)."""
    collecte = _Collecte()
    racine = _objet(entree, "entrée", _CLES_ENTREE, collecte)
    if racine is None:
        return None, collecte.verdict()
    if racine["version"] != VERSION_ENTREE:
        collecte.invalides.append(f"version : {VERSION_ENTREE!r} attendue")
    matrice = racine["matrice"]
    matrice_ok, message = distances.verifier_matrice(matrice)
    if not matrice_ok:
        collecte.invalides.append(message)
    equipes = _lire_equipes(racine["equipes"], collecte)
    chantiers = _lire_chantiers(racine["chantiers"], collecte)
    parametres = _lire_parametres(racine["parametres"], collecte)
    verdict = collecte.verdict()
    if verdict is not None:
        return None, verdict
    return _construire_probleme(equipes, chantiers, parametres, matrice)


def _construire_probleme(equipes, chantiers, parametres, matrice):
    indice = {identifiant: position for position, identifiant in enumerate(matrice["ids"])}
    collecte = _Collecte()
    identifiants_depots = {equipe["depot"] for equipe in equipes}
    for equipe in equipes:
        if equipe["depot"] not in indice:
            collecte.invalides.append(
                f"équipe {equipe['id']!r} : dépôt {equipe['depot']!r} absent de la matrice, "
                "ajouter son point à la matrice",
            )
    for chantier in chantiers:
        if chantier["id"] in identifiants_depots:
            collecte.invalides.append(f"chantier {chantier['id']!r} : identifiant déjà utilisé par un dépôt")
    verdict = collecte.verdict()
    if verdict is not None:
        return None, verdict

    entree = {
        "version": VERSION_ENTREE,
        "equipes": equipes,
        "chantiers": chantiers,
        "matrice": matrice["empreinte"],
        "parametres": parametres,
    }
    problem = {
        "entree": entree,
        "empreinte_entree": encodage.empreinte(entree),
        "matrice": matrice,
        "indice": indice,
        "metres": matrice["metres"],
        "trajet": [[_minutes_plafond(s) for s in ligne] for ligne in matrice["secondes"]],
        "parametres": parametres,
    }
    problem["vehicules"] = _vehicules(equipes, indice)
    problem["chantiers"] = {c["id"]: _chantier_interne(c, indice, parametres) for c in chantiers}
    problem["ids"] = [c["id"] for c in chantiers]
    verdict = _verifier_figes(problem)
    if verdict is not None:
        return None, verdict
    problem["admissibles"] = {
        cid: _admissibles(problem, problem["chantiers"][cid]) for cid in problem["ids"]
    }
    return problem, None


def _vehicules(equipes, indice):
    """Un véhicule par (équipe, jour), triés par (équipe, jour) : c'est l'ordre canonique du plan."""
    vehicules = []
    for equipe in equipes:
        for quart in equipe["quarts"]:
            vehicules.append({
                "equipe": equipe["id"],
                "jour": quart["jour"],
                "depot_id": equipe["depot"],
                "depot": indice[equipe["depot"]],
                "debut": quart["debut_min"],
                "fin": quart["fin_min"],
                "competences": frozenset(equipe["competences"]),
            })
    return vehicules


def _chantier_interne(chantier, indice, parametres):
    fenetre = chantier["fenetre"]
    fige = chantier["creneau_fige"]
    debut_max = fenetre["fin_min"] - chantier["duree_min"]
    return {
        "id": chantier["id"],
        "idx": indice.get(chantier["id"]),
        "duree": chantier["duree_min"],
        "debut_fen": fenetre["debut_min"],
        "debut_max": debut_max,
        "jours": frozenset(fenetre["jours"]),
        "competences": frozenset(chantier["competences_requises"]),
        "urgence": chantier["urgence"],
        "cout": parametres["cout_non_cedule_m"] * (1 + chantier["urgence"]),
        "fige": None if fige is None else (fige["equipe"], fige["jour"], fige["debut_min"]),
        # Fenêtre de début effective : celle du client, ou le seul instant du créneau figé.
        "debut_eff": fenetre["debut_min"] if fige is None else fige["debut_min"],
        "debut_max_eff": debut_max if fige is None else fige["debut_min"],
    }


def _indice_vehicule(problem, equipe, jour):
    for position, vehicule in enumerate(problem["vehicules"]):
        if vehicule["equipe"] == equipe and vehicule["jour"] == jour:
            return position
    return None


def _seul_faisable(problem, k, chantier):
    """Vrai si le chantier tient seul dans le quart du véhicule k (aller, fenêtre, service, retour)."""
    vehicule = problem["vehicules"][k]
    trajet = problem["trajet"]
    idx = chantier["idx"]
    debut = max(chantier["debut_eff"], vehicule["debut"] + trajet[vehicule["depot"]][idx])
    return (
        debut <= chantier["debut_max_eff"]
        and debut + chantier["duree"] + trajet[idx][vehicule["depot"]] <= vehicule["fin"]
    )


def _admissibles(problem, chantier):
    """Véhicules (indices triés) auxquels le chantier peut être confié : compétences, jour, quart."""
    if chantier["idx"] is None:
        return []
    if chantier["fige"] is not None:
        k = _indice_vehicule(problem, chantier["fige"][0], chantier["fige"][1])
        return [k] if k is not None and _seul_faisable(problem, k, chantier) else []
    return [
        k for k, vehicule in enumerate(problem["vehicules"])
        if chantier["competences"] <= vehicule["competences"]
        and vehicule["jour"] in chantier["jours"]
        and _seul_faisable(problem, k, chantier)
    ]


def _refus_fige(problem, chantier):
    """Message si le créneau figé du chantier est intenable seul, sinon None."""
    equipe, jour, debut = chantier["fige"]
    cid = chantier["id"]
    k = _indice_vehicule(problem, equipe, jour)
    if k is None:
        return f"chantier {cid!r} : l'équipe {equipe!r} n'a pas de quart le jour {jour}"
    vehicule = problem["vehicules"][k]
    if not chantier["competences"] <= vehicule["competences"]:
        return f"chantier {cid!r} : l'équipe {equipe!r} n'a pas toutes les compétences requises"
    if jour not in chantier["jours"]:
        return f"chantier {cid!r} : le jour {jour} n'est pas permis par la fenêtre du client"
    if not chantier["debut_fen"] <= debut <= chantier["debut_max"]:
        return f"chantier {cid!r} : le créneau figé ({debut} min) sort de la fenêtre du client"
    if not _seul_faisable(problem, k, chantier):
        return f"chantier {cid!r} : le créneau figé ne tient pas dans le quart de {equipe!r} (trajets compris)"
    return None


def _verifier_figes(problem):
    """Refuse l'entrée si un créneau figé est intenable seul ou en compagnie des autres figés du même quart."""
    par_vehicule = {}
    for cid in problem["ids"]:
        chantier = problem["chantiers"][cid]
        if chantier["fige"] is None:
            continue
        if chantier["idx"] is None:
            return _rejet(
                "REJ-CHAMP-MANQUANT",
                f"chantier {cid!r} : créneau figé sans coordonnées confirmées, "
                "confirmer la localisation avant de céduler (un créneau promis au client ne se perd pas)",
            )
        refus = _refus_fige(problem, chantier)
        if refus is not None:
            return verdict_tournees(CODE_CRENEAU_FIGE, refus)
        k = _indice_vehicule(problem, chantier["fige"][0], chantier["fige"][1])
        par_vehicule.setdefault(k, []).append(chantier)
    for k in sorted(par_vehicule):
        ordre = [c["id"] for c in sorted(par_vehicule[k], key=lambda c: (c["fige"][2], c["id"]))]
        if _planifier(problem, k, ordre) is None:
            vehicule = problem["vehicules"][k]
            return verdict_tournees(
                CODE_CRENEAU_FIGE,
                f"les créneaux figés {', '.join(repr(cid) for cid in ordre)} sont incompatibles entre eux "
                f"(équipe {vehicule['equipe']!r}, jour {vehicule['jour']})",
            )
    return None


# ---------------------------------------------------------------------------
# Horaire d'une route (plus tôt possible), partagé par le DP, l'assemblage et le diagnostic
# ---------------------------------------------------------------------------
def _planifier(problem, k, ordre):
    """Horaire au plus tôt de l'ordre donné pour le véhicule k, ou None s'il viole une contrainte de temps.

    Retourne ``{"depart", "retour", "metres", "visites": [(id, arrivee, debut, fin)]}``. Le départ du
    dépôt est différé au plus tard qui garde le premier début : la première visite n'attend donc jamais.
    Ne contrôle ni les compétences ni les jours (l'admissibilité les garantit avant).
    """
    vehicule = problem["vehicules"][k]
    chantiers = problem["chantiers"]
    trajet = problem["trajet"]
    metres = problem["metres"]
    depot = vehicule["depot"]
    position = depot
    libre = vehicule["debut"]
    total = 0
    visites = []
    for cid in ordre:
        chantier = chantiers[cid]
        idx = chantier["idx"]
        arrivee = libre + trajet[position][idx]
        debut = max(arrivee, chantier["debut_eff"])
        if debut > chantier["debut_max_eff"]:
            return None
        fin = debut + chantier["duree"]
        visites.append((cid, arrivee, debut, fin))
        total += metres[position][idx]
        position = idx
        libre = fin
    retour = libre + trajet[position][depot]
    if retour > vehicule["fin"]:
        return None
    total += metres[position][depot]
    depart = vehicule["debut"]
    if visites:
        cid, _arrivee, debut, fin = visites[0]
        depart = debut - trajet[depot][chantiers[cid]["idx"]]
        visites[0] = (cid, debut, debut, fin)
    return {"depart": depart, "retour": retour, "metres": total, "visites": visites}


# ---------------------------------------------------------------------------
# Moteur exact : programmation dynamique
# ---------------------------------------------------------------------------
def _inserer_pareto(liste, nouveau):
    """Insère (temps, coût, ordre) dans la liste des états non dominés ; à égalité, l'ordre le plus petit."""
    temps, cout, ordre = nouveau
    for existant in liste:
        if existant[0] <= temps and existant[1] <= cout and (existant[:2] != (temps, cout) or existant[2] <= ordre):
            return
    liste[:] = [
        e for e in liste if not (temps <= e[0] and cout <= e[1])
    ]
    liste.append(nouveau)
    liste.sort()


def _routes_du_vehicule(problem, k, candidats, bit):
    """Meilleure route (coût, ordre) pour CHAQUE sous-ensemble faisable de ``candidats`` (masque de bits).

    Les états sont (sous-ensemble visité, dernier chantier) avec la frontière de Pareto (heure de fin,
    mètres) : arriver plus tôt et plus court n'est jamais pire, puisque l'attente est permise.
    """
    vehicule = problem["vehicules"][k]
    chantiers = problem["chantiers"]
    trajet = problem["trajet"]
    metres = problem["metres"]
    depot = vehicule["depot"]
    fin_quart = vehicule["fin"]
    meilleur = {0: (0, ())}
    etats = {}
    for cid in candidats:
        chantier = chantiers[cid]
        idx = chantier["idx"]
        debut = max(chantier["debut_eff"], vehicule["debut"] + trajet[depot][idx])
        if debut > chantier["debut_max_eff"]:
            continue
        fin = debut + chantier["duree"]
        if fin + trajet[idx][depot] > fin_quart:
            continue
        etats[(1 << bit[cid], cid)] = [(fin, metres[depot][idx], (cid,))]
    while etats:
        for (masque, dernier), entrees in etats.items():
            retour = metres[chantiers[dernier]["idx"]][depot]
            for _temps, cout, ordre in entrees:
                candidat = (cout + retour, ordre)
                actuel = meilleur.get(masque)
                if actuel is None or candidat < actuel:
                    meilleur[masque] = candidat
        suivants = {}
        for (masque, dernier), entrees in etats.items():
            idx_dernier = chantiers[dernier]["idx"]
            for cid in candidats:
                drapeau = 1 << bit[cid]
                if masque & drapeau:
                    continue
                chantier = chantiers[cid]
                idx = chantier["idx"]
                for temps, cout, ordre in entrees:
                    debut = max(chantier["debut_eff"], temps + trajet[idx_dernier][idx])
                    if debut > chantier["debut_max_eff"]:
                        continue
                    fin = debut + chantier["duree"]
                    if fin + trajet[idx][depot] > fin_quart:
                        continue
                    nouveau = (fin, cout + metres[idx_dernier][idx], ordre + (cid,))
                    _inserer_pareto(suivants.setdefault((masque | drapeau, cid), []), nouveau)
        etats = suivants
    return meilleur


def _resoudre_dp(problem, solveur_ids):
    """Optimum exact : ``{k: [ordre]}`` des routes non vides. Les identifiants sont ceux entrés au solveur."""
    bit = {cid: position for position, cid in enumerate(solveur_ids)}
    n = len(solveur_ids)
    admissibles = problem["admissibles"]
    actifs = [
        k for k in range(len(problem["vehicules"])) if any(k in admissibles[cid] for cid in solveur_ids)
    ]
    routes = {}
    figes = {}
    for k in actifs:
        candidats = [cid for cid in solveur_ids if k in admissibles[cid]]
        routes[k] = _routes_du_vehicule(problem, k, candidats, bit)
        figes[k] = sum(1 << bit[cid] for cid in candidats if problem["chantiers"][cid]["fige"] is not None)

    # Couches : un véhicule à la fois. Pour chaque route possible (``sous``), on n'énumère que les sous-ensembles
    # du complément déjà atteints (2^(n - |sous|) au lieu de tous les états). À coût égal, le plus petit
    # (masque, sous) l'emporte : le résultat ne dépend pas de l'ordre d'énumération.
    tout = (1 << n) - 1
    couches = []
    courant = {0: (0, None, None)}
    for k in actifs:
        objets = sorted(routes[k].items())
        if figes[k]:
            objets = [(masque, valeur) for masque, valeur in objets if masque & figes[k] == figes[k]]
        suivant = {}
        for sous, (cout, _ordre) in objets:
            libre = tout & ~sous
            masque = libre
            while True:
                precedent = courant.get(masque)
                if precedent is not None:
                    candidat = (precedent[0] + cout, masque, sous)
                    fusion = masque | sous
                    actuel = suivant.get(fusion)
                    if actuel is None or candidat < actuel:
                        suivant[fusion] = candidat
                if masque == 0:
                    break
                masque = (masque - 1) & libre
        couches.append(suivant)
        courant = suivant
    if not courant:
        return None

    cout_masque = [0] * (1 << n)
    for masque in range(1, 1 << n):
        bas = masque & -masque
        cid = solveur_ids[bas.bit_length() - 1]
        cout_masque[masque] = cout_masque[masque ^ bas] + problem["chantiers"][cid]["cout"]
    total_non_cedule = cout_masque[(1 << n) - 1]
    meilleur_masque = min(courant, key=lambda m: (courant[m][0] + total_non_cedule - cout_masque[m], m))

    resultat = {}
    masque = meilleur_masque
    for k, couche in zip(reversed(actifs), reversed(couches), strict=True):
        _cout, precedent, sous = couche[masque]
        if sous:
            resultat[k] = list(routes[k][sous][1])
        masque = precedent
    return resultat


# ---------------------------------------------------------------------------
# Moteur PyVRP (import paresseux)
# ---------------------------------------------------------------------------
def _version_pyvrp():
    """``(version, "")`` si PyVRP est installé à la version épinglée, sinon ``(None, raison)``."""
    try:
        version = metadata.version("pyvrp")
    except metadata.PackageNotFoundError:
        return None, "pyvrp absent"
    if version != VERSION_PYVRP:
        return None, f"pyvrp {version} trouvé, {VERSION_PYVRP} exigé"
    return version, ""


def pyvrp_installe():
    """``(True, version)`` si PyVRP est utilisable, sinon ``(False, raison)``. Jamais d'exception."""
    version, raison = _version_pyvrp()
    if version is None:
        return False, raison
    try:
        import_module("pyvrp")
    except ImportError:
        return False, "pyvrp installé mais non importable"
    return True, version


def _resoudre_pyvrp(problem, solveur_ids, graine, iterations):
    """Routes proposées par PyVRP : ``{k: [ordre]}``. Ne fait confiance à rien : l'appelant vérifie."""
    pyvrp = import_module("pyvrp")
    arret = import_module("pyvrp.stop")
    valeur_max = import_module("pyvrp.constants").MAX_VALUE
    chantiers = problem["chantiers"]
    admissibles = problem["admissibles"]
    metres = problem["metres"]
    trajet = problem["trajet"]
    ids = problem["matrice"]["ids"]
    actifs = [
        k for k in range(len(problem["vehicules"])) if any(k in admissibles[cid] for cid in solveur_ids)
    ]

    modele = pyvrp.Model()
    positions = sorted({problem["vehicules"][k]["depot"] for k in actifs} | {chantiers[c]["idx"] for c in solveur_ids})
    lieux = {p: modele.add_location(0, 0, name=ids[p]) for p in positions}
    depots = {}
    for p in sorted({problem["vehicules"][k]["depot"] for k in actifs}):
        depots[p] = modele.add_depot(lieux[p], name=ids[p])
    for a in positions:
        for b in positions:
            if a != b:
                modele.add_edge(lieux[a], lieux[b], metres[a][b], trajet[a][b])
    for cid in solveur_ids:
        chantier = chantiers[cid]
        fige = chantier["fige"] is not None
        modele.add_client(
            lieux[chantier["idx"]],
            service_duration=chantier["duree"],
            tw_early=chantier["debut_eff"],
            tw_late=chantier["debut_max_eff"],
            prize=0 if fige else chantier["cout"],
            required=fige,
            name=cid,
        )

    # Profil 0 : aucune restriction (le voisinage de PyVRP se calcule sur lui). Un profil de plus par
    # ensemble de chantiers interdits : arêtes vers ces chantiers à valeur maximale, donc retard infini.
    base = modele.add_profile(name="base")
    profils = {(): base}
    for k in actifs:
        interdits = tuple(cid for cid in solveur_ids if k not in admissibles[cid])
        if interdits not in profils:
            profil = modele.add_profile(name=f"restreint-{len(profils)}")
            for cid in interdits:
                destination = lieux[chantiers[cid]["idx"]]
                for a in positions:
                    if lieux[a] is not destination:
                        modele.add_edge(lieux[a], destination, valeur_max, valeur_max, profile=profil)
            profils[interdits] = profil
        vehicule = problem["vehicules"][k]
        modele.add_vehicle_type(
            1,
            start_depot=depots[vehicule["depot"]],
            end_depot=depots[vehicule["depot"]],
            tw_early=vehicule["debut"],
            tw_late=vehicule["fin"],
            profile=profils[interdits],
            name=f"{vehicule['equipe']}|{vehicule['jour']}",
        )

    resultat = modele.solve(arret.MaxIterations(iterations), seed=graine, collect_stats=False, display=False)
    routes = {}
    for route in resultat.best.routes():
        ordre = [solveur_ids[activite.idx] for activite in route.schedule() if activite.is_client()]
        if ordre:
            routes[actifs[route.vehicle_type()]] = ordre
    return routes


# ---------------------------------------------------------------------------
# Diagnostic des chantiers non cédulés (notre code, après la résolution)
# ---------------------------------------------------------------------------
def _raison(code, raison, action):
    return {"code": code, "raison": raison, "action": action}


def _raison_statique(problem, chantier):
    """Pourquoi aucun quart ne peut accueillir ce chantier, même vide (jamais None)."""
    if chantier["idx"] is None:
        return _raison(
            RAISON_COORDONNEES,
            "coordonnées manquantes : à confirmer",
            "confirmer la localisation du chantier, puis relancer la cédule",
        )
    vehicules = problem["vehicules"]
    competents = [k for k, v in enumerate(vehicules) if chantier["competences"] <= v["competences"]]
    if not competents:
        return _raison(
            RAISON_COMPETENCE,
            "aucune équipe ne possède toutes les compétences requises : " + ", ".join(sorted(chantier["competences"])),
            "ajouter la compétence à une équipe, ou corriger les compétences requises du chantier",
        )
    largeur = chantier["debut_max"] + chantier["duree"] - chantier["debut_fen"]
    if chantier["duree"] > largeur:
        return _raison(
            RAISON_DUREE,
            f"durée de {chantier['duree']} min plus longue que la fenêtre du client ({largeur} min)",
            "élargir la fenêtre du client, ou corriger la durée du chantier",
        )
    permis = [k for k in competents if vehicules[k]["jour"] in chantier["jours"]]
    if not permis:
        return _raison(
            RAISON_FENETRE,
            "aucune équipe compétente n'a de quart un des jours permis par le client",
            "ajouter un quart à une équipe compétente un jour permis, ou élargir les jours du client",
        )
    plus_long = max(vehicules[k]["fin"] - vehicules[k]["debut"] for k in permis)
    if chantier["duree"] > plus_long:
        return _raison(
            RAISON_DUREE,
            f"durée de {chantier['duree']} min plus longue que tout quart admissible ({plus_long} min)",
            "allonger un quart, ou fournir la durée par visite",
        )
    return _raison(
        RAISON_FENETRE,
        "fenêtre du client inatteignable depuis le dépôt des équipes compétentes (trajets, fenêtre et quart)",
        "élargir la fenêtre du client, ou allonger le quart d'une équipe compétente",
    )


def _diagnostiquer(problem, ordres):
    """Raison de chaque chantier absent des routes ``ordres`` (``{k: [ordre]}``), triée par identifiant.

    Une insertion n'est essayée qu'à l'ordre existant (aucun autre chantier déplacé) : « journées
    pleines » veut dire aucune place SANS bousculer le plan.
    """
    planifies = {cid for ordre in ordres.values() for cid in ordre}
    horaires = {k: _planifier(problem, k, ordre) for k, ordre in ordres.items()}
    non_cedulees = []
    for cid in problem["ids"]:
        if cid in planifies:
            continue
        chantier = problem["chantiers"][cid]
        admissibles = problem["admissibles"][cid]
        if not admissibles:
            raison = _raison_statique(problem, chantier)
        else:
            meilleur = None
            for k in admissibles:
                ordre = ordres.get(k, [])
                horaire = horaires.get(k)
                base = horaire["metres"] if horaire is not None else 0
                for position in range(len(ordre) + 1):
                    essai = _planifier(problem, k, ordre[:position] + [cid] + ordre[position:])
                    if essai is not None and (meilleur is None or essai["metres"] - base < meilleur):
                        meilleur = essai["metres"] - base
            if meilleur is None:
                raison = _raison(
                    RAISON_JOURNEES_PLEINES,
                    "journées pleines : aucune insertion valide dans les quarts des équipes compétentes",
                    "ajouter ou allonger un quart, ou reporter le chantier",
                )
            elif meilleur >= chantier["cout"]:
                raison = _raison(
                    RAISON_COUT,
                    f"insertion valide possible (+{meilleur} m) mais au moins aussi coûteuse que le coût de "
                    f"non-cédule ({chantier['cout']} m)",
                    "augmenter cout_non_cedule_m, ou approuver l'ajout à la main",
                )
            else:
                raison = _raison(
                    RAISON_INSERTION,
                    f"insertion valide possible (+{meilleur} m), non retenue par le solveur",
                    "relancer avec plus d'itérations, ou approuver l'ajout à la main",
                )
        non_cedulees.append({"chantier": cid, **raison})
    return non_cedulees


# ---------------------------------------------------------------------------
# Assemblage de la sortie canonique
# ---------------------------------------------------------------------------
def _totaux(problem, distance_m, non_cedulees):
    cout = sum(problem["chantiers"][ligne["chantier"]]["cout"] for ligne in non_cedulees)
    return {
        "distance_m": distance_m,
        "cout_non_cedule_m": cout,
        "cout_total_m": distance_m + cout,
        "chantiers_cedules": len(problem["ids"]) - len(non_cedulees),
        "chantiers_non_cedules": len(non_cedulees),
    }


def _sortie_sans_empreinte(problem, routes, non_cedulees, moteur):
    plan = []
    distance_totale = 0
    for k in sorted(routes):
        vehicule = problem["vehicules"][k]
        horaire = _planifier(problem, k, routes[k])
        distance_totale += horaire["metres"]
        plan.append({
            "equipe": vehicule["equipe"],
            "jour": vehicule["jour"],
            "depot": vehicule["depot_id"],
            "depart_min": horaire["depart"],
            "retour_min": horaire["retour"],
            "distance_m": horaire["metres"],
            "visites": [
                {"chantier": cid, "arrivee_min": arrivee, "debut_min": debut, "fin_min": fin}
                for cid, arrivee, debut, fin in horaire["visites"]
            ],
        })
    matrice = problem["matrice"]
    return {
        "version": VERSION_SORTIE,
        "plan": plan,
        "non_cedulees": non_cedulees,
        "totaux": _totaux(problem, distance_totale, non_cedulees),
        "meta": {
            "solveur": moteur["solveur"],
            "version_solveur": moteur["version"],
            "graine": moteur["graine"],
            "iterations": moteur["iterations"],
            "empreinte_entree": problem["empreinte_entree"],
            "mode_distance": matrice["mode_distance"],
            "mode_bride": matrice["mode_bride"],
            "empreinte_matrice": matrice["empreinte"],
        },
    }


def _sceller(sortie):
    """Ajoute ``meta.empreinte_sortie`` : SHA-256 canonique de tout le reste."""
    sortie["meta"]["empreinte_sortie"] = encodage.empreinte(sortie)
    return sortie


def _assembler(problem, routes, moteur):
    """Sortie canonique à partir des routes d'un moteur, ou un verdict si le plan est inacceptable."""
    vus = set()
    for k in sorted(routes):
        for cid in routes[k]:
            if cid in vus or k not in problem["admissibles"].get(cid, ()):
                return None, verdict_tournees(
                    CODE_SOLVEUR_ECHEC, f"le solveur a placé le chantier {cid!r} hors de ses quarts admissibles",
                )
            vus.add(cid)
        if _planifier(problem, k, routes[k]) is None:
            return None, verdict_tournees(CODE_SOLVEUR_ECHEC, "le solveur a proposé une route qui viole un horaire")
    for cid in problem["ids"]:
        if problem["chantiers"][cid]["fige"] is not None and cid not in vus:
            return None, verdict_tournees(CODE_SOLVEUR_ECHEC, f"le solveur n'a pas tenu le créneau figé de {cid!r}")
    non_cedulees = _diagnostiquer(problem, routes)
    sortie = _sceller(_sortie_sans_empreinte(problem, routes, non_cedulees, moteur))
    violations = _verifier(problem, sortie)
    if violations:
        return None, verdict_tournees(CODE_PLAN_INVALIDE, " ; ".join(violations[:_MAX_PROBLEMES]))
    return sortie, None


# ---------------------------------------------------------------------------
# Résolution
# ---------------------------------------------------------------------------
def _graine_derivee(problem):
    """Graine du solveur : les 32 premiers bits de l'empreinte de l'entrée (aucune horloge, aucun aléa)."""
    return int(problem["empreinte_entree"][:8], 16)


def _choisir_moteur(moteur, nombre):
    """``(nom, None)`` avec ``nom`` dans ``("pyvrp", "dp")``, ou ``(None, verdict)``."""
    if moteur == "dp":
        if nombre > MAX_CHANTIERS_DP:
            return None, verdict_tournees(
                CODE_TAILLE_DP,
                f"{nombre} chantiers entrés au solveur, le repli exact en accepte au plus {MAX_CHANTIERS_DP}",
            )
        return "dp", None
    disponible, raison = pyvrp_installe()
    if disponible:
        return "pyvrp", None
    if moteur == "auto" and nombre <= MAX_CHANTIERS_DP:
        return "dp", None
    return None, verdict_tournees(
        CODE_SOLVEUR_ABSENT,
        f"{TEXTE_SOLVEUR_ABSENT} ({raison} ; {nombre} chantiers entrés au solveur, "
        f"le repli exact en accepte au plus {MAX_CHANTIERS_DP})",
    )


def empreinte_entree(entree):
    """Empreinte SHA-256 de l'entrée telle que le solveur la lit. Retourne (empreinte, None) ou (None, verdict).

    C'est le ``meta.empreinte_entree`` que ``resoudre`` inscrit au plan : équipes et chantiers triés,
    matrice réduite à sa propre empreinte, donc indépendante de l'ordre des listes. Elle sert à savoir si
    un plan mis de côté répond encore à la même entrée (par exemple après un changement de coordonnée), sans
    relancer le solveur. Même validation que ``resoudre`` : une entrée invalide rend son verdict."""
    problem, verdict = _preparer(entree)
    if verdict is not None:
        return None, verdict
    return problem["empreinte_entree"], None


def resoudre(entree, moteur="auto"):
    """Plan de tournées pour l'entrée donnée. Retourne (sortie, None) ou (None, verdict).

    ``entree`` : ``{"version": "tournees-entree-v1", "equipes": [...], "chantiers": [...], "matrice":
    <distances.obtenir_matrice>, "parametres": {"graine", "iterations", "cout_non_cedule_m"}}`` (voir la
    documentation du module et le README de M4). Rien n'est modifié dans ``entree``.

    ``moteur`` : ``"auto"`` (PyVRP s'il est installé à la version épinglée, sinon le DP exact jusqu'à
    ``MAX_CHANTIERS_DP`` chantiers), ``"pyvrp"`` ou ``"dp"``.

    ``sortie`` : ``{"version", "plan": [{equipe, jour, depot, depart_min, retour_min, distance_m,
    visites: [{chantier, arrivee_min, debut_min, fin_min}]}], "non_cedulees": [{chantier, code, raison,
    action}], "totaux", "meta": {solveur, version_solveur, graine, iterations, empreinte_entree,
    empreinte_sortie, mode_distance, mode_bride, empreinte_matrice}}`` : entiers, chaînes, booléens et
    ``None`` seulement, triée (équipe, jour, heure ; chantier), donc mêmes octets pour la même entrée.
    Le plan a déjà passé ``verifier_plan`` ; sinon un verdict ``REJ-TOURNEES-PLAN-INVALIDE`` est rendu.
    """
    if moteur not in MOTEURS:
        return None, _rejet("REJ-ENUM-INVALIDE", f"moteur : {', '.join(MOTEURS)} attendu")
    problem, verdict = _preparer(entree)
    if verdict is not None:
        return None, verdict
    solveur_ids = [cid for cid in problem["ids"] if problem["admissibles"][cid]]
    nom = "dp"  # sans chantier à placer, la réponse (aucune route) est exacte et n'exige aucun moteur
    if solveur_ids:
        nom, verdict = _choisir_moteur(moteur, len(solveur_ids))
        if verdict is not None:
            return None, verdict

    if nom == "dp":
        routes = _resoudre_dp(problem, solveur_ids)
        if routes is None:
            return None, verdict_tournees(CODE_SOLVEUR_ECHEC, "aucun plan ne tient les créneaux figés")
        meta_moteur = {"solveur": SOLVEUR_DP, "version": VERSION_DP, "graine": None, "iterations": None}
    else:
        graine = _graine_derivee(problem)
        iterations = problem["parametres"]["iterations"]
        try:
            routes = _resoudre_pyvrp(problem, solveur_ids, graine, iterations)
        except Exception as exc:  # une bibliothèque tierce ne plante jamais le dispatch : verdict stable
            return None, verdict_tournees(CODE_SOLVEUR_ECHEC, f"le solveur a levé {type(exc).__name__}")
        meta_moteur = {"solveur": SOLVEUR_PYVRP, "version": VERSION_PYVRP, "graine": graine, "iterations": iterations}
    return _assembler(problem, routes, meta_moteur)


# ---------------------------------------------------------------------------
# Validateur indépendant du solveur
# ---------------------------------------------------------------------------
def _json_entier(valeur):
    """Vrai si ``valeur`` ne contient que dict (clés chaînes), list, str, int (pas de flottant), bool, None."""
    if isinstance(valeur, dict):
        return all(isinstance(cle, str) and _json_entier(v) for cle, v in valeur.items())
    if isinstance(valeur, list):
        return all(_json_entier(v) for v in valeur)
    return valeur is None or isinstance(valeur, (str, bool)) or _est_entier(valeur)


def _controler_objet(valeur, chemin, cles, types, problemes):
    """Contrôle clés exactes et types d'un objet de la sortie ; vrai s'il est utilisable."""
    if not isinstance(valeur, dict) or set(valeur) != set(cles):
        problemes.append(f"{chemin} : clés attendues {', '.join(cles)}")
        return False
    bon = True
    for cle, attendu in types.items():
        element = valeur[cle]
        if attendu is int:
            conforme = _est_entier(element)
        elif attendu == "int|None":
            conforme = element is None or _est_entier(element)
        elif attendu is bool:
            conforme = isinstance(element, bool)
        else:
            conforme = isinstance(element, attendu)
        if not conforme:
            problemes.append(f"{chemin}.{cle} : type invalide")
            bon = False
    return bon


def _structure_sortie(sortie):
    """Problèmes de forme de la sortie (liste vide si elle est utilisable par ``_verifier``)."""
    problemes = []
    if not isinstance(sortie, dict) or set(sortie) != set(_CLES_SORTIE):
        return [f"sortie : clés attendues {', '.join(_CLES_SORTIE)}"]
    if not _json_entier(sortie):
        return ["sortie : entiers, chaînes, booléens et null seulement (aucun flottant)"]
    if sortie["version"] != VERSION_SORTIE:
        problemes.append(f"sortie.version : {VERSION_SORTIE!r} attendue")
    if not isinstance(sortie["plan"], list):
        problemes.append("sortie.plan : une liste est attendue")
    else:
        types_route = {"equipe": str, "jour": int, "depot": str, "depart_min": int, "retour_min": int,
                       "distance_m": int, "visites": list}
        types_visite = {"chantier": str, "arrivee_min": int, "debut_min": int, "fin_min": int}
        for position, route in enumerate(sortie["plan"]):
            chemin = f"plan[{position}]"
            if _controler_objet(route, chemin, _CLES_ROUTE, types_route, problemes):
                for rang, visite in enumerate(route["visites"]):
                    _controler_objet(visite, f"{chemin}.visites[{rang}]", _CLES_VISITE, types_visite, problemes)
    if not isinstance(sortie["non_cedulees"], list):
        problemes.append("sortie.non_cedulees : une liste est attendue")
    else:
        types_ligne = {"chantier": str, "code": str, "raison": str, "action": str}
        for position, ligne in enumerate(sortie["non_cedulees"]):
            _controler_objet(ligne, f"non_cedulees[{position}]", _CLES_NON_CEDULEE, types_ligne, problemes)
    _controler_objet(sortie["totaux"], "totaux", _CLES_TOTAUX, dict.fromkeys(_CLES_TOTAUX, int), problemes)
    types_meta = {
        "solveur": str, "version_solveur": str, "graine": "int|None", "iterations": "int|None",
        "empreinte_entree": str, "empreinte_sortie": str, "mode_distance": str, "mode_bride": bool,
        "empreinte_matrice": str,
    }
    _controler_objet(sortie["meta"], "meta", _CLES_META, types_meta, problemes)
    return problemes


def _verifier_route(problem, route, chemin, violations, vues):
    """Contrôle une route du plan contre les contraintes ; complète ``violations`` et ``vues``."""
    equipes = {e["id"]: e for e in problem["entree"]["equipes"]}
    equipe = equipes.get(route["equipe"])
    if equipe is None:
        violations.append(f"{chemin} : équipe {route['equipe']!r} inconnue")
        return None
    quart = next((q for q in equipe["quarts"] if q["jour"] == route["jour"]), None)
    if quart is None:
        violations.append(f"{chemin} : l'équipe {equipe['id']!r} n'a pas de quart le jour {route['jour']}")
        return None
    if route["depot"] != equipe["depot"]:
        violations.append(f"{chemin} : dépôt {route['depot']!r} différent de celui de l'équipe")
    if not route["visites"]:
        violations.append(f"{chemin} : route sans visite")
        return None
    indice = problem["indice"]
    trajet = problem["trajet"]
    metres = problem["metres"]
    depot = indice.get(equipe["depot"])
    if depot is None:
        return None
    competences = set(equipe["competences"])
    debut_quart, fin_quart = quart["debut_min"], quart["fin_min"]
    if route["depart_min"] < debut_quart:
        violations.append(f"{chemin} : départ à {route['depart_min']} min, avant le début du quart ({debut_quart} min)")
    position = depot
    libre = route["depart_min"]
    distance = 0
    ordre = []
    utilisable = True
    for visite in route["visites"]:
        cid = visite["chantier"]
        chantier = problem["chantiers"].get(cid)
        nom = f"{chemin}, chantier {cid!r}"
        if chantier is None:
            violations.append(f"{nom} : chantier inconnu de l'entrée")
            utilisable = False
            continue
        if chantier["idx"] is None:
            violations.append(f"{nom} : coordonnées manquantes, le chantier ne peut pas être cédulé")
            utilisable = False
            continue
        if cid in vues:
            violations.append(f"{nom} : visité deux fois (aussi {vues[cid]})")
            utilisable = False
        vues.setdefault(cid, f"équipe {equipe['id']!r}, jour {route['jour']}")
        if not chantier["competences"] <= competences:
            violations.append(f"{nom} : l'équipe {equipe['id']!r} n'a pas toutes les compétences requises")
        if route["jour"] not in chantier["jours"]:
            violations.append(f"{nom} : le jour {route['jour']} n'est pas permis par la fenêtre du client")
        idx = chantier["idx"]
        if visite["arrivee_min"] < libre + trajet[position][idx]:
            violations.append(
                f"{nom} : arrivée à {visite['arrivee_min']} min, trajet trop court depuis la visite précédente",
            )
        if visite["debut_min"] < visite["arrivee_min"]:
            violations.append(
                f"{nom} : début à {visite['debut_min']} min, avant l'arrivée ({visite['arrivee_min']} min)",
            )
        if visite["debut_min"] < chantier["debut_fen"]:
            violations.append(
                f"{nom} : début à {visite['debut_min']} min, avant l'ouverture de la fenêtre du client "
                f"({chantier['debut_fen']} min)",
            )
        if visite["fin_min"] != visite["debut_min"] + chantier["duree"]:
            violations.append(f"{nom} : fin à {visite['fin_min']} min, la durée fournie est {chantier['duree']} min")
        if visite["fin_min"] > chantier["debut_max"] + chantier["duree"]:
            violations.append(
                f"{nom} : fin à {visite['fin_min']} min, après la fermeture de la fenêtre du client "
                f"({chantier['debut_max'] + chantier['duree']} min)",
            )
        if chantier["fige"] is not None:
            figee = (chantier["fige"][0], chantier["fige"][1])
            if (equipe["id"], route["jour"]) != figee or visite["debut_min"] != chantier["fige"][2]:
                violations.append(f"{nom} : créneau figé non respecté")
        distance += metres[position][idx]
        ordre.append(cid)
        position = idx
        libre = visite["fin_min"]
    if not utilisable:
        return None
    retour_minimal = libre + trajet[position][depot]
    if route["retour_min"] < retour_minimal:
        violations.append(f"{chemin} : retour à {route['retour_min']} min, trajet de retour trop court")
    if route["retour_min"] > fin_quart:
        violations.append(f"{chemin} : retour à {route['retour_min']} min, après la fin du quart ({fin_quart} min)")
    distance += metres[position][depot]
    if route["distance_m"] != distance:
        violations.append(
            f"{chemin} : distance_m {route['distance_m']} différente de la distance recalculée ({distance})",
        )
    return ordre, distance


def _verifier(problem, sortie):
    """Violations de la sortie contre le problème (liste vide : plan valide). Ne fait confiance à rien."""
    violations = _structure_sortie(sortie)
    if violations:
        return violations
    vues = {}
    ordres = {}
    routes_vues = set()
    distance_totale = 0
    tout_utilisable = True
    for position, route in enumerate(sortie["plan"]):
        chemin = f"plan[{position}] ({route['equipe']!r}, jour {route['jour']})"
        cle = (route["equipe"], route["jour"])
        if cle in routes_vues:
            violations.append(f"{chemin} : deux routes pour la même équipe le même jour")
            tout_utilisable = False
            continue
        routes_vues.add(cle)
        verifie = _verifier_route(problem, route, chemin, violations, vues)
        if verifie is None:
            tout_utilisable = False
            continue
        ordre, distance = verifie
        distance_totale += distance
        ordres[_indice_vehicule(problem, route["equipe"], route["jour"])] = ordre

    lignes = {}
    for ligne in sortie["non_cedulees"]:
        cid = ligne["chantier"]
        if cid not in problem["chantiers"]:
            violations.append(f"non_cedulees : chantier {cid!r} inconnu de l'entrée")
        elif cid in lignes:
            violations.append(f"non_cedulees : chantier {cid!r} listé deux fois")
        elif cid in vues:
            violations.append(f"non_cedulees : chantier {cid!r} aussi présent au plan")
        lignes[cid] = ligne
    for cid in problem["ids"]:
        chantier = problem["chantiers"][cid]
        if cid not in vues and cid not in lignes:
            violations.append(f"chantier {cid!r} absent du plan et des non-cédulées")
        if chantier["fige"] is not None and cid not in vues:
            violations.append(f"chantier {cid!r} : créneau figé perdu (absent du plan)")

    if not violations and tout_utilisable:
        attendues = _diagnostiquer(problem, ordres)
        if sortie["non_cedulees"] != attendues:
            par_id = {ligne["chantier"]: ligne for ligne in sortie["non_cedulees"]}
            for attendue in attendues:
                recue = par_id.get(attendue["chantier"])
                if recue != attendue:
                    violations.append(
                        f"non_cedulees : chantier {attendue['chantier']!r} : raison recalculée "
                        f"{attendue['code']!r}, reçue {None if recue is None else recue['code']!r}",
                    )
            if not violations:
                violations.append("non_cedulees : ordre ou contenu différent du diagnostic recalculé")
        attendus = _totaux(problem, distance_totale, attendues)
        if sortie["totaux"] != attendus:
            violations.append("totaux : différents des totaux recalculés")
    _verifier_meta(problem, sortie, violations)
    return list(dict.fromkeys(violations))


def _verifier_meta(problem, sortie, violations):
    meta = sortie["meta"]
    matrice = problem["matrice"]
    if meta["empreinte_entree"] != problem["empreinte_entree"]:
        violations.append("meta.empreinte_entree : ne correspond pas à l'entrée fournie")
    if meta["mode_distance"] != matrice["mode_distance"] or meta["mode_bride"] != matrice["mode_bride"]:
        violations.append("meta : mode_distance ou mode_bride différent de la matrice")
    if meta["empreinte_matrice"] != matrice["empreinte"]:
        violations.append("meta.empreinte_matrice : ne correspond pas à la matrice fournie")
    if meta["solveur"] == SOLVEUR_PYVRP:
        if meta["version_solveur"] != VERSION_PYVRP:
            violations.append(f"meta.version_solveur : {VERSION_PYVRP!r} attendue pour pyvrp")
        if meta["graine"] != _graine_derivee(problem) or meta["iterations"] != problem["parametres"]["iterations"]:
            violations.append("meta : graine ou iterations différentes de celles dérivées de l'entrée")
    elif meta["solveur"] == SOLVEUR_DP:
        if meta["version_solveur"] != VERSION_DP or meta["graine"] is not None or meta["iterations"] is not None:
            violations.append("meta : le DP exact n'a ni graine ni itérations")
    else:
        violations.append(f"meta.solveur : {SOLVEUR_PYVRP!r} ou {SOLVEUR_DP!r} attendu")
    sans_empreinte = {**sortie, "meta": {c: v for c, v in meta.items() if c != "empreinte_sortie"}}
    if meta["empreinte_sortie"] != encodage.empreinte(sans_empreinte):
        violations.append("meta.empreinte_sortie : invalide, la sortie a été modifiée après le calcul")


def verifier_plan(entree, sortie):
    """Contrôle un plan sans rien reprendre du solveur. Retourne (True, []) ou (False, violations).

    Refuse : un chantier hors de sa fenêtre ou de son quart, une équipe sans les compétences requises, un
    jour non permis, un créneau figé déplacé ou perdu, un chantier visité deux fois, inventé, sans
    coordonnées ou oublié, un trajet ou une durée trop courts, une distance ou un total faux, une raison de
    non-cédule différente du diagnostic recalculé, une empreinte qui ne correspond plus à la sortie. Chaque
    violation dit quoi corriger. ``entree`` est celle de ``resoudre`` ; elle est revalidée, matrice comprise.
    Ne lève jamais.
    """
    problem, verdict = _preparer(entree)
    if verdict is not None:
        return False, [f"entrée invalide : {verdict['detail']}"]
    violations = _verifier(problem, sortie)
    return (not violations), violations
