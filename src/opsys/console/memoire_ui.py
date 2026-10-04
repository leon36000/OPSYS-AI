"""Recherche et preuves M10 pour la console; toutes les valeurs sont échappées."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .pages import e


def contenu(
    statut: Mapping[str, Any], paquet: Mapping[str, Any], *, prefixe: str, csrf: str, module: str, task: str, files: str
) -> str:
    options = "".join(
        f'<option value="{m}"{" selected" if m == module else ""}>{m}</option>'
        for m in ["OPSYS", "CORE", *(f"M{i}" for i in range(1, 11))]
    )
    recherche = (
        '<section class="carte pile"><h2>Retrouver le contexte d’une tâche</h2>'
        f'<form method="get" action="{e(prefixe)}/memoire" class="pile">'
        f'<label>Module<select name="module">{options}</select></label>'
        f'<label>Tâche ou question<input name="task" value="{e(task)}" maxlength="2000" required></label>'
        f'<label>Fichiers concernés, un par ligne<textarea name="files" maxlength="4000">{e(files)}</textarea></label>'
        '<button type="submit">Rechercher</button></form></section>'
    )
    sante = (
        f'<section class="carte"><h2>Registre de développement</h2>'
        f"<p>Chaîne : {e(statut['status'])} · {e(statut['verified'])} événements vérifiés.</p>"
        f'<p><a class="bouton" href="{e(prefixe)}/memoire/audit">Contrôler les liens et les sources</a></p>'
        f'<p><a class="bouton" href="{e(prefixe)}/memoire/consolidation">Jobs de consolidation planifiée</a></p>'
        f'<form method="post" action="{e(prefixe)}/memoire/scanner">'
        f'<input type="hidden" name="csrf" value="{e(csrf)}">'
        '<button type="submit">Actualiser les sources du dépôt</button></form>'
        "<p>Le scan conserve les références et extraits autorisés des fichiers suivis par Git. "
        "Les sources et leur fraîcheur apparaissent ci-dessous.</p></section>"
    )
    limites = "".join(f"<li>{e(item)}</li>" for item in paquet.get("limitations", []))
    contexte = (
        f'<section class="carte"><h2>Contexte retrouvé</h2><p>Statut : {e(paquet["status"])}</p><ul>{limites}</ul>'
    )
    for item in paquet.get("must_know", []):
        payload = item["payload"]
        texte = payload.get("objectif") or payload.get("summary") or payload.get("context") or ""
        contexte += (
            f"<article><h3>{e(item['kind'])} · {e(item['entity_id'])}</h3>"
            f"<p>Version {e(item['version'])} · {e(item['status'])} · {e(item['recorded_at'])}</p>"
            f"<p>{e(texte)}</p><small>Source : {e(item['event_id'])}</small></article>"
        )
    contexte += "</section>"
    preuves = '<section class="carte"><h2>Sources de fichiers</h2>'
    if not paquet.get("evidence"):
        preuves += "<p>Aucune source de fichier récupérée pour cette recherche.</p>"
    else:
        preuves += "<table><thead><tr><th>Fichier</th><th>Fraîcheur</th><th>Source</th></tr></thead><tbody>"
        preuves += "".join(
            f"<tr><td>{e(p['path'])}</td><td>{e(p['freshness'])}</td><td>{e(p['source_ref'])}</td></tr>"
            for p in paquet["evidence"]
        )
        preuves += "</tbody></table>"
    preuves += "</section>"
    contradictions = '<section class="carte"><h2>Contradictions</h2>'
    if not paquet.get("contradictions"):
        contradictions += "<p>Aucune contradiction retrouvée dans ce contexte.</p>"
    for conflit in paquet.get("contradictions", []):
        contradictions += f"<h3>{e(conflit['claim_key'])}</h3><ul>"
        contradictions += "".join(
            f"<li>{e(p['status'])} : {e(p['summary'])} ({e(p['event_id'])})</li>" for p in conflit["evidence"]
        )
        contradictions += "</ul>"
    return (
        sante
        + recherche
        + contexte
        + preuves
        + contradictions
        + "</section>"
        + '<section class="carte"><h2>Procédures internes</h2>'
        + f'<p><a class="bouton" href="{e(prefixe)}/memoire/procedures">Gérer les procédures M03</a></p></section>'
    )


def audit_contenu(rapport: Mapping[str, Any], prefixe: str) -> str:
    """Rend les constats de l'audit sans jamais afficher le contenu des prompts."""
    compteurs = rapport.get("counts", {})
    lignes_compteurs = "".join(
        f"<li>{e(nom.replace('_', ' '))} : {e(valeur)}</li>" for nom, valeur in compteurs.items()
    )
    findings = []
    for finding in rapport.get("findings", []):
        preuves = finding.get("preuves", [])
        preuves_html = "".join(
            "<li>" + " · ".join(f"{e(nom.replace('_', ' '))} : {e(valeur)}" for nom, valeur in preuve.items()) + "</li>"
            for preuve in preuves
        )
        ids = " · ".join(e(item) for item in finding.get("event_ids", []))
        findings.append(
            f"<article><h3>{e(finding.get('type', 'constat'))}</h3>"
            f"<p>{e(finding.get('detail', ''))}</p>"
            f"<p>Maillons : {ids or 'aucun'}</p><ul>{preuves_html}</ul></article>"
        )
    flags = " · ".join(
        f"{e(nom.replace('_', ' '))} : {e(rapport.get(nom, False))}"
        for nom in ("truncated", "source_scan_truncated", "event_scan_truncated", "relation_scan_truncated")
    )
    return (
        '<section class="carte pile"><h2>Audit de la mémoire de développement</h2>'
        f"<p>Statut : {e(rapport.get('status', 'inconnu'))} · Domaine : {e(rapport.get('domain', ''))}</p>"
        f"<p>Dépôt vérifié : {e(rapport.get('repository') or 'non précisé')} · "
        f"Limite : {e(rapport.get('limit', ''))}</p>"
        f"<p>{e(rapport.get('note', 'Rapport de contrôle non destructif.'))}</p>"
        f"<p>{flags}</p><h3>Comptages</h3><ul>{lignes_compteurs}</ul>"
        f"{''.join(findings) if findings else '<p>Aucun constat dans cette lecture.</p>'}"
        f'<p><a href="{e(prefixe)}/memoire">Retour à la mémoire de développement</a></p></section>'
    )
