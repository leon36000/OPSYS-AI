---
name: briefing-du-matin
description: Procédure pour produire le briefing du matin (décisions en attente, alertes M8, faits de la veille, manques) pour une date de référence donnée, sans jamais rien y inventer ni y ajouter de diagnostic.
---

# Produire le briefing du matin

1. Appelle `m9_produire_briefing_matin` une seule fois, avec `maintenant` : l'instant RFC 3339
   fourni par l'appelant (l'heure réelle de la planification, ou une date demandée). M9 n'a pas
   d'horloge : ne devine jamais cette valeur, ne la recalcule jamais.
2. La réponse porte quatre sections, dans `ordre_sections` — présente-les TOUJOURS dans cet
   ordre :
   - `decisions_en_attente` : la file du propriétaire, telle quelle (id, resume, niveau, depuis,
     action_proposee, departement). N'en résume ni n'en priorise le contenu toi-même.
   - `alertes_m8` : alertes de qualité proposées par M8 pour le jour du briefing (quoi, à qui,
     pourquoi, preuve, source). Ne dis jamais pourquoi la donnée manque ou diffère au-delà de ce
     que `pourquoi` rapporte déjà — ce n'est ni observable ni ton rôle.
   - `faits_veille` : derniers faits du bus consolidés par M9 pour la veille (module_source,
     horodatage, valeurs). Ce sont des faits bruts, pas une interprétation.
   - `manques_pour_conclure` : constat, pas une alarme — nomme seulement quelles sources n'ont
     rien rapporté (`constat`, `verifie`), jamais une cause.
3. Une section avec `vide: true` reste vide dans ta présentation : ne la remplis jamais d'un
   texte de remplissage ni d'une supposition. Chaque élément affiché porte déjà sa propre source
   (identifiant de demande, `evenement_id`, ou `module_source`/`horodatage`) — cite-la, ne
   l'invente jamais.
4. Aucun chiffre ne doit apparaître dans ton texte qui ne vienne pas directement d'un champ de la
   réponse : tu peux reformuler la forme, jamais recalculer ou halluciner un nombre.
5. Pour consulter uniquement les alertes M8 déjà reçues (sans assembler le briefing complet),
   appelle `m9_lire_alertes_m8` à la place.
