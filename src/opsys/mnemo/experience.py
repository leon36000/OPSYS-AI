"""Mémoire d'EXPÉRIENCE des agents, jalon J1 : le schéma fermé d'un élément et sa GARDE D'ADMISSION.

Contexte (proposition sur la branche claude/veille-memoire-agents, § 3, 5, 7 ;
docs/architecture/MEMOIRE-EXPERIENCE-AGENTS-J1-J2.md) : un agent de département, même petit,
ferait moins d'erreurs d'appel d'outil s'il lisait de courts éléments d'expérience (une stratégie, un exemple
d'appel, un
piège d'outil). Ces éléments sont une SURFACE D'ATTAQUE persistante (empoisonnement, fuite de renseignements personnels,
copie de valeurs, contournement d'approbation). Ce module est la porte : rien n'est rangé sans l'avoir passée.

Ce que ce jalon livre, et rien de plus :
- trois genres, un SCHÉMA FERMÉ (aucun champ libre non filtré) : `strategie_flux`, `exemple_sous_tache`,
  `convention_outil` ;
- la GARDE D'ADMISSION, refus typés `REJ-EXPERIENCE-…` : origine fiable, noms d'outils et d'arguments vérifiés contre le
  registre MCP scellé (jamais le texte de l'élément), exemple validé contre le `schema_entree` de l'outil avec des
  marques
  de substitution typées (`<MONTANT>`…), aucune VALEUR (aucun chiffre hors identifiant du registre), aucun renseignement
  personnel ni secret ni consigne glissée (garde-fou de texte et filtre de provenance existants), aucun contournement
  d'approbation, un outil N3 ou plus seulement par une convention d'arguments ;
- un registre append-only chaîné (celui de M10, `experiences`) : `experience_proposee` (état `candidat`) et
  `experience_refusee` (le code et l'empreinte du refus, JAMAIS le contenu refusé) ; l'état se rejoue, un élément dont
  l'empreinte d'un outil a changé est `perime` (lié à la version de l'outil).

Ce que ce jalon NE fait PAS : évaluer (J2 : le banc `opsys.evaluation.memoire_experience`), promouvoir, injecter dans un
paquet, ni entraîner quoi que ce soit. Un élément reste `candidat` : aucun département ne le lit, rien n'est
appliqué sans
promotion humaine N3 (J6, non construit). Aucun modèle réel n'est appelé.

Module pur : la lecture du registre MCP est injectée (`VueRegistre`).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Protocol

from . import vie_privee
from .codes import ErreurMnemo

GENRES = ("strategie_flux", "exemple_sous_tache", "convention_outil")
DOMAINES = ("affaires", "developpement")
# Origines que le code ou une personne peut déclarer. `fiche_deterministe` (J3) et `signal_sans_contenu` (J7) sont
# RÉSERVÉES au code : un appelant ne les déclare pas.
ORIGINES_ADMISES = ("reference_ecrite_main", "enseignant_fictif", "fiche_deterministe", "signal_sans_contenu")
ORIGINES_DECLARABLES = ("reference_ecrite_main", "enseignant_fictif")
# Surfaces non fiables : jamais une source d'induction (proposition § 4, règle de deux).
ORIGINES_NON_FIABLES = (
    "courriel",
    "piece_jointe",
    "document_ingere",
    "web",
    "conversation_client",
    "memoire_client",
    "page_web",
    "sms",
)
MARQUES = ("<MONTANT>", "<ID_AFFAIRE>", "<DATE>", "<IDENTIFIANT>", "<TEXTE>", "<DUREE>", "<QUANTITE>")
STATUT_CANDIDAT, STATUT_PERIME = "candidat", "perime"
NIVEAUX_ELEVES = ("N3", "N4", "N5")
TEXTE_MAX = 400
ETAPES_MIN, ETAPES_MAX, APPELS_MAX = 2, 8, 6
PLAFOND_CANDIDATS = 50  # par (département, domaine, genre) : une source qui déborde ne noie pas la revue

TYPE_PROPOSEE, TYPE_REFUSEE = "experience_proposee", "experience_refusee"

F = "REJ-EXPERIENCE-FORME"
GENRE_INCONNU = "REJ-EXPERIENCE-GENRE-INCONNU"
DOMAINE_INCONNU = "REJ-EXPERIENCE-DOMAINE-INCONNU"
DOMAINE_GENRE = "REJ-EXPERIENCE-DOMAINE-GENRE"
ORIGINE_INCONNUE = "REJ-EXPERIENCE-ORIGINE-INCONNUE"
ORIGINE_NON_FIABLE = "REJ-EXPERIENCE-ORIGINE-NON-FIABLE"
ORIGINE_RESERVEE = "REJ-EXPERIENCE-ORIGINE-RESERVEE"
OUTIL_INCONNU = "REJ-EXPERIENCE-OUTIL-INCONNU"
OUTIL_HORS_PORTEE = "REJ-EXPERIENCE-OUTIL-HORS-PORTEE"
ARGUMENT_INCONNU = "REJ-EXPERIENCE-ARGUMENT-INCONNU"
ARGUMENT_MANQUANT = "REJ-EXPERIENCE-ARGUMENT-MANQUANT"
VALEUR = "REJ-EXPERIENCE-VALEUR"
CHIFFRE = "REJ-EXPERIENCE-CHIFFRE"
CONTOURNEMENT = "REJ-EXPERIENCE-CONTOURNEMENT"
NIVEAU_ELEVE = "REJ-EXPERIENCE-NIVEAU-ELEVE"
TEXTE = "REJ-EXPERIENCE-TEXTE"
DONNEE_PERSONNELLE = "REJ-EXPERIENCE-DONNEE-PERSONNELLE"
SECRET = "REJ-EXPERIENCE-SECRET"
CONSIGNE = "REJ-EXPERIENCE-CONSIGNE"
PLAFOND = "REJ-EXPERIENCE-PLAFOND"
HORODATAGE = "REJ-EXPERIENCE-HORODATAGE"

_DEPARTEMENT = re.compile(r"^m(0[1-9]|10)-[a-z][a-z0-9-]*$")
_PACK = re.compile(r"^[a-z][a-z0-9-]{1,40}$")
_NOM_OUTIL = re.compile(r"^(?:m(?:10|[1-9])|opsys)_[a-z][a-z0-9_]{1,60}$")
_NOM_ARGUMENT = re.compile(r"^[a-z][a-z0-9_]{0,60}$")
_INTENTION = re.compile(r"^[a-z][a-z0-9_]{2,40}$")
_CODE_REFUS = re.compile(r"^REJ-[A-Z0-9]+(?:-[A-Z0-9]+)+$")
_CODE_REFUS_DANS_PROSE = re.compile(r"\bREJ-[A-Z0-9]+(?:-[A-Z0-9]+)+\b")
_MARQUE = re.compile(r"^<[A-Z][A-Z_]{1,24}>$")
_CHIFFRE_PROSE = re.compile(r"[0-9]")
_JETON_IDENTIFIANT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# Un conseil de contourner l'approbation, d'agir sans personne ou de passer outre une garde : refusé, jamais corrigé.
_CONTOURNEMENT = re.compile(
    r"(?i)sans\s+(?:l['’]\s*)?(?:approbation|validation|accord|confirmation|autorisation|demander|personne|humain)"
    r"|contourn|court-?circuit|passer\s+outre|outrepass|en\s+passant\s+par|bypass|skip|saute[rz]?\s+(?:l['’]|la\s|le\s|les\s)"
    r"|d[ée]sactiv|ignore[rz]?\s+(?:la|le|les|l['’])\s*(?:garde|r[èe]gle|refus|approbation|limite|sas|file)"
    r"|m[êe]me\s+si\s+(?:l['’]\s*)?(?:outil\s+)?(?:refus|bloqu|interdit)|forc(?:e[rz]?|ant)\s+(?:l['’]|la\s|le\s)"
    r"|r[ée]essay(?:e[rz]?)\s+(?:jusqu|sans)|abaiss\w+\s+(?:le\s+)?niveau|sans\s+attendre"
)


class VueRegistre(Protocol):
    """Ce que la garde lit du registre MCP scellé (`opsys.registre_mcp.registre.Registre` y satisfait)."""

    revision: int
    entrees: Mapping[str, Any]  # nom -> {departement, niveau, schema_entree, empreinte}


class ErreurExperience(ErreurMnemo):
    """Refus typé d'admission (`REJ-EXPERIENCE-…`), sans jamais citer le contenu refusé."""


def _refus(code: str, detail: str) -> ErreurExperience:
    return ErreurExperience(code, detail)


def empreinte(donnees: Any) -> str:
    return hashlib.sha256(
        json.dumps(donnees, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


# ---------------------------------------------------------------------------------------------------------------
# La garde
# ---------------------------------------------------------------------------------------------------------------
def _objet(valeur: Any, chemin: str, champs: set[str], requis: set[str] | None = None) -> Mapping[str, Any]:
    if not isinstance(valeur, Mapping):
        raise _refus(F, f"{chemin} : objet attendu")
    inconnus = set(valeur) - champs
    if inconnus:
        raise _refus(F, f"{chemin} : champ(s) hors schéma {sorted(map(str, inconnus))}")
    manquants = (champs if requis is None else requis) - set(valeur)
    if manquants:
        raise _refus(F, f"{chemin} : champ(s) manquant(s) {sorted(manquants)}")
    return valeur


def _entree(vue: VueRegistre, nom: Any, departement: str, chemin: str) -> Any:
    if not isinstance(nom, str) or not _NOM_OUTIL.fullmatch(nom):
        raise _refus(OUTIL_INCONNU, f"{chemin} : nom d'outil mal formé")
    entree = vue.entrees.get(nom)
    if entree is None:
        raise _refus(OUTIL_INCONNU, f"{chemin} : l'outil {nom!r} n'est pas au registre MCP scellé")
    if entree.departement not in (departement, "opsys"):
        raise _refus(
            OUTIL_HORS_PORTEE, f"{chemin} : l'outil {nom!r} n'est pas dans la portée du département de l'élément"
        )
    return entree


def _proprietes(entree: Any) -> Mapping[str, Any]:
    schema = entree.schema_entree if isinstance(entree.schema_entree, Mapping) else {}
    proprietes = schema.get("properties", {})
    return proprietes if isinstance(proprietes, Mapping) else {}


def _identifiants(vue: VueRegistre) -> set[str]:
    """Tout ce qu'une prose peut citer sans que ce soit une valeur : noms d'outils et d'arguments du registre."""
    noms = set(vue.entrees)
    for entree in vue.entrees.values():
        noms.update(map(str, _proprietes(entree)))
    return noms


def _texte(valeur: Any, chemin: str, vue: VueRegistre, *, maximum: int = TEXTE_MAX) -> str:
    """Un texte d'élément : borné, sans secret, sans renseignement personnel, sans consigne, sans contournement, sans
    chiffre (hors identifiant du registre ou code de refus)."""
    if not isinstance(valeur, str):
        raise _refus(TEXTE, f"{chemin} : texte attendu")
    if _CONTOURNEMENT.search(valeur):
        raise _refus(
            CONTOURNEMENT, f"{chemin} : un élément ne conseille jamais de contourner une approbation ou une garde"
        )
    try:
        propre = vie_privee.texte_propre(valeur, chemin, maximum=maximum)
    except ErreurMnemo as exc:
        correspondance = {
            "REJ-MNEMO-SECRET": SECRET,
            "REJ-MNEMO-DONNEE-PERSONNELLE": DONNEE_PERSONNELLE,
            "REJ-MNEMO-TEXTE-SUSPECT": CONSIGNE,
        }
        raise _refus(correspondance.get(exc.code, TEXTE), exc.detail) from None
    identifiants = _identifiants(vue)
    nu = _CODE_REFUS_DANS_PROSE.sub(" ", " ".join(propre.split()))
    nu = _JETON_IDENTIFIANT.sub(lambda m: " " if m.group(0) in identifiants else m.group(0), nu)
    if _CHIFFRE_PROSE.search(nu):
        raise _refus(
            CHIFFRE,
            f"{chemin} : aucun chiffre dans un élément (une valeur ne s'apprend pas), sauf un identifiant du registre",
        )
    return propre


def _argument(nom: Any, valeur: Any, proprietes: Mapping[str, Any], chemin: str) -> Any:
    if not isinstance(nom, str) or nom not in proprietes:
        raise _refus(ARGUMENT_INCONNU, f"{chemin} : argument absent du schéma de l'outil")
    declaration = proprietes[nom] if isinstance(proprietes[nom], Mapping) else {}
    if isinstance(valeur, str) and _MARQUE.fullmatch(valeur):
        if valeur not in MARQUES:
            raise _refus(VALEUR, f"{chemin}.{nom} : marque de substitution hors de {list(MARQUES)}")
        return valeur
    enumere = declaration.get("enum")
    if isinstance(enumere, list) and valeur in enumere and isinstance(valeur, str):
        return valeur
    if isinstance(valeur, bool) and declaration.get("type") == "boolean":
        return valeur
    raise _refus(
        VALEUR, f"{chemin}.{nom} : une marque de substitution typée ou un énuméré du schéma, jamais une valeur"
    )


def _appel(appel: Any, departement: str, vue: VueRegistre, chemin: str) -> dict[str, Any]:
    appel = _objet(appel, chemin, {"outil", "arguments"})
    entree = _entree(vue, appel["outil"], departement, f"{chemin}.outil")
    if entree.niveau in NIVEAUX_ELEVES:
        raise _refus(NIVEAU_ELEVE, f"{chemin} : un outil {entree.niveau} ne figure que dans une convention d'arguments")
    arguments = appel["arguments"]
    if not isinstance(arguments, Mapping):
        raise _refus(F, f"{chemin}.arguments : objet attendu")
    proprietes = _proprietes(entree)
    propres = {cle: _argument(cle, valeur, proprietes, f"{chemin}.arguments") for cle, valeur in arguments.items()}
    schema = entree.schema_entree if isinstance(entree.schema_entree, Mapping) else {}
    manquants = sorted(set(schema.get("required", [])) - set(propres))
    if manquants:
        raise _refus(ARGUMENT_MANQUANT, f"{chemin} : argument(s) obligatoire(s) manquant(s) du schéma : {manquants}")
    return {"outil": appel["outil"], "arguments": dict(sorted(propres.items()))}


def _contenu_convention(
    contenu: Any, departement: str, declencheur: Mapping[str, Any], vue: VueRegistre
) -> tuple[dict[str, Any], list[str]]:
    contenu = _objet(contenu, "contenu", {"outil", "cle_argument", "regle", "correction"})
    entree = _entree(vue, contenu["outil"], departement, "contenu.outil")
    if declencheur.get("outil") != contenu["outil"]:
        raise _refus(F, "declencheur.outil doit être l'outil de la convention")
    cle = contenu["cle_argument"]
    if not isinstance(cle, str) or cle not in _proprietes(entree):
        raise _refus(ARGUMENT_INCONNU, "contenu.cle_argument : argument absent du schéma de l'outil")
    return (
        {
            "outil": contenu["outil"],
            "cle_argument": cle,
            "regle": _texte(contenu["regle"], "contenu.regle", vue),
            "correction": _texte(contenu["correction"], "contenu.correction", vue),
        },
        [contenu["outil"]],
    )


def _contenu_exemple(contenu: Any, departement: str, vue: VueRegistre) -> tuple[dict[str, Any], list[str]]:
    contenu = _objet(contenu, "contenu", {"intention", "appels", "reponse_cles"})
    if not isinstance(contenu["intention"], str) or not _INTENTION.fullmatch(contenu["intention"]):
        raise _refus(F, "contenu.intention : un jeton en minuscules (vocabulaire fermé de l'intention)")
    appels = contenu["appels"]
    if not isinstance(appels, list) or not 1 <= len(appels) <= APPELS_MAX:
        raise _refus(F, f"contenu.appels : de 1 à {APPELS_MAX} appels")
    cles = contenu["reponse_cles"]
    if (
        not isinstance(cles, list)
        or len(cles) > 12
        or not all(isinstance(c, str) and _NOM_ARGUMENT.fullmatch(c) for c in cles)
    ):
        raise _refus(F, "contenu.reponse_cles : jusqu'à 12 clés de réponse (jetons)")
    propres = [_appel(a, departement, vue, f"contenu.appels[{i}]") for i, a in enumerate(appels)]
    return {"intention": contenu["intention"], "appels": propres, "reponse_cles": list(cles)}, [
        a["outil"] for a in propres
    ]


def _contenu_flux(contenu: Any, departement: str, vue: VueRegistre) -> tuple[dict[str, Any], list[str]]:
    contenu = _objet(contenu, "contenu", {"intention", "etapes"})
    if not isinstance(contenu["intention"], str) or not _INTENTION.fullmatch(contenu["intention"]):
        raise _refus(F, "contenu.intention : un jeton en minuscules (vocabulaire fermé de l'intention)")
    etapes = contenu["etapes"]
    if not isinstance(etapes, list) or not ETAPES_MIN <= len(etapes) <= ETAPES_MAX:
        raise _refus(F, f"contenu.etapes : de {ETAPES_MIN} à {ETAPES_MAX} étapes")
    propres = []
    for i, etape in enumerate(etapes):
        chemin = f"contenu.etapes[{i}]"
        etape = _objet(etape, chemin, {"outil", "condition"})
        entree = _entree(vue, etape["outil"], departement, f"{chemin}.outil")
        if entree.niveau in NIVEAUX_ELEVES:
            raise _refus(
                NIVEAU_ELEVE, f"{chemin} : un outil {entree.niveau} ne figure que dans une convention d'arguments"
            )
        propres.append(
            {"outil": etape["outil"], "condition": _texte(etape["condition"], f"{chemin}.condition", vue, maximum=160)}
        )
    return {"intention": contenu["intention"], "etapes": propres}, [e["outil"] for e in propres]


def admettre(element: Any, vue: VueRegistre, *, declarable_par_appelant: bool = False) -> dict[str, Any]:
    """L'élément NORMALISÉ (candidat) si tout passe, sinon `ErreurExperience` au premier défaut.
    `declarable_par_appelant`
    : un appelant (outil) ne peut déclarer que les origines `ORIGINES_DECLARABLES` ; le code (J3, J7) déclare les
    siennes."""
    element = _objet(
        element, "élément", {"genre", "departement", "domaine", "pack", "declencheur", "contenu", "origine"}
    )
    genre = element["genre"]
    if genre not in GENRES:
        raise _refus(GENRE_INCONNU, f"genre parmi {list(GENRES)}")
    domaine = element["domaine"]
    if domaine not in DOMAINES:
        raise _refus(DOMAINE_INCONNU, f"domaine parmi {list(DOMAINES)} (jamais mêlés)")
    if domaine == "developpement" and genre != "convention_outil":
        raise _refus(
            DOMAINE_GENRE, "le domaine développement ne reçoit que des conventions d'outillage (aucun flux d'affaires)"
        )
    departement = element["departement"]
    if not isinstance(departement, str) or not _DEPARTEMENT.fullmatch(departement):
        raise _refus(F, "departement : identifiant mNN-… attendu")
    pack = element["pack"]
    if pack is not None and (not isinstance(pack, str) or not _PACK.fullmatch(pack)):
        raise _refus(F, "pack : identifiant de pack ou null")
    origine = element["origine"]
    if origine in ORIGINES_NON_FIABLES:
        raise _refus(
            ORIGINE_NON_FIABLE,
            "une surface non fiable (courriel, document ingéré, web…) n'est jamais une source d'expérience",
        )
    if origine not in ORIGINES_ADMISES:
        raise _refus(ORIGINE_INCONNUE, f"origine parmi {list(ORIGINES_ADMISES)}")
    if declarable_par_appelant and origine not in ORIGINES_DECLARABLES:
        raise _refus(
            ORIGINE_RESERVEE, f"cette origine est réservée au code ; un appelant déclare {list(ORIGINES_DECLARABLES)}"
        )
    declencheur = _objet(element["declencheur"], "declencheur", {"outil", "code_refus"}, {"outil"})
    if (
        "code_refus" in declencheur
        and declencheur["code_refus"] is not None
        and (not isinstance(declencheur["code_refus"], str) or not _CODE_REFUS.fullmatch(declencheur["code_refus"]))
    ):
        raise _refus(F, "declencheur.code_refus : un code REJ-… ou null")
    if genre == "convention_outil":
        contenu, outils = _contenu_convention(element["contenu"], departement, declencheur, vue)
    elif genre == "exemple_sous_tache":
        contenu, outils = _contenu_exemple(element["contenu"], departement, vue)
    else:
        contenu, outils = _contenu_flux(element["contenu"], departement, vue)
    if declencheur["outil"] not in outils:
        raise _refus(F, "declencheur.outil doit être un des outils de l'élément")
    portee = [{"outil": nom, "empreinte": vue.entrees[nom].empreinte} for nom in sorted(set(outils))]
    normalise = {
        "genre": genre,
        "departement": departement,
        "domaine": domaine,
        "pack": pack,
        "declencheur": {"outil": declencheur["outil"], "code_refus": declencheur.get("code_refus")},
        "contenu": contenu,
        "origine": origine,
        "portee_outils": portee,
        "registre_mcp_revision": vue.revision,
    }
    normalise["id_element"] = "sha256:" + empreinte(normalise)
    normalise["statut"] = STATUT_CANDIDAT
    return normalise


# ---------------------------------------------------------------------------------------------------------------
# Le registre chaîné (celui de M10, `experiences`) : état rejoué
# ---------------------------------------------------------------------------------------------------------------
def etat(maillons: Iterable[Mapping[str, Any]], vue: VueRegistre | None = None) -> dict[str, Any]:
    """`{"elements": {id: élément + statut}, "refus": n}` rejoué. Avec une vue du registre MCP, un élément dont
    l'empreinte
    d'un outil a CHANGÉ (ou dont l'outil a disparu) est `perime` : il ne dit plus rien de vrai sur l'outil
    d'aujourd'hui."""
    elements: dict[str, dict[str, Any]] = {}
    refus = 0
    for maillon in maillons:
        genre = maillon.get("type_entree")
        if genre == TYPE_PROPOSEE and maillon["element"]["id_element"] not in elements:
            elements[maillon["element"]["id_element"]] = {
                **maillon["element"],
                "propose_par": maillon.get("par"),
                "propose_le": maillon.get("horodatage"),
            }
        elif genre == TYPE_REFUSEE:
            refus += 1
    if vue is not None:
        for element in elements.values():
            for portee in element["portee_outils"]:
                courant = vue.entrees.get(portee["outil"])
                if courant is None or courant.empreinte != portee["empreinte"]:
                    element["statut"] = STATUT_PERIME
                    break
    return {"elements": elements, "refus": refus}


def proposer(
    registre: Any, element: Any, vue: VueRegistre, *, par: str, horodatage: str, declarable_par_appelant: bool = True
) -> dict[str, Any]:
    """Admet puis range un candidat. Rejouer le même élément n'ajoute rien. Un refus lève `ErreurExperience` ;
    l'APPELANT
    le consigne (`consigner_refus`) puis rend le refus, pour que l'audit survive à l'annulation de la transaction."""
    normalise = admettre(element, vue, declarable_par_appelant=declarable_par_appelant)
    try:
        from datetime import datetime

        if datetime.fromisoformat(horodatage).tzinfo is None:
            raise ValueError
    except (TypeError, ValueError):
        raise _refus(HORODATAGE, "horodatage ISO-8601 avec fuseau requis") from None
    courant = etat(registre.lire())["elements"]
    if normalise["id_element"] in courant:
        return {
            "resultat": "deja_present",
            "id_element": normalise["id_element"],
            "statut": courant[normalise["id_element"]]["statut"],
        }
    meme_partition = sum(
        1
        for e in courant.values()
        if (e["departement"], e["domaine"], e["genre"])
        == (normalise["departement"], normalise["domaine"], normalise["genre"])
    )
    if meme_partition >= PLAFOND_CANDIDATS:
        raise _refus(
            PLAFOND,
            f"{PLAFOND_CANDIDATS} éléments par (département, domaine, genre) : retirer ou évaluer avant d'en ajouter",
        )
    ligne_id = registre.ajouter(
        {"type_entree": TYPE_PROPOSEE, "horodatage": horodatage, "par": par, "element": normalise}
    )
    return {
        "resultat": "ajoute",
        "id_element": normalise["id_element"],
        "statut": STATUT_CANDIDAT,
        "ligne_id": ligne_id,
    }


def consigner_refus(registre: Any, element: Any, erreur: ErreurExperience, *, par: str, horodatage: str) -> None:
    """Trace d'un refus d'admission : le code, l'empreinte de ce qui a été soumis et, quand ils sont bien formés, le
    genre
    et le département. JAMAIS le contenu (il pouvait être une donnée personnelle ou une consigne)."""
    genre = element.get("genre") if isinstance(element, Mapping) else None
    departement = element.get("departement") if isinstance(element, Mapping) else None
    registre.ajouter(
        {
            "type_entree": TYPE_REFUSEE,
            "horodatage": horodatage,
            "par": par,
            "code": erreur.code,
            "empreinte_soumis": empreinte(element),
            "genre": genre if genre in GENRES else None,
            "departement": departement
            if isinstance(departement, str) and _DEPARTEMENT.fullmatch(departement)
            else None,
        }
    )


def vue_elements(
    maillons: Sequence[Mapping[str, Any]],
    vue: VueRegistre | None,
    *,
    departement: str | None = None,
    domaine: str | None = None,
    statut: str | None = None,
) -> list[dict[str, Any]]:
    elements = etat(maillons, vue)["elements"].values()
    return [
        dict(e)
        for e in elements
        if (departement is None or e["departement"] == departement)
        and (domaine is None or e["domaine"] == domaine)
        and (statut is None or e["statut"] == statut)
    ]
