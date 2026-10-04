# Calendrier marketing M7 dans la console

La page `/opsys/marketing/calendrier` (préfixe configurable) permet au propriétaire et aux
administrateurs de relire les textes d'usine M7 et de préparer des créneaux manuels. L'accès et
les mutations passent par la session console active, les contrôles CSRF et les outils M7 canoniques.
Les identifiants, le texte, le consentement et les décisions affichés sont relus depuis les registres
durables; la page ne modifie pas ces preuves directement.

## Parcours

1. Saisir l'identifiant d'un WCT déjà reçu par M7. M7 vérifie sa source et le consentement marketing,
   puis propose des brouillons. Un identifiant absent ou un retrait de consentement ne crée aucun texte.
2. Lire le texte entier, sa plateforme, son numéro de révision, l'origine du texte, le WCT source et
   la preuve du consentement. La liste utilise la pagination de `m7_lister_contenus_chantier`, au plus
   huit contenus et selon sa limite canonique de taille.
3. Le propriétaire approuve ou rejette le texte exact. L'autorisation N3 du département M7 reste en
   vigueur; un administrateur sans rôle propriétaire ne peut pas la contourner.
4. À partir d'un texte approuvé, saisir un instant ISO 8601 avec fuseau, futur et dans les 365 jours.
   M7 crée un brouillon de créneau lié à la révision, au WCT et à son empreinte source.
5. Le propriétaire approuve ou rejette ce créneau exact. L'approbation du texte et celle du créneau
   sont deux décisions distinctes.
6. Après les deux approbations, le propriétaire peut demander une remise manuelle. Le paquet à copier
   est affiché et tracé dans les registres M7; il ne déclenche aucun appel de plateforme, publication
   ou programmation automatique. Un retrait du consentement entre l'affichage et l'export bloque la
   remise.

## API

- `GET /api/marketing/calendrier?decalage=0` : page canonique de contenus, pagination et état des
  créneaux.
- `POST /api/marketing/calendrier` : objet JSON CSRF-protégé avec un `mutation_id`, `action` et les
  seuls champs exacts de l'action. Les actions sont `proposer_contenus`, `decider_contenu`,
  `proposer_creneau`, `decider_creneau` et `exporter_creneau`.

Les décisions prennent `decision=approuver|rejeter`; le rejet peut porter un motif. `planifie_le`
doit inclure le fuseau. Les dates passées, trop lointaines et les décalages de pagination invalides
sont refusés. La portée d'idempotence utilise l'identifiant réel de l'utilisateur console.

Une réponse métier refusée demeure un refus dans l'API et dans l'interface, même si l'appel transport
ou la décision N3 a été accepté par la couche d'approbation. Les historiques d'approbation peuvent
donc contenir `echec` quand le service M7 a refusé l'opération.
