"""Chaîne « site web » de M7 : schéma -> garde-fous -> rendu Python -> contrôle qualité -> paquet -> plan -> demande.

Les outils de `outils.py` sont des enveloppes minces sur ces fonctions. Ordre fixe, fail-closed : un refus de
structure arrête tout (le contenu n'est pas lu sur un schéma mal formé) ; un refus de contenu ou d'actif arrête le
rendu ; un contrôle qualité non conforme arrête le paquet ; un site fictif, une empreinte différente de celle qui
est demandée ou l'absence d'un humain qui approuve arrêtent la demande de publication.

La publication publique est N3+ (validation de la direction). `demander_publication` ne publie JAMAIS : appelée par
un agent, la demande attend dans la file d'approbation du socle (mode `ombre`) ; exécutée après l'approbation du
propriétaire, elle rend le plan approuvé avec le statut `PUBLICATION_APPROUVEE_NON_EXECUTEE`. Aucun déploiement,
aucune connexion SSH n'existe dans OPSYS (docs/sites-web.md).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from opsys.stockage.moteur import dossier_opsys

from ..competitive.loader import load_fixture
from ..studio import portes
from ..usine import verdicts
from . import deploiement, garde_contenu, paquet, qa_site, rendu_statique, schema_site

_RACINE_M7 = Path(__file__).resolve().parents[3]
DOSSIER_DEMOS = _RACINE_M7 / "fixtures" / "sites"
DOSSIER_CONCURRENTS = _RACINE_M7 / "fixtures" / "concurrents"
SCHEMAS_DEMO = ("revetements-horizon-fictif",)

REJ_SCHEMA_SOURCE = "REJ-SITE-SCHEMA-SOURCE"
REJ_CONCURRENT = "REJ-SITE-CONCURRENT-ILLISIBLE"
REJ_QA = "REJ-SITE-QA-NON-CONFORME"
REJ_PAQUET_EXISTANT = "REJ-SITE-PAQUET-EXISTANT"
REJ_PUBLICATION_FICTIF = "REJ-PUBLICATION-SITE-FICTIF"
REJ_PUBLICATION_EMPREINTE = "REJ-PUBLICATION-EMPREINTE-DIFFERENTE"
STATUT_APPROUVEE = "PUBLICATION_APPROUVEE_NON_EXECUTEE"
NOM_OUTIL_PUBLICATION = "m7_demander_publication_site"


def _refus(*refus: Mapping[str, str]) -> dict[str, Any]:
    return {"accepte": False, "refus": [dict(r) for r in refus]}


def _lire_actifs(dossier: Path, schema: Mapping[str, Any]) -> dict[str, bytes]:
    """Les images déclarées, lues PAR NOM (déjà validé `images/<nom>.svg|png`) dans `dossier` : jamais un chemin
    fourni par l'appelant."""
    actifs = {}
    for image in schema.get("images", []):
        chemin = dossier / image["fichier"]
        if chemin.is_file():
            actifs[image["fichier"]] = chemin.read_bytes()
    return actifs


def dossier_site(site_id: str) -> Path:
    """`$OPSYS_HOME/sites/<site_id>` : actifs (`actifs/images/...`) et paquets (`paquets/<version>/`)."""
    return dossier_opsys() / "sites" / site_id


def resoudre_schema(
    schema: Mapping[str, Any] | None, schema_demo: str | None
) -> tuple[Mapping[str, Any] | None, dict[str, bytes], dict[str, Any] | None]:
    """(schéma, actifs, refus). Exactement un des deux : un schéma fourni (actifs lus dans `$OPSYS_HOME/sites/<id>/
    actifs/`) ou le nom d'une démonstration fictive livrée (`fixtures/sites/<nom>/`)."""
    if (schema is None) == (schema_demo is None):
        return None, {}, _refus(schema_site.refus(
            REJ_SCHEMA_SOURCE, "$", f"fournir exactement un de schema ou schema_demo ({list(SCHEMAS_DEMO)})",
        ))
    if schema_demo is not None:
        if schema_demo not in SCHEMAS_DEMO:
            inconnue = schema_site.refus(REJ_SCHEMA_SOURCE, "$", f"démonstration inconnue {schema_demo!r}")
            return None, {}, _refus(inconnue)
        dossier = DOSSIER_DEMOS / schema_demo
        charge = json.loads((dossier / "site.json").read_text(encoding="utf-8"))
        return charge, _lire_actifs(dossier / "actifs", charge), None
    refus = schema_site.valider_schema(schema)
    if refus:
        return None, {}, _refus(*refus)
    return schema, _lire_actifs(dossier_site(schema["site_id"]) / "actifs", schema), None


def textes_concurrents(slugs: Sequence[str] | None) -> tuple[dict[str, str], list[dict[str, str]]]:
    """Texte visible des snapshots concurrents locaux (`fixtures/concurrents/<slug>/`, chargeur de la veille
    concurrentielle, fictifs exigés) ; aucun crawl réseau."""
    textes, refus = {}, []
    for slug in sorted(set(slugs or ())):
        try:
            donnees = load_fixture(slug, str(DOSSIER_CONCURRENTS))
        except (OSError, ValueError) as exc:
            refus.append(schema_site.refus(REJ_CONCURRENT, f"$.concurrents.{slug}", f"snapshot illisible : {exc}"))
            continue
        textes[slug] = qa_site.texte_visible(donnees["index_html"])
    return textes, refus


def images_du_studio(
    schema: Mapping[str, Any], actifs: Mapping[str, bytes], resolveur: portes.Resolveur
) -> list[dict[str, str]]:
    """Refus des images du site qui sont des actifs du studio créatif non approuvés (ou des fonds bruts) : un fond
    généré ne se publie jamais tel quel, un visuel composé seulement une fois approuvé par une personne (N3)."""
    refus: list[dict[str, str]] = []
    for image in schema.get("images", []):
        octets = actifs.get(image["fichier"])
        if octets is not None:
            refus += portes.controler_image_site(image["id"], hashlib.sha256(octets).hexdigest(), resolveur)
    return refus


def construire_site(
    schema: Mapping[str, Any],
    actifs: Mapping[str, bytes],
    *,
    concurrents: Mapping[str, str] | None = None,
    noms_interdits: Sequence[str] = (),
    actifs_studio: portes.Resolveur | None = None,
) -> dict[str, Any]:
    """`{accepte, fichiers, qa}` ou `{accepte: False, refus}`. Les fichiers ne sont écrits nulle part. `actifs_studio` :
    résolveur du registre des actifs du studio créatif (les outils de M7 le fournissent toujours)."""
    refus = schema_site.valider_schema(schema)
    if refus:
        return _refus(*refus)
    refus = garde_contenu.controler_contenu(schema, textes_concurrents=concurrents, noms_interdits=noms_interdits)
    refus += rendu_statique.verifier_actifs(schema, actifs)
    if actifs_studio is not None:
        refus += images_du_studio(schema, actifs, actifs_studio)
    if refus:
        return _refus(*refus)
    fichiers = rendu_statique.rendre_site(schema, actifs)
    return {"accepte": True, "fichiers": fichiers, "qa": qa_site.controler_site(fichiers, schema)}


def preparer_paquet(
    schema: Mapping[str, Any],
    actifs: Mapping[str, bytes],
    version: str,
    cible: Mapping[str, Any],
    *,
    concurrents: Mapping[str, str] | None = None,
    noms_interdits: Sequence[str] = (),
    actifs_studio: portes.Resolveur | None = None,
) -> dict[str, Any]:
    """`{accepte, archive, manifeste, plan, qa}` : rien n'est écrit ni exécuté (voir `ecrire_paquet`)."""
    if not paquet.version_valide(version):
        return _refus(schema_site.refus(paquet.REJ_VERSION, "$.version", "version AAAAMMJJTHHMMSSZ (UTC) attendue"))
    construit = construire_site(schema, actifs, concurrents=concurrents, noms_interdits=noms_interdits,
                                actifs_studio=actifs_studio)
    if not construit["accepte"]:
        return construit
    qa = construit["qa"]
    if not qa["conforme"]:
        echecs = [c["code"] for c in qa["controles"] if not c["ok"]]
        return {**_refus(schema_site.refus(REJ_QA, "$", f"contrôle qualité non conforme : {echecs}")), "qa": qa}
    cible_normale, refus = deploiement.valider_cible(cible, schema["domaine"])
    if refus:
        return _refus(*refus)
    archive, manifeste = paquet.construire_paquet(construit["fichiers"], schema, version, qa)
    plan = deploiement.planifier_deploiement(
        manifeste, cible_normale, rendu_statique.feuille_de_style(schema["charte"])
    )
    return {"accepte": True, "archive": archive, "manifeste": manifeste, "plan": plan, "qa": qa}


def ecrire_paquet(prepare: Mapping[str, Any], dossier: Path) -> dict[str, Any]:
    """Écrit l'artefact (archive, manifeste, Caddyfile, plan JSON et Markdown) dans `dossier/<version>/`. Une version
    est immuable : le même contenu est un rejeu (`deja_prepare`), un autre contenu est refusé."""
    manifeste = prepare["manifeste"]
    cible = dossier / manifeste["version"]
    contenus = {
        manifeste["archive"]["nom"]: prepare["archive"],
        "MANIFESTE.json": paquet.manifeste_json(manifeste),
        "Caddyfile": prepare["plan"]["caddyfile"].encode("utf-8"),
        "PLAN-DEPLOIEMENT.json": (
            json.dumps(prepare["plan"], ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8"),
        "PLAN-DEPLOIEMENT.md": deploiement.plan_lisible(prepare["plan"]).encode("utf-8"),
    }
    archive_existante = cible / manifeste["archive"]["nom"]
    if cible.exists():
        if archive_existante.is_file() and archive_existante.read_bytes() == prepare["archive"]:
            return {"accepte": True, "deja_prepare": True, "dossier": str(cible), "fichiers": sorted(contenus)}
        return _refus(schema_site.refus(
            REJ_PAQUET_EXISTANT, "$.version",
            f"la version {manifeste['version']} existe déjà avec un autre contenu : une version est immuable",
        ))
    cible.mkdir(parents=True, mode=0o700)
    for nom, octets in contenus.items():
        (cible / nom).write_bytes(octets)
    return {"accepte": True, "deja_prepare": False, "dossier": str(cible), "fichiers": sorted(contenus)}


def demander_publication(
    schema: Mapping[str, Any],
    actifs: Mapping[str, bytes],
    version: str,
    empreinte_archive: str,
    cible: Mapping[str, Any],
    *,
    concurrents: Mapping[str, str] | None = None,
    actifs_studio: portes.Resolveur | None = None,
) -> dict[str, Any]:
    """La demande de publication publique (N3+), jamais exécutée ici.

    Refusée : site fictif, paquet non préparable (structure, contenu, QA, cible), empreinte d'archive différente de
    celle qui est demandée, ou aucun humain qui approuve (le propriétaire, `nathan_owner`, par la file
    d'approbation ; même règle que les décisions de contenu, `usine.service._proprietaire_qui_decide`). Acceptée :
    le plan approuvé, `execute: False`. La personne responsable exécute le plan à la main."""
    # Import local : `usine.service` tire le stockage et le bus ; la chaîne pure ci-dessus n'en dépend pas.
    from ..usine import service as usine_service

    if schema.get("fictif") is not False:
        return _refus(schema_site.refus(
            REJ_PUBLICATION_FICTIF, "$.fictif", "un site fictif (démonstration) n'est jamais publié publiquement",
        ))
    acteur, refus_humain = usine_service._proprietaire_qui_decide(NOM_OUTIL_PUBLICATION)
    if acteur is None:
        verdict = refus_humain or verdicts.verdict(verdicts.REJ_HUMAIN_REQUIS, "approbation humaine introuvable")
        return _refus(schema_site.refus(
            verdict["code"], "$",
            f"{verdict['detail']} Publier un site est une décision de la direction (N3+) : la demande attend dans "
            "la file d'approbation, elle n'est jamais exécutée par l'agent.",
        ))
    prepare = preparer_paquet(schema, actifs, version, cible, concurrents=concurrents, actifs_studio=actifs_studio)
    if not prepare["accepte"]:
        return prepare
    archive = prepare["manifeste"]["archive"]
    if empreinte_archive != archive["sha256"]:
        return _refus(schema_site.refus(
            REJ_PUBLICATION_EMPREINTE, "$.empreinte_archive",
            f"l'archive préparée a l'empreinte {archive['sha256']} : la demande doit porter exactement celle-ci",
        ))
    return {
        "accepte": True,
        "statut": STATUT_APPROUVEE,
        "execute": False,
        "approbation": acteur,
        "archive": archive,
        "version": version,
        "plan": prepare["plan"],
        "execution": (
            "Aucune : OPSYS ne déploie pas et n'ouvre aucune connexion SSH. La personne responsable exécute le plan "
            "à la main, dans l'ordre, puis les vérifications ; le retour arrière est dans le plan."
        ),
    }
