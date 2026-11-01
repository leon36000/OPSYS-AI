"""PLAN de déploiement d'un paquet de site vers le VPS du client, et configuration Caddy (décision r6, exigence 4).

Ce module ÉCRIT un plan ; il n'exécute rien. Il n'ouvre aucune connexion, ne lance aucun processus, n'importe ni
`subprocess`, ni `socket`, ni client SSH (un test le vérifie sur la source). Chaque étape porte la commande exacte
qu'une personne exécutera à la main, après l'approbation de la direction (publication publique : N3+, voir
`service.demander_publication` et docs/sites-web.md).

Modèle (R4 §1.3) : utilisateur NON ROOT dédié (`opsys-deploy`, clé ed25519), arborescence
`<racine>/releases/<version>` et lien symbolique `<racine>/current` basculé atomiquement (`ln -sfn` puis `mv -T`),
Caddy (HTTPS automatique par ACME) qui sert `current`, en-têtes de sécurité, retour arrière en une commande vers la
version précédente, N versions conservées. Le seul privilège demandé est `systemctl reload caddy` (liste blanche
sudoers, prérequis documenté).

Toute valeur insérée dans une commande est validée par une expression stricte AVANT d'être citée (`shlex.quote`) :
un hôte, un utilisateur ou une racine qui contiendrait `;`, une espace ou `..` est refusé, jamais échappé en silence.

Module pur : aucune entrée-sortie.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Mapping
from typing import Any

from .paquet import FICHIER_SOMMES, version_valide
from .rendu_statique import politique_csp

SCHEMA_PLAN = "opsys.site-plan-deploiement/v1"
STATUT_PLAN = "PLAN_NON_EXECUTE"

REJ_UTILISATEUR_ROOT = "REJ-DEPLOI-UTILISATEUR-ROOT"
REJ_UTILISATEUR = "REJ-DEPLOI-UTILISATEUR-INVALIDE"
REJ_HOTE = "REJ-DEPLOI-HOTE-INVALIDE"
REJ_PORT = "REJ-DEPLOI-PORT-INVALIDE"
REJ_RACINE = "REJ-DEPLOI-RACINE-INVALIDE"
REJ_CONSERVATION = "REJ-DEPLOI-CONSERVATION-INVALIDE"
REJ_VERSION = "REJ-DEPLOI-VERSION-INVALIDE"
REJ_CIBLE = "REJ-DEPLOI-CIBLE-INVALIDE"

UTILISATEUR_DEFAUT = "opsys-deploy"
CONSERVATION_DEFAUT = 5
_UTILISATEUR = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
_HOTE = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_RACINES_PERMISES = ("/srv/sites/", "/var/www/")
CHAMPS_CIBLE = ("hote", "utilisateur", "port", "racine", "versions_conservees", "version_precedente")

EN_TETES_SECURITE = (
    ("Strict-Transport-Security", "max-age=31536000; includeSubDomains"),
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "strict-origin-when-cross-origin"),
    ("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()"),
    ("Cross-Origin-Opener-Policy", "same-origin"),
)


def valider_cible(cible: Any, domaine: str) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    """(cible normalisée, refus). Défauts explicites et documentés : utilisateur `opsys-deploy`, port 22, racine
    `/srv/sites/<domaine>`, 5 versions conservées. Aucun défaut pour l'hôte : il vient de la personne qui demande."""
    if not isinstance(cible, Mapping):
        return None, [_refus(REJ_CIBLE, "$.cible", "objet {hote, utilisateur, port, racine, ...} attendu")]
    refus: list[dict[str, str]] = []
    inconnus = sorted(set(cible) - set(CHAMPS_CIBLE))
    if inconnus:
        refus.append(_refus(REJ_CIBLE, "$.cible", f"champs inconnus : {inconnus}"))
    hote = cible.get("hote")
    if not isinstance(hote, str) or not _HOTE.match(hote):
        refus.append(_refus(REJ_HOTE, "$.cible.hote", "nom d'hôte DNS en minuscules attendu (aucune IP, aucun espace)"))
    utilisateur = cible.get("utilisateur", UTILISATEUR_DEFAUT)
    if utilisateur == "root":
        refus.append(_refus(
            REJ_UTILISATEUR_ROOT, "$.cible.utilisateur",
            "jamais root : un utilisateur dédié non root (opsys-deploy) avec une liste blanche sudoers",
        ))
    elif not isinstance(utilisateur, str) or not _UTILISATEUR.match(utilisateur):
        refus.append(_refus(REJ_UTILISATEUR, "$.cible.utilisateur", "nom d'utilisateur POSIX attendu"))
    port = cible.get("port", 22)
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        refus.append(_refus(REJ_PORT, "$.cible.port", "port entier 1 à 65535"))
    racine = cible.get("racine", f"/srv/sites/{domaine}")
    if (
        not isinstance(racine, str) or not racine.startswith(_RACINES_PERMISES) or ".." in racine.split("/")
        or not re.fullmatch(r"/[a-z0-9._/-]+", racine) or racine.rstrip("/").split("/")[-1] != domaine
    ):
        refus.append(_refus(
            REJ_RACINE, "$.cible.racine",
            f"chemin absolu sous {list(_RACINES_PERMISES)}, sans « .. », terminé par le domaine du site ({domaine})",
        ))
    conservees = cible.get("versions_conservees", CONSERVATION_DEFAUT)
    if not isinstance(conservees, int) or isinstance(conservees, bool) or not 2 <= conservees <= 20:
        refus.append(_refus(REJ_CONSERVATION, "$.cible.versions_conservees", "entier 2 à 20 (retour arrière possible)"))
    precedente = cible.get("version_precedente")
    if precedente is not None and not version_valide(precedente):
        refus.append(_refus(REJ_VERSION, "$.cible.version_precedente", "version AAAAMMJJTHHMMSSZ attendue"))
    if refus:
        return None, refus
    return {
        "hote": hote, "utilisateur": utilisateur, "port": port, "racine": racine.rstrip("/"),
        "versions_conservees": conservees, "version_precedente": precedente,
    }, []


def _refus(code: str, chemin: str, detail: str) -> dict[str, str]:
    return {"code": code, "chemin": chemin, "detail": detail}


def caddyfile(domaine: str, racine: str, css: str, *, site_id: str, version: str) -> str:
    """Configuration Caddy du site : HTTPS automatique (ACME, aucun certificat manuel), service de `current`,
    compression, en-têtes de sécurité et CSP stricte, pages 404 par langue, redirection de `www`."""
    en_tetes = "\n".join(f'\t\t{nom} "{valeur}"' for nom, valeur in EN_TETES_SECURITE)
    csp = politique_csp(css, en_tete_http=True)
    return (
        f"# Généré par OPSYS-AI M7 pour {site_id}, version {version}.\n"
        "# Ne pas modifier à la main : régénérer le paquet.\n"
        f"# Inclus par la configuration principale de Caddy (import {racine.rsplit('/', 1)[0]}/*/Caddyfile).\n"
        f"{domaine} {{\n"
        f"\troot * {racine}/current\n"
        "\tencode zstd gzip\n"
        "\tfile_server\n"
        "\theader {\n"
        f"{en_tetes}\n"
        f'\t\tContent-Security-Policy "{csp}"\n'
        "\t\t-Server\n"
        "\t}\n"
        "\t@ressources path /favicon.svg /images/*\n"
        '\theader @ressources Cache-Control "public, max-age=604800"\n'
        "\thandle_errors {\n"
        "\t\t@introuvable_en {\n"
        "\t\t\texpression {err.status_code} == 404\n"
        "\t\t\tpath /en/*\n"
        "\t\t}\n"
        "\t\thandle @introuvable_en {\n"
        "\t\t\trewrite * /en/404.html\n"
        "\t\t\tfile_server\n"
        "\t\t}\n"
        "\t\t@introuvable expression {err.status_code} == 404\n"
        "\t\thandle @introuvable {\n"
        "\t\t\trewrite * /404.html\n"
        "\t\t\tfile_server\n"
        "\t\t}\n"
        "\t\thandle {\n"
        '\t\t\trespond "{err.status_code} {err.status_text}"\n'
        "\t\t}\n"
        "\t}\n"
        "}\n"
        f"www.{domaine} {{\n"
        f"\tredir https://{domaine}{{uri}} permanent\n"
        "}\n"
    )


def planifier_deploiement(manifeste: Mapping[str, Any], cible: Mapping[str, Any], css: str) -> dict[str, Any]:
    """Le plan, jamais exécuté : prérequis, étapes ordonnées (commande exacte, effet, réversibilité), vérifications
    après bascule, retour arrière, configuration Caddy. `cible` doit être normalisée par `valider_cible`."""
    domaine, version, site_id = manifeste["domaine"], manifeste["version"], manifeste["site_id"]
    archive, empreinte = manifeste["archive"]["nom"], manifeste["archive"]["sha256"]
    q = shlex.quote
    racine = cible["racine"]
    distant = f"{cible['utilisateur']}@{cible['hote']}"
    ssh = f"ssh -p {cible['port']} {q(distant)}"
    scp = f"scp -P {cible['port']}"
    release = f"{racine}/releases/{version}"
    url = f"https://{domaine}"

    def distante(commande: str) -> str:
        return f"{ssh} {q(commande)}"

    bascule = f"cd {q(racine)} && ln -sfn {q('releases/' + version)} current.tmp && mv -Tf current.tmp current"
    recharger = "sudo -n /usr/bin/systemctl reload caddy"
    etapes = [
        ("verifier_paquet_local", "Vérifier l'empreinte de l'archive approuvée avant tout envoi.",
         f"echo {q(empreinte + '  ' + archive)} | sha256sum -c -", "lecture", True),
        ("creer_repertoire_version", "Créer le répertoire de la nouvelle version (aucune version existante touchée).",
         distante(f"mkdir -p {q(release)}"), "écriture serveur", True),
        ("envoyer_archive", "Copier l'archive dans le répertoire de version.",
         f"{scp} {q(archive)} {q(distant + ':' + release + '/paquet.tar.gz')}", "écriture serveur", True),
        ("extraire_et_verifier",
         "Extraire puis vérifier chaque fichier contre SHA256SUMS ; arrêt si une somme diffère.",
         distante(f"cd {q(release)} && tar -xzf paquet.tar.gz && rm paquet.tar.gz && sha256sum -c {FICHIER_SOMMES}"),
         "écriture serveur", True),
        ("installer_configuration_caddy", "Copier puis valider la configuration Caddy du site (sans recharger).",
         f"{scp} Caddyfile {q(distant + ':' + racine + '/Caddyfile')} && "
         + distante(f"caddy validate --adapter caddyfile --config {q(racine + '/Caddyfile')}"),
         "écriture serveur", True),
        ("basculer_current", "Bascule ATOMIQUE du lien current vers la nouvelle version (publication publique).",
         distante(bascule), "publication", True),
        ("recharger_caddy", "Recharger Caddy (seule commande privilégiée, liste blanche sudoers).",
         distante(recharger), "publication", True),
        ("purger_anciennes_versions",
         f"Garder les {cible['versions_conservees']} versions les plus récentes ; ne jamais supprimer current.",
         distante(
             f"cd {q(racine + '/releases')} && ls -1 | sort | head -n -{cible['versions_conservees']} "
             f"| grep -vx {q(version)} | grep -vx \"$(basename \"$(readlink ../current)\")\" | xargs -r rm -rf --"
         ),
         "suppression serveur", False),
    ]
    verifications = [
        ("accueil_fr", f"curl -fsS -o /dev/null -w '%{{http_code}}' {q(url + '/')}", "200"),
        ("accueil_en", f"curl -fsS -o /dev/null -w '%{{http_code}}' {q(url + '/en/')}", "200"),
        ("plan_du_site", f"curl -fsS -o /dev/null -w '%{{http_code}}' {q(url + '/sitemap.xml')}", "200"),
        ("robots", f"curl -fsS -o /dev/null -w '%{{http_code}}' {q(url + '/robots.txt')}", "200"),
        ("page_introuvable", f"curl -s -o /dev/null -w '%{{http_code}}' {q(url + '/page-inexistante-opsys/')}", "404"),
        ("en_tetes_securite", f"curl -fsSI {q(url + '/')} | grep -ci -e strict-transport-security "
                              "-e content-security-policy -e x-content-type-options", "3"),
        ("certificat", f"echo | openssl s_client -connect {q(domaine + ':443')} -servername {q(domaine)} 2>/dev/null "
                       "| openssl x509 -noout -checkend 1209600", "Certificate will not expire"),
        ("redirection_www", f"curl -s -o /dev/null -w '%{{http_code}}' {q('https://www.' + domaine + '/')}", "301"),
    ]
    if cible["version_precedente"]:
        precedente = cible["version_precedente"]
        retour = distante(
            f"cd {q(racine)} && ln -sfn {q('releases/' + precedente)} current.tmp && mv -Tf current.tmp current && "
            f"{recharger}"
        )
    else:
        retour = distante(
            f"cd {q(racine)} && P=$(ls -1 releases | sort | grep -vx {q(version)} | tail -n 1) && "
            f'test -n "$P" && ln -sfn "releases/$P" current.tmp && mv -Tf current.tmp current && {recharger}'
        )
    return {
        "schema_plan": SCHEMA_PLAN,
        "statut": STATUT_PLAN,
        "execute": False,
        "site_id": site_id,
        "domaine": domaine,
        "version": version,
        "archive": dict(manifeste["archive"]),
        "cible": dict(cible),
        "niveau_publication": "N3",
        "approbation": (
            "La bascule de current publie le site : décision de la direction (N3+), demandée par "
            "m7_demander_publication_site ; OPSYS n'exécute aucune étape de ce plan."
        ),
        "prerequis": [
            "Exécuter les étapes depuis le dossier du paquet préparé (archive, Caddyfile), par une personne autorisée.",
            f"Utilisateur non root « {cible['utilisateur']} » créé par l'administrateur du serveur, clé publique "
            "ed25519 d'OPSYS dans ~/.ssh/authorized_keys, aucun mot de passe.",
            f"sudoers : « {cible['utilisateur']} ALL=(root) NOPASSWD: /usr/bin/systemctl reload caddy », rien d'autre.",
            f"Répertoire {racine} appartenant à {cible['utilisateur']} ; Caddy lit {racine}/current.",
            f"Configuration principale de Caddy : « import {racine.rsplit('/', 1)[0]}/*/Caddyfile ».",
            f"DNS : {domaine} et www.{domaine} pointent vers {cible['hote']} ; ports 80 et 443 ouverts (ACME).",
            "Caddy 2 installé par l'administrateur ; renouvellement ACME automatique (aucun certificat manuel).",
        ],
        "etapes": [
            {"ordre": n, "nom": nom, "description": desc, "commande": cmd, "effet": effet, "reversible": rev}
            for n, (nom, desc, cmd, effet, rev) in enumerate(etapes, start=1)
        ],
        "verifications_apres": [
            {"nom": nom, "commande": cmd, "attendu": attendu} for nom, cmd, attendu in verifications
        ],
        "retour_arriere": {
            "description": "Rebascule atomique de current vers la version précédente conservée, puis rechargement.",
            "commande": retour,
        },
        "caddyfile": caddyfile(domaine, racine, css, site_id=site_id, version=version),
    }


def plan_lisible(plan: Mapping[str, Any]) -> str:
    """Le plan en Markdown court, pour la personne qui l'exécutera (et la direction qui l'approuve)."""
    lignes = [
        f"# Plan de déploiement — {plan['site_id']} {plan['version']}",
        "",
        f"Statut : **{plan['statut']}** (rien n'a été exécuté par OPSYS). {plan['approbation']}",
        "",
        f"Archive : `{plan['archive']['nom']}` — SHA-256 `{plan['archive']['sha256']}`.",
        "",
        "## Prérequis",
        *[f"- {p}" for p in plan["prerequis"]],
        "",
        "## Étapes",
    ]
    for etape in plan["etapes"]:
        rev = "réversible" if etape["reversible"] else "IRRÉVERSIBLE"
        lignes += [f"{etape['ordre']}. {etape['description']} ({etape['effet']}, {rev})", "", "```sh",
                   etape["commande"], "```", ""]
    lignes.append("## Vérifications après bascule")
    lignes += [f"- {v['nom']} : `{v['commande']}` → attendu `{v['attendu']}`" for v in plan["verifications_apres"]]
    lignes += ["", "## Retour arrière", plan["retour_arriere"]["description"], "", "```sh",
               plan["retour_arriere"]["commande"], "```", ""]
    return "\n".join(lignes)
