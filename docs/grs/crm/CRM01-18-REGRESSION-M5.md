# Régression M5 — 90 échecs initiaux

Le tableau `CRM01-18-CLASSIFICATION-90.tsv` relie chaque cas ayant échoué sur `a4f25a2e8ca97e437f12fb184b88c31763fb10dc` à son résultat sur `d5ff2f858cbf195689b4a89ed34a2120814977fd`. La comparaison utilise les identifiants JUnit, avec un renommage explicite du test de coût partiel ; elle ne supprime ni n'ignore de cas. La colonne de classification décrit la première cause observée, pas une preuve que tous les autres scénarios sont couverts.

- Initial : 90 échecs sur 2 702 cas, zéro skip. Tête `d5ff2f858` : 17 échecs sur 2 714 cas, zéro skip ; 73 des 90 cas initiaux passent. Le fichier JUnit de cette dernière exécution a le SHA-256 `dd75b1bb836ccea75ad310f59e46776008ea127a59df84d17fe4cd05e0feae84`.
- Les anciennes attentes de coût complet attribuaient un WCT scalaire à une équipe sans preuve. Les attentes ont été ajustées pour garder inconnue cette composante ; les tests conservent les contrôles de matériaux, tarifs et confidentialité. Les cas de calcul et de schéma nécessitant un coût complet utilisent une fixture V3 typée synthétique : elle permet de tester le calcul, mais ne prouve pas son origine.
- Les 17 échecs restants concernent les tests de cascade, d'événement et de lecture historiques. Ils ne sont ni supprimés ni ignorés. Leur réussite positive demande un chemin autorisé de revalidation et une stratégie de fraîcheur pour les consommateurs. Le changement de contrat de l'ancien WCT n'est pas à lui seul une preuve que cette capacité existe.
- Une composition distincte a aussi exercé les véritables producteurs et consommateurs jusqu'à l'analyse locale privée : M4 `d83a19d4e242297400bdb65c62c331781bd5f2cd`, M5 `d5ff2f858cbf195689b4a89ed34a2120814977fd`, composition linéaire QA `b3df14f3b7d3f2fc5adfbf89c8d7957361e0e246`. 53 cas réussis sans skip ; SHA-256 JUnit `4f403f0eddf27ed1e392ffb34740a71e79c79eb4f593c35957ba322b9d5186a6`. Les scénarios de cette composition sont dans `CRM01-18-PREUVES-V3/` et restent fictifs. La trace V3 complète ne sort pas sur le bus.

Commandes de collecte : `python -m pytest -p no:cacheprovider -q departments/m05-financecore/tests --junitxml=<sortie>` pour la suite complète ; pour la jonction, les neuf modules cités dans les preuves QA, exécutés sur la composition indiquée. Les exécutions ont utilisé un venv et des répertoires privés, des limites de ressources et des espaces réseau/PID isolés. PostgreSQL n'est pas qualifié. Aucune fusion, mise en production ou opération financière réelle.

Dans la composition QA, les modules ciblés étaient :

```text
tests/test_console_rentabilite_chantier_ventilation.py
departments/m05-financecore/tests/test_ventilation_source_tarifs.py
tests/test_console_rentabilite_chantier_export.py
departments/m05-financecore/tests/test_validation_projection_v3.py
tests/test_console_rentabilite_chantier_tarifs.py
departments/m04-field-ops/tests/test_temps_certifies_v3.py
tests/test_qa_v3_http_reel.py
tests/test_qa_v3_historique_complet.py
tests/test_qa_m4_m5_v3_reel.py
```
