# g416m-verifier — [416m] `opsys-metier verifier` dans le conteneur

- Verdict : **PASSE**
- Attendu : manifestes, outils et dépendances valides (code 0)
- Début : 2026-11-01T11:15:27.354+00:00  ·  Fin : 2026-11-01T11:15:30.727+00:00  ·  Durée : 3.37 s

## Constats

| | Constat | Détail |
|---|---|---|
| OK | `opsys-metier verifier` : code 0 | ["OK : 10 départements, 415 outils, noms uniques, manifestes valides, événements cohérents, portées d'appareil valides (232 outils déclarés, les autres fermés aux appareils), taxonomie sans copie locale, 10 avatars aux noms distincts, 2 packs sectoriels valides (actif : generique-pme)."] |
| OK | 10 départements et 415 outils annoncés | "tils déclarés, les autres fermés aux appareils), taxonomie sans copie locale, 10 avatars aux noms distincts, 2 packs sectoriels valides (actif : generique-pme)." |

## Commandes (code de sortie réel)

| Code | Durée (s) | Commande |
|---|---|---|
| 0 | 3.37 | `docker exec qb768e49-g416m-s1 opsys-metier verifier` |

