# BMAD ÉTAPE 3 — ARCHITECTURE M2 (REVENUE CRM)

Rédigé par : Architecte BMAD | Statut : PROPOSÉ | Portée : mode ombre, prouvable en CI Python

## 1. Arborescence du module

Racine : `departments/m02-revenue-crm/`, un fichier par responsabilité, aucune logique transversale dupliquée entre stories.

- `encodage.py` — encodage canonique injectif (préfixage par longueur) pour dériver identifiants et empreintes sha256.
- `horodatage.py` — validation ISO-8601 avec timezone des horodatages fournis par l'appelant, refus explicite sinon.
- `verdicts.py` — catalogue d'identifiants stables M2, incluant REJ-FRONTIERE-VIOLEE et REJ-TRANSITION-ILLEGALE.
- `registre.py` — registre append-only hash-chaîné, API ajouter/lire/tete/valider_chaine/assert_chaine/taille.
- `contrats.py` — validation structurelle du contrat gelé LeadQualifie consommé et des entités propres à M2.
- `frontieres.py` — détection des champs interdits (prix, montant, date d'exécution, engagement) et rejet associé.
- `ingestion.py` — réception d'un lead qualifié, inscription au statut nouveau, accusé de réception.
- `statuts.py` — machine à états des quatre statuts et table des transitions conditionnées.
- `interactions.py` — enregistrement des interactions humaines post-qualification.
- `readiness.py` — fonction booléenne pure de la gate M3 et émission du marqueur signé.
- `doublons.py` — détection et signalement des doublons potentiels, arbitrage humain, jamais de fusion.
- `digest.py` — digest quotidien déterministe des leads en attente d'action.
- `adaptateurs.py` — Protocols d'écriture vers un CRM tiers, implémentations in-memory fail-closed hors mode ombre.
- `fixtures.py` — chargement fail-closed des fixtures exigeant le marqueur fictif: true.

Les tests vivent sous `departments/m02-revenue-crm/tests/`, un fichier par story, car c'est le seul chemin découvert par le job CI protégé `gates`. Les fixtures vivent sous `fixtures/`, toutes marquées fictif: true. Justification : une story égale un fichier égale une suite de tests, ce qui rend la couverture traçable story par story.

## 2. Ce qui est réutilisé de M1 et comment

Décision nette : M2 DUPLIQUE les patrons M1 dans son propre arbre et n'importe AUCUN module de M1. Justification : le canon impose des frontières nettes et un flux M1→M2 unidirectionnel dont le seul point de contact autorisé est le contrat gelé LeadQualifie ; importer le code de M1 créerait un couplage inter-modules où toute évolution de M1 casserait silencieusement la gate CI de M2 et détruirait sa portabilité.

Sont réimplémentés à l'identique : le registre hash-chaîné (même algorithme de chaînage sha256, même API), la convention du catalogue de verdicts, la validation d'horodatage avec refus explicite, et le patron d'adaptateurs in-memory fail-closed. Justification : des algorithmes identiques garantissent que les empreintes restent comparables entre modules sans créer de dépendance de code. L'identifiant REJ-CONVERSATION-CLOSE est repris tel quel du catalogue M1 pour cohérence inter-modules. Justification : la stabilité des identifiants de verdict est un invariant transversal, pas une propriété de module.

## 3. Contrat de données M2

Principe d'attachement : composition par enveloppe, jamais mutation. Justification : le contrat LeadQualifie est gelé et épinglé sha256 ; M2 embarque une copie immuable du contrat d'origine dans un champ dédié avec son empreinte, et tous les champs M2 vivent dans une enveloppe séparée indexée par lead_id, ce qui laisse le contrat intact et vérifiable.

Entité LeadM2 (dossier commercial) :
- `lead_id` : chaîne, obligatoire, reprise à l'identique du contrat gelé, jamais régénérée. Justification : c'est la clé de jointure avec M1 et les modules aval.
- `contrat_gele` : dict plus empreinte sha256, obligatoire, copie immuable du LeadQualifie d'origine.
- `statut` : énumération fermée {nouveau, qualifie, converti, perdu}, obligatoire, initialisé à nouveau.
- `owner` : chaîne non vide identifiant un humain, absent à l'ingestion, obligatoire pour la transition vers qualifie.
- `prochaine_action` : dict {description chaîne non vide, echeance horodatage ISO-8601}, fourni par l'appelant, obligatoire dès qualifie, jamais généré par M2. Justification : le PRD exclut toute génération par LLM pour éliminer l'hallucination sur les engagements.
- `interactions_humaines` : liste de dicts {auteur, resume, horodatage fourni}, vide à l'ingestion.
- `readiness` : dict {readiness_ok booléen, empreinte, hash_tete, horodatage}, produit uniquement au franchissement de la gate.
- `motif_perte` : chaîne non vide, obligatoire si et seulement si statut perdu.
- `reference_devis_m3` : chaîne opaque, obligatoire si et seulement si statut converti, jamais de montant. Justification : le montant appartient à M3/M5, M2 ne stocke qu'une référence.
- `disponibilite_declaree` : chaîne libre optionnelle destinée à M4, jamais une date ferme.
- `signalements` : liste d'identifiants de SignalementDoublon, vide par défaut.

Entité SignalementDoublon : `signalement_id` dérivé par encodage injectif des deux lead_id triés et du critère, `lead_id_a`, `lead_id_b`, `critere` énumération fermée {contact_identique, ville_et_travaux}, `horodatage` fourni, `arbitrage` énumération fermée {en_attente, distincts_confirmes}. Justification : la v1 ne connaît pas d'état « fusionné » car l'exécution d'une fusion est hors périmètre.

## 4. Machine à états des statuts

Quatre statuts : nouveau, qualifie, converti, perdu. Table des transitions autorisées :
- nouveau → qualifie, condition : owner humain fourni ET prochaine action complète fournie.
- qualifie → converti, condition : décision humaine ET reference_devis_m3 fournie.
- qualifie → perdu, condition : décision humaine ET motif non vide.
- nouveau → perdu, condition : décision humaine ET motif non vide.

Tout autre chemin est rejeté avec REJ-TRANSITION-ILLEGALE et aucun maillon n'est écrit. Justification : la validation précède toujours l'écriture, ce qui rend le registre incapable de contenir une transition illégale. Une condition manquante sur un chemin autorisé est rejetée avec un verdict spécifique (REJ-OWNER-ABSENT, REJ-DEVIS-ABSENT, REJ-MOTIF-ABSENT) distinct du chemin illégal. Justification : distinguer « chemin interdit » et « condition manquante » rend le digest d'erreurs actionnable par le responsable commercial.

Les statuts converti et perdu sont terminaux : le dossier est alors figé et tout appel d'écriture ultérieur est rejeté avec REJ-CONVERSATION-CLOSE. Justification : un lead clos qui bougerait encore détruirait la valeur probante de l'audit trail. Chaque transition réussie écrit un maillon EVT-TRANSITION horodaté par l'appelant. Aucune transition automatique n'existe : toute transition est déclenchée par un appel explicite porteur d'une décision humaine.

## 5. Readiness gate M3

Pré-requis d'appel : la gate n'est évaluée que sur un lead dont le statut courant est qualifie ; tout appel sur un lead dans un autre statut (nouveau, converti, perdu) retourne faux sans examiner les autres conditions et sans émettre de marqueur. Ce pré-requis n'est pas compté comme condition de la gate elle-même.

Conditions évaluées, toutes requises (quatre conditions conjointes, conformément à CA-M2-08 et au PRD §4) : owner non vide, ET type_travaux appartenant à l'énumération fermée M1, ET ville non vide, ET au moins une interaction humaine dont l'horodatage fourni par l'appelant est postérieur ou égal à celui de la transition vers qualifie. Justification : l'exigence « post-qualification » empêche la transmission sur la seule base de la qualification automatique M1. Le décompte de quatre conditions aligne l'architecture avec CA-M2-08 et le PRD §4 ; le statut qualifie est un pré-requis d'appel, non une cinquième condition.

La gate est une fonction booléenne pure, sans effet de bord. Le marqueur produit au franchissement est un dict {readiness_ok: true, lead_id, hash_tete_registre, horodatage fourni, empreinte} où l'empreinte est le sha256 de l'encodage canonique injectif des quatre conditions évaluées, du lead_id et du hash de tête. Justification : lier le marqueur au hash de tête l'ancre dans la chaîne au moment du franchissement.

M3 vérifie sans faire confiance : il recalcule l'empreinte depuis le dossier transmis, et vérifie que le hash de tête cité appartient à une chaîne dont valider_chaine retourne vrai. Justification : la preuve est recomputée, jamais crue sur parole, ce qui implémente le verrou R-M2-004.

## 6. Détection de doublons SANS fusion

Critère de rapprochement, conforme à la règle explicite du PRD : même contact, OU même combinaison ville et type_travaux, dans une fenêtre glissante de 7 jours calendaires calculée sur les dates d'ingestion fournies par l'appelant. Justification : la disjonction capture à la fois le client qui rappelle et le même chantier signalé par deux canaux.

Le signalement est un maillon EVT-DOUBLON-POTENTIEL dans le registre plus une entrée en_attente dans la liste des signalements, portant les deux lead_id, le critère et l'horodatage. L'arbitrage humain est enregistré comme décision, sans exécution de fusion en v1.

La garantie anti-fusion est architecturale, pas procédurale : aucune fonction de fusion n'existe dans l'arborescence, l'opération est littéralement inexprimable, et le registre append-only rend tout écrasement impossible. Justification : on ne peut pas appeler ce qui n'existe pas, et le test CA-M2-07 prouve que les deux leads coexistent après signalement.

## 7. Interfaces publiques par story

S001 : `encoder_canonique(valeurs) -> octets — encodage injectif préfixé par longueur` ; `valider_horodatage(texte) -> str — accepte ISO-8601 avec timezone, refuse sinon` ; `valider_fixture(doc) -> dict — refuse toute fixture sans fictif: true` ; `construire_verdict(code, statut, detail) -> dict — construit un verdict structuré stable pour un code d’erreur ou un succès` ; `est_verdict(code) -> bool — vérifie si un code figure dans le catalogue officiel des verdicts M2`.
S002 : `ajouter(entree) -> str — append et retourne le hash du maillon` ; `lire(depuis) -> list — lecture depuis un hash` ; `tete() -> str|None` ; `valider_chaine(ancre) -> bool` ; `assert_chaine(ancre) -> None — lève si valider_chaine retourne faux` ; `taille() -> int`.
S003 : `ingerer_lead(contrat, horodatage) -> dict — valide schéma et frontières, inscrit au statut nouveau, retourne l'accusé {lead_id, hash_maillon}`.
S004 : `assigner_owner(lead_id, owner, prochaine_action, horodatage) -> dict — transitionne nouveau vers qualifie` ; `convertir_lead(lead_id, reference_devis_m3, horodatage) -> dict` ; `perdre_lead(lead_id, motif, horodatage) -> dict`.
S005 : `enregistrer_interaction(lead_id, auteur, resume, horodatage) -> dict` ; `evaluer_readiness(lead_id) -> bool — gate pure` ; `produire_marqueur_readiness(lead_id, horodatage) -> dict — émet le marqueur signé si la gate passe`.
S006 : `detecter_doublons(lead_id, horodatage) -> list — signale sans fusionner` ; `arbitrer_doublon(signalement_id, decision, horodatage) -> dict — enregistre la décision humaine`.
S007 : `produire_digest(date_jour, horodatage) -> dict — digest déterministe des leads en attente, orphelins et doublons en attente`.
S008 : `ecrire_vers_crm(dossier, horodatage) -> dict — adaptateur in-memory, fail-closed hors mode ombre`.

## 8. Anti-dérive et stratégie de preuve

Propriété prouvée par story. S001 : l'encodage est injectif (deux entrées distinctes donnent deux empreintes distinctes, y compris les cas de collision par concaténation observés dans M1) et le déterminisme est inter-processus (deux processus avec PYTHONHASHSEED différent produisent la même empreinte depuis un conteneur non ordonné préalablement trié). S002 : valider_chaine retourne vrai après toute séquence valide et faux après altération d'un maillon (CA-M2-10). S003 : toute ingestion valide produit un statut de l'énumération (CA-M2-01) ; toute violation de frontière est rejetée sans écriture (CA-M2-02). S004 : zéro transition illégale acceptée, conditions manquantes rejetées avec le verdict spécifique (CA-M2-03 à CA-M2-06). S005 : la gate retourne faux dès qu'une des quatre conditions manque (CA-M2-08) et le marqueur est revérifiable par recalcul. S006 : le signalement ne fusionne jamais (CA-M2-07). S007 : le digest est exhaustif, trié par date d'ingestion fournie, et identique entre deux exécutions (CA-M2-09). S008 : tout appel hors mode ombre lève REJ-ADAPTATEUR-INDISPONIBLE.

Invariants CI transversaux : zéro réseau (test d'absence d'imports socket/requests), zéro horloge interne (tout horodatage est un paramètre ; le test d'orphelin à 24h et 48h utilise une horloge injectée), zéro LLM (REJ-0040), énumérations fermées partout, aucun champ deviné, fixtures sans fictif: true refusées avant lecture (CA-M2-11), identifiants dérivés uniquement par encodage canonique injectif à préfixage par longueur. Justification : la concaténation directe est ambiguë et a causé des collisions réelles dans M1, leçon que M2 ne répétera pas.

## 9. Découpage en stories


- M2-S001 (T1, dépendances : aucune) — utilitaires transversaux : encodage canonique injectif à préfixage par longueur, validation d'horodatage ISO-8601 avec timezone et refus explicite, catalogue de verdicts stables, validation fail-closed des fixtures exigeant fictif: true. Porte CA-M2-11. Porte également CA-M2-13 (empreintes sha256 attendues des fichiers dupliqués, déclarées comme constantes littérales dans les tests M2) et CA-M2-14 (suite de cas d'abus héritée de M1 rejouée contre les implémentations M2 d'encodage, d'horodatage et de registre).

- M2-S002 (T1, dépend : S001) — registre append-only hash-chaîné réimplémenté sur le patron M1, API ajouter/lire/tete/valider_chaine/assert_chaine/taille. Porte CA-M2-10. Les cas d'abus de chaîne (mutation, troncature, réordonnancement) sont rejoués ici au titre de CA-M2-14.

- M2-S003 (T1, dépend : S001, S002) — ingestion du contrat gelé LeadQualifie, validation structurelle, vérification des frontières de vérité, inscription au statut nouveau, accusé de réception portant lead_id et hash du maillon. Porte CA-M2-01 et CA-M2-02.

- M2-S004 (T1, dépend : S003) — machine à états des quatre statuts, transitions conditionnées avec verdicts spécifiques (REJ-OWNER-ABSENT, REJ-ACTION-ABSENTE, REJ-DEVIS-ABSENT, REJ-MOTIF-ABSENT), rejet des chemins interdits avec REJ-TRANSITION-ILLEGALE, états terminaux figés avec REJ-CONVERSATION-CLOSE. Porte CA-M2-03, CA-M2-04, CA-M2-05, CA-M2-06. La reference_devis_m3 est acceptée comme chaîne opaque non vide émise par l'appelant humain, jamais fabriquée ni validée structurellement par M2.

- M2-S005 (T1, dépend : S004) — enregistrement des interactions humaines post-qualification, readiness gate comme fonction booléenne pure exigeant une interaction dont l'horodatage est postérieur ou égal à celui de la transition vers qualifie, émission du marqueur signé vérifiable par recalcul. Porte CA-M2-08.

- M2-S006 (T2, dépend : S003) — détection de doublons potentiels sur le critère contact identique OU ville-et-travaux dans une fenêtre glissante de 7 jours calendaires calculée sur les dates d'ingestion fournies par l'appelant, signalement sans fusion, arbitrage humain enregistré comme décision. Porte CA-M2-07. Aucune fonction de fusion n'existe dans l'arborescence.

- M2-S007 (T2, dépend : S004, S005, S006) — digest quotidien déterministe hash-chaîné des leads en attente, orphelins et doublons en attente. Sémantique des deux paramètres de produire_digest : date_jour est la date calendaire cible du digest, horodatage est l'horodatage ISO-8601 avec timezone de production du digest fourni par l'appelant. Porte CA-M2-09 et CA-M2-12 (signalement des leads orphelins après 48 heures simulées, horloge entièrement injectée).

- M2-S008 (T2, dépend : S003) — adaptateurs in-memory fail-closed simulant l'écriture vers un CRM tiers, GATED hors mode ombre, tout appel hors mode ombre lève REJ-ADAPTATEUR-INDISPONIBLE.

Justification de l'ordonnancement : chaque story ne dépend que de stories déjà prouvées, ce qui permet à la gate CI de valider le module incrémentalement sans jamais tester au-dessus d'un vide. Les obligations de l'addendum D3 (empreintes épinglées et suite de conformité rejouée) sont portées explicitement par S001 et S002 via CA-M2-13 et CA-M2-14, ce qui garantit leur implémentation et leur vérification en CI sans introduire de dépendance de M2 vers l'arborescence de M1, même en test : les empreintes attendues sont des constantes littérales dans les tests M2, et un test miroir côté M1 vérifie symétriquement la même propriété.

---

ADDENDUM D'ARCHITECTURE M2 — Décision D3 : duplication scellée, conformité rejouée

Ma §2 justifiait la duplication par les frontières nettes et la portabilité ; elle n'en tarifiait pas le coût. Le voici tranché. Je retiens la combinaison des options 1 et 2, je rejette l'option 4 sans ambiguïté, et je diffère l'option 3 sous condition explicite.

Option 1 — copie verbatim scellée par empreinte. Les fichiers dupliqués (encodage, horodatage, registre, et tout tronc commun repris de M1) sont copiés à l'identique dans l'arborescence M2. Chaque module épingle dans ses propres tests, sous forme de constantes littérales déclarées en dur dans le fichier de test lui-même, l'empreinte sha256 attendue de ses fichiers — M2 déclare les empreintes de ses copies, M1 déclare symétriquement les empreintes de ses originaux, et aucun test ne lit jamais l'arborescence de l'autre module, ni en lecture directe ni par import. Toute modification d'un seul côté fait échouer la CI du module modifié ; la divergence cesse d'être silencieuse et devient une décision consciente, consignée dans le commit unique qui met à jour les deux fichiers et les deux jeux de constantes littérales. Coût quasi nul ; le mode d'échec documenté des duplications — la dérive asymétrique — devient impossible sans fracas, et l'absence de lecture croisée préserve l'indépendance des deux modules y compris en test, conformément à CA-M2-13.

Option 2 — suite de conformité recopiée. L'empreinte prouve l'identité du texte, pas l'identité du comportement après une divergence autorisée. J'impose donc une suite de cas d'abus — collisions par concaténation directe, horodatages invalides, mutations de chaîne, réordonnancements — recopiée intégralement dans les tests M2, sans aucun import depuis l'arborescence M1 ni partage de code de production, et rejouée contre les implémentations M2 d'encodage, d'horodatage et de registre. Un test miroir côté M1 rejoue symétriquement la même suite contre ses propres implémentations, avec les mêmes verdicts attendus. C'est cette duplication des cas, et non un partage de code, qui détecte la divergence comportementale quand les textes diffèrent légitimement, et qui satisfait l'invariant constitutionnel : la CI prouve, ou rien n'est prouvé. Cette obligation est portée explicitement par CA-M2-14 et rattachée aux stories S001 et S002.

Option 3 — extraction vers core/ : souhaitable, pas maintenant. Elle devient défendable à l'apparition d'un troisième consommateur (règle de trois) et constituerait un changement de périmètre à ratifier formellement. L'extraire aujourd'hui réintroduirait exactement le couplage que §2 refuse, sur la foi d'un échantillon de deux.

Option 4 — duplication nue : franchement inacceptable. Les défauts M1 corrigés étaient invisibles aux tests verts ; parier qu'aucun défaut résiduel ne subsiste, ou qu'une correction future sera pensée des deux côtés, est contredit par l'historique du projet — les collisions d'identifiants sont réapparues après un premier correctif.

Propriétés à re-prouver côté M2, rejouées depuis les cas d'abus M1. Sur le registre : unicité du chemin d'écriture — toute inscription transite par ajouter(), validation et chaînage compris, et un abandon laisse une trace explicite ; intégrité de la chaîne — toute mutation, troncature ou réordonnancement est détectée par valider_chaine(). Sur l'horodatage : refus uniforme — aucune erreur brute de datetime ne fuit, tout horodatage invalide reçoit le refus explicite du module. Sur l'encodage : injectivité — les cas qui collisionnaient par concaténation directe produisent des identifiants distincts ; déterminisme — empreintes identiques sous plusieurs PYTHONHASHSEED, avec interdiction de tout ordre d'itération d'ensemble ou de repr dans la sérialisation. Sur les statuts et frontières : toute transition hors table reçoit REJ-TRANSITION-ILLEGALE, tout champ interdit REJ-FRONTIERE-VIOLEE. Ce sont ces propriétés, non les lignes, que la duplication emporte et que la CI doit prouver deux fois.

## 10. Addendum — catalogue de verdicts (2026-07-29)

Écart constaté. Le catalogue livré en M2-S001 comptait huit identifiants et ne contenait pas REJ-CONVERSATION-CLOSE, alors que le PRD et la présente architecture le prescrivent explicitement comme invariant transversal repris du catalogue du module voisin. Mesure : est_verdict("REJ-CONVERSATION-CLOSE") retournait False côté M2 et True côté voisin. L'écart a été détecté au cadrage de M2-S003, pas par un test, ce qui motive la parade ci-dessous.

Correction. Le catalogue passe à quatorze identifiants, en trois groupes. Groupe 1, inchangé, les huit identifiants d'origine. Groupe 2, cinq identifiants repris tels quels du catalogue du module voisin : REJ-CONVERSATION-CLOSE, REJ-CONTRAT-INVALIDE, REJ-CHAMP-MANQUANT, REJ-CHAMP-VIDE, REJ-ENUM-INVALIDE. Justification : le principe déjà ratifié — la stabilité des identifiants de verdict est un invariant transversal, pas une propriété de module — impose de réutiliser un identifiant existant pour une sémantique identique plutôt que d'en forger un nouveau ; deux noms pour la même faute rendraient les digests inter-modules incomparables. Groupe 3, une addition déclarée : REJ-LEAD-DEJA-INGERE. Justification : la ré-ingestion d'un lead_id déjà présent n'est pas le doublon métier traité en M2-S006, qui porte sur deux leads distincts partageant un contact ou un couple ville/travaux, mais une violation d'unicité d'identité ; le registre étant append-only, deux maillons pour un même identifiant rendraient le statut, la readiness et l'arbitrage ambigus sans recours possible.

REJ-0040 n'est pas un verdict. Il apparaît dans les documents comme identifiant de règle « zéro LLM » et n'est présent dans aucun des deux catalogues. Il n'est pas ajouté.

Parade durable. Un test de cohérence extrait tous les identifiants de la forme REJ-... cités dans les documents de cadrage du module et vérifie que chacun figure au catalogue, et réciproquement qu'aucun code du catalogue n'est présent sans être prescrit ou déclaré comme addition. Justification : l'écart initial n'était visible ni à la lecture du code ni à l'exécution des tests ; seule une vérification croisée document-code l'empêche de se reproduire. Le test échoue si le nombre d'identifiants extraits est nul, faute de quoi un déplacement du dossier de cadrage le rendrait vert en ne lisant rien.

Gel resscellé. L'empreinte sha256 de verdicts.py, épinglée comme constante littérale au titre de CA-M2-13, a été mise à jour. Justification : le gel a rempli sa fonction — il a forcé la modification à devenir une décision explicite et journalisée au lieu de passer inaperçue.

construire_verdict lève désormais une exception dédiée CodeVerdictInconnu, sous-classe d'Exception. Justification : une Exception nue oblige l'appelant à écrire except Exception, ce qui masque toutes les autres fautes ; la sous-classe préserve la compatibilité des tests existants tout en rendant le rattrapage précis.

## 11. Addendum — décisions de cadrage de M2-S003 (2026-07-29)

Décisions rendues par la revue d'architecture avant toute écriture de code, figées ici pour que deux implémentations ne divergent pas.

Frontière structurelle : liste blanche stricte, pas liste noire. Tout champ absent des sept champs du contrat gelé est refusé, y compris un champ apparemment inoffensif. Justification : une liste noire est fail-open par construction, elle n'énumère que les interdits imaginés à l'avance et laisserait passer un champ non listé ; le contrat étant gelé et épinglé, toute déviation structurelle est par définition une tentative d'introduire du contenu hors frontière, et l'évolutivité se gère par une nouvelle version explicitement épinglée, jamais par tolérance implicite. Un écart purement structurel reçoit un identifiant du groupe 2, jamais REJ-FRONTIERE-VIOLEE qui désigne le franchissement d'une frontière de vérité.

Inspection des valeurs, pas seulement des noms de champs. Un contrat conforme aux sept champs peut dissimuler un prix ou une date d'exécution dans une valeur textuelle. Justification : le critère d'acceptation dit « toute » violation, et le registre étant append-only, une violation admise est indélébile alors qu'un faux positif se corrige en amont ; l'asymétrie impose d'inspecter. Les motifs sont réimplémentés localement, ancrés sur montant plus devise et sur date contextualisée par un verbe d'exécution, jamais sur des mots-clés nus — une ville nommée « Saint-Prix » ou une rue de l'Échéance sont des valeurs légitimes. Le corpus de motifs est figé dans la spécification de la story, faute de quoi les rejets ne seraient pas reproductibles.

Accusé de réception vérifiable sans confiance. Il porte lead_id, ligne_id, statut, empreinte_contrat, empreinte_maillon, tete_chaine et l'horodatage fourni. Justification : ligne_id localise le maillon mais ne le scelle pas ; l'empreinte du maillon et la tête de chaîne permettent à l'appelant de recalculer et d'ancrer extérieurement, sans rien croire du module. L'accusé est une fonction pure du contrat, de l'horodatage fourni et de l'état du registre, donc rejouable à l'identique.

Unicité d'identité vérifiée à l'ingestion. La ré-ingestion d'un lead_id déjà inscrit est rejetée avec REJ-LEAD-DEJA-INGERE, sans écrire de maillon. La vérification parcourt les maillons de type lead_ingere du registre. Justification : un index parallèle constituerait une seconde source de vérité susceptible de se désynchroniser ; le parcours est déterministe et son coût, linéaire, est acceptable en mode ombre — il doit être mesuré, jamais compensé par un cache.

Ordre des contrôles figé. Validation de l'horodatage fourni, puis structure, puis frontières sur les valeurs, puis unicité, puis écriture, puis accusé. Justification : quand un contrat cumule plusieurs fautes, c'est l'ordre qui détermine le verdict rendu ; le figer rend les rejets reproductibles d'une implémentation à l'autre. Tous les contrôles précèdent l'unique appel d'écriture, ce qui rend structurellement vrai — et pas seulement testé — le fait qu'un rejet n'inscrit aucun maillon. Aucun maillon de rejet n'est écrit : le registre n'est pas une piste d'audit des échecs.

Forme de retour : un couple. L'ingestion retourne (accuse, verdict) dont exactement un membre est non nul, garanti par construction et non par convention documentée. Justification : un retour polymorphe rend l'usage incorrect silencieux — la lecture d'une clé absente sur un verdict renvoie une valeur nulle qui se propage ; le couple rend la faute bruyante dès le premier accès. Les rejets sont des issues métier attendues, pas des fautes de programmation : les exceptions restent réservées à ces dernières.

Aucune normalisation du contrat entrant. Ni découpe d'espaces, ni changement de casse, ni réparation. Justification : toute normalisation invaliderait l'empreinte épinglée par le module amont ; l'ingestion accepte tel quel ou rejette, elle ne répare jamais.

Risque résiduel journalisé. Le registre n'impose pas la monotonie des horodatages — il n'a pas d'horloge interne et les horodatages viennent de l'appelant. L'ordre de la chaîne n'est donc pas nécessairement l'ordre temporel. Justification : tout traitement ultérieur fondé sur une fenêtre de temps doit raisonner sur les horodatages inscrits, jamais sur la position dans la chaîne. Cette contrainte est signalée ici pour les stories aval qui manipulent des fenêtres glissantes.

## Addendum PLAN T0.13 — M2 accepte le contrat `LeadQualifie` v1 et v2

`contrats.valider_structure` valide le lead dans la version qu'il déclare : `schema_version` présent (valeur 2 exactement), c'est la v2 (`service` de la taxonomie du socle, huit clés gelées `CHAMPS_CONTRAT_GELE_V2`, plus `source`/`utm`/`campagne` optionnels) ; absent, c'est la v1 gelée (`type_travaux`), validée comme avant. Aucune version n'est devinée : un lead v1 qui porte `service`, ou un lead v2 qui porte `type_travaux`, est refusé. Le service doit être déclaré par le profil d'entreprise de l'instance, à l'ingestion et à la readiness ; sinon le verdict (`REJ-ENUM-INVALIDE`, dont le détail porte le refus du socle) dit quoi configurer. Le marqueur de readiness signe la clé `service` pour un lead v2 et `type_travaux` pour un lead v1 (octets inchangés). Le rapprochement `ville_et_travaux` ne compare que des leads de la même version. Voir `docs/architecture/TAXONOMIE.md`.

## Addendum PLAN T1.4-k2 — identité authentifiée d'un appel d'appareil (2026-09-29)

Décision. Pour un appel d'appareil, la personne du jeton, confirmée en base à chaque appel, décide de ce que M2 lit et de ce qu'il écrit : l'auteur d'une interaction est cette personne, et un vendeur ne voit et n'agit que sur les leads dont il est le propriétaire. Justification : jusqu'ici l'auteur venait de l'appelant et chaque vendeur voyait tous les leads. Le module pur `acces.py` décide, `outils.py` lit l'identité, comme pour M4 et M5.

La propriété existait déjà. Le propriétaire d'un lead est l'owner que la transition vers qualifie exige et consigne. Aucun maillon d'assignation n'est ajouté, et le propriétaire n'est déduit d'aucun autre champ. Justification : une seconde source de propriété pourrait diverger de la première, et la readiness et le digest lisent déjà celle-ci. Un lead nouveau n'a pas de propriétaire : l'admin, ou l'agent sur décision humaine, l'assigne en qualifiant.

Le fait est publié. La qualification publie `m2.lead_assigne` dans la même transaction, avec un identifiant d'événement déterministe par lead. Justification : M3 relit ce fait à la source du bus, sans importer M2 (#109) et sans copie de la propriété.

Catalogue de verdicts. Quatre identifiants s'ajoutent en groupe 5, à la suite : REJ-IDENTITE-APPAREIL-INVALIDE et REJ-IDENTITE-FOURNIE-DIFFERENTE, repris tels quels de M4 et de M5, puis REJ-LEAD-NON-ASSIGNE et REJ-OWNER-INCONNU, propres à M2. Justification : même faute, même nom, pour que les refus restent comparables entre modules. Le refus REJ-LEAD-NON-ASSIGNE est le même pour un lead d'un autre, sans propriétaire ou inconnu, pour qu'un vendeur ne puisse pas sonder les leads existants.

Gel resscellé. L'empreinte sha256 de verdicts.py, épinglée au titre de CA-M2-13, a été mise à jour une seconde fois. Justification : le gel a rempli sa fonction, il a forcé cette modification à devenir une décision explicite et journalisée.

## Addendum PLAN T4.6 — liste des leads et segments M2.11 (2026-09-29)

Décision. M2 expose la liste de ses leads par statut et par segment (`m2_lister_leads`, lecture pure) : le vendeur lit ses leads, l'admin tous. Justification : DEFINITION-PRODUIT §9.4 (« ses leads ») et §9.5 (« pipeline, leads chauds ») n'avaient aucun outil, donc aucun écran vendeur ni pipeline. Le contrôle d'accès est celui de T1.4-k2 : un lead d'un autre vendeur n'est ni listé ni compté ni cité dans une règle.

Segments. Huit des quatorze segments de M2.11 se calculent des faits que M2 tient déjà, chacun avec sa règle citée et la donnée qui le déclenche (`segments.py`, module pur). Les six autres rendent « non calculable, manque X » pour tous les leads : la donnée n'atteint pas M2, et aucun segment n'est deviné. Justification : une liste vide se lirait « aucun lead », un faux vert.

Seuils. Les seuils d'inactivité et de soumission périmée sont dans `department.yaml`, vides : « seuil à configurer ». Justification : même patron que M6 et M8, aucune valeur inventée.

Catalogue de verdicts. Deux identifiants s'ajoutent en groupe 6, à la suite : REJ-SEGMENT-NON-CALCULABLE (un filtre sur un segment sans donnée ou sans seuil, avec ce qui manque) et REJ-PAGINATION-INVALIDE (décalage ou limite de page invalide). Justification : aucun code existant ne dit qu'une donnée manque pour calculer un segment, et un décalage n'est pas une énumération.

Gel resscellé. L'empreinte sha256 de verdicts.py, épinglée au titre de CA-M2-13, a été mise à jour une troisième fois. Justification : le gel a rempli sa fonction, il a forcé cette modification à devenir une décision explicite et journalisée.

## Addendum PLAN T1.4-m — réassignation d'un lead et republication du fait (2026-09-29)

Décision. Un lead se réassigne à un autre vendeur (`m2_reassigner_lead`, écriture N3 réservée à l'admin), et le fait `m2.lead_assigne` d'un lead qualifié avant T1.4-k2 se republie (`m2_republier_assignations`). Justification : le propriétaire n'était consigné qu'une fois, à la qualification. Un vendeur qui part, ou un owner saisi de travers, laissait le lead sans recours, et M3 refusait au vendeur les devis des leads qualifiés avant T1.4-k2, faute de fait au bus.

Un maillon de plus, une seule lecture. Le maillon de qualification n'est jamais modifié : la réassignation ajoute un maillon `reassignation` (qui décide, par quelle voie, pourquoi, de qui à qui, à quel rang). Le propriétaire courant est celui de la dernière assignation, lu en un seul endroit (`assignation.py`), sur lequel `acces.py`, la readiness et le digest s'alignent. Cette décision corrige celle de T1.4-k2 (« aucun maillon d'assignation n'est ajouté »), qui valait tant que le propriétaire ne pouvait plus changer. Justification : la seconde source de propriété écartée en T1.4-k2 pouvait diverger de la première ; une seule fonction de lecture rend cette divergence impossible.

Décision humaine, motif obligatoire. Le décideur est la personne d'un jeton d'appareil admin, confirmée en base à l'instant de l'appel, ou la personne qui vient d'approuver la demande d'un agent ; sans l'une ni l'autre, REJ-HUMAIN-REQUIS, même en mode supervisé ou autonome où un N3 s'exécute sans file. Le motif fait de 10 à 500 caractères. Le niveau est N3, choisi : pas N2, car la réassignation décide qui voit le dossier et les devis d'un client, et une personne doit la prendre ; pas N4, car elle n'engage rien à l'extérieur, ne touche ni argent ni prix, et une nouvelle réassignation la défait sans rien supprimer. La cible est une personne active de rôle seller, sinon REJ-OWNER-INCONNU. Justification : même patron que la clôture d'un transfert de M1, la saisie d'une facture fournisseur de M5 et les écritures humaines de M10.

Fait versionné, de façon additive. Le contrat du catalogue reste celui d'avant : toute charge valide avant reste valide. La qualification est le rang 1, sans clé rang, sous le même identifiant qu'en T1.4-k2. Une réassignation de rang n au moins égal à 2 publie les trois mêmes clés plus rang et proprietaire_precedent, dans la même transaction que son maillon, sous un identifiant d'une autre famille, qu'aucun lead_id ne peut confondre avec celui d'un rang 1. Le propriétaire courant est celui du plus grand rang publié. Justification : l'identifiant déterministe d'origine ne portait qu'un propriétaire par lead, et un fait déjà publié ne se modifie jamais. M3 doit lire le rang 1 puis les rangs suivants ; tant qu'il ne le fait pas, il montre encore les devis à l'ancien vendeur.

Republication. L'outil remet au bus, pour chaque assignation du registre, le fait absent, avec les mêmes identifiant et charge que la publication d'origine. Il est idempotent, n'écrit pas au registre et n'invente aucun propriétaire. Justification : le registre est la source de vérité ; le bus n'en est que la trace lue par M3.

Catalogue de verdicts. Cinq identifiants s'ajoutent en groupe 7, à la suite : REJ-HUMAIN-REQUIS, REJ-MOTIF-INVALIDE, REJ-LEAD-INCONNU, REJ-PROPRIETAIRE-INCHANGE et REJ-BUS-INDISPONIBLE. Justification : aucun code existant ne dit qu'une décision de personne manque, qu'un motif est hors bornes, qu'un lead n'existe pas, qu'il n'y a rien à réassigner ou qu'aucun bus n'attend la republication. REJ-OWNER-ABSENT, REJ-OWNER-INCONNU, REJ-MOTIF-ABSENT et REJ-HORODATAGE-INVALIDE servent aussi, avec leur détail propre.

Gel rescellé. L'empreinte sha256 de verdicts.py, épinglée au titre de CA-M2-13, a été mise à jour une quatrième fois. Justification : le gel a rempli sa fonction, il a forcé cette modification à devenir une décision explicite et journalisée.

## Addendum PLAN T4.9 — relances dues, consentement de contact et fréquence limitée (2026-09-29)

Décision. M2 tire ses relances dues des segments de T4.6 et les liste (`m2_lister_relances`, lecture pure, paginée : le vendeur lit celles de ses leads, l'admin toutes), prépare un texte fixe à partir d'un gabarit (`m2_preparer_relance`, sans aucun envoi) et tient un registre de consentement de contact (`m2_enregistrer_consentement_contact`, une personne l'inscrit). Justification : les relances n'étaient visibles qu'au Client 360, sans consentement modélisé, alors que §7 M2 exige « opt-in respecté, fréquence limitée, validation humaine au départ ». Le contrôle d'accès est celui de T1.4-k2 et de T1.4-m : le vendeur ne voit que les relances de ses leads, propriétaire courant compris.

Le consentement d'abord. Le registre garde le canal, la version de l'énoncé lu, la source, la preuve (son type et une référence, jamais le document ni un numéro), l'instant du consentement et celui de l'inscription, et qui l'a inscrit. Sans consentement actif pour un canal écrit, la relance est « appel seulement » : jamais un SMS ni un courriel. Le consentement est celui d'une personne : les leads d'un même client comptent ensemble, résolus à la lecture. Justification : POLITIQUE-consentement-sms (proposition, validée seulement par Nathan) demande un opt-in actif, daté et tracé, et interdit d'en déduire un de l'origine d'un lead : un SMS reçu n'est pas un opt-in.

Un retrait ne se lève pas. M2 consomme `m1.retrait_consentement` : le STOP d'un client est rangé par `lead_id`, sans jamais stocker son numéro, et prime sur tout consentement, quel que soit l'ordre des deux. Il vaut pour tous les canaux écrits, choix prudent isolé dans une seule fonction. Justification : M1 et M7 traitent déjà le retrait ainsi, et un retrait qu'un outil pourrait défaire serait un consentement fabriqué. Lever un retrait est une décision du propriétaire, pas d'un outil.

Le point de départ est l'envoi publié par M3. M2 consomme `m3.devis_envoye` et fait partir le délai d'une relance de devis de son horodatage, jamais d'une date supposée. Ce fait date l'approbation de l'envoi par le propriétaire, pas la livraison au client, que M1 fera en T2.1-c : chaque relance de devis le dit et porte un avertissement. Justification : M2 ne traite jamais un devis comme livré quand rien ne le prouve, et cache moins de vérité en disant la limite qu'en la taisant.

Délais et fréquence en configuration, jamais un défaut. Le délai de chaque règle est le seuil de son segment (`configuration.segments`) ; la fréquence maximale, le nombre minimal de jours entre deux relances d'un même client, est `configuration.relances`. Les deux sont vides à dessein : le verdict dit quoi configurer. La dernière relance est la dernière relance préparée, faute d'envoi réel. Justification : même patron que M6, M8 et T4.6, et AGENTS.md interdit une valeur par défaut inventée.

Gabarits fixes, contrôlés au chargement. Chaque texte destiné à un client passe par le garde-fou de texte partagé du socle avant que le département se charge : ni nom, ni identifiant, ni prix, ni date, ni promesse. Justification : un texte fautif se découvre au chargement, pas chez un client, et aucun département n'importe l'autre.

Catalogue de verdicts. Six identifiants s'ajoutent en groupe 8, à la suite : REJ-RELANCES-A-CONFIGURER (la fréquence maximale manque ou est invalide), REJ-RELANCE-NON-DUE (aucune relance de cette règle n'est due pour ce lead), REJ-RELANCE-TROP-PROCHE (la fréquence limitée refuse, avec la prochaine date permise), REJ-CONSENTEMENT-ABSENT (aucun consentement actif pour ce canal), REJ-CONSENTEMENT-RETIRE (le client s'est retiré) et REJ-CONSENTEMENT-INVALIDE (une saisie de consentement mal formée). Justification : aucun code existant ne dit qu'une fréquence manque, qu'une relance n'est pas due ou trop proche, ni l'état d'un consentement. REJ-SEGMENT-NON-CALCULABLE, REJ-ENUM-INVALIDE, REJ-PAGINATION-INVALIDE, REJ-HORODATAGE-INVALIDE, REJ-HUMAIN-REQUIS, REJ-LEAD-INCONNU, REJ-LEAD-NON-ASSIGNE et REJ-BUS-INDISPONIBLE servent aussi, avec leur détail propre.

Gel rescellé. L'empreinte sha256 de verdicts.py, épinglée au titre de CA-M2-13, a été mise à jour une cinquième fois. Justification : le gel a rempli sa fonction, il a forcé cette modification à devenir une décision explicite et journalisée.


## Addendum CRM-04 — rescellage explicite des verdicts (2026-10-27)

La correction humaine des coordonnées, documentée dans `docs/grs/crm/CORRECTION-COORDONNEES-M2.md` à la racine, ajoute uniquement deux codes par le commit `dd19e5cf` : `REJ-CONTACT-CONFLIT` (identité déjà détenue par un autre client) et `REJ-CONTACT-BACKEND-NON-QUALIFIE` (écriture hors stockage SQLite qualifié). Le diff depuis le parent de ce commit conserve tous les verdicts historiques ; aucune valeur ni sémantique antérieure n’est retirée.

Ancien SHA-256 de `verdicts.py` : `3525f2190a12641b0946567309c1d20d68a2c84b62b745814c550e065418e29f`. Nouveau SHA-256 : `842411b47028076c9718d5b915389676297f3624f9fdfb52eced49e5b86f9644`. Le contrôle d’empreinte reste strict et celui de `horodatage.py` reste inchangé. Ce rescellage réconcilie le contrat avec la capacité CRM-04 déjà implémentée ; il ne vaut pas validation complète du CRM.

## Addendum CRM-03 — catalogue fermé de l’agenda commercial (2026-10-27)

Le commit `14540419` remplace les codes d’agenda construits librement par un catalogue
explicite de quinze codes d’agenda. Ils représentent arguments invalides, conflit
d’horaire, identité, lead inconnu, conflit de mutation, propriétaire modifié, révision
périmée, sortie trop volumineuse, source invalide/modifiée/trop volumineuse, écriture
non qualifiée, mutation absente, vendeur inactif/inconnu. Un suffixe inconnu est refusé.
Les contrôles négatifs de l’agenda restent en place; aucun droit nouveau n’est accordé.

Identifiants complets : `REJ-AGENDA-ARGUMENTS`, `REJ-AGENDA-CONFLIT-HORAIRE`,
`REJ-AGENDA-IDENTITE`, `REJ-AGENDA-LEAD-INCONNU`, `REJ-AGENDA-MUTATION-CONFLIT`,
`REJ-AGENDA-PROPRIETAIRE-MODIFIE`, `REJ-AGENDA-REVISION-PERIMEE`,
`REJ-AGENDA-SORTIE-TROP-VOLUMINEUSE`, `REJ-AGENDA-SOURCE-INVALIDE`,
`REJ-AGENDA-SOURCE-MODIFIEE`, `REJ-AGENDA-SOURCES-TROP-VOLUMINEUSES`,
`REJ-AGENDA-ECRITURE-NON-QUALIFIEE`, `REJ-AGENDA-MUTATION-ABSENTE`,
`REJ-AGENDA-VENDEUR-INACTIF`, `REJ-AGENDA-VENDEUR-INCONNU`.

Le gel CA-M2-13 a signalé l’omission du rescellage dans la CI `40475457468`, job
`122092463574`. Vérification du diff depuis `14540419^` : tous les codes historiques
restent identiques et dans le même ordre; retirer le seul bloc d’ajout restaure les
octets antérieurs exacts. Le changement est donc une extension explicite du catalogue,
pas une modification silencieuse de ses décisions précédentes.

Ancien SHA-256 : `842411b47028076c9718d5b915389676297f3624f9fdfb52eced49e5b86f9644`.
Nouveau SHA-256 : `54e79d529522edf386ada2d998ecad927b2c5a7bdebd4cf87784ede9fc17553e`.
La comparaison d’empreinte demeure stricte; le gel `horodatage.py` est inchangé.
Vérifier conjointement conformité M2, catalogue utilitaires et refus/rejeux d’agenda.
