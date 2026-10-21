# Qualification de la continuation M1 — 10 octobre 2026, Toronto

OPSYS-AI reste **PARTIEL**. Cette tranche prépare la réception SMS M1 sous permissions : codec/reçu Python déterministes, captures Host privées, conservation de la commande originale, propriété Task/Context et adoption après le véritable COMMIT puis la confirmation de sa propre completion. Le signal capturé ferme l’état avant adoption ; après adoption, la révocation du Host reste exigée. Une lecture ne doit pas muter les tables. Les refus et inconnus conservent leurs intentions sans autoriser une nouvelle action.

Base publiée : `33911c7ba887a0134eaa7223cadbaa76ff096e3f`. Le [registre exhaustif](registre-74.json) rapproche **74 chemins : 39 modifications avec préimages et 35 nouveaux fichiers**. La sélection CI conserve ses 199 entrées et ajoute 21 suites existantes exclues aussi de `test:fast` : 220 chemins uniques. Le SourceReceiver suivant reste isolé.

## Vérifications

- **952 tests Core, 36 suites disjointes, zéro échec ou skip** : 809/30 puis 143/6, mêmes 36 421 empreintes sources actuelles. Temps 98,172 s et 44,028 s ; pics RSS 1 682 411 520 et 1 785 159 680 octets. Origines vérifiées, EOF/PIDFD/propriétaires fermés. Aucun total historique chevauchant ajouté.
- Backend : **2 292 réussites, zéro échec, cinq skips PostgreSQL/Docker**. Dépendances du périmètre rehashées pour cette publication ; le résultat n’est pas réexécuté ni présenté comme nouveau. Ruff ciblé et vérificateur métier qualifiés dans les preuves précédentes ; dix départements et 242 outils dérivés des manifestes.
- Oxfmt/Oxlint sur 51 fichiers : exit 0, **six avertissements max-lines conservés**, zéro erreur.
- **Build Core complet PC1 r2 : exit 0**, 521,868 s, pic RSS 6 022 696 960 octets sous garde 7 GiB. 18 groupes DTS, deux groupes SDK, 158 sous-chemins publics, UI/postbuild vérifiés. L’essai rouge heap 4 352 MiB est conservé ; reprise explicite heap 5 120 MiB, sans changement des dépendances ou de la CI.
- Build : 43 785 sources, 137 176 fichiers originaux et 4 060 liens protégés ; sorties rapprochées au census et relues indépendamment. Snapshot physique candidat 73 ; candidat 74 différent seulement par la liste CI, aucun code de production différent.
- **TypeScript global NON QUALIFIÉ** : garde RSS 3 GiB déclenché après 28,481 s, aucun diagnostic Source émis. Le build ne qualifie pas ce contrôle. Reprise avec budget justifié préparée séparément. `core/packages/plugin-sdk/dist` n’est pas préparé par ce seul build.

Les [preuves sélectionnées](preuves/) conservent reçus, JUnit et conclusions avec leurs empreintes. Logs complets, origines, censuses et essais rouges restent dans l’espace privé de qualification ; leurs références ne prétendent pas qu’ils sont tous publiés ici. Stamps du clone physique sans `.git` : `HEAD/commit=null`, aucune attribution fabriquée au futur commit. **La CI du nouveau commit exact reste à obtenir.** Les succès du précédent HEAD ne sont pas hérités.

## Limites et suite

Pas de réception SMS de production jusqu’au modèle/fournisseur prouvée. Gate, reçus métier et données de test fictifs ; claim SQLite, permis privé, COMMIT et attente de completion réels. Raccord Original-C natif complet, SourceReceiver, copies Context/FollowupRun, policy et tous les senders restent à joindre avant un parcours positif. Aucun téléphone, paiement, merge ou déploiement exécuté.

Pack léger : 426 empreintes et dispositions des 302 sources transférées conservées. **104 preuves exclues et supplément complet indisponibles** ; conversations absentes inconnues. Les déclarations générées présentes proviennent des producteurs canoniques verrouillés, sans les assimiler au supplément absent.

La suite conserve dix départements profonds, Core OpenClaw, outils déterministes, permissions, dashboard, mobile quatre profils/hors ligne, avatars et mémoires métier/développement séparées. Verticale **M7→M1→M2→M3→M4/M6→M5→M8/M9/M10**, identifiants communs et preuves de reprise. Le chantier attribue chaque écriture à un seul responsable ; les lecteurs Claude/LiteLLM utilisent des copies immuables. Avis de modèles et quota rapporté par le propriétaire ne constituent pas des preuves d’exécution ou de consommation mesurée.
