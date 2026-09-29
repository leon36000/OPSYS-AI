# M5-financecore

FinanceCore — comptabilite, fiscalite (mention CPA), paie, CFO IA

Statut : département OPSYS complet (mode `ombre`), sur le modèle de M3. Les 7
stories du PRD (`docs/bmad/02-PRD-PM.md`) sont livrées et vertes : contrats
gelés + validation d'entrée (S001), registre append-only hash-chaîné (S002),
solde/argent disponible (S003), taux fiscaux versionnés (S004), registre
d'approbation F0-F7 (S005), état financier filtré par rôle (S006), conformité
statique transversale (S007). Couche département ajoutée : `department.yaml`,
`SOUL.md`, 2 skills (`tenir-le-registre-financier`,
`gerer-les-approbations-f0-f7`), `src/m5_financecore/outils.py` (5 outils
agent), `tests/test_outils_agent.py`.

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
taxes) ; (4) ni correction ni annulation d'une facture saisie, ni facture sans PO reçu ; (5) rien n'est payé, donc rien n'est
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
les comptes à payer, du total de T4.15 ; les paies, DAS et dettes, de RIEN (M5.4, paie, est absent) : le propriétaire les DÉCLARE
avec leur source et leur date dans `department.yaml` (`configuration.obligations_declarees`), sinon elles sont « à déclarer ». Un
« 0.00 » déclaré est un zéro connu. Un déficit est rendu tel quel. Arrondi : `ROUND_HALF_UP`, une fois, au résultat.

Calendrier fiscal : `contracts/calendrier_fiscal.v1.yaml`, sur le patron de `taux_fiscaux.v1.yaml` (année, sources officielles
avec adresse et date de consultation, version). Les dates sont TRANSCRITES des calendriers de Revenu Québec (jours fériés et
Fêtes compris), jamais calculées ; le chargeur en vérifie la cohérence. Deux années déclarées (2025, 2026) ; `A_VALIDER` par le
CPA. `m5_lire_echeances_fiscales` (T0, `admin`) dit les prochaines échéances TPS/TVQ, les retards et la taxe nette de chaque
période. Une année non déclarée est REFUSÉE (`REJ-CALENDRIER-ANNEE-NON-DECLAREE`). La fréquence de production (mensuelle,
trimestrielle, annuelle), la fin d'exercice, le statut de particulier en affaires et la date de dernière remise sont des
décisions ou des faits du propriétaire (GATE NATHAN, `configuration.fiscal` de `department.yaml`) : absents, le calendrier le dit
et ne suppose rien. Hors du calendrier, faute de donnée : acomptes provisionnels, DAS, T4 et RL-1, CNESST.

Mention obligatoire (`analyse.py`) : « Analyse préparatoire IA — validation Nathan/CPA/fiscaliste requise avant toute décision
officielle ou action réelle. » (DEFINITION-PRODUIT §7 M5, §13.3) est portée par toute sortie acceptée d'un outil d'analyse
(`m5_etat_tresorerie`, `m5_lire_echeances_fiscales`, `m5_lire_rentabilite_chantier`, `m5_lister_comptes_a_payer`,
`m5_saisir_facture_fournisseur`) ; un test ferme le monde (chaque outil est classé) et lit la mention dans le document produit.

AUCUNE REMISE, AUCUNE DÉCLARATION, AUCUN PAIEMENT. Le calendrier propose des dates ; remettre une taxe est N5 (Nathan ET le
CPA). `conformite.verifier_aucun_decaissement` couvre le nouveau code : en régime strict (aucun mot de mouvement) pour le
calendrier, le cash libre et la mention, en lecture seule pour le code qui ouvre le registre des mouvements pour en tirer le
solde. Les seuls outils T3 de M5 sont les deux d'avant.

Limites connues : (1) les crédits de taxes sur intrants sont supposés récupérables à 100 % (à valider par le CPA) ; TPS et TVQ ne
se compensent pas entre elles et une taxe nette négative n'est jamais de l'argent (prudent) ; (2) aucune constatation de paiement
fournisseur ni de remise : un fournisseur payé ou une taxe remise reste retranché tant que le registre l'ignore
(`taxes_remises_jusqu_au` s'avance à la main, avec le CPA) : le cash libre est alors SOUS-estimé, jamais surestimé ; (3) une
PROVISION posée pour un autre poste (taxes, paies) compte deux fois : aucune catégorie de réserve n'existe encore ; (4) paies, DAS
et dettes sont déclarées à la main dans le manifeste, en attendant M5.4 et un registre des dettes ; (5) `aujourd_hui` est fourni
par l'appelant (M5 n'a pas d'horloge, DA-M5-06) ; (6) la fréquence de production et les autres décisions sont absentes du
manifeste livré : tant que Nathan ne les déclare pas, le cash libre est « non calculable » et le calendrier refuse de nommer une
échéance ; (7) la prévision de trésorerie (M5.7 : projection, scénarios, tests de stress) n'est PAS livrée : le cash libre est
l'état d'aujourd'hui, jamais une projection ; les catégories de réserve (M5.14, stratégie d'épargne) non plus.
