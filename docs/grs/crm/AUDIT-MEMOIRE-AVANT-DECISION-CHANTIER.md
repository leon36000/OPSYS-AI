# CRM-08 — mémoire d’affaire avant décision : audit du port réel

27 octobre 2026. Parent 28f8ab78734ef1a5fbcfc9ce5d9539b0f15c9915. PARTIAL.
Revue statique ciblée wave1_m4_calendar puis contrôle ROOT des propriétaires et tests existants.
Aucun raccord M10 console CRM n’est encore livré par ce document.

## Propriétaires et identité

`m10_memoire.outils.lire_paquet_affaire_appareil(affaire_id, horodatage)` est un vrai lecteur
T0 admin appareil. Il exige identité actuelle et transaction, assemble avec `agent=None` et
applique la vue restrictive; aucune donnée financière ni CLIENT_PRIVATE. Il rend directement
le paquet, sans l’enveloppe métier `accepte/resultat` utilisée par `preparation_chantier._appel`.
Il faut donc un adaptateur dédié, pas une adaptation silencieuse du helper partagé M2/M3/M4.

`m10_paquet_contexte_affaire` est un autre port, privé MCP, dont le destinataire vient du
contexte serveur; la console ne doit pas se faire passer pour M4 afin de voir davantage.
`m10_contexte_preflight` est T1 et peut écrire un refus; ce n’est pas le lecteur à réutiliser.
Le `/memoire` actuel de la console concerne le développement, pas les affaires CRM.

L’identité d’affaire vient du lead exact déjà validé avec le devis par le lecteur de préparation.
`m10_memoire.etapes._extraire_devis_accepte` conserve lead_id, devis_id, chantier_id éventuel,
horodatage_acceptation sous horodatage. `classification.lead_id` rend l’affaire du fait, sans
inférence depuis un identifiant d’intervention. Retrouver dans le registre M10 evenements le
fait m3.devis_accepte du devis exact : même lead et heure d’acceptation que le vrai M3.
Une autre soumission du même client ne remplace pas cette ancre.

Le contrat `m10_memoire.affaire.valide` accepte un lead ASCII 1–64 caractères ou une opportunité
`<lead>~opp~<wct_id>` bornée. Certains identifiants Unicode/longs admis par le CRM ne sont pas
représentables. Ne pas tronquer ni hacher ni substituer devis_id/intervention_id. Une opportunité
reste distincte du lead d’origine; aucune recherche de mémoire avec rabattement automatique.

## Paquet, omissions et absence

`paquets.assembler_paquet_contexte` expose quatre couches avec vide, tronque, nb_total,
nb_inclus, nb_omis. Garder ces compteurs et les compteurs globaux signaux.nb_ouverts,
nb_pris_en_compte, nb_clos, même si les faits correspondants ne tiennent pas dans le détail.
`consolidation` conserve les jours non résumés. Le budget nominal est 4 000 caractères et
cinq faits par couche; le lecteur appareil borne aussi l’enveloppe entière. Ce budget ne
borne pas le chargement initial des registres evenements et affaires.

`affaire` distingue AMONT-AFFAIRE-INCONNUE et AMONT-ORIGINE-NON-RECUE. Le code existant ne
définit pas une règle imposant de refuser N3 ou les dates quand M10 est vide. Pour la tranche
préparatoire, montrer explicitement absence/non-représentabilité/omissions et signaux; ne pas
présenter un paquet inconnu comme un preflight réussi. Une contradiction du lien devis/lead
ou une intégrité illisible doit refuser la consultation. Une politique bloquante par signal
critique reste à définir chez le propriétaire, sans prétendre l’avoir déduite du simple lecteur.

## Plus petit patch prévu

1. Adaptateur console privé de lecture, SQLite canonique, admin SQL et session vivante; aucune
   nouvelle permission et aucun rôle M4 usurpé. Réutiliser le lien réel M3/M4 de préparation.
2. Borner les deux registres M10 avant décodage, puis valider leurs chaînes par le vrai
   `m10_memoire.registre.Registre`. Lire le fait exact et ses références; pas de mémoire parallèle.
3. Appeler le vrai T0 sous identité console admin, heure serveur, cible serveur fixe. Vérifier
   affaire_id et confidentialité restrictive de la réponse, préserver couche/omission/signaux;
   borne JSON 64 Kio et rendu HTML 128 Kio. Aucune copie durable du paquet ni consolidation.
4. Intégrer cette lecture à la revue N3 : contexte humain visible, empreinte liée aux têtes M10
   et au lien devis. Exclure l’heure volatile de consultation de l’empreinte de décision.
5. Relire les têtes et l’identité avant/après une nouvelle application; un changement depuis
   la revue rend l’intention périmée. Conserver l’historicité du même reçu N3, sans reconstruire
   une nouvelle décision ni faire croire que son contexte historique est courant.
6. Ensuite seulement adapter les changements critiques de dates; ne pas modifier en même temps
   la politique de fraîcheur météo, le dispatch ou la capacité globale.

## Qualification à exécuter

Réutiliser les vrais producteurs/bus de `tests/test_cascade_amont_m10.py` et du parcours CRM-08;
les contrats `departments/m10-memoire/tests/test_paquet_affaire.py` et
`test_paquet_appareil_borne.py`, ainsi que `tests/test_lectures_m10_appareil_sans_artefact.py`.
Ajouter : devis étranger, fait exact absent, lien contradictoire, identifiant non représentable,
paquet tronqué avec signaux ouverts omis, révocation, quota avant décodage, chaîne altérée,
changement de tête entre revue/décision et pendant action, reçu historique après contexte changé.
Chaque lecture/refus doit laisser la base intacte; rollback complet de l’action et de sa décision
si la validation échoue après effet M4. Homes/tmp privés avant imports, Source lecture seule
pendant QA et réseau interdit; preuves distinctes, anciennes cohortes compatibles réutilisées.

## Statut, risques et gates

Audit prêt; aucun test nouveau de ce raccord n’a encore été exécuté, aucune intégration n’est
prétendue. Risques : confusion affaire/client, restriction ignorée, compteur caché par budget,
paquet vide pris pour un feu vert, heure volatile rendant toute intention périmée, mutation de
preflight T1 involontaire et prêt de rôle serveur. Aucun gate Nathan supplémentaire pour cette
lecture préparatoire réversible. Les décisions sensibles réelles et la politique de blocage
restent explicites. Prochaine action : écrire le cas réel de consultation M10 depuis la revue
N3 avant le port; conserver les dates et le dispatch complets ouverts.

## Constats reproduits pendant le port privé

`memory-read-v3` : 102 PASS et une régression SQL A→B→A rouge. Une nouvelle entrée temporaire
M10 consommée par le vrai T0 puis retirée avant la relecture pouvait produire un paquet accepté
sous les têtes initiales. Le lecteur appareil doit assembler sur des snapshots immuables dont
il cite les têtes réellement consommées; comparer ces preuves côté port, sans changer le paquet
privé serveur/Core. Valider les chaînes de ces snapshots avant assemblage.

La revue indépendante constate aussi chantier_id non comparé; `memory-read-v4` reproduit un
fait M10 rechaîné au chantier étranger encore marqué LIE. Dériver tous les champs depuis la
charge M3 publiée exacte par `etapes.etape(...).extraire`, puis comparer à la forme canonique
`amont._entree`, y compris chantier_id=None. Ne jamais assimiler ce chantier à intervention_id.

## Jalon exécuté — port privé de lecture, sans raccord décisionnel

`console/memoire_chantier.py::lire` valide le lien M3/M4 réel, borne avant décodage les deux
registres M10, contrôle leurs chaînes, vérifie l’intégralité du fait accepté par la projection
canonique M3 et appelle le vrai T0 admin restrictif. État LIE signifie uniquement ce lien de
source; DEVIS_NON_MEMORISE et NON_REPRESENTABLE restent explicites, jamais une autorisation.
Les couches, omissions, signaux et consolidation sont conservés et vérifiés; l’empreinte de
consultation exclut seulement l’heure volatile. Aucun reçu, événement ou preflight n’est écrit.

Le lecteur appareil M10 assemble maintenant depuis des copies capturées et validées des vrais
registres, puis cite `source_registres` (têtes effectivement consommées). Le port compare ces
preuves aux têtes préparées et relues; le contrat privé serveur/Core n’est pas modifié.

`memory-read-red-v1` constate le port absent; v1/v2/v5 sont des refus statiques avant tout test.
`memory-read-v3` 102 PASS et le rouge SQL ABA; v4 reproduit le chantier étranger accepté.
`memory-read-v6` **107 PASS, 0 FAIL/SKIP, 13,48 s**, dont 18 cas du nouveau port, cascade amont
réelle, quotas sans artefacts, paquet d’affaire et autorisations appareil; Ruff/vérificateur
297/173 passent. Les cohortes ne sont pas additionnées. Sont prouvés : lecture sans écriture,
ancre étrangère/contradictoire ou absente, retrait de rôle/expiration avant M10, chaîne cassée,
quota SQL avant décodage, projections altérées/excessives, tête changée et SQL A→B→A refusés.
Six signaux critiques réels M10 sont créés par les propriétaires WCT/variance : certains sont
omis du détail mais nb_ouverts=6 et nb_omis restent visibles. Ce fixture M10 ne qualifie pas à
lui seul une clôture terrain M4 réelle. Revue finale statique : aucun constat restant.

**PARTIAL** : port privé qualifié sur SQLite; pas encore d’affichage ni de contrôle M10 dans
la revue N3 ou la modification de dates. La branche NON_REPRESENTABLE suit le contrat existant
M10; une chaîne CRM complète avec un tel identifiant n’a pas été qualifiée ici. Aucun signal
n’est traité ou clos et aucune politique bloquante n’est inventée. Prochaine action : raccorder
le contexte courant à la revue N3 puis son empreinte avant/après application, en préservant le
reçu historique et le rollback atomique; les dates critiques restent une tranche distincte.

## Tranche suivante — contexte visible et CAS de décision N3

La revue doit afficher le paquet courant restrictif avant le bouton N3 : liaison du devis,
faits, sources, omissions et compteurs globaux de signaux, sans transformer un lien LIE en
validation métier. L’empreinte du formulaire inclut l’empreinte stable du lecteur M10;
l’heure volatile n’y entre pas. Après une nouvelle décision réelle, relire le même contexte
et refuser/rollback si sa source a changé, même lorsque l’erreur est capturée par l’appelant.
L’audit de décision garde l’empreinte, les têtes et la référence exacte du devis consulté,
sans recopier les faits. Le même reçu rejoué demeure historique : aucune seconde décision,
affichage du contexte actuel identifié comme tel, aucune prétention de contexte historique.

Le formulaire reste fermé aux trois champs existants. Une mémoire absente reste signalée;
aucune politique bloquante par signal n’est ajoutée. Les dates civiles ne sont pas modifiées
par cette tranche. Qualifier sources changées après revue et pendant décision, rollback,
rejeu avec nouveau contexte, signaux omis visibles et absence M10 avant de livrer le raccord.

## Jalon exécuté — revue N3 et décision liées au contexte courant

`application_chantier.preparer` relit le vrai paquet M10 restrictif et inclut uniquement son
empreinte stable dans le CAS existant. La revue HTTP affiche le contexte avant le bouton N3 :
liaison du devis, faits, sources, omissions, compteurs globaux de signaux et consolidation.
Le formulaire conserve les trois seuls champs CSRF/intention/empreinte; pas d’argument mémoire
libre, pas de changement de rôle ni de politique de blocage. Le GET ne modifie aucune table.

Après exécution d’une nouvelle décision N3 réelle, le port relit M10; une empreinte différente
refuse avant finalisation et le savepoint annule l’approbation, les effets M4, le reçu et l’audit.
L’audit final garde empreinte/têtes/référence du devis consulté, sans copier les faits. Un ancien
reçu reste historique et ne crée aucune seconde décision. La page de rejeu identifie le contexte
affiché comme actuel et dit qu’il ne reconstitue pas celui de la décision initiale.

`memory-decision-red-v1` reproduit l’absence de contexte dans la revue; v1/v2 s’arrêtent au
lint avant tests. `memory-decision-v3` **55 PASS, 0 FAIL/SKIP, 29,35 s** : cinq nouveaux cas
et cohortes existantes application privée/HTTP, lecteur M10 et proposition HTTP. Le refus de
mémoire changée après revue conserve la base complète; le changement injecté pendant la vraie
décision annule tout, même lorsque l’exception est capturée dans la transaction extérieure.
Six signaux critiques M10 restent comptés et avertis même lorsque des détails sont omis.
Le rejeu après nouvelle mémoire n’ajoute pas d’approbation et montre le contexte courant.

`memory-decision-v4` ajoute **2 PASS, 2,55 s** sous les mêmes sources produit, anciens tests
conservés comme préfixe exact : absence du devis M10 visible avant une décision humaine interne,
et données d’audit au format ancien sans champs M10 rejouables historiquement. Ce dernier cas
est une fixture de format de données, pas une exécution d’ancien binaire. Les cohortes se
recoupent et ne sont pas additionnées. Ruff et vérificateur 297/173 passent; revue indépendante
statique sans constat concret restant. Source lecture seule pendant QA, homes/tmp privés avant
imports, réseau interdit, 1 CPU/1 Gio/96 tâches; commandes/empreintes/logs/JUnit/reçus distincts.

**PARTIAL** : contexte M10 et CAS qualifiés pour l’application interne N3 sur HTTP/SQLite.
Aucun signal n’est clos ni sanctionné. Les changements critiques de dates civiles, plans
legacy/multi-interventions, la politique de fraîcheur météo, la capacité globale/trajets et
le dispatch restent à traiter. Navigateur, PostgreSQL, mobile et produit complet ne sont pas
qualifiés par ce jalon. Prochaine action : auditer les ancres M4 de chaque visite pour étendre
la lecture M10 aux dates sans inventer un devis accepté sur un chantier manuel.
