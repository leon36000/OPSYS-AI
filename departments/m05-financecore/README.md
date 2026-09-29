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
