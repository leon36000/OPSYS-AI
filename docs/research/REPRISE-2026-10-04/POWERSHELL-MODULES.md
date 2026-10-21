# Chargement des modules ACL Windows — 4 octobre 2026

La [PR #623](https://github.com/leon36000/OPSYS-AI/pull/623) est publiée. Sur
`669f32165e30aaf8e172a919fe9265a01e6b9939`, le
[job Windows 111335542202](https://github.com/leon36000/OPSYS-AI/actions/runs/37168050951/job/111335542202)
refuse le chargement de `Microsoft.PowerShell.Security` pour `Get-Acl`.
Le script se parse désormais ; cet échec est distinct du délimiteur typographique corrigé.

Le helper préférait Windows PowerShell 5 alors que le shell du runner est PowerShell 7.
Un `PSModulePath` hérité peut lui faire charger les modules de l'autre version. Le correctif
préfère `pwsh`, conserve le repli `powershell`, retire uniquement `PSModulePath` de
l'environnement du processus enfant et importe le manifeste de sécurité depuis son propre
`$PSHOME/Modules`. Le script limite son chemin de modules à ce répertoire. Il conserve la
vérification de DACL, le SID courant, le propriétaire et le refus avant écriture si le
module ou la protection échoue. Aucun droit élargi et aucun test Windows ignoré.

Deux nouveaux cas vérifient le choix du runtime, son repli, la transmission du chemin avec
espaces/accent, la conservation des autres variables et l'environnement parent inchangé.
Le test natif Everyone choisit également `pwsh` en priorité et n'hérite pas du chemin de modules.

## Preuves et limites

- `qa-r23` : Ruff rouge sur l'orthographe native d'une variable d'environnement dans le test.
  Reçu conservé ; corrigé explicitement sans désactivation de règle.
- `qa-r24` : 118 tests réussis avant l'import explicite du module ; source intermédiaire.
- `qa-r26` : source finale, Ruff réussi et trois fichiers entiers,
  **118 réussis, aucun ignoré** sous Linux. Les doubles Windows ne qualifient pas les ACL natives.
- `qa-r25` et `qa-r27` : scan Gitleaks du helper de production, aucune alerte brute.
  Cela ne remplace pas le scan des autres fichiers et son marqueur fictif déjà documenté.

Sur le commit `31dba4efff8f764592375b1b72c9ca8427d23a31`, le parcours
`e2e-core` **37167863144** passe, ainsi que la construction et les six lots unitaires du core.
Ces résultats restent attribués à ce commit. La validation `tests-opsys` est encore distincte.
Sur `669f3216`, l'installation macOS et l'analyse passent ; Windows échoue et Linux est encore
en cours au relevé archivé. La CI générale du premier commit échoue : aucun état global vert annoncé.

La revue du chemin MCP a également identifié une obligation d'idempotence manquante pour
les mutations portant seulement une identité d'appareil. Sa correction et sa qualification
font l'objet d'une tranche séparée ; le succès E2E n'est pas une preuve de cette propriété négative.
La PR demeure en brouillon et le gate mobile demeure rouge.

[Archive](preuves/POWERSHELL-MODULES-r1.tar.xz) et
[inventaire SHA256](preuves/POWERSHELL-MODULES-r1.json) conservent les reçus, sources figées,
relectures et observations GitHub. Une nouvelle exécution native Windows reste requise.
