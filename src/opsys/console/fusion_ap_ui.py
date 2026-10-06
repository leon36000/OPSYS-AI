"""Revue HTML privée des brouillons AP liés aux PDF natifs."""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from collections.abc import Callable, Mapping
from email.message import Message
from typing import Any
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from .. import fusion_ap, fusion_pdf, fusion_pdf_ocr
from . import fusion_ap_m5, pages, securite
from .securite import Session

_FORM_MAX = 16_384
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")
_MUTATION = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_REVISION = re.compile(r"(?:0|[1-9][0-9]{0,9})\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_CHAMPS = (
    ("fournisseur", "Fournisseur"),
    ("numero", "Numéro de facture"),
    ("date", "Date imprimée"),
    ("po", "Bon de commande"),
    ("sous_total_imprime", "Sous-total imprimé"),
    ("taxe_imprimee", "Taxes imprimées"),
    ("total_imprime", "Total imprimé"),
    ("devise", "Devise imprimée"),
)


def _privee(reponse: Response) -> Response:
    reponse.headers["Cache-Control"] = "private, no-store, max-age=0"
    reponse.headers["Pragma"] = "no-cache"
    reponse.headers["X-Content-Type-Options"] = "nosniff"
    return reponse


def _reponse(prefixe: str, session: Session, contenu: str, status: int = 200) -> HTMLResponse:
    html = pages.gabarit("Revue AP préparatoire", contenu, prefixe=prefixe, session=session, actif="fusion")
    return _privee(HTMLResponse(html, status_code=status))  # type: ignore[return-value]


def _code(erreur: HTTPException) -> str:
    detail = erreur.detail
    if isinstance(detail, Mapping) and isinstance(detail.get("code"), str):
        return detail["code"]
    return "REQUETE_REFUSEE"


async def _formulaire(request: Request, allowed: set[str]) -> dict[str, str]:
    media = Message()
    media["content-type"] = request.headers.get("content-type", "")
    if media.get_content_type() != "application/x-www-form-urlencoded":
        raise HTTPException(415, "formulaire urlencoded requis")
    annonce = request.headers.get("content-length")
    if annonce is not None:
        if not annonce.isascii() or not annonce.isdecimal() or len(annonce) > 10:
            raise HTTPException(400, "taille de formulaire invalide")
        if int(annonce) > _FORM_MAX:
            raise HTTPException(413, "formulaire trop volumineux")
    morceaux: list[bytes] = []
    total = 0
    async for morceau in request.stream():
        total += len(morceau)
        if total > _FORM_MAX:
            raise HTTPException(413, "formulaire trop volumineux")
        morceaux.append(morceau)
    try:
        corps = b"".join(morceaux)
        if re.search(rb"%(?![0-9A-Fa-f]{2})", corps):
            raise ValueError("échappement percent invalide")
        donnees = parse_qs(
            corps.decode("utf-8", errors="strict"),
            keep_blank_values=True,
            strict_parsing=True,
            max_num_fields=36,
            encoding="utf-8",
            errors="strict",
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(400, "formulaire invalide") from exc
    if set(donnees) != allowed or any(len(valeurs) != 1 for valeurs in donnees.values()):
        raise HTTPException(400, "champs absents, dupliqués ou inconnus")
    return {cle: valeurs[0] for cle, valeurs in donnees.items()}


def _revision(valeur: str, *, positive: bool = False) -> int:
    if not _REVISION.fullmatch(valeur) or (positive and valeur == "0"):
        raise HTTPException(400, "révision invalide")
    return int(valeur)


def _admin(session: Session) -> None:
    if not session.roles.intersection({"admin", "nathan_owner"}):
        raise HTTPException(403, {"code": "ACCES_AP_REFUSE"})


def _tokens_courants(candidat: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    page = candidat.get("page")
    tokens = page.get("tokens") if isinstance(page, Mapping) and page.get("numero") == 1 else None
    if not isinstance(tokens, list) or not 1 <= len(tokens) <= 2_048:
        raise HTTPException(409, {"code": "SOURCE_OCR_OBSOLETE"})
    for token in tokens:
        score = token.get("confiance_brute") if isinstance(token, Mapping) else None
        if (
            not isinstance(token, Mapping) or not isinstance(token.get("texte"), str)
            or type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 100
        ):
            raise HTTPException(409, {"code": "SOURCE_OCR_OBSOLETE"})
    return tokens


def _sha_token(token: Mapping[str, Any]) -> str:
    canonique = json.dumps(dict(token), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonique.encode("utf-8", "strict")).hexdigest()


def _editeur_ocr(
    prefixe: str,
    session: Session,
    lot_id: str,
    run_id: str,
    revision_pdf: int,
    revision_ap: int,
    tokens: list[Mapping[str, Any]],
    proposition: Mapping[str, Any],
    *,
    saisie_referencee: bool = False,
) -> str:
    champs, citations = proposition["champs"], proposition["citations"]
    sections: list[str] = []
    for cle, libelle in _CHAMPS:
        valeurs = citations.get(cle, [])
        indices = [reference["token_index"] for reference in valeurs]
        inputs = []
        for index in range(1, 4):
            selection = indices[index - 1] if index <= len(indices) else ""
            inputs.append(
                f'<label>Index du token, page 1 (0 à {len(tokens) - 1})'
                f'<input type="number" name="citation.{pages.e(cle)}.{index}" min="0" '
                f'max="{len(tokens) - 1}" value="{pages.e(selection)}"></label>'
            )
        sections.append(
            f'<fieldset><legend>{pages.e(libelle)}</legend>'
            f'<label>{pages.e(libelle)}<input name="champ.{pages.e(cle)}" maxlength="128" '
            f'value="{pages.e(champs.get(cle, ""))}"></label>{"".join(inputs)}</fieldset>'
        )
    mutation = uuid.uuid4().hex
    m5 = ""
    if session.roles.intersection({"finance", "nathan_owner"}) and not saisie_referencee:
        m5 = _formulaire_verifier_m5(prefixe, session, lot_id, revision_pdf, revision_ap)
    return (
        f'<p><a target="_blank" rel="noopener" href="{pages.e(prefixe)}/fusion/pdf/lots/{pages.e(lot_id)}'
        f'/ocr/{pages.e(run_id)}?bloc=1">Consulter les tokens OCR (128 par bloc)</a></p>'
        '<p>Les valeurs sont saisies ou corrigées par une personne. Les citations sont des index de tokens '
        'du run courant; la confiance affichée est brute et non calibrée. Aucun montant n’est prérempli.</p>'
        f'<form method="post" action="{pages.e(prefixe)}/fusion/pdf/lots/{pages.e(lot_id)}'
        f'/ap/ocr/{pages.e(run_id)}/enregistrer" class="pile">'
        f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">'
        f'<input type="hidden" name="mutation_id" value="{mutation}">'
        f'<input type="hidden" name="revision_pdf" value="{revision_pdf}">'
        f'<input type="hidden" name="revision_ap" value="{revision_ap}">'
        f'{"".join(sections)}'
        '<button class="principal" type="submit">Enregistrer la correction humaine</button></form>' + m5
    )


def _refs(resultat: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    refs: dict[str, dict[str, Any]] = {}
    pages_pdf = resultat.get("pages")
    if not isinstance(pages_pdf, list) or not 1 <= len(pages_pdf) <= fusion_pdf.PAGES_MAX:
        raise HTTPException(409, "PDF_RESULTAT_INDISPONIBLE")
    for page in pages_pdf:
        for fragment in page.get("fragments", []):
            cle = f"{page['numero']}:{fragment['id']}"
            refs[cle] = {
                "page": page["numero"],
                "fragment_id": fragment["id"],
                "fragment_sha256": fragment["sha256"],
            }
    if not refs:
        raise HTTPException(409, "PDF_RESULTAT_INDISPONIBLE")
    return refs


def _options(refs: Mapping[str, Mapping[str, Any]], selection: str | None) -> str:
    lignes = ['<option value="">Aucune référence</option>']
    for cle, reference in refs.items():
        page = reference["page"]
        identifiant = reference["fragment_id"]
        selected = " selected" if cle == selection else ""
        lignes.append(
            f'<option value="{pages.e(cle)}"{selected}>Page {pages.e(page)} — extrait {pages.e(identifiant)}</option>'
        )
    return "".join(lignes)


def _editeur(
    prefixe: str,
    session: Session,
    lot_id: str,
    revision_pdf: int,
    revision_ap: int,
    refs: Mapping[str, Mapping[str, Any]],
    champs: Mapping[str, Any] | None = None,
    citations: Mapping[str, Any] | None = None,
) -> str:
    champs = champs or {}
    citations = citations or {}
    mutation = uuid.uuid4().hex
    sections: list[str] = []
    for cle, libelle in _CHAMPS:
        valeurs_refs = citations.get(cle, [])
        text = pages.e(champs.get(cle, ""))
        selects = []
        for index in range(1, 4):
            marque = "référence" if index == 1 else f"référence supplémentaire {index}"
            reference = valeurs_refs[index - 1] if index <= len(valeurs_refs) else None
            selection = None if reference is None else f"{reference['page']}:{reference['fragment_id']}"
            selects.append(
                f"<label>{pages.e(marque)} pour {pages.e(libelle)}"
                f'<select name="citation.{pages.e(cle)}.{index}">{_options(refs, selection)}</select>'
                "</label>"
            )
        sections.append(
            f"<fieldset><legend>{pages.e(libelle)}</legend>"
            f'<label>{pages.e(libelle)}<input name="champ.{pages.e(cle)}" maxlength="128" value="{text}"></label>'
            f"{''.join(selects)}</fieldset>"
        )
    return (
        f'<p><a href="{pages.e(prefixe)}/fusion/pdf/lots/{pages.e(lot_id)}">Retour aux métadonnées PDF</a></p>'
        f'<p><a href="{pages.e(prefixe)}/fusion/pdf/lots/{pages.e(lot_id)}/extraits?page=1" '
        'target="_blank" rel="noopener">Consulter les extraits PDF dans un autre onglet</a></p>'
        '<p class="note">Proposition textuelle fournie ou corrigée par une personne. Les références identifient '
        "des fragments natifs à consulter; elles ne valident ni le contenu ni un montant. État conservé : A_REVOIR. "
        "Aucune facture ni écriture comptable n’est créée.</p>"
        f'<form method="post" action="{pages.e(prefixe)}/fusion/pdf/lots/{pages.e(lot_id)}'
        '/ap/enregistrer" class="pile">'
        f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">'
        f'<input type="hidden" name="mutation_id" value="{mutation}">'
        f'<input type="hidden" name="revision_pdf" value="{revision_pdf}">'
        f'<input type="hidden" name="revision_ap" value="{revision_ap}">'
        f"{''.join(sections)}"
        '<button class="principal" type="submit">Enregistrer le brouillon à revoir</button></form>'
    )


def _resume(
    prefixe: str,
    session: Session,
    lot: Mapping[str, Any],
    brouillon: Mapping[str, Any] | None,
    *,
    saisie_referencee: bool = False,
) -> str:
    if brouillon is None:
        status = "Aucun brouillon AP"
        revision_ap = 0
    else:
        status = f"{brouillon['statut']} — révision {brouillon['revision']}"
        revision_ap = brouillon["revision"]
    form = ""
    if brouillon is not None:
        form = (
            f'<form method="post" action="{pages.e(prefixe)}/fusion/pdf/lots/{pages.e(lot["lot_id"])}'
            '/ap/lire" class="pile">'
            f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">'
            f'<input type="hidden" name="revision_pdf" value="{pages.e(lot["revision"])}">'
            f'<input type="hidden" name="revision_ap" value="{revision_ap}">'
            '<button type="submit">Afficher les champs enregistrés</button></form>'
        )
        if session.roles.intersection({"finance", "nathan_owner"}) and not saisie_referencee:
            form += _formulaire_verifier_m5(
                prefixe, session, lot["lot_id"], lot["revision"], revision_ap,
            )
    return (
        f'<p><a href="{pages.e(prefixe)}/fusion/pdf/lots/{pages.e(lot["lot_id"])}">Retour au lot PDF</a></p>'
        f'<dl class="meta"><dt>État AP</dt><dd>{pages.e(status)}</dd>'
        f"<dt>Révision PDF</dt><dd>{pages.e(lot['revision'])}</dd></dl>" + form
    )


def _resultat_m5(resultat: Mapping[str, Any]) -> str:
    """Rend uniquement les éléments d'observation autorisés par le contrat privé M5."""
    calcul = resultat.get("calcul")
    source = resultat.get("source")
    if not isinstance(calcul, Mapping) or not isinstance(source, Mapping):
        raise HTTPException(503, {"code": "VERIFICATION_M5_INDISPONIBLE"})
    montants = (calcul.get("montant_avant_taxes"), calcul.get("total_taxes"), calcul.get("montant_apres_taxes"))
    if any(not isinstance(value, str) for value in montants):
        raise HTTPException(503, {"code": "VERIFICATION_M5_INDISPONIBLE"})
    taxes = calcul.get("taxes")
    avertissements = resultat.get("avertissements")
    if not isinstance(taxes, list) or not isinstance(avertissements, list):
        raise HTTPException(503, {"code": "VERIFICATION_M5_INDISPONIBLE"})
    lignes_taxes: list[str] = []
    source_ocr_html = ""
    if source.get("source_type") == "OCR_CANDIDAT":
        run_id, revision_run = source.get("ocr_run_id"), source.get("revision_run")
        if (
            not isinstance(run_id, str) or not _UUID.fullmatch(run_id)
            or type(revision_run) is not int or revision_run < 1
        ):
            raise HTTPException(503, {"code": "VERIFICATION_M5_INDISPONIBLE"})
        source_ocr_html = (
            f'<p>Source de la revue : OCR_CANDIDAT — candidat {pages.e(run_id)} '
            f'révision {pages.e(revision_run)}.</p>'
        )
    for taxe in taxes:
        if not isinstance(taxe, Mapping) or any(
            not isinstance(taxe.get(key), str) for key in ("id", "version", "source", "montant")
        ):
            raise HTTPException(503, {"code": "VERIFICATION_M5_INDISPONIBLE"})
        lignes_taxes.append(
            "<li>"
            + " — ".join(pages.e(taxe[key]) for key in ("id", "montant", "version", "source"))
            + "</li>"
        )
    if any(not isinstance(code, str) for code in avertissements):
        raise HTTPException(503, {"code": "VERIFICATION_M5_INDISPONIBLE"})
    codes = "".join(f"<li>{pages.e(code)}</li>" for code in avertissements) or "<li>Aucun</li>"
    return (
        '<section class="carte pile"><h2>Observation préparatoire M5</h2>'
        f'<p>{pages.e(resultat.get("statut", ""))} — observé le {pages.e(resultat.get("observe_le", ""))}</p>'
        f'<p>Snapshot {pages.e(resultat.get("snapshot_id", ""))}; révisions PDF/AP '
        f'{pages.e(source.get("revision_pdf", ""))}/{pages.e(source.get("revision_ap", ""))}.</p>'
        + source_ocr_html
        + '<dl class="meta">'
        f'<dt>Montant avant taxes</dt><dd>{pages.e(montants[0])} CAD</dd>'
        f'<dt>Total des taxes</dt><dd>{pages.e(montants[1])} CAD</dd>'
        f'<dt>Montant après taxes</dt><dd>{pages.e(montants[2])} CAD</dd></dl>'
        f'<h3>Taxes versionnées</h3><ul>{"".join(lignes_taxes)}</ul>'
        f'<h3>Codes d’avertissement</h3><ul>{codes}</ul>'
        '<p>Observation préparatoire, A_REVOIR conservé; aucune facture, dette, approbation ni paiement créé.</p>'
        '</section>'
    )


def _formulaire_verifier_m5(
    prefixe: str, session: Session, lot_id: str, revision_pdf: int, revision_ap: int,
) -> str:
    return (
        f'<form method="post" action="{pages.e(prefixe)}/fusion/pdf/lots/{pages.e(lot_id)}'
        '/ap/verifier-m5" class="pile">'
        f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">'
        f'<input type="hidden" name="revision_pdf" value="{pages.e(revision_pdf)}">'
        f'<input type="hidden" name="revision_ap" value="{pages.e(revision_ap)}">'
        '<label>Bon de commande reçu choisi dans M5'
        '<input name="po_id" maxlength="64" required autocomplete="off"></label>'
        '<label>Fournisseur canonique choisi dans M5'
        '<input name="fournisseur_id" maxlength="64" required autocomplete="off"></label>'
        '<label><input type="checkbox" name="correspondance_confirmee" value="oui" required>'
        'J’atteste que le PO et le fournisseur choisis correspondent aux identifiants imprimés sur la facture.'
        '</label><button class="principal" type="submit">Vérifier les contrôles M5</button></form>'
    )


def _confirmation_saisie_m5(
    prefixe: str,
    session: Session,
    lot_id: str,
    revision_pdf: int,
    revision_ap: int,
    po_id: str,
    fournisseur_id: str,
    resultat: Mapping[str, Any],
) -> str:
    commande_sha256 = resultat.get("commande_sha256")
    if not isinstance(commande_sha256, str) or not _SHA256.fullmatch(commande_sha256):
        raise HTTPException(503, {"code": "VERIFICATION_M5_INDISPONIBLE"})
    mutation_id = uuid.uuid4().hex
    return (
        '<section class="carte pile"><h2>Saisie humaine dans M5</h2>'
        '<p>La vérification précédente était une observation sans effet. Ce second envoi créera une facture SAISIE, '
        'donc une dette interne; aucun paiement ne sera lancé. Le brouillon Fusion restera A_REVOIR.</p>'
        f'<form method="post" action="{pages.e(prefixe)}/fusion/pdf/lots/{pages.e(lot_id)}/ap/saisir-m5" '
        'class="pile">'
        f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">'
        f'<input type="hidden" name="revision_pdf" value="{revision_pdf}">'
        f'<input type="hidden" name="revision_ap" value="{revision_ap}">'
        f'<input type="hidden" name="po_id" value="{pages.e(po_id)}">'
        f'<input type="hidden" name="fournisseur_id" value="{pages.e(fournisseur_id)}">'
        '<input type="hidden" name="correspondance_confirmee" value="oui">'
        f'<input type="hidden" name="snapshot_attendu" value="{pages.e(commande_sha256)}">'
        f'<input type="hidden" name="mutation_id" value="{mutation_id}">'
        '<label><input type="checkbox" name="saisie_confirmee" value="oui" required>'
        'Je confirme la saisie d’une dette interne dans M5, sans paiement.</label>'
        '<button class="principal" type="submit">Confirmer la saisie M5</button></form></section>'
    )


def _reference_saisie_m5(resultat: Mapping[str, Any] | None) -> str:
    if resultat is None:
        return ""
    if not isinstance(resultat, Mapping) or set(resultat) != {
        "facture_id", "approbation_id", "statut_m5", "corrections",
    }:
        raise HTTPException(503, {"code": "REFERENCE_SAISIE_M5_INDISPONIBLE"})
    facture_id, approbation_id = resultat.get("facture_id"), resultat.get("approbation_id")
    statut, corrections = resultat.get("statut_m5"), resultat.get("corrections")
    if (
        not isinstance(facture_id, str) or not facture_id or len(facture_id) > 128 or not facture_id.isprintable()
        or not isinstance(approbation_id, str) or not approbation_id or len(approbation_id) > 128
        or not approbation_id.isprintable()
        or not isinstance(statut, str) or statut not in {"SAISIE", "CORRIGEE", "ANNULEE"}
        or type(corrections) is not int or not 0 <= corrections <= 10_000
    ):
        raise HTTPException(503, {"code": "REFERENCE_SAISIE_M5_INDISPONIBLE"})
    return (
        '<section class="carte pile"><h2>Référence de saisie M5</h2>'
        f'<p>Facture : {pages.e(facture_id)}.</p>'
        f'<p>Approbation N3 : {pages.e(approbation_id)}.</p>'
        f'<p>État courant M5 : {pages.e(statut)}.</p>'
        f'<p>Corrections enregistrées : {corrections}.</p>'
        '<p>Référence historique de la saisie d’origine, distincte du brouillon A_REVOIR. Le statut courant '
        'et le compte des corrections proviennent de M5.</p></section>'
    )


def _recu_saisie_m5(
    resultat: Mapping[str, Any], *, prefixe: str | None = None, lot_id: str | None = None,
) -> str:
    status = resultat.get("statut")
    facture_id = resultat.get("facture_id")
    approbation_id = resultat.get("approbation_id")
    rejoue = resultat.get("rejoue")
    if (
        not isinstance(status, str)
        or not isinstance(facture_id, str)
        or not isinstance(approbation_id, str)
        or type(rejoue) is not bool
    ):
        raise HTTPException(503, {"code": "SAISIE_M5_INDISPONIBLE"})
    liens = ""
    if prefixe is not None and lot_id is not None:
        liens = (
            f'<p><a href="{pages.e(prefixe)}/fusion/pdf/lots/{pages.e(lot_id)}/ap">Retrouver la référence</a></p>'
            f'<p><a href="{pages.e(prefixe)}/finance">Finance</a></p>'
        )
    return (
        '<section class="carte pile"><h2>Référence de saisie M5</h2>'
        f'<p>État : {pages.e(status)}.</p>'
        f'<p>Référence de facture : {pages.e(facture_id)}.</p>'
        f'<p>Référence d’approbation : {pages.e(approbation_id)}.</p>'
        f'<p>Rejeu idempotent : {"oui" if rejoue else "non"}.</p>'
        '<p>Cette référence conserve la saisie interne d’origine dans M5. Consultez M5 pour son état courant '
        'et ses éventuelles corrections ou annulations. Aucun paiement n’a été lancé; le brouillon Fusion '
        'demeure A_REVOIR.</p>' + liens + '</section>'
    )


def _liste_a_revoir(prefixe: str, rows: list[Mapping[str, Any]]) -> str:
    if not rows:
        return '<p>Aucun brouillon AP à rouvrir.</p>'
    items: list[str] = []
    for row in rows:
        lot_id = row.get("lot_id")
        run_id = row.get("ocr_run_id")
        source_ocr = row.get("source_type") == "OCR_CANDIDAT"
        is_ocr = source_ocr and isinstance(run_id, str) and _UUID.fullmatch(run_id) is not None
        revision = row.get("revision")
        if row.get("etat_source") == "A_REVALIDER" and isinstance(lot_id, str):
            label = "À rouvrir et revalider"
            if source_ocr and not is_ocr:
                label, link = "Indisponible — à revalider", "Lien de revue indisponible"
            else:
                href = (
                    f"{pages.e(prefixe)}/fusion/pdf/lots/{pages.e(lot_id)}/ap/ocr/{pages.e(run_id)}"
                    if is_ocr else f"{pages.e(prefixe)}/fusion/pdf/lots/{pages.e(lot_id)}/ap"
                )
                link = f'<a href="{href}">Ouvrir la revue AP</a>'
        else:
            label = "Indisponible — à revalider"
            if isinstance(lot_id, str):
                if source_ocr and not is_ocr:
                    link = "Lien de revue indisponible"
                else:
                    href = (
                        f"{pages.e(prefixe)}/fusion/pdf/lots/{pages.e(lot_id)}/ap/ocr/{pages.e(run_id)}"
                        if is_ocr else f"{pages.e(prefixe)}/fusion/pdf/lots/{pages.e(lot_id)}/ap"
                    )
                    link = f'<a href="{href}">Rouvrir pour vérifier</a>'
            else:
                link = "Lien de revue indisponible"
        date = row.get("modifie_le")
        date_html = f'<span>Modifié le {pages.e(date)}</span>' if isinstance(date, str) else ""
        revision_html = f"<span>Révision AP {pages.e(revision)}</span>" if type(revision) is int else ""
        items.append(
            '<li class="pile">'
            f"<strong>{pages.e(label)}</strong> {revision_html} {date_html} {link}</li>"
        )
    return (
        f'<p>{len(rows)} brouillon(s) dans cette liste bornée.</p>'
        f'<ul class="pile">{"".join(items)}</ul>'
    )


def creer_router(
    *,
    session_page: Callable[..., Session],
    prefixe: str,
    cnx_factory: Callable[..., Any],
    deps: Mapping[str, Any] | None = None,
) -> APIRouter:
    router = APIRouter()

    def session_vivante(request: Request, utilisateur: str | None = None) -> Session:
        session = session_page(request)
        if utilisateur is not None and session.utilisateur != utilisateur:
            raise HTTPException(403, "identité modifiée pendant l’opération")
        return session

    def rendre_prive(request: Request, session: Session, contenu: str, status: int = 200) -> HTMLResponse:
        reponse = _reponse(prefixe, session, contenu, status)
        session_vivante(request, session.utilisateur)
        return reponse

    def echec_prive(request: Request, session: Session, erreur: HTTPException) -> HTMLResponse:
        code = pages.e(_code(erreur))
        contenu = (
            '<section class="carte pile"><h1>Revue AP indisponible</h1>'
            f'<p role="alert">Action refusée ({code}).</p>'
            f'<p><a href="{pages.e(prefixe)}/fusion/pdf">Retour aux lots PDF</a></p></section>'
        )
        return rendre_prive(request, session, contenu, erreur.status_code)

    def appeler(action: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        try:
            return action(*args, **kwargs)
        except fusion_ap.FusionAPErreur as exc:
            raise HTTPException(exc.statut_http, {"code": exc.code, "detail": exc.detail}) from exc
        except PermissionError as exc:
            raise HTTPException(403, {"code": "ACCES_AP_REFUSE", "detail": "accès AP refusé"}) from exc

    async def bloquant(action: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        return await run_in_threadpool(appeler, action, *args, **kwargs)

    def sans_query(request: Request) -> None:
        if request.query_params:
            raise HTTPException(400, "paramètres invalides")

    def valider_lot(lot_id: str) -> None:
        if not _UUID.fullmatch(lot_id):
            raise HTTPException(400, "identifiant de lot invalide")

    def valider_csrf(fields: Mapping[str, str], session: Session) -> None:
        if not securite.csrf_valide(fields.get("csrf"), session):
            raise HTTPException(403, "jeton CSRF absent ou invalide")

    def verifier_role_finance(session: Session) -> None:
        if not session.roles.intersection({"finance", "nathan_owner"}):
            raise HTTPException(403, {"code": "ACCES_FINANCE_REFUSE"})

    async def resultats_actuels(request: Request, utilisateur: str, lot_id: str, revision: int):
        lot = await bloquant(fusion_pdf.lire, cnx_factory, utilisateur, lot_id)
        session_vivante(request, utilisateur)
        if lot["statut"] != "EXTRAIT_PREPARATOIRE" or lot["revision"] != revision:
            raise HTTPException(409, {"code": "CONFLIT_REVISION_PDF"})
        resultat = await bloquant(fusion_pdf.lire_resultat, cnx_factory, utilisateur, lot_id)
        session_vivante(request, utilisateur)
        courant = await bloquant(fusion_pdf.lire, cnx_factory, utilisateur, lot_id)
        session_vivante(request, utilisateur)
        if courant["statut"] != "EXTRAIT_PREPARATOIRE" or courant["revision"] != revision:
            raise HTTPException(409, {"code": "CONFLIT_REVISION_PDF"})
        return courant, resultat, _refs(resultat)

    async def source_ap_ocr(request: Request, utilisateur: str, lot_id: str, run_id: str):
        revue = await bloquant(fusion_ap.lire_revue_privee, cnx_factory, utilisateur, lot_id)
        _admin(session_vivante(request, utilisateur))
        brouillon = revue.get("brouillon")
        if (
            not isinstance(brouillon, Mapping) or brouillon.get("source_type") != "OCR_CANDIDAT"
            or brouillon.get("ocr_run_id") != run_id or type(brouillon.get("revision_run")) is not int
        ):
            raise HTTPException(409, {"code": "SOURCE_OCR_OBSOLETE"})
        candidat = await bloquant(fusion_pdf_ocr.lire_resultat, cnx_factory, utilisateur, run_id)
        _admin(session_vivante(request, utilisateur))
        if (
            not isinstance(candidat, Mapping) or candidat.get("statut") != "CANDIDAT_A_REVOIR"
            or candidat.get("lot_id") != lot_id or candidat.get("revision_source") != brouillon.get("revision_pdf")
        ):
            raise HTTPException(409, {"code": "SOURCE_OCR_OBSOLETE"})
        tokens = _tokens_courants(candidat)
        return brouillon, revue.get("proposition"), candidat, tokens

    @router.get("/fusion/pdf/lots/{lot_id}/ap/ocr/{run_id}", response_class=HTMLResponse)
    async def lire_ap_ocr(lot_id: str, run_id: str, request: Request) -> HTMLResponse:
        session = session_vivante(request)
        _admin(session)
        sans_query(request)
        valider_lot(lot_id)
        if not _UUID.fullmatch(run_id):
            raise HTTPException(400, "identifiant OCR invalide")
        try:
            brouillon, proposition, _, tokens = await source_ap_ocr(
                request, session.utilisateur, lot_id, run_id,
            )
            session = session_vivante(request, session.utilisateur)
            _admin(session)
            reference_html = ""
            saisie_referencee = False
            if session.roles.intersection({"finance", "nathan_owner"}):
                try:
                    from . import fusion_ap_m5_reference

                    reference = await bloquant(
                        fusion_ap_m5_reference.lire, cnx_factory, session.utilisateur, lot_id,
                    )
                except Exception as exc:
                    session = session_vivante(request, session.utilisateur)
                    _admin(session)
                    raise HTTPException(503, {"code": "REFERENCE_SAISIE_M5_INDISPONIBLE"}) from exc
                session = session_vivante(request, session.utilisateur)
                _admin(session)
                verifier_role_finance(session)
                reference_html = _reference_saisie_m5(reference)
                saisie_referencee = reference is not None
                brouillon, proposition, _, tokens = await source_ap_ocr(
                    request, session.utilisateur, lot_id, run_id,
                )
                session = session_vivante(request, session.utilisateur)
                _admin(session)
                verifier_role_finance(session)
            if (
                not isinstance(proposition, Mapping) or type(brouillon.get("revision_pdf")) is not int
                or type(brouillon.get("revision")) is not int
            ):
                raise HTTPException(503, {"code": "BROUILLON_AP_INDISPONIBLE"})
            contenu = (
                '<section class="carte pile"><h1>Revue AP issue d’un candidat OCR</h1>'
                f'<p>PDF révision {pages.e(brouillon["revision_pdf"])}; candidat '
                f'{pages.e(run_id)} révision {pages.e(brouillon["revision_run"])}.</p>'
                f'<p>État {pages.e(brouillon["statut"])} — révision AP {pages.e(brouillon["revision"])}.</p>'
                + reference_html
                + _editeur_ocr(
                    prefixe, session, lot_id, run_id, brouillon["revision_pdf"], brouillon["revision"],
                    tokens, proposition, saisie_referencee=saisie_referencee,
                )
                + '</section>'
            )
            reponse = rendre_prive(request, session, contenu)
            if reference_html:
                session = session_vivante(request, session.utilisateur)
                _admin(session)
                verifier_role_finance(session)
            return reponse
        except HTTPException as exc:
            session = session_vivante(request, session.utilisateur)
            return echec_prive(request, session, exc)
        except Exception:
            session = session_vivante(request, session.utilisateur)
            return echec_prive(request, session, HTTPException(503, {"code": "SOURCE_OCR_OBSOLETE"}))

    @router.post("/fusion/pdf/lots/{lot_id}/ap/ocr/{run_id}/enregistrer", response_class=Response)
    async def enregistrer_ap_ocr(lot_id: str, run_id: str, request: Request) -> Response:
        session = session_vivante(request)
        _admin(session)
        sans_query(request)
        valider_lot(lot_id)
        if not _UUID.fullmatch(run_id):
            raise HTTPException(400, "identifiant OCR invalide")
        attendus = {"csrf", "mutation_id", "revision_pdf", "revision_ap"}
        attendus.update(f"champ.{cle}" for cle, _ in _CHAMPS)
        attendus.update(f"citation.{cle}.{index}" for cle, _ in _CHAMPS for index in range(1, 4))
        fields = await _formulaire(request, attendus)
        session_vivante(request, session.utilisateur)
        valider_csrf(fields, session)
        if not _MUTATION.fullmatch(fields["mutation_id"]):
            raise HTTPException(400, "identifiant de mutation invalide")
        revision_pdf = _revision(fields["revision_pdf"], positive=True)
        revision_ap = _revision(fields["revision_ap"], positive=True)
        for cle, _ in _CHAMPS:
            value = fields[f"champ.{cle}"]
            if len(value) > 128 or len(value.encode("utf-8")) > 128:
                raise HTTPException(400, "valeur de champ hors limite")
        try:
            brouillon, _, _, tokens = await source_ap_ocr(request, session.utilisateur, lot_id, run_id)
            session = session_vivante(request, session.utilisateur)
            if brouillon["revision_pdf"] != revision_pdf:
                raise HTTPException(409, {"code": "CONFLIT_REVISION"})
            champs = {cle: fields[f"champ.{cle}"] for cle, _ in _CHAMPS}
            citations: dict[str, list[dict[str, Any]]] = {}
            for cle, _ in _CHAMPS:
                brut = [fields[f"citation.{cle}.{index}"] for index in range(1, 4)]
                if any(value and not re.fullmatch(r"(?:0|[1-9][0-9]{0,3})", value) for value in brut):
                    raise HTTPException(400, {"code": "CITATION_INVALIDE"})
                selection = [int(value) for value in brut if value]
                if len(set(selection)) != len(selection):
                    raise HTTPException(400, {"code": "CITATION_INVALIDE"})
                if not champs[cle] and selection:
                    raise HTTPException(400, {"code": "CITATION_INVALIDE"})
                if champs[cle]:
                    if not 1 <= len(selection) <= 3 or any(index >= len(tokens) for index in selection):
                        raise HTTPException(400, {"code": "CITATION_INVALIDE"})
                    citations[cle] = [
                        {"page": 1, "token_index": index, "token_sha256": _sha_token(tokens[index])}
                        for index in selection
                    ]
            run_revision = brouillon["revision_run"]
            session = session_vivante(request, session.utilisateur)
            _admin(session)
            await bloquant(
                fusion_ap.enregistrer_ocr, cnx_factory, session.utilisateur, lot_id,
                mutation_id=fields["mutation_id"], revision_pdf_attendue=revision_pdf,
                revision_attendue=revision_ap, ocr_run_id=run_id, revision_run=run_revision,
                proposition={"schema_version": 1, "champs": champs, "citations": citations},
            )
            session = session_vivante(request, session.utilisateur)
            _admin(session)
        except HTTPException as exc:
            session = session_vivante(request, session.utilisateur)
            return echec_prive(request, session, exc)
        except Exception:
            session = session_vivante(request, session.utilisateur)
            return echec_prive(request, session, HTTPException(409, {"code": "SOURCE_OCR_OBSOLETE"}))
        reponse = _privee(RedirectResponse(
            f"{prefixe}/fusion/pdf/lots/{lot_id}/ap/ocr/{run_id}", status_code=303,
        ))
        session_vivante(request, session.utilisateur)
        return reponse

    @router.get("/fusion/pdf/ap/a-revoir", response_class=HTMLResponse)
    async def liste_ap_a_revoir(request: Request) -> HTMLResponse:
        session = session_vivante(request)
        sans_query(request)
        try:
            rows = await bloquant(
                fusion_ap.lister_a_revoir,
                cnx_factory,
                session.utilisateur,
                limite=fusion_pdf.NB_LOTS_MAX,
            )
            session = session_vivante(request, session.utilisateur)
            contenu = (
                '<section class="carte pile"><h1>Brouillons AP à revoir</h1>'
                '<p>Les brouillons restent préparatoires. Rouvrez chaque élément pour vérifier la source, '
                "les champs et leurs citations actuels.</p>"
                f"{_liste_a_revoir(prefixe, rows)}"
                f'<p><a href="{pages.e(prefixe)}/fusion/pdf">Retour aux lots PDF</a></p></section>'
            )
            return rendre_prive(request, session, contenu)
        except HTTPException as exc:
            if exc.status_code in (401, 403):
                raise
            session = session_vivante(request, session.utilisateur)
        except Exception:
            session = session_vivante(request, session.utilisateur)
        contenu = (
            '<section class="carte pile"><h1>Brouillons AP à revoir</h1>'
            '<p role="status">Liste indisponible; aucun zéro n’est déduit.</p>'
            f'<p><a href="{pages.e(prefixe)}/fusion/pdf">Retour aux lots PDF</a></p></section>'
        )
        return rendre_prive(request, session, contenu, 503)

    @router.get("/fusion/pdf/lots/{lot_id}/ap", response_class=HTMLResponse)
    async def page_ap(lot_id: str, request: Request) -> HTMLResponse:
        session = session_vivante(request)
        sans_query(request)
        valider_lot(lot_id)
        try:
            lot = await bloquant(fusion_pdf.lire, cnx_factory, session.utilisateur, lot_id)
            session = session_vivante(request, session.utilisateur)
            if lot["statut"] != "EXTRAIT_PREPARATOIRE":
                raise HTTPException(409, {"code": "PDF_RESULTAT_INDISPONIBLE"})
            _, _, refs = await resultats_actuels(request, session.utilisateur, lot_id, lot["revision"])
            session = session_vivante(request, session.utilisateur)
            brouillon = await bloquant(fusion_ap.lire, cnx_factory, session.utilisateur, lot_id)
            session = session_vivante(request, session.utilisateur)
        except HTTPException as exc:
            session = session_vivante(request, session.utilisateur)
            if _code(exc) == "BROUILLON_INCONNU":
                contenu = _resume(prefixe, session, lot, None) + _editeur(
                    prefixe, session, lot_id, lot["revision"], 0, refs
                )
                return rendre_prive(
                    request, session, f'<section class="carte pile"><h1>Revue AP</h1>{contenu}</section>'
                )
            return echec_prive(request, session, exc)
        reference_html = ""
        saisie_referencee = False
        if session.roles.intersection({"finance", "nathan_owner"}):
            try:
                from . import fusion_ap_m5_reference

                reference = await bloquant(fusion_ap_m5_reference.lire, cnx_factory, session.utilisateur, lot_id)
            except Exception:
                session = session_vivante(request, session.utilisateur)
                verifier_role_finance(session)
                return echec_prive(
                    request, session, HTTPException(503, {"code": "REFERENCE_SAISIE_M5_INDISPONIBLE"})
                )
            session = session_vivante(request, session.utilisateur)
            verifier_role_finance(session)
            try:
                reference_html = _reference_saisie_m5(reference)
            except Exception:
                session = session_vivante(request, session.utilisateur)
                verifier_role_finance(session)
                return echec_prive(
                    request, session, HTTPException(503, {"code": "REFERENCE_SAISIE_M5_INDISPONIBLE"})
                )
            saisie_referencee = reference is not None
        contenu = _resume(prefixe, session, lot, brouillon, saisie_referencee=saisie_referencee) + reference_html
        reponse = rendre_prive(request, session, f'<section class="carte pile"><h1>Revue AP</h1>{contenu}</section>')
        if saisie_referencee:
            session = session_vivante(request, session.utilisateur)
            verifier_role_finance(session)
        return reponse

    @router.post("/fusion/pdf/lots/{lot_id}/ap/lire", response_class=HTMLResponse)
    async def lire_ap(lot_id: str, request: Request) -> HTMLResponse:
        session = session_vivante(request)
        sans_query(request)
        valider_lot(lot_id)
        fields = await _formulaire(request, {"csrf", "revision_pdf", "revision_ap"})
        session_vivante(request, session.utilisateur)
        valider_csrf(fields, session)
        revision_pdf = _revision(fields["revision_pdf"], positive=True)
        revision_ap = _revision(fields["revision_ap"])
        try:
            revue = await bloquant(fusion_ap.lire_revue_privee, cnx_factory, session.utilisateur, lot_id)
            session = session_vivante(request, session.utilisateur)
            brouillon = revue["brouillon"]
            if brouillon["revision_pdf"] != revision_pdf or brouillon["revision"] != revision_ap:
                raise HTTPException(409, {"code": "CONFLIT_REVISION"})
            lot, _, refs = await resultats_actuels(request, session.utilisateur, lot_id, revision_pdf)
            session = session_vivante(request, session.utilisateur)
        except HTTPException as exc:
            session = session_vivante(request, session.utilisateur)
            return echec_prive(request, session, exc)
        contenu = _resume(prefixe, session, lot, brouillon) + _editeur(
            prefixe,
            session,
            lot_id,
            revision_pdf,
            revision_ap,
            refs,
            revue["proposition"]["champs"],
            revue["proposition"]["citations"],
        )
        return rendre_prive(
            request, session, f'<section class="carte pile"><h1>Revue AP explicite</h1>{contenu}</section>'
        )

    @router.post("/fusion/pdf/lots/{lot_id}/ap/enregistrer", response_class=Response)
    async def enregistrer_ap(lot_id: str, request: Request) -> Response:
        session = session_vivante(request)
        sans_query(request)
        valider_lot(lot_id)
        champs_attendus = {"csrf", "mutation_id", "revision_pdf", "revision_ap"}
        champs_attendus.update(f"champ.{cle}" for cle, _ in _CHAMPS)
        champs_attendus.update(f"citation.{cle}.{index}" for cle, _ in _CHAMPS for index in range(1, 4))
        fields = await _formulaire(request, champs_attendus)
        session_vivante(request, session.utilisateur)
        valider_csrf(fields, session)
        if not _MUTATION.fullmatch(fields["mutation_id"]):
            raise HTTPException(400, "identifiant de mutation invalide")
        revision_pdf = _revision(fields["revision_pdf"], positive=True)
        revision_ap = _revision(fields["revision_ap"])
        for cle, _ in _CHAMPS:
            value = fields[f"champ.{cle}"]
            if len(value) > 128 or len(value.encode("utf-8")) > 128:
                raise HTTPException(400, "valeur de champ hors limite")
        try:
            _, resultat, refs = await resultats_actuels(request, session.utilisateur, lot_id, revision_pdf)
            session = session_vivante(request, session.utilisateur)
            champs = {cle: fields[f"champ.{cle}"] for cle, _ in _CHAMPS}
            citations: dict[str, list[dict[str, Any]]] = {}
            for cle, _ in _CHAMPS:
                selections = [fields[f"citation.{cle}.{index}"] for index in range(1, 4)]
                if len(set(value for value in selections if value)) != len([value for value in selections if value]):
                    raise HTTPException(400, "références dupliquées")
                if not champs[cle] and any(selections):
                    raise HTTPException(400, "référence sans valeur")
                if champs[cle]:
                    choisies = [value for value in selections if value]
                    if not 1 <= len(choisies) <= 3 or any(value not in refs for value in choisies):
                        raise HTTPException(400, "référence de page invalide")
                    citations[cle] = [refs[value] for value in choisies]
            proposition = {"schema_version": 1, "champs": champs, "citations": citations}
            await bloquant(
                fusion_ap.enregistrer,
                cnx_factory,
                session.utilisateur,
                lot_id,
                mutation_id=fields["mutation_id"],
                revision_pdf_attendue=revision_pdf,
                revision_attendue=revision_ap,
                proposition=proposition,
            )
            session = session_vivante(request, session.utilisateur)
        except HTTPException as exc:
            session = session_vivante(request, session.utilisateur)
            return echec_prive(request, session, exc)
        reponse = _privee(RedirectResponse(f"{prefixe}/fusion/pdf/lots/{lot_id}/ap", status_code=303))
        session_vivante(request, session.utilisateur)
        return reponse

    @router.post("/fusion/pdf/lots/{lot_id}/ap/verifier-m5", response_class=HTMLResponse)
    async def verifier_ap_m5(lot_id: str, request: Request) -> HTMLResponse:
        session = session_vivante(request)
        sans_query(request)
        valider_lot(lot_id)
        verifier_role_finance(session)
        fields = await _formulaire(
            request,
            {"csrf", "revision_pdf", "revision_ap", "po_id", "fournisseur_id", "correspondance_confirmee"},
        )
        session = session_vivante(request, session.utilisateur)
        verifier_role_finance(session)
        valider_csrf(fields, session)
        revision_pdf = _revision(fields["revision_pdf"], positive=True)
        revision_ap = _revision(fields["revision_ap"], positive=True)
        po_id, fournisseur_id = fields["po_id"], fields["fournisseur_id"]
        if (
            not po_id
            or len(po_id) > 64
            or po_id.strip() != po_id
            or any(ord(char) < 32 for char in po_id)
            or not fournisseur_id
            or len(fournisseur_id) > 64
            or fournisseur_id.strip() != fournisseur_id
            or any(ord(char) < 32 for char in fournisseur_id)
        ):
            raise HTTPException(400, {"code": "IDENTIFIANT_M5_INVALIDE"})
        if fields["correspondance_confirmee"] != "oui":
            raise HTTPException(400, {"code": "CORRESPONDANCE_NON_ATTESTEE"})
        try:
            resultat = await bloquant(
                fusion_ap_m5.verifier,
                cnx_factory,
                session.utilisateur,
                lot_id,
                revision_pdf=revision_pdf,
                revision_ap=revision_ap,
                po_id=po_id,
                fournisseur_id=fournisseur_id,
                correspondance_confirmee=True,
            )
            session = session_vivante(request, session.utilisateur)
            verifier_role_finance(session)
            await bloquant(fusion_ap_m5.confirmer_sources, cnx_factory, session.utilisateur, lot_id, resultat)
            session = session_vivante(request, session.utilisateur)
            verifier_role_finance(session)
            contenu = _resultat_m5(resultat)
            contenu += _confirmation_saisie_m5(
                prefixe, session, lot_id, revision_pdf, revision_ap, po_id, fournisseur_id, resultat
            )
        except HTTPException as exc:
            session = session_vivante(request, session.utilisateur)
            return echec_prive(request, session, exc)
        except Exception:
            session = session_vivante(request, session.utilisateur)
            return echec_prive(request, session, HTTPException(503, {"code": "VERIFICATION_M5_INDISPONIBLE"}))
        reponse = rendre_prive(
            request,
            session,
            '<section class="carte pile"><h1>Vérification AP préparatoire</h1>' + contenu + '</section>',
        )
        verifier_role_finance(session_vivante(request, session.utilisateur))
        return reponse

    @router.post("/fusion/pdf/lots/{lot_id}/ap/saisir-m5", response_class=HTMLResponse)
    async def saisir_ap_m5(lot_id: str, request: Request) -> HTMLResponse:
        session = session_vivante(request)
        sans_query(request)
        valider_lot(lot_id)
        verifier_role_finance(session)
        fields = await _formulaire(
            request,
            {
                "csrf", "revision_pdf", "revision_ap", "po_id", "fournisseur_id",
                "correspondance_confirmee", "saisie_confirmee", "snapshot_attendu", "mutation_id",
            },
        )
        session = session_vivante(request, session.utilisateur)
        verifier_role_finance(session)
        valider_csrf(fields, session)
        revision_pdf = _revision(fields["revision_pdf"], positive=True)
        revision_ap = _revision(fields["revision_ap"], positive=True)
        po_id, fournisseur_id = fields["po_id"], fields["fournisseur_id"]
        if (
            not po_id or len(po_id) > 64 or po_id.strip() != po_id or not po_id.isprintable()
            or not fournisseur_id or len(fournisseur_id) > 64
            or fournisseur_id.strip() != fournisseur_id or not fournisseur_id.isprintable()
        ):
            raise HTTPException(400, {"code": "IDENTIFIANT_M5_INVALIDE"})
        if fields["correspondance_confirmee"] != "oui":
            raise HTTPException(400, {"code": "CORRESPONDANCE_NON_ATTESTEE"})
        if fields["saisie_confirmee"] != "oui":
            raise HTTPException(400, {"code": "SAISIE_NON_CONFIRMEE"})
        if not _SHA256.fullmatch(fields["snapshot_attendu"]):
            raise HTTPException(400, {"code": "SNAPSHOT_M5_INVALIDE"})
        if not re.fullmatch(r"[0-9a-f]{32}", fields["mutation_id"]):
            raise HTTPException(400, {"code": "IDENTIFIANT_MUTATION_INVALIDE"})
        try:
            from . import fusion_ap_m5_saisie

            resultat = await bloquant(
                fusion_ap_m5_saisie.saisir,
                cnx_factory,
                session.utilisateur,
                lot_id,
                deps=deps,
                revision_pdf=revision_pdf,
                revision_ap=revision_ap,
                po_id=po_id,
                fournisseur_id=fournisseur_id,
                correspondance_confirmee=True,
                saisie_confirmee=True,
                snapshot_attendu=fields["snapshot_attendu"],
                mutation_id=fields["mutation_id"],
            )
            session = session_vivante(request, session.utilisateur)
            verifier_role_finance(session)
            contenu = _recu_saisie_m5(resultat, prefixe=prefixe, lot_id=lot_id)
        except HTTPException as exc:
            session = session_vivante(request, session.utilisateur)
            return echec_prive(request, session, exc)
        except Exception:
            session = session_vivante(request, session.utilisateur)
            return echec_prive(request, session, HTTPException(503, {"code": "SAISIE_M5_INDISPONIBLE"}))
        reponse = rendre_prive(
            request,
            session,
            '<section class="carte pile"><h1>Saisie AP M5</h1>' + contenu + '</section>',
        )
        verifier_role_finance(session_vivante(request, session.utilisateur))
        return reponse

    return router
