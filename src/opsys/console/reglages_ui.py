"""Console : « Réglages de direction » (CFG-1) — ce qui manque, ce que ça bloque, la proposition, et le geste
d'adoption N3.

L'écran lit l'état des réglages que les départements DÉCLARENT (bloc `reglages:` de leur manifeste,
`opsys.reglages.lecture`) et ne fabrique aucune valeur. Une proposition y est étiquetée « recommandation, non validée »
avec sa justification et sa source ; elle ne s'applique jamais d'elle-même : le champ est prérempli, le propriétaire
écrit une raison et adopte.

Le geste passe par le sas existant, comme `application_chantier` : la console dépose la demande N3 de l'outil
`m9_adopter_reglage` (ou `m9_revenir_sur_reglage`) puis la décide sous l'identité du propriétaire connecté
(`approbations.decider`, rôle `nathan_owner` relu en base, personne active) ; l'outil relit ensuite lui-même
l'approbateur. Un administrateur qui n'est pas le propriétaire voit l'écran mais ne peut ni adopter ni annuler.
Session serveur, jeton CSRF, champs fermés, aucune valeur choisie par le navigateur au-delà de celle qu'il soumet
(type et bornes viennent du manifeste).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .. import approbations, identite, stockage
from ..outils import Niveau
from ..reglages import lecture, magasin
from ..reglages.declaration import Reglage, ReglageRefuse, analyser_saisie, valider_valeur
from ..stockage.concurrence import verrou_ecriture_console
from ..stockage.portabilite import DIALECTES_QUALIFIES
from . import pages, securite
from .securite import Session

DEPARTEMENT_OUTILS = "m09-strategic-intelligence"
OUTIL_ADOPTER = "m9_adopter_reglage"
OUTIL_REVENIR = "m9_revenir_sur_reglage"
ROLE_PROPRIETAIRE = "nathan_owner"
ACTIONS = ("adopter", "revenir")
_ENTETES = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
_CODE_REJ = re.compile(r"REJ-[A-Z0-9-]+")
_CODES_HTTP = {
    "PROPRIETAIRE_REQUIS": 403, "SESSION_EXPIREE": 403, "REJ-HUMAIN-REQUIS": 403, "REJ-REGLAGE-INCONNU": 404,
    "REJ-REGLAGE-VERSION": 409, "REJ-REGLAGE-CONCURRENCE": 409, "REJ-REGLAGE-CHAINE-INVALIDE": 409,
    "REJ-REGLAGE-RIEN-A-ANNULER": 409, "REJ-REGLAGE-NIVEAU": 409, "BACKEND_NON_QUALIFIE": 503,
    "OUTIL_INDISPONIBLE": 503, "CONTEXTE_INVALIDE": 503,
}
_STATUTS = {
    "adopte": ("Adopté", "badge-ok"), "fichier": ("Valeur du fichier du département", "badge-ok"),
    "vide": ("À décider", "badge-alerte"), "fichier_invalide": ("Valeur du fichier invalide", "badge-danger"),
}
_MESSAGES_SUCCES = {
    "adopte": ("Valeur adoptée (N3) : les départements la lisent dès leur prochain appel.", "ok"),
    "deja_adopte": ("Cette valeur était déjà en vigueur : rien n'a été changé.", "ok"),
    "retour_arriere": ("Retour arrière fait : la valeur précédente (ou l'absence) est rétablie.", "ok"),
}
_CHAMPS_GESTE = {"action", "cle", "raison"}


class RefusReglage(Exception):
    """Refus typé du geste de la console ; `code` stable, `detail` lisible (aucun secret, aucune personne)."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code, self.detail = code, detail


def _date(iso: str | None) -> str:
    return pages._date(iso)


# ---------------------------------------------------------------------------------------------------------
# Le geste (testable sans HTTP)
# ---------------------------------------------------------------------------------------------------------
def _proprietaire(cnx: Any, session: Session) -> str:
    if type(session) is not Session:
        raise RefusReglage("SESSION_INVALIDE", "session console serveur requise")
    personne = identite.personne_active(cnx, session.utilisateur)
    if personne is None or session.expire <= datetime.now(UTC).timestamp():
        raise RefusReglage("SESSION_EXPIREE", "session échue ou personne inactive")
    if ROLE_PROPRIETAIRE not in personne.roles:
        raise RefusReglage("PROPRIETAIRE_REQUIS", "seul le propriétaire adopte ou annule un réglage de direction")
    return personne.identifiant


def _declaration(deps: Mapping[str, Any], cle: Any) -> Reglage:
    if type(cle) is str:
        for departement in deps.values():
            for reglage in departement.reglages:
                if reglage.cle == cle:
                    return reglage
    raise RefusReglage("REJ-REGLAGE-INCONNU", "aucun département ne déclare ce réglage")


def _code_du_refus(reponse: Mapping[str, Any]) -> tuple[str, str]:
    details = str(reponse.get("details") or reponse.get("erreur") or "refus")
    trouve = _CODE_REJ.search(details)
    return (trouve.group(0) if trouve else "REJ-REGLAGE-REFUSE"), details


def executer_geste(
    cnx: Any, deps: Mapping[str, Any], session: Session, action: Any, cle: Any, raison: Any, *,
    valeur: Any = None, saisie: Any = None, version_attendue: Any = None,
) -> dict[str, Any]:
    """Adopte ou annule UN réglage sous l'identité du propriétaire connecté, par le sas N3. Rend le résultat de l'outil.

    Ordre : transaction courante → propriétaire relu en base → déclaration → valeur validée contre le type et les bornes
    DU DÉPARTEMENT (avant de déposer quoi que ce soit : une faute de frappe ne laisse aucune demande) → demande N3
    déposée
    et décidée → l'outil écrit UN maillon chaîné. Idempotent pour une valeur déjà en vigueur."""
    if cnx is not stockage.connexion_courante() or cnx.dialect.name not in DIALECTES_QUALIFIES:
        raise RefusReglage("CONTEXTE_INVALIDE", "transaction courante d'une base qualifiée requise")
    if type(action) is not str or action not in ACTIONS:
        raise RefusReglage("ACTION_INCONNUE", "action : adopter ou revenir")
    proprietaire = _proprietaire(cnx, session)
    reglage = _declaration(deps, cle)
    arguments: dict[str, Any] = {"cle": reglage.cle, "raison": raison}
    if version_attendue is not None:
        arguments["version_attendue"] = version_attendue
    nom_outil = OUTIL_REVENIR
    if action == "adopter":
        nom_outil = OUTIL_ADOPTER
        try:
            brute = analyser_saisie(reglage, saisie) if saisie is not None else valeur
            arguments["valeur"] = valider_valeur(reglage, brute)
            magasin.valider_raison(raison)
        except ReglageRefuse as exc:
            raise RefusReglage(exc.code, exc.detail) from None
    else:
        try:
            magasin.valider_raison(raison)
        except ReglageRefuse as exc:
            raise RefusReglage(exc.code, exc.detail) from None
    departement = deps.get(DEPARTEMENT_OUTILS)
    outil = None if departement is None else next((o for o in departement.charger_outils() if o.nom == nom_outil), None)
    if outil is None:
        raise RefusReglage("OUTIL_INDISPONIBLE", "outil de réglage absent du département de direction")
    verrou_ecriture_console(cnx)
    ident = approbations.creer_demande(
        cnx, DEPARTEMENT_OUTILS, nom_outil, arguments, niveau=Niveau.N3,
        motif="Geste de la direction depuis l'écran « Réglages de direction » de la console.",
    )
    try:
        decision = approbations.decider(
            cnx, ident, True, proprietaire, {nom_outil: outil}, deps, role=ROLE_PROPRIETAIRE,
            motif="Décision du propriétaire depuis la console (réglage de direction).",
        )
    except ValueError:
        raise RefusReglage("PROPRIETAIRE_REQUIS", "le sas refuse cette décision au rôle propriétaire") from None
    reponse = decision.get("reponse", {})
    if decision.get("statut") != "executee" or not approbations.execution_reussie(reponse):
        code, detail = _code_du_refus(reponse)
        raise RefusReglage(code, detail)
    metier = reponse.get("resultat", {})
    if not isinstance(metier, Mapping) or metier.get("accepte") is not True:
        raise RefusReglage("REJ-REGLAGE-REFUSE", "réponse de l'outil illisible")
    return {**metier["resultat"], "approbation_id": ident}


# ---------------------------------------------------------------------------------------------------------
# Rendu
# ---------------------------------------------------------------------------------------------------------
def _texte_valeur(item: Mapping[str, Any]) -> str:
    if item["valeur"] is None:
        return "—"
    unite = f" {item['unite']}" if item.get("unite") else ""
    return f"{item['valeur_texte']}{unite}"


def _bornes_lisibles(item: Mapping[str, Any]) -> str:
    b = item["bornes"]
    morceaux = []
    if "min" in b:
        morceaux.append(f"de {b['min']} à {b['max']}")
    if "longueur" in b:
        morceaux.append(f"{b['longueur']} valeurs strictement croissantes")
    if "ordre" in b:
        sens = "inférieure" if b["ordre"] == "croissant" else "supérieure"
        morceaux.append(f"« pire » {sens} à « cible »")
    if "longueur_max" in b:
        morceaux.append(f"texte de 3 à {b['longueur_max']} caractères")
    return ", ".join(morceaux) or "—"


def _aide_saisie(item: Mapping[str, Any]) -> str:
    return {
        "entier": "un nombre entier", "decimal": "un nombre (virgule ou point)", "texte": "un texte",
        "liste_entiers_croissants": "des entiers séparés par des virgules, croissants",
        "bornes_pire_cible": "deux nombres séparés par un point-virgule : pire ; cible",
    }[item["type"]]


def _formulaires(item: Mapping[str, Any], prefixe: str, csrf: str, proprietaire: bool) -> str:
    e = pages.e
    if not proprietaire:
        return '<p class="note">Seul le propriétaire adopte ou annule un réglage de direction.</p>'
    cle = e(item["cle"])
    prerempli = item["valeur_texte"] if item["valeur"] is not None else (
        item["proposition"]["valeur_texte"] if item["proposition"] else "")
    champs_communs = (
        f'<input type="hidden" name="csrf" value="{e(csrf)}"><input type="hidden" name="cle" value="{cle}">'
        f'<input type="hidden" name="version_attendue" value="{e(item["version"])}">'
    )
    adopter = (
        f'<form method="post" action="{e(prefixe)}/reglages/geste" class="pile">{champs_communs}'
        '<input type="hidden" name="action" value="adopter">'
        f'<label>Valeur à adopter ({e(_aide_saisie(item))})'
        f' <input name="saisie" required maxlength="200" value="{e(prerempli)}"></label>'
        '<label>Raison (3 à 300 caractères, sans renseignement personnel)'
        ' <input name="raison" required minlength="3" maxlength="300"></label>'
        '<button type="submit" class="principal">Adopter (N3, propriétaire)</button></form>'
    )
    revenir = ""
    if item["statut"] == "adopte":
        revenir = (
            f'<form method="post" action="{e(prefixe)}/reglages/geste" class="pile">{champs_communs}'
            '<input type="hidden" name="action" value="revenir">'
            '<label>Raison du retour arrière <input name="raison" required minlength="3" maxlength="300"></label>'
            '<button type="submit">Revenir en arrière</button></form>'
        )
    return adopter + revenir


def _carte(item: Mapping[str, Any], prefixe: str, csrf: str, proprietaire: bool) -> str:
    e = pages.e
    libelle_statut, classe = _STATUTS[item["statut"]]
    meta = [
        ("Valeur en vigueur", _texte_valeur(item)),
        ("Bornes de saisie", _bornes_lisibles(item)),
        ("Ce que cela débloque", item["debloque"]),
        ("Approbation requise", f"{item['niveau']} (propriétaire)"),
    ]
    if item["statut"] == "adopte":
        meta.append(("Adopté", f"version {item['version']}, par {item['adopte_par']}, le {_date(item['adopte_le'])}"))
    if item["statut"] == "fichier_invalide":
        meta.append(("Valeur lue dans le fichier", item["valeur_fichier_illisible"]))
    details = "".join(f"<dt>{e(c)}</dt><dd>{e(v)}</dd>" for c, v in meta)
    proposition = '<p class="vide">Aucune valeur proposée : à décider par la direction.</p>'
    if item["proposition"] is not None:
        p = item["proposition"]
        proposition = (
            f'<div class="proposition"><h4>Valeur proposée {pages._badge(p["etiquette"], "badge-alerte")}</h4>'
            f'<p><strong>{e(p["valeur_texte"])}</strong> {e(item["unite"] or "")}</p>'
            f'<p>{e(p["justification"])}</p><p class="note">Source : {e(p["source"])}</p></div>'
        )
    return (
        f'<article class="carte" id="reglage-{e(item["cle"])}"><header class="carte-entete">'
        f'<h3>{e(item["libelle"])}</h3>{pages._badge(libelle_statut, classe)}</header>'
        f'<p class="note"><code>{e(item["cle"])}</code> · <code>{e(item["chemin"])}</code></p>'
        f'<dl class="meta">{details}</dl>{proposition}{_formulaires(item, prefixe, csrf, proprietaire)}</article>'
    )


def _valeur_lisible(valeur: Any) -> str:
    if valeur is None:
        return "aucune"
    if isinstance(valeur, dict):
        return " ; ".join(f"{cle} {v}" for cle, v in valeur.items())
    if isinstance(valeur, list):
        return ", ".join(str(v) for v in valeur)
    return str(valeur)


def _journal(entrees: list[dict[str, Any]]) -> str:
    e = pages.e
    if not entrees:
        return pages._vide("Aucun geste de la direction enregistré.")
    lignes = "".join(
        f'<tr><td>{e(_date(m["quand"]))}</td><td><code>{e(m["cle"])}</code></td>'
        f'<td>{e("Adoption" if m["type"] == magasin.TYPE_ADOPTION else "Retour arrière")}</td>'
        f'<td>{e(_valeur_lisible(m["ancienne_valeur"]))} → {e(_valeur_lisible(m["nouvelle_valeur"]))}</td>'
        f'<td>{e(m["version"])}</td>'
        f'<td>{e(m["par"])}</td><td>{e(m["raison"])}</td></tr>'
        for m in entrees
    )
    return (
        "<table><thead><tr><th>Quand</th><th>Réglage</th><th>Geste</th><th>Ancienne → nouvelle valeur</th>"
        f"<th>Version</th><th>Par</th><th>Raison</th></tr></thead><tbody>{lignes}</tbody></table>"
    )


def _page(vue: Mapping[str, Any], entrees: list[dict[str, Any]], deps: Mapping[str, Any], prefixe: str,
          session: Session, proprietaire: bool, bandeau: pages.Bandeau | None) -> str:
    e = pages.e
    par_departement: dict[str, list[Mapping[str, Any]]] = {}
    for item in vue["reglages"]:
        par_departement.setdefault(item["departement"], []).append(item)
    alerte_chaine = ""
    if not vue["chaine"]["valide"]:
        alerte_chaine = (
            '<p class="message message-erreur" role="alert">Le journal des valeurs adoptées ne se rejoue pas '
            f"({e(vue['chaine']['detail'])}) : AUCUNE valeur adoptée n'est servie aux départements tant qu'il est "
            "réparé ; aucun geste n'est accepté.</p>"
        )
    sections = []
    for ident, items in par_departement.items():
        dep = deps.get(ident)
        titre = f"{dep.code} — {dep.nom}" if dep is not None else ident
        cartes = "".join(_carte(i, prefixe, session.csrf, proprietaire) for i in items)
        sections.append(f"<section><h2>{e(titre)}</h2>{cartes}</section>")
    resume = (
        f"<p><strong>{vue['manquants']}</strong> réglage(s) à décider sur {vue['total']}. Tant qu'un réglage manque, "
        "la fonction qui en dépend reste inerte ou « indéterminée » : rien n'est deviné. Une valeur proposée est une "
        "<em>recommandation, non validée</em> : elle ne s'applique jamais d'elle-même, vous l'adoptez (ou la changez) "
        "avec une raison, et vous pouvez revenir en arrière en un geste.</p>"
        "<p class=\"note\">Précédence : valeur adoptée ici, puis valeur déjà écrite dans le fichier du département, "
        "puis absence. Les valeurs fiscales, tarifaires ou légales restent à valider auprès d'un comptable (CPA) / "
        "professionnel qualifié.</p>"
    )
    corps = (
        f"{alerte_chaine}{resume}{''.join(sections) or pages._vide('Aucun département ne déclare de réglage.')}"
        f"<h2>Journal des gestes</h2>{_journal(entrees)}"
    )
    return pages.gabarit("Réglages de direction", corps, prefixe=prefixe, session=session, actif="reglages",
                         bandeau=bandeau)


# ---------------------------------------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------------------------------------
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
    verifier_formulaire: Callable[[Mapping[str, str], Session], None] | None = None,
    **_autres: Any,
) -> APIRouter:
    router = APIRouter(tags=["réglages de direction"])

    def _vue(session: Session) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
        with cnx_factory() as cnx:
            vue = lecture.etat_des_reglages(deps)
            entrees = lecture.journal()
            personne = identite.personne_active(cnx, session.utilisateur)
        return vue, entrees, personne is not None and ROLE_PROPRIETAIRE in personne.roles

    def _geste(session: Session, donnees: Mapping[str, Any]) -> dict[str, Any]:
        autorises = _CHAMPS_GESTE | {"valeur", "saisie", "version_attendue"}
        if not set(donnees) <= autorises or not set(donnees) >= _CHAMPS_GESTE:
            raise HTTPException(400, "champs : action, cle, raison, valeur ou saisie, version_attendue")
        try:
            with cnx_factory() as cnx:
                return executer_geste(
                    cnx, deps, session, donnees["action"], donnees["cle"], donnees["raison"],
                    valeur=donnees.get("valeur"), saisie=donnees.get("saisie"),
                    version_attendue=donnees.get("version_attendue"),
                )
        except RefusReglage as exc:
            texte = f"{exc.code} : {exc.detail}" if exc.detail else exc.code
            raise HTTPException(_CODES_HTTP.get(exc.code, 400), texte) from None

    @router.get("/api/reglages")
    def lire(request: Request) -> JSONResponse:
        session = session_api(request)
        if request.query_params:
            raise HTTPException(400, "Paramètres invalides")
        vue, entrees, proprietaire = _vue(session)
        return JSONResponse({**vue, "journal": entrees, "peut_adopter": proprietaire}, headers=_ENTETES)

    @router.post("/api/reglages")
    async def appliquer_api(request: Request) -> JSONResponse:
        session = ecriture_api(request)
        if request.query_params:
            raise HTTPException(400, "Paramètres invalides")
        donnees = await objet_json(request)
        return JSONResponse({"resultat": _geste(session, donnees)}, headers=_ENTETES)

    @router.get("/reglages", response_class=HTMLResponse)
    def page(request: Request) -> HTMLResponse:
        session = session_page(request)
        autorises = {"ok"}
        if not set(request.query_params) <= autorises:
            raise HTTPException(400, "Paramètres invalides")
        vue, entrees, proprietaire = _vue(session)
        bandeau = _MESSAGES_SUCCES.get(request.query_params.get("ok", ""))
        reponse = HTMLResponse(_page(vue, entrees, deps, prefixe, session, proprietaire, bandeau))
        reponse.headers.update(_ENTETES)
        return reponse

    @router.post("/reglages/geste")
    async def geste_formulaire(request: Request) -> RedirectResponse:
        session = session_page(request)
        if request.query_params:
            raise HTTPException(400, "Paramètres invalides")
        champs = await formulaire(request)
        if verifier_formulaire is not None:
            verifier_formulaire(champs, session)
        elif not securite.csrf_valide(champs.get("csrf"), session):
            raise HTTPException(403, "Jeton CSRF absent ou invalide")
        attendus = {"csrf", "action", "cle", "raison", "version_attendue"}
        if not (attendus - {"version_attendue"}) <= set(champs) <= attendus | {"saisie"}:
            raise HTTPException(400, "Champs invalides")
        version = champs.get("version_attendue")
        if version is not None and not re.fullmatch(r"[0-9]{1,9}", version):
            raise HTTPException(400, "Champs invalides")
        donnees: dict[str, Any] = {k: champs[k] for k in ("action", "cle", "raison")}
        if "saisie" in champs:
            donnees["saisie"] = champs["saisie"]
        if version is not None:
            donnees["version_attendue"] = int(version)
        resultat = _geste(session, donnees)
        return RedirectResponse(f"{prefixe}/reglages?ok={resultat['statut']}#reglage-{resultat['cle']}",
                                status_code=303, headers={"Cache-Control": "no-store"})

    return router
