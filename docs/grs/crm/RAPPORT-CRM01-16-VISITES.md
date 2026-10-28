# Rapport de mission — état intermédiaire

- Mission / responsable : `CLAUDE-M4-VISITES-CRM01-16` / Codex.
- Dépôt / branche / base SHA : `leon36000/OPSYS-AI`, `mission/claude-crm-visites-20261028`, `3ab7692f041892ec2af0cab6f241a715edac2d50`. Tête fonctionnelle testée : `da00b3216` ; la tête documentaire effective est celle de la PR.
- PR draft : https://github.com/leon36000/OPSYS-AI/pull/853.
- Résultat observable : parcours fictif lundi/vendredi, deux équipes, interruption météo, 150 + 240 = 390 minutes, WCT unique et relecture SQLite. La proposition, l'affectation et la date passent par HTTP ; les pointages et la complétion sont exercés par les primitives et outils M4.
- Réutilisation : grille et journal existants, ancres et notes historiques, composition/absences déclaratives, solveur M4 et approbation N3, calendrier civil et registres existants. Aucune paie M4 ni modification M5.
- Fichiers possédés modifiés : modules et tests sous `departments/m04-field-ops/**`, `src/opsys/console/visites_chantier.py`, `src/opsys/console/reprise_visite.py`, leurs tests spécifiques et documents de mission. Inventaire exact : `git diff --name-only 3ab7692f041892ec2af0cab6f241a715edac2d50...HEAD`.
- Raccord partagé séparé : commits `333415ecd` (routeur, registre métier et lien journal console), `b9290308b` (liens de visite) et `5e8c8427d` (curseur composé du journal commun).

| Critère métier | Code/contrat | Commande et preuve | Verdict réel |
|---|---|---|---|
| Minutes hors nuits entre visites, pauses et UTC/Montréal | `visites_chantier.py`, `outbox.py` | `test_console_reprise_visite.py`, `regression-20.log` | 390 minutes dans un scénario fictif mixte HTTP/M4 ; pas un pointage navigateur |
| Interruption, reprise, un WCT | `etats.py`, `visites_ecriture.py`, `outils.py` | mêmes preuves | Aucun WCT à l'interruption, un final, second refusé, relu après réouverture SQLite |
| Équipe différente, date et histoire | `reprise_visite.py`, calendrier existant | test HTTP et `browser-02-serveur.log` | Parcours HTTP et navigateur jusqu'à la fermeture de vendredi ; pointages simulés par primitives |
| Déclaré, pointé, inconnu | `visites_chantier.py` console, composition existante | tests console et QA navigateur | Composition et présence distinctes ; ancien fait non attribué laisse total global inconnu |
| Sources, CAS, rejeu, rôle et rollback | ports privés M4/console | `regression-20.log`, preuves ciblées | Tests fictifs positifs pour sources périmées, CSRF et révocation tardive ; couverture non exhaustive |
| Ancres et anciennes notes | registres et annotations existants | `regression-01.log`, tests de notes et journal | Ancres précédentes conservées dans les cas exercés ; projection console liée uniquement pour des identités vérifiées, T0 historique inchangé |
| GPS arbitré et dates limites | `visites_chantier.py`, tests M4 | `test_visites_reprise.py`, tests de calcul | Cas d'anomalie arbitrée et frontières couverts par tests ciblés ; audit complet restant |

## Vérification

Les commandes, logs, pins et limites effectives sont détaillés dans [CRM01-16-VISITES-CHANTIER.md](CRM01-16-VISITES-CHANTIER.md) et `preuves-visites-20261028/`. Les régressions `regression-20.log`, `regression-23.log`, `regression-27.log`, `regression-33.log`, `regression-34.log` et les contrôles `lint-33.log`, `lint-37.log`, `lint-40.log`, `lint-45.log`, `lint-46.log` ont exit 0 ; populations recoupées, pas de cumul. Test de reprise SHA-256 `4e5ed28dfb5c8187df1c508b74003f90b65129dbb1936f482887d6400664e639`. Les premiers essais et échecs sont conservés. Python et dépendances : `pins-02.txt` ; homes et données fictifs privés, réseau de test filtré ; la dernière régression utilise source montée en lecture seule et espaces réseau/PID isolés. Le plafond de processus demeure partagé avec l’utilisateur hôte ; les essais précédents conservent leurs limites propres.

Commande de la régression précédente depuis la racine du clone ; la commande isolée plus récente est dans `preuves-visites-20261028/commande-regression-33.sh` :

```sh
QA="$PWD/../preuves-qa/private"
env HOME="$QA/home" OPSYS_HOME="$QA/opsys" XDG_CONFIG_HOME="$QA/xdg" XDG_CACHE_HOME="$QA/xdg" XDG_DATA_HOME="$QA/xdg" TMPDIR="$QA/tmp" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 timeout 90s python3 ../preuves-qa/runner-03.py ../preuves-qa/venv/bin/python -m pytest -p no:cacheprovider -q tests/test_console_reprise_visite.py tests/test_console_visites_chantier.py tests/test_console_proposition_chantier.py tests/test_console_proposition_chantier_http.py tests/test_console_application_chantier.py tests/test_console_memoire_dates_civiles.py tests/test_console_journal_equipes_http.py departments/m04-field-ops/tests/test_visites_reprise.py departments/m04-field-ops/tests/test_etats.py departments/m04-field-ops/tests/test_outbox.py
```

## Risques et reprise

La deuxième session a été ouverte et fermée au navigateur ; les pointages et le WCT ont été produits séparément par primitives et outils M4, puis la page a été relue au navigateur. Le statut est terminé en attente de revue, et non une vérification finale. Le lien journal → visite a été exercé en HTTP et au navigateur. La carte des lecteurs indique les refus des aperçus et le risque de consommation M5 ; leur adaptation aval reste à coordonner. Les chiffres historiques ambigus ne sont pas attribués ; un total WCT incomplet est refusé. Le contrat de temps M5 est une proposition distincte, à intégrer par le coordinateur. Les services QA possédés sont arrêtés ; pas de production, déploiement, fusion, envoi ou paie. Prochaine action : terminer l’audit des critères et coordonner la consommation des temps, puis mettre à jour ce rapport et la PR. La mission n'est pas revendiquée terminée.
