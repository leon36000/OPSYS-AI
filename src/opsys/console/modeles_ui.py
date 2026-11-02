"""Console « Modèles et rôles » : rôles de modèles, passerelle LiteLLM, catalogue, coûts, licences, plafonds, replis.

Mêmes protections que « Plateforme » (session, rôle `nathan_owner`/`admin` relu en base à chaque requête, CSRF,
`no-store`,
CSP stricte) :
- AUCUNE valeur de secret n'est lue, rendue ni acceptée : seules les NOMS de secrets du coffre se choisissent ;
chaque page
  est contrôlée avant d'être servie (valeur active ou forme de clé détectée = 500) ;
- toute écriture passe par `roles_modeles.service.appliquer` (une seule porte), avec le niveau d'approbation de
l'opération :
  changer le fournisseur d'un rôle, ses replis, la passerelle, activer le raisonnement ou revenir en arrière =
  **N3**, case
  de confirmation explicite obligatoire (sans elle : refus `REJ-MODELES-CONFIRMATION-N3-REQUISE`) ; plafonds = N2 ;
- le test de connexion est un appel minuscule (≤ 8 jetons de sortie), jamais un repli, et son résultat est conservé.

Routes : /plateforme/modeles (page), /api/plateforme/modeles (lecture JSON) ; écritures POST sous /plateforme/modeles/….
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from ..fournisseurs import registre
from ..roles_modeles import appel, decouverte, service
from ..roles_modeles import roles as lex
from ..roles_modeles.codes import ModelesErreur
from ..secrets_coffre import coffre, masquage
from . import pages
from .securite import Session

ENTETES = {"Cache-Control": "no-store", "Pragma": "no-cache"}
ONGLET = "plateforme/fournisseurs"
# Transport HTTP du test de connexion : None = réel ; les tests y mettent un double.
OUVRIR_HTTP = None
_CODE = re.compile(r"^[A-Z][A-Z0-9_-]{2,60}$")
_SUCCES = {
    "passerelle": "Passerelle enregistrée.",
    "passerelle_retiree": "Passerelle déconnectée.",
    "catalogue": "Connexion testée : catalogue de la passerelle découvert.",
    "role_connecte": "Modèle connecté et affecté au rôle.",
    "role_affecte": "Rôle affecté.",
    "role_retire": "Affectation retirée : le rôle est inerte.",
    "plafonds": "Plafonds enregistrés.",
    "teste": "Test de connexion terminé : voir le résultat dans la ligne du rôle.",
    "raisonnement_active": "Raisonnement activé (geste N3 journalisé).",
    "raisonnement_desactive": "Raisonnement désactivé.",
    "revenu": "Retour arrière effectué.",
}


def _badge(texte: str, classe: str = "") -> str:
    return f'<span class="badge {pages.e(classe)}">{pages.e(texte)}</span>'


def _bandeau(params: Mapping[str, str]) -> pages.Bandeau | None:
    if params.get("ok") in _SUCCES:
        return (_SUCCES[params["ok"]], "ok")
    erreur = params.get("erreur", "")
    if _CODE.fullmatch(erreur):
        refus = [c for c in params.get("refus", "").split(",") if _CODE.fullmatch(c)]
        suite = f" — refus : {', '.join(refus)}" if refus else ""
        return (f"Action refusée ({erreur}){suite}. Rien n'a été modifié.", "erreur")
    return None


def _cle_ou_tiret(valeur: Any) -> str:
    return "—" if valeur in (None, "") else str(valeur)


def _cellule_fournisseur(r: Mapping[str, Any]) -> str:
    e = pages.e
    f = r["fournisseur"]
    if f is None:
        return "<em>Fournisseur introuvable dans le registre.</em>"
    lic = f["licence"]
    conforme = (
        _badge("Conforme", "badge-ok")
        if f["conforme"]
        else _badge("Refusé", "badge-danger") + " " + ", ".join(f"<code>{e(c)}</code>" for c in f["refus"])
    )
    return (
        f"<code>{e(f['identifiant'])}</code> — {e(r['modele_appel'])}<br>"
        f"{_badge('Local' if f['mode'] == 'local' else 'API', '')} {conforme}<br>"
        f"Licence : {e(_cle_ou_tiret(lic['code']))} / poids {e(_cle_ou_tiret(lic['poids']))} ; usage commercial "
        f"{e(lic['usage_commercial'])} ; service à des tiers {e(lic['service_tiers'])} ; "
        f"{'à lire' if lic['verification'] == 'a_lire' else 'vérifiée'}<br>"
        f"Résidence des données : {e(f['residence_donnees'])} ; EFVP : {e(_cle_ou_tiret(f['efvp_ref']))} ; contrat : "
        f"{e(_cle_ou_tiret(f['contrat_ref']))}"
    )


def _cellule_plafonds(r: Mapping[str, Any]) -> str:
    e = pages.e
    p, u, c = r["plafonds"], r["usage_jour"], r["cout"]
    jetons = f"{u['jetons_entree'] + u['jetons_sortie']} jetons aujourd'hui"
    plafond = "aucun plafond de jetons" if p["jetons_jour"] is None else f"plafond {p['jetons_jour']} jetons/jour"
    budget = "aucun budget" if p["budget_usd_mois"] is None else f"budget {p['budget_usd_mois']} USD/mois"
    if c["entree_par_million"] is None or c["sortie_par_million"] is None:
        cout = "coût non déclaré (la passerelle rapporte 0 ou rien : ce n'est pas « gratuit »)"
    else:
        cout = f"{c['entree_par_million']} / {c['sortie_par_million']} USD par million de jetons (entrée / sortie)"
    atteint = " " + _badge("Plafond atteint", "badge-danger") if r["plafond_atteint"] else ""
    return (
        f"{e(jetons)}, {e(plafond)}{atteint}<br>{e(budget)} ; {e(u['appels_repli'])} appel(s) de repli aujourd'hui<br>"
        f"{e(cout)}<br>Source du coût : {e(_cle_ou_tiret(c['source']))}"
    )


def _cellule_mesure(r: Mapping[str, Any]) -> str:
    e = pages.e
    m = r["mesure"]
    etat = _badge("Mesuré", "badge-ok") if m["mesure"] else _badge("Non mesuré", "badge-alerte")
    test = m["dernier_test"]
    texte = (
        "<br>Aucun test de connexion."
        if not test
        else f"<br>Dernier test : {e(test['statut'])} — {e(test.get('detail', ''))} ({e(test.get('date', ''))})"
        + (f" ; dimension {e(test['dimension'])}" if test.get("dimension") else "")
    )
    return etat + texte


def _options_fournisseurs(fournisseurs: list[dict[str, Any]], capacite: str) -> str:
    return "".join(
        f'<option value="{pages.e(f["identifiant"])}">{pages.e(f["identifiant"])} ({pages.e(f["mode"])})</option>'
        for f in fournisseurs
        if f["capacite"] == capacite and f["actif"] and f["politique"]["conforme"]
    )


def _formulaires_role(
    r: Mapping[str, Any], fournisseurs: list[dict[str, Any]], alias: list[str], prefixe: str, csrf: str
) -> str:
    e = pages.e
    base = f"{e(prefixe)}/plateforme/modeles"
    caches = (
        f'<input type="hidden" name="csrf" value="{e(csrf)}"><input type="hidden" name="role" value="{e(r["role"])}">'
    )
    n3 = (
        '<label><input type="checkbox" name="confirme_n3" value="oui"> Je confirme ce geste (niveau N3, journalisé)'
        "</label>"
    )
    reco = r["recommandation"]
    aide_reco = (
        (
            f'<p class="note">Suggestion de départ ({e(reco["statut"].replace("_", " "))}) : '
            f"{e(reco['modele_amont'])} — {e(reco['raison'])}.</p>"
        )
        if reco
        else ""
    )
    options_alias = "".join(f'<option value="{e(a)}">' for a in alias)
    connecter = (
        f"<details><summary>Connecter un modèle de la passerelle</summary>{aide_reco}"
        f'<form method="post" action="{base}/role/connecter" class="pile">{caches}'
        f'<label>Alias de la passerelle<input name="alias" list="alias-{e(r["role"])}" maxlength="80" required>'
        f'<datalist id="alias-{e(r["role"])}">{options_alias}</datalist></label>'
        "<label>Modèle d’amont (fournisseur/modèle, pour la configuration générée ; vide = passerelle existante)"
        '<input name="amont" maxlength="200" placeholder="openrouter/anthropic/claude-haiku-5.5"></label>'
        '<label>Référence EFVP (Loi 25)<input name="efvp_ref" maxlength="200" required></label>'
        '<label>Référence du contrat ou des conditions<input name="contrat_ref" maxlength="200" required></label>'
        f"{n3}<button>Connecter et affecter</button></form></details>"
    )
    options_f = _options_fournisseurs(fournisseurs, r["capacite"])
    affecter = (
        f"<details><summary>Affecter un fournisseur du registre (local, API directe)</summary>"
        f'<form method="post" action="{base}/role/affecter" class="pile">{caches}'
        f'<label>Fournisseur actif et conforme<select name="fournisseur_id">{options_f}</select></label>'
        '<label>Nom du modèle à appeler<input name="modele_appel" maxlength="200" required></label>'
        '<label>Replis ordonnés (fournisseur=modèle, un par ligne, 4 au plus)<textarea name="replis" rows="3" '
        'maxlength="800"></textarea></label>'
        f"{n3}<button>Affecter</button></form></details>"
    )
    plafonds = (
        f'<details><summary>Plafonds et coûts (N2)</summary><form method="post" action="{base}/role/plafonds" '
        f'class="pile">{caches}'
        '<label>Plafond de jetons par jour (vide = aucun)<input name="plafond_jetons_jour" inputmode="numeric" '
        'pattern="[0-9]*" maxlength="13"></label>'
        '<label>Budget en USD par mois (vide = aucun)<input name="budget_usd_mois" inputmode="decimal" maxlength="12">'
        "</label><button>Enregistrer les plafonds</button></form></details>"
    )
    actions = ""
    if r["configure"]:
        actions = (
            f'<form method="post" action="{base}/role/tester">{caches}<button>Tester la connexion</button></form>'
            f'<form method="post" action="{base}/role/retirer" class="pile">{caches}{n3}'
            "<button>Retirer l’affectation</button></form>"
            f'<form method="post" action="{base}/revenir" class="pile">{caches}'
            f'<input type="hidden" name="cible" value="role:{e(r["role"])}">{n3}'
            "<button>Retour arrière</button></form>"
        )
    return connecter + affecter + (plafonds if r["configure"] else "") + actions


def _ligne_role(
    r: Mapping[str, Any], fournisseurs: list[dict[str, Any]], alias: list[str], prefixe: str, csrf: str
) -> str:
    e = pages.e
    if not r["configure"]:
        reco = r["recommandation"]
        suggestion = f"<br>Suggestion (recommandation, non validée) : {e(reco['modele_amont'])}" if reco else ""
        corps = f"<td>{_badge('Inerte')} aucun appel (fail-closed){suggestion}</td><td>—</td><td>—</td>"
    else:
        replis = "".join(
            f"<li><code>{e(x['fournisseur'])}</code> — {e(x['modele'])}"
            + ("" if not x["fournisseur_vue"] else (" (conforme)" if x["fournisseur_vue"]["conforme"] else " (REFUSÉ)"))
            + "</li>"
            for x in r["replis"]
        )
        corps = (
            f"<td>{_cellule_fournisseur(r)}<br>Replis : " + (f"<ol>{replis}</ol>" if replis else "aucun") + "</td>"
            f"<td>{_cellule_plafonds(r)}</td><td>{_cellule_mesure(r)}</td>"
        )
    classes = ", ".join(r["classes"])
    extra = ""
    if r["role"] == lex.ROLE_RAISONNEMENT:
        extra = " " + (
            _badge("Escalade ACTIVE", "badge-alerte") if r.get("actif_raisonnement") else _badge("Escalade inactive")
        )
    return (
        f'<tr id="r-{e(r["role"])}"><td><strong>{e(r["libelle"])}</strong>{extra}<br><code>{e(r["role"])}</code><br>'
        f"Alias : <code>{e(r['alias'])}</code><br>Classes de tâche : {e(classes)}</td>{corps}"
        f"<td>{_formulaires_role(r, fournisseurs, alias, prefixe, csrf)}</td></tr>"
    )


def _section_passerelle(p: Mapping[str, Any], secrets_actifs: list[str], prefixe: str, csrf: str) -> str:
    e = pages.e
    base = f"{e(prefixe)}/plateforme/modeles"
    caches = f'<input type="hidden" name="csrf" value="{e(csrf)}">'
    n3 = (
        '<label><input type="checkbox" name="confirme_n3" value="oui"> '
        "Je confirme ce geste (niveau N3, journalisé)</label>"
    )
    options = "".join(f'<option value="{e(n)}">{e(n)}</option>' for n in secrets_actifs)
    if p["configuree"]:
        secrets = ", ".join(f"{e(n)} ({e(etat or 'absent')})" for n, etat in p["etat_secrets"].items())
        etat = (
            f"<p>{_badge('Connectée', 'badge-ok')} mode <strong>{e(p['mode'])}</strong> — <code>{e(p['url_base'])}"
            f"</code>{' (réseau privé confirmé)' if p['reseau_prive_confirme'] else ''}<br>Secrets du coffre : "
            f"{secrets}</p>"
            f'<form method="post" action="{base}/passerelle/tester">{caches}'
            "<button>Tester la connexion et découvrir le catalogue</button></form>"
            f'<form method="post" action="{base}/passerelle/retirer" class="pile">{caches}{n3}'
            "<button>Déconnecter la passerelle</button></form>"
            f'<form method="post" action="{base}/revenir" class="pile">{caches}'
            f'<input type="hidden" name="cible" value="passerelle">{n3}<button>Retour arrière</button></form>'
        )
    else:
        etat = "<p>" + _badge("Non configurée") + " Aucun rôle servi par une passerelle ne peut être appelé.</p>"
    formulaire = (
        f"<details><summary>{'Modifier' if p['configuree'] else 'Connecter'} la passerelle</summary>"
        f'<form method="post" action="{base}/passerelle" class="pile">{caches}'
        '<label>Mode<select name="mode"><option value="integree">LiteLLM intégré à OPSYS-AI (OPSYS génère sa '
        'configuration)</option><option value="existante">LiteLLM existant chez le client (URL + clé)</option>'
        '</select></label><label>URL de la passerelle<input name="url_base" maxlength="300" required '
        'placeholder="http://litellm:4000"></label>'
        f'<label>Secret du coffre : clé de la passerelle<select name="secret_cle">{options}</select></label>'
        f'<label>Secret du coffre : clé OpenRouter (mode intégré)<select name="secret_openrouter">'
        f'<option value="">(aucune)</option>{options}</select></label>'
        '<label><input type="checkbox" name="reseau_prive" value="oui"> '
        "Réseau privé de confiance (http:// toléré)</label>"
        f"{n3}<button>Enregistrer la passerelle</button></form></details>"
        '<p class="note">Les clés se saisissent UNE fois dans <a href="'
        f'{e(prefixe)}/plateforme/secrets">Secrets</a> ; cette page ne les lit ni ne les affiche jamais.</p>'
    )
    return f'<section class="carte pile"><h2>Passerelle LiteLLM</h2>{etat}{formulaire}</section>'


def _section_raisonnement(actif: bool, detail: Mapping[str, Any] | None, prefixe: str, csrf: str) -> str:
    e = pages.e
    base = f"{e(prefixe)}/plateforme/modeles"
    caches = f'<input type="hidden" name="csrf" value="{e(csrf)}">'
    if actif:
        etat = (
            f"<p>{_badge('Escalade ACTIVE', 'badge-alerte')} activée par {e((detail or {}).get('par'))} le "
            f"{e((detail or {}).get('le'))} — motif : {e((detail or {}).get('motif'))}</p>"
            f'<form method="post" action="{base}/raisonnement/desactiver">{caches}<button>Désactiver</button></form>'
        )
    else:
        etat = (
            f"<p>{_badge('Escalade inactive')} Le modèle de raisonnement n'est jamais appelé par défaut, "
            "ni en repli.</p>"
            f'<form method="post" action="{base}/raisonnement/activer" class="pile">{caches}'
            '<label>Motif de l’activation (10 à 300 caractères)<input name="motif" maxlength="300" required></label>'
            '<label><input type="checkbox" name="confirme_n3" value="oui"> '
            "Je confirme l’activation (niveau N3 explicite, journalisée)</label>"
            "<button>Activer le raisonnement</button></form>"
        )
    return (
        '<section class="carte pile"><h2>Raisonnement (escalade explicite)</h2>'
        "<p>Consigne : Opus seulement si vraiment nécessaire. Même activé, il n'est joignable que par la classe "
        "« escalade_raisonnement », demandée par une personne admin avec un motif.</p>" + etat + "</section>"
    )


def _section_catalogue(cat: Mapping[str, Any] | None) -> str:
    e = pages.e
    if not cat:
        return (
            '<section class="carte pile"><h2>Catalogue de la passerelle</h2><p>Aucune découverte : tester la connexion '
            "de la passerelle.</p></section>"
        )
    lignes = "".join(
        f"<tr><td><code>{e(x['nom'])}</code></td><td>{e(_cle_ou_tiret(x['mode']))}</td>"
        f"<td>{e(_cle_ou_tiret(x['cout_entree_par_million']))} / {e(_cle_ou_tiret(x['cout_sortie_par_million']))}</td>"
        f"<td>{e({True: 'oui', False: 'non', None: '?'}[x['vision']])}</td>"
        f"<td>{e(_cle_ou_tiret(x['modele_amont']))}</td></tr>"
        for x in cat["entrees"]
    )
    return (
        f'<section class="carte pile"><h2>Catalogue de la passerelle</h2><p>Découvert le {e(cat["decouvert_le"])} '
        "(« — » = non déclaré ; un coût rapporté à 0 n'est pas retenu).</p>"
        "<table><thead><tr><th>Alias</th><th>Mode</th>"
        "<th>Coût USD / million (entrée / sortie)</th><th>Vision</th><th>Modèle d'amont</th></tr></thead>"
        f"<tbody>{lignes}</tbody></table></section>"
    )


def _section_economie(politique: Mapping[str, Any]) -> str:
    e = pages.e
    lignes = "".join(
        f"<tr><td><code>{e(nom)}</code></td><td>{e(c['libelle'])}</td><td><code>{e(c['role'])}</code></td>"
        f"<td>{'approbation requise' if c['approbation'] else '—'}</td><td>{e(c['statut'].replace('_', ' '))}</td></tr>"
        for nom, c in politique["classes"].items()
    )
    return (
        '<section class="carte pile"><h2>Politique d’économie (classe de tâche → rôle)</h2><p>Recommandation, non '
        f"validée (version {e(politique['version'])}). Une classe inconnue est refusée : "
        "aucun aiguillage par défaut.</p>"
        "<table><thead><tr><th>Classe</th><th>Tâche</th><th>Rôle</th><th>Garde</th><th>Statut</th></tr></thead>"
        f"<tbody>{lignes}</tbody></table></section>"
    )


def _section_historique(historique: list[dict[str, Any]]) -> str:
    e = pages.e
    lignes = "".join(
        f"<tr><td>{e(h['quand'])}</td><td>{e(h['cible'])}</td><td>{e(h['action'])}</td>"
        f"<td>{e(h['acteur'])}</td><td>{e(h['niveau'])}</td></tr>"
        for h in historique
    ) or ('<tr><td colspan="5">Aucun changement.</td></tr>')
    return (
        '<section class="carte pile"><h2>Historique (append-only, sans secret)</h2><table><thead><tr><th>Quand</th>'
        f"<th>Cible</th><th>Action</th><th>Acteur</th><th>Niveau</th></tr></thead><tbody>{lignes}</tbody></table></section>"
    )


def contenu(
    vue: Mapping[str, Any], fournisseurs: list[dict[str, Any]], secrets_actifs: list[str], *, prefixe: str, csrf: str
) -> str:
    navigation = (
        pages.navigation_plateforme(prefixe, "modeles")
        + '<p class="note">Chaque rôle désigne un fournisseur du registre (licence et EFVP vérifiées) et le modèle à '
        "appeler ; sans affectation il est inerte. Tout est « non mesuré » tant qu'aucune mesure locale (français "
        "québécois, factures réelles) n'existe. Aucun coût n'est estimé : seulement ceux que la passerelle ou le "
        "propriétaire déclare.</p>"
    )
    if not vue["profil_licence_declare"]:
        navigation += (
            "<p><strong>Profil de licence du client non déclaré :</strong> aucune affectation n’est possible "
            f'(PROFIL_CLIENT_ABSENT). <a href="{pages.e(prefixe)}/plateforme/fournisseurs">Le déclarer</a>.</p>'
        )
    alias = [x["nom"] for x in (vue["catalogue_passerelle"] or {}).get("entrees", [])]
    lignes = "".join(_ligne_role(r, fournisseurs, alias, prefixe, csrf) for r in vue["roles"])
    table = (
        '<section class="pile"><h2>Rôles</h2><table><thead><tr><th>Rôle</th><th>Affectation courante</th>'
        "<th>Plafonds, usage et coût</th><th>Mesure</th><th>Actions</th></tr></thead>"
        f"<tbody>{lignes}</tbody></table></section>"
    )
    return (
        navigation
        + _section_passerelle(vue["passerelle"], secrets_actifs, prefixe, csrf)
        + _section_raisonnement(vue["raisonnement"]["actif"], vue["raisonnement"]["detail"], prefixe, csrf)
        + table
        + _section_catalogue(vue["catalogue_passerelle"])
        + _section_economie(vue["politique_economie"])
        + _section_historique(vue["historique"])
    )


def creer_router(
    *,
    session_page: Callable[..., Session],
    session_api: Callable[..., Session],
    verifier_formulaire: Callable[[Mapping[str, str], Session], None],
    formulaire: Callable[[Request], Awaitable[dict[str, str]]],
    cnx_factory: Callable[[], Any],
    prefixe: str,
) -> APIRouter:
    router = APIRouter(tags=["modeles"])
    masquage.installer()

    def servir(html: str) -> HTMLResponse:
        if masquage.contient_secret(html):
            raise HTTPException(500, "rendu refusé : contenu sensible détecté")
        return HTMLResponse(html, headers=ENTETES)

    def retour(**params: str) -> RedirectResponse:
        requete = "&".join(f"{k}={quote(v, safe=',-')}" for k, v in params.items() if v)
        return RedirectResponse(
            f"{prefixe}/plateforme/modeles" + (f"?{requete}" if requete else ""), status_code=303, headers=ENTETES
        )

    def echec(exc: ModelesErreur) -> RedirectResponse:
        return retour(erreur=exc.code, refus=",".join(exc.codes))

    async def ecriture(request: Request) -> tuple[Session, dict[str, str]]:
        session = session_page(request)
        champs = await formulaire(request)
        verifier_formulaire(champs, session)
        session_page(request)
        return session, champs

    def niveau(champs: Mapping[str, str]) -> str | None:
        return "N3" if champs.get("confirme_n3") == "oui" else None

    def donnees() -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
        with cnx_factory() as cnx:
            return (
                service.vue_complete(cnx),
                registre.lister(cnx),
                [m["nom"] for m in coffre.lister(cnx) if m["etat"] == "actif"],
            )

    @router.get("/plateforme/modeles", response_class=HTMLResponse)
    def page(request: Request) -> Response:
        session = session_page(request)
        vue, fournisseurs, secrets = donnees()
        corps = contenu(vue, fournisseurs, secrets, prefixe=prefixe, csrf=session.csrf)
        session_page(request)
        return servir(
            pages.gabarit(
                "Plateforme — modèles et rôles",
                corps,
                prefixe=prefixe,
                session=session,
                actif=ONGLET,
                bandeau=_bandeau(request.query_params),
            )
        )

    @router.get("/api/plateforme/modeles")
    def api(request: Request) -> JSONResponse:
        session_api(request)
        vue, _, _ = donnees()
        return JSONResponse(masquage.masquer({"ok": True, **vue}), headers=ENTETES)

    def appliquer(
        session: Session,
        operation: str,
        parametres: Mapping[str, Any],
        champs: Mapping[str, str],
        succes: str,
        motif: str | None = None,
    ) -> RedirectResponse:
        try:
            with cnx_factory() as cnx:
                service.appliquer(
                    cnx,
                    acteur=session.utilisateur,
                    operation=operation,
                    parametres=parametres,
                    niveau_confirme=niveau(champs),
                    motif=motif,
                )
        except ModelesErreur as exc:
            return echec(exc)
        return retour(ok=succes)

    @router.post("/plateforme/modeles/passerelle")
    async def form_passerelle(request: Request) -> Response:
        session, champs = await ecriture(request)
        amont = {"openrouter": champs["secret_openrouter"]} if champs.get("secret_openrouter") else {}
        parametres = {
            "mode": champs.get("mode"),
            "url_base": champs.get("url_base"),
            "secret_cle": champs.get("secret_cle"),
            "secrets_amont": amont,
            "reseau_prive_confirme": champs.get("reseau_prive") == "oui",
        }
        return appliquer(session, service.OP_PASSERELLE_CONFIGURER, parametres, champs, "passerelle")

    @router.post("/plateforme/modeles/passerelle/retirer")
    async def form_passerelle_retirer(request: Request) -> Response:
        session, champs = await ecriture(request)
        return appliquer(session, service.OP_PASSERELLE_RETIRER, {}, champs, "passerelle_retiree")

    @router.post("/plateforme/modeles/passerelle/tester")
    async def form_passerelle_tester(request: Request) -> Response:
        session, _ = await ecriture(request)
        resultat = await run_in_threadpool(
            decouverte.decouvrir, cnx_factory, acteur=session.utilisateur, ouvrir=OUVRIR_HTTP
        )
        if resultat["statut"] != "succes":
            return retour(erreur=resultat["code"])
        return retour(ok="catalogue")

    @router.post("/plateforme/modeles/raisonnement/activer")
    async def form_raisonnement_activer(request: Request) -> Response:
        session, champs = await ecriture(request)
        return appliquer(
            session, service.OP_RAISONNEMENT_ACTIVER, {}, champs, "raisonnement_active", motif=champs.get("motif", "")
        )

    @router.post("/plateforme/modeles/raisonnement/desactiver")
    async def form_raisonnement_desactiver(request: Request) -> Response:
        session, champs = await ecriture(request)
        return appliquer(session, service.OP_RAISONNEMENT_DESACTIVER, {}, champs, "raisonnement_desactive")

    @router.post("/plateforme/modeles/role/connecter")
    async def form_role_connecter(request: Request) -> Response:
        from ..roles_modeles import passerelle_fournisseur

        session, champs = await ecriture(request)
        role = champs.get("role", "")
        try:
            if role not in lex.ROLES:
                return retour(erreur="REJ-MODELES-ROLE-INCONNU")
            if niveau(champs) != "N3":
                return retour(erreur="REJ-MODELES-CONFIRMATION-N3-REQUISE")
            amont = None
            if champs.get("amont"):
                fournisseur, _, modele = champs["amont"].partition("/")
                amont = {"fournisseur": fournisseur, "modele": modele}
            with cnx_factory() as cnx:
                reglage = service.passerelle(cnx)
                if reglage is None:
                    return retour(erreur="REJ-MODELES-PASSERELLE-ABSENTE")
                declare = passerelle_fournisseur.declarer(
                    cnx,
                    acteur=session.utilisateur,
                    role=role,
                    alias=champs.get("alias", ""),
                    secret_cle=reglage["secret_cle"],
                    efvp_ref=champs.get("efvp_ref") or None,
                    contrat_ref=champs.get("contrat_ref") or None,
                )
                if not declare["active"]:
                    return retour(erreur="REJ-MODELES-FOURNISSEUR-REFUSE", refus=",".join(declare["refus"]))
                service.appliquer(
                    cnx,
                    acteur=session.utilisateur,
                    operation=service.OP_ROLE_AFFECTER,
                    parametres={
                        "role": role,
                        "fournisseur_id": declare["identifiant"],
                        "modele_appel": champs.get("alias"),
                        "amont": amont,
                    },
                    niveau_confirme="N3",
                )
        except ModelesErreur as exc:
            return echec(exc)
        return retour(ok="role_connecte")

    @router.post("/plateforme/modeles/role/affecter")
    async def form_role_affecter(request: Request) -> Response:
        session, champs = await ecriture(request)
        replis = []
        for ligne in (champs.get("replis") or "").splitlines():
            if ligne.strip():
                fournisseur, sep, modele = ligne.strip().partition("=")
                if not sep:
                    return retour(erreur="REJ-MODELES-REPLI-INVALIDE")
                replis.append({"fournisseur": fournisseur.strip(), "modele": modele.strip()})
        parametres = {
            "role": champs.get("role"),
            "fournisseur_id": champs.get("fournisseur_id"),
            "modele_appel": champs.get("modele_appel"),
            "replis": replis,
        }
        return appliquer(session, service.OP_ROLE_AFFECTER, parametres, champs, "role_affecte")

    @router.post("/plateforme/modeles/role/retirer")
    async def form_role_retirer(request: Request) -> Response:
        session, champs = await ecriture(request)
        return appliquer(session, service.OP_ROLE_RETIRER, {"role": champs.get("role")}, champs, "role_retire")

    @router.post("/plateforme/modeles/role/plafonds")
    async def form_role_plafonds(request: Request) -> Response:
        session, champs = await ecriture(request)
        brut = champs.get("plafond_jetons_jour", "")
        if brut and not brut.isdigit():
            return retour(erreur="REJ-MODELES-DECLARATION-INVALIDE")
        parametres = {
            "role": champs.get("role"),
            "plafond_jetons_jour": int(brut) if brut else None,
            "budget_usd_mois": champs.get("budget_usd_mois") or None,
        }
        return appliquer(session, service.OP_ROLE_PLAFONDS, parametres, champs, "plafonds")

    @router.post("/plateforme/modeles/role/tester")
    async def form_role_tester(request: Request) -> Response:
        session, champs = await ecriture(request)
        try:
            await run_in_threadpool(
                appel.tester_role,
                cnx_factory,
                acteur=session.utilisateur,
                role=champs.get("role", ""),
                ouvrir=OUVRIR_HTTP,
            )
        except ModelesErreur as exc:
            return echec(exc)
        except ValueError:
            return retour(erreur="REJ-MODELES-ROLE-INCONNU")
        return retour(ok="teste")

    @router.post("/plateforme/modeles/revenir")
    async def form_revenir(request: Request) -> Response:
        session, champs = await ecriture(request)
        return appliquer(session, service.OP_REVENIR, {"cible": champs.get("cible")}, champs, "revenu")

    return router
