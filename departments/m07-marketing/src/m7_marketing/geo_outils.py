"""Les outils M7 du SEO et du GEO sur données propres : robots d'IA, journaux, panel de visibilité, recommandations,
brouillons de site.

Chaque fonction est une enveloppe mince : elle appelle un module pur de `geo/` (ou `signaux/import_manuel`), traduit
un refus typé en `{accepte: False, refus: [{code, chemin, detail}]}` et n'écrit qu'aux registres durables de M7.

Niveaux (ADR-0009) :
  - lectures et calculs : T0 (analyse de `robots.txt`, analyse d'un journal fourni, plan et coût d'un panel, taux de
    visibilité, recommandations lues du registre des signaux, lecture des propositions) ;
  - importer un export au registre des signaux, proposer ou retirer un changement de site : N2 (rien ne sort d'OPSYS) ;
  - AUCUN outil ne publie, n'interroge un moteur d'IA, ne lit un journal du serveur ni ne modifie `robots.txt` : le
  panel
    s'exécute par un exécuteur hors outil, avec un fournisseur d'API officiel à brancher (jamais exercé ici).
Aucun rôle d'appareil.
"""

from __future__ import annotations

from typing import Any

from opsys import stockage
from opsys.outils import Autonomie, Niveau, Outil

from .geo import journaux_bots, panel, proposition_site, recommandations, robots_ia, visibilite
from .publication_outils import _horodatage
from .signaux import import_manuel, minimisation, modele, registre
from .signaux.erreurs import ErreurSignaux
from .site import service as site_service
from .usine import service as usine_service

REGISTRE_PROPOSITIONS = ("m07-marketing", "propositions_site")


def _refus_de(erreur: ValueError | ErreurSignaux) -> dict[str, Any]:
    code = getattr(erreur, "code", None) or str(erreur).split(" : ", 1)[0]
    detail = getattr(erreur, "detail", None) or str(erreur).split(" : ", 1)[-1]
    return {"accepte": False, "refus": [{"code": code, "chemin": "$", "detail": detail}]}


def analyser_robots_ia(texte_robots: str | None, statut_http: int, politique: dict[str, Any]) -> dict[str, Any]:
    """T0 : robots d'IA autorisés ou non par `robots.txt`, conformité à la politique du client, lignes recommandées."""
    try:
        return robots_ia.analyser_robots_ia(texte_robots, statut_http, politique)
    except ValueError as exc:
        return _refus_de(exc)


def analyser_journaux_robots_ia(texte_journal: str, plages: dict[str, Any] | None = None) -> dict[str, Any]:
    """T0 : décomptes des robots d'IA dans un journal d'accès fourni ; aucune adresse IP n'est rendue ni gardée."""
    try:
        reference = None
        if plages is not None:
            if not isinstance(plages, dict) or set(plages) != {"plages", "source", "date"}:
                return _refus_de(robots_ia.ErreurGeo("REJ-GEO-PLAGES-INVALIDES", "plages : {plages, source, date}"))
            reference = journaux_bots.PlagesDeclarees(plages["plages"], source=plages["source"], date=plages["date"])
        analyse = journaux_bots.analyser_journaux(texte_journal, reference)
    except ValueError as exc:
        return _refus_de(exc)
    return {**analyse, "lignes_a_importer": journaux_bots.lignes_visites(analyse)[:200]}


def importer_signaux_manuel(source: str, compte_ref: str, nature: str, mapping: dict[str, Any], fictif: bool,
                            horodatage: str, csv_texte: str | None = None, lignes: list[dict[str, Any]] | None = None,
                            delimiteur: str = ",") -> dict[str, Any]:
    """N2 : importe un export (CSV ou JSON) au registre des signaux avec provenance `import_manuel`."""
    instant = _horodatage(horodatage)
    if isinstance(instant, dict):
        return instant
    try:
        resultat = import_manuel.importer(
            source=source, compte_ref=compte_ref, nature=nature, mapping=mapping, csv_texte=csv_texte, lignes=lignes,
            delimiteur=delimiteur, fictif=fictif, maintenant=lambda: instant[1], masqueur=minimisation.masqueur_local())
    except ErreurSignaux as exc:
        return _refus_de(exc)
    return {**resultat, "par": usine_service._qui_appelle()[0]}


def planifier_panel_visibilite_ia(prompts: list[dict[str, Any]], moteurs: list[str], repetitions: int,
                                  cout_par_appel_cents_par_moteur: dict[str, Any],
                                  plafond_mensuel_cents: int | None = None) -> dict[str, Any]:
    """T0 : plan d'un passage mensuel du panel et son coût d'avance (aucun moteur n'est interrogé)."""
    try:
        return panel.planifier_panel(prompts, moteurs, repetitions, cout_par_appel_cents_par_moteur,
                                     plafond_mensuel_cents)
    except ValueError as exc:
        return _refus_de(exc)


def calculer_visibilite_ia(resultats: list[dict[str, Any]], plan: dict[str, Any] | None = None) -> dict[str, Any]:
    """T0 : taux de mention et part de citations par moteur avec intervalle de Wilson, effectifs et avertissements."""
    try:
        return visibilite.calculer_visibilite(resultats, plan=plan)
    except ValueError as exc:
        return _refus_de(exc)


def recommander_contenu_geo(horodatage: str, texte_robots: str | None = None, statut_robots: int | None = None,
                            politique: dict[str, Any] | None = None, audit_seo: dict[str, Any] | None = None,
                            audit_aeo: dict[str, Any] | None = None, audit_le: str | None = None) -> dict[str, Any]:
    """T0 : recommandations sourcées et priorisées, lues du registre des signaux (faits courants) et des audits "
    "fournis."""
    instant = _horodatage(horodatage)
    if isinstance(instant, dict):
        return instant
    try:
        analyse = None
        if politique is not None or statut_robots is not None:
            if politique is None or statut_robots is None:
                return _refus_de(robots_ia.ErreurGeo("REJ-GEO-POLITIQUE-ABSENTE",
                                                     "statut_robots et politique vont ensemble"))
            analyse = robots_ia.analyser_robots_ia(texte_robots, statut_robots, politique)
        faits = registre.courants(registre.charger(stockage.maillons(*registre.REGISTRE)))
        return recommandations.recommander(list(faits.values()), maintenant=instant[1], analyse_robots=analyse,
                                           audit_seo=audit_seo, audit_aeo=audit_aeo, audit_le=audit_le)
    except ValueError as exc:
        return _refus_de(exc)
    except ErreurSignaux as exc:
        return _refus_de(exc)


def _controle_marques():
    """Le contrôle de marques de la veille, ou `None` si le module n'existe pas (l'avertissement
    `controle_marques_non_applique`
    est alors rendu par la proposition). Un registre de veille altéré n'est PAS un repli : l'erreur sort."""
    try:
        from .veille import conformite, observations
        from .veille import registre as registre_veille
    except ImportError:
        return None
    concurrents = list(registre_veille.plier(stockage.maillons(*registre_veille.REGISTRE)).values())
    vues = observations.charger(stockage.maillons(*observations.REGISTRE_OBSERVATIONS))
    return lambda texte: conformite.controler_texte_propose(texte, concurrents, vues)


def proposer_changement_site(operations: list[dict[str, Any]], date_revision: str, horodatage: str,
                             schema: dict[str, Any] | None = None, schema_demo: str | None = None,
                             recommandation_id: str | None = None) -> dict[str, Any]:
    """N2 : brouillon de changement d'un site (liste blanche d'opérations), contrôlé sans rien écrire sur le site."""
    instant = _horodatage(horodatage)
    if isinstance(instant, dict):
        return instant
    charge, actifs, refus = site_service.resoudre_schema(schema, schema_demo)
    if refus is not None:
        return refus
    try:
        return proposition_site.proposer(
            charge, actifs, operations, date_revision, stockage.maillons(*REGISTRE_PROPOSITIONS),
            par=usine_service._qui_appelle()[0], horodatage=instant[0], recommandation_id=recommandation_id,
            controle_marques=_controle_marques())
    except ValueError as exc:
        return _refus_de(exc)


def retirer_proposition_site(proposition_id: str, motif: str, horodatage: str) -> dict[str, Any]:
    """N2 : retire un brouillon de proposition (il ne pourra plus être repris tel quel)."""
    instant = _horodatage(horodatage)
    if isinstance(instant, dict):
        return instant
    return proposition_site.retirer(stockage.maillons(*REGISTRE_PROPOSITIONS), proposition_id,
                                    usine_service._qui_appelle()[0], motif, instant[0])


def lire_propositions_site(proposition_id: str | None = None, etat: str | None = None, limite: int = 20) -> dict[str,
    Any]:
    """T0 : les propositions de changement de site, ou une proposition en détail."""
    try:
        return proposition_site.lire(stockage.maillons(*REGISTRE_PROPOSITIONS), proposition_id, etat, limite)
    except ValueError as exc:
        return _refus_de(exc)


# ---------------------------------------------------------------------------
# Manifeste
# ---------------------------------------------------------------------------
_HORODATAGE = {"type": "string", "description": "ISO 8601 avec fuseau (l'heure du serveur fait foi)."}
_POLITIQUE = {
    "type": "object",
    "description": ("Décision du client pour chaque catégorie de robot d'IA, sans valeur par défaut : {recherche, "
                    "recuperation_a_la_demande, entrainement}, chacune « autoriser » ou « bloquer »."),
}
_SCHEMA = {"type": "object", "description": "Schéma de site opsys.site/v1 (contenu seulement)."}


def _objet(proprietes: dict[str, Any], requis: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": proprietes, "required": requis, "additionalProperties": False}


def outils() -> tuple[Outil, ...]:
    return (
        Outil(
            nom="m7_analyser_robots_ia",
            description=(
                "Analyse le robots.txt du site du client (RFC 9309) pour les robots d'IA connus (liste fermée, à "
                "revérifier) : "
                "autorisé ou non, conforme ou non à la politique du client (qu'il décide : aucune valeur par défaut), "
                "constats et lignes RECOMMANDÉES à ajouter (rien n'est modifié). Aucune visibilité n'est promise."
            ),
            parametres=_objet({
                "texte_robots": {"type": ["string", "null"], "description": "Contenu de robots.txt (null si "
                                                                            "illisible)."},
                "statut_http": {"type": "integer", "description": "Statut HTTP obtenu pour /robots.txt."},
                "politique": _POLITIQUE,
            }, ["texte_robots", "statut_http", "politique"]),
            fonction=analyser_robots_ia,
        ),
        Outil(
            nom="m7_analyser_journaux_robots_ia",
            description=(
                "Compte les visites des robots d'IA dans un journal d'accès (combined/common) fourni : par robot, "
                "jour UTC, "
                "classe de statut et groupe de chemins. Aucune adresse IP n'est conservée ni rendue ; sans plages "
                "publiées, "
                "les décomptes sont « agent seulement ». 2 Mo et 100 000 lignes au plus."
            ),
            parametres=_objet({
                "texte_journal": {"type": "string"},
                "plages": {"type": ["object", "null"], "description": "{plages: {robot: [CIDR]}, source, date} "
                                                                      "copiées de la "
                           "page publiée de l'éditeur ; aucune plage par défaut."},
            }, ["texte_journal"]),
            fonction=analyser_journaux_robots_ia,
        ),
        Outil(
            nom="m7_importer_signaux_manuel",
            description=(
                "Importe un export (CSV ou lignes JSON) au registre des signaux, avec provenance import_manuel : "
                "rapport IA "
                "de Search Console ou Bing, journaux du serveur, ou export d'une source sans accès. Le mapping des "
                "colonnes "
                "est fourni par l'appelant (rien n'est deviné). Tout ou rien, idempotent, formules de tableur "
                "neutralisées."
            ),
            parametres=_objet({
                "source": {"type": "string", "enum": list(modele.SOURCES_IMPORT)},
                "compte_ref": {"type": "string"},
                "nature": {"type": "string", "enum": list(import_manuel.NATURES_IMPORTABLES)},
                "mapping": {"type": "object", "description": "{portee: {type, colonne | ref}, periode: {jour} | "
                                                             "{debut, fin}, "
                            "mesures: {nom: colonne}, echantillon}."},
                "fictif": {"type": "boolean"},
                "horodatage": _HORODATAGE,
                "csv_texte": {"type": "string"},
                "lignes": {"type": "array", "items": {"type": "object"}},
                "delimiteur": {"type": "string", "enum": list(import_manuel.DELIMITEURS)},
            }, ["source", "compte_ref", "nature", "mapping", "fictif", "horodatage"]),
            fonction=importer_signaux_manuel,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m7_planifier_panel_visibilite_ia",
            description=(
                "Valide un panel de 20 à 50 questions et calcule son COÛT d'avance avec les tarifs que le client "
                "déclare "
                "(tarif inconnu : coût « inconnu », jamais zéro ; plafond mensuel respecté). Moteurs : API officielles "
                "seulement (liste fermée) ; toute interface grand public est refusée. N'interroge aucun moteur."
            ),
            parametres=_objet({
                "prompts": {"type": "array", "items": {"type": "object"}, "description": "[{id, texte, langue "
                                                                                         "fr|en}]."},
                "moteurs": {"type": "array", "items": {"type": "string", "enum": list(panel.MOTEURS)}},
                "repetitions": {"type": "integer", "minimum": 1, "maximum": 10},
                "cout_par_appel_cents_par_moteur": {"type": "object", "description": "{moteur: cents | null}."},
                "plafond_mensuel_cents": {"type": ["integer", "null"], "minimum": 0},
            }, ["prompts", "moteurs", "repetitions", "cout_par_appel_cents_par_moteur"]),
            fonction=planifier_panel_visibilite_ia,
        ),
        Outil(
            nom="m7_calculer_visibilite_ia",
            description=(
                "Taux de mention et part de citations par moteur à partir des résultats d'un panel, avec effectifs et "
                "intervalle de Wilson à 95 %. Sous 20 réponses : insuffisant. Aucun classement quand les "
                "intervalles se "
                "chevauchent. Réponse d'API ≠ interface grand public ; aucune causalité."
            ),
            parametres=_objet({
                "resultats": {"type": "array", "items": {"type": "object"}},
                "plan": {"type": ["object", "null"], "description": "Plan du panel (pour afficher le coût)."},
            }, ["resultats"]),
            fonction=calculer_visibilite_ia,
        ),
        Outil(
            nom="m7_recommander_contenu_geo",
            description=(
                "Recommandations de contenu et de technique SOURCÉES (faits du registre des signaux avec fraîcheur) et "
                "PRIORISÉES par une formule visible (impact × facilité), règles GEO-01 à GEO-06. Une donnée absente ou "
                "périmée rend la règle « non évaluable ». Aucune promesse de visibilité ; chaque recommandation est un "
                "brouillon à faire relire."
            ),
            parametres=_objet({
                "horodatage": _HORODATAGE,
                "texte_robots": {"type": ["string", "null"]},
                "statut_robots": {"type": "integer"},
                "politique": _POLITIQUE,
                "audit_seo": {"type": "object"},
                "audit_aeo": {"type": "object"},
                "audit_le": {"type": "string", "description": "Date AAAA-MM-JJ de l'audit fourni (90 jours au plus)."},
            }, ["horodatage"]),
            fonction=recommander_contenu_geo,
        ),
        Outil(
            nom="m7_proposer_changement_site",
            description=(
                "Propose un changement de texte d'un site (schéma opsys.site/v1) sous forme de BROUILLON : opérations "
                "limitées à une liste blanche (titre, description, résumé, description de service, nouvelle entrée "
                "de FAQ), "
                "contrôlées par le validateur, la garde de contenu, le contrôle de marques de la veille et le contrôle "
                "qualité du rendu. Rien n'est publié ni écrit sur le site (publication : N3, direction)."
            ),
            parametres=_objet({
                "operations": {"type": "array", "items": {"type": "object"}, "maxItems": 20,
                               "description": "[{op: remplacer_texte, cible, id, valeur} | {op: ajouter_faq, id, "
                                              "valeur}]"},
                "date_revision": {"type": "string"},
                "horodatage": _HORODATAGE,
                "schema": _SCHEMA,
                "schema_demo": {"type": "string"},
                "recommandation_id": {"type": "string"},
            }, ["operations", "date_revision", "horodatage"]),
            fonction=proposer_changement_site,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m7_retirer_proposition_site",
            description="Retire un brouillon de proposition de changement de site. Rien n'est publié ni défait sur "
                        "le site.",
            parametres=_objet({"proposition_id": {"type": "string"}, "motif": {"type": "string", "maxLength": 300},
                               "horodatage": _HORODATAGE}, ["proposition_id", "motif", "horodatage"]),
            fonction=retirer_proposition_site,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m7_lire_propositions_site",
            description="Lit les propositions de changement de site (liste ou détail) et l'intégrité du journal. "
                        "Lecture seule.",
            parametres=_objet({
                "proposition_id": {"type": "string"},
                "etat": {"type": "string", "enum": ["BROUILLON", "RETIREE"]},
                "limite": {"type": "integer", "minimum": 1, "maximum": 50},
            }, []),
            fonction=lire_propositions_site,
        ),
    )


__all__ = ["outils"]
