"""Capacités d'agent du département M5 FinanceCore.

Chaque outil enveloppe une fonction métier déterministe existante : aucune n'est
réécrite. Les montants sont TOUJOURS des Decimal construits depuis une
représentation textuelle (jamais un float JSON, qui importerait une imprécision
binaire dans un registre financier).

Le registre (mouvements et approbations, deux chaînes DISTINCTES, PRD §5.4) : sauf si
l'appelant transmet explicitement `mouvements_historique`/`approbations_historique`
(l'historique renvoyé par un appel précédent — simulation en mémoire, rejouée via
`Registre.ajouter`, comportement historique gardé par les tests unitaires de ce
paquet), chaque appel obtient le registre de PRODUCTION. Pour les APPROBATIONS,
celui-ci reste en mémoire pour la durée d'un appel (registre de gouvernance interne,
hors périmètre de ce chantier). Pour les MOUVEMENTS, il est adossé au stockage durable
de l'instance (ADR-0009) dès le chargement du module, relu à chaque appel et jamais
ouvert au chargement ; `reinitialiser_stockage_mouvements()` le rebascule en mémoire
pour les tests unitaires, `utiliser_stockage_durable()` revient au durable.
`registre.py` reste pur (ni `opsys` ni SQLAlchemy) : ce module est l'unique endroit du
département qui connaît `opsys.stockage`.

RÈGLE FINANCE (autonomie) : toute écriture financière (registre des mouvements) et
toute décision d'approbation sont T3 — une action qui engage ou meut de l'argent
n'est jamais autonome, quel que soit le mode du département. Lecture et calcul purs
(état, taxes) sont T0. Créer une facture BROUILLON (M5.2, `m5_creer_facture_brouillon`)
est une écriture interne non finale sur un registre dédié — elle n'envoie rien au
client et n'engage aucun argent (le registre des MOUVEMENTS n'est jamais touché) —
donc T1, jamais T3 à ce stade.

PLAN T1.3-c (branchement sur les approbations du socle, ADR-0009 §4/§5) : les DEUX
transitions qui engagent sont maintenant des outils agent, gardés par le socle et
JAMAIS par la forme d'une donnée passée en argument :
- `m5_envoyer_facture` (BROUILLON -> ENVOYEE) est T2/N4 — le même niveau que F4/F5
  dans l'ancienne échelle interne (`NIVEAU_POUR_PALIER`, plus bas). `finance` ou
  `nathan_owner` (`department.yaml/approbations.n4`) décide dans la console/CLI
  OPSYS ; `opsys.capacites.Capacites._distribuer` intercepte tout appel direct en
  `en_attente_approbation` avant que `facturation.envoyer_facture` ne s'exécute.
- `m5_enregistrer_paiement_facture` (ENVOYEE -> PAYEE) est T3/N5 — le même niveau
  que F6/F7 : `nathan_owner` ET l'attestation du professionnel (ADR-0009 §5), jamais
  automatique, jamais vérifiées ici mais par `opsys.approbations.decider` seul. Le
  montant réellement déposé est comparé par le CODE au montant dû
  (`facturation.enregistrer_paiement_facture`) : un paiement partiel ou un écart est
  un verdict nommé, jamais une facture marquée PAYEE sans contrôle.

L'ancien registre interne F0-F7 (`approbation.py`) n'est plus routé par aucun outil
agent : il reste dans le dépôt comme bibliothèque pure, testée, mais vestigiale (voir
le rapport de PLAN T1.3-c) — toute future action F0-F7 de M5 doit obtenir son PROPRE
outil, au N mappé par `NIVEAU_POUR_PALIER`, plutôt que de rejoindre un registre de
gouvernance parallèle au socle.

Registre des FACTURES (M5.2, `facturation.py`) : troisième registre du département, sur
exactement le même patron d'adaptateur que celui des mouvements (`_registre_factures`/
`_etat_factures` ci-dessous, symétriques à `_registre_mouvements`/`_etat_mouvements`) — durable
dès que `_stockage_durable_actif` l'est (même bascule que les mouvements), jamais ouvert au
chargement, relu à chaque appel, `stockage.maillons("m05-financecore", "factures")` en
production. Le registre des MOUVEMENTS reste strictement celui déjà en place : aucune fonction
de ce fichier n'écrit un ENCAISSEMENT à partir d'une facture.

Consommateurs d'événements (ADR-0009 §3, PLAN T1.2-d, suite ; T1.3-c point 4) : `consommateurs()`
abonne `_recevoir_devis_accepte` (`m3.devis_accepte`) et `_recevoir_travaux_termines`
(`m4.travaux_termines`), chacun sur son propre registre durable dédié (`devis_recus.py`,
`wct_recus.py` — DISTINCTS des mouvements et des factures : ni une écriture financière, ni une
facture, seulement ce qui a été REÇU). Les deux délèguent à `_essayer_facture_brouillon`,
fonction UNIQUE (même patron que M6 `_evaluer_et_publier_variance`) qui tente la facture
BROUILLON dès que devis ET complétion sont connus, quel que soit l'ordre d'arrivée. Fail-closed :
devis inconnu, complétion inconnue, `chantier_id` absent du devis ou WCT sans `devis_id` donnent
un statut d'attente nommé, jamais une facture inventée — `lister_attentes_facturation` (T0) les
recalcule EN DIRECT depuis les registres reçus et celui des factures à chaque appel, aucun
troisième registre d'« attentes » à tenir synchronisé à part. Une incohérence interne (ex.
`prix_total` du devis qui ne concorde pas avec la somme recalculée des lignes) LÈVE : le
répartiteur réessaie puis met en quarantaine, jamais une facture fabriquée sur une donnée qui ne
tient pas debout. `consommateurs()` abonne en plus `_recevoir_variance_chantier`
(`m6.variance_chantier`, catalogue existant, M6 en est propriétaire) sur `variance_recus.py` :
M5 GARDE le signal (le dernier connu par `wct_id`, jamais un verrou) pour l'afficher à côté
d'une facture BROUILLON dans `attentes()`, sans jamais bloquer son envoi (M6 « signale
seulement »). Ce module reste le seul point du département qui connaît `opsys.evenements`,
comme il est déjà le seul à connaître `opsys.stockage` — `facturation.py` n'importe ni l'un ni
l'autre (DA-M5-04).

PLAN T2.2 (Client 360 de M2) : `consommateurs()` abonne en plus `_recevoir_client_associe`
(`m2.client_associe`, catalogue M2) sur `clients_recus.py` (même patron que les autres registres
« reçus »). `_essayer_facture_brouillon` facture avec le VRAI `client_id` du Client 360 quand il
est connu, sinon reprend le repli historique (`client_id = lead_id`, une donnée réelle, jamais
inventée) — JAMAIS bloquant : `m2.client_associe` est publié à l'ingestion du lead, bien avant
qu'un devis ou une complétion puisse exister pour lui, donc ce repli ne devrait normalement jamais
s'activer en usage réel ; il reste le filet pour un ordre d'arrivée inhabituel. Aucune facture
déjà créée n'est corrigée rétroactivement si `m2.client_associe` arrive après coup (immuabilité
des écritures, même principe que `variance_recus.py` : le signal est gardé pour l'AVENIR, jamais
appliqué au passé).

PLAN T1.4-k2 (identité authentifiée, `acces.py`, docs/architecture/ROLES.md) : pour un appel
d'appareil, `m5_etat_tresorerie` ne croit plus `role` ni `autorise_couts` — la vue vient du rôle de la
personne authentifiée, confirmée en base à chaque appel (`_acteur_appareil`) ; un argument ne peut que
restreindre. `m5_lister_attentes_facturation` exige la même identité confirmée. Sans identité d'appareil
(agent, console), comportement d'avant, sans contrôle de personne (« voie des agents »).

PLAN T1.5-d (coût réel et rentabilité, DEFINITION-PRODUIT §6 « travaux terminés », `cout_reel.py`,
DA-M5-10) : les consommateurs qui apportent une pièce (devis accepté, WCT, variance M6) appellent
`_essayer_cout_reel`, qui calcule le coût réel du chantier et sa rentabilité depuis des pièces LUES À LA SOURCE
(`_etat_chantier`) et les trace dans un cinquième registre durable, DÉRIVÉ (`rentabilite`, une trace par version
des entrées) : ni le grand livre, ni le registre des factures, ni les comptes à recevoir (une vue de ces
factures) ne sont écrits. Le livre de prix de M6 est lu en lecture seule (`_livre_de_prix_m6`) : le seul endroit du
département qui nomme un autre département. `m5_lire_rentabilite_chantier` et `m5_lire_comptes_a_recevoir` (T0,
`admin` seulement, même contrôle d'identité et de droit de voir les coûts que `m5_etat_tresorerie`) les rendent
à l'admin ; aucun montant, prix, taux, durée ni quantité ne se passe en argument.

PLAN T1.5-d (la marge réelle atteint M8 et M10) : chaque fois que `_essayer_cout_reel` ajoute une trace (une
nouvelle version des entrées), il publie `m5.rentabilite_chantier` dans la MÊME transaction (`_publier_rentabilite`,
`cout_reel.charge_evenement`) : le coût réel (ou, s'il est partiel, ce qui manque), la marge réelle et prévue en
texte décimal, `wct_id`, `devis_id` ; jamais un prix unitaire, un taux ni une donnée de client, et jamais une marge
pour un coût partiel. C'est le seul événement que M5 publie. Aucune écriture comptable n'en découle.

PLAN T4.15 (comptes à payer, `comptes_a_payer.py`, M5.2 et M6.16) : `consommateurs()` abonne en plus
`_recevoir_reception_enregistree` (`m6.reception_enregistree`) sur un sixième registre durable, DÉDIÉ,
`comptes_a_payer` : il garde chaque réception reçue (l'« à payer ATTENDU » d'un PO, cumulé sur ses livraisons) et
chaque facture fournisseur SAISIE.
`m5_saisir_facture_fournisseur` (T1, N3, `admin`) est une écriture interne non finale qu'un HUMAIN fait :
identité de jeton d'appareil confirmée en base, ou exécution d'une demande qu'un humain vient d'approuver (mêmes deux
voies que les écritures humaines de M10) ; un appel d'agent qui n'a pas passé par l'approbation (mode `supervise` ou
`autonome`, où un N3 s'exécute sans file) est refusé (`REJ-AP-HUMAIN-REQUIS`). Les taxes sont recalculées avec les
taux versionnés (`taxes.calculer_taxes`, `ROUND_HALF_UP`), un doublon est refusé, le rapprochement PO, réception et
facture est PROPOSÉ avec ses écarts et n'est jamais appliqué. `m5_lister_comptes_a_payer` (T0, `admin`, même
règle d'accès que les autres lectures financières) le rend par pages sous la limite de sortie de `Capacites`.
AUCUNE écriture au registre des mouvements : payer un fournisseur est N5 (Nathan ET le CPA) et n'existe pas ici ;
`conformite.verifier_aucun_decaissement` le prouve par l'AST. L'unité des prix du livre de prix de M6 n'est pas
déclarée (GATE NATHAN) : aucune conversion, et chaque attendu porte la réserve `REJ-AP-UNITE-PRIX-NON-CONFIRMEE`.

PLAN T4.15-c (correction, annulation, factures sans PO ; `comptes_a_payer.py`) : trois outils de plus, tous refusés à
un agent seul. `m5_corriger_facture_fournisseur` et `m5_annuler_facture_fournisseur` sont T2/N4 (engagement : écriture
finale sur une dépense, ADR-0009 §4) : depuis le téléphone de l'admin comme pour un agent, l'appel ATTEND dans la file
du propriétaire (mode `ombre` ou `supervise`), et ne s'exécute qu'après la décision de `finance` ou du propriétaire,
aux arguments exacts enregistrés ; ils AJOUTENT une pièce de correction ou d'annulation au registre des comptes à
payer, motif obligatoire, sans jamais modifier la facture d'origine. `m5_saisir_facture_sans_po` est T1/N3 comme la
saisie d'une facture de PO : une dépense sans PO, avec une catégorie de la liste fermée
`department.yaml/configuration.categories_depense_sans_po` (vide : « catégories à configurer »). Les trois exigent un
HUMAIN, par les deux voies de `_acteur_humain` : l'identité de jeton d'appareil confirmée en base (pour un N4, la
PERSONNE doit porter `nathan_owner` ou `finance` : le rôle `admin` du jeton ne dit pas qui est le propriétaire) ou
l'approbateur que le SOCLE dit (`opsys.approbations.approbateur_en_cours`, posé par `decider` autour de l'outil et
revérifié en base : il remplace la lecture de la table des approbations que M5 recopiait de M10 ; M1 et M10 n'y sont
pas encore passés). En mode `autonome`, où un N4 s'exécute sans file, c'est l'outil qui refuse l'agent.
`m5_lister_comptes_a_payer` lit l'état courant, factures sans PO comprises (`sans_po` les liste, avec l'identifiant
que la correction demande) ; le cash libre aussi : une annulée ne donne aucun crédit de taxes ni aucune dette, une
corrigée vaut sa correction, une facture sans PO est une dette ferme. Aucun DECAISSEMENT :
`conformite.verifier_aucun_decaissement` couvre le nouveau code.

PLAN T4.16 (cash libre réel et calendrier fiscal, `cash_libre.py`, `calendrier_fiscal.py`, `analyse.py`, M5.5, M5.14) :
`m5_etat_tresorerie` AJOUTE, sans rien changer à l'état financier gelé (mêmes clés, même `etat_id`), le cash libre réel
(`_cash_libre`) : le solde moins la TPS/TVQ à remettre, les paies, les DAS, les comptes à payer, les dettes et les
réserves, chaque composante avec sa source et sa fraîcheur ; une composante inconnue est « non calculable, manque X »,
jamais zéro. `_cash_libre` lit chaque registre UNE fois (solde et réserves : mouvements ; taxes : factures clients
`ENVOYEE` et `PAYEE`, factures fournisseur saisies ; comptes à payer : T4.15) et ne fait qu'assembler : aucun calcul de
taxe ici. Ce que le propriétaire décide ou constate (fréquence de production, fin d'exercice, date de dernière remise,
paies, DAS, dettes) vient de `department.yaml/configuration` (`_configuration_manifeste`, relu à chaque appel, absent :
« à déclarer »). `m5_lire_echeances_fiscales` (T0, `admin`) rend les prochaines échéances TPS/TVQ et la taxe nette de
chaque période. Toute sortie acceptée d'un outil d'analyse porte la mention obligatoire (`analyse.py`). Aucune remise,
aucune déclaration, aucun paiement : `conformite.verifier_aucun_decaissement` couvre le nouveau code (strict pour
`_cash_libre` et le calendrier, lecture seule pour `etat_tresorerie`, qui ouvre le registre des mouvements). La réponse
de `m5_etat_tresorerie` est bornée (`_borner_etat`) : le socle tronque au-delà de 6 000 caractères.

PLAN T4.16-d (prévision de trésorerie, `prevision.py`, M5.7) : `m5_prevoir_tresorerie` (T0, `admin`) rend, semaine par
semaine, ce que le solde devient avec les seuls flux CONNUS et DATÉS : les factures clientes envoyées, les factures
fournisseurs et l'attendu non facturé de chaque PO, les échéances TPS/TVQ du calendrier fiscal, les paies, DAS et
dettes déclarées. Aucune projection, aucune vente future. `_lectures_finance` lit chaque registre UNE fois (le cash
libre et la prévision partent du MÊME instantané) ; `_resultat_cash_libre` en tire le cash libre (T4.16, inchangé) ;
`_page_prevision` dit les flux (`prevision.flux_*`), assemble et rend la page sous `BUDGET_SORTIE`. L'horizon, le
seuil d'alerte, les délais de paiement des clients et des fournisseurs et la date de sortie des paies, DAS et dettes
sont au propriétaire (`configuration.prevision` de `department.yaml`, GATE NATHAN, relue à chaque appel) : absents, la
réponse dit quoi déclarer. `prevoir_tresorerie` ouvre le registre des mouvements pour en tirer le solde, comme
`etat_tresorerie` : la garde anti-décaissement la surveille en lecture seule, ses aides en strict. Aucune remise,
aucune déclaration, aucun paiement.

PLAN T4.19-b (constat du cash libre, `constat_cash_libre.py`, `m5_constater_cash_libre`) : M5 PUBLIE le cash libre
au bus (`m5.cash_libre_constate`) pour que M8 l'affiche dans la vue exécutive au lieu de « manque ». Le déclencheur
est un outil T1 DÉDIÉ, jamais `m5_etat_tresorerie` : un outil de lecture (T0) ne doit rien écrire (la garde
anti-décaissement le surveille en lecture seule, et un T0 s'exécute sans approbation même en mode `ombre`, ce qui
ferait partir un événement sans que personne ne l'ait demandé), alors qu'un T1 est une écriture interne : validée au
départ par l'humain qui agit (l'admin sur son téléphone), en file d'approbation pour un agent en mode `ombre`.
`aujourd_hui` est requis (M5 n'a pas d'horloge) : c'est la date de référence du constat. `_constater_cash_libre`
calcule le cash libre depuis le MÊME instantané que `m5_etat_tresorerie` (`_lectures_finance`,
`_resultat_cash_libre` : aucun calcul de plus), le trace au registre DÉRIVÉ `constats_cash_libre` (un maillon par
constat, son rang fait le `sequence` de l'événement) et publie `m5.cash_libre_constate` dans la MÊME transaction : la
trace et l'événement réussissent ou échouent ensemble. Un constat par date de référence et par version des données :
un appel qui redit le même jour et la même version que le DERNIER constat ne publie rien (`deja_constate`) ; une
version qui change, ou un jour qui change, publie un nouvel événement. Un cash libre « non calculable, manque X » se
publie tel quel, avec ses codes de manque : M8 le montre, il ne le remplace par aucun zéro. Rien de libre ni de
personnel ne part (voir `constat_cash_libre.py`). Aucun paiement, aucune remise, aucune écriture aux mouvements :
`conformite.verifier_aucun_decaissement` couvre le module et les deux fonctions (lecture seule pour
`constater_cash_libre`, qui ouvre le registre des mouvements pour le solde ; strict pour `_constater_cash_libre`,
qui écrit la trace et publie)."""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Callable, Mapping
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from opsys import approbations, contexte, evenements, identite, jetons, stockage
from opsys.outils import Autonomie, Niveau, Outil, depuis_couple

from . import (
    acces,
    analyse,
    brut_regulier,
    calendrier_fiscal,
    calendrier_obligations,
    cash_libre,
    clients_recus,
    comptes_a_payer,
    constat_cash_libre,
    contrats_salaries_horaires,
    cout_reel,
    couts_marketing,
    decision_capital,
    devis_recus,
    dossier_decision_cfo,
    echeanciers_contrats,
    etat_financier,
    facturation,
    prevision,
    soldes,
    sources_regles_paie,
    taux_fiscaux,
    taxes,
    validation,
    variance_recus,
    wct_recus,
)
from . import registre as registre_module

ValidateurSnapshotCfo = Callable[
    [list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]], dict[str, str] | None
]
LecteurHeuresM4 = Callable[[str, str, str, str], Mapping[str, Any]]

_CHEMIN_TAUX_FISCAUX = Path(__file__).resolve().parents[2] / "contracts" / "taux_fiscaux.v1.yaml"
# PLAN T4.16 : le calendrier fiscal versionné (années déclarées, sources citées), lu à chaque appel.
_CHEMIN_CALENDRIER_FISCAL = Path(__file__).resolve().parents[2] / "contracts" / "calendrier_fiscal.v1.yaml"
_CHEMIN_SOURCES_REGLES_PAIE = Path(__file__).resolve().parents[2] / "contracts" / "sources_regles_paie.v1.yaml"

_DEPARTEMENT = "m05-financecore"
_NOM_REGISTRE_MOUVEMENTS = "principal"
_NOM_REGISTRE_FACTURES = "factures"
_NOM_REGISTRE_DEVIS_RECUS = "devis_recus"
_NOM_REGISTRE_WCT_RECUS = "wct_recus"
_NOM_REGISTRE_VARIANCE_RECUE = "variance_recue"
_NOM_REGISTRE_CLIENTS_RECUS = "clients_recus"
_NOM_REGISTRE_RENTABILITE = "rentabilite"
# PLAN T4.15 : registre DÉDIÉ des comptes à payer (réceptions reçues de M6, factures fournisseur saisies). Toujours
# durable, comme `devis_recus` ou `rentabilite` : pas de mode « en mémoire » (rien à simuler, l'état vient du bus).
_NOM_REGISTRE_COMPTES_A_PAYER = "comptes_a_payer"
# PLAN T4.19-b : registre DÉRIVÉ des constats du cash libre publiés au bus (un maillon par constat : rang, jour,
# version, statut, identifiant). Toujours durable, comme `rentabilite` : l'état vient des registres lus, la charge
# complète est au bus.
_NOM_REGISTRE_CONSTATS = "constats_cash_libre"
# M5.4.a : données salariales privées, sur un flux durable séparé des mouvements et des obligations.
_NOM_REGISTRE_CONTRATS_SALARIES = "contrats_salaries_horaires"
# M5.8a : journal append-only des échéanciers commerciaux validés par un humain.
_NOM_REGISTRE_ECHEANCIERS_CONTRATS = "echeanciers_contrats_tresorerie"
# `Capacites._tronquer` mesure `{"ok": true, "resultat": {"accepte": true, "resultat": {"role": ..., <la page>}}}` : une
# centaine de caractères d'enveloppe, plus une marge. Le budget d'une page est la limite du socle moins cette réserve :
# sous elle, jamais tronquée.
_RESERVE_ENVELOPPE = 300
BUDGET_SORTIE = jetons.LIMITE_SORTIE_DEFAUT - _RESERVE_ENVELOPPE
# PLAN T1.5-d : le livre de prix de M6, lu en LECTURE SEULE à la source (le prix de chaque matériau utilisé
# ne vient ni de l'appelant ni d'un événement). Le seul endroit du département qui nomme un autre département
# ; il n'importe aucun de ses modules (DA-M5-04) et ne fait qu'itérer ses maillons, jamais `append`.
_DEPARTEMENT_LIVRE_DE_PRIX = "m06-material-control"
_NOM_REGISTRE_LIVRE_DE_PRIX = "livre_prix"
# `department.yaml/configuration.taux_horaire_main_d_oeuvre` : même source de configuration que M6
# (`seuil_variance_chantier_pourcentage`). ABSENT du manifeste livré : c'est un chiffre de l'entreprise, que
# M5 ne devine pas (le coût réel dit alors « taux horaire à configurer »).
_MANIFESTE = Path(__file__).resolve().parents[2] / "department.yaml"

# Correspondance F -> N (ADR-0009 §4), établie en UN SEUL endroit pour M5 (PLAN T1.3-c point 3) :
# F0-F2 automatique (N0-N2, le choix exact ne change aucun comportement d'approbation, même
# raisonnement que `opsys.outils.niveau_par_defaut`), F3 -> N3, F4/F5 -> N4 (engagement client),
# F6/F7 -> N5 (argent réel, jamais automatique). Les deux paliers F que M5 réalise concrètement
# aujourd'hui — l'envoi d'une facture (F4) et le paiement constaté (F6) — obtiennent chacun leur
# PROPRE outil, posé explicitement au N mappé ici (`niveau=`, plus bas) : il n'existe plus de
# demande F « libre » routée par un registre interne concurrent (voir `approbation.py`, retiré des
# outils exposés à l'agent ; rapport final de PLAN T1.3-c pour ce qui en reste).
NIVEAU_POUR_PALIER: dict[str, Niveau] = {
    "F0": Niveau.N0,
    "F1": Niveau.N1,
    "F2": Niveau.N2,
    "F3": Niveau.N3,
    "F4": Niveau.N4,
    "F5": Niveau.N4,
    "F6": Niveau.N5,
    "F7": Niveau.N5,
}
NIVEAU_ENVOI_FACTURE = NIVEAU_POUR_PALIER["F4"]  # engagement client (envoi), ADR-0009 §4
NIVEAU_PAIEMENT_FACTURE = NIVEAU_POUR_PALIER["F6"]  # argent réel constaté, ADR-0009 §4

# Registre de production des mouvements (ADR-0009) : durable dès le chargement du module. Les tests
# unitaires en mémoire le rebasculent par `reinitialiser_stockage_mouvements()`.
_stockage_durable_actif = True


def utiliser_stockage_durable() -> None:
    """Revient au registre de PRODUCTION des mouvements, adossé au stockage durable de l'instance
    (ADR-0009) : `opsys.stockage.maillons("m05-financecore", "principal")`, dans la base et la
    transaction de l'appel courant (`opsys.outils.executer_atomique`/`Capacites.appeler` en
    ouvre une autour de chaque appel d'outil). C'est l'état au chargement du module."""
    global _stockage_durable_actif
    _stockage_durable_actif = True


def reinitialiser_stockage_mouvements() -> None:
    """Revient au registre des mouvements EN MÉMOIRE (réservé aux tests) : annule un éventuel
    `utiliser_stockage_durable()`."""
    global _stockage_durable_actif
    _stockage_durable_actif = False


_MAILLON = {"type": "object", "description": "Maillon tel que renvoyé par un appel précédent."}
_HISTORIQUE_MOUVEMENTS = {
    "type": "array",
    "items": _MAILLON,
    "description": (
        "Optionnel. Fourni : simulation en mémoire sur cet historique, sans toucher au registre "
        "durable. Omis (cas normal en production) : lit/écrit le registre des mouvements de "
        "l'instance — la continuité entre appels n'a plus besoin d'être transportée par l'appelant."
    ),
}
_MONTANT_TEXTE = {
    "type": "string",
    "description": 'Montant décimal en texte, ex. "125.00" — jamais un nombre JSON (imprécision binaire).',
}
_TYPE_MOUVEMENT = {"type": "string", "enum": ["ENCAISSEMENT", "DECAISSEMENT", "PROVISION", "AJUSTEMENT", "AUTRE"]}
_CLASSE_RETENTION = {"type": "string", "enum": ["FISCALE_6_ANS", "STANDARD"]}
_LIGNE_FACTURE = {
    "type": "object",
    "properties": {
        "description": {"type": "string"},
        "quantite": _MONTANT_TEXTE,
        "unite": {"type": "string"},
        "prix_unitaire": _MONTANT_TEXTE,
        "reference_ligne_devis": {"type": "string"},
    },
    "required": ["description", "quantite", "unite", "prix_unitaire", "reference_ligne_devis"],
    "additionalProperties": False,
}
_HISTORIQUE_FACTURES = {
    "type": "array",
    "items": _MAILLON,
    "description": (
        "Optionnel. Fourni : simulation en mémoire sur cet historique, sans toucher au registre "
        "durable des factures. Omis (cas normal en production) : lit/écrit le registre des "
        "factures de l'instance."
    ),
}


def _rehydrater_facture_historique(entree: dict[str, Any]) -> dict[str, Any]:
    """Restaure les Decimal exportés en JSON, sans recalcul fiscal ni mutation de l'appelant."""
    copie = copy.deepcopy(entree)

    def decimal_fini(valeur: Any) -> Decimal:
        if isinstance(valeur, str):
            valeur = _vers_montant_decimal(valeur)
        if not isinstance(valeur, Decimal) or not valeur.is_finite():
            raise ValueError("Decimal fini requis, jamais un nombre JSON")
        return valeur

    try:
        for champ in ("montant_avant_taxes", "total_taxes", "montant_apres_taxes"):
            copie[champ] = decimal_fini(copie[champ])
        for collection, champs in (
            ("lignes", ("quantite", "prix_unitaire", "montant")),
            ("taxes", ("montant",)),
        ):
            if not isinstance(copie[collection], (list, tuple)):
                raise TypeError("collection de facture requise")
            for ligne in copie[collection]:
                if not isinstance(ligne, dict):
                    raise TypeError("ligne de facture requise")
                for champ in champs:
                    ligne[champ] = decimal_fini(ligne[champ])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("REJ-FACTURE-HISTORIQUE-INVALIDE : forme ou Decimal financier invalide") from exc
    return copie


def _rejouer_registre(historique: list[dict[str, Any]] | None) -> registre_module.Registre:
    """Reconstruit un registre M5 en rejouant l'historique fourni par l'appelant.

    Fonctionne indifféremment pour la chaîne des mouvements ou celle des
    approbations : `Registre.ajouter` distingue déjà les `type_entree`. Rejouer
    déterministe (mêmes entrées, même ordre -> mêmes hachages) : ce n'est pas une
    vérification contre une vérité externe, seulement une reconstruction fidèle.

    Frontière JSON : `opsys.outils.executer` sérialise un Decimal en texte pour la
    réponse (`vers_json`). Quand l'appelant renvoie cet historique tel quel à un
    appel suivant, le montant d'un mouvement et les champs Decimal d'une facture
    sont restaurés depuis ce texte (jamais un float intermédiaire) avant rejeu.
    """
    registre_cible = registre_module.Registre()
    for entree in historique or ():
        brut = {cle: valeur for cle, valeur in entree.items() if cle not in ("ligne_id", "precedent_ligne_id")}
        if brut.get("type_entree") == "mouvement_enregistre" and isinstance(brut.get("montant"), str):
            brut["montant"] = _vers_montant_decimal(brut["montant"])
        elif brut.get("type_entree") == "facture_creee":
            brut = _rehydrater_facture_historique(brut)
        registre_cible.ajouter(brut)
    return registre_cible


def _registre_mouvements(historique: list[dict[str, Any]] | None) -> registre_module.Registre:
    """Registre des MOUVEMENTS pour un appel.

    Un `historique` explicite (même vide, `[]`) est rejoué EN MÉMOIRE via
    `_rejouer_registre` — simulation sans effet sur le stockage durable, le
    comportement gardé par les tests unitaires de ce paquet. `None` (omis) rend le
    registre de PRODUCTION : en mémoire tant que `utiliser_stockage_durable()` n'a
    pas été appelé, adossé au stockage durable de l'instance (ADR-0009) ensuite.
    Jamais de cache ici, à dessein (même principe que `opsys.stockage.maillons`) :
    une instance fraîche à chaque appel relit l'état réel depuis la base, pour ne
    jamais figer un solde devenu périmé entre deux appels d'outil (concurrence,
    autre processus)."""
    if historique is not None:
        return _rejouer_registre(historique)
    if _stockage_durable_actif:
        return registre_module.Registre(maillons=stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_MOUVEMENTS))
    return registre_module.Registre()


def _etat_mouvements(historique: list[dict[str, Any]] | None, registre_cible: registre_module.Registre) -> dict:
    """Ce que la réponse dit du registre des mouvements. Registre durable : la tête et la taille,
    jamais tout l'historique, qui grossit sans limite et coûterait des tokens à chaque appel.
    Simulation en mémoire : l'historique complet, que l'appelant retransmet au prochain appel."""
    if historique is None and _stockage_durable_actif:
        return {"registre_mouvements": {"taille": registre_cible.taille(), "tete": registre_cible.tete()}}
    return {"mouvements_historique": registre_cible.lire()}


def _registre_factures(historique: list[dict[str, Any]] | None) -> registre_module.Registre:
    """Registre des FACTURES pour un appel — même patron d'adaptateur que `_registre_mouvements`
    (mandat T1.1-e, tâche 2), y compris la bascule `_stockage_durable_actif` déjà en place pour
    les mouvements (un seul interrupteur pour tout le module : `utiliser_stockage_durable()`/
    `reinitialiser_stockage_mouvements()` couvrent donc aussi le registre des factures)."""
    if historique is not None:
        return _rejouer_registre(historique)
    if _stockage_durable_actif:
        return registre_module.Registre(maillons=stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_FACTURES))
    return registre_module.Registre()


def _etat_factures(historique: list[dict[str, Any]] | None, registre_cible: registre_module.Registre) -> dict:
    """Même règle que `_etat_mouvements` : registre durable -> tête et taille seulement (jamais
    tout l'historique) ; simulation en mémoire -> historique complet à retransmettre."""
    if historique is None and _stockage_durable_actif:
        return {"registre_factures": {"taille": registre_cible.taille(), "tete": registre_cible.tete()}}
    return {"factures_historique": registre_cible.lire()}


def _registre_contrats_salaries() -> registre_module.Registre | None:
    """Le journal salarial est toujours durable; aucun repli en mémoire n'est permis."""
    if not _stockage_durable_actif:
        return None
    return registre_module.Registre(maillons=stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_CONTRATS_SALARIES))


def _registre_echeanciers_contrats() -> registre_module.Registre | None:
    """Journal durable propre aux échéanciers commerciaux; aucun repli en mémoire."""
    if not _stockage_durable_actif:
        return None
    return registre_module.Registre(maillons=stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_ECHEANCIERS_CONTRATS))


def _vers_montant_decimal(montant_texte: str) -> Decimal:
    if not isinstance(montant_texte, str):
        raise ValueError("montant doit être fourni en texte décimal (jamais un nombre JSON)")
    try:
        return Decimal(montant_texte)
    except InvalidOperation as exc:
        raise ValueError(f"montant décimal invalide : {montant_texte!r}") from exc


# Portée des rôles d'appareil sur les deux outils de lecture financière : la source UNIQUE, reprise
# par `Outil.roles_appareil` (plus bas) et par le contrôle de `_acteur_appareil`. §9.5 (M5, trésorerie et
# factures à approuver) : l'admin seul ; ni l'employé (§9.2) ni le vendeur (§9.4) ne voient les finances.
_ROLES_APPAREIL_FINANCE = frozenset({acces.ROLE_ADMIN})

# Les deux arguments de vue des outils de lecture financière ajoutés en T1.5-d (mêmes règles que ceux de
# `m5_etat_tresorerie`, T1.4-k2 : un argument ne peut que restreindre la vue).
_LIMITE_LECTURE_DEFAUT = 8
_LIMITE_LECTURE_MAX = 12
_ROLE_DE_LECTURE = {
    "type": ["string", "null"],
    "description": ("Appel d'appareil : omis, ou égal au rôle authentifié (sinon REJ-IDENTITE-FOURNIE-DIFFERENTE)."),
}
_AUTORISE_COUTS_DE_LECTURE = {
    "type": ["boolean", "null"],
    "description": (
        "Appel d'appareil : omis, il vaut le droit du rôle ; faux restreint (aucun montant) ; vrai sans ce "
        "droit est refusé (REJ-ROLE-ELARGI). Sans appareil (agent, console) : obligatoire et explicite."
    ),
}


def _acteur_appareil() -> tuple[acces.Acteur | None, dict[str, Any] | None]:
    """Qui appelle : ``(None, None)`` hors appel d'appareil, ``(acteur, None)`` si l'identité du jeton
    est CONFIRMÉE en base et dans la portée de l'outil, ``(None, verdict)`` sinon (PLAN T1.4-k2).

    ``contexte.identite_appelante()`` ne rend que ce que le core a transmis en `_meta` : la personne
    a pu être désactivée, ou perdre le rôle, depuis l'émission du jeton (le fragment de
    configuration du core n'est régénéré qu'à la demande). On la revérifie donc à chaque appel avec
    la même fonction que la validation humaine au départ (``approbations.signataire_valide``, T1.4-h :
    personne active portant encore ce rôle), au lieu d'une seconde règle qui pourrait diverger.
    Hors transaction (aucune base jointe), rien n'est vérifiable : refus fermé, jamais une identité
    crue sur parole. Ne lit JAMAIS les arguments de l'outil, n'écrit rien."""
    appelante = contexte.identite_appelante()
    if appelante is None:
        return None, None
    cnx = stockage.connexion_courante()
    confirmee = approbations.signataire_valide(cnx, appelante) if cnx is not None else None
    if confirmee is None:
        return None, validation.construire_verdict(
            "REJ-IDENTITE-APPAREIL-INVALIDE",
            detail=(
                f"personne {appelante.personne!r} inconnue, inactive, ou ne porte plus le rôle "
                f"{appelante.role!r} porté par le jeton d'appareil (ou identité non vérifiable "
                "hors transaction)"
            ),
        )
    return acces.acteur_de(
        confirmee.personne,
        confirmee.role,
        _ROLES_APPAREIL_FINANCE,
        source=getattr(confirmee, "source", "appareil"),
    )


def _refus(verdict: dict[str, Any]) -> dict[str, Any]:
    return {"accepte": False, "verdict": verdict}


_NOTE_ARGENT_DISPONIBLE = "solde moins les réserves posées seulement : ce n'est PAS le cash libre, lire cash_libre"
# La réponse de `m5_etat_tresorerie` est tronquée par le socle au-delà de 6 000 caractères (`jetons`) : un cash libre
# coupé au milieu serait pire qu'un cash libre plus court. Au-delà de ce budget (enveloppe et marge déduites), la
# réponse perd d'abord ses hypothèses (fixes, dites dans la description de l'outil, le SKILL et le SOUL de M5), puis
# le détail des composantes ; jamais un montant, une source, une fraîcheur, un manque ni la mention.
_BUDGET_ETAT_TRESORERIE = BUDGET_SORTIE - 500


def _borner_etat(etat: dict[str, Any]) -> dict[str, Any]:
    """`etat` tel quel s'il tient sous `_BUDGET_ETAT_TRESORERIE` ; sinon sans les hypothèses (`hypotheses_omises` dit
    combien), puis sans le détail des composantes (`detail_omis`). Ne touche à rien d'autre."""

    def taille(candidat: dict[str, Any]) -> int:
        return len(json.dumps(candidat, ensure_ascii=False, default=str))

    cash = etat.get("cash_libre")
    if cash is None or taille(etat) <= _BUDGET_ETAT_TRESORERIE:
        return etat
    cash = {**cash, "hypotheses": [], "hypotheses_omises": len(cash["hypotheses"])}
    reduit = {**etat, "cash_libre": cash}
    if taille(reduit) <= _BUDGET_ETAT_TRESORERIE:
        return reduit
    composantes = [{cle: valeur for cle, valeur in c.items() if cle != "detail"} for c in cash["composantes"]]
    return {**etat, "cash_libre": {**cash, "composantes": composantes, "detail_omis": True}}


def etat_tresorerie(
    role: str | None = None,
    autorise_couts: bool | None = None,
    mouvements_historique: list[dict[str, Any]] | None = None,
    taux_utilises: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Composé de bout en bout : obtient le registre des mouvements (§`_registre_mouvements`), calcule solde + argent
    disponible (solde moins réserves) et, PLAN T4.16, le CASH LIBRE RÉEL avec sa décomposition, filtre par rôle.

    `argent_disponible` garde son sens (CA-M5-06 : solde moins les réserves) et sa place, mais il n'est plus jamais
    affiché seul : `cash_libre` l'accompagne à chaque fois qu'un montant est montré (`_cash_libre`, `cash_libre.py`),
    et `argent_disponible_note` dit que ce n'est pas le cash libre. Un rôle sans droit de voir les coûts ne voit ni
    l'un ni l'autre (`cash_libre` est `None`). Ajout ADDITIF : aucune clé de l'état financier gelé n'est changée,
    `etat_id` non plus. La mention obligatoire des analyses est portée par la réponse.

    Pour un appel d'appareil (PLAN T1.4-k2), la vue vient du rôle authentifié et CONFIRMÉ en base
    (`_acteur_appareil`, `acces.resoudre_vue`) : `autorise_couts` est dérivé du rôle, un argument
    ne peut que la restreindre, `role` ne peut pas contredire le jeton. Un refus est un verdict nommé
    (`{"accepte": False, "verdict": ...}`), rendu AVANT de lire le registre ; la réponse d'un accord
    garde sa forme d'avant.

    Sans identité d'appareil (agent, console) : `autorise_couts` reste OBLIGATOIRE et explicite
    (fail-closed, absent = `REJ-AUTORISE-COUTS-REQUIS`) : aucune valeur par défaut n'expose jamais une
    donnée financière."""
    acteur, refus = _acteur_appareil()
    if refus is not None:
        return _refus(refus)
    vue, verdict = acces.resoudre_vue(acteur, role, autorise_couts)
    if verdict is not None:
        return _refus(verdict)
    registre_cible = _registre_mouvements(mouvements_historique)
    etat = etat_financier.construire_etat_financier(
        registre_cible, taux_utilises or [], role=vue["role"], autorise_couts=vue["autorise_couts"]
    )
    if vue["autorise_couts"]:
        etat = {**etat, "argent_disponible_note": _NOTE_ARGENT_DISPONIBLE, "cash_libre": _cash_libre(registre_cible)}
    else:
        etat = {**etat, "cash_libre": None}
    return _borner_etat(analyse.avec_mention(etat))


def calculer_taxes_tps_tvq(montant_avant_taxes: str) -> dict[str, Any]:
    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(_CHEMIN_TAUX_FISCAUX)
    if erreurs:
        return {"accepte": False, "verdict": {"code": "REJ-TAUX-FICHIER-INVALIDE", "detail": "; ".join(erreurs)}}
    resultat, verdict = taxes.calculer_taxes(_vers_montant_decimal(montant_avant_taxes), dictionnaire)
    return depuis_couple((resultat, verdict))


def enregistrer_mouvement(
    montant: str,
    type_mouvement: str,
    horodatage: str,
    classe_retention: str,
    source: str,
    mouvements_historique: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    registre_cible = _registre_mouvements(mouvements_historique)
    mouvement = {
        "montant": _vers_montant_decimal(montant),
        "type_mouvement": type_mouvement,
        "horodatage": horodatage,
        "classe_retention": classe_retention,
        "source": source,
    }
    maillons_mouvements = None
    if mouvements_historique is None and _stockage_durable_actif:
        # Le candidat et la réponse portent le même préfixe accepté. Une
        # écriture intercalée doit faire annuler l'appel, sans réparer la source.
        try:
            copie = registre_module.Registre(maillons=registre_cible.lire())
            valide, _ = copie.valider_chaine()
        except (AttributeError, KeyError, TypeError, ValueError, RecursionError):
            valide = False
        if valide is not True:
            raise ValueError("REJ-MOUVEMENT-CHAINE-INVALIDE : vérifier le journal M5 avant ajout")
        registre_cible = copie
        maillons_mouvements = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_MOUVEMENTS)
    try:
        maillon = registre_module.enregistrer_mouvement(mouvement, registre_cible)
        if maillons_mouvements is not None:
            maillons_mouvements.append(maillon, rang_attendu=registre_cible.taille() - 1)
    except validation.MouvementInvalide as exc:
        return {"accepte": False, "verdict": exc.verdict}
    return {"accepte": True, "resultat": maillon, **_etat_mouvements(mouvements_historique, registre_cible)}


def creer_facture_brouillon(
    facture_id: str,
    chantier_id: str,
    devis_id: str,
    client_id: str,
    lignes: list[dict[str, Any]],
    horodatage: str,
    montant_avant_taxes: str | None = None,
    factures_historique: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    dictionnaire_taux, erreurs = taux_fiscaux.charger_taux_fiscaux(_CHEMIN_TAUX_FISCAUX)
    if erreurs:
        return {"accepte": False, "verdict": {"code": "REJ-TAUX-FICHIER-INVALIDE", "detail": "; ".join(erreurs)}}
    registre_cible = _registre_factures(factures_historique)
    maillons_factures = None
    if factures_historique is None and _stockage_durable_actif:
        # L'outil direct crée sur un préfixe validé ; les consommateurs ont
        # leur propre chemin, hors de cette frontière d'écriture.
        try:
            copie = registre_module.Registre(maillons=registre_cible.lire())
            valide, _ = copie.valider_chaine()
        except (AttributeError, KeyError, TypeError, ValueError, RecursionError):
            valide = False
        if valide is not True:
            raise ValueError("REJ-FACTURE-CHAINE-INVALIDE : vérifier le journal M5 avant ajout")
        registre_cible = copie
        maillons_factures = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_FACTURES)
        taille_initiale = registre_cible.taille()
    resultat, verdict = facturation.creer_facture_brouillon(
        facture_id=facture_id,
        chantier_id=chantier_id,
        devis_id=devis_id,
        client_id=client_id,
        lignes=lignes,
        horodatage=horodatage,
        dictionnaire_taux=dictionnaire_taux,
        registre_cible=registre_cible,
        montant_avant_taxes_fourni=montant_avant_taxes,
    )
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    if maillons_factures is not None and registre_cible.taille() != taille_initiale:
        maillons_factures.append(resultat, rang_attendu=taille_initiale)
    return {"accepte": True, "resultat": resultat, **_etat_factures(factures_historique, registre_cible)}


def _essayer_facture_brouillon(devis_id: str) -> dict[str, Any]:
    """Fonction UNIQUE qui tente de créer la facture BROUILLON pour ce devis_id (PLAN T1.2-d,
    suite). Les deux consommateurs ci-dessous l'appellent avec le MÊME devis_id dès qu'ils
    viennent de garder leur propre pièce (`devis_recus.py`/`wct_recus.py`), quel que soit l'ordre
    d'arrivée entre `m3.devis_accepte` et `m4.travaux_termines` — jamais de calcul différent selon
    qui a déclenché l'appel (même patron que M6 `_evaluer_et_publier_variance`, PLAN T1.2-b).
    Appelable SEULEMENT dans la transaction du répartiteur (`stockage.maillons` y fait autorité).

    Fail-closed, jamais une facture inventée : devis inconnu, complétion inconnue, ou
    `chantier_id` absent du devis (nul ou vide) rendent un statut d'attente nommé (`en_attente_*`)
    — états normaux du flux réel (R12 §4/§9.7), jamais une panne. `lister_attentes_facturation`
    recalcule ces mêmes statuts EN DIRECT pour l'outil T0, sans rien stocker de plus ici.

    Idempotent : une facture déjà active pour ce devis_id (`facturation.facture_active_pour_devis`)
    court-circuite AVANT toute tentative de création — couvre la redélivrance de l'un ou l'autre
    événement, la double publication du même devis, et le second appel de cette fonction quand les
    deux pièces sont déjà connues (chaque consommateur rappelle systématiquement cette fonction).

    Incohérence interne (ex. taux fiscal illisible, ou `prix_total` du devis qui ne concorde pas
    avec la somme recalculée des lignes) : LÈVE. `creer_facture_brouillon` a déjà validé la forme
    de chaque ligne et le total à la source (M3, `devis_durable.py`) ; un refus ici trahirait une
    incohérence entre départements, jamais un cas d'usage normal — mieux vaut une panne explicite
    (réessais puis quarantaine par le répartiteur) qu'une facture fabriquée ou un statut inventé
    pour un cas qu'on n'a pas su nommer.
    """
    devis_recu = devis_recus.pour_devis_id(devis_id, stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_DEVIS_RECUS))
    if devis_recu is None:
        return {"traite": True, "devis_id": devis_id, "statut": "en_attente_devis_accepte"}

    wct_recu = wct_recus.pour_devis_id(devis_id, stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_WCT_RECUS))
    if wct_recu is None:
        return {"traite": True, "devis_id": devis_id, "statut": "en_attente_travaux_termines"}

    chantier_id = devis_recu.get("chantier_id")
    if not isinstance(chantier_id, str) or not chantier_id.strip():
        return {"traite": True, "devis_id": devis_id, "statut": "en_attente_chantier_id"}

    registre_cible = _registre_factures(None)
    if facturation.facture_active_pour_devis(registre_cible, devis_id) is not None:
        return {"traite": True, "devis_id": devis_id, "statut": "facture_deja_existante"}

    dictionnaire_taux, erreurs = taux_fiscaux.charger_taux_fiscaux(_CHEMIN_TAUX_FISCAUX)
    if erreurs:
        raise RuntimeError(f"taux fiscaux illisibles ({_CHEMIN_TAUX_FISCAUX}) : {'; '.join(erreurs)}")

    lignes = [
        {
            "description": ligne["description"],
            "quantite": ligne["quantite"],
            "unite": ligne["unite"],
            "prix_unitaire": ligne["prix_unitaire"],
            "reference_ligne_devis": ligne["reference_ligne"],
        }
        for ligne in devis_recu["lignes"]
    ]

    # PLAN T2.2 (Client 360 de M2) : client_id RÉEL si M5 a déjà reçu m2.client_associe pour ce
    # lead (clients_recus.py) ; sinon repli sur lead_id, EXACTEMENT le comportement historique
    # d'avant ce correctif — jamais bloquant (voir docstring du module) et jamais une valeur
    # inventée (lead_id est une donnée réelle, portée telle quelle depuis M3/M2).
    client_recu = clients_recus.pour_lead_id(
        devis_recu["lead_id"], stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_CLIENTS_RECUS)
    )
    client_id = client_recu["client_id"] if client_recu is not None else devis_recu["lead_id"]

    resultat, verdict = facturation.creer_facture_brouillon(
        facture_id=f"fac-{devis_id}",
        chantier_id=chantier_id,
        devis_id=devis_id,
        client_id=client_id,
        lignes=lignes,
        horodatage=wct_recu["horodatage_completion"],
        dictionnaire_taux=dictionnaire_taux,
        registre_cible=registre_cible,
        montant_avant_taxes_fourni=devis_recu["prix_total"],
    )
    if verdict is not None:
        if verdict["code"] == "REJ-FACTURE-DEVIS-DEJA-FACTURE":
            return {"traite": True, "devis_id": devis_id, "statut": "facture_deja_existante"}
        raise RuntimeError(f"creer_facture_brouillon a refusé une entrée déjà validée par M3 : {verdict}")

    return {
        "traite": True,
        "devis_id": devis_id,
        "statut": "facture_creee",
        "facture_id": resultat["facture_id"],
    }


def _taux_horaire_configure() -> Any:
    """`department.yaml/configuration.taux_horaire_main_d_oeuvre` tel que l'entreprise l'a écrit, ou `None`.

    Relu à chaque appel (comme M6 pour ses seuils) : Nathan change le taux sans redémarrer. Un manifeste
    illisible ou sans ce champ rend `None` : `cout_reel.valider_taux_horaire` en fait le verdict « taux
    horaire à configurer », jamais un taux par défaut. La valeur brute est rendue (validée plus loin)."""
    try:
        donnees = yaml.safe_load(_MANIFESTE.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    configuration = donnees.get("configuration") if isinstance(donnees, dict) else None
    return configuration.get("taux_horaire_main_d_oeuvre") if isinstance(configuration, dict) else None


def _livre_de_prix_m6() -> tuple[dict[str, Any], ...]:
    """Les entrées du livre de prix de M6, en LECTURE SEULE (copie ; aucun `append`, aucune écriture)."""
    maillons = stockage.maillons(_DEPARTEMENT_LIVRE_DE_PRIX, _NOM_REGISTRE_LIVRE_DE_PRIX)
    return tuple(dict(entree) for entree in maillons if isinstance(entree, Mapping))


def _sources_cout_reel() -> dict[str, Any]:
    """Lit UNE fois chaque source du coût réel (PLAN T1.5-d) : les registres reçus (devis, WCT, variance), la
    facture ACTIVE de chaque devis, le livre de prix de M6, le taux horaire configuré et le dernier état tracé de
    chaque devis. Lire une fois (et non à chaque devis) garde une liste de chantiers linéaire, pas quadratique."""
    traces: dict[str, dict[str, Any]] = {}
    nombre_de_traces: dict[str, int] = {}
    for maillon in stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_RENTABILITE):
        traces[maillon.get("devis_id")] = maillon  # le dernier écrit fait foi
        nombre_de_traces[maillon.get("devis_id")] = nombre_de_traces.get(maillon.get("devis_id"), 0) + 1
    return {
        "devis": list(stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_DEVIS_RECUS)),
        "wct": list(stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_WCT_RECUS)),
        "variance": list(stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_VARIANCE_RECUE)),
        "factures": facturation.factures_actives_par_devis(_registre_factures(None)),
        "livre": _livre_de_prix_m6(),
        "taux": _taux_horaire_configure(),
        "traces": traces,
        "nombre_de_traces": nombre_de_traces,
    }


def _etat_chantier(devis_id: str, sources: dict[str, Any] | None = None) -> dict[str, Any]:
    """L'état de coût réel et de rentabilité d'un devis, CALCULÉ à l'instant depuis les pièces lues à la
    source (PLAN T1.5-d) : le devis accepté et le WCT reçus du bus, le dernier signal de variance de M6,
    la facture active du devis, le livre de prix de M6 et le taux horaire configuré. N'écrit RIEN.

    Fonction UNIQUE, partagée par la cascade (`_essayer_cout_reel`, qui trace) et par l'outil de lecture (qui
    ne trace pas) : les deux ne peuvent pas diverger. Sans devis reçu ou sans WCT reçu, il n'y a rien à
    calculer : un statut d'attente nommé (mêmes noms que `lister_attentes_facturation`), jamais une valeur."""
    sources = _sources_cout_reel() if sources is None else sources
    devis_recu = devis_recus.pour_devis_id(devis_id, sources["devis"])
    if devis_recu is None:
        return {"statut": "en_attente_devis_accepte", "devis_id": devis_id, "chantier_id": None}
    chantier_devis = devis_recu.get("chantier_id")
    wct_recu = wct_recus.pour_devis_id(devis_id, sources["wct"])
    if wct_recu is None:
        return {
            "statut": "en_attente_travaux_termines",
            "devis_id": devis_id,
            "chantier_id": chantier_devis or None,
        }
    autres_wct = {
        m.get("wct_id")
        for m in sources["wct"]
        if m.get("devis_id") == devis_id and m.get("wct_id") not in (None, wct_recu["wct_id"])
    }
    signal = variance_recus.signal_retenu_pour_wct_id(wct_recu["wct_id"], sources["variance"])
    cout = cout_reel.calculer_cout_reel(wct_recu, signal, sources["livre"], sources["taux"], autres_wct)
    chantier_id = chantier_devis or (signal.get("chantier_id") if signal is not None else None) or None
    rentabilite = cout_reel.calculer_rentabilite(
        cout, sources["factures"].get(devis_id), devis_recu, devis_id=devis_id, chantier_id=chantier_id
    )
    return {
        "statut": "calculee",
        "devis_id": devis_id,
        "chantier_id": chantier_id,
        "rentabilite": rentabilite,
        "horodatage": wct_recu["horodatage_completion"],
    }


def _essayer_cout_reel(devis_id: str) -> dict[str, Any]:
    """Étape de la cascade « travaux terminés » (DEFINITION-PRODUIT §6, M5 « calcule le coût réel [...] et la
    rentabilité du chantier ») : calcule l'état de ce devis et le TRACE dans le registre `rentabilite`.

    Appelée par les consommateurs qui apportent une pièce (devis accepté, WCT, variance M6), dans la
    transaction du répartiteur, quel que soit l'ordre d'arrivée : la dernière pièce à arriver produit l'état
    complet. Écrit UNIQUEMENT dans le registre dérivé `rentabilite` (append-only) : ni le grand livre, ni le
    registre des factures, ni les comptes à recevoir (une vue). Idempotente par devis ET version des entrées :
    un rejeu, ou une pièce qui ne change aucune entrée du calcul, n'ajoute aucun maillon ; une entrée qui change
    (prix du livre, taux, facture envoyée...) en ajoute un, l'historique restant intact.

    Chaque maillon ajouté est publié dans la MÊME transaction (`m5.rentabilite_chantier`, `_publier_rentabilite`) :
    M8 et M10 apprennent la marge réelle (ou ce qui manque pour la chiffrer) au moment où M5 la trace, pas avant,
    pas ailleurs. Un rejeu (`deja_tracee`) ne publie rien.

    Ne lève pas sur une pièce mal formée (elle devient un manque du coût, voir `cout_reel.py`) : la création de
    la facture, faite dans la même transaction, ne dépend jamais de ce calcul. Seule la publication peut lever, et
    seulement si la charge n'était pas conforme au catalogue du socle (un défaut du code, jamais une pièce)."""
    sources = _sources_cout_reel()
    etat = _etat_chantier(devis_id, sources)
    if etat["statut"] != "calculee":
        return {"statut": etat["statut"]}
    rentabilite = etat["rentabilite"]
    trace = sources["traces"].get(devis_id)
    if trace is not None and trace.get("version_entrees") == rentabilite["version_entrees"]:
        return {"statut": "deja_tracee"}
    stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_RENTABILITE).append(
        cout_reel.construire_trace(rentabilite, etat["horodatage"])
    )
    _publier_rentabilite(rentabilite, sources["nombre_de_traces"].get(devis_id, 0) + 1, etat["horodatage"])
    return {"statut": "tracee"}


def _publier_rentabilite(rentabilite: dict[str, Any], sequence: int, horodatage: Any) -> None:
    """Publie `m5.rentabilite_chantier` pour la trace qui vient d'être ajoutée, dans la transaction courante (le
    répartiteur, seul appelant de la cascade : la trace et l'événement réussissent ou échouent ensemble).

    La charge est une liste blanche (`cout_reel.charge_evenement`) que le catalogue du socle valide à la
    publication, schéma fermé compris : une charge qui n'y tient pas LÈVE (`ChargeInvalide`), le répartiteur
    réessaie puis met en quarantaine, visible d'un humain. Mieux vaut cette panne qu'une marge publiée pour un
    coût partiel. L'identifiant est déterministe (devis, rang de la trace, version des entrées) : republier la
    même trace est un no-op du bus."""
    charge = cout_reel.charge_evenement(rentabilite, sequence, horodatage)
    evenements.publier(cout_reel.TYPE_EVENEMENT_RENTABILITE, _DEPARTEMENT, charge, evenement_id=charge["evenement_id"])


def _essayer_cout_reel_pour_wct(wct_id: str) -> dict[str, Any]:
    """Comme `_essayer_cout_reel`, depuis un `wct_id` (le signal de variance ne connaît que lui) : le WCT
    reçu donne le `devis_id`. WCT inconnu ou sans devis : un statut d'attente nommé, rien n'est tracé."""
    wct_recu = wct_recus.pour_wct_id(wct_id, stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_WCT_RECUS))
    if wct_recu is None:
        return {"statut": "en_attente_travaux_termines"}
    if wct_recu["devis_id"] is None:
        return {"statut": "wct_sans_devis_id"}
    return _essayer_cout_reel(wct_recu["devis_id"])


def _recevoir_devis_accepte(charge: dict[str, Any]) -> dict[str, Any]:
    """Consomme `m3.devis_accepte` : garde ce que M5 a reçu de ce devis (`devis_recus.py`,
    idempotent par devis_id), puis délègue toute la décision de facturer à
    `_essayer_facture_brouillon`, fonction UNIQUE partagée avec `_recevoir_travaux_termines`."""
    devis_id = charge["devis_id"]
    registre = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_DEVIS_RECUS)
    if devis_recus.pour_devis_id(devis_id, registre) is None:
        registre.append(
            devis_recus.construire(
                devis_id=devis_id,
                lead_id=charge["lead_id"],
                chantier_id=charge["chantier_id"],
                lignes=charge["lignes"],
                prix_total=charge["prix_total"],
                horodatage_acceptation=charge["horodatage_acceptation"],
                cout_total=charge.get("cout_total"),
                taux_marge=charge.get("taux_marge"),
            )
        )
    resultat = _essayer_facture_brouillon(devis_id)
    return {**resultat, "cout_reel": _essayer_cout_reel(devis_id)["statut"]}


def _recevoir_travaux_termines(charge: dict[str, Any]) -> dict[str, Any]:
    """Consomme `m4.travaux_termines` : garde ce que M5 a reçu de ce WCT (`wct_recus.py`,
    idempotent par wct_id — y compris quand `devis_id` est nul, pour que
    `lister_attentes_facturation` puisse le signaler), puis délègue à
    `_essayer_facture_brouillon` SEULEMENT si `devis_id` est connu : une intervention inscrite
    sans devis n'a rien à joindre, jamais deviné (fail-closed, PLAN T1.2-d)."""
    wct_id = charge["wct_id"]
    registre = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_WCT_RECUS)
    wct_recu = wct_recus.pour_wct_id(wct_id, registre)
    if wct_recu is None:
        wct_recu = wct_recus.construire(
            wct_id=wct_id,
            intervention_id=charge["intervention_id"],
            devis_id=charge.get("devis_id"),
            horodatage_completion=charge["horodatage_completion"],
            duree_reelle_minutes=charge.get("duree_reelle_minutes"),
        )
        registre.append(wct_recu)
    if wct_recu["devis_id"] is None:
        return {"traite": True, "wct_id": wct_id, "statut": "wct_sans_devis_id"}
    resultat = _essayer_facture_brouillon(wct_recu["devis_id"])
    return {**resultat, "cout_reel": _essayer_cout_reel(wct_recu["devis_id"])["statut"]}


def lister_attentes_facturation() -> dict[str, Any]:
    """Outil T0 compact : liste les devis/WCT en attente d'une facture BROUILLON (T1.3 s'en
    servira pour la file d'approbation du propriétaire). Recalculée EN DIRECT depuis les
    registres reçus (`devis_recus.py`, `wct_recus.py`) et celui des factures à CHAQUE appel — le
    même état que `_essayer_facture_brouillon` recalculerait pour chaque devis_id, sans effet de
    bord ni troisième registre d'« attentes » à tenir synchronisé à part."""
    devis_recus_registre = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_DEVIS_RECUS)
    wct_recus_registre = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_WCT_RECUS)
    factures_registre = _registre_factures(None)

    devis_ids_connus = {maillon["devis_id"] for maillon in devis_recus_registre}
    devis_ids_connus |= {maillon["devis_id"] for maillon in wct_recus_registre if maillon.get("devis_id") is not None}

    attentes_devis: list[dict[str, Any]] = []
    for devis_id in sorted(devis_ids_connus):
        if facturation.facture_active_pour_devis(factures_registre, devis_id) is not None:
            continue
        devis_recu = devis_recus.pour_devis_id(devis_id, devis_recus_registre)
        if devis_recu is None:
            attentes_devis.append({"devis_id": devis_id, "statut": "en_attente_devis_accepte"})
            continue
        wct_recu = wct_recus.pour_devis_id(devis_id, wct_recus_registre)
        if wct_recu is None:
            attentes_devis.append({"devis_id": devis_id, "statut": "en_attente_travaux_termines"})
            continue
        chantier_id = devis_recu.get("chantier_id")
        if not isinstance(chantier_id, str) or not chantier_id.strip():
            attentes_devis.append({"devis_id": devis_id, "statut": "en_attente_chantier_id"})

    attentes_wct_sans_devis_id = [
        {"wct_id": maillon["wct_id"], "intervention_id": maillon["intervention_id"], "statut": "wct_sans_devis_id"}
        for maillon in wct_recus_registre
        if maillon.get("devis_id") is None
    ]

    return {"attentes_devis": attentes_devis, "attentes_wct_sans_devis_id": attentes_wct_sans_devis_id}


def lister_attentes_facturation_appareil() -> dict[str, Any]:
    """L'outil `m5_lister_attentes_facturation` : la même liste, précédée de l'identité (PLAN
    T1.4-k2). Un appel d'appareil doit venir d'une personne confirmée en base dans la portée de l'outil
    (admin) : une personne désactivée, ou qui a perdu le rôle depuis l'appairage, ne lit plus rien.
    Sans identité d'appareil (agent, console) : la liste, comme avant. `attentes()` (file du
    propriétaire) et les tests appellent `lister_attentes_facturation` directement, sans ce contrôle."""
    _acteur, refus = _acteur_appareil()
    if refus is not None:
        return _refus(refus)
    return lister_attentes_facturation()


# --------------------------------------------------------------------------------- comptes à payer (T4.15)
def _registre_comptes_a_payer() -> registre_module.Registre:
    """Le registre DÉDIÉ des comptes à payer (`comptes_a_payer.py`), sur le stockage durable de l'instance, relu à
    chaque appel (jamais de cache : même principe que `_registre_mouvements`). Ni le registre des mouvements, ni celui
    des factures clients : `conformite.verifier_aucun_decaissement` garde cette frontière."""
    return registre_module.Registre(maillons=stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_COMPTES_A_PAYER))


def _dictionnaire_taux(*, contenu_octets: bytes | None = None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Les taux fiscaux versionnés, ou le refus nommé d'un fichier illisible (même verdict que les autres outils)."""
    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(_CHEMIN_TAUX_FISCAUX, contenu_octets=contenu_octets)
    if erreurs:
        return None, {"code": "REJ-TAUX-FICHIER-INVALIDE", "detail": "; ".join(erreurs)}
    return dictionnaire, None


def _recevoir_reception_enregistree(charge: dict[str, Any]) -> dict[str, Any]:
    """Consomme `m6.reception_enregistree` (PLAN T4.15) : range la réception au registre des comptes à payer, une
    seule fois par `evenement_id`. C'est ce qui donne à M5 son « à payer ATTENDU » par PO reçu, cumulé sur les
    livraisons.

    LÈVE si la charge ne tient pas debout (`REJ-AP-RECEPTION-INVALIDE`) ou si le PO est déjà connu sous un autre
    fournisseur ou un autre chantier (`REJ-AP-PO-INCOHERENT`) : le répartiteur réessaie puis met en quarantaine,
    visible d'un humain, plutôt que de devoir de l'argent à un fournisseur mal compris. Un prix du PO absent ou une
    devise autre que CAD ne lève PAS : c'est un `manque` de la réception, dont le montant attendu reste « non
    calculable ». N'écrit JAMAIS au registre des mouvements : rien ne sort de la caisse."""
    entree, verdict = comptes_a_payer.construire_reception(charge)
    if verdict is not None:
        raise ValueError(f"m6.reception_enregistree refusée : {verdict['code']} : {verdict['detail']}")
    resultat, verdict = comptes_a_payer.enregistrer_reception(entree, _registre_comptes_a_payer())
    if verdict is not None:
        raise ValueError(f"m6.reception_enregistree refusée : {verdict['code']} : {verdict['detail']}")
    maillon, deja_recue = resultat
    return {
        "traite": True,
        "evenement_id": maillon["evenement_id"],
        "po_id": maillon["po_id"],
        "statut": "deja_recue" if deja_recue else "recue",
        "attendu_complet": maillon["montant_avant_taxes"] is not None,
        "manque": list(maillon["manque"]),
    }


# Rôles qui peuvent avoir APPROUVÉ une saisie de facture fournisseur dans la file (`department.yaml/approbations.n3`,
# plus l'admin, dont l'appareil exécute lui-même) : la personne doit être ACTIVE et porter ce rôle à l'instant de
# l'appel.
_ROLES_APPROBATEURS_SAISIE = frozenset({"finance", "nathan_owner", acces.ROLE_ADMIN})
# PLAN T4.15-c : corriger ou annuler une facture fournisseur est un N4 (engagement : écriture finale sur une dépense,
# ADR-0009 §4), décidé par les rôles de `department.yaml/approbations.n4`. Le code les répète ici (un test les lie au
# manifeste) : la voie de l'appareil n'est JAMAIS plus large que la file. Un `admin` qui n'est ni le propriétaire ni
# la finance ne corrige ni n'annule rien, même par la voie directe (mode `autonome`, où un N4 s'exécute sans file).
_ROLES_APPROBATEURS_N4 = frozenset({"finance", "nathan_owner"})
NIVEAU_CORRECTION_FACTURE_FOURNISSEUR = Niveau.N4
_OUTIL_SAISIE_FACTURE = "m5_saisir_facture_fournisseur"
_OUTIL_SAISIE_SANS_PO = "m5_saisir_facture_sans_po"
_OUTIL_CORRECTION_FACTURE = "m5_corriger_facture_fournisseur"
_OUTIL_ANNULATION_FACTURE = "m5_annuler_facture_fournisseur"
_REFUS_HUMAIN_SAISIE = (
    "une facture fournisseur est saisie par un humain : depuis l'app admin (jeton d'appareil), ou proposée puis "
    "approuvée dans la file OPSYS (finance ou propriétaire). Un agent ne la saisit pas seul ; ne la présente pas comme "
    "saisie."
)
_REFUS_HUMAIN_SAISIE_SANS_PO = (
    "une facture fournisseur sans PO est saisie par un humain : depuis l'app admin (jeton d'appareil), ou proposée "
    "puis approuvée dans la file OPSYS (finance ou propriétaire). Un agent ne la saisit pas seul ; ne la présente pas "
    "comme saisie."
)
_REFUS_HUMAIN_N4 = (
    "corriger ou annuler une facture fournisseur est un engagement (N4) fait par un humain : proposé puis approuvé "
    "dans la file OPSYS (finance ou propriétaire), ou fait depuis l'app par une personne de rôle propriétaire ou "
    "finance (jeton d'appareil). Un agent ne le fait pas seul ; ne le présente pas comme fait."
)


def _acteur_humain(
    nom_outil: str,
    refus_humain: str,
    *,
    roles_approbateurs: frozenset[str],
    personne_doit_porter: frozenset[str] | None = None,
) -> tuple[dict[str, str] | None, dict[str, Any] | None]:
    """Qui agit : `({par, role, voie}, None)` si c'est un humain identifié, sinon `(None, verdict)`.

    Deux voies, jamais une troisième, et jamais un texte de modèle ni un argument :
    1. un appel d'appareil dont l'identité (posée par le core d'après un jeton vérifié, `_meta`) est CONFIRMÉE en base à
       l'instant même et de rôle `admin` (`_acteur_appareil`). `personne_doit_porter` (les outils N4) exige en plus que
       la PERSONNE porte l'un de ces rôles (`REJ-AP-APPROBATEUR-REQUIS` sinon) : le rôle du jeton ne dit pas qui est le
       propriétaire (un gestionnaire porte aussi `admin`) ;
    2. l'exécution d'une demande qu'un humain vient d'approuver dans la file : le SOCLE dit qui l'a approuvée
       (`approbations.approbateur_en_cours`, revérifié en base : personne active portant encore ce rôle, jamais celui
       d'un agent), et `roles_approbateurs` peut être plus strict que la politique du département.
    Tout le reste est refusé (`refus_humain`) : un appel d'agent qui n'a pas passé par l'approbation (un département en
    mode `supervise` ou `autonome` exécute un N3, ou un N4 en `autonome`, sans file), un appel en ligne de commande,
    un appel hors transaction où rien n'est vérifiable. Une identité d'appareil invalide ou hors portée est le refus de
    `_acteur_appareil`, jamais un repli sur la voie 2. Ne lit JAMAIS les arguments comme identité."""
    acteur, refus = _acteur_appareil()
    if refus is not None:
        return None, refus
    cnx = stockage.connexion_courante()
    if acteur is not None:
        if personne_doit_porter is not None:
            personne = identite.personne_active(cnx, acteur.personne) if cnx is not None else None
            if personne is None or not personne.roles & personne_doit_porter:
                return None, validation.construire_verdict(
                    "REJ-AP-APPROBATEUR-REQUIS",
                    detail=(
                        f"{acteur.personne!r} n'est ni propriétaire ni finance : ce geste engage l'entreprise (N4) et "
                        f"se décide par {' ou '.join(sorted(personne_doit_porter))}. Proposer la demande : elle attend "
                        "dans la file OPSYS."
                    ),
                )
        return {"par": acteur.personne, "role": acteur.role, "voie": "appareil"}, None
    approbateur = approbations.approbateur_en_cours(cnx, nom_outil, _DEPARTEMENT, roles=roles_approbateurs)
    if approbateur is not None:
        return {"par": approbateur.personne, "role": approbateur.role, "voie": "approbation"}, None
    return None, validation.construire_verdict("REJ-AP-HUMAIN-REQUIS", detail=refus_humain)


def _horodatage_faisant_foi(horodatage: str) -> str:
    """Pendant un appel d'appareil idempotent, l'heure de RÉCEPTION du serveur fait foi, jamais l'horloge de l'appareil
    ni l'`horodatage` fourni (même patron que M10 et `m4_pointer`). Par la file d'approbation, il n'y a pas d'appel
    d'appareil à l'exécution : l'`horodatage` enregistré avec la demande sert."""
    reception = contexte.horodatage_reception()
    return reception.recu_le.isoformat() if reception is not None else horodatage


def _suite_de_la_facture(
    facture: Mapping[str, Any], registre_cible: registre_module.Registre, dictionnaire_taux: dict[str, Any]
) -> dict[str, Any]:
    """Ce que la réponse d'une écriture sur une facture ajoute à la facture elle-même : pour une facture d'un PO, le
    rapprochement PROPOSÉ de ce PO (jamais appliqué) ; pour une facture sans PO, ce que les factures sans PO valent en
    tout. Les taux ont déjà servi à l'écriture : un refus ici trahirait une incohérence interne."""
    if facture["po_id"] is None:
        return {"sans_po": comptes_a_payer.totaux_sans_po(registre_cible)}
    rapprochement, verdict = comptes_a_payer.proposer_rapprochement(registre_cible, dictionnaire_taux, facture["po_id"])
    if verdict is not None:
        raise RuntimeError(f"rapprochement impossible pour une facture déjà écrite : {verdict}")
    return {"rapprochement": rapprochement}


def _reponse_facture(
    resultat: dict[str, Any], registre_cible: registre_module.Registre, dictionnaire_taux: dict[str, Any]
) -> dict[str, Any]:
    return {
        "accepte": True,
        "resultat": analyse.avec_mention(
            {
                "facture": comptes_a_payer.vue_facture(resultat["facture"]),
                "avertissements": resultat["avertissements"],
                **_suite_de_la_facture(resultat["facture"], registre_cible, dictionnaire_taux),
            }
        ),
    }


def saisir_facture_fournisseur(
    po_id: str,
    fournisseur_id: str,
    numero_facture: str,
    date_facture: str,
    montant_avant_taxes: str,
    total_facture: str | None,
    horodatage: str,
    *,
    contenu_taux: bytes | None = None,
) -> dict[str, Any]:
    """L'outil `m5_saisir_facture_fournisseur` (T1, N3, `admin`) : range une facture fournisseur SAISIE par un humain
    contre un PO déjà reçu (`comptes_a_payer.saisir_facture_fournisseur`), et rend la facture, ses avertissements et
    le rapprochement PROPOSÉ du PO.

    Tous les paramètres sont requis (`total_facture` peut être nul) : la demande approuvée rejoue les arguments EXACTS
    enregistrés. Les taxes et le total après taxes ne sont JAMAIS des arguments : ils sont recalculés (taux
    versionnés). Pendant un appel d'appareil idempotent, l'heure de RÉCEPTION du serveur fait foi, jamais l'`horodatage`
    fourni (même patron que M10).

    N'écrit qu'au registre des comptes à payer. Aucun DECAISSEMENT, aucune écriture aux mouvements : payer est N5."""
    acteur, refus = _acteur_humain(
        _OUTIL_SAISIE_FACTURE, _REFUS_HUMAIN_SAISIE, roles_approbateurs=_ROLES_APPROBATEURS_SAISIE
    )
    if acteur is None:
        return _refus(refus)
    # Octets internes optionnels : le pont Fusion transmet le snapshot déjà borné et
    # validé. Ils sont absents du schéma MCP, des arguments d'approbation et du navigateur.
    dictionnaire_taux, refus_taux = _dictionnaire_taux(contenu_octets=contenu_taux)
    if refus_taux is not None:
        return _refus(refus_taux)
    registre_cible = _registre_comptes_a_payer()
    resultat, verdict = comptes_a_payer.saisir_facture_fournisseur(
        po_id=po_id,
        fournisseur_id=fournisseur_id,
        numero_facture=numero_facture,
        date_facture=date_facture,
        montant_avant_taxes=montant_avant_taxes,
        total_facture=total_facture,
        saisi_par=acteur["par"],
        voie=acteur["voie"],
        horodatage=_horodatage_faisant_foi(horodatage),
        dictionnaire_taux=dictionnaire_taux,
        registre_cible=registre_cible,
    )
    if verdict is not None:
        return _refus(verdict)
    return _reponse_facture(resultat, registre_cible, dictionnaire_taux)


def _categories_depense_sans_po() -> Any:
    """`department.yaml/configuration.categories_depense_sans_po` tel que le propriétaire l'a écrit, ou `None` : relu à
    chaque appel (pas de redémarrage pour ajouter une catégorie). Absent : la saisie sans PO dit « catégories à
    configurer » (`comptes_a_payer.lire_categories_depense`), jamais une catégorie par défaut. Lecture seule."""
    return _configuration_manifeste().get("categories_depense_sans_po")


def saisir_facture_sans_po(
    fournisseur_id: str,
    categorie: str,
    numero_facture: str,
    date_facture: str,
    montant_avant_taxes: str,
    total_facture: str | None,
    horodatage: str,
) -> dict[str, Any]:
    """L'outil `m5_saisir_facture_sans_po` (T1, N3, `admin`) : range une facture fournisseur SANS PO (carburant, outils)
    saisie par un humain (`comptes_a_payer.saisir_facture_sans_po`), et rend la facture, ses avertissements et ce que
    les factures sans PO valent en tout.

    Mêmes gardes que `saisir_facture_fournisseur` : humain identifié (les deux mêmes voies), taxes et total recalculés,
    doublon refusé, tous les paramètres requis. La catégorie est de la liste fermée que le propriétaire déclare dans
    `department.yaml` (`configuration.categories_depense_sans_po`) ; vide ou absente, la saisie dit « catégories à
    configurer ». La facture entre en entier dans les comptes à payer et dans le cash libre. N'écrit qu'au registre des
    comptes à payer : aucun DECAISSEMENT, payer est N5."""
    acteur, refus = _acteur_humain(
        _OUTIL_SAISIE_SANS_PO, _REFUS_HUMAIN_SAISIE_SANS_PO, roles_approbateurs=_ROLES_APPROBATEURS_SAISIE
    )
    if acteur is None:
        return _refus(refus)
    dictionnaire_taux, refus_taux = _dictionnaire_taux()
    if refus_taux is not None:
        return _refus(refus_taux)
    registre_cible = _registre_comptes_a_payer()
    resultat, verdict = comptes_a_payer.saisir_facture_sans_po(
        fournisseur_id=fournisseur_id,
        categorie=categorie,
        numero_facture=numero_facture,
        date_facture=date_facture,
        montant_avant_taxes=montant_avant_taxes,
        total_facture=total_facture,
        saisi_par=acteur["par"],
        voie=acteur["voie"],
        horodatage=_horodatage_faisant_foi(horodatage),
        dictionnaire_taux=dictionnaire_taux,
        categories_configurees=_categories_depense_sans_po(),
        registre_cible=registre_cible,
    )
    if verdict is not None:
        return _refus(verdict)
    return _reponse_facture(resultat, registre_cible, dictionnaire_taux)


def corriger_facture_fournisseur(
    facture_fournisseur_id: str,
    motif: str,
    numero_facture: str | None,
    date_facture: str | None,
    montant_avant_taxes: str | None,
    total_facture: str | None,
    horodatage: str,
) -> dict[str, Any]:
    """L'outil `m5_corriger_facture_fournisseur` (T2, N4, `admin`) : corrige une facture fournisseur saisie en AJOUTANT
    une pièce de correction chaînée au registre (`comptes_a_payer.corriger_facture_fournisseur`) ; la facture d'origine
    n'est jamais modifiée. Rend la facture à son état courant et le rapprochement PROPOSÉ de son PO (ou le total sans
    PO), qui lisent ce nouvel état, comme le cash libre.

    N4 : un engagement. Le socle met l'appel dans la file du propriétaire (mode `ombre` ou `supervise`) : l'outil ne
    s'exécute qu'après la décision d'un humain (finance ou propriétaire), aux arguments EXACTS enregistrés. Il refuse
    lui-même tout appel qui n'est pas d'un humain (`_acteur_humain`), y compris en mode `autonome` où un N4 s'exécute
    sans file. Motif obligatoire ; numéro, date et montant nuls sont inchangés ; taxes et total recalculés. N'écrit
    qu'au registre des comptes à payer : aucun DECAISSEMENT."""
    acteur, refus = _acteur_humain(
        _OUTIL_CORRECTION_FACTURE,
        _REFUS_HUMAIN_N4,
        roles_approbateurs=_ROLES_APPROBATEURS_N4,
        personne_doit_porter=_ROLES_APPROBATEURS_N4,
    )
    if acteur is None:
        return _refus(refus)
    dictionnaire_taux, refus_taux = _dictionnaire_taux()
    if refus_taux is not None:
        return _refus(refus_taux)
    registre_cible = _registre_comptes_a_payer()
    resultat, verdict = comptes_a_payer.corriger_facture_fournisseur(
        facture_fournisseur_id=facture_fournisseur_id,
        motif=motif,
        numero_facture=numero_facture,
        date_facture=date_facture,
        montant_avant_taxes=montant_avant_taxes,
        total_facture=total_facture,
        corrige_par=acteur["par"],
        role=acteur["role"],
        voie=acteur["voie"],
        horodatage=_horodatage_faisant_foi(horodatage),
        dictionnaire_taux=dictionnaire_taux,
        registre_cible=registre_cible,
    )
    if verdict is not None:
        return _refus(verdict)
    return _reponse_facture(resultat, registre_cible, dictionnaire_taux)


def annuler_facture_fournisseur(facture_fournisseur_id: str, motif: str, horodatage: str) -> dict[str, Any]:
    """L'outil `m5_annuler_facture_fournisseur` (T2, N4, `admin`) : annule une facture fournisseur saisie en AJOUTANT
    une pièce d'annulation chaînée au registre (`comptes_a_payer.annuler_facture_fournisseur`) ; la facture d'origine
    n'est jamais modifiée ni effacée, elle reste au registre au statut `ANNULEE`. Rend la facture annulée et le
    rapprochement PROPOSÉ de son PO (ou le total sans PO), qui ne la comptent plus, comme le cash libre.

    Mêmes gardes que `corriger_facture_fournisseur` (N4, humain exigé par l'outil, motif obligatoire, arguments exacts
    rejoués). Annuler ne paie rien et n'efface pas la dette : un PO reçu et non facturé redevient un « à payer
    attendu ». N'écrit qu'au registre des comptes à payer : aucun DECAISSEMENT."""
    acteur, refus = _acteur_humain(
        _OUTIL_ANNULATION_FACTURE,
        _REFUS_HUMAIN_N4,
        roles_approbateurs=_ROLES_APPROBATEURS_N4,
        personne_doit_porter=_ROLES_APPROBATEURS_N4,
    )
    if acteur is None:
        return _refus(refus)
    dictionnaire_taux, refus_taux = _dictionnaire_taux()
    if refus_taux is not None:
        return _refus(refus_taux)
    registre_cible = _registre_comptes_a_payer()
    resultat, verdict = comptes_a_payer.annuler_facture_fournisseur(
        facture_fournisseur_id=facture_fournisseur_id,
        motif=motif,
        annule_par=acteur["par"],
        role=acteur["role"],
        voie=acteur["voie"],
        horodatage=_horodatage_faisant_foi(horodatage),
        registre_cible=registre_cible,
    )
    if verdict is not None:
        return _refus(verdict)
    return _reponse_facture(resultat, registre_cible, dictionnaire_taux)


def lister_comptes_a_payer(
    po_id: str | None = None,
    depart: int | None = None,
    role: str | None = None,
    autorise_couts: bool | None = None,
    sans_po: bool | None = None,
) -> dict[str, Any]:
    """L'outil `m5_lister_comptes_a_payer` (T0, `admin`) : ce que l'entreprise doit aux fournisseurs, PAR PO reçu, avec
    l'attendu, le facturé, le « à payer » et le rapprochement PROPOSÉ (`comptes_a_payer.lister`), les factures sans PO
    comprises dans les totaux ; `sans_po` vrai rend plutôt les factures SANS PO, une par ligne, avec leur identifiant
    (`comptes_a_payer.lister_sans_po`). Les factures s'y lisent à leur ÉTAT COURANT : une corrigée vaut sa correction,
    une annulée ne compte nulle part.

    Même contrôle d'accès que `lire_comptes_a_recevoir` : pour un appel d'appareil, l'identité confirmée en base
    (`admin` seulement), la vue vient du rôle authentifié, un argument ne peut que la restreindre ; refus AVANT toute
    lecture. Sans le droit de voir les coûts : le nombre de PO (ou de factures sans PO) seulement. Sans appareil
    (agent, console), `autorise_couts` reste obligatoire et explicite. Aucun montant, prix, taux ni quantité ne se
    passe en argument : tout est lu du registre. Paginé par rang (`depart`, `prochain_depart`) sous `BUDGET_SORTIE` :
    jamais tronqué. N'écrit rien."""
    acteur, refus = _acteur_appareil()
    if refus is not None:
        return _refus(refus)
    vue, verdict = acces.resoudre_vue(acteur, role, autorise_couts)
    if verdict is not None:
        return _refus(verdict)
    if sans_po is not None and not isinstance(sans_po, bool):
        return _refus(
            validation.construire_verdict("REJ-AP-LISTE-FILTRE-INVALIDE", detail="sans_po : vrai, faux ou nul")
        )
    if sans_po and po_id is not None:
        return _refus(
            validation.construire_verdict(
                "REJ-AP-LISTE-FILTRE-INVALIDE",
                detail="sans_po et po_id ne vont pas ensemble : une facture sans PO n'est d'aucun PO",
            )
        )
    if sans_po:
        page, verdict = comptes_a_payer.lister_sans_po(
            _registre_comptes_a_payer(), depart=0 if depart is None else depart, budget_caracteres=BUDGET_SORTIE
        )
        if verdict is not None:
            return _refus(verdict)
        if not vue["autorise_couts"]:
            masquee = {"role": vue["role"], "nombre_factures_sans_po": page["total"], "montants_masques": True}
            return {"accepte": True, "resultat": analyse.avec_mention(masquee)}
        return {"accepte": True, "resultat": {"role": vue["role"], **page}}
    dictionnaire_taux, refus_taux = _dictionnaire_taux()
    if refus_taux is not None:
        return _refus(refus_taux)
    page, verdict = comptes_a_payer.lister(
        _registre_comptes_a_payer(),
        dictionnaire_taux,
        depart=0 if depart is None else depart,
        budget_caracteres=BUDGET_SORTIE,
        po_id=po_id,
    )
    if verdict is not None:
        return _refus(verdict)
    if not vue["autorise_couts"]:
        masquee = {"role": vue["role"], "nombre_po": page["total"], "montants_masques": True}
        return {"accepte": True, "resultat": analyse.avec_mention(masquee)}
    return {"accepte": True, "resultat": {"role": vue["role"], **page}}


_ROLES_N4_CONTRAT_SALARIAL = frozenset({"finance", "nathan_owner"})
_OUTIL_CONTRAT_SALARIAL = "m5_enregistrer_contrat_horaire"
_OUTIL_REVOQUER_CONTRAT_SALARIAL = "m5_revoquer_contrat_horaire"


def _identite_employe_active(employee_person_id: str) -> bool:
    cnx = stockage.connexion_courante()
    personne = identite.personne_active(cnx, employee_person_id) if cnx is not None else None
    return personne is not None and "employee" in personne.roles


def _signataire_contrat_horaire(acteur: dict[str, str]) -> dict[str, str]:
    """Canonise le rôle N4 actif du signataire, même si le jeton porte le profil admin."""
    roles_autorises = _ROLES_N4_CONTRAT_SALARIAL
    role = acteur["role"]
    voie = acteur["voie"]
    if acteur["voie"] == "appareil":
        cnx = stockage.connexion_courante()
        personne = identite.personne_active(cnx, acteur["par"]) if cnx is not None else None
        roles = personne.roles if personne is not None else frozenset()
        role = "nathan_owner" if "nathan_owner" in roles else "finance" if "finance" in roles else ""
        appelante = contexte.identite_appelante()
        if appelante is not None and appelante.source == "console":
            voie = "console"
    if role not in roles_autorises:
        return {}
    return {
        "personne": acteur["par"],
        "role": role,
        "voie": voie,
        "decision_id": contexte.demande_approuvee_en_cours(),
    }


def enregistrer_contrat_horaire(
    employee_person_id: str,
    contrat_id: str,
    valide_du: str,
    valide_jusqu_au: str,
    fuseau: str,
    devise: str,
    taux_horaire: str,
    source_humaine: str,
    date_source: str,
    revision_attendue: int,
    ligne_id_attendue: str,
    motif: str,
) -> dict[str, Any]:
    """Crée ou révise un taux individuel après validation humaine N4; écrit seulement au flux salaire privé."""
    acteur, refus = _acteur_humain(
        _OUTIL_CONTRAT_SALARIAL,
        "un contrat salarial horaire exige une validation humaine N4 de finance ou du propriétaire",
        roles_approbateurs=_ROLES_N4_CONTRAT_SALARIAL,
        personne_doit_porter=_ROLES_N4_CONTRAT_SALARIAL,
    )
    if acteur is None:
        return _refus(refus)
    if not isinstance(employee_person_id, str) or not _identite_employe_active(employee_person_id):
        return _refus(validation.construire_verdict(
            "REJ-SALAIRE-EMPLOYE-INVALIDE", detail="ID cible absent, inactif ou sans rôle OPSYS employee"
        ))
    journal = _registre_contrats_salaries()
    if journal is None:
        return _refus(validation.construire_verdict(
            "REJ-SALAIRE-REGISTRE-INDISPONIBLE", detail="journal salarial durable non initialisé"
        ))
    signataire = _signataire_contrat_horaire(acteur)
    if not signataire:
        return _refus(validation.construire_verdict(
            "REJ-SALAIRE-IDENTITE-REQUIS", detail="aucun rôle N4 humain finance/propriétaire confirmé"
        ))
    maillon, verdict = contrats_salaries_horaires.enregistrer(
        journal,
        employee_person_id=employee_person_id,
        contrat_id=contrat_id,
        valide_du=valide_du,
        valide_jusqu_au=valide_jusqu_au,
        fuseau=fuseau,
        devise=devise,
        taux_horaire=taux_horaire,
        source_humaine=source_humaine,
        date_source=date_source,
        revision_attendue=revision_attendue,
        ligne_id_attendue=ligne_id_attendue,
        motif=motif,
        approbateur=signataire,
        horodatage=approbations._maintenant(),
    )
    if verdict is not None:
        return _refus(verdict)
    return {"accepte": True, "resultat": maillon}


def revoquer_contrat_horaire(
    employee_person_id: str,
    contrat_id: str,
    revision_attendue: int,
    ligne_id_attendue: str,
    motif: str,
) -> dict[str, Any]:
    """Ajoute la révocation N4 d'un contrat sans effacer les versions antérieures."""
    acteur, refus = _acteur_humain(
        _OUTIL_REVOQUER_CONTRAT_SALARIAL,
        "une révocation de contrat salarial exige une validation humaine N4 de finance ou du propriétaire",
        roles_approbateurs=_ROLES_N4_CONTRAT_SALARIAL,
        personne_doit_porter=_ROLES_N4_CONTRAT_SALARIAL,
    )
    if acteur is None:
        return _refus(refus)
    if not isinstance(employee_person_id, str) or not _identite_employe_active(employee_person_id):
        return _refus(validation.construire_verdict(
            "REJ-SALAIRE-EMPLOYE-INVALIDE", detail="ID cible absent, inactif ou sans rôle OPSYS employee"
        ))
    journal = _registre_contrats_salaries()
    if journal is None:
        return _refus(validation.construire_verdict(
            "REJ-SALAIRE-REGISTRE-INDISPONIBLE", detail="journal salarial durable non initialisé"
        ))
    signataire = _signataire_contrat_horaire(acteur)
    if not signataire:
        return _refus(validation.construire_verdict(
            "REJ-SALAIRE-IDENTITE-REQUIS", detail="aucun rôle N4 humain finance/propriétaire confirmé"
        ))
    maillon, verdict = contrats_salaries_horaires.revoquer(
        journal,
        employee_person_id=employee_person_id,
        contrat_id=contrat_id,
        revision_attendue=revision_attendue,
        ligne_id_attendue=ligne_id_attendue,
        motif=motif,
        approbateur=signataire,
        horodatage=approbations._maintenant(),
    )
    if verdict is not None:
        return _refus(verdict)
    return {"accepte": True, "resultat": maillon}


def lire_contrat_horaire(
    employee_person_id: str, valide_du: str, valide_jusqu_au: str, fuseau: str,
) -> dict[str, Any]:
    """Lecture privée du taux courant; authentifie l'appelant et l'employé avant de lire le journal salarial."""
    acteur, refus = _acteur_appareil()
    if refus is not None:
        return _refus(refus)
    if acteur is None:
        return _refus(validation.construire_verdict(
            "REJ-SALAIRE-IDENTITE-REQUIS", detail="identité admin d'appareil ou propriétaire console requise"
        ))
    cnx = stockage.connexion_courante()
    lecteur = identite.personne_active(cnx, acteur.personne) if cnx is not None else None
    roles_privilegies = lecteur.roles if lecteur is not None else frozenset()
    droit_admin_appareil = (
        acteur.source == "appareil" and acteur.role == "admin"
        and "admin" in roles_privilegies
    )
    droit_proprietaire_console = (
        acteur.source == "console" and acteur.role == "nathan_owner"
        and "nathan_owner" in roles_privilegies
    )
    if lecteur is None or not (droit_admin_appareil or droit_proprietaire_console):
        return _refus(validation.construire_verdict(
            "REJ-SALAIRE-ACCES-REFUSE",
            detail="lecture réservée à admin appareil ou nathan_owner de source console, confirmés en base",
        ))
    if not isinstance(employee_person_id, str) or not _identite_employe_active(employee_person_id):
        return _refus(validation.construire_verdict(
            "REJ-SALAIRE-EMPLOYE-INVALIDE", detail="ID cible absent, inactif ou sans rôle OPSYS employee"
        ))
    journal = _registre_contrats_salaries()
    if journal is None:
        return _refus(validation.construire_verdict(
            "REJ-SALAIRE-REGISTRE-INDISPONIBLE", detail="journal salarial durable non initialisé"
        ))
    contrat, verdict = contrats_salaries_horaires.lire(
        journal,
        employee_person_id=employee_person_id,
        valide_du=valide_du,
        valide_jusqu_au=valide_jusqu_au,
        fuseau=fuseau,
    )
    if verdict is not None:
        return _refus(verdict)
    return {"accepte": True, "resultat": contrat}


_ROLES_N4_ECHEANCIER_CONTRAT = frozenset({"finance", "nathan_owner"})
_OUTIL_ECHEANCIER_CONTRAT = "m5_enregistrer_echeancier_contrat"
_OUTIL_REVOQUER_ECHEANCIER_CONTRAT = "m5_revoquer_echeancier_contrat"


def _signataire_echeancier_contrat(acteur: dict[str, str]) -> dict[str, str]:
    """Enregistre le rôle N4 humain effectivement confirmé, jamais le rôle d'un argument."""
    signataire = _signataire_contrat_horaire(acteur)
    return signataire if signataire.get("role") in _ROLES_N4_ECHEANCIER_CONTRAT else {}


def enregistrer_echeancier_contrat(
    contrat_id: str,
    devis_id: str,
    prix_ht: str,
    prix_ttc: str,
    devise: str,
    source_humaine: str,
    date_source: str,
    couverture_jusquau: str,
    echeances: list[dict[str, str]],
    revision_attendue: int,
    ligne_id_attendue: str,
    motif: str,
) -> dict[str, Any]:
    """Enregistre/révise un échéancier client après N4; n'écrit jamais au registre des mouvements."""
    acteur, refus = _acteur_humain(
        _OUTIL_ECHEANCIER_CONTRAT,
        "un échéancier contractuel exige une validation N4 de finance ou du propriétaire",
        roles_approbateurs=_ROLES_N4_ECHEANCIER_CONTRAT,
        personne_doit_porter=_ROLES_N4_ECHEANCIER_CONTRAT,
    )
    if acteur is None:
        return _refus(refus)
    signataire = _signataire_echeancier_contrat(acteur)
    if not signataire:
        return _refus(validation.construire_verdict(
            "REJ-CONTRAT-IDENTITE-REQUIS", detail="signataire N4 finance/propriétaire confirmé requis"
        ))
    journal = _registre_echeanciers_contrats()
    if journal is None:
        return _refus(validation.construire_verdict(
            "REJ-CONTRAT-REGISTRE-INDISPONIBLE", detail="journal d'échéanciers durable non initialisé"
        ))
    devis_registre = list(stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_DEVIS_RECUS))
    champs_devis = {"devis_id", "lead_id", "chantier_id", "lignes", "prix_total", "horodatage_acceptation"}
    if any(not isinstance(devis, dict) or not champs_devis <= devis.keys() for devis in devis_registre):
        return _refus(validation.construire_verdict(
            "REJ-CONTRAT-DEVIS-INVALIDE", detail="la source devis reçue est mal formée"
        ))
    correspondants = [maillon for maillon in devis_registre
                      if isinstance(maillon, dict) and maillon.get("devis_id") == devis_id]
    if len(correspondants) != 1:
        return _refus(validation.construire_verdict(
            "REJ-CONTRAT-DEVIS-ABSENT", detail="un devis M3 accepté unique est requis"
        ))
    maillon, verdict = echeanciers_contrats.enregistrer(
        journal,
        devis=correspondants[0],
        contrat_id=contrat_id,
        devis_id=devis_id,
        prix_ht=prix_ht,
        prix_ttc=prix_ttc,
        devise=devise,
        source_humaine=source_humaine,
        date_source=date_source,
        couverture_jusquau=couverture_jusquau,
        echeances=echeances,
        revision_attendue=revision_attendue,
        ligne_id_attendue=ligne_id_attendue,
        motif=motif,
        approbateur=signataire,
        horodatage=approbations._maintenant(),
    )
    if verdict is not None:
        return _refus(verdict)
    return {"accepte": True, "resultat": maillon}


def revoquer_echeancier_contrat(
    contrat_id: str, devis_id: str, revision_attendue: int, ligne_id_attendue: str, motif: str,
) -> dict[str, Any]:
    """Révoque un échéancier par un nouveau maillon N4; l'historique demeure append-only."""
    acteur, refus = _acteur_humain(
        _OUTIL_REVOQUER_ECHEANCIER_CONTRAT,
        "la révocation d'un échéancier exige une validation N4 de finance ou du propriétaire",
        roles_approbateurs=_ROLES_N4_ECHEANCIER_CONTRAT,
        personne_doit_porter=_ROLES_N4_ECHEANCIER_CONTRAT,
    )
    if acteur is None:
        return _refus(refus)
    signataire = _signataire_echeancier_contrat(acteur)
    journal = _registre_echeanciers_contrats()
    if journal is None:
        return _refus(validation.construire_verdict(
            "REJ-CONTRAT-REGISTRE-INDISPONIBLE", detail="journal d'échéanciers durable non initialisé"
        ))
    maillon, verdict = echeanciers_contrats.revoquer(
        journal, contrat_id=contrat_id, devis_id=devis_id, revision_attendue=revision_attendue,
        ligne_id_attendue=ligne_id_attendue, motif=motif, approbateur=signataire,
        horodatage=approbations._maintenant(),
    )
    if verdict is not None:
        return _refus(verdict)
    return {"accepte": True, "resultat": maillon}


def prevoir_tresorerie_contrats(aujourd_hui: str) -> dict[str, Any]:
    """Prévision M5.8a: ajoute les seuls échéanciers humains rapprochés au forecast M5.7."""
    appelante = contexte.identite_appelante()
    if appelante is None:
        return _refus(validation.construire_verdict(
            "REJ-CONTRAT-ACCES-REFUSE", detail="lecture réservée au propriétaire confirmé via console",
        ))
    acteur, refus = _acteur_appareil()
    if refus is not None:
        return _refus(refus)
    if acteur is None or acteur.source != "console" or acteur.role != "nathan_owner":
        return _refus(validation.construire_verdict(
            "REJ-CONTRAT-ACCES-REFUSE", detail="lecture réservée au propriétaire confirmé via console",
        ))
    vue, verdict = acces.resoudre_vue(acteur, None, None)
    if verdict is not None:
        return _refus(verdict)
    if not vue["autorise_couts"]:
        return _refus(validation.construire_verdict(
            "REJ-CFO-COUTS-REQUIS", detail="la projection contractuelle contient des montants et exige le droit M5"
        ))
    configuration = _configuration_manifeste()
    reglages, verdict = _reglages_prevision(aujourd_hui, None, None, 0, configuration)
    if verdict is not None:
        return _refus(verdict)
    lectures = _lectures_finance(
        _registre_mouvements(None), configuration,
        validateur_snapshot=_valider_chaines_cfo,
        inclure_echeanciers_contrats=True,
    )
    if lectures.get("verdict_chaine") is not None:
        return _refus(lectures["verdict_chaine"])
    journal = registre_module.Registre(maillons=lectures["maillons_echeanciers_contrats"])
    etats, verdict = echeanciers_contrats.etats_courants(journal)
    if verdict is not None:
        return _refus(verdict)
    horizon_fin = reglages["aujourd_hui"] + timedelta(days=7 * reglages["horizon"] - 1)
    contrats = [etat for etat in etats.values() if etat.get("type_entree") == echeanciers_contrats.TYPE_ENREGISTRE]
    flux_contrats, flux_inclus, sans_echeancier, incomplet, bloques = echeanciers_contrats.flux_prevision(
        contrats, lectures["maillons_devis"], lectures["factures"], fin_horizon=horizon_fin,
    )
    cash, flux_base, seuil, verdict_seuil = _flux_connus_prevision(lectures, reglages)
    resultat = prevision.assembler(
        reglages["aujourd_hui"], reglages["horizon"], cash["solde"], [*flux_base, *flux_contrats],
        seuil=seuil, verdict_seuil=verdict_seuil, cash_libre_resultat=cash,
    )
    page, verdict = prevision.vue_prevision(resultat, depart=0, budget_caracteres=BUDGET_SORTIE - 1200)
    if verdict is not None:
        return _refus(verdict)
    bloc_contrats = {
        "statut": "PARTIEL",
        "couverture_incomplete": incomplet,
        "echeances_rapprochees": flux_inclus,
        "devis_sans_echeancier": sans_echeancier,
        "bloques": bloques,
        "limites": [
            "M3 fournit un devis accepté, pas une preuve de contrat signé; seul le contrat déclaré et revu en N4 "
            "est projeté",
            "prix_total M3 est comparé comme HT; le TTC vient de la source contractuelle déclarée, aucune taxe "
            "n'est calculée",
            "une facture cliente active du même devis bloque tout l'échéancier pour éviter un double compte",
            "PAYEE n'atteste pas un dépôt bancaire; seuls les mouvements du registre changent le solde",
            "le registre M3 reçu n'est pas chaîné; le journal M5 d'échéanciers, lui, est vérifié avant projection",
            "la prévision est hebdomadaire et n'expose pas un creux intrasemaine; probable et carnet non signé "
            "restent absents",
        ],
    }
    resultat_sortie = {"role": vue["role"], **page, "contrats": bloc_contrats}
    if len(json.dumps(resultat_sortie, ensure_ascii=False, default=str)) > BUDGET_SORTIE:
        return _refus(validation.construire_verdict(
            "REJ-CONTRAT-PROJECTION-TROP-GROSSE",
            detail="le rapport complet dépasserait le budget; aucune donnée tronquée",
        ))
    return {"accepte": True, "resultat": analyse.avec_mention(resultat_sortie)}


def _refuser_source_brut(detail: str) -> dict[str, Any]:
    return _refus(validation.construire_verdict("REJ-SALAIRE-STRUCTURE-INVALIDE", detail=detail))


def _refuser_acces_brut() -> dict[str, Any]:
    return _refus(validation.construire_verdict(
        "REJ-SALAIRE-ACCES-REFUSE",
        detail="le brouillon de brut est réservé au propriétaire confirmé via console",
    ))


def _sources_attendues_valides(sources: object) -> bool:
    if sources is None:
        return True
    if not isinstance(sources, Mapping) or set(sources) != {"heures_m4", "contrat_m5"}:
        return False
    heures, contrat = sources.get("heures_m4"), sources.get("contrat_m5")
    if not isinstance(heures, Mapping) or set(heures) != {"ligne_id", "revision", "empreinte_sources"}:
        return False
    if not isinstance(contrat, Mapping) or set(contrat) != {"contrat_id", "revision", "ligne_id"}:
        return False
    return (
        _hash_source_valide(heures.get("ligne_id"))
        and type(heures.get("revision")) is int and heures["revision"] >= 1
        and _hash_source_valide(heures.get("empreinte_sources"))
        and isinstance(contrat.get("contrat_id"), str) and bool(contrat["contrat_id"].strip())
        and type(contrat.get("revision")) is int and contrat["revision"] >= 1
        and _hash_source_valide(contrat.get("ligne_id"))
    )


def _hash_source_valide(valeur: object) -> bool:
    return isinstance(valeur, str) and len(valeur) == 64 and all(c in "0123456789abcdef" for c in valeur)


def _projection_heures_valide(
    enveloppe: object, employee_person_id: str, debut: str, fin: str, fuseau: str,
) -> dict[str, Any] | None:
    if not isinstance(enveloppe, Mapping) or enveloppe.get("ok") is not True:
        return None
    resultat_outil = enveloppe.get("resultat")
    if not isinstance(resultat_outil, Mapping) or resultat_outil.get("accepte") is not True:
        return None
    projection = resultat_outil.get("resultat")
    champs = {
        "technicien_id", "periode", "minutes_regulieres", "ligne_id", "revision", "empreinte_sources",
        "couverture_complete", "classification_reguliere_confirmee",
    }
    if not isinstance(projection, Mapping) or set(projection) != champs:
        return None
    periode = projection.get("periode")
    if not isinstance(periode, Mapping) or dict(periode) != {"debut": debut, "fin": fin, "fuseau": fuseau}:
        return None
    minutes = projection.get("minutes_regulieres")
    minutes_max = brut_regulier.limite_minutes_regulieres(debut, fin, fuseau)
    if (
        projection.get("technicien_id") != employee_person_id
        or type(minutes) is not int or minutes_max is None or not 0 <= minutes <= minutes_max
        or not _hash_source_valide(projection.get("ligne_id"))
        or type(projection.get("revision")) is not int or projection["revision"] < 1
        or not _hash_source_valide(projection.get("empreinte_sources"))
        or projection.get("couverture_complete") is not True
        or projection.get("classification_reguliere_confirmee") is not True
    ):
        return None
    return dict(projection)


def preparer_brut_regulier(
    employee_person_id: str,
    debut: str,
    fin: str,
    fuseau: str,
    politique_arrondi: str,
    hypothese_arrondi: str,
    sources_attendues: Mapping[str, Any] | None,
    *,
    lecteur_heures_m4: LecteurHeuresM4 | None,
) -> dict[str, Any]:
    """Produit un brouillon brut régulier calculé depuis M4 et le taux M5 courant; lecture seule."""
    periode = brut_regulier.valider_periode(debut, fin, fuseau)
    if periode is None:
        return _refus(validation.construire_verdict(
            "REJ-SALAIRE-PERIODE-INVALIDE", detail="dates inclusives ISO ordonnées et fuseau IANA requis",
        ))
    if not isinstance(employee_person_id, str) or not employee_person_id.strip():
        return _refuser_source_brut("identifiant salarié OPSYS requis")
    if not isinstance(hypothese_arrondi, str) or not 1 <= len(hypothese_arrondi.strip()) <= 300:
        return _refuser_source_brut("hypothèse ou référence humaine d'arrondi requise (1 à 300 caractères)")
    if politique_arrondi != brut_regulier.POLITIQUE_ARRONDI:
        return _refuser_source_brut("une politique d'arrondi explicitement supportée est requise")
    if not _sources_attendues_valides(sources_attendues):
        return _refuser_source_brut(
            "sources_attendues doit être null ou contenir les deux références M4 et M5 complètes"
        )

    acteur, refus = _acteur_appareil()
    if refus is not None:
        return _refus(refus)
    if acteur is None:
        return _refuser_acces_brut()
    cnx = stockage.connexion_courante()
    personne = identite.personne_active(cnx, acteur.personne) if cnx is not None else None
    roles = personne.roles if personne is not None else frozenset()
    droit_proprietaire_console = (
        acteur.source == "console" and acteur.role == "nathan_owner" and "nathan_owner" in roles
    )
    if personne is None or not droit_proprietaire_console:
        return _refuser_acces_brut()
    if not _identite_employe_active(employee_person_id):
        return _refus(validation.construire_verdict(
            "REJ-SALAIRE-EMPLOYE-INVALIDE", detail="la cible doit être une personne OPSYS employee active",
        ))
    if lecteur_heures_m4 is None:
        return _refuser_source_brut("lecteur M4 non raccordé ou contexte M4 absent")

    journal = _registre_contrats_salaries()
    if journal is None:
        return _refus(validation.construire_verdict(
            "REJ-SALAIRE-REGISTRE-INDISPONIBLE", detail="journal salarial durable non initialisé",
        ))
    contrat, verdict = contrats_salaries_horaires.lire(
        journal, employee_person_id=employee_person_id, valide_du=debut, valide_jusqu_au=fin, fuseau=fuseau,
    )
    if verdict is not None:
        return _refus(verdict)

    projection = _projection_heures_valide(
        lecteur_heures_m4(employee_person_id, debut, fin, fuseau), employee_person_id, debut, fin, fuseau,
    )
    if projection is None:
        return _refuser_source_brut("projection M4 absente, refusée ou mal formée; aucun brut calculé")
    references = {
        "heures_m4": {
            "ligne_id": projection["ligne_id"],
            "revision": projection["revision"],
            "empreinte_sources": projection["empreinte_sources"],
        },
        "contrat_m5": {
            "contrat_id": contrat["contrat_id"],
            "revision": contrat["revision"],
            "ligne_id": contrat["ligne_id"],
        },
    }
    if sources_attendues is not None and dict(sources_attendues) != references:
        return _refus(validation.construire_verdict(
            "REJ-SALAIRE-REVISION-PERIMEE",
            detail="références M4/M5 modifiées; confirmer explicitement le nouveau snapshot",
        ))
    brut, verdict = brut_regulier.calculer_brut_regulier(
        contrat["taux_horaire"], projection["minutes_regulieres"], politique_arrondi,
    )
    if verdict is not None:
        return _refus(verdict)
    sortie = analyse.avec_mention({
        **brut,
        "periode": {"debut": debut, "fin": fin, "fuseau": fuseau},
        "sources": {
            "heures_m4": references["heures_m4"],
            "contrat_m5": {
                **references["contrat_m5"],
                "date_source": contrat["date_source"],
                "source_humaine": contrat["source_humaine"],
            },
        },
        "couverture_complete": projection["couverture_complete"],
        "hypotheses": [{
            "politique_arrondi": politique_arrondi,
            "reference_humaine": hypothese_arrondi.strip(),
            "verifiee": False,
        }],
        "manquants": [],
        "non_calcules": ["retenues", "cotisations", "DAS", "paie_nette", "paiement"],
        "requires_human_validation": True,
        "official_action_blocked": True,
    })
    if len(json.dumps(sortie, ensure_ascii=False, separators=(",", ":"))) > BUDGET_SORTIE:
        return _refuser_source_brut("sources et résultat dépassent le budget; aucun brut tronqué n'est présenté")
    return {"accepte": True, "resultat": sortie}


def _fonction_brut_regulier(lecteur_heures_m4: LecteurHeuresM4 | None) -> Callable[..., dict[str, Any]]:
    def appeler(
        employee_person_id: str,
        debut: str,
        fin: str,
        fuseau: str,
        politique_arrondi: str,
        hypothese_arrondi: str,
        sources_attendues: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        return preparer_brut_regulier(
            employee_person_id,
            debut,
            fin,
            fuseau,
            politique_arrondi,
            hypothese_arrondi,
            sources_attendues,
            lecteur_heures_m4=lecteur_heures_m4,
        )

    return appeler


# ----------------------------------------------------------- cash libre réel et calendrier fiscal (T4.16)
def _configuration_manifeste() -> dict[str, Any]:
    """`department.yaml/configuration` tel que l'entreprise l'a écrit, ou `{}` : relu à chaque appel (comme le taux
    horaire), pour que Nathan ou le CPA change une déclaration sans redémarrer. Un manifeste illisible donne `{}` :
    tout ce qui en dépend devient « à déclarer », jamais une valeur par défaut. Lecture seule."""
    try:
        donnees = yaml.safe_load(_MANIFESTE.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    configuration = donnees.get("configuration") if isinstance(donnees, dict) else None
    return configuration if isinstance(configuration, dict) else {}


def _calendrier_fiscal() -> tuple[dict[int, dict[str, Any]] | None, dict[str, Any] | None]:
    """Le calendrier fiscal versionné, ou le refus nommé d'un fichier illisible ou incohérent : jamais un calendrier à
    moitié lu (`REJ-CALENDRIER-INVALIDE`)."""
    calendrier, erreurs = calendrier_fiscal.charger_calendrier_fiscal(_CHEMIN_CALENDRIER_FISCAL)
    if erreurs:
        return None, validation.construire_verdict("REJ-CALENDRIER-INVALIDE", detail="; ".join(erreurs))
    return calendrier, None


def _verdict_chaine_financiere(nom: str, maillons: list[dict[str, Any]]) -> dict[str, str] | None:
    """Valide la forme minimale des maillons puis leur empreinte, sans relire le registre."""
    for rang, maillon in enumerate(maillons):
        if not isinstance(maillon, dict):
            return validation.construire_verdict(
                "REJ-CFO-CHAINE-INVALIDE", detail=f"registre {nom}, rang {rang} : maillon non structuré"
            )
        champs_requis = {"ligne_id", "precedent_ligne_id", "type_entree", "horodatage"}
        if maillon.get("type_entree") == "mouvement_enregistre":
            champs_requis.update({"montant", "type_mouvement", "classe_retention", "source"})
        absents = sorted(champs_requis.difference(maillon))
        if absents:
            return validation.construire_verdict(
                "REJ-CFO-CHAINE-INVALIDE",
                detail=f"registre {nom}, rang {rang} : champs de maillon absents ({', '.join(absents)})",
            )
    valide, detail = registre_module.Registre(maillons=maillons).valider_chaine()
    if not valide:
        return validation.construire_verdict("REJ-CFO-CHAINE-INVALIDE", detail=f"registre {nom} : {detail}")
    return None


def _valider_chaines_cfo(
    maillons_mouvements: list[dict[str, Any]],
    maillons_factures: list[dict[str, Any]],
    maillons_a_payer: list[dict[str, Any]],
) -> dict[str, str] | None:
    """Contrôle les seules sources du dossier CFO à partir de leurs instantanés déjà capturés."""
    for nom, maillons in (
        ("principal", maillons_mouvements),
        ("factures", maillons_factures),
        ("comptes_a_payer", maillons_a_payer),
    ):
        verdict = _verdict_chaine_financiere(nom, maillons)
        if verdict is not None:
            return verdict
    return None


def _lectures_finance(
    registre_mouvements: registre_module.Registre,
    configuration: dict[str, Any] | None = None,
    *,
    validateur_snapshot: ValidateurSnapshotCfo | None = None,
    inclure_echeanciers_contrats: bool = False,
) -> dict[str, Any]:
    """Tout ce que le cash libre (T4.16) et la prévision de trésorerie (T4.16-d) lisent, lu UNE fois : un instantané,
    donc des chiffres cohérents entre eux. Le registre des mouvements arrive déjà ouvert (la lecture seule de son
    solde est faite par l'outil) ; les factures clientes, les comptes à payer, le calendrier, les taux et la
    configuration sont lus ici. `configuration` : celle que l'appelant a déjà lue (`_configuration_manifeste`), pour
    que tout parte de la même version du manifeste ; absente, elle est lue ici. Lecture pure : rien n'est écrit nulle
    part."""
    if configuration is None:
        configuration = _configuration_manifeste()
    declarees = configuration.get("obligations_declarees")
    declarees = declarees if isinstance(declarees, dict) else {}

    maillons_mouvements = registre_mouvements.lire()
    maillons_factures = _registre_factures(None).lire()
    maillons_a_payer = _registre_comptes_a_payer().lire()
    if validateur_snapshot is not None:
        verdict = validateur_snapshot(maillons_mouvements, maillons_factures, maillons_a_payer)
        if verdict is not None:
            return {"verdict_chaine": verdict}

    maillons_devis = maillons_echeanciers = None
    if inclure_echeanciers_contrats:
        maillons_devis = list(stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_DEVIS_RECUS))
        maillons_echeanciers = list(stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_ECHEANCIERS_CONTRATS))
        verdict = _verdict_chaine_financiere(_NOM_REGISTRE_ECHEANCIERS_CONTRATS, maillons_echeanciers)
        if verdict is not None:
            return {"verdict_chaine": validation.construire_verdict(
                "REJ-CONTRAT-CHAINE-INVALIDE", detail=verdict["detail"]
            )}
        champs_devis = {"devis_id", "lead_id", "chantier_id", "lignes", "prix_total", "horodatage_acceptation"}
        if any(not isinstance(devis, dict) or not champs_devis <= devis.keys() for devis in maillons_devis):
            return {"verdict_chaine": validation.construire_verdict(
                "REJ-CONTRAT-DEVIS-INVALIDE", detail="un devis M3 reçu a une structure absente ou invalide"
            )}
        if any(not isinstance(devis["devis_id"], str) or not devis["devis_id"].strip() for devis in maillons_devis):
            return {"verdict_chaine": validation.construire_verdict(
                "REJ-CONTRAT-DEVIS-INVALIDE", detail="un devis M3 reçu porte un identifiant invalide"
            )}
        identifiants_devis = [devis["devis_id"] for devis in maillons_devis]
        if len(identifiants_devis) != len(set(identifiants_devis)):
            return {"verdict_chaine": validation.construire_verdict(
                "REJ-CONTRAT-DEVIS-INVALIDE", detail="le registre M3 contient plusieurs événements pour un même devis"
            )}

    mouvements = registre_module.Registre(maillons=maillons_mouvements)
    provisions, nombre_provisions, derniere_provision = soldes.calculer_provisions(mouvements)
    factures = registre_module.Registre(maillons=maillons_factures)
    envoyees = facturation.factures_par_statut(factures, "ENVOYEE")
    a_payer = registre_module.Registre(maillons=maillons_a_payer)

    fiscal = configuration.get("fiscal")
    calendrier, verdict_calendrier = _calendrier_fiscal()
    remises = None
    verdict_remise = verdict_calendrier
    if verdict_remise is None:
        configuration_fiscale, verdict_remise = calendrier_fiscal.lire_configuration_fiscale(fiscal)
        if verdict_remise is None:
            remises, verdict_remise = calendrier_fiscal.lire_taxes_remises(fiscal, calendrier, configuration_fiscale)

    dictionnaire_taux, refus_taux = _dictionnaire_taux()
    resume = verdict_a_payer = None
    if refus_taux is not None:
        verdict_a_payer = validation.construire_verdict(refus_taux["code"], detail=refus_taux["detail"])
    else:
        resume, verdict_a_payer = comptes_a_payer.resume_a_payer(a_payer, dictionnaire_taux)

    return {
        "fiscal": fiscal,
        "declarees": declarees,
        "solde": soldes.calculer_solde(mouvements),
        "decrit": soldes.decrire_mouvements(mouvements),
        "provisions": (provisions, nombre_provisions, derniere_provision),
        "factures": factures,
        "maillons_devis": maillons_devis,
        "maillons_echeanciers_contrats": maillons_echeanciers,
        "envoyees": envoyees,
        "clients": [*envoyees, *facturation.factures_par_statut(factures, "PAYEE")],
        "fournisseurs": comptes_a_payer.factures_saisies(a_payer),
        "a_payer": a_payer,
        "calendrier": calendrier,
        "verdict_calendrier": verdict_calendrier,
        "remises": remises,
        "verdict_remise": verdict_remise,
        "dictionnaire_taux": dictionnaire_taux,
        "resume": resume,
        "verdict_a_payer": verdict_a_payer,
        "registres_taxes": [
            cash_libre.registre_lu("factures", maillons_factures),
            cash_libre.registre_lu("comptes_a_payer", maillons_a_payer),
        ],
        "maillons_mouvements": maillons_mouvements,
        "maillons_factures": maillons_factures,
        "maillons_a_payer": maillons_a_payer,
    }


def _resultat_cash_libre(lectures: dict[str, Any]) -> dict[str, Any]:
    """Le cash libre réel (`cash_libre.calculer_cash_libre`), en `Decimal`, depuis `_lectures_finance` : le solde
    moins la TPS/TVQ à remettre, les paies, les DAS, les comptes à payer, les dettes et les réserves critiques, chaque
    composante avec sa source et sa fraîcheur ; une composante inconnue est « non calculable, manque X », jamais zéro
    (voir `cash_libre.py`). La fréquence de production, la fin d'exercice, la date de dernière remise de taxes et les
    montants que rien ne calcule encore (paies, DAS, dettes) viennent de `configuration.fiscal` et
    `configuration.obligations_declarees` de `department.yaml` : absents, ils sont « à déclarer »."""
    declarees = lectures["declarees"]
    provisions, nombre_provisions, derniere_provision = lectures["provisions"]
    return cash_libre.calculer_cash_libre(
        cash_libre.composante_solde(lectures["solde"], lectures["decrit"]),
        [
            cash_libre.composante_taxes(
                lectures["clients"],
                lectures["fournisseurs"],
                lectures["remises"],
                lectures["verdict_remise"],
                lectures["registres_taxes"],
            ),
            cash_libre.composante_declaree("paies", declarees.get("paies")),
            cash_libre.composante_declaree("das", declarees.get("das")),
            cash_libre.composante_comptes_a_payer(
                lectures["resume"], lectures["verdict_a_payer"], lectures["registres_taxes"][1:]
            ),
            cash_libre.composante_declaree("dettes", declarees.get("dettes")),
            cash_libre.composante_reserves(
                provisions, nombre_provisions, derniere_provision, lectures["decrit"], declarees.get("reserves")
            ),
        ],
    )


def _cash_libre(registre_mouvements: registre_module.Registre) -> dict[str, Any]:
    """Le cash libre réel de l'instance, en vue JSON (`cash_libre.vue_cash_libre`) : le solde du registre des
    mouvements moins la TPS/TVQ à remettre, les paies, les DAS, les comptes à payer, les dettes et les réserves
    critiques.

    Lecture pure : chaque registre est lu UNE fois (`_lectures_finance` : un instantané, donc des composantes
    cohérentes entre elles) et rien n'est écrit nulle part. Chaque composante dit sa source et sa fraîcheur ; une
    composante inconnue est « non calculable, manque X », jamais zéro (voir `cash_libre.py`)."""
    return cash_libre.vue_cash_libre(_resultat_cash_libre(_lectures_finance(registre_mouvements)))


def _taxes_par_echeance(resultat: dict[str, Any]) -> None:
    """Ajoute à chaque échéance nommée ce que les registres disent de la TPS/TVQ NETTE de sa période (`taxes_nettes`),
    quand la date de dernière remise est déclarée (sinon on ne sait pas quelles factures sont déjà remises : rien
    n'est chiffré). Une période encore ouverte est PARTIELLE (`periode_terminee` faux) ; une facture illisible rend le
    chiffre « non calculable » (`taxes_nettes` nul avec son manque). Lecture pure."""
    if resultat["taxes_remises_jusqu_au"] is None or not resultat["echeances"]:
        return
    remises = date.fromisoformat(resultat["taxes_remises_jusqu_au"])
    factures = registre_module.Registre(maillons=_registre_factures(None).lire())
    clients = [
        *facturation.factures_par_statut(factures, "ENVOYEE"),
        *facturation.factures_par_statut(factures, "PAYEE"),
    ]
    a_payer = registre_module.Registre(maillons=_registre_comptes_a_payer().lire())
    fournisseurs = comptes_a_payer.factures_saisies(a_payer)
    if not clients and not fournisseurs:
        for echeance in resultat["echeances"]:
            echeance["taxes_nettes"] = None
            echeance["manque"] = [
                validation.construire_verdict(
                    "REJ-FISCAL-COUVERTURE-ABSENTE",
                    detail=(
                        "aucune pièce dans les registres clients et fournisseurs, et aucune attestation de couverture "
                        "de la période : un zéro ne peut pas être confirmé"
                    ),
                )
            ]
        return
    for echeance in resultat["echeances"]:
        debut, fin = date.fromisoformat(echeance["periode_debut"]), date.fromisoformat(echeance["periode_fin"])
        taxes_nettes = cash_libre.calculer_taxes_nettes(
            clients, fournisseurs, apres=max(remises, debut - timedelta(days=1)), jusqu_a=fin
        )
        if taxes_nettes["illisibles"]:
            echeance["taxes_nettes"] = None
            echeance["manque"] = [
                validation.construire_verdict(
                    "REJ-CASH-FACTURE-ILLISIBLE", detail=f"{len(taxes_nettes['illisibles'])} facture(s) illisible(s)"
                )
            ]
        else:
            echeance["taxes_nettes"] = cash_libre.vue_taxes_nettes(taxes_nettes)
            echeance["taxes_nettes"]["couverture"] = {
                "statut": "PARTIELLE",
                "detail": (
                    "les pièces admissibles aux registres sont les seules sources du calcul; aucune preuve ne confirme "
                    "que les périodes et les registres sont complets"
                ),
            }


def lire_echeances_fiscales(
    aujourd_hui: str,
    limite: int | None = None,
    role: str | None = None,
    autorise_couts: bool | None = None,
) -> dict[str, Any]:
    """L'outil `m5_lire_echeances_fiscales` (T0, `admin`) : les prochaines échéances de production et de paiement de
    la TPS et de la TVQ de l'entreprise (`calendrier_fiscal.prochaines_echeances`), avec pour chacune la TPS/TVQ NETTE
    de sa période que les registres portent.

    Même contrôle d'accès que les autres lectures financières : pour un appel d'appareil, l'identité confirmée en base
    (`admin` seulement) ; refus AVANT toute lecture. Sans droit de voir les coûts : les échéances sans aucun montant.
    Sans appareil (agent, console), `autorise_couts` reste obligatoire et explicite.

    `aujourd_hui` (`AAAA-MM-JJ`) est requis : M5 n'a pas d'horloge et ne devine jamais la date. La fréquence de
    production, le mois de fin d'exercice et la date de dernière remise sont ceux du propriétaire
    (`configuration.fiscal` de `department.yaml`) : absents, la réponse est un refus nommé qui dit quoi déclarer. Une
    année non déclarée au calendrier est refusée. Ni remise, ni déclaration, ni paiement, ni écriture : le calendrier
    PROPOSE des dates, à valider par le CPA."""
    acteur, refus = _acteur_appareil()
    if refus is not None:
        return _refus(refus)
    vue, verdict = acces.resoudre_vue(acteur, role, autorise_couts)
    if verdict is not None:
        return _refus(verdict)
    calendrier, refus_calendrier = _calendrier_fiscal()
    if refus_calendrier is not None:
        return _refus(refus_calendrier)
    fiscal = _configuration_manifeste().get("fiscal")
    resultat, verdict = calendrier_fiscal.prochaines_echeances(calendrier, aujourd_hui, fiscal, limite=limite)
    if verdict is not None:
        return _refus(verdict)
    if vue["autorise_couts"]:
        _taxes_par_echeance(resultat)
    return {"accepte": True, "resultat": {"role": vue["role"], **resultat}}


def lire_calendrier_obligations(
    aujourd_hui: str,
    limite: int | None = None,
    role: str | None = None,
    autorise_couts: bool | None = None,
) -> dict[str, Any]:
    """Calendrier préparatoire des échéances M5 documentées et du calendrier TPS/TVQ.

    Les valeurs viennent des obligations déjà déclarées, des échéances explicites de prévision et des sources
    annuelles que l'entreprise a déclarées. Données incomplètes restent des lignes visibles avec leur manque.
    Une échéance passée signifie « à vérifier » : aucun paiement ni dépôt n'est inféré.
    """
    acteur, refus = _acteur_appareil()
    if refus is not None:
        return _refus(refus)
    vue, verdict = acces.resoudre_vue(acteur, role, autorise_couts)
    if verdict is not None:
        return _refus(verdict)
    configuration = _configuration_manifeste()
    prevision_config = configuration.get("prevision")
    prevision_config = prevision_config if isinstance(prevision_config, dict) else {}
    try:
        obligations = calendrier_obligations.lire_obligations_documentees(
            aujourd_hui,
            configuration.get("obligations_declarees"),
            prevision_config.get("echeances_obligations"),
            configuration.get("calendrier_obligations"),
        )
    except ValueError as exc:
        return _refus(validation.construire_verdict("REJ-CALENDRIER-PREP-DATE-INVALIDE", detail=str(exc)))

    taxes = lire_echeances_fiscales(aujourd_hui, limite=limite, role=vue["role"], autorise_couts=vue["autorise_couts"])
    if taxes.get("accepte") is True:
        calendrier_taxes: dict[str, Any] = {"statut": "DOCUMENTE_A_VALIDER", **taxes["resultat"]}
    else:
        verdict_taxes = taxes.get("verdict", {})
        calendrier_taxes = {
            "statut": "NON_CALCULABLE",
            "manque": [verdict_taxes] if isinstance(verdict_taxes, dict) else [],
        }

    lignes = obligations["obligations"]
    if not vue["autorise_couts"]:
        for ligne in lignes:
            ligne["montant"] = None
            ligne["montant_utilisable"] = None
            ligne["devise"] = None
            ligne["manque"].append(
                validation.construire_verdict(
                    "REJ-AUTORISE-COUTS-REQUIS", detail="montants masqués selon le droit de l'appelant"
                )
            )
    return {
        "accepte": True,
        "resultat": {
            "role": vue["role"],
            "type": "CALENDRIER_PREPARATOIRE_M5",
            "aujourd_hui": obligations["aujourd_hui"],
            "obligations": lignes,
            "echeances_tps_tvq": calendrier_taxes,
            "limites": [
                *obligations["limites"],
                "les échéances TPS/TVQ officielles sont versionnées et restent à valider par le CPA",
            ],
            "mention": analyse.MENTION_ANALYSE_PREPARATOIRE,
        },
    }


def _mouvements_pour_decision_capital() -> registre_module.Registre:
    """L'adaptateur unique du registre financier pour l'outil capital (lecture seule)."""
    return _registre_mouvements(None)


# --------------------------------------------------------------------- prévision de trésorerie (T4.16-d)
def _reglages_prevision(
    aujourd_hui: Any,
    horizon_semaines: Any,
    semaine: Any,
    depart: Any,
    configuration: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Ce que la prévision demande, avant de lire le moindre registre : `(réglages, None)` ou `(None, verdict)`.

    `aujourd_hui` (AAAA-MM-JJ) est requis : M5 n'a pas d'horloge. L'horizon est l'argument, ou celui que le
    propriétaire a déclaré (`configuration.prevision.horizon_semaines`) ; ni l'un ni l'autre :
    `REJ-PREVISION-HORIZON-A-CONFIGURER`, aucun horizon n'est supposé. `configuration.prevision` est relue à chaque
    appel ; une clé inconnue est refusée (`REJ-PREVISION-CONFIGURATION-INVALIDE`). `semaine` et `depart` sont validés
    avec la page qu'ils choisissent. La configuration lue est celle dont toute la prévision part (un seul instantané
    du manifeste)."""
    jour, verdict = prevision.lire_jour(aujourd_hui)
    if verdict is not None:
        return None, verdict
    configuration = _configuration_manifeste() if configuration is None else configuration
    prevu, verdict = prevision.lire_reglages(configuration.get("prevision"))
    if verdict is not None:
        return None, verdict
    horizon, verdict = prevision.lire_horizon(
        prevu.get("horizon_semaines") if horizon_semaines is None else horizon_semaines
    )
    if verdict is not None:
        return None, verdict
    return {
        "aujourd_hui": jour,
        "horizon": horizon,
        "semaine": semaine,
        "depart": 0 if depart is None else depart,
        "configuration": configuration,
        "prevu": prevu,
    }, None


def _projection_capital_non_calculable(horizon: Any, raison: str) -> dict[str, Any]:
    return {
        "statut": "NON_CALCULABLE",
        "horizon_semaines": horizon,
        "manque": [raison],
        "flux_connus_inclus": [],
        "flux_encaissements_non_comptes": [],
        "options": {
            nom: {
                "statut": "NON_CALCULABLE",
                "solde_fin": None,
                "plus_bas": None,
                "manque": [raison],
                "flux_scenario": [],
                "sorties_hors_horizon": {"nombre": 0, "total": "0.00", "non_chiffres": 0},
            }
            for nom in ("achat_comptant", "financement", "location")
        },
    }


def _json_capital_tient_budget(rapport: dict[str, Any], role: str | None) -> bool:
    return len(json.dumps({"role": role, **rapport}, ensure_ascii=False, default=str)) <= BUDGET_SORTIE


def _ajouter_projection_scenarios_capital(
    rapport: dict[str, Any],
    sorties_scenarios: dict[str, list[dict[str, Any]] | None],
    lectures: dict[str, Any],
    configuration: dict[str, Any],
    aujourd_hui: str,
    cash: dict[str, Any],
    role: str | None,
) -> dict[str, Any] | None:
    """Ajoute la projection au même snapshot; retourne un verdict si le rapport complet ne tient pas."""
    reglages, verdict = _reglages_prevision(aujourd_hui, None, None, 0, configuration)
    if verdict is not None:
        code = verdict.get("code", "REJ-PREVISION-CONFIGURATION-INVALIDE")
        rapport["projections_scenarios"] = _projection_capital_non_calculable(
            None, f"configuration de prévision non disponible : {code}"
        )
    else:
        cash_projection, flux_connus, _seuil, _verdict_seuil = _flux_connus_prevision(lectures, reglages)
        projections = prevision.projeter_scenarios(
            reglages["aujourd_hui"],
            reglages["horizon"],
            cash_projection["solde"],
            flux_connus,
            sorties_scenarios,
        )
        rapport["projections_scenarios"] = {
            "statut": "CALCULE"
            if all(option["statut"] == "CALCULE" for option in projections["options"].values())
            else "PARTIEL",
            "horizon_semaines": reglages["horizon"],
            **projections,
        }

    rapport.pop("cash_libre_source", None)
    rapport.pop("sources_a_valider", None)
    rapport["cash_libre_composantes"] = [
        {
            "id": composante["id"],
            "statut": composante["statut"],
            "montant": composante["montant"],
            "source": {
                "de": composante["source"].get("de"),
                "registres": composante["source"].get("registres", []),
            },
            "fraicheur": composante["fraicheur"],
            "manque": composante["manque"],
        }
        for composante in rapport["cash_libre_composantes"]
    ]
    rapport["contexte_financier"]["cash_libre"] = {
        "calculable": cash["calculable"],
        "cash_libre": cash["cash_libre"],
        "manque": cash["manque"],
        "reserves": cash["reserves"],
    }
    rapport["contexte_financier"]["limite_flux"] = (
        "Les soldes hypothétiques utilisent le solde du registre et les flux connus/datés du même snapshot; "
        "les créances échues ou sans date ne sont pas comptées, et les obligations restent des déclarations saisies."
    )
    for cle in ("comptes_a_recevoir", "comptes_a_recevoir_manque", "comptes_a_payer", "devis_acceptes"):
        rapport["contexte_financier"].pop(cle, None)

    if _json_capital_tient_budget(rapport, role):
        return None

    rapport["projections_scenarios"] = _projection_capital_non_calculable(
        rapport["projections_scenarios"].get("horizon_semaines"),
        "provenance et scénarios dépassent le budget de sortie; aucun solde projeté n'est présenté",
    )
    if _json_capital_tient_budget(rapport, role):
        return None
    return validation.construire_verdict(
        "REJ-PREVISION-REPONSE-TROP-GROSSE",
        detail=(
            "le rapport complet dépasse le budget après omission des soldes projetés; "
            "aucune rubrique n'a été tronquée"
        ),
    )


def _preparer_decision_capital_impl(
    actif: str,
    prix: str,
    source_prix: str,
    prix_valide_jusqua: str,
    aujourd_hui: str,
    offre_financement: dict[str, Any],
    offre_location: dict[str, Any],
    echeanciers_hypothetiques: dict[str, Any] | None = None,
    role: str | None = None,
    autorise_couts: bool | None = None,
    *,
    _agent_autorise: bool = False,
) -> dict[str, Any]:
    """Analyse préparatoire en lecture seule, à partir du même registre financier que l'état CFO."""
    acteur, refus = _acteur_appareil()
    if refus is not None:
        return _refus(refus)
    vue, verdict = (
        ({"role": None, "autorise_couts": True}, None)
        if _agent_autorise
        else acces.resoudre_vue(acteur, role, autorise_couts)
    )
    if verdict is not None:
        return _refus(verdict)
    if not vue["autorise_couts"]:
        return {"accepte": True, "resultat": analyse.avec_mention({"role": vue["role"], "montants_masques": True})}
    sorties_scenarios, verdict_echeanciers = decision_capital.normaliser_echeanciers(
        echeanciers_hypothetiques, prix, offre_financement, offre_location
    )
    if verdict_echeanciers is not None:
        return _refus(verdict_echeanciers)
    configuration = _configuration_manifeste()
    lectures = _lectures_finance(
        _mouvements_pour_decision_capital(),
        configuration,
        validateur_snapshot=_valider_chaines_cfo if _agent_autorise else None,
    )
    if _agent_autorise and lectures.get("verdict_chaine"):
        return _refus(lectures["verdict_chaine"])
    cash = _resultat_cash_libre(lectures)
    snapshot = {
        "calculable": cash["calculable"],
        "cash_libre": cash["cash_libre"],
        "manque": cash["manque"],
        "sources": [c["source"]["description"] for c in [cash["solde"], *cash["composantes"]]],
        "composantes": [
            {
                "id": c["id"],
                "statut": c["statut"],
                "montant": c["montant"],
                "source": c["source"],
                "fraicheur": c["fraicheur"],
                "manque": c["manque"],
            }
            for c in [cash["solde"], *cash["composantes"]]
        ],
    }
    resultat = decision_capital.preparer(
        actif,
        prix,
        source_prix,
        prix_valide_jusqua,
        aujourd_hui,
        snapshot,
        offre_financement,
        offre_location,
    )
    if not resultat["accepte"]:
        return _refus(resultat["verdict"])
    rapport = resultat["resultat"]

    # Le rapport réutilise les mêmes registres canoniques que cash libre et comptes à recevoir.
    # Il ne transforme pas un devis accepté en contrat légal ni un encaissement attendu en cash.
    maillons_devis = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_DEVIS_RECUS)
    montants_devis: list[Decimal] = []
    manquants_devis: list[str] = []
    for devis in maillons_devis:
        try:
            montant_devis = _vers_montant_decimal(str(devis.get("prix_total", "")))
        except (ValueError, ArithmeticError):
            manquants_devis.append("prix_total d'un devis accepté illisible")
        else:
            if not montant_devis.is_finite() or montant_devis < 0 or montant_devis.adjusted() > 11:
                manquants_devis.append("prix_total d'un devis accepté hors domaine")
            else:
                montants_devis.append(montant_devis)
    if len(montants_devis) != len(maillons_devis):
        valeur_devis = None
        statut_devis = "NON_CALCULABLE"
    else:
        valeur_devis = format(sum(montants_devis, Decimal("0")), ".2f")
        statut_devis = "CALCULE"

    comptes_a_recevoir, verdict_ar = facturation.comptes_a_recevoir(lectures["factures"], aujourd_hui)
    ar_resume = (
        None
        if verdict_ar is not None
        else {
            "nombre": comptes_a_recevoir["nombre"],
            "total_a_recevoir": format(comptes_a_recevoir["total_a_recevoir"], ".2f"),
            "total_complet": comptes_a_recevoir["total_complet"],
            "source": {
                "registre": lectures["registres_taxes"][0],
                "statut": "VERIFIE" if comptes_a_recevoir["total_complet"] else "PARTIEL_NON_CALCULABLE",
            },
            "illisibles": comptes_a_recevoir["illisibles"],
        }
    )
    rapport["contexte_financier"] = {
        "comptes_a_recevoir": ar_resume,
        "comptes_a_recevoir_manque": verdict_ar,
        "comptes_a_payer": next((c for c in snapshot["composantes"] if c["id"] == "comptes_a_payer"), None),
        "devis_acceptes": {
            "statut": statut_devis,
            "nombre": len(maillons_devis),
            "valeur_cad": valeur_devis,
            "source": {"registre": _NOM_REGISTRE_DEVIS_RECUS, "statut": "EVENEMENTS_M3_RECUS"},
            "manque": manquants_devis,
            "limite": "Valeur de devis acceptés, sans échéancier contractuel ni prévision d'encaissement.",
        },
        "termes_contractuels_signes": {
            "statut": "NON_DISPONIBLE",
            "manque": ["contrat signé et échéancier de dépôts/jalons non présents dans les contrats M5 actuels"],
        },
        "provenance_des_offres": {
            "statut": "REFERENCE_MANUELLE_NON_VERIFIEE",
            "prix": source_prix,
            "financement": offre_financement["source"],
            "location": offre_location["source"],
            "limite": "Références fournies par l'appelant; aucun document ni connecteur externe n'a été vérifié.",
        },
        "cash_libre": cash_libre.vue_cash_libre(cash),
    }
    if sorties_scenarios is not None:
        verdict_budget = _ajouter_projection_scenarios_capital(
            rapport, sorties_scenarios, lectures, configuration, aujourd_hui, cash, vue["role"]
        )
        if verdict_budget is not None:
            return _refus(verdict_budget)
    return {"accepte": True, "resultat": {"role": vue["role"], **rapport}}


def preparer_decision_capital(
    actif: str,
    prix: str,
    source_prix: str,
    prix_valide_jusqua: str,
    aujourd_hui: str,
    offre_financement: dict[str, Any],
    offre_location: dict[str, Any],
    echeanciers_hypothetiques: dict[str, Any] | None = None,
    role: str | None = None,
    autorise_couts: bool | None = None,
) -> dict[str, Any]:
    arguments = contexte.arguments_ticket_agent_cfo() or {
        "actif": actif,
        "prix": prix,
        "source_prix": source_prix,
        "prix_valide_jusqua": prix_valide_jusqua,
        "aujourd_hui": aujourd_hui,
        "offre_financement": offre_financement,
        "offre_location": offre_location,
        **({"echeanciers_hypothetiques": echeanciers_hypothetiques} if echeanciers_hypothetiques is not None else {}),
        **({"role": role} if role is not None else {}),
        **({"autorise_couts": autorise_couts} if autorise_couts is not None else {}),
    }
    ticket = contexte.ticket_agent_cfo()
    if ticket is None:
        return _preparer_decision_capital_impl(**arguments)
    from opsys import agent_cfo_grants

    with stockage.transaction() as cnx:
        agent_cfo_grants.consommer(
            cnx,
            ticket,
            "m5_preparer_decision_capital",
            arguments,
            instance_id=agent_cfo_grants.instance_id(cnx),
        )
        return _preparer_decision_capital_impl(
            **{**arguments, "role": None, "autorise_couts": True, "_agent_autorise": True}
        )


def _dettes_fournisseurs(lectures: dict[str, Any]) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
    """Les dettes fournisseurs une à une (`comptes_a_payer.dettes_datables`), ou le verdict qui empêche de les chiffrer
    (le fichier des taux illisible, un taux manquant) : le même que celui du cash libre."""
    if lectures["dictionnaire_taux"] is None:
        return None, lectures["verdict_a_payer"]
    return comptes_a_payer.dettes_datables(lectures["a_payer"], lectures["dictionnaire_taux"])


def _flux_connus_prevision(
    lectures: dict[str, Any], reglages: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any] | None, dict[str, Any] | None]:
    """Monte les flux canoniques à partir d'un snapshot déjà lu, pour prévision et scénarios capital."""
    cash = _resultat_cash_libre(lectures)
    prevu = reglages["prevu"]
    seuil, verdict_seuil = prevision.lire_seuil(prevu.get("seuil_alerte"))
    delai_clients, verdict_clients = prevision.lire_delai(
        prevu.get("delai_encaissement_clients_jours"),
        "delai_encaissement_clients_jours",
        "REJ-PREVISION-DELAI-CLIENTS-A-DECLARER",
    )
    delai_fournisseurs, verdict_fournisseurs = prevision.lire_delai(
        prevu.get("delai_paiement_fournisseurs_jours"),
        "delai_paiement_fournisseurs_jours",
        "REJ-PREVISION-DELAI-FOURNISSEURS-A-DECLARER",
    )
    dettes, verdict_dettes = _dettes_fournisseurs(lectures)
    flux = [
        *prevision.flux_clients(lectures["envoyees"], delai_clients, verdict_clients),
        *prevision.flux_fournisseurs(dettes, delai_fournisseurs, verdict_fournisseurs, verdict_dettes),
        *prevision.flux_taxes(
            lectures["clients"],
            lectures["fournisseurs"],
            lectures["calendrier"],
            lectures["verdict_calendrier"],
            lectures["fiscal"],
            reglages["aujourd_hui"],
        ),
        *prevision.flux_obligations(
            {c["id"]: c for c in cash["composantes"]},
            prevision.lire_echeances_obligations(prevu.get("echeances_obligations")),
        ),
    ]
    return cash, flux, seuil, verdict_seuil


def _page_prevision(
    registre_mouvements: registre_module.Registre,
    reglages: dict[str, Any],
    *,
    lectures: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """La prévision de trésorerie, en une page JSON sous `BUDGET_SORTIE` (jamais tronquée par le socle) : `(page,
    None)` ou `(None, verdict)`. Sans `semaine`, la série (page de semaines, `depart` en rang de semaine) ; avec, les
    lignes de cette semaine (`depart` en rang de ligne), chacune avec sa source.

    Lecture pure. Tout part du même instantané (`_lectures_finance`) : le solde et le cash libre de T4.16, les
    factures clientes envoyées (encaissements), les dettes fournisseurs, les périodes de taxes du calendrier fiscal,
    les paies, DAS et dettes déclarées. Ce que le propriétaire décide (`configuration.prevision` : seuil d'alerte,
    délais de paiement, date de sortie des obligations déclarées) est dit à `prevision.py`, qui date chaque flux, le
    place, additionne et dit ce qui manque : ici, rien n'est calculé."""
    if lectures is None:
        lectures = _lectures_finance(registre_mouvements, reglages["configuration"])
    cash, flux, seuil, verdict_seuil = _flux_connus_prevision(lectures, reglages)
    resultat = prevision.assembler(
        reglages["aujourd_hui"],
        reglages["horizon"],
        cash["solde"],
        flux,
        seuil=seuil,
        verdict_seuil=verdict_seuil,
        cash_libre_resultat=cash,
    )
    if reglages["semaine"] is not None:
        return prevision.vue_semaine(
            resultat, reglages["semaine"], depart=reglages["depart"], budget_caracteres=BUDGET_SORTIE
        )
    return prevision.vue_prevision(resultat, depart=reglages["depart"], budget_caracteres=BUDGET_SORTIE)


def prevoir_tresorerie(
    aujourd_hui: str,
    horizon_semaines: int | None = None,
    semaine: int | None = None,
    depart: int | None = None,
    role: str | None = None,
    autorise_couts: bool | None = None,
) -> dict[str, Any]:
    """L'outil `m5_prevoir_tresorerie` (T0, `admin`) : la prévision de trésorerie des flux CONNUS et DATÉS
    (`prevision.py`), semaine par semaine sur `horizon_semaines` semaines de 7 jours à partir d'`aujourd_hui`.

    Même contrôle d'accès que les autres lectures financières : pour un appel d'appareil, l'identité confirmée en base
    (`admin` seulement), la vue vient du rôle authentifié, un argument ne peut que la restreindre ; refus AVANT toute
    lecture. Sans droit de voir les coûts : l'horizon seulement, aucun montant, aucune alerte. Sans appareil (agent,
    console), `autorise_couts` reste obligatoire et explicite.

    `aujourd_hui` est requis (M5 n'a pas d'horloge) ; l'horizon est l'argument ou celui du propriétaire, sinon refus
    nommé (aucun horizon n'est supposé). Aucun montant, date ni délai ne se passe en argument : tout est lu à la
    source ou déclaré par le propriétaire (`configuration.prevision`). Une donnée inconnue rend les semaines
    concernées « non calculables », avec ce qui manque : ce n'est pas un refus. Ni paiement, ni remise, ni
    déclaration, ni écriture : la prévision PROPOSE, à valider par le propriétaire et le CPA."""
    acteur, refus = _acteur_appareil()
    if refus is not None:
        return _refus(refus)
    vue, verdict = acces.resoudre_vue(acteur, role, autorise_couts)
    if verdict is not None:
        return _refus(verdict)
    reglages, verdict = _reglages_prevision(aujourd_hui, horizon_semaines, semaine, depart)
    if verdict is not None:
        return _refus(verdict)
    if not vue["autorise_couts"]:
        masquee = {"role": vue["role"], "montants_masques": True, "horizon_semaines": reglages["horizon"]}
        return {"accepte": True, "resultat": analyse.avec_mention(masquee)}
    page, verdict = _page_prevision(_registre_mouvements(None), reglages)
    if verdict is not None:
        return _refus(verdict)
    return {"accepte": True, "resultat": {"role": vue["role"], **page}}


def _preparer_dossier_decision_cfo_impl(
    aujourd_hui: str, question_posee: str, *, _agent_autorise: bool = False,
    volet: str = "dossier_complet",
) -> dict[str, Any]:
    """Compose le rapport M5.16 en lecture seule depuis les registres financiers capturés une fois."""
    acteur, refus = _acteur_appareil()
    if refus is not None:
        return _refus(refus)
    vue, verdict = (
        ({"role": None, "autorise_couts": True}, None) if _agent_autorise else acces.resoudre_vue(acteur, None, None)
    )
    if verdict is not None:
        return _refus(verdict)
    if not vue["autorise_couts"]:
        return _refus(
            validation.construire_verdict(
                "REJ-CFO-COUTS-REQUIS", detail="le rapport CFO contient des montants et exige le droit M5 actif"
            )
        )
    if not isinstance(question_posee, str) or not 1 <= len(question_posee.strip()) <= 1000:
        return _refus(
            validation.construire_verdict("REJ-CFO-QUESTION-INVALIDE", detail="question_posee : 1 à 1000 caractères")
        )
    if volet not in ("dossier_complet", "obligations_preparees"):
        return _refus(validation.construire_verdict("REJ-CFO-VOLET-INVALIDE", detail="volet CFO inconnu"))
    jour, verdict = prevision.lire_jour(aujourd_hui)
    if verdict is not None:
        return _refus(verdict)

    from . import obligations_preparees as ob

    try:
        snapshot_obligations = _snapshot_obligations_preparees()
        lecture_obligations = ob.lire(snapshot_obligations, jour.isoformat(), 0, 3)
    except ob.Refus as exc:
        return _refus(exc.verdict)

    configuration = _configuration_manifeste()
    configuration_prevision = configuration.get("prevision")
    configuration_prevision = configuration_prevision if isinstance(configuration_prevision, dict) else {}
    try:
        obligations_documentees = calendrier_obligations.lire_obligations_documentees(
            jour.isoformat(),
            configuration.get("obligations_declarees"),
            configuration_prevision.get("echeances_obligations"),
            configuration.get("calendrier_obligations"),
        )
    except ValueError as exc:
        obligations_documentees = None
        manques_obligations = [f"calendrier des obligations : {exc}"]
    else:
        manques_obligations = []
    registre_mouvements = _mouvements_pour_decision_capital()
    lectures = _lectures_finance(registre_mouvements, configuration, validateur_snapshot=_valider_chaines_cfo)
    if verdict := lectures.get("verdict_chaine"):
        return _refus(verdict)
    cash = cash_libre.vue_cash_libre(_resultat_cash_libre(lectures))
    ar, verdict_ar = facturation.comptes_a_recevoir(lectures["factures"], jour.isoformat())
    ar_resume = None
    manques_source: list[str] = list(manques_obligations)
    if verdict_ar is not None:
        manques_source.append(f"comptes à recevoir : {verdict_ar.get('code', 'source invalide')}")
    elif ar is not None:
        ar_resume = {
            "nombre": ar["nombre"],
            "total_a_recevoir_cad": format(ar["total_a_recevoir"], ".2f"),
            "total_complet": ar["total_complet"],
            "illisibles": len(ar["illisibles"]),
        }
        if ar["illisibles"]:
            manques_source.append(f"{len(ar['illisibles'])} facture(s) envoyée(s) illisible(s)")

    ap_resume = None
    if lectures["resume"] is None:
        verdict_ap = lectures["verdict_a_payer"] or {}
        manques_source.append(f"comptes à payer : {verdict_ap.get('code', 'source invalide')}")
    else:
        resume = lectures["resume"]
        ap_resume = {
            "nombre_po": resume["nombre_po"],
            "complet": resume["complet"],
            "a_payer_apres_taxes_cad": (
                format(resume["a_payer_apres_taxes"], ".2f") if resume["a_payer_apres_taxes"] is not None else None
            ),
            "a_payer_connu_apres_taxes_cad": format(resume["a_payer_connu_apres_taxes"], ".2f"),
            "non_calculables": resume["non_calculables"],
            "pieces": resume["pieces"],
            "derniere_piece": resume["derniere_piece"],
        }

    reglages, verdict_reglages = _reglages_prevision(jour.isoformat(), 26, None, 0, configuration)
    prevision_vue = None
    if verdict_reglages is not None:
        manques_source.append(f"prévision : {verdict_reglages.get('code', 'réglages invalides')}")
    else:
        prevision_vue, verdict_prevision = _page_prevision(registre_mouvements, reglages, lectures=lectures)
        if verdict_prevision is not None:
            manques_source.append(f"prévision : {verdict_prevision.get('code', 'non calculable')}")
            prevision_vue = None

    def ref(registre: str, maillons: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "departement": _DEPARTEMENT,
            "registre": registre,
            "taille": len(maillons),
            "tete": maillons[-1].get("ligne_id") if maillons else None,
        }

    sources = [
        ref("principal", lectures["maillons_mouvements"]),
        ref("factures", lectures["maillons_factures"]),
        ref("comptes_a_payer", lectures["maillons_a_payer"]),
    ]
    rapport = dossier_decision_cfo.composer(
        question_posee=question_posee,
        aujourd_hui=jour.isoformat(),
        cash=cash,
        comptes_a_recevoir=ar_resume,
        comptes_a_payer=ap_resume,
        prevision=prevision_vue,
        source_refs=sources,
        mention=analyse.MENTION_ANALYSE_PREPARATOIRE,
        manques_source=manques_source,
        configuration_id=dossier_decision_cfo.empreinte(configuration),
        calendrier_obligations=obligations_documentees,
        obligations_preparees={
            "source_ref": ref(ob.REGISTRE, snapshot_obligations), "lecture": lecture_obligations,
        },
        volet=volet,
    )
    enveloppe = {"ok": True, "resultat": {"accepte": True, "resultat": rapport}}
    borne = contexte.limite_sortie()
    hors_borne = type(borne) is int and len(json.dumps(enveloppe, ensure_ascii=False, default=str)) > borne
    if hors_borne or len(json.dumps(rapport, ensure_ascii=False, default=str)) > BUDGET_SORTIE:
        return _refus(
            validation.construire_verdict(
                "REJ-PREVISION-REPONSE-TROP-GROSSE",
                detail="la représentation demandée dépasse le budget; aucune donnée n'a été tronquée",
            )
        )
    return {"accepte": True, "resultat": rapport}


def preparer_dossier_decision_cfo(
    aujourd_hui: str, question_posee: str, *, volet: str | None = None,
) -> dict[str, Any]:
    # None représente uniquement l'absence historique du paramètre (le schéma refuse null).
    choix = {} if volet is None else {"volet": volet}
    ticket = contexte.ticket_agent_cfo()
    if ticket is None:
        return _preparer_dossier_decision_cfo_impl(aujourd_hui, question_posee, **choix)
    from opsys import agent_cfo_grants

    arguments = {"aujourd_hui": aujourd_hui, "question_posee": question_posee, **choix}
    transmis = contexte.arguments_ticket_agent_cfo()
    if transmis is not None and transmis != arguments:
        raise agent_cfo_grants.GrantCfoRefuse("arguments CFO effectifs différents du contexte du ticket")
    with stockage.transaction() as cnx:
        agent_cfo_grants.consommer(
            cnx,
            ticket,
            "m5_preparer_dossier_decision_cfo",
            arguments,
            instance_id=agent_cfo_grants.instance_id(cnx),
        )
        return _preparer_dossier_decision_cfo_impl(
            aujourd_hui, question_posee, _agent_autorise=True, **choix,
        )


# ------------------------------------------------------------ constat du cash libre au bus (T4.19-b)
def _constater_cash_libre(registre_mouvements: registre_module.Registre, jour: date) -> dict[str, Any]:
    """Calcule le cash libre, le trace et le publie : `{"deja_constate", "publie", "constat"}`. Écrit, donc jamais
    appelée par une lecture : seul `constater_cash_libre` l'appelle, après tous ses refus.

    Le cash libre vient du MÊME instantané que celui de `m5_etat_tresorerie` (`_lectures_finance`,
    `_resultat_cash_libre` : aucun calcul de plus). Le registre des mouvements arrive déjà ouvert : cette fonction ne
    le nomme pas et n'y écrit rien.

    Un constat par date de référence et par version des données : si le DERNIER constat du registre
    `constats_cash_libre` porte ce jour et cette version, rien n'est écrit ni publié (`deja_constate`, l'identifiant
    de ce constat est rendu) ; sinon le constat prend le rang suivant, est tracé, et `m5.cash_libre_constate` part
    dans la MÊME transaction (une charge qui ne tient pas au catalogue LÈVE : ni trace ni événement, jamais un
    constat à demi publié). La comparaison est avec le DERNIER constat seulement : un retour à une version
    antérieure (une déclaration du propriétaire remise à sa valeur d'avant) est un nouveau constat, au rang suivant,
    que le bus ne peut donc pas avaler comme un doublon. Deux appels simultanés au même rang : le second lève
    (`EcritureConcurrente`), l'appel est à rejouer."""
    resultat = _resultat_cash_libre(_lectures_finance(registre_mouvements))
    constats = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_CONSTATS)
    rang = len(constats)
    dernier = constats[-1] if rang else None
    if dernier is not None and (dernier["date_reference"], dernier["version_donnees"]) == (
        jour.isoformat(),
        resultat["cash_libre_id"],
    ):
        charge = constat_cash_libre.charge_evenement(resultat, jour, dernier["sequence"])
        resume = {**constat_cash_libre.resume(charge), "evenement_id": dernier["evenement_id"]}
        return {"deja_constate": True, "publie": False, "constat": resume}
    charge = constat_cash_libre.charge_evenement(resultat, jour, rang + 1)
    constats.append(constat_cash_libre.construire_trace(charge))
    evenements.publier(
        constat_cash_libre.TYPE_EVENEMENT_CASH_LIBRE, _DEPARTEMENT, charge, evenement_id=charge["evenement_id"]
    )
    return {"deja_constate": False, "publie": True, "constat": constat_cash_libre.resume(charge)}


def constater_cash_libre(
    aujourd_hui: str,
    role: str | None = None,
    autorise_couts: bool | None = None,
) -> dict[str, Any]:
    """L'outil `m5_constater_cash_libre` (T1, N3, `admin`) : fait constater le cash libre réel du jour et le publie
    au bus (`m5.cash_libre_constate`), pour que M8 l'affiche dans la vue exécutive (`constat_cash_libre.py`).

    Écriture INTERNE non finale (T1) : le constat et son événement, dans la même transaction. Aucun mouvement, aucune
    facture, aucun paiement, aucune remise : le registre des mouvements est ouvert pour en tirer le solde, jamais
    écrit.

    Même contrôle d'accès que les autres lectures financières : pour un appel d'appareil, l'identité confirmée en
    base (`admin` seulement) ; la vue vient du rôle authentifié. Un constat PUBLIE des montants : sans le droit de
    voir les coûts (un `autorise_couts` faux, ou un rôle qui ne l'a pas), il est refusé (`REJ-CONSTAT-COUTS-REQUIS`),
    jamais publié sans montant. Sans appareil (agent, console), `autorise_couts` reste obligatoire et explicite. Tout
    refus vient AVANT la lecture du moindre registre.

    `aujourd_hui` (`AAAA-MM-JJ`) est requis : M5 n'a pas d'horloge, c'est la date de référence du constat, jamais
    devinée. Hors du stockage durable, il n'y a ni registre réel ni bus où publier : refusé
    (`REJ-CONSTAT-STOCKAGE-NON-DURABLE`), jamais un « solde absent » publié pour un registre qui n'a simplement pas
    été lu."""
    acteur, refus = _acteur_appareil()
    if refus is not None:
        return _refus(refus)
    vue, verdict = acces.resoudre_vue(acteur, role, autorise_couts)
    if verdict is not None:
        return _refus(verdict)
    if not vue["autorise_couts"]:
        return _refus(
            validation.construire_verdict(
                "REJ-CONSTAT-COUTS-REQUIS",
                detail="un constat du cash libre publie des montants : il exige le droit de voir les coûts "
                "(autorise_couts vrai)",
            )
        )
    jour, verdict = constat_cash_libre.lire_jour(aujourd_hui)
    if verdict is not None:
        return _refus(verdict)
    if not _stockage_durable_actif:
        return _refus(
            validation.construire_verdict(
                "REJ-CONSTAT-STOCKAGE-NON-DURABLE",
                detail="le registre des mouvements n'est pas adossé au stockage durable : aucun registre réel à "
                "constater, aucun bus où publier",
            )
        )
    constat = _constater_cash_libre(_registre_mouvements(None), jour)
    return {"accepte": True, "resultat": analyse.avec_mention({"role": vue["role"], **constat})}


def _recevoir_variance_chantier(charge: dict[str, Any]) -> dict[str, Any]:
    """Consomme `m6.variance_chantier` (PLAN T1.3-c point 4, catalogue existant, M6 en est
    propriétaire) : garde le DERNIER signal connu par wct_id (`variance_recus.py`) — jamais un
    verrou sur la facture (M6 « signale seulement »). `attentes()` l'affiche à côté d'une facture
    BROUILLON quand il est critique, sans jamais bloquer son envoi."""
    registre = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_VARIANCE_RECUE)
    registre.append(
        variance_recus.construire(
            wct_id=charge["wct_id"],
            chantier_id=charge["chantier_id"],
            statut_variance=charge["statut_variance"],
            signal_critique=charge["signal_critique"],
            horodatage_completion=charge["horodatage_completion"],
            lignes=charge.get("lignes"),
        )
    )
    return {
        "traite": True,
        "wct_id": charge["wct_id"],
        "statut_variance": charge["statut_variance"],
        "cout_reel": _essayer_cout_reel_pour_wct(charge["wct_id"])["statut"],
    }


def _recevoir_client_associe(charge: dict[str, Any]) -> dict[str, Any]:
    """Consomme `m2.client_associe` (PLAN T2.2, catalogue M2) : garde le lien lead_id -> client_id
    (`clients_recus.py`, idempotent par lead_id), pour que `_essayer_facture_brouillon` facture le
    VRAI client_id du Client 360 M2 dès qu'il est connu. N'essaie PAS de facturer ici : ce type
    d'événement arrive à l'ingestion du lead, bien avant qu'un devis_id soit même connaissable
    (voir docstring du module) — rien à tenter tant qu'aucun devis n'existe pour ce lead."""
    lead_id = charge["lead_id"]
    registre = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_CLIENTS_RECUS)
    if clients_recus.pour_lead_id(lead_id, registre) is None:
        registre.append(
            clients_recus.construire(
                lead_id=lead_id,
                client_id=charge["client_id"],
                horodatage_association=charge["horodatage_association"],
            )
        )
    return {"traite": True, "lead_id": lead_id, "client_id": charge["client_id"]}


def consommateurs() -> dict[str, Callable[[dict], dict]]:
    return {
        "m2.client_associe": _recevoir_client_associe,
        "m3.devis_accepte": _recevoir_devis_accepte,
        "m4.travaux_termines": _recevoir_travaux_termines,
        "m6.variance_chantier": _recevoir_variance_chantier,
        comptes_a_payer.TYPE_EVENEMENT_RECEPTION: _recevoir_reception_enregistree,
    }


def _actualiser_rentabilite_apres_transition_facture(
    facture_id: str,
    registre_cible: registre_module.Registre,
    factures_historique: list[dict[str, Any]] | None,
) -> None:
    """Dans la transaction humaine : état courant de la facture → trace et événement dérivés.

    Le maillon de transition ne contient pas le devis : retrouver celui-ci dans la vue canonique,
    sans refaire la fusion des maillons. Les simulations avec historique injecté restent isolées.
    Une panne de publication annule aussi la transition via `executer_atomique`.
    """
    if factures_historique is not None or not _stockage_durable_actif:
        return
    devis_id = next(
        devis_id for devis_id, facture in facturation.factures_actives_par_devis(registre_cible).items()
        if facture["facture_id"] == facture_id
    )
    _essayer_cout_reel(devis_id)


def envoyer_facture(
    facture_id: str,
    horodatage: str,
    factures_historique: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Outil N4 (PLAN T1.3-c) : n'est JAMAIS exécuté hors d'une décision approuvée du socle
    (`opsys.approbations.decider`, `department.yaml/approbations.n4`) — voir
    `facturation.envoyer_facture` et le docstring de ce module (RÈGLE FINANCE)."""
    registre_cible = _registre_factures(factures_historique)
    resultat, verdict = facturation.envoyer_facture(facture_id, horodatage, registre_cible)
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    _actualiser_rentabilite_apres_transition_facture(facture_id, registre_cible, factures_historique)
    return {"accepte": True, "resultat": resultat, **_etat_factures(factures_historique, registre_cible)}


def enregistrer_paiement_facture(
    facture_id: str,
    montant_paye: str,
    approbateur: str,
    horodatage: str,
    factures_historique: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Outil N5 (PLAN T1.3-c) : le socle exige `nathan_owner` ET l'attestation du professionnel
    (ADR-0009 §5) avant exécution — jamais vérifiées ici. Voir
    `facturation.enregistrer_paiement_facture` pour la comparaison de montant, calculée par le
    code, jamais fournie sans contrôle (paiement partiel ou écart -> verdict nommé)."""
    registre_cible = _registre_factures(factures_historique)
    resultat, verdict = facturation.enregistrer_paiement_facture(
        facture_id, montant_paye, approbateur, horodatage, registre_cible
    )
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    _actualiser_rentabilite_apres_transition_facture(facture_id, registre_cible, factures_historique)
    return {"accepte": True, "resultat": resultat, **_etat_factures(factures_historique, registre_cible)}


def _factures_brouillon() -> tuple[dict[str, Any], ...]:
    return facturation.factures_par_statut(_registre_factures(None), "BROUILLON")


def _depuis_attente_devis(devis_id: str, statut: str, devis_registre: Any, wct_registre: Any) -> str:
    """Date de début d'attente d'un item `attentes_devis` (PLAN T1.3-c point 4) : celle de la
    pièce déjà connue (le WCT quand c'est le devis accepté qui manque encore, sinon le devis)."""
    if statut == "en_attente_devis_accepte":
        return wct_recus.pour_devis_id(devis_id, wct_registre)["horodatage_completion"]
    return devis_recus.pour_devis_id(devis_id, devis_registre)["horodatage_acceptation"]


def _variance_critique_pour_facture(
    facture: dict[str, Any], wct_registre: Any, variance_registre: Any
) -> dict[str, Any] | None:
    """Le signal de variance CRITIQUE de M6 (PLAN T1.3-c point 4) à afficher à côté de cette
    facture BROUILLON, ou None si M5 n'en a reçu aucun pour son WCT, ou si le dernier connu n'est
    pas évalué critique — jamais un blocage de l'envoi, seulement une information pour le
    propriétaire (`m5_envoyer_facture` reste disponible que ce signal existe ou non)."""
    wct_recu = wct_recus.pour_devis_id(facture["devis_id"], wct_registre)
    if wct_recu is None:
        return None
    signal = variance_recus.pour_wct_id(wct_recu["wct_id"], variance_registre)
    if signal is None or signal["statut_variance"] != "evaluee" or not signal["signal_critique"]:
        return None
    return {
        "type": "chantier_a_reviser",
        "id": f"variance-{signal['wct_id']}",
        "resume": (
            f"Écart matériaux critique sur le chantier {signal['chantier_id']} "
            f"(wct {signal['wct_id']}) — facture {facture['facture_id']} prête à envoyer quand même"
        ),
        "niveau": "N4",
        "depuis": signal["horodatage_completion"],
        "action_proposee": "réviser",
    }


def attentes() -> list[dict[str, Any]]:
    """File du propriétaire (ADR-0009 §5, PLAN T1.3-c point 4) :
    1. les attentes de facturation déjà calculées par `lister_attentes_facturation` (devis/WCT à
       qui il manque encore une pièce), reformées à la forme commune
       (`opsys.approbations.CHAMPS_ATTENTE`) ;
    2. chaque facture BROUILLON prête à envoyer, au même niveau que `m5_envoyer_facture` (N4) ;
    3. à côté d'une facture BROUILLON, le signal de variance de chantier CRITIQUE reçu de M6
       (`m6.variance_chantier`, gardé par wct_id — `variance_recus.py`) s'il existe : jamais un
       blocage de l'envoi, seulement une information (point 4 du mandat, relevé par le test de
       bout en bout `tests/test_attentes.py`).
    """
    brut = lister_attentes_facturation()
    devis_registre = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_DEVIS_RECUS)
    wct_registre = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_WCT_RECUS)
    variance_registre = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_VARIANCE_RECUE)

    items: list[dict[str, Any]] = []
    for attente in brut["attentes_devis"]:
        items.append(
            {
                "type": f"facturation_{attente['statut']}",
                "id": attente["devis_id"],
                "resume": f"Devis {attente['devis_id']} : {attente['statut']}",
                "niveau": "N3",
                "depuis": _depuis_attente_devis(attente["devis_id"], attente["statut"], devis_registre, wct_registre),
                "action_proposee": "compléter",
            }
        )
    for attente in brut["attentes_wct_sans_devis_id"]:
        wct_recu = wct_recus.pour_wct_id(attente["wct_id"], wct_registre)
        items.append(
            {
                "type": "wct_sans_devis_id",
                "id": attente["wct_id"],
                "resume": f"Intervention {attente['intervention_id']} sans devis relié (wct {attente['wct_id']})",
                "niveau": "N3",
                "depuis": wct_recu["horodatage_completion"],
                "action_proposee": "relier un devis",
            }
        )

    for facture in _factures_brouillon():
        items.append(
            {
                "type": "facture_brouillon",
                "id": facture["facture_id"],
                "resume": f"Facture {facture['facture_id']} prête à envoyer ({facture['montant_apres_taxes']} $)",
                "niveau": "N4",
                "depuis": facture["horodatage"],
                "action_proposee": "envoyer",
            }
        )
        variance = _variance_critique_pour_facture(facture, wct_registre, variance_registre)
        if variance is not None:
            items.append(variance)

    return items


def _vue_chantier(etat: dict[str, Any], sources: dict[str, Any], autorise_couts: bool, detail: bool) -> dict[str, Any]:
    """Ce que l'outil de lecture rend pour un devis : un statut d'attente (aucun montant), ou l'état calculé.

    Sans droit de voir les coûts (`autorise_couts` faux) : identifiants, verdict et codes de manque
    seulement (`cout_reel.masquer_montants`). Avec le droit : le détail (lignes de matériaux, sources de prix,
    hypothèses) pour un chantier précis, une ligne (`cout_reel.resumer`) pour une liste. `trace.a_jour` dit si le
    dernier état tracé par la cascade correspond aux pièces d'AUJOURD'HUI (faux : un prix, le taux ou la
    facture ont changé depuis ; le calcul rendu est, lui, toujours celui d'aujourd'hui)."""
    if etat["statut"] != "calculee":
        return {"devis_id": etat["devis_id"], "chantier_id": etat["chantier_id"], "statut": etat["statut"]}
    rentabilite = etat["rentabilite"]
    trace = sources["traces"].get(etat["devis_id"])
    if not autorise_couts:
        contenu = cout_reel.masquer_montants(rentabilite)
    elif detail:
        contenu = {cle: valeur for cle, valeur in rentabilite.items() if cle != "version_entrees"}
    else:
        contenu = cout_reel.resumer(rentabilite)
    trace_vue = {"a_jour": trace is not None and trace.get("version_entrees") == rentabilite["version_entrees"]}
    if detail:  # l'empreinte de 64 caractères n'a d'intérêt que pour un chantier précis
        trace_vue = {"version_entrees": rentabilite["version_entrees"], **trace_vue}
    return {
        "devis_id": etat["devis_id"],
        "chantier_id": etat["chantier_id"],
        "statut": "calculee",
        "rentabilite": contenu,
        "trace": trace_vue,
    }


def lire_rentabilite_chantier(
    chantier_id: str | None = None,
    devis_id: str | None = None,
    limite: int | None = None,
    role: str | None = None,
    autorise_couts: bool | None = None,
) -> dict[str, Any]:
    """Outil T0 (PLAN T1.5-d) : le coût réel et la rentabilité des chantiers, pour l'admin.

    Même contrôle d'accès que `m5_etat_tresorerie` (PLAN T1.4-k2) : pour un appel d'appareil, l'identité
    confirmée en base (`admin` seulement) ; la vue vient du rôle authentifié, un argument ne peut que la
    restreindre ; refus AVANT toute lecture, sans écriture. Sans appareil, `autorise_couts` reste obligatoire.

    Aucun montant, prix, taux, durée ni quantité ne se passe en argument : tout est lu à la source
    (`_etat_chantier`). `chantier_id` et `devis_id` ne servent qu'à CHOISIR quels chantiers lire ; un filtre
    sans résultat est `REJ-RENTABILITE-CHANTIER-INCONNU`. Les devis sont pris du plus récemment reçu au plus
    ancien, au plus `limite` (8 par défaut, 12 au plus : la réponse d'un outil est tronquée au-delà de 6 000
    caractères) ; `nombre` est le total qui correspond, `reste` ce qui n'est pas affiché."""
    acteur, refus = _acteur_appareil()
    if refus is not None:
        return _refus(refus)
    vue, verdict = acces.resoudre_vue(acteur, role, autorise_couts)
    if verdict is not None:
        return _refus(verdict)

    plafond = _LIMITE_LECTURE_DEFAUT if limite is None else limite
    if isinstance(plafond, bool) or not isinstance(plafond, int) or not 1 <= plafond <= _LIMITE_LECTURE_MAX:
        return _refus(
            validation.construire_verdict(
                "REJ-RENTABILITE-LIMITE-INVALIDE",
                detail=f"limite doit être un entier de 1 à {_LIMITE_LECTURE_MAX}",
            )
        )
    sources = _sources_cout_reel()
    filtre = devis_id is not None or chantier_id is not None
    recus = list(
        dict.fromkeys(  # ordre de réception, sans doublon
            m["devis_id"] for m in sources["devis"] if isinstance(m.get("devis_id"), str)
        )
    )
    etats = []
    for candidat in reversed(recus):  # le plus récemment reçu d'abord
        if devis_id is not None and candidat != devis_id:
            continue
        etat = _etat_chantier(candidat, sources)
        if chantier_id is not None and etat["chantier_id"] != chantier_id:
            continue
        etats.append(etat)
    if filtre and not etats:
        return _refus(
            validation.construire_verdict(
                "REJ-RENTABILITE-CHANTIER-INCONNU",
                detail="aucun devis accepté reçu ne correspond à ce devis_id / chantier_id",
            )
        )
    affiches = etats[:plafond]
    return {
        "accepte": True,
        "resultat": analyse.avec_mention(
            {
                "role": vue["role"],
                "nombre": len(etats),
                "affichees": len(affiches),
                "reste": len(etats) - len(affiches),
                "chantiers": [_vue_chantier(e, sources, vue["autorise_couts"], detail=filtre) for e in affiches],
            }
        ),
    }


def lire_comptes_a_recevoir(
    aujourd_hui: str | None = None,
    role: str | None = None,
    autorise_couts: bool | None = None,
) -> dict[str, Any]:
    """Outil T0 (PLAN T1.5-d) : les comptes à recevoir, c'est-à-dire les factures ENVOYEE (et seulement
    elles), avec leur âge quand la date du jour est fournie. Même contrôle d'accès que
    `lire_rentabilite_chantier` (admin authentifié ; sans droit de voir les coûts : le nombre seulement).
    Ne lit que le registre des factures, n'écrit rien."""
    acteur, refus = _acteur_appareil()
    if refus is not None:
        return _refus(refus)
    vue, verdict = acces.resoudre_vue(acteur, role, autorise_couts)
    if verdict is not None:
        return _refus(verdict)
    resultat, verdict = facturation.comptes_a_recevoir(_registre_factures(None), aujourd_hui)
    if verdict is not None:
        return _refus(verdict)
    if not vue["autorise_couts"]:
        return {
            "accepte": True,
            "resultat": {"role": vue["role"], "nombre": resultat["nombre"], "montants_masques": True},
        }
    return {"accepte": True, "resultat": {"role": vue["role"], **resultat}}


def _charger_catalogue_sources_paie() -> Any:
    """Charge la déclaration serveur; aucun document ou fournisseur n'est consulté à l'exécution."""
    return yaml.safe_load(_CHEMIN_SOURCES_REGLES_PAIE.read_text(encoding="utf-8"))


def lire_sources_regles_paie(
    juridiction: str,
    date_paie: str,
    periode_debut: str,
    periode_fin: str,
    fuseau: str,
    frequence: str,
) -> dict[str, Any]:
    """Expose l'état du catalogue de références, sans calculer ni certifier un résultat de paie."""
    acteur, refus = _acteur_appareil()
    if refus is not None:
        return _refus(refus)
    if acteur is None:
        return _refus(validation.construire_verdict(
            "REJ-PAIE-ACCES-REFUSE", detail="lecture réservée au propriétaire confirmé via console",
        ))
    cnx = stockage.connexion_courante()
    personne = identite.personne_active(cnx, acteur.personne) if cnx is not None else None
    roles = personne.roles if personne is not None else frozenset()
    if (personne is None or acteur.source != "console" or acteur.role != "nathan_owner"
            or "nathan_owner" not in roles):
        return _refus(validation.construire_verdict(
            "REJ-PAIE-ACCES-REFUSE", detail="lecture réservée au propriétaire confirmé via console",
        ))
    try:
        catalogue = _charger_catalogue_sources_paie()
    except (OSError, yaml.YAMLError) as exc:
        return _refus(validation.construire_verdict(
            "REJ-PAIE-CATALOGUE-INDISPONIBLE", detail=f"catalogue déclaré illisible ({type(exc).__name__})",
        ))
    resultat, verdict = sources_regles_paie.evaluer_sources(
        catalogue,
        racine=_CHEMIN_SOURCES_REGLES_PAIE.parent,
        juridiction=juridiction,
        date_paie=date_paie,
        periode_debut=periode_debut,
        periode_fin=periode_fin,
        fuseau=fuseau,
        frequence=frequence,
    )
    if verdict is not None:
        return _refus(verdict)
    return {"accepte": True, "resultat": resultat}


_CHAMPS_MONTANTS_FISCAUX_INCONNUS = (
    "impot_federal",
    "impot_quebec",
    "rrq_employe",
    "rqap_employe",
    "ae_employe",
    "retenues_totales",
    "net",
    "rrq_employeur",
    "rqap_employeur",
    "fss",
    "cnesst",
    "das",
)
_CHAMPS_PAIE_MANQUANTS = (
    {"id": "TP1015_3_CODE", "description": "Code de retenue et renseignements personnels du formulaire TP-1015.3."},
    {"id": "TP1016", "description": "Réduction autorisée des retenues, si applicable."},
    {"id": "TP1017", "description": "Retenue supplémentaire demandée, si applicable."},
    {"id": "TD1", "description": "Crédits personnels fédéraux et état TD1 courant."},
    {"id": "DONNEES_CUMUL_ANNUEL", "description": "Cumuls annuels par salarié pour RRQ, RQAP et AE."},
    {
        "id": "ASSIETTES_AVANTAGES",
        "description": "Avantages imposables et assiettes applicables, à confirmer humainement.",
    },
    {"id": "EMPLOYEUR_FSS_CNESST", "description": "Paramètres employeur, FSS, CNESST et autres contributions."},
    {"id": "DAS", "description": "Classe de remettant, fréquence et échéance de remise à confirmer."},
)
_LIENS_PAIE_OFFICIELS = (
    {
        "id": "webras",
        "url": "https://www.revenuquebec.ca/fr/services-en-ligne/outils/webras-calculer-les-retenues-a-la-source/",
        "usage": "Calcul humain des retenues à la source et cotisations; aucun appel automatisé par OPSYS.",
    },
    {
        "id": "rq_tp1015",
        "url": "https://www.revenuquebec.ca/fr/entreprises/retenues-a-la-source-et-cotisations-de-lemployeur/trousse-employeur/",
        "usage": "Références Revenu Québec; les éditions et leur applicabilité restent à confirmer.",
    },
    {
        "id": "cra_pdoc",
        "url": "https://www.canada.ca/en/revenue-agency/services/e-services/digital-services-businesses/payroll-deductions-online-calculator.html",
        "usage": "Calcul humain fédéral; aucun appel automatisé par OPSYS.",
    },
    {
        "id": "cra_t4127",
        "url": "https://www.canada.ca/en/revenue-agency/services/forms-publications/payroll/t4127-payroll-deductions-formulas.html",
        "usage": "Référence fédérale; ne couvre pas à elle seule l'impôt provincial du Québec.",
    },
)


def _frequence_webras(periodes_annuelles: int) -> str | None:
    return {12: "mensuelle", 24: "bimensuelle", 26: "bihebdomadaire", 52: "hebdomadaire"}.get(periodes_annuelles)


def preparer_dossier_webras(
    employee_person_id: str,
    debut: str,
    fin: str,
    fuseau: str,
    politique_arrondi: str,
    hypothese_arrondi: str,
    sources_attendues: Mapping[str, Any] | None,
    date_paie: str,
    periodes_annuelles: int,
    revenu_imposable_cad: str | None,
    reference_revenu_imposable: str | None,
    *,
    lecteur_heures_m4: LecteurHeuresM4 | None,
) -> dict[str, Any]:
    """Prépare un paquet privé de calcul humain; aucune retenue ou paie nette n'est estimée."""
    acteur, refus = _acteur_appareil()
    if refus is not None:
        return _refus(refus)
    cnx = stockage.connexion_courante()
    personne = identite.personne_active(cnx, acteur.personne) if cnx is not None and acteur is not None else None
    if (
        personne is None
        or acteur is None
        or acteur.source != "console"
        or acteur.role != "nathan_owner"
        or "nathan_owner" not in personne.roles
    ):
        return _refus(
            validation.construire_verdict(
                "REJ-PAIE-ACCES-REFUSE",
                detail="dossier réservé au propriétaire confirmé via console",
            )
        )
    if not isinstance(date_paie, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", date_paie):
        return _refus(validation.construire_verdict("REJ-PAIE-DATE-INVALIDE", detail="date de paie ISO requise"))
    try:
        date_paie_iso = date.fromisoformat(date_paie)
        fin_iso = date.fromisoformat(fin)
    except (TypeError, ValueError):
        return _refus(validation.construire_verdict("REJ-PAIE-DATE-INVALIDE", detail="date de paie ou fin invalide"))
    if date_paie_iso.isoformat() != date_paie or date_paie_iso < fin_iso:
        return _refus(
            validation.construire_verdict(
                "REJ-PAIE-DATE-INVALIDE",
                detail="date de paie canonique requise, égale ou postérieure à la période",
            )
        )
    frequence = _frequence_webras(periodes_annuelles) if type(periodes_annuelles) is int else None
    if frequence is None:
        return _refus(
            validation.construire_verdict(
                "REJ-PAIE-FREQUENCE-INVALIDE",
                detail="périodes annuelles explicites requises: 12, 24, 26 ou 52",
            )
        )
    if revenu_imposable_cad is not None:
        if (
            not isinstance(revenu_imposable_cad, str)
            or not re.fullmatch(r"(?:0|[1-9][0-9]{0,8})\.[0-9]{2}", revenu_imposable_cad)
            or not isinstance(reference_revenu_imposable, str)
            or not 1 <= len(reference_revenu_imposable.strip()) <= 240
        ):
            return _refus(
                validation.construire_verdict(
                    "REJ-PAIE-ASSIETTE-INVALIDE",
                    detail="montant déclaré en CAD au centime et référence humaine requis",
                )
            )
        assiette_declaree: dict[str, Any] = {
            "montant_cad": revenu_imposable_cad,
            "reference_humaine": reference_revenu_imposable.strip(),
            "rapprochee_au_brut_m5": False,
            "qualification": "déclaration humaine; OPSYS ne la qualifie pas comme revenu imposable",
        }
    elif reference_revenu_imposable is not None:
        return _refus(
            validation.construire_verdict(
                "REJ-PAIE-ASSIETTE-INVALIDE",
                detail="une référence d'assiette sans montant déclaré est refusée",
            )
        )
    else:
        assiette_declaree = {
            "montant_cad": "UNKNOWN",
            "reference_humaine": None,
            "qualification": "assiette imposable non fournie et non estimée",
        }
    if sources_attendues is None or not _sources_attendues_valides(sources_attendues):
        return _refus(
            validation.construire_verdict(
                "REJ-PAIE-SNAPSHOT-REQUIS",
                detail="les références M4 et M5 doivent être épinglées explicitement",
            )
        )
    brut = _fonction_brut_regulier(lecteur_heures_m4)(
        employee_person_id,
        debut,
        fin,
        fuseau,
        politique_arrondi,
        hypothese_arrondi,
        sources_attendues,
    )
    if brut.get("accepte") is not True:
        return brut
    connu = brut["resultat"]
    catalogue = lire_sources_regles_paie("QC", date_paie, debut, fin, fuseau, frequence)
    if catalogue.get("accepte") is not True:
        return catalogue
    source_catalogue = catalogue["resultat"]
    dossier = analyse.avec_mention(
        {
            "schema": "opsys.dossier-webras-preparatoire/v1",
            "portee": (
                "Dossier d'aide à une saisie et un calcul humains dans les services officiels; aucune paie officielle."
            ),
            "known_info": {
                "juridiction_declaree": "QC",
                "employee_person_id": employee_person_id,
                "periode": {"debut": debut, "fin": fin, "fuseau": fuseau, "bornes": "inclusives"},
                "date_paie": date_paie,
                "periodes_annuelles_declarees": periodes_annuelles,
                "frequence_catalogue": frequence,
                "brut_regulier_m5": {
                    "montant_cad": connu.get("brut_brouillon", "UNKNOWN"),
                    "minutes_regulieres": connu.get("minutes_regulieres"),
                    "sources": connu.get("sources"),
                    "politique_arrondi": connu.get("hypotheses"),
                },
                "revenu_imposable_declare": assiette_declaree,
            },
            "source_catalogue": {
                "statut": source_catalogue["statut"],
                "juridiction": source_catalogue["juridiction"],
                "date_paie": source_catalogue["date_paie"],
                "frequence": source_catalogue["frequence"],
                "references_declarees": [
                    {
                        "id": reference["id"],
                        "edition": reference["edition"],
                        "effet": [reference["applicable_du"], reference["applicable_au"]],
                        "statut": reference["statut_declare"],
                        "sha256": reference["sha256_declare"],
                    }
                    for reference in source_catalogue["references_catalogue"]
                ],
                "sources_verifiees": source_catalogue["sources_verifiees"],
                "manques": source_catalogue["manques"],
                "couverture_catalogue": source_catalogue["couverture_catalogue"],
            },
            "liens_officiels": list(_LIENS_PAIE_OFFICIELS),
            "champs_fiscaux_manquants": list(_CHAMPS_PAIE_MANQUANTS),
            "montants_fiscaux": {champ: "UNKNOWN" for champ in _CHAMPS_MONTANTS_FISCAUX_INCONNUS},
            "requires_human_calculation": True,
            "actions_officielles_bloquees": True,
            "do_not_treat_gross_as_taxable_income": True,
        }
    )
    if len(json.dumps(dossier, ensure_ascii=False, separators=(",", ":"))) > BUDGET_SORTIE:
        return _refus(
            validation.construire_verdict(
                "REJ-PAIE-DOSSIER-TROP-GROS",
                detail="le dossier dépasse le budget de sortie; aucun contenu tronqué",
            )
        )
    return {"accepte": True, "resultat": dossier}


def _fonction_dossier_webras(lecteur_heures_m4: LecteurHeuresM4 | None) -> Callable[..., dict[str, Any]]:
    def appeler(
        employee_person_id: str,
        debut: str,
        fin: str,
        fuseau: str,
        politique_arrondi: str,
        hypothese_arrondi: str,
        sources_attendues: Mapping[str, Any] | None,
        date_paie: str,
        periodes_annuelles: int,
        revenu_imposable_cad: str | None,
        reference_revenu_imposable: str | None,
    ) -> dict[str, Any]:
        return preparer_dossier_webras(
            employee_person_id,
            debut,
            fin,
            fuseau,
            politique_arrondi,
            hypothese_arrondi,
            sources_attendues,
            date_paie,
            periodes_annuelles,
            revenu_imposable_cad,
            reference_revenu_imposable,
            lecteur_heures_m4=lecteur_heures_m4,
        )

    return appeler


def _autorite_couts_marketing(nom: str | None = None) -> str:
    cnx = stockage.connexion_courante()
    if cnx is None:
        raise couts_marketing.CoutErreur("TRANSACTION-REQUISE")
    if cnx.dialect.name != "sqlite":
        raise couts_marketing.CoutErreur("BACKEND-NON-PRIS-EN-CHARGE")
    if nom is not None:
        acteur = approbations.approbateur_en_cours(cnx, nom, _DEPARTEMENT, roles=frozenset({"nathan_owner"}))
        demande_id = contexte.demande_approuvee_en_cours()
        demande = approbations.lire(cnx, demande_id) if demande_id else None
        if acteur is None or demande is None or demande["niveau"] != "N4":
            raise couts_marketing.CoutErreur("OWNER-N4-REQUIS")
        return acteur.personne
    appelante = contexte.identite_appelante()
    if appelante is None or appelante.source != "console" or appelante.role not in {"admin", "nathan_owner"}:
        raise couts_marketing.CoutErreur("ACCES-REFUSE")
    confirmee = approbations.signataire_valide(cnx, appelante)
    if confirmee is None:
        raise couts_marketing.CoutErreur("ACCES-REFUSE")
    return confirmee.personne


def _snapshot_couts_marketing(nom: str) -> list[dict]:
    """SQL/octet/nœuds avant restauration ; seulement les deux registres M5 autorisés."""
    import json
    import math

    from sqlalchemy import LargeBinary, cast, func, select

    from opsys.stockage import codec
    from opsys.stockage.schema import REGISTRES

    if nom not in {_NOM_REGISTRE_COMPTES_A_PAYER, couts_marketing.REGISTRE}:
        raise couts_marketing.CoutErreur("REGISTRE-INVALIDE")
    cnx = stockage.connexion_courante()
    if cnx is None or cnx.dialect.name != "sqlite":
        raise couts_marketing.CoutErreur("BACKEND-NON-PRIS-EN-CHARGE")
    filtre = (REGISTRES.c.departement == _DEPARTEMENT) & (REGISTRES.c.registre == nom)
    octets = func.length(cast(REGISTRES.c.maillon, LargeBinary))
    nombre, premier, dernier, total, maximum = cnx.execute(select(
        func.count(), func.min(REGISTRES.c.rang), func.max(REGISTRES.c.rang),
        func.coalesce(func.sum(octets), 0), func.coalesce(func.max(octets), 0),
    ).where(filtre)).one()
    if nombre > 10_000 or total > 8 * 1024 * 1024 or maximum > 64 * 1024:
        raise couts_marketing.CoutErreur("BORNE-SOURCE")
    if nombre and (premier != 0 or dernier != nombre - 1):
        raise couts_marketing.CoutErreur("PREFIXE-INVALIDE")
    lignes = cnx.execute(select(REGISTRES.c.rang, REGISTRES.c.maillon).where(filtre).order_by(
        REGISTRES.c.rang).limit(10_001)).all()
    if len(lignes) != nombre:
        raise couts_marketing.CoutErreur("PREFIXE-INVALIDE")

    def objet(paires):
        resultat = {}
        for cle, valeur in paires:
            if cle in resultat:
                raise ValueError("clé répétée")
            resultat[cle] = valeur
        return resultat

    def constante(_valeur):
        raise ValueError("nombre non fini")

    captures = []
    nombre_total = 0
    try:
        for rang, ligne in enumerate(lignes):
            if ligne.rang != rang:
                raise ValueError("rang discontinu")
            brut = json.loads(ligne.maillon, parse_constant=constante, object_pairs_hook=objet)
            pile, noeuds = [(brut, 0)], 0
            while pile:
                valeur, profondeur = pile.pop()
                noeuds += 1
                nombre_total += 1
                if profondeur > 16 or noeuds > 2048 or nombre_total > 500_000:
                    raise ValueError("borne JSON")
                if isinstance(valeur, float) and not math.isfinite(valeur):
                    raise ValueError("nombre non fini")
                if isinstance(valeur, dict):
                    pile.extend((v, profondeur + 1) for v in valeur.values())
                elif isinstance(valeur, list):
                    pile.extend((v, profondeur + 1) for v in valeur)
            maillon = codec.decoder(ligne.maillon)
            if not isinstance(maillon, dict):
                raise ValueError("objet requis")
            captures.append(maillon)
        couts_marketing.snapshot(captures)
    except (ArithmeticError, AttributeError, KeyError, TypeError, ValueError, RecursionError):
        raise couts_marketing.CoutErreur("CHAINE-INVALIDE") from None
    return captures


def _campagne_couts_marketing(lecteur: Callable, campagne_id: str) -> dict:
    import json

    try:
        reponse = lecteur(campagne_id)
    except PermissionError:
        raise couts_marketing.CoutErreur("ACCES-REFUSE") from None
    try:
        if len(json.dumps(reponse, ensure_ascii=False, allow_nan=False).encode("utf-8")) > 32 * 1024:
            raise ValueError
        if reponse.get("ok") is not True:
            raise ValueError
        charge = reponse["resultat"]
        if charge.get("statut") != "ok":
            raise ValueError
        source = couts_marketing.campagne_valide(charge["source_couts"])
        if source["campagne_id"] != campagne_id:
            raise ValueError
        return source
    except (ArithmeticError, AttributeError, KeyError, TypeError, ValueError, RecursionError):
        raise couts_marketing.CoutErreur("CAMPAGNE-INVALIDE") from None


def _borner_couts_marketing(resultat: dict) -> dict:
    import json

    while len(json.dumps(resultat, ensure_ascii=False, allow_nan=False).encode("utf-8")) > 31 * 1024:
        candidats = [(len(resultat[cle]), cle, page) for cle, page in (
            ("affectations", "pagination"), ("pieces_eligibles", "pagination_pieces"),
        ) if len(resultat[cle]) > 1]
        if not candidats:
            raise couts_marketing.CoutErreur("BORNE-SORTIE")
        _taille, cle, page = max(candidats)
        resultat[cle].pop()
        pagination = resultat[page]
        pagination["affichees"] -= 1
        pagination["reste"] += 1
        pagination["suivant"] = pagination["offset"] + pagination["affichees"]
    return resultat


def _outils_couts_marketing(lecteur: Callable) -> tuple[Outil, ...]:
    """Projection privée uniquement ; ces noms n'entrent jamais dans le catalogue MCP par défaut."""

    ident = {"type": "string", "minLength": 1, "maxLength": 128}
    fp = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
    entier = {"type": "integer", "minimum": 0}
    tete = {"type": ["string", "null"], "pattern": "^[0-9a-f]{64}$"}

    def objet(champs, requis=None):
        return {"type": "object", "properties": champs, "required": list(champs) if requis is None else requis,
                "additionalProperties": False}

    snap = objet({"nombre": entier, "tete": tete})
    ref_campagne = objet({"revision": {"type": "integer", "minimum": 1}, "empreinte": fp})
    sources = objet({"ap": objet({"nombre": entier, "tete": tete, "etat_sha256": fp}),
                     "campagne": ref_campagne,
                     "affectations": objet({"nombre": entier, "tete": tete, "version": entier})})
    dates = {"debut": {"type": "string", "format": "date"}, "fin": {"type": "string", "format": "date"}}
    motif = {"type": "string", "minLength": 1, "maxLength": 300}

    def lire(campagne_id, debut, fin, offset_affectations=0, offset_pieces=0, snapshot_attendu=None):
        _autorite_couts_marketing()
        ap_maillons = _snapshot_couts_marketing(_NOM_REGISTRE_COMPTES_A_PAYER)
        parts = _snapshot_couts_marketing(couts_marketing.REGISTRE)
        campagne = _campagne_couts_marketing(lecteur, campagne_id)
        resultat = couts_marketing.projeter(ap_maillons, parts, campagne, debut=debut, fin=fin,
                                           offset_affectations=offset_affectations, offset_pieces=offset_pieces,
                                           snapshot_attendu=snapshot_attendu)
        resultat["lue_le"] = approbations._maintenant()
        resultat = _borner_couts_marketing(resultat)
        if campagne != _campagne_couts_marketing(lecteur, campagne_id):
            raise couts_marketing.CoutErreur("SNAPSHOT-PERIME")
        for nom, avant in ((_NOM_REGISTRE_COMPTES_A_PAYER, ap_maillons), (couts_marketing.REGISTRE, parts)):
            if avant != _snapshot_couts_marketing(nom):
                raise couts_marketing.CoutErreur("SNAPSHOT-PERIME")
        _autorite_couts_marketing()
        return {"accepte": True, "resultat": resultat}

    def muter(nom, arguments):
        demande_id = contexte.demande_approuvee_en_cours()
        auteur = _autorite_couts_marketing(nom)
        if demande_id is None:
            raise couts_marketing.CoutErreur("OWNER-N4-REQUIS")
        ap_maillons = _snapshot_couts_marketing(_NOM_REGISTRE_COMPTES_A_PAYER)
        parts = _snapshot_couts_marketing(couts_marketing.REGISTRE)
        couts_marketing.etats_ap(ap_maillons)
        maintenant = approbations._maintenant()
        campagne = None
        if nom == "m5_affecter_cout_marketing":
            campagne = _campagne_couts_marketing(lecteur, arguments["campagne_id"])
            corps = couts_marketing.preparer_affectation(
                ap_maillons, parts, campagne, arguments, auteur=auteur, horodatage=maintenant,
                nouvel_id="cout-" + demande_id,
            )
            if campagne != _campagne_couts_marketing(lecteur, arguments["campagne_id"]):
                raise couts_marketing.CoutErreur("SNAPSHOT-PERIME")
        else:
            corps = couts_marketing.preparer_retrait(
                parts, arguments["affectation_id"], arguments["version_attendue"], arguments["snapshot_attendu"],
                arguments["motif"], auteur=auteur, horodatage=maintenant,
            )
        for registre_nom, avant in ((_NOM_REGISTRE_COMPTES_A_PAYER, ap_maillons), (couts_marketing.REGISTRE, parts)):
            if avant != _snapshot_couts_marketing(registre_nom):
                raise couts_marketing.CoutErreur("SNAPSHOT-PERIME")
        if _autorite_couts_marketing(nom) != auteur:
            raise couts_marketing.CoutErreur("ACCES-REFUSE")
        precedent = parts[-1]["ligne_id"] if parts else None
        maillon = {**corps, "precedent_ligne_id": precedent,
                   "ligne_id": couts_marketing.encodage.empreinte(corps, precedent)}
        stockage.maillons(_DEPARTEMENT, couts_marketing.REGISTRE).append(maillon, rang_attendu=len(parts))
        _autorite_couts_marketing(nom)
        return {"accepte": True, "resultat": {"affectation": corps}}

    champs = {"facture_fournisseur_id": ident, "campagne_id": ident, **dates, "devise": {"enum": ["CAD"]},
              "base": {"enum": ["HT", "TTC"]}, "montant_alloue_cad": {"type": "string", "maxLength": 15},
              "motif": motif, "sources_attendues": sources}
    schema = objet({**champs, "affectation_id": ident}, list(champs))
    schema_retrait = objet({"affectation_id": ident, "version_attendue": {"type": "integer", "minimum": 1},
                           "snapshot_attendu": snap, "motif": motif})
    schema_lire = objet({"campagne_id": ident, **dates, "offset_affectations": entier, "offset_pieces": entier,
                        "snapshot_attendu": {"type": ["object", "null"], "properties": {
                            "ap": snap, "affectations": snap, "campagne": ref_campagne,
                        }, "required": ["ap", "affectations", "campagne"], "additionalProperties": False}},
                       ["campagne_id", "debut", "fin"])
    return (
        Outil("m5_affecter_cout_marketing", "Affectation analytique humaine AP sans PO à campagne locale, CAD déclaré; "
              "N4 propriétaire réel, sans paiement ou ROI. Port privé console seulement.", schema,
              lambda **args: muter("m5_affecter_cout_marketing", args), Autonomie.T2, niveau=Niveau.N4),
        Outil("m5_revoquer_affectation_cout_marketing", "Retire une répartition humaine avec CAS; aucune pièce AP "
              "supprimée, aucun paiement. N4 propriétaire réel, port privé console seulement.", schema_retrait,
              lambda **args: muter("m5_revoquer_affectation_cout_marketing", args), Autonomie.T2, niveau=Niveau.N4),
        Outil("m5_lire_couts_marketing_affectes", "Projection privée AP/affectations vérifiées, bases séparées, "
              "paiements/ROI/exhaustivité inconnus; identité admin/propriétaire DB console.", schema_lire, lire),
    )


def outils(*, lecteur_heures_m4: LecteurHeuresM4 | None = None,
           lecteur_campagne_m7: Callable | None = None) -> tuple[Outil, ...]:
    return (
        Outil(
            nom="m5_etat_tresorerie",
            description=(
                "État financier de bout en bout : solde, argent disponible (solde moins réserves) et CASH LIBRE RÉEL "
                "avec sa décomposition (solde moins TPS/TVQ à remettre, paies, DAS, comptes à payer, dettes, réserves "
                "critiques ; chaque composante dit sa source et sa fraîcheur, une composante inconnue est « non "
                "calculable, manque X », jamais zéro). Ne présente jamais argent_disponible sans cash_libre. Filtrés "
                "par rôle : sans montant (ni solde, ni argent disponible, ni cash libre, ni taux) sauf autorisation. "
                "Analyse préparatoire : porte la mention obligatoire. Pendant un appel d'appareil authentifié (PLAN "
                "T1.4-k2), la vue vient du rôle authentifié — admin : montants ; les autres n'ont pas accès — et "
                "autorise_couts ne peut que la RESTREINDRE (faux), jamais l'élargir (refus nommé REJ-ROLE-ELARGI) ; "
                "role, s'il est fourni, doit être celui du jeton. Hors appel d'appareil (agent), autorise_couts est "
                "obligatoire et explicite : vrai pour voir un montant, faux pour l'état sans montant."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "role": {
                        "type": ["string", "null"],
                        "description": (
                            "Étiquette du rôle portée par la réponse. Appel d'appareil : omis, ou égal au "
                            "rôle authentifié ; un autre est refusé (REJ-IDENTITE-FOURNIE-DIFFERENTE)."
                        ),
                    },
                    "autorise_couts": {
                        "type": ["boolean", "null"],
                        "description": (
                            "Vrai pour voir solde, argent disponible et taux. Appel d'appareil : omis, il "
                            "vaut le droit du rôle authentifié ; faux restreint la vue ; vrai sans ce "
                            "droit est refusé (REJ-ROLE-ELARGI). Sans appareil (agent, console) : "
                            "obligatoire et explicite (REJ-AUTORISE-COUTS-REQUIS)."
                        ),
                    },
                    "mouvements_historique": _HISTORIQUE_MOUVEMENTS,
                    "taux_utilises": {"type": "array", "items": {"type": "object"}},
                },
                "additionalProperties": False,
            },
            fonction=etat_tresorerie,
            autonomie=Autonomie.T0,
            # §9.5 M5 (trésorerie et cash libre réel) : l'admin seul. Pour un appel d'appareil, la vue vient
            # du rôle authentifié et confirmé en base (T1.4-k2, acces.py), pas de `role` ni d'`autorise_couts`.
            roles_appareil=_ROLES_APPAREIL_FINANCE,
        ),
        Outil(
            nom="m5_calculer_taxes_tps_tvq",
            description=(
                "Calcule TPS + TVQ en Decimal sur un montant avant taxes, à partir des taux "
                "versionnés en vigueur (contracts/taux_fiscaux.v1.yaml). Bloque si un taux est absent."
            ),
            parametres={
                "type": "object",
                "properties": {"montant_avant_taxes": _MONTANT_TEXTE},
                "required": ["montant_avant_taxes"],
                "additionalProperties": False,
            },
            fonction=calculer_taxes_tps_tvq,
            autonomie=Autonomie.T0,
        ),
        Outil(
            nom="m5_enregistrer_mouvement",
            description=(
                "Enregistre un mouvement financier au registre append-only (écriture financière : "
                "T3, jamais autonome). Le signe du montant doit être cohérent avec le type "
                "(DECAISSEMENT négatif, ENCAISSEMENT/PROVISION positifs) ou le mouvement est refusé."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "montant": _MONTANT_TEXTE,
                    "type_mouvement": _TYPE_MOUVEMENT,
                    "horodatage": {"type": "string", "description": "ISO 8601 avec fuseau"},
                    "classe_retention": _CLASSE_RETENTION,
                    "source": {"type": "string"},
                    "mouvements_historique": _HISTORIQUE_MOUVEMENTS,
                },
                "required": ["montant", "type_mouvement", "horodatage", "classe_retention", "source"],
                "additionalProperties": False,
            },
            fonction=enregistrer_mouvement,
            autonomie=Autonomie.T3,
        ),
        Outil(
            nom="m5_creer_facture_brouillon",
            description=(
                "Crée une facture BROUILLON (M5.2) sur le registre dédié des factures, distinct "
                "du registre des mouvements. Recalcule tous les totaux et les taxes TPS/TVQ "
                "depuis les lignes — ne fait jamais confiance à un montant_avant_taxes fourni "
                "(rejet s'il diffère). Idempotente par devis_id : refuse un second brouillon "
                "actif pour le même devis. Écriture interne non finale (T1) : n'envoie rien au "
                "client, n'encaisse rien, ne touche jamais le registre des mouvements."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "facture_id": {"type": "string"},
                    "chantier_id": {"type": "string"},
                    "devis_id": {"type": "string"},
                    "client_id": {"type": "string"},
                    "lignes": {"type": "array", "items": _LIGNE_FACTURE, "minItems": 1},
                    "horodatage": {"type": "string", "description": "ISO 8601 avec fuseau"},
                    "montant_avant_taxes": {
                        "type": ["string", "null"],
                        "description": (
                            "Optionnel : contrôle défensif. Si fourni, doit correspondre "
                            "exactement au total recalculé depuis les lignes, sinon rejet."
                        ),
                    },
                    "factures_historique": _HISTORIQUE_FACTURES,
                },
                "required": ["facture_id", "chantier_id", "devis_id", "client_id", "lignes", "horodatage"],
                "additionalProperties": False,
            },
            fonction=creer_facture_brouillon,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m5_lister_attentes_facturation",
            description=(
                "Liste compacte (PLAN T1.2-d, suite) des devis acceptés (m3.devis_accepte) et "
                "des interventions terminées (m4.travaux_termines) qui n'ont PAS encore produit "
                "de facture BROUILLON, avec le statut nommé qui dit quoi demander : "
                "en_attente_devis_accepte, en_attente_travaux_termines, en_attente_chantier_id, "
                "ou wct_sans_devis_id (intervention inscrite sans devis, jamais reliée seule). "
                "Lecture pure recalculée à chaque appel, aucune écriture. T1.3 s'en servira pour "
                "la file d'approbation du propriétaire."
            ),
            parametres={"type": "object", "properties": {}, "additionalProperties": False},
            fonction=lister_attentes_facturation_appareil,
            autonomie=Autonomie.T0,
            # §9.5 M5 (factures à préparer et à approuver). Identité confirmée en base (T1.4-k2).
            roles_appareil=_ROLES_APPAREIL_FINANCE,
        ),
        Outil(
            nom="m5_lire_rentabilite_chantier",
            description=(
                "Coût réel et rentabilité des chantiers (PLAN T1.5-d), pour l'admin : matériaux réellement "
                "utilisés (variance M6) x prix du livre de prix M6, main-d'oeuvre pointée (WCT) x taux horaire "
                "configuré ; prix facturé avant taxes moins coût réel ; marge réelle contre marge prévue du "
                "devis. Tout est lu à la source, rien ne se passe en argument. Un coût partiel est dit partiel, "
                "avec la liste `manque` (prix non disponible, taux à configurer, temps absent...) : jamais un "
                "chiffre inventé. Avec devis_id ou chantier_id : le détail ; sans : une ligne par devis "
                "(limite, 8 récents). Lecture pure, aucune écriture comptable. Même règle d'accès que "
                "m5_etat_tresorerie : admin "
                "seulement ; autorise_couts ne peut que restreindre (sans droit : aucun montant)."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "chantier_id": {"type": ["string", "null"], "description": "Filtre : lire ce chantier."},
                    "devis_id": {"type": ["string", "null"], "description": "Filtre : lire ce devis."},
                    "limite": {
                        "type": ["integer", "null"],
                        "minimum": 1,
                        "maximum": _LIMITE_LECTURE_MAX,
                        "description": (
                            f"Nombre de devis rendus, du plus récent au plus ancien (défaut {_LIMITE_LECTURE_DEFAUT}, "
                            f"au plus {_LIMITE_LECTURE_MAX}) ; `reste` dit ce qui n'est pas affiché."
                        ),
                    },
                    "role": _ROLE_DE_LECTURE,
                    "autorise_couts": _AUTORISE_COUTS_DE_LECTURE,
                },
                "additionalProperties": False,
            },
            fonction=lire_rentabilite_chantier,
            autonomie=Autonomie.T0,
            roles_appareil=_ROLES_APPAREIL_FINANCE,
        ),
        Outil(
            nom="m5_lire_comptes_a_recevoir",
            description=(
                "Comptes à recevoir (PLAN T1.5-d), pour l'admin : les factures ENVOYEE, et seulement elles (une "
                "BROUILLON n'est pas due, une PAYEE ou ANNULEE non plus), avec le total et, si aujourd_hui "
                "(AAAA-MM-JJ) est fourni, l'âge par tranche (0-30, 31-60, 61-90, 90+). Sans aujourd_hui : pas "
                "d'âge, la date du jour n'est jamais devinée. Vue de l'état des factures : rien à mettre à "
                "jour, aucune écriture. Même règle d'accès que m5_etat_tresorerie : admin seulement ; "
                "autorise_couts ne peut que restreindre (sans droit : le nombre de factures seulement)."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "aujourd_hui": {
                        "type": ["string", "null"],
                        "description": "Date du jour ISO 8601 (AAAA-MM-JJ), pour l'âge des créances. Optionnelle.",
                    },
                    "role": _ROLE_DE_LECTURE,
                    "autorise_couts": _AUTORISE_COUTS_DE_LECTURE,
                },
                "additionalProperties": False,
            },
            fonction=lire_comptes_a_recevoir,
            autonomie=Autonomie.T0,
            roles_appareil=_ROLES_APPAREIL_FINANCE,
        ),
        Outil(
            nom="m5_saisir_facture_fournisseur",
            description=(
                "Saisit une facture FOURNISSEUR (M5.2, comptes à payer) contre un PO déjà reçu par M6, tapée par un "
                "HUMAIN : app admin, ou demande approuvée dans la file. Un agent ne la saisit pas seul "
                "(REJ-AP-HUMAIN-REQUIS). "
                "Les taxes TPS/TVQ et le total sont RECALCULÉS (taux versionnés, arrondi ROUND_HALF_UP) ; "
                "total_facture, "
                "le total imprimé, sert de contrôle (nul si absent) et doit concorder au cent près. Refuse un doublon "
                "(même fournisseur, numéro, montant), un PO sans réception, un autre fournisseur que celui du PO. "
                "Rend la "
                "facture et le rapprochement PO, réception, facture PROPOSÉ avec ses écarts : jamais appliqué. N'écrit "
                "jamais aux mouvements : payer un fournisseur est N5 (Nathan et CPA)."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "po_id": {"type": "string", "description": "Bon de commande de M6 déjà reçu, au moins en partie."},
                    "fournisseur_id": {
                        "type": "string",
                        "description": "Fournisseur imprimé sur la facture : celui du PO.",
                    },
                    "numero_facture": {"type": "string", "description": "Numéro TEL QU'IMPRIMÉ sur la facture."},
                    "date_facture": {"type": "string", "description": "AAAA-MM-JJ, telle qu'imprimée sur la facture."},
                    "montant_avant_taxes": {
                        "type": "string",
                        "description": (
                            'Total avant taxes de la facture, texte décimal à 2 décimales au plus, ex. "1234.50".'
                        ),
                    },
                    "total_facture": {
                        "type": ["string", "null"],
                        "description": (
                            "Total imprimé APRÈS taxes, texte décimal ; nul si tu ne l'as pas. Fourni, il doit égaler "
                            "le "
                            "total recalculé, sinon la saisie est refusée."
                        ),
                    },
                    "horodatage": {"type": "string", "description": "ISO 8601 avec fuseau, moment de la saisie."},
                },
                "required": [
                    "po_id",
                    "fournisseur_id",
                    "numero_facture",
                    "date_facture",
                    "montant_avant_taxes",
                    "total_facture",
                    "horodatage",
                ],
                "additionalProperties": False,
            },
            fonction=saisir_facture_fournisseur,
            # T1 -> N3 (par défaut) : écriture interne non finale, sur un registre dédié ; n'engage rien et ne touche
            # jamais
            # les mouvements. Un appel d'appareil `admin` confirmé en base s'exécute (validation humaine au départ,
            # ADR-0009 §4) ; un appel d'agent part en file d'approbation (`n3` : finance ou propriétaire).
            autonomie=Autonomie.T1,
            # §9.5 M5 (dépenses à valider) : le repli documenté de l'OCR fermé est la saisie manuelle, par un humain
            # sur son téléphone. Admin seulement : ni l'employé (§9.2) ni le vendeur (§9.4) ne touchent aux finances.
            roles_appareil=_ROLES_APPAREIL_FINANCE,
        ),
        Outil(
            nom="m5_saisir_facture_sans_po",
            description=(
                "Saisit une facture FOURNISSEUR SANS PO (carburant, outils : une dépense que M6 n'a pas commandée), "
                "tapée par un HUMAIN : app admin, ou demande approuvée dans la file. Un agent ne la saisit pas seul "
                "(REJ-AP-HUMAIN-REQUIS). categorie : de la liste fermée que le propriétaire déclare (department.yaml, "
                "configuration.categories_depense_sans_po) ; sinon refus « catégories à configurer ». TPS/TVQ et total "
                "RECALCULÉS (taux versionnés) ; total_facture, le total imprimé, sert de contrôle. Refuse un doublon "
                "(même fournisseur, numéro, montant). La facture est une dette dès sa saisie : elle entre en entier "
                "dans les comptes à payer et dans le cash libre. N'écrit jamais aux mouvements : payer est N5."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "fournisseur_id": {"type": "string", "description": "Nom du fournisseur, tel qu'imprimé."},
                    "categorie": {
                        "type": "string",
                        "description": "Catégorie de dépense, de la liste configurée ; hors liste : refusée.",
                    },
                    "numero_facture": {"type": "string", "description": "Numéro TEL QU'IMPRIMÉ sur la facture."},
                    "date_facture": {"type": "string", "description": "AAAA-MM-JJ, telle qu'imprimée sur la facture."},
                    "montant_avant_taxes": {
                        "type": "string",
                        "description": 'Total avant taxes, texte décimal à 2 décimales au plus, ex. "84.50".',
                    },
                    "total_facture": {
                        "type": ["string", "null"],
                        "description": (
                            "Total imprimé APRÈS taxes, texte décimal ; nul si tu ne l'as pas. Fourni, il doit égaler "
                            "le total recalculé."
                        ),
                    },
                    "horodatage": {"type": "string", "description": "ISO 8601 avec fuseau, moment de la saisie."},
                },
                "required": [
                    "fournisseur_id",
                    "categorie",
                    "numero_facture",
                    "date_facture",
                    "montant_avant_taxes",
                    "total_facture",
                    "horodatage",
                ],
                "additionalProperties": False,
            },
            fonction=saisir_facture_sans_po,
            # T1 -> N3 (par défaut) : comme la saisie d'une facture de PO, une écriture interne non finale sur le
            # registre dédié ; ne touche jamais les mouvements. Même règle d'humain exigé par l'outil.
            autonomie=Autonomie.T1,
            roles_appareil=_ROLES_APPAREIL_FINANCE,
        ),
        Outil(
            nom="m5_corriger_facture_fournisseur",
            description=(
                "Corrige une facture FOURNISSEUR saisie (numéro, date ou montant avant taxes ; nul = inchangé) en "
                "AJOUTANT une pièce de correction au registre : la facture d'origine n'est jamais modifiée. MOTIF "
                "OBLIGATOIRE. N4 (engagement) : l'appel attend dans la file du propriétaire, et l'outil n'agit que "
                "pour un HUMAIN (finance ou propriétaire) : REJ-AP-HUMAIN-REQUIS sinon. TPS/TVQ et total recalculés ; "
                "total_facture contrôle. Le rapprochement du PO, les totaux et le cash libre lisent le nouvel état. "
                "Refuse : facture inconnue ou annulée, rien ne change (un rejeu), doublon. Le PO et le fournisseur ne "
                "se corrigent pas : annuler puis ressaisir. Jamais de paiement."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "facture_fournisseur_id": {
                        "type": "string",
                        "description": "Identifiant lu dans les comptes à payer (apf-...).",
                    },
                    "motif": {"type": "string", "description": "Pourquoi : une ligne, 300 caractères au plus."},
                    "numero_facture": {"type": ["string", "null"], "description": "Nouveau numéro ; nul : inchangé."},
                    "date_facture": {
                        "type": ["string", "null"],
                        "description": "Nouvelle date AAAA-MM-JJ ; nul : inchangée.",
                    },
                    "montant_avant_taxes": {
                        "type": ["string", "null"],
                        "description": "Nouveau total avant taxes, texte décimal (2 décimales max) ; nul : inchangé.",
                    },
                    "total_facture": {
                        "type": ["string", "null"],
                        "description": "Total imprimé APRÈS taxes, contrôle optionnel du total recalculé.",
                    },
                    "horodatage": {"type": "string", "description": "ISO 8601 avec fuseau, moment de la correction."},
                },
                "required": [
                    "facture_fournisseur_id",
                    "motif",
                    "numero_facture",
                    "date_facture",
                    "montant_avant_taxes",
                    "total_facture",
                    "horodatage",
                ],
                "additionalProperties": False,
            },
            fonction=corriger_facture_fournisseur,
            # T2 -> N4 : modifier une dépense saisie est une écriture finale. Le socle met l'appel en file (ombre et
            # supervise), l'outil exige un humain (autonome : un N4 s'exécute sans file). `admin` peut PROPOSER depuis
            # son téléphone ; la décision est du propriétaire ou de la finance.
            autonomie=Autonomie.T2,
            niveau=NIVEAU_CORRECTION_FACTURE_FOURNISSEUR,
            roles_appareil=_ROLES_APPAREIL_FINANCE,
        ),
        Outil(
            nom="m5_annuler_facture_fournisseur",
            description=(
                "Annule une facture FOURNISSEUR saisie en AJOUTANT une pièce d'annulation au registre : la facture "
                "n'est ni modifiée ni effacée, elle reste au statut ANNULEE. MOTIF OBLIGATOIRE. N4 (engagement) : "
                "l'appel attend dans la file du propriétaire, et l'outil n'agit que pour un HUMAIN (finance ou "
                "propriétaire) : REJ-AP-HUMAIN-REQUIS sinon. Une annulée ne compte plus (facturé, à payer, "
                "rapprochement, doublon, crédits de taxes du cash libre) ; un PO reçu et non facturé redevient un « à "
                "payer attendu ». Refuse : facture inconnue, déjà annulée (un rejeu). Jamais de paiement."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "facture_fournisseur_id": {
                        "type": "string",
                        "description": "Identifiant lu dans les comptes à payer (apf-...).",
                    },
                    "motif": {"type": "string", "description": "Pourquoi : une ligne, 300 caractères au plus."},
                    "horodatage": {"type": "string", "description": "ISO 8601 avec fuseau, moment de l'annulation."},
                },
                "required": ["facture_fournisseur_id", "motif", "horodatage"],
                "additionalProperties": False,
            },
            fonction=annuler_facture_fournisseur,
            autonomie=Autonomie.T2,
            niveau=NIVEAU_CORRECTION_FACTURE_FOURNISSEUR,
            roles_appareil=_ROLES_APPAREIL_FINANCE,
        ),
        Outil(
            nom="m5_lister_comptes_a_payer",
            description=(
                "Comptes à payer (M5.2), pour l'admin : PAR PO reçu de M6, l'« à payer attendu » (quantités reçues x "
                "prix du "
                "PO, cumulé sur les livraisons, taxes recalculées), les factures fournisseur saisies, le « à payer » "
                "et le "
                "rapprochement PO, réception, facture PROPOSÉ avec ses écarts (jamais appliqué). Un attendu incomplet "
                "est "
                "dit non calculable avec son manque, jamais zéro. Réserve sur tout montant : l'unité des prix du "
                "livre de "
                "prix n'est pas déclarée. Par pages (depart, prochain_depart), jamais tronqué ; po_id donne le détail "
                "d'un PO. "
                "Lecture pure. Même règle d'accès que m5_etat_tresorerie : admin seulement ; autorise_couts ne peut "
                "que "
                "restreindre (sans droit : le nombre de PO seulement). Les factures SANS PO entrent dans les totaux ; "
                "sans_po=true les liste (une par ligne, avec l'identifiant que la correction et l'annulation "
                "demandent). Les factures y sont à leur état courant : une corrigée vaut sa correction, une annulée ne "
                "compte nulle part."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "po_id": {"type": ["string", "null"], "description": "Filtre : le détail de ce PO seulement."},
                    "depart": {
                        "type": ["integer", "null"],
                        "minimum": 0,
                        "description": (
                            "Rang du premier PO (ou de la première facture) rendu (0 par défaut) ; reprendre à "
                            "prochain_depart."
                        ),
                    },
                    "sans_po": {
                        "type": ["boolean", "null"],
                        "description": "Vrai : lister les factures SANS PO (avec leur identifiant) plutôt que les PO.",
                    },
                    "role": _ROLE_DE_LECTURE,
                    "autorise_couts": _AUTORISE_COUTS_DE_LECTURE,
                },
                "additionalProperties": False,
            },
            fonction=lister_comptes_a_payer,
            autonomie=Autonomie.T0,
            roles_appareil=_ROLES_APPAREIL_FINANCE,
        ),
        Outil(
            nom="m5_lire_echeances_fiscales",
            description=(
                "Calendrier fiscal vivant (M5.5), pour l'admin : les prochaines échéances de production et de "
                "paiement de la TPS et de la TVQ, avec la TPS/TVQ nette de chaque période et les retards. La "
                "fréquence de production, la fin d'exercice et la date de dernière remise sont celles du propriétaire "
                "(GATE NATHAN) : absentes, refus nommé qui dit quoi déclarer, rien n'est supposé. Une année non "
                "déclarée au calendrier est refusée. Sources officielles citées ; dates à valider par le CPA. Ni "
                "remise, ni déclaration, ni paiement : le calendrier propose. Lecture pure ; aujourd_hui est requis "
                "(M5 n'a pas d'horloge). Même règle d'accès que m5_etat_tresorerie : admin seulement ; autorise_couts "
                "ne peut que restreindre (sans droit : aucun montant)."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "aujourd_hui": {
                        "type": "string",
                        "description": "Jour de référence, AAAA-MM-JJ (jamais deviné : M5 n'a pas d'horloge).",
                    },
                    "limite": {
                        "type": ["integer", "null"],
                        "minimum": 1,
                        "maximum": 12,
                        "description": "Nombre maximal d'échéances rendues (4 par défaut, 12 au plus).",
                    },
                    "role": _ROLE_DE_LECTURE,
                    "autorise_couts": _AUTORISE_COUTS_DE_LECTURE,
                },
                "required": ["aujourd_hui"],
                "additionalProperties": False,
            },
            fonction=lire_echeances_fiscales,
            autonomie=Autonomie.T0,
            roles_appareil=_ROLES_APPAREIL_FINANCE,
        ),
        Outil(
            nom="m5_lire_calendrier_obligations",
            description=(
                "Calendrier préparatoire M5 : TPS/TVQ officielles et obligations déclarées de paie, DAS et dettes. "
                "Pour chaque obligation, expose l'autorité, la période, la date d'échéance, le montant connu ou le "
                "manque, la source du montant et de la date, l'année et la version si elles sont déclarées. Une source "
                "plus ancienne que le début de sa période est marquée périmée et son montant n'est pas utilisable. "
                "Un délai passé est à vérifier : aucun paiement/dépôt n'est présumé. Sans métadonnées, affiche "
                "la ligne "
                "incomplète; aucune date, autorité, période ou règle n'est inférée. Aucune formule de paie, remise, "
                "déclaration, transmission, écriture ou paiement. Lecture seule, analyse préparatoire. "
                "Même règle d'accès que m5_etat_tresorerie : admin seulement ; autorise_couts peut restreindre."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "aujourd_hui": {
                        "type": "string",
                        "format": "date",
                        "description": "Jour de référence AAAA-MM-JJ, fourni par la plateforme; jamais deviné par M5.",
                    },
                    "limite": {
                        "type": ["integer", "null"],
                        "minimum": 1,
                        "maximum": 12,
                        "description": "Nombre maximal d'échéances TPS/TVQ rendues (4 par défaut, 12 au plus).",
                    },
                    "role": _ROLE_DE_LECTURE,
                    "autorise_couts": _AUTORISE_COUTS_DE_LECTURE,
                },
                "required": ["aujourd_hui"],
                "additionalProperties": False,
            },
            fonction=lire_calendrier_obligations,
            autonomie=Autonomie.T0,
            roles_appareil=_ROLES_APPAREIL_FINANCE,
        ),
        Outil(
            nom="m5_preparer_decision_capital",
            description=(
                "Prépare une comparaison indicative comptant, financement et location pour un camion ou équipement. "
                "Si des échéanciers hypothétiques datés sont fournis, projette leurs sorties sur les flux connus "
                "du même "
                "snapshot M5 (maximum huit sorties par option); une option sans échéancier reste incomplète. "
                "Lit le cash libre réel depuis les registres M5, qui incluent AR, AP, taxes, paie, dettes et réserves; "
                "refuse si une composante manque. Le prix et les conditions doivent provenir d'offres identifiées et "
                "datées; aucun taux, frais, avantage fiscal ou valeur résiduelle n'est inventé. Analyse préparatoire "
                "avec questions CPA. Lecture seule : recommande de demander une approbation humaine; ne commande, "
                "ne signe et ne paie rien."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "actif": {"type": "string", "maxLength": 120},
                    "prix": {"type": "string", "pattern": "^[0-9]{1,12}(\\.[0-9]{1,2})?$"},
                    "source_prix": {"type": "string", "maxLength": 120},
                    "prix_valide_jusqua": {"type": "string", "format": "date"},
                    "aujourd_hui": {"type": "string", "format": "date"},
                    "offre_financement": {
                        "type": "object",
                        "properties": {
                            "source": {"type": "string", "minLength": 1, "maxLength": 120},
                            "mise_de_fonds": _MONTANT_TEXTE,
                            "paiement_mensuel": _MONTANT_TEXTE,
                            "mois": {"type": "integer", "minimum": 1, "maximum": 600},
                        },
                        "required": ["source", "mise_de_fonds", "paiement_mensuel", "mois"],
                        "additionalProperties": False,
                    },
                    "offre_location": {
                        "type": "object",
                        "properties": {
                            "source": {"type": "string", "minLength": 1, "maxLength": 120},
                            "mise_de_fonds": _MONTANT_TEXTE,
                            "paiement_mensuel": _MONTANT_TEXTE,
                            "mois": {"type": "integer", "minimum": 1, "maximum": 600},
                        },
                        "required": ["source", "mise_de_fonds", "paiement_mensuel", "mois"],
                        "additionalProperties": False,
                    },
                    "echeanciers_hypothetiques": {
                        "type": "object",
                        "description": (
                            "Facultatif et préparatoire : pour chaque option, flux datés, type de sortie et date "
                            "jusqu'à laquelle la liste est déclarée complète. Références manuelles non vérifiées. "
                            "Une couverture insuffisante reste incomplète; aucune échéance n'est générée."
                        ),
                        "properties": {
                            nom: {
                                "type": "object",
                                "properties": {
                                    "couvre_jusquau": {"type": "string", "format": "date"},
                                    "flux_sorties": {
                                        "type": "array",
                                        "maxItems": 8,
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "type_sortie": {"type": "string", "enum": [
                                                    "prix", "mise_de_fonds", "paiement_mensuel", "autre"
                                                ]},
                                                "montant": _MONTANT_TEXTE,
                                                "date": {"type": "string", "format": "date"},
                                                "source": {"type": "string", "minLength": 1, "maxLength": 80},
                                                "hypothese": {"type": "string", "minLength": 1, "maxLength": 80},
                                            },
                                            "required": ["type_sortie", "montant", "date", "source", "hypothese"],
                                            "additionalProperties": False,
                                        },
                                    },
                                },
                                "required": ["couvre_jusquau", "flux_sorties"],
                                "additionalProperties": False,
                            }
                            for nom in ("achat_comptant", "financement", "location")
                        },
                        "additionalProperties": False,
                    },
                    "role": _ROLE_DE_LECTURE,
                    "autorise_couts": _AUTORISE_COUTS_DE_LECTURE,
                },
                "required": [
                    "actif",
                    "prix",
                    "source_prix",
                    "prix_valide_jusqua",
                    "aujourd_hui",
                    "offre_financement",
                    "offre_location",
                ],
                "additionalProperties": False,
            },
            fonction=preparer_decision_capital,
            autonomie=Autonomie.T0,
            roles_appareil=_ROLES_APPAREIL_FINANCE,
        ),
        Outil(
            nom="m5_prevoir_tresorerie",
            description=(
                "Prévision de trésorerie (M5.7), pour l'admin : semaine par semaine (7 jours dès aujourd_hui), le "
                "solde qui suit des SEULS flux connus et datés : factures clientes envoyées, factures fournisseurs et "
                "attendu non facturé, échéances TPS/TVQ du calendrier, paies, DAS et dettes déclarées. Aucune "
                "projection, aucune vente future. Chaque ligne porte sa source (semaine=k les liste). Inconnu : « non "
                "calculable à partir de la semaine X, manque Y », jamais zéro ; un encaissement échu ou sans date "
                "n'est pas compté. Alerte si le solde de fin de semaine passe sous le seuil du propriétaire (« seuil à "
                "configurer » sinon). Horizon, seuil, délais de paiement : au propriétaire (GATE NATHAN), absents ils "
                "sont dits. Analyse préparatoire : mention obligatoire. Lecture pure. Même règle d'accès que "
                "m5_etat_tresorerie : admin seulement ; autorise_couts ne peut que restreindre (sans droit : aucun "
                "montant)."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "aujourd_hui": {
                        "type": "string",
                        "description": "Jour de départ, AAAA-MM-JJ (jamais deviné : M5 n'a pas d'horloge).",
                    },
                    "horizon_semaines": {
                        "type": ["integer", "null"],
                        "minimum": 1,
                        "maximum": prevision.HORIZON_MAX,
                        "description": (
                            f"Nombre de semaines (1 à {prevision.HORIZON_MAX}). Omis : celui du propriétaire "
                            "(configuration.prevision.horizon_semaines) ; absent aussi : refus, jamais supposé."
                        ),
                    },
                    "semaine": {
                        "type": ["integer", "null"],
                        "minimum": 1,
                        "maximum": prevision.HORIZON_MAX,
                        "description": "Rend les LIGNES (avec leur source) de cette semaine plutôt que la série.",
                    },
                    "depart": {
                        "type": ["integer", "null"],
                        "minimum": 0,
                        "description": (
                            "Rang du premier élément rendu (semaine de la série, ou ligne de la semaine) ; reprendre à "
                            "prochain_depart."
                        ),
                    },
                    "role": _ROLE_DE_LECTURE,
                    "autorise_couts": _AUTORISE_COUTS_DE_LECTURE,
                },
                "required": ["aujourd_hui"],
                "additionalProperties": False,
            },
            fonction=prevoir_tresorerie,
            autonomie=Autonomie.T0,
            # §9.5 M5 (trésorerie) : l'admin seul, comme le cash libre. L'identité est confirmée en base (T1.4-k2).
            roles_appareil=_ROLES_APPAREIL_FINANCE,
        ),
        Outil(
            nom="m5_preparer_dossier_decision_cfo",
            description=(
                "Assemble le rapport CFO M5.16 complet en 25 rubriques exactes depuis une seule lecture cohérente des "
                "registres M5 : cash libre, réserves, factures envoyées à recevoir, comptes à payer et prévision des "
                "seuls flux connus/datés jusqu'à 26 semaines. Les titres restent présents même quand leurs sources "
                "manquent. Scénarios, projections 12/24 mois, impact de décision, recommandation ou confiance restent "
                "INCONNUS sans méthode déterministe et données adaptées. Un devis accepté n'est ni un contrat signé "
                "ni un encaissement. Aucun montant, rôle ou droit n'est reçu en argument. T0, lecture seule, aucune "
                "écriture, approbation, paiement ou action externe; CPA et validations humaines restent nécessaires. "
                "Le volet optionnel obligations_preparees rend une vue source complète versionnée du journal validé, "
                "sans activer le cash. Le défaut dossier_complet garde ses 25 rubriques; journal vide validé: champ "
                "absent dans ce défaut, jamais preuve de zéro. Aucun tronquage si une sortie dépasse le budget."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "aujourd_hui": {
                        "type": "string",
                        "format": "date",
                        "description": (
                            "Date de référence ISO issue de la plateforme; le modèle ne choisit pas l'horloge."
                        ),
                    },
                    "question_posee": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 1000,
                        "description": "Question de cadrage uniquement; elle ne prouve pas l'identité de son auteur.",
                    },
                    "volet": {
                        "type": "string",
                        "enum": ["dossier_complet", "obligations_preparees"],
                        "default": "dossier_complet",
                        "description": "Rapport à 25 rubriques ou vue source préparatoire; même snapshot et grant.",
                    },
                },
                "required": ["aujourd_hui", "question_posee"],
                "additionalProperties": False,
            },
            fonction=preparer_dossier_decision_cfo,
            autonomie=Autonomie.T0,
            roles_appareil=_ROLES_APPAREIL_FINANCE,
        ),
        Outil(
            nom="m5_constater_cash_libre",
            description=(
                "Fait CONSTATER le cash libre réel du jour et le publie au bus (m5.cash_libre_constate), pour que M8 "
                "l'affiche dans la vue exécutive : les montants tels que le calcul les rend, chaque composante avec sa "
                "source et sa fraîcheur, ou « non calculable, manque X » (jamais zéro, publié tel quel). Un constat "
                "par jour de référence et par version des données : le redemander sans que rien ait changé ne publie "
                "rien "
                "(deja_constate). aujourd_hui (AAAA-MM-JJ) est requis : M5 n'a pas d'horloge. Écriture interne (T1) : "
                "le constat et l'événement partent dans la même transaction ; aucun paiement, aucune remise, aucune "
                "écriture aux mouvements. Même règle d'accès que m5_etat_tresorerie : admin seulement, et le droit de "
                "voir les coûts est requis (un constat publie des montants). Analyse préparatoire : mention "
                "obligatoire."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "aujourd_hui": {
                        "type": "string",
                        "description": (
                            "Jour de référence du constat, AAAA-MM-JJ (jamais deviné : M5 n'a pas d'horloge)."
                        ),
                    },
                    "role": _ROLE_DE_LECTURE,
                    "autorise_couts": {
                        "type": ["boolean", "null"],
                        "description": (
                            "Appel d'appareil : omis, il vaut le droit du rôle ; faux est refusé (un constat publie "
                            "des montants : REJ-CONSTAT-COUTS-REQUIS) ; vrai sans ce droit est refusé "
                            "(REJ-ROLE-ELARGI). Sans appareil (agent, console) : obligatoire, et vrai."
                        ),
                    },
                },
                "required": ["aujourd_hui"],
                "additionalProperties": False,
            },
            fonction=constater_cash_libre,
            # T1 -> N3 (par défaut) : écriture interne non finale, sur un registre dérivé et au bus ; ne touche
            # jamais les mouvements. Un appel d'appareil `admin` confirmé en base s'exécute (validation humaine au
            # départ, ADR-0009 §4) ; un appel d'agent part en file d'approbation en mode `ombre` (`n3` : finance ou
            # propriétaire).
            autonomie=Autonomie.T1,
            # §9.5 M5 (trésorerie et cash libre réel) : l'admin seul, comme le cash libre lu. Identité confirmée en
            # base.
            roles_appareil=_ROLES_APPAREIL_FINANCE,
        ),
        Outil(
            nom="m5_envoyer_facture",
            description=(
                "Transitionne une facture BROUILLON vers ENVOYEE (engagement client). N'est "
                "JAMAIS exécuté directement par l'agent : la file d'approbation du socle "
                "intercepte l'appel (N4) et ne l'exécute qu'après la décision signée d'une "
                "personne autorisée (department.yaml/approbations.n4 : finance ou nathan_owner). "
                "Aucun envoi réel de courriel ici (M1, plus tard) : seulement le statut et sa "
                "trace."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "facture_id": {"type": "string"},
                    "horodatage": {"type": "string", "description": "ISO 8601 avec fuseau"},
                    "factures_historique": _HISTORIQUE_FACTURES,
                },
                "required": ["facture_id", "horodatage"],
                "additionalProperties": False,
            },
            fonction=envoyer_facture,
            autonomie=Autonomie.T2,
            niveau=NIVEAU_ENVOI_FACTURE,
        ),
        Outil(
            nom="m5_enregistrer_paiement_facture",
            description=(
                "Transitionne une facture ENVOYEE vers PAYEE (argent réel). N'est JAMAIS exécuté "
                "directement : le socle exige nathan_owner ET l'attestation du professionnel "
                "(ex. référence de dépôt bancaire, N5, jamais automatique). montant_paye — ce qui "
                "a RÉELLEMENT été déposé — est comparé par le code au montant dû de la facture ; "
                "un paiement partiel ou tout autre écart est un verdict nommé, jamais accepté "
                "sans contrôle. N'écrit jamais dans le registre des mouvements (voir "
                "m5_enregistrer_mouvement, un ENCAISSEMENT réel reste un appel séparé)."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "facture_id": {"type": "string"},
                    "montant_paye": _MONTANT_TEXTE,
                    "approbateur": {"type": "string"},
                    "horodatage": {"type": "string", "description": "ISO 8601 avec fuseau"},
                    "factures_historique": _HISTORIQUE_FACTURES,
                },
                "required": ["facture_id", "montant_paye", "approbateur", "horodatage"],
                "additionalProperties": False,
            },
            fonction=enregistrer_paiement_facture,
            autonomie=Autonomie.T3,
            niveau=NIVEAU_PAIEMENT_FACTURE,
        ),
        Outil(
            nom="m5_enregistrer_contrat_horaire",
            description=(
                "Enregistre ou révise un contrat horaire individuel après validation humaine N4 signée par finance ou "
                "le propriétaire. Le taux est la source humaine fournie, CAD décimal texte; période fin exclusive, "
                "fuseau et référence sont explicites. Révision compare le numéro et l'empreinte courants. Journal "
                "salarial privé distinct des mouvements; aucune paie ni écriture de trésorerie."
            ),
            parametres={"type": "object", "properties": {
                "employee_person_id": {"type": "string", "minLength": 1, "maxLength": 128},
                "contrat_id": {"type": "string", "minLength": 1, "maxLength": 64},
                "valide_du": {"type": "string", "format": "date", "description": "Date incluse du contrat."},
                "valide_jusqu_au": {"type": "string", "format": "date", "description": "Borne exclusive."},
                "fuseau": {"type": "string", "minLength": 1, "maxLength": 64},
                "devise": {"type": "string", "enum": ["CAD"]},
                "taux_horaire": {"type": "string", "minLength": 1, "maxLength": 16},
                "source_humaine": {"type": "string", "minLength": 1, "maxLength": 500},
                "date_source": {"type": "string", "format": "date"},
                "revision_attendue": {"type": "integer", "minimum": 0},
                "ligne_id_attendue": {"type": "string", "maxLength": 64},
                "motif": {"type": "string", "minLength": 1, "maxLength": 500},
            }, "required": [
                "employee_person_id", "contrat_id", "valide_du", "valide_jusqu_au", "fuseau", "devise",
                "taux_horaire", "source_humaine", "date_source", "revision_attendue", "ligne_id_attendue", "motif",
            ], "additionalProperties": False},
            fonction=enregistrer_contrat_horaire,
            autonomie=Autonomie.T2,
            niveau=Niveau.N4,
            roles_appareil=_ROLES_APPAREIL_FINANCE,
        ),
        Outil(
            nom="m5_revoquer_contrat_horaire",
            description=(
                "Révoque un contrat horaire individuel après validation humaine N4; ajoute une pièce avec motif, "
                "signataire, révision et tête attendue, sans effacer l'historique. "
                "Aucune écriture de paie ou de caisse."
            ),
            parametres={"type": "object", "properties": {
                "employee_person_id": {"type": "string", "minLength": 1, "maxLength": 128},
                "contrat_id": {"type": "string", "minLength": 1, "maxLength": 64},
                "revision_attendue": {"type": "integer", "minimum": 1},
                "ligne_id_attendue": {"type": "string", "minLength": 64, "maxLength": 64},
                "motif": {"type": "string", "minLength": 1, "maxLength": 500},
            }, "required": ["employee_person_id", "contrat_id", "revision_attendue", "ligne_id_attendue", "motif"],
                "additionalProperties": False},
            fonction=revoquer_contrat_horaire,
            autonomie=Autonomie.T2,
            niveau=Niveau.N4,
            roles_appareil=_ROLES_APPAREIL_FINANCE,
        ),
        Outil(
            nom="m5_lire_contrat_horaire",
            description=(
                "Lecture privée du taux horaire individuel courant qui couvre entièrement les dates inclusives "
                "demandées. Réservée à l'admin confirmé ou au propriétaire via console; refuse trous, taux "
                "multiples, chaîne invalide et identité non autorisée. Ne calcule aucune paie."
            ),
            parametres={"type": "object", "properties": {
                "employee_person_id": {"type": "string", "minLength": 1, "maxLength": 128},
                "valide_du": {"type": "string", "format": "date", "description": "Date de début incluse demandée."},
                "valide_jusqu_au": {
                    "type": "string", "format": "date",
                    "description": "Date de fin incluse demandée; le contrat stocke sa borne de fin exclusive.",
                },
                "fuseau": {"type": "string", "minLength": 1, "maxLength": 64},
            }, "required": ["employee_person_id", "valide_du", "valide_jusqu_au", "fuseau"],
                "additionalProperties": False},
            fonction=lire_contrat_horaire,
            autonomie=Autonomie.T0,
            roles_appareil=_ROLES_APPAREIL_FINANCE,
        ),
        Outil(
            nom="m5_preparer_brut_regulier",
            description=(
                "Prépare une estimation provisoire du brut régulier depuis les minutes M4 complètes et le taux horaire "
                "M5 courant. Dates de requête inclusives, taux CAD et politique d'arrondi explicitement choisie avec "
                "une référence humaine non vérifiée. Accepte `sources_attendues: null` pour les sources courantes, "
                "ou les références M4 et M5 exactes pour refuser toute révision silencieuse. Réservé au propriétaire "
                "confirmé via console, seule origine autorisée par le port M4. Aucun impôt, retenue, cotisation, DAS, "
                "net, paiement ou action officielle calculé. Validation humaine Nathan/CPA requise."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "employee_person_id": {"type": "string", "minLength": 1, "maxLength": 128},
                    "debut": {"type": "string", "format": "date", "description": "Premier jour inclus."},
                    "fin": {"type": "string", "format": "date", "description": "Dernier jour inclus."},
                    "fuseau": {"type": "string", "minLength": 1, "maxLength": 64},
                    "politique_arrondi": {"type": "string", "enum": [brut_regulier.POLITIQUE_ARRONDI]},
                    "hypothese_arrondi": {
                        "type": "string", "minLength": 1, "maxLength": 300,
                        "description": "Référence ou hypothèse déclarée par l'humain, non authentifiée par OPSYS.",
                    },
                    "sources_attendues": {
                        "type": ["object", "null"],
                        "description": (
                            "null = snapshot courant; sinon les références M4 et M5 à comparer avant calcul."
                        ),
                        "properties": {
                            "heures_m4": {
                                "type": "object",
                                "properties": {
                                    "ligne_id": {"type": "string", "minLength": 64, "maxLength": 64},
                                    "revision": {"type": "integer", "minimum": 1},
                                    "empreinte_sources": {"type": "string", "minLength": 64, "maxLength": 64},
                                },
                                "required": ["ligne_id", "revision", "empreinte_sources"],
                                "additionalProperties": False,
                            },
                            "contrat_m5": {
                                "type": "object",
                                "properties": {
                                    "contrat_id": {"type": "string", "minLength": 1, "maxLength": 64},
                                    "revision": {"type": "integer", "minimum": 1},
                                    "ligne_id": {"type": "string", "minLength": 64, "maxLength": 64},
                                },
                                "required": ["contrat_id", "revision", "ligne_id"],
                                "additionalProperties": False,
                            },
                        },
                        "required": ["heures_m4", "contrat_m5"],
                        "additionalProperties": False,
                    },
                },
                "required": [
                    "employee_person_id", "debut", "fin", "fuseau", "politique_arrondi", "hypothese_arrondi",
                    "sources_attendues",
                ],
                "additionalProperties": False,
            },
            fonction=_fonction_brut_regulier(lecteur_heures_m4),
            autonomie=Autonomie.T0,
            # Ce premier raccord est propriétaire-console uniquement; aucune capacité mobile n'est annoncée.
            roles_appareil=frozenset(),
        ),
        Outil(
            nom="m5_lire_sources_regles_paie",
            description=(
                "Expose au propriétaire confirmé par console l'état des références de règles de paie pour une "
                "juridiction, une date, une période, un fuseau et une fréquence fermés. Le catalogue serveur est "
                "la seule déclaration d'état; aucun argument ne peut valider une source. Les références ARC/RQ "
                "actuelles sont NON_QUALIFIEES, les lacunes restent PARTIEL et bloquent tout calcul. Aucun taux, "
                "retenue, contribution, montant, dépôt, déclaration ou action officielle n'est produit."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "juridiction": {"type": "string", "minLength": 2, "maxLength": 8},
                    "date_paie": {"type": "string", "format": "date"},
                    "periode_debut": {"type": "string", "format": "date"},
                    "periode_fin": {"type": "string", "format": "date"},
                    "fuseau": {"type": "string", "minLength": 1, "maxLength": 64},
                    "frequence": {"type": "string", "enum": [
                        "hebdomadaire", "bihebdomadaire", "bimensuelle", "mensuelle",
                    ]},
                },
                "required": ["juridiction", "date_paie", "periode_debut", "periode_fin", "fuseau", "frequence"],
                "additionalProperties": False,
            },
            fonction=lire_sources_regles_paie,
            autonomie=Autonomie.T0,
            # Phase propriétaire-console seulement; aucun accès appareil ou grant d'agent n'est ajouté.
            roles_appareil=frozenset(),
        ),
        Outil(
            nom="m5_preparer_dossier_webras",
            description=(
                "Prépare un JSON privé borné pour saisie et calcul humains dans WebRAS/PDOC. Réutilise le brut "
                "régulier M4/M5 et le catalogue documentaire épinglé; une assiette humaine est facultative, et le "
                "brut régulier n'est jamais assimilé au revenu imposable. Tous impôts, cotisations, retenues, net "
                "et DAS restent UNKNOWN. Aucun appel WebRAS, paiement ou action officielle. "
                "Propriétaire console uniquement."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "employee_person_id": {"type": "string", "minLength": 1, "maxLength": 128},
                    "debut": {"type": "string", "format": "date"},
                    "fin": {"type": "string", "format": "date"},
                    "fuseau": {"type": "string", "minLength": 1, "maxLength": 64},
                    "politique_arrondi": {"type": "string", "enum": [brut_regulier.POLITIQUE_ARRONDI]},
                    "hypothese_arrondi": {"type": "string", "minLength": 1, "maxLength": 300},
                    "sources_attendues": {"type": ["object", "null"]},
                    "date_paie": {"type": "string", "format": "date"},
                    "periodes_annuelles": {"type": "integer", "enum": [12, 24, 26, 52]},
                    "revenu_imposable_cad": {
                        "type": ["string", "null"],
                        "pattern": "^(?:0|[1-9][0-9]{0,8})\\.[0-9]{2}$",
                    },
                    "reference_revenu_imposable": {"type": ["string", "null"], "maxLength": 240},
                },
                "required": [
                    "employee_person_id",
                    "debut",
                    "fin",
                    "fuseau",
                    "politique_arrondi",
                    "hypothese_arrondi",
                    "sources_attendues",
                    "date_paie",
                    "periodes_annuelles",
                    "revenu_imposable_cad",
                    "reference_revenu_imposable",
                ],
                "additionalProperties": False,
            },
            fonction=_fonction_dossier_webras(lecteur_heures_m4),
            autonomie=Autonomie.T0,
            roles_appareil=frozenset(),
        ),
        Outil(
            nom="m5_enregistrer_echeancier_contrat",
            description=(
                "Enregistre ou révise un échéancier d'encaissement d'un contrat client après validation humaine N4. "
                "Rapproche le prix HT déclaré au prix_total HT du devis M3; le TTC, les échéances datées, la source "
                "et la couverture sont saisis explicitement depuis la pièce humaine. Maximum 8 échéances. Aucune taxe "
                "n'est calculée et aucun mouvement financier n'est écrit. Voie propriétaire/approbation seulement; "
                "aucun accès appareil n'est déclaré."
            ),
            parametres={"type": "object", "properties": {
                "contrat_id": {"type": "string", "minLength": 1, "maxLength": 64},
                "devis_id": {"type": "string", "minLength": 1, "maxLength": 128},
                "prix_ht": {"type": "string", "pattern": "^(?:0|[1-9][0-9]{0,11})(?:\\.[0-9]{1,2})?$"},
                "prix_ttc": {"type": "string", "pattern": "^(?:0|[1-9][0-9]{0,11})(?:\\.[0-9]{1,2})?$"},
                "devise": {"type": "string", "enum": ["CAD"]},
                "source_humaine": {"type": "string", "minLength": 1, "maxLength": 500},
                "date_source": {"type": "string", "format": "date"},
                "couverture_jusquau": {"type": "string", "format": "date"},
                "echeances": {"type": "array", "minItems": 1, "maxItems": 8, "items": {
                    "type": "object", "properties": {
                        "date": {"type": "string", "format": "date"},
                        "montant_ttc": {"type": "string", "pattern": "^(?:0|[1-9][0-9]{0,11})(?:\\.[0-9]{1,2})?$"},
                    }, "required": ["date", "montant_ttc"], "additionalProperties": False,
                }},
                "revision_attendue": {"type": "integer", "minimum": 0},
                "ligne_id_attendue": {"type": "string", "maxLength": 64},
                "motif": {"type": "string", "minLength": 1, "maxLength": 500},
            }, "required": [
                "contrat_id", "devis_id", "prix_ht", "prix_ttc", "devise", "source_humaine", "date_source",
                "couverture_jusquau", "echeances", "revision_attendue", "ligne_id_attendue", "motif",
            ], "additionalProperties": False},
            fonction=enregistrer_echeancier_contrat,
            autonomie=Autonomie.T2,
            niveau=Niveau.N4,
            roles_appareil=frozenset(),
        ),
        Outil(
            nom="m5_revoquer_echeancier_contrat",
            description=(
                "Révoque un échéancier contractuel par un nouveau maillon N4 append-only, avec tête attendue et motif. "
                "Ne supprime pas l'historique et n'écrit aucun mouvement. Voie propriétaire/approbation seulement; "
                "aucun accès appareil n'est déclaré."
            ),
            parametres={"type": "object", "properties": {
                "contrat_id": {"type": "string", "minLength": 1, "maxLength": 64},
                "devis_id": {"type": "string", "minLength": 1, "maxLength": 128},
                "revision_attendue": {"type": "integer", "minimum": 1},
                "ligne_id_attendue": {"type": "string", "minLength": 64, "maxLength": 64},
                "motif": {"type": "string", "minLength": 1, "maxLength": 500},
            }, "required": ["contrat_id", "devis_id", "revision_attendue", "ligne_id_attendue", "motif"],
                "additionalProperties": False},
            fonction=revoquer_echeancier_contrat,
            autonomie=Autonomie.T2,
            niveau=Niveau.N4,
            roles_appareil=frozenset(),
        ),
        Outil(
            nom="m5_prevoir_tresorerie_contrats",
            description=(
                "Prévision M5.8a à partir du solde et des obligations M5.7 existants, plus les échéanciers "
                "explicitement "
                "saisis et revus en N4. Compare HT au devis M3 et TTC à la somme déclarée des échéances; ne calcule "
                "aucune taxe. Une facture active du devis bloque l'échéancier pour éviter un double compte; "
                "PAYEE n'est "
                "pas une preuve de dépôt bancaire. Rapport PARTIEL, prévision hebdomadaire et lecture CFO avant toute "
                "lecture sensible. Propriétaire console confirmé seulement; aucun nouvel accès agent/appareil."
            ),
            parametres={"type": "object", "properties": {
                "aujourd_hui": {"type": "string", "format": "date"},
            }, "required": ["aujourd_hui"], "additionalProperties": False},
            fonction=prevoir_tresorerie_contrats,
            autonomie=Autonomie.T0,
            roles_appareil=frozenset(),
        ),
    ) + (
        _outils_couts_marketing(lecteur_campagne_m7) if lecteur_campagne_m7 is not None else ()
    ) + _outils_obligations_preparees()


# DEVICE préparatoire, hors registre des mouvements et hors consommateurs YAML.
def _autorite_obligations_preparees():
    from . import obligations_preparees as ob

    cnx = stockage.connexion_courante()
    actor = contexte.identite_appelante()
    if (
        cnx is None
        or actor is None
        or actor.source != "appareil"
        or actor.role != "admin"
    ):
        raise ob.Refus("IDENTITE-INVALIDE")
    valid = approbations.signataire_valide(cnx, actor)
    if valid is None or valid.role != "admin":
        raise ob.Refus("IDENTITE-INVALIDE")
    return {"personne": valid.personne, "role": "admin", "source": "appareil"}


def _snapshot_obligations_preparees():
    from . import obligations_preparees as ob

    try:
        snapshot = list(stockage.maillons(_DEPARTEMENT, ob.REGISTRE))
    except (ValueError, TypeError, KeyError):
        raise ob.Refus("REGISTRE-INVALIDE") from None
    ob.snapshot_courant(snapshot)
    return snapshot


def _intention_obligations_preparees(arguments):
    from opsys import idempotence, intentions_obligations_m5

    from . import obligations_preparees as ob

    current = intentions_obligations_m5.intention_courante()
    if current is None:
        raise ob.Refus("CONTEXTE-ABSENT")
    meta, copied = current
    reception = contexte.horodatage_reception()
    if (
        copied != arguments
        or reception is None
        or reception.appareil != meta.appareil
        or not ob.texte(meta.appareil)
        or not ob.texte(meta.cle)
    ):
        raise ob.Refus("CONTEXTE-ABSENT")
    try:
        ob.instant(meta.horodatage_appareil)
    except ob.Refus:
        raise ob.Refus("CONTEXTE-ABSENT") from None
    intent = {
        "appareil_id": meta.appareil,
        "intention_uuid": meta.cle,
        "empreinte_arguments": idempotence.empreinte_arguments(copied),
    }
    return meta, intent, reception.recu_le.isoformat()


def _ack_obligations_preparees(maillon, index):
    from . import obligations_preparees as ob

    return {
        "accepte": True,
        "version_schema": 1,
        "resultat": ob.projection(maillon, ob.reference(maillon, index)),
        "registre": ob.REGISTRE,
    }


def _borner_obligations_preparees(business):
    from . import obligations_preparees as ob

    limit = contexte.limite_sortie()
    if type(limit) is not int:
        raise ob.Refus("CONTEXTE-ABSENT")
    for replay in (False, True):
        whole = {"ok": True, "resultat": business, "rejoue": replay}
        if len(json.dumps(whole, ensure_ascii=False)) > min(5400, limit):
            raise ob.Refus("SORTIE-TROP-VOLUMINEUSE")
    return business


def autoriser_obligation_preparee_appareil(
    arguments, *, nom="m5_enregistrer_obligation_preparee_appareil"
):
    from . import obligations_preparees as ob

    auteur = _autorite_obligations_preparees()
    if nom == "m5_lire_obligations_preparees_appareil":
        ob.valider_lecture(arguments)
        _snapshot_obligations_preparees()
        return
    if nom != "m5_enregistrer_obligation_preparee_appareil":
        raise ob.Refus("ARGUMENTS-INVALIDES")
    a = ob.valider_mutation(arguments)
    meta, intent, hora = _intention_obligations_preparees(a)
    snapshot = _snapshot_obligations_preparees()
    # Cached-success size is measured against its own prefix, not a later category head.
    own = [
        i
        for i, m in enumerate(snapshot)
        if m["intention"]["appareil_id"] == meta.appareil
        and m["intention"]["intention_uuid"] == meta.cle
    ]
    if own:
        _borner_obligations_preparees(
            _ack_obligations_preparees(snapshot[own[0]], own[0])
        )
    else:
        entry = ob.construire_entree(a, auteur, intent, hora, meta.horodatage_appareil)
        proposed = registre_module.Registre(copy.deepcopy(snapshot))
        proposed.ajouter(entry)
        _borner_obligations_preparees(
            _ack_obligations_preparees(proposed.lire()[-1], len(snapshot))
        )


def verifier_rejeu_obligation_preparee_appareil(arguments, reponse):
    from . import obligations_preparees as ob

    autoriser_obligation_preparee_appareil(arguments)
    auteur = _autorite_obligations_preparees()
    meta, intent, _ = _intention_obligations_preparees(arguments)
    snapshot = _snapshot_obligations_preparees()
    if (
        type(reponse) is not dict
        or set(reponse) != {"ok", "resultat"}
        or reponse["ok"] is not True
    ):
        raise ob.Refus("REJEU-INCOHERENT")
    found = [
        i
        for i, m in enumerate(snapshot)
        if m["intention"] == intent
        and m["auteur"] == auteur
        and m["horodatage_appareil_declare"] == meta.horodatage_appareil
    ]
    if len(found) != 1:
        raise ob.Refus("REJEU-INCOHERENT")
    expected = _ack_obligations_preparees(snapshot[found[0]], found[0])
    try:
        identical = json.dumps(
            reponse["resultat"], ensure_ascii=False, sort_keys=True, allow_nan=False
        ) == json.dumps(expected, ensure_ascii=False, sort_keys=True, allow_nan=False)
    except (ValueError, TypeError):
        identical = False
    if not identical:
        raise ob.Refus("REJEU-INCOHERENT")
    _borner_obligations_preparees(expected)


def lire_obligations_preparees_appareil(aujourd_hui, decalage, limite):
    from . import obligations_preparees as ob

    try:
        _autorite_obligations_preparees()
        ob.valider_lecture(
            {"aujourd_hui": aujourd_hui, "decalage": decalage, "limite": limite}
        )
        result = ob.lire(
            _snapshot_obligations_preparees(), aujourd_hui, decalage, limite
        )
        business = {"accepte": True, "resultat": result}
        # T0 has no replay metadata in its actual transport envelope.
        bound = contexte.limite_sortie()
        if type(bound) is not int or len(
            json.dumps({"ok": True, "resultat": business}, ensure_ascii=False)
        ) > min(5400, bound):
            raise ob.Refus("SORTIE-TROP-VOLUMINEUSE")
        return business
    except ob.Refus as exc:
        return {"accepte": False, "verdict": exc.verdict}


def enregistrer_obligation_preparee_appareil(
    categorie, operation, declaration, revision_attendue, motif
):
    from . import obligations_preparees as ob

    arguments = {
        "categorie": categorie,
        "operation": operation,
        "declaration": declaration,
        "revision_attendue": revision_attendue,
        "motif": motif,
    }
    try:
        autoriser_obligation_preparee_appareil(arguments)
        auteur = _autorite_obligations_preparees()
        meta, intent, hora = _intention_obligations_preparees(arguments)
        snapshot = _snapshot_obligations_preparees()
        ob.verifier_revision(ob.snapshot_courant(snapshot), arguments)
        entry = ob.construire_entree(
            arguments, auteur, intent, hora, meta.horodatage_appareil
        )
        proposed = registre_module.Registre(copy.deepcopy(snapshot))
        proposed.ajouter(entry)
        preflight = _borner_obligations_preparees(
            _ack_obligations_preparees(proposed.lire()[-1], len(snapshot))
        )
    except ob.Refus as exc:
        return {"accepte": False, "verdict": exc.verdict}
    # Every technical/postappend failure escapes to the external transaction rollback.
    try:
        durable = registre_module.Registre(stockage.maillons(_DEPARTEMENT, ob.REGISTRE))
        line = durable.ajouter(entry)
        persisted = durable.lire()
        ob.snapshot_courant(persisted)
        if len(persisted) != len(snapshot) + 1 or persisted[-1]["ligne_id"] != line:
            raise RuntimeError("confirmation durable M5 incohérente")
        ack = _borner_obligations_preparees(
            _ack_obligations_preparees(persisted[-1], len(snapshot))
        )
        if ack != preflight:
            raise RuntimeError("confirmation durable M5 divergente")
        return ack
    except Exception as exc:
        raise RuntimeError("échec technique après écriture préparatoire M5") from exc


def _outils_obligations_preparees():
    return (
        Outil(
            nom="m5_lire_obligations_preparees_appareil",
            description="Déclaration humaine préparatoire non attestée ; aucun mouvement financier ni activation cash.",
            parametres={
                "additionalProperties": False,
                "properties": {
                    "aujourd_hui": {
                        "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$",
                        "type": "string",
                    },
                    "decalage": {"maximum": 10000, "minimum": 0, "type": "integer"},
                    "limite": {"maximum": 8, "minimum": 1, "type": "integer"},
                },
                "required": ["aujourd_hui", "decalage", "limite"],
                "type": "object",
            },
            fonction=lire_obligations_preparees_appareil,
            autonomie=Autonomie.T0,
            roles_appareil=frozenset({"admin"}),
            portee_contexte="globale",
        ),
        Outil(
            nom="m5_enregistrer_obligation_preparee_appareil",
            description="Déclaration humaine préparatoire non attestée ; aucun mouvement financier ni activation cash.",
            parametres={
                "additionalProperties": False,
                "allOf": [
                    {
                        "if": {"properties": {"operation": {"const": "declarer"}}},
                        "then": {
                            "properties": {
                                "declaration": {
                                    "additionalProperties": False,
                                    "properties": {
                                        "au": {
                                            "anyOf": [
                                                {
                                                    "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$",
                                                    "type": "string",
                                                },
                                                {"type": "null"},
                                            ]
                                        },
                                        "calendrier": {
                                            "anyOf": [
                                                {
                                                    "additionalProperties": False,
                                                    "properties": {
                                                        "annee": {
                                                            "anyOf": [
                                                                {
                                                                    "maximum": 9999,
                                                                    "minimum": 1,
                                                                    "type": "integer",
                                                                },
                                                                {"type": "null"},
                                                            ]
                                                        },
                                                        "autorite": {
                                                            "anyOf": [
                                                                {
                                                                    "maxLength": 240,
                                                                    "minLength": 1,
                                                                    "type": "string",
                                                                },
                                                                {"type": "null"},
                                                            ]
                                                        },
                                                        "echeance_source": {
                                                            "anyOf": [
                                                                {
                                                                    "maxLength": 240,
                                                                    "minLength": 1,
                                                                    "type": "string",
                                                                },
                                                                {"type": "null"},
                                                            ]
                                                        },
                                                        "periode_debut": {
                                                            "anyOf": [
                                                                {
                                                                    "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$",
                                                                    "type": "string",
                                                                },
                                                                {"type": "null"},
                                                            ]
                                                        },
                                                        "periode_fin": {
                                                            "anyOf": [
                                                                {
                                                                    "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$",
                                                                    "type": "string",
                                                                },
                                                                {"type": "null"},
                                                            ]
                                                        },
                                                        "source_applicable_du": {
                                                            "anyOf": [
                                                                {
                                                                    "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$",
                                                                    "type": "string",
                                                                },
                                                                {"type": "null"},
                                                            ]
                                                        },
                                                        "source_applicable_jusqu_au": {
                                                            "anyOf": [
                                                                {
                                                                    "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$",
                                                                    "type": "string",
                                                                },
                                                                {"type": "null"},
                                                            ]
                                                        },
                                                        "source_consultee_le": {
                                                            "anyOf": [
                                                                {
                                                                    "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$",
                                                                    "type": "string",
                                                                },
                                                                {"type": "null"},
                                                            ]
                                                        },
                                                        "version": {
                                                            "anyOf": [
                                                                {
                                                                    "maxLength": 240,
                                                                    "minLength": 1,
                                                                    "type": "string",
                                                                },
                                                                {"type": "null"},
                                                            ]
                                                        },
                                                    },
                                                    "required": [
                                                        "autorite",
                                                        "periode_debut",
                                                        "periode_fin",
                                                        "echeance_source",
                                                        "source_consultee_le",
                                                        "source_applicable_du",
                                                        "source_applicable_jusqu_au",
                                                        "annee",
                                                        "version",
                                                    ],
                                                    "type": "object",
                                                },
                                                {"type": "null"},
                                            ]
                                        },
                                        "echeance": {
                                            "anyOf": [
                                                {
                                                    "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$",
                                                    "type": "string",
                                                },
                                                {"type": "null"},
                                            ]
                                        },
                                        "montant": {
                                            "anyOf": [
                                                {
                                                    "pattern": "^[0-9]{1,12}(\\.[0-9]{1,2})?$",
                                                    "type": "string",
                                                },
                                                {"type": "null"},
                                            ]
                                        },
                                        "source": {
                                            "anyOf": [
                                                {
                                                    "maxLength": 120,
                                                    "minLength": 1,
                                                    "type": "string",
                                                },
                                                {"type": "null"},
                                            ]
                                        },
                                    },
                                    "required": [
                                        "montant",
                                        "source",
                                        "au",
                                        "echeance",
                                        "calendrier",
                                    ],
                                    "type": "object",
                                }
                            }
                        },
                    },
                    {
                        "if": {"properties": {"operation": {"const": "retirer"}}},
                        "then": {
                            "properties": {
                                "declaration": {"type": "null"},
                                "motif": {
                                    "maxLength": 500,
                                    "minLength": 1,
                                    "type": "string",
                                },
                            }
                        },
                    },
                ],
                "properties": {
                    "categorie": {"enum": ["paies", "das", "dettes"]},
                    "declaration": {
                        "anyOf": [
                            {
                                "additionalProperties": False,
                                "properties": {
                                    "au": {
                                        "anyOf": [
                                            {
                                                "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$",
                                                "type": "string",
                                            },
                                            {"type": "null"},
                                        ]
                                    },
                                    "calendrier": {
                                        "anyOf": [
                                            {
                                                "additionalProperties": False,
                                                "properties": {
                                                    "annee": {
                                                        "anyOf": [
                                                            {
                                                                "maximum": 9999,
                                                                "minimum": 1,
                                                                "type": "integer",
                                                            },
                                                            {"type": "null"},
                                                        ]
                                                    },
                                                    "autorite": {
                                                        "anyOf": [
                                                            {
                                                                "maxLength": 240,
                                                                "minLength": 1,
                                                                "type": "string",
                                                            },
                                                            {"type": "null"},
                                                        ]
                                                    },
                                                    "echeance_source": {
                                                        "anyOf": [
                                                            {
                                                                "maxLength": 240,
                                                                "minLength": 1,
                                                                "type": "string",
                                                            },
                                                            {"type": "null"},
                                                        ]
                                                    },
                                                    "periode_debut": {
                                                        "anyOf": [
                                                            {
                                                                "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$",
                                                                "type": "string",
                                                            },
                                                            {"type": "null"},
                                                        ]
                                                    },
                                                    "periode_fin": {
                                                        "anyOf": [
                                                            {
                                                                "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$",
                                                                "type": "string",
                                                            },
                                                            {"type": "null"},
                                                        ]
                                                    },
                                                    "source_applicable_du": {
                                                        "anyOf": [
                                                            {
                                                                "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$",
                                                                "type": "string",
                                                            },
                                                            {"type": "null"},
                                                        ]
                                                    },
                                                    "source_applicable_jusqu_au": {
                                                        "anyOf": [
                                                            {
                                                                "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$",
                                                                "type": "string",
                                                            },
                                                            {"type": "null"},
                                                        ]
                                                    },
                                                    "source_consultee_le": {
                                                        "anyOf": [
                                                            {
                                                                "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$",
                                                                "type": "string",
                                                            },
                                                            {"type": "null"},
                                                        ]
                                                    },
                                                    "version": {
                                                        "anyOf": [
                                                            {
                                                                "maxLength": 240,
                                                                "minLength": 1,
                                                                "type": "string",
                                                            },
                                                            {"type": "null"},
                                                        ]
                                                    },
                                                },
                                                "required": [
                                                    "autorite",
                                                    "periode_debut",
                                                    "periode_fin",
                                                    "echeance_source",
                                                    "source_consultee_le",
                                                    "source_applicable_du",
                                                    "source_applicable_jusqu_au",
                                                    "annee",
                                                    "version",
                                                ],
                                                "type": "object",
                                            },
                                            {"type": "null"},
                                        ]
                                    },
                                    "echeance": {
                                        "anyOf": [
                                            {
                                                "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$",
                                                "type": "string",
                                            },
                                            {"type": "null"},
                                        ]
                                    },
                                    "montant": {
                                        "anyOf": [
                                            {
                                                "pattern": "^[0-9]{1,12}(\\.[0-9]{1,2})?$",
                                                "type": "string",
                                            },
                                            {"type": "null"},
                                        ]
                                    },
                                    "source": {
                                        "anyOf": [
                                            {
                                                "maxLength": 120,
                                                "minLength": 1,
                                                "type": "string",
                                            },
                                            {"type": "null"},
                                        ]
                                    },
                                },
                                "required": [
                                    "montant",
                                    "source",
                                    "au",
                                    "echeance",
                                    "calendrier",
                                ],
                                "type": "object",
                            },
                            {"type": "null"},
                        ]
                    },
                    "motif": {"maxLength": 500, "type": "string"},
                    "operation": {"enum": ["declarer", "retirer"]},
                    "revision_attendue": {
                        "anyOf": [
                            {
                                "additionalProperties": False,
                                "properties": {
                                    "index": {
                                        "maximum": 9999,
                                        "minimum": 0,
                                        "type": "integer",
                                    },
                                    "ligne_id": {
                                        "pattern": "^[0-9a-f]{64}$",
                                        "type": "string",
                                    },
                                    "precedent_ligne_id": {
                                        "anyOf": [
                                            {
                                                "pattern": "^[0-9a-f]{64}$",
                                                "type": "string",
                                            },
                                            {"type": "null"},
                                        ]
                                    },
                                    "registre": {"const": "obligations_preparees"},
                                },
                                "required": [
                                    "registre",
                                    "index",
                                    "ligne_id",
                                    "precedent_ligne_id",
                                ],
                                "type": "object",
                            },
                            {"type": "null"},
                        ]
                    },
                },
                "required": [
                    "categorie",
                    "operation",
                    "declaration",
                    "revision_attendue",
                    "motif",
                ],
                "type": "object",
            },
            fonction=enregistrer_obligation_preparee_appareil,
            autonomie=Autonomie.T1,
            roles_appareil=frozenset({"admin"}),
            portee_contexte="globale",
        ),
    )
