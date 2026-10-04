# R18 — preuves ciblées des raccords M7/M10

Archive datée du 30 septembre 2026 pour les ajouts locaux M7 performance campagne, M10 jobs/cron
et leurs raccords. Les fichiers source restent dans l’espace de preuves externe; les copies `.gz`
sont déterministes, décompressées puis comparées octet pour octet à leurs originaux. Les empreintes,
tailles, périmètres et comptages indépendants figurent dans [MANIFEST.json](MANIFEST.json).

| Preuve | Collectés | Passés | Échecs | Erreurs | Sautés | Portée |
|---|---:|---:|---:|---:|---:|---|
| [M7 complet](preuves/m7-performance-revue-root-suite-final.xml.gz) | 1 031 | 1 031 | 0 | 0 | 0 | Suite M7 après le correctif de performance, UTC, conflits et autorisations. ROI numérique et dépenses restent non branchés. |
| [M2 complet](preuves/m2-performance-campagnes-suite.xml.gz) | 1 795 | 1 795 | 0 | 0 | 0 | Suite M2 vérifiant notamment la publication UTM source/campagne minimisée. |
| [Console performance M7](preuves/integration-performance-m7-console.xml.gz) | 16 | 16 | 0 | 0 | 0 | TestClient réel, événements M2/M3/M5 publiés puis répartis par le bus vers le registre M7; événements synthétiques explicitement fictifs. Le manifeste JSON d’origine et le log de collecte sont également archivés. |
| [Raccords M7/M10/Core ciblés](preuves/raccords-m7-m10-core-cible.xml.gz) | 128 | 128 | 0 | 0 | 0 | Parcours ciblés local; cette suite recoupe des tests M7, console et M10. |
| [M10 jobs sur sources gelées](preuves/m10-job-cibles-final.xml.gz) | 84 | 84 | 0 | 0 | 0 | Cibles isolées : 35 nouveau job, 22 développement, 27 conformité; également incluses dans la suite complète, comptées séparément. |
| [M10 et CLI métier](preuves/m10-job-departement-final.xml.gz) | 954 | 954 | 0 | 0 | 0 | Snapshot final 20:57 UTC après correction du contrat à neuf types, avant extension C02 `source=cli`; 945 cas M10 et 9 cas `tests/test_commande_metier.py`, 33,109 s. Recoupe les 84 cibles. |
| [Gel SHA-256 des sources M10](preuves/m10-job-source-freeze.json.gz) | — | — | — | — | — | Manifeste des 5 fichiers gelés à 20:50 UTC; aucun code source archivé. |
| [Projection cron M10](preuves/m10-cron-projection-final-v2.xml.gz) | 4 | 4 | 0 | 0 | 0 | Tests Python de projection cron; preuve distincte du probe Gateway natif. |
| [Jobs console M10](preuves/m10-console-jobs-final.xml.gz) | 57 | 57 | 0 | 0 | 0 | 46 tests console et 11 tests jobs, preuve locale gelée; log de collecte associé. |
| [Probe cron natif final](preuves/m10-native-cron-probe-result.json.gz) | — | — | — | — | — | JSON final sur les sources gelées; timer → available → rapport/checkpoint, rejeu même ID sans doublon, nettoyage. SHA-256 source : `d2ab1ce54164aad397f2e137fa305a0fcd6f772106784f5e7c1ff8c46e851589`. Le hash du log harness final est inscrit au manifeste; son contenu n’est pas archivé. |

Chaque ligne décrit un périmètre autonome. Les nombres ne sont **pas additionnés** : les suites
M2/M7, le TestClient console et les 128 raccords ont des recouvrements. R18 n’ajoute pas ces cas aux
totaux R17, et ne réédite ni ne remplace les preuves du [jalon R17](../R17-2026-09-30/README.md).

Précision de périmètre établie lors de R19 : les « 35 fichiers » annoncés initialement pour
le JUnit M10 étaient 35 groupes JUnit, correspondant à 32 chemins uniques : 31 fichiers M10
et le fichier de CLI métier. Les 945 cas de la nouvelle suite départementale seule et les
954 cas de cette preuve historique n'ont donc pas le même périmètre. Les archives et leurs
empreintes restent inchangées.

## Limites et exclusions

- M7 rend les coûts publicitaires, le coût par lead et le ROI `null`; il n’existe pas de source de
  dépenses réelles branchée dans cette tranche. La marge M5 observée n’établit pas un encaissement.
- Le probe cron utilise SQLite synthétique et un Gateway local sur le même hôte. Aucun fournisseur
  de modèle, canal, plugin réseau, service OS persistant ni VPS de production n’a été validé.
- Le snapshot final de la suite d’audit M10 à 20:57 UTC est vert : 954 tests passés, aucun échec,
  erreur ou saut, sur les sources M10 gelées après correction du contrat à neuf types. Il précède
  l’extension C02 `source=cli` dans `humain.py` et ses tests; cette preuve ne certifie pas cette extension
  ou l’état C02 courant. Les 84 cibles M10 restent une ligne séparée, recoupée et non additionnée.
  Les preuves rouges antérieures restent référencées dans l’espace externe, sans archivage de journaux
  volumineux. Le probe natif pré-freeze est historique; seul le JSON final fonde la ligne courante.
- Le backend et le raccord TypeScript C02 en développement sont exclus; l’état global C02 demeure
  **partiel**. R18 ne certifie ni le produit entier ni un déploiement.
- Les données de test sont synthétiques. Aucun harness contenant potentiellement des secrets, aucun
  journal de probe natif, code source, fixture métier, UI, worker ou artefact global de programme n’est archivé.

Les archives ont été générées avec gzip déterministe (`mtime=0`) et leur décompression a été
comparée à l’original. Les `.gz` peuvent être vérifiés avec `sha256sum` selon les empreintes archive
du manifeste; l’empreinte source permet de comparer le fichier externe exact s’il reste disponible.
