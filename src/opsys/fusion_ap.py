"""Brouillons AP chiffrés, liés à un extrait PDF et sans écriture M5."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import func, insert, select, update

from . import etat, fusion_csv, fusion_pdf, fusion_pdf_ocr
from .stockage.schema import (
    FUSION_AP_BROUILLONS,
    FUSION_AP_COMMANDES,
    FUSION_AP_OCR_SOURCES,
    FUSION_PDF_OCR_RUNS,
    FUSION_PDF_QUOTA,
)

FusionAPErreur = fusion_pdf.FusionPDFErreur
MAX_COMMANDES_PAR_LOT = 128
PROPOSITION_MAX = 8_192
PROPOSITION_CIPHER_MAX = PROPOSITION_MAX + 16
_CHAMPS = frozenset(
    {
        "fournisseur",
        "numero",
        "date",
        "po",
        "sous_total_imprime",
        "taxe_imprimee",
        "total_imprime",
        "devise",
    }
)
_MUTATION = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")
_AAD_PREFIX = "opsys-fusion-ap-brouillon"


def _erreur(code: str, status: int = 409) -> FusionAPErreur:
    return fusion_pdf._erreur(code, status)


def _json(valeur: Any) -> str:
    return json.dumps(valeur, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _vue(brouillon: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source_type": brouillon["source_type"],
        "lot_id": brouillon["lot_id"],
        "source_sha256": brouillon["source_sha256"],
        "configuration_sha256": brouillon["configuration_sha256"],
        "extracteur": brouillon["extracteur"],
        "revision_pdf": brouillon["revision_pdf"],
        "revision": brouillon["revision"],
        "statut": brouillon["statut"],
        "auteur": brouillon["auteur"],
        "modifie_par": brouillon["modifie_par"],
        "cree_le": brouillon["cree_le"],
        "modifie_le": brouillon["modifie_le"],
        "ocr_run_id": brouillon.get("ocr_run_id"),
        "revision_run": brouillon.get("revision_run"),
    }


def _source_ocr_courante(cnx, lot: Mapping[str, Any], ocr_run_id: str, revision_run: int) -> tuple[dict, dict]:
    try:
        run, candidat = fusion_pdf_ocr.lire_resultat_dans_transaction(cnx, ocr_run_id)
    except fusion_pdf.FusionPDFErreur as exc:
        raise _erreur(exc.code, exc.statut_http) from exc
    if (
        run["pdf_lot_id"] != lot["lot_id"]
        or run["source_sha256"] != lot["source_sha256"]
        or run["revision_pdf_source"] != lot["revision"]
        or run["revision_run"] != revision_run
        or run["profil_id"] != "ocr-scan-2"
        or run["configuration_sha256"] != fusion_pdf_ocr.CONFIGURATION_SHA256
        or lot["statut"] != "REFUSE"
        or lot["code"] != "PDF_IMAGE_OU_MIXTE"
    ):
        raise _erreur("SOURCE_OCR_OBSOLETE")
    return {
        "source_type": "OCR_CANDIDAT",
        "ocr_run_id": run["ocr_run_id"],
        "revision_run": run["revision_run"],
        "ocr_configuration_sha256": run["configuration_sha256"],
        "ocr_profil_id": run["profil_id"],
    }, candidat


def _source_ocr_enregistree(cnx, lot: Mapping[str, Any]) -> tuple[dict, dict] | None:
    row = cnx.execute(select(FUSION_AP_OCR_SOURCES).where(
        FUSION_AP_OCR_SOURCES.c.lot_id == lot["lot_id"],
    )).mappings().one_or_none()
    if row is None:
        return None
    source = dict(row)
    if source["source_type"] != "OCR_CANDIDAT":
        raise _erreur("SOURCE_AP_INVALIDE", 503)
    courant, candidat = _source_ocr_courante(cnx, lot, source["ocr_run_id"], source["revision_run"])
    if any(source.get(cle) != courant[cle] for cle in (
        "source_type", "ocr_run_id", "revision_run", "ocr_configuration_sha256", "ocr_profil_id",
    )):
        raise _erreur("SOURCE_OCR_OBSOLETE")
    return courant, candidat


def _verifier_pdf(cnx, lot_id: str, revision_attendue: int) -> tuple[dict[str, Any], dict[str, Any]]:
    lot = fusion_pdf._lot(cnx, lot_id)
    fusion_pdf._compatible(lot)
    if type(revision_attendue) is not int or revision_attendue < 1:
        raise _erreur("REVISION_PDF_INVALIDE", 400)
    if lot["revision"] != revision_attendue:
        raise _erreur("CONFLIT_REVISION_PDF")
    if lot["statut"] != "EXTRAIT_PREPARATOIRE":
        raise _erreur("PDF_RESULTAT_INDISPONIBLE")
    return lot, fusion_pdf._resultat(lot)


def _valider_proposition(proposition: Any, resultat: Mapping[str, Any]) -> dict[str, Any]:
    if (
        type(proposition) is not dict
        or len(proposition) != 3
        or set(proposition)
        != {
            "schema_version",
            "champs",
            "citations",
        }
    ):
        raise _erreur("PROPOSITION_INVALIDE", 400)
    if type(proposition["schema_version"]) is not int or proposition["schema_version"] != 1:
        raise _erreur("PROPOSITION_INVALIDE", 400)
    champs, citations = proposition["champs"], proposition["citations"]
    if (
        type(champs) is not dict
        or len(champs) != len(_CHAMPS)
        or set(champs) != _CHAMPS
        or type(citations) is not dict
        or len(citations) > len(_CHAMPS)
    ):
        raise _erreur("PROPOSITION_INVALIDE", 400)

    champs_valides: dict[str, str] = {}
    for cle, valeur in champs.items():
        if not isinstance(cle, str) or not isinstance(valeur, str):
            raise _erreur("PROPOSITION_INVALIDE", 400)
        if len(valeur) > 128:
            raise _erreur("PROPOSITION_INVALIDE", 400)
        try:
            taille = len(valeur.encode("utf-8", errors="strict"))
        except UnicodeEncodeError as exc:
            raise _erreur("PROPOSITION_INVALIDE", 400) from exc
        if taille > 128 or any(ord(caractere) < 32 or ord(caractere) == 127 for caractere in valeur):
            raise _erreur("PROPOSITION_INVALIDE", 400)
        champs_valides[cle] = valeur
    if not any(champs_valides.values()) or len(citations) != sum(bool(valeur) for valeur in champs_valides.values()):
        raise _erreur("CITATION_INVALIDE", 400)
    if set(citations) != {cle for cle, valeur in champs_valides.items() if valeur}:
        raise _erreur("CITATION_INVALIDE", 400)

    pages = {page["numero"]: page for page in resultat["pages"]}
    citations_valides: dict[str, list[dict[str, Any]]] = {}
    for cle, references in citations.items():
        if (
            not isinstance(cle, str)
            or cle not in _CHAMPS
            or type(references) is not list
            or not 1 <= len(references) <= 3
        ):
            raise _erreur("CITATION_INVALIDE", 400)
        uniques: set[tuple[int, str]] = set()
        cibles: list[dict[str, Any]] = []
        for reference in references:
            if (
                type(reference) is not dict
                or len(reference) != 3
                or set(reference)
                != {
                    "page",
                    "fragment_id",
                    "fragment_sha256",
                }
            ):
                raise _erreur("CITATION_INVALIDE", 400)
            numero, fragment_id, empreinte = (reference["page"], reference["fragment_id"], reference["fragment_sha256"])
            if (
                type(numero) is not int
                or numero not in pages
                or not isinstance(fragment_id, str)
                or len(fragment_id) > 16
                or not isinstance(empreinte, str)
                or len(empreinte) != 64
                or not _SHA256.fullmatch(empreinte)
            ):
                raise _erreur("CITATION_INVALIDE", 400)
            fragment = next((f for f in pages[numero]["fragments"] if f["id"] == fragment_id), None)
            if fragment is None or fragment["sha256"] != empreinte or (numero, fragment_id) in uniques:
                raise _erreur("CITATION_INVALIDE", 400)
            uniques.add((numero, fragment_id))
            cibles.append({"page": numero, "fragment_id": fragment_id, "fragment_sha256": empreinte})
        citations_valides[cle] = cibles

    sortie = {"schema_version": 1, "champs": champs_valides, "citations": citations_valides}
    if len(_json(sortie).encode("utf-8")) > PROPOSITION_MAX:
        raise _erreur("PROPOSITION_TROP_GRANDE", 413)
    return sortie


def _empreinte_token(token: Mapping[str, Any]) -> str:
    return hashlib.sha256(_json(dict(token)).encode("utf-8", "strict")).hexdigest()


def _valider_proposition_ocr(
    proposition: Any, candidat: Mapping[str, Any], *, permettre_vide: bool = False,
) -> dict[str, Any]:
    """Valide les seules citations tokenisées du run OCR courant; les valeurs restent humaines."""
    if (
        type(proposition) is not dict or len(proposition) != 3
        or set(proposition) != {"schema_version", "champs", "citations"}
        or type(proposition["schema_version"]) is not int or proposition["schema_version"] != 1
    ):
        raise _erreur("PROPOSITION_INVALIDE", 400)
    champs, citations = proposition["champs"], proposition["citations"]
    if type(champs) is not dict or set(champs) != _CHAMPS or type(citations) is not dict:
        raise _erreur("PROPOSITION_INVALIDE", 400)
    champs_valides: dict[str, str] = {}
    for cle, valeur in champs.items():
        if not isinstance(valeur, str) or len(valeur) > 128:
            raise _erreur("PROPOSITION_INVALIDE", 400)
        try:
            taille = len(valeur.encode("utf-8", "strict"))
        except UnicodeEncodeError as exc:
            raise _erreur("PROPOSITION_INVALIDE", 400) from exc
        if taille > 128 or any(ord(caractere) < 32 or ord(caractere) == 127 for caractere in valeur):
            raise _erreur("PROPOSITION_INVALIDE", 400)
        champs_valides[cle] = valeur
    presentes = {cle for cle, valeur in champs_valides.items() if valeur}
    if not presentes and not permettre_vide:
        raise _erreur("CITATION_INVALIDE", 400)
    if set(citations) != presentes:
        raise _erreur("CITATION_INVALIDE", 400)
    page = candidat.get("page")
    tokens = page.get("tokens") if isinstance(page, Mapping) and page.get("numero") == 1 else None
    if not isinstance(tokens, list) or not tokens:
        raise _erreur("SOURCE_OCR_INVALIDE", 503)
    citations_valides: dict[str, list[dict[str, Any]]] = {}
    for cle, references in citations.items():
        if cle not in _CHAMPS or not isinstance(references, list) or not 1 <= len(references) <= 3:
            raise _erreur("CITATION_INVALIDE", 400)
        uniques: set[int] = set()
        cibles: list[dict[str, Any]] = []
        for reference in references:
            if (
                type(reference) is not dict or len(reference) != 3
                or set(reference) != {"page", "token_index", "token_sha256"}
            ):
                raise _erreur("CITATION_INVALIDE", 400)
            numero, index, empreinte = reference["page"], reference["token_index"], reference["token_sha256"]
            if (
                type(numero) is not int or numero != 1
                or type(index) is not int or not 0 <= index < len(tokens)
                or not isinstance(empreinte, str) or _SHA256.fullmatch(empreinte) is None
                or empreinte != _empreinte_token(tokens[index]) or index in uniques
            ):
                raise _erreur("CITATION_INVALIDE", 400)
            uniques.add(index)
            cibles.append({"page": 1, "token_index": index, "token_sha256": empreinte})
        citations_valides[cle] = cibles
    sortie = {"schema_version": 1, "champs": champs_valides, "citations": citations_valides}
    if len(_json(sortie).encode("utf-8")) > PROPOSITION_MAX:
        raise _erreur("PROPOSITION_TROP_GRANDE", 413)
    return sortie


def _aad(brouillon: Mapping[str, Any]) -> bytes:
    if brouillon["version_format"] != 1:
        raise _erreur("FORMAT_NON_SUPPORTE")
    valeurs = (
        _AAD_PREFIX,
        "v1",
        brouillon["lot_id"],
        brouillon["source_sha256"],
        brouillon["configuration_sha256"],
        str(brouillon["revision_pdf"]),
        str(brouillon["revision"]),
    )
    if brouillon.get("source_type", "PDF_NATIF") == "OCR_CANDIDAT":
        valeurs += (
            "OCR_CANDIDAT", brouillon["ocr_run_id"], str(brouillon["revision_run"]),
            brouillon["ocr_configuration_sha256"], brouillon["ocr_profil_id"],
        )
    try:
        return ":".join(valeurs).encode("ascii")
    except (UnicodeEncodeError, TypeError) as exc:
        raise _erreur("PROPOSITION_INVALIDE") from exc


def _chiffrer(brouillon: Mapping[str, Any], clair: bytes, cle: bytes) -> tuple[str, str, int]:
    import secrets

    nonce = secrets.token_bytes(12)
    chiffre = fusion_csv._aesgcm()(cle).encrypt(nonce, clair, _aad(brouillon))
    return base64.b64encode(nonce).decode("ascii"), base64.b64encode(chiffre).decode("ascii"), len(chiffre)


def _dechiffrer(brouillon: Mapping[str, Any]) -> dict[str, Any]:
    octets, nonce, chiffre = (
        brouillon["proposition_cipher_octets"],
        brouillon["proposition_nonce"],
        brouillon["proposition_cipher"],
    )
    if (
        type(octets) is not int
        or not 16 < octets <= PROPOSITION_CIPHER_MAX
        or not isinstance(chiffre, str)
        or len(chiffre) != 4 * ((octets + 2) // 3)
        or not isinstance(nonce, str)
        or len(nonce) != 16
    ):
        raise _erreur("CIPHER_INVALIDE")
    try:
        aesgcm = fusion_csv._aesgcm()
        from cryptography.exceptions import InvalidTag
    except fusion_csv.FusionErreur:
        raise
    except ImportError as exc:
        raise _erreur("CHIFFREMENT_INDISPONIBLE", 503) from exc
    try:
        clair = aesgcm(fusion_csv._cle(brouillon["cle_reference"])).decrypt(
            base64.b64decode(nonce, validate=True),
            base64.b64decode(chiffre, validate=True),
            _aad(brouillon),
        )
    except (InvalidTag, ValueError, TypeError) as exc:
        raise _erreur("CIPHER_INVALIDE") from exc
    if len(clair) + 16 != octets:
        raise _erreur("CIPHER_INVALIDE")

    def object_pairs(paires):
        objet = {}
        for cle, valeur in paires:
            if cle in objet:
                raise ValueError("clé JSON dupliquée")
            objet[cle] = valeur
        return objet

    try:
        payload = json.loads(clair, object_pairs_hook=object_pairs)
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        raise _erreur("CIPHER_INVALIDE") from exc
    # Les références sont aussi revalidées à la lecture privée contre l'extrait courant.
    return payload


def _lire_brouillon(
    cnx,
    lot: Mapping[str, Any],
    resultat: Mapping[str, Any] | None = None,
    *,
    dechiffrer_ocr: bool = False,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    row = (
        cnx.execute(select(FUSION_AP_BROUILLONS).where(FUSION_AP_BROUILLONS.c.lot_id == lot["lot_id"]))
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise _erreur("BROUILLON_INCONNU", 404)
    brouillon = dict(row)
    if (
        brouillon["source_sha256"] != lot["source_sha256"]
        or brouillon["configuration_sha256"] != lot["configuration_sha256"]
        or brouillon["extracteur"] != lot["extracteur"]
        or brouillon["revision_pdf"] != lot["revision"]
        or brouillon["statut"] != "A_REVOIR"
    ):
        raise _erreur("BROUILLON_OBSOLETE")
    if brouillon["version_format"] != 1:
        raise _erreur("FORMAT_NON_SUPPORTE")
    proposition = None
    source_ocr = _source_ocr_enregistree(cnx, lot)
    if source_ocr is not None:
        if resultat is not None:
            raise _erreur("SOURCE_AP_INVALIDE", 503)
        source, candidat = source_ocr
        brouillon.update(source)
        if dechiffrer_ocr:
            proposition = _valider_proposition_ocr(_dechiffrer(brouillon), candidat, permettre_vide=True)
    elif resultat is not None:
        brouillon["source_type"] = "PDF_NATIF"
        proposition = _valider_proposition(_dechiffrer(brouillon), resultat)
    else:
        brouillon["source_type"] = "PDF_NATIF"
    return brouillon, proposition


def lire(fabrique: fusion_pdf.FabriqueConnexion, acteur: str, lot_id: str) -> dict[str, Any]:
    """Métadonnées privées, sans déchiffrer ni rendre les champs AP."""
    with fusion_pdf._transaction(fabrique, acteur) as cnx:
        lot = fusion_pdf._lot(cnx, lot_id)
        fusion_pdf._compatible(lot)
        brouillon, _ = _lire_brouillon(cnx, lot)
        return _vue(brouillon)


def _date_liste_ap(value: Any) -> bool:
    if not isinstance(value, str) or not 1 <= len(value) <= 64:
        return False
    try:
        from datetime import datetime

        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _projection_liste_ap(row: Mapping[str, Any]) -> dict[str, Any]:
    lot_id = row.get("ap_lot_id")
    try:
        uuid_valide = isinstance(lot_id, str) and str(uuid.UUID(lot_id)) == lot_id
    except (TypeError, ValueError):
        uuid_valide = False

    revision = row.get("ap_revision")
    revision_pdf = row.get("pdf_revision")
    etat = "INDISPONIBLE"
    ocr_run_id = row.get("ocr_run_id")
    revision_run = row.get("ocr_source_revision_run")
    ocr_link = (
        row.get("ap_ocr_lot_id") == lot_id
        and row.get("ap_ocr_source_type") == "OCR_CANDIDAT"
        and isinstance(ocr_run_id, str)
        and _UUID.fullmatch(ocr_run_id) is not None
        and type(revision_run) is int and revision_run > 0
    )
    ocr_courant = (
        ocr_link
        and uuid_valide
        and row.get("pdf_lot_id") == lot_id
        and row.get("ap_statut") == "A_REVOIR"
        and type(row.get("ap_version_format")) is int and row["ap_version_format"] == 1
        and type(revision) is int and revision > 0
        and type(row.get("ap_revision_pdf")) is int and row["ap_revision_pdf"] > 0
        and type(revision_pdf) is int and revision_pdf > 0
        and row.get("ap_revision_pdf") == revision_pdf
        and row.get("ap_source_sha256") == row.get("pdf_source_sha256")
        and row.get("ap_configuration_sha256") == row.get("pdf_configuration_sha256")
        and row.get("ap_extracteur") == row.get("pdf_extracteur")
        and isinstance(row.get("ap_source_sha256"), str)
        and _SHA256.fullmatch(row["ap_source_sha256"]) is not None
        and isinstance(row.get("ap_configuration_sha256"), str)
        and _SHA256.fullmatch(row["ap_configuration_sha256"]) is not None
        and row.get("pdf_version_format") == 1
        and row.get("pdf_type_source") == "pdf_natif"
        and row.get("pdf_classe") == "FINANCIAL"
        and row.get("pdf_statut") == "REFUSE"
        and row.get("pdf_code") == "PDF_IMAGE_OU_MIXTE"
        and row.get("ocr_lot_id") == lot_id
        and row.get("ocr_source_sha256") == row.get("pdf_source_sha256")
        and row.get("ocr_revision_pdf_source") == revision_pdf
        and row.get("ocr_configuration_sha256") == row.get("ocr_run_configuration_sha256")
        and row.get("ocr_profil_id") == row.get("ocr_run_profil_id")
        and row.get("ocr_revision_run") == revision_run
        and row.get("ocr_run_statut") == "A_REVOIR"
        and row.get("ocr_run_version_format") == 1
        and type(row.get("ocr_run_resultat_cipher_octets")) is int
        and row["ocr_run_resultat_cipher_octets"] > 0
        and isinstance(row.get("ocr_run_configuration_sha256"), str)
        and _SHA256.fullmatch(row["ocr_run_configuration_sha256"]) is not None
        and isinstance(row.get("ocr_run_profil_id"), str)
        and 1 <= len(row["ocr_run_profil_id"]) <= 32
        and _date_liste_ap(row.get("ap_cree_le"))
        and _date_liste_ap(row.get("ap_modifie_le"))
        and _date_liste_ap(row.get("pdf_modifie_le"))
        and _date_liste_ap(row.get("ocr_run_modifie_le"))
    )
    natif_courant = (
        uuid_valide
        and row.get("pdf_lot_id") == lot_id
        and row.get("ap_statut") == "A_REVOIR"
        and type(row.get("ap_version_format")) is int
        and row["ap_version_format"] == 1
        and type(revision) is int
        and revision > 0
        and type(row.get("ap_revision_pdf")) is int
        and row["ap_revision_pdf"] > 0
        and type(revision_pdf) is int
        and revision_pdf > 0
        and row.get("pdf_version_format") == 1
        and row.get("pdf_type_source") == "pdf_natif"
        and row.get("pdf_classe") == "FINANCIAL"
        and row.get("pdf_statut") == "EXTRAIT_PREPARATOIRE"
        and row.get("ap_revision_pdf") == revision_pdf
        and row.get("ap_source_sha256") == row.get("pdf_source_sha256")
        and row.get("ap_configuration_sha256") == row.get("pdf_configuration_sha256")
        and row.get("ap_extracteur") == row.get("pdf_extracteur")
        and isinstance(row.get("ap_source_sha256"), str)
        and _SHA256.fullmatch(row["ap_source_sha256"]) is not None
        and isinstance(row.get("ap_configuration_sha256"), str)
        and _SHA256.fullmatch(row["ap_configuration_sha256"]) is not None
        and row.get("ap_extracteur") == fusion_pdf.EXTRACTEUR
        and _date_liste_ap(row.get("ap_cree_le"))
        and _date_liste_ap(row.get("ap_modifie_le"))
        and _date_liste_ap(row.get("pdf_modifie_le"))
    )
    if ocr_courant or natif_courant:
        etat = "A_REVALIDER"

    # This is intentionally only a metadata projection. The detail route must
    # still decrypt and validate the current PDF and citations before display.
    projection = {
        "lot_id": lot_id if uuid_valide else None,
        "revision": revision if type(revision) is int and revision > 0 else None,
        "statut": "A_REVOIR" if row.get("ap_statut") == "A_REVOIR" else "INDISPONIBLE",
        "cree_le": row.get("ap_cree_le") if _date_liste_ap(row.get("ap_cree_le")) else None,
        "modifie_le": row.get("ap_modifie_le") if _date_liste_ap(row.get("ap_modifie_le")) else None,
        "etat_source": etat,
    }
    if row.get("ap_ocr_source_type") == "OCR_CANDIDAT":
        projection.update({
            "source_type": "OCR_CANDIDAT",
            "ocr_run_id": ocr_run_id if ocr_link else None,
            "revision_run": revision_run if ocr_link else None,
        })
    return projection


def lister_a_revoir(
    fabrique: fusion_pdf.FabriqueConnexion,
    acteur: str,
    *,
    limite: int = fusion_pdf.NB_LOTS_MAX,
) -> list[dict[str, Any]]:
    """Liste bornée de métadonnées AP seulement; ne lit ni ne déchiffre aucun contenu."""
    if type(limite) is not int or not 1 <= limite <= fusion_pdf.NB_LOTS_MAX:
        raise _erreur("LIMITE_INVALIDE", 400)
    ap = FUSION_AP_BROUILLONS
    pdf = fusion_pdf.FUSION_PDF_LOTS
    ap_ocr = FUSION_AP_OCR_SOURCES
    ocr_run = FUSION_PDF_OCR_RUNS
    colonnes = (
        (ap.c.lot_id, "ap_lot_id"), (ap.c.statut, "ap_statut"), (ap.c.revision, "ap_revision"),
        (ap.c.revision_pdf, "ap_revision_pdf"), (ap.c.version_format, "ap_version_format"),
        (ap.c.source_sha256, "ap_source_sha256"), (ap.c.configuration_sha256, "ap_configuration_sha256"),
        (ap.c.extracteur, "ap_extracteur"), (ap.c.cree_le, "ap_cree_le"), (ap.c.modifie_le, "ap_modifie_le"),
        (pdf.c.lot_id, "pdf_lot_id"), (pdf.c.statut, "pdf_statut"), (pdf.c.revision, "pdf_revision"),
        (pdf.c.version_format, "pdf_version_format"), (pdf.c.type_source, "pdf_type_source"),
        (pdf.c.classe, "pdf_classe"), (pdf.c.source_sha256, "pdf_source_sha256"),
        (pdf.c.configuration_sha256, "pdf_configuration_sha256"), (pdf.c.extracteur, "pdf_extracteur"),
        (pdf.c.modifie_le, "pdf_modifie_le"), (pdf.c.code, "pdf_code"),
        (ap_ocr.c.lot_id, "ap_ocr_lot_id"), (ap_ocr.c.source_type, "ap_ocr_source_type"),
        (ap_ocr.c.ocr_run_id, "ocr_run_id"), (ap_ocr.c.revision_run, "ocr_source_revision_run"),
        (ap_ocr.c.ocr_configuration_sha256, "ocr_configuration_sha256"),
        (ap_ocr.c.ocr_profil_id, "ocr_profil_id"),
        (ocr_run.c.pdf_lot_id, "ocr_lot_id"), (ocr_run.c.source_sha256, "ocr_source_sha256"),
        (ocr_run.c.revision_pdf_source, "ocr_revision_pdf_source"),
        (ocr_run.c.configuration_sha256, "ocr_run_configuration_sha256"),
        (ocr_run.c.profil_id, "ocr_run_profil_id"), (ocr_run.c.revision_run, "ocr_revision_run"),
        (ocr_run.c.version_format, "ocr_run_version_format"), (ocr_run.c.statut, "ocr_run_statut"),
        (ocr_run.c.resultat_cipher_octets, "ocr_run_resultat_cipher_octets"),
        (ocr_run.c.modifie_le, "ocr_run_modifie_le"),
    )
    with fusion_pdf._transaction(fabrique, acteur) as cnx:
        requete = (
            select(*(column.label(label) for column, label in colonnes))
            .select_from(
                ap.outerjoin(pdf, ap.c.lot_id == pdf.c.lot_id)
                .outerjoin(ap_ocr, ap_ocr.c.lot_id == ap.c.lot_id)
                .outerjoin(ocr_run, ocr_run.c.ocr_run_id == ap_ocr.c.ocr_run_id)
            )
            .order_by(ap.c.modifie_le.desc(), ap.c.lot_id.asc())
            .limit(limite + 1)
        )
        rows = [dict(row._mapping) for row in cnx.execute(requete)]
        if len(rows) > limite:
            raise _erreur("LISTE_AP_DEPASSE_QUOTA", 503)
        return [_projection_liste_ap(row) for row in rows]


def lire_champs(fabrique: fusion_pdf.FabriqueConnexion, acteur: str, lot_id: str) -> dict[str, Any]:
    """Lecture explicite privée d'un brouillon; seules les valeurs humaines saisies sont retournées."""
    with fusion_pdf._transaction(fabrique, acteur) as cnx:
        lot = fusion_pdf._lot(cnx, lot_id)
        if _source_ocr_enregistree(cnx, lot) is None:
            lot, resultat = _verifier_pdf(cnx, lot_id, lot["revision"])
            _, proposition = _lire_brouillon(cnx, lot, resultat)
        else:
            _, proposition = _lire_brouillon(cnx, lot, dechiffrer_ocr=True)
        assert proposition is not None
        return proposition


def lire_revue_privee(fabrique: fusion_pdf.FabriqueConnexion, acteur: str, lot_id: str) -> dict[str, Any]:
    """Lit ensemble les métadonnées CAS et les champs déchiffrés, dans une transaction admin."""
    with fusion_pdf._transaction(fabrique, acteur) as cnx:
        lot = fusion_pdf._lot(cnx, lot_id)
        if _source_ocr_enregistree(cnx, lot) is None:
            lot, resultat = _verifier_pdf(cnx, lot_id, lot["revision"])
            brouillon, proposition = _lire_brouillon(cnx, lot, resultat)
        else:
            brouillon, proposition = _lire_brouillon(cnx, lot, dechiffrer_ocr=True)
        assert proposition is not None
        return {"brouillon": _vue(brouillon), "proposition": proposition}


def _enregistrer(
    fabrique: fusion_pdf.FabriqueConnexion,
    acteur: str,
    lot_id: str,
    *,
    mutation_id: str,
    revision_pdf_attendue: int,
    revision_attendue: int,
    proposition: Mapping[str, Any],
    source_ocr: Mapping[str, Any] | None = None,
    permettre_vide: bool = False,
    creation_seule: bool = False,
) -> dict[str, Any]:
    """Crée ou remplace par CAS le brouillon courant; toute révision reste `A_REVOIR`."""
    if not isinstance(mutation_id, str) or not _MUTATION.fullmatch(mutation_id):
        raise _erreur("MUTATION_INVALIDE", 400)
    if type(revision_attendue) is not int or revision_attendue < 0:
        raise _erreur("REVISION_INVALIDE", 400)
    try:
        lot_uuid = isinstance(lot_id, str) and len(lot_id) == 36 and str(uuid.UUID(lot_id)) == lot_id
    except (AttributeError, TypeError, ValueError):
        lot_uuid = False
    if not lot_uuid:
        raise _erreur("LOT_INCONNU", 404)

    with fusion_pdf._transaction(fabrique, acteur) as cnx:
        meta_ocr = None
        candidat_ocr = None
        if source_ocr is None:
            lot, resultat = _verifier_pdf(cnx, lot_id, revision_pdf_attendue)
            contenu = _valider_proposition(proposition, resultat)
        else:
            if (
                type(source_ocr) is not dict or set(source_ocr) != {"ocr_run_id", "revision_run"}
                or type(source_ocr.get("ocr_run_id")) is not str
                or type(source_ocr.get("revision_run")) is not int or source_ocr["revision_run"] < 1
            ):
                raise _erreur("SOURCE_OCR_INVALIDE", 400)
            lot = fusion_pdf._lot(cnx, lot_id)
            fusion_pdf._compatible(lot)
            if type(revision_pdf_attendue) is not int or lot["revision"] != revision_pdf_attendue:
                raise _erreur("CONFLIT_REVISION_PDF")
            meta_ocr, candidat_ocr = _source_ocr_courante(
                cnx, lot, source_ocr["ocr_run_id"], source_ocr["revision_run"],
            )
            contenu = _valider_proposition_ocr(proposition, candidat_ocr, permettre_vide=permettre_vide)
            resultat = None
        requete = {
            "revision_pdf": revision_pdf_attendue,
            "revision_ap": revision_attendue,
            "proposition": contenu,
        }
        if meta_ocr is not None:
            requete["source_ocr"] = {
                "ocr_run_id": meta_ocr["ocr_run_id"], "revision_run": meta_ocr["revision_run"],
            }
        empreinte = hashlib.sha256(_json(requete).encode("utf-8")).hexdigest()
        commande = (
            cnx.execute(
                select(FUSION_AP_COMMANDES).where(
                    (FUSION_AP_COMMANDES.c.lot_id == lot_id)
                    & (FUSION_AP_COMMANDES.c.acteur == acteur)
                    & (FUSION_AP_COMMANDES.c.mutation_id == mutation_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        actuel_row = (
            cnx.execute(select(FUSION_AP_BROUILLONS).where(FUSION_AP_BROUILLONS.c.lot_id == lot_id))
            .mappings()
            .one_or_none()
        )
        actuel = dict(actuel_row) if actuel_row is not None else None
        if commande is not None:
            if commande["empreinte_requete"] != empreinte:
                raise _erreur("CONFLIT_MUTATION")
            if actuel is None:
                raise _erreur("BROUILLON_INCONNU", 404)
            actuel_source, _ = _lire_brouillon(cnx, lot, resultat, dechiffrer_ocr=meta_ocr is not None)
            if (actuel_source.get("source_type") == "OCR_CANDIDAT") != (meta_ocr is not None):
                raise _erreur("SOURCE_AP_IMMUTABLE")
            if meta_ocr is not None and any(actuel_source.get(cle) != meta_ocr[cle] for cle in (
                "ocr_run_id", "revision_run", "ocr_configuration_sha256", "ocr_profil_id",
            )):
                raise _erreur("SOURCE_AP_IMMUTABLE")
            return {**_vue({
                **actuel,
                "source_type": "PDF_NATIF" if meta_ocr is None else "OCR_CANDIDAT",
                **{k: v for k, v in (meta_ocr or {}).items()},
            }),
                    "revision_appliquee": commande["revision_resultat"]}
        if actuel is not None:
            actuel_source, _ = _lire_brouillon(cnx, lot, resultat, dechiffrer_ocr=meta_ocr is not None)
            if (actuel_source.get("source_type") == "OCR_CANDIDAT") != (meta_ocr is not None):
                raise _erreur("SOURCE_AP_IMMUTABLE")
            if meta_ocr is not None and any(actuel_source.get(cle) != meta_ocr[cle] for cle in (
                "ocr_run_id", "revision_run", "ocr_configuration_sha256", "ocr_profil_id",
            )):
                raise _erreur("SOURCE_AP_IMMUTABLE")
            if creation_seule:
                raise _erreur("BROUILLON_AP_EXISTANT")
        elif creation_seule and revision_attendue != 0:
            raise _erreur("CONFLIT_REVISION")
        elif meta_ocr is not None and not creation_seule:
            raise _erreur("BROUILLON_AP_ABSENT")
        if (actuel is None and revision_attendue != 0) or (
            actuel is not None and actuel["revision"] != revision_attendue
        ):
            raise _erreur("CONFLIT_REVISION")
        nb_commandes = cnx.execute(
            select(func.count()).select_from(FUSION_AP_COMMANDES).where(FUSION_AP_COMMANDES.c.lot_id == lot_id)
        ).scalar_one()
        if nb_commandes >= MAX_COMMANDES_PAR_LOT:
            raise _erreur("AP_COMMANDES_QUOTA_ATTEINT", 409)

        revision = 1 if actuel is None else revision_attendue + 1
        reference = lot["cle_reference"]
        brouillon = {
            "lot_id": lot_id,
            "source_type": "PDF_NATIF" if meta_ocr is None else "OCR_CANDIDAT",
            "source_sha256": lot["source_sha256"],
            "configuration_sha256": lot["configuration_sha256"],
            "extracteur": lot["extracteur"],
            "revision_pdf": lot["revision"],
            "revision": revision,
            "statut": "A_REVOIR",
            "auteur": acteur if actuel is None else actuel["auteur"],
            "modifie_par": acteur,
            "cle_reference": reference,
            "version_format": 1,
        }
        if meta_ocr is not None:
            brouillon.update(meta_ocr)
        clair = _json(contenu).encode("utf-8")
        nonce, chiffre, octets = _chiffrer(brouillon, clair, fusion_csv._cle(reference))
        ancien_octets = 0 if actuel is None else actuel["proposition_cipher_octets"]
        reserve = cnx.execute(
            update(FUSION_PDF_QUOTA)
            .where(
                (FUSION_PDF_QUOTA.c.id == 1)
                & (FUSION_PDF_QUOTA.c.octets_cipher >= ancien_octets)
                & (FUSION_PDF_QUOTA.c.octets_cipher - ancien_octets + octets <= fusion_pdf.QUOTA_CIPHER_MAX)
            )
            .values(octets_cipher=FUSION_PDF_QUOTA.c.octets_cipher - ancien_octets + octets)
        )
        if reserve.rowcount != 1:
            raise _erreur("PDF_QUOTA_ATTEINT")
        maintenant = fusion_csv._maintenant()
        valeurs = {
            **{cle: valeur for cle, valeur in brouillon.items() if cle not in {
                "source_type", "ocr_run_id", "revision_run", "ocr_configuration_sha256", "ocr_profil_id",
            }},
            "proposition_nonce": nonce,
            "proposition_cipher": chiffre,
            "proposition_cipher_octets": octets,
            "cree_le": maintenant if actuel is None else actuel["cree_le"],
            "modifie_le": maintenant,
        }
        if actuel is None:
            cnx.execute(insert(FUSION_AP_BROUILLONS).values(**valeurs))
            if meta_ocr is not None:
                cnx.execute(insert(FUSION_AP_OCR_SOURCES).values(
                    lot_id=lot_id,
                    **{cle: meta_ocr[cle] for cle in (
                        "source_type", "ocr_run_id", "revision_run", "ocr_configuration_sha256", "ocr_profil_id",
                    )},
                ))
        else:
            ecrit = cnx.execute(
                update(FUSION_AP_BROUILLONS)
                .where(
                    (FUSION_AP_BROUILLONS.c.lot_id == lot_id) & (FUSION_AP_BROUILLONS.c.revision == revision_attendue)
                )
                .values(**{cle: valeur for cle, valeur in valeurs.items() if cle != "cree_le"})
            )
            if ecrit.rowcount != 1:
                raise _erreur("CONFLIT_REVISION")
        cnx.execute(
            insert(FUSION_AP_COMMANDES).values(
                lot_id=lot_id,
                acteur=acteur,
                mutation_id=mutation_id,
                empreinte_requete=empreinte,
                revision_resultat=revision,
                cree_le=maintenant,
            )
        )
        etat.journaliser(
            cnx,
            acteur,
            "fusion.ap.brouillon.enregistre",
            lot_id,
            {
                "source_sha256": lot["source_sha256"],
                "revision_pdf": lot["revision"],
                "revision": revision,
                "statut": "A_REVOIR",
                "source_type": "PDF_NATIF" if meta_ocr is None else "OCR_CANDIDAT",
                "nombre_champs": len(contenu["champs"]),
                "nombre_citations": sum(len(items) for items in contenu["citations"].values()),
            },
        )
        return {**_vue({
            **valeurs,
            "source_type": "PDF_NATIF" if meta_ocr is None else "OCR_CANDIDAT",
            **(meta_ocr or {}),
        }), "revision_appliquee": revision}


def enregistrer(
    fabrique: fusion_pdf.FabriqueConnexion,
    acteur: str,
    lot_id: str,
    *,
    mutation_id: str,
    revision_pdf_attendue: int,
    revision_attendue: int,
    proposition: Mapping[str, Any],
) -> dict[str, Any]:
    """Crée ou révise un brouillon adossé au PDF natif, sans élargir son contrat."""
    return _enregistrer(
        fabrique, acteur, lot_id, mutation_id=mutation_id,
        revision_pdf_attendue=revision_pdf_attendue, revision_attendue=revision_attendue,
        proposition=proposition,
    )


def _proposition_vide() -> dict[str, Any]:
    return {"schema_version": 1, "champs": {cle: "" for cle in _CHAMPS}, "citations": {}}


def creer_brouillon_ocr(
    fabrique: fusion_pdf.FabriqueConnexion,
    acteur: str,
    lot_id: str,
    *,
    mutation_id: str,
    revision_pdf_attendue: int,
    ocr_run_id: str,
    revision_run: int,
) -> dict[str, Any]:
    """Crée explicitement un brouillon OCR vide; aucun champ n'est transféré du candidat."""
    return _enregistrer(
        fabrique, acteur, lot_id, mutation_id=mutation_id,
        revision_pdf_attendue=revision_pdf_attendue, revision_attendue=0,
        proposition=_proposition_vide(),
        source_ocr={"ocr_run_id": ocr_run_id, "revision_run": revision_run},
        permettre_vide=True, creation_seule=True,
    )


def enregistrer_ocr(
    fabrique: fusion_pdf.FabriqueConnexion,
    acteur: str,
    lot_id: str,
    *,
    mutation_id: str,
    revision_pdf_attendue: int,
    revision_attendue: int,
    ocr_run_id: str,
    revision_run: int,
    proposition: Mapping[str, Any],
) -> dict[str, Any]:
    """Enregistre les corrections humaines avec citations au run OCR immuable courant."""
    return _enregistrer(
        fabrique, acteur, lot_id, mutation_id=mutation_id,
        revision_pdf_attendue=revision_pdf_attendue, revision_attendue=revision_attendue,
        proposition=proposition, source_ocr={"ocr_run_id": ocr_run_id, "revision_run": revision_run},
    )
