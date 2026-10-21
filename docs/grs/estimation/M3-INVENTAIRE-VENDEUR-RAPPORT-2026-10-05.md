# M3 — retrouver les devis du vendeur

Le vendeur peut lister les devis des leads qui lui sont actuellement assignés, sans connaître
leurs numéros. L’outil `m3_lister_devis` réutilise le registre durable, le réducteur d’états M3,
la projection commerciale et les faits courants d’assignation M2. Il ne crée aucune facture,
acceptation client, demande d’envoi ni nouvelle donnée commerciale.

## Contrat et accès

Lecture T0 réservée à un appareil humain `seller`; personne active et rôle relus dans la base.
Aucun argument de propriétaire, rôle ou dossier n’est accepté. Défaut 20 devis, limite entière
entre 1 et 50, curseur suivant ou null. L’ordre repose sur le numéro de devis. Les états
courants incluent brouillons, envoyés et acceptés; `envoye` signifie approuvé pour envoi selon
le contrat existant, pas livraison effective au client.

Le curseur canonique base64 contient la personne et le repère de tri. Il n’est pas signé et
n’accorde aucun droit : chaque page revalide l’identité et la propriété actuelle de chaque
lead. Un repère inconnu, appartenant à un autre vendeur ou réassigné produit le même refus
générique. Une modification du curseur ne peut pas étendre les droits. Aucun total global ou
identifiant hors portée n’est exposé. Le vendeur conserve la vue commerciale déjà autorisée
pour ses devis; cet outil ne donne aucune portée supplémentaire à l’employé, l’admin ou un agent.

## Preuves et état

ROOT r306 : **137/137 dans cinq fichiers complets**, Ruff et manifestes verts. Les tests
couvrent lecture sans mutation, pagination, états effectifs, identité inactive, rôle retiré,
réassignation du repère et curseur forgé visant un devis étranger ou inconnu.
ROOT r307 : **10/10 dans le fichier complet d’intégration des accès**, Ruff et manifestes verts.
Le nouveau parcours passe par le vrai MCP et `Capacites.appeler`, avec les assignations M2
produites par les outils réels puis une désactivation de personne; aucune lecture n’écrit dans
la base. Les tests de portée générée incluent maintenant cet outil pour le vendeur seulement.
Les deux reçus gèlent les sources, sans changement pendant exécution ni OOM observé.

## Limites et suite

Cette tranche livre le contrat backend et ses accès. Le raccord de l’écran vendeur est en
cours; aucune interaction sur téléphone ou rendu React Native n’est prouvée ici.
La réponse est bornée, mais le réducteur relit et filtre le registre entier à chaque appel.
Aucun benchmark de grande entreprise n’est fourni. Une réassignation entre pages peut retirer
un devis ou invalider le repère : le client doit repartir de la première page après un refus.
Aucune pagination ne promet un instantané immuable pendant des changements métier.

Code : departments/m03-estimation/src/m3_estimation/outils.py.
Tests : departments/m03-estimation/tests/test_acces_par_proprietaire.py et
 tests/test_acces_par_proprietaire.py, avec les quatre suites de régression r306.

## Sources et reçus

[Capsule sources et reçus](../../research/REPRISE-2026-10-05/preuves/M3-INVENTAIRE-VENDEUR-r1.tar.xz)
— SHA-256 7270a1eb873865693fada64c71c05227abe99272a1462ea6dc8e766ba3497f10.
[Inventaire](../../research/REPRISE-2026-10-05/preuves/M3-INVENTAIRE-VENDEUR-r1.json).
Scan r308 : 18 fichiers, aucune détection. La capsule conserve le rapport avant ces liens.
