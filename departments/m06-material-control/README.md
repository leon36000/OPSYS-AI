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

PLAN T4.15 — pont finance vers M5 (M6.16) : `m6_receptionner_commande`, pour un bon de commande PERSISTÉ, publie
`m6.reception_enregistree` dans la MÊME transaction que le stock et la transition du PO (`evenement_reception.py`
construit la charge, `outils._publier_reception` la publie ; type au catalogue du socle, schéma fermé). Elle dit à
M5 ce qui est arrivé CETTE fois-là (quantités commandées et reçues, prix unitaire du PO, prix résolu à la réception,
écart de prix au-delà du seuil configuré), en texte décimal exact (`Decimal(str(x))`, jamais un float ni la
notation scientifique) ; elle ne porte aucun montant, aucun total, aucune taxe : M5 est la source de vérité de
l'argent. Identifiant déterministe `m6-reception-<po_id>-<16 premiers caractères du hash du dernier mouvement de
stock>` : deux livraisons du même PO, deux événements ; rejouer la même réception, un no-op du bus. Rien n'est
publié pour une réception « éphémère » (aucun PO persisté : pas de fournisseur, M5 n'aurait personne à qui devoir)
ni pour une réception qui n'apparie aucune ligne. Refus AVANT toute écriture, pour un PO persisté : une quantité
reçue négative ou non finie (`REJ-RECEPTION-QUANTITE-INVALIDE` ; zéro reste permis : ligne pas encore livrée) et un
horodatage sans fuseau (`REJ-RECEPTION-HORODATAGE-INVALIDE`). Si la publication échoue, la réception entière est
annulée (stock, PO, événement). M6 ne paie jamais.
Limites connues : (1) l'unité des prix est une question ouverte (GATE NATHAN) : le livre de prix ne déclare pas
l'unité d'un prix unitaire et le PO n'en déclare pas pour une quantité ; M6 ne convertit rien et n'invente aucune
unité, et le dit dans le schéma (M5 le dit dans chacun de ses verdicts) ; (2) `reception.py` compare CHAQUE livraison
à la commande entière : c'est le verdict de la LIVRAISON (celui de `verdict_reception` dans l'événement) ; le
statut du PO, lui, suit le cumul depuis T4.15-b (ci-dessous) ; (3) les quantités et les prix restent des `float`
dans les registres de M6 (contrat gelé) : la conversion en texte est la frontière ; (4) [levée par T4.15-b] la
validation des quantités reçues valait pour un PO persisté seulement.

PLAN T4.15-b — les livraisons d'un PO se CUMULENT (M6.7). Avant : la livraison qui complétait un PO déjà partiel
restait `RECEPTION_INFERIEURE` et le PO ne passait jamais à `received`. Maintenant `m6_receptionner_commande`, pour
un PO persisté, additionne les livraisons (`reception.evaluer_cumul`, décimal exact : 0,1 + 0,2 vaut 0,3) et
décide du statut sur ce cumul : `received` quand chaque ligne a atteint sa commande (`CONFORME` ou
`RECEPTION_SUPERIEURE`), `partially_received` tant qu'une ligne manque (même si une autre est en excédent :
`RECEPTION_MIXTE`). Chaque transition de réception garde SA livraison (`livraison` : empreinte, horodatage,
quantités en texte décimal) dans le registre append-only du PO : le cumul se relit, il n'est jamais un total
recopié. La réponse porte `reception_cumulee` (verdict, quantité reçue cumulée et écart par ligne, `fiable`) ;
`resultat.accuse_reception` et le `verdict_reception` de l'événement restent ceux de CETTE livraison (contrat
gelé, schéma du catalogue inchangé : seul `statut_po` change de valeur). Deux garde-fous : une livraison déjà
enregistrée (même PO, même horodatage, mêmes quantités) est refusée avant toute écriture
(`REJ-RECEPTION-DEJA-ENREGISTREE`) — additionnée deux fois, la moitié d'un PO ferait passer le PO à `received` ; et
un PO dont une réception d'AVANT T4.15-b n'a pas gardé sa livraison (le stock ne porte pas le `po_id`) ne devine pas
son cumul : `fiable` est faux, le verdict reste celui de la livraison seule. Enfin, une quantité négative ou non
finie est refusée avant toute écriture aussi pour une réception ÉPHÉMÈRE (`REJ-RECEPTION-QUANTITE-INVALIDE`) ;
l'horodatage sans fuseau reste permis hors PO persisté.

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
