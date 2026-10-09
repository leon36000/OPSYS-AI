"""Documents internes par affaire : domaine pur, aucun outil ou stockage livré.

Les candidats sont scellés mais jamais ajoutés ici. Le contexte injecté représente
une forme et une corrélation, jamais une preuve d'autorité SQL ou DEVICE. Le retrait
ferme l'accès au texte ; les maillons et la copie APP future ne sont pas effacés.
"""

from __future__ import annotations

import hashlib
import json
import re

from . import affaire, encodage, humain
from .amont import AMONT_AFFAIRE_INCONNUE, AMONT_ORIGINE_NON_RECUE
from .registre import Registre

REGISTRE = "documents_affaire"
METHODE = "utf8-exact-v1"
MAX_POINTS = 2000
MAX_OCTETS = 8000
MAX_CITATION_OCTETS = 1024
MAX_DOCUMENTS = 8
MAX_VERSIONS = 8
MAX_MAILLONS = 512
OUTILS = {
    "deposer": "m10_deposer_version_document_appareil",
    "activer": "m10_activer_version_document_appareil",
    "retirer": "m10_retirer_document_appareil",
}
_TYPES = {
    "document_depose": "deposer",
    "document_version_deposee": "deposer",
    "document_version_activee": "activer",
    "document_retire": "retirer",
}
_BASE = {
    "version_schema",
    "type_entree",
    "affaire_id",
    "confidentialite",
    "auteur",
    "intention",
    "horodatage_appareil_declare",
    "horodatage",
}
_SOURCE = {"version_no", "titre", "corps", "methode", "source_sha256", "taille_points", "taille_octets"}
_CHAINE = {"ligne_id", "precedent_ligne_id"}
_SUPPLEMENTS = {
    "document_depose": _SOURCE,
    "document_version_deposee": _SOURCE | {"document_ref", "version_precedente"},
    "document_version_activee": {"document_ref", "version_source", "activation_attendue"},
    "document_retire": {"document_ref", "activation_attendue", "code_motif"},
}
_COMMANDES = {
    "deposer": {"affaire_id", "document_ref", "version_precedente", "titre", "corps", "confidentialite"},
    "activer": {"affaire_id", "document_ref", "version_source", "activation_attendue"},
    "retirer": {"affaire_id", "document_ref", "activation_attendue", "code_motif"},
}
_DETAILS = {
    "FORME-INVALIDE": "la forme documentaire est invalide",
    "SOURCE-INVALIDE": "la source documentaire est invalide",
    "REGISTRE-INVALIDE": "le registre documentaire est invalide",
    "AUTORITE-INVALIDE": "le contexte documentaire est inadmissible",
    "MODE-NON-ADMIS": "ce mode ne permet pas une mutation documentaire",
    "AFFAIRE-INCONNUE": "l'affaire documentaire n'est pas connue",
    "REFERENCE-INVALIDE": "la référence documentaire est invalide",
    "REVISION-PERIMEE": "la révision documentaire attendue est périmée",
    "RETIRE": "le document est retiré de l'accès",
    "CITATION-INVALIDE": "la citation documentaire est invalide",
    "BORNE-DEPASSEE": "une borne du pilote documentaire est dépassée",
    "QUOTA-DEPASSE": "la sortie documentaire dépasse le quota courant",
    "CONFIRMATION-INCONNUE": "la mutation documentaire ne peut pas être confirmée",
}
_HASH = re.compile(r"[0-9a-f]{64}")


class RefusDocument(ValueError):
    """Verdict fermé sans écho des arguments ou du texte source."""

    def __init__(self, suffixe):
        self.code = "REJ-M10-DOC-" + suffixe
        self.detail = _DETAILS[suffixe]
        super().__init__(self.code + " : " + self.detail)

    def verdict(self):
        return {"code": self.code, "detail": self.detail}


def _refuser(suffixe="FORME-INVALIDE"):
    raise RefusDocument(suffixe)


def _copie(valeur, profondeur=0):
    """JSON fermé, sans coercition ni accès aux propriétés d'objets arbitraires."""
    if profondeur > 12:
        _refuser()
    t = type(valeur)
    if t is str:
        try:
            valeur.encode("utf-8", "strict")
        except UnicodeError:
            _refuser()
        return valeur
    if t in (int, bool) or valeur is None:
        return valeur
    if t is list:
        return [_copie(x, profondeur + 1) for x in valeur]
    if t is dict:
        if any(type(k) is not str for k in valeur):
            _refuser()
        return {_copie(k, profondeur + 1): _copie(v, profondeur + 1) for k, v in valeur.items()}
    _refuser()


def _forme(objet, cles):
    if type(objet) is not dict or set(objet) != set(cles):
        _refuser()


def _texte(valeur, limite):
    if type(valeur) is not str or not valeur.strip() or len(valeur) > limite:
        _refuser()


def _entier(valeur, minimum, maximum):
    if type(valeur) is not int or not minimum <= valeur <= maximum:
        _refuser()


def _hash(valeur):
    if type(valeur) is not str or _HASH.fullmatch(valeur) is None:
        _refuser()


def _hora(valeur):
    if type(valeur) is not str or len(valeur) > 40 or not humain.horodatage_valide(valeur):
        _refuser()


def _auteur(objet):
    _forme(objet, {"personne", "role", "source"})
    if (
        any(type(v) is not str for v in objet.values())
        or (not humain.acteur_valide(objet["personne"], objet["role"], objet["source"]))
        or (objet["role"] != "admin" or objet["source"] != "appareil")
    ):
        _refuser("AUTORITE-INVALIDE")


def _intention(objet, operation=None):
    _forme(objet, {"appareil", "cle", "outil", "empreinte_arguments"})
    _texte(objet["appareil"], 256)
    _texte(objet["cle"], 256)
    _hash(objet["empreinte_arguments"])
    if objet["outil"] not in OUTILS.values() or (operation is not None and objet["outil"] != OUTILS[operation]):
        _refuser()


def _situation(objet):
    _forme(objet, {"connue", "origine_recue", "origine", "verdict"})
    if type(objet["connue"]) is not bool or type(objet["origine_recue"]) is not bool:
        _refuser()
    if objet["origine"] not in (None, "m1.lead_qualifie", "m2.client_associe") or (
        objet["verdict"] not in (None, AMONT_AFFAIRE_INCONNUE, AMONT_ORIGINE_NON_RECUE)
    ):
        _refuser()
    if objet["origine_recue"] != (objet["origine"] is not None):
        _refuser()
    attendu = (
        AMONT_AFFAIRE_INCONNUE if not objet["connue"] else None if objet["origine_recue"] else AMONT_ORIGINE_NON_RECUE
    )
    if objet["verdict"] != attendu or (not objet["connue"] and objet["origine_recue"]):
        _refuser()


def _contexte(contexte, cible, operation=None, *, lecture=False):
    c = _copie(contexte)
    cles = {"affaire_id", "auteur", "situation", "mode", "quota"}
    if not lecture:
        cles |= {"intention", "horodatage_appareil_declare", "horodatage"}
    _forme(c, cles)
    if type(cible) is not str or not affaire.valide(cible) or c["affaire_id"] != cible:
        _refuser("AUTORITE-INVALIDE")
    _auteur(c["auteur"])
    if not lecture:
        _intention(c["intention"], operation)
        _hora(c["horodatage_appareil_declare"])
        _hora(c["horodatage"])
    _situation(c["situation"])
    if not c["situation"]["connue"]:
        _refuser("AFFAIRE-INCONNUE")
    if c["mode"] not in ("ombre", "supervise", "autonome") or (not lecture and c["mode"] != "ombre"):
        _refuser("MODE-NON-ADMIS")
    if type(c["quota"]) is not int or c["quota"] < 1:
        _refuser()
    return c


def _reference(maillons, index):
    return {"registre": REGISTRE, "index": index, "ligne_id": maillons[index]["ligne_id"]}


def _index(maillons, ref):
    _forme(ref, {"registre", "index", "ligne_id"})
    _entier(ref["index"], 0, MAX_MAILLONS - 1)
    _hash(ref["ligne_id"])
    index = ref["index"]
    if ref["registre"] != REGISTRE or index >= len(maillons):
        _refuser("REFERENCE-INVALIDE")
    cible = maillons[index]
    if type(cible) is not dict or cible.get("ligne_id") != ref["ligne_id"]:
        _refuser("REFERENCE-INVALIDE")
    return index


def _egal(a, b):
    if type(a) is not type(b):
        return False
    if type(a) is dict:
        return set(a) == set(b) and all(_egal(a[k], b[k]) for k in a)
    if type(a) is list:
        return len(a) == len(b) and all(_egal(x, y) for x, y in zip(a, b, strict=True))
    return a == b


def _source(m):
    _texte(m["titre"], 120)
    corps = m["corps"]
    if type(corps) is not str or not 0 < len(corps) <= MAX_POINTS:
        _refuser("BORNE-DEPASSEE")
    raw = corps.encode("utf-8", "strict")
    if len(raw) > MAX_OCTETS:
        _refuser("BORNE-DEPASSEE")
    _entier(m["taille_points"], 1, MAX_POINTS)
    _entier(m["taille_octets"], 1, MAX_OCTETS)
    _entier(m["version_no"], 1, MAX_VERSIONS)
    _hash(m["source_sha256"])
    if (
        m["methode"] != METHODE
        or m["taille_points"] != len(corps)
        or (m["taille_octets"] != len(raw) or m["source_sha256"] != hashlib.sha256(raw).hexdigest())
    ):
        _refuser("SOURCE-INVALIDE")


def _empreinte_arguments(arguments):
    try:
        canonique = json.dumps(arguments, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        octets = canonique.encode("utf-8")
    except (ValueError, TypeError, RecursionError):
        _refuser()
    return hashlib.sha256(octets).hexdigest()


def _arguments_du_maillon(m):
    genre = m["type_entree"]
    if genre in ("document_depose", "document_version_deposee"):
        return {
            "affaire_id": m["affaire_id"],
            "document_ref": None if genre == "document_depose" else m["document_ref"],
            "version_precedente": None if genre == "document_depose" else m["version_precedente"],
            "titre": m["titre"],
            "corps": m["corps"],
            "confidentialite": m["confidentialite"],
        }
    return {k: m[k] for k in _COMMANDES[_TYPES[genre]]}


def _analyse(maillons):
    chain = _copie(maillons)
    if type(chain) is not list:
        _refuser("REGISTRE-INVALIDE")
    if len(chain) > MAX_MAILLONS:
        _refuser("BORNE-DEPASSEE")
    docs, intentions, nombres = {}, set(), {}
    for i, m in enumerate(chain):
        if type(m) is not dict or type(m.get("type_entree")) is not str or m["type_entree"] not in _TYPES:
            _refuser("REGISTRE-INVALIDE")
        genre = m["type_entree"]
        _forme(m, _BASE | _SUPPLEMENTS[genre] | _CHAINE)
        if (
            type(m["version_schema"]) is not int
            or m["version_schema"] != 1
            or (m["confidentialite"] != "INTERNAL" or not affaire.valide(m["affaire_id"]))
        ):
            _refuser("REGISTRE-INVALIDE")
        _auteur(m["auteur"])
        _intention(m["intention"], _TYPES[genre])
        if _empreinte_arguments(_arguments_du_maillon(m)) != m["intention"]["empreinte_arguments"]:
            _refuser("REGISTRE-INVALIDE")
        _hora(m["horodatage_appareil_declare"])
        _hora(m["horodatage"])
        _hash(m["ligne_id"])
        if m["precedent_ligne_id"] is not None:
            _hash(m["precedent_ligne_id"])
        pair = (m["intention"]["appareil"], m["intention"]["cle"])
        if pair in intentions:
            _refuser("REGISTRE-INVALIDE")
        intentions.add(pair)
        if genre == "document_depose":
            _source(m)
            if m["version_no"] != 1:
                _refuser("REGISTRE-INVALIDE")
            nombres[m["affaire_id"]] = nombres.get(m["affaire_id"], 0) + 1
            if nombres[m["affaire_id"]] > MAX_DOCUMENTS:
                _refuser("BORNE-DEPASSEE")
            docs[i] = {"versions": [i], "activations": [], "retire": False}
            continue
        root = _index(chain, m["document_ref"])
        if root not in docs or m["affaire_id"] != chain[root]["affaire_id"] or docs[root]["retire"]:
            _refuser("REGISTRE-INVALIDE")
        doc = docs[root]
        if genre == "document_version_deposee":
            _source(m)
            if m["version_no"] != len(doc["versions"]) + 1 or (
                _index(chain, m["version_precedente"]) != doc["versions"][-1]
            ):
                _refuser("REGISTRE-INVALIDE")
            doc["versions"].append(i)
        else:
            attendu = _reference(chain, doc["activations"][-1]) if doc["activations"] else None
            if not _egal(m["activation_attendue"], attendu):
                _refuser("REGISTRE-INVALIDE")
            if genre == "document_version_activee":
                if _index(chain, m["version_source"]) not in doc["versions"]:
                    _refuser("REGISTRE-INVALIDE")
                doc["activations"].append(i)
            else:
                if m["code_motif"] != "RETRAIT_ACCES":
                    _refuser("REGISTRE-INVALIDE")
                doc["retire"] = True
    if not Registre(chain).valider_chaine()[0]:
        _refuser("REGISTRE-INVALIDE")
    return chain, docs


def valider_snapshot(maillons: list[dict]) -> None:
    """Valide la chaîne et les liens sans toucher à l'enum générique ou aux entrées."""
    _analyse(maillons)


def borner_enveloppe(frame: dict, quota: int) -> None:
    """Mesure exacte en caractères, sans repli ARTEFACT ou omission."""
    if type(quota) is not int or quota < 1 or type(frame) is not dict:
        _refuser()
    copie = _copie(frame)
    try:
        taille = len(json.dumps(copie, ensure_ascii=False, allow_nan=False))
    except (ValueError, TypeError, RecursionError):
        _refuser()
    if taille > quota:
        _refuser("QUOTA-DEPASSE")


def _ack(chain, index):
    m = chain[index]
    genre = m["type_entree"]
    doc = _reference(chain, index) if genre == "document_depose" else m["document_ref"]
    source = (
        _reference(chain, index)
        if genre in ("document_depose", "document_version_deposee")
        else m["version_source"]
        if genre == "document_version_activee"
        else None
    )
    sha = chain[_index(chain, source)]["source_sha256"] if source is not None else None
    return _copie(
        {
            "version_schema": 1,
            "operation": _TYPES[genre],
            "document_ref": doc,
            "reference": _reference(chain, index),
            "version_source": source,
            "source_sha256": sha,
            "auteur": m["auteur"],
            "intention": m["intention"],
            "horodatage_appareil_declare": m["horodatage_appareil_declare"],
            "horodatage": m["horodatage"],
        }
    )


def accuse_propre(maillons: list[dict], reference: dict) -> dict:
    """Projection pure historique ; l'adaptateur futur doit établir l'autorité actuelle."""
    chain, _ = _analyse(maillons)
    return _ack(chain, _index(chain, _copie(reference)))


def _borner_ack(ack, quota):
    for flag in (False, True):
        borner_enveloppe({"ok": True, "resultat": {"accepte": True, "resultat": ack}, "rejoue": flag}, quota)


def _debut(maillons, commande, contexte, operation):
    args = _copie(commande)
    _forme(args, _COMMANDES[operation])
    c = _contexte(contexte, args["affaire_id"], operation)
    if _empreinte_arguments(args) != c["intention"]["empreinte_arguments"]:
        _refuser()
    chain, docs = _analyse(maillons)
    if any(
        (m["intention"]["appareil"], m["intention"]["cle"]) == (c["intention"]["appareil"], c["intention"]["cle"])
        for m in chain
    ):
        _refuser("CONFIRMATION-INCONNUE")
    if len(chain) >= MAX_MAILLONS:
        _refuser("BORNE-DEPASSEE")
    return chain, docs, args, c


def _header(c, genre):
    return {
        "version_schema": 1,
        "type_entree": genre,
        "affaire_id": c["affaire_id"],
        "confidentialite": "INTERNAL",
        "auteur": c["auteur"],
        "intention": c["intention"],
        "horodatage_appareil_declare": c["horodatage_appareil_declare"],
        "horodatage": c["horodatage"],
    }


def _sceller(chain, payload, quota):
    precedent = chain[-1]["ligne_id"] if chain else None
    candidat = {**payload, "ligne_id": encodage.empreinte(payload, precedent), "precedent_ligne_id": precedent}
    suite, _ = _analyse(chain + [candidat])
    _borner_ack(_ack(suite, len(chain)), quota)
    return _copie(candidat)


def _document(chain, docs, ref, cible):
    root = _index(chain, ref)
    if root not in docs or chain[root]["affaire_id"] != cible:
        _refuser("REFERENCE-INVALIDE")
    return root, docs[root]


def preparer_depot(maillons: list[dict], commande: dict, contexte: dict) -> dict:
    chain, docs, args, c = _debut(maillons, commande, contexte, "deposer")
    if args["confidentialite"] != "INTERNAL":
        _refuser()
    if args["document_ref"] is None:
        if args["version_precedente"] is not None:
            _refuser()
        if sum(chain[i]["affaire_id"] == args["affaire_id"] for i in docs) >= MAX_DOCUMENTS:
            _refuser("BORNE-DEPASSEE")
        payload = _header(c, "document_depose")
        version = 1
    else:
        _, doc = _document(chain, docs, args["document_ref"], args["affaire_id"])
        if doc["retire"]:
            _refuser("RETIRE")
        if len(doc["versions"]) >= MAX_VERSIONS:
            _refuser("BORNE-DEPASSEE")
        if not _egal(args["version_precedente"], _reference(chain, doc["versions"][-1])):
            _refuser("REVISION-PERIMEE")
        payload = {
            **_header(c, "document_version_deposee"),
            "document_ref": args["document_ref"],
            "version_precedente": args["version_precedente"],
        }
        version = len(doc["versions"]) + 1
    raw = args["corps"].encode("utf-8", "strict") if type(args["corps"]) is str else b""
    payload.update(
        version_no=version,
        titre=args["titre"],
        corps=args["corps"],
        methode=METHODE,
        source_sha256=hashlib.sha256(raw).hexdigest(),
        taille_points=len(args["corps"]) if type(args["corps"]) is str else 0,
        taille_octets=len(raw),
    )
    _source(payload)
    return _sceller(chain, payload, c["quota"])


def _preparer_etat(maillons, commande, contexte, operation):
    chain, docs, args, c = _debut(maillons, commande, contexte, operation)
    _, doc = _document(chain, docs, args["document_ref"], args["affaire_id"])
    if doc["retire"]:
        _refuser("RETIRE")
    attendu = _reference(chain, doc["activations"][-1]) if doc["activations"] else None
    if not _egal(args["activation_attendue"], attendu):
        _refuser("REVISION-PERIMEE")
    if operation == "activer":
        if _index(chain, args["version_source"]) not in doc["versions"]:
            _refuser("REFERENCE-INVALIDE")
        genre = "document_version_activee"
    else:
        if args["code_motif"] != "RETRAIT_ACCES":
            _refuser()
        genre = "document_retire"
    payload = {**_header(c, genre), **{k: v for k, v in args.items() if k != "affaire_id"}}
    return _sceller(chain, payload, c["quota"])


def preparer_activation(maillons: list[dict], commande: dict, contexte: dict) -> dict:
    return _preparer_etat(maillons, commande, contexte, "activer")


def preparer_retrait(maillons: list[dict], commande: dict, contexte: dict) -> dict:
    return _preparer_etat(maillons, commande, contexte, "retirer")


def lire_version(
    maillons: list[dict], affaire_id: str, document_ref: dict, version_source: dict, contexte: dict
) -> dict:
    c = _contexte(contexte, affaire_id, lecture=True)
    chain, docs = _analyse(maillons)
    root, doc = _document(chain, docs, _copie(document_ref), affaire_id)
    index = _index(chain, _copie(version_source))
    if index not in doc["versions"]:
        _refuser("REFERENCE-INVALIDE")
    m = chain[index]
    actives = [i for i in doc["activations"] if _index(chain, chain[i]["version_source"]) == index]
    activation = _reference(chain, actives[-1]) if actives else None
    if doc["retire"]:
        statut = "RETIREE"
    elif not actives:
        statut = "DEPOSEE_NON_ACTIVEE"
    elif doc["activations"][-1] == actives[-1]:
        statut = "COURANTE"
    else:
        statut = "HISTORIQUE_NON_COURANTE"
    dto = {
        "version_schema": 1,
        "affaire_id": affaire_id,
        "document_ref": _reference(chain, root),
        "version_source": _reference(chain, index),
        "statut": statut,
        "titre": m["titre"],
        "methode": METHODE,
        "source_sha256": m["source_sha256"],
        "taille_points": m["taille_points"],
        "taille_octets": m["taille_octets"],
        "auteur": m["auteur"],
        "horodatage": m["horodatage"],
        "activation_ref": activation,
    }
    if not doc["retire"]:
        dto["corps"] = m["corps"]
    borner_enveloppe({"ok": True, "resultat": {"accepte": True, "resultat": dto}}, c["quota"])
    return _copie(dto)


def verifier_citation(maillons: list[dict], citation: dict, contexte: dict) -> dict:
    cite = _copie(citation)
    _forme(
        cite,
        {
            "version_schema",
            "affaire_id",
            "document_ref",
            "version_source",
            "activation_ref",
            "source_sha256",
            "methode",
            "debut_octet",
            "fin_octet",
            "extrait",
        },
    )
    c = _contexte(contexte, cite["affaire_id"], lecture=True)
    chain, docs = _analyse(maillons)
    _, doc = _document(chain, docs, cite["document_ref"], cite["affaire_id"])
    if doc["retire"]:
        _refuser("RETIRE")
    index = _index(chain, cite["version_source"])
    activation = _index(chain, cite["activation_ref"])
    if (
        index not in doc["versions"]
        or activation not in doc["activations"]
        or (_index(chain, chain[activation]["version_source"]) != index)
    ):
        _refuser("CITATION-INVALIDE")
    m = chain[index]
    raw = m["corps"].encode("utf-8")
    if (
        type(cite["version_schema"]) is not int
        or cite["version_schema"] != 1
        or (cite["methode"] != METHODE or cite["source_sha256"] != m["source_sha256"])
    ):
        _refuser("CITATION-INVALIDE")
    start, end = cite["debut_octet"], cite["fin_octet"]
    if (
        type(start) is not int
        or type(end) is not int
        or not 0 <= start < end <= len(raw)
        or (end - start > MAX_CITATION_OCTETS)
    ):
        _refuser("CITATION-INVALIDE")
    try:
        extrait = raw[start:end].decode("utf-8", "strict")
    except UnicodeError:
        _refuser("CITATION-INVALIDE")
    if type(cite["extrait"]) is not str or cite["extrait"] != extrait:
        _refuser("CITATION-INVALIDE")
    borner_enveloppe({"ok": True, "resultat": {"accepte": True, "resultat": cite}}, c["quota"])
    return cite


def verifier_rejeu(maillons: list[dict], claim: dict, contexte: dict) -> dict:
    c = _contexte(contexte, contexte.get("affaire_id") if type(contexte) is dict else None)
    try:
        chain, _ = _analyse(maillons)
        row = _copie(claim)
        _forme(row, {"appareil", "cle", "outil", "empreinte_arguments", "horodatage_appareil", "statut", "reponse"})
        intention = c["intention"]
        if (
            row["statut"] != "ok"
            or any(row[k] != intention[k] for k in ("appareil", "cle", "outil", "empreinte_arguments"))
            or row["horodatage_appareil"] != c["horodatage_appareil_declare"]
        ):
            _refuser()
        owns = [
            i
            for i, m in enumerate(chain)
            if _egal(m["intention"], intention)
            and _egal(m["auteur"], c["auteur"])
            and m["affaire_id"] == c["affaire_id"]
            and m["horodatage_appareil_declare"] == c["horodatage_appareil_declare"]
        ]
        if len(owns) != 1:
            _refuser()
        ack = _ack(chain, owns[0])
        if not _egal(row["reponse"], {"ok": True, "resultat": {"accepte": True, "resultat": ack}}):
            _refuser()
    except RefusDocument:
        _refuser("CONFIRMATION-INCONNUE")
    _borner_ack(ack, c["quota"])
    return ack
