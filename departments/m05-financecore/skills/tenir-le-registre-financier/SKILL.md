---
name: tenir-le-registre-financier
description: Procédure pour consulter l'état financier (solde, argent disponible), calculer les taxes TPS/TVQ, et enregistrer un mouvement financier — sans jamais inventer un montant, un taux ou un solde.
---

# Tenir le registre financier

## Consulter l'état financier

1. Détermine le rôle de la personne qui demande l'état : autorisée aux coûts (ex.
   dirigeant, rôle financier) ou non (ex. terrain).
2. Appelle `m5_etat_tresorerie` avec `mouvements_historique` (l'historique renvoyé
   par le dernier appel connu, `[]` si aucun), le `role`, et `autorise_couts` réglé
   explicitement selon l'étape 1 — jamais laissé implicite.
3. Si `autorise_couts=false`, l'état renvoyé ne contient ni solde, ni argent
   disponible, ni taux : c'est le comportement attendu, pas une panne.
4. Présente toujours `solde` ET `argent_disponible` séparément — jamais l'un pour
   l'autre : l'argent disponible exclut les provisions.

## Calculer une taxe TPS/TVQ

1. Appelle `m5_calculer_taxes_tps_tvq` avec le montant avant taxes (texte décimal).
2. Le taux utilisé est toujours celui du fichier versionné en vigueur — si un
   identifiant de taux est absent de la version courante, l'outil bloque avec
   `REJ-TAUX-INCONNU` : ne recalcule jamais un taux de tête.

## Enregistrer un mouvement

1. Rassemble : montant (texte décimal, signé selon le type — négatif pour un
   DECAISSEMENT, positif pour un ENCAISSEMENT ou une PROVISION), type de mouvement,
   horodatage ISO 8601 avec fuseau, classe de rétention, source.
2. Appelle `m5_enregistrer_mouvement`. C'est une écriture financière : T3, jamais
   autonome — elle passe par la file d'approbation humaine.
3. Un refus porte un verdict nommé (ex. `REJ-MOUVEMENT-SIGNE-INCOHERENT` si le
   signe contredit le type) : corrige l'entrée, ne force jamais le passage.
4. Conserve `mouvements_historique` renvoyé pour le prochain appel — c'est la
   continuité du registre entre deux appels.
