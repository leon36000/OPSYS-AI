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

## Provenance privée du devis — raccord du domaine

`provenance_tarifs.py` valide désormais une copie optionnelle fermée dans `devis_durable`.
Elle lie la source textuelle, la source/révision du jeu de lignes et les tarifs par
référence de ligne. Chaque ligne du devis sourcé est couverte une fois, avec identifiant
de modèle unique, coût décimal égal au coût calculé, unité identique, CAD et date non future
à la création. Le marquage documentaire reste déclaratif ou fallback. L’adaptateur futur
doit toujours vérifier les sources réelles; le validateur ne les authentifie pas.

La provenance participe au refus de rejeu avec contenu différent, ne peut être ajoutée
rétroactivement à un devis manuel et reste copiée profondément après lecture/acceptation.
Elle ne figure pas dans les documents clients, la projection employé ou les événements
existants. Les anciens appels et rendus restent compatibles; aucun port supplémentaire
n’accepte encore cette donnée depuis un navigateur ou un agent.

Preuve locale `provenance-v2` : 534 réussites, aucun échec, un saut historique du garde
réservé à GitHub Actions. Le PDF réel a bien été généré et lu. Cas vérifiés : couverture
de 20 lignes, doublons refusés, unité/coût/date/source incohérents, changements de provenance
au rejeu, copies indépendantes, SQLite migré puis moteur fermé/rouvert, rollback, acceptation,
HTML et octets PDF identiques au devis équivalent sans provenance. Ruff et manifestes
réussis. La sélection recoupe les précédentes; ne pas additionner les populations.

## Prochaine capacité

Ajouter les ports console privés, les formulaires et
le parcours HTTP/SQLite réel modèle → tarif choisi → devis → HTML/PDF. Vérifier révocation,
CSRF, source modifiée GET/POST, double clic, rollback et absence de coût/fournisseur dans
les documents clients. Les modèles manuels restent compatibles. L’import courriel,
M10, PostgreSQL, navigateur natif et mobile restent des capacités distinctes à qualifier.

Les commandes réelles, paiements, envois externes et changements sensibles gardent les
validations Nathan prévues; ce lot n’en déclenche aucun.
