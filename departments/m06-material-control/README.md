# M6-material-control

Material Control OS — inventaire, PO, variance sans accusation

Statut : PARTIEL (mode `ombre`, sur le modèle de M3 ; état exigence par exigence :
`docs/reprise/MATRICES-20261031/MATRICE-EXIGENCES-M6.json`). Les 9
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

M6.6 (tranche du 1er novembre 2026) — commande par courriel via M1 : une demande de commande reçue par courriel devient un brouillon de demande rapproché des devis et des WCT
(`commande_courriel.py`, `m6_lire_commandes_courriel`, `m6_traiter_commande_courriel`), la confirmation d'un fournisseur met le PO à « confirmé » seulement si tout tient
(sinon `m6_valider_confirmation_courriel`, personne), et le courriel d'un PO approuvé part par le sas de M1 après l'approbation d'une personne (`m6.po_courriel_pret`).
**PARTIEL, prouvé sur doubles** : voir [`docs/architecture/M1-M6-LEA-ROSALIE.md`](../../docs/architecture/M1-M6-LEA-ROSALIE.md).

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
le stock bas. Limites : [levée par T4.14 : le seuil se compare au DISPONIBLE quand du stock est réservé] ; le digest quotidien et `m6_receptionner_commande` gardent leurs seuils fournis par
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

PLAN T4.14 — réservation par chantier, emplacements et « matériel prêt » (M6.8, M6.9, M6.4).

*Réservation* (`reservations.py`, pur ; registre durable `reservations`, un instantané par fait). Le consommateur de
`m3.devis_accepte` réserve, dans la MÊME transaction que le prévu, ce qui est disponible pour le devis : pour chaque
ligne, `min(besoin, disponible)`, jamais plus. Une estimation (`m3.besoins_materiaux`, prévu provisoire) ne réserve jamais ; un
prévu vide ne réserve rien et ne dit rien (jamais « prêt » par défaut) ; un devis dont les matériaux sont déjà déclarés
non plus. Pas de double réservation : un devis a au plus une réservation active, et le total réservé d'un article ne
dépasse jamais son en main. `disponible = en main - réservé`, où `en main = stock théorique tous lieux - hors main`
(`stock.deriver_disponibilite`) ; il alimente le réapprovisionnement (`reapprovisionnement.evaluer(..., reserve=)` : le
seuil se compare au disponible, `quantite_a_commander = cible - disponible`, sans réservation rien ne change). Le stock
n'est jamais négatif : réception, déclaration des matériaux, transfert hors main et libération réconcilient les
réservations (`reservations.reconcilier`, les plus récentes cèdent d'abord quand l'en main baisse, les plus anciennes se
complètent d'abord quand il monte). La déclaration des matériaux d'un chantier CLÔT sa réservation. Libération :
`m6_liberer_reservation` (N2, motif requis, rejeu sans effet) ; le bus ne re-réserve jamais ce qu'un humain a libéré,
`m6_reserver_materiel` le peut.

*`m6.materiel_pret`* (catalogue `src/opsys/evenements/catalogue/m6.materiel_pret.json`, schéma fermé, toutes propriétés
requises) : `pret` (chaque ligne réservée en entier), `a_commander` (rien n'est réservé) ou `partiel`, avec `lignes` et
`lignes_manquantes` (quantités en texte décimal canonique, unité du prévu recopiée sans conversion), `reservation_active`,
`declencheur` et l'horodatage du fait (M6 n'a pas d'horloge). Identifiant déterministe
`m6-materiel-pret-<devis_id>-<revision>` : une révision par changement (création, ajustement, libération), donc un retour à
un état déjà vu n'est jamais confondu avec le premier. Publié dans la transaction du fait de réservation. Après une
libération : `a_commander`, `reservation_active` faux. **Ce que M4 doit lire** : pour l'intervention née d'un devis, la
charge de plus grande `revision` de son `devis_id` ; `statut == "pret"` avec `reservation_active` vrai est le SEUL état
« prêt » ; aucune charge pour ce devis n'est PAS « prêt » (M6 n'a rien vérifié : prévu vide, estimation, ou devis pas
encore reçu). Aucun bon de commande n'est jamais créé seul : `a_commander` dit ce qui manque, le brouillon de PO se
demande (`m6_creer_po_brouillon`, qui commande alors ce qui MANQUE à la réservation, pas l'écart au stock du chantier),
puis s'approuve.

*Emplacements* (`emplacements.py`, pur ; registre durable `emplacements`, hash-chaîné). Liste FERMÉE : dépôt, camion,
remorque, chantier, employé, fournisseur, retour, rebut, inconnu (référence requise pour camion, remorque, employé,
chantier, fournisseur). `m6_transferer_stock` déplace du stock, AUDITÉ : acteur (l'identité d'appareil confirmée, ou
`agent`), motif requis, horodatage, quantité, avant et après des deux extrémités ; idempotent par `transfert_id` ;
aucune quantité par emplacement n'est jamais négative ; le stock non localisé (tout celui d'avant T4.14) est à
`inconnu`, un résidu. Fournisseur, retour et rebut ne sont pas en main. **La chaîne de mouvements (`registre.py`) n'est
pas modifiée** : aucun champ de plus, aucun hachage qui bouge (empreintes figées dans `test_emplacements.py`, calculées
avant T4.14). Lecture : `m6_lire_disponibilite` (T0). Quatre outils, `admin` seulement (`docs/architecture/ROLES.md`) : la
portée d'appareil ET le code (`REJ-IDENTITE-APPAREIL-INVALIDE` pour tout autre rôle, la lecture T0 comprise).

Limites connues : (1) le stock ne déclare pas d'unité : M6 ne convertit rien ; (2) les sorties de stock ne disent pas d'où
elles sortent : la répartition par emplacement ne suit que les transferts, et une sortie non localisée qui dépasse le
stock localisé bloque les transferts jusqu'à régularisation (`REJ-TRANSFERT-STOCK-LOCALISE-INCOHERENT`) ; (3) « ajustement
si l'estimation change » (M6.8) : le prévu définitif d'un devis ne change plus après l'acceptation ; (4) le facteur de
perte du prévu provisoire n'est pas appliqué ; (5) les seuils de réapprovisionnement restent GATE NATHAN : vides,
« seuil non configuré » ; (6) M4 ne lit pas encore l'événement (`preparation.py`, autre agent) ; (7) si les matériaux d'un
chantier sont déclarés avant que M6 ait reçu son WCT (`m4.travaux_termines`) et que `m3.devis_accepte` arrive ensuite,
la réservation créée reste active ; les événements étant livrés dans l'ordre de création (devis avant travaux), le cas
n'est pas observé.

PLAN C1/C2/C3 (2026-11-02, branche `claude/m6-sortie-article-po`) — la sortie de stock se chiffre au niveau de l'ARTICLE, le
bon de commande se COMMANDE à un vrai fournisseur, et l'admin le VOIT. **PARTIEL, prouvé sur doubles** (SQLite, bus réel, M1 sur
double de Gmail) ; aucun fournisseur réel, aucun courriel réel.

*C1 — coût de sortie par article* (`cout_sortie.py`, pur ; défaut F1 de l'analyse M6). `m6_declarer_materiaux_utilises` n'est
plus refusée en entier (`REJ-COUT-UNITAIRE-INTROUVABLE`) quand un article n'a jamais été reçu SOUS CE chantier : l'achat sur place
d'un article inédit, l'article non prévu inédit et la sortie du dépôt vers un autre chantier se déclarent. Le coût de chaque ligne
vient d'une source ORDONNÉE et DITE (`origine_cout`, sur le mouvement, dans son empreinte) : 1. dernière réception de l'article sous
le chantier (`RECEPTION_CHANTIER`) ; 2. sinon sa dernière réception ailleurs (`RECEPTION_ARTICLE`, une livraison de quantité nulle
ne compte pas) ; 3. sinon le livre de prix (`LIVRE_PRIX`), comme M5 le lit : dernière entrée de chaque fournisseur datée au plus
tard du jour du WCT, DANS L'UNITÉ DE LA LIGNE (une unité absente ou différente n'est jamais présumée égale), en CAD ; un seul prix
distinct : ce prix, marqué `SOURCE_DECLAREE` (document cité) ou `FALLBACK_PRICE_BOOK` (aucun document) ; des prix différents selon le
fournisseur : AMBIGU, aucun prix choisi ; 4. sinon `INCONNU` (`cout_unitaire: null`, motif `AUCUN_PRIX`, `UNITE_NON_CONFIRMEE`,
`PRIX_AMBIGU` ou `DATE_ILLISIBLE`) : la déclaration est ACCEPTÉE et l'admin reçoit une attente `cout_sortie_inconnu` qui dit quoi
déclarer (`m6_enregistrer_prix`, unité comprise) ; elle disparaît dès qu'un prix applicable existe, sans réécrire le mouvement.
Aucun coût n'est « validé » (le mot n'existe pas dans ce chemin) ; l'employé ne voit ni coût ni origine. Un stock devenu négatif
par cette voie est dit à l'admin (attente `stock_negatif`, même sans seuil de réapprovisionnement). Décision d'écart avec la
consigne « puis refus lisible » : refuser la déclaration pour un prix manquant AURAIT ÉTÉ le défaut F1 lui-même ; le refus lisible
est donc l'attente adressée à l'admin, pas un blocage du terrain.

*C2 — PO commandable* (`bons_commande.py`, `po_lecture.py`, `outils.py`, `commande_courriel_outils.py`). Chaque ligne porte son
UNITÉ (obligatoire ; égale à celle de la fiche article `catalogue_materiaux` quand elle existe, sinon l'unité du besoin, et le PO
le dit : `unite_source`), sa quantité NETTE, le facteur de perte DÉCLARÉ par l'estimation M3 (jamais inventé : sans déclaration,
quantité à commander = nette, et la réponse liste `facteurs_perte_absents`) et la quantité à commander = nette x (1 + perte),
appliquée UNE seule fois, en décimal exact (aucun arrondi à l'unité de commande n'est inventé). Le PO porte `date_requise`
(jour civil, au plus tôt celui de la création), `mode_livraison` (`livraison_depot`, `livraison_chantier` avec `lieu_livraison`,
`ramassage`), `ville` (pour l'objet), `notes` et `devis_id`. Un prix du livre dans une autre unité ne s'applique pas
(`INDETERMINE`, approbation refusée) ; sans unité il s'applique mais `prix_unite_confirmee` est faux. Un PO d'avant C2 se lit mais
n'est ni approuvé ni envoyé (`REJ-PO-NON-COMMANDABLE`) : on l'annule et on le refait. UN besoin, PLUSIEURS fournisseurs :
`m6_creer_pos_depuis_besoin` crée un PO brouillon par fournisseur ; chaque ligne à commander est affectée à un seul PO (ni oubliée,
ni doublée, ni inconnue) et tout est écrit ou rien. Le courriel de M1 est complet (objet « Commande matériaux — PO — ville »,
chantier, date requise, livraison ou ramassage, lignes avec unité et perte visibles, demande de confirmation ; AUCUN prix) et son
`empreinte` identifie le texte exact. `m6_creer_po_brouillon`, `m6_creer_pos_depuis_besoin` et `m6_generer_courriel_po` passent
en N2 (règle d'autonomie r1 : brouillons N0-N2) ; l'APPROBATION du PO reste N3 et l'envoi reste approuvé par une personne au sas de
M1. Plus de double approbation : `m1.commande_courriel_envoyee` porte maintenant l'empreinte du courriel du PO et dit si le texte
envoyé est celui qui avait été préparé ; M6 passe le PO à `sent_to_supplier` seulement si le PO est `email_ready`, l'empreinte est
celle du courriel de CE PO et le texte n'a pas été modifié au sas (constat rangé sur la transition) ; sinon l'attente N4 « marquer le PO
envoyé » reste à une personne, comme pour un envoi hors M1. Aucun chemin d'envoi n'est ouvert.

*C3 — lire et piloter* (`po_lecture.py`). `m6_lister_po` / `m6_lire_po` (T0/N0, admin ; aucun rôle d'appareil) : liste blanche de
champs, pages de 25 au plus sans troncature, comptes par statut, « en retard » (envoyé, confirmé ou partiel, date requise passée à
un jour dit) ; `m6_changer_statut_po` (N3, motif) pilote `pending_admin_review`, `disputed`, `invoiced`, `closed`. Attentes de
l'admin : `po_a_approuver` (N3), `ecart_materiaux_critique` (le MESSAGE IMPOSÉ de Nathan mot pour mot, jamais « vol », jusqu'à ce que
la cause de chaque ligne critique soit classée par une personne ; le résultat de `m6_evaluer_variance_chantier` le porte aussi).
Les seuils de variance (0.30) et d'écart de prix (0.15) sont des RÉGLAGES DE DIRECTION (`reglages:` du manifeste, adoption N3 du
propriétaire depuis la console, retour arrière) étiquetés « recommandation, non validée » : ils viennent d'un agent, pas de Nathan.
Écran admin « Commandes » de la console (`src/opsys/console/commandes_ui.py`, lecture seule).
*Fournisseurs connus, amorçage VIDE* (`fournisseurs_a_fournir.py`, `configuration.fournisseurs_a_fournir` du manifeste) : Gentek, Royal Solution
de Bâtiment, O.A.M. et Kaycan n'ont fourni ni courriel, ni compte, ni tarif, ni délai ; le manifeste ne porte que leurs NOMS et ce qu'il faut
fournir pour chacun, et l'écran « Fournisseurs » de la console les montre « à fournir » tant qu'aucune fiche de ce nom n'existe (aucune fiche
n'est créée, aucun PO ne peut leur être adressé). Déclarer un fournisseur reste le geste d'une personne.
Limites : voir `docs/utilisation/LIMITES-CONNUES.md` (M6).

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

## Disponibilité du matériel publiée pour M8 — `m6_constater_disponibilite`
(phase 2 de l'entrepôt de M8, D2 : `docs/architecture/M8-ENTREPOT-SOURCES.md`) L'outil (T1/N2, agent seulement, aucun droit d'appareil) publie `m6.disponibilite_constatee` : CINQ comptes (articles suivis, en rupture, sur-réservés, réservations actives et incomplètes), calculés comme `m6_lire_disponibilite` (module pur `constat_disponibilite.py`). Aucun article, quantité, prix ni chantier ne part. L'identifiant porte l'instant du constat.

**Déclenchement.** Ce constat est déclaré par `constats_planifies` du `department.yaml` et lancé par le planificateur durable
(exécuteur `m6.constat.disponibilite`, inactif par défaut, cadence par défaut dérivée du catalogue de M8) : `horodatage` = le début du créneau. Aucun agent n'a besoin de le
faire à la main. Voir `docs/architecture/PLANIFICATION.md` §9.

## C5 — réception enrichie, C6 — achats sur place (M6.7, M6.17)

(2026-11-03, vague 13) **PARTIEL, prouvé sur SQLite réelle + bus réel, données fictives** : aucun service externe, aucun
paiement, aucun envoi.

*C5* (`details_reception.py`, pur ; additif à `receptionner_commande`, contrats gelés) : chaque ligne reçue porte un
statut fermé (`conforme`, `manquant`, `substitue`, `endommage`) — `substitue` exige le matériau substitué nommé
(`REJ-RECEPTION-SUBSTITUE-INCOMPLET`), `endommage` exige au moins une photo CAS `fichier:sha256:` (sinon preuve
manquante, refus avant écriture), tout autre statut est refusé (`REJ-RECEPTION-STATUT-INCONNU`, injection comprise) ;
le lieu de livraison est un lieu fermé d'arrivée (`depot`, `chantier`, `camion`, `remorque`, `employe`, référence exigée
sauf `depot`, délégué à `emplacements.normaliser`, sinon `REJ-RECEPTION-LIEU-INVALIDE`) ; le prix lu du bon de livraison
(`prix_bl`, donnée saisie marquée `BON_LIVRAISON`) est comparé au prix prévu du PO en `Fraction` sur le texte décimal au
seuil DÉCLARÉ `m6.seuil_ecart_prix_reception_pourcentage` (0.15, borne incluse, baisse comprise) : au-delà, signaux
`signaux_prix_bl` retournés (vers M5/M8 comme `signaux_ecart_prix`, jamais transmis directement) et attentes admin
`ecart_prix_bl_a_verifier` (N3). Absents, le comportement est inchangé. L'événement `m6.reception_enregistree`
(schéma fermé) est inchangé.

*C6* (`achats_terrain.py`, pur ; nouvel outil `m6_declarer_achat_terrain`, T1, `employee`+`admin`) : l'achat sur place
(montant en TEXTE décimal exact, jamais un float, reçu photo CAS OBLIGATOIRE `REJ-ACHAT-TERRAIN-PREUVE-MANQUANTE`,
chantier, raison) est validé fail-closed (rôle terrain, sinon `REJ-ACHAT-TERRAIN-ROLE-INTERDIT`), décidé au plafond
DÉCLARÉ `m6.plafond_achat_terrain` (150, borne incluse, CFG-1 : absent ou illisible, attente admin) : sous le plafond,
accepté et tracé au registre durable dédié `achats_terrain` (idempotent par reçu + matériau + chantier,
`REJ-ACHAT-TERRAIN-DEJA-DECLARE`), avec l'attente M5 `depense_terrain_a_saisir` (source `RECU_TERRAIN`, jamais de
`paiement`/`remboursement`) ; au-delà, attente admin N3 tracée (`en_attente: True`) AVANT toute entrée au stock.
M6 ne paie ni ne rembourse jamais. Bouts couverts : `tests/test_reception_enrichie_c5.py`,
`tests/test_achats_terrain_c6.py`, `tests/test_cablage_c5_c6.py`, `tests/test_bout_en_bout_c5_c6.py` (PO persisté →
réception enrichie → événement → achat sous/hors plafond → idempotence → injection refusée).
Limites : signaux BL retournés comme les écarts PO (aucune publication dédiée) ; seuils et plafond à adopter par la
direction (recommandations d'agent, non validées).

## C10 — ajustements d'inventaire audités, C9 — alertes et rappels planifiés (M6.14, M6.13)

(2026-11-03, vague 14) **PARTIEL, prouvé sur SQLite réelle + registres durables, données fictives** : aucun service
externe, aucun envoi, aucune suppression.

*C10* (`ajustements.py`, pur ; nouvel outil `m6_ajuster_stock`, T1/N3, agent seulement) : un humain corrige le stock avec
un motif de la liste FERMÉE (`correction`, `stock_retrouve`, `retour_fournisseur`, `erreur_saisie`,
`inventaire_physique`, `annulation`), une quantité VISÉE (`quantite_apres`, jamais un écart fourni), une preuve CAS
`fichier:sha256:` FACULTATIVE et un horodatage. L'écart (après - avant) est calculé contre le registre ; il est écrit
comme mouvement `AJUSTEMENT` et change le stock total, jamais celui d'un chantier (`chantier_id` = `*`). Le maillon
porte une extension `ajustement` (identifiant, motif, preuve, emplacement, avant/après, écart, niveau et seuil
d'approbation, acteur, approbateur, horodatage) qui entre dans son empreinte ; les maillons antérieurs, qui ne la
portent pas, gardent leur hash à l'octet près. Un ajustement sur un emplacement NOMMÉ écrit en plus un transfert audité
entre ce lieu et `inconnu`, pour que le lieu porte vraiment la quantité corrigée. Idempotent par `ajustement_id` (même
demande : aucun second maillon ; même identifiant, autre demande : refus). Seuil DÉCLARÉ
`m6.seuil_ajustement_stock_quantite` : `abs(écart) <= seuil` reste N3 ; au-delà — ou seuil absent/illisible — il faut
l'approbation d'un `admin` ou du `nathan_owner` (`approbations.approbateur_en_cours`), une approbation de `manager` ne
suffit plus. Aucun prix n'est lu ni écrit.

*C9* (`alertes_approvisionnement.py`, pur ; constat planifié existant `m6.constat.disponibilite`, **inactif par
défaut** ; lecture `m6_lire_alertes_approvisionnement`, T0) : le constat calcule des agrégats NEUTRES par article et par
équipe DÉCLARÉE — variance d'inventaire répétée, pertes/bris répétés, ajustements fréquents —, « commande reçue mais
stock disparu », « déclaration d'usage manquante » (WCT reçu sans aucun mouvement), « réception de PO en retard »
(statut `sent_to_supplier`, au-delà STRICT du `delai_habituel_jours` déclaré du fournisseur). Aucun nom d'employé, aucun
prix, aucun texte libre ; un WCT dont le `technicien_id` n'est pas une équipe déclarée n'est jamais regroupé. La fenêtre
`m6.alertes_fenetre_jours` et le seuil de répétition `m6.alertes_seuil_repetition` sont DÉCLARÉS (vides à dessein) :
sans eux, l'instantané porte une entrée `non_evaluees` qui dit quoi déclarer, et les comptes ne sont pas présentés comme
un verdict. L'instantané est écrit dans un registre chaîné `alertes_approvisionnement` (idempotent par instantané) ; les
alertes remontent aussi dans les attentes de l'admin (`attentes()`), 20 au plus, plus une attente « à configurer ».
Bouts couverts : `tests/test_ajustements_inventaire.py`, `tests/test_alertes_approvisionnement.py` (motifs hostiles,
preuve mal formée, seuil à la borne, préparation d'approbation N4, rejeu idempotent, empreintes d'avant, emplacement,
fuite de nom, PO à la borne du délai, fenêtre absente).
Limites : la clôture d'un inventaire physique en lot n'existe pas (l'ajustement se fait article par article) ; le
rapprochement par emplacement s'appuie sur les transferts, pas sur un comptage multi-emplacements ; le constat ne
s'active pas seul ; aucune alerte n'est poussée vers un téléphone ou un courriel (« À voir » se lit dans l'app) ; les
seuils et la fenêtre restent à adopter par la direction (aucune valeur proposée).
## C7 — seuils de variance déclarés et éditables, C4 — cycle de vie du PO (2026-11-03)

**PARTIEL, prouvé sur SQLite réelle + vrais outils/registres/bus, données fictives.** Voir
[docs/architecture/M6-SEUILS-VARIANCE-C7.md](../../docs/architecture/M6-SEUILS-VARIANCE-C7.md).

*C7* (`seuils_variance.py`, pur) : le seuil applicable est celui du **matériau**, sinon de sa **catégorie déclarée**
(`categories`), sinon le global. Une configuration C7 complète porte en plus un **plancher de quantité** et un
**plancher de dollars** obligatoires ; un écart sous l'un des deux ne déclenche pas la revue, même au-dessus du
pourcentage. Le montant est en décimal exact, au cent, à partir d'une valeur unitaire fournie (réception ou livre de
prix) ; sans valeur, le plancher n'est pas inventé : l'écart est marqué critique et une attente dit quel prix déclarer.
L'écran console « Seuils matériaux » (`/seuils-materiaux`, admin ou propriétaire) écrit un registre append-only et
chaîné (version, avant/après, auteur, rôle, motif, horodatage, approbation, empreintes) ; une chaîne retouchée ne sert
plus aucun seuil (`seuil_absent` + attente de reconfiguration). Le message imposé de Nathan est déjà dans l'attente
`ecart_materiaux_critique` et dans le résultat de `m6_evaluer_variance_chantier`, mot pour mot, sans « vol ». Sans
décision C7, le mode `herite` conserve le seul seuil global (0.30, valeur d'agent « recommandation, non validée »).

*C4* (`rapprochements_recus.py::propositions_facturation`, `outils.py::_attentes_po_a_facturer`) : un rapprochement
M5 `CONCORDANT` sur un PO **reçu** produit une attente N3 `po_a_facturer` (une par PO, rejeu sans doublon) ; M6 ne
facture pas seul, l'admin applique `m6_changer_statut_po` avec un motif. Un PO partiel, déjà facturé, fermé, contesté
ou inconnu ne propose rien ; `ECART`/`INCOMPLET` garde l'attente « À voir » vers M5. `closed`/`disputed` restent des
outils N3 avec motif ; l'envoi constaté par M1 (C2) n'exige plus de second clic N4, et `m6_marquer_po_envoye` reste la
voie d'un envoi hors M1.

Limites : aucun navigateur réel, aucun mobile, PostgreSQL non rejoué ; aucune valeur réelle (seuils, planchers et
catégories vides tant que la direction ne les déclare pas) ; le plancher en dollars utilise le coût de sortie, pas le
prix payé ; l'audit n'a pas d'ancre externe ; aucune politique permanente de facturation.
