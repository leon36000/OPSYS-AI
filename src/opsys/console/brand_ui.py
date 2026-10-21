"""Console M7 de configuration du profil Brand Core courant.

La page ne lit et n'écrit que par les outils M7 canoniques. Elle ne prétend pas vérifier les
promesses du profil et n'expose pas directement les maillons internes du registre.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from .. import identite
from . import metier, pages, securite
from .securite import Session

_CHAMPS_PROFIL = {"name", "tagline", "tone", "colors", "langue"}
_LONGUEUR_TEXTE = 2000
_MAX_COULEURS = 32
_MAX_MUTATION_ID = 200
_OPTIONS_PROFIL = {"site_url", "garanties_validees", "heures_publication", "hashtags", "mentions"}
_HEURES = {"facebook", "instagram", "fiche_google", "video_courte", "demande_temoignage"}


def creer_router(
    *,
    session_page: Callable[..., Session],
    session_api: Callable[..., Session],
    ecriture_api: Callable[[Request], Session],
    formulaire: Callable[[Request], Any],
    objet_json: Callable[[Request], Any],
    cnx_factory: Callable[[], Any],
    deps: Mapping[str, Any],
    prefixe: str,
) -> APIRouter:
    """Routes Brand Core : lecture courante et configuration sous autorité M7 existante."""
    router = APIRouter(tags=["marketing Brand Core M7"])

    def appeler(session: Session, outil: str, arguments: Mapping[str, Any], mutation_id: str | None = None,
                *, revision_attendue: int | None = None):
        try:
            with cnx_factory() as cnx:
                if outil == "m7_configurer_profil_marque" and mutation_id is not None:
                    _exiger_proprietaire_cnx(cnx, session)
                    from m7_marketing.brand import registre

                    with registre.preserver_options_console(revision_attendue):
                        return metier.executer(cnx, deps, session, outil, arguments, mutation_id=mutation_id,
                                               preuve_commande={"revision_attendue": revision_attendue})
                return metier.executer(cnx, deps, session, outil, arguments, mutation_id=mutation_id)
        except PermissionError as exc:
            raise HTTPException(403, "accès métier refusé") from exc
        except KeyError as exc:
            raise HTTPException(404, "outil M7 indisponible") from exc
        except ValueError as exc:
            detail = str(exc).casefold()
            code = 403 if "aucun rôle autorisé" in detail else 409 if "conflit" in detail else 400
            raise HTTPException(code, "demande métier refusée") from exc

    def lire(session: Session) -> dict[str, Any]:
        reponse = appeler(session, "m7_lire_profil_marque_courant", {})
        ok, corps, erreur = _resultat(reponse)
        if not ok or not isinstance(corps, Mapping):
            raise HTTPException(409, erreur or "réponse Brand Core invalide")
        statut = corps.get("statut")
        if statut not in {"a_configurer", "configure"}:
            raise HTTPException(409, "état Brand Core inconnu")
        profil = corps.get("profil")
        if statut == "configure" and not _profil_affichable(profil):
            raise HTTPException(409, "profil Brand Core invalide")
        return dict(corps)

    def exiger_proprietaire(session: Session) -> None:
        with cnx_factory() as cnx:
            _exiger_proprietaire_cnx(cnx, session)

    def page(
        session: Session,
        *,
        message: str = "",
        erreur: str = "",
        status_code: int = 200,
        mutation_id: str | None = None,
    ) -> HTMLResponse:
        courant = lire(session)
        profil = courant.get("profil") if isinstance(courant.get("profil"), Mapping) else {}
        configure = courant.get("statut") == "configure"
        champs = []
        for cle, libelle in (
            ("name", "Nom de l’entreprise"),
            ("tagline", "Signature"),
            ("tone", "Ton rédactionnel"),
            ("langue", "Langue"),
        ):
            champs.append(
                f'<label>{pages.e(libelle)}<input name="{cle}" maxlength="{_LONGUEUR_TEXTE}" '
                f'value="{pages.e(profil.get(cle, ""))}" required></label>'
            )
        couleurs = profil.get("colors", []) if isinstance(profil.get("colors", []), list) else []
        champs.append(
            '<label>Couleurs (une valeur par ligne)<textarea name="colors" '
            f'maxlength="{_LONGUEUR_TEXTE}" required>{pages.e(chr(10).join(couleurs))}'
            "</textarea></label>"
        )
        champs.append('<label>Site public HTTPS<input name="site_url" maxlength="2000" '
                      f'value="{pages.e(profil.get("site_url", ""))}"></label>')
        for cle, libelle in (("garanties_validees", "Garanties déclarées"), ("hashtags", "Mots-clics"),
                             ("mentions", "Mentions déclarées")):
            valeurs = profil.get(cle, [])
            champs.append(f'<label>{pages.e(libelle)} (une par ligne)<textarea name="{cle}" maxlength="16032">'
                          f'{pages.e(chr(10).join(valeurs))}</textarea></label>')
        for code in sorted(_HEURES):
            heure = profil.get("heures_publication", {}).get(code, "")
            champs.append(f'<label>Heure suggérée · {pages.e(code)}<input name="heure_{code}" '
                          f'type="time" value="{pages.e(heure)}"></label>')
        sections = [
            f'<p><a href="{pages.e(prefixe)}/marketing">Retour au marketing</a></p>',
            '<p class="note">Le schéma vérifie les champs requis et leur type; il ne confirme pas la '
            "véracité du texte ni les services offerts.</p>",
        ]
        if message:
            sections.append(f'<p class="message message-ok" role="status">{pages.e(message)}</p>')
        if erreur:
            sections.append(f'<p class="message message-erreur" role="alert">{pages.e(erreur)}</p>')
        if configure:
            sections.extend(
                [
                    '<section class="carte"><h2>Profil courant</h2>',
                    f"<p>État : configuré · révision {pages.e(courant.get('revision', 'inconnue'))}</p>",
                    f"<p>Configuré par : {pages.e(courant.get('configure_par', 'inconnu'))}</p>",
                    "<dl>",
                ]
            )
            for cle, libelle in (
                ("name", "Nom"),
                ("tagline", "Signature"),
                ("tone", "Ton"),
                ("langue", "Langue"),
            ):
                sections.append(f"<dt>{pages.e(libelle)}</dt><dd>{pages.e(profil[cle])}</dd>")
            sections.append("<dt>Couleurs</dt><dd>" + ", ".join(pages.e(c) for c in profil["colors"]) + "</dd>")
            sections.append("</dl></section>")
        else:
            sections.append('<section class="carte"><h2>À configurer</h2><p>Aucun profil courant.</p></section>')
        if "nathan_owner" in session.roles:
            sections.extend(
                [
                    '<section class="carte"><h2>Configurer le profil</h2>',
                    "<p>Chaque enregistrement conserve une version de votre profil de marque.</p>",
                    f'<form method="post" action="{pages.e(prefixe)}/marketing/marque" class="pile">',
                    f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">',
                    f'<input type="hidden" name="mutation_id" value="{pages.e(mutation_id or uuid.uuid4().hex)}">',
                    f'<input type="hidden" name="revision_attendue" value="{pages.e(courant.get("revision") or 0)}">',
                    '<p class="note">Les options omises sont conservées depuis cette révision. '
                    'Les garanties et mentions sont déclarées, sans vérification externe.</p>',
                    *champs,
                    '<button type="submit">Enregistrer une révision</button></form></section>',
                ]
            )
        else:
            sections.append('<p class="note">L’enregistrement est réservé au propriétaire actif.</p>')
        sections.append(
            '<p class="note">Le lecteur courant fournit la révision et le signataire; '
            "les versions antérieures ne sont pas affichées ici.</p>"
        )
        return HTMLResponse(
            pages.gabarit("Profil de marque", "".join(sections), prefixe=prefixe, session=session, actif="marketing"),
            status_code=status_code,
        )

    @router.get("/marketing/marque", response_class=HTMLResponse)
    def page_marque(request: Request) -> Response:
        session = session_page(request)
        _query_fermee(request)
        return page(session)

    @router.get("/api/marketing/marque")
    def api_lire(request: Request) -> Response:
        session = session_api(request)
        _query_fermee(request)
        return JSONResponse({"ok": True, "resultat": lire(session)})

    @router.post("/marketing/marque", response_class=HTMLResponse)
    async def formulaire_marque(request: Request) -> Response:
        session = session_page(request)
        exiger_proprietaire(session)
        _query_fermee(request)
        champs = await formulaire(request)
        if not isinstance(champs, Mapping) or not securite.csrf_valide(champs.get("csrf"), session):
            raise HTTPException(403, "jeton CSRF absent ou invalide")
        try:
            profil, mutation_id = _formulaire_commande(champs)
            reponse = appeler(session, "m7_configurer_profil_marque", {"profil": profil}, mutation_id,
                             revision_attendue=_revision_attendue(champs.get("revision_attendue")))
            ok, valeur, erreur = _resultat(reponse)
            if ok and valeur.get("statut") != "configure":
                ok, erreur = False, str(valeur.get("motif") or "Profil non configuré.")
            if not ok:
                return page(session, erreur=erreur, status_code=409, mutation_id=mutation_id)
        except HTTPException:
            raise
        except (TypeError, ValueError) as exc:
            return page(session, erreur="Profil invalide : " + str(exc), status_code=400)
        return page(session, message="Nouvelle révision enregistrée.")

    @router.post("/api/marketing/marque")
    async def api_configurer(request: Request) -> Response:
        session = ecriture_api(request)
        exiger_proprietaire(session)
        _query_fermee(request)
        corps = await objet_json(request)
        try:
            profil, mutation_id = _json_commande(corps)
            reponse = appeler(session, "m7_configurer_profil_marque", {"profil": profil}, mutation_id,
                             revision_attendue=_revision_attendue(corps.get("revision_attendue")))
            ok, valeur, erreur = _resultat(reponse)
            if ok and valeur.get("statut") != "configure":
                ok, erreur = False, str(valeur.get("motif") or "Profil non configuré.")
            if not ok:
                return JSONResponse({"ok": False, "erreur": {"message": erreur}, "resultat": reponse}, status_code=409)
            return JSONResponse({"ok": True, "resultat": valeur})
        except HTTPException:
            raise
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, "profil de marque invalide") from exc

    return router


def _exiger_proprietaire_cnx(cnx: Any, session: Session) -> None:
    """Revalide le rôle dans la même transaction qui créera la demande et exécutera l'outil."""
    personne = identite.personne_active(cnx, session.utilisateur)
    if personne is None:
        raise HTTPException(401, "authentification requise")
    if "nathan_owner" not in personne.roles:
        raise HTTPException(403, "configuration réservée au propriétaire actif")


def _resultat(reponse: Any) -> tuple[bool, Any, str]:
    refus = _refus(reponse)
    if refus:
        return False, None, refus
    valeur = reponse
    while isinstance(valeur, Mapping) and "resultat" in valeur:
        valeur = valeur["resultat"]
    if not isinstance(valeur, Mapping):
        return False, None, "Réponse métier invalide."
    return True, valeur, ""


def _refus(valeur: Any) -> str | None:
    if not isinstance(valeur, Mapping):
        return "Réponse métier invalide."
    if valeur.get("ok") is False:
        return str(valeur.get("details") or valeur.get("erreur") or "Action refusée.")
    if valeur.get("accepte") is False:
        verdict = valeur.get("verdict")
        return str(verdict.get("detail", "Action refusée.")) if isinstance(verdict, Mapping) else "Action refusée."
    if valeur.get("statut") in {"echec", "refusee", "profil_invalide"}:
        return str(valeur.get("motif") or valeur.get("verdict") or "Le profil a été refusé.")
    for cle in ("resultat", "reponse"):
        if cle in valeur:
            refus = _refus(valeur[cle])
            if refus:
                return refus
    return None


def _profil_affichable(profil: Any) -> bool:
    if not isinstance(profil, Mapping) or not _CHAMPS_PROFIL.issubset(profil):
        return False
    if any(not isinstance(profil[cle], str) for cle in _CHAMPS_PROFIL - {"colors"}):
        return False
    couleurs = profil["colors"]
    return (
        bool(profil["name"].strip())
        and isinstance(couleurs, list)
        and bool(couleurs)
        and all(isinstance(couleur, str) for couleur in couleurs)
    )


def _valider_profil(profil: Any) -> dict[str, Any]:
    if not isinstance(profil, Mapping) or not _CHAMPS_PROFIL.issubset(profil) \
            or set(profil) - _CHAMPS_PROFIL - _OPTIONS_PROFIL:
        raise ValueError("champs attendus : name, tagline, tone, colors, langue")
    resultat: dict[str, Any] = {}
    for cle in _CHAMPS_PROFIL - {"colors"}:
        valeur = profil[cle]
        if not isinstance(valeur, str) or len(valeur) > _LONGUEUR_TEXTE:
            raise ValueError(f"{cle} doit être un texte de {_LONGUEUR_TEXTE} caractères au plus")
        resultat[cle] = valeur
    couleurs = profil["colors"]
    if (
        not isinstance(couleurs, list)
        or not couleurs
        or len(couleurs) > _MAX_COULEURS
        or any(not isinstance(couleur, str) or len(couleur) > 100 for couleur in couleurs)
    ):
        raise ValueError("colors doit contenir de 1 à 32 textes de 100 caractères au plus")
    resultat["colors"] = list(couleurs)
    for cle in _OPTIONS_PROFIL & set(profil):
        resultat[cle] = profil[cle]
    from m7_marketing.brand import registre

    try:
        registre.valider_profil(resultat)
    except (registre.brand_schema.ProfileError, OSError, TypeError, ValueError) as exc:
        raise ValueError("options de marque invalides") from exc
    return resultat


def _mutation_id(valeur: Any) -> str:
    if not isinstance(valeur, str) or not valeur.strip() or len(valeur) > _MAX_MUTATION_ID:
        raise ValueError("mutation_id requis (200 caractères au plus)")
    return valeur.strip()


def _formulaire_commande(champs: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    requis = {"csrf", "mutation_id", *_CHAMPS_PROFIL}
    allowed = {*requis, "revision_attendue", *_OPTIONS_PROFIL - {"heures_publication"},
               *("heure_" + code for code in _HEURES)}
    if not requis.issubset(champs) or set(champs) - allowed:
        raise ValueError("champs de formulaire inattendus ou manquants")
    profil = {cle: champs[cle] for cle in _CHAMPS_PROFIL - {"colors"}}
    if not isinstance(champs["colors"], str):
        raise ValueError("colors doit être un texte")
    profil["colors"] = [ligne.strip() for ligne in champs["colors"].splitlines() if ligne.strip()]
    for cle in _OPTIONS_PROFIL - {"heures_publication"}:
        if cle not in champs:
            continue
        valeur = champs[cle]
        if not isinstance(valeur, str) or len(valeur) > 16032:
            raise ValueError("option trop longue")
        if valeur.strip():
            profil[cle] = valeur.strip() if cle == "site_url" else [
                ligne.strip() for ligne in valeur.splitlines() if ligne.strip()
            ]
    heures = {}
    for code in _HEURES:
        heure = champs.get("heure_" + code, "")
        if not isinstance(heure, str) or len(heure) > 5:
            raise ValueError("heure invalide")
        if heure:
            heures[code] = heure
    if heures:
        profil["heures_publication"] = heures
    return _valider_profil(profil), _mutation_id(champs["mutation_id"])


def _json_commande(corps: Any) -> tuple[dict[str, Any], str]:
    if not isinstance(corps, Mapping) or not {"profil", "mutation_id"}.issubset(corps) \
            or set(corps) - {"profil", "mutation_id", "revision_attendue"}:
        raise ValueError("champs JSON inattendus ou manquants")
    return _valider_profil(corps["profil"]), _mutation_id(corps["mutation_id"])


def _revision_attendue(valeur: Any) -> int | None:
    if valeur is None:
        return None
    if isinstance(valeur, str) and valeur.isascii() and valeur.isdecimal() and len(valeur) <= 4:
        valeur = int(valeur)
    if type(valeur) is not int or not 0 <= valeur < 4096:
        raise ValueError("revision_attendue : entier borné requis")
    return valeur


def _query_fermee(request: Request) -> None:
    if request.query_params:
        raise HTTPException(400, "paramètres de lecture inattendus")
