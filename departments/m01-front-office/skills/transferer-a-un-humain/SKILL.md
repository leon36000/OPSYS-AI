---
name: transferer-a-un-humain
description: Procédure quand un client se plaint, signale un danger ou demande ce que tu ne dois pas traiter seule : lire ce que le code a escaladé, transférer avec un résumé, ne rien écrire au client, ne jamais clore.
---

# Transférer à un humain

Une plainte ou une urgence de sécurité n'est **jamais un lead**. Le code la reconnaît avant toute qualification
(les mots sont ceux de l'entreprise) et ouvre un transfert que le propriétaire voit dans « À voir ».

1. Après `m1_recevoir_message_canal`, lis `decision` :
   - `ESCALADE_PLAINTE` ou `ESCALADE_URGENCE` : c'est fait, par le code. Aucun lead n'existe. `plainte` dit ce qui a été
     reconnu, `transfert` dit le type, le niveau et le destinataire. Si `transfert.verdict_destinataire` est présent, le
     destinataire n'est pas configuré : dis-le, n'en choisis pas un.
   - `TRANSFERT_EN_COURS` : la conversation a déjà un transfert ouvert ; ce message y est rattaché, aucun lead ne s'ouvre.
   - `plainte.statut` vaut `vocabulaire_a_configurer` : l'entreprise n'a écrit aucun mot ; rien n'est reconnu par le code.
     Si tu vois toi-même une plainte ou un danger, escalade-le (étape 2) et dis-le à une personne.
2. Un message que le code n'a pas reconnu mais que **tu juges** être une plainte : `m1_escalader_plainte` avec `canal`,
   `expediteur` (recopiés de la plateforme) et `raison` (`insatisfaction`, `degat`, `garantie`, `avocat`, `securite`, ou
   `autre`). Un danger pour des personnes ou des biens : `securite`, toujours. Pour toute autre conversation à confier à
   une personne : `m1_transferer` avec un `type_transfert` de l'ensemble fermé (ventes, estimation, admin, finance,
   plainte, urgence, technique, proprietaire).
3. **Le résumé est obligatoire.** Omets `resume` : le code le compose (les faits de la conversation, sans texte du client).
   Si tu en fournis un, il est contrôlé : non vide, sans téléphone ni courriel (le contact est porté à part), sans prix,
   date, promesse ni aveu. Un refus dit quoi retirer ; n'insiste pas, omets le résumé.
4. **Tu n'écris pas au client.** Si `brouillon_reponse` est un texte, c'est un brouillon de ton empathique : propose-le avec
   `m1_emettre_notification`, une personne doit l'approuver, ne dis jamais qu'il est parti. Sinon `sans_brouillon` dit
   pourquoi (menace juridique : la réponse est humaine ; client retiré : rien).
5. **Urgence de sécurité : aucun conseil de sécurité, aucune promesse d'intervention**, pas même « appelez le 9-1-1 » : ce
   n'est pas à toi de le dire. Signale-le tout de suite à une personne dans ta réponse finale.
6. Tu ne clos jamais un transfert : `m1_clore_transfert` est une décision humaine (l'app admin ou la console).
   Sans elle, l'attente reste dans « À voir » : c'est voulu.
7. Jamais un avis légal, jamais un tort reconnu, jamais un prix ni une date, dans aucun texte que tu prépares.
