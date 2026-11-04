"""Console « Seuils matériaux » (C7) : le seuil global, les seuils par catégorie et par matériau, et les deux planchers
(quantité et dollars) s'éditent par un administrateur, avec un audit chaîné de qui a changé quoi.

La page lit les seuils que M6 applique réellement (registre `seuils_variance_chantier`, sinon le seuil global hérité
du manifeste / de CFG-1) et écrit un maillon d'audit par décision. Elle ne calcule aucun seuil d'affaires : les
valeurs sont celles que la personne soumet, validées par le module M6 (`seuils_variance.valider_config`). Aucune
valeur par défaut n'est inventée : une configuration incomplète ou hors bornes est refusée, et un plancher absent
se déclare (`0`), il ne se devine pas.

Gardes : session obligatoire, rôle `admin` ou `nathan_owner` RELU EN BASE, CSRF, champs fermés, version attendue (pas de
mise à jour perdue), en-têtes `no-store`, contrôle de secret avant de servir, échappement HTML.

Routes : GET /seuils-materiaux (état + formulaire + journal) ; POST /seuils-materiaux (une décision).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from m6_material_control import seuils_variance

from opsys import identite, stockage
from opsys.secrets_coffre import masquage
from opsys.stockage.concurrence import verrou_ecriture_console

from . import pages
from .securite import Session

BASE = "/seuils-materiaux"
DEPARTEMENT = "m06-material-control"
ROLES_EDITEURS = frozenset({"admin", "nathan_owner"})
_ENTETES = {"Cache-Control": "no-store", "Pragma": "no-cache", "X-Content-Type-Options": "nosniff"}
_CHAMPS = {
    "csrf", "global_pourcentage", "plancher_quantite", "plancher_dollars", "par_categorie", "par_materiau",
    "categories", "raison", "version_attendue",
}
_PARAMETRES = {"ok"}
_MESSAGES = {
    "enregistre": ("Seuils enregistrés (N3, audit chaîné) : M6 les applique dès son prochain appel.", "ok"),
    "deja": ("Ces seuils étaient déjà en vigueur : rien n'a été réécrit.", "ok"),
}
_CODE_HTTP = {"REJ-SEUILS-VERSION": 409, "REJ-SEUILS-CHAINE": 409}
_MESSAGES_REFUS = {
    "REJ-SEUILS-CHAINE": (
        "REJ-SEUILS-CHAINE : chaîne d'audit invalide (retouchée ou illisible). Une chaîne retouchée ne sert plus "
        "aucune valeur et ne se répare pas depuis cet écran : un administrateur de base doit intervenir hors outil, "
        "avec une trace."
    ),
    "REJ-SEUILS-VERSION": (
        "REJ-SEUILS-VERSION : la version attendue ne correspond plus (un autre administrateur a écrit entre-temps). "
        "Recharger la page et recommencer."
    ),
}


def _journal_lisible(maillon: Any) -> bool:
    """Un maillon assez complet pour être AFFICHÉ : version entière positive et date texte (ou absente)."""
    if not isinstance(maillon, Mapping):
        return False
    version = maillon.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        return False
    return isinstance(maillon.get("horodatage"), (str, type(None)))


def _apres(maillon: Mapping[str, Any]) -> Mapping[str, Any]:
    """L'« après » d'un maillon, ou un objet vide : une valeur absente ou hostile s'affiche « — », sans crash."""
    apres = maillon.get("apres")
    return apres if isinstance(apres, Mapping) else {}


def _mappage(texte: str, quoi: str) -> dict[str, str]:
    """Un textarea « clé=valeur » : une ligne = une entrée. Vide = aucune entrée. Un doublon est refusé (jamais
    « la dernière gagne » silencieusement)."""
    if not isinstance(texte, str) or len(texte) > 20000:
        raise seuils_variance.SeuilsRefuses("REJ-SEUILS-STRUCTURE", f"{quoi} : textarea illisible")
    resultat: dict[str, str] = {}
    for brute in texte.splitlines():
        ligne = brute.strip()
        if not ligne:
            continue
        if ligne.count("=") != 1:
            raise seuils_variance.SeuilsRefuses("REJ-SEUILS-STRUCTURE", f"{quoi} : une ligne « clé=valeur » attendue")
        cle, valeur = (morceau.strip() for morceau in ligne.split("=", 1))
        if not cle or not valeur or cle in resultat:
            raise seuils_variance.SeuilsRefuses(
                "REJ-SEUILS-STRUCTURE", f"{quoi} : clé et valeur non vides, aucune clé répétée")
        resultat[cle] = valeur
    return resultat


def _config_du_formulaire(champs: Mapping[str, str]) -> dict[str, Any]:
    return seuils_variance.valider_config({
        "global_pourcentage": champs["global_pourcentage"],
        "plancher_quantite": champs["plancher_quantite"],
        "plancher_dollars": champs["plancher_dollars"],
        "par_categorie": _mappage(champs["par_categorie"], "par_categorie"),
        "par_materiau": _mappage(champs["par_materiau"], "par_materiau"),
        "categories": _mappage(champs["categories"], "categories"),
    })


def _version(texte: str) -> int:
    if not isinstance(texte, str) or not re.fullmatch(r"[0-9]{1,9}", texte):
        raise HTTPException(400, "version_attendue : entier attendu")
    return int(texte)


def _role(cnx: Any, session: Session) -> str:
    personne = identite.personne_active(cnx, session.utilisateur)
    if personne is None:
        raise HTTPException(403, "administration requise")
    roles = set(personne.roles)
    if "nathan_owner" in roles:
        return "nathan_owner"
    if "admin" in roles:
        return "admin"
    raise HTTPException(403, "administration requise")


def _etat() -> tuple[dict[str, Any] | None, float | None, list[Mapping[str, Any]]]:
    registre = list(stockage.maillons(DEPARTEMENT, seuils_variance.REGISTRE))
    config = seuils_variance.config_en_vigueur(registre) if registre else None
    heritage = None
    if config is None:
        from m6_material_control import outils as m6_outils

        heritage = m6_outils._seuil_variance_chantier()
    return config, heritage, registre


def _texte_decimal(valeur: Any) -> str:
    return "—" if valeur is None else str(valeur)


def _bandeau(config: Mapping[str, Any] | None, heritage: float | None, journal: list[Mapping[str, Any]]) -> str:
    if config is None:
        if journal:
            return pages._badge(
                "Chaîne d'audit invalide ou illisible : aucun seuil n'est appliqué (seuil absent). Une chaîne "
                "retouchée ne sert plus aucune valeur et cet écran ne peut pas la réparer : un administrateur de base "
                "doit intervenir hors outil, avec une trace.", "badge-danger")
        if heritage is None:
            return pages._badge("Aucun seuil global lisible : toute variance sort en « seuil absent »", "badge-danger")
        return pages._badge(
            "valeur initiale proposée par l'architecte, à confirmer — aucun seuil par catégorie/matériau ni plancher "
            "n'est déclaré", "badge-alerte")
    if config.get("role") == "nathan_owner":
        return pages._badge("Seuils confirmés par le propriétaire (audit ci-dessous)", "badge-ok")
    return pages._badge(
        "Seuils adoptés par un administrateur ; le propriétaire ne les a pas encore confirmés (audit ci-dessous)",
        "badge-alerte")


def _lignes_mappage(mappage: Mapping[str, Any]) -> str:
    return "\n".join(f"{cle}={valeur}" for cle, valeur in mappage.items())


def rendre(config: Mapping[str, Any] | None, heritage: float | None, journal: list[Mapping[str, Any]], prefixe: str,
           csrf: str, ok: str | None = None) -> str:
    version = int(config["version"]) if config is not None else 0
    global_pourcentage = config["global_pourcentage"] if config is not None else (
        "—" if heritage is None else str(heritage))
    plancher_quantite = config["plancher_quantite"] if config is not None else ""
    plancher_dollars = config["plancher_dollars"] if config is not None else ""
    par_categorie = _lignes_mappage(config["par_categorie"]) if config is not None else ""
    par_materiau = _lignes_mappage(config["par_materiau"]) if config is not None else ""
    categories = _lignes_mappage(config["categories"]) if config is not None else ""
    bandeau = ""
    if ok in _MESSAGES:
        texte, genre = _MESSAGES[ok]
        bandeau = f'<p class="badge {"badge-ok" if genre == "ok" else "badge-alerte"}">{pages.e(texte)}</p>'
    lisibles = [maillon for maillon in journal if _journal_lisible(maillon)]
    ignores = len(journal) - len(lisibles)
    if ignores:
        bandeau += (
            f'<p class="badge badge-danger">{ignores} entrée(s) du journal d\'audit illisible(s) ignorée(s) : un '
            "administrateur de base doit vérifier le registre (l'écran ne les répare pas).</p>"
        )
    journal_html = "".join(
        f"<tr><td>{maillon['version']}</td><td>{pages.e(pages._date(maillon.get('horodatage')))}</td>"
        f"<td>{pages.e(maillon.get('auteur'))}</td><td>{pages.e(maillon.get('role'))}</td>"
        f"<td>{pages.e(maillon.get('motif'))}</td>"
        f"<td>{pages.e(_texte_decimal(_apres(maillon).get('global_pourcentage')))}</td>"
        f"<td>{pages.e(_texte_decimal(_apres(maillon).get('plancher_quantite')))}</td>"
        f"<td>{pages.e(_texte_decimal(_apres(maillon).get('plancher_dollars')))}</td></tr>"
        for maillon in lisibles
    )
    tableau_journal = (
        '<div class="table-defilante"><table><caption>Journal d\'audit des seuils</caption><thead><tr>'
        '<th scope="col">Version</th><th scope="col">Quand</th><th scope="col">Auteur</th><th scope="col">Rôle</th>'
        '<th scope="col">Motif</th><th scope="col">Global</th><th scope="col">Plancher quantité</th>'
        '<th scope="col">Plancher dollars</th></tr></thead>'
        f"<tbody>{journal_html}</tbody></table></div>"
        if journal_html else "<p>Aucune décision enregistrée : le seuil global hérité du manifeste s'applique seul.</p>"
    )
    return (
        f"{bandeau}<p>{_bandeau(config, heritage, journal)}</p>"
        "<p>Un écart de matériaux est critique quand son pourcentage atteint le seuil du MATÉRIAU (sinon de SA "
        "catégorie déclarée, sinon le global) ET qu'il atteint les deux planchers. Les planchers se déclarent : "
        "« 0 » veut dire « aucun minimum ». Une valeur absente est refusée, jamais remplacée par un défaut.</p>"
        f'<form method="post" action="{pages.e(prefixe + BASE)}" class="pile">'
        f'<input type="hidden" name="csrf" value="{pages.e(csrf)}">'
        f'<input type="hidden" name="version_attendue" value="{version}">'
        '<p><label>Seuil global (fraction, 0.3 = 30 %)<br>'
        f'<input name="global_pourcentage" value="{pages.e(global_pourcentage)}" inputmode="decimal" '
        'required></label></p>'
        '<p><label>Plancher en quantité (unité du matériau)<br>'
        f'<input name="plancher_quantite" value="{pages.e(plancher_quantite)}" inputmode="decimal" '
        'required></label></p>'
        '<p><label>Plancher en dollars (CAD)<br>'
        f'<input name="plancher_dollars" value="{pages.e(plancher_dollars)}" inputmode="decimal" required></label></p>'
        '<p><label>Seuils par catégorie, une ligne « catégorie=seuil »<br>'
        f'<textarea name="par_categorie" rows="4">{pages.e(par_categorie)}</textarea></label></p>'
        '<p><label>Seuils par matériau, une ligne « matériau=seuil »<br>'
        f'<textarea name="par_materiau" rows="4">{pages.e(par_materiau)}</textarea></label></p>'
        '<p><label>Catégorie de chaque matériau, une ligne « matériau=catégorie »<br>'
        f'<textarea name="categories" rows="4">{pages.e(categories)}</textarea></label></p>'
        '<p><label>Motif de la décision (obligatoire, gardé à l\'audit)<br>'
        '<input name="raison" maxlength="500" required></label></p>'
        '<p><button type="submit">Enregistrer ces seuils</button></p></form>'
        "<h2>Journal d'audit</h2>"
        f"{tableau_journal}"
    )


def creer_router(
    *,
    session_page: Callable[..., Session],
    cnx_factory: Callable[[], Any],
    deps: Mapping[str, Any],
    prefixe: str,
    verifier_formulaire: Callable[[Mapping[str, str], Session], None],
) -> APIRouter:
    router = APIRouter(tags=["seuils matériaux"])

    def servir(session: Session, contenu: str) -> HTMLResponse:
        html = pages.gabarit("Seuils matériaux", contenu, prefixe=prefixe, session=session, actif="seuils-materiaux")
        if masquage.contient_secret(html):
            raise HTTPException(500, "rendu refusé : contenu sensible détecté")
        return HTMLResponse(html, headers=_ENTETES)

    @router.get(BASE, response_class=HTMLResponse)
    def page(request: Request) -> HTMLResponse:
        session = session_page(request)
        if not set(request.query_params) <= _PARAMETRES:
            raise HTTPException(400, "Paramètres invalides")
        with cnx_factory() as cnx:
            _role(cnx, session)
            config, heritage, journal = _etat()
        return servir(session, rendre(
            config, heritage, journal, prefixe, session.csrf, request.query_params.get("ok")))

    @router.post(BASE)
    async def enregistrer(request: Request) -> RedirectResponse:
        session = session_page(request)
        if request.query_params:
            raise HTTPException(400, "Paramètres invalides")
        champs = await request.form()
        champs = {cle: valeur for cle, valeur in champs.items() if isinstance(valeur, str)}
        if set(champs) != _CHAMPS:
            raise HTTPException(400, "Champs invalides")
        verifier_formulaire(champs, session)
        version = _version(champs["version_attendue"])
        try:
            config = _config_du_formulaire(champs)
        except seuils_variance.SeuilsRefuses as refus:
            raise HTTPException(400, f"{refus.code} : {refus.detail}") from None
        with cnx_factory() as cnx:
            role = _role(cnx, session)
            personne = identite.personne_active(cnx, session.utilisateur)
            verrou_ecriture_console(cnx)
            resultat, code = seuils_variance.enregistrer(
                config, auteur=personne.identifiant, role=role, motif=champs["raison"].strip(),
                horodatage=datetime.now(UTC).isoformat(timespec="microseconds"),
                registre_cible=stockage.maillons(DEPARTEMENT, seuils_variance.REGISTRE),
                version_attendue=version,
            )
            apres = identite.personne_active(cnx, session.utilisateur)
            if apres is None or role not in apres.roles:
                raise HTTPException(403, "administration retirée avant la fin du geste")
        if code is not None:
            raise HTTPException(_CODE_HTTP.get(code, 400), _MESSAGES_REFUS.get(code, code))
        ok = "deja" if resultat.get("deja_en_vigueur") is True else "enregistre"
        return RedirectResponse(f"{prefixe}{BASE}?ok={ok}", status_code=303, headers={"Cache-Control": "no-store"})

    return router
