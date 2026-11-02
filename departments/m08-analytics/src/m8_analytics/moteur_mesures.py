"""Moteur de lecture des mesures du catalogue : UN seul endroit où les registres deviennent des mesures d'entreprise.

Module PUR (ADR-0009) : aucun import d'``opsys``, aucune horloge. Les wallboards (M8.8), le score de santé (M8.11), le
copilote (M8.12), l'entrepôt (M8.2), le pont BI (M8.14) et la mémoire (M8.18) lisent TOUS les mesures par ici : une
mesure
n'a donc qu'une valeur, qu'une provenance et qu'une fraîcheur, quelle que soit la surface qui la montre.

Il ne calcule rien lui-même : il appelle les moteurs gouvernés qui existent (``entonnoir.mesurer``,
``contenus.situation``,
``synthese.mesurer``) sur les faits des registres que ``outils.py`` lui passe, puis joint au résultat ce que le
catalogue
déclare (domaine, sens, sensibilité, fraîcheur attendue) et l'instant du dernier fait qui porte la mesure.

Forme d'une mesure lue (``MesureLue``) : ``metric_id``, ``nom``, ``unite``, ``proprietaire``, ``domaine``, ``sens``,
``sensibilite``, ``statut`` (``calculee`` ou ``non_calculable``), ``valeur`` (texte décimal, ``None`` si non
calculable),
``manque`` et ``detail`` (ce qu'il faut fournir, et de qui), ``entrees`` lues, ``source`` (la source gouvernée),
``version_definition``, ``dernier_fait_le`` (l'instant du fait le plus récent qui porte la mesure, ``None`` si aucun) et
``fraicheur_declaree`` (la fenêtre ou ``terminale`` du catalogue), ``couverture`` (``complete``, ``partielle`` avec ce
qui est couvert et ce qui ne l'est pas, ou ``inconnue`` pour une mesure non calculable) et ``fenetre_source_s`` (la
fenêtre de fraîcheur que le département SOURCE déclare lui-même, ``None`` sinon : ``fraicheur_mesures`` retient la
plus stricte des fenêtres). Les mesures interdépartements (``mesures_interdepartements``, ``mesures_constats``) lisent
aussi le registre
``operations`` des constats de M7, M5, M3, M6, M4, M2 et M1.
"""

from __future__ import annotations

from typing import Any

from . import catalogue_mesures, contenus, encodage, entonnoir, mesures_interdepartements, synthese

_CLES_REGISTRES = ("chantier", "entonnoir", "contenus", "cash_libre", "operations")
# Ce que le PROPRIÉTAIRE déclare et que M8 lit sans l'interpréter (D6 : la correspondance canal publicitaire -> sources
# UTM).
# Facultatif : un appelant qui n'en donne pas n'a rien déclaré, et les mesures qui en dépendent sont non calculables.
_CLES_FACULTATIVES = ("declarations",)

# Événements dont chaque métrique par contenu a besoin (l'instant du dernier fait vient du plus récent d'entre eux).
_EVENEMENTS_CONTENUS = {
    "m8_contenus_exportes": (contenus.EVENEMENT_CONTENU,),
    "m8_leads_par_contenu": (contenus.EVENEMENT_CONTENU, contenus.EVENEMENT_LEAD),
    "m8_devis_envoyes_par_contenu": (contenus.EVENEMENT_CONTENU, contenus.EVENEMENT_LEAD, "m3.devis_envoye"),
    "m8_devis_acceptes_par_contenu": (contenus.EVENEMENT_CONTENU, contenus.EVENEMENT_LEAD, "m3.devis_accepte"),
    "m8_impressions_par_contenu": (),
    "m8_clics_par_contenu": (),
}


def normaliser_registres(registres: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Les cinq registres de faits (et les déclarations du propriétaire, facultatives) sous forme de listes de faits
    (copie). Une clé inconnue ou un registre qui n'est pas une liste de faits est un refus : une lecture ne devine
    jamais
    un registre vide ; les déclarations absentes valent « rien déclaré »."""
    inconnues = set(registres) - set(_CLES_REGISTRES) - set(_CLES_FACULTATIVES)
    manquantes = set(_CLES_REGISTRES) - set(registres)
    if inconnues or manquantes:
        raise ValueError(
            f"REJ-MOTEUR-REGISTRES : clés inconnues {sorted(inconnues)} ou manquantes {sorted(manquantes)}"
        )
    normalises: dict[str, list[dict[str, Any]]] = {}
    for cle in (*_CLES_REGISTRES, *_CLES_FACULTATIVES):
        faits = registres.get(cle, []) if cle in _CLES_FACULTATIVES else registres[cle]
        if not isinstance(faits, (list, tuple)) or not all(isinstance(fait, dict) for fait in faits):
            raise ValueError(f"REJ-MOTEUR-REGISTRES : le registre {cle} doit être une liste de faits")
        normalises[cle] = [dict(fait) for fait in faits]
    return normalises


def empreinte_registres(registres: dict[str, Any]) -> str:
    """Empreinte déterministe du contenu des registres (déclarations du propriétaire comprises) : la même suite de
    faits donne la même empreinte, un fait
    de plus (ou de moins, ou changé) en donne une autre. C'est ce qui dit qu'un entrepôt construit est en retard."""
    lus = normaliser_registres(registres)
    return encodage.empreinte([lus[cle] for cle in (*_CLES_REGISTRES, *_CLES_FACULTATIVES)])


def _plus_recent(instants: list[str | None]) -> str | None:
    lus = [(entonnoir.instant_lu(texte), texte) for texte in instants if texte]
    lisibles = [(instant, texte) for instant, texte in lus if instant is not None]
    return max(lisibles, key=lambda paire: paire[0])[1] if lisibles else None


def _mesures_brutes(registres: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Toutes les mesures gouvernées, chacune avec ``dernier_fait_le``, dans l'ordre : entonnoir, contenus, synthèse."""
    brutes: list[dict[str, Any]] = []
    for mesure in entonnoir.mesurer(registres["entonnoir"], registres["chantier"], entonnoir.charger_definitions()):
        mesure["dernier_fait_le"] = entonnoir.dernier_fait_le(registres["entonnoir"], mesure["metric_id"])
        brutes.append(mesure)
    situation = contenus.situation(registres["contenus"], registres["entonnoir"], contenus.charger_definitions())
    instants = {ligne["evenement"]: ligne["dernier_fait_le"] for ligne in situation["sources"]}
    for mesure in situation["mesures"]:
        evenements = _EVENEMENTS_CONTENUS.get(mesure["metric_id"], ())
        mesure["dernier_fait_le"] = _plus_recent([instants.get(evenement) for evenement in evenements])
        brutes.append(mesure)
    fuseau = synthese.fuseau_declare(registres.get("declarations", []))
    brutes.extend(
        synthese.mesurer(registres["chantier"], registres["cash_libre"], synthese.charger_definitions(), fuseau)
    )
    brutes.extend(mesures_interdepartements.mesurer(registres, mesures_interdepartements.charger_definitions()))
    return brutes


def lire(registres: dict[str, Any], catalogue: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Les mesures du catalogue, dans l'ordre du catalogue, d'après les faits des registres. Lecture pure : rien n'est
    écrit, rien n'est publié. Une mesure du catalogue qu'aucun moteur ne produit est non calculable, nommément (jamais
    absente en silence) ; une mesure produite que le catalogue n'a pas n'est pas montrée."""
    catalogue = catalogue if catalogue is not None else catalogue_mesures.charger()
    lus = normaliser_registres(registres)
    brutes = {mesure["metric_id"]: mesure for mesure in _mesures_brutes(lus)}
    resultat: list[dict[str, Any]] = []
    for entree in catalogue["mesures"]:
        brute = brutes.get(entree["metric_id"])
        if brute is None:
            brute = {
                "statut": entonnoir.STATUT_NON_CALCULABLE,
                "valeur": None,
                "entrees": {},
                "source": "",
                "detail": "non calculable, manque calcul (aucun moteur ne produit cette mesure)",
                "manque": [{"champ": "calcul", "source": "M8", "raison": "aucun moteur ne produit cette mesure"}],
                "dernier_fait_le": None,
            }
        couverture = brute.get("couverture")
        if couverture is None:
            couverture = {"etat": "complete" if brute["statut"] == entonnoir.STATUT_CALCULEE else "inconnue"}
        resultat.append(
            {
                "metric_id": entree["metric_id"],
                "nom": entree["nom"],
                "unite": entree["unite"],
                "proprietaire": entree["proprietaire"],
                "domaine": entree["domaine"],
                "sens": entree["sens"],
                "sensibilite": entree["sensibilite"],
                "statut": brute["statut"],
                "valeur": brute["valeur"],
                "manque": brute["manque"],
                "detail": brute["detail"],
                "entrees": brute["entrees"],
                "source": brute["source"],
                "version_definition": entree["version_definition"],
                "dernier_fait_le": brute["dernier_fait_le"],
                "fraicheur_declaree": dict(entree["fraicheur"]),
                "couverture": couverture,
                "fenetre_source_s": brute.get("fenetre_source_s"),
            }
        )
    return resultat


__all__ = ["empreinte_registres", "lire", "normaliser_registres"]
