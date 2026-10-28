# Pertes et alertes du WCT — lecture appareil M6

Deux outils T0/N0, réservés à une identité DEVICE active dont le rôle `admin` est
revérifié dans la transaction avant les sources :

- `m6_lister_wct_pertes_appareil(decalage, limite)` sélectionne les WCT reçus par
  M6 et rapprochés de leur publication réelle `m4.travaux_termines` par ID,
  producteur M4, charge validée au catalogue et empreinte complète reçue.
- `m6_lire_pertes_alertes_wct_appareil(wct_id, decalage, limite)` relit les
  mouvements PERTE/BRIS du WCT exact et les cinq statuts publiables M6 de variance.

Les entrées sont fermées et toutes requises dans le schéma. `limite` est un entier
strict de 1 à 8 ; `decalage`, un entier strict de 0 à 10000. Les identifiants métier
sont conservés verbatim : au plus 256 points de code, sans caractères Cc/Cs et non
vides selon le prédicat Python `strip`. Aucun trim ni NFC ne réécrit un ID ; U+FEFF
est donc admissible et conservé. La seule référence de publication de variance
admet 300 points de code et doit être exactement l'ID canonique
`m6-variance-<wct_id>-<statut>` lu dans la source.

Une référence de reçu expose son rang durable, réellement lu dans le stockage,
et l'empreinte complète déjà conservée ; elle n'invente aucun hash de reçu. Un
reçu ancien sans empreinte est refusé explicitement. Une référence de mouvement
expose l'index et le hash du maillon réel, après validation intégrale de la chaîne.
Les quantités sont finies, strictement négatives pour PERTE/BRIS, et projetées en
texte décimal canonique sans conversion ni arrondi. L'unité déclarée est exposée lorsqu'elle est conservée dans le maillon hash-chaîné ;
elle reste `null` pour un ancien maillon sans unité. La date du mouvement reste `null`. Le coût n'est
jamais projeté ni calculé ; `null` reste un coût inconnu légitime, alors qu'un type
incohérent ou un nombre non fini rend le snapshot invalide.

`declaration_presente` signifie qu'au moins un mouvement CONSOMMATION, RETOUR,
PERTE ou BRIS est effectivement lié au WCT. L'absence de mouvement ne prouve pas
l'absence d'un formulaire humain vide. Une publication `evaluee` sans un tel
mouvement est incohérente et refusée. RECEPTION et VARIANCE_INVENTAIRE ne constituent
pas une déclaration de ce WCT. Les chantiers connus dans les mouvements et les
publications doivent concorder.

L'historique comporte exactement cinq slots, dans l'ordre fixe `seuil_absent`,
`prevu_absent`, `declaration_absente`, `evaluee`, `unites_indeterminees`. Cet ordre n'est pas une chronologie.
Chaque slot présent contient la référence réellement relue du bus M6, son signal,
son seuil et sa date de complétion du WCT ; la date de publication reste `null`.
`evaluee_terminal` rapporte seulement la présence du slot `evaluee`. Les signaux
publiés sont relus, jamais réévalués ni attribués à une personne.
Le seuil numérique est conservé verbatim : un entier au-delà de
`Number.MAX_SAFE_INTEGER` est refusé nominalement comme source invalide, même s'il
est fini en Python. Les seuils entiers sûrs et les valeurs fractionnaires finies
restent admissibles ; le writer et le calcul de variance ne sont pas changés.

La liste suit les rangs reçus décroissants ; les pertes/bris suivent les indices
croissants. La pagination est courante, sans snapshot figé ; un décalage au-delà
du total donne une page vide. Les trois snapshots sont copiés avant la borne
combinée de 10000 lignes : cette borne de traitement n'est pas une limite initiale
d'allocation. L'enveloppe DIRECTE entière `{ok: true, resultat: ...}` est limitée à
5400 points de code JSON, caractères Unicode conservés. `taille_caracteres` est mesuré au point
fixe sur cette enveloppe entière. Une page peut renvoyer moins de lignes que
`limite`, avec `suivant` exact ; un noyau fixe ou une seule ligne trop volumineuse
produit un refus nommé sans détail partiel. La garde du socle applique aussi sa
limite effective avant tout repli en artefact.

Un WCT publié par M4 mais non reçu par M6 est distinct d'un WCT inconnu. Les sources
requises absentes, corrompues ou incohérentes produisent un verdict nominal générique,
sans contenu brut. Rien n'est écrit, commandé ou ajusté. Stock courant, inventaire
physique, réapprovisionnement, coûts, responsables, photos, unités historiques non documentées et dates
de perte/bris restent explicitement hors corpus.
