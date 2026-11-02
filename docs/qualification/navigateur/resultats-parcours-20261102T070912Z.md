# Résultats du banc navigateur — parcours — 20261102T070912Z

- Verdict : **PASSE**
- Navigateur : chromium 156.0.8078.4 (Playwright 1.64.1, headless)
- Durée : 7.4 s ; captures : 438 Ko

| Groupe | Constat | Verdict | Niveau |
|---|---|---|---|
| tableau-de-bord | tableau de bord : h1, 18 onglets, onglet courant, une carte par département (10 réels + 1 fictif) | OK | bloquant |
| tableau-de-bord | la pastille d'approbations annonce les 4 demandes en attente | OK | bloquant |
| tableau-de-bord | la personne connectée est nommée | OK | bloquant |
| reglages | écran des réglages : h1, onglet courant, 10 réglages « À décider » (4 de M2, 6 de M8), un bouton d'adoption N3 chacun | OK | bloquant |
| reglages | trois propositions seulement (les délais de M2), chacune étiquetée « recommandation, non validée » avec sa source ; aucune pour M8 | OK | bloquant |
| reglages | règles d'accessibilité (WCAG 2.1 AA maison) sur l'écran des réglages : 3 largeurs × 2 thèmes, aucune violation | OK | bloquant |
| reglages | écran des réglages : aucun défilement horizontal de la page à 375, 768 et 1280 px | OK | bloquant |
| reglages | la proposition (7 jours) PRÉREMPLIT le champ sans rien appliquer : l'état reste « À décider » | OK | bloquant |
| reglages | la raison est obligatoire côté navigateur (champ requis, soumission vide bloquée) | OK | bloquant |
| reglages | adopter : redirection, bandeau « Valeur adoptée (N3) » annoncé poliment, carte « Adopté », 9 réglages restants, journal rempli | OK | bloquant |
| reglages | valeur hors bornes : 400 et motif lisible (REJ-REGLAGE-HORS-BORNES), rien n'est adopté | OK | bloquant |
| reglages | adoption sans jeton CSRF : 403, rien n'est adopté | OK | bloquant |
| reglages | l'état du serveur après ces essais : 9 manquants, une seule valeur adoptée (jours_entre_relances), chaîne valide, une ligne au journal | OK | bloquant |
| reglages | revenir en arrière : la valeur est retirée, 10 réglages à décider de nouveau, le retour figure au journal | OK | bloquant |
| reglages | l'administrateur voit l'écran sans formulaire (note « Seul le propriétaire… ») et son POST direct est refusé (403) | OK | bloquant |
| global | aucune requête n'a quitté 127.0.0.1 (le banc refuse tout le reste) | OK | bloquant |
| global | taille totale des captures de cette exécution < 3 Mo | OK | info |
