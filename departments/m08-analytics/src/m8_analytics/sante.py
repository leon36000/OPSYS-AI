"""Score de santé de l'entreprise (M8.11) : un indice composite TRANSPARENT, sourcé, qui refuse de noter dans le doute.

Module PUR (ADR-0009) : aucun import d'``opsys``, aucune horloge. Le score est calculé par ce code en ``Decimal`` à
partir
de mesures du catalogue (``moteur_mesures``), jamais par un modèle. Définition : ``definitions/m8-sante.v1.yaml``.

Transparence : chaque composante (finance, ventes, opérations, qualité, clientèle) montre ses indicateurs, leur valeur
exacte, leur source, leur fraîcheur, les bornes utilisées, le score de l'indicateur, la pondération déclarée et la
contribution en points au score global. La somme des contributions EST le score global (à l'arrondi du centième près) ;
rien n'est caché dans un résidu.

Refus plutôt que faux score. Une composante est ``indeterminee`` — et le score global avec elle — si l'un de ses
indicateurs est : non calculable (mesure manquante), périmé ou de fraîcheur inconnue (``fraicheur_mesures``), ou sans
bornes déclarées par le propriétaire. Aucune composante inconnue n'est remplacée par une moyenne, un zéro ou un « comme
l'an passé ». Le résultat dit alors QUOI corriger (``manques``) et montre quand même les composantes déterminables.

Échelle d'un indicateur : la borne « pire » vaut 0 point, la borne « cible » 100 points, interpolation linéaire bornée à
[0, 100]. Les bornes sont des seuils d'affaires déclarés par le propriétaire (configuration), jamais inventés ici. Les
pondérations viennent de la définition (entiers, somme 100) et sont montrées avec le fait qu'elles ont été validées ou
non.

Historique : ``ligne_historique`` rend l'enregistrement append-only que ``outils.py`` range au registre
``historique_sante`` ; ``calibrer`` mesure le comportement du score (ordre, bornes, sensibilité) sur des entreprises
FICTIVES dont l'état est connu — sans quoi un score n'est qu'un chiffre.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import yaml

from . import catalogue_mesures, encodage, entonnoir, fraicheur_mesures, nombres, qualite_mesures

SCHEMA = "opsys.m8.sante/v1"
CLE_CONFIGURATION = "sante"
_CHEMIN = Path(__file__).resolve().parents[2] / "definitions" / "m8-sante.v1.yaml"
_CENT = Decimal("100")
_ZERO = Decimal("0")
_CENTIEME = Decimal("0.01")
_CLES_RACINE = frozenset({"schema", "version", "declare_par", "mention", "composantes"})
_CLES_COMPOSANTE = frozenset({"id", "libelle", "poids", "indicateurs"})
_CLES_INDICATEUR = frozenset({"mesure", "poids", "proxy"})

STATUT_DETERMINE = "determine"
STATUT_INDETERMINE = "indetermine"

RAISON_MESURE_MANQUANTE = "mesure_manquante"
RAISON_QUALITE_ECHEC = "qualite_echec"
RAISON_MESURE_PERIMEE = "mesure_perimee"
RAISON_FRAICHEUR_INCONNUE = "fraicheur_inconnue"
RAISON_BORNES_A_CONFIGURER = "bornes_a_configurer"
RAISON_BORNES_INVALIDES = "bornes_invalides"

REJ_SANTE_INVALIDE = "REJ-SANTE-INVALIDE"
REJ_SANTE_BORNES_INVALIDES = "REJ-SANTE-BORNES-INVALIDES"

_ECHELLE = "0 à 100 (100 = au mieux de ce que le propriétaire a déclaré comme cible)"


class SanteRefusee(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code} : {detail}")
        self.code = code
        self.detail = detail


def _refus(detail: str) -> SanteRefusee:
    return SanteRefusee(REJ_SANTE_INVALIDE, detail)


# ---------------------------------------------------------------------------
# Définition
# ---------------------------------------------------------------------------
def _somme_100(valeurs: list[int], nom: str) -> None:
    if sum(valeurs) != 100:
        raise _refus(f"{nom} : les pondérations doivent totaliser 100 (total {sum(valeurs)})")


def valider_definition(brut: Any, catalogue: dict[str, Any]) -> dict[str, Any]:
    """La définition validée (fail-closed). Chaque indicateur nomme une mesure du catalogue ET de sens connu
    (``plus_est_mieux`` ou ``moins_est_mieux`` : une mesure neutre n'a pas de « mieux »)."""
    if not isinstance(brut, dict) or brut.get("schema") != SCHEMA:
        raise _refus(f"schema attendu : {SCHEMA}")
    if set(brut) - _CLES_RACINE or {"version", "composantes", "declare_par", "mention"} - set(brut):
        raise _refus("clés de la racine inconnues ou manquantes")
    if isinstance(brut["version"], bool) or not isinstance(brut["version"], int) or brut["version"] < 1:
        raise _refus("version : entier positif attendu")
    entrees = catalogue_mesures.par_identifiant(catalogue)
    composantes = brut["composantes"]
    if not isinstance(composantes, list) or not composantes:
        raise _refus("composantes : liste non vide attendue")
    vues: set[str] = set()
    mesures_vues: set[str] = set()
    resultat: list[dict[str, Any]] = []
    for composante in composantes:
        if not isinstance(composante, dict) or set(composante) != _CLES_COMPOSANTE:
            raise _refus("chaque composante = {id, libelle, poids, indicateurs} exactement")
        cid = composante["id"]
        if not isinstance(cid, str) or not cid or cid in vues:
            raise _refus(f"composante : identifiant illisible ou en double ({cid!r})")
        vues.add(cid)
        poids = composante["poids"]
        if isinstance(poids, bool) or not isinstance(poids, int) or not 1 <= poids <= 100:
            raise _refus(f"{cid} : poids : entier de 1 à 100")
        indicateurs = composante["indicateurs"]
        if not isinstance(indicateurs, list) or not indicateurs:
            raise _refus(f"{cid} : indicateurs : liste non vide attendue")
        liste: list[dict[str, Any]] = []
        for indicateur in indicateurs:
            if (
                not isinstance(indicateur, dict)
                or set(indicateur) - _CLES_INDICATEUR
                or not {"mesure", "poids"} <= set(indicateur)
            ):
                raise _refus(f"{cid} : chaque indicateur = {{mesure, poids, [proxy]}}")
            mesure, poids_i = indicateur["mesure"], indicateur["poids"]
            if mesure not in entrees:
                raise _refus(f"{cid} : la mesure {mesure!r} n'est pas au catalogue fermé")
            if entrees[mesure]["sens"] == "neutre":
                raise _refus(f"{cid} : {mesure} est neutre : sans « mieux » défini, elle ne peut pas être notée")
            if mesure in mesures_vues:
                raise _refus(f"{mesure} figure dans deux indicateurs : une mesure compte une seule fois")
            mesures_vues.add(mesure)
            if isinstance(poids_i, bool) or not isinstance(poids_i, int) or not 1 <= poids_i <= 100:
                raise _refus(f"{cid} : poids de {mesure} : entier de 1 à 100")
            proxy = indicateur.get("proxy", False)
            if not isinstance(proxy, bool):
                raise _refus(f"{cid} : proxy de {mesure} : booléen attendu")
            liste.append({"mesure": mesure, "poids": poids_i, "proxy": proxy})
        _somme_100([i["poids"] for i in liste], cid)
        resultat.append({"id": cid, "libelle": str(composante["libelle"]), "poids": poids, "indicateurs": liste})
    _somme_100([c["poids"] for c in resultat], "composantes")
    definition = {
        "version": brut["version"],
        "declare_par": str(brut["declare_par"]),
        "mention": str(brut["mention"]),
        "composantes": resultat,
    }
    definition["version_definition"] = encodage.empreinte(definition)
    return definition


def charger(catalogue: dict[str, Any], chemin: str | Path | None = None) -> dict[str, Any]:
    fichier = Path(chemin) if chemin is not None else _CHEMIN
    try:
        brut = yaml.safe_load(fichier.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as erreur:
        raise _refus(f"{fichier} illisible ({erreur})") from erreur
    return valider_definition(brut, catalogue)


# ---------------------------------------------------------------------------
# Configuration du propriétaire : bornes et validation des pondérations
# ---------------------------------------------------------------------------
def lire_configuration(configuration: Any, definition: dict[str, Any]) -> dict[str, Any]:
    """``configuration.sante`` = ``{bornes: {mesure: {pire, cible}}, ponderations_validees_par: texte}``. Rend
    ``{bornes, invalides, ignorees, ponderations_validees_par}`` : une borne illisible est DITE (jamais corrigée, jamais
    remplacée par une valeur par défaut), une clé qui n'est pas un indicateur aussi."""
    indicateurs = {i["mesure"] for c in definition["composantes"] for i in c["indicateurs"]}
    lues: dict[str, dict[str, Decimal]] = {}
    invalides: list[dict[str, str]] = []
    ignorees: list[str] = []
    validees_par = None
    brut = configuration.get("bornes") if isinstance(configuration, dict) else None
    if isinstance(configuration, dict):
        validees_par = configuration.get("ponderations_validees_par")
        if not isinstance(validees_par, str) or not validees_par.strip():
            validees_par = None
    if isinstance(brut, dict):
        for mesure, bornes in brut.items():
            if mesure not in indicateurs:
                ignorees.append(str(mesure))
                continue
            pire = (
                nombres.decimal_lu(bornes.get("pire"))
                if isinstance(bornes, dict) and not isinstance(bornes.get("pire"), bool)
                else None
            )
            cible = (
                nombres.decimal_lu(bornes.get("cible"))
                if isinstance(bornes, dict) and not isinstance(bornes.get("cible"), bool)
                else None
            )
            if not isinstance(bornes, dict) or set(bornes) != {"pire", "cible"} or pire is None or cible is None:
                invalides.append({"metric_id": mesure, "raison": "bornes = {pire, cible}, deux nombres finis"})
            elif pire == cible:
                invalides.append({"metric_id": mesure, "raison": "pire et cible ne peuvent pas être égaux"})
            else:
                lues[mesure] = {"pire": pire, "cible": cible}
    return {
        "bornes": lues,
        "invalides": invalides,
        "ignorees": sorted(ignorees),
        "ponderations_validees_par": validees_par,
    }


# ---------------------------------------------------------------------------
# Calcul
# ---------------------------------------------------------------------------
def _arrondi(valeur: Decimal) -> Decimal:
    return valeur.quantize(_CENTIEME, rounding=ROUND_HALF_UP)


def score_indicateur(valeur: Decimal, sens: str, pire: Decimal, cible: Decimal) -> Decimal:
    """Points de 0 à 100 d'une valeur entre les bornes (interpolation linéaire bornée). Les bornes doivent aller dans le
    sens du « mieux » du catalogue : pour ``plus_est_mieux`` pire < cible, pour ``moins_est_mieux`` pire > cible."""
    if (sens == "plus_est_mieux") != (pire < cible):
        raise SanteRefusee(
            REJ_SANTE_BORNES_INVALIDES, f"bornes à contre-sens de « {sens} » (pire {pire}, cible {cible})"
        )
    avancement = (valeur - pire) / (cible - pire)
    return max(_ZERO, min(_CENT, avancement * _CENT))


def _indicateur(
    ind: dict[str, Any],
    mesure: dict[str, Any],
    bornes: dict[str, dict[str, Decimal]],
    invalides: set[str],
) -> dict[str, Any]:
    fraicheur = mesure["fraicheur"]
    ligne: dict[str, Any] = {
        "metric_id": ind["mesure"],
        "nom": mesure["nom"],
        "poids": ind["poids"],
        "proxy": ind["proxy"],
        "valeur": mesure["valeur"],
        "unite": mesure["unite"],
        "sens": mesure["sens"],
        "source": mesure["source"],
        "proprietaire": mesure["proprietaire"],
        "version_definition": mesure["version_definition"],
        "dernier_fait_le": mesure["dernier_fait_le"],
        "fraicheur": fraicheur["statut"],
        "bornes": None,
        "score": None,
        "raison": None,
        "detail": None,
    }
    if qualite_mesures.en_echec(mesure):
        # Une donnée FAUSSE n'est pas une donnée manquante : la composante est indéterminée pour une raison de qualité,
        # dite comme telle (pas de note sur une valeur que le contrôle de qualité a bloquée).
        ligne.update(raison=RAISON_QUALITE_ECHEC, detail=mesure["detail"])
        return ligne
    if mesure["statut"] != entonnoir.STATUT_CALCULEE:
        ligne.update(raison=RAISON_MESURE_MANQUANTE, detail=mesure["detail"])
        return ligne
    if fraicheur["statut"] == fraicheur_mesures.STATUT_PERIME:
        ligne.update(raison=RAISON_MESURE_PERIMEE, detail=fraicheur["motif"])
        return ligne
    if not fraicheur["peut_etre_montree_comme_a_jour"]:
        ligne.update(raison=RAISON_FRAICHEUR_INCONNUE, detail=fraicheur["motif"])
        return ligne
    if ind["mesure"] in invalides:
        ligne.update(raison=RAISON_BORNES_INVALIDES, detail="les bornes déclarées sont illisibles")
        return ligne
    borne = bornes.get(ind["mesure"])
    if borne is None:
        ligne.update(
            raison=RAISON_BORNES_A_CONFIGURER,
            detail="bornes à configurer : le propriétaire déclare « pire » et « cible » (configuration.sante)",
        )
        return ligne
    valeur = nombres.decimal_lu(mesure["valeur"])
    if valeur is None:
        ligne.update(raison=RAISON_MESURE_MANQUANTE, detail="valeur illisible")
        return ligne
    try:
        points = score_indicateur(valeur, mesure["sens"], borne["pire"], borne["cible"])
    except SanteRefusee as refus:
        ligne.update(raison=RAISON_BORNES_INVALIDES, detail=refus.detail)
        return ligne
    ligne["bornes"] = {"pire": format(borne["pire"], "f"), "cible": format(borne["cible"], "f")}
    ligne["score"] = points
    return ligne


_LIBELLE_RAISON = {
    RAISON_MESURE_MANQUANTE: "mesure non calculable",
    RAISON_QUALITE_ECHEC: "contrôle de qualité en échec",
    RAISON_MESURE_PERIMEE: "mesure périmée",
    RAISON_FRAICHEUR_INCONNUE: "fraîcheur inconnue",
    RAISON_BORNES_A_CONFIGURER: "bornes à configurer",
    RAISON_BORNES_INVALIDES: "bornes invalides",
}


def evaluer(
    definition: dict[str, Any],
    mesures: list[dict[str, Any]],
    configuration: dict[str, Any],
) -> dict[str, Any]:
    """Le score de santé à partir des mesures lues AVEC leur fraîcheur (``lire_mesures_avec_fraicheur``) et de la
    configuration lue (``lire_configuration``). Déterministe ; ne lit rien d'autre."""
    par_id = {mesure["metric_id"]: mesure for mesure in mesures}
    invalides = {i["metric_id"] for i in configuration["invalides"]}
    composantes: list[dict[str, Any]] = []
    manques: list[dict[str, str]] = []
    for composante in definition["composantes"]:
        indicateurs = [
            _indicateur(i, par_id[i["mesure"]], configuration["bornes"], invalides) for i in composante["indicateurs"]
        ]
        inconnus = [i for i in indicateurs if i["score"] is None]
        if inconnus:
            for i in inconnus:
                manques.append(
                    {
                        "composante": composante["id"],
                        "metric_id": i["metric_id"],
                        "raison": i["raison"],
                        "detail": i["detail"] or "",
                    }
                )
            composantes.append(
                {
                    "id": composante["id"],
                    "libelle": composante["libelle"],
                    "poids": composante["poids"],
                    "statut": STATUT_INDETERMINE,
                    "score": None,
                    "contribution": None,
                    "indicateurs": indicateurs,
                    "explication": f"{composante['libelle']} : indéterminée — "
                    + " ; ".join(f"{i['nom']} : {_LIBELLE_RAISON[i['raison']]}" for i in inconnus)
                    + ".",
                }
            )
            continue
        score = sum((i["score"] * i["poids"] for i in indicateurs), _ZERO) / _CENT
        for i in indicateurs:
            i["contribution"] = format(_arrondi(i["score"] * i["poids"] / _CENT * composante["poids"] / _CENT), "f")
        composantes.append(
            {
                "id": composante["id"],
                "libelle": composante["libelle"],
                "poids": composante["poids"],
                "statut": STATUT_DETERMINE,
                "score": score,
                "contribution": score * composante["poids"] / _CENT,
                "indicateurs": indicateurs,
                "explication": f"{composante['libelle']} : {format(_arrondi(score), 'f')} / 100 — "
                + " ; ".join(
                    f"{i['nom']} {i['valeur']} (bornes {i['bornes']['pire']} → {i['bornes']['cible']}, "
                    f"{format(_arrondi(i['score']), 'f')} points, pondération {i['poids']} %)"
                    for i in indicateurs
                )
                + ".",
            }
        )
    determine = not manques
    score_global = sum((c["contribution"] for c in composantes), _ZERO) if determine else None
    for c in composantes:  # les Decimal deviennent du texte à la sortie : jamais un flottant
        if c["score"] is not None:
            c["score"] = format(_arrondi(c["score"]), "f")
            c["contribution"] = format(_arrondi(c["contribution"]), "f")
        for i in c["indicateurs"]:
            if i["score"] is not None:
                i["score"] = format(_arrondi(i["score"]), "f")
    return {
        "statut": STATUT_DETERMINE if determine else STATUT_INDETERMINE,
        "score": format(_arrondi(score_global), "f") if score_global is not None else None,
        "echelle": _ECHELLE,
        "explication": (
            f"Score de santé : {format(_arrondi(score_global), 'f')} / 100."
            if determine
            else f"Score INDÉTERMINÉ : {len(manques)} indicateur(s) ne permettent pas de noter. "
            "Aucun score n'est donné plutôt qu'un faux score."
        ),
        "composantes": composantes,
        "manques": manques,
        "ponderations": {
            "declaree_par": definition["declare_par"],
            "validee_par": configuration["ponderations_validees_par"],
            "validee": configuration["ponderations_validees_par"] is not None,
            "composantes": {c["id"]: c["poids"] for c in definition["composantes"]},
        },
        "configuration": {"bornes_invalides": configuration["invalides"], "cles_ignorees": configuration["ignorees"]},
        "version_definition": definition["version_definition"],
        "mention": definition["mention"],
    }


# ---------------------------------------------------------------------------
# Historique
# ---------------------------------------------------------------------------
def ligne_historique(resultat: dict[str, Any], *, maintenant: str, empreinte_registres: str) -> dict[str, Any]:
    """L'enregistrement APPEND-ONLY d'une évaluation : instant, statut, score (ou ``None``), score par composante
    (``None`` si indéterminée), version de la définition et empreinte des registres lus. Aucune valeur de mesure :
    l'historique garde le jugement, pas les données."""
    if entonnoir.instant_lu(maintenant) is None:
        raise ValueError(f"{fraicheur_mesures.REJ_MAINTENANT_INVALIDE} : maintenant illisible ({maintenant!r})")
    return {
        "type_entree": "sante",
        "maintenant": maintenant,
        "statut": resultat["statut"],
        "score": resultat["score"],
        "composantes": {c["id"]: c["score"] for c in resultat["composantes"]},
        "version_definition": resultat["version_definition"],
        "empreinte_registres": empreinte_registres,
        "ponderations_validees": resultat["ponderations"]["validee"],
    }


def meme_jugement(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Deux lignes d'historique disent le même jugement (mêmes registres, même définition, mêmes scores) : la seconde
    n'est pas rangée (pas de bruit)."""
    cles = ("statut", "score", "composantes", "version_definition", "empreinte_registres", "ponderations_validees")
    return all(a.get(cle) == b.get(cle) for cle in cles)


# ---------------------------------------------------------------------------
# Calibration et sensibilité, sur des entreprises FICTIVES
# ---------------------------------------------------------------------------
def _perturber(mesures: list[dict[str, Any]], metric_id: str, delta: Decimal) -> list[dict[str, Any]]:
    resultat = []
    for mesure in mesures:
        if mesure["metric_id"] == metric_id and mesure["valeur"] is not None:
            lue = nombres.decimal_lu(mesure["valeur"])
            assert lue is not None
            resultat.append({**mesure, "valeur": format(lue + delta, "f")})
        else:
            resultat.append(mesure)
    return resultat


def _score_global(resultat: dict[str, Any]) -> Decimal | None:
    return None if resultat["score"] is None else Decimal(resultat["score"])


def calibrer(
    definition: dict[str, Any],
    configuration: dict[str, Any],
    scenarios: dict[str, list[dict[str, Any]]],
    *,
    pas_pct: int = 10,
    ecart_poids: int = 5,
) -> dict[str, Any]:
    """Mesure le comportement du score sur des scénarios dont l'état est connu : ``scenarios`` = ``{nom: mesures avec
    fraîcheur}``. Rend :

    * ``scores`` : le score (ou ``None``) et le statut de chaque scénario ;
    * ``sensibilite_mesures`` : pour chaque indicateur et chaque scénario déterminé, de combien de points le score
    global
      bouge quand la mesure se déplace de ``pas_pct`` % de l'étendue pire→cible dans le sens du mieux (déplacement
      exact,
      recalcul complet) ;
    * ``sensibilite_ponderations`` : pour chaque paire de composantes, le score de chaque scénario quand ``ecart_poids``
      points de pondération passent de l'une à l'autre, et si l'ORDRE des scénarios déterminés change.

    Aucun scénario n'est ajusté pour « bien » sortir : la mesure dit ce que le score fait, y compris ses défauts."""
    pas = Decimal(pas_pct) / _CENT
    base = {nom: evaluer(definition, mesures, configuration) for nom, mesures in scenarios.items()}
    scores = {nom: {"statut": r["statut"], "score": r["score"]} for nom, r in base.items()}
    sensibilite_mesures: list[dict[str, Any]] = []
    for composante in definition["composantes"]:
        for ind in composante["indicateurs"]:
            borne = configuration["bornes"].get(ind["mesure"])
            if borne is None:
                continue
            etendue = borne["cible"] - borne["pire"]  # signé : positif si le mieux est vers le haut
            for nom, mesures in scenarios.items():
                avant = _score_global(base[nom])
                if avant is None:
                    continue
                apres = _score_global(
                    evaluer(definition, _perturber(mesures, ind["mesure"], etendue * pas), configuration)
                )
                sensibilite_mesures.append(
                    {
                        "scenario": nom,
                        "metric_id": ind["mesure"],
                        "composante": composante["id"],
                        "points_globaux": format(_arrondi(apres - avant), "f") if apres is not None else None,
                    }
                )
    determines = {nom: Decimal(r["score"]) for nom, r in base.items() if r["score"] is not None}
    ordre_base = sorted(determines, key=lambda nom: (-determines[nom], nom))
    sensibilite_ponderations: list[dict[str, Any]] = []
    composantes = definition["composantes"]
    for i, a in enumerate(composantes):
        for b in composantes[i + 1 :]:
            for donneur, receveur in ((a, b), (b, a)):
                if donneur["poids"] - ecart_poids < 1:
                    continue
                variante = {
                    **definition,
                    "composantes": [
                        {
                            **c,
                            "poids": c["poids"] - ecart_poids
                            if c["id"] == donneur["id"]
                            else c["poids"] + ecart_poids
                            if c["id"] == receveur["id"]
                            else c["poids"],
                        }
                        for c in composantes
                    ],
                }
                nouveaux = {
                    nom: _score_global(evaluer(variante, mesures, configuration)) for nom, mesures in scenarios.items()
                }
                valides = {nom: s for nom, s in nouveaux.items() if s is not None}
                ordre = sorted(valides, key=lambda nom: (-valides[nom], nom))
                sensibilite_ponderations.append(
                    {
                        "de": donneur["id"],
                        "vers": receveur["id"],
                        "ecart_points": ecart_poids,
                        "scores": {nom: format(_arrondi(s), "f") for nom, s in valides.items()},
                        "ordre_inchange": ordre == ordre_base,
                    }
                )
    return {
        "pas_pct": pas_pct,
        "ecart_poids": ecart_poids,
        "scores": scores,
        "ordre": ordre_base,
        "sensibilite_mesures": sensibilite_mesures,
        "sensibilite_ponderations": sensibilite_ponderations,
        "fictif": True,
    }


__all__ = [
    "CLE_CONFIGURATION",
    "RAISON_BORNES_A_CONFIGURER",
    "RAISON_BORNES_INVALIDES",
    "RAISON_FRAICHEUR_INCONNUE",
    "RAISON_MESURE_MANQUANTE",
    "RAISON_MESURE_PERIMEE",
    "RAISON_QUALITE_ECHEC",
    "REJ_SANTE_BORNES_INVALIDES",
    "REJ_SANTE_INVALIDE",
    "SCHEMA",
    "STATUT_DETERMINE",
    "STATUT_INDETERMINE",
    "SanteRefusee",
    "calibrer",
    "charger",
    "evaluer",
    "lire_configuration",
    "ligne_historique",
    "meme_jugement",
    "score_indicateur",
    "valider_definition",
]
