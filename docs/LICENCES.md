# Périmètre des licences OPSYS-AI

## Décision du propriétaire — 28 octobre 2026

Nathan St-Louis demande une politique restrictive pour ses futurs apports originaux
et un accueil public succinct. Le texte applicable est [LICENSE](../LICENSE).
Cette décision résout la contradiction de présentation entre l'ancien fichier
Apache et l'intention propriétaire de l'[ADR-0003, Q7](decisions/ADR-0003-RATIFICATION.md).
Elle ne révoque aucun droit accordé avant la transition et ne requalifie pas tous
les fichiers existants comme propriétaires.

La transition est identifiée par le premier commit qui remplace le LICENSE racine
par cette politique, sur chaque ligne de développement qui l'adopte. Une date
seule, une PR non fusionnée sur sa branche cible ou ce document seul ne changent
pas la licence d'une autre branche. Les travaux déjà publiés dans des PR ou
branches sous une autre licence gardent les droits déjà accordés. Les branches
actives doivent reprendre explicitement cette transition, sans réécrire leur
historique ni supprimer les apports d'autres intervenants.

Révisions publiques contrôlées avant préparation : `main` à
`54d89d355555ba29c51a05828bb2ee9b8abbfc1d` et la branche de développement
`codex/restructuration-2026-09-30` à `3ab7692f041892ec2af0cab6f241a715edac2d50`.
Ces repères documentent l'état antérieur ; ils ne prétendent pas borner tous les
apports publiés sur d'autres branches. Chaque PR de transition indique son parent
et son nouveau commit exacts pour rendre la prise d'effet vérifiable.

## Carte des droits

| Périmètre | Régime |
|---|---|
| Nouveaux apports originaux appartenant à Nathan St-Louis, publiés pour la première fois avec la nouvelle politique et sans licence antérieure ou distincte | [Politique propriétaire](../LICENSE), tous droits réservés hors exceptions explicites |
| Code et documents déjà publiés sous Apache-2.0 | Permissions antérieures conservées ; [texte Apache intact](../LICENSES/Apache-2.0.txt) et historique Git |
| `core/` y compris son fork existant | [MIT](../core/LICENSE), [NOTICE](../core/NOTICE), [provenance](../core/PROVENANCE.md) et [avis tiers](../core/THIRD_PARTY_NOTICES.md) conservés |
| Dépendances, bibliothèques, composants vendoriés, modèles, médias, extraits et contributions de tiers | Leurs licences et ayants droit respectifs ; aucune appropriation par cette politique |
| Personnes et agents mandatés pour OPSYS-AI | Permission limitée au mandat, détaillée au §4 du LICENSE ; pas d'autorisation de production ou de fusion ajoutée |

## Consignes aux mainteneurs et agents

- Continuer les missions autorisées : le README réduit n'est pas une réduction du produit.
- Lire [AGENTS.md](../AGENTS.md) et les [repères de développement](DEVELOPPEMENT.md).
- Conserver tous les avis de licence/provenance des tiers et les inclure dans les
  distributions qui les nécessitent. Ne pas remplacer `core/LICENSE` ni annoncer
  « tout le dépôt est propriétaire ».
- Pour un apport nouveau hors Core, vérifier la provenance et les droits avant de
  l'inclure sous cette politique. Pour une licence distincte, la rendre explicite.
  Une contribution externe ne transfère pas automatiquement ses droits.
- Ne pas étiqueter un paquet mélangeant ces périmètres comme intégralement
  propriétaire, intégralement Apache ou intégralement MIT sans analyse des fichiers
  distribués. Les manifestes de composants tiers restent inchangés.
- Ne pas requalifier les missions en cours, versions déjà publiées ou branches
  restées sur Apache. Coordonner l'adoption du commit de transition.

## Limite de protection et page publique

Un dépôt public permet toujours la lecture et la copie technique ; GitHub permet
également certains usages comme le fork suivant ses conditions. Le changement de
licence n'efface ni les clones, ni les forks, ni l'historique, ni les droits
antérieurs. Une licence encadre les droits ; elle ne fournit pas un contrôle d'accès.
Le README succinct et un champ About neutre réduisent la mise en avant commerciale,
mais les spécifications et le code restent accessibles.

Le champ About est un réglage GitHub distinct des fichiers du dépôt. Texte proposé :
« OPSYS-AI — dépôt de développement. » Aucun changement de visibilité n'est autorisé
par cette préparation. Le passage en privé et l'organisation/coût des CI doivent
faire l'objet d'une décision séparée du propriétaire.

Références : [licences sur GitHub](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository),
[texte Apache-2.0](https://www.apache.org/licenses/LICENSE-2.0.txt).
