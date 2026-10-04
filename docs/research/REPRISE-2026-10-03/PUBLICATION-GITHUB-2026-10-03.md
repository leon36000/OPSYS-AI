# Publication de la reprise — 3 octobre 2026

La branche de reprise `codex/restructuration-2026-09-30` est publiée sur le dépôt privé
`leon36000/OPSYS-AI`. La [PR #623](https://github.com/leon36000/OPSYS-AI/pull/623) est ouverte en brouillon contre
`claude/opsys-ai-analysis-x4jt87`, base `2e56c0d5605dfe575bde9244f38924d5390f2674`.
Cette base isole notre reprise : comparer immédiatement à `main` ajouterait les
525 commits de la refonte historique. La publication ne fusionne aucune branche.

L'état publié conserve les corrections, tests, documentations et preuves du travail
local. Il contient aussi des capacités partielles explicitement suivies. Il ne doit
pas être assimilé à une livraison production ni au produit entièrement terminé.

- [Programme de restructuration](../../programme/RESTRUCTURATION-2026-09-30.md) :
  ambitions, douze périmètres et état détaillé de la reprise.
- [Index de preuves actuel](README.md) : qualifications séparées, sans addition
  artificielle des campagnes qui se recouvrent.
- [Audit et limites de M1](../../grs/reception/M1-APPELS-HOTE-2026-10-03.md) :
  205 cas Python, 164 cas natifs Core, puis deux scénarios distincts utilisant le
  vrai client MCP et le serveur Python dans des processus séparés. Régression M9
  interrompue par le plancher mémoire : zéro cas qualifié dans cette tentative.
- [Contrôle de publication](preuves/publication-github/VERIFICATION-ROOT.json) :
  Gitleaks 8.30.1 vérifié par checksum, rapport expurgé, classement des 5 269 alertes
  (empreintes, URL de commits, fixtures et exemple JWT documentaire). Aucun contexte
  inconnu dans ce rapport; cette revue ne garantit pas l'absence de tout secret.

Les huit fichiers natifs M1 sont inscrits dans le job CI `tests-opsys` existant,
qui prépare déjà le Python verrouillé et `OPSYS_TEST_PYTHON`. Les résultats de cette
CI distante sont analysés dans le [point du 4 octobre](../REPRISE-2026-10-04/CI-PUBLICATION.md).

Le build complet du premier commit publié réussit en CI. Les exports SDK générés, le profilage du plugin compilé, les
parcours Gateway de récupération, la téléphonie réelle et l'installation sur VPS
restent à qualifier. M5 CFO complet, M7 CMO autonome, assimilation massive M10,
précision géospatiale réelle et interaction ACE de production restent partiels.

Les journaux, licences amont et prompt exact gardent leurs octets, même lorsque
le contrôle global de whitespace signale leurs espaces historiques. Aucun constat
whitespace ne touche le code de production ajouté. Certaines références historiques
vers `/workspace` ne sont pas portables sur GitHub; les capsules liées par chemins
relatifs dans l'index actuel sont consultables dans la branche publiée.

Pour préserver l'arbre existant malgré le disque presque plein, le commit de
publication est préparé avec un index et des objets Git isolés. Les sources du dépôt
partagé sont préservées; la branche distante et sa PR constituent le point de reprise
publié. La CI et les régressions manquantes doivent passer avant une fusion.
