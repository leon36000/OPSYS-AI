---
name: briefing-du-matin
description: Procédure pour produire le briefing du matin (décisions en attente, alertes M8, faits de la veille, manques) pour une date de référence donnée, lire ce qu'il n'a pas pu afficher, et lire les alertes de mesure de M8 avec leurs preuves, sans jamais rien y inventer, y décider ni y ajouter de diagnostic.
---

# Produire le briefing du matin

1. Appelle `m9_produire_briefing_matin` une seule fois, avec `maintenant` : l'instant RFC 3339
   fourni par l'appelant (l'heure réelle de la planification, ou une date demandée). M9 n'a pas
   d'horloge : ne devine jamais cette valeur, ne la recalcule jamais.
2. La réponse porte quatre sections, dans `ordre_sections` — présente-les TOUJOURS dans cet
   ordre :
   - `decisions_en_attente` : la file du propriétaire, telle quelle (id, resume, niveau, depuis,
     action_proposee, departement). N'en résume ni n'en priorise le contenu toi-même.
   - `alertes_m8` : alertes proposées par M8 dans la fenêtre de jours du briefing (quoi, à qui,
     pourquoi, preuve, source) : qualité des données, ou seuil de mesure de chantier franchi. Ne dis
     jamais pourquoi la donnée manque ou diffère au-delà de ce que `pourquoi` rapporte déjà — ce n'est
     ni observable ni ton rôle.
   - `faits_veille` : derniers faits du bus consolidés par M9 pour la veille (module_source,
     horodatage, valeurs). Ce sont des faits bruts, pas une interprétation.
   - `manques_pour_conclure` : constat, pas une alarme — nomme seulement quelles sources n'ont
     rien rapporté et quels seuils de M8 restent à configurer (`constat`, `verifie`), jamais une cause.
3. Une section avec `vide: true` reste vide dans ta présentation : ne la remplis jamais d'un
   texte de remplissage ni d'une supposition. Chaque élément affiché porte déjà sa propre source
   (identifiant de demande, `evenement_id`, ou `module_source`/`horodatage`) — cite-la, ne
   l'invente jamais.
4. Aucun chiffre ne doit apparaître dans ton texte qui ne vienne pas directement d'un champ de la
   réponse : tu peux reformuler la forme, jamais recalculer ou halluciner un nombre.
5. Le briefing est BORNÉ sous la limite de sortie : si `affichage.complet` est faux, dis-le tel quel
   (`affichage.message` : « N autres éléments non affichés ») et n'écris JAMAIS que la liste affichée
   est toute la liste. Pour lire le reste, appelle `m9_lire_suite_briefing` avec les `arguments` de
   chaque entrée de `affichage.lire_la_suite` (maintenant, section, depart), puis avec
   `prochain_depart` jusqu'à ce qu'il soit nul. Les éléments viennent du plus ancien au plus récent.
6. Pour consulter uniquement les alertes M8 déjà reçues (sans assembler le briefing complet),
   appelle `m9_lire_alertes_m8` à la place. Elle est BORNÉE et sans filtre de date : elles viennent du plus
   récent au plus ancien (à instant égal, par `evenement_id`), et la réponse porte `total`, `reste` et
   `prochain_depart`. Si `prochain_depart` n'est pas nul, dis-le tel quel (`message`) et rappelle l'outil avec
   `depart` égal à cette valeur, jusqu'à ce qu'il soit nul : n'écris JAMAIS que la page reçue est toute la liste.
   Un `depart` refusé (au-delà de la fin, ou négatif) se corrige en reprenant à 0.

# Lire les alertes de mesure de M8

Quand M8 a mesuré un chantier terminé (temps réel contre prévu, marge, matériaux) et qu'un seuil est
franchi, il propose une alerte. Pour la lire avec ses preuves, appelle
`m9_produire_lecture_strategique` (`maintenant`, et `depart` pour la page suivante) :

- chaque lecture cite ses preuves telles que M8 les a publiées : `metric_id`, `version_definition`,
  `chantier`, `valeur`, `seuil`, `evenement_id`. Cite-les ; n'en calcule, n'en arrondis aucune ;
- `action_proposee_par_m8` est l'action que M8 propose : relaie-la comme une proposition, jamais
  comme une décision ni un ordre ;
- tu ne décides RIEN : `decision.prise_par_m9` est faux, la décision revient au propriétaire
  (`decision.a_prendre_par`). Ne dis jamais qu'une action est faite ou retenue ;
- `manques.seuils_a_configurer` liste les métriques que M8 ne peut pas alerter faute de seuil : c'est
  un manque à signaler au propriétaire, pas un risque ;
- ne dis jamais pourquoi un chantier dépasse : la lecture rapporte un constat chiffré, pas une cause,
  et aucun nom de technicien n'y figure.
