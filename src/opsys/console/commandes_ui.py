"""Console « Commandes » : les bons de commande de M6, pour que l'admin voie ce qui est à approuver, envoyé sans
réponse, partiellement reçu ou en retard (chantier C3 de l'analyse M6).

Lecture seule. La page ne calcule rien : elle montre ce que `m6_lister_po` et `m6_lire_po` (outils N0 de M6, réservés à
l'admin) rendent. Elle n'approuve, n'envoie, ne reçoit, n'annule rien : ces gestes passent par leurs outils et leurs
approbations (N3, N4), jamais par un bouton de cette page. Aucun prix de ligne n'est montré dans la liste ; le courriel
de commande (adresse du fournisseur comprise) n'est que dans le détail. Aucun mot de jugement sur une personne : ce sont
des états de documents.

Gardes (mêmes que la Collecte) : session obligatoire, rôle `admin` RELU EN BASE avant l'appel, en-têtes `no-store`,
aucun
formulaire, aucune écriture, contrôle de secret avant de servir, paramètres de requête fermés (un paramètre inconnu ou
répété est refusé).

Routes : /commandes (liste, filtres `statut`, `en_retard`, `debut`) ; /commandes/{po_id} (détail)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from .. import identite
from ..secrets_coffre import masquage
from . import metier, pages
from .securite import Session

ENTETES = {"Cache-Control": "no-store", "Pragma": "no-cache"}
BASE = "/commandes"
_PAGE = 25
_PARAMETRES_LISTE = {"statut", "en_retard", "debut"}
LIBELLES_STATUT = {
    "draft": "Brouillon",
    "pending_admin_review": "En revue (admin)",
    "approved": "Approuvé",
    "email_ready": "Courriel prêt",
    "sent_to_supplier": "Envoyé au fournisseur",
    "supplier_confirmed": "Confirmé par le fournisseur",
    "partially_received": "Partiellement reçu",
    "received": "Reçu",
    "cancelled": "Annulé",
    "disputed": "Contesté",
    "invoiced": "Facturé",
    "closed": "Fermé",
}
LIBELLES_MODE = {
    "livraison_depot": "Livraison au dépôt",
    "livraison_chantier": "Livraison au chantier",
    "ramassage": "Ramassage",
}
_FILTRES_RAPIDES = (
    ("", "", "Tous"),
    ("draft", "", "À approuver"),
    ("sent_to_supplier", "", "Envoyés, sans confirmation"),
    ("partially_received", "", "Partiellement reçus"),
    ("", "1", "En retard"),
)


def _libelle_statut(statut: Any) -> str:
    return LIBELLES_STATUT.get(statut, str(statut))


def _entier_borne(texte: str | None, maximum: int) -> int:
    if texte is None:
        return 0
    if not texte.isascii() or not texte.isdigit() or len(texte) > 6 or int(texte) > maximum:
        raise HTTPException(400, "Paramètres invalides")
    return int(texte)


def _montant(valeur: Any) -> str:
    return "—" if valeur is None else f"{valeur:,.2f} $".replace(",", " ").replace(".", ",")


def _quantite(valeur: Any) -> str:
    if valeur is None:
        return "—"
    return str(valeur).removesuffix(".0").replace(".", ",")


def _liens_filtres(prefixe: str, statut: str | None, en_retard: bool) -> str:
    liens = []
    for cible, retard, libelle in _FILTRES_RAPIDES:
        courant = (cible or None) == statut and bool(retard) == en_retard
        requete = {k: v for k, v in (("statut", cible), ("en_retard", retard)) if v}
        href = prefixe + BASE + ("?" + urlencode(requete) if requete else "")
        marque = ' aria-current="true"' if courant else ""
        liens.append(f'<a href="{pages.e(href)}"{marque}>{pages.e(libelle)}</a>')
    return '<nav aria-label="Filtres des commandes"><p>' + " · ".join(liens) + "</p></nav>"


def _ligne_liste(po: Mapping[str, Any], prefixe: str) -> str:
    badges = ""
    if po["en_retard"]:
        badges += " " + pages._badge("En retard", "badge-danger")
    if not po["commandable"]:
        badges += " " + pages._badge("Incomplet", "badge-alerte")
    lien = f'{prefixe}{BASE}/{pages._segment(po["po_id"])}'
    fournisseur = po["fournisseur_nom"] or po["fournisseur_id"]
    return (
        f'<tr><th scope="row"><a href="{lien}">{pages.e(po["po_id"])}</a></th>'
        f"<td>{pages.e(_libelle_statut(po['statut']))}{badges}</td>"
        f"<td>{pages.e(fournisseur)}</td>"
        f"<td>{pages.e(po['chantier_id'])}</td>"
        f"<td>{pages.e(po['date_requise'] or '—')}</td>"
        f"<td>{pages.e(LIBELLES_MODE.get(po['mode_livraison'], '—'))}</td>"
        f"<td>{pages.e(_montant(po['montant_total_prevu']))}</td>"
        f"<td>{int(po['nb_livraisons'])}</td></tr>"
    )


def rendre_liste(page: Mapping[str, Any], prefixe: str, statut: str | None, en_retard: bool, debut: int) -> str:
    comptes = " · ".join(
        f"{pages.e(_libelle_statut(s))} : {int(n)}" for s, n in page["comptes"].items()
    ) or "aucun bon de commande"
    lignes = "".join(_ligne_liste(po, prefixe) for po in page["pos"])
    tableau = (
        '<div class="table-defilante"><table><caption>Bons de commande</caption><thead><tr>'
        '<th scope="col">Bon</th><th scope="col">Statut</th><th scope="col">Fournisseur</th>'
        '<th scope="col">Chantier</th><th scope="col">Date requise</th><th scope="col">Livraison</th>'
        '<th scope="col">Montant prévu</th><th scope="col">Livraisons reçues</th></tr></thead>'
        f"<tbody>{lignes}</tbody></table></div>"
        if lignes else "<p>Aucun bon de commande ne correspond à ce filtre.</p>"
    )
    navigation = ""
    precedent = max(0, debut - _PAGE) if debut else None
    for decalage, libelle in ((precedent, "Page précédente"), (page["suivant"], "Page suivante")):
        if decalage is not None:
            requete = {
                k: v for k, v in (
                    ("statut", statut or ""), ("en_retard", "1" if en_retard else ""),
                    ("debut", str(decalage) if decalage else ""),
                ) if v
            }
            lien = pages.e(prefixe + BASE + "?" + urlencode(requete))
            navigation += f'<p><a href="{lien}">{libelle}</a></p>'
    return (
        "<p>Cette page est en lecture seule : elle n'approuve, n'envoie, ne reçoit et n'annule rien. "
        "Ces gestes passent par leurs outils et leurs approbations. Un bon « en retard » est envoyé, confirmé ou "
        "partiellement reçu avec une date requise dépassée.</p>"
        f"{_liens_filtres(prefixe, statut, en_retard)}<h2>Résumé</h2><p>{comptes}</p>"
        f"<h2>Liste</h2>{tableau}<p>{int(page['total'])} bon(s) de commande.</p>{navigation}"
    )


def _ligne_materiau(ligne: Mapping[str, Any]) -> str:
    nom = pages.e(ligne["designation"] or ligne["materiau_id"])
    code = f"<br><code>{pages.e(ligne['materiau_id'])}</code>" if ligne["designation"] else ""
    perte = ligne["facteur_perte"] if ligne["facteur_perte"] is not None else "non déclarée"
    prix = "" if ligne["verdict_prix"] != "INDETERMINE" else " (prix à fournir)"
    return (
        f'<tr><th scope="row">{nom}{code}</th><td>{pages.e(ligne["unite"] or "—")}</td>'
        f"<td>{pages.e(_quantite(ligne['quantite_nette']))}</td><td>{pages.e(perte)}</td>"
        f"<td>{pages.e(_quantite(ligne['quantite_demandee']))}</td>"
        f"<td>{pages.e(_montant(ligne['montant_ligne_prevu']))}{prix}</td></tr>"
    )


def _ligne_historique(h: Mapping[str, Any]) -> str:
    detail = pages.e(h.get("motif_annulation") or h.get("motif_statut") or h.get("verdict_reception") or "")
    constat = "; envoi constaté par M1" if h.get("envoi_constate") else ""
    return (
        f"<tr><td>{pages.e(h['horodatage'])}</td><td>{pages.e(_libelle_statut(h['statut']))}</td>"
        f"<td>{detail}{constat}</td></tr>"
    )


def _ligne_recu(c: Mapping[str, Any]) -> str:
    return (
        f'<tr><th scope="row">{pages.e(c["materiau_id"])}</th>'
        f"<td>{pages.e(_quantite(c['quantite_demandee']))}</td>"
        f"<td>{pages.e(_quantite(c['quantite_recue_cumulee']))}</td>"
        f"<td>{pages.e(_quantite(c['ecart_cumule']))}</td></tr>"
    )


def rendre_detail(po: Mapping[str, Any], prefixe: str) -> str:
    lignes = "".join(_ligne_materiau(ligne) for ligne in po["lignes"])
    historique = "".join(_ligne_historique(h) for h in po["historique"])
    cumul = po["reception_cumulee"]
    recu = "".join(_ligne_recu(c) for c in (cumul["lignes"] if cumul else ()))
    courriel = po["courriel"]
    badges = (" " + pages._badge("En retard", "badge-danger") if po["en_retard"] else "") + (
        "" if po["commandable"] else " " + pages._badge("Incomplet", "badge-alerte"))
    manque = "" if po["commandable"] else (
        "<p>Ce bon est incomplet (il manque : " + pages.e(", ".join(po["manques"])) + "). "
        "Il ne peut être ni approuvé ni envoyé tel quel : on l'annule et on le refait.</p>")
    fournisseur = po["fournisseur_nom"] or po["fournisseur_id"]
    mode = LIBELLES_MODE.get(po["mode_livraison"], "—")
    lieu = f" : {pages.e(po['lieu_livraison'])}" if po["lieu_livraison"] else ""
    notes = f" · Notes : {pages.e(po['notes'])}" if po["notes"] else ""
    en_tete = (
        f'<p><a href="{pages.e(prefixe + BASE)}">Tous les bons de commande</a></p>'
        f"<h2>{pages.e(po['po_id'])} · {pages.e(_libelle_statut(po['statut']))}{badges}</h2>{manque}"
        f"<p>Fournisseur : {pages.e(fournisseur)} · Chantier : {pages.e(po['chantier_id'])} · "
        f"Devis : {pages.e(po['devis_id'] or '—')}</p>"
        f"<p>Date requise : {pages.e(po['date_requise'] or '—')} · {pages.e(mode)}{lieu}{notes} · "
        f"Montant prévu : {pages.e(_montant(po['montant_total_prevu']))}</p>"
    )
    table_lignes = (
        '<div class="table-defilante"><table><caption>Lignes commandées</caption><thead><tr>'
        '<th scope="col">Matériau</th><th scope="col">Unité</th><th scope="col">Quantité nette</th>'
        '<th scope="col">Perte déclarée</th><th scope="col">À commander</th>'
        '<th scope="col">Montant prévu</th></tr></thead>'
        f"<tbody>{lignes}</tbody></table></div>"
    )
    table_recu = (
        '<div class="table-defilante"><table><caption>Réception cumulée</caption><thead><tr>'
        '<th scope="col">Matériau</th><th scope="col">Commandé</th><th scope="col">Reçu en tout</th>'
        f'<th scope="col">Écart</th></tr></thead><tbody>{recu}</tbody></table></div>'
        if cumul else ""
    )
    adresse = courriel["destinataire"] or "aucune adresse de commande : envoi à la main" if courriel else ""
    bloc_courriel = (
        f"<h2>Courriel de commande</h2><p>À : {pages.e(adresse)}<br>Objet : {pages.e(courriel['objet'])}</p>"
        f"<pre>{pages.e(courriel['corps'])}</pre>"
        if courriel else ""
    )
    vide = "<tr><td colspan=3>Brouillon, aucune transition.</td></tr>"
    table_historique = (
        '<div class="table-defilante"><table><caption>Historique</caption><thead><tr>'
        '<th scope="col">Quand</th><th scope="col">Statut</th><th scope="col">Détail</th></tr></thead>'
        f"<tbody>{historique or vide}</tbody></table></div>"
    )
    return en_tete + table_lignes + table_recu + bloc_courriel + table_historique


def creer_router(
    *,
    session_page: Callable[..., Session],
    cnx_factory: Callable[[], Any],
    deps: Mapping[str, Any],
    prefixe: str,
) -> APIRouter:
    router = APIRouter(tags=["commandes"])
    masquage.installer()

    def exiger_admin(session: Session) -> None:
        with cnx_factory() as cnx:
            personne = identite.personne_active(cnx, session.utilisateur)
        if personne is None or "admin" not in personne.roles:
            raise HTTPException(403, "administration requise")

    def appeler_outil(session: Session, nom: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            with cnx_factory() as cnx:
                reponse = metier.executer(cnx, deps, session, nom, arguments)
        except PermissionError as exc:
            raise HTTPException(403, "accès refusé") from exc
        except KeyError as exc:
            raise HTTPException(404, "approvisionnement indisponible") from exc
        resultat = reponse.get("resultat") if isinstance(reponse, Mapping) and reponse.get("ok") is True else None
        if not isinstance(resultat, Mapping):
            raise HTTPException(409, "lecture des commandes refusée")
        if resultat.get("accepte") is not True:
            verdict = resultat.get("verdict")
            code = verdict.get("code") if isinstance(verdict, Mapping) else ""
            if code == "REJ-PO-INTROUVABLE":
                raise HTTPException(404, "bon de commande introuvable")
            if "IDENTITE" in str(code):
                raise HTTPException(403, "accès refusé")
            raise HTTPException(409, "lecture des commandes refusée")
        return dict(resultat["resultat"])

    def servir(session: Session, titre: str, contenu: str) -> Response:
        html = pages.gabarit(titre, contenu, prefixe=prefixe, session=session, actif="commandes")
        if masquage.contient_secret(html):
            raise HTTPException(500, "rendu refusé : contenu sensible détecté")
        return HTMLResponse(html, headers=ENTETES)

    @router.get(BASE, response_class=HTMLResponse)
    def liste(request: Request) -> Response:
        session = session_page(request)
        exiger_admin(session)
        parametres = request.query_params
        if set(parametres) - _PARAMETRES_LISTE or any(len(parametres.getlist(cle)) != 1 for cle in parametres):
            raise HTTPException(400, "Paramètres invalides")
        statut = parametres.get("statut") or None
        if statut is not None and statut not in LIBELLES_STATUT:
            raise HTTPException(400, "Paramètres invalides")
        if parametres.get("en_retard", "") not in ("", "1"):
            raise HTTPException(400, "Paramètres invalides")
        en_retard = parametres.get("en_retard") == "1"
        debut = _entier_borne(parametres.get("debut"), 100000)
        arguments: dict[str, Any] = {"depart": debut, "limite": _PAGE}
        if statut:
            arguments["statut"] = statut
        if en_retard:
            arguments["en_retard"] = True
        page = appeler_outil(session, "m6_lister_po", arguments)
        exiger_admin(session_page(request))
        return servir(session, "Commandes", rendre_liste(page, prefixe, statut, en_retard, debut))

    @router.get(BASE + "/{po_id}", response_class=HTMLResponse)
    def detail(po_id: str, request: Request) -> Response:
        session = session_page(request)
        exiger_admin(session)
        if request.query_params:
            raise HTTPException(400, "Paramètres invalides")
        po = appeler_outil(session, "m6_lire_po", {"po_id": po_id})
        exiger_admin(session_page(request))
        return servir(session, f"Commande {po['po_id']}", rendre_detail(po, prefixe))

    return router
