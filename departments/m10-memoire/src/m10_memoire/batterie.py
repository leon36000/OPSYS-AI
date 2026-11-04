"""Batterie de questions-tests « non-oubli » (M10-05) : un corpus FICTIF, des faits sourcés et des
mesures déterministes.

Ce que ce module mesure, sans modèle et sans réseau :

- le **rappel** : parmi les faits qu'une question déclare attendus, combien sont réellement
  retrouvables dans le registre Événements de M10, par leur clé publique (type d'événement +
  identifiant) ;
- la **précision** : parmi les faits que la portée de la question retourne, combien sont attendus.
  Un fait interdit, ou sourcé d'un document qui n'appartient pas au domaine des affaires, compte
  au dénominateur et jamais au numérateur : c'est une fuite, pas une réponse ;
- la **couverture** : questions évaluables / questions de la batterie, et sources attendues
  disponibles / sources attendues. Un dénominateur absent n'est jamais remplacé par zéro : la
  mesure est dite non évaluable avec sa raison.

**Agrégats par occurrence, pas couverture d'ensemble.** Les totaux du rapport sont des sommes
d'**occurrences par question** : un fait attendu par deux questions compte deux fois au numérateur
et au dénominateur du rappel ; une source attendue par deux questions compte deux fois dans la
couverture des sources ; un fait retourné par la portée de deux questions compte deux fois au
dénominateur de la précision. ``sources_absentes`` est nommé au grain (question, fait, source) : une
même source absente peut donc y apparaître plusieurs fois. Ce choix mesure la réussite de chaque
question, pas le pourcentage de faits uniques retrouvés dans la mémoire ; il est déclaré dans
``semantique_agregation`` et ne doit pas être lu comme une couverture d'ensemble.

L'inventaire du magasin de sources est **explicite** : ``documents_disponibles`` est une séquence
d'identifiants de documents réellement présents (jamais un mapping, dont les clés seraient lues
comme un inventaire). Son absence (``None``) n'est ni un zéro ni un 100 % : la couverture des
sources est dite non évaluable (``AUCUN_INVENTAIRE_SOURCES``), et aucune source n'est déclarée
présente ou absente. Une liste vide est un zéro connu ; une liste complète est un 100 % connu. Le
corpus déclaré n'est jamais présumé présent dans le magasin.

Les maillons fournis par l'appelant sont le **contrat des registres** : une séquence de mappings,
chacun portant un ``type_entree`` de l'énuméré de :mod:`registre`. Un conteneur mapping, un maillon
non-mapping ou un ``type_entree`` absent/inconnu est un refus ``REJ-BATTERIE-FORME``, jamais une
absence de faits. Pour un **événement reconnu** (un type opérationnel que :mod:`classification`
classe, y compris les types historiques), la clé publique lue par ``classification.identifiant``
doit être une chaîne de la forme réelle du type : un ``devis_id``, ``wct_id``, ``evenement_id`` ou
``fait_id`` absent, ``None``, mal typé ou non hashable est refusé, au lieu de produire un faux
oubli, une fausse précision ou un ``TypeError``. Une relation de portée **présente** mais malformée
(``lead_id`` d'un WCT ou d'un fait de l'amont, ``wct_id`` d'une variance ou d'une rentabilité) est
refusée pour la même raison ; une relation **absente** reste acceptée, car des maillons historiques
incomplets existent réellement et refuser tout le registre pour eux serait abusif : le maillon
n'est alors rattaché à aucune affaire, sans que la batterie n'invente son affaire. Un maillon
**valide hors du périmètre de la batterie** (autre ``type_entree``, événement du bus non modélisé)
est accepté et simplement non classifié : refuser un événement valide serait une autre faute. La
batterie ne lit aucun stockage et ne certifie ni l'ACL, ni la provenance, ni la chaîne de hash, ni
la présence réelle des sources : elle évalue les données que l'appelant lui remet.

Une **suppression de fait** (le fait n'est plus dans le registre) fait baisser le rappel et nomme
le fait manquant. Une **source absente** (un inventaire explicite ne la contient pas) fait baisser
la couverture des sources sans effacer le fait : les deux mesures restent distinctes.

Le corpus est fermé : un champ inconnu, un identifiant dupliqué, une source inconnue, un fait
attendu hors de la portée de sa question ou un volume hors bornes est un refus typé
(``BatterieInvalide``), jamais un cas ignoré. Le rapport ne recopie JAMAIS le texte d'un document :
il ne rend que des identifiants, des comptes et les motifs d'absence. Le domaine ``affaires`` est
le seul admissible ; un fait sourcé d'un document ``developpement`` est non évaluable et signalé
comme fuite s'il est retourné. Les deux mémoires ne sont donc jamais mêlées.

Module pur (DA-M10-08) : aucun import d'``opsys``, aucune horloge, aucun accès fichier ou réseau.
Le corpus est fourni par l'appelant ; l'instant n'intervient pas.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from typing import Any

from . import affaire, audit, classification, etapes, registre

SCHEMA_BATTERIE = "opsys.m10.non_oubli/v1"

MAX_DOCUMENTS = 200
MAX_FAITS = 500
MAX_QUESTIONS = 100
MAX_SOURCES_PAR_FAIT = 10
MAX_TEXTE_DOCUMENT = 2000
MAX_TEXTE_QUESTION = 1000
MAX_VERSION = 64
MAX_AUTEUR = 160
MAX_ENTREPRISE = 200
MAX_DESCRIPTION = 1000

_DOMAINES = ("affaires", "developpement")

RAISON_AUCUN_FAIT_ATTENDU = "AUCUN_FAIT_ATTENDU"
RAISON_SOURCE_HORS_DOMAINE = "SOURCE_HORS_DOMAINE"
RAISON_AUCUN_FAIT_EVALUABLE = "AUCUN_FAIT_EVALUABLE"
RAISON_AUCUN_FAIT_RETOURNE = "AUCUN_FAIT_RETOURNE"
RAISON_AUCUNE_SOURCE_ATTENDUE = "AUCUNE_SOURCE_ATTENDUE"
RAISON_AUCUN_INVENTAIRE_SOURCES = "AUCUN_INVENTAIRE_SOURCES"

MODE_SOURCES_INVENTAIRE_EXPLICITE = "inventaire_explicite"
MODE_SOURCES_INVENTAIRE_ABSENT = "inventaire_absent"

MOTIF_INTERDIT = "INTERDIT"
MOTIF_SOURCE_HORS_DOMAINE = "SOURCE_HORS_DOMAINE"

_IDENTIFIANT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_CHAMPS_CORPUS = {
    "schema",
    "fictif",
    "version",
    "auteur",
    "entreprise",
    "description",
    "documents",
    "faits",
    "questions",
}
_CHAMPS_DOCUMENT = {"id", "domaine", "texte"}
_CHAMPS_FAIT = {"id", "affaire_id", "type_evenement", "identifiant", "sources"}
_CHAMPS_QUESTION = {"id", "texte", "affaire_id", "types_evenement", "attendus", "interdits"}


class BatterieInvalide(ValueError):
    """Refus typé de la batterie : ``code`` stable, ``chemin`` du champ fautif, ``detail`` lisible."""

    def __init__(self, code: str, chemin: str, detail: str) -> None:
        self.code, self.chemin, self.detail = code, chemin, detail
        super().__init__(f"{code} : {chemin + ' : ' if chemin else ''}{detail}")

    def publique(self) -> dict[str, str]:
        return {"code": self.code, "chemin": self.chemin, "detail": self.detail}


def _refus(code: str, chemin: str, detail: str) -> BatterieInvalide:
    return BatterieInvalide(code, chemin, detail)


def _objet(
    valeur: Any, chemin: str, champs: set[str], requis: set[str] = frozenset()
) -> dict[str, Any]:
    if not isinstance(valeur, Mapping):
        raise _refus("REJ-BATTERIE-FORME", chemin, "objet attendu")
    # Normalise tout Mapping (MappingProxyType, UserDict…) en dict : le corpus validé ne doit
    # contenir que des formes JSON canoniques, jamais un objet dont la représentation `str`
    # dépendrait de l'ordre d'insertion.
    valeur = dict(valeur)
    inconnus = set(valeur) - champs
    if inconnus:
        raise _refus(
            "REJ-BATTERIE-CHAMP-INCONNU", chemin, f"champ(s) inconnu(s) : {sorted(map(str, inconnus))}"
        )
    manquants = set(requis) - set(valeur)
    if manquants:
        raise _refus(
            "REJ-BATTERIE-FORME", chemin, f"champ(s) requis manquant(s) : {sorted(map(str, manquants))}"
        )
    return valeur


def _texte(valeur: Any, chemin: str, maximum: int) -> str:
    if not isinstance(valeur, str) or not valeur.strip():
        raise _refus("REJ-BATTERIE-FORME", chemin, "texte non vide attendu")
    if len(valeur) > maximum:
        raise _refus("REJ-BATTERIE-BORNE", chemin, f"texte de {maximum} caractères au plus attendu")
    return valeur


def _identifiant(valeur: Any, chemin: str) -> str:
    if not isinstance(valeur, str) or _IDENTIFIANT.fullmatch(valeur) is None:
        raise _refus("REJ-BATTERIE-FORME", chemin, "identifiant borné attendu")
    return valeur


def _cle_publique_fait(type_evenement: str, valeur: Any, chemin: str) -> str:
    """La clé publique d'un fait, dans la forme réelle de son type d'événement.

    Deux étapes de l'amont ont une clé qui est une **affaire** : M1 ne publie qu'un lead, tandis que
    M2 peut ouvrir une opportunité ``<lead>~opp~<wct_id>`` (jusqu'à 197 caractères, cf.
    :mod:`affaire`). Tous les autres faits (WCT, variance, rentabilité, devis, fait_id) gardent
    l'identifiant borné historique, sans élargir le tilde aux types qui ne le portent pas.
    """
    if type_evenement == etapes.TYPE_LEAD_QUALIFIE:
        if not affaire.est_lead(valeur):
            raise _refus("REJ-BATTERIE-FORME", chemin, "identifiant de lead attendu")
        return valeur
    if type_evenement == etapes.TYPE_CLIENT_ASSOCIE:
        if not affaire.valide(valeur):
            raise _refus(
                "REJ-BATTERIE-FORME", chemin, "identifiant d'affaire (lead ou opportunité) attendu"
            )
        return valeur
    return _identifiant(valeur, chemin)


def _liste(valeur: Any, chemin: str, maximum: int) -> list[Any]:
    if not isinstance(valeur, list):
        raise _refus("REJ-BATTERIE-FORME", chemin, "liste attendue")
    if len(valeur) > maximum:
        raise _refus("REJ-BATTERIE-BORNE", chemin, f"au plus {maximum} éléments")
    return valeur


def _valider_documents(valeur: Any) -> dict[str, Mapping[str, Any]]:
    documents: dict[str, Mapping[str, Any]] = {}
    for index, document in enumerate(_liste(valeur, "documents", MAX_DOCUMENTS)):
        chemin = f"documents[{index}]"
        document = _objet(document, chemin, _CHAMPS_DOCUMENT, _CHAMPS_DOCUMENT)
        identifiant = _identifiant(document["id"], f"{chemin}.id")
        if identifiant in documents:
            raise _refus("REJ-BATTERIE-DOUBLON", f"{chemin}.id", "document en double")
        if document["domaine"] not in _DOMAINES:
            raise _refus("REJ-BATTERIE-FORME", f"{chemin}.domaine", f"domaine parmi {list(_DOMAINES)}")
        _texte(document["texte"], f"{chemin}.texte", MAX_TEXTE_DOCUMENT)
        documents[identifiant] = document
    return documents


def _valider_faits(valeur: Any, documents: Mapping[str, Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    faits: dict[str, Mapping[str, Any]] = {}
    cles: set[tuple[str, str]] = set()
    for index, fait in enumerate(_liste(valeur, "faits", MAX_FAITS)):
        chemin = f"faits[{index}]"
        fait = _objet(fait, chemin, _CHAMPS_FAIT, _CHAMPS_FAIT)
        identifiant = _identifiant(fait["id"], f"{chemin}.id")
        if identifiant in faits:
            raise _refus("REJ-BATTERIE-DOUBLON", f"{chemin}.id", "fait en double")
        if not affaire.valide(fait["affaire_id"]):
            raise _refus("REJ-BATTERIE-FORME", f"{chemin}.affaire_id", "forme d'affaire invalide")
        if fait["type_evenement"] not in audit.types_audites():
            raise _refus(
                "REJ-BATTERIE-FORME", f"{chemin}.type_evenement", "type d'événement audité attendu"
            )
        cle_publique = _cle_publique_fait(
            fait["type_evenement"], fait["identifiant"], f"{chemin}.identifiant"
        )
        cle = (fait["type_evenement"], cle_publique)
        if cle in cles:
            raise _refus(
                "REJ-BATTERIE-DOUBLON",
                f"{chemin}.identifiant",
                "deux faits pour la même clé publique de registre",
            )
        cles.add(cle)
        sources = _liste(fait["sources"], f"{chemin}.sources", MAX_SOURCES_PAR_FAIT)
        if not sources:
            raise _refus("REJ-BATTERIE-FORME", f"{chemin}.sources", "au moins une source attendue")
        vues: set[str] = set()
        for position, source in enumerate(sources):
            if not isinstance(source, str) or source not in documents:
                raise _refus(
                    "REJ-BATTERIE-SOURCE-INCONNUE", f"{chemin}.sources[{position}]", "document inconnu"
                )
            if source in vues:
                raise _refus("REJ-BATTERIE-DOUBLON", f"{chemin}.sources[{position}]", "source en double")
            vues.add(source)
        faits[identifiant] = fait
    return faits


def _verifier_scope(fait: Mapping[str, Any], question: Mapping[str, Any], champ: str, position: int) -> None:
    if fait["affaire_id"] != question["affaire_id"]:
        raise _refus(
            "REJ-BATTERIE-QUESTION-INCOHERENTE",
            f"{champ}[{position}]",
            "le fait n'appartient pas à l'affaire de la question",
        )
    if fait["type_evenement"] not in question["types_evenement"]:
        raise _refus(
            "REJ-BATTERIE-QUESTION-INCOHERENTE",
            f"{champ}[{position}]",
            "le fait est hors des types d'événement de la question",
        )


def _valider_questions(
    valeur: Any, faits: Mapping[str, Mapping[str, Any]]
) -> list[Mapping[str, Any]]:
    questions = _liste(valeur, "questions", MAX_QUESTIONS)
    if not questions:
        raise _refus("REJ-BATTERIE-VIDE", "questions", "au moins une question")
    vus: set[str] = set()
    for index, question in enumerate(questions):
        chemin = f"questions[{index}]"
        question = _objet(
            question,
            chemin,
            _CHAMPS_QUESTION,
            {"id", "texte", "affaire_id", "types_evenement", "attendus"},
        )
        identifiant = _identifiant(question["id"], f"{chemin}.id")
        if identifiant in vus:
            raise _refus("REJ-BATTERIE-DOUBLON", f"{chemin}.id", "question en double")
        vus.add(identifiant)
        _texte(question["texte"], f"{chemin}.texte", MAX_TEXTE_QUESTION)
        if not affaire.valide(question["affaire_id"]):
            raise _refus("REJ-BATTERIE-FORME", f"{chemin}.affaire_id", "forme d'affaire invalide")
        types = _liste(question["types_evenement"], f"{chemin}.types_evenement", len(audit.types_audites()))
        if not types:
            raise _refus("REJ-BATTERIE-QUESTION-INCOHERENTE", f"{chemin}.types_evenement", "au moins un type")
        for position, type_evenement in enumerate(types):
            if type_evenement not in audit.types_audites():
                raise _refus(
                    "REJ-BATTERIE-QUESTION-INCOHERENTE",
                    f"{chemin}.types_evenement[{position}]",
                    "type d'événement audité attendu",
                )
        if len(set(types)) != len(types):
            raise _refus(
                "REJ-BATTERIE-QUESTION-INCOHERENTE", f"{chemin}.types_evenement", "type en double"
            )
        attendus = _liste(question["attendus"], f"{chemin}.attendus", MAX_FAITS)
        vus_attendus: set[str] = set()
        for position, fait_id in enumerate(attendus):
            if not isinstance(fait_id, str) or fait_id not in faits:
                raise _refus(
                    "REJ-BATTERIE-FAIT-INCONNU", f"{chemin}.attendus[{position}]", "fait attendu inconnu"
                )
            if fait_id in vus_attendus:
                raise _refus("REJ-BATTERIE-DOUBLON", f"{chemin}.attendus[{position}]", "fait attendu en double")
            vus_attendus.add(fait_id)
            _verifier_scope(faits[fait_id], question, f"{chemin}.attendus", position)
        interdits = _liste(question.get("interdits", []), f"{chemin}.interdits", MAX_FAITS)
        vus_interdits: set[str] = set()
        for position, fait_id in enumerate(interdits):
            if not isinstance(fait_id, str) or fait_id not in faits:
                raise _refus(
                    "REJ-BATTERIE-FAIT-INCONNU", f"{chemin}.interdits[{position}]", "fait interdit inconnu"
                )
            if fait_id in vus_interdits:
                raise _refus("REJ-BATTERIE-DOUBLON", f"{chemin}.interdits[{position}]", "fait interdit en double")
            vus_interdits.add(fait_id)
            _verifier_scope(faits[fait_id], question, f"{chemin}.interdits", position)
        if vus_attendus & vus_interdits:
            raise _refus(
                "REJ-BATTERIE-QUESTION-INCOHERENTE",
                f"{chemin}.interdits",
                "un fait ne peut pas être attendu et interdit",
            )
    return questions


def valider_batterie(corpus: Any) -> dict[str, Any]:
    """Valide le corpus et le rend (copie profonde). Lève ``BatterieInvalide`` au premier défaut."""
    corpus = _objet(
        corpus,
        "",
        _CHAMPS_CORPUS,
        {"schema", "fictif", "version", "auteur", "entreprise", "documents", "faits", "questions"},
    )
    if corpus["schema"] != SCHEMA_BATTERIE:
        raise _refus("REJ-BATTERIE-FORME", "schema", f"attendu {SCHEMA_BATTERIE!r}")
    if corpus["fictif"] is not True:
        raise _refus("REJ-BATTERIE-FICTIF", "fictif", "fictif: true requis (aucune donnée réelle)")
    _texte(corpus["version"], "version", MAX_VERSION)
    _texte(corpus["auteur"], "auteur", MAX_AUTEUR)
    _texte(corpus["entreprise"], "entreprise", MAX_ENTREPRISE)
    if "description" in corpus:
        _texte(corpus["description"], "description", MAX_DESCRIPTION)
    documents = _valider_documents(corpus["documents"])
    faits = _valider_faits(corpus["faits"], documents)
    questions = _valider_questions(corpus["questions"], faits)
    # `_objet` a déjà normalisé chaque sous-objet ; on reconstruit les listes depuis les objets
    # validés pour que `deepcopy` et l'empreinte ne voient plus aucun Mapping exotique.
    corpus["documents"] = [dict(document) for document in documents.values()]
    corpus["faits"] = [dict(fait) for fait in faits.values()]
    corpus["questions"] = [dict(question) for question in questions]
    return copy.deepcopy(corpus)


def empreinte_batterie(corpus: Any) -> str:
    """SHA-256 du corpus validé, en JSON canonique : même contenu, même empreinte."""
    valide = valider_batterie(corpus)
    return _empreinte(valide)


def _empreinte(corpus: Mapping[str, Any]) -> str:
    try:
        contenu = json.dumps(
            corpus,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as erreur:
        raise _refus(
            "REJ-BATTERIE-FORME",
            "corpus",
            f"forme non sérialisable en JSON canonique ({type(erreur).__name__})",
        ) from None
    return hashlib.sha256(contenu).hexdigest()


def _verifier_relation_affaire(maillon: Mapping[str, Any], cle: str, chemin: str) -> None:
    if cle not in maillon:
        return
    if not affaire.valide(maillon[cle]):
        raise _refus(
            "REJ-BATTERIE-FORME",
            f"{chemin}.{cle}",
            "identifiant d'affaire (lead ou opportunité) attendu",
        )


def _verifier_relation_identifiant(maillon: Mapping[str, Any], cle: str, chemin: str) -> None:
    if cle not in maillon:
        return
    _identifiant(maillon[cle], f"{chemin}.{cle}")


def _verifier_identifiants_evenement(maillon: Mapping[str, Any], chemin: str) -> None:
    """Valide les identifiants d'un **événement reconnu**, sans valider tout le registre.

    ``classification.type_evenement`` rend ``None`` pour un événement inconnu ou un maillon d'un
    autre ``type_entree`` : ces formes restent acceptées. Pour un type reconnu, la clé publique est
    obligatoire et doit avoir la forme du type (``_cle_publique_fait``). Une relation de portée
    présente doit être valide ; une relation absente reste acceptée (maillon historique incomplet
    réel, non attribué, jamais deviné).
    """
    type_evenement = classification.type_evenement(maillon)
    if type_evenement is None:
        return
    _cle_publique_fait(
        type_evenement, classification.identifiant(maillon), f"{chemin}.identifiant"
    )
    if type_evenement == classification.TYPE_WCT:
        _verifier_relation_affaire(maillon, "lead_id", chemin)
    elif type_evenement in (classification.TYPE_VARIANCE, classification.TYPE_RENTABILITE):
        _verifier_relation_identifiant(maillon, "wct_id", chemin)
    elif type_evenement not in (etapes.TYPE_LEAD_QUALIFIE, etapes.TYPE_CLIENT_ASSOCIE):
        # Les faits de l'amont (devis, correction, note) et le compagnon financier portent leur
        # affaire dans ``lead_id`` ; M1 et M2 l'ont déjà validé comme clé publique.
        _verifier_relation_affaire(maillon, "lead_id", chemin)


def _maillons(valeur: Any, chemin: str) -> list[Mapping[str, Any]]:
    """Matérialise une séquence de maillons et refuse les formes qui ne sont pas un registre.

    Le contrat des registres de M10 est une séquence de mappings portant un ``type_entree`` de
    l'énuméré de :mod:`registre` (``Registre.lire`` rend des ``dict``). Un mapping comme conteneur
    (dont les clés seraient lues comme des maillons), un maillon non-mapping, un conteneur binaire
    (``str``/``bytes``/``bytearray``/``memoryview``) ou un ``type_entree`` absent/inconnu est refusé.
    Un maillon valide d'un autre type — événement historique, événement du bus non modélisé ou
    maillon d'un autre registre — reste accepté : il ne devient simplement pas un fait classifié.
    Pour un événement reconnu, la clé publique et les relations présentes sont validées (voir
    ``_verifier_identifiants_evenement``) : sans cela, un identifiant absent, mal typé ou non
    hashable produirait un faux oubli, une fausse précision ou un ``TypeError``.
    """
    if isinstance(valeur, (str, bytes, bytearray, memoryview, Mapping)) or not isinstance(
        valeur, Iterable
    ):
        raise _refus("REJ-BATTERIE-FORME", chemin, "séquence de maillons attendue")
    try:
        bruts = list(valeur)
    except TypeError:
        raise _refus("REJ-BATTERIE-FORME", chemin, "séquence de maillons attendue") from None
    valides: list[Mapping[str, Any]] = []
    for index, maillon in enumerate(bruts):
        if not isinstance(maillon, Mapping):
            raise _refus(
                "REJ-BATTERIE-FORME", f"{chemin}[{index}]", "maillon de registre (objet) attendu"
            )
        # ``classification`` ne reconnaît que les ``dict`` ; tout Mapping valide est normalisé
        # AVANT la validation pour qu'un MappingProxyType ne soit pas silencieusement ignoré.
        try:
            maillon_dict = dict(maillon)
        except (TypeError, ValueError):
            raise _refus(
                "REJ-BATTERIE-FORME", f"{chemin}[{index}]", "maillon de registre lisible attendu"
            ) from None
        type_entree = maillon_dict.get("type_entree")
        if not isinstance(type_entree, str) or type_entree not in registre.types_entree():
            raise _refus(
                "REJ-BATTERIE-FORME",
                f"{chemin}[{index}].type_entree",
                "type_entree de registre attendu",
            )
        _verifier_identifiants_evenement(maillon_dict, f"{chemin}[{index}]")
        valides.append(maillon_dict)
    return valides


def _documents_disponibles(
    corpus: Mapping[str, Any], disponibles: Iterable[str] | None
) -> set[str] | None:
    """L'inventaire explicite du magasin, ou ``None`` quand l'appelant n'en fournit aucun.

    ``None`` ne vaut jamais « tous les documents déclarés sont présents » : l'absence d'inventaire
    ne prouve rien sur le magasin. Le corpus ne sert qu'à refuser un identifiant qui n'y figure pas.
    Un mapping est refusé : ses clés ne sont pas un inventaire de sources.
    """
    declares = {document["id"] for document in corpus["documents"]}
    if disponibles is None:
        return None
    if (
        isinstance(disponibles, (str, bytes, bytearray, memoryview, Mapping))
        or not isinstance(disponibles, Iterable)
    ):
        raise _refus("REJ-BATTERIE-FORME", "documents_disponibles", "identifiants de documents attendus")
    try:
        choisis = set(disponibles)
    except TypeError:
        raise _refus("REJ-BATTERIE-FORME", "documents_disponibles", "identifiants de documents attendus") from None
    if not all(isinstance(identifiant, str) for identifiant in choisis):
        raise _refus("REJ-BATTERIE-FORME", "documents_disponibles", "identifiants de documents attendus")
    inconnus = choisis - declares
    if inconnus:
        raise _refus(
            "REJ-BATTERIE-DOCUMENT-INCONNU",
            "documents_disponibles",
            f"document(s) absent(s) du corpus : {sorted(inconnus)}",
        )
    return choisis


def _mesure(numerateur: int, denominateur: int, *, non_evaluable: str) -> dict[str, Any]:
    if denominateur == 0:
        return {"evaluable": False, "raison": non_evaluable}
    return {
        "evaluable": True,
        "numerateur": numerateur,
        "denominateur": denominateur,
        "valeur": round(numerateur / denominateur, 4),
        "valeur_pct": round(100 * numerateur / denominateur, 1),
    }


def evaluer_batterie(
    corpus: Any,
    maillons_evenements: Iterable[Mapping[str, Any]],
    maillons_affaires: Iterable[Mapping[str, Any]] | None = None,
    documents_disponibles: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Évalue la batterie sur les faits Événements fournis. Ne lit ni n'écrit aucun stockage.

    ``maillons_evenements`` et ``maillons_affaires`` sont des séquences de maillons du contrat des
    registres (mappings avec un ``type_entree`` connu). Un conteneur mapping ou un maillon malformé
    est refusé (``REJ-BATTERIE-FORME``) ; un maillon valide hors du périmètre de la batterie est
    accepté et non classifié.

    Les agrégats (``rappel``, ``precision``, ``couverture_sources``) sont des sommes
    d'**occurrences par question**, pas des ensembles de faits/sources uniques : voir
    ``semantique_agregation`` dans le rapport. Une question non évaluable n'entre dans aucun
    dénominateur ; pour rester cohérentes avec eux, les listes globales ``manquants`` et
    ``sources_absentes`` ne la listent pas non plus, tandis que ``par_question`` conserve ses faits
    manquants, ses sources absentes et sa ``raison`` de non-évaluation.

    Pour un événement **reconnu** par :mod:`classification`, la clé publique et les relations
    présentes sont validées (``REJ-BATTERIE-FORME``) ; un événement inconnu ou un maillon d'un autre
    ``type_entree`` reste accepté, et un maillon historique incomplet dont la relation de portée est
    absente est accepté sans être attribué.

    ``documents_disponibles`` : l'inventaire explicite des sources réellement présentes dans le
    magasin. ``None`` (défaut) signifie « inventaire non fourni » : la couverture des sources est
    non évaluable (``AUCUN_INVENTAIRE_SOURCES``), jamais présumée à 100 %. Une liste vide est un
    zéro connu, une liste complète un 100 % connu. Un identifiant inconnu du corpus est refusé
    (fail-closed), et un mapping n'est pas un inventaire. Le corpus déclaré n'est jamais tenu pour
    présent dans le magasin.
    """
    valide = valider_batterie(corpus)
    maillons = _maillons(maillons_evenements, "maillons_evenements")
    affaires = [] if maillons_affaires is None else _maillons(maillons_affaires, "maillons_affaires")
    disponible = _documents_disponibles(valide, documents_disponibles)
    mode_sources = (
        MODE_SOURCES_INVENTAIRE_EXPLICITE
        if disponible is not None
        else MODE_SOURCES_INVENTAIRE_ABSENT
    )

    documents = {document["id"]: document for document in valide["documents"]}
    faits = {fait["id"]: fait for fait in valide["faits"]}
    faits_par_cle = {
        (fait["type_evenement"], fait["identifiant"]): identifiant
        for identifiant, fait in faits.items()
    }
    par_question: list[dict[str, Any]] = []
    non_evaluables: list[dict[str, str]] = []
    manquants: list[dict[str, str]] = []
    sources_absentes: list[dict[str, str]] = []
    fuites: list[dict[str, str]] = []

    attendus_total = 0
    trouves_total = 0
    retournes_total = 0
    pertinents_total = 0
    sources_total = 0
    sources_presentes_total = 0
    evaluables = 0

    for question in valide["questions"]:
        de_l_affaire = classification.evenements_de_laffaire(question["affaire_id"], maillons)
        cles_retournees = {
            (type_evenement, identifiant)
            for maillon in de_l_affaire
            if (type_evenement := classification.type_evenement(maillon)) in question["types_evenement"]
            and (identifiant := classification.identifiant(maillon)) is not None
        }
        retournes_faits = sorted(
            {faits_par_cle[cle] for cle in cles_retournees if cle in faits_par_cle}
        )
        non_references = sorted(
            f"{type_evenement}:{identifiant}"
            for type_evenement, identifiant in cles_retournees
            if (type_evenement, identifiant) not in faits_par_cle
        )

        attendus = list(question["attendus"])
        faits_attendus = [faits[identifiant] for identifiant in attendus]
        sources_attendues = sorted({source for fait in faits_attendus for source in fait["sources"]})
        if disponible is None:
            # Inventaire absent : ni présence ni absence ne sont prouvées. On ne fabrique donc
            # aucune liste de sources présentes ou absentes.
            sources_presentes: list[str] = []
            sources_manquantes: list[dict[str, str]] = []
        else:
            sources_presentes = [source for source in sources_attendues if source in disponible]
            sources_manquantes = [
                {"question": question["id"], "fait": fait["id"], "source": source}
                for fait in faits_attendus
                for source in fait["sources"]
                if source not in disponible
            ]

        hors_domaine = [
            fait
            for fait in faits_attendus
            if any(documents[source]["domaine"] != "affaires" for source in fait["sources"])
        ]
        if not attendus:
            raison = RAISON_AUCUN_FAIT_ATTENDU
        elif hors_domaine:
            raison = RAISON_SOURCE_HORS_DOMAINE
        else:
            raison = None
        if raison is not None:
            non_evaluables.append({"question": question["id"], "raison": raison})
        evaluable = raison is None

        fuites_question: list[dict[str, str]] = []
        for fait_id in retournes_faits:
            fait = faits[fait_id]
            motif = None
            if any(documents[source]["domaine"] != "affaires" for source in fait["sources"]):
                motif = MOTIF_SOURCE_HORS_DOMAINE
            elif fait_id in question.get("interdits", []):
                motif = MOTIF_INTERDIT
            if motif is not None:
                fuites_question.append({"question": question["id"], "fait": fait_id, "motif": motif})
        fuites.extend(fuites_question)

        trouves = [identifiant for identifiant in attendus if identifiant in retournes_faits]
        absents = [identifiant for identifiant in attendus if identifiant not in retournes_faits]

        if evaluable:
            evaluables += 1
            attendus_total += len(attendus)
            trouves_total += len(trouves)
            retournes_total += len(cles_retournees)
            pertinents_total += len(trouves)
            sources_total += len(sources_attendues)
            sources_presentes_total += len(sources_presentes)
            # Les listes globales sont au grain des dénominateurs : seules les questions
            # évaluables y entrent. Une question non évaluable garde ses faits manquants et ses
            # sources absentes dans ``par_question``, avec sa raison.
            manquants.extend(
                {"question": question["id"], "fait": identifiant} for identifiant in absents
            )
            sources_absentes.extend(sources_manquantes)
            rappel = _mesure(
                len(trouves), len(attendus), non_evaluable=RAISON_AUCUN_FAIT_ATTENDU
            )
            precision = _mesure(
                len(trouves), len(cles_retournees), non_evaluable=RAISON_AUCUN_FAIT_RETOURNE
            )
            if disponible is None and sources_attendues:
                couverture_sources = {
                    "evaluable": False,
                    "raison": RAISON_AUCUN_INVENTAIRE_SOURCES,
                }
            else:
                couverture_sources = _mesure(
                    len(sources_presentes),
                    len(sources_attendues),
                    non_evaluable=RAISON_AUCUNE_SOURCE_ATTENDUE,
                )
        else:
            rappel = {"evaluable": False, "raison": raison}
            precision = {"evaluable": False, "raison": raison}
            couverture_sources = {"evaluable": False, "raison": raison}

        par_question.append(
            {
                "id": question["id"],
                "question": question["texte"],
                "affaire_id": question["affaire_id"],
                "types_evenement": list(question["types_evenement"]),
                "evaluable": evaluable,
                "raison": raison,
                "attendus": attendus,
                "trouves": trouves,
                "manquants": absents,
                "retournes": len(cles_retournees),
                "retournes_non_references": non_references,
                "sources": sources_attendues,
                "sources_presentes": sources_presentes,
                "sources_absentes": sources_manquantes,
                "fuites": fuites_question,
                "rappel": rappel,
                "precision": precision,
                "couverture_sources": couverture_sources,
            }
        )

    if evaluables == 0:
        # Aucune question évaluable : il n'y a pas de source attendue *évaluable* à couvrir. Dire
        # `AUCUNE_SOURCE_ATTENDUE` serait faux (des sources existent, mais hors du champ évalué)
        # et `AUCUN_INVENTAIRE_SOURCES` masquerait la raison première.
        couverture_sources_globale = {
            "evaluable": False,
            "raison": RAISON_AUCUN_FAIT_EVALUABLE,
        }
    elif disponible is None and sources_total:
        couverture_sources_globale = {
            "evaluable": False,
            "raison": RAISON_AUCUN_INVENTAIRE_SOURCES,
        }
    else:
        couverture_sources_globale = _mesure(
            sources_presentes_total,
            sources_total,
            non_evaluable=RAISON_AUCUNE_SOURCE_ATTENDUE,
        )

    rapport = {
        "schema": SCHEMA_BATTERIE,
        "version": valide["version"],
        "fictif": True,
        "empreinte_batterie": _empreinte(valide),
        "mode": "evenements_du_bus_v1",
        "mode_sources": mode_sources,
        "semantique_agregation": {
            "unite": "occurrence_par_question",
            "couverture_ensemble": False,
            "rappel": (
                "somme, par question évaluable, des faits attendus retrouvés / somme des faits "
                "attendus par question"
            ),
            "precision": (
                "somme, par question évaluable, des faits attendus retrouvés / somme des faits "
                "retournés par la portée de la question"
            ),
            "couverture_sources": (
                "somme, par question évaluable, des sources attendues uniques de la question et "
                "disponibles / somme des sources attendues uniques de la question"
            ),
            "doublons": (
                "un fait ou une source partagé par deux questions compte deux occurrences ; une "
                "même source absente peut apparaître plusieurs fois dans sources_absentes (grain "
                "question, fait, source)"
            ),
        },
        "nb_documents": len(valide["documents"]),
        "nb_faits": len(faits),
        "nb_questions": len(valide["questions"]),
        "nb_maillons_affaires": len(affaires),
        "nb_questions_evaluables": evaluables,
        "rappel": _mesure(trouves_total, attendus_total, non_evaluable=RAISON_AUCUN_FAIT_EVALUABLE),
        "precision": _mesure(pertinents_total, retournes_total, non_evaluable=RAISON_AUCUN_FAIT_RETOURNE),
        "couverture": _mesure(evaluables, len(valide["questions"]), non_evaluable="AUCUNE_QUESTION"),
        "couverture_sources": couverture_sources_globale,
        "non_evaluables": non_evaluables,
        "manquants": manquants,
        "sources_absentes": sources_absentes,
        "fuites": fuites,
        "par_question": par_question,
        "limites": [
            "batterie fictive écrite par un seul auteur : biais de rédaction non mesuré",
            "ne couvre que les faits d'événements du bus (amont, WCT, variance, rentabilité) : "
            "décisions, leçons et documents métier ne sont pas encore des faits attendus de cette batterie",
            "aucun modèle, aucun réseau, aucun service extérieur : la mesure est déterministe, pas une "
            "qualité de réponse d'un agent",
        ],
    }
    return rapport
