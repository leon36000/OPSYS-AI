# M9.14 — veille de marché

Statut : **DONE_VERIFIED** (aucun accès externe : import explicite seulement).
[Architecture M9](M9-STRATEGIC-INTELLIGENCE-ARCHITECTURE.md) · [table d'audit](M9-AUDIT-INITIAL-QUADRUPLE-A.md).

## Objectif

Tenir une veille datée et versionnée (concurrents, marché, prix, avis, SEO, fournisseurs, réglementation, saisonnalité,
météo) à partir de documents publics que la personne **importe**, avec leur licence, leur qualité et leur péremption, et
les relier aux décisions qu'ils informent.

## Pourquoi

Une récupération réseau ouvrirait une surface nouvelle (secrets, licences, injection de consignes, données
personnelles). Tant qu'aucun accès externe n'est autorisé, l'import manuel est le seul chemin ; il est contrôlé avant
toute écriture et un texte suspect n'est jamais rendu au modèle.

## État actuel

`veille.py` (schéma `m9.veille.v1`, événements `SOURCE`, `SOURCE_RETIREE`, `DOCUMENT`, `LIEN`) :

- **Source déclarée** : `source_id`, `nom`, `url_prefixe` (https sobre : ni requête, ni fragment, ni identifiants),
  `licences_admises` parmi `CC0-1.0`, `CC-BY-4.0`, `CC-BY-SA-4.0`, `OGL-Canada-2.0`, `DOMAINE-PUBLIC`,
  `perime_apres_jours` (1–3650) et `categorie` facultative. Déclarer une source n'accorde aucun accès
  (`acces_externe: false`).
- **Catégories** (`CATEGORIES`) : `concurrent`, `marche` (défaut), `prix`, `avis`, `seo`, `fournisseur`,
  `reglementation`, `saisonnalite`, `meteo` ; une autre valeur : `REJ-VEILLE-CATEGORIE`. Le registre de concurrents est
  une source de catégorie `concurrent`.
- **Qualité des données** (`QUALITES`) : `public` (publié tel quel), `estime` (estimé par la personne), `incertain`
  (défaut, jamais `public` par défaut) ; autre valeur : `REJ-VEILLE-QUALITE`.
- **Import refusé avant écriture** : source inconnue ou retirée (`REJ-VEILLE-SOURCE`), URL hors préfixe
  (`REJ-VEILLE-URL`), licence non admise (`REJ-VEILLE-LICENCE`), date invalide (`REJ-VEILLE-DATE`), champ ou contenu hors
  borne de 20 000 caractères (`REJ-VEILLE-DOCUMENT`), courriel, téléphone ou NAS apparent
  (`REJ-VEILLE-DONNEES-PERSONNELLES`, rien n'est conservé).
- **Quarantaine** : un texte qui ressemble à une instruction (huit familles de motifs : ignorer les consignes, prompt
  système, changement de rôle, oubli, balise de rôle, appel d'outil, commande, révélation) ou qui contient des caractères
  invisibles est conservé `QUARANTAINE` : métadonnées et motifs visibles, ni extrait ni contenu, non citable, non reliable
  (`REJ-VEILLE-QUARANTAINE`).
- **Projection** à un instant : `ACCEPTE`, `REMPLACE` (version plus récente de la même URL), `PERIME` (au-delà de la
  péremption de la source), `QUARANTAINE` ; seul `ACCEPTE` est `citable`. Un import identique est idempotent.

## Architecture

Module pur sans module réseau (la garde `RESEAU_INTERDIT` de `conformite.py` refuse `socket`, `urllib`, `requests`) ;
analyse déterministe par expressions régulières (`analyser_contenu`). `etat()` calcule aussi `par_categorie`
(documents, citables, répartition par qualité des seuls citables) ; **l'outil `m9_lire_veille` ne renvoie pas ce
décompte** (il rend sources, documents sans contenu et liens) : la catégorie se lit sur la source.

## Fichiers

[veille.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/veille.py),
[outils_veille.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/outils_veille.py),
`chainage.py` (registre chaîné), [direction_ui.py](../../../src/opsys/console/direction_ui.py).

## Outils et pages de console

| Outil | Accès |
|---|---|
| `m9_declarer_source_veille`, `m9_retirer_source_veille`, `m9_importer_document_veille`, `m9_lier_veille_decision` | admin strict, T1/N2 (écriture interne) |
| `m9_lire_veille` (`connaissance`, `decision_ref`) | admin strict, T0/N0 |
| `m9_lire_document_veille` (tranches `depart`/`longueur`) | admin strict ; étiqueté `donnee_non_fiable` ; `REJ-VEILLE-TRANCHE` |

Pages : panneau « Veille » de `/direction` et `/direction/veille` (lecture, filtre `decision_ref`). Aucun formulaire
d'import en console : l'import passe par l'outil.

## Données et registres

Registre chaîné `veille` (département `m09-strategic-intelligence`) ; chaîne altérée : `REJ-VEILLE-CHAINE-INVALIDE`.
Provenance de chaque document : `IMPORT_MANUEL`, `importe_par` (personne authentifiée).

## Workflows

1. Déclarer la source (préfixe, licences, péremption, catégorie).
2. Importer le document (titre, version, date de publication, licence, qualité, contenu).
3. Lire l'état à un instant ; relier un document accepté à une décision (`LIEN`, information seulement).
4. Retirer une source : plus aucun import, documents existants lisibles.

## Intégrations

Aucune intégration externe. Le lien `decision_ref` est un identifiant libre : il n'est pas vérifié contre une session de
conseil ni une décision M10. L'orchestrateur accepte une source `veille:<empreinte>` pour une action proposée.

## Risques

- La véracité des documents n'est pas vérifiée ; la qualité est déclarée par la personne.
- La détection d'injection est par motifs : un texte malveillant habile peut passer ; c'est pourquoi le contenu est
  toujours étiqueté donnée non fiable.
- Aucune collecte automatique : la veille est aussi fraîche que les imports.

## Gates Nathan

Autoriser (ou non) un accès externe à des sources publiques, avec licence vérifiée ; sans cette décision, l'import reste
le seul chemin (statut externe non ouvert, aucun `GATED_EXTERNAL_API` revendiqué).

## Tests

`departments/m09-strategic-intelligence/tests/test_veille.py` (import cité, idempotence, quarantaine, données
personnelles, refus avant écriture, périmé/remplacé/source retirée, lien, chaîne corrompue, catégories et qualités,
quarantaine hors décompte) ; `tests/test_m9_veille_integre.py` (parcours par les vrais outils, refus, identités).

## Statut

DONE_VERIFIED pour l'import explicite ; aucune récupération réseau livrée, par choix.

## Prochaines étapes

1. Exposer `par_categorie` dans `m9_lire_veille` si le tableau de bord doit montrer la qualité par catégorie.
2. Vérifier `decision_ref` contre les sessions de conseil closes, si Nathan veut un lien contrôlé.
