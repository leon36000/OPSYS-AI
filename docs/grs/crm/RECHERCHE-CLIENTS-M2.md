# Recherche de clients et prospects — source M2

Statut : PARTIAL pour CRM-04. La recherche complète la consultation du répertoire ; la correction est décrite dans [son contrat](CORRECTION-COORDONNEES-M2.md).
Aucune fusion de contacts ni moteur CRM parallèle.

## Objectif et audit

Le répertoire consultait une page de `m2_lister_leads`, sans recherche textuelle. Filtrer seulement
cette page aurait caché des résultats du reste du répertoire. Le module pur `liste_leads.py` sait déjà
appliquer la visibilité, le statut et les segments avant pagination : c’est ce chemin qui est étendu.
Aucune dépendance, nouvelle table, index externe ou calcul par modèle n’est ajouté.

## Contrat et comportement

L’outil existant `m2_lister_leads` reçoit le paramètre facultatif `recherche` (texte ou null,
120 caractères maximum). L’absence, null et les espaces seuls gardent le comportement antérieur.
Une saisie invalide est refusée ; elle ne devient jamais silencieusement une liste complète.

Les termes séparés par des espaces doivent tous être présents, chacun dans au moins un champ autorisé :
nom, courriel, téléphone ou identifiant de lead. Le texte est normalisé Unicode NFKD, sans distinction
de casse ni d’accents. La comparaison est littérale, sans regex, SQL généré, correction orthographique
ni inférence. Un téléphone conserve sa ponctuation : cette tranche ne prétend pas reconnaître toutes
les écritures nationales/internationales d’un numéro. Les notes, pièces et autres champs ne sont pas
recherchés. Le résultat garde la forme habituelle des leads, sans ajouter leurs coordonnées à la liste.

La visibilité est appliquée avant la comparaison et les comptes. Les filtres de statut et de segment
restent combinables. L’ordre canonique M2 et le budget de taille de réponse sont préservés ; les totaux
et le lien suivant portent seulement les résultats autorisés. Une recherche active apparaît dans
`filtre.recherche` ; sans recherche, la forme historique de `filtre` reste identique.

## Interface et fichiers

`GET /crm?q=...` (sous le préfixe configuré) ajoute un champ de recherche au filtre de statut. La
pagination conserve le texte saisi et le filtre ; une nouvelle soumission du formulaire repart au
premier résultat. Une recherche vide de résultats l’annonce sans prétendre que le répertoire est vide.
La saisie est échappée en HTML et encodée dans les liens.

Fichiers : `departments/m02-revenue-crm/src/m2_revenue_crm/liste_leads.py` et `outils.py`,
`src/opsys/console/crm_ui.py`, `journaux_http.py`, `application.py`. Tests dans `test_liste_leads.py`,
`tests/test_console_crm.py` et `tests/test_console.py`.

## Confidentialité, permissions et risques

La recherche conserve les règles existantes : vendeur limité à ses leads, admin SQL actif pour le
cockpit, révocations prises en compte. Aucune attribution de droit à une personne réelle. Les lectures
ne modifient ni contacts, ni notes, ni événements. Aucune action externe ni validation financière
n’est créée ; les gates Nathan existants restent inchangés.

Le texte recherché peut contenir un nom ou un courriel. Le point d’entrée officiel de la console
installe donc un filtre sur le handler d’accès Uvicorn : une requête portant `q` est journalisée avec
`?q=[MASQUE]`, tout en gardant méthode, chemin, statut et client réseau. Le filtre ne touche pas la
requête utilisée par l’application et ne désactive pas les logs d’erreurs. La politique existante
`Referrer-Policy: no-referrer` et les réponses privées restent présentes.

L’URL de recherche reste visible dans l’historique du navigateur. Un reverse proxy ou un lancement
ASGI personnalisé doit également masquer les paramètres ; cette tranche ne configure pas ces
infrastructures et ne revendique pas leur qualification. Le filtre est testé avec le formateur réel
Uvicorn installé et sa configuration non modifiée globalement.

## Preuves et prochaines étapes

Les tests couvrent accents/casse, plusieurs termes, téléphone, résultat situé après vingt-quatre
non-correspondances, pagination, combinaison avec statut, recherche vide, entrées invalides,
syntaxe regex/SQL traitée littéralement, exclusion des notes et des leads d’un autre vendeur,
HTML/URL échappés, masquage des logs et base inchangée. Les tests existants de liste, accès M2 et console
restent dans la qualification ciblée. Les populations se recoupent : ne pas les additionner.

Les reçus `crm-root-qa-20261027-r1/search-*` conservent les rouges et les reprises. Le rapport de
qualification donne les résultats exacts ; il ne prouve ni navigateur, ni déploiement, ni gros volume.
La recherche parcourt les fiches déjà chargées par M2 : indexation et mesures de charge restent à
qualifier si le volume l’exige. La correction historisée utilise désormais cette recherche sur les coordonnées courantes.
Restent à qualifier les performances, PostgreSQL et la propagation vers les documents dépendants.
