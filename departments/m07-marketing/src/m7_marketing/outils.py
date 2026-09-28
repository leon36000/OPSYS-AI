"""Capacités d'agent du département M7 Marketing.

Chaque outil enveloppe une fonction métier déterministe existante (aucune n'est
réécrite) : brand core, audit SEO, AEO/GEO, UTM, attribution/ROI, fabrique de contenu,
réputation, veille concurrentielle. Les outils composés (ex. `m7_calculer_roi`,
`m7_proposer_contenu`, `m7_proposer_reponse_avis`, `m7_calculer_metriques_reputation`)
chaînent plusieurs moteurs en un seul appel pour économiser des allers-retours au modèle,
sur le patron déjà établi par M3 (`m3_estimer_projet`).

Autonomie (voir `opsys.outils.Autonomie` et `docs/architecture/DEPARTEMENTS.md`) :
  T0 lecture/analyse/calcul pur ; T1 génération de brouillon (jamais publié) ;
  T2 action externe réversible ; T3 publication publique / envoi (frontière humaine).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from opsys.outils import Autonomie, Outil, depuis_couple

from .ads import intelligence as ads_intelligence
from .aeo import aeo_engine
from .attribution import attribution_engine
from .brand import brand_schema
from .competitive import report as competitive_report
from .content import approval as content_approval
from .content import factory as content_factory
from .reputation import classifier as reputation_classifier
from .reputation import ingestion as reputation_ingestion
from .reputation import metrics as reputation_metrics
from .reputation import response_builder as reputation_response_builder
from .roi import roi_engine
from .seo import seo_audit
from .social.postiz_adapter import (
    AdapterDisabled,
    Canal,
    NotAutorise,
    PostizAdapter,
    SocialPost,
)
from .utm import utm_engine
from .workflows import campagne_saisonniere as campagne_saisonniere_workflow

_RACINE_M7 = Path(__file__).resolve().parents[2]
_CONTRATS = _RACINE_M7 / "contracts"
_FIXTURES = _RACINE_M7 / "fixtures"
_DONNEES = _RACINE_M7 / "data" / "saisons" / "calendrier-quebec.v1.yaml"
_SITE_STATIQUE = _RACINE_M7 / "src" / "m7_marketing" / "site" / "static" / "index.html"

# ---------------------------------------------------------------------------
# Schémas JSON réutilisés (courts : payés à chaque tour)
# ---------------------------------------------------------------------------
_BRAND = {
    "type": "object",
    "description": "Profil de marque (name, tagline, tone, colors, langue, ...).",
}
_SUJET = {
    "type": "object",
    "properties": {
        "titre": {"type": "string"},
        "description": {"type": "string"},
        "mots_cles": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["titre", "description"],
    "additionalProperties": True,
}


# ---------------------------------------------------------------------------
# Brand Core
# ---------------------------------------------------------------------------
def lire_profil_marque(profil: dict[str, Any]) -> dict[str, Any]:
    """Valide un profil de marque contre le contrat gelé brand-contract.v1.yaml."""
    try:
        return {"accepte": True, "resultat": brand_schema.validate_profile(profil)}
    except brand_schema.ProfileError as exc:
        return {"accepte": False, "verdict": {"champ": exc.field, "raison": exc.message}}


# ---------------------------------------------------------------------------
# Audit SEO local
# ---------------------------------------------------------------------------
def auditer_seo_site(site_dir: str | None = None) -> dict[str, Any]:
    """Audit SEO technique statique (title, meta description, lang, h1, JSON-LD,
    scripts externes, robots.txt). Zéro réseau : mesure ce qui est sur disque."""
    cible = Path(site_dir) if site_dir else _SITE_STATIQUE.parent
    return seo_audit.audit_dir(cible)


# ---------------------------------------------------------------------------
# AEO / GEO
# ---------------------------------------------------------------------------
def evaluer_aeo(timestamp: str, html_path: str | None = None, content_item: dict[str, Any] | None = None) -> dict[str, Any]:
    """Évalue la visibilité IA (AEO) d'une page : soit le site statique généré
    (html_path, défaut : le site réel du département), soit un content-item déjà
    produit par `m7_proposer_contenu` (rendu en artefact minimal)."""
    if content_item is not None:
        artifact = aeo_engine.build_item_artifact(content_item, aeo_engine.SEO_KNOWLEDGE_PATH, timestamp)
    else:
        cible = Path(html_path) if html_path else _SITE_STATIQUE
        artifact = aeo_engine.build_site_artifact(cible, aeo_engine.SEO_KNOWLEDGE_PATH, timestamp)
    return aeo_engine.evaluate(artifact)


# ---------------------------------------------------------------------------
# UTM (composé : génère ET valide en un seul appel)
# ---------------------------------------------------------------------------
def generer_lien_utm(
    url_base: str,
    source: str,
    medium: str,
    campaign: str,
    content: str | None = None,
) -> dict[str, Any]:
    """Génère un lien UTM canonique et le valide contre les règles U-01..U-12 du contrat
    S012, en un seul appel. `url_base` est TOUJOURS fourni par l'appelant (profil de
    marque / site de l'entreprise cliente) : jamais de domaine par défaut caché."""
    lien = utm_engine.generer_lien_utm(url_base, source, medium, campaign, content)
    verdicts = utm_engine.valider_lien_utm(lien)
    echecs = [{"regle": r, "detail": d} for r, v, d in verdicts if v == "fail"]
    return {
        "lien": lien,
        "conforme": not echecs,
        "echecs": echecs,
        "verdicts": [{"regle": r, "verdict": v, "detail": d} for r, v, d in verdicts],
    }


# ---------------------------------------------------------------------------
# Attribution + ROI (outil composé de bout en bout — remplace 4-5 allers-retours)
# ---------------------------------------------------------------------------
def calculer_roi(
    date_reference: str,
    chemin_matomo: str | None = None,
    chemin_crm: str | None = None,
    fenetre_jours: int = 30,
    dossier_ads: str | None = None,
    chemin_calendrier: str | None = None,
    chemin_mapping: str | None = None,
) -> dict[str, Any]:
    """Chaîne complète : fixtures Matomo/CRM -> attribution (première/dernière touche)
    -> rapport ads (règles AD-01..AD-06) -> consolidation ROI par canal ET par fenêtre
    marketing, via la table de correspondance canal->plateforme_ads explicite. Ne
    fabrique jamais un coût ou un nombre de leads : `donnees_insuffisantes` explicite
    chaque lien manquant (canal sans plateforme connue, fenêtre sans mapping, etc.).
    """
    chemin_matomo = chemin_matomo or str(_FIXTURES / "matomo" / "visites.v1.yaml")
    chemin_crm = chemin_crm or str(_FIXTURES / "crm" / "leads.v1.yaml")
    dossier_ads = dossier_ads or str(_FIXTURES / "ads")
    chemin_calendrier = chemin_calendrier or str(_DONNEES)
    chemin_mapping = chemin_mapping or str(_CONTRATS / "roi-mapping.v1.yaml")

    visites, leads = attribution_engine.charger_et_valider_fixtures(chemin_matomo, chemin_crm)
    rapport_attribution = attribution_engine.attribuer(visites, leads, fenetre_jours=fenetre_jours)
    rapport_ads = ads_intelligence.generate_report(dossier_ads, chemin_calendrier, date_reference)

    with open(chemin_calendrier, "r", encoding="utf-8") as f:
        calendrier = yaml.safe_load(f)
    with open(chemin_mapping, "r", encoding="utf-8") as f:
        mapping = yaml.safe_load(f)

    roi = roi_engine.consolider_roi(rapport_attribution, rapport_ads, mapping, calendrier, date_reference)
    return {
        "date_reference": date_reference,
        "non_attribuables": rapport_attribution["non_attribuables"],
        "recommandations_ads": rapport_ads["recommandations"],
        "roi": roi,
    }


# ---------------------------------------------------------------------------
# Contenu (composé : fabrique + propose en un seul appel — T1, jamais publié)
# ---------------------------------------------------------------------------
def proposer_contenu(
    brand: dict[str, Any],
    surface: str,
    type: str,
    sujet: dict[str, Any],
    timestamp: str,
    acteur: str,
) -> dict[str, Any]:
    """Compose un content-item (gabarit Brand Core + tactiques SEO/AEO) et le dépose
    PROPOSE dans la file d'approbation 0-6, en un seul appel. Ne publie jamais rien :
    l'approbation reste un acte humain hors de ce périmètre d'outils."""
    item = content_factory.build_content_item(brand, surface, type, sujet, timestamp)
    item = content_approval.propose(item, acteur, timestamp)
    return item


def lister_file_approbation(statut: str | None = None) -> list[dict[str, Any]]:
    """Liste les content-items de la file d'approbation 0-6, filtrés par statut
    (PROPOSE | APPROVED | REJECTED) si fourni."""
    return content_approval.list_items(statut)


def planifier_campagne_saisonniere(date_reference: str, chemin_calendrier: str | None = None) -> dict[str, Any]:
    """Plan de contenu saisonnier composé de bout en bout : identifie les fenêtres
    marketing actives (calendrier saisonnier québécois) pour la date de référence,
    compose un content-item par thème et les dépose PROPOSE dans la file d'approbation.
    Aucune fenêtre active -> plan vide (jamais un plan fabriqué)."""
    chemin = chemin_calendrier or str(_DONNEES)
    return campagne_saisonniere_workflow.planifier_campagne_saisonniere(date_reference, chemin)


# ---------------------------------------------------------------------------
# Réputation (deux outils composés : métriques agrégées, et brouillon de réponse)
# ---------------------------------------------------------------------------
def calculer_metriques_reputation(
    reponses: list[dict[str, Any]] | None = None,
    chemin_avis: str | None = None,
) -> dict[str, Any]:
    """Charge les avis (lecture seule, D-043), les classe (règles déterministes,
    REJ-0040) et calcule les métriques agrégées alignées m7-metrics.v1.yaml (ids
    m7_rep_*), en un seul appel. `reponses` (optionnel) = réponses déjà proposées via
    `m7_proposer_reponse_avis`, pour le taux de réponse et le délai moyen."""
    avis_list = reputation_ingestion.charger_avis(Path(chemin_avis) if chemin_avis else None)
    classifications = [reputation_classifier.classifier_avis(a) for a in avis_list]
    return reputation_metrics.calculer_metriques(avis_list, reponses, classifications)


def proposer_reponse_avis(
    avis: dict[str, Any],
    brand: dict[str, Any],
    niveau_validation: int = 1,
) -> dict[str, Any]:
    """Classe un avis (litige/urgence/eloge/neutre, règles déterministes) puis compose
    une réponse PROPOSÉE à partir des gabarits Brand Core, en un seul appel. Statut
    TOUJOURS PROPOSE : jamais auto-publié (D-043, REJ-0040)."""
    categorie = reputation_classifier.classifier_avis(avis)
    reponse = reputation_response_builder.construire_reponse(avis, categorie, brand, niveau_validation)
    return reponse


# ---------------------------------------------------------------------------
# Veille concurrentielle
# ---------------------------------------------------------------------------
def analyser_concurrents(
    slugs: list[str],
    timestamp: str,
    notre_site: str | None = None,
    dossier_fixtures: str | None = None,
    chemin_stopwords: str | None = None,
) -> dict[str, Any]:
    """Audit de snapshots concurrents locaux (title/meta/h1/schema.org, robots.txt,
    sitemap.xml, couverture thématique) contre notre propre site généré."""
    if notre_site is None:
        notre_site = _SITE_STATIQUE.read_text(encoding="utf-8") if _SITE_STATIQUE.is_file() else ""
    return competitive_report.generate_report(
        slugs,
        notre_site=notre_site,
        base_fixtures=dossier_fixtures or str(_FIXTURES / "concurrents"),
        stopwords_path=chemin_stopwords or "",
        timestamp=timestamp,
    )


# ---------------------------------------------------------------------------
# Publication sociale / GBP — T3 : publication publique, frontière humaine.
# ---------------------------------------------------------------------------
def publier_post_social(
    canal: str,
    texte: str,
    niveau_validation: int,
    media: list[str] | None = None,
    adapter_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Publie (ou prévisualise, selon adapter_config) un post social via l'adapter
    Postiz GATED. Défaut sûr : enabled=True, dry_run=True (prévisualisation sans appel
    réseau). Une écriture réelle (dry_run=False) reste INTERDITE tant que l'Approval
    Engine n'est pas branché (D-010) : NotAutorise est traduit en verdict, jamais une
    exception qui casse l'appel."""
    cfg = adapter_config or {"enabled": True, "dry_run": True}
    adapter = PostizAdapter(cfg)
    try:
        post = SocialPost(canal=canal, texte=texte, media=media, niveau_validation=niveau_validation)
        resultat = adapter.publier(post)
        return {"publie": False, "statut": resultat.get("statut", "dry-run"), "resultat": resultat}
    except AdapterDisabled as exc:
        return {"publie": False, "statut": "desactive", "raison": str(exc)}
    except NotAutorise as exc:
        return {"publie": False, "statut": "non_autorise", "raison": str(exc)}


# ---------------------------------------------------------------------------
# Manifeste des outils
# ---------------------------------------------------------------------------
def outils() -> tuple[Outil, ...]:
    """Capacités exposées aux agents (fonction : les constantes publiques des paquets
    m7_marketing.* sont des énumérés métier, cf. garde AST des paquets)."""
    return (
        Outil(
            nom="m7_lire_profil_marque",
            description="Valide un profil de marque (name, tagline, tone, colors, langue) contre le contrat gelé Brand Core.",
            parametres={
                "type": "object",
                "properties": {"profil": _BRAND},
                "required": ["profil"],
                "additionalProperties": False,
            },
            fonction=lire_profil_marque,
        ),
        Outil(
            nom="m7_auditer_seo_site",
            description="Audit SEO technique local (title, meta description, lang, h1 unique, JSON-LD valide, scripts externes, robots.txt). Zéro réseau.",
            parametres={
                "type": "object",
                "properties": {
                    "site_dir": {"type": "string", "description": "Répertoire du site statique (défaut : le site généré du département)."}
                },
                "required": [],
                "additionalProperties": False,
            },
            fonction=auditer_seo_site,
        ),
        Outil(
            nom="m7_evaluer_aeo",
            description="Évalue la visibilité IA (AEO/GEO) d'une page (règles A-01..A-10 : title, description, h1, schema.org, citations, NAP LocalBusiness, fraîcheur, cohérence brand).",
            parametres={
                "type": "object",
                "properties": {
                    "timestamp": {"type": "string", "description": "Horodatage ISO 8601 de référence (jamais d'horloge interne)."},
                    "html_path": {"type": "string", "description": "Chemin d'une page HTML (défaut : le site statique généré)."},
                    "content_item": {"type": "object", "description": "Content-item déjà produit (évalue ce contenu au lieu du site)."},
                },
                "required": ["timestamp"],
                "additionalProperties": False,
            },
            fonction=evaluer_aeo,
        ),
        Outil(
            nom="m7_generer_lien_utm",
            description="Génère un lien UTM canonique et le valide contre le contrat S012 (U-01..U-12) en un seul appel. url_base = URL du site de l'entreprise (jamais un domaine par défaut caché).",
            parametres={
                "type": "object",
                "properties": {
                    "url_base": {"type": "string"},
                    "source": {"type": "string"},
                    "medium": {"type": "string"},
                    "campaign": {"type": "string"},
                    "content": {"type": ["string", "null"]},
                },
                "required": ["url_base", "source", "medium", "campaign"],
                "additionalProperties": False,
            },
            fonction=generer_lien_utm,
        ),
        Outil(
            nom="m7_calculer_roi",
            description=(
                "Chaîne complète attribution -> ads -> ROI de bout en bout : charge Matomo/CRM, attribue "
                "première/dernière touche, charge les campagnes ads, consolide le coût par lead par canal "
                "ET par fenêtre marketing. Jamais de coût ou de nb_leads fabriqué : donnees_insuffisantes "
                "explicite chaque lien manquant."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "date_reference": {"type": "string", "description": "Date de référence ISO (fenêtres actives, snapshot)."},
                    "chemin_matomo": {"type": "string"},
                    "chemin_crm": {"type": "string"},
                    "fenetre_jours": {"type": "integer", "description": "Fenêtre d'attribution en jours (défaut 30)."},
                    "dossier_ads": {"type": "string"},
                    "chemin_calendrier": {"type": "string"},
                    "chemin_mapping": {"type": "string"},
                },
                "required": ["date_reference"],
                "additionalProperties": False,
            },
            fonction=calculer_roi,
        ),
        Outil(
            nom="m7_proposer_contenu",
            description="Compose un content-item (gabarit Brand Core + tactiques SEO/AEO) et le dépose PROPOSE dans la file d'approbation, en un seul appel. Ne publie jamais.",
            parametres={
                "type": "object",
                "properties": {
                    "brand": _BRAND,
                    "surface": {"type": "string", "enum": ["google_aio", "perplexity", "assistants_ia"]},
                    "type": {"type": "string", "enum": ["post_social", "page_seo", "fiche_gbp", "article_blog"]},
                    "sujet": _SUJET,
                    "timestamp": {"type": "string"},
                    "acteur": {"type": "string"},
                },
                "required": ["brand", "surface", "type", "sujet", "timestamp", "acteur"],
                "additionalProperties": False,
            },
            fonction=proposer_contenu,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m7_lister_file_approbation",
            description="Liste les content-items de la file d'approbation 0-6, filtrés par statut (PROPOSE | APPROVED | REJECTED) si fourni.",
            parametres={
                "type": "object",
                "properties": {"statut": {"type": ["string", "null"], "enum": ["PROPOSE", "APPROVED", "REJECTED", None]}},
                "required": [],
                "additionalProperties": False,
            },
            fonction=lister_file_approbation,
        ),
        Outil(
            nom="m7_planifier_campagne_saisonniere",
            description=(
                "Plan de contenu saisonnier de bout en bout : détecte les fenêtres marketing actives "
                "(calendrier québécois) pour une date, compose un content-item par thème et les dépose "
                "PROPOSE dans la file d'approbation. Jamais publié."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "date_reference": {"type": "string", "description": "Date ISO servant à détecter les fenêtres actives."},
                    "chemin_calendrier": {"type": "string"},
                },
                "required": ["date_reference"],
                "additionalProperties": False,
            },
            fonction=planifier_campagne_saisonniere,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m7_calculer_metriques_reputation",
            description="Charge les avis (lecture seule), les classe (litige/urgence/eloge/neutre, déterministe) et calcule les métriques agrégées m7_rep_*, en un seul appel.",
            parametres={
                "type": "object",
                "properties": {
                    "reponses": {"type": "array", "items": {"type": "object"}, "description": "Réponses déjà proposées (pour taux de réponse et délai moyen)."},
                    "chemin_avis": {"type": "string"},
                },
                "required": [],
                "additionalProperties": False,
            },
            fonction=calculer_metriques_reputation,
        ),
        Outil(
            nom="m7_proposer_reponse_avis",
            description="Classe un avis client puis compose une réponse PROPOSÉE (gabarits Brand Core), en un seul appel. Statut toujours PROPOSE, jamais auto-publiée.",
            parametres={
                "type": "object",
                "properties": {
                    "avis": {"type": "object", "description": "{id, note (1-5), texte, ...}"},
                    "brand": _BRAND,
                    "niveau_validation": {"type": "integer", "description": "Niveau dans la file 0-6 (défaut 1)."},
                },
                "required": ["avis", "brand"],
                "additionalProperties": False,
            },
            fonction=proposer_reponse_avis,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m7_analyser_concurrents",
            description="Audit de snapshots concurrents locaux (balisage SEO, robots.txt, sitemap, couverture thématique) contre notre propre site généré.",
            parametres={
                "type": "object",
                "properties": {
                    "slugs": {"type": "array", "items": {"type": "string"}, "description": "Slugs sous fixtures/concurrents/."},
                    "timestamp": {"type": "string"},
                    "notre_site": {"type": "string"},
                    "dossier_fixtures": {"type": "string"},
                    "chemin_stopwords": {"type": "string"},
                },
                "required": ["slugs", "timestamp"],
                "additionalProperties": False,
            },
            fonction=analyser_concurrents,
        ),
        Outil(
            nom="m7_publier_post_social",
            description=(
                "Publie (ou prévisualise en dry-run) un post sur un canal social/GBP via l'adapter Postiz "
                "GATED. Publication publique = frontière humaine : écriture réelle toujours refusée "
                "(NotAutorise) tant que l'Approval Engine n'est pas branché."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "canal": {"type": "string", "enum": [c.value for c in Canal]},
                    "texte": {"type": "string"},
                    "niveau_validation": {"type": "integer", "description": "0 à 6."},
                    "media": {"type": ["array", "null"], "items": {"type": "string"}},
                    "adapter_config": {
                        "type": ["object", "null"],
                        "description": "{enabled, dry_run, base_url} — défaut {enabled: true, dry_run: true}.",
                    },
                },
                "required": ["canal", "texte", "niveau_validation"],
                "additionalProperties": False,
            },
            fonction=publier_post_social,
            autonomie=Autonomie.T3,
        ),
    )
