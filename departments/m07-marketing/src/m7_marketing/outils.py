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

Usine à contenu d'un chantier (PLAN T4.17) : les six outils `m7_*_chantier`, `m7_decider_contenu`,
`m7_exporter_paquet_manuel` et `m7_enregistrer_retrait_consentement_marketing` sont des enveloppes minces
sur `usine.service` ; la logique vit dans les modules purs de `usine/`. Le consommateur `m4.travaux_termines`
propose aussi les cinq contenus d'un chantier terminé (gabarits du code, jamais un modèle), et `attentes()`
montre au propriétaire, dans « À voir », les contenus qui attendent sa décision.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from opsys import stockage, taxonomie
from opsys.outils import Autonomie, Niveau, Outil

from .ads import intelligence as ads_intelligence
from .aeo import aeo_engine
from .attribution import attribution_engine
from .brand import brand_schema
from .brand import profil_client as brand_profil_client
from .competitive import report as competitive_report
from .content import approval as content_approval
from .content import contenu_public as content_contenu_public
from .content import factory as content_factory
from .moderation import detection as moderation_detection
from .moderation.image import ImageSynthetique
from .reputation import classifier as reputation_classifier
from .reputation import demande_avis as reputation_demande_avis
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
from .usine import decision as usine_decision
from .usine import plateformes as usine_plateformes
from .usine import registre as usine_registre
from .usine import retrait as usine_retrait
from .usine import service as usine_service
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
_IMAGE_SYNTHETIQUE = {
    "type": "object",
    "description": (
        "Image déjà décodée en pixels RGB (jamais un fichier JPEG/PNG brut : le décodage réel "
        "reste à brancher avec la brique retenue, voir docs/research/INGREDIENTS.md § M7)."
    ),
    "properties": {
        "largeur": {"type": "integer"},
        "hauteur": {"type": "integer"},
        "pixels": {
            "type": "array",
            "description": "largeur * hauteur triplets [r, g, b], rangée par rangée.",
            "items": {"type": "array", "items": {"type": "integer"}, "minItems": 3, "maxItems": 3},
        },
    },
    "required": ["largeur", "hauteur", "pixels"],
    "additionalProperties": False,
}
_PHOTO = {
    "type": "object",
    "properties": {"reference": {"type": "string"}, "image": _IMAGE_SYNTHETIQUE},
    "required": ["reference", "image"],
    "additionalProperties": False,
}
_HORODATAGE = {"type": "string", "description": "ISO 8601 avec fuseau (l'heure du serveur fait foi)."}
_TEXTES_PAR_PLATEFORME = {
    "type": "object",
    "description": (
        "Texte rédigé par toi, par plateforme (facultatif : sans lui, le gabarit du code). Chaque texte est "
        "contrôlé en code et refusé en nommant la règle (m7_lire_matiere_chantier les liste)."
    ),
    "properties": {code: {"type": "string"} for code in usine_plateformes.CODES_PLATEFORMES},
    "additionalProperties": False,
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
def evaluer_aeo(
    timestamp: str, html_path: str | None = None, content_item: dict[str, Any] | None = None
) -> dict[str, Any]:
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

    with open(chemin_calendrier, encoding="utf-8") as f:
        calendrier = yaml.safe_load(f)
    with open(chemin_mapping, encoding="utf-8") as f:
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


# ---------------------------------------------------------------------------
# Contenu public (photo de chantier) — consentement + floutage (PLAN T4.3, T1, jamais publié)
#
# Correctif de relecture (0a7aaef) : ni le consentement ni l'identité de marque ne sont plus des
# arguments de cet outil. AGENTS.md « le code calcule, le LLM orchestre » : un modèle qui appelle
# l'outil ne peut ni inventer ni élargir un consentement — celui-ci vient EXCLUSIVEMENT du WCT
# `m4.travaux_termines` déjà reçu et enregistré par `_recevoir_travaux_termines` (registre
# `wct_recus`, ci-dessous) ; l'identité de marque vient EXCLUSIVEMENT du profil client configuré
# (`brand.profil_client`), jamais d'un paramètre fourni par l'appelant.
# ---------------------------------------------------------------------------
_REGISTRE_CONTENU_PUBLIC = ("m07-marketing", "contenu_public")
_REGISTRE_WCT_RECUS = ("m07-marketing", "wct_recus")

STATUT_WCT_INCONNU = "wct_inconnu"
STATUT_PROFIL_MARQUE_NON_CONFIGURE = "profil_marque_non_configure"


def _image_depuis_dict(donnees: dict[str, Any]) -> ImageSynthetique:
    pixels = tuple((int(p[0]), int(p[1]), int(p[2])) for p in donnees["pixels"])
    return ImageSynthetique(largeur=donnees["largeur"], hauteur=donnees["hauteur"], pixels=pixels)


def _wct_recu(wct_id: str) -> dict[str, Any] | None:
    """Le WCT `m4.travaux_termines` déjà reçu pour `wct_id` (registre `wct_recus`, alimenté
    uniquement par `_recevoir_travaux_termines`, jamais par un argument d'outil), ou `None`."""
    return usine_service.wct_recu(wct_id)


def preparer_contenu_public(
    wct_id: str,
    photos: list[dict[str, Any]],
    seuil_confiance: float,
) -> dict[str, Any]:
    """Prépare un brouillon de contenu public (photo de chantier) FLOUTÉ, avec la preuve du
    consentement et le rapport de floutage — jamais une publication (T1). La publication réelle
    reste N5 (approbation signée du socle), hors de cet outil.

    Le CONSENTEMENT vient uniquement du WCT `m4.travaux_termines` déjà reçu par le bus pour
    `wct_id` (registre durable `wct_recus`) : un `wct_id` inconnu de ce registre refuse
    (`statut: "wct_inconnu"`), jamais un brouillon composé sur un consentement supposé ou fourni
    par l'appelant. L'IDENTITÉ DE MARQUE vient uniquement du profil client configuré
    (`brand.profil_client.charger_profil_client`), jamais d'un argument.

    Fail-closed : `wct_id` inconnu, profil de marque non configuré, aucune photo, consentement
    absent/faux dans le WCT reçu, ou détecteur réel indisponible dans cet environnement ->
    `statut != "propose"` et `brouillon: None`, jamais une exception qui casse l'appel, jamais un
    brouillon composé sous une identité ou un consentement inventés.

    Idempotent par `wct_id` : un brouillon déjà déposé pour ce chantier n'est jamais dupliqué (un
    nouvel appel le retourne tel quel, `statut: "deja_prepare"`).
    """
    charge = _wct_recu(wct_id)
    if charge is None:
        return {
            "brouillon": None,
            "statut": STATUT_WCT_INCONNU,
            "motif": f"wct_id inconnu : {wct_id!r} — aucun m4.travaux_termines reçu pour ce wct_id",
        }

    # Un retrait du consentement marketing (Loi 25) bloque toute tâche de contenu de ce chantier, avant tout,
    # y compris le brouillon déjà déposé : on ne le rend plus, on dit pourquoi (PLAN T4.17).
    bloquant = usine_service.retrait_bloquant(charge)
    if bloquant is not None:
        return {
            "brouillon": None, "statut": "consentement_retire",
            "motif": f"consentement marketing retiré par le client (retrait {bloquant['retrait_id']}) : aucun contenu",
        }

    registre = stockage.maillons(*_REGISTRE_CONTENU_PUBLIC)
    for existant in registre:
        if existant.get("wct_id") == wct_id:
            return {"brouillon": existant, "statut": "deja_prepare", "motif": None}

    # Consentement vérifié TÔT, avant de résoudre un profil de marque ou un détecteur : le motif
    # le plus fondamental d'abord, jamais un travail inutile sur une charge qu'on va refuser de
    # toute façon (`preparer_brouillon_contenu_public` la revérifie aussi, en profondeur).
    motif_consentement = content_contenu_public.verifier_consentement(charge)
    if motif_consentement is not None:
        return {"brouillon": None, "statut": "refuse", "motif": motif_consentement}

    profil, motif = brand_profil_client.charger_profil_client()
    if profil is None:
        return {"brouillon": None, "statut": STATUT_PROFIL_MARQUE_NON_CONFIGURE, "motif": motif}

    try:
        detecteur = moderation_detection.detecteur_opencv_par_defaut()
    except moderation_detection.DetecteurIndisponible as exc:
        return {"brouillon": None, "statut": "detecteur_indisponible", "motif": str(exc)}

    images = [(p["reference"], _image_depuis_dict(p["image"])) for p in photos]
    brouillon, motif = content_contenu_public.preparer_brouillon_contenu_public(
        charge, images, profil, detecteur, seuil_confiance
    )
    if brouillon is None:
        return {"brouillon": None, "statut": "refuse", "motif": motif}

    registre.append(brouillon)
    return {"brouillon": brouillon, "statut": "propose", "motif": None}


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
# Bus d'événements (ADR-0009 §3, PLAN T1.2-c) : consommateur de m4.travaux_termines
# ---------------------------------------------------------------------------
_REGISTRE_DEMANDES_AVIS = ("m07-marketing", "demandes_avis")
# Les statuts d'une plateforme qui n'a PAS de contenu à la fin de la préparation (texte refusé par le contrôle,
# ou rejeté par le propriétaire et à récrire) : le résumé du consommateur les nomme, `contenus` les détaille.
_ITEMS_BLOQUES = ("refuse", "texte_requis")


def _enregistrer_wct_recu(charge: dict[str, Any]) -> None:
    """Enregistre CHAQUE WCT `m4.travaux_termines` reçu dans le registre durable `wct_recus`,
    QUEL QUE SOIT le sort de la demande d'avis ci-dessous (le FAIT reçu du bus — dont
    `consentement_marketing` — est distinct de la décision prise dessus) : idempotent par
    `wct_id`. C'est désormais la SEULE source de vérité du consentement pour l'outil
    `m7_preparer_contenu_public` (correctif de relecture, 0a7aaef) — AGENTS.md « le LLM
    orchestre, il ne fournit jamais un fait » : aucun outil n'accepte plus le consentement en
    argument, il vient toujours de ce que M4 a réellement publié sur le bus.

    Note d'architecture (limite documentée, jamais cachée) : le répartiteur
    (`opsys.evenements.repartiteur._livrer_une_paire`) n'appelle un consommateur qu'avec la
    charge (`fonction(dict(charge))`) — ni `evenement_id` ni horodatage de réception ne sont
    accessibles ici. Le champ `horodatage_completion`, déjà présent dans `charge` (fait réel de
    l'événement, jamais une horloge interne), sert de référence temporelle pour ce qui est
    enregistré. Exposer `evenement_id` au consommateur nécessiterait un changement du contrat du
    répartiteur (partagé par tous les départements) — hors périmètre d'un correctif M7 seul.
    """
    wct_id = charge["wct_id"]
    registre = stockage.maillons(*_REGISTRE_WCT_RECUS)
    for existant in registre:
        if existant.get("wct_id") == wct_id:
            return  # déjà enregistré (relivraison de l'événement, ou repartir() rejoué)
    registre.append(dict(charge))


def _libelle_du_service(charge: dict[str, Any]) -> tuple[str | None, str | None]:
    """`(libellé, None)` du service d'un WCT v2, `(None, motif)` si ce service n'est pas déclaré par
    l'entreprise (profil d'instance, `opsys.taxonomie`), `(None, None)` pour un WCT v1 (`type_travaux`,
    aucune taxonomie : jamais l'un déduit de l'autre, PLAN T0.13-b). Le motif ne porte que le code du
    verdict : le détail nomme un chemin de fichier du serveur, qui n'entre pas dans un brouillon."""
    if "service" not in charge:
        return None, None
    service, verdict = taxonomie.valider_service(charge["service"])
    if service is None:
        return None, f"libellé du service {charge['service']!r} introuvable ({verdict['code']})"
    return service.libelle, None


def _recevoir_travaux_termines(charge: dict[str, Any]) -> dict[str, Any]:
    """Consommateur `m4.travaux_termines` (ADR-0009 §3, DEPARTEMENTS.md « Événements ») :
    enregistre d'abord le WCT reçu (`_enregistrer_wct_recu`, inconditionnel), puis prépare une
    demande d'avis EN BROUILLON (`_demande_avis_du_chantier`), puis, si le client a consenti à l'usage de
    son chantier en contenu public, propose les cinq contenus du chantier (`usine.service`, PLAN T4.17 :
    gabarits du code, jamais un modèle ; rien sans consentement prouvé, rien après un retrait). Toute écriture
    est interne au registre du département, jamais un envoi ni une publication : la décision et la
    publication restent humaines, hors de ce consommateur et de tout outil exposé ici.

    Le résumé rendu garde les clés de la demande d'avis (`brouillon_cree`, `deja_enregistre`, ...) et ajoute
    `contenus` : `{statut, motif, crees, deja_la, refuses}`, sans texte (les textes se lisent avec
    `m7_lister_contenus_chantier`). Un refus de contenu (profil non configuré, consentement absent) est un
    statut, jamais une exception : il ne fait ni échouer ni rejouer la livraison.
    """
    _enregistrer_wct_recu(charge)
    resume = _demande_avis_du_chantier(charge)
    contenus = usine_service.proposer_pour_charge(charge, None, usine_service.ORIGINE_BUS)
    statuts = [item["statut"] for item in contenus["contenus"]]
    return {
        **resume,
        "contenus": {
            "statut": contenus["statut"],
            "motif": contenus["motif"],
            "crees": statuts.count("propose"),
            "deja_la": statuts.count("deja_propose"),
            "refuses": [item["plateforme"] for item in contenus["contenus"] if item["statut"] in _ITEMS_BLOQUES],
        },
    }


def _demande_avis_du_chantier(charge: dict[str, Any]) -> dict[str, Any]:
    """La demande d'avis d'un chantier reçu (PLAN T1.2-c, T1.5-d), séparée du reste du consommateur.

    PLAN T1.5-d : le brouillon naît du consentement du client à une demande d'avis
    (`consentement_demande_avis`, recueilli par l'employé dans l'app « Terminer », prouvé par M4 : qui,
    quand, quel texte), lu ICI dans le WCT reçu par le bus, jamais dans un argument. Fail-closed :
    consentement absent ou faux, ou sans sa preuve, ou `client_satisfait = false`, refuse la
    préparation (aucun brouillon écrit) avec un motif explicite dans le résumé rendu — mais le WCT reste
    enregistré dans `wct_recus` dans tous les cas : un refus de demande d'avis n'empêche jamais
    d'enregistrer le fait reçu. Pour un lead v2, le texte dit le libellé du service déclaré par
    l'entreprise ; pour un lead v1, `type_travaux`.

    Idempotent par `wct_id` : un brouillon déjà déposé pour ce wct_id (relivraison de
    l'événement, ou `repartir()` rejoué) n'est jamais dupliqué — no-op qui rend
    `deja_enregistre=True`.

    PLAN T1.5-d, décision écrite (inchangée par T4.17) : cette demande naît de `consentement_demande_avis`,
    un consentement DISTINCT de `consentement_marketing` ; le retrait de ce dernier ne la touche pas.
    """
    wct_id = charge["wct_id"]
    registre_demandes = stockage.maillons(*_REGISTRE_DEMANDES_AVIS)
    for brouillon_existant in registre_demandes:
        if brouillon_existant.get("wct_id") == wct_id:
            return {"brouillon_cree": False, "deja_enregistre": True, "wct_id": wct_id}

    libelle_service, motif_service = _libelle_du_service(charge)
    brouillon, motif = reputation_demande_avis.construire_brouillon(charge, libelle_service, motif_service)
    if brouillon is None:
        return {"brouillon_cree": False, "deja_enregistre": False, "wct_id": wct_id, "motif": motif}

    registre_demandes.append(brouillon)
    return {
        "brouillon_cree": True,
        "deja_enregistre": False,
        "wct_id": wct_id,
        "demande_avis_id": brouillon["id"],
    }


# Ce qu'une ligne de `m7_lister_demandes_avis` porte : de quoi relire le brouillon et la preuve du
# consentement, sans le reste (`lead_id`, `intervention_id` restent au registre). Bornée : `Capacites`
# tronque au-delà de 6 000 caractères, et un brouillon en pèse environ 650, d'où huit au plus.
_CHAMPS_LIGNE_DEMANDE_AVIS = (
    "id", "wct_id", "nature_travaux", "ville", "texte", "approval_status", "avertissements",
)
_LIMITE_DEMANDES_AVIS_DEFAUT = 5
_LIMITE_DEMANDES_AVIS_MAX = 8


def lister_demandes_avis(limite: int = _LIMITE_DEMANDES_AVIS_DEFAUT) -> dict[str, Any]:
    """Les brouillons de demande d'avis que M7 a préparés (PLAN T1.5-d), les plus récents d'abord :
    lecture seule du registre durable `demandes_avis`, sans écrire ni envoyer quoi que ce soit. Chaque
    ligne dit ce qu'on écrirait au client et sur quel consentement (qui l'a recueilli, quand, quel texte).
    `total` compte tous les brouillons ; `reste` ceux que `limite` ne montre pas."""
    if isinstance(limite, bool) or not isinstance(limite, int) or not 1 <= limite <= _LIMITE_DEMANDES_AVIS_MAX:
        raise ValueError(f"limite : un entier de 1 à {_LIMITE_DEMANDES_AVIS_MAX} est attendu")
    demandes = list(stockage.maillons(*_REGISTRE_DEMANDES_AVIS))
    lignes = []
    for demande in reversed(demandes[-limite:]):
        preuve = demande["preuve_consentement"]
        lignes.append({
            **{cle: demande.get(cle) for cle in _CHAMPS_LIGNE_DEMANDE_AVIS},
            "consentement": {
                "recueilli_par": preuve["recueilli_par"], "recueilli_le": preuve["recueilli_le"],
                "version_texte": preuve["version_texte"],
            },
        })
    return {"total": len(demandes), "demandes": lignes, "reste": len(demandes) - len(lignes)}


def consommateurs() -> dict[str, Any]:
    """Types d'événements consommés par M7 (ADR-0009 §3) — voir `department.yaml:evenements.consomme`
    et `docs/architecture/DEPARTEMENTS.md` § Événements."""
    return {"m4.travaux_termines": _recevoir_travaux_termines}


# Même mécanisme de découverte que `consommateurs()` (`opsys.departements.Departement.charger_attentes`) :
# fonction module-level, sans argument, appelée par `approbations.file_proprietaire` et par
# `m9_lister_demandes_approbation` (section « À voir » de l'app admin) DANS une transaction déjà ouverte.
def attentes() -> list[dict[str, Any]]:
    """Ce qui attend le propriétaire chez M7 (PLAN T4.17) : un contenu de chantier `PROPOSE` par ligne, niveau
    N3, que `m7_decider_contenu` approuve ou rejette. Lecture seule : ne décide ni n'exporte rien. Un contenu
    dont le client a retiré son consentement n'y figure plus."""
    return usine_service.attentes()


# ---------------------------------------------------------------------------
# Manifeste des outils
# ---------------------------------------------------------------------------
def outils() -> tuple[Outil, ...]:
    """Capacités exposées aux agents (fonction : les constantes publiques des paquets
    m7_marketing.* sont des énumérés métier, cf. garde AST des paquets)."""
    return (
        Outil(
            nom="m7_lire_profil_marque",
            description=(
                "Valide un profil de marque (name, tagline, tone, colors, langue) contre le contrat gelé Brand Core."
            ),
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
            description=(
                "Audit SEO technique local (title, meta description, lang, h1 unique, JSON-LD valide, "
                "scripts externes, robots.txt). Zéro réseau."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "site_dir": {
                        "type": "string",
                        "description": "Répertoire du site statique (défaut : le site généré du département).",
                    }
                },
                "required": [],
                "additionalProperties": False,
            },
            fonction=auditer_seo_site,
        ),
        Outil(
            nom="m7_evaluer_aeo",
            description=(
                "Évalue la visibilité IA (AEO/GEO) d'une page (règles A-01..A-10 : title, description, h1, schema.org, "
                "citations, NAP LocalBusiness, fraîcheur, cohérence brand)."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "timestamp": {
                        "type": "string",
                        "description": "Horodatage ISO 8601 de référence (jamais d'horloge interne).",
                    },
                    "html_path": {
                        "type": "string",
                        "description": "Chemin d'une page HTML (défaut : le site statique généré).",
                    },
                    "content_item": {
                        "type": "object",
                        "description": "Content-item déjà produit (évalue ce contenu au lieu du site).",
                    },
                },
                "required": ["timestamp"],
                "additionalProperties": False,
            },
            fonction=evaluer_aeo,
        ),
        Outil(
            nom="m7_generer_lien_utm",
            description=(
                "Génère un lien UTM canonique et le valide contre le contrat S012 (U-01..U-12) en un seul appel. "
                "url_base = URL du site de l'entreprise (jamais un domaine par défaut caché)."
            ),
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
                    "date_reference": {
                        "type": "string",
                        "description": "Date de référence ISO (fenêtres actives, snapshot).",
                    },
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
            description=(
                "Compose un content-item (gabarit Brand Core + tactiques SEO/AEO) et le dépose PROPOSE dans la file "
                "d'approbation, en un seul appel. Ne publie jamais."
            ),
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
            description=(
                "Liste les content-items de la file d'approbation 0-6, filtrés par statut (PROPOSE | APPROVED | "
                "REJECTED) si fourni."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "statut": {"type": ["string", "null"], "enum": ["PROPOSE", "APPROVED", "REJECTED", None]}
                },
                "required": [],
                "additionalProperties": False,
            },
            fonction=lister_file_approbation,
            # §9.5 M7 (contenus et réponses aux avis à approuver).
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m7_lister_demandes_avis",
            description=(
                "Liste les brouillons de demande d'avis nés d'un « Terminer » avec le consentement du client "
                "(les plus récents d'abord) : texte proposé, preuve du consentement (qui, quand, quel texte). "
                "Lecture seule : rien n'est envoyé, l'envoi au client reste une décision humaine."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "limite": {
                        "type": "integer", "minimum": 1, "maximum": _LIMITE_DEMANDES_AVIS_MAX,
                        "description": f"Nombre de brouillons montrés (défaut {_LIMITE_DEMANDES_AVIS_DEFAUT}).",
                    }
                },
                "required": [],
                "additionalProperties": False,
            },
            fonction=lister_demandes_avis,
            # §9.5 M7 (avis à approuver) : le brouillon est ce que le propriétaire relit avant d'écrire au client.
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m7_preparer_contenu_public",
            description=(
                "Prépare un brouillon de contenu public (photo de chantier) FLOUTÉ (visages et "
                "plaques), avec la preuve du consentement et le rapport de floutage. Le "
                "consentement vient UNIQUEMENT du WCT m4.travaux_termines déjà reçu par le bus "
                "pour ce wct_id (jamais d'un argument) ; l'identité de marque vient UNIQUEMENT du "
                "profil client configuré (jamais d'un argument). Refuse (fail-closed) si wct_id "
                "est inconnu, si le consentement du WCT reçu est absent/faux, si le profil de "
                "marque n'est pas configuré, ou si le détecteur réel est indisponible. Jamais une "
                "publication : la publication réelle reste N5 (approbation signée du socle)."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "wct_id": {
                        "type": "string",
                        "description": (
                            "Identifiant du WCT m4.travaux_termines déjà reçu par le bus (jamais "
                            "un consentement ou une identité de marque fournis ici)."
                        ),
                    },
                    "photos": {"type": "array", "items": _PHOTO},
                    "seuil_confiance": {
                        "type": "number",
                        "description": "Seuil [0,1] sous lequel une détection force une revue humaine ; jamais deviné.",
                    },
                },
                "required": ["wct_id", "photos", "seuil_confiance"],
                "additionalProperties": False,
            },
            fonction=preparer_contenu_public,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m7_lire_matiere_chantier",
            description=(
                "Ce qu'il faut pour rédiger les contenus d'un chantier terminé : marque, accroche, nature des "
                "travaux, ville, note du chantier (si elle passe le contrôle), mots-clics, plateformes et leurs "
                "plafonds, règles du contrôle. Mêmes refus que m7_proposer_contenus_chantier."
            ),
            parametres={
                "type": "object",
                "properties": {"wct_id": {"type": "string", "description": "WCT m4.travaux_termines déjà reçu."}},
                "required": ["wct_id"],
                "additionalProperties": False,
            },
            fonction=usine_service.lire_matiere_chantier,
        ),
        Outil(
            nom="m7_proposer_contenus_chantier",
            description=(
                "Propose les cinq contenus d'un chantier terminé (Facebook, Instagram, fiche Google, script de "
                "vidéo courte, demande de témoignage) depuis le WCT reçu du bus et le profil de marque : gabarit "
                "du code, ou `textes` rédigés par toi. Chaque texte passe un contrôle en code qui refuse en "
                "nommant la règle (adresse, nom du client, prix, chiffre, garantie non validée, date promise, "
                "exagération, lien). Rien sans consentement marketing prouvé ni après un retrait. Jamais publié : "
                "le propriétaire décide dans « À voir »."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "wct_id": {"type": "string", "description": "WCT m4.travaux_termines déjà reçu."},
                    "textes": _TEXTES_PAR_PLATEFORME,
                },
                "required": ["wct_id"],
                "additionalProperties": False,
            },
            fonction=usine_service.proposer_contenus_chantier,
            # Un brouillon (N1, ADR-0009 §4) : le consommateur du bus les crée déjà sans approbation ; la
            # décision humaine est celle de m7_decider_contenu.
            autonomie=Autonomie.T1,
            niveau=Niveau.N1,
        ),
        Outil(
            nom="m7_lister_contenus_chantier",
            description=(
                "Les contenus de chantier du moment (dernière révision par plateforme), les plus récents d'abord : "
                "statut, texte entier, décision, preuve du consentement. Lecture seule, bornée (huit au plus, "
                "`suivant` pour la page suivante)."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "wct_id": {"type": "string", "description": "Un seul chantier."},
                    "statut": {"type": "string", "enum": list(usine_registre.STATUTS)},
                    "limite": {
                        "type": "integer", "minimum": 1, "maximum": usine_service.LIMITE_LISTE_MAX,
                        "description": f"Contenus montrés (défaut {usine_service.LIMITE_LISTE_DEFAUT}).",
                    },
                    "decalage": {"type": "integer", "minimum": 0, "description": "Rang de départ (`suivant`)."},
                },
                "required": [],
                "additionalProperties": False,
            },
            fonction=usine_service.lister_contenus_chantier,
            # §9.5 M7 (contenus à approuver) : le propriétaire lit le texte entier avant de décider.
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m7_decider_contenu",
            description=(
                "DÉCISION HUMAINE (N3, « À voir ») : le propriétaire approuve ou rejette un contenu de chantier "
                "proposé. Un agent ne peut pas la prendre seul : depuis l'app admin (la personne doit être le "
                "propriétaire), ou en attente d'approbation dans la console. Refuse un consentement retiré, un "
                "contenu déjà tranché ou périmé, un texte qui ne passe plus le contrôle. Un rejet dit pourquoi."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "contenu_id": {"type": "string"},
                    "decision": {"type": "string", "enum": list(usine_decision.DECISIONS)},
                    "horodatage": _HORODATAGE,
                    "motif": {"type": "string", "description": "Obligatoire pour un rejet : ce qu'il faut corriger."},
                },
                "required": ["contenu_id", "decision", "horodatage"],
                "additionalProperties": False,
            },
            fonction=usine_service.decider_contenu,
            autonomie=Autonomie.T1,
            # §9.5 M7 (contenus à approuver), N3 : la personne authentifiée qui agit tient lieu de validation
            # au départ (ADR-0009 §4, T1.4-h), à condition d'être le propriétaire.
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m7_exporter_paquet_manuel",
            description=(
                "Paquet manuel d'un contenu APPROUVÉ : texte, mots-clics, lien de suivi, médias (« à flouter à la "
                "main »), heure suggérée du profil de marque, instructions. Ne publie rien, n'appelle aucune API : "
                "le propriétaire publie lui-même. Refuse un contenu non approuvé ou dont le consentement est retiré."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "contenu_id": {"type": "string"},
                    "horodatage": _HORODATAGE,
                },
                "required": ["contenu_id", "horodatage"],
                "additionalProperties": False,
            },
            fonction=usine_service.exporter_paquet_manuel,
            # Une tâche interne (N2) : la décision humaine est déjà prise (m7_decider_contenu) ; le paquet ne
            # sort de M7 que vers celui qui le demande.
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
            # §9.5 M7 (contenus approuvés) : le propriétaire prend le paquet sur son téléphone.
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m7_enregistrer_retrait_consentement_marketing",
            description=(
                "Le client retire son consentement à l'usage de son chantier en contenu public (Loi 25) : bloque "
                "aussitôt toute tâche de contenu de ce chantier, paquet déjà proposé compris ; ne se lève pas. "
                "Aucun texte libre : canal, personne et heure seulement. Dit ce qui, déjà exporté, se retire à la main."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "wct_id": {"type": "string"},
                    "canal": {"type": "string", "enum": list(usine_retrait.CANAUX_RETRAIT)},
                    "horodatage": _HORODATAGE,
                },
                "required": ["wct_id", "canal", "horodatage"],
                "additionalProperties": False,
            },
            fonction=usine_service.enregistrer_retrait_consentement_marketing,
            # N2 : un retrait ne restreint que (rien n'est publié, rien n'est envoyé) et doit prendre effet à
            # l'instant, sans attendre une approbation (Loi 25).
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
            # Loi 25 : la personne qui reçoit la demande du client (le propriétaire ou son gestionnaire).
            roles_appareil=frozenset({"admin"}),
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
                    "date_reference": {
                        "type": "string",
                        "description": "Date ISO servant à détecter les fenêtres actives.",
                    },
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
            description=(
                "Charge les avis (lecture seule), les classe (litige/urgence/eloge/neutre, déterministe) et calcule "
                "les métriques agrégées m7_rep_*, en un seul appel."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "reponses": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Réponses déjà proposées (pour taux de réponse et délai moyen).",
                    },
                    "chemin_avis": {"type": "string"},
                },
                "required": [],
                "additionalProperties": False,
            },
            fonction=calculer_metriques_reputation,
        ),
        Outil(
            nom="m7_proposer_reponse_avis",
            description=(
                "Classe un avis client puis compose une réponse PROPOSÉE (gabarits Brand Core), en un seul appel. "
                "Statut toujours PROPOSE, jamais auto-publiée."
            ),
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
            description=(
                "Audit de snapshots concurrents locaux (balisage SEO, robots.txt, sitemap, couverture thématique) "
                "contre notre propre site généré."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "slugs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Slugs sous fixtures/concurrents/.",
                    },
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
