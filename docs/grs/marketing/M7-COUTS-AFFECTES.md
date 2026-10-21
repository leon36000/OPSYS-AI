# Coûts de campagnes sur pièces fournisseur

Cette tranche prépare une répartition interne des factures fournisseur sans bon
de commande vers les campagnes locales M7 déjà enregistrées. Depuis la page CMO,
le lien « Coûts de campagne sur pièces M5 » ouvre la sélection privée. La campagne
est identifiée par son ID métier ; son nom, sa période et ses UTM proviennent du
lecteur public M7. Le budget de campagne n'est jamais une dépense réalisée.

Le propriétaire choisit une pièce disponible, une période de prestation, la base
HT ou TTC, une part en CAD au cent et un motif. CAD est une déclaration explicite :
la pièce AP sans PO actuelle ne porte pas de devise. Il n'y a ni conversion,
paiement, écriture bancaire, import fournisseur ni publication. L'authenticité
externe de la facture saisie n'est pas vérifiée par cette répartition.

Une vraie décision N4 du propriétaire actif en base conserve cette version, son
signataire et les références des sources. L'administrateur actif peut consulter ;
il ne peut pas écrire. Les trois outils SDK de cette tranche sont projetés
seulement avec un port serveur M7 privé : le catalogue MCP par défaut et celui des
appareils ne les exposent pas. Aucun rôle, signataire ou montant de facture
fabriqué par le navigateur n'élargit ces droits.

Une pièce peut financer plusieurs campagnes. Toutes ses parts actives partagent
la même base ; leur somme ne dépasse pas le montant HT ou TTC courant de M5. Les
parts périmées restent réservées jusqu'à un retrait ou une nouvelle version
explicite. Modifier la cible exige un retrait puis une nouvelle affectation.
L'historique AP et les anciennes versions ne sont jamais réécrits.

Une correction ou annulation AP arrivée plus tard peut périmer une affectation
d'une ancienne période. La page l'exclut du total sans prorata ni ajustement
silencieux. Une écriture sur une autre pièce ne périme pas la facture ciblée,
mais une commande préparée avec un ancien head doit être rafraîchie. L'heure de
lecture ne prétend pas connaître l'état disponible à la fin de la période métier.

Le filtre ISO couvre au plus 366 jours inclusifs. Seules les affectations dont
la période est entièrement incluse sont additionnées. Un chevauchement partiel
reste signalé et exclu. Les totaux HT et TTC restent séparés. Une base absente
est inconnue, jamais zéro. Paiement, taxes non récupérables, coût économique net,
exhaustivité et ROI restent inconnus. Cette page ne calcule donc pas encore le
retour sur investissement ni une causalité marketing.

Les GET `/marketing/cmo/couts` et `/api/marketing/cmo/couts` n'écrivent rien et ne
mettent rien en cache. Deux pages distinctes de dix éléments montrent les parts
et les pièces AP disponibles, avec compte exact des lignes restantes. Les totaux
portent sur toutes les parts valides du préfixe, pas seulement la page affichée.
Le curseur suivant porte les snapshots attendus : un changement refuse la page
ancienne, sans associer les lignes de deux versions.

Une lecture ou affectation appelle au plus deux fois le lecteur SDK M7, pour
capture puis recontrôle ; un retrait n'appelle pas M7. Les deux registres M5 sont
capturés puis relus avant retour ou effet. Aucun fanout réseau, boucle de pages
SDK, modèle ou autre département n'est invoqué dans ce parcours.

Avant décodage, les deux registres M5 sont limités chacun à 10 000 lignes,
8 Mio UTF-8 et 64 Kio par ligne ; la chaîne native de toutes les lignes capturées
est vérifiée. Le registre local M7 est limité à 1 000 lignes et 1 Mio, avec
recalcul de l'empreinte des campagnes et consentements existants. Sa décision
historique de plafond reste non scellée et n'est pas une preuve de dépense.
Le décodage refuse les doublons de clés, une profondeur supérieure à seize,
plus de 2 048 nœuds par ligne ou 500 000 par registre. Une corruption même hors
campagne ou période recherchée ferme la lecture sans montant. La projection
JSON reste sous 32 Kio, avec troncature comptée ; le HTML refuse au-delà de 64 Kio.

La chaîne M5 démontre la cohérence des octets avec ses empreintes persistées ;
elle ne prouve ni l'authenticité des factures externes ni une protection contre
un opérateur capable de réécrire tout le registre et recalculer ses hashes.

Les commandes ont une clé de reçu canonique. Une même clé et les mêmes arguments
rejouent le reçu **historique** après contrôle du propriétaire vivant ; le GET
courant reste recalculé. Une clé réutilisée avec une autre version, part, période
ou source refuse. Une source périmée ou un échec annule demande, reçu, journal et
maillon de cette commande. Un ancien reçu ne devient pas une validation nouvelle
des sources actuelles.

Cette phase fonctionne seulement sur SQLite avec la transaction réelle
`BEGIN IMMEDIATE`. Les mutations et la projection nouvelle refusent PostgreSQL ;
les autres capacités financières existantes conservent leur contrat. Aucun
verrouillage PostgreSQL, navigateur réel, fournisseur, VPS ou isolation SaaS
n'est qualifié. Les tests ciblés utilisent une vraie base SQLite temporaire, de
vraies identités et décisions SDK, et des pièces fictives. Une campagne complète
indépendante ROOT reste nécessaire avant une certification plus large.

Sources : [règles M5](../../../departments/m05-financecore/src/m5_financecore/couts_marketing.py),
[adaptateur privé](../../../src/opsys/console/couts_marketing.py),
[tests HTTP](../../../tests/test_console_couts_marketing.py),
[tests purs](../../../departments/m05-financecore/tests/test_couts_marketing.py)
et [catalogue privé](../../../tests/test_sdk_couts_marketing.py).
