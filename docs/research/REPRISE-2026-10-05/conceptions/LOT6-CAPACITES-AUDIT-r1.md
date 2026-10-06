# Lot 6 — audit interne des capacités par département

Lecture statique seulement de la console, des manifestes et des fabriques d’outils; aucun test, build, appel réseau, installation, accès à une valeur secrète, ni changement du dépôt. État des fichiers identifié par SHA-256 en bas.

## Ce que les sources prouvent

Departement.charger_outils() importe la fabrique réelle et valide type, préfixe et unicité des outils (src/opsys/departements.py:122-159). Les capacités déclarées ne sont donc pas le seul catalogue. M1 expose notamment m1_traiter_demande_entrante et exige données de canal, source/UTM et horodatage (departments/m01-front-office/src/m1_front_office/outils.py:1826-1860). M3 expose m3_estimer_projet (contrat et marqueur M2, photos, barème, seuils, quantité) et m3_qualifier_photos; photos/échelle insuffisantes bloquent le prix (departments/m03-estimation/src/m3_estimation/outils.py:1741-1797,1798-1810). M5 expose un registre et des calculs internes, par exemple taxes versionnées et brouillons de facture (departments/m05-financecore/src/m5_financecore/outils.py:3858-3948). M7 décrit des campagnes en brouillon/export manuel (departments/m07-marketing/department.yaml:5-18); son export n’appelle pas une plateforme (departments/m07-marketing/src/m7_marketing/outils.py:1264-1284), et la publication sociale Postiz reste dry-run/refusée tant que l’Approval Engine n’est pas raccordé (même fichier:1562-1585). M10 expose préflight/mémoire interne (departments/m10-memoire/src/m10_memoire/outils.py:550-580). Les cinq manifestes disent tous mode: ombre; leurs liens/dépendances sont des contrats, pas des tâches observées.

## Cinq risques de dérive concrets

1. **M1, profil activé ≠ capture opérationnelle.** La page dit que l’activation n’effectue pas la synchronisation Core ni ne fait tourner de tâche (agents_ui.py:88-92); les déclencheurs sont explicitement des intentions non raccordées (agents_ui.py:266-267, connecteurs_ui.py:123-127). Une équipe peut avoir un profil activé et pourtant ne recevoir aucun nouveau lead. La fiche ne donne aucun dernier dispatch observé.
2. **M3, catalogue d’estimation ≠ mesure photo disponible.** Le panneau classe mesure photo/géospatiale en capacité à qualifier (connecteurs_ui.py:30-37), tandis que l’outil M3 reçoit déjà les photos en arguments et refuse le prix si qualité/échelle ne passent pas. Le vendeur ne peut déduire d’une configuration d’agent que ses photos sont mesurables ou qu’un devis est prêt.
3. **M4 OSRM ≠ géométrie d’estimation M3.** Le seul adaptateur OSRM consulté est celui de Field Ops; il demande une matrice table à un sidecar local et retourne durée/distance de trajet, avec coordonnées sensibles (departments/m04-field-ops/src/m4_field_ops/distances_osrm.py:1-18,35-47). L’assimiler au connecteur photo/mesure de toiture confondrait trajet routier et dimensions; l’audit M3 précise qu’aucune source géospatiale d’estimation n’est raccordée et que distance_km n’est qu’un contexte appelant (docs/grs/estimation/M3-APPRENTISSAGE-AUDIT-2026-10-05.md:21).
4. **M5/M7, outils métier ≠ intégrations fournisseurs.** Un m5_creer_facture_brouillon n’atteste ni logiciel comptable ni dépôt fiscal; aucun adaptateur comptable n’est dans les quatre lignes de connecteurs. M7 peut produire/exporter un paquet ou un lien UTM, mais l’export est manuel; la publication sociale est gated. Une capacité visible peut donc être prise pour une action externe effectuée, alors qu’aucune preuve d’envoi/fichier n’est fournie par cette vue.
5. **Présence/configuration ≠ clé valable, droit ou API couverte.** etat_connecteurs ne traite que SMS, STT, mémoire PostgreSQL et embeddings; une valeur non vide donne « présence déclarée », avec authentification distante non vérifiée (connecteurs_ui.py:40-80). La page cache les valeurs et avertit que l’inventaire API est partiel (connecteurs_ui.py:83-108,131-144). Elle protège les secrets mais ne permet pas de conclure que M3/M5/M7 ont leurs fournisseurs, scopes ou API requis. Une DSN mémoire seule ne prouve d’ailleurs pas le schéma PostgreSQL requis (l.49-54).

## Première correction utile (une seule)

Dans la page existante src/opsys/console/connecteurs_ui.py, ajouter une fiche lecture seule **« Capacité devis M3 »**, alimentée par deps["m03-estimation"].charger_outils() et le manifeste, plutôt qu’une ligne générique « à construire » : montrer séparément outil d’estimation réellement catalogué, entrées métier nécessaires (marqueur M2, photos/échelle, barème), mesure photo/géométrique non disponible/non qualifiée, et OSRM trajet M4 hors de cette capacité. Afficher « exécution non observée » et « fournisseur/authentification non vérifiés » lorsque c’est le cas; aucun prix, feu vert chantier ou secret. Cela aide le vendeur à expliquer pourquoi une demande attend encore les photos sans créer d’estimation fictive.

**Scénario vérifiable après changement :** catalogue M3 contient m3_estimer_projet, M4 possède éventuellement son adaptateur OSRM, aucun adaptateur photo n’est déclaré. La fiche montre estimation locale existante, photos/échelle encore requises, OSRM limité au trajet, mesure photo indisponible et aucune exécution prouvée. Elle ne présente pas la configuration comme synchronisée ni n’expose de clé.

## Preuves (SHA-256 des sources citées)

- src/opsys/console/agents_ui.py — 73a082bd5e9262065900c04f9465de67a8a2b74941b3a33dec21fc0b16dd3b14
- src/opsys/console/connecteurs_ui.py — 7494a0742edd52e8bcd7f6f6da4111343b0c58eddd13b78dbbe5c89abe0c1835
- src/opsys/departements.py — 04be90246c690975ede44f0e185ebbbcf40153f8e23c98ee7904f58b008ad288
- src/opsys/agents.py — eb7516f3a853bb443ac6f5f26fa3dbf19314119091d496c82e4b9f9be2ddf883
- departments/m03-estimation/department.yaml — d54bc461618309b6d39420f6caf89ef29c927d9c0ee93bb50cf0c6833762e8d0
- departments/m03-estimation/src/m3_estimation/outils.py — 8157b9e8e4714fbdf4bd339e8376959c25ffd304b32093fdfc3f18c2cf356160
- departments/m04-field-ops/src/m4_field_ops/distances_osrm.py — 15d58bca13f4366e4bb1186e1b4616ff74c7f27a09ead58289f0f65e79fade28
- departments/m01-front-office/src/m1_front_office/outils.py — a02bc9921d8ea0c14274ac0a1ed521a302021715459271c915acc32c1afa5a04
- departments/m05-financecore/src/m5_financecore/outils.py — 3a06fe08c423287c927ac37b1461a6bb0f2dbff694e341b1fb45d7dffdbcf304
- departments/m07-marketing/src/m7_marketing/outils.py — 7246857becbc0af318f650419fb535c5951a7980e91a03dc3894e9ba5f87f209
- departments/m10-memoire/src/m10_memoire/outils.py — ff4e9a79889a37617ebe24c79cdba8fc388f645ce1f1d4ba5ca80d9cbf7f947c
- docs/grs/estimation/M3-APPRENTISSAGE-AUDIT-2026-10-05.md — la ligne 21 est la source de l’affirmation sur la jointure M3/M4 citée ci-dessus.

- departments/m01-front-office/department.yaml — e4ffb1cffa7c166b84d1a2880693ad497f21cb4c16f895fc8737bef5ddcbfcb1
- departments/m05-financecore/department.yaml — f7e18a1c80aa9f44b9345d06af682f00523938553fc08abba81d99db4f2c57f9
- departments/m07-marketing/department.yaml — 3e8b4b8782161417da083ae1698733d8e8a8a94a30c18cc3800f04b0d5895f3a
- departments/m10-memoire/department.yaml — 6ac8b7eddbb757523c8361f261adce173e5c339a7079ac02f40c580f65933ae0
- docs/grs/estimation/M3-APPRENTISSAGE-AUDIT-2026-10-05.md — 3f3c65537bf8705cde4e40fe7f91cdf5fd5014469cd6d3034e9afc37312363f0
