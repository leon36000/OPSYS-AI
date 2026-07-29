# BMAD ÉTAPE 3 — ARCHITECTURE M2 (REVENUE CRM)

Rédigé par : Architecte BMAD | Statut : PROPOSÉ | Portée : mode ombre, prouvable en CI Python

## 1. Arborescence du module

Racine : `Modules M/M2-revenue-crm/`, un fichier par responsabilité, aucune logique transversale dupliquée entre stories.

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

Les tests vivent sous `Modules M/M2-revenue-crm/tests/`, un fichier par story, car c'est le seul chemin découvert par le job CI protégé `gates`. Les fixtures vivent sous `fixtures/`, toutes marquées fictif: true. Justification : une story égale un fichier égale une suite de tests, ce qui rend la couverture traçable story par story.

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
