"""Prévisualisation privée des rapprochements bancaires CAD.

Le fichier bancaire ne quitte pas la requête : seul le callback interne de l'application lit le
snapshot M5, exécute le moteur pur et écrit la projection épurée dans le registre distinct.
Les requêtes ont des erreurs 400 (structure), 403 (autorisation), 409 (refus métier) ou 413
(limite globale du corps).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from . import pages, securite
from .banque_metier import RapprochementErreur
from .securite import Session

_CHAMPS = frozenset({"mutation_id", "compte_interne_id", "devise", "mapping_colonnes", "csv_utf8"})
_CHAMPS_MAPPING = frozenset({"date", "montant", "reference_facture"})


def _demande(data: Mapping[str, Any]) -> dict[str, Any]:
    if set(data) != _CHAMPS:
        raise HTTPException(400, "champs de rapprochement invalides")
    mutation_id = data.get("mutation_id")
    compte_id = data.get("compte_interne_id")
    devise = data.get("devise")
    csv_utf8 = data.get("csv_utf8")
    mapping = data.get("mapping_colonnes")
    if not isinstance(mutation_id, str) or not mutation_id.strip() or len(mutation_id) > 128:
        raise HTTPException(400, "mutation_id invalide")
    if not isinstance(compte_id, str) or not compte_id.strip() or len(compte_id) > 64:
        raise HTTPException(400, "compte_interne_id invalide")
    if devise != "CAD":
        raise HTTPException(400, "seuls les relevés CAD sont pris en charge")
    if not isinstance(csv_utf8, str):
        raise HTTPException(400, "csv_utf8 doit être une chaîne")
    if not isinstance(mapping, Mapping) or set(mapping) != _CHAMPS_MAPPING:
        raise HTTPException(400, "mapping_colonnes invalide")
    if any(not isinstance(value, str) or not value for value in mapping.values()):
        raise HTTPException(400, "mapping_colonnes invalide")
    try:
        mutation_id.encode("utf-8", errors="strict")
        compte_id.encode("utf-8", errors="strict")
        for value in mapping.values():
            value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise HTTPException(400, "champs de rapprochement non UTF-8") from exc
    return {
        "mutation_id": mutation_id.strip(),
        "compte_interne_id": compte_id.strip(),
        "devise": devise,
        "mapping_colonnes": dict(mapping),
        "csv_utf8": csv_utf8,
    }


def _form_demande(data: Mapping[str, Any]) -> dict[str, Any]:
    champs = {
        "csrf",
        "mutation_id",
        "compte_interne_id",
        "devise",
        "csv_utf8",
        *(f"mapping_{key}" for key in _CHAMPS_MAPPING),
    }
    if set(data) != champs:
        raise HTTPException(400, "champs de formulaire invalides")
    if not isinstance(data.get("csrf"), str):
        raise HTTPException(403, "jeton CSRF absent ou invalide")
    return _demande(
        {
            "mutation_id": data.get("mutation_id"),
            "compte_interne_id": data.get("compte_interne_id"),
            "devise": data.get("devise"),
            "csv_utf8": data.get("csv_utf8"),
            "mapping_colonnes": {key: data.get(f"mapping_{key}") for key in _CHAMPS_MAPPING},
        }
    )


def _resultat_html(reponse: Mapping[str, Any]) -> str:
    enveloppe = reponse.get("resultat")
    if not isinstance(enveloppe, Mapping):
        return '<section class="carte pile"><h2>Prévisualisation refusée</h2><p>Réponse invalide.</p></section>'
    if enveloppe.get("accepte") is not True:
        verdict = enveloppe.get("verdict")
        code = verdict.get("code") if isinstance(verdict, Mapping) else "REFUS"
        detail = verdict.get("detail") if isinstance(verdict, Mapping) else "Aucun rapprochement n'a été produit."
        return (
            '<section class="carte pile"><h2>Prévisualisation refusée</h2>'
            f"<p><code>{pages.e(str(code))}</code> — {pages.e(str(detail))}</p></section>"
        )
    projection = enveloppe.get("resultat")
    if not isinstance(projection, Mapping):
        return '<section class="carte pile"><h2>Prévisualisation refusée</h2><p>Projection invalide.</p></section>'
    source = projection.get("source_csv")
    source_factures = projection.get("source_factures")
    lignes = projection.get("lignes")
    propositions = projection.get("propositions")
    sha = source.get("sha256") if isinstance(source, Mapping) else None
    version_factures = source_factures.get("version") if isinstance(source_factures, Mapping) else None
    empreinte_factures = source_factures.get("empreinte") if isinstance(source_factures, Mapping) else None
    lot_id = projection.get("lot_id")
    rows = []
    if isinstance(lignes, list):
        for ligne in lignes:
            if not isinstance(ligne, Mapping):
                continue
            values = (
                ligne.get("numero"),
                ligne.get("date"),
                ligne.get("montant"),
                ligne.get("montant_du"),
                ligne.get("reference_facture"),
                (
                    "Partielle — à vérifier"
                    if ligne.get("statut_rapprochement") == "PROPOSITION_PARTIELLE"
                    else ligne.get("statut_rapprochement")
                ),
                (
                    ligne.get("facture_id")
                    if ligne.get("statut_rapprochement") in {"PROPOSITION_EXACTE", "PROPOSITION_PARTIELLE"}
                    else None
                ),
            )
            cells = "".join(
                f"<td>{pages.e(str(value if value is not None else ''))}</td>" for value in values
            )
            rows.append(f"<tr>{cells}</tr>")
    table = (
        "<table><thead><tr><th>Ligne</th><th>Date</th><th>Montant</th><th>Montant dû</th><th>Référence</th>"
        "<th>Statut</th><th>Facture candidate</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )
    count = len(propositions) if isinstance(propositions, list) else 0
    archived = (
        "<p>Résultat archivé : il reflète le snapshot source indiqué et ne vérifie pas l’état actuel.</p>"
        if reponse.get("rejoue") is True
        else ""
    )
    return (
        '<section class="carte pile"><h2>Prévisualisation enregistrée</h2>'
        f"{archived}<p>Lot : <code>{pages.e(str(lot_id or ''))}</code></p>"
        f"<p>Source CSV SHA-256 : <code>{pages.e(str(sha or ''))}</code></p>"
        f"<p>Snapshot factures version {pages.e(str(version_factures))}, tête "
        f"<code>{pages.e(str(empreinte_factures or 'aucune'))}</code></p>"
        f"<p>Propositions de rapprochement : {count}</p>{table}"
        "<p>Aucune facture, aucun mouvement ni solde n’a été modifié.</p></section>"
    )


def _page(
    prefixe: str, session: Session, comptes: tuple[str, ...], contenu: str = "", *, status_code: int = 200
) -> HTMLResponse:
    options = "".join(f'<option value="{pages.e(compte)}">{pages.e(compte)}</option>' for compte in comptes)
    if not comptes:
        options = '<option value="" disabled selected>Compte bancaire non configuré</option>'
    form = (
        f'<form method="post" action="{pages.e(prefixe)}/finance/rapprochement-bancaire/proposer" '
        'class="carte pile">'
        f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">'
        f'<input type="hidden" name="mutation_id" value="{uuid.uuid4()}">'
        f'<label>Compte interne <select name="compte_interne_id" required>{options}</select></label>'
        '<input type="hidden" name="devise" value="CAD">'
        '<label>Colonne de date <input name="mapping_date" required maxlength="128"></label>'
        '<label>Colonne de montant <input name="mapping_montant" required maxlength="128"></label>'
        '<label>Colonne de référence facture <input name="mapping_reference_facture" required maxlength="128"></label>'
        '<label>Contenu CSV UTF-8 <textarea name="csv_utf8" required></textarea></label>'
        '<button type="submit">Prévisualiser le rapprochement</button></form>'
    )
    limite = (
        "<p>Le moteur propose les correspondances exactes par référence facture et montant dû complet. "
        "Un CSV d’une seule ligne peut aussi proposer un candidat partiel : montant déclaré "
        "strictement positif, inférieur au dû du snapshot, avec une référence facture exacte. "
        "Ce candidat ne confirme ni paiement, ni encaissement, ni frais ; il ne distingue pas "
        "un acompte d’un montant net de frais et ne calcule aucun solde restant. "
        "Partiels dans un CSV multi-lignes, splits, frais et surpaiements restent non pris en charge. "
        "La provenance bancaire et l’identité du compte doivent être vérifiées par un humain.</p>"
    )
    return HTMLResponse(
        pages.gabarit(
            "Rapprochement bancaire préparatoire",
            f"<h1>Rapprochement bancaire préparatoire</h1>{contenu}{limite}{form}",
            prefixe=prefixe,
            session=session,
            actif="finance",
        ),
        status_code=status_code,
        headers={"Cache-Control": "no-store"},
    )


def creer_router(
    *,
    session_page: Callable[..., Session],
    session_api: Callable[..., Session],
    ecriture_api: Callable[..., Session],
    formulaire: Callable[[Request], Any],
    objet_json: Callable[[Request], Any],
    autoriser_page: Callable[[Session], None],
    lire_comptes: Callable[[], tuple[str, ...]],
    previsualiser: Callable[[Session, Mapping[str, Any]], Mapping[str, Any]],
    prefixe: str,
) -> APIRouter:
    router = APIRouter(tags=["finance rapprochement bancaire"])

    @router.get("/finance/rapprochement-bancaire", response_class=HTMLResponse)
    def page_banque(request: Request) -> HTMLResponse:
        session = session_page(request)
        try:
            autoriser_page(session)
        except PermissionError as exc:
            raise HTTPException(403, "accès financier refusé") from exc
        return _page(prefixe, session, lire_comptes())

    def executer(session: Session, demande: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            return previsualiser(session, demande)
        except PermissionError as exc:
            raise HTTPException(403, "accès financier refusé") from exc
        except RapprochementErreur as exc:
            return {"ok": True, "resultat": {"accepte": False, "verdict": exc.verdict()}}

    def statut_reponse(reponse: Mapping[str, Any]) -> int:
        enveloppe = reponse.get("resultat")
        return 200 if isinstance(enveloppe, Mapping) and enveloppe.get("accepte") is True else 409

    @router.post("/api/finance/rapprochement-bancaire/proposer")
    async def proposer_api(request: Request) -> JSONResponse:
        session = ecriture_api(request)
        data = await objet_json(request)
        if not isinstance(data, Mapping):
            raise HTTPException(400, "objet JSON attendu")
        demande = _demande(data)
        reponse = executer(session, demande)
        return JSONResponse(reponse, status_code=statut_reponse(reponse), headers={"Cache-Control": "no-store"})

    @router.post("/finance/rapprochement-bancaire/proposer", response_class=HTMLResponse)
    async def proposer_form(request: Request) -> HTMLResponse:
        session = session_page(request)
        champs = await formulaire(request)
        if not isinstance(champs, Mapping) or not securite.csrf_valide(champs.get("csrf"), session):
            raise HTTPException(403, "jeton CSRF absent ou invalide")
        demande = _form_demande(champs)
        resultat = executer(session, demande)
        return _page(
            prefixe, session, lire_comptes(), _resultat_html(resultat), status_code=statut_reponse(resultat)
        )

    return router
