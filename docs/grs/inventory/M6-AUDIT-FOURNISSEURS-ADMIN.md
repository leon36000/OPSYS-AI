# Fiches fournisseurs admin — audit avant code

27 octobre 2026, source `84308044609d052a956e7fe3844facec1f2e9b0d`.
Objectif : supprimer la préparation Python des fournisseurs dans le parcours de saisie des tarifs.

`fournisseurs.py::{enregistrer_fournisseur,lire_fournisseur,lister_fournisseurs}` possède déjà
le journal vivant append-only et la projection fusionnée. Les outils agents M6 correspondants
restent compatibles. La liste privée du formulaire tarif est limitée à identité/nom. Aucun
écran admin de création/correction du fournisseur n’a été établi dans le code console inspecté.

Attention : `enregistrer_fournisseur` reconstruit un candidat intégral dont les paramètres
optionnels omis sont `None`. Une correction de nom seule par ce chemin peut donc vider des
coordonnées ou conditions existantes. Le nouveau port doit appliquer un PATCH fermé sur la
fiche courante, sous sa garde de source, puis appeler le domaine avec tous les champs retenus.
Le journal historique reste inchangé; un champ non édité conserve sa valeur. Un `None`
explicite est un effacement volontaire de ce champ, pas une valeur devinée.

Tranche : ports console privés de lecture et d’enregistrement, réutilisant autorité SQL,
réception serveur, enveloppe bornée et contexte de mutation M6. Écriture CAS sur empreinte
exacte de la fiche courante, création seulement sans fiche, reçu idempotent puis audit dans
le même savepoint. Réauthentifier avant rejeu. Fermer chemins génériques/runtime/MCP; aucun
droit appareil ajouté. Nom obligatoire, contacts facultatifs bornés et fournis par l’humain;
aucune coordonnée, condition commerciale, délai ou nom d’employé inféré. Les champs riches
existants non affichés dans le formulaire (catégories, délais, format) sont préservés.

Interface : `/crm/fournisseurs`, fiche courante, formulaire nom/courriel/téléphone, liens depuis
catalogue matériaux et saisie tarif. UUID de fournisseur généré pour une nouvelle fiche;
identités historiques conservées. La liste projette noms/identifiants; la fiche admin peut
voir ses contacts. Pas de suppression dure, envoi de courriel, commande ou paiement.

Preuves : création/révision/rejeu, source périmée et concurrence, PATCH préservant les champs
riches, effacement explicite, rollback audit/quota, révocation/CSRF et canaux génériques;
HTTP fournisseur → matériau → tarif → soumission et document client sans contacts/coûts.
Données QA fictives, sources en lecture seule pendant les tests, bornes habituelles.
Historique navigable fournisseur, M10 des fournisseurs/tarifs, import de courriel, navigateur
natif, PostgreSQL et mobile restent à qualifier séparément. M6/CRM/OPSYS : PARTIAL.

## Qualification des ports privés

Le 27 octobre : `fournisseurs_console.py` expose lecture, liste paginée de noms et
PATCH privé. Le journal M6 est borné avant sa matérialisation. Les nouvelles valeurs ont
des limites explicites; les valeurs historiques inchangées suivent la validation du
domaine initial, même au-delà des limites de saisie nouvelles. Régression : 26 catégories,
ancien courriel libre, téléphone long et délai historique conservés pendant une correction
du nom. Aucun nettoyage implicite. L’entrée globale est bornée à 128 Kio, la sortie à 64 Kio.

`supplier-ports-v5` : 200 tests passent, aucun échec/skip, 14,77 s; Ruff et vérificateur
297 outils/173 portées déclarées passent. Populations recoupées non additionnées. Les reçus
QA privés conservent les étapes rouges : v1 lint, v2 mauvais import du codec, v3 contrôle
de champs/tailles incomplet, v4 oracle de rejet des booléens par le répartiteur et deux
lignes trop longues. Revue statique : compatibilité historique et lecture bornée corrigées.
Les ports génériques/runtime restent fermés, sans nouvelle portée appareil.

Limites : la qualification concerne SQLite, pas PostgreSQL; écran HTTP encore à raccorder
à ce jalon. Pas de mémoire M10 des fournisseurs/tarifs, d’import courriel ni d’envoi réel.

## Raccord HTTP qualifié

`src/opsys/console/fournisseurs_ui.py` apporte GET `/crm/fournisseurs`, GET
`/crm/fournisseurs/{fournisseur_id}` et POST `/crm/fournisseurs/enregistrer`. Les liens
depuis les matériaux et les tarifs ouvrent cette gestion. Les listes paginées ne diffusent
pas les contacts; l’admin actif peut consulter et corriger une fiche privée sans envoi.

Chaque champ a une action explicite : conserver, remplacer, ou effacer pour les contacts.
Sur une fiche existante, conserver est sélectionné au départ. Le serveur n’utilise alors
pas la valeur du champ reçu : une normalisation CR/LF par le navigateur ne doit pas réécrire
un ancien contact pendant une correction du nom. Catégories, délais et formats cachés ne
sont jamais envoyés par le formulaire. Une fiche nouvelle ne présélectionne aucun contact.

`supplier-ui-v3` : 96 tests passent, aucun échec/skip, 30,83 s; Ruff et vérificateur
297 outils/173 portées passent. Le parcours crée réellement fournisseur, matériau, tarif,
modèle, lignes et devis par HTTP, puis vérifie le document client sans prix de revient,
identité ni contact fournisseur. Les sources d’ancrage M3 viennent du lien de la page réelle.
Une correction fournisseur entre aperçu et confirmation du tarif bloque celle-ci.
Rejeu, source périmée, révocation, CSRF, corps excessif, champs étrangers, effacement explicite,
échappement HTML et conservation d’anciennes coordonnées normalisées sont vérifiés.

Les populations ne s’additionnent pas avec `supplier-ports-v5`. L’historique rouge reste
conservé : v1 deux mauvaises URL de fixture construisaient `/tarifs` après la query de version;
v2 une chaîne Python non fermée empêchait le chargement du routeur. La revue statique a
détecté la perte possible de CR/LF et une lecture de fixture M3 inutile, toutes deux corrigées.
Ce parcours ASGI/SQLite ne démontre ni navigateur natif, ni PostgreSQL, ni app mobile.
Prochaine capacité : audit et raccord M10 des nouvelles versions fournisseurs/tarifs,
sans coordonnées ni coût copié dans l’événement. M6/CRM/OPSYS restent **PARTIAL**.

Le raccord serveur des références fournisseurs est maintenant qualifié localement :
[projection historique, bus M10 et preuves](M6-AUDIT-REFERENCES-FOURNISSEURS-TARIFS-M10.md).
Il conserve les préfixes et refuse les sources altérées, sans recopier les contacts. Le badge
admin fournisseur, la mémoire des tarifs et l’import courriel restent ouverts.
