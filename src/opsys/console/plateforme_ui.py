"""Console « Plateforme » : registre de fournisseurs (licence, politique, test de connexion) et coffre de secrets.

Protections (les mêmes que le reste de la console, plus celles du coffre) :
- session obligatoire et rôle `nathan_owner`/`admin` RELU EN BASE à chaque requête (`session_page`), puis relu
  encore par le registre et le coffre dans leur propre transaction ;
- CSRF sur chaque écriture (champ `csrf`), corps borné (`formulaire` de l'application) ;
- `Cache-Control: no-store` sur chaque réponse ; CSP stricte ajoutée par l'application ;
- un secret est saisi UNE fois (champ mot de passe, jamais prérempli) et n'est JAMAIS réaffiché : les pages et
  l'API ne lisent que des métadonnées ; la redirection après écriture ne porte qu'un code fixe ;
- avant d'être servie, chaque page est contrôlée : un jeton opaque ou une valeur active détectée = 500.

Routes : /plateforme/fournisseurs, /plateforme/secrets (pages) ; /api/plateforme/fournisseurs,
/api/plateforme/secrets (lecture JSON) ; écritures POST par formulaire sous /plateforme/….
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from ..fournisseurs import registre, sondes
from ..fournisseurs.modele import CAPACITES, TERRITOIRES
from ..fournisseurs.registre import RegistreErreur
from ..secrets_coffre import coffre, masquage
from ..secrets_coffre.erreurs import CoffreErreur
from . import pages
from .securite import Session

ENTETES = {"Cache-Control": "no-store", "Pragma": "no-cache"}
ONGLET = "plateforme/fournisseurs"
# Sonde HTTP du test de connexion : None = sonde réelle (production) ; les tests la remplacent par une simulation.
SONDE_HTTP: sondes.Sonde | None = None
_CODE = re.compile(r"^[A-Z][A-Z0-9_]{2,47}$")
_IDENT = re.compile(r"^[a-z0-9][a-z0-9._-]{2,79}$")
_LIBELLES_CAPACITES = {
    "llm": "LLM", "embeddings": "Embeddings", "reranker": "Reranker", "ocr": "OCR / parsing", "stt": "Voix → texte",
    "tts": "Texte → voix", "avatar": "Avatar", "image": "Image", "video": "Vidéo", "recherche_web": "Recherche web",
    "courriel": "Courriel",
}
_STATUTS = {"adopte": ("Adopté", "badge-ok"), "repli": ("Repli", ""), "conditionnel": ("Conditionnel", "badge-alerte"),
            "ecarte": ("Écarté", "badge-danger"), "declare": ("Déclaré", "")}
_SUCCES = {
    "profil": "Profil de licence enregistré.", "configure": "Configuration enregistrée.",
    "active": "Fournisseur activé : politique conforme.", "desactive": "Fournisseur désactivé.",
    "teste": "Test de connexion terminé : voir le résultat dans la ligne du fournisseur.",
    "selection": "Sélection enregistrée.", "secret_defini": "Secret enregistré, chiffré. Il ne sera plus affiché.",
    "secret_tourne": "Nouvelle valeur enregistrée ; l'ancienne est détruite.",
    "secret_revoque": "Secret révoqué : ses octets chiffrés sont détruits et ses jetons refusés.",
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
        return (f"Action refusée ({erreur}){suite}. Rien d'autre n'a été activé à la place.", "erreur")
    return None


def _cellule_licence(f: Mapping[str, Any]) -> str:
    lic = f["licence"]
    lignes = [f"Code : {lic['code'] or 'n/a'}", f"Poids : {lic['poids'] or 'sans poids'}",
              f"Usage commercial : {lic['usage_commercial']}"]
    if lic["seuil_revenu_usd"]:
        lignes.append(f"Seuil de revenu : {lic['seuil_revenu_usd']:,} USD".replace(",", " "))
    if lic["territoires_exclus"]:
        lignes.append(f"Territoires exclus : {', '.join(lic['territoires_exclus'])}")
    lignes.append(f"Service à des tiers : {lic['service_tiers']}")
    if lic["mention_obligatoire"]:
        lignes.append(f"Mention obligatoire : {lic['mention_obligatoire']}")
    if lic["verification"] == "a_lire":
        lignes.append("Texte intégral à lire" + (f" (lu : {f['licence_lue_par']})" if f["licence_lue_par"] else ""))
    lignes.append(f"Source : {lic['source']}")
    if lic["note"]:
        lignes.append(f"Note : {lic['note']}")
    return "<br>".join(pages.e(x) for x in lignes)


def _cellule_politique(f: Mapping[str, Any]) -> str:
    politique = f["politique"]
    if politique["conforme"]:
        return _badge("Conforme", "badge-ok")
    return _badge("Refusé", "badge-danger") + "<ul>" + "".join(
        f"<li><code>{pages.e(r['code'])}</code> {pages.e(r['motif'])}</li>" for r in politique["refus"]) + "</ul>"


def _cellule_etat(f: Mapping[str, Any]) -> str:
    etat = _badge("Actif", "badge-ok") if f["actif"] else _badge("Inactif" if f["configure"] else "Non configuré")
    qualif = (_badge("À mesurer", "badge-alerte") if f["qualification"] == "a_mesurer"
              else _badge("Qualifié", "badge-ok"))
    test = f.get("dernier_test")
    texte = (f"<br>Dernier test : {pages.e(test['statut'])} — {pages.e(test.get('detail', ''))} "
             f"({pages.e(test.get('date', ''))})") if test else "<br>Aucun test."
    return etat + " " + qualif + texte


def _formulaires_fournisseur(f: Mapping[str, Any], secrets_actifs: list[str], prefixe: str, csrf: str) -> str:
    e = pages.e
    base = f"{e(prefixe)}/plateforme/fournisseurs"
    caches = (f'<input type="hidden" name="csrf" value="{e(csrf)}">'
              f'<input type="hidden" name="identifiant" value="{e(f["identifiant"])}">')
    options = '<option value="">(aucun)</option>' + "".join(
        f'<option value="coffre:{e(n)}"{" selected" if f["reference_secret"] == "coffre:" + n else ""}>{e(n)}</option>'
        for n in secrets_actifs)
    lue = "" if f["licence"]["verification"] != "a_lire" or f["licence_lue_par"] else (
        '<label><input type="checkbox" name="licence_lue" value="oui"> J’ai lu le texte intégral de la licence</label>')
    mention = "" if not f["licence"]["mention_obligatoire"] else (
        '<input type="hidden" name="mention_confirmee_present" value="oui">'
        '<label><input type="checkbox" name="mention_confirmee" value="oui"'
        f'{" checked" if f["mention_confirmee"] else ""}> La mention obligatoire sera affichée</label>')
    configurer = (
        f'<details><summary>Configurer</summary><form method="post" action="{base}/configurer" class="pile">{caches}'
        f'<input type="hidden" name="revision_attendue" value="{int(f["revision"])}">'
        f'<label>Point d’accès<input name="point_acces" maxlength="500" value="{e(f["point_acces"] or "")}"></label>'
        '<label>Secret (référence au coffre, jamais la valeur)'
        f'<select name="reference_secret">{options}</select></label>'
        '<label>Référence EFVP (Loi 25)'
        f'<input name="efvp_ref" maxlength="200" value="{e(f["efvp_ref"] or "")}"></label>'
        f'<label>Référence du contrat / des conditions<input name="contrat_ref" maxlength="200" '
        f'value="{e(f["contrat_ref"] or "")}"></label>{mention}{lue}'
        '<button>Enregistrer la configuration</button></form></details>'
    )
    actions = ""
    if f["configure"]:
        bouton = "desactiver" if f["actif"] else "activer"
        actions = (f'<form method="post" action="{base}/{bouton}">{caches}'
                   f'<button>{"Désactiver" if f["actif"] else "Activer (politique vérifiée)"}</button></form>'
                   f'<form method="post" action="{base}/tester">{caches}<button>Tester la connexion</button></form>')
    return configurer + actions


def contenu_fournisseurs(vues: list[dict[str, Any]], profil: dict[str, Any] | None, choix: list[dict[str, Any]],
                         secrets_actifs: list[str], departements: list[str], *, prefixe: str, csrf: str) -> str:
    e = pages.e
    base = f"{e(prefixe)}/plateforme/fournisseurs"
    navigation = (f'<p><a href="{base}">Fournisseurs</a> · <a href="{e(prefixe)}/plateforme/secrets">Secrets</a></p>'
                  "<p class=\"note\">Chaque fournisseur porte son bloc licence ; l’activation est refusée, avec son "
                  "code, si la licence n’est pas conforme au profil du client. Aucun repli automatique. Les mesures "
                  "locales n’existent pas encore : tout est « à mesurer ».</p>")
    p = profil or {"usage_commercial": True, "revenu_annuel_usd": None, "territoires": [], "heberge_pour_tiers": False,
                   "revision": 0}
    territoires = "".join(
        f'<label><input type="checkbox" name="territoire_{t}" value="oui"{" checked" if t in p["territoires"] else ""}>'
        f" {e(t)}</label>" for t in TERRITOIRES)
    etat_profil = ("<p><strong>Profil non déclaré :</strong> toute activation est refusée "
                   "(PROFIL_CLIENT_ABSENT).</p>") if profil is None else (
        f"<p>Révision {int(p['revision'])}, par {e(p['modifie_par'])} le {e(p['modifie_le'])}.</p>")
    revenu = "" if p["revenu_annuel_usd"] is None else str(int(p["revenu_annuel_usd"]))
    section_profil = (
        '<section class="carte pile"><h2>Profil de licence du client</h2>' + etat_profil +
        f'<form method="post" action="{base}/profil" class="pile">'
        f'<input type="hidden" name="csrf" value="{e(csrf)}">'
        f'<input type="hidden" name="revision_attendue" value="{int(p["revision"])}">'
        '<label><input type="checkbox" name="usage_commercial" value="oui"'
        f'{" checked" if p["usage_commercial"] else ""}> Usage commercial des sorties</label>'
        f'<label>Revenu annuel déclaré (USD, affiliés compris ; vide = inconnu)<input name="revenu_annuel_usd" '
        f'inputmode="numeric" pattern="[0-9]*" maxlength="15" value="{e(revenu)}"></label>'
        f"<fieldset><legend>Territoires du client et de l’hébergement</legend>{territoires}</fieldset>"
        '<label><input type="checkbox" name="heberge_pour_tiers" value="oui"'
        f'{" checked" if p["heberge_pour_tiers"] else ""}> OPSYS sert ces composants à des tiers '
        "(multi-locataire)</label><button>Enregistrer le profil</button></form></section>"
    )
    actifs = [v for v in vues if v["actif"]]
    lignes_choix = "".join(
        f"<tr><td>{e(c['capacite'])}</td><td>{'Défaut global' if c['portee'] == '*' else e(c['portee'])}</td>"
        f"<td><code>{e(c['identifiant'])}</code></td></tr>" for c in choix) or (
        '<tr><td colspan="3">Aucune sélection : chaque capacité est sans fournisseur '
        "(refus AUCUN_FOURNISSEUR).</td></tr>")
    section_choix = (
        '<section class="carte pile"><h2>Sélection par capacité et par département</h2>'
        f"<table><thead><tr><th>Capacité</th><th>Portée</th><th>Fournisseur</th></tr></thead><tbody>{lignes_choix}"
        f'</tbody></table><form method="post" action="{base}/selectionner" class="pile">'
        f'<input type="hidden" name="csrf" value="{e(csrf)}">'
        '<label>Capacité<select name="capacite">' + "".join(
            f'<option value="{e(c)}">{e(_LIBELLES_CAPACITES[c])}</option>' for c in CAPACITES) + "</select></label>"
        '<label>Portée<select name="departement"><option value="*">Défaut global</option>' + "".join(
            f'<option value="{e(d)}">{e(d)}</option>' for d in departements) + "</select></label>"
        '<label>Fournisseur actif<select name="identifiant">' + "".join(
            f'<option value="{e(v["identifiant"])}">{e(v["identifiant"])}</option>' for v in actifs)
        + "</select></label>"
        "<button>Enregistrer la sélection</button></form></section>"
    )
    sections = []
    for capacite in CAPACITES:
        lignes = []
        for f in (v for v in vues if v["capacite"] == capacite):
            libelle, classe = _STATUTS[f["statut_catalogue"]]
            raison = f"<br><em>{e(f['raison_ecart'])}</em>" if f["raison_ecart"] else ""
            cout = f["cout_unitaire"]
            cout_txt = (f"{e(cout['montant'])} {e(cout['devise'])} / {e(cout['unite'])}" if cout else "non déclaré")
            lignes.append(
                f'<tr id="f-{e(f["identifiant"])}"><td><code>{e(f["identifiant"])}</code><br>{_badge(libelle, classe)}'
                f"{raison}</td><td>{e(f['mode'])} — {e(f['modele'])}<br>Coût : {cout_txt}</td>"
                f"<td>{_cellule_licence(f)}</td><td>{_cellule_politique(f)}</td><td>{_cellule_etat(f)}</td>"
                f"<td>{_formulaires_fournisseur(f, secrets_actifs, prefixe, csrf)}</td></tr>")
        sections.append(
            f'<section class="pile"><h2>{e(_LIBELLES_CAPACITES[capacite])}</h2><table><thead><tr><th>Fournisseur</th>'
            "<th>Mode et modèle</th><th>Licence</th><th>Politique</th><th>État</th><th>Actions</th></tr></thead>"
            f"<tbody>{''.join(lignes)}</tbody></table></section>")
    return navigation + section_profil + section_choix + "".join(sections)


def contenu_secrets(metas: list[dict[str, Any]], journal: list[dict[str, Any]], *, prefixe: str, csrf: str) -> str:
    e = pages.e
    base = f"{e(prefixe)}/plateforme/secrets"
    lignes = "".join(
        f"<tr><td><code>{e(m['nom'])}</code></td><td>{e(m['service'])}</td><td>"
        + (_badge("Actif", "badge-ok") if m["etat"] == "actif" else _badge("Révoqué", "badge-danger"))
        + f"</td><td>{e(m['version'] or '—')}</td><td>{e(m['modifie_le'])} ({e(m['modifie_par'])})</td>"
        f"<td>{int(m['jetons_actifs'])}</td><td>•••• (jamais réaffiché)</td></tr>" for m in metas
    ) or '<tr><td colspan="7">Aucun secret.</td></tr>'
    actifs = [m["nom"] for m in metas if m["etat"] == "actif"]
    choix = "".join(f'<option value="{e(n)}">{e(n)}</option>' for n in actifs)
    services = "".join(f'<option value="{e(s)}">{e(s)}</option>' for s in coffre.SERVICES)
    jeton = f'<input type="hidden" name="csrf" value="{e(csrf)}">'
    valeur = ('<label>Valeur (saisie unique, jamais réaffichée)<input type="password" name="valeur" required '
              'autocomplete="new-password" spellcheck="false" maxlength="16384"></label>')
    entrees = "".join(
        f"<tr><td>{e(j['quand'])}</td><td><code>{e(j['nom'])}</code></td><td>{e(j['action'])}</td>"
        f"<td>{e(j['acteur'])}</td><td>{e(j['usage'] or '')}</td><td>{e(j['resultat'])}</td>"
        f"<td>{e(j['code'] or '')}</td></tr>" for j in journal) or '<tr><td colspan="7">Journal vide.</td></tr>'
    return (
        f'<p><a href="{e(prefixe)}/plateforme/fournisseurs">Fournisseurs</a> · <a href="{base}">Secrets</a></p>'
        "<p class=\"note\">Les valeurs sont chiffrées au repos (AES-256-GCM, clé maîtresse hors base). Les agents ne "
        "reçoivent qu’un jeton opaque, résolu par le serveur au moment de l’appel. Aucun export en clair.</p>"
        "<table><thead><tr><th>Nom</th><th>Service</th><th>État</th><th>Version</th><th>Modifié</th>"
        f"<th>Jetons actifs</th><th>Valeur</th></tr></thead><tbody>{lignes}</tbody></table>"
        f'<section class="carte pile"><h2>Nouveau secret</h2><form method="post" action="{base}/definir" class="pile">'
        f'{jeton}<label>Nom<input name="nom" required maxlength="80" pattern="[a-z0-9][a-z0-9._-]{{2,79}}" '
        f'autocomplete="off"></label><label>Service<select name="service">{services}</select></label>{valeur}'
        "<button>Chiffrer et enregistrer</button></form></section>"
        f'<section class="carte pile"><h2>Rotation</h2><form method="post" action="{base}/rotation" class="pile">'
        f'{jeton}<label>Secret<select name="nom">{choix}</select></label>{valeur}'
        "<button>Remplacer la valeur</button></form></section>"
        f'<section class="carte pile"><h2>Révocation</h2><form method="post" action="{base}/revoquer" class="pile">'
        f'{jeton}<label>Secret<select name="nom">{choix}</select></label>'
        '<label><input type="checkbox" name="confirme" value="oui" required> Révoquer immédiatement : la valeur est '
        "détruite et ne pourra plus être utilisée</label><button>Révoquer</button></form></section>"
        "<section class=\"pile\"><h2>Journal d’accès (50 derniers)</h2><table><thead><tr><th>Quand</th><th>Nom</th>"
        "<th>Action</th><th>Acteur</th><th>Usage</th><th>Résultat</th><th>Code</th></tr></thead>"
        f"<tbody>{entrees}</tbody></table></section>"
    )


def creer_router(
    *, session_page: Callable[..., Session], session_api: Callable[..., Session],
    verifier_formulaire: Callable[[Mapping[str, str], Session], None],
    formulaire: Callable[[Request], Awaitable[dict[str, str]]], cnx_factory: Callable[[], Any],
    departements: list[str], prefixe: str,
) -> APIRouter:
    router = APIRouter(tags=["plateforme"])
    masquage.installer()

    def servir(html: str, code: int = 200) -> HTMLResponse:
        if masquage.contient_secret(html):
            raise HTTPException(500, "rendu refusé : contenu sensible détecté")
        return HTMLResponse(html, status_code=code, headers=ENTETES)

    def retour(page: str, **params: str) -> RedirectResponse:
        requete = "&".join(f"{k}={quote(v, safe=',')}" for k, v in params.items() if v)
        return RedirectResponse(f"{prefixe}/plateforme/{page}" + (f"?{requete}" if requete else ""), status_code=303,
                                headers=ENTETES)

    def echec(page: str, exc: RegistreErreur | CoffreErreur) -> RedirectResponse:
        codes = ",".join(getattr(exc, "codes", ()) or ())
        return retour(page, erreur=exc.code, refus=codes)

    async def ecriture(request: Request) -> tuple[Session, dict[str, str]]:
        session = session_page(request)
        champs = await formulaire(request)
        verifier_formulaire(champs, session)
        session_page(request)  # rôle relu à nouveau juste avant l'écriture
        return session, champs

    def identifiant(champs: Mapping[str, str]) -> str:
        valeur = champs.get("identifiant", "")
        if not _IDENT.fullmatch(valeur):
            raise HTTPException(422, "identifiant de fournisseur invalide")
        return valeur

    # -- lecture ----------------------------------------------------------------------------------
    def donnees_fournisseurs() -> tuple[list, dict | None, list, list[str]]:
        with cnx_factory() as cnx:
            return (registre.lister(cnx), registre.profil_brut(cnx), registre.selections(cnx),
                    [m["nom"] for m in coffre.lister(cnx) if m["etat"] == "actif"])

    @router.get("/plateforme/fournisseurs", response_class=HTMLResponse)
    def page_fournisseurs(request: Request) -> Response:
        session = session_page(request)
        vues, profil, choix, actifs = donnees_fournisseurs()
        corps = contenu_fournisseurs(vues, profil, choix, actifs, departements, prefixe=prefixe, csrf=session.csrf)
        session_page(request)
        return servir(pages.gabarit("Plateforme — fournisseurs", corps, prefixe=prefixe, session=session,
                                    actif=ONGLET, bandeau=_bandeau(request.query_params)))

    @router.get("/plateforme/secrets", response_class=HTMLResponse)
    def page_secrets(request: Request) -> Response:
        session = session_page(request)
        with cnx_factory() as cnx:
            metas, journal = coffre.lister(cnx), coffre.journal(cnx, limite=50)
        session_page(request)
        return servir(pages.gabarit("Plateforme — secrets", contenu_secrets(metas, journal, prefixe=prefixe,
                                                                           csrf=session.csrf),
                                    prefixe=prefixe, session=session, actif=ONGLET,
                                    bandeau=_bandeau(request.query_params)))

    @router.get("/api/plateforme/fournisseurs")
    def api_fournisseurs(request: Request) -> JSONResponse:
        session_api(request)
        vues, profil, choix, _ = donnees_fournisseurs()
        return JSONResponse(masquage.masquer({"ok": True, "profil": profil, "selections": choix,
                                              "fournisseurs": vues}), headers=ENTETES)

    @router.get("/api/plateforme/secrets")
    def api_secrets(request: Request) -> JSONResponse:
        session_api(request)
        with cnx_factory() as cnx:
            metas = coffre.lister(cnx)
        return JSONResponse({"ok": True, "secrets": metas}, headers=ENTETES)

    @router.get("/api/plateforme/secrets/{nom}/valeur")
    def api_valeur_refusee(nom: str, request: Request) -> JSONResponse:
        session = session_api(request)
        try:
            coffre.avec_journal(cnx_factory, coffre.exporter, acteur=session.utilisateur,
                                nom=nom if _IDENT.fullmatch(nom) else None)
        except CoffreErreur as exc:
            return JSONResponse({"ok": False, **exc.publique()}, status_code=exc.statut_http, headers=ENTETES)
        raise HTTPException(500, "export inattendu")  # exporter refuse toujours

    # -- fournisseurs : écritures -----------------------------------------------------------------
    @router.post("/plateforme/fournisseurs/profil")
    async def form_profil(request: Request) -> Response:
        session, champs = await ecriture(request)
        revenu = champs.get("revenu_annuel_usd", "").strip()
        if revenu and not revenu.isdigit():
            return retour("fournisseurs", erreur="PROFIL_INVALIDE")
        try:
            with cnx_factory() as cnx:
                registre.declarer_profil(
                    cnx, acteur=session.utilisateur, usage_commercial=champs.get("usage_commercial") == "oui",
                    revenu_annuel_usd=int(revenu) if revenu else None,
                    territoires=[t for t in TERRITOIRES if champs.get(f"territoire_{t}") == "oui"],
                    heberge_pour_tiers=champs.get("heberge_pour_tiers") == "oui",
                    revision_attendue=int(champs.get("revision_attendue", "-1") or -1))
        except RegistreErreur as exc:
            return echec("fournisseurs", exc)
        return retour("fournisseurs", ok="profil")

    @router.post("/plateforme/fournisseurs/configurer")
    async def form_configurer(request: Request) -> Response:
        session, champs = await ecriture(request)
        ident = identifiant(champs)
        modifications: dict[str, Any] = {
            "point_acces": champs.get("point_acces", "").strip(),
            "reference_secret": champs.get("reference_secret", "").strip(),
            "efvp_ref": champs.get("efvp_ref", "").strip(), "contrat_ref": champs.get("contrat_ref", "").strip(),
        }
        if "mention_confirmee" in champs or "mention_confirmee_present" in champs:
            modifications["mention_confirmee"] = champs.get("mention_confirmee") == "oui"
        if champs.get("licence_lue") == "oui":
            modifications["licence_lue"] = True
        try:
            revision = int(champs.get("revision_attendue", "-1"))
            with cnx_factory() as cnx:
                registre.configurer(cnx, acteur=session.utilisateur, identifiant=ident, modifications=modifications,
                                    revision_attendue=revision)
        except ValueError as exc:
            if isinstance(exc, RegistreErreur):
                return echec("fournisseurs", exc)
            return retour("fournisseurs", erreur="CHAMP_INVALIDE")
        return retour("fournisseurs", ok="configure")

    @router.post("/plateforme/fournisseurs/activer")
    async def form_activer(request: Request) -> Response:
        session, champs = await ecriture(request)
        ident = identifiant(champs)
        try:
            with cnx_factory() as cnx:
                decision = registre.activer(cnx, acteur=session.utilisateur, identifiant=ident)
        except RegistreErreur as exc:
            return echec("fournisseurs", exc)
        if not decision.conforme:
            return retour("fournisseurs", erreur="REFUS_POLITIQUE", refus=",".join(decision.codes))
        return retour("fournisseurs", ok="active")

    @router.post("/plateforme/fournisseurs/desactiver")
    async def form_desactiver(request: Request) -> Response:
        session, champs = await ecriture(request)
        try:
            with cnx_factory() as cnx:
                registre.desactiver(cnx, acteur=session.utilisateur, identifiant=identifiant(champs))
        except RegistreErreur as exc:
            return echec("fournisseurs", exc)
        return retour("fournisseurs", ok="desactive")

    @router.post("/plateforme/fournisseurs/tester")
    async def form_tester(request: Request) -> Response:
        session, champs = await ecriture(request)
        try:
            registre.tester(cnx_factory, acteur=session.utilisateur, identifiant=identifiant(champs), sonde=SONDE_HTTP)
        except RegistreErreur as exc:
            return echec("fournisseurs", exc)
        return retour("fournisseurs", ok="teste")

    @router.post("/plateforme/fournisseurs/selectionner")
    async def form_selectionner(request: Request) -> Response:
        session, champs = await ecriture(request)
        departement = champs.get("departement", "*")
        if departement != "*" and departement not in departements:
            return retour("fournisseurs", erreur="DEPARTEMENT_INVALIDE")
        try:
            with cnx_factory() as cnx:
                registre.selectionner(cnx, acteur=session.utilisateur, capacite=champs.get("capacite", ""),
                                      identifiant=identifiant(champs), departement=departement)
        except RegistreErreur as exc:
            return echec("fournisseurs", exc)
        return retour("fournisseurs", ok="selection")

    # -- secrets : écritures (la valeur ne quitte jamais cette requête en clair) ------------------
    @router.post("/plateforme/secrets/definir")
    async def form_definir(request: Request) -> Response:
        session, champs = await ecriture(request)
        try:
            coffre.avec_journal(cnx_factory, coffre.definir, acteur=session.utilisateur, nom=champs.get("nom", ""),
                                service=champs.get("service", ""), valeur=champs.get("valeur", ""))
        except CoffreErreur as exc:
            return echec("secrets", exc)
        finally:
            champs.pop("valeur", None)
        return retour("secrets", ok="secret_defini")

    @router.post("/plateforme/secrets/rotation")
    async def form_rotation(request: Request) -> Response:
        session, champs = await ecriture(request)
        try:
            coffre.avec_journal(cnx_factory, coffre.rotation, acteur=session.utilisateur, nom=champs.get("nom", ""),
                                valeur=champs.get("valeur", ""))
        except CoffreErreur as exc:
            return echec("secrets", exc)
        finally:
            champs.pop("valeur", None)
        return retour("secrets", ok="secret_tourne")

    @router.post("/plateforme/secrets/revoquer")
    async def form_revoquer(request: Request) -> Response:
        session, champs = await ecriture(request)
        if champs.get("confirme") != "oui":
            return retour("secrets", erreur="CONFIRMATION_REQUISE")
        try:
            coffre.avec_journal(cnx_factory, coffre.revoquer, acteur=session.utilisateur, nom=champs.get("nom", ""))
        except CoffreErreur as exc:
            return echec("secrets", exc)
        return retour("secrets", ok="secret_revoque")

    return router
