# M7 — plan d’interface de performance campagne

**Portée :** première tranche de M7.8, sans calcul de ROI numérique ni branchement de dépenses.
Elle produit des comptes observés, une marge observée par M5 et des lacunes de couverture.

## Sources et responsabilités

- Le consommateur M7 lit le bus canonique puis inscrit ses faits minimisés dans les maillons M7.
- M2 `m2.client_associe` transporte `lead_id`, `source`, `campagne` et `utm_campaign` uniquement si
  présents et déjà validés par le contrat M2. Aucun nom, adresse, téléphone, courriel ou texte libre.
- M3 `m3.devis_accepte` fournit le lien `lead_id` → `devis_id`/`chantier_id`.
- M5 `m5.rentabilite_chantier` reste l’autorité de marge. M7 lit l’événement, jamais les tables M5,
  et n’en recalcule aucun montant. Le plus grand `sequence` d’un devis est courant, même si le WCT change.
- M5 peut précéder M3 ou M2 sur le bus : les registres sont idempotents par type d’événement et les
  jointures sont résolues à la lecture après réception; un rejeu identique n’ajoute pas de maillon.
- Le `chantier_id` M3 doit correspondre au `chantier_id` M5 avant de compter une marge; contradiction
  nommée, marge exclue.
- Conflit de payload pour un même identifiant métier/sequence: échec fermé avec anomalie nommée;
  doublon identique et séquence ancienne: sans effet sur les comptes.

## Interfaces Python prévues

Dans `m7_marketing.performance_campagnes` :

```python
enregistrer_fait(type_evenement: str, charge: dict[str, Any]) -> dict[str, Any]
construire_performance(faits: Sequence[dict[str, Any]], debut: date, fin: date) -> dict[str, Any]
```

`enregistrer_fait` valide et minimise les trois contrats consommés; il est idempotent sur les faits
identiques et refuse un conflit au lieu de remplacer un fait à séquence égale (séquence M5 par devis). Les handlers nommés
du bus dans `outils.consommateurs()` le délèguent à cette fonction. La fonction de lecture
`outils.lire_performance_campagnes(debut, fin)` suit la politique M5 de lecture des coûts : un
`admin` actif confirmé (appareil ou console), ou `nathan_owner` actif confirmé à la console. Elle
refuse une identité périmée/révoquée avant toute lecture et les agents sans autorisation serveur;
les arguments ne choisissent jamais l’acteur ni le rôle. Aucun nouveau nom de permission sans
registre d’octroi/révocation.

Le registre privé M7 `performance_campagnes` ne conserve que les identifiants opaques nécessaires
aux jointures et la charge canonique minimisée, avec références d’événements et version M5. Il n’est
pas exposé comme table ni accessible depuis un outil d’écriture d’agent.

## Forme de sortie de lecture

```json
{
  "type": "PERFORMANCE_CAMPAGNES",
  "periode": {"debut": "YYYY-MM-DD", "fin": "YYYY-MM-DD"},
  "couverture": "PARTIELLE",
  "manque": ["DEPENSES_NON_BRANCHEES", "COUVERTURE_SOURCES_NON_PROUVEE"],
  "source_refs": [{"type": "m2.client_associe", "reference": "lead_id_opaque"}],
  "campagnes": [{
    "source": "google", "campagne": "printemps",
    "leads_associes_observes": 2, "devis_acceptes": 1,
    "chantiers_marge_constatee": 1, "marge_constatee_M5_cad": "1250.00",
    "statut_financier": "INCONNU",
    "couverture": "PARTIELLE", "manque": ["DEPENSES_NON_BRANCHEES"],
    "cout_ads_cad": null, "cout_par_lead_cad": null, "roi": null,
    "source_refs": [{"type": "m5.rentabilite_chantier", "reference": "evenement_id_opaque", "sequence": 2}]
  }]
}
```

La période est la cohorte inclusive des associations `m2.client_associe`, après conversion des
horodatages RFC 3339 vers UTC; un horodatage naïf est refusé. Les devis et marges canoniques reliés
à cette cohorte sont observés jusqu’à `fin`. Les événements postérieurs à `fin`,
les leads associés hors cohorte, les liens manquants et les conflits sont exclus et nommés dans
`exclusions`/`manque`; ils ne deviennent pas des zéros. « Leads associés observés » ne signifie pas
nouveaux leads acquis. Les références sont les identifiants opaques présents dans les contrats
(lead/devis ou `evenement_id` M5). Agrégats monétaires en `Decimal`, sérialisés en chaînes CAD;
champs indémontrables nuls. L’attribution vient de l’UTM canonique validé du lead, jamais d’une
inférence visiteur. Attribution absente/incohérente reste inconnue.
Une marge M5 calculée est une marge constatée selon M5, pas une preuve d’encaissement ni un profit
final. Aucun état de facture/encaissement n’est inventé. `cout_ads_cad`, `cout_par_lead_cad` et `roi`
restent toujours `null` dans cette tranche.

## Compatibilité, droits et tests

`m7_calculer_roi` garde sa signature et sa forme de retour; sa description et son libellé précisent
qu’il s’agit d’une démonstration fictive. Le nouvel outil est en lecture seule et réservé à un
admin confirmé par appareil ou console, ou au propriétaire actif confirmé à la console; la politique
de lecture des coûts suit la règle M5. Un agent M7 sans autorisation serveur n’accède pas au registre.

Les tests rouges puis verts couvrent : schéma/sortie avec coûts et ROI nuls, période UTC et refus
d’horodatage naïf, source_refs, attribution explicite/inconnue/ambiguë, marge M5 `Decimal`, devis
sans observation de marge, statut d’encaissement inconnu, livraison durable M5→M3→M2 avec rejeu,
séquence M5 hors ordre sans double compte, conflits de clé, incohérence `chantier_id` M3/M5,
exclusions de cohorte nommées, refus d’accès avant lecture et révocation admin en base. Le test M2
vérifie l’événement UTM minimisé sans medium/content ni PII.
