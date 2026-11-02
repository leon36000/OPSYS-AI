"""Actions de croissance ORGANIQUES dérivées des observations déclarées (formats gagnants, créneaux, séries).

Remplace le « poursuivre la mesure » générique du plan à 30 jours : quand les données existent, le plan dit CE QUE les
observations montrent et l'action légitime qui s'en suit ; sinon il dit EXACTEMENT ce qui manque. Jamais d'achat
d'abonnés,
de faux engagement, de spam, de DM massif ni d'automatisation contre les conditions d'une plateforme :
`verifier_legitimite`
refuse toute action qui en parle (défense en profondeur contre un libellé de campagne piégé).

Convention de lecture : une observation (`plateforme`, `campagne`, `metrique`, `valeur`, `unite`) est rangée dans une
dimension quand son champ `campagne` commence par `format:`, `creneau:` ou `serie:` (« format:reel », «
creneau:mardi-19h »,
« serie:avant-apres »). Les observations sans cette étiquette ne servent pas à comparer : elles restent des
observations.

Règle de décision (déterministe, observationnelle, jamais causale) : dans une même (plateforme, dimension, métrique,
unité),
au moins `GROUPES_MIN` étiquettes ayant chacune au moins `OBSERVATIONS_MIN` observations ; l'étiquette de plus haute
moyenne est
« gagnante » si elle dépasse la deuxième d'au moins `ECART_MIN_PCT` %. Sinon : pas de gagnant net, et c'est dit.

Module pur.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

GROUPES_MIN = 2
OBSERVATIONS_MIN = 3
ECART_MIN_PCT = Decimal("20")
DIMENSIONS = ("format", "creneau", "serie")
# Métriques dont « plus haut = mieux » est sans équivoque. Une autre métrique ne sert pas à classer.
METRIQUES_PLUS_EST_MIEUX = frozenset(
    {
        "taux_engagement",
        "engagements",
        "portee",
        "impressions",
        "clics",
        "visites",
        "abonnes",
        "abonnes_gagnes",
        "vues",
        "partages",
        "commentaires",
        "enregistrements",
        "retention_video_pct",
    }
)
# Tactiques qu'OPSYS ne propose JAMAIS (DEFINITION-PRODUIT §7 M7.4 : croissance organique, conforme, mesurable).
INTERDITS_CROISSANCE = (
    "acheter des abonnes",
    "achat d'abonnes",
    "achat de followers",
    "faux like",
    "faux commentaire",
    "faux engagement",
    "faux abonne",
    "pod d'engagement",
    "pods d'engagement",
    "spam",
    "message prive massif",
    "dm massif",
    "envoi massif",
    "bot",
    "automatisation contre",
    "scraping",
    "contourner les limites",
)
_ETIQUETTE = re.compile(r"^(format|creneau|serie):([^:]{1,40})$")
_LIBELLE_SUR = re.compile(r"^[a-z0-9àâäçéèêëîïôöùûüœ _-]{1,40}$")


def _plie(texte: str) -> str:
    decompose = unicodedata.normalize("NFD", texte.casefold())
    return "".join(c for c in decompose if not unicodedata.combining(c)).replace("’", "'")


def verifier_legitimite(action: str) -> bool:
    """Vrai si l'action ne contient aucune tactique interdite (achat d'abonnés, faux engagement, spam…)."""
    plie = _plie(action)
    return not any(
        re.search(r"(?<![a-z0-9])" + re.escape(mot) + r"s?(?![a-z0-9])", plie) for mot in INTERDITS_CROISSANCE
    )


def etiquette(campagne: str) -> tuple[str, str] | None:
    """`(dimension, libellé)` si `campagne` porte une étiquette de comparaison au libellé sûr, sinon `None`."""
    trouve = _ETIQUETTE.match(campagne.strip()) if isinstance(campagne, str) else None
    if trouve is None:
        return None
    libelle = trouve.group(2).strip()
    if not _LIBELLE_SUR.match(libelle.casefold()):
        return None
    return trouve.group(1), libelle


def _moyenne(valeurs: list[Decimal]) -> Decimal:
    return (sum(valeurs, Decimal(0)) / len(valeurs)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _decimal(valeur: Any) -> Decimal | None:
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)):
        return None
    try:
        d = Decimal(str(valeur))
    except Exception:  # noqa: BLE001
        return None
    return d if d.is_finite() else None


def analyser(observations: list[dict[str, Any]]) -> dict[str, Any]:
    """`{actions, manques}` : les actions organiques que les observations permettent, et ce qui manque pour les autres.

    Chaque action : `{plateforme, dimension, metrique, gagnant, action, observations_source, hypotheses, ecart_pct}`.
    Chaque manque : une phrase qui dit quoi saisir. Ordre stable (plateforme, dimension, métrique)."""
    groupes: dict[tuple[str, str, str, str], dict[str, list[tuple[Decimal, str]]]] = {}
    for obs in observations:
        marque = etiquette(obs.get("campagne", ""))
        valeur = _decimal(obs.get("valeur"))
        if marque is None or valeur is None or obs.get("metrique") not in METRIQUES_PLUS_EST_MIEUX:
            continue
        cle = (obs["plateforme"], marque[0], obs["metrique"], obs["unite"])
        groupes.setdefault(cle, {}).setdefault(marque[1], []).append((valeur, obs["observation_id"]))
    actions: list[dict[str, Any]] = []
    manques: list[str] = []
    if observations and not groupes:
        manques.append(
            "aucune observation étiquetée (campagne « format:… », « creneau:… » ou « serie:… ») d'une métrique de "
            "performance connue : rien à comparer ; saisir au moins deux étiquettes avec trois observations chacune"
        )
    for cle in sorted(groupes):
        plateforme, dimension, metrique, unite = cle
        par_etiquette = groupes[cle]
        complets = {e: v for e, v in par_etiquette.items() if len(v) >= OBSERVATIONS_MIN}
        if len(complets) < GROUPES_MIN:
            detail = ", ".join(f"« {e} » {len(v)}/{OBSERVATIONS_MIN}" for e, v in sorted(par_etiquette.items()))
            manques.append(
                f"{plateforme}, {dimension}, {metrique} : au moins {GROUPES_MIN} étiquettes avec {OBSERVATIONS_MIN} "
                f"observations chacune pour comparer (actuellement {detail}) ; saisir les observations manquantes"
            )
            continue
        moyennes = sorted(((_moyenne([x for x, _ in v]), e) for e, v in complets.items()), key=lambda p: (-p[0], p[1]))
        (premiere, gagnant), (deuxieme, suivant) = moyennes[0], moyennes[1]
        ecart = (
            None if deuxieme <= 0 else ((premiere - deuxieme) / deuxieme * 100).quantize(Decimal("1"), ROUND_HALF_UP)
        )
        net = premiere > 0 and (deuxieme <= 0 or (premiere - deuxieme) / deuxieme * 100 >= ECART_MIN_PCT)
        if not net:
            manques.append(
                f"{plateforme}, {dimension}, {metrique} : écart inférieur à {ECART_MIN_PCT} % entre « {gagnant} » et "
                f"« {suivant} » : pas de gagnant net, poursuivre la collecte avec des observations de plus"
            )
            continue
        sources = sorted(i for _, i in complets[gagnant]) + sorted(i for _, i in complets[suivant])
        texte = _texte_action(dimension, plateforme, gagnant, suivant, metrique, unite, premiere, deuxieme)
        if not verifier_legitimite(texte):  # défense en profondeur : ne devrait jamais arriver
            manques.append(f"{plateforme}, {dimension} : action refusée par la garde de légitimité")
            continue
        actions.append(
            {
                "plateforme": plateforme,
                "dimension": dimension,
                "metrique": metrique,
                "gagnant": gagnant,
                "action": texte,
                "observations_source": sources,
                "hypotheses": ["observation de la période passée : aucune causalité n'est établie"],
                "ecart_pct": None if ecart is None else int(ecart),
            }
        )
    return {"actions": actions, "manques": manques}


def _texte_action(
    dimension: str,
    plateforme: str,
    gagnant: str,
    suivant: str,
    metrique: str,
    unite: str,
    premiere: Decimal,
    deuxieme: Decimal,
) -> str:
    mesure = f"{metrique} moyen de {premiere} {unite} contre {deuxieme} {unite} pour « {suivant} »"
    if dimension == "format":
        return f"Sur {plateforme}, produire davantage de contenus au format « {gagnant} » (organique) : {mesure}."
    if dimension == "creneau":
        return f"Sur {plateforme}, publier de préférence au créneau « {gagnant} » (organique) : {mesure}."
    return f"Sur {plateforme}, poursuivre la série « {gagnant} » (organique) : {mesure}."
