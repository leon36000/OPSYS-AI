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
