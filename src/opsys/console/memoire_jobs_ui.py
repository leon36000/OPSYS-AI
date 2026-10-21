"""Pilotage humain des jobs M10 de développement; cette UI ne lance jamais le worker."""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping
from datetime import date
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from starlette.concurrency import run_in_threadpool

from opsys import stockage
from opsys.console import memoire_ui, pages
from opsys.console.memoire_api import _repository

_JOB_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
_MAX_FUSEAU_CHARS = 64
_JOB_PUBLIC = frozenset({
    "job_id", "principal", "domain", "active", "version", "fuseau", "premier_jour", "limits",
    "backlog", "next_slot", "last_report",
})
_LAST_REPORT_PUBLIC = frozenset({"report_id", "slot", "status", "observed_at", "grant_version"})


def _public_job(job: Mapping[str, Any]) -> dict[str, Any]:
    result = {key: job[key] for key in _JOB_PUBLIC if key in job}
    if isinstance(result.get("last_report"), Mapping):
        result["last_report"] = {
            key: result["last_report"][key]
            for key in _LAST_REPORT_PUBLIC
            if key in result["last_report"]
        }
    return result


def contenu(jobs: list[Mapping[str, Any]], *, prefixe: str, csrf: str) -> str:
    """Vue HTML avec échappement systématique et sans credential ni empreinte de capacité."""
    body = [
        '<section class="carte pile"><h2>Consolidation planifiée</h2>',
        "<p>Un grant actif n’installe pas un ordonnanceur et ne lance aucun job. La planification Core "
        "n’est pas vérifiée ici. Après toute autorisation ou tout renouvellement, préparez explicitement "
        "la déclaration avec <code>opsys-metier memoire-developpement configurer-cron --job-id ID</code>; "
        "cela ne prouve pas l’installation de la tâche.</p>",
        f'<form method="post" action="{pages.e(prefixe)}/memoire/consolidation">',
        f'<input type="hidden" name="csrf" value="{pages.e(csrf)}">',
        (
            '<label>Identifiant du job<input name="job_id" maxlength="80" '
            'pattern="[a-z0-9][a-z0-9._-]{0,79}" required></label>'
        ),
        '<label>Fuseau<select name="fuseau"><option>America/Toronto</option><option>UTC</option></select></label>',
        '<button type="submit">Autoriser ce job</button></form></section>',
    ]
    if not jobs:
        body.append('<section class="carte"><p>Aucun job de consolidation autorisé.</p></section>')
    for job in jobs:
        ident = pages.e(job.get("job_id", ""))
        active = bool(job.get("active"))
        dernier = job.get("last_report") or {}
        body.append(
            '<section class="carte pile">'
            f"<h2>Job {ident}</h2>"
            f"<p>État : {pages.e('actif' if active else 'révoqué')} · domaine : {pages.e(job.get('domain', ''))}</p>"
            f"<p>Depuis : {pages.e(job.get('premier_jour', ''))} · fuseau : {pages.e(job.get('fuseau', ''))} · "
            f"prochain créneau : {pages.e(job.get('next_slot', ''))}"
            f" · backlog : {pages.e(job.get('backlog', ''))}</p>"
        )
        if dernier:
            body.append(
                f"<p>Dernier rapport : {pages.e(dernier.get('status', ''))} · "
                f"créneau {pages.e(dernier.get('slot', ''))} · observé le "
                f"{pages.e(dernier.get('observed_at', ''))}</p>"
                f'<p><a href="{pages.e(prefixe)}/memoire/consolidation/{ident}/rapport">Lire le rapport</a></p>'
            )
        else:
            body.append("<p>Aucun rapport enregistré.</p>")
        if active:
            body.extend([
                f'<form method="post" action="{pages.e(prefixe)}/memoire/consolidation/{ident}/revoquer">',
                f'<input type="hidden" name="csrf" value="{pages.e(csrf)}">',
                '<button type="submit">Révoquer</button></form>',
            ])
        body.append("</section>")
    return "".join(body)


def rapport_contenu(payload: Mapping[str, Any], *, prefixe: str) -> str:
    report = payload.get("report") if isinstance(payload, Mapping) else None
    if not isinstance(report, Mapping):
        return (
            '<section class="carte pile"><h2>Rapport de consolidation</h2>'
            "<p>Aucun rapport n’a encore été enregistré pour ce job.</p>"
            f'<p><a href="{pages.e(prefixe)}/memoire/consolidation">Retour aux jobs</a></p></section>'
        )
    audit = report.get("audit") if isinstance(report.get("audit"), Mapping) else {}
    flags = ("domain", "analyzer_version", "observed_at", "commit", "input_head")
    facts = "".join(f"<li>{pages.e(key.replace('_', ' '))} : {pages.e(report.get(key, ''))}</li>" for key in flags)
    limits = report.get("limits") if isinstance(report.get("limits"), Mapping) else {}
    caps_html = "".join(
        f"<li>{pages.e(key.replace('_', ' '))} : {pages.e(value)}</li>" for key, value in limits.items()
    )
    coverage = report.get("coverage") if isinstance(report.get("coverage"), Mapping) else {}
    coverage_html = "".join(
        f"<li>{pages.e(key.replace('_', ' '))} : {pages.e(value)}</li>" for key, value in coverage.items()
    )
    self_model = report.get("self_model") if isinstance(report.get("self_model"), Mapping) else {}
    model_parts = [
        f"<p>Identité : {pages.e(self_model.get('identity', 'inconnue'))} · "
        f"complétion : {pages.e(self_model.get('completion', 'inconnue'))}</p>"
    ]
    modules = self_model.get("modules", [])
    for module in modules if isinstance(modules, list) else []:
        if not isinstance(module, Mapping):
            continue
        model_parts.append(
            f"<article><h4>Module {pages.e(module.get('module', 'inconnu'))} · "
            f"{pages.e(module.get('state', 'inconnu'))}</h4><ul>"
        )
        proofs = module.get("proofs", [])
        for proof in proofs if isinstance(proofs, list) else []:
            if isinstance(proof, Mapping):
                fields = (
                    "source_ref", "event_id", "path", "indexed_sha256", "observed_sha256", "freshness", "scope"
                )
                proof_values = []
                for key in fields:
                    if key not in proof:
                        continue
                    value = proof[key]
                    if key == "observed_sha256" and value is None:
                        value = "non lu / inconnu"
                    proof_values.append(f"{pages.e(key.replace('_', ' '))} : {pages.e(value)}")
                model_parts.append("<li>" + " · ".join(proof_values) + "</li>")
        model_parts.append("</ul></article>")
    for key, label in (("mission", "Mission"), ("tools_and_permissions", "Outils et permissions")):
        item = self_model.get(key)
        if isinstance(item, Mapping):
            model_parts.append(
                f"<p>{pages.e(label)} — état : {pages.e(item.get('state', 'inconnu'))}; "
                f"raison : {pages.e(item.get('reason', ''))}</p>"
            )
            refs = item.get("source_refs", [])
            if isinstance(refs, list):
                model_parts.append("<ul>" + "".join(f"<li>{pages.e(ref)}</li>" for ref in refs) + "</ul>")
    model_limits = self_model.get("limits", [])
    if isinstance(model_limits, list):
        model_parts.append("<h4>Limites du modèle de soi</h4><ul>" + "".join(
            f"<li>{pages.e(item)}</li>" for item in model_limits
        ) + "</ul>")
    freshness = audit.get("freshness") if isinstance(audit.get("freshness"), Mapping) else {}
    freshness_html = "".join(
        f"<li>{pages.e(key.replace('_', ' '))} : {pages.e(value)}</li>" for key, value in freshness.items()
    )
    audit_visible = dict(audit)
    audit_visible.pop("repository", None)
    audit_html = memoire_ui.audit_contenu(audit_visible, prefixe)
    return (
        '<section class="carte pile"><h2>Rapport de consolidation</h2><ul>' + facts + "</ul>"
        "<h3>Caps et couverture</h3><ul>" + caps_html + coverage_html + "</ul>"
        f"<h3>Modèle de soi : déclaré, observé et inconnu</h3>{''.join(model_parts)}"
        f"<h3>Fraîcheur, omissions et périmètre</h3><ul>{freshness_html}</ul>{audit_html}"
        f'<p><a href="{pages.e(prefixe)}/memoire/consolidation">Retour aux jobs</a></p></section>'
    )


def _objets(data: Any, champs: set[str], *, optionnels: set[str] = frozenset()) -> Mapping[str, Any]:
    if not isinstance(data, dict) or not champs <= set(data) or set(data) - (champs | optionnels):
        raise HTTPException(400, "champs de job invalides")
    return data


def _credential_path(job_id: str, *, version: int = 1) -> Path:
    if _JOB_ID.fullmatch(job_id) is None:
        raise HTTPException(400, "identifiant de job invalide")
    if type(version) is not int or version < 1:
        raise HTTPException(400, "version de credential invalide")
    name = f"{job_id}.json" if version == 1 else f"{job_id}-v{version}.json"
    return stockage.dossier_opsys() / "secrets" / "memoire-jobs" / name


def _assurer_dossier_credential(path: Path) -> None:
    """Crée les deux sous-dossiers privés après autorisation, sans suivre aucun lien symbolique."""
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
        raise HTTPException(400, "credentials OS protégés indisponibles")
    absolute = Path(os.path.abspath(path))
    if ".." in path.parts:
        raise HTTPException(400, "chemin de credential invalide")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(absolute.anchor, flags)
    try:
        parts = absolute.parts[1:]
        for index, component in enumerate(parts[:-1]):
            try:
                suivant = os.open(component, flags, dir_fd=descriptor)
            except FileNotFoundError:
                # OPSYS_HOME doit déjà exister; seuls secrets/ et memoire-jobs/ sont créés ici.
                if index < len(parts) - 3 or component not in {"secrets", "memoire-jobs"}:
                    raise HTTPException(400, "racine OPSYS_HOME absente ou invalide") from None
                os.mkdir(component, 0o700, dir_fd=descriptor)
                suivant = os.open(component, flags, dir_fd=descriptor)
            info = os.fstat(suivant)
            home_index = len(parts) - 4
            private_index = len(parts) - 3
            if index == home_index and (info.st_uid != os.geteuid() or info.st_mode & 0o022):
                os.close(suivant)
                raise HTTPException(400, "OPSYS_HOME non détenu ou modifiable par un tiers")
            if index >= private_index and (info.st_uid != os.geteuid() or info.st_mode & 0o077):
                os.close(suivant)
                raise HTTPException(400, "répertoire de credential non privé")
            os.close(descriptor)
            descriptor = suivant
    except OSError as exc:
        raise HTTPException(400, "chemin de credential inaccessible ou symlink") from exc
    finally:
        os.close(descriptor)


def creer_router(
    *,
    session_api: Callable[[Request], Any],
    ecriture_api: Callable[[Request], Any],
    session_page: Callable[[Request], Any],
    objet_json: Callable[[Request], Any],
    formulaire: Callable[[Request], Any],
    verifier_formulaire: Callable[[Mapping[str, str], Any], None],
    appeler_memoire: Callable[..., Any],
    prefixe: str,
) -> APIRouter:
    router = APIRouter()

    def worker():
        from m10_memoire import consolidation_developpement as jobs

        return jobs

    def verifier_query(request: Request, permis: frozenset[str] = frozenset()) -> str | None:
        items = request.query_params.multi_items()
        keys = [key for key, _ in items]
        if len(items) > len(permis) or any(key not in permis for key in keys):
            raise HTTPException(400, "paramètres de lecture de job invalides")
        if len(keys) != len(set(keys)):
            raise HTTPException(400, "paramètres répétés interdits")
        return request.query_params.get("report_id") if "report_id" in permis else None

    def appeler_job(session: Any, action: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        try:
            return appeler_memoire(session, action, *args, **kwargs)
        except worker().BackendConsolidationNonPrisEnCharge as exc:
            raise HTTPException(409, "backend non pris en charge : les jobs exigent SQLite fichier") from exc
        except worker().AccesConsolidationRefuse as exc:
            raise HTTPException(403, "accès au job de consolidation refusé") from exc
        except worker().ConflitJob as exc:
            raise HTTPException(409, "état du job de consolidation en conflit") from exc

    async def autoriser_grant(
        session: Any, job_id: str, zone: str, first_day: str | None, limits: dict[str, int]
    ) -> dict[str, Any]:
        jobs = await run_in_threadpool(appeler_job, session, worker().lister_jobs)
        previous = next((job for job in jobs if job.get("job_id") == job_id), None)
        if previous is not None and previous.get("active"):
            raise HTTPException(409, "ce job possède déjà une autorisation active")
        version = 1 if previous is None else previous["version"] + 1
        credential = _credential_path(job_id, version=version)
        _assurer_dossier_credential(credential)
        try:
            grant = await run_in_threadpool(
                appeler_job, session, worker().autoriser, job_id, _repository(), credential,
                fuseau=zone, premier_jour=first_day, limites=limits,
            )
        except FileExistsError as exc:
            raise HTTPException(409, "un credential existe déjà pour cette version") from exc
        except OSError as exc:
            raise HTTPException(400, "credential de job inaccessible") from exc
        public = _public_job(grant)
        return {**public, "configuration_core_a_regenerer": True}

    @router.get("/memoire/consolidation")
    def page_jobs(request: Request) -> HTMLResponse:
        session = session_page(request)
        jobs = appeler_job(session, worker().lister_jobs)
        html = pages.gabarit(
            "Consolidation planifiée", contenu(jobs, prefixe=prefixe, csrf=session.csrf),
            prefixe=prefixe, session=session, actif="memoire",
        )
        return HTMLResponse(html)

    @router.get("/api/memoire-developpement/jobs")
    def liste_jobs(request: Request) -> dict[str, Any]:
        session = session_api(request)
        verifier_query(request)
        return {"jobs": [_public_job(item) for item in appeler_job(session, worker().lister_jobs)]}

    @router.get("/api/memoire-developpement/jobs/{job_id}")
    def lire_job(job_id: str, request: Request) -> dict[str, Any]:
        session = session_api(request)
        verifier_query(request)
        _credential_path(job_id)
        try:
            return _public_job(appeler_job(session, worker().lire_statut, job_id))
        except ValueError as exc:
            raise HTTPException(404, "job inconnu") from exc

    @router.get("/api/memoire-developpement/jobs/{job_id}/rapport")
    def lire_rapport(job_id: str, request: Request, report_id: str | None = None) -> dict[str, Any]:
        session = session_api(request)
        _credential_path(job_id)
        report_id = verifier_query(request, frozenset({"report_id"}))
        if report_id is not None and (
            not report_id or len(report_id) > 128 or not re.fullmatch(r"[a-f0-9]+", report_id)
        ):
            raise HTTPException(400, "identifiant de rapport invalide")
        try:
            entry = appeler_job(session, worker().lire_rapport, job_id, report_id)
        except ValueError as exc:
            raise HTTPException(404, "job inconnu") from exc
        if entry is None:
            if report_id is not None:
                raise HTTPException(404, "rapport inconnu")
            return {"job_id": job_id, "report": None}
        return {"job_id": job_id, "report_id": entry["report_id"], "report": entry["report"]}

    @router.post("/api/memoire-developpement/jobs")
    async def autoriser_job(request: Request) -> dict[str, Any]:
        session = ecriture_api(request)
        data = _objets(await objet_json(request), {"job_id"}, optionnels={"fuseau", "premier_jour", "limites"})
        job_id = data["job_id"]
        if not isinstance(job_id, str) or _JOB_ID.fullmatch(job_id) is None:
            raise HTTPException(400, "identifiant de job invalide")
        zone = data.get("fuseau", "America/Toronto")
        if not isinstance(zone, str) or not zone or len(zone) > _MAX_FUSEAU_CHARS:
            raise HTTPException(400, "fuseau invalide")
        try:
            ZoneInfo(zone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise HTTPException(400, "fuseau invalide") from exc
        first_day = data.get("premier_jour")
        if first_day is not None and (
            not isinstance(first_day, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", first_day) is None
        ):
            raise HTTPException(400, "premier_jour invalide")
        if first_day is not None:
            try:
                if date.fromisoformat(first_day).isoformat() != first_day:
                    raise ValueError
            except ValueError as exc:
                raise HTTPException(400, "premier_jour invalide") from exc
        worker_limits = worker().LIMITES
        limits = data.get("limites", {})
        if not isinstance(limits, dict) or set(limits) - set(worker_limits):
            raise HTTPException(400, "plafonds invalides")
        for key, value in limits.items():
            if (
                type(value) is not int
                or not 1 <= value <= worker_limits[key]
                or (key == "max_report_bytes" and value < 2048)
            ):
                raise HTTPException(400, "plafonds invalides")
        return await autoriser_grant(session, job_id, zone, first_day, limits)

    @router.post("/api/memoire-developpement/jobs/{job_id}/revoquer")
    async def revoquer_job(job_id: str, request: Request) -> dict[str, Any]:
        session = ecriture_api(request)
        _credential_path(job_id)
        data = await objet_json(request)
        if data:
            raise HTTPException(400, "corps de révocation invalide")
        try:
            return await run_in_threadpool(appeler_job, session, worker().revoquer, job_id)
        except PermissionError as exc:
            raise HTTPException(403, "révocation refusée") from exc
        except ValueError as exc:
            raise HTTPException(404, "job inconnu") from exc

    @router.post("/memoire/consolidation")
    async def autoriser_job_formulaire(request: Request) -> HTMLResponse:
        session = session_page(request)
        fields = await formulaire(request)
        verifier_formulaire(fields, session)
        if set(fields) - {"csrf", "job_id", "fuseau"}:
            raise HTTPException(400, "formulaire de job invalide")
        data = {"job_id": fields.get("job_id"), "fuseau": fields.get("fuseau", "America/Toronto")}
        if (
            not isinstance(data["job_id"], str)
            or _JOB_ID.fullmatch(data["job_id"]) is None
            or not isinstance(data["fuseau"], str)
            or not data["fuseau"]
            or len(data["fuseau"]) > _MAX_FUSEAU_CHARS
        ):
            raise HTTPException(400, "formulaire de job invalide")
        try:
            ZoneInfo(data["fuseau"])
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise HTTPException(400, "formulaire de job invalide") from exc
        await autoriser_grant(session, data["job_id"], data["fuseau"], None, {})
        from fastapi.responses import RedirectResponse

        return RedirectResponse(f"{prefixe}/memoire/consolidation", status_code=303)

    @router.post("/memoire/consolidation/{job_id}/revoquer")
    async def revoquer_job_formulaire(job_id: str, request: Request) -> Any:
        session = session_page(request)
        fields = await formulaire(request)
        verifier_formulaire(fields, session)
        if set(fields) != {"csrf"}:
            raise HTTPException(400, "formulaire de révocation invalide")
        _credential_path(job_id)
        try:
            await run_in_threadpool(appeler_job, session, worker().revoquer, job_id)
        except (PermissionError, ValueError) as exc:
            raise HTTPException(400, "révocation refusée") from exc
        from fastapi.responses import RedirectResponse

        return RedirectResponse(f"{prefixe}/memoire/consolidation", status_code=303)

    @router.get("/memoire/consolidation/{job_id}/rapport")
    def page_rapport(job_id: str, request: Request) -> HTMLResponse:
        session = session_page(request)
        _credential_path(job_id)
        try:
            entry = appeler_job(session, worker().lire_rapport, job_id)
        except ValueError as exc:
            raise HTTPException(404, "job inconnu") from exc
        payload = {"report": None} if entry is None else entry
        return HTMLResponse(pages.gabarit(
            "Rapport de consolidation", rapport_contenu(payload, prefixe=prefixe),
            prefixe=prefixe, session=session, actif="memoire",
        ))

    return router
