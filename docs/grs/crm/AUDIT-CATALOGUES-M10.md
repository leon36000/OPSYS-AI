# Révisions M3/M6 → mémoire M10 — audit avant code

27 octobre 2026, source `ef6fcb31f267323b1a5dee4d1f6c65f5eb3833ce`.

Le parcours HTTP/SQLite est qualifié. Les modèles textuels M3, leurs lignes et les fiches
matériaux M6 écrivent leurs versions et l’audit SQL, mais ne publient pas encore de fait M10.
L’acceptation d’un devis atteint déjà M10 par `m3.devis_accepte` : ne pas refaire ce raccord.

## Réutilisation et frontières

Réutiliser outbox/répartiteur, schémas fermés du catalogue d’événements et `M10.Registre`
append-only dans un registre dédié `references_configuration` (type existant `evenement_memorise`). Les consommateurs d’amont (`etapes.py`, `amont.py`)
exigent une affaire : aucune affaire artificielle pour un modèle ou une fiche entreprise.
`provenance_documentaire.py` concerne les lots bancaires/PDF M5 avec schémas stricts; ne pas
leur faire accepter une configuration commerciale en élargissant leurs formes existantes.
Les nouveaux faits restent marqués `SENSITIVE`, hors paquets d’affaires et mémoire développement.
Aucune ouverture de rôle, de couche de contexte ou de droit de lecture.

## Patch minimal

Deux types bus : `m3.catalogue_reference` (registre modèles textuels ou lignes) et
`m6.catalogue_reference` (registre fiches matériaux). Liste blanche : registre source,
rang SQL, révision, empreinte, horodatage original. Aucun nom/identifiant utilisateur libre,
auteur, texte, clause, nom matériau, prix, fournisseur, quantité ou lead dans la charge.
L’identité d’événement est déterministe depuis type, registre, rang et empreinte.

Publication uniquement pour une nouvelle version, dans la transaction du producteur et de
son audit/reçu. Échec de publication : rollback entier. Aucun rattrapage ou rejeu automatique
des versions antérieures. Le consommateur M10 relit la source à ce rang, compare empreinte,
révision et horodatage, puis ajoute une référence dans la chaîne M10 dédiée. Pas de copie
ni d’interprétation du contenu source. Une référence sans source est refusée et suit les
retries/quarantaine existants. Déduplication du fait métier même sous un autre event_id.

## Preuves nécessaires

Outils producteurs réels → outbox → répartiteur → source relue → reçu M10/chaîne durable;
reprise sans doublon, versions distinctes, réouverture SQL, canaris privés absents du bus et
M10, ajout de champ refusé, source absente/incohérente sans écriture, rollback publication et
audit, non-rétroactivité, régressions M10 amont/confidentialité et parcours HTTP existants.
Qualification cible SQLite privée, pas core, navigateur natif, PostgreSQL ou GO global.
Les lectures de contenu restent dans M3/M6 sous leurs permissions; M10 mémorise les références.

## Réalisation et preuves

Le registre dédié `references_configuration` réutilise `M10.Registre` et le type
`evenement_memorise`, marqué explicitement `confidentialite=SENSITIVE`. Aucun lecteur
agent, paquet d’affaire ou mémoire développement n’est élargi. Le courtier du socle
`catalogues_memoire.verifier_source` relit et valide le journal par son domaine propriétaire
M3/M6 avant comparaison : la présence d’un champ source_id ne suffit pas. Le domaine M10
reste pur et les départements ne s’importent pas entre eux.

`tests/test_cascade_catalogues_m10.py` exerce les vrais producteurs privés et le bus SQL :
les trois genres sont publiés puis reçus par M10, avec source relue, chaîne durable et
reprise sans doublon même sous un autre identifiant de livraison. Versions successives
conservées, canaris privés absents des charges et maillons; champs supplémentaires,
source absente, source corrompue, référence contradictoire et chaîne M10 invalide refusés.
La panne de publication annule source, audit et reçu pour chacun des trois producteurs.
Aucun rattrapage automatique des versions historiques non publiées.

QA privée `crm-prefill-qa-20261027-r1/catalog-memory-v3` : 245 tests réussis,
aucun échec ni saut, 20,27 s; Ruff et vérificateur 291/173 réussis. Inclut les régressions
HTTP catalogue, sources M3, mémoire amont et confidentialité. Populations recoupées,
non additives. Source en lecture seule, réseau bloqué, CPU 100 %, mémoire 1 Gio, 96 tâches,
homes/tmp privés; commandes, empreintes, limites et reçus durables.

Les rouges restent conservés. V1 : trois échecs (snapshot préparatoire muté avant son rang
CAS; garde M10 sur nom de constante de champs; cascade associée), un lint. Le rang est
maintenant calculé sur le snapshot immuable, la constante suit la convention CHAMPS_ du
paquet sans changer la garde. La revue a aussi exigé la validation canonique de la source,
prouvée par corruption de clauses, précédent et nom conservant source_id. V2 : un échec
du harnais (`deepcopy` d’une liste de test à append spécialisé), corrigé sur copie de liste
ordinaire; deux lint corrigés. Cet échec de harnais n’est pas un bug produit.

Statut : **références de versions confirmées sur HTTP/outbox/SQLite**. Leur consultation
admin avec état de livraison reste à raccorder à l’interface. Aucune lecture de texte M10,
consolidation sémantique de clauses, import courriel, navigateur natif ou PostgreSQL qualifié
par ce jalon. M10 et CRM-07 restent PARTIAL.

## Consultation admin de la preuve

Les fiches matériaux, les modèles et leurs éditeurs de lignes affichent maintenant un
indicateur privé, calculé par `catalogues_memoire.consulter` et rendu par
`console/catalogue_memoire_ui.py`. La façade revalide l’admin actif et la session SQL avant
lecture. Aucun outil générique, nouvelle portée appareil ou lecture de contenu n’est ouvert.

`MEMORISE` exige ensemble : source canonique valide, publication exacte, reçu M10 `traite`
concordant et maillon attendu dans une chaîne M10 `SENSITIVE` valide. Sans reçu, même si un
maillon est présent, l’état reste en attente. Un reçu incohérent indique un conflit; échec,
quarantaine et corruption sont distingués. Sans publication, la version est explicitement
signalée comme non publiée; les GET ne déclenchent aucun rattrapage ni aucune écriture.

`tests/test_console_catalogue_memoire.py` prouve les transitions par HTTP et bus réels,
les réceptions absentes/échouées/en quarantaine, faux résultat, chaîne corrompue, version
sans publication et révocation avant lecture. QA privée `catalog-status-v2` : 108 tests
réussis, zéro échec/saut, 27,76 s; Ruff et vérificateur 291/173 réussis. Populations
recoupées, non additives. Revue statique indépendante sans constat sur faux MEMORISE,
autorité, chaîne ou effet des GET. V1 conservé : 107 réussites et une assertion de harnais
qui exigeait à tort une outbox entièrement vide malgré les faits M2 de la fixture, plus
deux imports à trier. La vérification porte désormais explicitement sur les types catalogue;
l’assertion générale de zéro effet sur toute la base reste maintenue.

La consultation de références est qualifiée sur HTTP/SQLite; la CI du jalon précédent
continue et ces changements attendent une publication normale ultérieure. La mémoire de
texte/clauses, recherche sémantique, navigateur natif, PostgreSQL et application mobile
restent hors de ces preuves. Aucun statut global terminé n’est induit.
