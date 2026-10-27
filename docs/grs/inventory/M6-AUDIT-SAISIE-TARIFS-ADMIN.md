# Saisie des tarifs fournisseurs — audit avant raccord admin

27 octobre 2026, source `0f975e337b0146daf6706a7f10b4e6a370546eb8`.
Statut : **PARTIAL**, préparation de la prochaine tranche; aucun nouveau port tarif ni écran livré ici.

## Besoin et constat vérifié

Le catalogue nommé, le choix de fournisseur et les devis préremplis sont qualifiés sur
HTTP/SQLite. Leurs tests préparent encore les tarifs avec les domaines Python réels :
le secrétariat ne dispose pas d’un parcours HTTP démontré de saisie du livre de prix.
`rg` des fichiers console n’a pas trouvé d’écran prix/fournisseurs/inventaire dédié à ce flux.

Réutiliser `m6_enregistrer_prix` (nom exact), `m6_enregistrer_fournisseur`,
`m6_lister_fournisseurs`, `livre_prix.enregistrer_prix`, `tarif_soumission.selectionner_tarif`
et le catalogue nommé. L’outil historique `m6_enregistrer_prix` accepte prix numérique,
unité facultative, source déclarée facultative et un historique de substitution en mode
mémoire. Ces formes restent compatibles pour leurs appelants; elles ne doivent pas être
exposées telles quelles à un formulaire admin sécurisé.

Le domaine historique exige int/float et sélectionne le dernier écrit du couple
matériau/fournisseur. Le lecteur qualifié de soumission exige montant positif borné,
unité exacte, CAD et date civile non future. Une conversion Decimal → float ne doit pas
changer le montant décimal relu : prévoir une vérification stricte du roundtrip textuel
ou une extension compatible du domaine, avec preuve, sans arrondir silencieusement.
Une référence documentaire reste `SOURCE_DECLAREE`; absence = `FALLBACK_PRICE_BOOK`,
jamais source authentifiée. Aucun prix officiel n’est inventé ou importé implicitement.

## Tranche minimale proposée

1. Port console privé de lecture/choix du matériau actif et du fournisseur réel, puis de
   prévisualisation du tarif saisi : coût CAD explicite, unité M6, date, source et provenance.
2. Confirmation humaine avec intention idempotente; autorité SQL admin/session revérifiée,
   réception serveur, schéma fermé, historique de substitution interdit, borne source/sortie.
3. Garde CAS du dernier tarif du couple par rang SQL et empreinte, plus version de fiche
   matériau/fournisseur; pas d’écrasement silencieux après préparation. Append seulement.
4. Transaction de l’entrée tarif, audit et reçu. Rejeu exact revalidé, sans seconde entrée.
   Le fournisseur ou matériau inconnu/inactif, unité modifiée, date future, coût non fini,
   conversion décimale altérée et source périmée refusent sans effet.
5. Formulaire HTTP accessible depuis la fiche matériau; choix nommés, préparation sans
   écriture, confirmation du nouveau tarif. Fournisseurs absents : indiquer la donnée à
   fournir, ne pas fabriquer des contacts. Gestion de leurs fiches reste une tranche distincte
   si aucun écran existant réutilisable n’est établi.

## Preuves et limites

E2E HTTP : saisir un tarif sourcé → sélectionner ce tarif dans un devis → prix M3 identique;
tarif changé pendant préparation refusé; double clic/reprise; réouverture SQL; rollback
sur audit/quota; révocation/CSRF; absence de coûts dans document client; ancien devis figé.
Préserver les tests du livre de prix, PO et lecteur de soumission. QA privée sans réseau.

Pas d’envoi fournisseur, achat, paiement ni courriel réel. L’import automatique des listes
reçues par courriel reste prévu et distinct : document reçu → extraction privée bornée →
correspondances et unités vérifiées → changements préparatoires → politique humaine validée.
Ce jalon n’autorise ni lecture de courriel réel en QA ni modification de données de production.
M6, CRM et l’objectif OPSYS-AI global restent PARTIAL.

## Ports privés qualifiés

`prix_console.py` apporte `m6_lister_fournisseurs_tarif_console`,
`m6_preparer_tarif_console` et `m6_confirmer_tarif_console`. La liste projette seulement
identité et nom, 25 par page. Préparation : fiche matériau active et unité canonique,
fournisseur connu, montant décimal fourni, date civile non future, source déclarée ou
fallback explicitement marqué. Une conversion vers le nombre historique est acceptée
seulement si sa relecture Decimal depuis le texte reste exactement égale au montant fourni.
Le livre historique et ses anciens outils ne changent pas de contrat.

La confirmation compare les empreintes de la fiche matériau et fournisseur et le rang SQL /
empreinte du dernier tarif du couple (ou l’absence explicite). Une autre écriture impose
une nouvelle préparation. Tarif, audit et reçu sont atomiques; le rejeu retourne son reçu
original après revalidation de l’admin, sans nouvelle entrée. Les ports génériques, runtime
profilé et MCP sont fermés avant toute intention; aucune portée appareil ajoutée.

`tests/test_console_prix_m6.py` couvre préparation sans effet, précision, réouverture,
rejeu après changement de prix, sources périmées, refus des champs injectés, date/montant,
rollback audit/quota, révocation et deux confirmations concurrentes (une seule entrée).
QA privée `crm-prefill-qa-20261027-r1/price-ports-v2` : 136 réussites, aucun échec/saut,
13,40 s; Ruff et vérificateur 294 outils/173 portées réussis. Populations recoupées,
non additives. Revue statique indépendante sans constat sur précision, CAS ou transaction.
Le reçu v1 conserve 136 tests réussis et deux E501 corrigés. HTTP et mémoire des nouveaux
tarifs restent à raccorder; aucune capacité de prix par courriel ou d’achat annoncée ici.

## Parcours HTTP confirmé

`src/opsys/console/tarifs_ui.py` expose GET
`/crm/materiaux/{materiau_id}/tarifs`, POST `/preparer` et POST `/confirmer`, accessibles
depuis la fiche active du matériau. Fournisseurs connus par nom, pages de 25, aucun choix
ni prix ni date présélectionné. Absence de fournisseur et matériau inactif sont signalés.
Unité et CAD sont relus/imposés côté serveur. La préparation montre ancien tarif utilisable
ou son indisponibilité, nouveau coût, date et marquage documentaire; elle ne crée rien.
La confirmation ajoute une version et retourne à la fiche, avec garde de sources et reçu.

QA privée `crm-prefill-qa-20261027-r1/price-ui-v2` : 85 tests réussis, zéro échec/saut,
28,42 s; Ruff et vérificateur 294/173 réussis. Parcours réel : saisie HTTP → confirmation →
réouverture SQL → devis M3 prérempli au tarif → document client sans coût/fournisseur privé.
Un changement de tarif ultérieur ne change ni le devis existant ni le reçu original.
Refus HTTP : source périmée, CSRF, rôle révoqué, unité/devise/historique injectés,
fournisseur inconnu, corps excessif. Prix fallback sans document et échappement HTML prouvés.
Revue statique indépendante sans défaut établi. V1 conservé : 84 tests réussis et deux
E501 corrigés; V2 ajoute l’échappement de la référence et un nouveau prix préparé par le
formulaire avant confirmation. Populations recoupées, non additives.

La CI de `ef6fcb31` a révélé un compteur documentaire resté à 288 au lieu de 291 après
l’ajout des ports privés du catalogue. Le compteur courant est maintenant 294, dont les
mêmes 173 outils appareil. `roles-count-v1` qualifie les 116 tests de portées appareil,
zéro échec/saut, 1,13 s, Ruff et vérificateur réussis; aucun droit ajouté ni test affaibli.
Le rouge CI et ses SKIP demeurent historiques; cela ne transforme pas la CI précédente en verte.

Le parcours suppose un fournisseur déjà enregistré. Création/modification de fiches
fournisseurs en HTTP, mémoire M10 des tarifs, historique navigable de prix, import annuel
par courriel, navigateur natif et PostgreSQL restent ouverts. Pas d’achat, de paiement ou
de modification des devis antérieurs. Statut M6/CRM/OPSYS : PARTIAL.
