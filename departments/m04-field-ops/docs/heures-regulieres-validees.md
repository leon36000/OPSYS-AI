# Heures régulières individuelles validées — interface M4

Ce maillon prépare les données d'heures que le parcours salarial M5 pourra lire. Il ne constitue pas une paie et ne rend pas une règle de paie ou une conclusion juridique. Le statut M4 du département reste `PARTIAL`.

## Outils M4

Les trois outils sont ajoutés à M4. Les outils historiques conservent leur ordre, avec `m4_lire_retards_incidents` en dernier.

- `m4_previsualiser_heures_regulieres` (T0, administrateur) reçoit `technicien_id`, `debut`, `fin`, `fuseau`. Le technicien doit être une personne OPSYS active avec le rôle `employee`. Les deux dates sont ISO `AAAA-MM-JJ`, inclusives, et couvrent de 1 à 31 jours civils dans le fuseau IANA donné. Le calcul n'étend pas la période à une date de complétion, un WCT ou une somme d'équipe.
- `m4_valider_heures_regulieres` écrit après une approbation N4 signée. Le signataire confirme explicitement la couverture complète, la classification « régulière » et, pour `travail`, `deplacement` et `pause`, le choix d'inclure ou non la catégorie et sa source humaine. M4 n'infère aucune règle juridique ou de convention collective.
- `m4_lire_heures_regulieres_validees` relit la révision courante après vérification de chaîne, re-dérivation des pointages et cohérence de la demande N4. La lecture admin existante conserve le maillon détaillé destiné à l'examen autorisé.

## Dérivation et bornes

M4 n'accepte que des pointages canoniques attribués sans ambiguïté à une personne. Les instants doivent être zonés; ils sont comparés et durées calculées en UTC, puis interprétés dans le fuseau de la période. Le temps de travail sur site est l'intervalle arrivée–départ moins les intervalles de pause appariés. Le déplacement est l'intervalle du passage `en_route` à l'arrivée. Chaque séquence doit être complète, cohérente et contenue dans les bornes; une séquence qui traverse ou touche la période sans y placer de borne est quand même détectée et refusée. Les interventions et déplacements qui se chevauchent sont refusés. Des durées à la seconde non exprimables en minutes entières ne sont pas arrondies.

L'aperçu conserve les références de maillons et leur empreinte, pas les coordonnées GPS. Il expose les catégories séparées. Au moment de la validation N4, `minutes_regulieres` est la somme des catégories que l'humain a explicitement incluses. Ce total est une donnée préparatoire; il n'intègre aucun taux salarial, heures supplémentaires, vacances, avantage, retenue, DAS, coût employeur, CCQ ou net.

## Approbation, révisions et changements de source

Toute validation est un maillon append-only avec numéro de révision, référence du maillon remplacé, décision de catégories, signataire et demande d'approbation N4. Le payload N4 scelle `validation_precedente_attendue` : `null` pour la première révision, sinon `{revision, ligne_id}`. L'outil compare cette attente à la tête courante avant append. Si une autre décision a écrit une correction entre-temps, la demande ancienne est refusée; elle ne peut pas remplacer silencieusement la correction.

Les handlers refusent avant lecture/calcul/écriture si l'intégrité de chaîne échoue. La lecture revalide les champs, catégories, intervalles, sources, révision précédente et la demande N4 exécutée. Des pointages ou une validation modifiés, une empreinte discordante ou une approbation incohérente empêchent le retour des heures courantes. Les maillons historiques ne deviennent pas actifs après une correction.

## Lecture admin et port privé M5

Hors origine M5, le chemin admin conserve sa lecture existante et sa réponse détaillée. Pour la seule origine fiable `m05-financecore`, le port privé exige avant toute lecture du registre une identité ambiante `source="console"`, rôle `nathan_owner`, confirmée active avec ce rôle en base. Il ne transforme pas cette identité en acteur admin. Les appels sans identité, issus d'un jeton d'appareil, d'une autre origine, d'un autre rôle, d'une source différente ou d'une personne inactive sont refusés. Des champs identitaires ajoutés aux arguments ne remplacent pas cette provenance et le schéma fermé les rejette.

Les quatre arguments du reader sont `technicien_id`, `debut`, `fin`, `fuseau`. Le succès métier M5 est exactement :

```json
{
  "technicien_id": "…",
  "periode": {"debut": "AAAA-MM-JJ", "fin": "AAAA-MM-JJ", "fuseau": "Zone/IANA"},
  "minutes_regulieres": 0,
  "ligne_id": "…",
  "revision": 1,
  "empreinte_sources": "…",
  "couverture_complete": true,
  "classification_reguliere_confirmee": true
}
```

La réponse M5 ne contient ni détail de pointage, source brute, GPS, motif, identité du signataire ou salaire. Le refus métier a la forme `{accepte: false, verdict: {code, statut, detail}}`, sans résultat. Aucun détail n'est publié sur le bus.

## État de validation

Les 34 tests ciblés du scratch passent : 10 cas du pont M5/admin et les 24 cas du calcul/validation M4. La provenance pytest de ces tests vient du scratch, consignée dans les preuves du pont. Indépendamment, le root rapporte une suite active M4/M5 de 4 962 tests réussis; ce résultat porte sur l'arbre actif et n'est ni une extension de ces 34 cas ni une validation du scratch. Le full n'est pas déclaré complet ici. Le présent contrat ne signifie ni « paie complète » ni approbation de paie.
