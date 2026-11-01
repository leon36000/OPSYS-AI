"""Console « Connecteurs » (administration) : connecter un compte courriel, voir l'état, activer ou désactiver les
exécuteurs du planificateur (TOUS les tours : connecteurs, départements, vérifications, rétention Loi 25), voir ce qui
attend la direction avant tout envoi ou toute publication.

Un exécuteur IRRÉVERSIBLE (purge de rétention) ne passe en « Actif » qu'après l'aperçu à blanc : choisir « Actif »
affiche la
liste de ce qui sera purgé (références, jamais un contenu) ; la confirmation expresse porte l'empreinte de CETTE liste,
et
la décision est refusée si la liste a changé entre-temps (on n'approuve que ce qu'on a vu).

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
from ..connecteurs_planification import inventaire
from ..connecteurs_planification import journal as journal_plan
from ..connecteurs_planification import planificateur as exec_planificateur
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
    "irreversible": "Activation irréversible approuvée : l'aperçu que vous avez vu est consigné avec votre nom.",
}
_FAMILLES = (
    ("connecteurs", "Connecteurs (courriel, WordPress, réseaux sociaux)"),
    ("departements", "Départements (calculs, reconstructions, lectures)"),
    ("verification", "Vérifications"),
    ("retention", "Rétention Loi 25 (suppressions irréversibles)"),
)
_LIBELLE_DECISION = {
    "brancher_quand_transport": "À brancher quand le transport existera",
    "ne_jamais_automatiser": "Ne jamais automatiser",
    "a_construire": "À construire",
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


def _date(epoch: Any) -> str:
    if not epoch:
        return "—"
    import datetime as dt

    return dt.datetime.fromtimestamp(int(epoch), dt.UTC).strftime("%Y-%m-%d %H:%M UTC")


def _etat_affiche(v: Mapping[str, Any]) -> str:
    e = pages.e
    morceaux = [f'<strong>{e(_LIBELLE_MODE[v["mode"]])}</strong>{" (expiré)" if v["expire"] else ""}']
    if v["en_attente_transport"]:
        morceaux.append(f'<br><strong>En attente de transport</strong> : {e(v["transport_libelle"] or "")} '
                        'non raccordé. Rien n\'est tenté ni simulé.')
    if v["dernier_statut"] == "plafond":
        morceaux.append("<br><strong>Plafond d'appels atteint</strong> (24 h glissantes).")
    if v["irreversible"] and v["mode"] == "actif" and v["approbation"] is None:
        morceaux.append("<br><strong>Sans décision humaine valide</strong> : n'efface rien.")
    return "".join(morceaux)


def _formulaire_executeur(v: Mapping[str, Any], prefixe: str, csrf: str) -> str:
    e = pages.e
    options = "".join(f'<option value="{m}"{" selected" if m == v["mode"] else ""}>{e(_LIBELLE_MODE[m])}</option>'
                      for m in exec_etat.MODES)
    ident = re.sub(r"[^a-z0-9]+", "-", v["executeur"])
    note = (f'<small id="irr-{ident}">Irréversible : « Actif » montre d\'abord ce qui sera purgé et demande votre '
            'confirmation.</small>' if v["irreversible"] else "")
    decrit = f' aria-describedby="irr-{ident}"' if v["irreversible"] else ""
    return (
        f'<form method="post" action="{e(prefixe)}/plateforme/connecteurs/executeurs" class="pile">'
        f'<input type="hidden" name="csrf" value="{e(csrf)}">'
        f'<input type="hidden" name="executeur" value="{e(v["executeur"])}">'
        f'<label>Mode<select name="mode"{decrit}>{options}</select></label>'
        f'<label>Intervalle (s)<input name="intervalle_s" inputmode="numeric" pattern="[0-9]*" maxlength="5" '
        f'value="{int(v["intervalle_s"])}"></label>'
        '<label>Motif<input name="motif" required minlength="3" maxlength="500"></label>'
        f'{note}<button>Enregistrer (90 jours)</button></form>')


def contenu_apercu(v: Mapping[str, Any], apercu: Mapping[str, Any], champs: Mapping[str, str], *, prefixe: str,
                   csrf: str) -> str:
    """L'aperçu à blanc d'un exécuteur irréversible et le formulaire de confirmation expresse."""
    e = pages.e
    lignes = "".join(
        f'<tr><td>{e(el.get("categorie", ""))}</td><td><code>{e(el.get("ref", ""))}</code></td>'
        f'<td>{e(", ".join(el.get("comptes", [])) or "—")}</td></tr>' for el in apercu["elements"]
    ) or '<tr><td colspan="3">Rien n\'est échu : une activation ne purgerait rien aujourd\'hui.</td></tr>'
    cache = "".join(f'<input type="hidden" name="{n}" value="{e(champs.get(n, ""))}">'
                    for n in ("executeur", "mode", "motif", "intervalle_s"))
    return (
        pages.navigation_plateforme(prefixe, "connecteurs") +
        f'<section class="pile"><h2>Aperçu à blanc : {e(v["libelle"])}</h2>'
        f'<p><strong>{int(apercu["nombre"])} élément(s)</strong> seraient supprimés ou rendus illisibles à la première '
        'exécution. C\'est <strong>irréversible</strong>. Ce sont des références (identifiants, noms de segment), '
        'jamais un contenu. Ensuite, la purge se répète automatiquement selon la politique déclarée, jusqu\'à '
        'l\'expiration de 90 jours.</p>'
        '<table><caption>Ce qui serait purgé</caption><thead><tr><th scope="col">Catégorie</th>'
        '<th scope="col">Référence</th><th scope="col">Comptes</th></tr></thead>'
        f'<tbody>{lignes}</tbody></table>'
        f'<p>Empreinte de cette liste : <code>{e(apercu["empreinte"][:16])}</code></p>'
        f'<form method="post" action="{e(prefixe)}/plateforme/connecteurs/executeurs" class="pile">'
        f'<input type="hidden" name="csrf" value="{e(csrf)}">{cache}'
        f'<input type="hidden" name="apercu_empreinte" value="{e(apercu["empreinte"])}">'
        '<label><input type="checkbox" name="confirme_irreversible" value="oui" required> J\'ai lu cette liste et '
        'j\'autorise cette suppression irréversible, puis son renouvellement automatique selon la politique.</label>'
        '<button>Confirmer l\'activation irréversible</button></form>'
        f'<p><a href="{e(prefixe)}/plateforme/connecteurs">Annuler</a></p></section>')


def _section_executeurs(executeurs: list[dict[str, Any]], *, prefixe: str, csrf: str) -> str:
    e = pages.e
    sortie = ""
    for famille, titre in _FAMILLES:
        choisis = [v for v in executeurs if v["famille"] == famille]
        if not choisis:
            continue
        lignes = "".join(
            f'<tr><td><strong>{e(v["libelle"])}</strong><br><code>{e(v["executeur"])}</code><br>'
            f'<small>{e(v["description"])}</small></td><td>{e(v["niveau"])}</td>'
            f'<td>{_etat_affiche(v)}</td><td>{e(_date(v["expire_le"]))}</td>'
            f'<td>{e(_date(v["dernier_passage"]))}<br>{e(v["dernier_statut"] or "jamais")} '
            f'<code>{e(v["dernier_code"] or "")}</code><br>Échecs (24 h) : {int(v["echecs_24h"])}</td>'
            f'<td>{e(_date(v["prochain_passage"]))}</td><td>{_formulaire_executeur(v, prefixe, csrf)}</td></tr>'
            for v in choisis)
        sortie += (
            f'<h3>{e(titre)}</h3><table><caption class="cache">{e(titre)}</caption><thead><tr>'
            '<th scope="col">Tour</th><th scope="col">Niveau</th><th scope="col">État</th>'
            '<th scope="col">Expire</th><th scope="col">Dernier passage</th><th scope="col">Prochain</th>'
            f'<th scope="col">Réglage</th></tr></thead><tbody>{lignes}</tbody></table>')
    return sortie


def _section_tours_non_branches() -> str:
    e = pages.e
    lignes = "".join(
        f'<tr><td><strong>{e(t.libelle)}</strong><br><code>{e(t.identifiant)}</code></td><td>{e(t.niveau)}</td>'
        f'<td>{e(_LIBELLE_DECISION[t.decision])}</td><td>{e(t.justification)}</td></tr>'
        for t in inventaire.TOURS if t.decision in _LIBELLE_DECISION)
    return (
        '<section class="pile"><h2>Tours non branchés</h2><p class="note">Livrés mais volontairement absents du '
        'planificateur : la raison est dite, rien n\'est simulé. Un geste humain reste un geste humain.</p>'
        '<table><caption class="cache">Tours non branchés</caption><thead><tr><th scope="col">Tour</th>'
        '<th scope="col">Niveau</th><th scope="col">Décision</th><th scope="col">Pourquoi</th></tr></thead>'
        f'<tbody>{lignes}</tbody></table></section>')


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
    lignes_att = "".join(
        f'<tr><td><code>{e(d["id"])}</code></td><td>{e(d["outil"])}</td><td>{e(d["departement"])}</td>'
        f'<td>{e(d["niveau"])}</td><td>{e(str(d["cree_le"])[:19])}</td></tr>' for d in en_attente
    ) or '<tr><td colspan="5">Rien n\'attend la direction.</td></tr>'
    lignes_journal = "".join(
        f'<tr><td>{e(j["quand"][:19])}</td><td><code>{e(j["executeur"])}</code></td><td>{e(j["evenement"])}</td>'
        f'<td>{e(j["mode"] or "")} {e(j["statut"] or "")}</td><td><code>{e(j["code"] or "")}</code></td>'
        f'<td>{e(j["acteur"])}</td></tr>' for j in journal)
    return (
        pages.navigation_plateforme(prefixe, "connecteurs") +
        '<p class="note">Rien ne tourne tant qu\'un admin n\'a pas activé un exécuteur ici. Aucun envoi ni aucune '
        'publication ne part sans l\'approbation de la direction (N3) : le planificateur ne fait que transmettre '
        'ce qui a été approuvé, une seule fois. Tout est qualifié sur des doubles seulement.</p>'
        f'<section class="pile"><h2>Comptes courriel</h2><table><thead><tr><th>Compte</th><th>Fournisseur</th>'
        '<th>Adresse</th><th>État</th><th>Usage</th><th>Dernier passage</th><th>Brouillons</th><th>Actions</th>'
        f'</tr></thead><tbody>{ligne_comptes or "<tr><td colspan=8>Aucun compte.</td></tr>"}</tbody></table></section>'
        f"{creer}"
        '<section class="pile"><h2>Tours du planificateur</h2><p class="note">Inactif par défaut. « Ombre » '
        'constate sans rien appeler ni écrire ; « Actif » exécute. Chaque activation expire après 90 jours. Un tour '
        'dont le transport n\'est pas raccordé le dit : « En attente de transport ». Aucun tour de niveau N3 ou plus '
        'n\'agit sans l\'approbation humaine consommée.</p>'
        f'{_section_executeurs(executeurs, prefixe=prefixe, csrf=csrf)}'
        '</section>'
        f'{_section_tours_non_branches()}'
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

    def ports_hote() -> Any:
        """Les ports de l'hôte : seulement pour dire quel transport est (ou n'est pas) raccordé."""
        from ..connecteurs_planification import hote

        return hote.ports_par_defaut()

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
            return {"comptes": comptes.lister(cnx), "executeurs": exec_etat.vue(cnx, ports=ports_hote()),
                    "en_attente": attente,
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
        d["tours"] = [{**t.__dict__, "n3_ou_plus": t.n3_ou_plus} for t in inventaire.TOURS]
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
        nom, mode = champs.get("executeur"), champs.get("mode")
        definition = exec_etat.definition(nom) if isinstance(nom, str) else None
        irreversible_actif = bool(definition and definition.irreversible and mode == "actif")
        apercu: Mapping[str, Any] | None = None
        if irreversible_actif:
            try:
                apercu = exec_planificateur.apercu(nom, ports=ports_hote())  # type: ignore[arg-type]
            except exec_etat.RefusOperateur as exc:  # pragma: no cover — apercu ne lève pas ce type
                return echec(exc)
            except Exception as exc:  # noqa: BLE001 — la cause (dossier, clé) ne fuit pas : code fixe
                return retour(erreur=getattr(exc, "code", "APERCU_INDISPONIBLE"))
            if not champs.get("apercu_empreinte"):
                # Première étape : on MONTRE ce qui serait purgé ; rien n'est enregistré.
                vue = next(v for v in donnees()["executeurs"] if v["executeur"] == nom)
                corps = contenu_apercu(vue, apercu, champs, prefixe=prefixe, csrf=session.csrf)
                return servir(pages.gabarit("Plateforme — aperçu à blanc", corps, prefixe=prefixe, session=session,
                                            actif=ONGLET))
        try:
            with cnx_factory() as cnx:
                exec_etat.appliquer(
                    cnx, session, nom, mode, motif=champs.get("motif"),
                    intervalle_s=int(intervalle) if intervalle else None,
                    apercu_empreinte=champs.get("apercu_empreinte"),
                    apercu_courant=(lambda: (apercu["empreinte"], apercu["nombre"])) if apercu else None,
                    confirme_irreversible=champs.get("confirme_irreversible") == "oui")
        except exec_etat.RefusOperateur as exc:
            return echec(exc)
        return retour(ok="irreversible" if irreversible_actif else "mode")

    return router


__all__ = ["CHEMIN_RETOUR", "OUTILS_EN_ATTENTE", "creer_router"]
