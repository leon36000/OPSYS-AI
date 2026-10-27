# Fournisseurs et tarifs → M10 : audit avant raccord

27 octobre 2026, source `04da87660d290ffb294b8a4eaff2f1cbb72b4705`.
Statut : **PARTIAL**, conception du prochain raccord; aucun nouvel événement livré par ce document.

## Objectif et état mesuré

Une modification admin du fournisseur ou du coût matériau doit laisser une référence
durable dans M10, sans recopier coordonnées ou prix dans une mémoire accessible hors M6.
Les formulaires HTTP/SQLite sont qualifiés; leurs ports écrivent journal, audit et reçu.
Ils ne publient pas encore les changements fournisseurs/tarifs vers M10.

Réutiliser `opsys.catalogues_memoire`, l’outbox, le répartiteur et le registre M10
`references_configuration` déjà qualifiés pour modèles, lignes et matériaux. Les événements
d’affaire ne conviennent pas à une fiche fournisseur : aucune affaire artificielle.

## Sources réelles et différences

`fournisseurs.py` garde un journal vivant : création puis mises à jour, fusion dans l’ordre,
no-op si le contenu est identique. Les entrées possèdent `horodatage`, mais ni révision,
ni chaîne de hashes, ni `source_id`. Le hash de fiche courante utilisé par le CAS console
ne désigne pas nécessairement un maillon historique : une ancienne mise à jour partielle
peut fusionner des champs antérieurs. Un consommateur différé doit vérifier la source à
son rang d’origine, même après une correction ultérieure.

`livre_prix.py` écrit des entrées append-only avec `date_effet`; il ne stocke aucun
horodatage de réception serveur. `date_effet` est une date commerciale, pas une date
d’écriture. Le lecteur `tarif_soumission.py` ferme les clés autorisées du maillon : lui
ajouter silencieusement `horodatage` ferait refuser les nouveaux tarifs. Les métadonnées
SQL exposent `cree_le`, dont la copie conserve explicitement la présence ou l’absence de
fuseau. Ajouter UTC à un datetime naïf serait une invention. Le nouveau raccord ne doit
ni modifier le format historique de prix ni transformer une date effective en minuit UTC.

## Décision et tranche minimale

Commencer par **fournisseurs**, dont l’horodatage source existe déjà. Ajouter au propriétaire
M6 une projection pure de référence pour un préfixe de journal borné : rang réel, numéro
de version de la fiche dans ce préfixe, hash déterministe du préfixe validé et horodatage
de l’entrée. Le hash couvre aussi les champs fusionnés : altérer un ancien champ hérité
doit invalider la référence, même si la dernière entrée reste intacte. Conserver les valeurs
historiques acceptées par le domaine, sans leur imposer les nouvelles limites du formulaire.

Le courtier du socle utilisera cette projection du propriétaire pour produire et relire
la référence; M10 reste pur et aucun département n’importe un autre département. Étendre
explicitement les genres fermés du schéma M6 et de M10. Publier seulement après un append
réel du port privé, dans son savepoint source/audit/reçu. Une panne de publication annule
tout. Le reçu exact retourné après une correction ultérieure ne republie rien. Un no-op
ne crée pas de version mémoire. Aucun rattrapage automatique des écritures anciennes.

Le payload garde les six champs existants de référence : fait, genre, rang, version, hash,
horodatage. Aucun nom, identifiant libre, contact, condition fournisseur ou coût. La preuve
de réception doit rester distincte de la publication. Les lecteurs ne gagnent aucun droit.

**Tarifs ensuite**, avec une provenance de réception durable explicite qui ne change pas
le contrat fermé du livre de prix. Cette décision demande un choix de stockage et des tests
sur la transaction complète; le présent audit n’autorise pas un timestamp dérivé arbitraire.
Ce travail est technique et réversible, sans gate humain supplémentaire tant qu’il conserve
les permissions, les données fictives et les limites de la session.

## Preuves requises

- Création puis correction fournisseur par HTTP → deux publications → vrai répartiteur
  → deux références M10 privées, sources relues et chaîne valide après réouverture SQL.
- Livraison différée de la première version après la seconde; rejeu du reçu original et
  second identifiant de livraison sans nouveau maillon.
- Hash/version/rang/horodatage altérés, champ hérité du préfixe corrompu, source absente,
  champ supplémentaire ou chaîne M10 invalide : refus sans mémoire ajoutée.
- Panne outbox : aucun fournisseur, audit ou reçu partiellement validé. No-op, rôle révoqué,
  quota et concurrence gardent les propriétés déjà qualifiées des ports.
- Contacts et prix canaris absents de l’événement et de M10; les anciennes trois familles
  et leurs badges restent fonctionnels. Populations non additionnées.

Fichiers concernés : nouvelle projection pure M6, `fournisseurs_console.py`,
`src/opsys/catalogues_memoire.py`, schéma `m6.catalogue_reference.json`,
`m10_memoire/references_configuration.py`, tests ciblés de cascade et de console.
QA privée habituelle, Source en lecture seule pendant l’exécution. Pas de modèle requis.
M6, M10 et OPSYS restent PARTIAL; import courriel, historique de prix navigable,
PostgreSQL, navigateur natif et mobile ne sont pas qualifiés par cette préparation.
