---
name: contenu-de-chantier
description: Procédure pour proposer les cinq contenus d'un chantier terminé (Facebook, Instagram, fiche Google, script de vidéo courte, demande de témoignage), les faire passer le contrôle du code, puis laisser le propriétaire décider et publier lui-même, sans jamais publier ni approuver.
---

# Le contenu d'un chantier terminé

1. **Le bus propose déjà.** Quand un chantier est terminé avec le consentement du client à l'usage de son chantier
   (`consentement_marketing`, prouvé : qui, quand, quel texte) et que le profil de marque est configuré, M7 crée
   lui-même les cinq contenus avec les gabarits du code. Lis-les avec `m7_lister_contenus_chantier` : chacun est
   `PROPOSE`, jamais publié.
2. **Rien n'est proposé ?** Appelle `m7_proposer_contenus_chantier(wct_id)` et lis `statut` : `wct_inconnu`,
   `refuse` (consentement absent, faux ou sans preuve, client insatisfait), `consentement_retire`,
   `profil_marque_non_configure`, `nature_inconnue`. Dis-le au propriétaire tel quel : ne contourne jamais un refus
   et ne fournis jamais un consentement ni une marque en argument (l'outil ne les accepte pas).
3. **Un texte de toi.** `m7_lire_matiere_chantier(wct_id)` donne la marque, l'accroche, la nature des travaux, la
   ville (absente : n'en invente pas), la note du chantier (si elle est utilisable), les mots-clics, les plateformes
   et leurs plafonds, et les règles du contrôle. Rédige un texte par plateforme et passe-les dans `textes`.
4. **Le contrôle est celui du code.** Tout texte, le tien comme celui du gabarit, est refusé en nommant la règle :
   adresse, coordonnées, nom de client, identifiant interne, prix ou offre, chiffre avec unité (pieds, heures, ans,
   %), garantie non validée par l'entreprise, date ou promesse de délai, exagération (meilleur, numéro 1…), lien.
   Récris sans la chose nommée ; ne la déguise pas (le contrôle n'est pas un obstacle à contourner, c'est la règle).
   Le lien de suivi (UTM) est ajouté par le code, jamais écrit dans le texte.
5. **Tu ne décides pas.** `m7_decider_contenu` est la décision du propriétaire (« À voir »). Ne l'appelle pas pour
   approuver un contenu que tu as proposé : un appel sans le propriétaire est refusé (`REJ-HUMAIN-REQUIS`).
   Un contenu rejeté a son motif : propose un nouveau texte (`textes`) qui le corrige, c'est une révision.
6. **Le paquet manuel.** Après l'approbation, le propriétaire prend le paquet (`m7_exporter_paquet_manuel`) et publie
   lui-même. Chaque média est « à flouter à la main » : aucun détecteur réel de visages et de plaques n'est
   installé, ne présente jamais une photo comme sûre. L'heure suggérée vient du profil de marque ; sans elle, dis
   qu'il n'y en a pas.
   Le paquet porte `utm_content`, la clé de mesure du contenu, que son lien de suivi contient : à l'export, M7 annonce
   au bus le contenu (clé, chantier, canal ; rien de personnel) et M8 compte les leads qui portent cette clé. Si
   `lien_utm` est vide (site du profil absent, ou message privé), aucun lead ne pourra porter la clé : dis-le, ne promets
   aucune mesure. Un refus `REJ-UTM-CONTENT-INCOHERENT` veut dire que le lien du contenu date d'avant la convention :
   propose-en un nouveau texte (révision) après le rejet du propriétaire.
7. **La demande de témoignage** est un message privé au client : elle ne s'envoie que si le paquet dit
   `contact_client.autorise` (le client a consenti à être contacté, preuve à l'appui).
8. **Retrait du consentement (Loi 25).** Si le client dit qu'il retire son consentement, enregistre-le tout de suite
   avec `m7_enregistrer_retrait_consentement_marketing` (canal, aucune note libre). Il bloque tout contenu de ce
   chantier, paquet déjà proposé ou approuvé compris. S'il dit `contenus_deja_exportes`, le propriétaire retire les
   publications à la main : dis-le. Un retrait ne se lève pas ; un nouveau consentement passe par un nouveau
   « Terminer ».
9. `m7_publier_post_social` (T3) n'est jamais utilisé pour cela : la publication réelle n'est pas câblée.
