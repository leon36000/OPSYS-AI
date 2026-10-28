# M4 — preuves de complétion conservées pour les futures interventions

## Objectif et pourquoi
Une complétion ne doit pas perdre les références des photos après, la note et la signature déclarées par le terrain. Le serveur les conserve maintenant avec l’état métier qui les a acceptées. L’[audit initial](M4-AUDIT-PERSISTANCE-PREUVES-COMPLETION.md) a établi la perte avant tout correctif.

## État actuel et statut
**Correctif serveur qualifié localement; M4 et CRM-12 restent PARTIAL.** Conservation pour les nouvelles complétions seulement. Les dossiers historiques sans bloc restent sans preuve retrouvée; aucune reconstruction ou migration ne leur attribue de photos, note ou signature. Le raccordement de ce nouveau bloc à la galerie CRM et le parcours mobile restent à réaliser.

## Architecture, fichiers et routes
- `departments/m04-field-ops/src/m4_field_ops/preuves.py` : préparation et validation d’un snapshot privé de types fermés.
- `.../outils.py` : validation structurelle, snapshot borné **avant** les lectures CAS, validation CAS et transmission exclusive de la copie.
- `.../outbox.py` : ajout optionnel au maillon composite unique, hash couvrant le bloc, contrôle à la lecture des invariants.
- `departments/m04-field-ops/tests/test_preuves_completion_durables.py` : 15 cas ciblés.
Aucune route, permission, table, migration ou nouvelle capacité MCP. Les paramètres publics de `m4_completer_intervention` restent les mêmes.

## Données et contrat
Le maillon de première complétion peut porter :

```json
{
  "preuves_completion": {
    "version_schema": 1,
    "signature_requise": false,
    "preuves": {
      "checklist_complete": true,
      "photos_apres": ["fichier:sha256:<empreinte-verifiee-par-M4>"],
      "notes": "Déclaration terrain",
      "signature": null
    }
  }
}
```

Le bloc est dans la partie transition couverte par `hash_maillon`. Il ne figure **pas dans le WCT** ni dans l’événement envoyé aux départements. Les binaires restent dans le CAS existant; aucune copie de photo/signature. La note est une déclaration conservée, pas une décision ou preuve d’authenticité inférée.

## Bornes et workflow
Types exacts, version entière 1, booléen strict, quatre clés de preuve fermées. Au plus 512 références. Somme des longueurs puis taille UTF-8 bornées avant copie; représentation canonique finale, métadonnées comprises, au plus 65 536 octets. Les UTF-8 invalides sont refusés. Ces nouvelles bornes de persistance sont explicites : un dossier valide structurellement peut être trop volumineux pour être conservé et donc refusé sans complétion.

L’outil gèle la copie avant CAS : changer ensuite la liste de l’appelant ne peut archiver une référence différente de celle validée. L’outbox prépare sa propre copie avant toute lecture du registre/hash/ajout. L’unique `ajouter` écrit transition, preuves et WCT ensemble. La publication native reste dans la même transaction; une exception annule l’ensemble.

## Intégrations et permissions
Aucun contenu privé supplémentaire envoyé à M2/M3/M5/M6/M7/M8/M10; seul le hash opaque change pour une nouvelle complétion avec preuves. `CHAMPS_WCT` et le schéma événementiel sont inchangés. Les lecteurs outbox, calibration, digest et revue utilisent leurs projections existantes. Le contrôle d’appareil/affectation, les vérifications de fichier et les permissions existantes demeurent applicables.

L’absence totale des deux nouveaux arguments de la fonction pure outbox garde la forme et les hashes historiques. Un seul argument fourni, un bloc nul/invalide ou une présence sur une confirmation/revue sans WCT sont refusés. Une signature fournie alors qu’elle n’est pas requise garde sa sémantique historique : elle n’est pas nouvellement déclarée authentifiée ou CAS vérifiée.

## Risques et limites
Le bloc contient des références et une note potentiellement personnelles : consultation privée et politique de rétention à conserver dans les futurs lecteurs. Aucun partage marketing, exposition des notes/signatures dans la galerie ou accès global par hash. Le pilote privé de console actuel reste SQLite; cette QA ne prouve pas PostgreSQL, la production ni une application terrain complète.

## Tests et preuves
QA `m4-completion-proof-v4` : **392 tests PASS en 23,45 s**, dont **15** ciblés sur ce correctif; régressions outbox, preuves, fichiers, événements, outils terrain, digest, revue et vues CRM/préparation incluses. Lint des quatre fichiers modifiés, vérificateur natif : 10 départements, 306 outils, 177 portées déclarées. Les 11 PASS initiaux et les 390 PASS intermédiaires sont des populations recoupées, jamais additionnées.

Dépôt CAS natif d’un PNG fictif réel, outil de complétion natif, SQL/reconnexion, un seul nouveau maillon, publication sans note/signature privée, rollback de publication interrompue, copie isolée, bornes avant CAS, UTF-8 et représentation canonique, invariants après rehash, anciens appels/hashes et confirmations. Une revue indépendante a identifié la copie initiale trop tardive après CAS; deux tests natifs rouges ont reproduit une référence substituée et une lecture SQL avant refus de borne. Le correctif place le snapshot avant CAS, puis les 392 tests passent. Tous les rouges, erreurs de fixture/lint et l’enchaînement opérateur v3 sur Source inchangée sont conservés dans des reçus distincts.

## Gates Nathan et prochaines étapes
Aucune approbation additionnelle pour les données fictives et cette correction réversible. Préflight M10 privé frais v2 qualifié; le refus v1 d’un chemin sous `crm` reste historique, la garde n’a pas été élargie. La base vide privée ne remplace pas la mémoire projet.
Prochaine tranche : lire explicitement les nouvelles références `photos_apres` depuis la galerie du devis/chantier exact, garder le statut historique absent distinct et vérifier le binaire/les permissions à chaque ouverture. Puis bibliothèque photos/PDF complète et mobile dans la phase prévue. CI de publication et production ne sont pas qualifiées par ce seul résultat local.
