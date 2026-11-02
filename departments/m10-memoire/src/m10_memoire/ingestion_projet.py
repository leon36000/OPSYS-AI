"""Ingestion de la mémoire de projet (directives de Nathan, ADR, règles d'agent, condensés, matrices) dans la mémoire de
DÉVELOPPEMENT de M10, isolée des données d'affaires (ADR-0012).

Ce que fait `ingerer(depot)` : lit les fichiers SUIVIS PAR GIT du dépôt que l'ordre de vérité
(`contracts/ordre-verite.v1.json`) met dans son périmètre, et range, de façon déterministe :

- chaque fichier retenu : une source (chemin, empreinte sha256 du contenu, dernier commit et sa date, classe
  d'autorité) et son
  extrait, avec une CLASSIFICATION DE SENSIBILITÉ (`aucune` ou `masquee` : secrets, courriels et téléphones comptés par
  catégorie, jamais cités) ; tout ce qui est rangé passe par l'expurgation existante (`developpement._nettoyer*`) ;
- une directive ou une règle d'agent : une décision PAR SECTION (`## …`), autorité = la classe du fichier ;
- un ADR : une décision (statut lu de son en-tête). Une ligne « Remplace : … » lie l'ADR remplacé à son successeur
  (`superseded_by`) quand le remplacement est TOTAL ; un remplacement partiel (« le point 1 de … ») n'est que consigné ;
- un condensé de prompt de Nathan : un prompt versionné, module lu du nom du fichier (`M7-…` -> `M7`) ;
- une matrice d'exigences : une affirmation par exigence (classe `matrice_vivante`), et tout fichier peut porter un bloc
  ```` ```m10-affirmations ```` (JSON : sujet, attribut, valeur) dont les affirmations prennent la classe de leur
  fichier.
  La détection de contradictions (`contradictions.py`) les compare aux autres sources.

Propriétés :
- **Idempotente.** La clé d'un enregistrement est l'empreinte du contenu : relancer sur le même dépôt n'ajoute RIEN
  (aucun
  événement, aucun maillon). Un fichier modifié ajoute une version (l'ancienne est « remplacée », sa trace reste).
- **Jamais de suppression.** Une section, un ADR ou un condensé qui disparaît de sa source reçoit une nouvelle version
  « archivée » ; une affirmation dont la source a disparu est RETIRÉE (entrée de retrait), pas effacée.
- **Sourcée.** Chaque enregistrement cite le chemin, l'empreinte et la date de sa source.
- **Bornée.** 200 fichiers, 256 Ko par fichier, 4 Mo au total, aucun lien symbolique, aucun chemin privé.
- **Une personne.** Comme tout le domaine développement : identité humaine authentifiée (`developpement._acteur`).

Limite dite sans euphémisme : c'est un analyseur de structure (titres, en-têtes, lignes « Remplace ») sur des fichiers
de ce dépôt. Il ne comprend pas le sens d'une directive ; une directive qui change de sens sans changer de section est
une nouvelle version, pas une contradiction (seule une affirmation à clé en est une).
"""

from __future__ import annotations

import json
import re
import subprocess
import unicodedata
from pathlib import Path
from typing import Any

from opsys import stockage
from opsys.stockage.concurrence import verrou_consultatif

from . import contradictions, contradictions_outils, verite
from . import developpement as dev

MAX_FICHIERS = 200
MAX_OCTETS_TOTAL = 4_000_000
MAX_SECTION_CHARS = 3_000
MAX_AFFIRMATIONS_PAR_FICHIER = 200
MARQUE = "ingestion"

_SECTION = re.compile(r"^##\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_BLOC_AFFIRMATIONS = re.compile(r"```m10-affirmations[ \t]*\n(.*?)\n[ \t]*```", re.DOTALL)
_ADR_ID = re.compile(r"ADR-(\d{4})", re.IGNORECASE)
_LIGNE_STATUT = re.compile(r"^\s*(?:[-*]\s*)?\**Statut\**\s*:?\**\s*:?\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_LIGNE_REMPLACE = re.compile(r"^\s*[-*]?\s*\**Remplace\**\s*:?\**\s*:?\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_LIGNE_DATE = re.compile(r"^\s*(?:[-*]\s*)?\**Date\**\s*:?\**\s*:?\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_MENTION_ADR = re.compile(r"ADR-(\d{4})(?:\s+à\s+ADR-(\d{4}))?", re.IGNORECASE)
_MODULE_NOM = re.compile(r"^M(\d{1,2})-", re.IGNORECASE)


def _slug(titre: str, repli: str) -> str:
    base = unicodedata.normalize("NFKD", titre).encode("ascii", "ignore").decode("ascii").lower()
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")[:60].strip("-")
    return base or repli


def classifier(texte: str) -> dict[str, Any]:
    """La sensibilité d'un contenu : combien de secrets, de courriels et de téléphones il portait (jamais lesquels).
    `masquee` : tout ce qui est rangé en est expurgé ; `aucune` : rien n'a été trouvé."""
    secrets = (
        len(dev._ASSIGNED_SECRET.findall(texte))
        + len(dev._TOKEN_SECRET.findall(texte))
        + len(dev._BEARER_SECRET.findall(texte))
    )
    courriels, telephones = len(dev._EMAIL.findall(texte)), len(dev._PHONE.findall(texte))
    return {
        "niveau": "masquee" if secrets or courriels or telephones else "aucune",
        "secrets": secrets,
        "courriels": courriels,
        "telephones": telephones,
    }


def sections(texte: str) -> list[tuple[str, str]]:
    """Les sections `## titre` (corps jusqu'au titre suivant) ; un `##` dans un bloc de code n'ouvre pas de section."""
    resultat: list[tuple[str, list[str]]] = []
    dans_code = False
    for ligne in texte.splitlines():
        if _FENCE.match(ligne):
            dans_code = not dans_code
        trouve = None if dans_code else _SECTION.match(ligne)
        if trouve:
            resultat.append((trouve.group(1).strip(), []))
        elif resultat:
            resultat[-1][1].append(ligne)
    return [(titre, "\n".join(corps).strip()) for titre, corps in resultat]


def _titre(texte: str, repli: str) -> str:
    trouve = re.search(r"^#\s+(.+?)\s*$", texte, re.MULTILINE)
    return trouve.group(1).strip() if trouve else repli


# ---------------------------------------------------------------------------------------------------------------
# ADR : statut et remplacements
# ---------------------------------------------------------------------------------------------------------------
def statut_adr(ligne: str | None) -> str:
    """Statut du vocabulaire de la mémoire de développement d'après la ligne « Statut ». « Accepted (…qui supersede) »
    est accepté : la mention d'un successeur futur n'est pas un remplacement."""
    texte = (ligne or "").lower()
    if re.search(r"rejet|rejected|refus", texte):
        return "rejected"
    if re.search(r"accept", texte):
        return "active"
    if re.search(r"propos", texte):
        return "draft"
    if re.search(r"remplac|supersed|obsol", texte):
        return "superseded"
    return "requires_review"


def remplacements(ligne: str | None) -> dict[str, list[str]]:
    """`{"total": [numéros], "partiel": [numéros]}` d'une ligne « Remplace : … ». On retire d'abord les parenthèses
    et les
    guillemets (« ADR-0008, réponse au point 5 » n'est pas un remplacement), on coupe à la première phrase, puis chaque
    mention est PARTIELLE si le mot « point » (ou « partiel ») la précède dans sa proposition, TOTALE sinon. Une plage
    « ADR-0001 à ADR-0005 » compte ses cinq numéros."""
    resultat: dict[str, list[str]] = {"total": [], "partiel": []}
    if not ligne:
        return resultat
    texte = re.sub(r"\([^)]*\)", " ", ligne)
    texte = re.sub(r"«[^»]*»", " ", texte)
    texte = re.split(r"\.\s", texte + " ", maxsplit=1)[0]
    fin = 0
    for mention in _MENTION_ADR.finditer(texte):
        avant = texte[fin : mention.start()]
        fin = mention.end()
        debut, dernier = int(mention.group(1)), int(mention.group(2) or mention.group(1))
        if dernier < debut or dernier - debut > 50:
            continue
        categorie = "partiel" if re.search(r"\bpoint\b|\bpartiel", avant, re.IGNORECASE) else "total"
        resultat[categorie].extend(f"{n:04d}" for n in range(debut, dernier + 1))
    return resultat


def _adr(chemin: str, texte: str, sha16: str) -> dict[str, Any] | None:
    numero = _ADR_ID.search(Path(chemin).name)
    if numero is None:
        return None
    statut_brut = next(iter(_LIGNE_STATUT.findall(texte)), None)
    remplace = next(iter(_LIGNE_REMPLACE.findall(texte)), None)
    date = next(iter(_LIGNE_DATE.findall(texte)), None)
    corps = next((c for t, c in sections(texte) if re.match(r"d[ée]cisions?\b", t, re.IGNORECASE)), "") or texte
    lien = remplacements(remplace)
    consequences = []
    if lien["partiel"]:
        consequences.append("Remplace partiellement : " + ", ".join(f"ADR-{n}" for n in lien["partiel"]) + ".")
    if lien["total"]:
        consequences.append("Remplace : " + ", ".join(f"ADR-{n}" for n in lien["total"]) + ".")
    statut = statut_adr(statut_brut)
    return {
        "id": f"adr-{numero.group(1)}",
        "numero": numero.group(1),
        "titre": _titre(texte, Path(chemin).stem),
        "statut": statut,
        "statut_brut": (statut_brut or "")[:200],
        "date": (date or "")[:60],
        "raisons": [corps.strip()[:MAX_SECTION_CHARS]],
        "consequences": consequences,
        "remplace_total": lien["total"],
    }


# ---------------------------------------------------------------------------------------------------------------
# Affirmations : matrices et blocs structurés
# ---------------------------------------------------------------------------------------------------------------
def _affirmations_matrice(texte: str) -> list[dict[str, str]]:
    try:
        donnees = json.loads(texte)
        exigences = donnees["requirements"]
    except (ValueError, KeyError, TypeError):
        return []
    sortie = []
    for exigence in exigences if isinstance(exigences, list) else []:
        if (
            isinstance(exigence, dict)
            and isinstance(exigence.get("id"), str)
            and isinstance(exigence.get("current_status"), str)
        ):
            sortie.append(
                {"sujet": f"exigence:{exigence['id']}", "attribut": "statut", "valeur": exigence["current_status"]}
            )
    return sortie


def _affirmations_bloc(texte: str) -> list[dict[str, str]]:
    sortie: list[dict[str, str]] = []
    for bloc in _BLOC_AFFIRMATIONS.findall(texte):
        try:
            elements = json.loads(bloc)
        except ValueError:
            continue
        for element in elements if isinstance(elements, list) else []:
            if isinstance(element, dict) and set(element) == {"sujet", "attribut", "valeur"}:
                sortie.append({k: element[k] for k in ("sujet", "attribut", "valeur")})
    return sortie


# ---------------------------------------------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------------------------------------------
def _git_sortie(top: Path, *arguments: str) -> str:
    return subprocess.check_output(["git", "-C", str(top), *arguments], text=True, stderr=subprocess.DEVNULL).strip()


def _depot(depot: str | Path) -> tuple[Path, list[str]]:
    racine = Path(depot).expanduser().resolve()
    try:
        top = Path(_git_sortie(racine, "rev-parse", "--show-toplevel")).resolve()
        suivis = subprocess.check_output(["git", "-C", str(top), "ls-files", "-z"], stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("le dépôt Git local n'est pas accessible") from exc
    try:
        racine.relative_to(top)
    except ValueError as exc:
        raise ValueError("le chemin demandé doit rester dans son dépôt Git") from exc
    return top, sorted(p for p in suivis.decode("utf-8", errors="strict").split("\0") if p)


def _dernier_commit(top: Path, chemin: str) -> tuple[str, str]:
    try:
        sortie = _git_sortie(top, "log", "-1", "--format=%H %cI", "--", chemin)
        commit, _, date = sortie.partition(" ")
    except (OSError, subprocess.CalledProcessError):
        return "", ""
    return commit, date


# ---------------------------------------------------------------------------------------------------------------
# L'ingestion
# ---------------------------------------------------------------------------------------------------------------
def _marqueur(chemin: str, element: str, sha16: str) -> str:
    return f"{MARQUE}|{chemin}|{element}|{sha16}"


_MARQUEUR_DECISION = re.compile(rf"{MARQUE}\|([^|]+)\|[^|]*\|[0-9a-z]+")
_MARQUEUR_PROMPT = re.compile(rf" \[{MARQUE}\|([^|\]]+)\|[^|\]]*\|[0-9a-z]+\]$")


def _chemin_du_marqueur(texte: Any, genre: str) -> str | None:
    """Le chemin d'un enregistrement d'ingestion, lu de SON marqueur exact (rien d'autre n'est jamais archivé)."""
    if not isinstance(texte, str):
        return None
    trouve = _MARQUEUR_DECISION.fullmatch(texte) if genre == "decision" else _MARQUEUR_PROMPT.search(texte)
    return trouve.group(1) if trouve else None


def _module_du_condense(chemin: str) -> str:
    trouve = _MODULE_NOM.match(Path(chemin).name)
    return f"M{int(trouve.group(1))}" if trouve else dev.MODULE_TRANSVERSAL


class _Elements:
    """Ce qu'un fichier donne : décisions, prompts, affirmations, avant toute écriture."""

    def __init__(self) -> None:
        self.decisions: list[dict[str, Any]] = []
        self.prompts: list[dict[str, Any]] = []
        self.affirmations: list[dict[str, str]] = []
        self.remplacements_totaux: list[tuple[str, list[str]]] = []  # (decision_id du successeur, numéros remplacés)


def _extraire(genre: str, classe: str, chemin: str, texte: str, sha: str) -> _Elements:
    elements = _Elements()
    sha16 = sha[:16]
    stem = _slug(Path(chemin).stem, "fichier")
    if genre in ("directive", "regle"):
        deja: set[str] = set()
        for position, (titre, corps) in enumerate(sections(texte), 1):
            identifiant = _slug(titre, f"section-{position}")
            if identifiant in deja:
                identifiant = f"{identifiant}-{position}"
            deja.add(identifiant)
            tronque = len(corps) > MAX_SECTION_CHARS
            extrait = corps[:MAX_SECTION_CHARS]
            marque_texte = f"{titre}\n{extrait}"
            elements.decisions.append(
                {
                    "id": f"{'directive' if genre == 'directive' else 'regle-' + stem}-{identifiant}",
                    "contexte": _marqueur(chemin, identifiant, dev._hash(marque_texte)[:16]),
                    "options": [],
                    "raisons": [f"{titre} : {extrait}" if extrait else titre],
                    "consequences": ["Texte tronqué à 3 000 caractères (voir la source)."] if tronque else [],
                    "autorite": classe,
                    "statut": "active",
                }
            )
    elif genre == "adr":
        adr = _adr(chemin, texte, sha16)
        if adr is not None:
            declare, date = adr["statut_brut"] or "non lu", adr["date"] or "non lue"
            autorite = f"{classe} ; statut déclaré : {declare} ; date : {date}"
            elements.decisions.append(
                {
                    "id": adr["id"],
                    "contexte": _marqueur(chemin, adr["id"], dev._hash(json.dumps(adr, sort_keys=True))[:16]),
                    "options": [],
                    "raisons": adr["raisons"],
                    "consequences": adr["consequences"],
                    "autorite": autorite[:300],
                    "statut": adr["statut"],
                    "titre": adr["titre"],
                }
            )
            if adr["remplace_total"]:
                elements.remplacements_totaux.append((adr["id"], adr["remplace_total"]))
    elif genre == "condense":
        elements.prompts.append(
            {
                "id": f"condense-{stem}",
                "texte": texte,
                "module": _module_du_condense(chemin),
                "objectif": f"{_titre(texte, stem)[:150]} [{_marqueur(chemin, 'condense', sha16)}]",
            }
        )
    elif genre == "matrice":
        elements.affirmations.extend(_affirmations_matrice(texte))
    if genre != "matrice":
        elements.affirmations.extend(_affirmations_bloc(texte))
    return elements


def _ecrire_decisions(
    cnx: Any, acteur: tuple[str, str], chemin: str, elements: _Elements, horodatage: str, bilan: dict[str, int]
) -> set[str]:
    produits: set[str] = set()
    for item in elements.decisions:
        entite = f"decision:{item['id']}"
        produits.add(entite)
        marque_propre = dev._nettoyer_texte(item["contexte"])[0]
        courant = dev._dernier(cnx, entite)
        if courant is not None:
            charge = json.loads(courant["payload_json"])
            if charge.get("contexte") == marque_propre and charge.get("status") != "archived":
                bilan["inchanges"] += 1
                continue
        version = courant["version"] + 1 if courant is not None else 1
        payload = dev._charge_decision(
            item["id"],
            version,
            dev.MODULE_TRANSVERSAL,
            item["contexte"],
            item["options"],
            item["raisons"],
            item["consequences"],
            item["autorite"],
            [chemin],
            item["statut"],
        )
        dev._ecrire_decision(cnx, acteur, payload, horodatage)
        bilan["ajoutes" if courant is None else "versions"] += 1
    return produits


def _ecrire_prompts(
    cnx: Any, acteur: tuple[str, str], chemin: str, elements: _Elements, horodatage: str, bilan: dict[str, int]
) -> set[str]:
    produits: set[str] = set()
    for item in elements.prompts:
        entite = f"prompt:{item['id']}"
        produits.add(entite)
        objectif_propre = dev._nettoyer_texte(item["objectif"])[0]
        courant = dev._dernier(cnx, entite)
        if courant is not None:
            charge = json.loads(courant["payload_json"])
            if charge.get("objectif") == objectif_propre and charge.get("status") != "archived":
                bilan["inchanges"] += 1
                continue
        version = courant["version"] + 1 if courant is not None else 1
        payload = dev._charge_prompt(
            item["id"], item["texte"], version, item["module"], item["objectif"], [chemin], "active"
        )
        dev._ecrire_prompt(cnx, acteur, payload, horodatage)
        bilan["ajoutes" if courant is None else "versions"] += 1
    return produits


def _archiver(
    cnx: Any,
    acteur: tuple[str, str],
    produits: set[str],
    chemins_traites: set[str],
    chemins_suivis: set[str],
    horodatage: str,
    bilan: dict[str, int],
) -> None:
    """Une décision ou un prompt d'ingestion dont la source n'en parle plus (section retirée, fichier disparu)
    reçoit une
    version « archivée » : la trace reste, l'état change. Un fichier simplement NON TRAITÉ cette fois (borne atteinte,
    refus) n'archive rien."""
    derniers: dict[str, Any] = {}
    for ligne in cnx.execute("SELECT * FROM events WHERE event_type IN ('decision','prompt') ORDER BY seq"):
        derniers[ligne["entity_id"]] = ligne
    for entite, ligne in sorted(derniers.items()):
        charge = json.loads(ligne["payload_json"])
        champ = "contexte" if ligne["event_type"] == "decision" else "objectif"
        chemin = _chemin_du_marqueur(charge.get(champ), ligne["event_type"])
        if chemin is None or entite in produits or charge.get("status") == "archived":
            continue
        if not (chemin in chemins_traites or chemin not in chemins_suivis):
            continue
        version = ligne["version"] + 1
        if ligne["event_type"] == "decision":
            archive = dev._charge_decision(
                charge["decision_id"],
                version,
                charge["module"],
                f"{MARQUE}|{chemin}|archive|0",
                charge.get("options", []),
                charge["raisons"],
                [*charge.get("consequences", []), "Retirée de sa source : archivée, la trace est conservée."],
                charge["autorite"],
                charge["source_refs"],
                "archived",
            )
            dev._ecrire_decision(cnx, acteur, archive, horodatage)
        else:
            archive = dev._charge_prompt(
                charge["prompt_id"],
                charge["content"],
                version,
                charge["module"],
                re.sub(r"\[ingestion\|[^\]]*\]", f"[{MARQUE}|{chemin}|archive|0]", charge["objectif"]),
                charge["source_refs"],
                "archived",
            )
            dev._ecrire_prompt(cnx, acteur, archive, horodatage)
        bilan["archives"] += 1


def _lier_remplacements(
    cnx: Any, remplacements_totaux: list[tuple[str, list[str]]], horodatage: str, bilan: dict[str, int]
) -> None:
    """ADR remplacé -> ADR qui le remplace (`superseded_by`, comme une nouvelle version d'une décision)."""
    for successeur, numeros in remplacements_totaux:
        nouveau = dev._dernier(cnx, f"decision:{successeur}")
        for numero in numeros:
            ancien = dev._dernier(cnx, f"decision:adr-{numero}")
            if ancien is None or nouveau is None or ancien["event_id"] == nouveau["event_id"]:
                continue
            deja = cnx.execute(
                "SELECT 1 FROM relations WHERE from_event=? AND to_ref=? AND relation_type='superseded_by'",
                (ancien["event_id"], nouveau["event_id"]),
            ).fetchone()
            if deja is None:
                dev._relier(cnx, ancien["event_id"], nouveau["event_id"], "superseded_by", horodatage)
                bilan["remplacements"] += 1


def _source(
    cnx: Any,
    acteur: tuple[str, str],
    top: Path,
    chemin: str,
    sha: str,
    texte: str,
    genre: str,
    classe: str,
    commit: str,
    date: str,
    sensibilite: dict[str, Any],
    horodatage: str,
) -> bool:
    """Range la source (chemin, empreinte, commit, date) et son extrait expurgé. Vrai si elle est nouvelle."""
    source_ref = f"projet:{chemin}@{sha}"
    if cnx.execute("SELECT 1 FROM sources WHERE source_ref=?", (source_ref,)).fetchone() is not None:
        return False  # même contenu déjà rangé (même si le dernier commit a changé entre-temps : retour arrière)
    extrait, masque = dev._nettoyer_texte(texte[: dev.MAX_SNIPPET_CHARS])
    charge = {
        "repository": str(top),
        "commit": commit,
        "path": chemin,
        "sha256": sha,
        "module": dev.MODULE_TRANSVERSAL,
        "redacted": masque,
        "genre": genre,
        "classe_source": classe,
        "sensibilite": sensibilite,
        "source_date": date,
    }
    evenement = dev._ajouter_evenement(
        cnx,
        event_type="source_snapshot",
        entity_id=f"source:{source_ref}",
        version=1,
        payload=charge,
        actor=acteur,
        horodatage=horodatage,
        idempotency_key=f"snapshot:{source_ref}",
    )
    if evenement["replayed"]:
        return False
    cnx.execute(
        "INSERT OR IGNORE INTO sources(source_ref,repository,commit_id,path,sha256,module,excerpt,status,redacted,"
        "scanned_at,event_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            source_ref,
            str(top),
            commit,
            chemin,
            sha,
            dev.MODULE_TRANSVERSAL,
            extrait,
            "redacted" if masque else "active",
            int(masque),
            horodatage,
            evenement["event_id"],
        ),
    )
    return True


def ingerer(
    depot: str | Path,
    *,
    horodatage: str,
    ordre: verite.OrdreVerite | None = None,
    max_fichiers: int = MAX_FICHIERS,
    max_octets: int = MAX_OCTETS_TOTAL,
) -> dict[str, Any]:
    """Ingère le périmètre de l'ordre de vérité depuis `depot`. Voir le docstring du module."""
    acteur = dev._acteur()
    ordre = ordre or verite.charger()
    if not 1 <= max_fichiers <= MAX_FICHIERS or not 1 <= max_octets <= MAX_OCTETS_TOTAL:
        raise ValueError("bornes de l'ingestion au-delà des maximums autorisés")
    dev._valider_horodatage(horodatage)
    top, suivis = _depot(depot)
    candidats: list[tuple[int, str, str, str]] = []
    ignores: list[dict[str, str]] = []
    for chemin in suivis:
        classement = ordre.classement(chemin)
        if classement is None:
            continue
        if dev._chemin_interdit(chemin) or Path(chemin).suffix.lower() not in (".md", ".json"):
            ignores.append({"chemin": chemin, "raison": "chemin privé ou extension hors périmètre"})
            continue
        candidats.append((classement[0], chemin, classement[1], classement[2]))
    # Les motifs les plus précis d'abord (directives, ADR, règles, matrices, condensés), la documentation générale
    # ensuite :
    # si la borne de fichiers est atteinte, c'est elle qui est écartée.
    choisis = [(chemin, classe, genre) for _, chemin, classe, genre in sorted(candidats)]
    for chemin, _, _ in choisis[max_fichiers:]:
        ignores.append({"chemin": chemin, "raison": "limite de fichiers"})
    choisis = choisis[:max_fichiers]

    bilan = {"ajoutes": 0, "versions": 0, "inchanges": 0, "archives": 0, "remplacements": 0, "sources_nouvelles": 0}
    fichiers: list[dict[str, Any]] = []
    produits: set[str] = set()
    traites: set[str] = set()
    a_lier: list[tuple[str, list[str]]] = []
    affirmations_voulues: list[dict[str, str]] = []
    octets = 0
    with dev._connexion() as cnx:
        cnx.execute("BEGIN IMMEDIATE")
        try:
            for chemin, classe, genre in choisis:
                try:
                    donnees = dev._lire_fichier_borne(top, Path(chemin), min(dev.MAX_FILE_BYTES, max_octets - octets))
                    texte = donnees.decode("utf-8")
                except (dev._LimiteScanAtteinte, OSError, ValueError, UnicodeDecodeError):
                    ignores.append(
                        {"chemin": chemin, "raison": "illisible, trop volumineux, symbolique ou non textuel"}
                    )
                    continue
                octets += len(donnees)
                sha = dev._hash_bytes(donnees)
                commit, date = _dernier_commit(top, chemin)
                sensibilite = classifier(texte)
                nouvelle = _source(
                    cnx, acteur, top, chemin, sha, texte, genre, classe, commit, date, sensibilite, horodatage
                )
                bilan["sources_nouvelles"] += 1 if nouvelle else 0
                elements = _extraire(genre, classe, chemin, texte, sha)
                try:
                    produits |= _ecrire_decisions(cnx, acteur, chemin, elements, horodatage, bilan)
                    produits |= _ecrire_prompts(cnx, acteur, chemin, elements, horodatage, bilan)
                except (
                    ValueError
                ) as exc:  # ex. prompt de plus de 64 000 caractères : le fichier est signalé, pas ingéré à moitié
                    ignores.append({"chemin": chemin, "raison": f"enregistrement refusé : {str(exc)[:120]}"})
                    continue
                traites.add(chemin)
                a_lier.extend(elements.remplacements_totaux)
                vues: dict[tuple[str, str], str] = {}
                for a in elements.affirmations[:MAX_AFFIRMATIONS_PAR_FICHIER]:
                    vues[(a["sujet"], a["attribut"])] = a["valeur"]
                for (sujet, attribut), valeur in vues.items():
                    affirmations_voulues.append(
                        {
                            "domaine": "developpement",
                            "sujet": sujet,
                            "attribut": attribut,
                            "valeur": valeur,
                            "classe": classe,
                            "ref": f"projet:{chemin}@{sha}",
                            "emetteur": f"fichier:{chemin}",
                        }
                    )
                fichiers.append(
                    {
                        "chemin": chemin,
                        "sha256": sha,
                        "genre": genre,
                        "classe_source": classe,
                        "commit": commit,
                        "date_source": date,
                        "sensibilite": sensibilite,
                    }
                )
            _archiver(cnx, acteur, produits, traites, set(suivis), horodatage, bilan)
            _lier_remplacements(cnx, a_lier, horodatage, bilan)
            cnx.commit()
        except Exception:
            cnx.rollback()
            raise
        affirmations = _ranger_affirmations(affirmations_voulues, traites, set(suivis), ordre, horodatage)
    return {
        "depot": str(top),
        "fichiers_lus": len(fichiers),
        "ignores": ignores,
        "fichiers": fichiers,
        **bilan,
        "affirmations": affirmations,
        "sensibilite": {
            "fichiers_masques": sum(1 for f in fichiers if f["sensibilite"]["niveau"] == "masquee"),
            "fichiers_propres": sum(1 for f in fichiers if f["sensibilite"]["niveau"] == "aucune"),
        },
    }


def _ranger_affirmations(
    voulues: list[dict[str, str]], traites: set[str], suivis: set[str], ordre: verite.OrdreVerite, horodatage: str
) -> dict[str, Any]:
    """Écrit au registre des affirmations (domaine développement) ce que les fichiers affirment, remplace ce qui a
    changé
    et RETIRE ce que la source n'affirme plus. Même transaction que l'ingestion (le stockage de l'instance)."""
    cnx = stockage.connexion_courante()
    bilan: dict[str, Any] = {"ajoutees": 0, "remplacees": 0, "inchangees": 0, "retirees": 0, "refusees": {}}
    if cnx is None:
        raise RuntimeError("REJ-INGESTION-STOCKAGE: une transaction de l'instance est requise")
    verrou_consultatif(cnx, "m10-affirmations")
    registre = contradictions_outils._REGISTRE_AFFIRMATIONS
    cles_voulues: set[tuple[str, str]] = set()
    for champs in voulues:
        try:
            valide = contradictions.valider(champs, ordre, "ingestion")
        except ValueError as exc:
            code = str(exc).partition(": ")[0]
            bilan["refusees"][code] = bilan["refusees"].get(code, 0) + 1
            continue
        if contradictions_outils.secret_dans(valide):
            bilan["refusees"]["REJ-AFFIRMATION-SECRET"] = bilan["refusees"].get("REJ-AFFIRMATION-SECRET", 0) + 1
            continue
        cles_voulues.add((valide["emetteur"], contradictions.cle_de(valide)))
        try:
            prepare = contradictions.preparer(contradictions.affirmations(registre.lire()), valide, horodatage, ordre)
        except ValueError as exc:
            code = str(exc).partition(": ")[0]
            bilan["refusees"][code] = bilan["refusees"].get(code, 0) + 1
            continue
        if prepare["entree"] is None:
            bilan["inchangees"] += 1
            continue
        registre.ajouter(prepare["entree"])
        bilan["remplacees" if prepare["resultat"] == "remplace" else "ajoutees"] += 1
    for existante in contradictions.affirmations(registre.lire()):
        if not existante["active"] or existante["domaine"] != "developpement" or existante["canal"] != "ingestion":
            continue
        chemin = existante["emetteur"].removeprefix("fichier:")
        disparue = chemin not in suivis
        if (
            chemin in traites and (existante["emetteur"], contradictions.cle_de(existante)) not in cles_voulues
        ) or disparue:
            registre.ajouter(contradictions.entree_retrait(existante, "absente_de_la_source", horodatage))
            bilan["retirees"] += 1
    return bilan
