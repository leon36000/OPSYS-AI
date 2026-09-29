---
name: tenir-le-registre-financier
description: Procédure pour consulter l'état financier (solde, argent disponible), calculer les taxes TPS/TVQ, et enregistrer un mouvement financier — sans jamais inventer un montant, un taux ou un solde.
---

# Tenir le registre financier

## Consulter l'état financier

1. Détermine le rôle de la personne qui demande l'état : autorisée aux coûts (ex.
   dirigeant, rôle financier) ou non (ex. terrain).
2. Appelle `m5_etat_tresorerie` avec `mouvements_historique` (l'historique renvoyé
   par le dernier appel connu, `[]` si aucun), le `role`, et `autorise_couts` réglé
   explicitement selon l'étape 1 — jamais laissé implicite. (Un appel venu de l'app
   mobile n'a pas à le dire : la vue vient du jeton de la personne authentifiée, et
   un argument ne peut que la restreindre. Tu n'y changes rien.)
3. Si `autorise_couts=false`, l'état renvoyé ne contient ni solde, ni argent
   disponible, ni taux : c'est le comportement attendu, pas une panne. Un verdict
   `REJ-AUTORISE-COUTS-REQUIS` dit que tu as oublié de le préciser : ajoute-le.
4. Présente toujours `solde` ET `argent_disponible` séparément — jamais l'un pour
   l'autre : l'argent disponible exclut les provisions.

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
4. Conserve `mouvements_historique` renvoyé pour le prochain appel — c'est la
   continuité du registre entre deux appels.

## Lire le coût réel et la rentabilité d'un chantier

1. Appelle `m5_lire_rentabilite_chantier` avec `chantier_id` ou `devis_id` (sans filtre : une ligne
   par devis). Tu ne fournis AUCUN montant, prix, taux, durée ni quantité : le code les lit à la
   source (variance de M6, temps pointé de M4, livre de prix de M6, taux configuré, facture, devis).
   Un argument de ce genre est refusé.
2. Un verdict `CALCULEE` donne le coût réel complet, la marge réelle et son écart à la marge prévue
   (en dollars et en points de pourcentage du prix). Présente-les tels quels, avec leurs sources.
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
   personne ne t'a donnés, et tu ne saisis pas une facture lue d'une image : l'OCR est fermé, la saisie est manuelle.
   Depuis l'app, la personne s'identifie ; sinon ta demande attend l'approbation de la finance ou du propriétaire (ne la
   présente pas comme saisie). Les taxes sont recalculées : si le total imprimé ne concorde pas au cent près, la saisie est
   refusée avec les deux chiffres, vérifie ce qui a été tapé.
4. Un doublon (même fournisseur, numéro, montant) est refusé ; un PO jamais reçu par M6 aussi (enregistre d'abord la réception
   dans M6). Aucun outil ne paie un fournisseur : c'est N5, Nathan et le CPA.
