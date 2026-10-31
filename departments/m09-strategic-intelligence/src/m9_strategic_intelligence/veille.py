"""Veille de marché M9.14 : des documents publics IMPORTÉS, jamais récupérés, datés, versionnés et reliés aux décisions.

Module pur, sans réseau : la personne importe un document d'une source qu'elle a d'abord DÉCLARÉE (préfixe d'URL https,
licences admises, durée avant péremption). Rien n'est récupéré par M9 : le repli import/export est le seul chemin tant
qu'aucun accès externe n'est autorisé.

Refus avant toute écriture : source inconnue ou retirée, URL hors du préfixe déclaré, licence non admise par la source,
données personnelles apparentes (courriel, téléphone, NAS), document trop gros. Un document dont le texte ressemble à
une
INSTRUCTION (injection) ou qui contient des caractères invisibles est conservé en QUARANTAINE : métadonnées et motifs
visibles, contenu jamais rendu ni citable. Une nouvelle version d'une même URL remplace la précédente dans la lecture
sans
l'effacer ; au-delà de la durée de péremption déclarée par la source, le document est PERIME. Le lien à une décision est
un
événement distinct (``LIEN``) : la veille informe, elle n'autorise rien.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from . import capture_strategique as cs
from . import chainage

SCHEMA = "m9.veille.v1"
TYPES = frozenset({"SOURCE", "SOURCE_RETIREE", "DOCUMENT", "LIEN"})
MAX_CONTENU = 20_000
MAX_EXTRAIT = 280
LICENCES_CONNUES = frozenset({"CC0-1.0", "CC-BY-4.0", "CC-BY-SA-4.0", "OGL-Canada-2.0", "DOMAINE-PUBLIC"})
CATEGORIES = frozenset(
    {"concurrent", "marche", "prix", "avis", "seo", "fournisseur", "reglementation", "saisonnalite", "meteo"}
)
QUALITES = ("public", "estime", "incertain")  # donnée publiée telle quelle / estimée par la personne / à confirmer
_ID = re.compile(r"[a-z0-9][a-z0-9_.\-]{0,63}")
_JOUR = re.compile(r"\d{4}-\d{2}-\d{2}")
_INJECTION = (
    ("IGNORER_INSTRUCTIONS", re.compile(r"ignor\w*\W+(?:\w+\W+){0,3}(?:instructions?|consignes?|prompts?)", re.I)),
    ("PROMPT_SYSTEME", re.compile(r"(?:system|syst[eè]me)\s*prompt|prompt\s+syst[eè]me", re.I)),
    (
        "CHANGEMENT_DE_ROLE",
        re.compile(r"(?:you are now|tu es maintenant|vous [eê]tes maintenant|act as|agis comme)", re.I),
    ),
    (
        "OUBLIER",
        re.compile(
            r"(?:disregard|forget)\W+(?:\w+\W+){0,3}(?:instructions|above|previous)"
            r"|oublie\w*\W+(?:\w+\W+){0,3}instructions",
            re.I,
        ),
    ),
    ("BALISE_DE_ROLE", re.compile(r"<\s*/?\s*(?:system|assistant|tool|instructions?)\b", re.I)),
    ("APPEL_D_OUTIL", re.compile(r"\"(?:tool|function|tool_name|name)\"\s*:\s*\"", re.I)),
    (
        "COMMANDE",
        re.compile(
            r"\b(?:curl|wget)\s+https?://|rm\s+-rf|\bexec(?:ute|ute[zr])?\s+(?:the following|la commande)", re.I
        ),
    ),
    (
        "REVELER",
        re.compile(
            r"(?:reveal|r[eé]v[eè]le\w*|print|affiche\w*)\W+(?:\w+\W+){0,3}(?:prompt|instructions|secrets?)", re.I
        ),
    ),
)
_INVISIBLES = re.compile("[​-‏‪-‮⁠-⁤﻿]")
_PERSONNELLES = (
    ("COURRIEL", re.compile(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+")),
    ("TELEPHONE", re.compile(r"(?<!\d)(?:\+?1[ .\-]?)?\(?\d{3}\)?[ .\-]\d{3}[ .\-]\d{4}(?!\d)")),
    ("NAS", re.compile(r"(?<!\d)\d{3}[ \-]\d{3}[ \-]\d{3}(?!\d)")),
)
_LIMITES = (
    "Documents IMPORTÉS par une personne, de sources déclarées : M9 ne récupère rien et ne vérifie pas la véracité.",
    "Un document en quarantaine ou périmé n'est jamais citable ; un lien à une décision n'est pas une autorisation.",
)


def _refus(code: str, detail: str) -> ValueError:
    return ValueError(f"{code} : {detail}")


def valider_chaine(chaine: Sequence[Mapping]) -> tuple[bool, str]:
    return chainage.valider(SCHEMA, TYPES, chaine)


def analyser_contenu(contenu: str) -> dict:
    """Verdicts déterministes sur un texte : injection (motifs) et données personnelles (types)."""
    motifs = [nom for nom, motif in _INJECTION if motif.search(contenu)]
    if _INVISIBLES.search(contenu):
        motifs.append("CARACTERES_INVISIBLES")
    personnelles = [nom for nom, motif in _PERSONNELLES if motif.search(contenu)]
    return {"injection_suspectee": bool(motifs), "motifs": motifs, "donnees_personnelles": personnelles}


def _jour(valeur: object, nom: str) -> str:
    if type(valeur) is not str or not _JOUR.fullmatch(valeur) or cs.instant(valeur + "T00:00:00Z") is None:
        raise _refus("REJ-VEILLE-DATE", f"{nom} : jour AAAA-MM-JJ valide requis")
    return valeur


_URL_HTTPS = re.compile(
    r"https://([a-z0-9](?:[a-z0-9\-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9\-]*[a-z0-9])?)*)(?::\d{1,5})?(/[^\s?#@]*)?", re.I
)


def _url_sobre(url: object) -> str:
    """URL https sobre : hôte seul (ni identifiants, ni requête, ni fragment), analysée sans module réseau."""
    if type(url) is not str or len(url) > 300 or url.strip() != url:
        raise _refus("REJ-VEILLE-URL", "URL https bornée requise")
    if "?" in url:
        raise _refus("REJ-VEILLE-URL", "aucune chaîne de requête : elle peut porter un jeton ou une donnée privée")
    if "#" in url or "@" in url or not _URL_HTTPS.fullmatch(url):
        raise _refus("REJ-VEILLE-URL", "https sans identifiants ni fragment requis")
    return url


def etat(chaine: Sequence[Mapping], *, connaissance: str) -> dict:
    """Projection à ``connaissance`` : sources, documents (versions remplacées marquées), liens."""
    limite = cs.instant(connaissance)
    if limite is None:
        raise _refus("REJ-CAPTURE-TEMPS", "instant de connaissance avec fuseau explicite requis")
    sources: dict[str, dict] = {}
    documents: dict[str, dict] = {}
    liens: list[dict] = []
    for evenement in chaine:
        recu = cs.instant(evenement["recu_a"])
        if recu is None or recu > limite:
            continue
        type_ = evenement["type"]
        if type_ == "SOURCE":
            sources[evenement["source_id"]] = {**evenement["source"], "actif": True, "declaree_le": evenement["recu_a"]}
        elif type_ == "SOURCE_RETIREE" and evenement["source_id"] in sources:
            sources[evenement["source_id"]]["actif"] = False
        elif type_ == "DOCUMENT":
            documents[evenement["document"]["document_id"]] = {**evenement["document"], "recu_a": evenement["recu_a"]}
        elif type_ == "LIEN":
            liens.append({k: evenement[k] for k in ("document_id", "decision_ref", "note", "recu_a")})
    derniere_version: dict[tuple[str, str], str] = {}
    for doc in documents.values():
        cle = (doc["source_id"], doc["url"])
        courant = documents.get(derniere_version.get(cle, ""))
        if courant is None or (doc["publie_le"], doc["recu_a"]) >= (courant["publie_le"], courant["recu_a"]):
            derniere_version[cle] = doc["document_id"]
    jour_connaissance = limite.date()
    sortie = []
    for doc in sorted(documents.values(), key=lambda d: (d["recu_a"], d["document_id"])):
        source = sources.get(doc["source_id"], {})
        publie = cs.instant(doc["publie_le"] + "T00:00:00Z")
        age = (jour_connaissance - publie.date()).days if publie is not None else None
        statut = doc["statut"]
        if statut == "ACCEPTE":
            if derniere_version[(doc["source_id"], doc["url"])] != doc["document_id"]:
                statut = "REMPLACE"
            elif (
                age is not None and source.get("perime_apres_jours") is not None and age > source["perime_apres_jours"]
            ):
                statut = "PERIME"
        sortie.append({**doc, "statut_courant": statut, "age_jours": age, "citable": statut == "ACCEPTE"})
    par_categorie: dict[str, dict] = {}
    for doc in sortie:
        categorie = sources.get(doc["source_id"], {}).get("categorie", "marche")
        ligne = par_categorie.setdefault(categorie, {"documents": 0, "citables": 0, "par_qualite": {}})
        ligne["documents"] += 1
        ligne["citables"] += 1 if doc["citable"] else 0
        if doc["citable"]:
            qualite_doc = doc.get("qualite", "incertain")
            ligne["par_qualite"][qualite_doc] = ligne["par_qualite"].get(qualite_doc, 0) + 1
    return {
        "type": "ETAT_VEILLE",
        "connaissance": connaissance,
        "sources": [{"source_id": k, **v} for k, v in sorted(sources.items())],
        "par_categorie": {k: par_categorie[k] for k in sorted(par_categorie)},
        "documents": sortie,
        "liens": liens,
        "limites": list(_LIMITES),
    }


def declarer_source(chaine: Sequence[Mapping], source: Mapping, *, recu_a: str, declare_par: str) -> dict:
    """Maillon SOURCE. Une source se redéclare (nouvelle version) tant qu'elle n'est pas retirée."""
    champs = {"source_id", "nom", "url_prefixe", "licences_admises", "perime_apres_jours"}
    if not isinstance(source, Mapping) or not champs <= set(source) <= champs | {"categorie"}:
        raise _refus("REJ-VEILLE-SOURCE", f"source {sorted(champs)} requise, « categorie » facultative")
    categorie = source.get("categorie", "marche")
    if categorie not in CATEGORIES:
        raise _refus("REJ-VEILLE-CATEGORIE", f"catégorie parmi {sorted(CATEGORIES)}")
    if type(source["source_id"]) is not str or not _ID.fullmatch(source["source_id"]):
        raise _refus("REJ-VEILLE-SOURCE", "identifiant minuscule sobre requis")
    if type(source["nom"]) is not str or not source["nom"].strip() or len(source["nom"]) > 200:
        raise _refus("REJ-VEILLE-SOURCE", "nom borné requis")
    prefixe = _url_sobre(source["url_prefixe"])
    licences = source["licences_admises"]
    if type(licences) is not list or not licences or not set(licences) <= LICENCES_CONNUES:
        raise _refus("REJ-VEILLE-LICENCE", f"licences admises parmi {sorted(LICENCES_CONNUES)}")
    peremption = source["perime_apres_jours"]
    if type(peremption) is not int or not 1 <= peremption <= 3650:
        raise _refus("REJ-VEILLE-SOURCE", "perime_apres_jours : entier de 1 à 3650")
    if cs.instant(recu_a) is None:
        raise _refus("REJ-CAPTURE-TEMPS", "instant avec fuseau explicite requis")
    if any(e["type"] == "SOURCE_RETIREE" and e["source_id"] == source["source_id"] for e in chaine):
        raise _refus("REJ-VEILLE-SOURCE", "source retirée : un nouvel identifiant est requis")
    propre = {
        "source_id": source["source_id"],
        "nom": source["nom"],
        "url_prefixe": prefixe,
        "licences_admises": sorted(set(licences)),
        "perime_apres_jours": peremption,
        "categorie": categorie,
    }
    return chainage.suivant(
        SCHEMA,
        chaine,
        {"type": "SOURCE", "source_id": source["source_id"], "source": propre, "recu_a": recu_a, "par": declare_par},
    )


def retirer_source(chaine: Sequence[Mapping], source_id: str, *, recu_a: str, retire_par: str) -> dict:
    if not any(e["type"] == "SOURCE" and e["source_id"] == source_id for e in chaine):
        raise _refus("REJ-VEILLE-SOURCE", "source inconnue")
    if any(e["type"] == "SOURCE_RETIREE" and e["source_id"] == source_id for e in chaine):
        raise _refus("REJ-VEILLE-SOURCE", "source déjà retirée")
    return chainage.suivant(
        SCHEMA, chaine, {"type": "SOURCE_RETIREE", "source_id": source_id, "recu_a": recu_a, "par": retire_par}
    )


def importer(
    chaine: Sequence[Mapping], document: Mapping, *, recu_a: str, importe_par: str
) -> tuple[dict | None, dict]:
    """(maillon à ajouter ou ``None`` si identique déjà importé, document décrit). Refus avant écriture."""
    champs = {"source_id", "url", "titre", "publie_le", "version", "licence", "contenu"}
    if not isinstance(document, Mapping) or not champs <= set(document) <= champs | {"qualite"}:
        raise _refus("REJ-VEILLE-DOCUMENT", f"document {sorted(champs)} requis, « qualite » facultative")
    qualite = document.get("qualite", "incertain")
    if qualite not in QUALITES:
        raise _refus("REJ-VEILLE-QUALITE", f"qualité parmi {list(QUALITES)} ; sans précision : « incertain »")
    if cs.instant(recu_a) is None:
        raise _refus("REJ-CAPTURE-TEMPS", "instant avec fuseau explicite requis")
    source = None
    for evenement in chaine:
        if evenement["type"] == "SOURCE" and evenement["source_id"] == document["source_id"]:
            source = evenement["source"]
        if evenement["type"] == "SOURCE_RETIREE" and evenement["source_id"] == document["source_id"]:
            raise _refus("REJ-VEILLE-SOURCE", "source retirée : import refusé")
    if source is None:
        raise _refus("REJ-VEILLE-SOURCE", "source non déclarée : import refusé")
    url = _url_sobre(document["url"])
    if not url.startswith(source["url_prefixe"]):
        raise _refus("REJ-VEILLE-URL", "URL hors du préfixe déclaré pour la source")
    if document["licence"] not in source["licences_admises"]:
        raise _refus("REJ-VEILLE-LICENCE", "licence non admise par la source : import refusé")
    for nom in ("titre", "version"):
        if type(document[nom]) is not str or not document[nom].strip() or len(document[nom]) > 200:
            raise _refus("REJ-VEILLE-DOCUMENT", f"{nom} : texte borné requis")
    publie = _jour(document["publie_le"], "publie_le")
    contenu = document["contenu"]
    if type(contenu) is not str or not contenu.strip() or len(contenu) > MAX_CONTENU:
        raise _refus("REJ-VEILLE-DOCUMENT", f"contenu : texte de 1 à {MAX_CONTENU} caractères requis")
    analyse = analyser_contenu(contenu)
    if analyse["donnees_personnelles"]:
        raise _refus(
            "REJ-VEILLE-DONNEES-PERSONNELLES",
            f"données personnelles apparentes {analyse['donnees_personnelles']} : à retirer, rien n'est conservé",
        )
    empreinte = cs.empreinte(
        {"source": document["source_id"], "url": url, "version": document["version"], "contenu": contenu}
    )
    document_id = empreinte[:32]
    if any(e["type"] == "DOCUMENT" and e["document"]["document_id"] == document_id for e in chaine):
        existant = next(
            e["document"] for e in chaine if e["type"] == "DOCUMENT" and e["document"]["document_id"] == document_id
        )
        return None, existant
    quarantaine = analyse["injection_suspectee"]
    decrit = {
        "document_id": document_id,
        "source_id": document["source_id"],
        "url": url,
        "titre": document["titre"],
        "publie_le": publie,
        "version": document["version"],
        "licence": document["licence"],
        "qualite": qualite,
        "taille": len(contenu),
        "statut": "QUARANTAINE" if quarantaine else "ACCEPTE",
        "analyse": analyse,
        "extrait": None if quarantaine else contenu[:MAX_EXTRAIT],
        "contenu": None if quarantaine else contenu,
        "provenance": "IMPORT_MANUEL",
        "importe_par": importe_par,
    }
    return chainage.suivant(SCHEMA, chaine, {"type": "DOCUMENT", "document": decrit, "recu_a": recu_a}), decrit


def lier(chaine: Sequence[Mapping], document_id: str, decision_ref: str, note: str, *, recu_a: str) -> dict:
    document = next(
        (e["document"] for e in chaine if e["type"] == "DOCUMENT" and e["document"]["document_id"] == document_id), None
    )
    if document is None:
        raise _refus("REJ-VEILLE-DOCUMENT", "document inconnu")
    if document["statut"] != "ACCEPTE":
        raise _refus("REJ-VEILLE-QUARANTAINE", "un document en quarantaine ne peut pas être relié à une décision")
    if (
        type(decision_ref) is not str
        or not _ID.fullmatch(decision_ref.lower())
        or type(note) is not str
        or len(note) > 300
    ):
        raise _refus("REJ-VEILLE-LIEN", "référence de décision sobre et note bornée requises")
    if cs.instant(recu_a) is None:
        raise _refus("REJ-CAPTURE-TEMPS", "instant avec fuseau explicite requis")
    return chainage.suivant(
        SCHEMA,
        chaine,
        {"type": "LIEN", "document_id": document_id, "decision_ref": decision_ref, "note": note, "recu_a": recu_a},
    )
