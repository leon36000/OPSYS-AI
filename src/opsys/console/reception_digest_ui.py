"""Résumé privé, borné et sans effet du registre anti-perte M1."""

from __future__ import annotations

import importlib
import re
import time
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from .. import identite, stockage
from ..stockage import lecture_m1
from ..stockage.maillons import MaillonsDurables
from . import metier, pages
from .securite import Session

_DEPARTEMENT = "m01-front-office"
_REGISTRE = "principal"
_MAX_LIGNES = lecture_m1.MAX_LIGNES
_MAX_MAILLON_OCTETS = lecture_m1.MAX_MAILLON_OCTETS
_MAX_TOTAL_OCTETS = lecture_m1.MAX_TOTAL_OCTETS
_MAX_DIGEST_OCTETS = 32_768
_CANAUX = {
    "telephone": "Téléphone",
    "courriel": "Courriel",
    "formulaire": "Formulaire",
    "texte": "Messages",
}
_TYPES = {
    "signal": "Événements reçus",
    "transition_phase": "Transitions",
    "lead_emis": "Leads transmis",
    "chiffrage_emis": "Demandes d’estimation",
    "alerte": "Alertes",
}
_NOMBRE = r"(0|[1-9][0-9]{0,4})"
_LIGNE_GRILLE = re.compile(rf"- ([a-z_]+): ([a-z_]+): {_NOMBRE}\Z", re.ASCII)
_LIGNES_OPTIONNELLES = {
    "- conversations ouvertes à suivre": re.compile(rf"- conversations ouvertes à suivre : {_NOMBRE}\Z", re.ASCII),
    "- conversations sans suivi à l'échéance de leur fenêtre": re.compile(
        rf"- conversations sans suivi à l'échéance de leur fenêtre : {_NOMBRE}\Z", re.ASCII
    ),
    "- transferts à un humain ouverts": re.compile(rf"- transferts à un humain ouverts : {_NOMBRE}\Z", re.ASCII),
    "- dont urgences de sécurité": re.compile(
        rf"- dont urgences de sécurité : {_NOMBRE}, plaintes : {_NOMBRE}\Z", re.ASCII
    ),
}


def _preflight(cnx: Any) -> int:
    """Borne l'unique source SQLite avant le premier décodage du registre."""
    return lecture_m1.borner(
        cnx, max_lignes=_MAX_LIGNES, max_maillon_octets=_MAX_MAILLON_OCTETS,
        max_total_octets=_MAX_TOTAL_OCTETS,
    )


def creer_router(
    *,
    session_page: Callable[..., Session],
    session_api: Callable[..., Session],
    cnx_factory: Callable[[], Any],
    deps: Mapping[str, Any],
    prefixe: str,
) -> APIRouter:
    router = APIRouter()

    def _autoriser(cnx: Any, session: Session) -> None:
        if session.expire <= int(time.time()):
            raise HTTPException(401, "authentification requise")
        personne = identite.personne_active(cnx, session.utilisateur)
        if personne is None:
            raise HTTPException(401, "authentification requise")
        if not personne.roles.intersection({"nathan_owner", "admin"}):
            raise HTTPException(403, "accès refusé")

    def _date_reference(request: Request) -> str:
        brut = request.scope.get("query_string", b"")
        if not isinstance(brut, bytes) or len(brut) > 256:
            raise HTTPException(400, "requête invalide")
        try:
            texte = brut.decode("ascii")
            if not texte:
                return datetime.now(UTC).date().isoformat()
            elements = texte.split("&")
            if len(elements) != 1 or not elements[0].startswith("date_reference="):
                raise ValueError
            valeur = elements[0][len("date_reference=") :]
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", valeur, re.ASCII):
                raise ValueError
            if date.fromisoformat(valeur).isoformat() != valeur:
                raise ValueError
            return valeur
        except (UnicodeDecodeError, ValueError):
            raise HTTPException(400, "requête invalide") from None

    def _valider_digest(texte: Any, date_reference: str, *, nombre_maillons: int) -> dict[str, Any]:
        if not isinstance(texte, str):
            raise ValueError("réponse invalide")
        brut = texte.encode("utf-8", errors="strict")
        if len(brut) > _MAX_DIGEST_OCTETS or "\r" in texte or "\x00" in texte:
            raise ValueError("réponse invalide")
        lignes = texte.split("\n")
        vide = f"Absence d'activité enregistrée pour la période de référence {date_reference}."
        if lignes == [vide]:
            if nombre_maillons != 0:
                raise ValueError("réponse invalide")
            return {
                "grille": [],
                "suivi": [],
                "transferts": [],
                "appels": {},
                "non_classes": 0,
                "registre_non_vide": False,
            }
        if nombre_maillons == 0:
            raise ValueError("réponse invalide")
        if not lignes or lignes[0] != f"DIGEST - Période de référence : {date_reference}":
            raise ValueError("réponse invalide")
        compteurs: dict[tuple[str, str], int] = {}
        suivi: list[dict[str, Any]] = []
        transferts: dict[str, int] = {}
        appels: dict[str, int] = {}
        non_classes: int | None = None
        option_seen: set[str] = set()
        phase = "grille"
        grille_lignes = lignes[1:21]
        if len(grille_lignes) != 20:
            raise ValueError("réponse invalide")
        expected = [
            (c, t)
            for c in ("telephone", "courriel", "formulaire", "texte")
            for t in ("signal", "transition_phase", "lead_emis", "chiffrage_emis", "alerte")
        ]
        for ligne, paire in zip(grille_lignes, expected, strict=True):
            match = _LIGNE_GRILLE.fullmatch(ligne)
            if match is None or (match.group(1), match.group(2)) != paire:
                raise ValueError("réponse invalide")
            compteurs[paire] = int(match.group(3))
            if compteurs[paire] > _MAX_LIGNES:
                raise ValueError("réponse invalide")
        for ligne in lignes[21:]:
            match = re.fullmatch(rf"- entrées non classées : {_NOMBRE}", ligne, re.ASCII)
            if match is not None:
                if non_classes is not None:
                    raise ValueError("réponse invalide")
                non_classes = int(match.group(1))
                if non_classes > _MAX_LIGNES:
                    raise ValueError("réponse invalide")
                phase = "termine"
                continue
            if phase == "termine":
                raise ValueError("réponse invalide")
            if ligne.startswith("- appels importés : "):
                if appels or phase not in {"grille", "suivi", "transferts"}:
                    raise ValueError("réponse invalide")
                contenu = ligne.removeprefix("- appels importés : ")
                if not contenu:
                    raise ValueError("réponse invalide")
                for partie in contenu.split(", "):
                    if ": " not in partie:
                        raise ValueError("réponse invalide")
                    statut, nombre = partie.split(": ", 1)
                    if (
                        statut not in {"manque", "voicemail", "inconnu"}
                        or statut in appels
                        or not re.fullmatch(_NOMBRE, nombre, re.ASCII)
                    ):
                        raise ValueError("réponse invalide")
                    appels[statut] = int(nombre)
                    if appels[statut] > _MAX_LIGNES:
                        raise ValueError("réponse invalide")
                if list(appels) != sorted(appels):
                    raise ValueError("réponse invalide")
                phase = "appels"
                continue
            reconnu = False
            for cle, motif in _LIGNES_OPTIONNELLES.items():
                if ligne.startswith(cle + " :"):
                    if cle in option_seen or phase == "appels":
                        raise ValueError("réponse invalide")
                    if cle.startswith("- conversations") and phase == "transferts":
                        raise ValueError("réponse invalide")
                    if (
                        cle == "- conversations sans suivi à l'échéance de leur fenêtre"
                        and "- conversations ouvertes à suivre" not in option_seen
                    ):
                        raise ValueError("réponse invalide")
                    if cle == "- dont urgences de sécurité" and "- transferts à un humain ouverts" not in option_seen:
                        raise ValueError("réponse invalide")
                    m = motif.fullmatch(ligne)
                    if m is None:
                        raise ValueError("réponse invalide")
                    option_seen.add(cle)
                    valeurs = [int(x) for x in m.groups()]
                    if any(value > _MAX_LIGNES for value in valeurs):
                        raise ValueError("réponse invalide")
                    if cle.startswith("- conversations"):
                        suivi.append({"label": cle[2:].capitalize(), "nombre": valeurs[0]})
                        phase = "suivi"
                    else:
                        transferts[cle[2:].capitalize()] = valeurs[0]
                        if len(valeurs) == 2:
                            transferts["Plaintes"] = valeurs[1]
                        phase = "transferts"
                    reconnu = True
                    break
            if reconnu:
                continue
            raise ValueError("réponse invalide")
        if non_classes is None:
            raise ValueError("réponse invalide")
        if (
            option_seen
            & {
                "- conversations ouvertes à suivre",
                "- conversations sans suivi à l'échéance de leur fenêtre",
            }
        ) not in (
            set(),
            {
                "- conversations ouvertes à suivre",
                "- conversations sans suivi à l'échéance de leur fenêtre",
            },
        ):
            raise ValueError("réponse invalide")
        if (option_seen & {"- transferts à un humain ouverts", "- dont urgences de sécurité"}) not in (
            set(),
            {"- transferts à un humain ouverts", "- dont urgences de sécurité"},
        ):
            raise ValueError("réponse invalide")
        grille = [
            {"canal": _CANAUX[canal], "type": _TYPES[type_], "nombre": compteurs[(canal, type_)]}
            for canal, type_ in expected
        ]
        return {
            "grille": grille,
            "suivi": suivi,
            "transferts": transferts,
            "appels": appels,
            "non_classes": non_classes,
            "registre_non_vide": True,
        }

    def _lire(session: Session, date_reference: str) -> tuple[str, dict[str, Any], str]:
        with cnx_factory() as cnx:
            _autoriser(cnx, session)
            if stockage.connexion_courante() is not cnx:
                raise RuntimeError("connexion source divergente")
            departement = deps.get(_DEPARTEMENT)
            if departement is None or departement.module_outils != "m1_front_office.outils":
                raise RuntimeError("source indisponible")
            outils = importlib.import_module(departement.module_outils)
            registre = getattr(outils, "_registre", None)
            maillons = getattr(registre, "_entrees", None)
            if (
                getattr(outils, "_stockage_durable_actif", False) is not True
                or not isinstance(maillons, MaillonsDurables)
                or maillons.departement != _DEPARTEMENT
                or maillons.registre != _REGISTRE
            ):
                raise RuntimeError("source non durable")
            nombre_maillons = _preflight(cnx)
            reponse = metier.executer(cnx, deps, session, "m1_produire_digest", {"date_reference": date_reference})
            _autoriser(cnx, session)
            if not isinstance(reponse, Mapping) or set(reponse) != {"ok", "resultat"} or reponse.get("ok") is not True:
                raise RuntimeError("réponse indisponible")
            digest = _valider_digest(reponse.get("resultat"), date_reference, nombre_maillons=nombre_maillons)
            return date_reference, digest, datetime.now(UTC).isoformat(timespec="seconds")

    def _contenu(digest: Mapping[str, Any]) -> str:
        pieces = [
            '<section class="carte"><h2>Événements enregistrés</h2>',
            "<p>Ces nombres comptent des événements enregistrés, pas des clients uniques.</p>",
        ]
        if not digest["registre_non_vide"]:
            pieces.append('<p class="vide">Le journal de réception ne contient aucun événement.</p>')
        else:
            pieces.append(
                '<div class="table-defilante"><table><thead><tr>'
                '<th>Canal</th><th>Type</th><th>Événements</th></tr></thead><tbody>'
            )
            for ligne in digest["grille"]:
                pieces.append(
                    f"<tr><td>{pages.e(ligne['canal'])}</td><td>{pages.e(ligne['type'])}</td>"
                    f"<td>{ligne['nombre']}</td></tr>"
                )
            pieces.append("</tbody></table></div>")
            for ligne in digest["suivi"]:
                pieces.append(f"<p>{pages.e(ligne['label'])} : {ligne['nombre']}</p>")
            for label, nombre in digest["transferts"].items():
                pieces.append(f"<p>{pages.e(label)} : {nombre}</p>")
            if digest["appels"]:
                appels_labels = {
                    "manque": "Appels manqués",
                    "voicemail": "Messages vocaux",
                    "inconnu": "Statut inconnu",
                }
                pieces.append("<h3>Appels importés</h3><ul>")
                for statut, nombre in digest["appels"].items():
                    pieces.append(f"<li>{appels_labels[statut]} : {nombre}</li>")
                pieces.append("</ul>")
            if digest["non_classes"]:
                pieces.append(f"<p>Événements non classés : {digest['non_classes']}</p>")
        pieces.extend(
            [
                '<p class="note">La grille suit les dates inscrites dans les événements; '
                "les anciennes entrées sans date restent incluses. "
                "Le suivi des conversations reflète leur dernier état connu à la lecture, "
                "même pour une date antérieure. Les transferts utilisent leurs dates d’ouverture "
                "et de clôture. Ce résumé n’est pas un état historique uniforme.</p>",
                '<p class="note">Résumé du journal de réception enregistré dans cette instance.</p></section>',
            ]
        )
        return "".join(pieces)

    def _json_response(session: Session, date_reference: str) -> Response:
        try:
            jour, digest, lu_le = _lire(session, date_reference)
            corps = {
                "ok": True,
                "date_reference": jour,
                "lu_le": lu_le,
                "methode": "Compteurs d’événements enregistrés; suivi des conversations courant.",
                "limites": [
                    "Les entrées sans date restent incluses.",
                    "Le suivi reflète le dernier état connu à la lecture, y compris pour une date antérieure.",
                    "Les transferts suivent leurs dates d’ouverture/clôture; "
                    "aucune garantie d’état historique uniforme.",
                    "Source : journal de réception enregistré dans cette instance.",
                ],
                "digest": digest,
            }
            response = JSONResponse(corps, headers={"Cache-Control": "no-store"})
            with cnx_factory() as cnx:
                _autoriser(cnx, session)
            return response
        except HTTPException:
            raise
        except PermissionError:
            raise HTTPException(403, "accès refusé") from None
        except Exception:
            raise HTTPException(503, "résumé temporairement indisponible") from None

    @router.get("/reception/digest", response_class=HTMLResponse)
    def page_digest(request: Request) -> Response:
        session = session_page(request)
        jour = _date_reference(request)
        try:
            jour, digest, lu_le = _lire(session, jour)
            contenu = (
                f'<p><a href="{pages.e(prefixe)}/reception">Retour à la réception</a></p>'
                f'<p><a href="{pages.e(prefixe)}/api/reception/digest?date_reference={jour}">'
                "Version JSON privée</a></p>"
                f'<section class="carte"><p>Date de référence : {jour}</p>'
                f"<p>Lu le {pages.e(lu_le)} (UTC).</p>"
                f'<form method="get" action="{pages.e(prefixe)}/reception/digest" class="pile">'
                f'<label>Choisir une date de référence<input type="date" name="date_reference" '
                f'value="{jour}" required></label><button type="submit">Afficher</button></form></section>'
                + _contenu(digest)
            )
            response = HTMLResponse(
                pages.gabarit("Résumé de réception", contenu, prefixe=prefixe, session=session, actif="reception"),
                headers={"Cache-Control": "no-store"},
            )
            with cnx_factory() as cnx:
                _autoriser(cnx, session)
            return response
        except HTTPException:
            raise
        except PermissionError:
            raise HTTPException(403, "accès refusé") from None
        except Exception:
            raise HTTPException(503, "résumé temporairement indisponible") from None

    @router.get("/api/reception/digest")
    def api_digest(request: Request) -> Response:
        session = session_api(request)
        jour = _date_reference(request)
        return _json_response(session, jour)

    return router
