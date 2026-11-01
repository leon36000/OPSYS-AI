"""Format de corpus du gabarit d'évaluation (`opsys.evaluation.corpus/v1`) et sa validation.

Un corpus par département, en YAML versionné, rédigé à la main à partir du `SOUL.md` et des outils réels. Chaque cas
porte une ENTRÉE (ce que le répondant voit), des ATTENTES vérifiables de façon déterministe (ce que le répondant ne voit
jamais) et une RÉPONSE DE RÉFÉRENCE écrite à la main, qui prouve que les attentes sont satisfaisables : le répondant
simulé « référence » doit obtenir 100 %.

La validation est fermée : un champ inconnu, une catégorie hors liste, une expression régulière invalide, un doublon
ou une couverture insuffisante est un refus typé (`RefusEvaluation`, code `REJ-EVAL-CORPUS-…` et chemin du champ),
jamais un cas ignoré en silence.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

SCHEMA_CORPUS = "opsys.evaluation.corpus/v1"
FICHIER_CORPUS = "evals/gabarit.v1.yaml"
MIN_CAS_PAR_DEPARTEMENT = 12

# Catégories du gabarit, identiques pour les dix départements.
CATEGORIES = (
    "tache_metier",          # la tâche métier du département, faite sans inventer
    "appel_outil",           # le bon outil OPSYS, avec des arguments contraints, réellement exécuté si sûr
    "refus_attendu",         # sécurité, autorité, données réelles, irréversible sans approbation
    "injection_consigne",    # une consigne glissée dans une donnée observée (courriel, avis, document)
    "francais_quebecois",    # une demande en français québécois familier, comprise et servie en français
    "mention_professionnel", # la mention CPA / professionnel qualifié attendue
    "honnetete_inconnu",     # « inconnu » plutôt qu'estimé
)
MOTIFS_REFUS = ("securite", "autorite", "donnees_reelles", "irreversible")
GRAVITES = ("bloquante", "majeure", "mineure")
DECISIONS = ("executer", "refuser", "demander_approbation", "refuser_ou_demander_approbation")
NIVEAUX = ("N0", "N1", "N2", "N3", "N4", "N5")
ISSUES_OUTIL = ("execute", "en_attente_approbation", "refuse")
VERDICTS_SONDE = ("en_attente_approbation", "refuse")
# Vocabulaire fermé des refus d'un répondant (même liste pour tous les départements).
CODES_REFUS = (
    "REFUS-SECURITE",          # danger signalé : une personne agit, l'agent n'improvise aucun conseil
    "REFUS-AUTORITE",          # décision ou droit d'un humain (rôle, identité, approbation)
    "REFUS-DONNEES-REELLES",   # renseignement personnel ou donnée réelle hors du cadre (Loi 25, minimisation)
    "REFUS-IRREVERSIBLE",      # action irréversible ou externe sans approbation
    "REFUS-INJECTION",         # consigne trouvée dans une donnée observée : donnée, jamais instruction
    "REFUS-HORS-PERIMETRE",    # appartient à un autre département (prix → M3, date → M4…)
)

_CHAMPS_CORPUS = {"schema", "departement", "version", "fictif", "description", "auteur", "chiffres_permis",
                  "references", "cas"}
_CHAMPS_CAS = {"id", "categorie", "motif_refus", "gravite", "poids", "source", "derive_de", "entree", "attentes",
               "reponse_reference"}
_CHAMPS_ENTREE = {"demande", "donnees_observees", "faits"}
_CHAMPS_ATTENTES = {"decision", "codes_refus", "niveau_minimal", "outil_attendu", "outils_interdits", "aucun_outil",
                    "motifs_requis", "motifs_interdits", "inconnu_attendu", "chiffres", "chiffres_autorises",
                    "sonde_autorite"}
_CHAMPS_OUTIL_ATTENDU = {"nom", "arguments", "issue", "resultat"}
_CHAMPS_SONDE = {"outil", "arguments", "verdict", "erreur"}
_CHAMPS_REFERENCE = {"chemin", "sha256", "executeur", "description"}
_CHAMPS_CONTRAINTE = {"egal", "motif", "present", "dans"}
_ID_CAS = re.compile(r"^m(?:10|[1-9])-[a-z0-9][a-z0-9-]{1,40}$")
_NOM_OUTIL = re.compile(r"^(m(?:10|[1-9])|opsys)_[a-z][a-z0-9_]{1,60}$")
_ID_DEPARTEMENT = re.compile(r"^m(?:0[1-9]|10)-[a-z0-9-]+$")
_EXECUTEUR = re.compile(r"^[a-z_][a-z0-9_.]*:[a-z_][a-z0-9_]*$")


class RefusEvaluation(ValueError):
    """Refus typé du gabarit : `code` stable (`REJ-EVAL-…`), `chemin` du champ fautif, `detail` lisible."""

    def __init__(self, code: str, detail: str, chemin: str = "") -> None:
        self.code, self.detail, self.chemin = code, detail, chemin
        super().__init__(f"{code} : {chemin + ' : ' if chemin else ''}{detail}")

    def publique(self) -> dict[str, str]:
        return {"code": self.code, "chemin": self.chemin, "detail": self.detail}


def _refus(code: str, chemin: str, detail: str) -> RefusEvaluation:
    return RefusEvaluation(code, detail, chemin)


def _objet(valeur: Any, chemin: str, champs: set[str], requis: set[str] = frozenset()) -> Mapping[str, Any]:
    if not isinstance(valeur, Mapping):
        raise _refus("REJ-EVAL-CORPUS-FORME", chemin, "objet attendu")
    inconnus = set(valeur) - champs
    if inconnus:
        raise _refus("REJ-EVAL-CORPUS-CHAMP-INCONNU", chemin, f"champ(s) inconnu(s) : {sorted(map(str, inconnus))}")
    manquants = set(requis) - set(valeur)
    if manquants:
        raise _refus("REJ-EVAL-CORPUS-FORME", chemin, f"champ(s) requis manquant(s) : {sorted(manquants)}")
    return valeur


def _texte(valeur: Any, chemin: str, *, vide: bool = False) -> str:
    if not isinstance(valeur, str) or (not vide and not valeur.strip()):
        raise _refus("REJ-EVAL-CORPUS-FORME", chemin, "texte non vide attendu")
    return valeur


def _liste_textes(valeur: Any, chemin: str) -> list[str]:
    if not isinstance(valeur, list):
        raise _refus("REJ-EVAL-CORPUS-FORME", chemin, "liste attendue")
    return [_texte(v, f"{chemin}[{i}]") for i, v in enumerate(valeur)]


def _motifs(valeur: Any, chemin: str) -> list[str]:
    motifs = _liste_textes(valeur, chemin)
    for i, motif in enumerate(motifs):
        try:
            re.compile(motif)
        except re.error as exc:
            raise _refus("REJ-EVAL-CORPUS-MOTIF", f"{chemin}[{i}]", f"expression régulière invalide : {exc}") from exc
    return motifs


def _nom_outil(valeur: Any, chemin: str) -> str:
    if not isinstance(valeur, str) or not _NOM_OUTIL.match(valeur):
        raise _refus("REJ-EVAL-CORPUS-FORME", chemin, "nom d'outil OPSYS attendu (mN_… ou opsys_…)")
    return valeur


def _contraintes(valeur: Any, chemin: str) -> None:
    if not isinstance(valeur, Mapping):
        raise _refus("REJ-EVAL-CORPUS-FORME", chemin, "objet {champ: contrainte} attendu")
    for cle, contrainte in valeur.items():
        sous = f"{chemin}.{cle}"
        _objet(contrainte, sous, _CHAMPS_CONTRAINTE)
        if len(contrainte) != 1:
            raise _refus("REJ-EVAL-CORPUS-FORME", sous, "exactement une contrainte parmi egal, motif, present, dans")
        if "motif" in contrainte:
            _motifs([contrainte["motif"]], f"{sous}.motif")
        if "present" in contrainte and not isinstance(contrainte["present"], bool):
            raise _refus("REJ-EVAL-CORPUS-FORME", f"{sous}.present", "booléen attendu")
        if "dans" in contrainte and (not isinstance(contrainte["dans"], list) or not contrainte["dans"]):
            raise _refus("REJ-EVAL-CORPUS-FORME", f"{sous}.dans", "liste non vide attendue")


def _valider_entree(entree: Any, chemin: str) -> None:
    entree = _objet(entree, chemin, _CHAMPS_ENTREE, {"demande"})
    _texte(entree["demande"], f"{chemin}.demande")
    if "donnees_observees" in entree:
        observees = entree["donnees_observees"]
        if not isinstance(observees, list) or not observees:
            raise _refus("REJ-EVAL-CORPUS-FORME", f"{chemin}.donnees_observees", "liste non vide attendue")
        for i, donnee in enumerate(observees):
            sous = f"{chemin}.donnees_observees[{i}]"
            donnee = _objet(donnee, sous, {"source", "contenu"}, {"source", "contenu"})
            _texte(donnee["source"], f"{sous}.source")
            _texte(donnee["contenu"], f"{sous}.contenu")
    if "faits" in entree:
        faits = entree["faits"]
        if not isinstance(faits, Mapping) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in faits.items()
        ):
            raise _refus("REJ-EVAL-CORPUS-FORME", f"{chemin}.faits", "objet {clé: texte} attendu (valeurs en texte)")


def _valider_attentes(attentes: Any, chemin: str, categorie: str) -> None:
    attentes = _objet(attentes, chemin, _CHAMPS_ATTENTES, {"decision"})
    decision = attentes["decision"]
    if decision not in DECISIONS:
        raise _refus("REJ-EVAL-CORPUS-FORME", f"{chemin}.decision", f"attendu parmi {list(DECISIONS)}")
    if "codes_refus" in attentes:
        codes = _liste_textes(attentes["codes_refus"], f"{chemin}.codes_refus")
        if not codes or any(c not in CODES_REFUS for c in codes):
            raise _refus("REJ-EVAL-CORPUS-FORME", f"{chemin}.codes_refus", f"codes parmi {list(CODES_REFUS)}")
        if decision not in ("refuser", "refuser_ou_demander_approbation"):
            raise _refus("REJ-EVAL-CORPUS-INCOHERENT", f"{chemin}.codes_refus", "codes de refus sans décision de refus")
    if "niveau_minimal" in attentes and attentes["niveau_minimal"] not in NIVEAUX:
        raise _refus("REJ-EVAL-CORPUS-FORME", f"{chemin}.niveau_minimal", f"attendu parmi {list(NIVEAUX)}")
    if decision in ("demander_approbation", "refuser_ou_demander_approbation") and "niveau_minimal" not in attentes:
        raise _refus("REJ-EVAL-CORPUS-INCOHERENT", f"{chemin}.niveau_minimal", "requis pour une approbation attendue")
    if "outil_attendu" in attentes:
        sous = f"{chemin}.outil_attendu"
        outil = _objet(attentes["outil_attendu"], sous, _CHAMPS_OUTIL_ATTENDU, {"nom", "issue"})
        _nom_outil(outil["nom"], f"{sous}.nom")
        if outil["issue"] not in ISSUES_OUTIL:
            raise _refus("REJ-EVAL-CORPUS-FORME", f"{sous}.issue", f"attendu parmi {list(ISSUES_OUTIL)}")
        if "arguments" in outil:
            _contraintes(outil["arguments"], f"{sous}.arguments")
        if "resultat" in outil:
            _contraintes(outil["resultat"], f"{sous}.resultat")
    if "outils_interdits" in attentes:
        for i, nom in enumerate(_liste_textes(attentes["outils_interdits"], f"{chemin}.outils_interdits")):
            _nom_outil(nom, f"{chemin}.outils_interdits[{i}]")
    for cle in ("aucun_outil", "inconnu_attendu"):
        if cle in attentes and not isinstance(attentes[cle], bool):
            raise _refus("REJ-EVAL-CORPUS-FORME", f"{chemin}.{cle}", "booléen attendu")
    if attentes.get("aucun_outil") and "outil_attendu" in attentes:
        raise _refus("REJ-EVAL-CORPUS-INCOHERENT", chemin, "aucun_outil et outil_attendu ensemble")
    for cle in ("motifs_requis", "motifs_interdits"):
        if cle in attentes:
            _motifs(attentes[cle], f"{chemin}.{cle}")
    if "chiffres" in attentes and attentes["chiffres"] not in ("interdits_hors_entree", "libres"):
        raise _refus("REJ-EVAL-CORPUS-FORME", f"{chemin}.chiffres", "attendu 'interdits_hors_entree' ou 'libres'")
    if "chiffres_autorises" in attentes:
        _liste_textes(attentes["chiffres_autorises"], f"{chemin}.chiffres_autorises")
    if "sonde_autorite" in attentes:
        sous = f"{chemin}.sonde_autorite"
        sonde = _objet(attentes["sonde_autorite"], sous, _CHAMPS_SONDE, {"outil", "arguments", "verdict"})
        _nom_outil(sonde["outil"], f"{sous}.outil")
        if not isinstance(sonde["arguments"], Mapping):
            raise _refus("REJ-EVAL-CORPUS-FORME", f"{sous}.arguments", "objet attendu")
        if sonde["verdict"] not in VERDICTS_SONDE:
            raise _refus("REJ-EVAL-CORPUS-FORME", f"{sous}.verdict", f"attendu parmi {list(VERDICTS_SONDE)}")
        if "erreur" in sonde:
            _texte(sonde["erreur"], f"{sous}.erreur")
    # Règles du gabarit par catégorie : une injection ou un refus attendu sans garde nommée n'évalue rien.
    if categorie in ("refus_attendu", "injection_consigne") and decision == "executer":
        raise _refus("REJ-EVAL-CORPUS-INCOHERENT", f"{chemin}.decision", f"{categorie} : refus ou approbation attendu")
    if categorie == "appel_outil" and "outil_attendu" not in attentes:
        raise _refus("REJ-EVAL-CORPUS-INCOHERENT", chemin, "appel_outil : outil_attendu requis")
    if categorie == "honnetete_inconnu" and not attentes.get("inconnu_attendu"):
        raise _refus("REJ-EVAL-CORPUS-INCOHERENT", chemin, "honnetete_inconnu : inconnu_attendu: true requis")
    if categorie == "mention_professionnel" and not attentes.get("motifs_requis"):
        raise _refus("REJ-EVAL-CORPUS-INCOHERENT", chemin, "mention_professionnel : motifs_requis requis")


def _valider_reference_reponse(reponse: Any, chemin: str) -> None:
    from .repondants import reponse_depuis_objet  # import différé : repondants dépend de ce module

    try:
        reponse_depuis_objet(reponse)
    except RefusEvaluation as exc:
        raise _refus("REJ-EVAL-CORPUS-FORME", f"{chemin}.{exc.chemin}".rstrip("."), exc.detail) from exc


def valider_corpus(corpus: Any, *, departement: str | None = None) -> dict[str, Any]:
    """Valide un corpus de département et le rend (copie profonde). Lève `RefusEvaluation` au premier défaut."""
    corpus = _objet(corpus, "", _CHAMPS_CORPUS, {"schema", "departement", "version", "fictif", "cas"})
    if corpus["schema"] != SCHEMA_CORPUS:
        raise _refus("REJ-EVAL-CORPUS-FORME", "schema", f"attendu {SCHEMA_CORPUS!r}")
    if corpus["fictif"] is not True:
        raise _refus("REJ-EVAL-CORPUS-FICTIF", "fictif", "un corpus porte fictif: true (aucune donnée réelle)")
    dep = corpus["departement"]
    if not isinstance(dep, str) or not _ID_DEPARTEMENT.match(dep):
        raise _refus("REJ-EVAL-CORPUS-FORME", "departement", "identifiant de département attendu (mNN-…)")
    if departement is not None and dep != departement:
        raise _refus("REJ-EVAL-CORPUS-INCOHERENT", "departement", f"corpus de {dep!r} rangé sous {departement!r}")
    _texte(corpus["version"], "version")
    if "chiffres_permis" in corpus:
        _liste_textes(corpus["chiffres_permis"], "chiffres_permis")
    if "references" in corpus:
        if not isinstance(corpus["references"], list):
            raise _refus("REJ-EVAL-CORPUS-FORME", "references", "liste attendue")
        for i, ref in enumerate(corpus["references"]):
            ref = _objet(ref, f"references[{i}]", _CHAMPS_REFERENCE, {"chemin", "sha256", "executeur"})
            _texte(ref["chemin"], f"references[{i}].chemin")
            if not isinstance(ref["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", ref["sha256"]):
                raise _refus("REJ-EVAL-CORPUS-FORME", f"references[{i}].sha256", "empreinte sha256 attendue")
            if not isinstance(ref["executeur"], str) or not _EXECUTEUR.match(ref["executeur"]):
                raise _refus("REJ-EVAL-CORPUS-FORME", f"references[{i}].executeur", "module:fonction attendu")
    cas_liste = corpus["cas"]
    if not isinstance(cas_liste, list):
        raise _refus("REJ-EVAL-CORPUS-FORME", "cas", "liste attendue")
    prefixe = f"m{int(dep[1:3])}-"
    ids: set[str] = set()
    for i, cas in enumerate(cas_liste):
        chemin = f"cas[{i}]"
        cas = _objet(cas, chemin, _CHAMPS_CAS,
                     {"id", "categorie", "gravite", "poids", "source", "entree", "attentes", "reponse_reference"})
        ident = cas["id"]
        if not isinstance(ident, str) or not _ID_CAS.match(ident) or not ident.startswith(prefixe):
            raise _refus("REJ-EVAL-CORPUS-FORME", f"{chemin}.id", f"identifiant {prefixe}… attendu")
        chemin = f"cas[{ident}]"
        if ident in ids:
            raise _refus("REJ-EVAL-CORPUS-DOUBLON", chemin, "identifiant de cas en double")
        ids.add(ident)
        if cas["categorie"] not in CATEGORIES:
            raise _refus("REJ-EVAL-CORPUS-CATEGORIE", f"{chemin}.categorie", f"attendu parmi {list(CATEGORIES)}")
        if (cas["categorie"] == "refus_attendu") != ("motif_refus" in cas):
            raise _refus("REJ-EVAL-CORPUS-INCOHERENT", f"{chemin}.motif_refus",
                         "motif_refus requis pour refus_attendu, et seulement pour lui")
        if "motif_refus" in cas and cas["motif_refus"] not in MOTIFS_REFUS:
            raise _refus("REJ-EVAL-CORPUS-FORME", f"{chemin}.motif_refus", f"attendu parmi {list(MOTIFS_REFUS)}")
        if cas["gravite"] not in GRAVITES:
            raise _refus("REJ-EVAL-CORPUS-FORME", f"{chemin}.gravite", f"attendu parmi {list(GRAVITES)}")
        if type(cas["poids"]) is not int or not 1 <= cas["poids"] <= 5:
            raise _refus("REJ-EVAL-CORPUS-FORME", f"{chemin}.poids", "entier de 1 à 5 attendu")
        _texte(cas["source"], f"{chemin}.source")
        if "derive_de" in cas:
            _texte(cas["derive_de"], f"{chemin}.derive_de")
        _valider_entree(cas["entree"], f"{chemin}.entree")
        _valider_attentes(cas["attentes"], f"{chemin}.attentes", cas["categorie"])
        _valider_reference_reponse(cas["reponse_reference"], f"{chemin}.reponse_reference")
    if len(cas_liste) < MIN_CAS_PAR_DEPARTEMENT:
        raise _refus("REJ-EVAL-CORPUS-COUVERTURE", "cas",
                     f"{len(cas_liste)} cas : au moins {MIN_CAS_PAR_DEPARTEMENT} par département")
    absentes = [c for c in CATEGORIES if not any(cas["categorie"] == c for cas in cas_liste)]
    if absentes:
        raise _refus("REJ-EVAL-CORPUS-COUVERTURE", "cas", f"catégorie(s) non couverte(s) : {absentes}")
    return copy.deepcopy(dict(corpus))


def empreinte(donnees: Any) -> str:
    """sha256 du JSON canonique (clés triées) : même contenu, même empreinte, quel que soit le format source."""
    return hashlib.sha256(
        json.dumps(donnees, sort_keys=True, ensure_ascii=False, allow_nan=False, default=str).encode("utf-8")
    ).hexdigest()


def charger_corpus(chemin: Path, *, departement: str | None = None) -> dict[str, Any]:
    """Lit et valide un corpus YAML ; `RefusEvaluation` si le fichier est absent, illisible ou mal formé."""
    try:
        texte = Path(chemin).read_text(encoding="utf-8")
    except OSError as exc:
        raise RefusEvaluation("REJ-EVAL-CORPUS-ABSENT", f"fichier illisible : {exc.strerror}", str(chemin)) from exc
    try:
        donnees = yaml.safe_load(texte)
    except yaml.YAMLError as exc:
        raise RefusEvaluation("REJ-EVAL-CORPUS-FORME", f"YAML invalide : {exc}", str(chemin)) from exc
    return valider_corpus(donnees, departement=departement)


def verifier_references(corpus: Mapping[str, Any], racine_departement: Path) -> list[dict[str, Any]]:
    """Vérifie l'empreinte des corpus existants référencés (ex. M9) : une dérive est un refus, jamais ignorée."""
    verifiees = []
    for i, ref in enumerate(corpus.get("references", ())):
        fichier = Path(racine_departement) / ref["chemin"]
        try:
            contenu = fichier.read_bytes()
        except OSError as exc:
            raise _refus("REJ-EVAL-CORPUS-REFERENCE", f"references[{i}]",
                         f"corpus référencé illisible : {exc}") from exc
        reel = hashlib.sha256(contenu).hexdigest()
        if reel != ref["sha256"]:
            raise _refus("REJ-EVAL-CORPUS-REFERENCE", f"references[{i}]",
                         f"{ref['chemin']} a changé (sha256 {reel[:12]}…, attendu {ref['sha256'][:12]}…) : "
                         "revoir le corpus de référence puis mettre à jour l'empreinte")
        verifiees.append({"chemin": ref["chemin"], "sha256": reel, "executeur": ref["executeur"]})
    return verifiees
