# M7.8 — audit et proposition de chaîne ROI canonique

**État actuel, 30 septembre 2026 :** la première tranche décrite dans le
[plan de performance campagne](M7-ROI-CANONIQUE-PLAN.md) est implémentée localement. M2 publie
ses champs d'attribution minimisés; M7 joint les faits M2/M3/M5 et la console affiche couverture,
exclusions et marge constatée. Dépenses publicitaires et ROI numérique restent inconnus.
Les [preuves R18](../../research/R18-2026-09-30/README.md) conservent les validations de cette tranche.

**Audit initial conservé ci-dessous :** inspection et conception avant cette implémentation;
les formulations « actuel », « proposé » et « à arbitrer » des sections suivantes décrivent cet
état initial. L'arbitrage de la tranche minimale a depuis été effectué par le responsable du projet.
Référence métier : [Définition produit §6–7](../../produit/DEFINITION-PRODUIT.md#6-le-système-en-mouvement),
M7.8 « marketing → leads → ventes → profit ». Données privées exclues de ce rapport.

## Existant et autorité des données

| Domaine | Source/fonctions actuelles | Faits disponibles | Manques pour M7.8 |
|---|---|---|---|
| M7 ROI | [`outils.calculer_roi`](../../../departments/m07-marketing/src/m7_marketing/outils.py) orchestre `attribution_engine.attribuer`, `ads.intelligence.generate_report` et `roi_engine.consolider_roi`. | Comptes de visites/leads fictifs, premières/dernières touches, dépenses et mesures ads fictives, mapping `utm_campaign`/fenêtre/plateforme, CPL. | Aucune vente ni marge M5; aucun fait CRM de production; la fonction charge par défaut des fichiers `fictif: true`. Le nom « ROI » dépasse le résultat livré. |
| Attribution M7 | [`attribution_engine.py`](../../../departments/m07-marketing/src/m7_marketing/attribution/attribution_engine.py) joint les visites au lead par `visitor_id`, date et fenêtre, puis agrège `utm_source`/`utm_campaign`. | `lead_id`, date, source déclarée et visites UTM dans les fixtures. | Ces identifiants visiteurs/leads ne viennent pas des registres de production; UTM absent ou visite hors fenêtre devient non attribuable. |
| Dépenses ads M7 | [`ads_loader.load_fixture`](../../../departments/m07-marketing/src/m7_marketing/ads/ads_loader.py) refuse explicitement toute fixture sans `fictif: true`; `intelligence.generate_report` calcule CTR/CPC/CPA en `float`. | Champs campagne, fenêtre, budget, coût, impressions, clics, conversions de démonstration. | Pas de connecteur ni registre de dépenses réelles dans la chaîne actuelle. Les nombres présents ne peuvent pas alimenter un ROI d'entreprise. |
| Source du lead M2 | [`contrats.py`](../../../departments/m02-revenue-crm/src/m2_revenue_crm/contrats.py) accepte `source`, `campagne`, `utm` optionnels; [`clients.vue_360`](../../../departments/m02-revenue-crm/src/m2_revenue_crm/clients.py) les restitue depuis le contrat du lead. `m2.client_associe` porte actuellement `lead_id`, `client_id` opaque et horodatage. | Lead et rattachement client; champs d'attribution validés s'ils sont fournis. M2 sait lier lead↔client. | Les champs d'attribution restent facultatifs. L'événement d'association ne les transporte pas encore; `source` manquante n'est pas un zéro/une source organique. |
| Vente M3 | L'événement [`m3.devis_accepte`](../../../src/opsys/evenements/catalogue/m3.devis_accepte.json) relie `devis_id` à `lead_id` et `chantier_id`; M8 a déjà `entonnoir.fait_devis_accepte`. | Devis accepté et lead d'origine, prix total côté M3. | Devis accepté n'est ni facture finale, encaissement ni profit. Aucun indicateur de vente ne doit remplacer la marge réelle M5. |
| Marge M5 | [`outils._etat_chantier` / `lire_rentabilite_chantier`](../../../departments/m05-financecore/src/m5_financecore/outils.py), `cout_reel.calculer_rentabilite` et événement [`m5.rentabilite_chantier`](../../../src/opsys/evenements/catalogue/m5.rentabilite_chantier.json). | Jointure M5 par `devis_id`/`wct_id`; marge réelle CAD = prix facturé avant taxes moins coût réel complet; `CALCULEE`/`PARTIELLE`, codes de manque, séquence/version. L'événement ne contient pas de PII ni de lignes détaillées. | L'événement n'a pas `lead_id`, `facture_id`, statut facture ni date de paiement. Le calcul « facture connue » ne prouve pas un encaissement; la sélection de statut définitif doit être clarifiée avant d'appeler le résultat profit encaissé. |
| Observation M8 | [`contenus.py`](../../../departments/m08-analytics/src/m8_analytics/contenus.py) joint export M7→lead M1 sur `utm_content`, puis devis M3 sur `lead_id`. [`mesures_chantier.py`](../../../departments/m08-analytics/src/m8_analytics/mesures_chantier.py) reprend la marge M5 par `wct_id` et refuse une marge si le coût est partiel. | Bonne discipline locale d'événements idempotents, de minimisation PII, de provenance et de valeurs `non_calculable`. | Ces deux chaînes M8 restent des métriques distinctes; elles ne constituent pas un ROI campagne→affaire→marge et M8 ne doit pas devenir une deuxième autorité financière. |

## Jointures et limites observées

- Chaîne cible: identifiant de campagne UTM validé M2 → `lead_id` → `devis_id` M3 → `wct_id` et marge M5. M2 porte déjà l'attribution déclarée; M3 porte le lien lead/devis; M5 est l'unique autorité du coût réel et de la marge.
- L'événement M2 actuel ne publie pas ses champs UTM; M5 publie la marge sans `lead_id`. M7 ne peut donc pas faire cette jointure en production aujourd'hui sans deux compléments d'événement minimaux et autorisés.
- `roi-mapping.v1.yaml` relie des UTM à une fenêtre/plateforme, pas une campagne précise aux lignes de coût ads. `roi_engine.consolider_roi` additionne les campagnes d'une plateforme/fenêtre: plusieurs UTM partageant ce couple peuvent recevoir le même coût; le mapping n'établit pas une répartition financière.
- L'agrégation actuelle ne définit pas cohortes de lead, retard de conversion, annulations/remboursements, partage d'un lead sur plusieurs devis, ni choix entre première et dernière touche. Un même job ne doit pas être compté plusieurs fois au fil des versions de rentabilité M5.
- `m7_calculer_roi` accepte des chemins de fichiers (dont CRM/ads), utilise des `float` et n'annonce pas `roles_appareil`; un futur outil qui porte coûts/marges doit avoir une autorisation admin/coûts explicite et une entrée issue des contrats/events autorisés, jamais un chemin fourni par l'appelant.

## Réutilisation et licences

La tranche doit réutiliser les contrats et calculs Python locaux de M2, M3, M5 et les patrons idempotents/provenance de M8; aucun calcul M5 ne sera recopié dans M7. Aucun nouveau paquet ROI n'est justifié. La [recherche R16 M7](../../research/R16-2026-09-30/recherche-m7.md#ce-que-le-code-prouve-déjà) recommande attribution native et marge exclusivement de M5; Matomo/Umami sont des sources web optionnelles, pas des ponts vers les ventes. PyMC-Marketing/Meridian sont différés jusqu'à un historique et une question causale adaptés. Pas de code tiers ou nouvelle licence à importer dans ce lot.

## Tranche minimale proposée à arbitrer

1. Remplacer le chemin fixture du calcul métier par une lecture asynchrone idempotente de faits autorisés: source/UTM M2 minimisés, `devis_id`/`lead_id` M3, rentabilité M5. Garder l'identifiant de jointure seulement dans le registre analytique privé M7; ne conserver ni contact, ville, ligne de facture ni détail de coût.
2. Étendre le contrat `m2.client_associe` avec les seuls champs d'attribution optionnels déjà validés (`source`, `campagne`, `utm`) ou définir un événement M2 équivalent minimisé. Étendre M5 seulement si le contrat retenu exige le statut définitif de facture; pas d'accès direct aux tables privées d'un autre département.
3. Tant qu'une source de dépense réelle campagne, son CAD, sa période et sa couverture ne sont pas disponibles, rendre ROI `null` avec manque explicite. Le chargeur ads fictif reste étiqueté simulation; aucune API publicitaire ou dépense n'est simulée.
4. Une fois dépense et politique d'attribution arbitrées, M7 compose les totaux par campagne/cohorte. Les mesures intermédiaires restent distinctes (leads, devis acceptés, marge M5, dépense); ne pas présenter revenu/devis accepté comme profit. Le ratio proposé `(marge réelle M5 attribuée − dépense marketing complète) / dépense marketing complète` exige une décision explicite M5/M7 sur statut facture, cohortes, attribution, annulations et la définition « complète » de dépense. Dénominateur absent ou nul: ratio `null`.

## Contrat de sortie et tests à exiger

- Montants calculés avec `Decimal`, sérialisés en chaînes décimales CAD, jamais en `float`; champs monétaires ou ROI non calculables = `null`. Chaque mesure porte formule, période/cohorte, date d'observation, sources (événement, identifiant opaque, séquence/version) et manque nommé.
- `couverture` porte au minimum `PARTIELLE` ou `INCONNUE`; pas d'état « complète » sans preuve de couverture de chaque source. Une somme de marges connues ne devient pas le total des affaires lorsque d'autres marges manquent.
- Tests négatifs: UTM/source absente/ambiguë, dépense fictive ou sans devise/période, devis sans lead, M5 PARTIELLE, plusieurs WCT/version/out-of-order, facture non définitive, source incomplète et dénominateur zéro → nul/manque/couverture partielle, jamais ROI zéro.
- Tests positifs: une jointure exacte lead→devis→WCT, une seule marge M5 complète et un coût campagne complet dans la même cohorte donnent un ratio déterministe; deux sources UTM ne se partagent pas silencieusement une dépense; événement relivré ou séquence ancienne ne double-compte pas.
- Accès: admin avec permission coûts seulement; refus avant lecture sinon. Pas de PII dans les charges M7, rapports M8, outils ou traces. Mode `ombre` reste en lecture; décisions de budget/publication restent soumises à approbation humaine.

**Limite de cet audit :** cette proposition identifie les contrats manquants, mais ne prétend pas que M2/M3/M5 ont déjà des intégrations réseau en production, que les dépenses ads sont réelles, ni qu'une causalité marketing est démontrée. Arbitrage demandé au responsable avant toute tranche de code.
