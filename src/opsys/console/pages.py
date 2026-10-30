"""Pages HTML de la console, rendues côté serveur à partir des vues de `opsys.tableau_de_bord`.

Fonctions pures qui renvoient du texte. Toute valeur dynamique passe par `e()` (échappement
HTML). Aucun script ni style en ligne : la CSP n'autorise que les ressources de la console.
"""

from __future__ import annotations

import datetime as dt
import html
import json
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import quote

from .securite import Session

# Fournisseur des serveurs locaux compatibles OpenAI (Ollama, vLLM, llama.cpp) : opsys.modeles
# exige alors base_url (un test garde l'alignement avec le socle).
FOURNISSEUR_COMPATIBLE_OPENAI = "custom"
PLAFOND_PASTILLE = 100  # au-delà, la navigation affiche « 100+ »

ONGLETS = (
    ("departements", "Départements"),
    ("crm", "CRM"),
    ("approbations", "Approbations"),
    ("budgets", "Budgets"),
    ("modeles", "Modèles"),
    ("connecteurs", "Connecteurs"),
    ("agents", "Agents"),
    ("memoire", "Mémoire"),
    ("reception", "Réception"),
    ("marketing", "Marketing"),
    ("finance", "Finance"),
    ("fusion", "Fusion opérationnelle"),
    ("strategie", "Suivis stratégiques"),
    ("direction", "Direction IA"),
)
LIBELLES_MODES = {"ombre": "Ombre", "supervise": "Supervisé", "autonome": "Autonome"}
STATUTS = {
    "en_attente": ("En attente", "badge-alerte"),
    "executee": ("Exécutée", "badge-ok"),
    "refusee": ("Refusée", ""),
    "echec": ("Échec", "badge-danger"),
}
FILTRES = (
    ("", "Toutes"),
    ("en_attente", "En attente"),
    ("executee", "Exécutées"),
    ("refusee", "Refusées"),
    ("echec", "Échecs"),
)
NIVEAUX = {"ok": ("OK", "badge-ok"), "alerte": ("Alerte", "badge-alerte"), "epuise": ("Épuisé", "badge-danger")}
CLASSES_AUTONOMIE = {"T2": "badge-alerte", "T3": "badge-danger"}
MESSAGES = {
    "mode": ("Mode d'autonomie modifié.", "ok"),
    "executee": ("Demande approuvée : l'outil a été exécuté avec les arguments enregistrés.", "ok"),
    "echec": ("Demande approuvée, mais l'outil a renvoyé une erreur : voir le résultat dans l'historique.", "alerte"),
    "refusee": ("Demande refusée : rien n'a été exécuté.", "ok"),
    "palier": ("Palier enregistré.", "ok"),
}
Bandeau = tuple[str, str]  # (texte, genre) ; genre : ok, alerte ou erreur


def e(valeur: object) -> str:
    return html.escape("" if valeur is None else str(valeur), quote=True)


def _segment(valeur: str) -> str:
    return e(quote(valeur, safe=""))


def _entier(nombre: int) -> str:
    return f"{nombre:,}".replace(",", " ")


def _pct(pct: float) -> str:
    return f"{pct:.1f}".replace(".", ",") + " %"


def _date(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        moment = dt.datetime.fromisoformat(iso)
    except ValueError:
        return iso
    return f"{moment:%Y-%m-%d %H:%M} UTC" if moment.utcoffset() == dt.timedelta(0) else iso


def _json(valeur: Any) -> str:
    return json.dumps(valeur, ensure_ascii=False, indent=2)


def _badge(texte: str, classe: str = "") -> str:
    return f'<span class="badge {classe}">{e(texte)}</span>' if classe else f'<span class="badge">{e(texte)}</span>'


def _vide(texte: str) -> str:
    return f'<p class="vide">{e(texte)}</p>'


def bandeau_succes(code: str) -> Bandeau | None:
    """Message fixe après une redirection réussie (?ok=code) ; un code inconnu n'affiche rien."""
    return MESSAGES.get(code)


# -- gabarit -------------------------------------------------------------------------------------


def gabarit(
    titre: str,
    contenu: str,
    *,
    prefixe: str,
    session: Session | None = None,
    actif: str = "",
    en_attente: int = 0,
    bandeau: Bandeau | None = None,
) -> str:
    entete = '<div class="marque">OPSYS <span>Console</span></div>'
    if session is not None:
        liens = []
        for cle, libelle in ONGLETS:
            courant = ' aria-current="page"' if cle == actif else ""
            pastille = ""
            if cle == "approbations" and en_attente:
                nombre = f"{PLAFOND_PASTILLE}+" if en_attente >= PLAFOND_PASTILLE else str(en_attente)
                pastille = f'<span class="pastille">{nombre}</span>'
            liens.append(f'<a href="{e(prefixe)}/{cle}"{courant}>{e(libelle)}{pastille}</a>')
        entete += (
            f'<nav aria-label="Sections">{"".join(liens)}</nav>'
            f'<form method="post" action="{e(prefixe)}/deconnexion" class="session">'
            f"<span>Connecté : {e(session.utilisateur)}</span>"
            f'<input type="hidden" name="csrf" value="{e(session.csrf)}">'
            '<button type="submit">Se déconnecter</button></form>'
        )
    message = ""
    if bandeau is not None:
        texte, genre = bandeau
        message = f'<p class="message message-{e(genre)}" role="status">{e(texte)}</p>'
    return (
        "<!doctype html>\n"
        '<html lang="fr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{e(titre)} · Console OPSYS</title>"
        f'<link rel="stylesheet" href="{e(prefixe)}/statique/console.css">'
        f'<script src="{e(prefixe)}/statique/console.js" defer></script>'
        f'</head><body><header class="entete">{entete}</header>'
        f"<main>{message}<h1>{e(titre)}</h1>{contenu}</main></body></html>\n"
    )


def page_connexion(*, prefixe: str, erreur: str = "", identifiant: str = "") -> str:
    contenu = (
        f'<form method="post" action="{e(prefixe)}/connexion" class="carte pile connexion">'
        '<label for="identifiant">Identifiant</label>'
        f'<input id="identifiant" name="identifiant" autocomplete="username" required maxlength="80" '
        f'value="{e(identifiant)}">'
        '<p class="note">Votre compte signe chaque décision, changement de mode et palier.</p>'
        '<label for="mot_de_passe">Mot de passe</label>'
        '<input id="mot_de_passe" name="mot_de_passe" type="password" autocomplete="current-password" required>'
        '<button type="submit" class="principal">Se connecter</button></form>'
    )
    return gabarit("Connexion", contenu, prefixe=prefixe, bandeau=(erreur, "erreur") if erreur else None)


def page_erreur(titre: str, texte: str, *, prefixe: str) -> str:
    lien = f'<p><a href="{e(prefixe)}/departements">Retour à la console</a></p>'
    return gabarit(titre, lien, prefixe=prefixe, bandeau=(texte, "erreur"))


# -- départements --------------------------------------------------------------------------------


def _jauge(libelle: str, periode: Mapping[str, Any], alerte_pct: int) -> str:
    pct = periode["pct"]
    return (
        f'<div class="jauge"><div class="jauge-titre"><strong>{e(libelle)}</strong>'
        f"<span>{_entier(periode['utilise'])} / {_entier(periode['limite'])} tokens · {_pct(pct)}</span></div>"
        f'<meter min="0" max="100" low="{e(alerte_pct)}" high="100" optimum="0" value="{e(min(pct, 100))}" '
        f'title="{e(libelle)} : {_pct(pct)} (alerte à {e(alerte_pct)} %)">{_pct(pct)}</meter></div>'
    )


def _details(titre: str, nombre: int, contenu: str) -> str:
    return f"<details><summary>{e(titre)} ({nombre})</summary>{contenu}</details>"


def _outils(outils: Sequence[Mapping[str, Any]]) -> str:
    if not outils:
        return ""
    lignes = "".join(
        f"<tr><td><code>{e(o['nom'])}</code></td>"
        f"<td>{_badge(o['autonomie'], CLASSES_AUTONOMIE.get(o['autonomie'], ''))}</td>"
        f"<td>{'requise' if o['approbation_requise'] else 'non'}</td><td>{e(o['description'])}</td></tr>"
        for o in outils
    )
    table = (
        "<table><thead><tr><th>Outil</th><th>Autonomie</th><th>Approbation</th><th>Description</th></tr>"
        f"</thead><tbody>{lignes}</tbody></table>"
    )
    return _details("Outils", len(outils), table)


def _planifications(planifications: Sequence[Mapping[str, str]]) -> str:
    if not planifications:
        return ""
    lignes = "".join(
        f"<tr><td>{e(p['nom'])}</td><td><code>{e(p['cron'])}</code></td><td>{e(p['consigne'])}</td></tr>"
        for p in planifications
    )
    table = f"<table><thead><tr><th>Nom</th><th>Cron</th><th>Consigne</th></tr></thead><tbody>{lignes}</tbody></table>"
    return _details("Planifications", len(planifications), table)


def _carte_departement(v: Mapping[str, Any], modes: Sequence[Mapping[str, str]], prefixe: str, csrf: str) -> str:
    ident, mode = v["id"], v["mode"]
    options = "".join(
        f'<option value="{e(m["mode"])}"{" selected" if m["mode"] == mode else ""}>'
        f"{e(LIBELLES_MODES.get(m['mode'], m['mode']))} — approbation dès {e(m['approbation_des'])}</option>"
        for m in modes
    )
    alertes = ""
    if v["erreur_outils"]:
        alertes += f'<p class="message message-erreur">Outils illisibles : {e(v["erreur_outils"])}</p>'
    if v["dependances_manquantes"]:
        alertes += (
            '<p class="message message-alerte">Dépendances non installées : '
            f"{e(', '.join(v['dependances_manquantes']))}</p>"
        )
    manifeste = ""
    if mode != v["mode_manifeste"]:
        manifeste = (
            f'<p class="note">Mode du manifeste : {e(LIBELLES_MODES.get(v["mode_manifeste"]))} ; '
            "le mode fixé depuis la console prévaut.</p>"
        )
    conso, alerte_pct = v["consommation"], v["budget"]["alerte_pct"]
    niveau, classe = NIVEAUX.get(conso["niveau"], (conso["niveau"], ""))
    skills = "".join(f"<li>{_badge(s)}</li>" for s in v["skills"])
    kpis = "".join(f"<li><strong>{e(k['id'])}</strong> — {e(k['description'])}</li>" for k in v["kpis"])
    usages = "".join(f"<dt>{e(usage)}</dt><dd>{e(palier)}</dd>" for usage, palier in v["modeles"].items())
    dependances = e(", ".join(v["dependances"])) if v["dependances"] else "aucune"
    confirmation = (
        f"Changer le mode d'autonomie du département {v['code']} ({v['nom']}) ? "
        "Il s'applique aux prochains appels d'outils."
    )
    return (
        f'<article class="carte" id="{e(ident)}">'
        f'<header class="carte-entete"><span class="code">{e(v["code"])}</span><h2>{e(v["nom"])}</h2>'
        f"{_badge(LIBELLES_MODES.get(mode, mode))}{_badge(niveau, classe)}</header>"
        f"<p>{e(v['mission'])}</p>{alertes}"
        f'<form method="post" action="{e(prefixe)}/departements/{_segment(ident)}/mode" class="ligne" '
        f'data-confirmer="{e(confirmation)}"><input type="hidden" name="csrf" value="{e(csrf)}">'
        f'<label for="mode-{e(ident)}">Mode</label><select id="mode-{e(ident)}" name="mode">{options}</select>'
        f'<button type="submit">Appliquer</button></form>{manifeste}'
        f'<div class="jauges">{_jauge("Jour", conso["jour"], alerte_pct)}{_jauge("Mois", conso["mois"], alerte_pct)}'
        f"</div>{_outils(v['outils'])}"
        + (_details("Skills", len(v["skills"]), f'<ul class="puces">{skills}</ul>') if v["skills"] else "")
        + _planifications(v["planifications"])
        + (_details("KPIs", len(v["kpis"]), f"<ul>{kpis}</ul>") if v["kpis"] else "")
        + _details("Paliers de modèles", len(v["modeles"]), f'<dl class="meta">{usages}</dl>')
        + f'<p class="note">Dépendances : {dependances}</p></article>'
    )


def contenu_departements(
    vues: Sequence[Mapping[str, Any]], modes: Sequence[Mapping[str, str]], *, prefixe: str, csrf: str
) -> str:
    if not vues:
        return _vide("Aucun département installé.")
    intro = (
        '<p class="intro">Le mode d\'autonomie décide quelles actions attendent une approbation humaine. '
        "Les actions T3 (paiement, engagement, publication, suppression) l'attendent toujours.</p>"
    )
    cartes = "".join(_carte_departement(v, modes, prefixe, csrf) for v in vues)
    return f'{intro}<div class="grille">{cartes}</div>'


# -- approbations --------------------------------------------------------------------------------


def _formulaire_decision(d: Mapping[str, Any], prefixe: str, csrf: str) -> str:
    ident = d["id"]
    confirmation = f"Approuver exécute {d['outil']} avec ces arguments exacts, signé à votre nom. Confirmer ?"
    if d.get("autonomie") == "T3":
        confirmation = (
            "Action T3 (frontière humaine : paiement, écriture financière, publication, engagement "
            f"ou suppression). {confirmation}"
        )
    attestation = ""
    if d.get("niveau") == "N5":
        attestation = (
            '<p class="note">Niveau N5 (ADR-0009 §5) : approuver exige, en plus de votre signature, '
            "l'attestation du professionnel concerné (comptable, fiscaliste, avocat, prêteur…).</p>"
            f'<label for="attestation_nom-{e(ident)}">Nom du professionnel</label>'
            f'<input id="attestation_nom-{e(ident)}" name="attestation_nom" maxlength="200">'
            f'<label for="attestation_profession-{e(ident)}">Profession</label>'
            f'<input id="attestation_profession-{e(ident)}" name="attestation_profession" maxlength="200">'
            f'<label for="attestation_document-{e(ident)}">Référence du document joint</label>'
            f'<input id="attestation_document-{e(ident)}" name="attestation_document" maxlength="200">'
        )
    return (
        f'<form method="post" action="{e(prefixe)}/approbations/{_segment(ident)}/decision" class="pile">'
        f'<input type="hidden" name="csrf" value="{e(csrf)}">'
        f'<label for="motif-{e(ident)}">Motif (facultatif)</label>'
        f'<textarea id="motif-{e(ident)}" name="motif" rows="2" maxlength="1000"></textarea>'
        f"{attestation}"
        '<div class="actions">'
        f'<button type="submit" name="decision" value="approuver" class="principal" data-confirmer="{e(confirmation)}">'
        "Approuver et exécuter</button>"
        '<button type="submit" name="decision" value="refuser" class="danger">Refuser</button></div></form>'
    )


def _carte_demande(d: Mapping[str, Any], prefixe: str, csrf: str) -> str:
    statut = d["statut"]
    libelle, classe = STATUTS.get(statut, (statut, ""))
    autonomie = d.get("autonomie")
    meta: list[tuple[str, Any]] = []
    if d.get("description_outil"):
        meta.append(("Outil", d["description_outil"]))
    departement = f"{d['departement_nom']} ({d['departement']})" if d.get("departement_nom") else d["departement"]
    meta += [("Département", departement), ("Demandée le", _date(d["cree_le"])), ("Identifiant", d["id"])]
    if d.get("motif_demande"):
        meta.append(("Motif de la demande", d["motif_demande"]))
    if statut != "en_attente":
        decideur = d.get("decide_par")
        if d.get("decide_role"):
            decideur = f"{decideur} ({d['decide_role']})"
        meta += [
            ("Décidée par", decideur),
            ("Décidée le", _date(d.get("decide_le"))),
            ("Motif de la décision", d.get("motif_decision") or "—"),
        ]
    details = "".join(f"<dt>{e(cle)}</dt><dd>{e(valeur)}</dd>" for cle, valeur in meta)
    resultat = "" if d.get("resultat") is None else f"<h4>Résultat</h4><pre>{e(_json(d['resultat']))}</pre>"
    attestation = ""
    if d.get("attestation"):
        att = d["attestation"]
        attestation = (
            "<h4>Attestation du professionnel (N5)</h4>"
            f'<dl class="meta"><dt>Nom</dt><dd>{e(att.get("nom"))}</dd>'
            f"<dt>Profession</dt><dd>{e(att.get('profession'))}</dd>"
            f"<dt>Document</dt><dd>{e(att.get('reference_document'))}</dd></dl>"
        )
    return (
        f'<article class="carte" id="demande-{e(d["id"])}"><header class="carte-entete">'
        f"{_badge(autonomie or 'T?', CLASSES_AUTONOMIE.get(autonomie or '', ''))}"
        f"<h3><code>{e(d['outil'])}</code></h3>{_badge(libelle, classe)}</header>"
        f'<dl class="meta">{details}</dl><h4>Arguments exacts</h4><pre>{e(_json(d["arguments"]))}</pre>'
        f"{attestation}{resultat}"
        + (_formulaire_decision(d, prefixe, csrf) if statut == "en_attente" else "")
        + "</article>"
    )


def _liste_demandes(demandes: Sequence[Mapping[str, Any]], vide: str, prefixe: str, csrf: str) -> str:
    if not demandes:
        return _vide(vide)
    return '<div class="grille">' + "".join(_carte_demande(d, prefixe, csrf) for d in demandes) + "</div>"


def contenu_approbations(demandes: Sequence[Mapping[str, Any]], *, statut: str, prefixe: str, csrf: str) -> str:
    liens = []
    for code, libelle in FILTRES:
        requete = f"?statut={e(code)}" if code else ""
        courant = ' aria-current="page"' if code == statut else ""
        liens.append(f'<a href="{e(prefixe)}/approbations{requete}"{courant}>{e(libelle)}</a>')
    filtres = "".join(liens)
    intro = (
        "<p class=\"intro\">Approuver exécute l'outil avec les arguments exacts enregistrés, jamais d'autres. "
        "Votre nom signe la décision.</p>"
    )
    if statut:
        corps = _liste_demandes(demandes, "Aucune demande avec ce statut.", prefixe, csrf)
    else:
        en_attente = [d for d in demandes if d["statut"] == "en_attente"]
        traitees = [d for d in demandes if d["statut"] != "en_attente"]
        corps = (
            f"<section><h2>En attente de décision ({len(en_attente)})</h2>"
            f"{_liste_demandes(en_attente, 'Aucune demande en attente.', prefixe, csrf)}</section>"
            "<section><h2>Décisions récentes</h2>"
            f"{_liste_demandes(traitees, 'Aucune décision pour l’instant.', prefixe, csrf)}</section>"
        )
    return f'{intro}<nav class="filtres" aria-label="Filtrer par statut">{filtres}</nav>{corps}'


# -- budgets -------------------------------------------------------------------------------------


def contenu_budgets(budgets: Sequence[Mapping[str, Any]], *, prefixe: str) -> str:
    if not budgets:
        return _vide("Aucun département installé.")
    lignes = []
    for b in budgets:
        niveau, classe = NIVEAUX.get(b["niveau"], (b["niveau"], ""))
        lignes.append(
            f'<tr><td><a href="{e(prefixe)}/departements#{e(b["departement"])}">{e(b["code"])}</a> {e(b["nom"])}</td>'
            f"<td>{_badge(niveau, classe)}</td><td>{_jauge('Jour', b['jour'], b['alerte_pct'])}</td>"
            f"<td>{_jauge('Mois', b['mois'], b['alerte_pct'])}</td><td>{e(b['alerte_pct'])} %</td></tr>"
        )
    return (
        '<p class="intro">Tokens facturables (entrée + sortie) comptés par OPSYS pour chaque département, '
        "face à son budget du jour et du mois.</p>"
        "<table><thead><tr><th>Département</th><th>État</th><th>Jour</th><th>Mois</th><th>Seuil d'alerte</th></tr>"
        f"</thead><tbody>{''.join(lignes)}</tbody></table>"
        '<p class="note">À 100 % du jour ou du mois, les outils autres que la lecture et le calcul (T0) sont '
        "bloqués pour le département.</p>"
    )


# -- paliers de modèles --------------------------------------------------------------------------


def contenu_modeles(
    vue: Mapping[str, Any], *, prefixe: str, csrf: str, saisie: Mapping[str, Mapping[str, str]] | None = None
) -> str:
    saisie = saisie or {}
    intro = (
        '<p class="intro">Les départements demandent un palier (local, rapide, standard, fort), jamais un modèle '
        "précis. Associez ici chaque palier à un fournisseur et à un modèle : changer de fournisseur ne touche aucun "
        "département.</p>"
        '<div class="carte"><p><strong>Modèles locaux (Ollama, vLLM, llama.cpp)</strong> : ces serveurs exposent '
        f"une API compatible OpenAI. Fournisseur <code>{e(FOURNISSEUR_COMPATIBLE_OPENAI)}</code> et base_url du "
        "serveur, par exemple <code>http://ollama:11434/v1</code>.</p>"
        '<p class="note">Le core utilise les fournisseurs directement. La configuration est appliquée à sa '
        "régénération et au redémarrage du service. LiteLLM reste une option explicite.</p></div>"
    )
    manquants = ""
    if vue["manquants"]:
        manquants = (
            '<p class="message message-alerte">Paliers utilisés par des départements mais non configurés : '
            f"{e(', '.join(vue['manquants']))}.</p>"
        )
    cartes = []
    for p in vue["paliers"]:
        nom = p["nom"]
        valeurs = saisie.get(nom) or p["configuration"] or {}
        if p["configuration"]:
            etat = _badge("Configuré", "badge-ok")
        else:
            etat = _badge("Requis, non configuré", "badge-alerte") if p["requis_par"] else _badge("Non configuré")
        requis = ", ".join(f"{r['code']} · {r['usage']}" for r in p["requis_par"]) or "aucun département"
        cartes.append(
            f'<article class="carte" id="palier-{e(nom)}"><header class="carte-entete"><h2>{e(nom)}</h2>{etat}'
            f'</header><p class="note">Utilisé par : {e(requis)}</p>'
            f'<form method="post" action="{e(prefixe)}/modeles/{_segment(nom)}" class="pile">'
            f'<input type="hidden" name="csrf" value="{e(csrf)}">'
            f'<label for="provider-{e(nom)}">Fournisseur</label>'
            f'<input id="provider-{e(nom)}" name="provider" required value="{e(valeurs.get("provider", ""))}" '
            'placeholder="anthropic, openai, custom…">'
            f'<label for="model-{e(nom)}">Modèle</label>'
            f'<input id="model-{e(nom)}" name="model" required value="{e(valeurs.get("model", ""))}">'
            f'<label for="base_url-{e(nom)}">base_url (facultatif, sauf fournisseur '
            f"{e(FOURNISSEUR_COMPATIBLE_OPENAI)})</label>"
            f'<input id="base_url-{e(nom)}" name="base_url" type="url" value="{e(valeurs.get("base_url", ""))}" '
            'placeholder="http://ollama:11434/v1">'
            f'<label for="api_key_env-{e(nom)}">Variable contenant la clé (nom uniquement)</label>'
            f'<input id="api_key_env-{e(nom)}" name="api_key_env" value="{e(valeurs.get("api_key_env", ""))}" '
            'placeholder="OPENAI_API_KEY">'
            f'<label for="fallbacks-{e(nom)}">Paliers de repli explicites (séparés par une virgule)</label>'
            f'<input id="fallbacks-{e(nom)}" name="fallbacks" '
            f'value="{e(", ".join(valeurs.get("fallbacks", [])))}">'
            '<button type="submit" class="principal">Enregistrer</button></form></article>'
        )
    fichier = f'<p class="note">Fichier : <code>{e(vue["fichier"])}</code></p>'
    return f'{intro}{manquants}<div class="grille">{"".join(cartes)}</div>{fichier}'
