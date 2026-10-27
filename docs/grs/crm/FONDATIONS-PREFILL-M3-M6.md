# Lignes de modèles et sélection de coûts M6 — composants préparés

27 octobre 2026. Suite de [l’audit préalable](AUDIT-LIGNES-PREFILL-M3-M6.md).
Statut CRM-07 : **PARTIAL**. Ces composants purs sont testés; le formulaire de devis
ne les appelle pas encore. Aucun préremplissage de lignes annoncé comme livré.

## Objectif et architecture

Réutiliser une liste de descriptions et d’unités sans inventer les quantités ni les coûts.
`modeles_lignes_soumission.py` (M3) conserve un journal distinct, append-only, lié au hash
exact du modèle textuel. Chaque ligne porte seulement son identifiant, sa description,
son matériau et son unité. Versions, CAS, auteur, intention et limite UTF-8 réutilisent
les mécanismes M3 existants. Réviser le texte ne transfère pas les lignes automatiquement.

`tarif_soumission.py` (M6) lit une séquence bornée de couples rang SQL/entrée de livre de
prix et un fournisseur déjà résolu. Le dernier écrit pour le matériau et le fournisseur
choisis reste la convention M6. Il doit avoir unité exacte, devise CAD, date civile non
future et coût numérique fini positif représentable sans arrondi supplémentaire.
Une identité d’entrée illisible bloque la sélection, même après un ancien tarif valide.
Le lecteur ne change pas le stock, le livre de prix, les achats ou les prix de vente.

Le résultat donne rang, empreinte, coût décimal, unité, devise, date et source déclarée.
Sans document, le marquage reste `FALLBACK_PRICE_BOOK`. Une empreinte détecte une sélection
modifiée; elle ne certifie pas l’authenticité documentaire. Aucun fournisseur moins cher,
conversion d’unité, taux de change ou quantité par défaut n’est choisi implicitement.

## Interfaces, données et permissions

Fonctions pures `enregistrer`/`lire` (M3), `selectionner_tarif` (M6); aucune nouvelle route
ni nouveau port public. Aucun droit appareil ou agent ajouté. Le futur adaptateur devra
contrôler l’admin SQL actif, la provenance M3, les références M6, le jour serveur et la
taille SQL avant lecture, puis relire rang/empreinte dans la transaction de création.
Les permissions ne sont pas démontrées par ces fonctions pures : elles relèvent du prochain raccord.

## Vérification et limites

Tests : `test_modeles_lignes_soumission.py`, `test_tarif_soumission.py`, régressions modèles
textuels/livre de prix et conformité des deux départements. Dernière sélection locale :
257 réussis, aucun échec ni saut; Ruff et vérificateur des manifestes réussis (283 outils,
173 déclarés aux appareils, inchangés). Cette population recoupe les précédentes.

Le premier passage conserve son rouge : le harnais tentait de sérialiser un tuple avant
d’atteindre le validateur; le test corrigé appelle bien le domaine et conserve l’exigence
de refus sans écriture. Un constat de revue sur l’identité manquante du dernier tarif a
été corrigé avec huit cas de régression. Aucun changement de contrat historique M6.

Preuves locales distinctes : `work/chantier-opsys-20261010/crm-prefill-qa-20261027-r1/`,
phases `foundation-v1`, `foundation-v2`, `foundation-v3`, avec reçus, JUnit, empreintes et
limites effectives. QA sans réseau, source en lecture seule, homes/tmp privés.

## Prochaine capacité

Conserver une provenance privée fermée dans le nouveau devis, incluse dans l’idempotence
et les copies profondes. Ajouter ensuite les ports console privés, les formulaires et
le parcours HTTP/SQLite réel modèle → tarif choisi → devis → HTML/PDF. Vérifier révocation,
CSRF, source modifiée GET/POST, double clic, rollback et absence de coût/fournisseur dans
les documents clients. Les modèles manuels restent compatibles. L’import courriel,
M10, PostgreSQL, navigateur natif et mobile restent des capacités distinctes à qualifier.

Les commandes réelles, paiements, envois externes et changements sensibles gardent les
validations Nathan prévues; ce lot n’en déclenche aucun.
