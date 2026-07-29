PRD M2 — Revenue CRM
Rédigé par : PM BMAD | Statut : PROPOSÉ | Date : 2025-01-XX

1. Personas

Le représentant commercial consulte chaque matin la liste des leads qui lui sont assignés, filtrée par statut et par ville. Il attend de M2 un contexte complet et non dupliqué : coordonnées, type de travaux, urgence déclarée, canal d'entrée, et l'historique des interactions post-qualification. Il ne veut jamais recevoir un lead orphelin, un doublon, ni un lead transmis à M3 sans qu'il l'ait validé. Le responsable commercial pilote le pipeline : il assigne les owners, arbitre les doublons signalés, et consulte le digest quotidien des leads en attente d'action pour détecter les trous noirs. Nathan, propriétaire, reçoit un digest synthétique horodaté et hash-chaîné listant les signaux commerciaux de la journée, les leads sans owner depuis plus de 24 heures simulées, et les doublons potentiels en attente de décision humaine. Nathan ne reçoit jamais de prix, de date d'exécution, ni de chiffre financier.

2. Parcours principaux

(a) Ingestion d'un lead qualifié. M1 transmet un contrat LeadQualifie gelé. M2 valide le schéma, vérifie les frontières de vérité, inscrit le lead dans le registre append-only hash-chaîné avec le statut initial nouveau, et retourne un accusé de réception portant le lead_id et le hash du maillon. Le lead reste en statut nouveau jusqu'à ce qu'un owner humain lui soit assigné, ce qui déclenche la transition vers qualifie et l'enregistrement d'une prochaine action horodatée. (b) Détection de doublon potentiel. À chaque ingestion, M2 compare le nouveau lead aux leads existants sur le triplet contact, ville, type_travaux dans une fenêtre glissante de 7 jours. Si une correspondance est trouvée, M2 émet un signalement de doublon potentiel sans jamais fusionner. La décision de fusion ou de conservation distincte appartient exclusivement à un humain, avec audit trail complet. (c) Franchissement de la readiness gate. Un lead en statut qualifie, doté d'un owner humain confirmé, d'un type de travaux validé, d'une ville renseignée, et d'au moins une interaction humaine post-qualification, satisfait la readiness gate. M2 produit alors un marqueur readiness_ok: true signé, et le lead devient transmissible à M3. (d) Clôture. Un lead passe au statut converti uniquement sur décision humaine et avec référence à un devis M3 accepté. Il passe au statut perdu sur décision humaine avec motif obligatoire. Aucune transition automatique vers converti ou perdu n'est autorisée.

3. Périmètre v1 (mode ombre) vs roadmap

Vague 1, prouvable en CI Python sans réseau ni CRM externe : registre append-only hash-chaîné, machine à états des statuts avec transitions validées et rejet des transitions illégales, détection de doublons potentiels avec signalement sans fusion, readiness gate M3 comme fonction booléenne pure, digest quotidien déterministe des leads en attente, adaptateurs in-memory fail-closed simulant l'écriture vers un CRM tiers, fixtures fictives marquées fictif: true, tests unitaires couvrant tous les chemins de transition et tous les rejets. Roadmap, capacités gatées T3 : intégration réelle avec un CRM tiers (HubSpot, Pipedrive), envois réels de notifications courriel ou Slack, webhooks entrants depuis formulaires web tiers, toute écriture réelle en base de données externe. Ces capacités nécessitent des credentials, un environnement de test, et une validation humaine explicite.

4. Règles métier explicites

Énumération fermée des statuts : nouveau, qualifie, converti, perdu.

Transitions autorisées et conditions :
- nouveau vers qualifie : owner humain non vide fourni ET prochaine_action complète fournie (description non vide et échéance ISO-8601 avec timezone).
- qualifie vers converti : décision humaine explicite ET reference_devis_m3 fournie. La reference_devis_m3 est une chaîne opaque émise par l'appelant humain (responsable commercial) qui saisit la référence du devis M3 accepté ; M2 ne la fabrique pas, ne la valide pas structurellement, et vérifie uniquement qu'elle est une chaîne non vide. M3 reste l'autorité émettrice du devis lui-même.
- qualifie vers perdu : décision humaine explicite ET motif non vide.
- nouveau vers perdu : décision humaine explicite ET motif non vide.

Transitions interdites : tout autre chemin, notamment converti vers qualifie, perdu vers qualifie, converti vers perdu, perdu vers converti, et toute transition automatique non déclenchée par une action humaine explicite. Les statuts converti et perdu sont terminaux : le dossier est figé et tout appel d'écriture ultérieur est rejeté avec REJ-CONVERSATION-CLOSE.

Readiness gate M3 : owner humain confirmé ET type_travaux appartenant à l'énumération fermée M1 ET ville non vide ET au moins une interaction humaine dont l'horodatage fourni par l'appelant est postérieur ou égal à l'horodatage de transition vers qualifie. Les quatre conditions sont conjointes ; l'absence d'une seule fait échouer la gate.

Signalement de doublon potentiel : même contact OU même combinaison ville et type_travaux, dans une fenêtre glissante de 7 jours calendaires calculée sur les dates d'ingestion fournies par l'appelant. Le signalement ne fusionne jamais ; la décision de fusion ou de conservation distincte appartient exclusivement à un humain.

Prochaine action : description textuelle non vide et échéance horodatée ISO-8601 avec timezone, fournie par l'appelant, jamais générée par M2.

Digest quotidien : produire_digest(date_jour, horodatage) accepte deux paramètres distincts. date_jour est la date calendaire cible du digest (filtre : leads en attente à cette date). horodatage est l'horodatage ISO-8601 avec timezone de production du digest lui-même, fourni par l'appelant, servant à horodater le maillon EVT-DIGEST inscrit au registre. Aucune horloge interne n'est consultée.

5. Frontières de vérité

M2 ne stocke jamais de prix, de montant, ou de chiffre financier : ce domaine appartient à M3 pour les devis et à M5 pour les factures. M2 ne stocke jamais de date d'exécution, de date de chantier, ou de planification d'intervention : ce domaine appartient à M4. M2 ne stocke jamais d'engagement contractuel, de promesse de délai, ou d'aveu de responsabilité. Tout champ tentant de déborder sur ces domaines est rejeté à l'ingestion avec le verdict REJ-FRONTIERE-VIOLEE, le lead n'est pas inscrit au registre, et l'appelant reçoit un accusé d'erreur déterministe.

6. Critères d'acceptation testables

CA-M2-01 : toute ingestion réussie d'un contrat LeadQualifie valide retourne un lead portant un statut appartenant à l'énumération fermée {nouveau, qualifie, converti, perdu} ; aucune ingestion ne produit un lead sans statut.

CA-M2-02 : toute ingestion d'un contrat violant les frontières de vérité est rejetée avec le verdict REJ-FRONTIERE-VIOLEE et n'inscrit aucun maillon au registre.

CA-M2-03 : la transition nouveau vers qualifie est rejetée avec REJ-OWNER-ABSENT si aucun owner humain non vide n'est fourni, et avec REJ-ACTION-ABSENTE si aucune prochaine_action complète n'est fournie.

CA-M2-04 : la transition qualifie vers converti est rejetée avec REJ-DEVIS-ABSENT si aucune reference_devis_m3 non vide n'est fournie. M2 ne valide que la présence d'une chaîne non vide, jamais le format ni l'existence du devis sous-jacent.

CA-M2-05 : les transitions qualifie vers perdu et nouveau vers perdu sont rejetées avec REJ-MOTIF-ABSENT si aucun motif non vide n'est fourni.

CA-M2-06 : toute transition non listée dans les transitions autorisées est rejetée avec REJ-TRANSITION-ILLEGALE et aucun maillon n'est écrit.

CA-M2-07 : la détection de doublon potentiel signale sans fusionner ; le registre contient toujours les deux leads distincts après signalement ; aucune fonction de fusion n'existe dans l'arborescence du module.

CA-M2-08 : la readiness gate retourne faux si l'une quelconque des quatre conditions n'est pas satisfaite, et retourne faux spécifiquement lorsque l'unique interaction humaine enregistrée porte un horodatage strictement antérieur à l'horodatage de transition vers qualifie (l'interaction doit être post-qualification).

CA-M2-09 : le digest quotidien liste de manière déterministe et exhaustive tous les leads en statut nouveau ou qualifie, triés par date d'ingestion fournie par l'appelant, et produit un résultat identique entre deux exécutions successives avec les mêmes entrées.

CA-M2-10 : le registre est hash-chaîné ; valider_chaine retourne vrai après toute séquence d'opérations valides et faux après altération, troncature ou réordonnancement d'un maillon.

CA-M2-11 : toute fixture utilisée en test porte le marqueur fictif: true ; une fixture sans ce marqueur ou avec fictif: false est rejetée avant toute lecture.

CA-M2-12 : le digest signale comme orphelin tout lead en statut nouveau dépourvu d'owner dont la date d'ingestion fournie par l'appelant précède de plus de 48 heures l'horodatage de production du digest ; ce comportement est vérifié avec une horloge entièrement injectée par l'appelant, sans aucun appel à datetime.now ni équivalent.

CA-M2-13 : chaque fichier dupliqué depuis M1 (encodage.py, horodatage.py, registre.py) porte dans les tests M2 une empreinte sha256 attendue, déclarée comme constante littérale dans le fichier de test M2 lui-même (jamais lue depuis l'arborescence M1, afin de préserver l'absence de couplage inter-modules même en test). Un test miroir côté M1 vérifie symétriquement que ses propres fichiers produisent les mêmes empreintes. Toute divergence fait échouer la CI des deux côtés.

CA-M2-14 : une suite de cas d'abus héritée de M1 (collisions par concaténation directe, horodatages invalides, mutations de chaîne, réordonnancements) est rejouée intégralement contre les implémentations M2, sans partage de code de production entre M1 et M2, et chaque cas produit le même verdict déterministe des deux côtés.

7. Hors périmètre v1

Intégration CRM tiers réelle : nécessite credentials et environnement T3. Envois réels de notifications : GATED, même régime que M1-S007. Webhooks entrants depuis formulaires tiers : GATED, surface d'attaque nécessitant validation sécurité. Écriture en base de données externe : T3. Fusion automatique de doublons : exclue par conception, la fusion est une décision humaine irréversible qui ne doit jamais être déléguée à un algorithme. Calcul de prix, de devis, ou de marge : domaine M3. Planification de chantier ou attribution de créneaux : domaine M4. Facturation et suivi financier : domaine M5. Génération de prochaine action par LLM : exclue, toute prochaine action est fournie par l'appelant humain pour garantir l'absence d'hallucination sur les engagements.
