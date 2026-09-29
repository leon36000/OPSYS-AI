# M6-material-control

Material Control OS — inventaire, PO, variance sans accusation

Statut : département OPSYS complet (mode `ombre`), sur le modèle de M3. Les 9
stories du PRD (`docs/bmad/02-PRD-PM.md`) sont livrées et vertes : validation
des entrées WCT/formulaire/clés interdites (S001), catalogue + résolution de
prix FALLBACK (S002), cycle PO → réception (S003), stock localisé par
chantier (S004), variance d'inventaire sans accusation (S005),
réapprovisionnement suggéré (S006), contrats de sortie séparés par
destinataire (S007), registre append-only hash-chaîné (S008), conformité
statique + digest (S009). Couche département ajoutée : `department.yaml`,
`SOUL.md`, 3 skills (`receptionner-une-commande`,
`consommer-du-materiel-terrain`, `compter-l-inventaire`),
`src/m6_material_control/outils.py` (7 outils agent, dont
`m6_receptionner_commande` : réception → stock → variance de bout en bout),
`tests/test_outils_agent.py`.

PLAN T1.1-d — formulaire de fin de chantier enrichi et variance de chantier (ajout postérieur
à la passe ci-dessus) : `materiel.soumettre_materiaux_utilises` (nouvelle fonction, lignes
typées prevu/non_prevu/retour/perte/bris/achat_terrain, `REJ-ACHAT-TERRAIN-PREUVE-MANQUANTE`
fail-closed si aucune photo ni reçu ; `m6_consommer_materiaux` inchangé) ;
`variance_chantier.py` (nouveau module, **distinct** de `variance.py` : estimé M3 vs réel
déclaré, verdict neutre, `cause_possible` toujours `None`, jamais « vol ») ; outil
`m6_evaluer_variance_chantier` (T0) qui émet `SignalVarianceChantierCritique` sur un seuil
fourni par l'appelant — M6 signale, ne touche jamais le statut M4.

PLAN T1.1-d2 — la déclaration de fin de chantier est maintenant persistée : `materiel.
soumettre_materiaux_utilises` prend un `registre` et écrit des mouvements typés (CONSOMMATION
pour prevu/non_prevu/achat_terrain ; nouveaux types `RETOUR`/`PERTE`/`BRIS`, ajoutés à
`registre.TYPES_MOUVEMENT_VALIDES` et autorisés explicitement dans `conformite.
DESIGNATION_TYPE_MOUVEMENT` — « et rien d'autre » n'a changé à la garde AST), tout ou rien
(`ajouter_lot`), idempotente par `wct_id` (`REJ-DECLARATION-DEJA-SOUMISE` sur une seconde
déclaration). `registre.py` porte désormais un `wct_id` optionnel sur chaque maillon —
absent, forme et hash restent identiques bit à bit à avant ce changement (rétrocompatibilité
prouvée, `test_registre.py`) ; présent, il entre dans le hash (tamper-evident). `stock.
deriver_stock_theorique` inclut RETOUR (réintègre)/PERTE/BRIS (sortent sans être une
CONSOMMATION). Nouvel outil `m6_declarer_materiaux_utilises` (T1). `variance_chantier.
comparer_depuis_registre` relit le réel déclaré directement au registre (par `wct_id` ou
`chantier_id`) ; `m6_evaluer_variance_chantier` l'utilise quand `lignes_declarees` est omis
— l'entrée explicite reste disponible pour les appels directs.

PLAN T1.4-i — `m6_declarer_materiaux_utilises` prend un `wct_id`, plus le WCT : un fait vient de sa
source de vérité (AGENTS.md), et l'ancien contrat laissait un appareil (ou un modèle) fabriquer un
WCT dont M6 ne vérifiait que la forme. M6 relit la charge `m4.travaux_termines` publiée par M4 pour
ce `wct_id` (`opsys.evenements.charge_publiee`, le magasin du bus, privée de `statut` que le
`WctRecu` de M6 ne porte pas) et la valide comme avant (`valider_wct`,
`valider_formulaire_materiaux_utilises`). Un `wct_id` que M4 n'a jamais publié : `REJ-WCT-INCONNU`,
rien n'est écrit. L'outil ne tourne plus qu'en transaction (registre durable + bus) : il n'a plus de
mode `registre_historique` en mémoire, et hors transaction rien n'est connu, donc tout est refusé.
Idempotence par `wct_id`, arrivée tardive et réévaluation de la variance : inchangées.
`m6_consommer_materiaux` garde, lui, un `wct` fourni par l'appelant (non modifié).

PLAN T1.4-k — qui déclare, et pour quel chantier (`acces.py`, pur ; détail et limites dans
`docs/architecture/ROLES.md`). Pour un appel d'appareil, la personne authentifiée
(`opsys.contexte.identite_appelante()`, revérifiée en base) est confrontée au `technicien_id` du WCT :
un `employee` ne déclare que pour SON WCT (`REJ-INTERVENTION-NON-ASSIGNEE`), l'`admin` pour tous,
l'identité invalide est refusée (`REJ-IDENTITE-APPAREIL-INVALIDE`), rien n'est écrit. Sans identité
d'appareil (agent, console) : aucun contrôle de personne, comme avant. Pour TOUS les appelants,
`intervention_id` du formulaire = celui du WCT (`REJ-FORMULAIRE-MATERIAUX-INTERVENTION-INCOHERENTE`) et
`chantier_id` = celui du prévu du devis du WCT quand il le connaît
(`REJ-FORMULAIRE-MATERIAUX-CHANTIER-INCOHERENT`). Le WCT ne porte pas de `chantier_id` : sans prévu qui
le connaisse, un employé doit envoyer l'`intervention_id` du WCT (un chantier de M4 EST une
intervention), un admin ou un agent restent libres, rien n'est deviné.

PLAN T1.5-d — stock bas et besoin de commande à « travaux terminés » (DEFINITION-PRODUIT.md §6, ligne M6).
`m6_declarer_materiaux_utilises` évalue, après avoir sorti du stock, chaque article touché contre SON seuil
(`reapprovisionnement.py`, règle pure : stock théorique de l'article, tous lieux, strictement sous le seuil ⇒
besoin de `quantite_cible - stock`). Seuil et quantité cible : `department.yaml`, bloc
`configuration.reapprovisionnement.articles`, par `materiau_id` — vide à dessein. Sous le seuil : constat
`besoin_commande` au registre durable `besoins_commande` (idempotent par article et WCT). Sans paramètres
utilisables : constat `seuil_a_configurer`, jamais un seuil deviné, et la déclaration n'est jamais refusée. Stock
négatif : signalé sans quantité. `outils.attentes()` rend à l'admin (`m9_lister_demandes_approbation`, section
« À voir », file du propriétaire, briefing du matin) l'état d'AUJOURD'HUI : un besoin par article encore sous son
seuil, une attente unique « seuil non configuré » pour les articles sans paramètres. Aucun bon de commande n'est
jamais créé par ce chemin (DA-M6-13, DA-M6-17). `m6_consommer_materiaux` (WCT fourni par l'appelant) n'évalue pas
le stock bas. Limites : pas de réservation par chantier (M6.8) ni d'emplacements (M6.9), donc « en main » et
non « disponible » ; le digest quotidien et `m6_receptionner_commande` gardent leurs seuils fournis par
l'appelant ; aucun événement de besoin de commande vers M8/M9 encore.

Bugs corrigés (test rouge → vert) lors de cette passe :
- `materiel.py` n'exposait que `consommer_materiaux`. `enregistrer_reception`
  et `soumettre_comptage`, prescrits par `docs/bmad/03-ARCHITECTURE.md`
  (l.51, 406-410), n'existaient pas : `reception.traiter_reception` est une
  fonction pure qui n'écrit rien, donc aucun matériau reçu n'atteignait
  jamais le registre, et toute consommation ultérieure échouait par
  `REJ-STOCK-INSUFFISANT` faute de stock réellement enregistré. Les deux
  fonctions sont maintenant implémentées selon l'architecture (écriture
  atomique, `SignalPoAPayer` jamais émis si indéterminé, réévaluation du
  reorder).
- `frontieres.py` (clés interdites comme « virement », « statut_paiement »)
  n'était appelé nulle part dans le pipeline réel — câblé dans
  `validation.py` (WCT, formulaire, bon de commande, réception, comptage,
  seuils) et donc dans les 3 orchestrateurs d'écriture.
- Les montants M6 restent des `float` (contrat gelé), alors que
  M5-FinanceCore exige un `Decimal` fini. `contrats_sortie.py` porte
  désormais `montant_decimal_a_la_frontiere` (conversion sûre
  `Decimal(str(x))`, jamais `Decimal(x)`), prouvée par un test
  inter-départements M6 → M5 réel (`tests/test_frontiere_finance_m5.py`,
  aucune modification de m5_financecore).
