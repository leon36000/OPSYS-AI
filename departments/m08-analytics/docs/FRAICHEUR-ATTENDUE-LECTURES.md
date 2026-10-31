# Fraîcheur attendue d'une lecture de M8 (`fraicheur_attendue_s`)

Contrat entre M8 (propriétaire de la fenêtre) et M9 (qui compare). Données fictives dans les tests.

## Besoin

M9 expose au conseil l'âge de chaque lecture (`age_s`). Sa `fraicheur` reste `NON_EVALUEE` tant qu'aucun producteur ne
déclare ce qu'il attend. M8 le déclare ; M9 compare. M8 ne juge jamais qu'une lecture est périmée.

## Déclaration

`department.yaml` de M8, `configuration.fraicheur_lectures_s`, VIDE par défaut :

```yaml
fraicheur_lectures_s:
  m8_lire_vue_executive: 86400      # exemple de forme, pas une valeur livrée
```

- Clé : un outil de lecture déclarable (`m8_lire_vue_executive`, `m8_lire_mesures_chantier`) : ceux que M9 capture et dont
  la réponse déclare un instant métier à dater.
- Valeur : entier (ni booléen, ni décimal, ni texte), `1 <= n <= 315360000` (3650 jours, la borne des péremptions de M9).
- C'est de la configuration du propriétaire, comme `seuils_entonnoir` : aucune valeur n'est livrée, aucune n'est dérivée.

Choix du niveau : par LECTURE (« vue »), pas par métrique. M9 date une lecture entière ; en déduire une fenêtre à partir des
métriques qu'elle contient (minimum, maximum…) serait inventer une règle. Les `fraicheur_attendue_jours` du registre durable
des métriques datent une VALEUR de métrique (alertes de péremption de M8) : autre notion, laissée intacte, jamais convertie.

## Exposition

| Déclaration | Clés ajoutées à la réponse de la lecture |
|---|---|
| absente | aucune : la réponse est identique à celle d'avant |
| valide | `fraicheur_attendue_s` (entier) et `version_definition_fraicheur` (SHA-256) |
| invalide ou illisible | `fraicheur_attendue_refusee: {raison, source}` ; aucune fenêtre exposée |
| clés qui ne sont pas une lecture déclarable | `fraicheur_attendue_ignorees: [clés]` (en plus) |

Niveau racine de la réponse (`resultat.fraicheur_attendue_s` côté M9). `m8_lire_mesures_chantier` ne les porte que pour un
chantier trouvé (un chantier inconnu n'a aucun instant à dater).

## Version de définition

`version_definition_fraicheur = empreinte({"lecture": <outil>, "fraicheur_attendue_s": <n>})`, avec `encodage.empreinte` (la
même empreinte que `version_definition` des métriques). Elle change si et seulement si l'outil ou la fenêtre change, et se
recalcule à l'identique. Aucune `version_definition` de métrique ne change (les métriques ne portent pas ce champ) : les
empreintes figées existantes sont inchangées.

## Ce que cela ne fait pas

Aucun nouvel outil, paramètre, rôle ou grant ; aucun événement ; aucune horloge dans M8 ; aucune alerte. L'instant métier
daté reste celui que le catalogue de M9 déclare pour la lecture.
