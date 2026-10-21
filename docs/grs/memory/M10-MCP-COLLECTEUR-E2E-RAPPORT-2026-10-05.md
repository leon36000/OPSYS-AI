# M10 — raccord intégré MCP, collecteur, SQLite et Python HTTP

État : qualification locale du raccord existant. Ce lot ajoute des tests et leur fixture isolée, sans changer le code de production. **r363 : cinq parcours complets passent, Oxlint/Oxfmt et Ruff verts**, sans erreur ni skip. Trois parcours antérieurs sont conservés et deux nouveaux traversent le vrai runtime MCP, le vrai observer du collecteur, la base SQLite du transcript et le vrai service M10 Python sur loopback. Le ticket, l’admission fournisseur et l’effet métier source restent synthétiques.

## Montage et contrat observé

Les deux nouveaux cas réutilisent `withPython` dans `opsys-postflight-delivery.python-http.integration.test.ts` et la fixture Python existante. Celle-ci accorde au seul profil jetable `it-postflight` le droit supplémentaire `m3_marquer_devis_accepte` dès sa création ; activation et révision 2 restent inchangées. Aucun profil réel, catalogue de production ou droit client n’est modifié.

Le helper `opsys-postflight-mcp.test-support.ts` persiste une entrée et un transcript sous l’agent **m03-estimation**, puis vérifie leur reçu avant de créer le collecteur. Il n’utilise pas le helper historique qui force `main`. L’admission provider/attempt est explicitement synthétique et sa fonction d’autorité est un no-op de test ; les tests d’autorité existants restent distincts.

Le ticket et le serveur source sont deux processus Node MCP stdio synthétiques. Le runtime et le client SDK sont réels, aucun mock de `assertBeforeEffect`, `observe` ou de la façade SQLite. Au moment de recevoir le RPC métier, le processus source ouvre lui-même le fichier SQLite canonique en lecture seule. Il enregistre uniquement la clé d’intention, son état et le nombre de lots. Les assertions exigent **une intention `uncertain` sous la clé exacte et zéro lot avant résultat**. Aucun jeton, ticket ou argument client dans ce journal d’observation.

## Résultat connu

Le peer renvoie un résultat source marqué `fictif: true`. Le collecteur réel convertit l’intention en un seul lot fermé, avec affaire, profil, révision, clé et outil exacts. `deliverPending` appelle le vrai endpoint privé runtime de Python/M10. L’ACK confirmé retire le lot local ; l’inspection du registre M10 trouve un seul fait candidat exact et une chaîne valide.

Ce parcours qualifie l’ordre et la composition Core/SQLite/M10 pour un résultat MCP reçu. Il ne prouve pas l’acceptation réelle d’un devis, le contrôle humain M3, l’émission/consommation Python du ticket ni une exécution de modèle.

## Transport perdu et reprise

Le peer observe l’intention et sort avant de renvoyer un résultat. Le vrai SDK rejette l’appel ; le collecteur rapporte l’incertitude, garde une seule intention, ne crée aucun lot et refuse la livraison. Le manager est ensuite fermé et réacquis : le prochain effet est testé avec un transport de nouveau disponible. Son refus vient ainsi du collecteur, pas d’une ancienne connexion cassée.

Une autre clé dans la même tentative est refusée avant un deuxième appel source. SQLite est fermée puis réouverte ; l’intention demeure exactement identique. Un nouveau collecteur tentant la même clé est refusé par la réservation durable. Le journal du peer ne contient qu’une seule observation et M10 ne contient aucun fait. Ce cas ne prétend pas garantir l’absence de replay sous une autre clé après un redémarrage complet ; le registre ne fournit pas de tombstone après ACK ni rapprochement humain automatique.

## Qualification conservée

r360 : trois parcours existants passent, les deux nouveaux échouent avant RPC parce qu’un template de script stdio interprétait les échappements de newline. Le correctif utilise `String.raw`. r361 : les cinq parcours passent, mais lint refuse un `if` sans accolades. r362 : cinq parcours, lint/format/Ruff verts. Après revue Luna, r363 renforce l’oracle du processus source avec la lecture du nombre de lots, puis requalifie le fichier complet : **5/5**, lint/format/Ruff verts. Tous les reçus et variantes sont conservés, aucun rouge remplacé.

Durée totale r363 : **52,747 s** ; pic RSS du groupe Vitest **1 773 187 072 octets**, garde inchangée de 2 Gio et 180 s, heap Node 1 024 Mio. Aucun nouvel OOM, sources stables pendant l’exécution et aucun descendant du groupe survivant. Ces cinq tests incluent les trois tests TCP précédents ; leurs totaux ne s’ajoutent pas comme cinq nouvelles capacités ou cinq nouveaux cas au total antérieur.

## Limites et suite

Admission fournisseur, tickets et effet source synthétiques ; pas de provider, runner embarqué complet, véritable mutation M3, émission Python de ticket ou preuve cryptographique d’un effet ancien. Aucun nouveau daemon, reprise permanente, connecteur externe, paiement, publication ou dépendance. Compilation globale Core, types globaux et CI distante non qualifiés. Les intentions sans résultat restent conservées : la prochaine capacité utile est leur diagnostic/rapprochement humain sourcé, sans purge ni replay aveugle.

Cette preuve retire la lacune du raccord **MCP réel / observer réel / SQLite / M10 HTTP**. La lacune du parcours complet modèle/runner/outil métier réel demeure. M10 et le produit global restent partiels ; la préparation Git est locale, sans push disponible.

## Preuves

[Capsule](../../research/REPRISE-2026-10-05/preuves/M10-MCP-COLLECTEUR-E2E-r1.tar.xz) ; [inventaire SHA-256 et références](../../research/REPRISE-2026-10-05/preuves/M10-MCP-COLLECTEUR-E2E-r1.json). Reçus, JUnit complets, sources exactes, designs et deux revues Luna en lecture seule sont conservés. Les entrées et toutes les références d’archives sont relues avant finalisation. r364 contrôle les dix chemins de sources, documents et revues avec la configuration de secrets par défaut ; ce n’est pas un scan de toute l’archive.
