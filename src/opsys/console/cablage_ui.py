"""Console « Connecteurs » (administration) : connecter un compte courriel, voir l'état, activer ou désactiver les
exécuteurs du planificateur, voir ce qui attend la direction avant tout envoi ou toute publication.

Mêmes protections que les pages Plateforme :
- session obligatoire et rôle `nathan_owner`/`admin` RELU EN BASE avant ET après chaque lecture ; avant chaque
  écriture ;
- CSRF sur chaque écriture (champ `csrf`) ; corps borné ; `Cache-Control: no-store` sur chaque réponse ;
- un mot de passe d'application IMAP est saisi UNE fois (champ mot de passe), jamais réaffiché ; le coffre le chiffre ;
- avant d'être servie, chaque page est contrôlée : un jeton opaque ou une valeur active détectée = 500 ;
- la redirection après écriture ne porte qu'un code fixe (`ok=` ou `erreur=REJ-…`), JAMAIS un jeton ni un contenu.

Retour OAuth (`GET /courriel/oauth/retour?state=…&code=…`) : le `state` est signé, lié au compte et à USAGE UNIQUE (le
nonce est consommé même si l'échange échoue) ; la session admin qui revient doit être celle qui a démarré
l'autorisation ; le code n'est jamais journalisé ni redirigé (la réponse est une redirection 303 vers une adresse sans
paramètre sensible, `Referrer-Policy: no-referrer`) ; les journaux d'accès d'Uvicorn masquent la requête
(`journaux_http`). Aucun jeton d'accès n'apparaît dans une URL : il va du fournisseur au serveur, puis au coffre.

Le départ vers le fournisseur n'est PAS une redirection de formulaire (la CSP `form-action 'self'` la bloquerait) : la
page rend un lien à suivre.

Routes : /plateforme/connecteurs (page), /api/plateforme/connecteurs (JSON), POST
/plateforme/connecteurs/{comptes/creer,
comptes/connecter, comptes/imap, comptes/mbox, comptes/revoquer, executeurs}, GET /courriel/oauth/retour.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import func, select

from .. import approbations
from ..connecteurs_planification import etat as exec_etat
from ..connecteurs_planification import journal as journal_plan
from ..courriel_connecteurs import comptes
from ..courriel_connecteurs.erreurs import ErreurCourriel
from ..secrets_coffre import masquage
from ..stockage.schema import COURRIEL_BROUILLONS
from . import pages
from .securite import Session

ENTETES = {"Cache-Control": "no-store", "Pragma": "no-cache"}
ONGLET = "plateforme/fournisseurs"
CHEMIN_RETOUR = "/courriel/oauth/retour"
_CODE = re.compile(r"^REJ-[A-Z]+-[A-Z0-9-]{2,60}$|^[A-Z][A-Z0-9_]{2,47}$")
_COMPTE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_SUCCES = {
    "cree": "Compte créé et consentement consigné (Loi 25). Il reste à le connecter.",
    "connecte": "Compte connecté : les jetons sont dans le coffre, jamais ici.",
    "revoque": "Compte révoqué : le secret est détruit.", "mode": "Mode de l'exécuteur enregistré.",
}
# Ce que la direction doit décider avant qu'un envoi ou une publication ne parte (file d'approbation du socle).
OUTILS_EN_ATTENTE = frozenset({
    "opsys_courriel_approuver_envoi", "m7_demander_publication_wordpress", "m7_demander_publication_sociale",
    "m7_demander_annonce_payante",
})
_LIBELLE_MODE = {"inactif": "Inactif", "ombre": "Ombre (constate seulement)", "actif": "Actif"}


def _bandeau(params: Mapping[str, str]) -> pages.Bandeau | None:
    if params.get("ok") in _SUCCES:
        return (_SUCCES[params["ok"]], "ok")
    erreur = params.get("erreur", "")
    if _CODE.fullmatch(erreur):
        return (f"Action refusée ({erreur}). Rien d'autre n'a été fait à la place.", "erreur")
    return None


def _formulaire_executeur(v: Mapping[str, Any], prefixe: str, csrf: str) -> str:
    e = pages.e
    options = "".join(f'<option value="{m}"{" selected" if m == v["mode"] else ""}>{e(_LIBELLE_MODE[m])}</option>'
                      for m in exec_etat.MODES)
    return (
        f'<form method="post" action="{e(prefixe)}/plateforme/connecteurs/executeurs" class="pile">'
        f'<input type="hidden" name="csrf" value="{e(csrf)}">'
        f'<input type="hidden" name="executeur" value="{e(v["executeur"])}">'
        f'<label>Mode<select name="mode">{options}</select></label>'
        f'<label>Intervalle (s)<input name="intervalle_s" inputmode="numeric" pattern="[0-9]*" maxlength="5" '
        f'value="{int(v["intervalle_s"])}"></label>'
        '<label>Motif<input name="motif" required minlength="3" maxlength="500"></label>'
        '<button>Enregistrer (90 jours)</button></form>')


def contenu_page(comptes_liste: list[dict[str, Any]], executeurs: list[dict[str, Any]],
                 en_attente: list[dict[str, Any]], brouillons: Mapping[str, Mapping[str, int]],
                 journal: list[dict[str, Any]], oauth: list[str], *, prefixe: str, csrf: str) -> str:
    e = pages.e
    base = f"{e(prefixe)}/plateforme/connecteurs"
    ligne_comptes = ""
    for c in comptes_liste:
        actions = ""
        if c["etat"] in ("non_connecte", "reconnexion_requise", "erreur", "autorisation_en_cours"):
            if c["fournisseur"] in oauth:
                actions += (f'<form method="post" action="{base}/comptes/connecter">'
                            f'<input type="hidden" name="csrf" value="{e(csrf)}">'
                            f'<input type="hidden" name="compte_id" value="{e(c["compte_id"])}">'
                            '<button>Connecter chez le fournisseur</button></form>')
            elif c["fournisseur"] == "imap":
                actions += (f'<form method="post" action="{base}/comptes/imap" class="pile">'
                            f'<input type="hidden" name="csrf" value="{e(csrf)}">'
                            f'<input type="hidden" name="compte_id" value="{e(c["compte_id"])}">'
                            '<label>Mot de passe d\'application (saisi une fois)<input type="password" '
                            'name="mot_de_passe" required autocomplete="new-password" spellcheck="false" '
                            'maxlength="512"></label><button>Enregistrer et connecter</button></form>')
            elif c["fournisseur"] == "mbox":
                actions += (f'<form method="post" action="{base}/comptes/mbox">'
                            f'<input type="hidden" name="csrf" value="{e(csrf)}">'
                            f'<input type="hidden" name="compte_id" value="{e(c["compte_id"])}">'
                            '<button>Connecter l\'export</button></form>')
            else:
                actions += "<em>Fournisseur OAuth non configuré sur le serveur.</em>"
        if c["etat"] != "revoque":
            actions += (f'<form method="post" action="{base}/comptes/revoquer">'
                        f'<input type="hidden" name="csrf" value="{e(csrf)}">'
                        f'<input type="hidden" name="compte_id" value="{e(c["compte_id"])}">'
                        '<label><input type="checkbox" name="confirme" value="oui" required> Révoquer</label>'
                        '<button>Révoquer</button></form>')
        att = brouillons.get(c["compte_id"], {})
        ligne_comptes += (
            f'<tr><td><a href="{e(prefixe)}/courriel/comptes/{e(c["compte_id"])}">{e(c["compte_id"])}</a></td>'
            f'<td>{e(c["fournisseur"])}</td><td>{e(c["adresse"])}</td><td>{e(c["etat"])}</td>'
            f'<td>{e(c["usage"])}</td><td>{e((c["derniere_synchro_le"] or "jamais")[:19])} '
            f'{e(c["derniere_synchro_statut"] or "")}<br><code>{e(c["derniere_erreur_code"] or "")}</code></td>'
            f'<td>{e(", ".join(f"{k} {v}" for k, v in sorted(att.items())) or "—")}</td><td>{actions}</td></tr>')
    options_f = "".join(f'<option value="{f}">{f}</option>' for f in comptes.FOURNISSEURS)
    creer = (
        f'<section class="carte pile"><h2>Nouveau compte</h2><form method="post" action="{base}/comptes/creer" '
        f'class="pile"><input type="hidden" name="csrf" value="{e(csrf)}">'
        '<label>Identifiant<input name="compte_id" required maxlength="64" pattern="[a-z0-9][a-z0-9_-]{0,63}"></label>'
        f'<label>Fournisseur<select name="fournisseur">{options_f}</select></label>'
        '<label>Adresse<input name="adresse" type="email" required maxlength="254"></label>'
        '<label>Usage<select name="usage"><option value="lecture">Lecture seule</option>'
        '<option value="lecture_envoi">Lecture et envoi (sous approbation N3)</option></select></label>'
        '<label>Finalité (Loi 25)<input name="finalite" required maxlength="500"></label>'
        '<label>Rétention déclarée (jours)<input name="retention_jours" required inputmode="numeric" '
        'pattern="[0-9]*" maxlength="4" value="365"></label>'
        '<label><input type="checkbox" name="reception_m1" value="1"> Les nouveaux courriels de la boîte deviennent '
        'des réceptions de M1 (après l\'amorçage)</label>'
        '<label><input type="checkbox" name="contacts_courriel" value="1"> L\'historique propose des contacts au CRM '
        '(brouillons à confirmer)</label>'
        '<label><input type="checkbox" name="consentement" value="oui" required> Le titulaire de la boîte a consenti '
        'à cette finalité</label><button>Créer</button></form></section>')
    lignes_exec = "".join(
        f'<tr><td><strong>{e(v["libelle"])}</strong><br><code>{e(v["executeur"])}</code><br>'
        f'<small>{e(v["description"])}</small></td><td>{e(v["niveau"])}</td>'
        f'<td>{e(_LIBELLE_MODE[v["mode"]])}{" (expiré)" if v["expire"] else ""}</td>'
        f'<td>{e(v["expire_le"] or "—")}</td><td>{e(v["dernier_statut"] or "jamais")} '
        f'<code>{e(v["dernier_code"] or "")}</code></td><td>{_formulaire_executeur(v, prefixe, csrf)}</td></tr>'
        for v in executeurs)
    lignes_att = "".join(
        f'<tr><td><code>{e(d["id"])}</code></td><td>{e(d["outil"])}</td><td>{e(d["departement"])}</td>'
        f'<td>{e(d["niveau"])}</td><td>{e(str(d["cree_le"])[:19])}</td></tr>' for d in en_attente
    ) or '<tr><td colspan="5">Rien n\'attend la direction.</td></tr>'
    lignes_journal = "".join(
        f'<tr><td>{e(j["quand"][:19])}</td><td><code>{e(j["executeur"])}</code></td><td>{e(j["evenement"])}</td>'
        f'<td>{e(j["mode"] or "")} {e(j["statut"] or "")}</td><td><code>{e(j["code"] or "")}</code></td>'
        f'<td>{e(j["acteur"])}</td></tr>' for j in journal)
    return (
        f'<p><a href="{e(prefixe)}/plateforme/fournisseurs">Fournisseurs</a> · '
        f'<a href="{e(prefixe)}/plateforme/secrets">Secrets</a> · <a href="{base}">Connecteurs</a></p>'
        '<p class="note">Rien ne tourne tant qu\'un admin n\'a pas activé un exécuteur ici. Aucun envoi ni aucune '
        'publication ne part sans l\'approbation de la direction (N3) : le planificateur ne fait que transmettre '
        'ce qui a été approuvé, une seule fois. Tout est qualifié sur des doubles seulement.</p>'
        f'<section class="pile"><h2>Comptes courriel</h2><table><thead><tr><th>Compte</th><th>Fournisseur</th>'
        '<th>Adresse</th><th>État</th><th>Usage</th><th>Dernier passage</th><th>Brouillons</th><th>Actions</th>'
        f'</tr></thead><tbody>{ligne_comptes or "<tr><td colspan=8>Aucun compte.</td></tr>"}</tbody></table></section>'
        f"{creer}"
        '<section class="pile"><h2>Exécuteurs du planificateur</h2><p class="note">Inactif par défaut. « Ombre » '
        'constate sans rien appeler ; « Actif » exécute. Chaque activation expire après 90 jours.</p>'
        '<table><thead><tr><th>Exécuteur</th><th>Niveau</th><th>Mode</th><th>Expire</th><th>Dernier passage</th>'
        f'<th>Réglage</th></tr></thead><tbody>{lignes_exec}</tbody></table></section>'
        f'<section class="pile"><h2>En attente de la direction</h2><p>Les décisions se prennent dans '
        f'<a href="{e(prefixe)}/approbations">Approbations</a> ; chaque envoi ou publication y est approuvé pour une '
        'empreinte précise.</p><table><thead><tr><th>Demande</th><th>Outil</th><th>Département</th><th>Niveau</th>'
        f'<th>Déposée</th></tr></thead><tbody>{lignes_att}</tbody></table></section>'
        '<section class="pile"><h2>Journal du planificateur (50 derniers)</h2><table><thead><tr><th>Quand</th>'
        f'<th>Exécuteur</th><th>Événement</th><th>Mode</th><th>Code</th><th>Acteur</th></tr></thead>'
        f'<tbody>{lignes_journal}</tbody></table></section>')


def creer_router(
    *, session_page: Callable[..., Session], session_api: Callable[..., Session],
    verifier_formulaire: Callable[[Mapping[str, str], Session], None],
    formulaire: Callable[[Request], Awaitable[dict[str, str]]], cnx_factory: Callable[[], Any], prefixe: str,
    construire_service: Callable[[], Any] | None = None,
) -> APIRouter:
    router = APIRouter(tags=["connecteurs"])
    masquage.installer()
    if construire_service is None:
        from ..connecteurs_planification import hote

        def construire_service() -> Any:  # résolu à chaque requête : l'environnement du serveur fait foi
            return hote.construire_service()

    def servir(html: str, code: int = 200) -> HTMLResponse:
        if masquage.contient_secret(html):
            raise HTTPException(500, "rendu refusé : contenu sensible détecté")
        return HTMLResponse(html, status_code=code, headers=ENTETES)

    def retour(**params: str) -> RedirectResponse:
        requete = "&".join(f"{k}={quote(v, safe=',-')}" for k, v in params.items() if v)
        return RedirectResponse(f"{prefixe}/plateforme/connecteurs" + (f"?{requete}" if requete else ""),
                                status_code=303, headers=ENTETES)

    def echec(exc: Exception) -> RedirectResponse:
        code = getattr(exc, "code", "")
        return retour(erreur=code if isinstance(code, str) and _CODE.fullmatch(code) else "REFUSE")

    async def ecriture(request: Request) -> tuple[Session, dict[str, str]]:
        session = session_page(request)
        champs = await formulaire(request)
        verifier_formulaire(champs, session)
        session_page(request)  # rôle relu à nouveau juste avant l'écriture
        return session, champs

    def compte_id(champs: Mapping[str, str]) -> str:
        valeur = champs.get("compte_id", "")
        if not _COMPTE.fullmatch(valeur):
            raise HTTPException(422, "identifiant de compte invalide")
        return valeur

    def donnees() -> dict[str, Any]:
        with cnx_factory() as cnx:
            brouillons: dict[str, dict[str, int]] = {}
            for compte, statut, n in cnx.execute(select(
                    COURRIEL_BROUILLONS.c.compte_id, COURRIEL_BROUILLONS.c.statut, func.count()).where(
                    COURRIEL_BROUILLONS.c.statut.in_(("DEMANDE", "APPROUVE", "ENVOI_RESERVE", "INCERTAIN"))
            ).group_by(COURRIEL_BROUILLONS.c.compte_id, COURRIEL_BROUILLONS.c.statut)):
                brouillons.setdefault(compte, {})[statut] = n
            attente = [
                {k: d[k] for k in ("id", "outil", "departement", "niveau", "cree_le")}
                for d in approbations.lister(cnx, "en_attente", 200) if d["outil"] in OUTILS_EN_ATTENTE]
            return {"comptes": comptes.lister(cnx), "executeurs": exec_etat.vue(cnx), "en_attente": attente,
                    "brouillons": brouillons, "journal": journal_plan.lire(cnx, None, 50)}

    def oauth_configures() -> list[str]:
        try:
            return sorted(construire_service()._oauth)  # noqa: SLF001 — lecture de la liste des fournisseurs
        except Exception:  # noqa: BLE001 — la page se rend même si l'environnement est incomplet
            return []

    # -- lecture ---------------------------------------------------------------------------------
    @router.get("/plateforme/connecteurs", response_class=HTMLResponse)
    def page(request: Request) -> Response:
        session = session_page(request)
        d = donnees()
        corps = contenu_page(d["comptes"], d["executeurs"], d["en_attente"], d["brouillons"], d["journal"],
                             oauth_configures(), prefixe=prefixe, csrf=session.csrf)
        session_page(request)
        return servir(pages.gabarit("Plateforme — connecteurs", corps, prefixe=prefixe, session=session,
                                    actif=ONGLET, bandeau=_bandeau(request.query_params)))

    @router.get("/api/plateforme/connecteurs")
    def api(request: Request) -> JSONResponse:
        session_api(request)
        d = donnees()
        d["comptes"] = [{k: v for k, v in c.items() if k != "secret_nom"} for c in d["comptes"]]
        return JSONResponse(masquage.masquer({"ok": True, **d, "oauth": oauth_configures()}), headers=ENTETES)

    # -- écritures -------------------------------------------------------------------------------
    @router.post("/plateforme/connecteurs/comptes/creer")
    async def creer(request: Request) -> Response:
        session, champs = await ecriture(request)
        try:
            retention = int(champs.get("retention_jours", ""))
        except ValueError:
            return retour(erreur="REJ-COURRIEL-ARGUMENT-INVALIDE")
        options = {o: 1 for o in comptes.OPTIONS_BINAIRES if champs.get(o) == "1"}
        try:
            with cnx_factory() as cnx:
                comptes.creer_compte(
                    cnx, session.utilisateur, compte_id=compte_id(champs), fournisseur=champs.get("fournisseur", ""),
                    adresse=champs.get("adresse", ""), usage=champs.get("usage", ""),
                    finalite=champs.get("finalite", ""), retention_jours=retention, configuration=options)
                if champs.get("consentement") == "oui":
                    comptes.enregistrer_consentement(cnx, session.utilisateur, compte_id(champs))
        except ErreurCourriel as exc:
            return echec(exc)
        return retour(ok="cree")

    @router.post("/plateforme/connecteurs/comptes/connecter")
    async def connecter(request: Request) -> Response:
        session, champs = await ecriture(request)
        try:
            url = construire_service().demarrer_autorisation(session.utilisateur, compte_id(champs))
        except ErreurCourriel as exc:
            return echec(exc)
        lien = (f'<p>Autorisation prête. <a href="{pages.e(url.url)}" rel="noopener noreferrer">Continuer chez le '
                "fournisseur</a> (valable 10 minutes, usage unique).</p>"
                f'<p><a href="{pages.e(prefixe)}/plateforme/connecteurs">Retour</a></p>')
        return servir(pages.gabarit("Connecter un compte", lien, prefixe=prefixe, session=session, actif=ONGLET))

    @router.get(CHEMIN_RETOUR)
    def retour_oauth(request: Request) -> Response:
        session = session_page(request)
        etat_, code = request.query_params.get("state", ""), request.query_params.get("code", "")
        if request.query_params.get("error") or not etat_ or not code:
            return retour(erreur="REJ-COURRIEL-OAUTH-ECHANGE-REFUSE")
        try:
            service = construire_service()
            fournisseur = service._fournisseur_du_state(etat_)  # noqa: SLF001
            donnees_state = service._oauth_de(fournisseur)._ouvrir_state(etat_)  # noqa: SLF001
            with cnx_factory() as cnx:
                demarre_par = next((j["acteur"] for j in comptes.journal(cnx, donnees_state["c"], 50)
                                    if j["evenement"] == "oauth.demarre"), None)
            if demarre_par != session.utilisateur:
                raise ErreurCourriel("REJ-COURRIEL-OAUTH-ETAT-INVALIDE",
                                     "l'autorisation a été démarrée par une autre session", 403)
            service.terminer_autorisation(session.utilisateur, etat_, code)
        except ErreurCourriel as exc:
            return echec(exc)
        return retour(ok="connecte")

    @router.post("/plateforme/connecteurs/comptes/imap")
    async def imap(request: Request) -> Response:
        session, champs = await ecriture(request)
        secret = champs.pop("mot_de_passe", "")
        try:
            construire_service().enregistrer_mot_de_passe_imap(session.utilisateur, compte_id(champs), secret)
        except ErreurCourriel as exc:
            return echec(exc)
        finally:
            secret = ""
        return retour(ok="connecte")

    @router.post("/plateforme/connecteurs/comptes/mbox")
    async def mbox(request: Request) -> Response:
        session, champs = await ecriture(request)
        try:
            construire_service().connecter_export_mbox(session.utilisateur, compte_id(champs))
        except ErreurCourriel as exc:
            return echec(exc)
        return retour(ok="connecte")

    @router.post("/plateforme/connecteurs/comptes/revoquer")
    async def revoquer(request: Request) -> Response:
        session, champs = await ecriture(request)
        if champs.get("confirme") != "oui":
            return retour(erreur="CONFIRMATION_REQUISE")
        try:
            construire_service().revoquer(session.utilisateur, compte_id(champs))
        except ErreurCourriel as exc:
            return echec(exc)
        return retour(ok="revoque")

    @router.post("/plateforme/connecteurs/executeurs")
    async def executeurs(request: Request) -> Response:
        session, champs = await ecriture(request)
        intervalle = champs.get("intervalle_s", "").strip()
        if intervalle and not intervalle.isdigit():
            return retour(erreur="INTERVALLE_INVALIDE")
        try:
            with cnx_factory() as cnx:
                exec_etat.appliquer(cnx, session, champs.get("executeur"), champs.get("mode"),
                                    motif=champs.get("motif"), intervalle_s=int(intervalle) if intervalle else None)
        except exec_etat.RefusOperateur as exc:
            return echec(exc)
        return retour(ok="mode")

    return router


__all__ = ["CHEMIN_RETOUR", "OUTILS_EN_ATTENTE", "creer_router"]
