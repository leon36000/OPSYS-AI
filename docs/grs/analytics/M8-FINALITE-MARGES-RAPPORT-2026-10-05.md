# M8 — marges qualifiées avant apprentissage

Statut : **tranche vérifiée localement; lot 3 encore partiel**.
[Programme](../../programme/PROGRAMME-24H-2026-10-04.md) · [Finalité M5](../compta/M5-FINALITE-EVENEMENT-RAPPORT-2026-10-05.md).

La lecture a identifié une vraie dérive : M5 peut calculer une marge sur facture brouillon; M8 la présentait comme « réelle » depuis la seule présence du montant. La finalité propagée au lot 1 était insuffisante sans contrôle au consommateur.

`mesures_chantier.py::raison_marge_reelle_non_qualifiee` exige maintenant `verdict=CALCULEE`, `cout_reel_complet is True` et `prix_definitif is True`. Les trois métriques de marge/écart et `vue_executive.py` utilisent la même garde. Brouillon, finalité historique inconnue, complétude absente/partielle ou verdict non calculé produisent une absence de valeur motivée. Les montants M5 qualifiés sont repris tels quels; les formules d'écart ne changent pas. Le YAML gouverné reflète cette sémantique et son empreinte `version_definition` change automatiquement.

La projection garde `prix_definitif`, `cout_reel_complet` et `version_entrees` si présents. Aucun fait historique n'est réécrit; un ancien fait sans preuve demeure non calculable. Aucune migration ni action financière. La finalité envoyée ne signifie pas paiement reçu.

La vue conserve son budget : source M5 commune à la section, booléen de finalité par ligne et motif d'exclusion. Répéter source/verdict/coût sur chaque ligne tronquait les trois chantiers du cas ordinaire (r232, 3 échecs); ROOT a supprimé cette redondance, sans augmenter le budget ni retirer les faits détaillés ou la garde. Les tests de trois lignes et les tests de bornage restent intacts.

Le vrai scénario bus `tests/test_cascade_mesure_m8_m9.py` garde la marge M5 calculée 52.00 et le coût complet, mais exige désormais M8 non calculable parce que la facture reste brouillon. Aucun envoi n'est ajouté pour rendre le scénario vert.

## Vérification

- ROOT r238 : 289/289 dans sept fichiers complets M5/M8/M10, Ruff et manifests verts.
- ROOT r239 : 350/350 dans dix fichiers complets, ajout du dictionnaire gouverné, réception des mesures et cascade M8/M9; Ruff des deux sources M8 et tests, manifests verts.
- SHA de sources stables pendant chaque exécution; aucun OOM. SQLite/fonctions pures dans cette tranche; PostgreSQL actuel, restauration et production non exécutés. Le PostgreSQL tmpfs du lot précédent est une preuve distincte.

Suite qualifiée localement le 5 octobre : le [rapport de lecture jointe](../estimation/M3-APPRENTISSAGE-LECTURE-RAPPORT-2026-10-05.md)
réunit ces preuves sans activation. Périmètre requis : jointure exactes WCT/devis/hash/version, matière par unité, exclusions de doublons/incompatibilités, aucun GPS/identité employé; durée d'intervention ≠ heures-personnes/paie. `version_entrees` conservée ne suffit pas à prouver une jointure. Aucun barème ou modèle n'est promu, et aucune amélioration de précision n'est annoncée depuis les fixtures.

Preuves : [capsule](../../research/REPRISE-2026-10-05/preuves/VENDEUR-M8-PROMPTS-r1.tar.xz) et [manifestes](../../research/REPRISE-2026-10-05/preuves/VENDEUR-M8-PROMPTS-r1.json). La recherche externe OCR/AP et le raccord client réel sont des tâches séparées.
