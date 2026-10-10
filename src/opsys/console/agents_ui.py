"""Formulaires HTML des profils d'agents, échappés et sans script requis."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import quote

from ..departements import PALIERS, Departement
from .pages import e


def specification(champs: Mapping[str, str]) -> dict[str, Any]:
    spec: dict[str, Any] = {
        cle: champs.get(cle, "") for cle in ("id", "departement", "responsabilite", "palier_modele")
    }
    spec["outils"] = [nom.strip() for nom in champs.get("outils", "").splitlines() if nom.strip()]
    for cle in ("budget_jour", "budget_mois", "limite_tours", "limite_reessais", "limite_concurrence"):
        try:
            spec[cle] = int(champs.get(cle, ""))
        except ValueError as exc:
            raise ValueError(f"{cle} : entier requis") from exc
    declencheurs = []
    for ligne in champs.get("declencheurs", "").splitlines():
        ligne = ligne.strip()
        if not ligne:
            continue
        if ligne == "manuel":
            declencheurs.append({"type": "manuel"})
        elif ligne.startswith("horaire "):
            declencheurs.append({"type": "cron", "expression": ligne[8:]})
        elif ligne.startswith("evenement "):
            declencheurs.append({"type": "evenement", "nom": ligne[10:]})
        elif ligne.split(maxsplit=1)[0] == "canal":
            mots = ligne.split()
            if len(mots) != 4:
                raise ValueError("déclencheur canal : canal sms suivi du compte_id et de l’account_sid")
            declencheurs.append(
                {"type": "canal", "version": 1, "canal": mots[1], "compte_id": mots[2], "account_sid": mots[3]}
            )
        else:
            raise ValueError("déclencheur : manuel, horaire suivi de cinq champs ou evenement suivi du nom")
    spec["declencheurs"] = declencheurs
    return spec


def _choix(valeurs: Sequence[str], selection: str) -> str:
    return "".join(
        f'<option value="{e(v)}"' + (" selected" if v == selection else "") + f">{e(v)}</option>" for v in valeurs
    )


def _champ(nom: str, libelle: str, valeur: Any, *, type_: str = "text", minimum: int | None = None) -> str:
    borne = f' min="{minimum}"' if minimum is not None else ""
    return (
        f'<label for="agent-{e(nom)}">{e(libelle)}</label>'
        f'<input id="agent-{e(nom)}" name="{e(nom)}" type="{e(type_)}" required{borne} value="{e(valeur)}">'
    )


def plafonds_entreprise(politique: Mapping[str, Any] | None, *, prefixe: str, csrf: str) -> str:
    valeurs = politique or {"budget_jour": "", "budget_mois": "", "revision": 0}
    champs = _champ(
        "budget_jour", "Plafond entreprise : tokens par jour", valeurs["budget_jour"], type_="number", minimum=1
    )
    champs += _champ(
        "budget_mois", "Plafond entreprise : tokens par mois", valeurs["budget_mois"], type_="number", minimum=1
    )
    return (
        '<article class="carte"><h2>Plafonds des agents spécialistes</h2>'
        "<p>La réservation applique les plafonds de l’agent, du département et de l’entreprise. "
        "Sans plafond entreprise, toute nouvelle réservation est refusée. "
        "Chaque génération des spécialistes configurés exige une réservation et un usage vérifiable. "
        "Un résultat incertain garde sa réservation. Ces plafonds concernent des tokens estimés, "
        "pas un montant en dollars ni les agents historiques.</p>"
        f'<form method="post" action="{e(prefixe)}/budgets/agents" class="pile">'
        f'<input type="hidden" name="csrf" value="{e(csrf)}">'
        f'<input type="hidden" name="revision_attendue" value="{e(valeurs["revision"])}">'
        f'{champs}<button type="submit" class="principal">Enregistrer les plafonds</button></form></article>'
    )


def contenu(
    profils: Sequence[Mapping[str, Any]],
    deps: Mapping[str, Departement],
    *,
    profil: Mapping[str, Any] | None,
    historique: Sequence[Mapping[str, Any]],
    prefixe: str,
    csrf: str,
    reservations_actives: Mapping[str, Any] | None = None,
) -> str:
    intro = (
        '<p class="intro">Configurez plusieurs spécialistes par département avec leurs responsabilités, '
        "outils et plafonds de tokens. L’activation enregistre le profil ; son chargement dans le core "
        "nécessite la synchronisation de la configuration. Elle ne signifie pas qu’une tâche tourne.</p>"
    )
    lignes = "".join(
        f'<tr><td><a href="{e(prefixe)}/agents/{e(quote(p["id"], safe=""))}">{e(p["id"])}</a></td>'
        f"<td>{e(p['departement'])}</td><td>{e(p['responsabilite'])}</td>"
        f"<td>{'Activé' if p['actif'] else 'Désactivé'}</td><td>{e(p['revision'])}</td></tr>"
        for p in profils
    )
    liste = (
        (
            "<table><thead><tr><th>Agent</th><th>Département</th><th>Responsabilité</th>"
            f"<th>Profil</th><th>Révision</th></tr></thead><tbody>{lignes}</tbody></table>"
        )
        if profils
        else "<p>Aucun agent configuré.</p>"
    )
    valeurs = profil or {
        "id": "",
        "departement": next(iter(deps), ""),
        "palier_modele": "rapide",
        "outils": [],
        "budget_jour": 1000,
        "budget_mois": 10000,
        "limite_tours": 8,
        "limite_reessais": 2,
        "limite_concurrence": 1,
        "declencheurs": [{"type": "manuel"}],
    }
    action = f"{prefixe}/agents" + (f"/{quote(profil['id'], safe='')}" if profil else "")
    caches = (
        f'<input type="hidden" name="csrf" value="{e(csrf)}">'
        f'<input type="hidden" name="mutation_id" value="{uuid.uuid4()}">'
    )
    if profil:
        caches += f'<input type="hidden" name="revision_attendue" value="{e(profil["revision"])}">'
    champs = _champ("id", "Identifiant stable", valeurs["id"])
    if profil:
        champs = champs.replace('name="id"', 'name="id" readonly')
    champs += (
        f'<label for="agent-departement">Département</label><select id="agent-departement" name="departement">'
        f"{_choix(list(deps), valeurs['departement'])}</select>"
    )
    champs += (
        f'<label for="agent-responsabilite">Responsabilité</label><textarea id="agent-responsabilite" '
        f'name="responsabilite" required maxlength="2000">{e(valeurs.get("responsabilite", ""))}</textarea>'
    )
    champs += (
        '<label for="agent-palier_modele">Palier de modèle</label>'
        '<select id="agent-palier_modele" name="palier_modele">'
        f"{_choix(PALIERS, valeurs['palier_modele'])}</select>"
    )
    outils = "\n".join(valeurs["outils"])
    champs += (
        f'<label for="agent-outils">Outils autorisés (un nom par ligne)</label>'
        f'<textarea id="agent-outils" name="outils">{e(outils)}</textarea>'
    )
    for nom, label in (
        ("budget_jour", "Tokens par jour"),
        ("budget_mois", "Tokens par mois"),
        ("limite_tours", "Tours maximum"),
        ("limite_reessais", "Réessais maximum"),
        ("limite_concurrence", "Exécutions simultanées maximum"),
    ):
        champs += _champ(nom, label, valeurs[nom], type_="number", minimum=0 if nom == "limite_reessais" else 1)
    declencheurs = "\n".join(
        "manuel"
        if d["type"] == "manuel"
        else "horaire " + d["expression"]
        if d["type"] == "cron"
        else f"canal {d['canal']} {d['compte_id']} {d['account_sid']}"
        if d["type"] == "canal"
        else "evenement " + d["nom"]
        for d in valeurs["declencheurs"]
    )
    champs += (
        f'<label for="agent-declencheurs">Déclencheurs (une ligne par déclencheur)</label>'
        f'<textarea id="agent-declencheurs" name="declencheurs" required>{e(declencheurs)}</textarea>'
        '<p class="note">manuel ; horaire suivi de cinq champs ; '
        "evenement suivi du nom déclaré par le département ; "
        "canal sms suivi du compte_id puis de l’account_sid (quatre mots ; "
        "profil m01-front-office, déclencheur unique).</p>"
    )
    formulaire = (
        f'<article class="carte"><h2>{"Modifier" if profil else "Créer"} un profil</h2>'
        f'<form method="post" action="{e(action)}" class="pile">{caches}{champs}'
        '<button class="principal" type="submit">Enregistrer</button></form></article>'
    )
    choix_outils = "".join(
        f"<details><summary>{e(ident)}</summary><p>{e(', '.join(o.nom for o in dep.charger_outils()))}</p></details>"
        for ident, dep in deps.items()
    )
    detail = ""
    if profil:

        def commande() -> str:
            return (
                f'<input type="hidden" name="csrf" value="{e(csrf)}">'
                f'<input type="hidden" name="mutation_id" value="{uuid.uuid4()}">'
                f'<input type="hidden" name="revision_attendue" value="{e(profil["revision"])}">'
            )

        detail = (
            f'<form method="post" action="{e(action)}/activation">{commande()}'
            f'<input type="hidden" name="actif" value="{"false" if profil["actif"] else "true"}">'
            f'<button type="submit">{"Désactiver" if profil["actif"] else "Activer"} le profil</button></form>'
            f'<form method="post" action="{e(action)}/archivage">{commande()}'
            '<button type="submit">Archiver le profil (historique conservé)</button></form>'
            f"<h2>Historique</h2><ul>"
            + "".join(
                f"<li>Révision {e(h['revision'])} — {e(h['modifie_par'])} — {e(h['modifie_le'])}</li>"
                for h in historique
            )
            + "</ul>"
        )
    reservations = ""
    if profil:
        observation = reservations_actives or {"reservations": [], "total": 0, "retournees": 0, "omises": 0}
        items = observation.get("reservations")
        items = items if isinstance(items, list) else []
        reservations = (
            '<section class="carte"><h2>Réservations runtime actives</h2>'
            '<p>Utilisation fournisseur à vérifier. L’enveloppe réservée est conservée jusqu’au rapprochement. '
            'L’âge est calculé selon l’horloge UTC du serveur.</p>'
        )
        if items:
            reservations += (
                f'<p>{e(observation.get("retournees", len(items)))} affichée(s) sur '
                f'{e(observation.get("total", len(items)))}; '
                f'{e(observation.get("omises", 0))} omise(s).</p>'
                '<div class="table-defilante"><table><thead><tr><th>Profil</th><th>Exécution</th>'
                '<th>Cycle</th><th>Âge (UTC serveur)</th><th>Enveloppe (tokens)</th><th>État d’usage</th>'
                '<th>Dernier état</th><th>Horodatage du dernier état</th><th>Rapprochement</th></tr></thead><tbody>'
            )
            for item in items:
                if not isinstance(item, Mapping):
                    continue
                age = item.get("age_secondes")
                if type(age) is int and age >= 0:
                    age_affiche = f"{age} s"
                elif item.get("age_statut") == "INCONNU_DATE_FUTURE":
                    age_affiche = "INCONNU — date future selon l’horloge serveur"
                else:
                    age_affiche = "INCONNU — horodatage invalide ou sans fuseau"
                cycle = item.get("cycle_id") or "cycle legacy non renseigné"
                reference = e(item.get("reservation_id", ""))
                action = f'{e(prefixe)}/agents/{e(quote(profil["id"], safe=""))}/reservations/{reference}/concilier'
                reservations += (
                    f'<tr><td>{e(item.get("agent_id"))}</td><td>{e(item.get("execution_id"))}</td>'
                    f'<td>{e(cycle)}</td><td>{e(age_affiche)}</td><td>{e(item.get("tokens_plafond"))}</td>'
                    f'<td>{"Inconnu — à rapprocher" if item.get("usage") == "INCONNU" else e(item.get("usage"))}</td>'
                    f'<td>{e(item.get("dernier_evenement", "INCONNU"))}</td>'
                    f'<td>{e(item.get("derniere_transition_le", "INCONNU"))}</td>'
                    '<td><details><summary>Déclarer un rapprochement</summary>'
                    '<p>Consultez le relevé final du fournisseur et saisissez le total exact attribuable à ce cycle. '
                    'Vous devez déclarer que cet appel fournisseur est terminé et ne peut plus générer de frais. '
                    'OPSYS ne vérifie ni le relevé ni cette déclaration humaine; un propriétaire reste responsable '
                    'de son exactitude.</p>'
                    f'<form method="post" action="{action}" class="pile">'
                    f'<input type="hidden" name="csrf" value="{e(csrf)}">'
                    '<label>Tokens exacts indiqués dans le relevé'
                    '<input type="number" name="tokens_reels" min="0" step="1" required></label>'
                    '<label>Identifiant court non secret du relevé fournisseur (120 caractères; '
                    'OPSYS ne détecte pas les secrets)'
                    '<input type="text" name="reference_releve" maxlength="120" required></label>'
                    '<label><input type="checkbox" name="attestation" value="oui" required>'
                    'Je déclare avoir consulté le relevé final, reporté son total exact et confirmé que cet appel '
                    'est terminé.</label>'
                    '<p>Un relevé intermédiaire ne suffit pas. Si la finalité ou le total reste inconnu, '
                    'ne soumettez pas : '
                    'l’enveloppe reste réservée.</p>'
                    '<button type="submit">Enregistrer cette déclaration manuelle</button></form></details></td></tr>'
                )
            reservations += "</tbody></table></div>"
        else:
            reservations += "<p>Aucune réservation active pour ce profil.</p>"
        reservations += "</section>"
    return intro + liste + formulaire + detail + reservations + "<h2>Outils disponibles</h2>" + choix_outils


def demandes_cron(profil: Mapping[str, Any], *, prefixe: str, csrf: str) -> str:
    """Formulaires humains pour préparer/retirer une intention; aucune activation Core."""
    declencheurs = profil.get("declencheurs")
    a_cron = isinstance(declencheurs, list) and any(
        isinstance(item, Mapping) and item.get("type") == "cron" for item in declencheurs
    )
    ident = quote(str(profil["id"]), safe="")
    action = f"{e(prefixe)}/agents/{ident}/declencheurs/cron"

    def champs_communs() -> str:
        return (
            f'<input type="hidden" name="csrf" value="{e(csrf)}">'
            f'<input type="hidden" name="mutation_id" value="{uuid.uuid4()}">'
            f'<input type="hidden" name="revision_attendue" value="{e(profil["revision"])}">'
            '<label><input type="checkbox" name="confirme" value="oui" required>'
            "Je confirme préparer une demande humaine; cela ne crée ni n’active une tâche Core.</label>"
        )

    demander = ""
    if a_cron:
        demander = (
            f'<form method="post" action="{action}/demander" class="pile">{champs_communs()}'
            '<label for="cron-fuseau">Fuseau horaire IANA</label>'
            '<input id="cron-fuseau" name="fuseau" type="text" maxlength="64" required '
            'placeholder="America/Toronto">'
            '<button class="principal" type="submit">Préparer la demande cron</button></form>'
        )
    else:
        demander = (
            "<p>Aucun déclencheur cron ne figure dans la révision courante. Les anciennes intentions "
            "peuvent toujours recevoir une demande de retrait.</p>"
        )
    return (
        '<article class="carte"><h2>Déclencheurs planifiés</h2>'
        "<p>Cette action prépare une intention durable liée à cette révision du profil. Un raccordement hôte "
        "reste requis; aucune planification, aucun agent et aucun fournisseur ne sont activés ici.</p>"
        f"{demander}"
        f'<form method="post" action="{action}/retirer" class="pile">{champs_communs()}'
        '<button type="submit">Demander le retrait des intentions cron</button></form></article>'
    )


def grant_cfo(
    profil: Mapping[str, Any], grant: Mapping[str, Any] | None, *, prefixe: str, csrf: str, instance_configuree: bool
) -> str:
    """Owner/admin control for the two read-only CFO preparation tools only."""
    if profil.get("departement") != "m05-financecore":
        return ""
    action = f"{e(prefixe)}/agents/{quote(profil['id'], safe='')}/droit-cfo"
    utc_today = dt.datetime.now(dt.UTC).date()
    date_debut = grant["report_date_start"] if grant else utc_today.isoformat()
    date_fin = grant["report_date_end"] if grant else (utc_today + dt.timedelta(days=30)).isoformat()
    outils = grant["tools"] if grant else ["m5_preparer_dossier_decision_cfo", "m5_preparer_decision_capital"]
    rapports_par_jour = grant["reports_per_day"] if grant else 3
    expire_le = grant["expires_at"] if grant else ""
    if not instance_configuree:
        return (
            '<article class="carte"><h2>Lecture CFO préparatoire</h2>'
            "<p>Grant indisponible : le premier jalon exige un stockage SQLite configuré.</p></article>"
        )
    form = (
        '<article class="carte"><h2>Lecture CFO préparatoire</h2>'
        "<p>Grant humain limité à cette instance et à ces deux outils en lecture seule; "
        "toute nouvelle révision du profil l’invalide. Aucun autre registre ou département.</p>"
        "<p>Les rapports utilisent les données financières de l’instance entière. Les dates ci-dessous "
        "limitent la date du rapport, sans exclure les opérations plus anciennes.</p>"
        f'<form method="post" action="{action}" class="pile">'
        f'<input type="hidden" name="csrf" value="{e(csrf)}">'
        f'<input type="hidden" name="revision_attendue" value="{e(profil["revision"])}">'
        f'<input type="hidden" name="version_grant_attendue" value="{e(grant["version"] if grant else 0)}">'
        '<label for="cfo-outils">Outils accordés (un nom autorisé par ligne)</label>'
        f'<textarea id="cfo-outils" name="outils" required>{e(chr(10).join(outils))}</textarea>'
        f'<label for="cfo-date-debut">Première date de rapport permise</label>'
        f'<input id="cfo-date-debut" type="date" name="date_debut_rapport" value="{e(date_debut)}" required>'
        f'<label for="cfo-date-fin">Dernière date de rapport permise</label>'
        f'<input id="cfo-date-fin" type="date" name="date_fin_rapport" value="{e(date_fin)}" required>'
        "<p>La fenêtre par défaut couvre les 30 prochains jours UTC; 90 jours maximum par grant.</p>"
        f"{_champ('rapports_par_jour', 'Rapports maximum par jour', rapports_par_jour, type_='number', minimum=1)}"
        "<p>Cette limite compte les autorisations de rapport émises, même si le rapport n’aboutit pas. "
        "Renouveler le droit ne remet pas ce compte quotidien à zéro.</p>"
        f"{_champ('expire_le', 'Expiration UTC ISO (vide = 30 jours)', expire_le)}"
        '<button class="principal" type="submit">Accorder / renouveler le grant</button></form>'
    )
    if grant:
        statut = "actif" if grant.get("active") else "révoqué"
        form += (
            f"<p>Grant {statut} version {e(grant['version'])} — expire {e(grant['expires_at'])} — "
            f"{e(', '.join(grant['tools']))}</p>"
            f"<p>Dates de rapport permises : {e(grant['report_date_start'])} à {e(grant['report_date_end'])}.</p>"
        )
        if grant.get("active"):
            form += (
                f'<form method="post" action="{action}/retrait"><input type="hidden" name="csrf" value="{e(csrf)}">'
                f'<input type="hidden" name="version_grant_attendue" value="{e(grant["version"])}">'
                '<button type="submit">Révoquer</button></form>'
            )
    return form + "</article>"
