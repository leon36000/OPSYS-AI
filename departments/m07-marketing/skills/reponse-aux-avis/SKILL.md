---
name: reponse-aux-avis
description: Procédure pour classer les avis clients et proposer une réponse, sans jamais publier automatiquement ni sous-estimer un litige ou une urgence.
---

# Répondre aux avis clients

1. Appelle `m7_calculer_metriques_reputation` pour la vue d'ensemble : note moyenne, taux de
   réponse déjà proposée, répartition des catégories (`litige`, `urgence`, `eloge`, `neutre`).
   Priorise les `litige` et `urgence` — ce sont les seules catégories où un mot-clé prime sur
   la note (un avis 5 étoiles qui mentionne une réclamation reste un litige).
2. Pour chaque avis à traiter, appelle `m7_proposer_reponse_avis` avec l'avis réel et le
   profil de marque réel. La réponse revient toujours `approval_status: "PROPOSE"` : présente-la
   au propriétaire, ne la publie jamais toi-même et ne la marque jamais approuvée.
3. Un avis classé `litige` : signale-le immédiatement au propriétaire même si la réponse
   proposée paraît suffisante — un litige non traité rapidement est un risque, pas juste un
   texte à envoyer.
4. Ne modifie jamais le texte de la réponse pour qu'il paraisse plus positif que ce que
   l'avis mérite, et ne retire jamais un fait gênant : le gabarit Brand Core est déjà
   professionnel par construction, tu ne le réécris pas.
5. `m7_publier_post_social` (T3) n'est jamais utilisé pour publier une réponse d'avis : la
   publication réelle d'une réponse (Google Business Profile Reviews) n'est pas encore câblée
   dans ce département — dis-le explicitement plutôt que de simuler une publication.
