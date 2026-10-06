"""Stockage local chiffré des candidats OCR issus d'un refus PDF image/mixte.

Le moteur reste confiné dans ``ocr_runtime``. Ce module ne transforme jamais un
candidat en donnée comptable et conserve le statut PARTIEL du parcours.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import LargeBinary, cast, func, insert, select, update

from . import fusion_csv, fusion_pdf, identite
from .ocr_candidat import ContexteOCR, OCRContratErreur, decoder_candidat
from .ocr_profil import MODELE_SHA256, PDFIUM_SHA256, OCRProfilErreur, valider_bundle
from .ocr_runtime import OCRRuntimeErreur, contexte_ocr, extraire_candidat
from .ocr_worker import CONFIGURATION_SHA256
from .stockage.schema import (
    FUSION_PDF_LOTS,
    FUSION_PDF_OCR_COMMANDES,
    FUSION_PDF_OCR_QUOTA,
    FUSION_PDF_OCR_RUNS,
)

FusionPDFOCRErreur = fusion_pdf.FusionPDFErreur
FabriqueConnexion = fusion_pdf.FabriqueConnexion
_RESERVATION_MAX = 262_160
_CIPHER_MAX = _RESERVATION_MAX
_CIPHER_B64_MAX = 349_548
_SOURCE_CIPHER_MAX = fusion_pdf.SOURCE_MAX + 16
_SOURCE_B64_MAX = 4 * ((_SOURCE_CIPHER_MAX + 2) // 3)
_PROFIL_ID = "ocr-scan-2"
_COMMANDES_MAX = 256
_MUTATION = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_REFERENCE_CLE = re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z")
_STATUTS = frozenset({"RESERVE", "A_REVOIR", "REFUSE", "ERREUR_REPRENABLE", "PERIME"})
_CODES_RUNTIME = frozenset({
    "OCR_STRUCTURE_REFUSEE", "OCR_PROFIL_INDISPONIBLE", "OCR_RUNTIME_INDISPONIBLE",
    "OCR_SOURCE_INVALIDE", "OCR_RESULTAT_INVALIDE", "OCR_LIMITES_INDISPONIBLES",
    "OCR_ISOLATION_INDISPONIBLE", "OCR_TIMEOUT", "OCR_SORTIE_EXCESSIVE", "OCR_PROTOCOLE_INVALIDE",
})
_CODES_REFUS = frozenset({"OCR_STRUCTURE_REFUSEE", "OCR_SOURCE_INVALIDE"})
_CODES_SERVICE = _CODES_RUNTIME | frozenset({
    "OCR_SOURCE_MODIFIEE", "OCR_CHIFFREMENT_INDISPONIBLE", "OCR_QUOTA_CORROMPU",
})
_MESSAGE = "opération OCR refusée ou temporairement indisponible"


def _erreur(code: str, statut: int = 409) -> FusionPDFOCRErreur:
    return FusionPDFOCRErreur(code, _MESSAGE, statut)


def _uuid(value: object) -> bool:
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value
    except (ValueError, AttributeError):
        return False


def _run_id(value: object) -> bool:
    return _uuid(value)


def _vue(row: Any) -> dict[str, Any]:
    return {key: row[key] for key in (
        "ocr_run_id", "pdf_lot_id", "acteur", "source_sha256", "revision_pdf_source",
        "configuration_sha256", "profil_id", "version_format", "revision_run", "statut",
        "reserve_octets", "resultat_cipher_octets", "code", "cree_le", "modifie_le",
    )}


def _aad(row: Any, *, revision_run: int) -> bytes:
    # L'ordre et l'encodage sont stables; toute identité différente invalide le tag GCM.
    champs = (
        "opsys-fusion-pdf-ocr:v1", row["ocr_run_id"], row["pdf_lot_id"], row["acteur"],
        row["source_sha256"], str(row["revision_pdf_source"]), row["profil_id"],
        row["configuration_sha256"], row["cle_reference"], str(row["version_format"]), PDFIUM_SHA256,
        MODELE_SHA256, str(revision_run), "candidat",
    )
    return ":".join(champs).encode("ascii", "strict")


def _chiffrer_resultat(row: Any, candidat: dict[str, Any], *, revision_run: int) -> tuple[str, str, int]:
    contenu = json.dumps(candidat, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    clair = contenu.encode("utf-8", "strict")
    if not 1 <= len(clair) <= 262_144:
        raise _erreur("OCR_RESULTAT_INVALIDE")
    nonce_octets = secrets.token_bytes(12)
    chiffre = fusion_csv._aesgcm()(fusion_csv._cle(row["cle_reference"])).encrypt(
        nonce_octets, clair, _aad(row, revision_run=revision_run),
    )
    return (
        base64.b64encode(nonce_octets).decode("ascii"),
        base64.b64encode(chiffre).decode("ascii"), len(chiffre),
    )


def _meta_pdf(cnx, lot_id: str) -> dict[str, Any]:
    if not _uuid(lot_id):
        raise _erreur("LOT_INCONNU", 404)
    t = FUSION_PDF_LOTS
    taille = func.length(cast(t.c.source_cipher, LargeBinary))
    stmt = select(
        t.c.lot_id, t.c.acteur, t.c.type_source, t.c.classe, t.c.extracteur, t.c.configuration_sha256,
        t.c.source_sha256, t.c.source_octets, t.c.source_cipher_octets,
        func.typeof(t.c.source_cipher).label("source_cipher_type"), taille.label("source_cipher_taille"),
        func.typeof(t.c.source_nonce).label("source_nonce_type"),
        func.length(cast(t.c.source_nonce, LargeBinary)).label("source_nonce_taille"),
        t.c.cle_reference, t.c.version_format, t.c.statut, t.c.revision, t.c.code,
    ).where(t.c.lot_id == lot_id)
    row = cnx.execute(stmt).mappings().one_or_none()
    if row is None:
        raise _erreur("LOT_INCONNU", 404)
    data = dict(row)
    octets = data["source_cipher_octets"]
    if (
        type(octets) is not int or not 17 <= octets <= _SOURCE_CIPHER_MAX
        or data["source_cipher_type"] != "text"
        or type(data["source_cipher_taille"]) is not int
        or data["source_cipher_taille"] != 4 * ((octets + 2) // 3)
        or data["source_cipher_taille"] > _SOURCE_B64_MAX
        or type(data["source_octets"]) is not int or not 1 <= data["source_octets"] <= fusion_pdf.SOURCE_MAX
        or octets != data["source_octets"] + 16
        or type(data["version_format"]) is not int or data["version_format"] != 1
        or type(data["revision"]) is not int or not 1 <= data["revision"] <= 2_147_483_647
        or not isinstance(data["source_sha256"], str) or _SHA256.fullmatch(data["source_sha256"]) is None
        or not isinstance(data["cle_reference"], str) or not 1 <= len(data["cle_reference"]) <= 64
        or data["source_nonce_type"] != "text" or data["source_nonce_taille"] != 16
    ):
        raise _erreur("OCR_SOURCE_CORROMPUE", 503)
    if (
        data["type_source"] != "pdf_natif" or data["classe"] != "FINANCIAL"
        or data["extracteur"] != fusion_pdf.EXTRACTEUR
        or data["configuration_sha256"] != fusion_pdf.CONFIGURATION_SHA256
        or data["statut"] != "REFUSE" or data["code"] != "PDF_IMAGE_OU_MIXTE"
    ):
        raise _erreur("OCR_PDF_NON_ELIGIBLE")
    # La sélection du payload n'a lieu qu'après les contrôles SQL de type et longueur.
    payload = cnx.execute(select(
        t.c.source_nonce, t.c.source_cipher,
    ).where(
        (t.c.lot_id == lot_id) & (func.typeof(t.c.source_cipher) == "text")
        & (func.typeof(t.c.source_nonce) == "text")
        & (func.length(cast(t.c.source_nonce, LargeBinary)) == 16)
        & (func.length(cast(t.c.source_cipher, LargeBinary)) <= _SOURCE_B64_MAX)
        & t.c.source_cipher_octets.between(17, _SOURCE_CIPHER_MAX)
    )).one_or_none()
    if payload is None or type(payload[0]) is not str or type(payload[1]) is not str:
        raise _erreur("OCR_SOURCE_CORROMPUE", 503)
    data["source_nonce"], data["source_cipher"] = payload[0], payload[1]
    if len(payload[1]) != 4 * ((octets + 2) // 3):
        raise _erreur("OCR_SOURCE_CORROMPUE", 503)
    return data


def _source(lot: dict[str, Any]) -> bytes:
    if (
        lot["type_source"] != "pdf_natif" or lot["classe"] != "FINANCIAL"
        or lot["extracteur"] != fusion_pdf.EXTRACTEUR
        or lot["configuration_sha256"] != fusion_pdf.CONFIGURATION_SHA256
        or lot["statut"] != "REFUSE" or lot["code"] != "PDF_IMAGE_OU_MIXTE"
    ):
        raise _erreur("OCR_PDF_NON_ELIGIBLE")
    try:
        clair = fusion_csv._dechiffrer(
            fusion_csv._cle(lot["cle_reference"]), lot, "pdf-natif-1:source",
            lot["source_nonce"], lot["source_cipher"],
        )
    except Exception:
        raise _erreur("OCR_SOURCE_CORROMPUE", 503) from None
    if len(clair) != lot["source_octets"] or hashlib.sha256(clair).hexdigest() != lot["source_sha256"]:
        raise _erreur("OCR_SOURCE_CORROMPUE", 503)
    return clair


def _bundle(bundle: Path) -> dict[str, str]:
    if not isinstance(bundle, Path):
        raise _erreur("OCR_PROFIL_INDISPONIBLE", 503)
    try:
        resultat = valider_bundle(bundle)
    except OCRProfilErreur:
        raise _erreur("OCR_PROFIL_INDISPONIBLE", 503) from None
    if not isinstance(resultat, dict) or not resultat or any(
        type(key) is not str or not key.startswith("rasterizer/")
        or type(value) is not str or _SHA256.fullmatch(value) is None
        for key, value in resultat.items()
    ):
        raise _erreur("OCR_PROFIL_INDISPONIBLE", 503)
    return dict(resultat)


def _empreinte(acteur: str, lot_id: str, revision: int, source_sha: str, profil: dict[str, str]) -> str:
    payload = {
        "acteur": acteur, "lot_id": lot_id, "revision_source": revision,
        "source_sha256": source_sha, "profil_id": _PROFIL_ID,
        "configuration_sha256": CONFIGURATION_SHA256, "pdfium_sha256": PDFIUM_SHA256,
        "modele_sha256": MODELE_SHA256, "bundle": sorted(profil.items()),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")).hexdigest()


def _run(cnx, run_id: str) -> dict[str, Any]:
    if not _run_id(run_id):
        raise _erreur("OCR_RUN_INCONNU", 404)
    t = FUSION_PDF_OCR_RUNS
    row = cnx.execute(select(
        t.c.ocr_run_id, t.c.pdf_lot_id, t.c.acteur, t.c.source_sha256, t.c.revision_pdf_source,
        t.c.configuration_sha256, t.c.profil_id, t.c.cle_reference, t.c.version_format,
        t.c.revision_run, t.c.statut, t.c.reserve_octets, t.c.resultat_cipher_octets, t.c.code,
        t.c.cree_le, t.c.modifie_le,
        func.typeof(t.c.resultat_cipher).label("cipher_type"),
        func.length(cast(t.c.resultat_cipher, LargeBinary)).label("cipher_taille"),
        func.typeof(t.c.resultat_nonce).label("nonce_type"),
        func.length(cast(t.c.resultat_nonce, LargeBinary)).label("nonce_taille"),
    ).where(t.c.ocr_run_id == run_id)).mappings().one_or_none()
    if row is None:
        raise _erreur("OCR_RUN_INCONNU", 404)
    data = dict(row)
    if (
        data["statut"] not in _STATUTS or type(data["version_format"]) is not int or data["version_format"] != 1
        or type(data["revision_run"]) is not int or not 1 <= data["revision_run"] <= 2_147_483_647
        or type(data["reserve_octets"]) is not int or not 0 <= data["reserve_octets"] <= _RESERVATION_MAX
        or type(data["resultat_cipher_octets"]) is not int
        or not 0 <= data["resultat_cipher_octets"] <= _CIPHER_MAX
        or not _uuid(data["ocr_run_id"]) or not _uuid(data["pdf_lot_id"])
        or not isinstance(data["acteur"], str) or not identite.identifiant_valide(data["acteur"])
        or not isinstance(data["source_sha256"], str) or _SHA256.fullmatch(data["source_sha256"]) is None
        or type(data["revision_pdf_source"]) is not int
        or not 1 <= data["revision_pdf_source"] <= 2_147_483_647
        or not isinstance(data["configuration_sha256"], str)
        or _SHA256.fullmatch(data["configuration_sha256"]) is None
        or not isinstance(data["profil_id"], str) or data["profil_id"] != _PROFIL_ID
        or not isinstance(data["cle_reference"], str) or _REFERENCE_CLE.fullmatch(data["cle_reference"]) is None
        or any(not isinstance(data[key], str) or not 1 <= len(data[key]) <= 64 for key in ("cree_le", "modifie_le"))
        or (data["code"] is not None and data["code"] not in _CODES_SERVICE)
        or (data["statut"] in {"RESERVE", "A_REVOIR"} and data["code"] is not None)
        or (data["statut"] in {"REFUSE", "ERREUR_REPRENABLE", "PERIME"} and data["code"] is None)
    ):
        raise _erreur("OCR_RUN_CORROMPU", 503)
    if data["statut"] == "A_REVOIR":
        if (
            data["reserve_octets"] != 0
            or data["nonce_type"] != "text" or data["nonce_taille"] != 16
            or data["cipher_type"] != "text" or type(data["cipher_taille"]) is not int
            or not 24 <= data["cipher_taille"] <= _CIPHER_B64_MAX
            or not 17 <= data["resultat_cipher_octets"] <= _CIPHER_MAX
            or data["cipher_taille"] != 4 * ((data["resultat_cipher_octets"] + 2) // 3)
        ):
            raise _erreur("OCR_RUN_CORROMPU", 503)
    else:
        reserve_attendue = _RESERVATION_MAX if data["statut"] == "RESERVE" else 0
        if (
            data["reserve_octets"] != reserve_attendue or data["resultat_cipher_octets"] != 0
            or data["cipher_type"] not in (None, "null") or data["cipher_taille"] is not None
            or data["nonce_type"] not in (None, "null") or data["nonce_taille"] is not None
        ):
            raise _erreur("OCR_RUN_CORROMPU", 503)
    return data


def _ciphertext_resultat(cnx, run: dict[str, Any]) -> tuple[str, str]:
    t = FUSION_PDF_OCR_RUNS
    row = cnx.execute(select(t.c.resultat_nonce, t.c.resultat_cipher).where(
        (t.c.ocr_run_id == run["ocr_run_id"]) & (t.c.statut == "A_REVOIR")
        & (func.typeof(t.c.resultat_cipher) == "text")
        & (func.typeof(t.c.resultat_nonce) == "text")
        & (func.length(cast(t.c.resultat_cipher, LargeBinary)) <= _CIPHER_B64_MAX)
        & t.c.resultat_cipher_octets.between(17, _CIPHER_MAX)
        & (func.length(cast(t.c.resultat_nonce, LargeBinary)) == 16)
    )).one_or_none()
    if row is None or type(row[0]) is not str or type(row[1]) is not str:
        raise _erreur("OCR_RESULTAT_INDISPONIBLE", 503)
    return row[0], row[1]


def _objet_candidat(candidat: Any, contexte: ContexteOCR) -> tuple[dict[str, Any], bytes]:
    if not isinstance(candidat, dict):
        raise _erreur("OCR_RESULTAT_INVALIDE", 503)
    try:
        brut = json.dumps(
            candidat, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        valide = decoder_candidat(brut, contexte=contexte)
    except (TypeError, ValueError, UnicodeEncodeError, OCRContratErreur, RecursionError):
        raise _erreur("OCR_RESULTAT_INVALIDE", 503) from None
    if not 1 <= len(brut) <= 262_144:
        raise _erreur("OCR_RESULTAT_INVALIDE", 503)
    return valide, brut


def _mappage_runtime(exc: Exception) -> tuple[str, str]:
    code = getattr(exc, "code", None)
    if not isinstance(code, str) or code not in _CODES_RUNTIME:
        code = "OCR_RUNTIME_INDISPONIBLE"
    return ("REFUSE" if code in _CODES_REFUS else "ERREUR_REPRENABLE", code)


def _exiger_place_commande(cnx) -> None:
    nombre = cnx.execute(select(func.count()).select_from(FUSION_PDF_OCR_COMMANDES)).scalar_one()
    if type(nombre) is not int or nombre >= _COMMANDES_MAX:
        raise _erreur("OCR_COMMANDES_QUOTA_ATTEINT")


def _vue_courant(fabrique: FabriqueConnexion, acteur: str, run_id: str) -> dict[str, Any]:
    with fusion_pdf._transaction(fabrique, acteur) as cnx:
        return _vue(_run(cnx, run_id))


def preparer(
    fabrique: FabriqueConnexion, acteur: str, pdf_lot_id: str, revision_source: int,
    mutation_id: str, *, bundle: Path,
) -> dict[str, Any]:
    if not identite.identifiant_valide(acteur):
        raise _erreur("ACTEUR_INVALIDE", 400)
    if not _uuid(pdf_lot_id):
        raise _erreur("LOT_INCONNU", 404)
    if type(revision_source) is not int or not 1 <= revision_source <= 2_147_483_647:
        raise _erreur("REVISION_INVALIDE", 400)
    if not isinstance(mutation_id, str) or _MUTATION.fullmatch(mutation_id) is None:
        raise _erreur("MUTATION_INVALIDE", 400)
    bundle_preuve = _bundle(bundle)
    run_id: str
    source: bytes
    empreinte: str
    nouvelle_reservation = False
    with fusion_pdf._transaction(fabrique, acteur) as cnx:
        pdf = _meta_pdf(cnx, pdf_lot_id)
        source = _source(pdf)
        if pdf["revision"] != revision_source:
            raise _erreur("CONFLIT_REVISION")
        empreinte = _empreinte(acteur, pdf_lot_id, revision_source, pdf["source_sha256"], bundle_preuve)
        commande = cnx.execute(select(FUSION_PDF_OCR_COMMANDES).where(
            (FUSION_PDF_OCR_COMMANDES.c.acteur == acteur)
            & (FUSION_PDF_OCR_COMMANDES.c.mutation_id == mutation_id)
        )).mappings().one_or_none()
        if commande is not None:
            if commande["empreinte_requete"] != empreinte:
                raise _erreur("CONFLIT_MUTATION")
            return _vue(_run(cnx, commande["ocr_run_id"]))
        identique = cnx.execute(select(FUSION_PDF_OCR_RUNS.c.ocr_run_id).where(
            (FUSION_PDF_OCR_RUNS.c.pdf_lot_id == pdf_lot_id)
            & (FUSION_PDF_OCR_RUNS.c.source_sha256 == pdf["source_sha256"])
            & (FUSION_PDF_OCR_RUNS.c.revision_pdf_source == revision_source)
            & (FUSION_PDF_OCR_RUNS.c.configuration_sha256 == CONFIGURATION_SHA256)
        )).mappings().one_or_none()
        if identique is not None:
            run_id = identique["ocr_run_id"]
            _exiger_place_commande(cnx)
            cnx.execute(insert(FUSION_PDF_OCR_COMMANDES).values(
                acteur=acteur, mutation_id=mutation_id, empreinte_requete=empreinte,
                ocr_run_id=run_id, cree_le=fusion_csv._maintenant(),
            ))
            return _vue(_run(cnx, run_id))
        cle_reference = fusion_csv._reference_cle()
        fusion_csv._cle(cle_reference)
        fusion_csv._aesgcm()
        _exiger_place_commande(cnx)
        reserve = cnx.execute(update(FUSION_PDF_OCR_QUOTA).where(
            (FUSION_PDF_OCR_QUOTA.c.id == 1)
            & (FUSION_PDF_OCR_QUOTA.c.lots < 16)
            & (FUSION_PDF_OCR_QUOTA.c.octets_cipher + _RESERVATION_MAX <= 4_194_304)
        ).values(
            lots=FUSION_PDF_OCR_QUOTA.c.lots + 1,
            octets_cipher=FUSION_PDF_OCR_QUOTA.c.octets_cipher + _RESERVATION_MAX,
        ))
        if reserve.rowcount != 1:
            raise _erreur("OCR_QUOTA_ATTEINT", 409)
        run_id = str(uuid.uuid4())
        maintenant = fusion_csv._maintenant()
        cnx.execute(insert(FUSION_PDF_OCR_RUNS).values(
            ocr_run_id=run_id, pdf_lot_id=pdf_lot_id, acteur=acteur,
            source_sha256=pdf["source_sha256"], revision_pdf_source=revision_source,
            configuration_sha256=CONFIGURATION_SHA256, profil_id=_PROFIL_ID,
            cle_reference=cle_reference, version_format=1, revision_run=1,
            statut="RESERVE", reserve_octets=_RESERVATION_MAX, resultat_nonce=None,
            resultat_cipher=None, resultat_cipher_octets=0, code=None,
            cree_le=maintenant, modifie_le=maintenant,
        ))
        cnx.execute(insert(FUSION_PDF_OCR_COMMANDES).values(
            acteur=acteur, mutation_id=mutation_id, empreinte_requete=empreinte,
            ocr_run_id=run_id, cree_le=maintenant,
        ))
        nouvelle_reservation = True

    if not nouvelle_reservation:
        return _vue_courant(fabrique, acteur, run_id)

    try:
        candidat = extraire_candidat(
            source, lot_id=pdf_lot_id, revision_source=revision_source, bundle=bundle,
        )
        contexte = contexte_ocr(source, lot_id=pdf_lot_id, revision_source=revision_source)
        candidat, clair = _objet_candidat(candidat, contexte)
        resultat = {"statut": "A_REVOIR", "code": None, "clair": clair, "candidat": candidat}
    except OCRRuntimeErreur as exc:
        statut, code = _mappage_runtime(exc)
        resultat = {"statut": statut, "code": code}
    except Exception:
        resultat = {"statut": "ERREUR_REPRENABLE", "code": "OCR_RESULTAT_INVALIDE"}

    # Si l'identité a été révoquée pendant le worker, _transaction échoue et la
    # réservation RESERVE est conservée pour reprise administrative ultérieure.
    with fusion_pdf._transaction(fabrique, acteur) as cnx:
        courant = _run(cnx, run_id)
        identites_run_ok = (
            courant["acteur"] == acteur and courant["pdf_lot_id"] == pdf_lot_id
            and courant["source_sha256"] == pdf["source_sha256"]
            and courant["revision_pdf_source"] == revision_source
            and courant["configuration_sha256"] == CONFIGURATION_SHA256
            and courant["profil_id"] == _PROFIL_ID
            and courant["cle_reference"] == cle_reference
            and courant["version_format"] == 1
        )
        perime = False
        try:
            pdf_courant = _meta_pdf(cnx, pdf_lot_id)
            source_courante = _source(pdf_courant)
            profil_courant = _bundle(bundle)
        except FusionPDFOCRErreur:
            # Sous identité toujours valide, source/profil désormais illisible signifie
            # candidat périmé; la réservation est restituée dans cette transaction.
            perime = True
            pdf_courant = None
            source_courante = b""
            profil_courant = {}
        perime = perime or (
            not identites_run_ok
            or courant["statut"] != "RESERVE" or courant["revision_run"] != 1
            or pdf_courant is None or pdf_courant["revision"] != revision_source
            or pdf_courant["source_sha256"] != courant["source_sha256"]
            or pdf_courant["source_nonce"] != pdf["source_nonce"]
            or pdf_courant["source_cipher"] != pdf["source_cipher"]
            or pdf_courant["source_octets"] != pdf["source_octets"]
            or pdf_courant["cle_reference"] != pdf["cle_reference"]
            or pdf_courant["version_format"] != pdf["version_format"]
            or pdf_courant["configuration_sha256"] != pdf["configuration_sha256"]
            or pdf_courant["type_source"] != pdf["type_source"]
            or pdf_courant["classe"] != pdf["classe"]
            or pdf_courant["extracteur"] != pdf["extracteur"]
            or source_courante != source or profil_courant != bundle_preuve
            or courant["configuration_sha256"] != CONFIGURATION_SHA256
            or courant["profil_id"] != _PROFIL_ID
        )
        maintenant = fusion_csv._maintenant()
        valeurs: dict[str, Any] = {
            "revision_run": courant["revision_run"] + 1,
            "reserve_octets": 0,
            "resultat_nonce": None, "resultat_cipher": None, "resultat_cipher_octets": 0,
            "modifie_le": maintenant,
        }
        if perime:
            statut, code = "PERIME", "OCR_SOURCE_MODIFIEE"
        elif resultat["statut"] == "A_REVOIR":
            # Le contexte est reconstruit après revalidation et le candidat est redécodé ici.
            try:
                contexte_courant = contexte_ocr(source_courante, lot_id=pdf_lot_id, revision_source=revision_source)
                candidat, _clair_json = _objet_candidat(resultat["candidat"], contexte_courant)
                nonce_b64, cipher_b64, cipher_octets = _chiffrer_resultat(
                    courant, candidat, revision_run=valeurs["revision_run"],
                )
                if not 17 <= cipher_octets <= _CIPHER_MAX or len(cipher_b64) > _CIPHER_B64_MAX:
                    raise _erreur("OCR_RESULTAT_INVALIDE", 503)
            except Exception:
                statut, code = "ERREUR_REPRENABLE", "OCR_CHIFFREMENT_INDISPONIBLE"
            else:
                statut, code = "A_REVOIR", None
                valeurs.update(
                    resultat_nonce=nonce_b64, resultat_cipher=cipher_b64,
                    resultat_cipher_octets=cipher_octets,
                )
        else:
            statut, code = resultat["statut"], resultat["code"]
        valeurs.update(statut=statut, code=code)
        ecrit = cnx.execute(update(FUSION_PDF_OCR_RUNS).where(
            (FUSION_PDF_OCR_RUNS.c.ocr_run_id == run_id)
            & (FUSION_PDF_OCR_RUNS.c.statut == "RESERVE")
            & (FUSION_PDF_OCR_RUNS.c.revision_run == 1)
        ).values(**valeurs))
        if ecrit.rowcount != 1:
            raise _erreur("OCR_CONFLIT_REVISION")
        taille_reserve = courant["reserve_octets"]
        taille_finale = valeurs["resultat_cipher_octets"]
        quota = cnx.execute(update(FUSION_PDF_OCR_QUOTA).where(
            (FUSION_PDF_OCR_QUOTA.c.id == 1)
            & (FUSION_PDF_OCR_QUOTA.c.lots >= 1)
            & (FUSION_PDF_OCR_QUOTA.c.octets_cipher >= taille_reserve)
            & (FUSION_PDF_OCR_QUOTA.c.octets_cipher - taille_reserve + taille_finale <= 4_194_304)
        ).values(octets_cipher=FUSION_PDF_OCR_QUOTA.c.octets_cipher - taille_reserve + taille_finale))
        if quota.rowcount != 1:
            raise _erreur("OCR_QUOTA_CORROMPU", 503)
        return _vue(_run(cnx, run_id))


def lire(fabrique: FabriqueConnexion, acteur: str, ocr_run_id: str) -> dict[str, Any]:
    with fusion_pdf._transaction(fabrique, acteur) as cnx:
        return _vue(_run(cnx, ocr_run_id))


def lire_resultat_dans_transaction(cnx, ocr_run_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Relit le run et son candidat dans la transaction de l'appelant.

    Le contrat est interne au raccord AP : il ne saute aucune vérification de
    ``lire_resultat`` et permet au brouillon AP de vérifier provenance et contenu
    sous le même snapshot SQL que son CAS.
    """
    run = _run(cnx, ocr_run_id)
    if (run["statut"] != "A_REVOIR" or run["profil_id"] != _PROFIL_ID
            or run["configuration_sha256"] != CONFIGURATION_SHA256):
        raise _erreur("OCR_RESULTAT_INDISPONIBLE")
    pdf = _meta_pdf(cnx, run["pdf_lot_id"])
    if (
        pdf["revision"] != run["revision_pdf_source"] or pdf["source_sha256"] != run["source_sha256"]
        or pdf["statut"] != "REFUSE" or pdf["code"] != "PDF_IMAGE_OU_MIXTE"
    ):
        raise _erreur("OCR_RESULTAT_INDISPONIBLE")
    source = _source(pdf)
    contexte = contexte_ocr(source, lot_id=run["pdf_lot_id"], revision_source=run["revision_pdf_source"])
    nonce_b64, cipher_b64 = _ciphertext_resultat(cnx, run)
    try:
        nonce = base64.b64decode(nonce_b64, validate=True)
        cipher = base64.b64decode(cipher_b64, validate=True)
        if len(nonce) != 12 or len(cipher) != run["resultat_cipher_octets"]:
            raise ValueError("taille cipher incohérente")
        clair = fusion_csv._aesgcm()(fusion_csv._cle(run["cle_reference"])).decrypt(
            nonce, cipher, _aad(run, revision_run=run["revision_run"]),
        )
        if not 1 <= len(clair) <= 262_144:
            raise ValueError("taille résultat incohérente")
        candidat = decoder_candidat(clair, contexte=contexte)
    except Exception:
        raise _erreur("OCR_RESULTAT_CORROMPU", 503) from None
    return _vue(run), candidat


def lire_resultat(fabrique: FabriqueConnexion, acteur: str, ocr_run_id: str) -> dict[str, Any]:
    with fusion_pdf._transaction(fabrique, acteur) as cnx:
        _, candidat = lire_resultat_dans_transaction(cnx, ocr_run_id)
        return candidat


def lister(fabrique: FabriqueConnexion, acteur: str, *, limite: int = 16) -> list[dict[str, Any]]:
    if type(limite) is not int or not 1 <= limite <= 16:
        raise _erreur("LIMITE_INVALIDE", 400)
    with fusion_pdf._transaction(fabrique, acteur) as cnx:
        rows = cnx.execute(select(FUSION_PDF_OCR_RUNS.c.ocr_run_id).order_by(
            FUSION_PDF_OCR_RUNS.c.cree_le.desc(), FUSION_PDF_OCR_RUNS.c.ocr_run_id,
        ).limit(limite)).mappings()
        return [_vue(_run(cnx, row["ocr_run_id"])) for row in rows]
