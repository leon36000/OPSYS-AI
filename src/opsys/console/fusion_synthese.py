"""Synthèse privée des états de métadonnées Fusion par filière."""

from __future__ import annotations

import datetime as dt
import os
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from .. import fusion_ap, fusion_csv, fusion_pdf
from ..memoire.ingestion_procedures import IngestionProcedures
from ..memoire.store import MemoireEntreprise
from . import pages
from .securite import Session

_ETATS_CSV = frozenset({
    "RECU", "EN_COURS", "PROPOSITIONS", "AUCUNE_PROPOSITION", "REFUSE", "SNAPSHOT_OBSOLETE",
    "ERREUR_REPRENABLE",
})
_ETATS_PDF = frozenset({"RECU", "EXTRAIT_PREPARATOIRE", "REFUSE", "ERREUR_REPRENABLE"})
_ETATS_PROCEDURES = frozenset({"RECU", "INDEXE"})
_ETATS_AP = frozenset({"A_REVALIDER", "INDISPONIBLE"})
_SERIES_MAX = 64
_VERSIONS_MAX = 8
_IMPORTS_M03_MAX = 64
_REFERENCE_IMPORT_M03 = re.compile(r"^[0-9a-f]{64}$")


def lire_procedures() -> IngestionProcedures:
    """Retourne la façade M03 existante pour les séries, versions et imports privés."""
    return MemoireEntreprise(os.environ.get("OPSYS_DATABASE_URL", "")).procedures()


def _entier(valeur: Any, *, minimum: int = 0) -> int:
    if type(valeur) is not int or valeur < minimum:
        raise ValueError("métadonnée de synthèse invalide")
    return valeur


def _liste_mappings(valeur: Any, limite: int) -> list[Mapping[str, Any]]:
    if not isinstance(valeur, Sequence) or isinstance(valeur, (str, bytes)) or len(valeur) > limite:
        raise ValueError("liste de métadonnées invalide")
    if not all(isinstance(item, Mapping) for item in valeur):
        raise ValueError("entrée de métadonnées invalide")
    return list(valeur)


def _compteurs_csv(lots: Any) -> dict[str, int]:
    rows = _liste_mappings(lots, fusion_csv.NB_LOTS_MAX)
    counts = {state: 0 for state in sorted(_ETATS_CSV)}
    rows_done = rows_known = rows_unknown = proposals = 0
    for lot in rows:
        status = lot.get("statut")
        if status not in _ETATS_CSV:
            raise ValueError("état CSV inconnu")
        counts[status] += 1
        cursor = _entier(lot.get("curseur"))
        rows_done += cursor
        total = lot.get("total_lignes")
        if total is None:
            rows_unknown += 1
        else:
            rows_known += _entier(total)
            if cursor > total:
                raise ValueError("curseur CSV hors borne")
        count_proposals = _entier(lot.get("nombre_propositions"))
        if status in {"PROPOSITIONS", "AUCUNE_PROPOSITION"}:
            proposals += count_proposals
    return {
        "lots": len(rows), "recu": counts["RECU"], "en_cours": counts["EN_COURS"],
        "propositions": counts["PROPOSITIONS"], "aucune_proposition": counts["AUCUNE_PROPOSITION"],
        "refuse": counts["REFUSE"], "snapshot_obsolete": counts["SNAPSHOT_OBSOLETE"],
        "erreur_reprenable": counts["ERREUR_REPRENABLE"], "lignes_traitees": rows_done,
        "lignes_totales_connues": rows_known, "lots_total_inconnu": rows_unknown,
        "propositions_potentielles": proposals,
    }


def _compteurs_pdf(lots: Any) -> dict[str, int]:
    rows = _liste_mappings(lots, fusion_pdf.NB_LOTS_MAX)
    counts = {state: 0 for state in sorted(_ETATS_PDF)}
    pages_known = pages_unknown = 0
    for lot in rows:
        status = lot.get("statut")
        if status not in _ETATS_PDF:
            raise ValueError("état PDF inconnu")
        counts[status] += 1
        total = _entier(lot.get("total_pages"))
        if total > 20:
            raise ValueError("nombre de pages PDF hors quota")
        if status == "EXTRAIT_PREPARATOIRE":
            if total < 1:
                raise ValueError("pages PDF absentes après extraction")
            pages_known += total
        elif total != 0:
            raise ValueError("pages PDF non attendues avant extraction")
        if status != "EXTRAIT_PREPARATOIRE":
            pages_unknown += 1
    return {
        "lots": len(rows), "recu": counts["RECU"], "extrait_preparatoire": counts["EXTRAIT_PREPARATOIRE"],
        "refuse": counts["REFUSE"], "erreur_reprenable": counts["ERREUR_REPRENABLE"],
        "pages_extraites_preparatoires": pages_known, "lots_pages_inconnues": pages_unknown,
    }


def _compteurs_ap(brouillons: Any) -> dict[str, int]:
    rows = _liste_mappings(brouillons, fusion_pdf.NB_LOTS_MAX)
    revalidables = indisponibles = 0
    champs = {"lot_id", "revision", "statut", "cree_le", "modifie_le", "etat_source"}
    for row in rows:
        if set(row) != champs or row.get("etat_source") not in _ETATS_AP:
            raise ValueError("métadonnées AP invalides")
        if row["etat_source"] == "A_REVALIDER":
            if row.get("statut") != "A_REVOIR" or type(row.get("revision")) is not int or row["revision"] < 1:
                raise ValueError("métadonnées AP à revalider invalides")
            revalidables += 1
        else:
            indisponibles += 1
    return {"brouillons": len(rows), "a_revalider": revalidables, "indisponibles": indisponibles}


def _compteurs_procedures(service: IngestionProcedures, verifier: Callable[[], None]) -> dict[str, int]:
    verifier()
    first = service.lister_series(limite=50, offset=0)
    total = _entier(first.total)
    if total > _SERIES_MAX:
        raise ValueError("quota séries dépassé")
    series = list(first.series)
    if len(series) != min(50, total):
        raise ValueError("première page de séries incomplète")
    while len(series) < total:
        offset = len(series)
        verifier()
        page = service.lister_series(limite=min(50, total - offset), offset=offset)
        if page.total != total or not page.series:
            raise ValueError("pagination de séries instable")
        series.extend(page.series)
        if len(series) > total:
            raise ValueError("pagination de séries hors borne")
    states = {state: 0 for state in sorted(_ETATS_PROCEDURES)}
    versions_count = active_count = 0
    ids: set[str] = set()
    for serie in series:
        if not isinstance(serie, Mapping):
            raise ValueError("série invalide")
        ident = serie.get("document_id")
        if not isinstance(ident, str) or not ident or ident in ids:
            raise ValueError("identité de série invalide")
        ids.add(ident)
        verifier()
        versions = service.lister_versions(ident)
        if (not isinstance(versions, Sequence) or isinstance(versions, (str, bytes))
                or not versions or len(versions) > _VERSIONS_MAX):
            raise ValueError("versions de procédure invalides")
        actives_serie = 0
        for version in versions:
            state = version.get("etat") if isinstance(version, Mapping) else getattr(version, "etat", None)
            active = version.get("active") if isinstance(version, Mapping) else getattr(version, "active", None)
            if state not in _ETATS_PROCEDURES or type(active) is not bool:
                raise ValueError("état de version invalide")
            states[state] += 1
            active_count += int(active)
            actives_serie += int(active)
        if actives_serie > 1:
            raise ValueError("plusieurs versions actives dans une série")
        versions_count += len(versions)
    return {
        "series": total, "versions": versions_count, "versions_recues": states["RECU"],
        "versions_indexees": states["INDEXE"], "versions_actives": active_count,
    }


def _attribut_import_m03(lot: Any, nom: str) -> Any:
    if isinstance(lot, Mapping):
        return lot.get(nom)
    return getattr(lot, nom, None)


def _compteurs_imports_m03(lots: Any) -> dict[str, int]:
    """Valide et additionne la projection privée des manifestes M03, sans exposer leurs références."""
    if (
        not isinstance(lots, Sequence)
        or isinstance(lots, (str, bytes))
        or len(lots) > _IMPORTS_M03_MAX
    ):
        raise ValueError("liste des imports M03 hors contrat")

    compteurs = {
        "lots": len(lots), "emplacements": 0, "attente": 0, "recu": 0, "indexe": 0, "actifs": 0,
    }
    references: set[str] = set()
    for lot in lots:
        reference = _attribut_import_m03(lot, "reference")
        if not isinstance(reference, str) or not _REFERENCE_IMPORT_M03.fullmatch(reference):
            raise ValueError("référence de lot M03 invalide")
        if reference in references:
            raise ValueError("référence de lot M03 dupliquée")
        references.add(reference)

        nombre = _entier(_attribut_import_m03(lot, "nombre_emplacements"), minimum=1)
        if nombre > 5:
            raise ValueError("nombre d’emplacements M03 hors quota")
        attente = _entier(_attribut_import_m03(lot, "attente"))
        recu = _entier(_attribut_import_m03(lot, "recu"))
        indexe = _entier(_attribut_import_m03(lot, "indexe"))
        actifs = _entier(_attribut_import_m03(lot, "actifs"))
        if attente + recu + indexe != nombre or actifs > indexe:
            raise ValueError("compteurs d’imports M03 incohérents")

        compteurs["emplacements"] += nombre
        compteurs["attente"] += attente
        compteurs["recu"] += recu
        compteurs["indexe"] += indexe
        compteurs["actifs"] += actifs

    if compteurs["attente"] + compteurs["recu"] + compteurs["indexe"] != compteurs["emplacements"]:
        raise ValueError("somme des imports M03 incohérente")
    return compteurs


def _source(
    request: Request,
    lecteur_session: Callable[..., Session],
    acteur: str,
    action: Callable[[], Any],
    convertir: Callable[..., dict[str, int]],
) -> dict[str, Any]:
    def verifier() -> None:
        session = lecteur_session(request)
        if session.utilisateur != acteur:
            raise HTTPException(403, "identité modifiée pendant la lecture")

    verifier()
    try:
        resultat = action()
    except PermissionError as exc:
        verifier()
        raise HTTPException(403, "accès Fusion refusé") from exc
    except Exception:
        verifier()
        return {"etat": "INDISPONIBLE", "observe_le": dt.datetime.now(dt.UTC).isoformat(timespec="seconds")}
    verifier()
    try:
        compteurs = convertir(resultat, verifier)
    except Exception:
        verifier()
        return {"etat": "INDISPONIBLE", "observe_le": dt.datetime.now(dt.UTC).isoformat(timespec="seconds")}
    verifier()
    return {
        "etat": "DISPONIBLE", "observe_le": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "compteurs": compteurs,
    }


def lire_synthese(
    request: Request,
    session_page: Callable[..., Session],
    cnx_factory: Callable[..., Any],
    acteur: str,
) -> dict[str, dict[str, Any]]:
    """Lit chaque autorité séparément; un défaut d’un magasin ne s’affiche jamais comme zéro."""
    return {
        "csv": _source(
            request, session_page, acteur,
            lambda: fusion_csv.lister(cnx_factory, acteur), lambda value, _verify: _compteurs_csv(value),
        ),
        "pdf": _source(
            request, session_page, acteur,
            lambda: fusion_pdf.lister(cnx_factory, acteur, limite=fusion_pdf.NB_LOTS_MAX),
        lambda value, _verify: _compteurs_pdf(value),
        ),
        "ap": _source(
            request, session_page, acteur,
            lambda: fusion_ap.lister_a_revoir(cnx_factory, acteur, limite=fusion_pdf.NB_LOTS_MAX),
            lambda value, _verify: _compteurs_ap(value),
        ),
        "procedures": _source(
            request, session_page, acteur,
            lire_procedures, _compteurs_procedures,
        ),
        "imports_m03": _source(
            request, session_page, acteur,
            lambda: lire_procedures().lister_lots(auteur=acteur),
            lambda value, _verify: _compteurs_imports_m03(value),
        ),
    }


def _compteur(source: Mapping[str, Any], cle: str) -> str:
    compteurs = source.get("compteurs", {})
    return pages.e(compteurs.get(cle, 0)) if isinstance(compteurs, Mapping) else "0"


def _carte(titre: str, source: Mapping[str, Any], lignes: tuple[tuple[str, str], ...], note: str) -> str:
    if source.get("etat") != "DISPONIBLE":
        return (
            f'<section class="carte pile"><h2>{pages.e(titre)}</h2><p>État indisponible</p>'
            "<p>Les compteurs ne sont pas disponibles; ils ne sont pas assimilés à zéro.</p></section>"
        )
    items = "".join(f"<dt>{pages.e(label)}</dt><dd>{_compteur(source, key)}</dd>" for key, label in lignes)
    return (
        f'<section class="carte pile"><h2>{pages.e(titre)}</h2>'
        f'<p>Observé le {pages.e(source.get("observe_le", "inconnu"))} UTC</p><dl>{items}</dl>'
        f"<p>{pages.e(note)}</p></section>"
    )


def _html(synthese: Mapping[str, Mapping[str, Any]], prefixe: str, session: Session) -> str:
    csv = _carte("M5 · CSV bancaire", synthese["csv"], (
        ("lots", "Lots admis"), ("recu", "Reçus"), ("en_cours", "En préparation"),
        ("propositions", "Avec propositions préparatoires"), ("aucune_proposition", "Sans proposition"),
        ("refuse", "Refusés"), ("snapshot_obsolete", "Snapshots périmés"),
        ("erreur_reprenable", "Erreurs reprenables"), ("lignes_traitees", "Lignes traitées"),
        ("lignes_totales_connues", "Lignes totales connues"), ("lots_total_inconnu", "Lots au total inconnu"),
        ("propositions_potentielles", "Propositions potentiellement consultables"),
    ), (
        "Un résultat préparatoire reste à vérifier par une personne. "
        "Les snapshots périmés n’exposent aucune proposition."
    ))
    pdf = _carte("Finance · PDF natif", synthese["pdf"], (
        ("lots", "Lots admis"), ("recu", "Reçus, pages inconnues"),
        ("extrait_preparatoire", "Extraits préparatoires"), ("refuse", "Refusés"),
        ("erreur_reprenable", "Erreurs reprenables"),
        ("pages_extraites_preparatoires", "Pages extraites préparatoires"),
        ("lots_pages_inconnues", "Lots sans nombre de pages connu"),
    ), "Les extraits ne sont pas vérifiés ni comptables.")
    ap = _carte("Finance · Brouillons AP", synthese["ap"], (
        ("brouillons", "Brouillons repérés"), ("a_revalider", "À rouvrir et revalider"),
        ("indisponibles", "Indisponibles, à vérifier"),
    ), "Cette boîte liste des métadonnées préparatoires seulement; le détail revalide la source et les citations.")
    ap += (
        f'<p><a href="{pages.e(prefixe)}/fusion/pdf/ap/a-revoir">'
        "Ouvrir la boîte des brouillons AP</a></p>"
    )
    procedures = _carte("M03 · Procédures internes", synthese["procedures"], (
        ("series", "Séries admises"), ("versions", "Versions"),
        ("versions_recues", "Versions reçues"), ("versions_indexees", "Versions indexées"),
        ("versions_actives", "Versions actives"),
    ), "L’indexation et l’activation ne certifient ni la justesse ni la couverture des procédures.")
    imports_m03 = _carte("Mes imports M03", synthese["imports_m03"], (
        ("lots", "Lots"), ("emplacements", "Emplacements"), ("attente", "En attente"),
        ("recu", "Reçus"), ("indexe", "Indexés"), ("actifs", "Actifs"),
    ), (
        "Ces états de manifestes personnels restent distincts des séries et versions; "
        "ils ne mesurent pas l’assimilation."
    ))
    imports_m03 += (
        f'<p><a href="{pages.e(prefixe)}/memoire/procedures/imports">'
        "Ouvrir Mes imports M03</a></p>"
    )
    return (
        f'<section class="carte pile"><h1>Synthèse des sources et des imports</h1>'
        "<p>Cette page compte séparément les sources admises et les manifestes d’import déclarés; elle ne mesure pas "
        "la couverture de l’entreprise. Les observations ont des heures distinctes et les accès restent séparés.</p>"
        f"{csv}{pdf}{ap}{procedures}{imports_m03}"
        f"<p><a href=\"{pages.e(prefixe)}/fusion-operationnelle\">Retour aux lots CSV</a></p>"
        f'<p><a href="{pages.e(prefixe)}/fusion/pdf">Consulter les lots PDF</a> · '
        f'<a href="{pages.e(prefixe)}/memoire/procedures">Consulter les procédures M03</a></p></section>'
    )


def creer_router(
    *, session_page: Callable[..., Session], prefixe: str, cnx_factory: Callable[..., Any],
) -> APIRouter:
    router = APIRouter()

    @router.get("/fusion-operationnelle/synthese", response_class=HTMLResponse)
    def synthese(request: Request) -> HTMLResponse:
        session = session_page(request)
        if request.query_params:
            raise HTTPException(400, "paramètres de synthèse invalides")
        resume = lire_synthese(request, session_page, cnx_factory, session.utilisateur)
        session_finale = session_page(request)
        if session_finale.utilisateur != session.utilisateur:
            raise HTTPException(403, "identité modifiée pendant la lecture")
        session = session_finale
        body = pages.gabarit("Synthèse des sources et des imports", _html(resume, prefixe, session), prefixe=prefixe,
                             session=session, actif="fusion")
        return HTMLResponse(body, headers={"Cache-Control": "private, no-store, max-age=0"})

    return router
