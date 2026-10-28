# Raccord pour le coordinateur

## Commit de raccord commun (isolé)

`RACCORD COMMUN console : servir les huit outils du dossier de paie M5 par metier.executer` — `src/opsys/console/metier.py` :
noms des huit outils ajoutés à `LECTURES`/`COMMANDES` et au branchement qui donne le port privé M4 (comme `m5_preparer_brut_regulier`).
Aucune règle de droits, de routage ni de CLI modifiée. Sans ce commit, la console ne peut pas exécuter les outils ; la surface n'est
« livrée » que pour l'application intégrée avec ce commit (c'est ainsi qu'elle a été exercée).

Le routeur `paie_dossier_ui` est monté depuis `paie_ui.py` (module M5 existant) : aucun changement à `application.py`.

## Ce qui n'a pas été fait (réservé)

- Aucun grant Core ni allowlist d'agent. Les huit outils sont **listés** sur le serveur MCP `m05-financecore` (comme le brut régulier) ; leur appel
  est refusé (`test_transport_mcp_http_un_agent_ne_recoit_ni_montant_ni_ecriture`). Si le coordinateur veut les masquer aux agents, deux options propres :
  ne pas les inclure dans les profils Core, ou ajouter leurs noms à la liste « port console privé » de `Capacites.appeler` (`port_console_prive_requis`),
  qui refuse avant toute normalisation ou réclamation — durcissement proposé, non appliqué (`capacites.py` est une surface partagée).
- Aucune modification de `core/**`, `agents.py`, `serveur_mcp.py`, `openclaw.py`, `schema.py`, `application.py`, CLI, installation.

## Intégration à démontrer après fusion avec M4/CRM

Rejouer `tests/test_console_paie_dossier.py` sur la tête portant les visites M4 : ancien cas régulier préservé, deux visites sans durée fantôme,
source corrigée détectée (`SOURCE-HEURES_M4-MODIFIEE`), dossier historique conservé.

## Déploiement

Déposer les quatre PDF d'admission (noms et SHA-256 dans `contracts/admission_paie_preparatoire.v1.json`) dans `departments/m05-financecore/contracts/captures-paie/`.
Sans eux, l'admission refuse avec `CAPTURE_INDISPONIBLE_OU_LIEE` et le dossier reste `ADMISSION_REFUSEE` (conservable comme diagnostic, jamais revu comme complet).
Le chiffrement exige `cryptography` (extra `ingestion`, présent dans `requirements-runtime.lock.txt`) ; sans lui, écriture et lecture sont refusées (fail-closed).
