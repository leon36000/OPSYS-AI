"""Aperçu admin, strictement en lecture seule, des faits candidats M03 de M10."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from collections.abc import Callable, Collection
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from m10_memoire import apprentissage, registre
from sqlalchemy import select, text

from opsys import stockage
from opsys.stockage import codec
from opsys.stockage.schema import REGISTRES

from . import pages
from .securite import Session

MAX_MAILLONS = apprentissage.MAX_MAILLONS
MAX_OCTETS_TOTAL = 8 * 1024 * 1024
MAX_OCTETS_LIGNE = 64 * 1024
MAX_PROFONDEUR_JSON = 64
MAX_REFERENCES_PAR_GROUPE = 20
MAX_REPONSE_OCTETS = 128 * 1024
_REGISTRES = ("affaires", "evenements")


class BackendNonPrisEnCharge(RuntimeError):
    """La cohérence de ce parcours n'est qualifiée que sur SQLite."""


def _verifier_profondeur(texte: str) -> None:
    profondeur = 0
    chaine = False
    echappe = False
    for caractere in texte:
        if chaine:
            if echappe:
                echappe = False
            elif caractere == "\\":
                echappe = True
            elif caractere == '"':
                chaine = False
            continue
        if caractere == '"':
            chaine = True
        elif caractere in "[{":
            profondeur += 1
            if profondeur > MAX_PROFONDEUR_JSON:
                raise ValueError("profondeur JSON dépassée")
        elif caractere in "]}":
            profondeur -= 1
            if profondeur < 0:
                raise ValueError("JSON mal formé")
    if chaine or echappe or profondeur != 0:
        raise ValueError("JSON mal formé")


def _valider_json_borne(texte: str) -> Any:
    _verifier_profondeur(texte)

    def objet(paires: list[tuple[str, Any]]) -> dict[str, Any]:
        resultat: dict[str, Any] = {}
        for cle, valeur in paires:
            if cle in resultat:
                raise ValueError("clé JSON dupliquée")
            resultat[cle] = valeur
        return resultat

    def flottant(valeur: str) -> float:
        resultat = float(valeur)
        if not math.isfinite(resultat):
            raise ValueError("nombre JSON non fini")
        return resultat

    def constante(_valeur: str) -> None:
        raise ValueError("constante JSON non standard")

    return json.loads(texte, object_pairs_hook=objet, parse_float=flottant, parse_constant=constante)


def _backend_sqlite() -> None:
    if stockage.moteur().dialect.name != "sqlite":
        raise BackendNonPrisEnCharge("aperçu M10 : backend SQLite uniquement, concurrence PostgreSQL non qualifiée")


def _exiger_plafonds(compte: int, octets: int, maximum: int) -> None:
    if compte > MAX_MAILLONS or octets > MAX_OCTETS_TOTAL or maximum > MAX_OCTETS_LIGNE:
        raise HTTPException(413, "historique M10 hors plafond de lecture; aperçu refusé")


def _lire_snapshot() -> tuple[list[dict[str, Any]], dict[str, str | None]]:
    """Préflight SQL avant tout décodage/deepcopy; lit les deux registres dans un snapshot SQLite borné."""
    _backend_sqlite()
    noms = list(_REGISTRES)
    with stockage.transaction() as cnx:
        compte, octets, maximum = cnx.execute(text(
            "SELECT count(*), COALESCE(sum(length(CAST(maillon AS BLOB))),0), "
            "COALESCE(max(length(CAST(maillon AS BLOB))),0) FROM registres_maillons "
            "WHERE departement=:departement AND registre IN (:r0,:r1)"
        ), {"departement": "m10-memoire", "r0": noms[0], "r1": noms[1]}).one()
        _exiger_plafonds(compte, octets, maximum)
        lignes = cnx.execute(
            select_maillons_m10(), {"departement": "m10-memoire", "r0": noms[0], "r1": noms[1]}
        ).all()
        if len(lignes) != compte:
            raise HTTPException(409, "photo M10 modifiée pendant la lecture; rechargez")
        par_registre: dict[str, list[dict[str, Any]]] = defaultdict(list)
        octets_lus = 0
        for ligne in lignes:
            texte_maillon = ligne.maillon
            if not isinstance(texte_maillon, str):
                raise HTTPException(409, "maillon M10 invalide; aperçu refusé")
            try:
                brut = texte_maillon.encode("utf-8")
            except UnicodeError as exc:
                raise HTTPException(409, "maillon M10 non UTF-8; aperçu refusé") from exc
            octets_lus += len(brut)
            if len(brut) > MAX_OCTETS_LIGNE or octets_lus > MAX_OCTETS_TOTAL:
                raise HTTPException(413, "historique M10 hors plafond de lecture; aperçu refusé")
            try:
                json_maillon = _valider_json_borne(texte_maillon)
                if not isinstance(json_maillon, dict):
                    raise ValueError("objet JSON M10 requis")
                maillon = codec.decoder(texte_maillon)
            except (ValueError, TypeError, RecursionError) as exc:
                raise HTTPException(409, "maillon M10 mal formé; aperçu refusé") from exc
            if not isinstance(maillon, dict) or ligne.registre not in _REGISTRES:
                raise HTTPException(409, "maillon M10 invalide; aperçu refusé")
            par_registre[ligne.registre].append((ligne.rang, maillon))
        if octets_lus != octets:
            raise HTTPException(409, "photo M10 incohérente; rechargez")

        têtes: dict[str, str | None] = {}
        copies: dict[str, list[dict[str, Any]]] = {}
        for nom in noms:
            rang_maillons = par_registre[nom]
            if any(rang != index for index, (rang, _) in enumerate(rang_maillons)):
                raise HTTPException(409, "rang du registre M10 invalide; aperçu refusé")
            copie = [maillon for _, maillon in rang_maillons]
            journal = registre.Registre(maillons=copie)
            try:
                valide, _ = journal.valider_chaine()
            except (KeyError, TypeError, ValueError, RecursionError) as exc:
                raise HTTPException(409, "chaîne M10 mal formée; aperçu refusé") from exc
            if not valide:
                raise HTTPException(409, "chaîne M10 invalide; aperçu refusé")
            copies[nom] = copie
            têtes[nom] = journal.tete()
        return copies["affaires"], têtes


def select_maillons_m10():
    """Retourne les colonnes minimales; séparé pour que le SQL reste facilement inspectable."""
    return (
        select(REGISTRES.c.registre, REGISTRES.c.rang, REGISTRES.c.maillon)
        .where(REGISTRES.c.departement == "m10-memoire")
        .where(REGISTRES.c.registre.in_(_REGISTRES))
        .order_by(REGISTRES.c.registre, REGISTRES.c.rang)
    )


def _lire_tetes() -> dict[str, str | None]:
    _backend_sqlite()
    têtes: dict[str, str | None] = {}
    with stockage.transaction() as cnx:
        for nom in _REGISTRES:
            taille = cnx.execute(
                text("SELECT length(CAST(maillon AS BLOB)) FROM registres_maillons "
                     "WHERE departement=:departement AND registre=:registre "
                     "ORDER BY rang DESC LIMIT 1"),
                {"departement": "m10-memoire", "registre": nom},
            ).scalar_one_or_none()
            if taille is None:
                têtes[nom] = None
                continue
            if taille > MAX_OCTETS_LIGNE:
                raise HTTPException(409, "tête M10 hors plafond; aperçu refusé")
            ligne = cnx.execute(
                select(REGISTRES.c.maillon)
                .where(REGISTRES.c.departement == "m10-memoire", REGISTRES.c.registre == nom)
                .order_by(REGISTRES.c.rang.desc()).limit(1)
            ).first()
            if ligne is None:
                raise HTTPException(409, "tête M10 changée pendant la relecture; aperçu refusé")
            texte_maillon = ligne.maillon
            if not isinstance(texte_maillon, str):
                raise HTTPException(409, "tête M10 invalide; aperçu refusé")
            try:
                octets_payload = len(texte_maillon.encode("utf-8"))
                if octets_payload > MAX_OCTETS_LIGNE or octets_payload != taille:
                    raise HTTPException(409, "tête M10 hors plafond; aperçu refusé")
                json_maillon = _valider_json_borne(texte_maillon)
                if not isinstance(json_maillon, dict):
                    raise ValueError("objet JSON M10 requis")
                maillon = codec.decoder(texte_maillon)
            except (ValueError, TypeError, RecursionError, UnicodeError) as exc:
                raise HTTPException(409, "tête M10 mal formée; aperçu refusé") from exc
            if not isinstance(maillon, dict) or not isinstance(maillon.get("ligne_id"), str):
                raise HTTPException(409, "tête M10 invalide; aperçu refusé")
            têtes[nom] = maillon["ligne_id"]
    return têtes


def _contenu(rapport: dict[str, Any], prefixe: str) -> str:
    propositions = rapport["propositions"]
    if not propositions:
        tableau = '<p>Aucun groupe n’atteint le seuil de tri dans cette fenêtre.</p>'
    else:
        lignes = []
        for item in propositions:
            sources = item["sources_ligne_id"]
            refs = " ".join(
                f"<code>{pages.e(ref)}</code>" for ref in sources[:MAX_REFERENCES_PAR_GROUPE]
            )
            references_omises = len(sources) - min(len(sources), MAX_REFERENCES_PAR_GROUPE)
            if references_omises:
                refs += f" <span>+{references_omises} références omises</span>"
            lignes.append(
                "<tr>"
                f"<td>{pages.e(item['outil'])}</td><td>{pages.e(item['resultat'])}</td>"
                f"<td>{pages.e(item['code'])}</td><td>{item['affaires_distinctes']}</td>"
                f"<td>{item['observations']}</td><td>{pages.e(item['premiere_observation_utc'])} – "
                f"{pages.e(item['derniere_observation_utc'])}</td><td>{refs}</td></tr>"
            )
        tableau = (
            '<div class="table-scroll"><table><thead><tr><th>Outil</th><th>Résultat</th><th>Code</th>'
            '<th>Affaires distinctes</th><th>Observations</th><th>Dates UTC</th><th>Sources M10</th>'
            f"</tr></thead><tbody>{''.join(lignes)}</tbody></table></div>"
        )
    return (
        '<section><h2>Aperçu statistique des faits candidats M03</h2>'
        '<p>Tri humain seulement : ces répétitions ne prouvent ni cause ni efficacité. Aucun fait n’est '
        'ajouté au contexte des agents.</p>'
        f"<p>Cutoff UTC : {pages.e(rapport['cutoff_utc'])}; fenêtre : 365 jours; seuil : 3 affaires; "
        f"rapport SHA-256 : <code>{pages.e(rapport['rapport_sha256'])}</code>.</p>"
        f"<p>Groupes omis au plafond : {rapport['propositions_omises']}.</p>{tableau}"
        f"<p>Maillons omis : outils hors catalogue {rapport['maillons_outil_hors_catalogue_omis']}; "
        f"codes hors catalogue {rapport['maillons_code_hors_catalogue_omis']}.</p>"
        f'<p><a href="{pages.e(prefixe)}/memoire/procedures">Ouvrir le parcours humain des procédures M03</a></p>'
        '</section>'
    )


def creer_router(
    *,
    session_page: Callable[[Request], Session],
    revalider_administration: Callable[[Session], None],
    prefixe: str,
    outils_m03: Collection[str],
    codes_m3: Collection[str],
) -> APIRouter:
    router = APIRouter()

    @router.get("/memoire/apprentissages-affaires", response_class=HTMLResponse)
    def apprentissages_affaires(request: Request) -> HTMLResponse:
        session = session_page(request)
        if not outils_m03 or not codes_m3:
            raise HTTPException(503, "catalogue M03 indisponible; aperçu refusé")
        try:
            affaires, têtes = _lire_snapshot()
            rapport = apprentissage.analyser_candidats(
                affaires,
                cutoff_utc=datetime.now(UTC),
                tete_affaires=têtes["affaires"],
                tete_evenements=têtes["evenements"],
                outils_m03=outils_m03,
                codes_m3=codes_m3,
            )
        except BackendNonPrisEnCharge as exc:
            raise HTTPException(503, str(exc)) from exc
        except apprentissage.ApercuRefuse as exc:
            raise HTTPException(409, "faits candidats M03 invalides; aperçu refusé") from exc
        from .pages import gabarit

        page = gabarit(
            "Aperçu des faits candidats M03",
            _contenu(rapport, prefixe), prefixe=prefixe, session=session,
            actif="memoire", en_attente=0,
        )
        if len(page.encode("utf-8")) > MAX_REPONSE_OCTETS:
            raise HTTPException(413, "aperçu hors plafond de réponse; rechargez avec un historique plus court")
        if _lire_tetes() != têtes:
            raise HTTPException(409, "l’historique M10 a changé; rechargez l’aperçu")
        revalider_administration(session)
        return HTMLResponse(page, headers={"Cache-Control": "no-store"})

    return router
