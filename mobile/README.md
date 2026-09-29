# App mobile OPSYS

Expo SDK 57, Expo Router, React Native 0.86, TypeScript strict. Quatre profils (un groupe de routes par profil) :
`(employee)`, `(seller)`, `(admin)`, `(client)`. Le profil est celui que le serveur confirme pour l'appareil
(`GET /opsys/identite`), jamais un choix de l'utilisateur. Décisions, pile et limites :
[`docs/architecture/MOBILE.md`](../docs/architecture/MOBILE.md) ; portée de chaque rôle :
[`docs/architecture/ROLES.md`](../docs/architecture/ROLES.md).

## Commandes

```bash
npm ci
npm run typecheck        # tsc --noEmit
npm test -- --ci         # Jest (preset jest-expo)
npx expo start           # développement
```

Le bac à sable de développement n'exécute pas le core : il se construit et se teste en CI (`.github/workflows/mobile.yml`
pour cette app). Les écrans (`app/`) ne sont pas testés en rendu (pas de `@testing-library/react-native`) : leur
logique vit dans `src/`, en fonctions pures, testées.

## Écrans par profil

| Profil | Écrans (`app/`) | Outils appelés (nom nu) |
|---|---|---|
| Employé | `today`, `job/[id]` (statut, checklist, photos, signature, matériaux, terminer), `punch`, `consent` | `m4_*`, `m6_declarer_materiaux_utilises` |
| Vendeur | `leads`, `lead/[id]`, `quotes` | `m2_lister_leads`, `m2_suggerer_prochaine_action`, `m2_trouver_client_de_lead`, `m2_obtenir_client_360`, `m2_enregistrer_interaction`, `m3_lire_devis` |
| Admin | `approvals` | `m9_lister_demandes_approbation`, `m9_decider_demande_approbation` |

### Vendeur (PLAN T4.8, §9.4)

- **`leads`** : ses leads (`m2_lister_leads`), paginés (`decalage`, `suivant`), filtre par statut et par segment. Chaque
  segment cite sa règle et la donnée qui l'a déclenché. Un segment non calculable est dit « non calculable, manque X »,
  jamais une liste vide.
- **`lead/[id]`** : prochaine action suggérée avec sa règle citée, Client 360, historique, et une note
  (`m2_enregistrer_interaction`) qui part par la file sortante avec sa clé d'idempotence (300 caractères au plus).
- **`quotes`** : statut et prix de ses soumissions (`m3_lire_devis`), jamais le coût ni la marge. Aucun outil ne liste les
  soumissions d'un vendeur : la liste montre celles que ses leads citent, et une autre s'ouvre par son numéro.
- **Hors ligne** : lecture d'abord ; le cache SQLite (une clé par personne) est rendu marqué comme cache, avec sa date.

## Règles de l'app

- **Fail-closed.** Une valeur absente est dite absente ; une réponse illisible n'est jamais un succès ; un élément
  illisible est compté, jamais deviné. L'app ne calcule ni prix, ni solde, ni score, ni date.
- **Tout passe par la porte d'appareil** (`src/protocole/`) : le nom NU de l'outil, jamais une personne ni un rôle en
  argument (le core pose `_meta` d'après le jeton). Le serveur décide de la portée ; l'app ne la recalcule pas.
- **Écritures par la file sortante** (`src/outbox/`) : l'id de la mutation, créé sur l'appareil, est la clé d'idempotence.
  Un renvoi rend la réponse enregistrée, sans second effet. Un refus du serveur est un échec permanent dont le verdict est
  montré.
- **Vues par rôle appliquées deux fois** : le serveur, puis l'app (elle ne garde pas ce qu'un rôle ne doit pas voir).
- Textes en `fr-CA` (défaut) et `en-CA` (`src/i18n/`), clés vérifiées par Jest.

## `src/`

`roles/` garde de routes · `appairage/`, `identite/` appairage et identité · `protocole/` client `/tools/invoke` ·
`outbox/` file sortante et vidangeur · `stockage/` dépôt clé/valeur · `m2/`, `m3/`, `m4/`, `m6/`, `approbations/` contrats
des outils · `vendeur/` chargeurs, cache et fusion de pages du profil vendeur (`fixtures/` : vraies réponses du moteur) ·
`today/`, `checklist/`, `photos/`, `signature/`, `fichiers/` profil employé · `ecrans/` logique pure des écrans ·
`i18n/` textes.
