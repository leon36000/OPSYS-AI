# T4.23 — Stock M6, 7 octobre 2026, Toronto

Parent `47ae120066c1bbe4fa6c97c9b885703525fd0ab0`. OPSYS-AI reste **PARTIEL**. Poursuite autonome et continuation privée autorisées par le propriétaire, sans force-push, fusion ni production.

L’écran `/stock` lit disponibilité et digest dans deux sections indépendantes. Calculs et quantités signées viennent de M6 ; aucun stock physique, unité de stock, total, curseur ou besoin d’achat n’est inventé. Fenêtres natives 15 articles/10 réservations et deux limites distinctes. Les lignes manquantes peuvent concerner d’autres matériaux. Le digest garde les écarts enregistrés, même nuls, sans fenêtre journalière ; `{}` ne fournit aucun seuil. Aucun effet matériel.

Le digest revalide une personne admin active avant registre/calcul, selon le guard M6 existant. Le contexte interne sans appareil est conservé. Neuf régressions de garde : vrai rouge 8F/1P avant correction puis qualification verte. Le lecteur mobile refuse héritage/accesseurs, malformations et compteurs incohérents ; un champ absent hérité a été reproduit rouge puis corrigé. Cache personnel normalisé, refus prioritaires et invalidation avant/après lecture. Les réponses initiales tardives sont écartées après rafraîchissement.

Preuves intégrées : **2842 tests mobiles /137 suites**, **1315 tests métier /2 skips PostgreSQL**, types mobile, Ruff global, vérificateur métier (10 départements/217 outils/125 outils appareils), export Android JavaScript (1540 modules). Onze contrats HTTP MCP/SQLite construisent un vrai parcours devis/réservation/réception/transfert/comptage dans le moteur Python ; la porte Core est simulée. Toutes les tables restent identiques autour des lectures. Le théorique reste 100 malgré comptage 98 ; transfert30, en-main70, réservé70, disponible0. Les fixtures natives portent leur provenance et `fictif: true`.

Les skips PostgreSQL correspondent à l’accès refusé au daemon Docker local. CI exacte nouvelle à obtenir. La CI du parent47 est historique (six workflows,37 jobs verts,2 opt-in Docker Desktop ignorés). Build Core candidat et types UI passent, mais le budget startup est encore rouge +25B : travail séparé, aucun seuil relevé. Téléphone, Expo SQLite, client authentifié et Hermes natifs restent non qualifiés.

302 sources et124 supports du pack léger rapprochés avec SHA transport relues. Les104preuves omises et le supplément généré restent absents ; références conservées sans prétendre les avoir réexécutées. Les rouges, erreurs d’environnement/invocation et verts portent des noms distincts dans le registre. Les déclarations de qualification restent bornées aux commandes réellement exécutées.

Les capacités profondes M6 (catalogue, prix, commandes, comptage physique et gestion fournisseur) demeurent requises. Les dix départements, Core OpenClaw, outils déterministes, permissions, dashboard, quatre profils/hors ligne, avatars et mémoires métier/développement séparées restent dans le périmètre. La suite T4.24/M7 commence par ses contrats natifs et ses permissions.

[Registre exhaustif](REGISTRE-STOCK-M6-2026-10-07-r1.json).
