# Budget d’agents — libération avant appel au modèle

Le correctif est intégré localement. Une réservation fraîche qui n’atteint jamais
le fournisseur peut être libérée quand la vérification finale d’autorité ou
l’annulation empêche l’appel. Les résultats incertains restent réservés : une
exception du fournisseur, une réponse d’admission perdue ou un usage absent ne
prouvent pas une consommation nulle. Le statut global reste **PARTIEL**.

## Contrat privé

Le wrapper capture avant son premier `await` la configuration, la route MCP,
l’agent, la révision et les identifiants du run/candidat/stream. La même capture
sert à libérer ou à concilier l’usage réel, même si une configuration mutable
change pendant l’appel. L’autorité vivante reste vérifiée avant chaque dispatch.

`opsys_runtime_liberer_avant_dispatch` est accessible uniquement par la route
runtime privée authentifiée. Le profil vient de cette route; le payload fermé
porte réservation, exécution, tentative, cycle, candidat, ordinal et révision.
L’identité/auteur et la raison ne sont pas des arguments libres. La politique
`opsys_runtime_*__*` interdit ce namespace aux outils découverts et appelés par
les modèles.

Python verrouille politique puis réservation, vérifie la capture complète et
l’unique preuve de révision écrite dans la transaction d’admission. Les anciennes
réservations sans cette preuve restent à concilier humainement. Une libération
exactement rejouée ne crée pas un second événement; un cycle déjà admis ne donne
jamais un nouvel accord de dispatch. Une réservation conciliée refuse la libération.

Le cleanup fait une seule tentative, avec délai propre de dix secondes, même
si le signal du run est annulé. Il conserve l’erreur d’origine si sa réponse se
perd ou échoue. `tokens_reels` reste inconnu; aucun faux usage zéro n’est écrit.
Le backend ne peut pas constater seul qu’un fournisseur n’a pas été appelé :
cette garantie dépend du wrapper hôte de confiance et de la position du cleanup.

## Qualifications distinctes

- [Core : 18 cas du wrapper et un cas du namespace privé](../research/REPRISE-2026-10-03/preuves/provider-pre-dispatch/core/VERIFICATION-ROOT.json).
  Fichiers complets, Node 24, configurations Vitest natives, plugins/setup conservés.
  Les 18 cas doublent le transport MCP; le cas de namespace utilise le propriétaire
  natif `unit-fast`, qui l’exclut du shard `agents-core`.
- [Python : 110 cas, zéro échec/erreur/skip](../research/REPRISE-2026-10-03/preuves/provider-pre-dispatch/python/JUNIT-ADDENDUM-ROOT.json),
  [reçu et historique des six essais](../research/REPRISE-2026-10-03/preuves/provider-pre-dispatch/python/VERIFICATION-ROOT.json).
  Cinq fichiers complets et les cas SQLite du fichier d’admission; cinq cas PostgreSQL
  sont explicitement exclus. Ruff passe, 667 sources sont stables, aucun nouvel OOM
  et aucun processus survivant dans la dernière campagne. Son pic RSS est 315 887 616
  octets, sa réserve minimale disponible 1 129 680 896 octets.

Ces comptes se recouvrent avec des campagnes antérieures et ne sont pas additionnés.
Le compagnon Core/Python HTTP de deux cas demeure non qualifié : un worker sort
avant tout résultat attesté et laisse un JUnit vide. Le diagnostic ne démontre
ni une assertion métier échouée ni la cause de cette sortie. Les tentatives et
leur échec sont conservés, sans remplacer les propriétaires ou retirer des tests.
La [reprise diagnostique](../research/REPRISE-2026-10-03/preuves/provider-pre-dispatch/core-supplement-r2/ETAT-ROOT.json)
importe directement la même fonction de politique réexportée par la façade; elle
ne produit toujours aucun cas attesté. Le profil suivant, V8 256 MiB/RSS de groupe
896 MiB et réserve inchangée, est refusé au plancher 1 408 MiB avant tout lancement.
Le contrôle natif de format des quatre fichiers courants passe séparément.

PostgreSQL est aussi non qualifié dans cette correction : le pilote Docker `vfs`
copie le système de fichiers de l’image même si les données sont en RAM. L’espace
disponible est insuffisant. Seuls les deux conteneurs créés par ces essais, encore
à l’état `Created`, ont été retirés; aucun conteneur préexistant ni image n’a été
supprimé. La réserve mémoire de 512 MiB est maintenue.

Aucun fournisseur réel, secret de production, job de production, paiement,
publication ou déploiement VPS n’a été utilisé. La qualification du stream SDK,
du cycle de vie complet et du retrait cron natif reste distincte :
[état du raccordement hôte](CRON-RACCORDEMENT-HOTE-2026-10-03.md).

## Propriétaires

- [Wrapper et capture](../../core/src/agents/embedded-agent-runner/opsys-runtime-admission.ts).
- [Admission et libération](../../src/opsys/admission_agents.py).
- [Route MCP privée](../../src/opsys/serveur_mcp.py).
- [Tests du wrapper](../../core/src/agents/embedded-agent-runner/opsys-runtime-admission.test.ts),
  [intégration HTTP écrite](../../core/src/agents/embedded-agent-runner/opsys-runtime-admission.python-http.integration.test.ts),
  [refus du namespace](../../core/src/agents/agent-tools.before-tool-call.opsys-runtime-deny.test.ts).
