"""Météo bloquante d'un créneau (M4.10, PLAN T4.13) : règles par service, verdict, prévision citée, report proposé.

Module pur (stdlib et ``verdicts`` ; aucun import ``opsys``, aucune horloge, aucun aléa, aucun réseau, aucun flottant ;
un test le vérifie par analyse du code). Il reçoit des RÈGLES (le profil météo de l'entreprise, ``opsys.meteo``, lues et
validées par l'adaptateur) et une PRÉVISION (rendue par un fournisseur du port ``FournisseurMeteo``), et répond à une
seule question : « ce créneau tient-il, compte tenu de la météo prévue ? ». Le code calcule, le modèle n'invente rien :
aucun seuil, aucune valeur météo, aucune date ne vient d'un modèle.

Quatre issues, jamais autre chose ::

    ``bloquant``            au moins une règle est franchie au niveau « blocage » : le créneau ne se tient pas ;
    ``validation_requise``  au moins une règle est franchie au niveau « validation » : un humain décide ;
    ``ok``                  chaque risque est jugé (ou déclaré sans objet), chaque heure du créneau est couverte par la
                            prévision, aucun seuil n'est franchi ;
    ``inconnu``             quelque chose ne peut pas être jugé : seuil à configurer, prévision absente, heure sans
                            donnée, fournisseur en panne. « Inconnu » n'est JAMAIS « ok » (fail-closed, AGENTS.md).

Le pire l'emporte : bloquant, puis validation requise, puis inconnu, puis ok. Un blocage observé sur une partie du
créneau reste un blocage même si le reste manque de données ; un « ok » exige que tout soit su.

Règles (``opsys.meteo``) : pour chaque service, des seuils par MESURE (vent moyen, rafales, précipitations horaires,
probabilité de précipitations, gel, verglas, chaleur), chacun à deux niveaux (validation, blocage), et les risques que
l'entreprise déclare SANS OBJET. Des règles vides, ou un risque sans décision, donnent « seuil à configurer » et un
verdict « inconnu » : aucune valeur par défaut. Un service dont les cinq risques sont déclarés sans objet ne demande
aucune prévision.

Prévision : une liste de points HORAIRES du fournisseur ; ``heure`` est l'heure LOCALE du chantier (``AAAA-MM-JJTHH:MM``
puis secondes et décalage), comparée sans conversion à la date et aux minutes du créneau. Un point à l'heure ``H``
compte pour un créneau ``[debut_min, fin_min]`` si ``debut_min // 60 <= H <= ceil(fin_min / 60)`` (bornes incluses : les
précipitations et les rafales d'un point résument l'heure PRÉCÉDENTE, la prudence commande d'inclure les deux bouts). La
prévision cite sa SOURCE et son HEURE d'émission, celles du fournisseur, jamais une horloge de M4 (M4 n'en a pas).

Lieu : la position d'un chantier est un renseignement personnel (Loi 25). Elle n'est jamais envoyée telle quelle à un
fournisseur : ``lieu_generalise`` l'arrondit au dixième de degré (environ 11 km), assez pour une prévision, trop
grossier pour désigner une adresse. ``est_lieu_generalise`` est le contrôle que chaque adaptateur refait avant d'ouvrir
une connexion.

Report proposé : un créneau bloquant ne déplace rien tout seul. ``preparer_relance`` calcule, pour les jours restants,
les arguments d'une nouvelle proposition de cédule (fenêtres sans le jour bloqué pour le service touché) ; l'application
reste un geste de l'admin (N3).
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Protocol, runtime_checkable

from . import verdicts

STATUT_BLOQUANT = "bloquant"
STATUT_VALIDATION = "validation_requise"
STATUT_INCONNU = "inconnu"
STATUT_OK = "ok"
STATUT_SANS_OBJET = "sans_objet"
# Du plus grave au moins grave : le pire l'emporte.
STATUTS = (STATUT_BLOQUANT, STATUT_VALIDATION, STATUT_INCONNU, STATUT_OK)
_GRAVITE = {statut: rang for rang, statut in enumerate(reversed(STATUTS))}

MOTIF_REPORT = "meteo"

RISQUES = ("vent", "pluie", "gel", "verglas", "chaleur")
# mesure -> (risque, sens, champ du point de prévision, unité). Même catalogue que `opsys.meteo.MESURES` (un test les
# compare).
MESURES = {
    "vent_kmh": ("vent", ">=", "vent_kmh", "km/h"),
    "rafales_kmh": ("vent", ">=", "rafales_kmh", "km/h"),
    "pluie_mm_h": ("pluie", ">=", "precipitation_mm_h", "mm/h"),
    "pluie_probabilite_pct": ("pluie", ">=", "probabilite_precipitation_pct", "%"),
    "gel_c": ("gel", "<=", "temperature_c", "°C"),
    "verglas": ("verglas", "presence", "verglas", None),
    "chaleur_c": ("chaleur", ">=", "temperature_c", "°C"),
}
CHAMPS_NOMBRE = (
    "temperature_c",
    "vent_kmh",
    "rafales_kmh",
    "precipitation_mm_h",
    "probabilite_precipitation_pct",
)
CHAMP_VERGLAS = "verglas"
CLES_POINT = ("heure",) + CHAMPS_NOMBRE + (CHAMP_VERGLAS,)

# Précision du lieu envoyé à un fournisseur : 0,1 degré, en microdegrés entiers (environ 11 km de latitude).
PAS_LIEU_MICRODEGRES = 100_000
LATITUDE_MAX_MICRODEG = 90_000_000
LONGITUDE_MAX_MICRODEG = 180_000_000

# Verdicts propres à la météo, inscrits au catalogue de ``verdicts.py`` (un test le vérifie).
CODE_FOURNISSEUR_INDISPONIBLE = "REJ-METEO-FOURNISSEUR-INDISPONIBLE"
CODE_REPONSE_INVALIDE = "REJ-METEO-REPONSE-INVALIDE"
CODE_FOURNISSEUR_FERME = "REJ-METEO-FOURNISSEUR-FERME"
CODE_LIEU_TROP_PRECIS = "REJ-METEO-LIEU-TROP-PRECIS"
CODES_METEO = (
    CODE_FOURNISSEUR_INDISPONIBLE,
    CODE_REPONSE_INVALIDE,
    CODE_FOURNISSEUR_FERME,
    CODE_LIEU_TROP_PRECIS,
)

RAISON_CRENEAU_FIGE = "creneau_fige"
RAISON_SANS_JOUR_RESTANT = "sans_jour_restant"

_FORME_HEURE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?$")
_FORME_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")

__all__ = [
    "STATUT_BLOQUANT",
    "STATUT_VALIDATION",
    "STATUT_INCONNU",
    "STATUT_OK",
    "STATUT_SANS_OBJET",
    "STATUTS",
    "MOTIF_REPORT",
    "RISQUES",
    "MESURES",
    "CHAMPS_NOMBRE",
    "CHAMP_VERGLAS",
    "CLES_POINT",
    "PAS_LIEU_MICRODEGRES",
    "CODE_FOURNISSEUR_INDISPONIBLE",
    "CODE_REPONSE_INVALIDE",
    "CODE_FOURNISSEUR_FERME",
    "CODE_LIEU_TROP_PRECIS",
    "CODES_METEO",
    "RAISON_CRENEAU_FIGE",
    "RAISON_SANS_JOUR_RESTANT",
    "FournisseurMeteo",
    "verdict_meteo",
    "pire",
    "est_date",
    "en_texte",
    "lieu_generalise",
    "est_lieu_generalise",
    "heures_attendues",
    "valider_previsions",
    "risques_a_decider",
    "regles_exigent_une_prevision",
    "evaluer_creneau",
    "resultat_inconnu",
    "preparer_relance",
]


@runtime_checkable
class FournisseurMeteo(Protocol):
    """Port d'un fournisseur de prévisions (sur le patron de ``distances.FournisseurMatrice``).

    Un fournisseur ne fait QUE fournir des points de prévision ; les règles, le verdict, le lieu généralisé et la
    citation sont traités ici, une seule fois, pour tous les fournisseurs.

    ``descripteur()`` : dict de chaînes non vides, stable d'un appel à l'autre : ``fournisseur`` (nom), ``attribution``
    (mention exigée par la licence de la source, ou ``None`` pour une saisie à la main) et tout ce qui identifie la
    source (version de l'API, licence).

    ``previsions(lieu, date_debut, date_fin)`` : ``lieu`` est ``{"latitude_microdegres", "longitude_microdegres"}``,
    déjà GÉNÉRALISÉ (``est_lieu_generalise`` : l'adaptateur le refuse sinon) ; ``date_debut`` et ``date_fin`` sont des
    dates ``AAAA-MM-JJ``. Rend ``({"citation": {...}, "points": [...]}, None)`` ou ``(None, verdict)``. Ne lève rien ;
    n'écrit rien ; n'est appelé que si l'appelant en fournit un. ``citation`` porte au moins ``source``, ``emise_le``
    (heure d'émission de la prévision, celle du fournisseur) et ``heure_type`` (ce que cette heure est : mise à jour
    de la source, réponse HTTP, heure saisie), plus ``attribution`` quand la licence l'exige. Chaque point est
    ``CLES_POINT`` ; une valeur que la source ne donne pas vaut ``None`` (jamais 0).
    """

    def descripteur(self):
        """Métadonnées stables du fournisseur (voir la classe)."""

    def previsions(self, lieu, date_debut, date_fin):
        """Prévisions horaires autour du lieu, ou un verdict (voir la classe)."""


def verdict_meteo(code, detail):
    """Verdict de la météo, au catalogue de M4 (``verdicts.construire_verdict``)."""
    return verdicts.construire_verdict(code, detail=detail)


# ---------------------------------------------------------------------------
# Petits outils purs : gravité, dates, nombres
# ---------------------------------------------------------------------------
def pire(statuts):
    """Le statut le plus grave d'une liste ; « inconnu » si la liste est vide (rien n'a été jugé, jamais « ok »)."""
    statuts = list(statuts)
    if not statuts:
        return STATUT_INCONNU
    return max(statuts, key=lambda statut: _GRAVITE[statut])


def _jours_du_mois(annee, mois):
    if mois == 2:
        bissextile = annee % 4 == 0 and (annee % 100 != 0 or annee % 400 == 0)
        return 29 if bissextile else 28
    return 30 if mois in (4, 6, 9, 11) else 31


def _date_valide(annee, mois, jour):
    return 1 <= mois <= 12 and 1 <= jour <= _jours_du_mois(annee, mois)


def est_date(texte):
    """Vrai si ``texte`` est une date civile ``AAAA-MM-JJ`` qui existe (29 février seulement les années bissextiles)."""
    if not isinstance(texte, str):
        return False
    trouve = _FORME_DATE.match(texte)
    return trouve is not None and _date_valide(*(int(morceau) for morceau in trouve.groups()))


def _nombre(valeur):
    """``Decimal`` d'un entier ou d'un ``Decimal`` fini ; ``None`` sinon (booléen, texte, infini, absent)."""
    if isinstance(valeur, bool):
        return None
    if isinstance(valeur, int):
        return Decimal(valeur)
    if isinstance(valeur, Decimal) and valeur.is_finite():
        return valeur
    return None


def en_texte(nombre):
    """Texte décimal exact et canonique d'un nombre (``Decimal('62.50')`` -> ``62.5`` ; ``Decimal('100')`` ->
    ``100``)."""
    return format(Decimal(nombre).normalize(), "f")


def _hhmm(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


# ---------------------------------------------------------------------------
# Lieu : jamais l'adresse d'un client chez un tiers
# ---------------------------------------------------------------------------
def lieu_generalise(latitude_microdegres, longitude_microdegres):
    """Le lieu arrondi au dixième de degré le plus proche (demi vers le haut), en microdegrés entiers.

    Fonction pure sur des entiers : même entrée, même sortie. Ne rend qu'un lieu de la précision d'un secteur."""
    pas = PAS_LIEU_MICRODEGRES
    return {
        "latitude_microdegres": (latitude_microdegres + pas // 2) // pas * pas,
        "longitude_microdegres": (longitude_microdegres + pas // 2) // pas * pas,
    }


def est_lieu_generalise(lieu):
    """Vrai si ``lieu`` est un lieu de la précision permise : deux entiers, multiples du pas, dans les bornes."""
    if not isinstance(lieu, dict) or set(lieu) != {"latitude_microdegres", "longitude_microdegres"}:
        return False
    latitude, longitude = lieu["latitude_microdegres"], lieu["longitude_microdegres"]
    if isinstance(latitude, bool) or isinstance(longitude, bool):
        return False
    if not isinstance(latitude, int) or not isinstance(longitude, int):
        return False
    return (
        latitude % PAS_LIEU_MICRODEGRES == 0
        and longitude % PAS_LIEU_MICRODEGRES == 0
        and abs(latitude) <= LATITUDE_MAX_MICRODEG
        and abs(longitude) <= LONGITUDE_MAX_MICRODEG
    )


# ---------------------------------------------------------------------------
# Créneau et prévision
# ---------------------------------------------------------------------------
def heures_attendues(debut_min, fin_min):
    """Les heures pleines (0 à 23) dont la prévision est exigée pour juger un créneau ``[debut_min, fin_min]``."""
    return list(range(debut_min // 60, min(23, -(-fin_min // 60)) + 1))


def _heure_du_point(point):
    """``(date, heure, minutes)`` de l'heure locale d'un point, ou ``None`` si elle est mal formée."""
    heure = point.get("heure") if isinstance(point, dict) else None
    trouve = _FORME_HEURE.match(heure) if isinstance(heure, str) else None
    if trouve is None:
        return None
    annee, mois, jour, hh, mm = (int(morceau) for morceau in trouve.groups())
    if not _date_valide(annee, mois, jour) or hh > 23 or mm > 59:
        return None
    return heure[:10], hh, mm


def valider_previsions(previsions):
    """Rend ``None`` si ``previsions`` respecte le port, sinon la phrase qui dit ce qui est faux.

    Exige une citation (source et heure d'émission non vides), des points HORAIRES (minutes à zéro), une heure locale
    bien formée, aucune heure en double, des valeurs entières, décimales exactes ou ``None`` (jamais un booléen ni un
    texte), et un booléen ou ``None`` pour le verglas. Un point qui ne respecte pas le port ne sert jamais à juger un
    créneau."""
    if not isinstance(previsions, dict) or set(previsions) != {"citation", "points"}:
        return "prévision : un objet {citation, points} est attendu"
    citation = previsions["citation"]
    if not isinstance(citation, dict):
        return "prévision.citation : un objet est attendu"
    for cle in ("source", "emise_le", "heure_type"):
        if not isinstance(citation.get(cle), str) or citation[cle].strip() == "":
            return f"prévision.citation.{cle} : texte non vide requis (la source et son heure se citent toujours)"
    points = previsions["points"]
    if not isinstance(points, list) or not points:
        return "prévision.points : au moins un point horaire est attendu"
    vues = set()
    for position, point in enumerate(points):
        nom = f"prévision.points[{position}]"
        if not isinstance(point, dict) or not set(point) <= set(CLES_POINT):
            return f"{nom} : clés permises {', '.join(CLES_POINT)}"
        lue = _heure_du_point(point)
        if lue is None:
            return f"{nom}.heure : heure locale AAAA-MM-JJTHH:MM attendue"
        date, heure, minutes = lue
        if minutes != 0:
            return f"{nom}.heure : point horaire attendu (minutes à zéro)"
        if (date, heure) in vues:
            return f"{nom}.heure : heure en double ({date} {heure:02d}:00)"
        vues.add((date, heure))
        for champ in CHAMPS_NOMBRE:
            valeur = point.get(champ)
            if valeur is not None and _nombre(valeur) is None:
                return f"{nom}.{champ} : nombre entier ou décimal exact, ou null (reçu {valeur!r})"
        if point.get(CHAMP_VERGLAS) is not None and not isinstance(point[CHAMP_VERGLAS], bool):
            return f"{nom}.{CHAMP_VERGLAS} : true, false ou null (reçu {point[CHAMP_VERGLAS]!r})"
    return None


def _points_du_jour(points, date):
    """``{heure: point}`` des points de cette date locale."""
    par_heure = {}
    for point in points:
        lue = _heure_du_point(point)
        if lue is not None and lue[0] == date:
            par_heure[lue[1]] = point
    return par_heure


def _point_en_texte(point):
    """Le point tel que le résultat le cite : nombres en texte décimal exact, verglas booléen, absent = ``None``."""
    sortie = {"heure": point["heure"]}
    for champ in CHAMPS_NOMBRE:
        nombre = _nombre(point.get(champ))
        sortie[champ] = None if nombre is None else en_texte(nombre)
    sortie[CHAMP_VERGLAS] = point.get(CHAMP_VERGLAS)
    return sortie


# ---------------------------------------------------------------------------
# Règles
# ---------------------------------------------------------------------------
def risques_a_decider(regles):
    """Les risques qu'un service n'a ni jugés (aucune mesure dans ses seuils) ni déclarés sans objet (l'ordre
    canonique).

    Sans règles (``None`` ou vides), les cinq : « seuil à configurer »."""
    if not regles:
        return list(RISQUES)
    jugees = {MESURES[mesure][0] for mesure in regles.get("seuils", {})}
    sans_objet = set(regles.get("sans_objet", ()))
    return [risque for risque in RISQUES if risque not in jugees and risque not in sans_objet]


def regles_exigent_une_prevision(regles):
    """Vrai si au moins une mesure est jugée : sinon (tout est sans objet, ou rien n'est déclaré) aucune prévision ne
    sert."""
    return bool(regles) and bool(regles.get("seuils"))


def _franchit(valeur, seuil, sens):
    return valeur >= seuil if sens == ">=" else valeur <= seuil


def _evaluer_verglas(seuil, observees, manquantes):
    presence = [heure for heure, valeur in observees if valeur is True]
    blocage, validation = seuil.get("blocage") is True, seuil.get("validation") is True
    if presence and blocage:
        statut = STATUT_BLOQUANT
    elif presence and validation:
        statut = STATUT_VALIDATION
    elif manquantes or not observees:
        statut = STATUT_INCONNU
    else:
        statut = STATUT_OK
    observe = {"valeur": True, "heure": _hhmm(presence[0] * 60)} if presence else None
    if presence:
        niveau = "blocage" if blocage else "validation"
        detail = f"verglas : précipitations verglaçantes prévues à {_hhmm(presence[0] * 60)} (niveau {niveau})"
    elif statut == STATUT_OK:
        detail = "verglas : aucune précipitation verglaçante prévue pendant le créneau"
    else:
        detail = "verglas : jugé impossible, la prévision ne dit pas tout (jamais présumé sans risque)"
    return statut, observe, detail


def _evaluer_nombre(mesure, seuil, observees, manquantes):
    _, sens, _, unite = MESURES[mesure]
    if not observees:
        return (
            STATUT_INCONNU,
            None,
            f"{mesure} : aucune donnée de la prévision pour ce créneau (jamais présumé sans risque)",
        )
    extreme = max if sens == ">=" else min
    valeur = extreme(valeur for _, valeur in observees)
    heure = next(heure for heure, v in observees if v == valeur)
    observe = {"valeur": en_texte(valeur), "heure": _hhmm(heure * 60)}
    dit = f"{en_texte(valeur)} {unite} à {_hhmm(heure * 60)}"
    if "blocage" in seuil and _franchit(valeur, seuil["blocage"], sens):
        return STATUT_BLOQUANT, observe, f"{mesure} : {dit}, blocage {sens} {seuil['blocage']}"
    if "validation" in seuil and _franchit(valeur, seuil["validation"], sens):
        return STATUT_VALIDATION, observe, f"{mesure} : {dit}, validation requise {sens} {seuil['validation']}"
    if manquantes:
        return (
            STATUT_INCONNU,
            observe,
            (
                f"{mesure} : {dit}, sous les seuils, mais sans donnée à "
                + ", ".join(_hhmm(h * 60) for h in manquantes)
                + " (jamais présumé sans risque)"
            ),
        )
    return STATUT_OK, observe, f"{mesure} : {'maximum' if sens == '>=' else 'minimum'} prévu {dit}, sous les seuils"


def _evaluer_mesure(mesure, seuil, par_heure, attendues):
    risque, _, champ, _ = MESURES[mesure]
    observees, manquantes = [], []
    for heure in attendues:
        point = par_heure.get(heure)
        brut = None if point is None else point.get(champ)
        valeur = brut if champ == CHAMP_VERGLAS and isinstance(brut, bool) else _nombre(brut)
        if valeur is None:
            manquantes.append(heure)
        else:
            observees.append((heure, valeur))
    if champ == CHAMP_VERGLAS:
        statut, observe, detail = _evaluer_verglas(seuil, observees, manquantes)
    else:
        statut, observe, detail = _evaluer_nombre(mesure, seuil, observees, manquantes)
    return {
        "risque": risque,
        "mesure": mesure,
        "statut": statut,
        "seuils": dict(seuil),
        "observe": observe,
        "heures_sans_donnee": [_hhmm(heure * 60) for heure in manquantes],
        "detail": detail,
    }


def _a_configurer(a_decider):
    return [f"{risque} : seuil à configurer (ou risque déclaré sans objet)" for risque in a_decider]


def evaluer_creneau(regles, previsions, date, debut_min, fin_min):
    """Le verdict météo d'un créneau : ``{statut, date, debut_min, fin_min, regles, sans_objet, a_configurer,
    prevision}``.

    ``regles`` : les règles du service (``{"seuils": {...}, "sans_objet": [...]}``) ou ``None`` ; ``previsions`` : une
    prévision qui respecte le port (``valider_previsions``), ou ``None`` si aucune règle n'en demande. ``date`` :
    ``AAAA-MM-JJ`` locale du chantier ; ``debut_min`` et ``fin_min`` : minutes depuis minuit, ``debut_min < fin_min``.

    Fonction pure : même entrée, mêmes octets. Un risque sans décision, une heure sans donnée, une mesure que la source
    ne donne pas : « inconnu ». Un seuil franchi sur une heure connue : validation ou blocage, quoi qu'il manque
    ailleurs."""
    seuils = regles.get("seuils", {}) if regles else {}
    a_decider = risques_a_decider(regles)
    attendues = heures_attendues(debut_min, fin_min)
    par_heure = {} if previsions is None else _points_du_jour(previsions["points"], date)
    evaluees = [_evaluer_mesure(mesure, seuils[mesure], par_heure, attendues) for mesure in MESURES if mesure in seuils]
    statuts = [regle["statut"] for regle in evaluees]
    if a_decider:
        statuts.append(STATUT_INCONNU)
    prevision = None
    if previsions is not None:
        prevision = {
            "citation": dict(previsions["citation"]),
            "points": [_point_en_texte(par_heure[heure]) for heure in attendues if heure in par_heure],
        }
    return {
        "statut": pire(statuts) if statuts else STATUT_OK,
        "date": date,
        "debut_min": debut_min,
        "fin_min": fin_min,
        "regles": evaluees,
        "sans_objet": list(regles.get("sans_objet", ())) if regles else [],
        "a_configurer": _a_configurer(a_decider),
        "prevision": prevision,
    }


def resultat_inconnu(regles, date, debut_min, fin_min, cause):
    """Le résultat d'un créneau qu'on ne peut pas juger : « inconnu », jamais « ok », et la cause dite.

    ``cause`` : ``{"code", "detail"}`` (verdict du fournisseur, règle manquante, date absente...). Les risques sans
    décision restent listés, et aucune règle n'est évaluée : sans prévision, il n'y a rien à comparer."""
    return {
        "statut": STATUT_INCONNU,
        "date": date,
        "debut_min": debut_min,
        "fin_min": fin_min,
        "regles": [],
        "sans_objet": list(regles.get("sans_objet", ())) if regles else [],
        "a_configurer": _a_configurer(risques_a_decider(regles)),
        "prevision": None,
        "cause": {"code": cause["code"], "detail": cause["detail"]},
    }


# ---------------------------------------------------------------------------
# Report proposé : les jours restants
# ---------------------------------------------------------------------------
def preparer_relance(chantiers_du_plan, bloques, service_de):
    """Les chantiers d'une nouvelle proposition de cédule, sans les jours que la météo a fermés.

    ``chantiers_du_plan`` : les entrées du solveur du plan proposé (``id``, ``fenetre`` avec ``jours``,
    ``creneau_fige``) ; ``bloques`` : ``[{"intervention_id", "jour"}]``, les créneaux bloquants ; ``service_de`` :
    ``{intervention_id: service}`` (``None`` pour un lead v1, qui n'a pas de service).

    Un jour bloqué pour un service est retiré de la fenêtre de TOUS les chantiers de ce service du plan : la règle météo
    est celle du service, et la prévision d'un secteur voisin ne dit pas le contraire (prudence). Un chantier sans
    service ne perd que le jour de son propre créneau. Rend ``{"chantiers", "intervention_ids", "exclues",
    "jours_retires"}`` : ``chantiers`` au format de l'argument de ``m4_proposer_cedule`` (``intervention_id``,
    ``fenetre``, ``creneau_fige``) ; ``exclues`` : les chantiers qu'on ne peut pas replacer, avec la raison
    (``creneau_fige`` : un créneau déjà confirmé au client tombe sur un jour fermé, il ne se déplace jamais tout seul ;
    ``sans_jour_restant`` : sa fenêtre n'a plus de jour). Aucun chantier n'est modifié en place."""
    par_service = {}
    propres = {}
    for bloque in bloques:
        identifiant, jour = bloque["intervention_id"], bloque["jour"]
        service = service_de.get(identifiant)
        if service is None:
            propres.setdefault(identifiant, set()).add(jour)
        else:
            par_service.setdefault(service, set()).add(jour)
    chantiers, exclues = [], []
    for chantier in chantiers_du_plan:
        identifiant = chantier["id"]
        retires = par_service.get(service_de.get(identifiant), set()) | propres.get(identifiant, set())
        fenetre = chantier["fenetre"]
        jours = [jour for jour in fenetre["jours"] if jour not in retires]
        fige = chantier["creneau_fige"]
        if retires & set(fenetre["jours"]) or (fige is not None and fige["jour"] in retires):
            if fige is not None and fige["jour"] in retires:
                exclues.append(
                    {
                        "intervention_id": identifiant,
                        "raison": RAISON_CRENEAU_FIGE,
                        "detail": f"le créneau confirmé au client (jour {fige['jour']}) tombe sur un jour fermé par la "
                        "météo : un créneau confirmé ne se déplace jamais tout seul, un report (m4_signaler_report) se "
                        "décide",
                    }
                )
                continue
            if not jours:
                exclues.append(
                    {
                        "intervention_id": identifiant,
                        "raison": RAISON_SANS_JOUR_RESTANT,
                        "detail": "la fenêtre du client n'a plus aucun jour une fois retirés ceux que la météo ferme : "
                        "élargir la fenêtre, ou céduler plus tard",
                    }
                )
                continue
        chantiers.append(
            {
                "intervention_id": identifiant,
                "fenetre": {"jours": jours, "debut_min": fenetre["debut_min"], "fin_min": fenetre["fin_min"]},
                "creneau_fige": None if fige is None else dict(fige),
            }
        )
    jours_retires = {service: sorted(jours) for service, jours in sorted(par_service.items())}
    return {
        "chantiers": chantiers,
        "intervention_ids": [chantier["intervention_id"] for chantier in chantiers],
        "exclues": exclues,
        "jours_retires": jours_retires,
    }
