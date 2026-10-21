---
name: etat-consolide-et-contradictions
description: Procédure pour ingérer un snapshot d'un module, reconstruire l'état consolidé de l'entreprise et présenter ses contradictions internes sans jamais les résoudre ni en inventer la cause.
---

# Tenir l'état consolidé

1. Rassemble le `SnapshotModule` reçu : `module_source`, `horodatage` (fourni par l'appelant,
   M9 n'a pas d'horloge), `valeurs` (toujours du texte). N'en invente aucun champ.
2. Appelle `m9_etat_consolide` une seule fois avec ce snapshot. Pour consulter l'état courant
   SANS rien ingérer (ex. un digest planifié), appelle `m9_lire_etat_consolide` à la place.
3. Lis la réponse :
   - `etape: "validation"` et `accepte: false` → le `verdict` nomme ce qui est structurellement
     invalide. Corrige l'entrée, ne réessaie pas à l'identique.
   - `etape: "complet"` → l'`etat_consolide` porte `faits_par_module` (dernier fait connu,
     choisi chronologiquement) et `contradictions` (liste, potentiellement vide).
4. Pour chaque contradiction : nomme les deux `ligne_id_a`/`ligne_id_b`, le `module_source` et
   l'`horodatage` en cause. Ne dis jamais pourquoi les deux valeurs diffèrent ni laquelle est
   correcte — ce n'est ni observable ni ton rôle. Signale-la à un humain pour arbitrage
   (registré côté M10, hors de ta portée directe en v1).
5. Un rapport stratégique complet (15 clés) n'est jamais rédigé par toi en v1 : s'il t'en
   parvient un, appelle `m9_valider_rapport_strategique` pour n'en vérifier que la structure.
