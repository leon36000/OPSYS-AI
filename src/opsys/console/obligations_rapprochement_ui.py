"""Formulaire HTML privé de rapprochement paie/DAS; aucun endpoint public ni calcul financier."""
from __future__ import annotations

import re
import secrets
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import Connection
from starlette.concurrency import run_in_threadpool

from opsys import identite
from opsys.console import pages, securite
from opsys.console.securite import Session

_MAX_OPTIONS = 200
_HEX32 = re.compile(r"^[a-f0-9]{32}$")
_HEX64 = re.compile(r"^[a-f0-9]{64}$")
_MONTANT = re.compile(r"^(?:0|[1-9][0-9]{0,8})\.[0-9]{2}$")
_CHAMPS = frozenset({
    "action", "obligation_id", "source_ref", "montant_cad", "revision_attendue",
    "snapshot_id_attendu", "mutation_id", "csrf",
})
_MODES = {"LEGACY_IDENTIQUE", "NOUVELLE_COMPOSANTE", "PROVISION_CREDIT", "PROVISION_HORS_PAIE"}


def _finance_active(cnx: Connection, session: Session) -> identite.Personne:
    personne = identite.personne_active(cnx, session.utilisateur)
    if personne is None or not (personne.roles & {"finance", "nathan_owner"}):
        raise HTTPException(403, "accès financier privé refusé")
    return personne


def _sans_query(request: Request) -> None:
    if request.query_params:
        raise HTTPException(400, "aucun paramètre de requête accepté")


def _form(data: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(data, Mapping) or set(data) != _CHAMPS:
        raise HTTPException(400, "champs du rapprochement invalides")
    result: dict[str, str] = {}
    for key in _CHAMPS:
        value = data.get(key)
        if not isinstance(value, str) or len(value) > 256:
            raise HTTPException(400, "valeur du rapprochement invalide")
        result[key] = value
    if result["action"] not in _MODES:
        raise HTTPException(400, "action de rapprochement invalide")
    if result["obligation_id"] and not _HEX32.fullmatch(result["obligation_id"]):
        raise HTTPException(400, "référence d'obligation invalide")
    if not _HEX64.fullmatch(result["snapshot_id_attendu"]):
        raise HTTPException(400, "snapshot financier invalide")
    if not re.fullmatch(r"0|[1-9][0-9]{0,5}", result["revision_attendue"]):
        raise HTTPException(400, "révision invalide")
    if not _HEX32.fullmatch(result["mutation_id"]):
        raise HTTPException(400, "identifiant de mutation invalide")
    if not _MONTANT.fullmatch(result["montant_cad"]):
        raise HTTPException(400, "montant au centime requis")
    return result


def _montant_source(capture: Any, mode: str, source_ref: str, montant_form: str) -> tuple[str, str, str]:
    sources = capture.sources
    if not isinstance(sources, Mapping) or set(sources) != {"legacy", "provisions"}:
        raise HTTPException(409, "sources financières indisponibles")
    if mode == "LEGACY_IDENTIQUE":
        source = sources["legacy"].get(source_ref)
        if (not isinstance(source, Mapping) or source_ref not in {"paies", "das"}
                or not isinstance(source.get("sha256"), str) or not _HEX64.fullmatch(source["sha256"])):
            raise HTTPException(409, "déclaration legacy absente du snapshot")
        return "legacy", source_ref, source["sha256"]
    if mode in {"PROVISION_CREDIT", "PROVISION_HORS_PAIE"}:
        source = sources["provisions"].get(source_ref)
        if (not isinstance(source, Mapping) or not isinstance(source.get("sha256"), str)
                or not _HEX64.fullmatch(source["sha256"])
                or not isinstance(source.get("montant_cad"), str)
                or not _MONTANT.fullmatch(source["montant_cad"])):
            raise HTTPException(409, "provision absente du snapshot")
        if mode == "PROVISION_HORS_PAIE" and montant_form != source["montant_cad"]:
            raise HTTPException(409, "montant de provision périmé; rechargez la page")
        return "provision", source_ref, source["sha256"]
    if mode == "NOUVELLE_COMPOSANTE":
        if source_ref:
            raise HTTPException(400, "aucune source legacy ne doit être sélectionnée")
        return "none", "", "0" * 64
    raise HTTPException(400, "mode invalide")


def _options_sources(capture: Any) -> tuple[str, str, int]:
    sources = capture.sources
    legacy = sources.get("legacy", {}) if isinstance(sources, Mapping) else {}
    provisions = sources.get("provisions", {}) if isinstance(sources, Mapping) else {}
    if (not isinstance(legacy, Mapping) or not isinstance(provisions, Mapping)
            or set(legacy) - {"paies", "das"}
            or any(not isinstance(ref, str) or not _HEX64.fullmatch(ref) for ref in provisions)):
        raise HTTPException(409, "catalogue de sources invalide")
    count = len(legacy) + len(provisions)
    if count > _MAX_OPTIONS:
        return "", "", count
    if any(not isinstance(item, Mapping) or not isinstance(item.get("montant_cad"), str)
           or not _MONTANT.fullmatch(item["montant_cad"]) or not isinstance(item.get("sha256"), str)
           or not _HEX64.fullmatch(item["sha256"]) for item in [*legacy.values(), *provisions.values()]):
        raise HTTPException(409, "catalogue de montants invalide")
    legacy_options = "".join(
        f'<option value="{pages.e(ref)}">Déclaration historique {pages.e(ref)} — '
        f'{pages.e(item.get("montant_cad"))} CAD</option>'
        for ref, item in sorted(legacy.items())
    )
    provision_options = "".join(
        f'<option value="{pages.e(ref)}">Provision {pages.e(ref)} — '
        f'{pages.e(item.get("montant_cad"))} CAD</option>'
        for ref, item in sorted(provisions.items())
    )
    return legacy_options, provision_options, count


def _page(session: Session, capture: Any, projection: Mapping[str, Any], *, prefixe: str) -> HTMLResponse:
    legacy_options, provision_options, source_count = _options_sources(capture)
    snapshot_id = projection.get("finance_snapshot_id")
    digest = projection.get("obligations_sha256")
    revision = projection.get("revision")
    can_write = bool(isinstance(snapshot_id, str) and _HEX64.fullmatch(snapshot_id)
                     and isinstance(digest, str) and _HEX64.fullmatch(digest)
                     and type(revision) is int)
    reasons = projection.get("raisons", [])
    if not isinstance(reasons, list) or any(not isinstance(reason, str) for reason in reasons):
        reasons = ["État du rapprochement illisible"]
    reasons_html = "".join(f"<li>{pages.e(reason)}</li>" for reason in reasons)
    obligations = projection.get("obligations_actives", [])
    if not isinstance(obligations, list):
        obligations = []
    under_limit = source_count <= _MAX_OPTIONS and len(obligations) <= _MAX_OPTIONS
    can_write = can_write and under_limit
    rows = []
    if isinstance(obligations, list):
        for item in obligations[:_MAX_OPTIONS]:
            if not isinstance(item, Mapping) or not isinstance(item.get("obligation"), Mapping):
                continue
            obligation = item["obligation"]
            oid, kind, amount = item.get("id"), obligation.get("type"), obligation.get("montant_cad")
            if not isinstance(oid, str) or not _HEX32.fullmatch(oid) or kind not in {"paies", "das"}:
                continue
            rows.append(
                "<tr>" + f"<td>{pages.e(oid)}</td><td>{pages.e(kind)}</td>"
                + f"<td>{pages.e(obligation.get('periode_debut'))} au {pages.e(obligation.get('periode_fin'))}</td>"
                + f"<td>{pages.e(amount)} CAD</td><td>{pages.e(obligation.get('date_paie'))}</td>"
                + f"<td>{pages.e(obligation.get('echeance'))}</td></tr>"
            )
            if not can_write:
                continue
            common = (
                f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">'
                f'<input type="hidden" name="obligation_id" value="{pages.e(oid)}">'
                f'<input type="hidden" name="revision_attendue" value="{revision}">'
                f'<input type="hidden" name="snapshot_id_attendu" value="{pages.e(snapshot_id)}">'
                f'<input type="hidden" name="mutation_id" value="{secrets.token_hex(16)}">'
            )
            for mode in ("LEGACY_IDENTIQUE", "NOUVELLE_COMPOSANTE"):
                if mode == "LEGACY_IDENTIQUE" and kind not in capture.sources["legacy"]:
                    continue
                if mode == "NOUVELLE_COMPOSANTE" and kind in capture.sources["legacy"]:
                    continue
                source_ref = kind if mode == "LEGACY_IDENTIQUE" else ""
                rows.append(
                    f'<tr><td colspan="6"><form method="post" action="{pages.e(prefixe)}/finance/paie/rapprochements">'
                    + common + f'<input type="hidden" name="action" value="{mode}">'
                    + f'<input type="hidden" name="source_ref" value="{pages.e(source_ref)}">'
                    + f'<input type="hidden" name="montant_cad" value="{pages.e(amount)}">'
                    + f'<button type="submit">Confirmer {pages.e(mode)} — {pages.e(oid)}</button></form></td></tr>'
                )
            if capture.sources["provisions"]:
                rows.append(
                    f'<tr><td colspan="6"><form method="post" action="{pages.e(prefixe)}/finance/paie/rapprochements">'
                    + common + '<input type="hidden" name="action" value="PROVISION_CREDIT">'
                + '<label>Provision à rapprocher<select name="source_ref" required>'
                + provision_options + '</select></label>'
                + '<label>Crédit déclaré CAD<input name="montant_cad" inputmode="decimal" '
                + f'value="{pages.e(amount)}" required></label>'
                    + '<button type="submit">Déclarer le crédit plafonné</button></form></td></tr>'
                )
    provisions = capture.sources.get("provisions", {}) if isinstance(capture.sources, Mapping) else {}
    if can_write and under_limit:
        for ref, source in sorted(provisions.items()):
            rows.append(
                '<tr><td colspan="6"><form method="post" '
                f'action="{pages.e(prefixe)}/finance/paie/rapprochements">'
                f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">'
                '<input type="hidden" name="obligation_id" value="">'
                f'<input type="hidden" name="revision_attendue" value="{revision}">'
                f'<input type="hidden" name="snapshot_id_attendu" value="{pages.e(snapshot_id)}">'
                f'<input type="hidden" name="mutation_id" value="{secrets.token_hex(16)}">'
                f'<input type="hidden" name="montant_cad" value="{pages.e(source["montant_cad"])}">'
                '<input type="hidden" name="action" value="PROVISION_HORS_PAIE">'
                f'<input type="hidden" name="source_ref" value="{pages.e(ref)}">'
                f'<button type="submit">Classer hors paie/DAS : {pages.e(ref)} '
                f'({pages.e(source["montant_cad"])} CAD)</button></form></td></tr>'
            )
    message_limite = (
        f"Le snapshot contient {source_count} sources et {len(obligations)} obligations; la limite d'écran "
        f"est {_MAX_OPTIONS}. Les sources au-delà de la limite ne sont pas affichées et aucune écriture "
        "n'est proposée. Le snapshot financier complet reste contrôlé côté serveur."
        if not under_limit else ""
    )
    status = projection.get("statut", "INCONNU")
    montant = projection.get("montant_utilisable")
    cash = format(montant, ".2f") if isinstance(montant, Decimal) and montant.is_finite() else "non calculable"

    content = (
        '<section class="carte pile"><h1>Rapprocher les déclarations paie/DAS</h1>'
        f'<p>Cash libre privé rapproché (CAD) : {pages.e(cash)}.</p>'
        '<p>Action humaine privée uniquement. Elle ne confirme ni paiement bancaire, ni paie nette, ni déclaration. '
        'Le snapshot est capturé à nouveau et toute modification bloque le rapprochement.</p>'
        f'<p>État actuel : {pages.e(status)}; révision du journal : {pages.e(revision)}; '
        f'ID du snapshot : {pages.e(snapshot_id)}.</p>'
        + (f'<p class="message message-erreur">{pages.e(message_limite)}</p>' if message_limite else "")
        + ('<ul>' + reasons_html + '</ul>' if reasons_html else "")
        + '<table><thead><tr><th>ID privé</th><th>Type</th><th>Période</th><th>Montant déclaré</th>'
        '<th>Date de paie</th><th>Échéance</th></tr></thead><tbody>' + "".join(rows) + '</tbody></table>'
        + ("" if can_write else '<p class="message message-erreur">Snapshot indisponible; aucune mutation permise.</p>')
        + '</section>'
    )
    return HTMLResponse(
        pages.gabarit("Rapprochements paie/DAS privés", content, prefixe=prefixe, session=session, actif="finance"),
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


def creer_router(
    *, session_page: Callable[..., Session], formulaire: Callable[[Request], Any],
    cnx_factory: Callable[[], Any], journal: Any, finance_snapshot: Any, prefixe: str,
) -> APIRouter:
    """Router uniquement HTML humain; la console doit le monter explicitement séparément des APIs publiques."""
    router = APIRouter(tags=["rapprochement paie/DAS privé"])

    def capturer(cnx: Connection, session: Session):
        _finance_active(cnx, session)
        try:
            capture = finance_snapshot.capturer_snapshot_prive(cnx)
            projection = journal.lire_rapprochements(cnx, capture.snapshot_builder)
            vue = finance_snapshot.calculer_capture_privee(capture, projection)
        except Exception as exc:
            if isinstance(exc, HTTPException):
                raise
            raise HTTPException(409, "snapshot financier ou journal privé indisponible") from None
        _finance_active(cnx, session)  # après toute lecture/déchiffrement avant rendu ou action
        return capture, vue

    @router.get("/finance/paie/rapprochements", response_class=HTMLResponse)
    def page_privee(request: Request) -> HTMLResponse:
        session = session_page(request, administrateur=False)
        _sans_query(request)
        with cnx_factory() as cnx:
            capture, vue = capturer(cnx, session)
        return _page(session, capture, vue, prefixe=prefixe)

    def ecrire_rapprochement(session: Session, data: dict[str, str]) -> None:
        mode = data["action"]
        if mode == "PROVISION_HORS_PAIE":
            if data["obligation_id"]:
                raise HTTPException(400, "aucune obligation privée attendue")
            target = None
        else:
            if not data["obligation_id"]:
                raise HTTPException(400, "obligation privée requise")
            target = data["obligation_id"]
        with cnx_factory() as cnx:
            personne = _finance_active(cnx, session)
            try:
                capture = finance_snapshot.capturer_snapshot_prive(cnx)
            except Exception:
                raise HTTPException(409, "snapshot financier indisponible") from None
            source_kind, source_ref, source_hash = _montant_source(
                capture, mode, data["source_ref"], data["montant_cad"],
            )
            if mode == "PROVISION_HORS_PAIE":
                data["montant_cad"] = capture.sources["provisions"][source_ref]["montant_cad"]

            def verifier_acteur(cnx_courant: Connection, acteur: str) -> None:
                if acteur != session.utilisateur or acteur != personne.identifiant:
                    raise HTTPException(403, "acteur financier modifié")
                verifier_sources = getattr(capture, "verifier_sources_courantes", None)
                try:
                    sources_courantes = callable(verifier_sources) and verifier_sources()
                except Exception:
                    sources_courantes = False
                if not sources_courantes:
                    raise HTTPException(409, "sources financières modifiées; rechargez la page")
                _finance_active(cnx_courant, session)  # dernier contrôle d'autorité avant append

            payload = {
                "obligation_id": target, "mode": mode, "source_kind": source_kind,
                "source_ref": source_ref, "source_sha256": source_hash, "montant_cad": data["montant_cad"],
            }
            try:
                journal.rapprocher(
                    cnx, payload, snapshot=capture.snapshot_builder,
                    revision_attendue=int(data["revision_attendue"]),
                    snapshot_id_attendu=data["snapshot_id_attendu"], mutation_id=data["mutation_id"],
                    confirme_par=personne.identifiant,
                    confirme_le=datetime.now(UTC).isoformat(timespec="seconds"),
                    verifier_acteur=verifier_acteur,
                )
            except journal.RefusObligation:
                raise HTTPException(409, "source, obligation ou snapshot modifié; rechargez la page") from None

    @router.post("/finance/paie/rapprochements", response_class=HTMLResponse)
    async def rapprocher_formulaire(request: Request):
        session = session_page(request, administrateur=False)
        _sans_query(request)
        with cnx_factory() as cnx:
            _finance_active(cnx, session)
        raw = await formulaire(request)
        if not isinstance(raw, Mapping) or set(raw) != _CHAMPS:
            raise HTTPException(400, "champs du rapprochement invalides")
        if not isinstance(raw.get("csrf"), str) or not securite.csrf_valide(raw.get("csrf"), session):
            raise HTTPException(403, "jeton CSRF absent ou invalide")
        data = _form(raw)
        await run_in_threadpool(ecrire_rapprochement, session, data)
        return RedirectResponse(
            f"{prefixe}/finance/paie/rapprochements", status_code=303,
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )

    return router
