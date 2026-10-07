# T4.22 — Comptes M5, 7 octobre 2026, Toronto

Base : `453545df9f9878cc24f624f1f4daafc2b367ca8f`. OPSYS-AI reste **PARTIEL**. Conception directement approuvée ; les permissions locales ont été rétablies. Le code préparé uniquement en mémoire a été restauré depuis les appels de cette conversation, puis réellement exécuté dans le clone isolé. Aucune garantie de mémoire permanente n’est supposée.

L’écran `/comptes`, accessible depuis « À voir », présente créances envoyées, comptes à payer PO/sans PO et attentes de facturation. Les outils existants calculent les montants, les permissions et les totaux. Inconnus, anomalies, âge depuis envoi, totaux incomplets, mentions et versions fiscales restent explicites. Aucun paiement, envoi ni application du rapprochement proposé.

Cache personnel normalisé, gardes avant/après lecture, refus jamais remplacé par cache. Créances par jour local ; première page AP seule en cache, suites en ligne remplacées comme pages courantes. La course entre réponse AP initiale tardive et changement de filtre a été démontrée rouge, puis corrigée et vérifiée. Les noms de versions fiscales sont des données, jamais des clés de traduction construites depuis le serveur.

Qualifications : 2761 tests Jest /133 suites ; quatre cas HTTP MCP/SQLite couvrant admin, employé, vendeur et révocation, lectures sans mutation ; types, Ruff et vérificateur métier ; export Metro Android JavaScript, 1535 modules. Les résultats, commandes, empreintes et RSS sont dans le registre. La suite M5 existante passe ; deux fichiers mobiles ont changé pendant cette exécution, aucune source Python n’a changé. La qualification HTTP finale est relancée sur le code final.

L’essai Hermes local échoue car son compilateur Linux x86 ne s’exécute pas sur cet hôte ARM ; il reste conservé. L’export JavaScript sans bytecode correspond à la CI mobile actuelle. Il ne qualifie pas Hermes ni un téléphone natif. La compilation Core complète locale passe (`pnpm build`), sous surveillance RSS/temps/espace disque. Elle a tourné pendant édition documentaire ; aucune source Core ni dépendance verrouillée n’a changé. La mesure startup JS locale dépasse encore le seuil : 371600 B pour 371332 B (268 B). La commande build sort à zéro, ce qui ne qualifie pas ce guard. Le seuil n’a pas été relevé. La CI du nouveau commit reste à obtenir.

426 contenus du pack léger rapprochés : 302 sources et 124 supports, empreintes transport relues. Le registre décrit chaque préimage, adaptation, origine, vérification et limite, et conserve les dispositions antérieures. Les 104 preuves omises restent absentes ; leurs références ne valent ni disponibilité ni réexécution. Le supplément généré absent reste absent. L’historique rouge/vert et les preuves antérieures restent conservés.

Publication autorisée sur la branche privée existante et PR #623 en brouillon, sans force-push, fusion ni production. CI du nouveau commit à obtenir ; le résultat exact sera ajouté à la PR et à une capsule de preuves distincte sans confondre le parent historique.

T4.22 reste partiel jusqu’à qualification native. M6/T4.23 conserve son blocage digest Core déjà diagnostiqué. Les dix départements profonds, les quatre profils mobiles et les mémoires métier/développement séparées restent requis ; cet écran ne clôt ni M5 complet ni les ambitions produit.

[Registre exhaustif](REGISTRE-COMPTES-M5-2026-10-07-r1.json).
