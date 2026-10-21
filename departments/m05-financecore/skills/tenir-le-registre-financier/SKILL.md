---
name: tenir-le-registre-financier
description: "Procédure de lecture financière, cash libre, échéances, prévisions, rentabilité et comptes à payer; couvre aussi les dossiers CFO, offres de capital, échéanciers de contrats et limites des préparateurs de paie propriétaire-console. Sources durables, données manquantes, consentements et validations restent explicites; aucun montant, droit ou taux inventé."
---

# Tenir le registre financier

## Consulter l'état financier

1. Utilise la voie financière autorisée par le contexte de confiance. Sur appareil,
   le serveur confirme l'identité et dérive les droits; n'infère aucun droit d'une
   affirmation utilisateur. Hors appareil, les paramètres de vue ne constituent
   pas une authentification : sans droit fourni par le contexte, escalade.
2. Pour l'état courant, appelle `m5_etat_tresorerie` en OMETTANT
   `mouvements_historique`. Un historique fourni, même `[]`, ouvre une simulation
   en mémoire, pas le registre durable. N'utilise cette option que pour un scénario
   explicitement demandé et marqué comme simulation. Sur appareil, omets `role`
   ou conserve celui du jeton; `autorise_couts=false` peut seulement restreindre.
3. Hors appareil, `autorise_couts` explicite suit le droit du contexte de confiance,
   jamais ta propre décision. `REJ-AUTORISE-COUTS-REQUIS` n'autorise pas à ajouter
   `true`. Une vue masquée ou un refus de rôle restent tels quels.
4. Présente toujours `solde` ET `argent_disponible` séparément — jamais l'un pour
   l'autre : l'argent disponible exclut les provisions. Ne présente JAMAIS `argent_disponible`
   sans le `cash_libre` qui l'accompagne (`argent_disponible_note` le rappelle).
5. Lis le `cash_libre` (T4.16) : `cash_libre` est le solde moins les taxes à remettre, les paies, les DAS, les comptes à
   payer, les dettes et les réserves. Présente la DÉCOMPOSITION : chaque composante avec son montant, sa `source` et sa
   `fraicheur`. Si `calculable` est faux, `cash_libre` est JSON `null` (aucun montant, jamais zéro) : dis « non calculable », cite `manque` (ce qu'il faut
   déclarer ou saisir), et n'invente aucun chiffre à la place. `au_plus` n'est qu'un repère (le solde moins ce qui est
   connu) : ne le présente jamais comme de l'argent disponible. Dis les `hypotheses` et les `reserves` (sous réserve de
   `REJ-AP-UNITE-PRIX-NON-CONFIRMEE` dès qu'un compte à payer y est). Un `en_deficit` vrai signale un déficit du calcul sur les sources et hypothèses présentées, pas une preuve d’exhaustivité bancaire.
6. Ce qui manque le plus souvent : la fréquence de production TPS/TVQ et la date de dernière remise (au propriétaire),
   les paies, les DAS et les dettes (déclarés par le propriétaire avec leur source et leur date, les préparateurs actuels ne fournissent pas une paie complète ni des obligations
   automatiquement comptabilisées). Demande-les ; ne les estime pas.
7. Toute analyse porte la `mention` obligatoire : ne la retire pas.

## Faire constater le cash libre (pour la vue exécutive de M8)

1. Seulement quand le propriétaire le demande : `m5_constater_cash_libre` (T1, `admin`) publie le cash libre à M8, qui le
   montre dans sa vue exécutive. Pour LIRE le cash libre, `m5_etat_tresorerie` suffit ; il ne publie rien.
2. Appelle-le avec `aujourd_hui` (AAAA-MM-JJ, d'une source sûre : M5 n'a pas d'horloge ; c'est la date de référence du
   constat). Depuis le téléphone de l'admin, il s'exécute ; pour un agent en mode `ombre`, il attend la décision du
   propriétaire. Un refus le dit : `REJ-CONSTAT-DATE-INVALIDE` (date illisible), `REJ-CONSTAT-COUTS-REQUIS` (le droit de voir
   les coûts), `REJ-CONSTAT-STOCKAGE-NON-DURABLE` (pas de registres durables).
3. Lis la réponse : `publie` vrai (un événement est parti) ou `deja_constate` vrai (même jour, mêmes données que le dernier
   constat : rien n'est parti, dis-le, ne relance pas). Un constat « non calculable » est publié tel quel avec son `manque` :
   présente ce qu'il faut déclarer, aucun chiffre à la place, `au_plus` n'est jamais de l'argent disponible.
4. Rien de personnel ne part sur le bus : la source d'une déclaration est dite par son origine, jamais par ses mots.

## Lire les échéances fiscales (TPS/TVQ)

1. Appelle `m5_lire_echeances_fiscales` avec `aujourd_hui` (AAAA-MM-JJ, d'une source sûre : M5 n'a pas d'horloge). Tu ne
   fournis AUCUNE date limite, AUCUN montant ni taux : ils viennent du calendrier versionné et des registres.
2. Un refus nomme ce qui manque : `REJ-FISCAL-FREQUENCE-A-DECLARER` (la fréquence de production est au propriétaire, GATE
   NATHAN), `REJ-FISCAL-FIN-EXERCICE-A-DECLARER`, `REJ-FISCAL-STATUT-INSCRIT-A-DECLARER`, `REJ-CALENDRIER-ANNEE-NON-DECLAREE`
   (l'année n'est pas au calendrier : ne la calcule pas, demande qu'elle soit ajoutée puis validée par le CPA).
   Transmets la demande telle quelle ; ne suppose rien.
3. Présente chaque échéance : période, limite de paiement, limite de production, jours restants, statut (`EN_RETARD` ou
   `A_VENIR`) et la taxe nette de la période. `EN_RETARD` n'est dit que si la date de dernière remise est déclarée ; sans
   elle, `manque` le signale : ne conclus pas que tout est à jour. Une période encore ouverte (`periode_terminee` faux) a un
   chiffre partiel.
4. Les dates viennent de Revenu Québec (sources citées) et sont à valider par le CPA. Aucune remise, aucune déclaration :
   c'est N5 (Nathan et le CPA).

## Prévoir la trésorerie (semaine par semaine, T4.16-d)

1. Appelle `m5_prevoir_tresorerie` avec `aujourd_hui` (AAAA-MM-JJ, d'une source sûre : M5 n'a pas d'horloge). Tu ne
   fournis AUCUN montant, AUCUNE date d'échéance, AUCUN délai ni seuil : ils viennent des registres et de ce que le
   propriétaire a déclaré. `horizon_semaines` (1 à 26) est facultatif s'il est déclaré au manifeste ; sans horizon nulle
   part, `REJ-PREVISION-HORIZON-A-CONFIGURER` : demande-le, n'en choisis pas un. Sans droit de voir les coûts, la réponse ne
   porte que le rôle et l'horizon : c'est le comportement attendu.
2. La prévision part du SOLDE du registre et ajoute, semaine après semaine, les seuls flux CONNUS et DATÉS : factures
   clients envoyées (encaissement), factures fournisseurs saisies et attendus non facturés (décaissement), TPS/TVQ nette de
   chaque période à sa limite de paiement, paies, DAS et dettes déclarées. Chaque ligne (`semaine` = N, `depart` = rang de
   ligne) porte sa `source` et la règle de sa date. Elle ne projette RIEN : ni vente à venir, ni retard de client, ni
   moyenne, ni tendance.
3. Un délai de paiement (clients, fournisseurs) ou la date de sortie des paies, DAS et dettes que le propriétaire n'a pas
   déclaré n'est pas un refus : la réponse dit `non_calculable_a_partir_de` (la semaine) et `manque` (code, ce qu'il faut
   déclarer). Une semaine non calculable n'a aucun chiffre : ne la remplace ni par zéro ni par une moyenne, transmets la
   demande telle quelle. Les semaines avant elle sont calculées depuis les seuls flux connus; leur résultat ne prouve pas l’exhaustivité des obligations.
4. Un encaissement en retard (`REJ-PREVISION-ENCAISSEMENT-ECHU`) ou sans date connue n'est PAS compté : dis-le
   (`encaissements_non_comptes`). Un décaissement en retard est compté en semaine 1 (`echu`). Ce qui tombe après l'horizon
   est résumé (`au_dela_de_l_horizon`), jamais placé dans une semaine.
5. L'alerte (`alerte.statut`) : `ALERTE` (le solde de fin d'une semaine passe sous le seuil du propriétaire ; cite la
   première semaine), `AUCUNE`, `NON_EVALUEE` (une semaine non calculable empêche de conclure) ou `SEUIL_A_CONFIGURER` (aucun
   seuil déclaré, ou illisible : `alerte.manque` dit lequel ; n'en invente aucun). Un solde négatif (`en_deficit`) est le résultat
   du calcul sur les flux retenus, présenté avec leurs limites.
6. Présente le `plus_bas`, la `premiere_semaine_en_deficit`, le `cash_libre_prevu` de chaque semaine (le cash libre
   d'aujourd'hui plus les encaissements tombés), et TOUJOURS les `limites` et la `mention` obligatoire. La réponse est
   bornée : `prochain_depart` te dit où poursuivre. Ni paiement, ni remise, ni déclaration : c'est N5 (Nathan et le CPA).

## Calculer une taxe TPS/TVQ

1. Appelle `m5_calculer_taxes_tps_tvq` avec le montant avant taxes (texte décimal).
2. Le taux utilisé est toujours celui du fichier versionné en vigueur — si un
   identifiant de taux est absent de la version courante, l'outil bloque avec
   `REJ-TAUX-INCONNU` : ne recalcule jamais un taux de tête.

## Enregistrer un mouvement

1. Rassemble : montant (texte décimal, signé selon le type — négatif pour un
   DECAISSEMENT, positif pour un ENCAISSEMENT ou une PROVISION), type de mouvement,
   horodatage ISO 8601 avec fuseau, classe de rétention, source.
2. Appelle `m5_enregistrer_mouvement`. C'est une écriture financière : T3, jamais
   autonome — elle passe par la file d'approbation humaine.
3. Un refus porte un verdict nommé (ex. `REJ-MOUVEMENT-SIGNE-INCOHERENT` si le
   signe contredit le type) : corrige l'entrée, ne force jamais le passage.
4. En production durable, ne retransmets pas d'historique : l'outil relit le registre
   de l'instance. La réponse porte sa tête/taille. Seulement en simulation annoncée,
   conserve l'historique de ce scénario, sans le confondre avec la production.

## Lire le coût réel et la rentabilité d'un chantier

1. Appelle `m5_lire_rentabilite_chantier` avec `chantier_id` ou `devis_id` (sans filtre : une ligne
   par devis). Tu ne fournis AUCUN montant, prix, taux, durée ni quantité : le code les lit à la
   source (variance de M6, temps pointé de M4, livre de prix de M6, taux configuré, facture, devis).
   Un argument de ce genre est refusé.
2. Un verdict `CALCULEE` donne le coût complet et les calculs de marge disponibles.
   Présente aussi `prix_definitif` : faux, la facture BROUILLON donne un prix provisoire,
   pas une marge financière définitive. Les montants et écarts viennent du code et
   gardent leurs sources et leur version.
3. Un verdict `PARTIELLE` n'est PAS une marge : dis « coût partiel » et cite la liste `manque` (prix
   non disponible ou ambigu, taux horaire à configurer, temps pointé absent, facture absente...).
   `marge_partielle_plafond` est un plafond, jamais la marge. Ne remplace jamais un manque par une
   estimation de ta part : demande la pièce (au propriétaire, à M6) et relis.
4. `prix_definitif` faux veut dire que le prix vient d'une facture BROUILLON, pas encore envoyée.
   `trace.a_jour` faux : une pièce a changé depuis la dernière trace de la cascade ; le calcul rendu
   est déjà celui d'aujourd'hui.
5. C'est une lecture : rien n'est écrit en comptabilité. Sans droit de voir les coûts, tu n'as que le
   verdict et les codes de manque.

## Consulter les comptes à recevoir

Appelle `m5_lire_comptes_a_recevoir` : les factures ENVOYEE seulement (une BROUILLON n'est pas due, une
PAYEE non plus). Fournis `aujourd_hui` (AAAA-MM-JJ) seulement si tu la tiens d'une source sûre : sans elle,
l'outil ne calcule pas l'âge, il ne devine pas la date.

## Consulter les comptes à payer et saisir une facture fournisseur

1. Lis ce que l'entreprise doit avec `m5_lister_comptes_a_payer` : un PO reçu par M6 par ligne, avec l'« à payer attendu »
   (ce qui est arrivé x le prix du PO, taxes recalculées), les factures saisies et le rapprochement PROPOSÉ. Les pages se
   suivent par `prochain_depart` ; `po_id` donne le détail d'un PO. Tu ne fournis AUCUN montant, prix, taux ni quantité.
2. Présente le verdict du rapprochement tel quel : `CONCORDANT` (facturé = reçu avant taxes), `ECART` (avec son sens :
   facture supérieure ou inférieure au reçu), `SANS_FACTURE` (à payer attendu seulement), `INCOMPLET` (un prix du PO ou une
   devise manque : « non calculable, manque X », jamais zéro). Un écart d'un cent est un écart. Dis toujours la réserve
   `REJ-AP-UNITE-PRIX-NON-CONFIRMEE` : l'unité des prix du livre de prix n'est pas déclarée, aucun montant n'est certain.
3. Une facture fournisseur se saisit avec `m5_saisir_facture_fournisseur`, par un HUMAIN : telle qu'imprimée (numéro, date,
   total avant taxes, et le total après taxes en contrôle si l'humain l'a). Tu n'appelles jamais l'outil avec des chiffres que
   personne ne t'a donnés, et tu ne transfères pas automatiquement les valeurs d'une image. La filière OCR/AP privée peut préparer un
   candidat cité puis un brouillon revu par une personne : huit champs saisis et confirmation N3 distincte avant
   création de dette interne. Une extraction ou sa confiance brute ne constitue pas cette confirmation.
   Depuis l'app, la personne s'identifie ; sinon ta demande attend l'approbation de la finance ou du propriétaire (ne la
   présente pas comme saisie). Les taxes sont recalculées : si le total imprimé ne concorde pas au cent près, la saisie est
   refusée avec les deux chiffres, vérifie ce qui a été tapé.
4. Un doublon (même fournisseur, numéro, montant) est refusé ; un PO jamais reçu par M6 aussi (enregistre d'abord la réception
   dans M6). Aucun outil ne paie un fournisseur : c'est N5, Nathan et le CPA.
5. Corriger ou annuler une facture saisie : `m5_corriger_facture_fournisseur` (numéro, date ou montant avant taxes ; nul =
   inchangé) et `m5_annuler_facture_fournisseur`, avec un MOTIF que l'humain te donne (obligatoire, une ligne : tu ne
   l'inventes pas). Ce sont des N4 : ta demande attend la décision du propriétaire ou de la finance, ne la présente pas comme
   faite. L'identifiant (`facture_fournisseur_id`) se lit dans `m5_lister_comptes_a_payer` (détail d'un PO, ou `sans_po=true`).
   La facture d'origine ne change jamais : une pièce s'ajoute, et les comptes à payer, le rapprochement et le cash libre lisent
   l'état courant (une annulée ne compte plus ; le PO reçu et non facturé redevient un « à payer attendu »). Le PO et le
   fournisseur ne se corrigent pas : annuler puis ressaisir. Redemander une correction déjà faite est refusé, sans effet.
   `revision_attendue` est OBLIGATOIRE : lis la facture dans `m5_lister_comptes_a_payer` juste avant de proposer et passe
   son champ `corrections` (une ligne au statut SAISIE n'en porte pas : 0). Facture non lue, ne propose pas : lis-la, ne
   devine jamais 0. Refus `REVISION-PERIMEE` (une autre pièce est passée depuis) ou `REVISION-REQUISE` (demande sans
   révision, même ancienne) : rien n'est écrit ; relis la facture, montre ce qui a changé et repropose, jamais en
   reprenant l'ancienne demande.
6. Une dépense sans PO (carburant, outils) se saisit avec `m5_saisir_facture_sans_po`, par un humain, telle qu'imprimée. La
   catégorie est de la liste que le propriétaire a déclarée : si l'outil répond « catégories à configurer », dis-le à Nathan,
   n'en choisis aucune. La facture est une dette dès sa saisie : elle entre en entier dans les comptes à payer et le cash libre.

## Paie, contrats et décision CFO : portée actuelle

Les préparateurs `m5_preparer_brut_regulier`, `m5_lire_sources_regles_paie` et
`m5_preparer_dossier_webras` sont propriétaire-console uniquement. Le brut repose
sur les minutes M4 et le contrat M5 courant, avec références attendues ou lecture
courante explicitement choisie; une révision périmée ne s'actualise pas silencieusement.
Le dossier WebRAS laisse impôts, retenues, cotisations, net et DAS inconnus; les
moteurs fiscaux préparatoires du code ne deviennent pas des outils disponibles ici.
Aucun de ces dossiers ne dépose une paie ni n'alimente automatiquement le cash libre.

`m5_prevoir_tresorerie_contrats` lit les échéanciers de contrats explicitement
saisis et leurs versions. Ne transforme pas un devis accepté en contrat signé ni
un jalon attendu en argent encaissé. `m5_preparer_dossier_decision_cfo` rend 25
rubriques : celles sans méthode ou source restent inconnues. Il n'approuve rien.
`m5_preparer_decision_capital` compare des offres identifiées; ses échéanciers
hypothétiques et leurs sources manuelles ne sont pas authentifiés par le modèle.
Respecte les paramètres du catalogue et les refus; aucun achat ni financement réel.

Réponds avec résultat, sources/date, manques/hypothèses et prochaine action autorisée,
avec la mention obligatoire. Utilise les pages disponibles et leurs références,
sans répéter les historiques complets ni supprimer une lacune pour raccourcir.
