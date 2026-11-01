"""Garde-fous de CONTENU d'un site (décision d'architecte r6, exigence 2) : ce qu'un site public ne dit jamais.

`guardrail.py` contrôle une PAGE rendue (structure HTML, accessibilité, JSON-LD) ; ce module contrôle le SCHÉMA avant
tout rendu, avec les familles de règles du socle (`opsys.garde_fou_texte`, les mêmes que l'usine à contenu de M7) :

- **Données personnelles** (adresse, courriel, téléphone, nom de client, identifiant interne) : toujours refusées
  dans un texte libre. Les coordonnées de l'ENTREPRISE viennent de la NAP structurée, jamais d'un paragraphe.
- **Promesse chiffrée** (prix ou offre, chiffre avec unité, garantie, date ou délai) : refusée sauf si le bloc
  déclare une `source` (contrat, registre officiel, mesure…) validée par une personne nommée et datée.
- **Texte légal** (vocabulaire juridique, section mentions légales ou confidentialité) : refusé sauf source de
  nature `juridique`. Le code ne rédige aucun avis légal ; il exige qu'un texte légal vienne d'une source.
- **Exagération** et **lien dans le texte** : toujours refusés (rien ne les rend vérifiables).
- **Témoignages** : marqués consentis (statut, preuve, date), auteur en initiales seulement.
- **Copie d'un concurrent** : aucune suite de `LONGUEUR_COPIE` mots en commun avec un snapshot concurrent local.
- **Loi 25** : aucun traceur non essentiel (aucun mécanisme de consentement n'existe dans un site sans JavaScript).
- **Marque** : jamais le gabarit non configuré (`brand/profil_client.PLACEHOLDER_NOM`).

Les motifs du socle sont écrits pour le français ; un complément anglais court (`_MOTIFS_ANGLAIS`) couvre les mêmes
familles pour en-CA. Un motif ne comprend pas le sens (fail-closed) : la règle est nommée, la phrase se récrit.

Module pur : aucune entrée-sortie (les textes concurrents sont fournis par l'appelant).
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

from opsys import garde_fou_texte as socle
from opsys.garde_fou_texte._types import plier

from ..brand.profil_client import PLACEHOLDER_NOM
from .schema_site import TYPES_SECTION_LEGALE, refus

REJ_DONNEE_PERSONNELLE = "REJ-SITE-DONNEE-PERSONNELLE"
REJ_PROMESSE_NON_SOURCEE = "REJ-SITE-PROMESSE-NON-SOURCEE"
REJ_TEXTE_LEGAL_NON_SOURCE = "REJ-SITE-TEXTE-LEGAL-NON-SOURCE"
REJ_EXAGERATION = "REJ-SITE-EXAGERATION"
REJ_LIEN_DANS_TEXTE = "REJ-SITE-LIEN-DANS-TEXTE"
REJ_TEMOIGNAGE_NON_CONSENTI = "REJ-SITE-TEMOIGNAGE-NON-CONSENTI"
REJ_COPIE_CONCURRENT = "REJ-SITE-COPIE-CONCURRENT"
REJ_TRACEUR = "REJ-SITE-TRACEUR-SANS-CONSENTEMENT"
REJ_MARQUE = "REJ-SITE-MARQUE-NON-CONFIGUREE"

CODES_REFUS_CONTENU = (
    REJ_DONNEE_PERSONNELLE, REJ_PROMESSE_NON_SOURCEE, REJ_TEXTE_LEGAL_NON_SOURCE, REJ_EXAGERATION,
    REJ_LIEN_DANS_TEXTE, REJ_TEMOIGNAGE_NON_CONSENTI, REJ_COPIE_CONCURRENT, REJ_TRACEUR, REJ_MARQUE,
)

# Familles du socle et le refus du site qui les regroupe.
_FAMILLES_TOUJOURS = {
    socle.ADRESSE: REJ_DONNEE_PERSONNELLE,
    socle.COORDONNEES: REJ_DONNEE_PERSONNELLE,
    socle.NOM_CLIENT: REJ_DONNEE_PERSONNELLE,
    socle.IDENTIFIANT_INTERNE: REJ_DONNEE_PERSONNELLE,
    socle.LIEN: REJ_LIEN_DANS_TEXTE,
    socle.EXAGERATION: REJ_EXAGERATION,
}
_FAMILLES_PROMESSE = (socle.PRIX_OFFRE, socle.CHIFFRE_NON_SOURCE, socle.GARANTIE_NON_VALIDEE, socle.PROMESSE_DE_DATE)
PROFIL_TEXTE_SITE = socle.profil(
    "m7_texte_site", (*_FAMILLES_TOUJOURS, *_FAMILLES_PROMESSE, socle.AVIS_LEGAL),
)

# Vocabulaire qui fait d'un texte un texte légal (en plus de la famille `avis_legal` du socle), sur le texte plié.
_TEXTE_LEGAL = re.compile(
    r"\bloi\b|\blois\b|\breglement\w*|\brenseignements personnels\b|\bconditions d'utilisation\b|"
    r"\bresponsabilite\w*|\blaw\b|\blaws\b|\blegal\w*|\bregulation\w*|\bpersonal information\b|\bliabilit\w*|"
    r"\bterms of (?:use|service)\b|\bprivacy act\b"
)

# Complément anglais des familles du socle (texte plié). Même partage : toujours refusé / refusé sans source.
_MOTIFS_ANGLAIS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (REJ_EXAGERATION, re.compile(
        r"\bbest\b|\bnumber one\b|#\s?1\b|\bunbeatable\b|\bcheapest\b|\bperfect\w*|\bleading\b|\bunmatched\b|"
        r"\bflawless\b"
    )),
    (REJ_PROMESSE_NON_SOURCEE, re.compile(
        r"\$\s*\d|\d\s*\$|\bfree\b|\bdiscount\w*|\bfinancing\b|\bprices?\b|\bpricing\b|\bcosts?\b|"
        r"\bguarant\w*|\bwarrant\w*|\blifetime\b|\bmoney.back\b|\brisk.free\b|"
        r"\b\d+(?:[.,]\d+)?\s*(?:%|years?|hours?|days?|weeks?|months?|sq\.? ?ft|feet|foot|ft|inch\w*)\b|"
        r"\btomorrow\b|\bwithin \d+|\bnext (?:week|month|year)\b"
    )),
)

# Forme des identifiants internes d'OPSYS (chantier, lead, devis, bon de commande, facture), en plus de ceux que
# l'appelant fournit (`identifiants_interdits`) : un site public n'en cite jamais.
_IDENTIFIANT_OPSYS = re.compile(r"\b(?:wct|lead|devis|po|fac|int)-[a-z0-9][a-z0-9-]*")

LONGUEUR_COPIE = 8  # mots consécutifs en commun avec un concurrent : au-delà du hasard d'une expression courante
_MOT = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)?")


def _localises(valeur: Any) -> Iterator[tuple[str, str]]:
    """(langue, texte) d'un texte localisé ou d'une liste de paragraphes localisée."""
    if not isinstance(valeur, Mapping):
        return
    for langue in sorted(valeur):
        contenu = valeur[langue]
        if isinstance(contenu, str):
            yield langue, contenu
        elif isinstance(contenu, list):
            yield from ((langue, p) for p in contenu if isinstance(p, str))


def textes_libres(schema: Mapping[str, Any]) -> Iterator[tuple[str, str, str | None, bool]]:
    """Chaque texte libre du schéma : (chemin, texte, identifiant de source du bloc ou None, bloc légal ?).

    Les champs structurés (NAP, heures, initiales, slugs, couleurs) ne sont pas des textes libres : ils sont
    validés par `schema_site` et rendus par le code."""
    entreprise = schema.get("entreprise", {})
    for langue, texte in _localises(entreprise.get("description")):
        yield f"$.entreprise.description.{langue}", texte, None, False
    for i, image in enumerate(schema.get("images", [])):
        for langue, texte in _localises(image.get("alt")):
            yield f"$.images[{i}].alt.{langue}", texte, None, False
    for i, service in enumerate(schema.get("services", [])):
        for cle in ("nom", "resume", "description"):
            for langue, texte in _localises(service.get(cle)):
                yield f"$.services[{i}].{cle}.{langue}", texte, service.get("source"), False
    for i, temoignage in enumerate(schema.get("temoignages", [])):
        for langue, texte in _localises(temoignage.get("texte")):
            yield f"$.temoignages[{i}].texte.{langue}", texte, None, False
    for i, question in enumerate(schema.get("faq", [])):
        for cle in ("question", "reponse"):
            for langue, texte in _localises(question.get(cle)):
                yield f"$.faq[{i}].{cle}.{langue}", texte, question.get("source"), False
    for i, cta in enumerate(schema.get("cta", [])):
        for langue, texte in _localises(cta.get("libelle")):
            yield f"$.cta[{i}].libelle.{langue}", texte, None, False
    sources_legales: dict[str, Any] = {}
    for i, page in enumerate(schema.get("pages", [])):
        # Le titre et la description d'une page légale NOMMENT un sujet légal : ils relèvent de la source juridique
        # de la section légale de la page, jamais d'une source absente.
        source_page = next(
            (s.get("source") for s in page.get("sections", []) if s.get("type") in TYPES_SECTION_LEGALE), None
        )
        for section in page.get("sections", []):
            if section.get("type") in TYPES_SECTION_LEGALE:
                sources_legales[section["type"]] = section.get("source")
        for cle in ("titre", "titre_nav", "description"):
            for langue, texte in _localises(page.get(cle)):
                yield f"$.pages[{i}].{cle}.{langue}", texte, source_page, False
        for j, section in enumerate(page.get("sections", [])):
            legal = section.get("type") in TYPES_SECTION_LEGALE
            for cle in ("titre", "texte", "paragraphes"):
                for langue, texte in _localises(section.get(cle)):
                    # Le titre d'une section légale (« Confidentialité ») n'est pas un texte légal en soi.
                    yield (
                        f"$.pages[{i}].sections[{j}].{cle}.{langue}", texte, section.get("source"),
                        legal and cle != "titre",
                    )
    responsable = schema.get("legal", {}).get("responsable_rp", {})
    for langue, texte in _localises(responsable.get("titre")):
        yield f"$.legal.responsable_rp.titre.{langue}", texte, sources_legales.get("confidentialite"), False


def _shingles(texte: str) -> set[tuple[str, ...]]:
    mots = _MOT.findall(plier(texte))
    return {tuple(mots[i:i + LONGUEUR_COPIE]) for i in range(len(mots) - LONGUEUR_COPIE + 1)}


def controler_contenu(
    schema: Mapping[str, Any],
    *,
    textes_concurrents: Mapping[str, str] | None = None,
    noms_interdits: Sequence[str] = (),
    identifiants_interdits: Sequence[str] = (),
) -> list[dict[str, str]]:
    """Les refus de contenu d'un schéma DÉJÀ valide structurellement, dans l'ordre du schéma ; vide s'il passe.

    `textes_concurrents` : {slug: texte visible} de snapshots concurrents locaux. `noms_interdits` : noms de clients
    réels connus (CRM) qui ne doivent apparaître nulle part ; le contrôle reconnaît aussi les FORMES d'un nom.
    `identifiants_interdits` : identifiants internes connus (dossiers), en plus de la forme `wct-…`, `lead-…`."""
    resultat: list[dict[str, str]] = []
    entreprise = schema.get("entreprise", {})
    nom = str(entreprise.get("nom", ""))
    if nom == PLACEHOLDER_NOM or "configurer" in plier(nom):
        resultat.append(refus(REJ_MARQUE, "$.entreprise.nom", "nom de marque non configuré : gabarit refusé"))
    if schema.get("legal", {}).get("traceurs_non_essentiels") is not False:
        resultat.append(refus(
            REJ_TRACEUR, "$.legal.traceurs_non_essentiels",
            "aucun traceur non essentiel : la Loi 25 exige un consentement actif préalable, qu'un site statique "
            "sans JavaScript ne recueille pas (analytique : hors tranche 1)",
        ))
    for i, temoignage in enumerate(schema.get("temoignages", [])):
        consentement = temoignage.get("consentement", {})
        if (
            consentement.get("statut") != "consenti" or not str(consentement.get("preuve", "")).strip()
            or not str(consentement.get("date", "")).strip()
        ):
            resultat.append(refus(
                REJ_TEMOIGNAGE_NON_CONSENTI, f"$.temoignages[{i}].consentement",
                "témoignage publié seulement s'il est consenti : statut « consenti », preuve et date",
            ))

    sources = {s.get("id"): s for s in schema.get("sources", []) if isinstance(s, Mapping)}
    contexte = socle.Contexte(
        noms_de_marque=(nom,) if nom else (), noms_clients=tuple(noms_interdits),
        identifiants=tuple(identifiants_interdits),
    )
    concurrents = {slug: _shingles(texte) for slug, texte in sorted((textes_concurrents or {}).items())}
    for chemin, texte, source_id, legal in textes_libres(schema):
        source = sources.get(source_id) if source_id else None
        resultat.extend(_controler_texte(chemin, texte, source, legal, contexte))
        communs = _shingles(texte)
        for slug, empreintes in concurrents.items():
            commun = sorted(communs & empreintes)
            if commun:
                resultat.append(refus(
                    REJ_COPIE_CONCURRENT, chemin,
                    f"{LONGUEUR_COPIE} mots consécutifs repris du concurrent {slug!r} : « {' '.join(commun[0])} »",
                ))
    return resultat


def _controler_texte(
    chemin: str, texte: str, source: Mapping[str, Any] | None, legal: bool, contexte: socle.Contexte
) -> list[dict[str, str]]:
    trouves: dict[str, str] = {}
    for violation in socle.controler(texte, PROFIL_TEXTE_SITE, contexte):
        if violation.famille in _FAMILLES_TOUJOURS:
            code = _FAMILLES_TOUJOURS[violation.famille]
        elif violation.famille == socle.AVIS_LEGAL:
            code = REJ_TEXTE_LEGAL_NON_SOURCE
        else:
            code = REJ_PROMESSE_NON_SOURCEE
        trouves.setdefault(code, f"{violation.regle} : {violation.detail}")
    plie = plier(texte)
    trouve = _IDENTIFIANT_OPSYS.search(plie)
    if trouve is not None:
        trouves.setdefault(REJ_DONNEE_PERSONNELLE, f"identifiant interne « {trouve.group(0)} »")
    for code, motif in _MOTIFS_ANGLAIS:
        trouve = motif.search(plie)
        if trouve is not None:
            trouves.setdefault(code, f"« {trouve.group(0)} »")
    trouve = _TEXTE_LEGAL.search(plie)
    if trouve is not None:
        trouves.setdefault(REJ_TEXTE_LEGAL_NON_SOURCE, f"vocabulaire légal « {trouve.group(0)} »")
    if legal:
        trouves.setdefault(REJ_TEXTE_LEGAL_NON_SOURCE, "section légale")
    if source is not None:
        trouves.pop(REJ_PROMESSE_NON_SOURCEE, None)
        if source.get("nature") == "juridique":
            trouves.pop(REJ_TEXTE_LEGAL_NON_SOURCE, None)
    details = {
        REJ_PROMESSE_NON_SOURCEE: "promesse chiffrée, prix, garantie ou délai sans source déclarée",
        REJ_TEXTE_LEGAL_NON_SOURCE: "texte légal sans source de nature « juridique » validée",
    }
    return [
        refus(code, chemin, f"{details.get(code, 'interdit dans un texte public')} ({detail})")
        for code, detail in sorted(trouves.items(), key=lambda kv: CODES_REFUS_CONTENU.index(kv[0]))
    ]
