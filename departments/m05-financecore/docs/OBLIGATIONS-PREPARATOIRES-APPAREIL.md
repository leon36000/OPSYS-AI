# Déclarations préparatoires paies, DAS et dettes — T4.16-b.a.1

Ce lot enregistre une déclaration humaine non attestée ; il ne paie, ne remet,
ni ne comptabilise rien de final. La personne qui dit « CPA » ou « relevé bancaire »
dans une source ne prouve pas cette provenance. Admin DEVICE actif est confirmé
par SQL ; ce rôle ne devient ni propriétaire ni professionnel agréé.

Deux outils fermés :

- `m5_lire_obligations_preparees_appareil` : T0/N0, admin, portée globale ; arguments
  `aujourd_hui` civil explicite, `decalage` entier 0..10000, `limite` entier 1..8.
  Sans Meta de mutation. Couple unique `accepte/resultat`, ou `accepte:false/verdict`.
- `m5_enregistrer_obligation_preparee_appareil` : T1/N3, admin, portée globale ;
  exactement `categorie`, `operation`, `declaration`, `revision_attendue`, `motif`.
  `declarer` exige l'objet brut fermé ; `retirer` exige null et un motif non vide.
  Aucun acteur, appareil, UUID, URL ou rôle dans les arguments métier.

Les catégories sont seulement `paies`, `das`, `dettes`. Le montant est un texte
non négatif de 1..12 chiffres entiers et 0..2 décimales ou null. Aucune conversion,
troncature, correction ou arrondi de la déclaration brute. Source 120 points,
champs texte calendrier 240, motif 500 ; Unicode scalaire valide. Les dates
civiles impossibles et intervalles connus inversés sont refusés ; des champs null
restent des inconnus. Une obligation retirée ne retombe jamais sur une ancienne
version. Absence, retrait et déclaration zéro documentée sont trois situations.

Le registre `m05-financecore/obligations_preparees` utilise les maillons durables
existants et deux types nommés : `declaration_obligation_preparee` et
`retrait_obligation_preparee`. Chaque maillon version1 scelle l'objet brut,
la référence précédente de sa catégorie, le motif, auteur SQL admin/source appareil,
réception serveur, heure déclarée appareil et intention appareil/clé/empreinte
canonique des cinq arguments. Aucun UUID rétrospectif n'est fabriqué. La référence
est `{registre,index,ligne_id,precedent_ligne_id}` et vise son préfixe original.

La lecture valide la chaîne et les formes avant de sélectionner la dernière
révision par catégorie, puis pagine l'ordre paies/DAS/dettes. Les pages courantes
ne sont pas un snapshot immuable. `ABSENTE` met toutes les données persistées à
null. L'objet `calendrier_preparatoire` est une projection distincte réutilisant
`calendrier_obligations.lire_obligations_documentees`, avec `aujourd_hui` fourni.
Cette projection normalise certains textes ; le brut stocké demeure inchangé.
Une échéance passée signifie à vérifier, jamais impayée. Aucune règle fiscale ni
valeur récurrente n'est calculée, aucune source textuelle n'est attestée.

L'ACK accepté est fermé : `accepte`, `version_schema`, `resultat`, `registre`.
`resultat` contient les neuf champs persistés de la ligne de lecture, **sans**
`calendrier_preparatoire`. Aucune date d'évaluation n'est inventée à partir de la
réception. Un rejeu est confirmé seulement par son maillon, association propre,
corps, auteur et heure appareil d'origine ; une révision suivante ne l'invalide
pas. La comparaison JSON canonique distingue booléens et entiers. Un négatif sans
preuve indépendante propre reste inconnu côté consommateur ; il ne certifie pas
l'absence d'un effet historique. Conserver UUID, corps et destination d'origine.

La façade exige le contexte spécifique `intentions_obligations_m5` fourni par le
socle, les horloges de réception et la borne de sortie fiable. Gardes actuelles
avant lecture métier et claim/cache ; précondition fraîche de catégorie uniquement
pour un nouvel effet. Le socle contrôle aussi les colonnes réelles du claim et la
portée d'outil. Son N3 trace seulement une acceptation métier, dans la même
transaction. Toute panne postappend/projection/trace doit sortir en RuntimeError
et annuler maillon, claim et trace ; aucun refus certain ne masque un append.

Bornes : snapshot copié puis validé, au plus 10000 maillons. Le prochain index10000
est refusé au préflight. La copie n'est pas une borne d'allocation mémoire. Les
réponses complètes sont mesurées avec `json.dumps(...,ensure_ascii=False)`, plafond
`min(5400,quota Cap)` ; les deux valeurs de `rejoue` sont contrôlées pour mutation.
T0 n'a pas de champ `rejoue`. Aucun fragment, omission ni artefact de repli ne doit
être créé par ces outils. Les hooks Cap et leur trace sont qualifiés séparément
par Root, pas par les tests de façade directe.

Les tests département utilisent vraie SQLite, personnes fictives et identité
injectée, sans authentification HTTP/Gateway. Ils vérifient lecture sans mutation,
retrait, rejeu propre après redémarrage, refus avant source, rollback et concurrence.
Les preuves Cap/transport et les captures produites par Root restent distinctes.
Aucune preuve téléphone, Hermes, PostgreSQL ou fournisseur ne découle de ce lot.

`department.yaml`, cash libre, calendrier existant, CFO, mouvements du principal,
factures et bus restent hors raccord. Une consommation financière future exige
son propre contrat de source/priorité/version/absence, sans substitution silencieuse.
La paie réelle et les remises officielles demeurent N5 et non livrées ici.
