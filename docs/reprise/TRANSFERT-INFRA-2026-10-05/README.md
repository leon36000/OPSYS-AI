# Reprise OPSYS-AI sur l’infrastructure de Nathan

Lire d’abord `PROMPT-REPRISE-CODEX.md`, `AUDIT-TRANSMISSION.md` et `ETAT-ET-SUITE.md`. Le [cahier consolidé](../../produit/CAHIER-AMBITIONS-TRANSMISSION-2026-10-05.md) lie la profondeur cible aux documents détaillés. Le rapport Luna décrit le corpus documentaire avant l’ajout du lien de transfert; ROOT en a vérifié les SHA.

Le pack externe contient `OPSYS-AI.bundle`, `MANIFESTE-TRANSFERT.json`, `VERIFIER-ET-RESTAURER.py`, le prompt et ces documents. Le bundle contient la base locale capturée et le snapshot complet final (code, docs, licences et preuves versionnées), avec deux commits locaux synthétiques de transport. Il ne contient pas les secrets/configurations personnelles, environnements installés, node_modules non versionnés, bases client ou caches non versionnés. Il n’archive pas toutes les anciennes conversations ni tout l’historique Git réel; celui-ci est à récupérer de GitHub.

## Import sans écraser l’existant

Décompresser le ZIP dans un dossier de transfert. Python 3.10+ et Git sont nécessaires. Aucune installation de dépendance/API n’est exécutée par le vérificateur.

```bash
python3 VERIFIER-ET-RESTAURER.py verifier
python3 VERIFIER-ET-RESTAURER.py restaurer --destination /chemin/neuf/OPSYS-AI-reprise
```

Le premier mode vérifie tailles/SHA et que le bundle est autonome. Le second clone le snapshot dans un dossier qui ne doit pas exister, contrôle l’arbre et les chemins préparés, renomme le remote bundle en `transfert-local` et ajoute le remote GitHub `origin`. Aucun fetch, push, reset du dépôt existant, merge ou déploiement. En cas d’échec, le dossier de tentative est conservé pour inspection; il ne faut pas réutiliser son nom comme si la restauration était validée.

Dans Codex sur l’infra, ouvrir le dossier restauré ou mettre ce pack à côté du vrai checkout GitHub, puis coller le prompt. Si le vrai dépôt est plus récent, le conserver et intégrer dans un nouveau worktree les changements utiles : comparer la base de transport et le snapshot avec `git diff`, **pas de copie globale** sur l’existant. Le chef de projet doit identifier l’ascendance distante réelle avant publication privée. L’autorisation de continuation ne vaut pas fusion sur main, force-push ou action de production.

Les secrets de PC1 et identités GitHub restent sur l’infra, références seulement; utiliser les profils existants sans afficher leurs valeurs. Ne pas importer d’environnement shell ou de credentials cloud depuis ce pack.

Un supplément `supplements/non-integre/core/src/state/openclaw-state-db.generated.d.ts` conserve une déclaration générée différente de r29. Elle n’est pas automatiquement copiée par la restauration : comparer/régénérer et qualifier avant intégration. Le manifeste fournit la SHA actuelle et le blob de référence. Cela préserve le travail sans annoncer cette divergence comme testée.
