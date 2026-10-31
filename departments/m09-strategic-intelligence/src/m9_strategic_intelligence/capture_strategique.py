"""Captures stratégiques M9.1 : lectures de producteurs conservées avec quatre temps distincts, chaînées et vérifiables.

Module pur (ADR-0009) : aucun import d'``opsys``, aucune horloge. L'adaptateur lit un producteur par le port privé du
socle
(``opsys.lecteurs_m9``), puis fournit la réponse, l'instant de réception ``recu_a`` et la référence de lecture ; ce
module
construit, valide et interroge les captures.

Les QUATRE temps ne se confondent jamais :

* ``instants_metier`` — ce que le PRODUCTEUR déclare de l'instant des faits (chemins du catalogue) : min/max/nombre ;
* ``reference`` — l'instant que l'appelant a demandé de lire (« où en est-on au… ») ; il ne prouve rien du producteur ;
* ``recu_a`` — quand M9 a CONNU cette réponse ; monotone dans la chaîne ; fonde « ce qui était connu à telle date » ;
* l'âge n'est qu'un écart signé (référence − dernier instant métier), jamais un SLA ni une fraîcheur.

Une capture n'est pas une vérité : c'est la trace d'une lecture reçue du propriétaire. Une réponse refusée ou en erreur
est
conservée comme telle (un manque se prouve). Une page suivante non lue rend la capture ``PARTIELLE``. Une correction de
source
(même lecture, mêmes arguments, révision ou instant plus récent) s'ajoute ; elle ne remplace ni ne réécrit l'ancienne.
Deux
réponses différentes pour la même lecture, les mêmes arguments, la même révision et le même instant sont une
CONTRADICTION
conservée, jamais arbitrée ici.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal

from . import catalogue_producteurs, charges_producteurs, encodage

SCHEMA = "opsys.m9.capture/v1"
HASH_INITIAL = ""
MAX_OCTETS_DEFAUT = 900_000
MAX_PAGES = 50
MAX_REVISIONS = 256
FRAICHEUR_MAX_S = 3650 * 86400  # 3650 jours : la borne que M9 applique à ses propres péremptions
_HEX = re.compile(r"[0-9a-f]{64}")
_JOUR = re.compile(r"\d{4}-\d{2}-\d{2}")
VERDICTS = frozenset({"ACCEPTEE", "REFUSEE", "ERREUR"})
REGLE_CONTRADICTION = "meme_lecture_memes_arguments_meme_revision_meme_instant_empreinte_differente/v1"
_CHAMPS = frozenset(
    {
        "schema", "index", "hash_precedent", "hash_maillon", "catalogue_version", "lecture_id", "departement", "outil",
        "arguments", "arguments_sha256", "pages", "reponse_sha256", "verdict", "code", "complete", "raison_incomplete",
        "recu_a", "reference", "reference_jour", "instants_metier", "revisions", "limites",
    }
)  # fmt: skip
_LIMITES = (
    "Réponse reçue d'un producteur : ni authenticité du producteur au-delà du port serveur, ni vérité, ni fraîcheur "
    "métier.",
    "Le temps métier est celui que le producteur déclare ; absent, il reste non déclaré (jamais déduit de la "
    "réception).",
)


def _refus(code: str, detail: str) -> ValueError:
    return ValueError(f"{code} : {detail}")


def normaliser(valeur: object, _profondeur: int = 0) -> object:
    """Forme JSON stable d'une réponse de producteur : Decimal en texte exact (jamais un flottant), dates en ISO 8601,
    tuples en listes, clés en texte. Tout autre type (ensemble, objet) est refusé plutôt que converti à l'aveugle."""
    if _profondeur > 64:
        raise _refus("REJ-CAPTURE-JSON", "profondeur excessive")
    if valeur is None or isinstance(valeur, (bool, int, str)):
        return valeur
    if isinstance(valeur, float):
        if valeur != valeur or valeur in (float("inf"), float("-inf")):
            raise _refus("REJ-CAPTURE-JSON", "nombre non fini")
        return valeur
    if isinstance(valeur, Decimal):
        if not valeur.is_finite():
            raise _refus("REJ-CAPTURE-JSON", "Decimal non fini")
        return format(valeur, "f")
    if isinstance(valeur, (datetime, date)):
        return valeur.isoformat()
    if isinstance(valeur, Mapping):
        if not all(isinstance(cle, str) for cle in valeur):
            raise _refus("REJ-CAPTURE-JSON", "clés textuelles requises")
        return {cle: normaliser(element, _profondeur + 1) for cle, element in valeur.items()}
    if isinstance(valeur, (list, tuple)):
        return [normaliser(element, _profondeur + 1) for element in valeur]
    raise _refus("REJ-CAPTURE-JSON", f"type non représentable : {type(valeur).__name__}")


def canonique(valeur: object) -> str:
    try:
        return json.dumps(valeur, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError, RecursionError, OverflowError) as exc:
        raise _refus("REJ-CAPTURE-JSON", "JSON fini et représentable requis") from exc


def empreinte(valeur: object) -> str:
    return hashlib.sha256(canonique(valeur).encode()).hexdigest()


def instant(valeur: object) -> datetime | None:
    """Instant ISO 8601 à fuseau explicite, en UTC ; ``None`` sinon (un instant sans fuseau n'est jamais deviné)."""
    if type(valeur) is not str or not valeur or valeur.strip() != valeur or len(valeur) > 64:
        return None
    try:
        analyse = datetime.fromisoformat(valeur[:-1] + "+00:00" if valeur.endswith("Z") else valeur)
    except ValueError:
        return None
    if analyse.utcoffset() is None:
        return None
    return analyse.astimezone(UTC)


def _iso(valeur: datetime) -> str:
    return valeur.isoformat().replace("+00:00", "Z")


def extraire(document: object, chemin: str) -> list:
    """Valeurs trouvées à ``a.b[*].c`` ; une clé ou un niveau absent n'ajoute rien (jamais une valeur par défaut)."""
    courants = [document]
    for morceau in chemin.split("."):
        parcourir = morceau.endswith("[*]")
        cle = morceau[:-3] if parcourir else morceau
        suivants = []
        for courant in courants:
            if not isinstance(courant, Mapping) or cle not in courant:
                continue
            valeur = courant[cle]
            if parcourir:
                if isinstance(valeur, list):
                    suivants.extend(valeur)
            else:
                suivants.append(valeur)
        courants = suivants
    return courants


def verdict_reponse(reponse: object) -> tuple[str, str | None]:
    """(verdict, code) d'une réponse du dispatcher : ``ok`` faux = ERREUR, ``accepte`` faux = REFUSEE, sinon OK."""
    if not isinstance(reponse, Mapping) or reponse.get("ok") is not True:
        code = reponse.get("erreur") if isinstance(reponse, Mapping) else None
        return "ERREUR", code if type(code) is str else "reponse_illisible"
    interne = reponse.get("resultat")
    if isinstance(interne, Mapping) and interne.get("accepte") is False:
        verdict = interne.get("verdict")
        code = verdict.get("code") if isinstance(verdict, Mapping) else None
        return "REFUSEE", code if type(code) is str else "refus_sans_code"
    return "ACCEPTEE", None


def _hash_maillon(capture: Mapping) -> str:
    return empreinte({cle: valeur for cle, valeur in capture.items() if cle != "hash_maillon"})


def construire(
    lecture: catalogue_producteurs.Lecture,
    arguments: Mapping,
    pages: Sequence[Mapping],
    *,
    recu_a: str,
    reference: str | None,
    index: int,
    hash_precedent: str,
    dernier_recu_a: str | None = None,
    max_octets: int = MAX_OCTETS_DEFAUT,
) -> dict:
    """Une capture à ajouter à la chaîne. Refus avant toute écriture : instant de réception invalide ou antérieur à la
    dernière réception, réponse non JSON, trop volumineuse (aucune troncature : lire par fenêtres plus étroites)."""
    recu = instant(recu_a)
    if recu is None:
        raise _refus("REJ-CAPTURE-TEMPS", "instant de réception avec fuseau explicite requis")
    if dernier_recu_a is not None and recu < instant(dernier_recu_a):  # type: ignore[operator]
        raise _refus("REJ-CAPTURE-TEMPS", "l'instant de réception ne peut pas précéder la dernière capture connue")
    reference_jour = None
    if lecture.reference_genre == "date" and reference is not None:
        # Le producteur lit un JOUR civil (AAAA-MM-JJ) : aucun fuseau n'est deviné, la référence reste un jour.
        try:
            date.fromisoformat(reference)
            valide = bool(_JOUR.fullmatch(reference))
        except (TypeError, ValueError):
            valide = False
        if not valide:
            raise _refus("REJ-CAPTURE-TEMPS", "référence de lecture : jour AAAA-MM-JJ valide requis")
        reference_jour, reference = reference, None
    elif reference is not None and instant(reference) is None:
        raise _refus("REJ-CAPTURE-TEMPS", "référence de lecture avec fuseau explicite requise")
    if type(index) is not int or index < 0 or (index == 0) != (hash_precedent == HASH_INITIAL):
        raise _refus("REJ-CAPTURE-CHAINE", "rang et prédécesseur incohérents")
    if not 1 <= len(pages) <= MAX_PAGES:
        raise _refus("REJ-CAPTURE-PAGES", f"1 à {MAX_PAGES} pages requises")
    pages_json = [json.loads(canonique(normaliser(page))) for page in pages]
    if len(canonique(pages_json)) > max_octets:
        raise _refus(
            "REJ-CAPTURE-BORNE", "réponse au-delà du budget : lire par fenêtres plus étroites, sans troncature"
        )

    verdict, code = "ACCEPTEE", None
    for page in pages_json:
        v, c = verdict_reponse(page)
        if v != "ACCEPTEE":
            verdict, code = v, c
            break
    detail_refus = None
    if verdict == "ACCEPTEE":
        # Producteur à CONTRAT : une charge qui viole son contrat est un refus conservé (aucun fait citable), jamais
        # une donnée « acceptée sous réserve ». Les messages nomment le champ, jamais la valeur reçue.
        for page in pages_json:
            erreurs = charges_producteurs.valider(lecture.id, page, arguments)
            if erreurs:
                verdict, code = "REFUSEE", "charge_invalide"
                detail_refus = "; ".join(erreurs[:3])[:300]
                break
    complete, raison = True, None
    if detail_refus is not None:
        complete, raison = False, f"charge non conforme au contrat du producteur : {detail_refus}"
    elif verdict != "ACCEPTEE":
        complete, raison = False, "réponse refusée ou en erreur : aucun fait reçu"
    elif lecture.pagination is not None:
        suite = extraire(pages_json[-1], lecture.pagination.chemin_suivant)
        if any(valeur is not None for valeur in suite):
            complete, raison = False, "page suivante non lue"
    if complete and lecture.incomplets:
        # Une lecture paginée dit « reste » à chaque page intermédiaire : seule la dernière page est jugée.
        a_juger = pages_json[-1:] if lecture.pagination is not None else pages_json
        for page in a_juger:
            for marqueur in lecture.incomplets:
                for valeur in extraire(page, marqueur.chemin):
                    if marqueur.genre == "vrai":
                        declare = valeur is True
                    elif marqueur.genre == "faux":
                        declare = valeur is False
                    elif marqueur.genre == "egal":
                        declare = type(valeur) is str and valeur == marqueur.valeur
                    elif marqueur.genre == "autre_que":
                        declare = type(valeur) is str and valeur != marqueur.valeur
                    else:
                        declare = type(valeur) is int and valeur > 0
                    if declare and complete:
                        complete, raison = (
                            False,
                            f"réponse tronquée ou vide déclarée par le producteur ({marqueur.chemin})",
                        )
    instants, invalides = [], 0
    revisions: set[str] = set()
    if verdict == "ACCEPTEE":
        for page in pages_json:
            for chemin in lecture.instants_metier:
                for valeur in extraire(page, chemin):
                    analyse = instant(valeur)
                    if analyse is None:
                        invalides += 1
                    else:
                        instants.append(analyse)
            for chemin in lecture.revisions:
                revisions.update(
                    str(valeur) for valeur in extraire(page, chemin) if type(valeur) in (str, int) and valeur != ""
                )
    if len(revisions) > MAX_REVISIONS:
        raise _refus("REJ-CAPTURE-BORNE", "trop de révisions déclarées pour une capture : fenêtre plus étroite requise")
    capture = {
        "schema": SCHEMA,
        "index": index,
        "hash_precedent": hash_precedent,
        "hash_maillon": "",
        "catalogue_version": catalogue_producteurs.CATALOGUE_VERSION,
        "lecture_id": lecture.id,
        "departement": lecture.departement,
        "outil": lecture.outil,
        "arguments": json.loads(canonique(normaliser(dict(arguments)))),
        "arguments_sha256": empreinte(normaliser(dict(arguments))),
        "pages": pages_json,
        "reponse_sha256": empreinte(pages_json),
        "verdict": verdict,
        "code": code,
        "complete": complete,
        "raison_incomplete": raison,
        "recu_a": _iso(recu),
        "reference": _iso(instant(reference)) if reference is not None else None,  # type: ignore[arg-type]
        "reference_jour": reference_jour,
        "instants_metier": {
            "declares": bool(lecture.instants_metier),
            "nombre": len(instants),
            "invalides": invalides,
            "min": _iso(min(instants)) if instants else None,
            "max": _iso(max(instants)) if instants else None,
        },
        "revisions": sorted(revisions),
        "limites": list(_LIMITES),
    }
    capture["hash_maillon"] = _hash_maillon(capture)
    return capture


def valider_capture(capture: object) -> None:
    """Structure, empreintes internes et cohérence des temps d'UNE capture ; lève ValueError sinon."""
    if not isinstance(capture, dict) or set(capture) != _CHAMPS or capture["schema"] != SCHEMA:
        raise _refus(
            "REJ-CAPTURE-STRUCTURE", "capture {schema, rang, empreintes, lecture, pages, temps…} exacte requise"
        )
    if capture["verdict"] not in VERDICTS or type(capture["complete"]) is not bool:
        raise _refus("REJ-CAPTURE-STRUCTURE", "verdict ou complétude invalides")
    if not _HEX.fullmatch(str(capture["hash_maillon"])) or capture["hash_maillon"] != _hash_maillon(capture):
        raise _refus("REJ-CAPTURE-EMPREINTE", "empreinte de maillon incohérente")
    if capture["arguments_sha256"] != empreinte(capture["arguments"]) or capture["reponse_sha256"] != empreinte(
        capture["pages"]
    ):
        raise _refus("REJ-CAPTURE-EMPREINTE", "empreinte d'arguments ou de réponse incohérente")
    jour = capture["reference_jour"]
    if jour is not None and (type(jour) is not str or not _JOUR.fullmatch(jour) or capture["reference"] is not None):
        raise _refus("REJ-CAPTURE-TEMPS", "référence en jour incohérente")
    if instant(capture["recu_a"]) is None or (
        capture["reference"] is not None and instant(capture["reference"]) is None
    ):
        raise _refus("REJ-CAPTURE-TEMPS", "instants de réception/référence invalides")
    lecture = catalogue_producteurs.PAR_ID.get(capture["lecture_id"])
    if lecture is None or (lecture.departement, lecture.outil) != (capture["departement"], capture["outil"]):
        raise _refus("REJ-CAPTURE-LECTURE", "lecture inconnue du catalogue ou incohérente")
    temps = capture["instants_metier"]
    if not isinstance(temps, dict) or set(temps) != {"declares", "nombre", "invalides", "min", "max"}:
        raise _refus("REJ-CAPTURE-STRUCTURE", "instants métier mal formés")
    if (temps["min"] is None) != (temps["max"] is None) or (temps["nombre"] == 0) != (temps["min"] is None):
        raise _refus("REJ-CAPTURE-TEMPS", "instants métier incohérents")
    if capture["complete"] and capture["verdict"] != "ACCEPTEE":
        raise _refus("REJ-CAPTURE-STRUCTURE", "une capture refusée n'est jamais complète")


def valider_chaine(captures: Sequence[Mapping]) -> tuple[bool, str]:
    """Rangs contigus, chaînage, empreintes, instants de réception monotones. ``(ok, raison)`` ; ne lève jamais."""
    precedent, dernier = HASH_INITIAL, None
    try:
        for rang, capture in enumerate(captures):
            valider_capture(capture)
            if capture["index"] != rang or capture["hash_precedent"] != precedent:
                return False, f"maillon invalide à l'index {rang}"
            recu = instant(capture["recu_a"])
            if dernier is not None and recu < dernier:
                return False, f"instant de réception régressif à l'index {rang}"
            precedent, dernier = capture["hash_maillon"], recu
    except (ValueError, KeyError, TypeError, RecursionError) as exc:
        return False, str(exc)[:200]
    return True, ""


def connues_a(captures: Sequence[Mapping], connaissance: str) -> list[Mapping]:
    """Captures que M9 connaissait à l'instant ``connaissance`` (réception ≤) : une arrivée tardive n'y figure pas."""
    limite = instant(connaissance)
    if limite is None:
        raise _refus("REJ-CAPTURE-TEMPS", "instant de connaissance avec fuseau explicite requis")
    return [capture for capture in captures if instant(capture["recu_a"]) <= limite]  # type: ignore[operator]


def _cle_lecture(capture: Mapping) -> tuple[str, str]:
    return capture["lecture_id"], capture["arguments_sha256"]


def _sans_chemin(document: object, morceaux: list[str]) -> object:
    """Copie du document sans la clé désignée par ``morceaux`` (chemin sans ``[*]``) ; le reste est inchangé."""
    if not morceaux or not isinstance(document, Mapping):
        return document
    tete, reste = morceaux[0], morceaux[1:]
    if tete not in document:
        return document
    if not reste:
        return {cle: valeur for cle, valeur in document.items() if cle != tete}
    return {**document, tete: _sans_chemin(document[tete], reste)}


def empreinte_comparable(capture: Mapping) -> str:
    """Empreinte de la réponse à comparer pour une contradiction : celle de la capture, ou, quand le catalogue déclare
    des métadonnées de lecture volatiles (horloge du producteur), celle des pages privées de ces métadonnées. Deux
    lectures du même contenu faites à deux moments ne se contredisent pas."""
    lecture = catalogue_producteurs.PAR_ID.get(capture["lecture_id"])
    if lecture is None or not lecture.volatils:
        return capture["reponse_sha256"]
    pages = capture["pages"]
    for chemin in lecture.volatils:
        pages = [_sans_chemin(page, chemin.split(".")) for page in pages]
    return empreinte(pages)


def contradictions(captures: Sequence[Mapping]) -> list[dict]:
    """Paires de captures ACCEPTÉES, même lecture et mêmes arguments, même révision déclarée et même instant métier max,
    dont les réponses diffèrent. Les deux preuves sont citées ; aucune n'est choisie. Sans révision ni instant déclarés,
    la
    comparaison est impossible (``COMPARABLE: false`` n'est pas émis : rien n'est affirmé)."""
    groupes: dict[tuple, list[Mapping]] = {}
    for capture in captures:
        if capture["verdict"] != "ACCEPTEE":
            continue
        marque = (capture["revisions"] and tuple(capture["revisions"])) or None
        horodatage = capture["instants_metier"]["max"]
        if marque is None and horodatage is None:
            continue
        groupes.setdefault((*_cle_lecture(capture), marque, horodatage), []).append(capture)
    resultat = []
    for (lecture_id, arguments_sha, _marque, _horodatage), membres in groupes.items():
        for position, a in enumerate(membres):
            for b in membres[position + 1 :]:
                if empreinte_comparable(a) != empreinte_comparable(b):
                    resultat.append(
                        {
                            "lecture_id": lecture_id,
                            "arguments_sha256": arguments_sha,
                            "index_a": a["index"],
                            "index_b": b["index"],
                            "hash_a": a["hash_maillon"],
                            "hash_b": b["hash_maillon"],
                            "regle": REGLE_CONTRADICTION,
                        }
                    )
    return sorted(resultat, key=lambda c: (c["index_a"], c["index_b"]))


def fraicheur_declaree(capture: Mapping) -> tuple[int | None, bool]:
    """``(fenêtre en secondes, déclaration ignorée)`` que le PROPRIÉTAIRE a écrite dans la réponse conservée.

    Seule une déclaration entièrement valide est retenue : valeur ``type(x) is int`` de 1 à ``FRAICHEUR_MAX_S`` (ni
    booléen, ni décimal, ni texte), lue une seule fois, ET version qui se recalcule à l'identique de l'outil et de la
    fenêtre (``encodage.empreinte``). Toute autre déclaration (absente de ce côté, invalide, incohérente, refusée par le
    propriétaire) est IGNORÉE : la fraîcheur reste NON_EVALUEE, jamais HORS_FENETRE. Le second terme dit qu'une
    déclaration était présente mais n'a pas été retenue. Sans déclaration, ``(None, False)``."""
    lecture = catalogue_producteurs.PAR_ID.get(capture["lecture_id"])
    if lecture is None or lecture.fraicheur_attendue is None or capture["verdict"] != "ACCEPTEE":
        return None, False
    refusee = lecture.fraicheur_attendue.rsplit(".", 1)[0] + ".fraicheur_attendue_refusee"
    fenetres, versions, refus = [], [], []
    for page in capture["pages"]:
        fenetres += extraire(page, lecture.fraicheur_attendue)
        versions += extraire(page, lecture.fraicheur_version)
        refus += extraire(page, refusee)
    if not fenetres and not versions and not refus:
        return None, False
    if len(fenetres) != 1 or len(versions) != 1 or refus:
        return None, True
    secondes, version = fenetres[0], versions[0]
    if type(secondes) is not int or not 1 <= secondes <= FRAICHEUR_MAX_S or type(version) is not str:
        return None, True
    attendue = encodage.empreinte({"lecture": lecture.outil, "fraicheur_attendue_s": secondes})
    return (secondes, False) if version == attendue else (None, True)


def evaluer_couverture(
    captures: Sequence[Mapping],
    *,
    reference: str,
    connaissance: str,
    attendues: Sequence[str],
    fraicheur_attendue_s: Mapping[str, int] | None = None,
) -> dict:
    """État de couverture des lectures ``attendues`` à la référence, avec ce que M9 connaissait à ``connaissance``.

    Une lecture attendue est : ABSENTE (aucune capture connue), REFUSEE (la dernière est un refus/erreur), PARTIELLE
    (page non lue), CONTRADICTOIRE, TEMPS_METIER_NON_DECLARE, FUTURE (tous ses faits postérieurs à la référence) ou
    PRESENTE. ``age_s`` = référence − dernier instant métier (signé, informatif) ; ``fraicheur`` n'est ÉVALUÉE que si
    une attente de fraîcheur existe pour cette lecture : celle de l'appelant (``fraicheur_attendue_s``), à défaut
    la fenêtre que le PROPRIÉTAIRE a déclarée dans sa réponse (M8, ``fraicheur_declaree``) ; sinon ``NON_EVALUEE``."""
    ref = instant(reference)
    if ref is None:
        raise _refus("REJ-CAPTURE-TEMPS", "référence avec fuseau explicite requise")
    connues = connues_a(captures, connaissance)
    conflits = contradictions(connues)
    en_conflit = {c["lecture_id"] for c in conflits}
    fraicheurs = dict(fraicheur_attendue_s or {})
    lectures = []
    for lecture_id in attendues:
        catalogue_producteurs.obtenir(lecture_id)
        siennes = [capture for capture in connues if capture["lecture_id"] == lecture_id]
        entree: dict = {"lecture_id": lecture_id, "captures_connues": len(siennes)}
        if not siennes:
            entree |= {"statut": "ABSENTE", "manque": "aucune capture connue à l'instant de connaissance"}
            lectures.append(entree)
            continue
        derniere = siennes[-1]
        entree |= {
            "dernier_index": derniere["index"],
            "hash_maillon": derniere["hash_maillon"],
            "recu_a": derniere["recu_a"],
        }
        temps = derniere["instants_metier"]
        if derniere["verdict"] != "ACCEPTEE":
            entree |= {"statut": "REFUSEE", "code": derniere["code"], "manque": "dernière lecture refusée ou en erreur"}
        elif not derniere["complete"]:
            entree |= {"statut": "PARTIELLE", "manque": derniere["raison_incomplete"]}
        elif lecture_id in en_conflit:
            entree |= {
                "statut": "CONTRADICTOIRE",
                "manque": "deux réponses différentes pour la même révision et le même instant",
            }
        elif not temps["declares"] or temps["nombre"] == 0:
            entree |= {"statut": "TEMPS_METIER_NON_DECLARE", "manque": "le producteur ne déclare aucun instant métier"}
        else:
            dernier_metier = instant(temps["max"])
            premier_metier = instant(temps["min"])
            age = int((ref - dernier_metier).total_seconds())  # type: ignore[operator]
            entree["age_s"] = age
            entree["instants_metier"] = {"min": temps["min"], "max": temps["max"], "invalides": temps["invalides"]}
            if premier_metier > ref:  # type: ignore[operator]
                entree |= {"statut": "FUTURE", "manque": "tous les faits déclarés sont postérieurs à la référence"}
            else:
                entree["statut"] = "PRESENTE"
        attente = fraicheurs.get(lecture_id)
        declaree, ignoree = fraicheur_declaree(derniere)
        if "age_s" in entree:
            if attente is not None:
                entree |= {"fraicheur_attendue_s": attente, "fraicheur_source": "APPELANT"}
            elif declaree is not None:
                attente = declaree
                entree |= {"fraicheur_attendue_s": declaree, "fraicheur_source": "PRODUCTEUR"}
            if ignoree and declaree is None:
                entree["fraicheur_declaration_ignoree"] = True
            if attente is None:
                entree["fraicheur"] = "NON_EVALUEE"
            else:
                entree["fraicheur"] = "DANS_LA_FENETRE" if 0 <= entree["age_s"] <= attente else "HORS_FENETRE"
        lectures.append(entree)
    manquantes = [e["lecture_id"] for e in lectures if e["statut"] != "PRESENTE"]
    return {
        "type": "COUVERTURE_STRATEGIQUE",
        "reference": _iso(ref),
        "connaissance": _iso(instant(connaissance)),  # type: ignore[arg-type]
        "lectures": lectures,
        "contradictions": conflits,
        "lectures_non_presentes": manquantes,
        "complete": not manquantes and not conflits,
        "limites": [
            "PRESENTE signifie : capture complète, acceptée, à instants métier déclarés non futurs — jamais « vrai » "
            "ni « frais ».",
            "Une lecture absente de la liste attendue n'est pas évaluée : la couverture ne dépasse pas ce qui est "
            "attendu.",
        ],
    }
