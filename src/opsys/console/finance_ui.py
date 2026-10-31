"""Console CFO : rendu HTML et routes métier M5 par les contrats canoniques.

Les lectures ne créent pas de mouvement ni de constat métier. Une demande de décision capital
est une analyse préparatoire idempotente et signée par la session console active.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Mapping
from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from .. import contexte
from . import memoire_chantier as autorite
from . import metier, pages, securite
from .securite import Session

_MONTANT = re.compile(r"^[0-9]{1,12}(?:\.[0-9]{1,2})?$")
_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_MAX_TEXTE = 120
_CHAMPS_DECISION = frozenset(
    {
        "actif",
        "prix",
        "source_prix",
        "prix_valide_jusqua",
        "offre_financement",
        "offre_location",
        "mutation_id",
    }
)
_CHAMPS_OFFRE = frozenset({"source", "mise_de_fonds", "paiement_mensuel", "mois"})
_STATUTS_OBLIGATIONS = {
    "INCOMPLETE": "Données incomplètes",
    "SOURCE_PERIMEE": "Source périmée",
    "ECHEANCE_PASSEE_A_VERIFIER": "Échéance passée à vérifier",
    "DOCUMENTEE_A_VALIDER": "Documentée, à valider",
}


def _texte(data: Mapping[str, Any], cle: str, *, max_length: int = _MAX_TEXTE) -> str:
    valeur = data.get(cle)
    if not isinstance(valeur, str) or not valeur.strip() or len(valeur) > max_length:
        raise HTTPException(400, f"{cle} invalide")
    return valeur.strip()


def _montant(data: Mapping[str, Any], cle: str) -> str:
    valeur = _texte(data, cle, max_length=16)
    if not _MONTANT.fullmatch(valeur):
        raise HTTPException(400, f"{cle} doit être un montant CAD en texte décimal")
    return valeur


def _date(data: Mapping[str, Any], cle: str) -> str:
    valeur = _texte(data, cle, max_length=10)
    if not _DATE.fullmatch(valeur):
        raise HTTPException(400, f"{cle} doit être une date AAAA-MM-JJ")
    try:
        date.fromisoformat(valeur)
    except ValueError as exc:
        raise HTTPException(400, f"{cle} invalide") from exc
    return valeur


def _offre_json(valeur: Any, cle: str) -> dict[str, Any]:
    if not isinstance(valeur, dict) or set(valeur) != _CHAMPS_OFFRE:
        raise HTTPException(400, f"{cle} doit contenir exactement source, mise_de_fonds, paiement_mensuel et mois")
    source = _texte(valeur, "source")
    mise = _montant(valeur, "mise_de_fonds")
    paiement = _montant(valeur, "paiement_mensuel")
    mois = valeur.get("mois")
    if type(mois) is not int or not 1 <= mois <= 600:
        raise HTTPException(400, f"{cle}.mois invalide")
    return {"source": source, "mise_de_fonds": mise, "paiement_mensuel": paiement, "mois": mois}


def _decision_json(data: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    if set(data) != _CHAMPS_DECISION:
        raise HTTPException(400, "champs de décision invalides")
    mutation_id = _texte(data, "mutation_id", max_length=200)
    args = {
        "actif": _texte(data, "actif"),
        "prix": _montant(data, "prix"),
        "source_prix": _texte(data, "source_prix"),
        "prix_valide_jusqua": _date(data, "prix_valide_jusqua"),
        "offre_financement": _offre_json(data.get("offre_financement"), "offre_financement"),
        "offre_location": _offre_json(data.get("offre_location"), "offre_location"),
    }
    return args, mutation_id


def _decision_form(data: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    champs = _CHAMPS_DECISION - {"offre_financement", "offre_location"}
    champs_form = (
        champs
        | {"csrf"}
        | {f"{offre}_{champ}" for offre in ("offre_financement", "offre_location") for champ in _CHAMPS_OFFRE}
    )
    if set(data) != champs_form:
        raise HTTPException(400, "champs du formulaire invalides")
    converti = {
        "actif": data.get("actif"),
        "prix": data.get("prix"),
        "source_prix": data.get("source_prix"),
        "prix_valide_jusqua": data.get("prix_valide_jusqua"),
        "mutation_id": data.get("mutation_id"),
    }
    for offre in ("offre_financement", "offre_location"):
        converti[offre] = {champ: data.get(f"{offre}_{champ}") for champ in _CHAMPS_OFFRE}
        converti[offre]["mois"] = _entier_formulaire(converti[offre]["mois"], f"{offre}.mois")
    return _decision_json(converti)


def _entier_formulaire(valeur: Any, cle: str) -> int:
    if not isinstance(valeur, str) or not valeur.isascii() or not valeur.isdigit() or len(valeur) > 3:
        raise HTTPException(400, f"{cle} invalide")
    resultat = int(valeur)
    if not 1 <= resultat <= 600:
        raise HTTPException(400, f"{cle} invalide")
    return resultat


def _appeler(
    cnx_factory: Callable[[], Any],
    deps: Mapping[str, Any],
    session: Session,
    nom: str,
    arguments: Mapping[str, Any],
    *,
    mutation_id: str | None = None,
) -> dict[str, Any]:
    try:
        with cnx_factory() as cnx:
            return metier.executer(cnx, deps, session, nom, arguments, mutation_id=mutation_id)
    except PermissionError as exc:
        raise HTTPException(403, "accès métier refusé") from exc
    except KeyError as exc:
        raise HTTPException(404, "outil M5 indisponible") from exc
    except ValueError as exc:
        texte = str(exc)
        code = 409 if "conflit" in texte.lower() else 400
        raise HTTPException(code, "demande métier refusée") from exc


def _resultat(reponse: Mapping[str, Any]) -> Mapping[str, Any]:
    if reponse.get("ok") is not True:
        return {"accepte": False, "erreur": reponse.get("erreur", "outil_refuse")}
    valeur = reponse.get("resultat")
    return valeur if isinstance(valeur, Mapping) else {"accepte": False, "erreur": "réponse M5 invalide"}


def _cash(reponse: Mapping[str, Any]) -> Mapping[str, Any] | None:
    corps = _resultat(reponse)
    if corps.get("accepte") is False:
        return None
    cash = corps.get("cash_libre")
    return cash if isinstance(cash, Mapping) else None


def _liste_manques(valeurs: Any) -> str:
    if not isinstance(valeurs, (list, tuple)) or not valeurs:
        return ""
    items = "".join(f"<li>{pages.e(_description(item))}</li>" for item in valeurs)
    return f"<ul>{items}</ul>"


def _description(valeur: Any) -> str:
    if isinstance(valeur, Mapping):
        for cle in ("description", "detail", "libelle", "code"):
            if valeur.get(cle) is not None:
                return str(valeur[cle])
        return "Indisponible"
    return str(valeur)


def _fraicheur(valeur: Any) -> str:
    if not isinstance(valeur, Mapping):
        return "Date de la source inconnue"
    derniere = valeur.get("derniere_piece")
    return f"Dernière pièce : {derniere}" if derniere else "Date de la source inconnue"


def _contenu_cash(cash: Mapping[str, Any] | None) -> str:
    if cash is None:
        return '<p class="message message-erreur">État financier indisponible ou accès refusé.</p>'
    statut = "Calculable" if cash.get("calculable") is True else "Non calculable"
    total = cash.get("cash_libre")
    composantes = cash.get("composantes", [])
    lignes = []
    if isinstance(composantes, list):
        for item in composantes:
            if not isinstance(item, Mapping):
                continue
            source = item.get("source", {})
            lignes.append(
                "<tr>"
                f'<th scope="row">{pages.e(item.get("libelle", item.get("id")))}</th>'
                f"<td>{pages.e(item.get('statut'))}</td>"
                f"<td>{pages.e(item.get('montant')) if item.get('montant') is not None else '—'}</td>"
                f"<td>{pages.e(_description(source))}</td>"
                f"<td>{pages.e(_fraicheur(item.get('fraicheur')))}</td>"
                f"<td>{_liste_manques(item.get('manque'))}</td></tr>"
            )
    table = (
        "<table><thead><tr><th>Obligation / composante</th><th>Statut</th><th>Montant CAD</th>"
        "<th>Source</th><th>Fraîcheur</th><th>Manquants</th></tr></thead><tbody>" + "".join(lignes) + "</tbody></table>"
    )
    manque = _liste_manques(cash.get("manque")) or "<p>Aucun manquant déclaré.</p>"
    ident = cash.get("cash_libre_id", "")
    return (
        '<section class="carte pile"><h2>Cash libre réel</h2>'
        f"<p>Statut : <strong>{pages.e(statut)}</strong></p>"
        f"<p>Cash libre CAD : <strong>{pages.e(total) if total is not None else '—'}</strong></p>"
        f"<p>Source de l’état : empreinte <code>{pages.e(ident)}</code></p>{table}"
        f"<h3>Manquants qui bloquent le calcul</h3>{manque}</section>"
    )


def _contenu_obligations(reponse: Mapping[str, Any]) -> str:
    corps = _resultat(reponse)
    calendrier = corps.get("resultat")
    if corps.get("accepte") is False or not isinstance(calendrier, Mapping):
        return '<section class="carte"><h2>Échéances et obligations</h2><p>Calendrier indisponible.</p></section>'
    lignes = []
    for ligne in calendrier.get("obligations", []):
        if not isinstance(ligne, Mapping):
            continue
        montant = ligne.get("montant_utilisable")
        source = ligne.get("source_echeance", {})
        periode = ligne.get("periode", {})
        periode = periode if isinstance(periode, Mapping) else {}
        lignes.append(
            "<tr>"
            f"<th scope='row'>{pages.e(ligne.get('nom'))}</th>"
            f"<td>{pages.e(ligne.get('autorite') or 'À déclarer')}</td>"
            f"<td>{pages.e(periode.get('debut') or '—')} / {pages.e(periode.get('fin') or '—')}</td>"
            f"<td>{pages.e(ligne.get('echeance') or 'À déclarer')}</td>"
            f"<td>{pages.e(montant) if montant is not None else 'Non calculable'}</td>"
            f"<td>{pages.e(_STATUTS_OBLIGATIONS.get(ligne.get('statut'), 'À vérifier'))}</td>"
            f"<td>{pages.e(_description(source))}<br>Version : {pages.e(ligne.get('version') or '—')}</td>"
            f"<td>{_liste_manques(ligne.get('manque'))}</td></tr>"
        )
    return (
        '<section class="carte pile"><h2>Échéances et obligations</h2>'
        f"<p>Situation au {pages.e(calendrier.get('aujourd_hui'))}. Validation humaine requise.</p>"
        '<div class="table-defilante"><table><thead><tr><th>Obligation</th><th>Autorité</th>'
        "<th>Période</th><th>Échéance</th><th>Montant CAD documenté</th><th>État</th>"
        "<th>Source de l’échéance</th><th>Données manquantes</th></tr></thead><tbody>"
        + "".join(lignes)
        + "</tbody></table></div><p>Une échéance passée reste à vérifier avec les pièces et les paiements.</p>"
        + f"<p>{pages.e(calendrier.get('mention', ''))}</p>"
        + _liste_manques(calendrier.get("limites"))
        + _contenu_echeances_taxes(calendrier.get("echeances_tps_tvq"))
        + "</section>"
    )


def _contenu_echeances_taxes(calendrier: Any) -> str:
    if not isinstance(calendrier, Mapping):
        return "<h3>TPS/TVQ préparatoires</h3><p>Calendrier indisponible.</p>"
    lignes = []
    for echeance in calendrier.get("echeances", []):
        if not isinstance(echeance, Mapping):
            continue
        taxes = echeance.get("taxes_nettes")
        montant = taxes.get("a_remettre") if isinstance(taxes, Mapping) else None
        couverture = taxes.get("couverture") if isinstance(taxes, Mapping) else None
        couverture_texte = (
            "Partielle : pièces reçues seulement"
            if isinstance(couverture, Mapping) and couverture.get("statut") == "PARTIELLE"
            else "Non documentée"
        )
        lignes.append(
            "<tr>"
            f"<td>{pages.e(echeance.get('periode_debut'))} / {pages.e(echeance.get('periode_fin'))}</td>"
            f"<td>{pages.e(echeance.get('limite_production'))}</td>"
            f"<td>{pages.e(echeance.get('limite_paiement'))}</td>"
            f"<td>{pages.e(montant) if montant is not None else 'Non calculable'}</td>"
            f"<td>{pages.e(couverture_texte)}</td></tr>"
        )
    sources = []
    for source in calendrier.get("sources", []):
        if isinstance(source, Mapping):
            sources.append(" · ".join(str(v) for v in source.values() if isinstance(v, (str, int))))
    contenu = "<h3>TPS/TVQ préparatoires</h3>"
    if lignes:
        contenu += (
            '<div class="table-defilante"><table><thead><tr><th>Période</th><th>Production</th>'
            "<th>Paiement</th><th>À remettre CAD estimé</th><th>Couverture des pièces</th></tr></thead><tbody>"
            + "".join(lignes)
            + "</tbody></table></div>"
        )
    else:
        contenu += "<p>Aucune échéance calculable avec les déclarations actuelles.</p>"
    contenu += _liste_manques(calendrier.get("manque"))
    contenu += _liste_manques(sources)
    if calendrier.get("avertissement_couverture"):
        contenu += f"<p>{pages.e(calendrier['avertissement_couverture'])}</p>"
    return contenu


def _champ(nom: str, label: str, *, value: str = "", placeholder: str = "", type_: str = "text") -> str:
    return (
        f'<label for="{pages.e(nom)}">{pages.e(label)}'
        f'<input id="{pages.e(nom)}" name="{pages.e(nom)}" type="{pages.e(type_)}" '
        f'value="{pages.e(value)}" placeholder="{pages.e(placeholder)}" required></label>'
    )


def _formulaire(
    *,
    prefixe: str,
    csrf: str,
    mutation_id: str,
    valeurs: Mapping[str, str] | None = None,
) -> str:
    vals = valeurs or {}
    out = [
        f'<form method="post" action="{pages.e(prefixe)}/finance/decision" class="carte pile">',
        f'<input type="hidden" name="csrf" value="{pages.e(csrf)}">',
        f'<input type="hidden" name="mutation_id" value="{pages.e(mutation_id)}">',
        "<h2>Question d’achat</h2>",
        _champ("actif", "Actif", value=vals.get("actif", ""), placeholder="Camion ou équipement"),
        _champ("prix", "Prix CAD", value=vals.get("prix", ""), placeholder="95000.00"),
        _champ("source_prix", "Référence de soumission", value=vals.get("source_prix", "")),
        _champ(
            "prix_valide_jusqua", "Soumission valide jusqu’au", value=vals.get("prix_valide_jusqua", ""), type_="date"
        ),
        "<fieldset><legend>Offre de financement</legend>",
        _champ("offre_financement_source", "Référence de l’offre", value=vals.get("offre_financement_source", "")),
        _champ(
            "offre_financement_mise_de_fonds",
            "Mise de fonds CAD",
            value=vals.get("offre_financement_mise_de_fonds", ""),
            placeholder="5000.00",
        ),
        _champ(
            "offre_financement_paiement_mensuel",
            "Paiement mensuel CAD",
            value=vals.get("offre_financement_paiement_mensuel", ""),
            placeholder="1600.00",
        ),
        _champ(
            "offre_financement_mois",
            "Durée en mois",
            value=vals.get("offre_financement_mois", ""),
            placeholder="60",
            type_="number",
        ),
        "</fieldset><fieldset><legend>Offre de location</legend>",
        _champ("offre_location_source", "Référence de l’offre", value=vals.get("offre_location_source", "")),
        _champ(
            "offre_location_mise_de_fonds",
            "Mise de fonds CAD",
            value=vals.get("offre_location_mise_de_fonds", ""),
            placeholder="3000.00",
        ),
        _champ(
            "offre_location_paiement_mensuel",
            "Paiement mensuel CAD",
            value=vals.get("offre_location_paiement_mensuel", ""),
            placeholder="1800.00",
        ),
        _champ(
            "offre_location_mois",
            "Durée en mois",
            value=vals.get("offre_location_mois", ""),
            placeholder="48",
            type_="number",
        ),
        '</fieldset><p class="note">Les montants d’exemple dans les champs sont des formats indicatifs; '
        "aucune donnée n’est préremplie. Les références saisies ne vérifient pas les documents.</p>",
        '<button type="submit">Comparer les scénarios</button></form>',
    ]
    return "".join(out)


def _rapport_html(rapport: Mapping[str, Any] | None, erreur: Mapping[str, Any] | None = None) -> str:
    if erreur is not None:
        code = pages.e(erreur.get("code", erreur.get("erreur", "decision_refusee")))
        detail = pages.e(erreur.get("detail", ""))
        return (
            '<section class="carte pile"><h2>Décision non calculable</h2>'
            f"<p>Verdict : <code>{code}</code></p><p>{detail}</p>"
            f"<h3>Données à fournir</h3>{_liste_manques(erreur.get('manque'))}</section>"
        )
    if rapport is None:
        return ""
    scenarios = rapport.get("scenarios", {})
    noms = {"achat_comptant": "Comptant", "financement": "Financement", "location": "Location"}
    cartes = []
    if isinstance(scenarios, Mapping):
        for cle, nom in noms.items():
            scenario = scenarios.get(cle)
            if not isinstance(scenario, Mapping):
                continue
            lignes = "".join(
                f"<li><strong>{pages.e(libelle)}</strong> : {pages.e(valeur)}</li>"
                for libelle, valeur in scenario.items()
            )
            cartes.append(f'<article class="carte"><h3>{nom}</h3><ul>{lignes}</ul></article>')
    contexte = rapport.get("contexte_financier", {})
    contexte_html = ""
    if isinstance(contexte, Mapping):
        devis = contexte.get("devis_acceptes", {})
        ar = contexte.get("comptes_a_recevoir", {})
        ap = contexte.get("comptes_a_payer", {})
        contrats = contexte.get("termes_contractuels_signes", {})
        provenance = contexte.get("provenance_des_offres", {})
        contexte_html = (
            '<section class="carte pile"><h2>Contexte et provenance</h2>'
            f"<p>Devis M3 reçus : {pages.e(devis.get('nombre'))}; valeur CAD : "
            f"{pages.e(devis.get('valeur_cad'))}; statut {pages.e(devis.get('statut'))}.</p>"
            f"<p>Comptes à recevoir : {pages.e(ar.get('nombre') if isinstance(ar, Mapping) else '—')}; "
            f"total CAD : {pages.e(ar.get('total_a_recevoir') if isinstance(ar, Mapping) else '—')}.</p>"
            f"<p>Comptes à payer : statut {pages.e(ap.get('statut') if isinstance(ap, Mapping) else '—')}; "
            f"montant CAD : {pages.e(ap.get('montant') if isinstance(ap, Mapping) else '—')}.</p>"
            f"<p>Contrats signés : {pages.e(contrats.get('statut'))}; "
            f"{_liste_manques(contrats.get('manque'))}</p>"
            f"<p>Offres : {pages.e(provenance.get('statut'))}; références fournies par l’appelant, "
            "documents non vérifiés.</p></section>"
        )
    questions = _liste_manques(rapport.get("questions_cpa"))
    risques = _liste_manques(rapport.get("limites"))
    sources = _liste_manques(rapport.get("sources_a_valider"))
    mention = pages.e(rapport.get("mention", ""))
    return (
        '<section class="pile"><h2>Scénarios préparatoires</h2><div class="grille">'
        + "".join(cartes)
        + "</div></section>"
        + contexte_html
        + f'<section class="carte"><h2>Sources à valider</h2>{sources}</section>'
        + f'<section class="carte"><h2>Risques et limites</h2>{risques}</section>'
        + f'<section class="carte"><h2>Questions pour le CPA</h2>{questions}</section>'
        + f'<p class="message message-alerte">{mention}</p>'
    )


def creer_router(
    *,
    session_page: Callable[..., Session],
    session_api: Callable[..., Session],
    ecriture_api: Callable[..., Session],
    formulaire: Callable[[Request], Any],
    objet_json: Callable[[Request], Any],
    cnx_factory: Callable[[], Any],
    deps: Mapping[str, Any],
    prefixe: str,
) -> APIRouter:
    """Routes CFO, protégées par les fonctions de session/CSRF de la console parente."""
    router = APIRouter(tags=["finance CFO"])

    def lire_cash(session: Session) -> tuple[dict[str, Any], Mapping[str, Any] | None]:
        reponse = _appeler(cnx_factory, deps, session, "m5_etat_tresorerie", {})
        corps = _resultat(reponse)
        return reponse, _cash(reponse) if corps.get("accepte") is not False else None

    def page_finance(
        session: Session,
        *,
        rapport: Mapping[str, Any] | None = None,
        erreur: Mapping[str, Any] | None = None,
        mutation_id: str | None = None,
        valeurs: Mapping[str, str] | None = None,
        message: str = "",
    ) -> HTMLResponse:
        _, cash = lire_cash(session)
        contenu = (
            f'<p><a class="bouton" href="{pages.e(prefixe)}/finance/cfo">'
            "Préparer un dossier de décision</a></p>"
            f'<p><a class="bouton" href="{pages.e(prefixe)}/finance/tarifs-equipes">'
            "Consulter les tarifs des équipes</a></p>"
            f'<p><a class="bouton" href="{pages.e(prefixe)}/finance/rapprochement-bancaire">'
            "Prévisualiser un rapprochement bancaire</a></p>"
            f'<p><a class="bouton" href="{pages.e(prefixe)}/finance/paie">'
            "Préparer un brut régulier</a></p>"
        ) + _contenu_cash(cash)
        obligations = _appeler(cnx_factory, deps, session, "m5_lire_calendrier_obligations", {})
        contenu += _contenu_obligations(obligations)
        if message:
            contenu += f'<p class="message message-alerte">{pages.e(message)}</p>'
        contenu += _formulaire(
            prefixe=prefixe, csrf=session.csrf, mutation_id=mutation_id or uuid.uuid4().hex, valeurs=valeurs
        )
        contenu += _rapport_html(rapport, erreur)
        return HTMLResponse(
            pages.gabarit("Finance et décisions", contenu, prefixe=prefixe, session=session, actif="finance")
        )

    def executer_decision(session: Session, data: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
        arguments, mutation_id = _decision_json(data)
        return _appeler(
            cnx_factory, deps, session, "m5_preparer_decision_capital", arguments, mutation_id=mutation_id
        ), mutation_id

    @router.get("/finance", response_class=HTMLResponse)
    def finance(request: Request) -> HTMLResponse:
        session = session_page(request)
        return page_finance(session)

    @router.get("/api/finance/cash-libre")
    def api_cash_libre(request: Request) -> dict[str, Any]:
        session = session_api(request)
        reponse, cash = lire_cash(session)
        return {"etat": _resultat(reponse), "cash_libre": cash}

    @router.get("/api/finance/obligations")
    def api_obligations(request: Request) -> dict[str, Any]:
        session = session_api(request)
        if request.query_params:
            raise HTTPException(400, "le calendrier utilise la date du serveur")
        reponse = _appeler(cnx_factory, deps, session, "m5_lire_calendrier_obligations", {})
        return {"etat": _resultat(reponse)}

    @router.post("/finance/decision", response_class=HTMLResponse)
    async def decision_form(request: Request) -> HTMLResponse:
        session = session_page(request)
        champs = await formulaire(request)
        if not isinstance(champs, Mapping) or not securite.csrf_valide(champs.get("csrf"), session):
            raise HTTPException(403, "jeton CSRF absent ou invalide")
        arguments, mutation_id = _decision_form(champs)
        try:
            reponse = _appeler(
                cnx_factory, deps, session, "m5_preparer_decision_capital", arguments, mutation_id=mutation_id
            )
        except HTTPException as exc:
            return page_finance(
                session,
                erreur={"code": "demande_refusee", "detail": exc.detail},
                mutation_id=mutation_id,
                valeurs=champs,
            )
        corps = _resultat(reponse)
        if corps.get("accepte") is True and isinstance(corps.get("resultat"), Mapping):
            return page_finance(session, rapport=corps["resultat"], mutation_id=mutation_id)
        verdict = corps.get("verdict") if isinstance(corps.get("verdict"), Mapping) else corps
        return page_finance(session, erreur=verdict, mutation_id=mutation_id, valeurs=champs)

    @router.post("/api/finance/decision")
    async def decision_api(request: Request) -> JSONResponse:
        session = ecriture_api(request)
        data = await objet_json(request)
        if not isinstance(data, Mapping):
            raise HTTPException(400, "objet JSON attendu")
        reponse, _ = executer_decision(session, data)
        return JSONResponse(reponse)

    def _tarifs(session: Session, data: Mapping[str, Any] | None) -> JSONResponse:
        """Port privé : seule la session console vérifiée peut déclarer un tarif."""
        dep = deps.get('m05-financecore')
        if dep is None or dep.module_outils != 'm5_financecore.outils':
            raise HTTPException(503, 'Source des tarifs indisponible')
        try:
            from m5_financecore import outils as m5
        except ImportError:
            raise HTTPException(503, 'Source des tarifs indisponible') from None
        try:
            with cnx_factory() as cnx:
                autorite._admin(cnx, session)
                with (contexte.appele_par_appareil(
                        contexte.IdentiteAppelante(session.utilisateur, 'admin', source='console')),
                      contexte.appeler_en_tant_que('m05-financecore', origine='console')):
                    if data is None:
                        resultat = m5._lire_tarifs_equipes()
                    else:
                        if set(data) != {'tarif', 'mutation_id', 'source_attendue'}:
                            raise HTTPException(400, 'Champs de déclaration invalides')
                        resultat = m5._inscrire_tarif_equipe(
                            data['tarif'], mutation_id=data['mutation_id'], source_attendue=data['source_attendue'])
                    reponse = JSONResponse(resultat, headers={'Cache-Control': 'no-store',
                        'X-Content-Type-Options': 'nosniff'})
                    if len(reponse.body) > 131072:
                        raise HTTPException(503, 'Source des tarifs trop volumineuse')
                    if data is None and m5._lire_tarifs_equipes() != resultat:
                        raise HTTPException(409, 'Source des tarifs modifiée')
                    autorite._admin(cnx, session)
        except PermissionError:
            raise HTTPException(403, 'Accès admin requis') from None
        except ValueError as exc:
            detail = str(exc).lower()
            integrity = ('chaîne invalide', 'empreinte invalide', 'rangs incomplets')
            if data is None or any(mot in detail for mot in integrity):
                code = 503
            else:
                code = 409 if any(mot in detail for mot in ('périmée', 'divergente', 'ambigu', 'révision')) else 400
            raise HTTPException(code, 'Déclaration de tarif refusée') from None
        return reponse

    @router.get('/api/finance/tarifs-equipes')
    def lire_tarifs_equipes(request: Request) -> JSONResponse:
        session = session_api(request)
        if request.query_params:
            raise HTTPException(400, 'Paramètres de consultation invalides')
        return _tarifs(session, None)

    @router.post('/api/finance/tarifs-equipes')
    async def declarer_tarif_equipe(request: Request) -> JSONResponse:
        session = ecriture_api(request)
        if request.query_params:
            raise HTTPException(400, 'Paramètres de déclaration invalides')
        data = await objet_json(request)
        if not isinstance(data, Mapping):
            raise HTTPException(400, 'Objet JSON requis')
        return _tarifs(session, data)

    @router.get('/finance/tarifs-equipes')
    def page_tarifs_equipes(request: Request) -> HTMLResponse:
        import json

        session = session_page(request)
        if request.query_params:
            raise HTTPException(400, 'Paramètres de consultation invalides')
        try:
            with cnx_factory() as cnx:
                autorite._admin(cnx, session)
                vue = json.loads(_tarifs(session, None).body)
                champs = (('equipe_id', 'Équipe'), ('taux', 'Taux CAD par heure-équipe'),
                          ('source', 'Source'), ('version', 'Version'), ('date_effet', 'Date de début'),
                          ('date_fin', 'Date de fin'), ('remplace_id', 'Référence à remplacer (facultatif)'))
                colonnes = ('equipe_id', 'taux', 'devise', 'unite', 'source', 'version',
                            'date_effet', 'date_fin', 'ligne_id')
                lignes = ''.join(
                    '<tr>' + ''.join(f'<td>{pages.e(ligne.get(k))}</td>' for k in
                        colonnes)
                    + '</tr>' for ligne in vue['lignes'])
                formulaire_html = ''.join(
                    f'<label>{pages.e(libelle)} <input name="{nom}"'
                    f'{"" if nom == "remplace_id" else " required"}></label>'
                    for nom, libelle in champs)
                corps = ('<p>Déclarations préparatoires. Aucun paiement ni écriture comptable.</p>'
                    '<table><thead><tr><th>Équipe</th><th>Taux</th><th>Devise</th><th>Unité</th>'
                    '<th>Source</th><th>Version</th><th>Début</th><th>Fin</th><th>Référence</th></tr></thead>'
                    f'<tbody>{lignes}</tbody></table><form method="post" '
                    f'action="{pages.e(prefixe)}/finance/tarifs-equipes">'
                    f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">'
                    f'<input type="hidden" name="source_attendue" value="{pages.e(vue["source"])}">'
                    f'<input type="hidden" name="mutation_id" value="{uuid.uuid4().hex}">'
                    f'{formulaire_html}<button type="submit">Déclarer le tarif</button></form>')
                reponse = HTMLResponse(pages.gabarit('Tarifs des équipes', corps, prefixe=prefixe,
                                                    session=session, actif='finance'))
                if len(reponse.body) > 131072:
                    raise HTTPException(503, 'Présentation des tarifs trop volumineuse')
                if json.loads(_tarifs(session, None).body) != vue:
                    raise HTTPException(409, 'Source des tarifs modifiée')
                autorite._admin(cnx, session)
                reponse.headers['Cache-Control'] = 'no-store'
                reponse.headers['X-Content-Type-Options'] = 'nosniff'
                return reponse
        except PermissionError:
            raise HTTPException(403, "Accès admin requis") from None
        except ValueError:
            raise HTTPException(503, "Source des tarifs indisponible") from None

    @router.post('/finance/tarifs-equipes')
    async def declarer_tarif_equipe_form(request: Request) -> HTMLResponse:
        from fastapi.responses import RedirectResponse

        session = session_page(request)
        if request.query_params:
            raise HTTPException(400, 'Paramètres de déclaration invalides')
        champs = await formulaire(request)
        if not isinstance(champs, Mapping) or not securite.csrf_valide(champs.get('csrf'), session):
            raise HTTPException(403, 'Jeton CSRF absent ou invalide')
        noms = {'csrf', 'mutation_id', 'source_attendue', 'equipe_id', 'taux', 'source', 'version',
                'date_effet', 'date_fin', 'remplace_id'}
        if set(champs) != noms:
            raise HTTPException(400, 'Champs de déclaration invalides')
        tarif = {k: champs[k] for k in ('equipe_id', 'taux', 'source', 'version', 'date_effet', 'date_fin')}
        tarif.update(unite='heure-equipe', devise='CAD', remplace_id=champs['remplace_id'] or None)
        _tarifs(session, {'tarif': tarif, 'mutation_id': champs['mutation_id'],
                          'source_attendue': champs['source_attendue']})
        return RedirectResponse(f'{prefixe}/finance/tarifs-equipes', status_code=303,
                                headers={'Cache-Control': 'no-store'})

    return router
