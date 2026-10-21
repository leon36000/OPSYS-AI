# M5-financecore

FinanceCore — comptabilite, fiscalite (mention CPA), paie, CFO IA

Statut au 1er octobre 2026 : **PARTIEL — consolidation requise**. Les opérations internes et des
rapports préparatoires sont raccordés, mais le périmètre CFO complet n'est pas livré. Le comptage
historique au commit `2e56c0d` (17 outils) et le constat initial DEP-001 ne décrivent plus l'arbre
courant : DEP-001 est corrigé localement, avec régression en mémoire et sur stockage durable
(`test_facturation.py`, `test_registre_durable.py`). M5 expose maintenant 26 outils; M5.4.a ajoute 3 outils (deux N4, un T0), M5.4.b ajoute un outil T0 de brouillon brut régulier, M5.4.c expose seulement l'état des références de paie et M5.4.d prépare un export manuel WebRAS réservé au propriétaire-console. Le brut ne calcule ni retenues ni obligations employeur et n'alimente pas le cash libre; le dossier WebRAS ne calcule aucun montant fiscal ni net et ne qualifie pas le brut comme revenu imposable.
`opsys-metier verifier` confirme les nombres de départements, outils et portées d'appareil dans sa preuve de cette tranche. Voir le [périmètre cible](../../docs/produit/PERIMETRE-MODULES.md), la
[recherche actuelle](../../docs/research/R16-2026-09-30/recherche-m5.md) et le
[bilan intégré](../../docs/programme/BILAN-RESTRUCTURATION-2026-09-30.md).

Historique du premier lot (mode `ombre`), sur le modèle de M3. Les 7
stories du PRD (`docs/bmad/02-PRD-PM.md`) sont livrées et vertes : contrats
gelés + validation d'entrée (S001), registre append-only hash-chaîné (S002),
solde/argent disponible (S003), taux fiscaux versionnés (S004), registre
d'approbation F0-F7 (S005), état financier filtré par rôle (S006), conformité
statique transversale (S007). Couche département ajoutée : `department.yaml`,
`SOUL.md`, 2 skills (`tenir-le-registre-financier`,
`gerer-les-approbations-f0-f7`), `src/m5_financecore/outils.py` (5 outils
agent au premier lot, 17 actuellement), `tests/test_outils_agent.py`.

Quatre bugs corrigés (test rouge → vert) lors de cette passe :
- `soldes.py` n'imposait aucun signe : un DECAISSEMENT positif gonflait le
  solde au lieu de le diminuer. Le signe est désormais imposé à l'écriture
  (`validation.py::valider_mouvement`, `REJ-MOUVEMENT-SIGNE-INCOHERENT`).
- `etat_financier.construire_etat_financier` exposait le solde par défaut
  (`autorise_couts=True`) : un rôle non autorisé (ex. « employe ») le voyait
  sans le demander. Par défaut désormais : refus (fail-closed).
- `approbation.py` acceptait n'importe quelle chaîne comme preuve MFA/CPA
  F6/F7. Une preuve doit maintenant être une structure JSON vérifiable
  (`methode`, `horodatage` ISO 8601 avec fuseau, `identifiant_approbateur`) —
  aucun fournisseur MFA n'est présumé ni codé en dur.
- Les taux fiscaux versionnés (`contracts/taux_fiscaux.v1.yaml`) n'étaient
  utilisés par aucun calcul : `taxes.py` (nouveau) calcule TPS/TVQ en Decimal
  en les lisant via `taux_fiscaux.rechercher_taux`, jamais codés en dur.

PLAN T1.3-c (branchement sur les approbations du socle) : `m5_envoyer_facture` (N4)
et `m5_enregistrer_paiement_facture` (N5, montant comparé par le code) remplacent la
confiance à la forme d'un maillon F4/d'un `approbateur` texte libre — les deux
outils ne s'exécutent que derrière une décision signée de `opsys.approbations`
(`department.yaml/approbations.n3`/`n4` ; N5 fixé à `nathan_owner` par le socle).
`m5_creer_demande_approbation`/`m5_decider_approbation` sont retirés des outils
agent ; `approbation.py` (registre F0-F7) reste dans le dépôt comme bibliothèque
pure et testée, mais n'a plus aucun appelant — voir son docstring et le rapport de
PLAN T1.3-c. `outils.attentes()` alimente désormais la file du propriétaire
(`opsys.approbations.file_proprietaire`) : attentes de facturation, factures
BROUILLON prêtes à envoyer, et le signal de variance critique de M6
(`m6.variance_chantier`, `variance_recus.py`) affiché à côté, sans jamais bloquer
l'envoi.

PLAN T1.4-k2 (identité authentifiée) : pour un appel d'appareil (app mobile), `m5_etat_tresorerie`
ne croit plus `role` ni `autorise_couts`. La vue vient du rôle de la personne authentifiée,
confirmée en base à chaque appel (`outils._acteur_appareil`, même règle que M4) ; la décision est
dans `acces.py` (module pur). Règle écrite : `admin` voit solde, argent disponible et taux (définition
§9.5) ; `employee` (§9.2) et `seller` (§9.4) ne les voient pas et n'ont d'ailleurs aucune portée sur l'outil
(`roles_appareil` = `admin`). `autorise_couts` absent vaut le droit du rôle ; `false` restreint (honoré,
comme `role` dans `m3_lire_devis`) ; `true` sans le droit est refusé (`REJ-ROLE-ELARGI`) ; un `role`
qui contredit le jeton est refusé (`REJ-IDENTITE-FOURNIE-DIFFERENTE`) ; identité inconnue, désactivée
ou dont le rôle a été retiré : `REJ-IDENTITE-APPAREIL-INVALIDE`. Tout refus vient avant la lecture du
registre et sans aucune écriture. `m5_lister_attentes_facturation` exige la même identité.
Sans identité d'appareil (agent, console) : comportement d'avant, `autorise_couts` obligatoire et
explicite (son absence est maintenant le verdict `REJ-AUTORISE-COUTS-REQUIS`, autrefois un refus de
schéma). Détail, cas et limites : `docs/architecture/ROLES.md`, section « La vue financière de M5 ».

PLAN T1.5-d (coût réel et rentabilité, DEFINITION-PRODUIT §6 « travaux terminés ») : la cascade calcule le
coût réel d'un chantier et sa rentabilité (`cout_reel.py`, module pur ; `outils._essayer_cout_reel`, appelé
par les consommateurs de `m3.devis_accepte`, `m4.travaux_termines` et `m6.variance_chantier`, quel que soit
l'ordre d'arrivée). Les sources sont lues, jamais fournies : les matériaux réellement utilisés (`lignes` du
signal de variance de M6, gardées par `variance_recus.py`), multipliés par le prix du livre de prix de M6 (lu
en lecture seule par `outils._livre_de_prix_m6` ; prix absent : ligne « prix non disponible », deux
fournisseurs à prix différents : « prix ambigu ») ; la main-d'oeuvre (durée pointée du WCT, gardée par
`wct_recus.py`) multipliée par `department.yaml/configuration.taux_horaire_main_d_oeuvre`, absent du manifeste
livré (verdict « taux horaire à configurer »). Un coût partiel est dit partiel, avec la liste `manque`. La
rentabilité est le prix facturé avant taxes (facture BROUILLON, ENVOYEE ou PAYEE) moins le coût réel, contre la
marge prévue du devis (`cout_total` et `prix_total` de `m3.devis_accepte`). Tout est en Decimal, `ROUND_HALF_UP`.
L'état est tracé dans le registre dérivé `rentabilite`, une fois par version des entrées : ni le grand livre
ni les factures ne sont touchés. Les comptes à recevoir sont une vue des factures ENVOYEE
(`facturation.comptes_a_recevoir`). L'admin lit le tout par `m5_lire_rentabilite_chantier` et
`m5_lire_comptes_a_recevoir` (portée `admin` seulement, même règle d'accès que `m5_etat_tresorerie`).

Garde des tarifs historiques (audit du 21 octobre 2026) : un coût matériel complet exige une `unite`
explicite du tarif identique à celle de la consommation (espaces externes ignorés, aucune conversion
implicite). Les entrées M6 historiques ne portent pas cette unité : elles donnent désormais un coût
partiel, `REJ-COUT-PRIX-NON-DISPONIBLE`, avec demande de confirmation ; la facture brouillon reste créée.
Le calcul retient seulement les `date_effet` civiles ISO au plus tard à la date civile du WCT dans sa
zone déclarée. Le dernier maillon écrit par fournisseur parmi ces tarifs éligibles conserve la priorité
M6 ; une date manquante/illisible bloque, sans repli sur une ancienne révision. Un horodatage WCT sans
zone ne permet pas de conclure. Un tarif futur ne modifie ni le coût ni la version d'un chantier passé.
La valorisation reste celle du livre M6 ; elle ne prouve pas le coût d'acquisition du lot consommé.
L’outil `m6_enregistrer_prix` accepte désormais cette unité explicite optionnelle pour ses nouveaux tarifs ;
son absence reste inconnue et aucune entrée historique n’est réécrite.

PLAN T4.15 (comptes à payer, M5.2 « comptes à payer » et M6.16 « pont finance », `comptes_a_payer.py`) : M5 sait maintenant
ce que l'entreprise doit à ses fournisseurs. Un registre DÉDIÉ, `comptes_a_payer`, garde deux choses. (1) Chaque réception
que M6 publie (`m6.reception_enregistree`, consommée par `outils._recevoir_reception_enregistree`) : quantité reçue x prix
unitaire du PO, arrondie au cent par ligne, donne l'« à payer ATTENDU » du PO ; une réception partielle donne un attendu
partiel, les livraisons d'un même PO se cumulent, une redélivrance ne double rien (idempotent par `evenement_id`). (2) Chaque
facture fournisseur SAISIE (`m5_saisir_facture_fournisseur`, T1, N3, `admin`) : tapée par un HUMAIN (identité de jeton
d'appareil confirmée en base, ou demande approuvée par `finance` ou le propriétaire ; un agent seul est refusé,
`REJ-AP-HUMAIN-REQUIS`), contre un PO déjà reçu et au fournisseur de ce PO. L'OCR est fermé : la saisie manuelle est le repli.

Montants : `Decimal`, en texte dans les échanges, jamais un float. Les taxes TPS/TVQ sont RECALCULÉES depuis le montant avant
taxes avec les taux versionnés (`contracts/taux_fiscaux.v1.yaml`, version citée dans chaque facture et dans la liste) ; le total
imprimé sur la facture, s'il est fourni, doit concorder au cent près. Arrondi : `ROUND_HALF_UP`, la règle déjà en place
(`taxes.py` : ARC RC4022 « Arrondir les montants fractionnaires », Revenu Québec « Calcul des taxes » ; même mode que
`facturation.py`, `cout_reel.py` et M3) ; sur 300.00 $, la TVQ de 29.925 $ devient 29.93 $ (le mode par défaut de `decimal`
donnerait 29.92 $). Le produit quantité x prix est calculé en précision étendue avant l'arrondi. Aucune tolérance n'est inventée :
un écart d'un cent est un écart. Un doublon (même fournisseur, même numéro, espaces et casse ignorés, même montant) est refusé ;
même fournisseur et même numéro avec un autre montant passe avec l'avertissement `REJ-AP-FACTURE-NUMERO-REPETE`.

Le rapprochement PO, réception et facture est PROPOSÉ avec ses écarts (`CONCORDANT`, `ECART` et son sens, `SANS_FACTURE`,
`INCOMPLET`), recalculé à chaque lecture, jamais stocké : il n'existe aucun état « rapproché » ni « approuvé », donc rien qui
l'applique seul. `m5_lister_comptes_a_payer` (T0, portée `admin`, même règle d'accès que `m5_etat_tresorerie`) le rend PAR PO,
par pages sous la limite de sortie de `Capacites` (6 000 caractères, mesurés : `depart`, `prochain_depart`, `totaux` sur TOUS les
PO). Une pièce absente (prix du PO, devise autre que CAD) rend l'attendu « non calculable » avec son manque, jamais zéro ; le
total `a_payer_apres_taxes` est alors nul et `a_payer_connu_apres_taxes` n'est qu'un plancher.

AUCUN DÉCAISSEMENT. Payer un fournisseur est de l'argent réel : N5, Nathan ET le CPA (ADR-0009 §5). Rien, dans les comptes à payer,
n'écrit au registre des mouvements ni aux factures clients : `conformite.verifier_aucun_decaissement` (garde AST : aucun import de
`registre.py`, aucun `enregistrer_mouvement`, aucun type de mouvement) le prouve sur le vrai paquet et sur des fichiers piégés ;
un test sur base réelle montre le registre des mouvements inchangé (même tête, même taille) après tout le parcours. Les seuls
outils T3 de M5 sont les deux d'avant.

Limites connues : (1) l'unité des prix du livre de prix de M6 n'est pas déclarée (GATE NATHAN) : M5 ne convertit rien, suppose un
prix par unité de la quantité reçue, le DIT (`hypotheses` de la liste) et porte la réserve `REJ-AP-UNITE-PRIX-NON-CONFIRMEE` sur
tout attendu et tout rapprochement, même concordant ; elle ne se retire que par une décision de Nathan et un changement de code ;
(2) l'attendu vient du prix du PO ; l'écart avec le prix de réception (`ecart_prix_unitaire`, `ecart_prix_critique`) est gardé
pour l'audit sans le changer ; (3) les taxes de l'attendu sont calculées une fois sur le cumul du PO, celles d'une facture à sa
saisie : un cent de différence entre les deux, dû à l'arrondi de chaque facture, n'est pas un écart (le verdict se juge avant
taxes) ; (4) ni correction ni annulation d'une facture saisie, ni facture sans PO reçu (levé par T4.15-c, ci-dessous) ; (5) rien n'est payé, donc rien n'est
retranché du « à payer » : c'est dû tant qu'un paiement N5 n'est pas enregistré (à construire) ; (6) le solde et l'argent
disponible restent ceux d'avant (CA-M5-05, CA-M5-06) ; c'est le cash libre réel (T4.16, plus bas) qui retranche les comptes à
payer.

PLAN T4.16 (cash libre réel et calendrier fiscal vivant, M5.5, M5.7, M5.14, `cash_libre.py`, `calendrier_fiscal.py`) :
« solde bancaire ≠ argent disponible ». `m5_etat_tresorerie` garde ses clés d'avant (`solde`, `argent_disponible`, `etat_id` :
le contrat gelé de l'état financier n'a pas bougé) et y AJOUTE `cash_libre`, `argent_disponible_note` et `mention`.
`argent_disponible` (solde moins les réserves) n'est plus jamais affiché sans le cash libre ni sans sa note ; un rôle sans droit
de voir les coûts ne voit ni l'un ni l'autre.

Cash libre = solde du registre - TPS/TVQ à remettre - paies - DAS - comptes à payer - dettes - réserves critiques. Chaque
composante porte sa SOURCE (le registre lu, sa taille, la tête de sa chaîne, ou la déclaration du propriétaire) et sa FRAÎCHEUR
(l'horodatage de la pièce la plus récente). Une composante inconnue donne « non calculable, manque X », JAMAIS zéro : le cash
libre est alors nul, la réponse nomme ce qui manque et donne un `au_plus` (le solde moins ce qui est connu ; un repère, pas de
l'argent disponible). Sans aucun mouvement au registre, le solde lui-même est inconnu. D'où vient chaque composante : le solde et
les réserves, du registre des mouvements (les mouvements `PROVISION`) ; les taxes, de la taxe des factures clients envoyées
(`ENVOYEE`, `PAYEE`) moins les crédits de taxes sur intrants des factures fournisseur SAISIES (T4.15), depuis la dernière remise ;
les comptes à payer, du total de T4.15 ; les paies, DAS et dettes restent des obligations réelles déclarées manuellement
avec leur source et leur date dans `department.yaml` (`configuration.obligations_declarees`), sinon elles sont « à déclarer ».
M5.4.a conserve le taux individuel et M5.4.b prépare un brut régulier, sans créer de paie ni d'obligation déclarée. Un
« 0.00 » déclaré est un zéro connu. Un déficit est rendu tel quel. Arrondi : `ROUND_HALF_UP`, une fois, au résultat.

Calendrier fiscal : `contracts/calendrier_fiscal.v1.yaml`, sur le patron de `taux_fiscaux.v1.yaml` (année, sources officielles
avec adresse et date de consultation, version). Les dates sont TRANSCRITES des calendriers de Revenu Québec (jours fériés et
Fêtes compris), jamais calculées ; le chargeur en vérifie la cohérence. Deux années déclarées (2025, 2026) ; `A_VALIDER` par le
CPA. `m5_lire_echeances_fiscales` (T0, `admin`) dit les prochaines échéances TPS/TVQ, les retards et la taxe nette de chaque
période. Une année non déclarée est REFUSÉE (`REJ-CALENDRIER-ANNEE-NON-DECLAREE`). La fréquence de production (mensuelle,
trimestrielle, annuelle), la fin d'exercice, le statut de particulier en affaires et la date de dernière remise sont des
décisions ou des faits du propriétaire (GATE NATHAN, `configuration.fiscal` de `department.yaml`) : absents, le calendrier le dit
et ne suppose rien. Hors du calcul fiscal, faute de source officielle déclarée : acomptes provisionnels, paie, DAS, T4 et RL-1,
CNESST.

`m5_lire_calendrier_obligations` (T0, `admin`) ajoute un calendrier préparatoire pour les paies, DAS et dettes déjà déclarées :
il reprend leur montant/source/date dans `obligations_declarees`, leur échéance explicite dans la configuration de prévision et
les métadonnées d'autorité, période, source, validité déclarée, année et version dans `calendrier_obligations`. Une ligne
incomplète reste visible avec les champs manquants. Une fenêtre de source qui ne couvre pas la période est marquée périmée;
aucun âge maximal n'est inventé. Une échéance passée est à vérifier, jamais considérée comme non payée. Ce n'est pas un moteur
de paie : aucun taux, calcul de retenue, date récurrente, dépôt ou paiement n'est ajouté.

Mention obligatoire (`analyse.py`) : « Analyse préparatoire IA — validation Nathan/CPA/fiscaliste requise avant toute décision
officielle ou action réelle. » (DEFINITION-PRODUIT §7 M5, §13.3) est portée par toute sortie acceptée d'un outil d'analyse
(`m5_etat_tresorerie`, `m5_lire_echeances_fiscales`, `m5_lire_calendrier_obligations`, `m5_prevoir_tresorerie` (T4.16-d), `m5_lire_rentabilite_chantier`, `m5_lister_comptes_a_payer`,
`m5_saisir_facture_fournisseur`, et depuis T4.15-c `m5_saisir_facture_sans_po`, `m5_corriger_facture_fournisseur`,
`m5_annuler_facture_fournisseur`, ainsi que `m5_preparer_brut_regulier`) ; un test ferme le monde (chaque outil est classé)
et lit la mention dans le document produit.

AUCUNE REMISE, AUCUNE DÉCLARATION, AUCUN PAIEMENT. Le calendrier propose des dates ; remettre une taxe est N5 (Nathan ET le
CPA). `conformite.verifier_aucun_decaissement` couvre le nouveau code : en régime strict (aucun mot de mouvement) pour le
calendrier, le cash libre et la mention, en lecture seule pour le code qui ouvre le registre des mouvements pour en tirer le
solde. Les seuls outils T3 de M5 sont les deux d'avant.

Limites connues : (1) les crédits de taxes sur intrants sont supposés récupérables à 100 % (à valider par le CPA) ; TPS et TVQ ne
se compensent pas entre elles et une taxe nette négative n'est jamais de l'argent (prudent) ; (2) aucune constatation de paiement
fournisseur ni de remise : un fournisseur payé ou une taxe remise reste retranché tant que le registre l'ignore
(`taxes_remises_jusqu_au` s'avance à la main, avec le CPA) : le cash libre est alors SOUS-estimé, jamais surestimé ; (3) une
PROVISION posée pour un autre poste (taxes, paies) compte deux fois : aucune catégorie de réserve n'existe encore ; (4) paies, DAS
et dettes sont déclarées à la main dans le manifeste ; le brut préparatoire M5.4.b ne crée aucune obligation et ne remplace pas
cette déclaration ; (5) `aujourd_hui` est fourni
par l'appelant (M5 n'a pas d'horloge, DA-M5-06) ; (6) la fréquence de production et les autres décisions sont absentes du
manifeste livré : tant que Nathan ne les déclare pas, le cash libre est « non calculable » et le calendrier refuse de nommer une
échéance ; (7) le cash libre est l'état d'aujourd'hui, jamais une projection : la prévision des flux connus et datés vient de
T4.16-d (plus bas), mais ni projection statistique, ni scénarios, ni tests de stress (M5.7) ne sont livrés ; les catégories de
réserve (M5.14, stratégie d'épargne) non plus.

PLAN T4.16-d (prévision de trésorerie, M5.7, `prevision.py`) : `m5_prevoir_tresorerie` (T0, lecture, `admin` seulement ; le code refuse
aussi tout autre rôle d'appareil ; mention « Analyse préparatoire IA ») dit, semaine par semaine sur un horizon de 1 à 26 semaines
(7 jours chacune, à partir d'`aujourd_hui`), où irait le solde si seuls les flux CONNUS et DATÉS se produisaient. `prevision.py` est
PUR : aucune entrée-sortie, aucune horloge, `Decimal`, `ROUND_HALF_UP` au cent, une seule fois ; l'adaptateur
(`outils._page_prevision`) lit chaque registre une fois (le même instantané que le cash libre) et lui passe les faits.

Le point de départ est le SOLDE du registre, pas le cash libre : celui-ci a déjà retranché les taxes, les paies, les DAS, les comptes à
payer et les dettes ; en partir et faire sortir ces mêmes obligations les compterait deux fois. Le `cash_libre_prevu` de chaque semaine
est le cash libre d'aujourd'hui plus les encaissements tombés ; quand toutes les obligations sont sorties, solde de fin de semaine moins
réserves = cash libre prévu.

Les flux, chacun avec sa SOURCE et la règle qui date : (a) les factures clients ENVOYÉES (montant après taxes) : encaissement ; (b) les
factures fournisseurs vivantes et l'« à payer attendu » des PO reçus et non facturés (`comptes_a_payer.dettes_datables`, les mêmes dettes
que le cash libre, une à une) : décaissement ; (c) la TPS/TVQ nette de chaque période du calendrier fiscal non remise, à sa limite de
paiement (une période encore ouverte est `partielle` : les factures déjà émises seulement) ; (d) les paies, DAS et dettes DÉCLARÉES, pour le
montant de la composante du cash libre, à la date que le propriétaire a déclarée. Aucune échéance de paiement n'est enregistrée sur les
factures, ni clients ni fournisseurs : la date d'un encaissement ou d'un décaissement est celle de la pièce (envoi d'une facture, date
d'une facture fournisseur, PREMIÈRE réception d'un PO) plus un délai que le propriétaire déclare (`configuration.prevision`, GATE NATHAN,
aucune valeur par défaut).

Ce qui est inconnu ne devient jamais un zéro ni une moyenne, et la prudence dépend du sens (règles ASYMÉTRIQUES) : un décaissement inconnu
(montant illisible, date inconnue, délai non déclaré) rend la prévision « non calculable à partir de la semaine X, manque Y » (X est sa
semaine, la semaine 1 si sa date est inconnue) : les semaines avant X restent exactes, celles de X en avant n'ont aucun chiffre ; un
décaissement échu est compté en semaine 1 (`echu`) ; un encaissement inconnu ou échu (le client est en retard : sa date de paiement est
inconnue) n'est PAS compté et le dit (`encaissements_non_comptes`) ; un flux après l'horizon est agrégé (`au_dela_de_l_horizon`), jamais
placé dans une semaine.

L'alerte est déterministe : le solde de fin d'une semaine calculée passe STRICTEMENT sous le seuil que le propriétaire a fourni
(`configuration.prevision.seuil_alerte` : montant, source, date). Absent : « seuil à configurer » (`SEUIL_A_CONFIGURER`), aucun seuil n'est
supposé ; une semaine non calculable empêche de conclure (`NON_EVALUEE`). Un solde négatif (`en_deficit`) est un fait rendu tel quel, pas
une alerte. AUCUNE projection statistique : ni moyenne, ni tendance, ni saison, ni vente à venir, ni retard de client (R-009 :
l'historique est insuffisant, la projection statistique de M5.7 reste reportée, comme le PRD l'a décidé).

La réponse tient dans les 6 000 caractères du socle (pagination mesurée : `depart` ; `semaine` pour les lignes d'une semaine ; les
`limites` sont retirées avant de refuser, `REJ-PREVISION-REPONSE-TROP-GROSSE`). `prevision_id` est l'empreinte du contenu : la même donnée
donne la même prévision. Sans droit de voir les coûts : le rôle et l'horizon, aucun montant. Rien n'est écrit, payé, remis ni déclaré :
`conformite.verifier_aucun_decaissement` couvre `prevision.py` (régime strict : aucun mot de mouvement) et l'outil (lecture seule : il ouvre
le registre des mouvements pour en tirer le solde). Les seuls outils T3 de M5 restent les deux d'avant.

GATE NATHAN : le seuil d'alerte, l'horizon, les délais de paiement des clients et des fournisseurs et la date de sortie des paies, DAS et
dettes ne sont PAS dans le manifeste livré (bloc commenté dans `department.yaml`) : tant qu'ils ne sont pas déclarés, la prévision dit ce
qui manque et ne suppose rien.

Limites connues : (1) rien de futur n'est connu, donc rien n'est prévu : ni vente, ni nouveau chantier, ni dépense non saisie, ni retard de
client, et aucune statistique ; (2) le point de départ est le solde du REGISTRE des mouvements, pas celui de la banque : un paiement que le
registre ignore n'y est pas ; (3) un encaissement est placé à son échéance déclarée, sans retard ; échu ou sans date, il n'est pas compté ;
un décaissement échu est placé en semaine 1 (aucun paiement n'est constaté) ; (4) le délai est unique par sens (clients, fournisseurs) : les
conditions propres à un client ou à un fournisseur ne sont pas connues ; (5) la taxe d'une période non terminée est celle des factures déjà
émises ; un remboursement de taxes n'est jamais compté ; les dates du calendrier sont à valider par le CPA ; acomptes provisionnels et CNESST
hors calendrier ; (6) le solde d'une semaine est celui de sa fin : un creux au milieu d'une semaine n'est pas vu ; (7) le code critique de
M5 exige des preuves financières et des régressions ciblées avant intégration ; ADR-0012 supprime
l'obligation d'attendre un autre modèle ou fournisseur. La validation humaine des actions financières
réelles reste obligatoire.

PLAN T4.15-c (correction, annulation et factures sans PO, `comptes_a_payer.py`, M5.2) : trois outils de plus, tous refusés à un
agent seul.

La FACTURE D'ORIGINE N'EST JAMAIS MODIFIÉE. `m5_corriger_facture_fournisseur` (numéro, date ou montant avant taxes ; nul =
inchangé ; taxes et total recalculés, total imprimé en contrôle) et `m5_annuler_facture_fournisseur` AJOUTENT une pièce
(`correction_facture_fournisseur`, `annulation_facture_fournisseur`) au registre des comptes à payer, chaînée à la précédente (la
chaîne de hash reste valide) : motif OBLIGATOIRE (une ligne, 300 caractères au plus), personne, rôle, voie, avant et après. L'état
courant d'une facture (`SAISIE`, `CORRIGEE`, `ANNULEE`) est relu de ses pièces (`_etats_factures`, le seul endroit où une facture se
lit) : c'est de lui que partent le facturé, l'« à payer », le rapprochement PROPOSÉ, le doublon et les crédits de taxes du cash
libre. Une annulée n'y compte plus (mais un PO reçu et non facturé redevient un « à payer attendu » : annuler n'efface pas la
dette) ; ressaisir la même facture est permis (son identifiant prend le rang suivant, il reste unique). Le PO, le fournisseur et la
catégorie ne se corrigent pas : annuler puis ressaisir. Un REJEU n'a aucun effet : la même correction (`REJ-AP-CORRECTION-SANS-
CHANGEMENT`), la même annulation (`REJ-AP-FACTURE-DEJA-ANNULEE`), une correction d'une annulée (`REJ-AP-FACTURE-ANNULEE`) sont
refusées sans écrire une pièce de plus ; et un registre où une pièce vise une facture absente ou annulée LÈVE (jamais un chiffre à
demi lu). L'avertissement `REJ-AP-FACTURE-NUMERO-REPETE` se relit sur les factures vivantes : corriger ou annuler l'une des deux le
lève.

Corriger et annuler sont N4 (T2, engagement : écriture finale sur une dépense, ADR-0009 §4) : depuis le téléphone de l'admin comme
pour un agent, l'appel ATTEND dans la file du propriétaire (le socle ne valide au départ que N3 au plus), et l'outil ne s'exécute
qu'après la décision de `finance` ou du propriétaire, aux arguments exacts enregistrés. L'outil exige aussi un HUMAIN par lui-même,
comme la saisie, par deux voies : (1) l'identité de jeton d'appareil confirmée en base, avec, pour un N4, une PERSONNE qui porte
`nathan_owner` ou `finance` (le rôle `admin` du jeton ne dit pas qui est le propriétaire : un gestionnaire `admin` reçoit
`REJ-AP-APPROBATEUR-REQUIS`) ; (2) l'approbateur que le SOCLE dit, `opsys.approbations.approbateur_en_cours` (posé par `decider`
autour de l'outil, revérifié en base : demande `en_cours` de cet outil et de ce département, personne active portant encore ce rôle,
jamais un rôle d'agent ou de client). Cette fonction remplace la lecture de la table des approbations que M5 recopiait de M10 (M1 et
M10 n'y sont pas encore passés). En mode `autonome`, où un N4 s'exécute sans file, c'est l'outil qui refuse l'agent
(`REJ-AP-HUMAIN-REQUIS`).

`m5_saisir_facture_sans_po` (T1, N3, `admin`, comme la saisie d'une facture de PO) : une dépense que M6 n'a pas commandée (carburant,
outils). Même règle d'humain exigé, mêmes taxes recalculées, même doublon refusé (fournisseur, numéro, montant : parmi TOUTES les
factures vivantes, PO ou non ; le fournisseur, tapé à la main, se compare sans égard à la casse ni aux espaces). La catégorie est de
la liste FERMÉE `configuration.categories_depense_sans_po` de `department.yaml` (GATE NATHAN, relue à chaque appel) ; absente ou
vide : « catégories à configurer » (`REJ-AP-CATEGORIES-A-CONFIGURER`), illisible : `REJ-AP-CATEGORIES-INVALIDES`, hors liste :
`REJ-AP-CATEGORIE-INCONNUE` (avec la liste). Le manifeste livré n'en déclare aucune : rien n'est supposé. La facture est une DETTE
ferme dès sa saisie, sans réception ni rapprochement : elle entre EN ENTIER dans les totaux de `m5_lister_comptes_a_payer` (bloc
`sans_po`, par catégorie ; `sans_po=true` les liste une à une avec l'identifiant que la correction demande), dans le résumé et dans
le cash libre (composante « comptes à payer », détail `factures_sans_po`), et ses crédits de taxes dans la TPS/TVQ à remettre.

Aucun DÉCAISSEMENT : la garde AST couvre le nouveau code (les trois outils et leurs assistants d'`outils.py`, le module entier) ; un
test sur base réelle montre le registre des mouvements et celui des factures clients intacts après tout le parcours.

Limites : (1) le cash libre suppose les crédits de taxes sur intrants récupérables à 100 %, factures sans PO comprises : le carburant
et l'outillage ne sont pas tous entièrement récupérables (à valider par le CPA) ; (2) la liste des catégories est celle de Nathan :
tant qu'elle est vide, aucune facture sans PO ne se saisit ; (3) un même fournisseur d'essence saisi de deux façons (« Pétro » et
« Petro-Canada ») reste deux fournisseurs : seule la casse et les espaces se comparent ; (4) la date d'une correction se lit avec
l'`horodatage` de la demande par la file (l'heure de réception du serveur ne fait foi que pour un appel d'appareil direct) ; (5) la
correction ne change ni le PO, ni le fournisseur, ni la catégorie ; (6) aucun paiement fournisseur n'existe (N5).

PLAN T4.19-b (constat du cash libre, `constat_cash_libre.py`, `m5_constater_cash_libre`) : M5 PUBLIE le cash libre au bus
(`m5.cash_libre_constate`, catalogue du socle, schéma fermé) pour que M8 l'affiche dans sa vue exécutive au lieu de « manque ».
Le déclencheur est un outil T1 DÉDIÉ (N3, `admin` : le propriétaire le lance depuis son téléphone, un agent en mode `ombre`
attend sa décision) ; `m5_etat_tresorerie` (T0) ne publie rien. `aujourd_hui` est requis : c'est la date de référence du
constat (M5 n'a pas d'horloge). Le constat est calculé depuis le MÊME instantané que `m5_etat_tresorerie` (aucun second
calcul), tracé au registre dérivé `constats_cash_libre`, puis publié dans la même transaction : la trace et l'événement
réussissent ou échouent ensemble. Un constat par date de référence et par version des données : redire le même jour et la
même version que le dernier ne publie rien (`deja_constate`). L'identifiant porte le rang du constat : un retour à une
version antérieure des données (une déclaration remise à sa valeur d'avant) est un nouvel événement, jamais un doublon avalé
par le bus. Un cash libre « non calculable, manque X » se publie tel quel, avec ses codes de manque, jamais un zéro.

Rien de libre ni de personnel ne part : la source d'une déclaration du propriétaire est dite par son origine
(`DECLARATION_PROPRIETAIRE`), jamais par ses mots (elle pourrait nommer un employé) ; ni le détail d'un verdict, ni un client,
ni un fournisseur. Le schéma du catalogue est fermé : un champ de plus est refusé à la publication. Refus nommés, tous AVANT la
lecture des registres : `REJ-CONSTAT-DATE-INVALIDE`, `REJ-CONSTAT-COUTS-REQUIS` (le droit de voir les coûts), et
`REJ-CONSTAT-STOCKAGE-NON-DURABLE` (sans registres durables, il n'y a ni registre réel ni bus). Aucun paiement, aucune remise,
aucune écriture aux mouvements : `conformite.verifier_aucun_decaissement` couvre le module et les deux fonctions d'`outils.py`.

Limites : (1) personne ne déclenche le constat seul : le digest de 7 h ne l'appelle pas (GATE NATHAN : qui le déclenche, à
quelle fréquence, un bouton du profil admin ?) ; (2) la date de référence est celle de l'appelant, et un agent en mode
`supervise` ou `autonome` exécute ce T1 sans file : le constat ne porte que des montants que M5 a calculés, mais la date qu'il
porte est celle qu'on lui a donnée ; (3) le constat vieillit : M8 dit son âge, aucun seuil de péremption n'est inventé (GATE
NATHAN) ; (4) les hypothèses du calcul (crédits de taxes récupérables à 100 %) voyagent avec le constat et restent à valider par
le CPA ; (5) deux appels simultanés pour le même rang : le second échoue (écriture concurrente) et se rejoue sans dégât.

M5.10.a (intégré localement le 1er octobre 2026, décision capital) :
`m5_preparer_decision_capital` accepte facultativement
`echeanciers_hypothetiques`; chaque option saisit `couvre_jusquau` et jusqu'à huit sorties datées, catégorisées, avec
montant texte au cent, référence source et hypothèse. Le prix comptant et les mises de fonds sont rapprochés des montants
cités; chaque paiement mensuel saisi est rapproché du montant mensuel de l'offre. Un montant non rapproché, une sortie sans
source/date ou une couverture qui s'arrête avant la fin de l'horizon laisse l'option `INCOMPLET`, sans solde projeté. La
couverture jusqu'à la fin de l'horizon de 1 à 26 semaines est une déclaration manuelle, non une preuve de calendrier complet.
L'extension est additive : sans cette entrée, l'ancienne forme de comparaison d'offres est conservée. La comparaison
capital reste un outil compact distinct du dossier CFO à 25 rubriques; avec l'extension, la réponse omet son contexte AR/AP/devis
pour tenir dans le budget. M5 ne génère aucune date ou échéance depuis le paiement mensuel cité et ne calcule ni taux, taxe,
intérêt ou frais. La projection réutilise le même instantané financier et ses flux connus/datés, part du solde du registre
(jamais du cash libre) et ne soustrait pas une seconde fois réserves ou obligations. Elle montre le solde de fin et le plus bas
des fins de semaine si l'horizon est calculable; ce minimum n'est pas un creux intra-semaine. Un premier dépassement budgétaire
rend les soldes `NON_CALCULABLE`; le rapport est mesuré à nouveau et refusé s'il dépasse encore la limite. Aucune
recommandation, validation fiscale, commande, signature ou dépense n'en découle. Les retenues, cotisations, DAS, paie nette,
obligations calculées, fiscalité officielle, rapprochement bancaire, contrats signés, DSCR et projections à 12/24 mois
restent partiels ou absents.


M5.4.a ajoute le journal privé des contrats horaires individuels. M5.4.b ajoute un brouillon du brut régulier depuis M4 et le taux M5, sans retenues, cotisations, DAS, paie nette, écriture, paiement ou alimentation du cash libre. M5.4.c expose l'inventaire versionné des références de règles : ARC/RQ sont actuellement NON_QUALIFIEES et toute lacune laisse l'état PARTIEL; aucune retenue n'est calculée. M5.4.d produit un JSON privé destiné à une saisie et un calcul humains dans WebRAS/PDOC, sans appel à ces services; l'assiette humaine est facultative et reste inconnue si elle n'est pas fournie. Les hypothèses d'arrondi restent déclaratives et non vérifiées; une validation humaine est requise. Les retenues, cotisations, paie nette et obligations employeur calculées restent absentes. Le périmètre est décrit dans [M5.4.a — contrat salarial horaire](docs/m54-contrat-salarial-horaire.md), [M5.4.b — brut régulier préparatoire](docs/m54b-brut-regulier-preparatoire.md), [M5.4.c — références de règles de paie](docs/m54c-sources-regles-paie.md) et [M5.4.d — dossier WebRAS manuel](docs/m54d-dossier-webras-manuel.md).


Le dossier `m5_preparer_dossier_decision_cfo` raccorde aussi le journal durable
`obligations_preparees` après vérification de l'identité ou du grant CFO exact. La lecture
réutilise les statuts du calendrier préparatoire existant; elle ne change ni l'autorité des
outils DEVICE, ni les déclarations YAML utilisées par le cash, ni le calcul de paie/fiscalité.
Un journal capturé et validé vide conserve exactement la forme, les sources et le hash v1;
l'absence du champ ne signifie jamais zéro. Dès un maillon courant, y compris un retrait,
le champ `obligations_preparees` expose les données non attestées, références et auteur.

Le [contrat du dossier](contracts/dossier_decision_cfo.v1.yaml) décrit la projection dédupliquée :
`source_ref` est l'index exact dans les sources de la rubrique 5; les références natives sont
`[index, ligne_id, precedent_ligne_id]`, l'auteur `[personne, role, source]`, la date de référence
celle du dossier. Les déclarations et leurs sources/dates/calendriers restent exactes; les codes
connus utilisent le même masque canonique que le calendrier CFO, les codes inconnus restent
intégralement présents. Une correction ou un retrait change le snapshot du dossier. Les
rubriques 6 et 20 pointent vers le contexte unique, sans ajouter de vingt-sixième rubrique.

La borne de sortie reste inchangée. Un dossier riche enrichi peut être refusé avec
`REJ-PREVISION-REPONSE-TROP-GROSSE`, y compris après une correction ou avec un calendrier
complet, si les références/métadonnées excèdent l'enveloppe. Aucune provenance ou rubrique
n'est tronquée pour rendre le dossier. Ce raccord ne livre ni le CFO complet, ni une saisie
financière ou un paiement, ni des obligations officielles calculées; les dates passées restent
à vérifier et les sources absentes/périmées restent inconnues.

Le même outil accepte maintenant `volet="obligations_preparees"` pour une vue source
`VUE_OBLIGATIONS_PREPAREES_CFO` version `v1`. Le défaut `dossier_complet` et les anciens appels
à deux arguments conservent les 25 rubriques. Le volet fourni fait partie des arguments exacts
liés au ticket CFO; modifier le volet, la date ou la question ne peut pas réutiliser ce ticket.
La vue choisie est rendue avant la même garde de sortie à 5700 caractères et la borne active.
Elle réutilise le même snapshot validé, avec question, référence, mention préparatoire, matrice
`sources` propre et projection complète des obligations. Son `source_ref` pointe dans cette
matrice; elle expose corrections, retraits, sources périmées et catégories absentes sans
promouvoir leur montant dans le cash. Un journal vide y est explicite (trois catégories absentes,
aucune déclaration), sans inventer zéro; le dossier complet vide garde sa forme historique.
Un contexte extrême peut encore dépasser le budget et doit être refusé intégralement. Cette
vue source n'apporte ni recommandation CFO complète ni validation fiscale ni action financière.
