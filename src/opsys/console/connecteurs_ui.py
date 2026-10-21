"""Catalogue privé et configuration STT M1, avec diagnostic distant manuel et borné."""

from __future__ import annotations

import dataclasses
import logging
import os
import secrets
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from m1_front_office import voicemail_stt

from opsys import canaux, connecteurs, identite
from opsys.departements import Departement
from opsys.memoire import embeddings
from opsys.memoire import outils as outils_memoire

from . import configuration_lecture, pages, securite
from .securite import Session

_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}
_LOGGER = logging.getLogger(__name__)
_LIMITE_FORMULAIRE_STT = 16 * 1024
_CHAMPS_STT_UI = ("url", "modele", "cle", "local", "delai_s")
_A_CONSTRUIRE = (
    ("M3", "Mesure photographique et géospatiale", "Échelle, sources, droits et précision à qualifier."),
    ("M3/M4/M6", "Calibration des estimations", "Paramètres versionnés et évaluation sur chantiers distincts."),
    ("M5", "Logiciels comptables et fiscalité", "OAuth, mappings, lecture/dry-run et sources officielles à qualifier."),
    ("M7", "Plateformes marketing", "OAuth, scopes, limites et validation avant action externe."),
    ("M10", "Ingestion et Fusion opérationnelle", "Lots documentaires, reprise, classification et qualité mesurée."),
    ("M1–M10", "Avatar 3D / Audio2Face", "Audio, rendu, licences et matériel à qualifier par adaptateur."),
)


def _capacite_devis_m3(deps: Mapping[str, Departement]) -> dict[str, str]:
    """Décrit le catalogue local M3 sans inférer la disponibilité des données ni l'exécution."""
    departement = deps.get("m03-estimation")
    if departement is None or departement.module_outils != "m3_estimation.outils":
        return {"catalogue": "non_verifie", "estimation": "non_verifie", "photos": "non_verifie"}
    try:
        noms = {outil.nom for outil in departement.charger_outils()}
    except Exception:
        return {"catalogue": "non_verifie", "estimation": "non_verifie", "photos": "non_verifie"}
    return {
        "catalogue": "verifie",
        "estimation": "present" if "m3_estimer_projet" in noms else "absent",
        "photos": "present" if "m3_qualifier_photos" in noms else "absent",
    }


def _capacite_devis_m3_html(deps: Mapping[str, Departement]) -> str:
    capacite = _capacite_devis_m3(deps)
    e = pages.e
    if capacite["catalogue"] != "verifie":
        estimation = "Catalogue d’outils M3 non consultable; disponibilité non vérifiée."
        photos = "Contrôle de qualité des photos M3 non vérifié."
    else:
        estimation = (
            "Outil M3 d’estimation présent au catalogue."
            if capacite["estimation"] == "present"
            else "Outil M3 d’estimation absent du catalogue courant."
        )
        photos = (
            "Contrôle de qualité des photos M3 présent au catalogue; il ne mesure pas les dimensions."
            if capacite["photos"] == "present"
            else "Contrôle de qualité des photos M3 absent du catalogue courant."
        )
    return (
        '<section class="carte pile"><h2>Capacité de préparation d’un devis M3</h2>'
        f'<p>{e(estimation)}</p><p>{e(photos)}</p>'
        '<p>Un devis ne peut être calculé qu’à partir d’une demande CRM qualifiée, '
        'des renseignements utiles au projet, '
        'de photos suffisantes avec une référence d’échelle et d’un barème applicable. Cette page ne vérifie pas un '
        'dossier et ne confirme pas que des photos ont été reçues.</p>'
        '<p>La mesure géométrique à partir de photos reste non qualifiée. OSRM en M4 sert au calcul d’itinéraires; '
        'il ne mesure pas les dimensions du bâtiment. Aucune exécution d’estimation n’est observée ici.</p></section>'
    )


def etat_connecteurs(environ: Mapping[str, str], deps: Mapping[str, Departement]) -> dict[str, Any]:
    """Présence seulement : une valeur non vide, même invalide, ne prouve aucune intégration."""
    specifications = (
        ("sms-m1", "SMS", "m01-front-office", "m1_front_office.outils", canaux.CANAL_SMS.variables,
         (), "Déclaration SMS; politiques, extension Core et authentification restent à vérifier."),
        ("stt-m1", "Transcription des messages vocaux", "m01-front-office", "m1_front_office.outils",
         (voicemail_stt.ENV_URL, voicemail_stt.ENV_MODELE),
         (voicemail_stt.ENV_CLE, voicemail_stt.ENV_LOCAL, voicemail_stt.ENV_DELAI),
         "Import STT borné; cette présence ne valide ni URL, modèle, consentement ni fournisseur."),
        ("memoire-entreprise", "Mémoire documentaire", "m10-memoire", "m10_memoire.outils",
         (outils_memoire.ENV_URL,), (),
         "Le store exige PostgreSQL et son schéma mémoire; un DSN SQLite ne le rend pas disponible."),
        ("embeddings-memoire", "Recherche vectorielle", "m10-memoire", "m10_memoire.outils",
         (embeddings.ENV_URL, embeddings.ENV_MODELE), (embeddings.ENV_CLE, embeddings.ENV_LOCAL),
         "Service optionnel; dimension, politique de données et schéma mémoire restent à vérifier."),
    )
    lignes = []
    for ident, libelle, departement, module, requis, optionnels, note in specifications:
        dep = deps.get(departement)
        source_presente = dep is not None and dep.module_outils == module
        if ident == "sms-m1" and source_presente:
            source_presente = "sms" in dep.canaux
        absentes = [nom for nom in requis if not environ.get(nom, "").strip()]
        statut = (
            "source_indisponible" if not source_presente else
            "configuration_incomplete" if absentes else "presence_declaree"
        )
        lignes.append({
            "id": ident, "libelle": libelle, "departement": departement,
            "source_presente": source_presente, "statut": statut,
            "requis": list(requis), "optionnels": list(optionnels), "variables_manquantes": absentes,
            "validation_locale": "non_executee", "authentification_distante": "non_verifiee",
            "note": note,
        })
    return {
        "connecteurs": lignes, "verification_distante": "non_executee",
        "a_construire": [
            {"departements": dep, "capacite": capacite, "limite": limite}
            for dep, capacite, limite in _A_CONSTRUIRE
        ],
    }


def contenu(resultat: Mapping[str, Any], prefixe: str, deps: Mapping[str, Departement]) -> str:
    html = [
        '<section class="carte pile"><h2>Prérequis des connexions</h2>',
        "<p>La présence d’une configuration ne prouve pas une connexion réussie. "
        "Les valeurs et secrets restent masqués; aucun contrôle réseau n’est lancé par cette page.</p>",
        "<p>La configuration STT stocke uniquement des noms de variables. Le contrôle distant ne "
        "part qu’à la demande et ne transmet aucun audio.</p>",
        f'<p><a href="{pages.e(prefixe)}/modeles">Configurer les modèles</a> · '
        f'<a href="{pages.e(prefixe)}/memoire">Consulter la mémoire</a></p></section>',
    ]
    libelles = {
        "source_indisponible": "Département ou canal indisponible",
        "configuration_incomplete": "Configuration incomplète",
        "configuration_desactivee": "Configuration désactivée",
        "presence_declaree": "Présence déclarée — validation non effectuée",
    }
    for ligne in resultat["connecteurs"]:
        requis = " · ".join(pages.e(nom) for nom in ligne["requis"])
        optionnels = " · ".join(pages.e(nom) for nom in ligne["optionnels"]) or "Aucun"
        absentes = " · ".join(pages.e(nom) for nom in ligne["variables_manquantes"]) or "Aucune"
        html.append(
            '<section class="carte pile">'
            f'<h2>{pages.e(ligne["libelle"])}</h2><p>{pages.e(ligne["departement"])}</p>'
            f'<p>{pages.e(libelles[ligne["statut"]])}</p>'
            f'<p>Variables requises : {requis}</p><p>Optionnelles : {optionnels}</p>'
            f'<p>Variables manquantes : {absentes}</p><p>{pages.e(ligne["note"])}</p></section>'
        )
    html.append(_capacite_devis_m3_html(deps))
    html.append(
        '<section class="carte pile"><h2>Réception des chantiers pour l’apprentissage M3</h2>'
        '<p>Comparer les identités publiées par M4 avec les reçus M3 de cette instance. '
        'Ce diagnostic n’active aucun barème et ne certifie pas la précision des mesures.</p>'
        f'<p><a href="{pages.e(prefixe + "/estimation/apprentissage/couverture")}">'
        'Consulter les écarts de réception M4 → M3</a></p></section>'
    )
    html.append('<section class="carte pile"><h2>Capacités à construire et qualifier</h2><ul>')
    for ligne in resultat["a_construire"]:
        html.append(
            f'<li>{pages.e(ligne["departements"])} · {pages.e(ligne["capacite"])} : '
            f'{pages.e(ligne["limite"])}</li>'
        )
    return "".join(html) + "</ul></section>"


def configuration_contenu(projection: Mapping[str, Any], prefixe: str) -> str:
    """Vue synthétique : références uniquement, jamais les configurations brutes."""
    e = pages.e
    sections = [
        '<section class="carte pile"><h2>Spécialistes et connexions par département</h2>'
        '<p>Profil activé, configuration projetée et tâche exécutée sont trois états distincts. '
        'Le chargement Core et les exécutions ne sont pas observés ici.</p>'
        '<p>Déclencheurs déclarés, non raccordés. Mémoire et droits métier héritent du département. '
        'Les liens entre départements ci-dessous sont les contrats déclarés, pas des travaux exécutés.</p>'
        f'<p><a href="{e(prefixe)}/agents">Configurer les spécialistes</a> · '
        f'<a href="{e(prefixe)}/budgets">Plafonds de tokens</a> · '
        f'<a href="{e(prefixe)}/approbations">Approbations humaines</a></p>'
        '<p>Les plafonds concernent des tokens ; le coût financier reste inconnu. '
        'L’inventaire des API est partiel : un département sans adaptateur listé '
        'ne signifie pas qu’aucune API n’est requise.</p></section>',
    ]
    libelles = {"non_configure": "Non configuré", "references_manquantes": "Références manquantes",
                "presence_declaree": "Présence déclarée — authentification non vérifiée"}
    for palier in projection["paliers"]:
        sections.append(
            '<section class="carte pile">'
            f'<h3>Palier {e(palier["nom"])}</h3><p>{e(libelles[palier["statut"]])}</p>'
            f'<p>Fournisseur déclaré : {e(palier["fournisseur"] or "à configurer")}</p>'
            f'<p>Références requises : {e(", ".join(palier["references_requises"]) or "aucune clé API déclarée")}. '
            f'Absentes : {e(", ".join(palier["references_absentes"]) or "aucune")}</p>'
            f'<a href="{e(prefixe)}/modeles#palier-{e(palier["nom"])}">Modifier le palier</a></section>'
        )
    politique = projection["plafonds_specialistes"]
    sections.append(
        '<p class="note">Plafonds entreprise pour les spécialistes : '
        + (f'{e(politique["budget_jour"])} tokens/jour, {e(politique["budget_mois"])} tokens/mois.'
           if politique else 'non configurés ; nouvelle génération refusée par l’admission.')
        + ' Ces limites ne constituent pas un plafond universel des agents historiques.</p>'
    )
    for dep in projection["departements"]:
        paliers = " · ".join(
            f'<a href="{e(prefixe)}/modeles#palier-{e(nom)}">{e(nom)}</a>' for nom in dep["paliers_requis"]
        )
        refs = " · ".join(
            f'<a href="{e(prefixe)}/departements#{e(quote(ident, safe=""))}">{e(ident)}</a>'
            for ident in dep["dependances"]
        ) or "aucune déclarée"
        sections.append(
            '<section class="carte pile">'
            f'<h3><a href="{e(prefixe)}/departements#{e(quote(dep["id"], safe=""))}">'
            f'{e(dep["code"])} · {e(dep["nom"])}</a></h3>'
            f'<p>Mode actuel : {e(dep["mode"])}. Paliers requis : {paliers or "aucun déclaré"}.</p>'
            f'<p>Spécialistes : {e(dep["specialistes"]["actifs"])} actifs, '
            f'{e(dep["specialistes"]["inactifs"])} inactifs. '
            f'Budget département : {e(dep["tokens"]["jour"])} tokens/jour, '
            f'{e(dep["tokens"]["mois"])} tokens/mois.</p>'
            f'<p>Dépendances : {refs}.</p>'
            f'<p>Événements publiés : {e(", ".join(dep["evenements_declares"]["publie"]) or "aucun déclaré")}. '
            f'Consommés : {e(", ".join(dep["evenements_declares"]["consomme"]) or "aucun déclaré")}.</p>'
            f'<p>Mémoire déclarée en lecture : {e(", ".join(dep["memoire_declaree"]["lecture"]) or "aucune")}. '
            f'En écriture : {e(", ".join(dep["memoire_declaree"]["ecriture"]) or "aucune")}.</p>'
            '<p>Outils du département et politiques métier ; aucune permission nouvelle accordée ici.</p></section>'
        )
    profils = projection["profils"]
    lignes = "".join(
        f'<li><a href="{e(prefixe)}/agents/{e(quote(p["id"], safe=""))}">{e(p["id"])}</a> · '
        f'{e(p["departement"])} · révision {e(p["revision"])} · {"activé" if p["actif"] else "inactif"} · '
        f'{e(p["palier"])} · {e(p["budget_jour"])} tokens/jour, {e(p["budget_mois"])} tokens/mois</li>'
        for p in profils["items"]
    )
    sections.append(
        f'<section class="carte pile"><h3>Profils configurés</h3><p>{e(profils["retournes"])} '
        f'affichés sur {e(profils["total"])} ; {e(profils["omis"])} omis par la borne.</p>'
        f'<ul>{lignes}</ul></section>'
    )
    return "".join(sections)


def creer_router(
    *, session_page: Callable[..., Session], session_api: Callable[..., Session],
    cnx_factory: Callable[[], Any], deps: Mapping[str, Departement], prefixe: str,
    ecriture_api: Callable[..., Session] | None = None,
    objet_json: Callable[..., Any] | None = None,
    chemin_paliers: Path | None = None,
) -> APIRouter:
    router = APIRouter(tags=["prérequis connecteurs"])

    def autoriser(session: Session) -> None:
        with cnx_factory() as cnx:
            personne = identite.personne_active(cnx, session.utilisateur)
            if personne is None:
                raise HTTPException(401, "authentification requise")
            if not personne.roles.intersection({"nathan_owner", "admin"}):
                raise HTTPException(403, "administration requise")

    def lire(session: Session) -> dict[str, Any]:
        autoriser(session)
        resultat = etat_connecteurs(os.environ, deps)
        autoriser(session)
        return resultat

    def configuration(session: Session) -> dict[str, Any] | None:
        autoriser(session)
        with cnx_factory() as cnx:
            resultat = connecteurs.lire(cnx)
        autoriser(session)
        return resultat

    def projection(session: Session) -> dict[str, Any]:
        autoriser(session)
        try:
            with cnx_factory() as cnx:
                resultat = configuration_lecture.lire(cnx, deps, os.environ, chemin_paliers)
        except configuration_lecture.ConfigurationLectureErreur as exc:
            raise HTTPException(exc.statut, exc.code) from exc
        autoriser(session)
        return resultat

    def reponse_bornee(reponse: HTMLResponse | JSONResponse, session: Session):
        try:
            configuration_lecture.verifier_sortie(reponse.body)
        except configuration_lecture.ConfigurationLectureErreur as exc:
            raise HTTPException(exc.statut, exc.code) from exc
        autoriser(session)  # Après le rendu effectif, même si le rôle a changé pendant celui-ci.
        return reponse

    def connecter_etat(resultat: dict[str, Any], config: dict[str, Any] | None) -> None:
        if config is None:
            return
        ligne = next(item for item in resultat["connecteurs"] if item["id"] == "stt-m1")
        ligne["statut"] = "configuration_incomplete"
        ligne["validation_locale"] = "non_executee"
        ligne["authentification_distante"] = "non_verifiee"
        ligne["derniere_observation"] = config.get("derniere_observation")
        refs = config["references"]
        vars_refs = {"url": refs["url"], "modele": refs["modele"]}
        vars_refs.update({key: refs[key] for key in ("cle", "local", "delai_s") if key in refs})
        ligne["requis"] = [vars_refs[key] for key in ("url", "modele")]
        ligne["optionnels"] = [vars_refs[key] for key in ("cle", "local", "delai_s") if key in vars_refs]
        ligne["variables_manquantes"] = [nom for nom in vars_refs.values() if not os.environ.get(nom, "").strip()]
        if not config["actif"]:
            ligne["statut"] = "configuration_desactivee"
            return
        try:
            runtime = connecteurs.construire_configuration(config["references"], os.environ)
        except Exception:
            return
        if runtime is not None:
            ligne["statut"] = "presence_declaree"
            ligne["validation_locale"] = "valide"

    def abandonner_diagnostic(mutation_id: Any, jeton: Any) -> None:
        if not isinstance(mutation_id, str) or not isinstance(jeton, str):
            return
        try:
            with cnx_factory() as cnx:
                connecteurs.diagnostic_abandonner(cnx, mutation_id, jeton)
        except Exception as exc:
            _LOGGER.warning("nettoyage de réservation STT impossible (%s)", type(exc).__name__)

    def statut_diagnostic(config: Mapping[str, Any]) -> str:
        try:
            runtime = connecteurs.construire_configuration(config["references"], os.environ)
        except voicemail_stt.ErreurVoicemail as exc:
            return "references_incompletes" if exc.code == "REJ-STT-REFERENCES" else "configuration_invalide"
        if runtime is None:
            return "references_incompletes"
        try:
            connecteurs.verifier_adresse_diagnostic(runtime)
        except ValueError:
            return "configuration_invalide"
        runtime = dataclasses.replace(runtime, delai_s=min(runtime.delai_s, 5.0))
        return runtime.verifier_connexion()["statut"]

    async def formulaire_stt(request: Request, champs_attendus: set[str]) -> dict[str, str]:
        morceaux = []
        taille = 0
        async for morceau in request.stream():
            taille += len(morceau)
            if taille > _LIMITE_FORMULAIRE_STT:
                raise HTTPException(413, "formulaire STT trop volumineux")
            morceaux.append(morceau)
        try:
            parsed = parse_qs(b"".join(morceaux).decode("utf-8"), keep_blank_values=True, max_num_fields=20)
        except (UnicodeDecodeError, ValueError) as exc:
            raise HTTPException(400, "formulaire STT invalide") from exc
        if set(parsed) - champs_attendus:
            raise HTTPException(422, "champ de formulaire STT non pris en charge")
        if any(len(valeurs) != 1 for valeurs in parsed.values()):
            raise HTTPException(400, "champ de formulaire STT répété")
        return {cle: valeurs[0] for cle, valeurs in parsed.items()}

    @router.get("/connecteurs", response_class=HTMLResponse)
    def page_connecteurs(request: Request) -> HTMLResponse:
        session = session_page(request)
        config = configuration(session)
        refs = config["references"] if config else {"url": "OPSYS_M1_STT_URL", "modele": "OPSYS_M1_STT_MODELE"}
        csrf = pages.e(session.csrf)
        champs = "".join(
            f'<label>{pages.e(nom)}<input name="ref_{nom}" value="{pages.e(refs.get(nom, ""))}" '
            f'{"required" if nom in {"url", "modele"} else ""}></label>'
            for nom in ("url", "modele", "cle", "local", "delai_s")
        )
        revision = config["revision"] if config else 0
        observation = config.get("derniere_observation") if config else None
        observation_html = (
            f'<p>Dernière observation distante, révision {observation["revision"]} : '
            f'{pages.e(observation["statut"])} ({pages.e(observation["date"])}); '
            "le STT n’est pas vérifié.</p>"
            if observation else "<p>Aucune observation distante enregistrée.</p>"
        )
        formulaire = (
            '<section class="carte pile"><h2>Configuration STT M1</h2>'
            '<p>Seuls les noms de variables sont enregistrés. Les valeurs restent côté serveur.</p>'
            f'<form method="post" action="{pages.e(prefixe)}/connecteurs/stt-m1/configuration">'
            f'<input type="hidden" name="csrf" value="{csrf}">'
            f'<input type="hidden" name="revision_attendue" value="{revision}">'
            '<label><input type="checkbox" name="actif" value="true" '
            + ("checked" if config and config["actif"] else "") + ">Actif</label>"
            + champs + '<button>Enregistrer la configuration</button></form>'
            f'<form method="post" action="{pages.e(prefixe)}/connecteurs/stt-m1/diagnostic">'
            f'<input type="hidden" name="csrf" value="{csrf}">'
            f'<input type="hidden" name="revision" value="{revision}">'
            '<button>Vérifier /models</button></form>' + observation_html + '</section>'
        )
        resultat = lire(session)
        connecter_etat(resultat, config)
        dashboard = projection(session)
        return reponse_bornee(HTMLResponse(
            pages.gabarit("Connecteurs", configuration_contenu(dashboard, prefixe) + formulaire
                          + contenu(resultat, prefixe, deps), prefixe=prefixe,
                          session=session, actif="connecteurs"), headers=_HEADERS,
        ), session)

    @router.get("/api/connecteurs")
    def api_connecteurs(request: Request) -> JSONResponse:
        session = session_api(request)
        resultat = lire(session)
        config = configuration(session)
        connecter_etat(resultat, config)
        resultat["configuration_dashboard"] = projection(session)
        return reponse_bornee(JSONResponse(
            {"ok": True, "resultat": resultat, "configuration": config},
            headers=_HEADERS,
        ), session)

    if ecriture_api is not None and objet_json is not None:
        @router.put("/api/connecteurs/stt-m1/configuration")
        async def put_configuration(request: Request) -> JSONResponse:
            session = ecriture_api(request)
            try:
                payload = await objet_json(request)
                with cnx_factory() as cnx:
                    resultat = connecteurs.modifier(cnx, acteur=session.utilisateur, payload=payload)
                autoriser(session)
                return JSONResponse({"ok": True, "configuration": resultat}, headers=_HEADERS)
            except PermissionError as exc:
                raise HTTPException(403, str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(409 if "conflit" in str(exc) else 422, str(exc)) from exc

        @router.post("/api/connecteurs/stt-m1/diagnostic")
        async def post_diagnostic(request: Request) -> JSONResponse:
            session = ecriture_api(request)
            jeton = None
            try:
                payload = await objet_json(request)
                if set(payload) != {"revision", "mutation_id"}:
                    raise ValueError("diagnostic : champs absents ou inconnus")
                revision, mutation = payload["revision"], payload["mutation_id"]
                with cnx_factory() as cnx:
                    resultat = connecteurs.diagnostic_reserver(cnx, acteur=session.utilisateur,
                                                               revision=revision, mutation_id=mutation)
                    config = connecteurs.lire(cnx)
                if isinstance(resultat, dict) and "_jeton_reservation" in resultat:
                    jeton = resultat["_jeton_reservation"]
                    statut = statut_diagnostic(config)
                    with cnx_factory() as cnx:
                        resultat = connecteurs.diagnostic_terminer(
                            cnx, acteur=session.utilisateur, revision=revision,
                            mutation_id=mutation, jeton=jeton, statut=statut,
                        )
                elif resultat is None:
                    with cnx_factory() as cnx:
                        connecteurs._admin(cnx, session.utilisateur)
                autoriser(session)
                return JSONResponse({"ok": True, "resultat": resultat}, headers=_HEADERS)
            except PermissionError as exc:
                abandonner_diagnostic(mutation if "mutation" in locals() else None, jeton)
                raise HTTPException(403, str(exc)) from exc
            except RuntimeError as exc:
                abandonner_diagnostic(mutation if "mutation" in locals() else None, jeton)
                raise HTTPException(409, str(exc)) from exc
            except ValueError as exc:
                abandonner_diagnostic(mutation if "mutation" in locals() else None, jeton)
                raise HTTPException(409, str(exc)) from exc
            except Exception as exc:
                # Délier le verrou de reprise si l'appel local/sonde échoue avant sa clôture.
                abandonner_diagnostic(mutation if "mutation" in locals() else None, jeton)
                _LOGGER.error("échec du diagnostic STT (%s)", type(exc).__name__)
                raise HTTPException(503, "diagnostic STT indisponible") from None

        @router.post("/connecteurs/stt-m1/configuration")
        async def form_configuration(request: Request) -> HTMLResponse:
            from fastapi.responses import RedirectResponse
            session = session_api(request)
            champs_form = await formulaire_stt(
                request,
                {"csrf", "revision_attendue", "actif", *(f"ref_{key}" for key in _CHAMPS_STT_UI)},
            )
            if not securite.csrf_valide(champs_form.get("csrf"), session):
                raise HTTPException(403, "jeton CSRF invalide")
            refs = {nom: champs_form.get("ref_" + nom, "")
                    for nom in ("url", "modele", "cle", "local", "delai_s")
                    if champs_form.get("ref_" + nom, "")}
            try:
                with cnx_factory() as cnx:
                    connecteurs.modifier(cnx, acteur=session.utilisateur, payload={
                        "actif": champs_form.get("actif") == "true", "references": refs,
                        "revision_attendue": int(champs_form.get("revision_attendue", "-1")),
                        "mutation_id": "web-" + secrets.token_hex(12),
                    })
                autoriser(session)
            except (ValueError, PermissionError) as exc:
                raise HTTPException(422, str(exc)) from exc
            return RedirectResponse(f"{prefixe}/connecteurs", status_code=303)

        @router.post("/connecteurs/stt-m1/diagnostic")
        async def form_diagnostic(request: Request) -> JSONResponse:
            session = session_api(request)
            jeton = None
            champs_form = await formulaire_stt(request, {"csrf", "revision"})
            if not securite.csrf_valide(champs_form.get("csrf"), session):
                raise HTTPException(403, "jeton CSRF invalide")
            try:
                revision = int(champs_form.get("revision", "-1"))
                mutation = "web-" + secrets.token_hex(12)
                with cnx_factory() as cnx:
                    reserve = connecteurs.diagnostic_reserver(
                        cnx, acteur=session.utilisateur, revision=revision, mutation_id=mutation,
                    )
                    config = connecteurs.lire(cnx)
                if isinstance(reserve, dict) and "_jeton_reservation" in reserve:
                    jeton = reserve["_jeton_reservation"]
                    statut = statut_diagnostic(config)
                    with cnx_factory() as cnx:
                        reserve = connecteurs.diagnostic_terminer(
                            cnx, acteur=session.utilisateur, revision=revision,
                            mutation_id=mutation, jeton=jeton, statut=statut,
                        )
                autoriser(session)
                return JSONResponse({"ok": True, "resultat": reserve}, headers=_HEADERS)
            except PermissionError as exc:
                abandonner_diagnostic(mutation if "mutation" in locals() else None, jeton)
                raise HTTPException(403, str(exc)) from exc
            except RuntimeError as exc:
                abandonner_diagnostic(mutation if "mutation" in locals() else None, jeton)
                raise HTTPException(409, str(exc)) from exc
            except ValueError as exc:
                abandonner_diagnostic(mutation if "mutation" in locals() else None, jeton)
                raise HTTPException(409, str(exc)) from exc
            except Exception as exc:
                abandonner_diagnostic(mutation if "mutation" in locals() else None, jeton)
                _LOGGER.error("échec du diagnostic STT (%s)", type(exc).__name__)
                raise HTTPException(503, "diagnostic STT indisponible") from None

    return router
