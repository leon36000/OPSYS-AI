"""Les outils de MESURE MARKETING de M7 : UTM normalisées, conversions hors ligne, conception et lecture de tests,
attribution.

Chaque fonction est une enveloppe mince : elle établit QUI appelle (la plateforme, jamais un argument), lit ou écrit
le registre durable de M7 et appelle la fonction pure de `mesure/`. Registres (journaux append-only à chaîne de
hachage de `opsys.stockage`) : `conversions_hors_ligne`, `plans_tests_marketing`.

Niveaux (ADR-0009) :
  - normaliser des UTM, concevoir un test (reçu de calcul), analyser un résultat, rejouer un reçu : T0 (calcul pur) ;
  - importer des conversions hors ligne, préenregistrer un plan de test : T1/N2 (écriture interne, réversible dans ses
    effets : rien ne sort d'OPSYS ; l'import annonce un fait au bus pour M2 et M8) ;
  - lire l'attribution simple : T0, mais MÊME garde d'argent que `m7_lire_depenses_marketing` (la valeur des
  conversions et la
    dépense sont des chiffres financiers).
Aucun rôle d'appareil. Aucun outil n'affirme une causalité : un résultat sans plan préenregistré est « exploratoire ».
"""

from __future__ import annotations

from datetime import date
from typing import Any

from opsys import stockage
from opsys.outils import Autonomie, Niveau, Outil

from . import depenses_marketing
from .mesure import attribution_simple, experiences, utm
from .mesure import conversions as conv
from .mesure.verdicts import construire_verdict, refus_outil
from .publication_outils import _horodatage
from .usine import service as usine_service

NOM_ATTRIBUTION = "m7_lire_attribution_simple"
MOTEURS_CONCEPTION = (
    "taille_echantillon_deux_proportions",
    "puissance_deux_proportions",
    "duree_test_marche_arret",
    "plan_test_geographique",
)


def _journal(registre: tuple[str, str]):
    return stockage.maillons(*registre)


def normaliser_utm(
    urls: list[str] | None = None,
    source: str | None = None,
    medium: str | None = None,
    campagne: str | None = None,
    contenu: str | None = None,
) -> dict[str, Any]:
    """T0 : normalise des URL fournies en texte (jamais ouvertes) ou quatre paramètres isolés."""
    if (urls is None) == (source is None and medium is None and campagne is None and contenu is None):
        return refus_outil(
            construire_verdict(
                "REJ-MESURE-UTM-ENTREE-INVALIDE", detail="fournir exactement une liste d'urls OU des paramètres isolés"
            )
        )
    if urls is not None:
        try:
            return {"accepte": True, **utm.analyser_urls(urls)}
        except ValueError as exc:
            code, _, detail = str(exc).partition(" : ")
            return refus_outil(construire_verdict(code, detail=detail))
    return {"accepte": True, **utm.normaliser_parametres(source, medium, campagne, contenu)}


def importer_conversions_hors_ligne(conversions: list[dict[str, Any]], horodatage: str) -> dict[str, Any]:
    """N2 : importe un lot (200 au plus) de conversions hors ligne, tout ou rien ; annonce chacune au bus."""
    instant = _horodatage(horodatage)
    if isinstance(instant, dict):
        return instant
    return conv.importer(_journal(conv.REGISTRE), conversions, usine_service._qui_appelle()[0], instant[1])


def concevoir_test_marketing(moteur: str, entrees: dict[str, Any], parametres: dict[str, Any]) -> dict[str, Any]:
    """T0 : conçoit un test (taille, puissance, durée marche-arrêt, plan géographique) et rend le reçu rejouable."""
    if moteur not in MOTEURS_CONCEPTION:
        return refus_outil(
            construire_verdict("REJ-MESURE-MOTEUR-INCONNU", detail=f"moteur parmi {list(MOTEURS_CONCEPTION)}")
        )
    recu, verdict = experiences.produire(moteur, experiences.VERSION, entrees, parametres)
    if verdict is not None:
        return refus_outil(verdict)
    return {"accepte": True, "recu": recu, "resultat": recu["resultat"], "avertissements": recu["avertissements"]}


def enregistrer_plan_test_marketing(
    plan_id: str, recu: dict[str, Any], hypothese: str, metrique_primaire: str, debut: str, fin: str, horodatage: str
) -> dict[str, Any]:
    """N2 : préenregistre le plan d'un test (reçu de conception figé, hypothèse, métrique primaire, dates)."""
    instant = _horodatage(horodatage)
    if isinstance(instant, dict):
        return instant
    return experiences.enregistrer_plan(
        _journal(experiences.REGISTRE_PLANS),
        plan_id,
        recu,
        hypothese,
        metrique_primaire,
        debut,
        fin,
        usine_service._qui_appelle()[0],
        instant[1],
    )


def analyser_test_marketing(
    entrees: dict[str, Any],
    niveau: str = "0.95",
    plan_id: str | None = None,
    periode_donnees: dict[str, str] | None = None,
) -> dict[str, Any]:
    """T0 : différence test - témoin et intervalle ; `preenregistre` seulement avec un plan antérieur et la bonne "
    "période."""
    return experiences.analyser_resultat(
        _journal(experiences.REGISTRE_PLANS), entrees, niveau, plan_id, periode_donnees
    )


def lire_attribution_simple(debut: str, fin: str, niveau: str = "0.95") -> dict[str, Any]:
    """T0, garde d'argent : l'attribution descriptive des conversions hors ligne de la période, avec la dépense "
    "connue."""
    from . import outils as _o  # paresseux : outils.py importe ce module

    _o._autoriser_lecture_performance(NOM_ATTRIBUTION)
    try:
        jour_debut, jour_fin = date.fromisoformat(debut), date.fromisoformat(fin)
    except (TypeError, ValueError) as exc:
        raise ValueError("PERIODE_DATE_INVALIDE : debut et fin doivent être des dates ISO") from exc
    if jour_debut > jour_fin:
        raise ValueError("PERIODE_INVERSEE")
    courantes = conv.courantes(_journal(conv.REGISTRE))
    depenses = depenses_marketing.lire_depenses(jour_debut, jour_fin)
    resultat = attribution_simple.attribuer(
        conv.dans_la_periode(courantes, jour_debut, jour_fin), jour_debut, jour_fin, depenses, niveau
    )
    if resultat.get("accepte"):
        resultat["depenses"] = {
            "statut": depenses["statut"],
            "periode": depenses["periode"],
            "manque": depenses["manque"],
        }
    _o._autoriser_lecture_performance(NOM_ATTRIBUTION)
    return resultat


def rejouer_recu_mesure(recu: dict[str, Any]) -> dict[str, Any]:
    """T0 : vérifie les empreintes d'un reçu de mesure et le rejoue (reçu retouché, compact ou inconnu : refusé)."""
    resultat, verdict = experiences.rejouer(recu)
    if verdict is not None:
        return refus_outil(verdict)
    return {"accepte": True, **resultat}


def _objet(proprietes: dict[str, Any], requis: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": proprietes, "required": requis, "additionalProperties": False}


_HORODATAGE = {"type": "string", "description": "ISO 8601 avec fuseau (l'heure du serveur fait foi)."}
_DATE = {"type": "string", "description": "Date AAAA-MM-JJ."}
_NIVEAU = {"type": "string", "enum": ["0.80", "0.90", "0.95", "0.99"], "description": "Niveau de confiance."}
_RECU = {"type": "object", "description": "Reçu recu-calcul.v1 tel que rendu par m7_concevoir_test_marketing."}


def outils() -> tuple[Outil, ...]:
    return (
        Outil(
            nom="m7_normaliser_utm",
            description=(
                "Ramène des paramètres UTM à la convention gelée (sources, mediums, campagne) par une table "
                "d'alias DÉCLARÉE : "
                "conforme, normalisable ou non normalisable AVEC la raison (jamais deviné, jamais « autre » ; « "
                "meta » seul "
                "est ambigu). Fournir une liste d'URL (500 au plus, jamais ouvertes ni recopiées) ou les "
                "paramètres isolés. "
                "Les identifiants de clic (gclid, fbclid…) sont signalés par leur nom et écartés. Rend la "
                "couverture exacte."
            ),
            parametres=_objet(
                {
                    "urls": {"type": "array", "items": {"type": "string", "maxLength": 2048}, "maxItems": 500},
                    "source": {"type": "string", "maxLength": 100},
                    "medium": {"type": "string", "maxLength": 100},
                    "campagne": {"type": "string", "maxLength": 100},
                    "contenu": {"type": "string", "maxLength": 100},
                },
                [],
            ),
            fonction=normaliser_utm,
        ),
        Outil(
            nom="m7_importer_conversions_hors_ligne",
            description=(
                "Importe un lot (200 au plus, tout ou rien) de conversions HORS LIGNE (appel, rendez_vous, "
                "soumission_signee, "
                "vente) : conversion_id, lead_id opaque de M2, jour, valeur_cad en TEXTE, source/medium/campagne "
                "normalisés "
                "ou absents. Champs fermés : aucun nom, courriel, téléphone ni identifiant publicitaire. "
                "Idempotent ; une "
                "révision exige un motif de l'énuméré. Annonce m7.conversion_hors_ligne_importee à M2 et M8. N'établit "
                "aucune causalité."
            ),
            parametres=_objet(
                {
                    "conversions": {
                        "type": "array",
                        "items": {"type": "object"},
                        "minItems": 1,
                        "maxItems": 200,
                        "description": "Chaque conversion : {conversion_id, lead_id, type, convertie_le, "
                        "valeur_cad?, utm_source?, utm_medium?, utm_campaign?, revision?, "
                        "motif_revision?}.",
                    },
                    "horodatage": _HORODATAGE,
                },
                ["conversions", "horodatage"],
            ),
            fonction=importer_conversions_hors_ligne,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m7_concevoir_test_marketing",
            description=(
                "Conçoit un test marketing par un moteur déterministe et rend un REÇU de calcul rejouable : "
                "taille_echantillon_deux_proportions, puissance_deux_proportions, duree_test_marche_arret "
                "(irréalisable "
                "au-delà du plafond, jamais un plan trompeur), plan_test_geographique (moins de six paires : "
                "INSUFFISANT). "
                "Montants et taux en texte décimal. Les hypothèses (taille d'effet, indépendance) sont des "
                "suppositions."
            ),
            parametres=_objet(
                {
                    "moteur": {"type": "string", "enum": list(MOTEURS_CONCEPTION)},
                    "entrees": {"type": "object"},
                    "parametres": {"type": "object"},
                },
                ["moteur", "entrees", "parametres"],
            ),
            fonction=concevoir_test_marketing,
        ),
        Outil(
            nom="m7_enregistrer_plan_test_marketing",
            description=(
                "PRÉENREGISTRE le plan d'un test avant son début : reçu de conception (taille, durée ou plan "
                "géographique), "
                "hypothèse, métrique primaire, dates. Un plan ne se modifie pas. Sans plan enregistré avant le "
                "début, un "
                "résultat reste exploratoire : aucune causalité."
            ),
            parametres=_objet(
                {
                    "plan_id": {"type": "string"},
                    "recu": _RECU,
                    "hypothese": {"type": "string", "minLength": 10, "maxLength": 300},
                    "metrique_primaire": {"type": "string", "enum": list(experiences.METRIQUES)},
                    "debut": _DATE,
                    "fin": _DATE,
                    "horodatage": _HORODATAGE,
                },
                ["plan_id", "recu", "hypothese", "metrique_primaire", "debut", "fin", "horodatage"],
            ),
            fonction=enregistrer_plan_test_marketing,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m7_analyser_test_marketing",
            description=(
                "Analyse un résultat de test : taux du test et du témoin (k sur n), différence, intervalle de "
                "Newcombe-Wilson, reçu. Le statut est « preenregistre » seulement si le plan_id existe, a été "
                "enregistré AVANT "
                "le début et que periode_donnees est celle du plan ; sinon « exploratoire » avec les raisons. Ne "
                "dit jamais "
                "« causé par » : « associé à », « observé pendant le test »."
            ),
            parametres=_objet(
                {
                    "entrees": {"type": "object", "description": "{test: {k, n}, temoin: {k, n}} (entiers)."},
                    "niveau": _NIVEAU,
                    "plan_id": {"type": "string"},
                    "periode_donnees": {"type": "object", "description": "{debut, fin} des données analysées."},
                },
                ["entrees"],
            ),
            fonction=analyser_test_marketing,
        ),
        Outil(
            nom=NOM_ATTRIBUTION,
            description=(
                "Attribution DESCRIPTIVE des conversions hors ligne d'une période : comptes et parts par source "
                "normalisée "
                "(dernière source connue) avec intervalles de Wilson, « sans_source » à part, sources "
                "indistinguables sans "
                "classement, coût par conversion SEULEMENT quand la dépense du canal est CONNUE (sinon inconnu). "
                "Toujours "
                "causalite = non_etablie. Garde d'argent : admin confirmé ou propriétaire de console, ou "
                "approbation serveur."
            ),
            parametres=_objet({"debut": _DATE, "fin": _DATE, "niveau": _NIVEAU}, ["debut", "fin"]),
            fonction=lire_attribution_simple,
        ),
        Outil(
            nom="m7_rejouer_recu_mesure",
            description=(
                "Vérifie les empreintes d'un reçu de mesure de M7 (taille, puissance, durée, plan géographique, "
                "analyse) et le "
                "REJOUE : même moteur, mêmes entrées, mêmes empreintes. Un reçu retouché, compact (sans entrées) "
                "ou d'un "
                "moteur inconnu est refusé."
            ),
            parametres=_objet({"recu": _RECU}, ["recu"]),
            fonction=rejouer_recu_mesure,
        ),
    )


__all__ = ["NOM_ATTRIBUTION", "outils"]
