# M6 — contexte et prévu du WCT : contrat préparatoire r1

Complément prioritaire à `M6-13-PREUVES-CONCEPTION-PREPARATOIRE-r1.md`, dont le reçu r1 est conservé. Décisions ROOT du2026-10-08 intégrées. Conception seule, avant allocation backend et après publication/qualification du correctif ACK. Référence publiée indiquée par ROOT : `34095c35` ; aucun HEAD Git relu par cet agent. Les sources ciblées lues restent attestées séparément par SHA. Pendant cette étude, ROOT a intégré les deux sources mobiles candidates ACK : leur lecture actuelle est attestée, sans assimiler cette observation à une qualification ou publication ACK.

## Lot retenu

Une seule nouvelle capacité DEVICE `m6_lire_contexte_materiaux_appareil` : T0/N0, employee/admin, lecture pure du contexte nécessaire au formulaire. Elle réutilise l’admission M4, le WCT publié, `besoins_prevus.pour_devis` et `acces.chantier_attendu`. Elle ne déclare aucun usage, ne réserve, ne réévalue, n’écrit pas, ne lit pas les fichiers CAS et ne propose ni motif ni photo. Le wrapper preuves vient **après** ce lot complet.

L’UI peut afficher le prévu et charger explicitement des lignes de saisie dont la **quantité réelle reste vide**. Aucune quantité réellement utilisée n’est copiée depuis l’estimation. Le prévu absent, le prévu connu vide et la ligne prévue présente sont trois cas distincts.

## Entrées exactes et admission

Objet fermé, quatre champs requis :

```text
{ intervention_id: string, wct_id: string, decalage: integer, limite: integer }
```

IDs publics non vides, verbatim, ≤256codepoints, sans Cc/Cs et non vides selon le prédicat Python strip ; pas de trim/réécriture. `decalage` entier strict0..10000, `limite` entier strict1..8 ; bool/null/flottants refusés. Aucun argument technicien/personne/rôle/agent/devis/chantier/prix ou configuration. Les valeurs0/8 des constructeurs mobiles n’assouplissent pas les champs required du schéma.

Ordre obligatoire, dans une transaction :

1. Identité DEVICE présente, personne active et rôle employee/admin actuel confirmés en base ; les métadonnées d’appairage seules ne suffisent pas. Pas de voie agents/console pour cette nouvelle façade.
2. Employee : admission **de l’intervention demandée** depuis M4 avant bus/prévuM6/config. Inconnue, non assignée ou assignée à autrui donnent le même refus sans données ni compte de prévu. Pour un WCT complété, vérifier le technicien individuel courant de l’assignation/départ ; ne pas charger un profil d’équipe ni inventer un droit par un argument. Admin actif accède au contexte autorisé sans exposer une identité employee.
3. Seulement après admission, lookup du WCT publié M4 sous `evenement_id=wct_id`, vrai producteur/catalogue. Son intervention doit être exactement `intervention_id`. Pour employee, technicien WCT = personne authentifiée, comme `m6.acces.controler_declarant` ; pas de transfert implicite de droits si l’assignation courante a changé. Vérifier aussi la complétion courante et les références/chaînes M4 requises.
4. Lire le seul prévu du devis du WCT, par `besoins_prevus.pour_devis`. La sélection actuelle gagne : premier définitif, sinon provisoire de rangM3 le plus récent. Ne pas choisir une version M3 par date ni remplacer un définitif par un provisoire « plus frais ».
5. Calculer **uniquement** la cible suivant `acces.chantier_attendu` : chantier non nul du prévu ; sinon intervention pour employee ; sinon null pour admin. Origine explicitée, aucun ID dérivé d’un lead/libellé/route ou « corrigé » silencieusement.

**Mesure honnête de la garde :** avec seul WCT, l’assignation nécessiterait une lecture préalable du bus ; d’où les deux IDs requis. La vérification d’assignation nécessite elle-même la source M4. Le lookup M4 d’autorisation et les lectures SQL d’identité sont instrumentés séparément des sources métier de contexte. Refus de rôle actuel =>0admissionM4/bus/prévu/config ; refus d’assignation =>lookupM4 d’autorisation permis mais0busWCT/prévuM6/config. Aucun « zéro de toute lecture » fictif. L’adaptateur d’admission doit rester dans la convention M4 et revérifier ses sources natives, pas dupliquer une table de permission ou créer un ticket d’autorité.

## Réponse DIRECTE fermée

Les lignes ci-dessous définissent des types, **pas un DTO de fixture ni une réponse capturée**. Toutes les clés montrées sont requises, sauf aucun champ optionnel implicite ; clés étrangères refusées par les deux lecteurs.

```text
{
  wct: {
    wct_id: string, intervention_id: string, devis_id: string|null,
    horodatage_completion: ISO_date_avec_secondes_et_timezone,
    hash_maillon: hex64,
    reference_bus: {type: "m4.travaux_termines", evenement_id: string}
  },
  chantier: {
    chantier_id: string|null,
    origine: "prevu_m6"|"intervention_employee"|"absent_admin"
  },
  prevu: {
    statut: "absent"|"definitif"|"provisoire_estimation_m3",
    source: null|{
      registre: "besoins_prevus", rang: integer,
      empreinte_snapshot: hex64,
      estimation_id: hex64|null, rang_m3: integer|null,
      bareme_version: string|null,
      horodatage: ISO_date_avec_secondes_et_timezone|null,
      reference_m3: null|{
        type: "m3.besoins_materiaux"|"m3.devis_accepte",
        evenement_id: string
      }
    }
  },
  lignes: [{
    position_source: integer,
    materiau_id: string, unite: string,
    quantite_estimee: texte_decimal_positif,
    origine_quantite: "texte_m3_verifie"|"nombre_m6_persiste"
  }],
  pagination: {
    decalage: integer, limite: integer, affichees: integer,
    total: integer, suivant: integer|null, reste: integer, courante: true
  },
  manques: ["devis_absent"|"prevu_absent"|"chantier_source_absent"|
            "horodatage_prevu_absent"|"provenance_m3_absente"],
  couverture: {
    objet: "contexte_et_prevu_du_wct",
    quantite_reelle: "non_renseignee",
    pages: "courantes", plafond_lignes: 10000
  },
  borne_caracteres: 5400, taille_caracteres: integer
}
```

Enveloppe vraie à qualifier : `{ok:true,resultat:DTO}` dans la réponse Gateway complète. Refus nominal fermé proposé `{ok:true,resultat:{accepte:false,verdict:{code,detail}}}` ; refus Cap réel `{ok:false,erreur:code,details:texte_constant}`. Préfixe de verdict proposé `REJ-M6-CONTEXTE-` ; suffixes fermés `ARGUMENTS-INVALIDES`, `IDENTITE-INVALIDE`, `INTERVENTION-NON-ASSIGNEE`, `WCT-INCONNU`, `LIAISON-INCOHERENTE`, `SOURCE-INVALIDE`, `BORNE-SOURCES`, `SORTIE-TROP-VOLUMINEUSE`. Aucun détail raw, nom d’employee, coût ou contenu de registre dans un refus. Status HTTP réel à capturer ; ne pas assimiler tous ces refus métier à403.

Invariants du DTO : IDs liés exactement aux deux arguments ; `reference_bus.evenement_id=wct_id` ; `source=null` iff prévu absent ; absent=>lignes[]/total0 et manque `prevu_absent` ; définitif/provisoire peuvent avoir lignes[]/total0 sans prétendre absence. Cible `prevu_m6` non nulle provenant du prévu ; repli employee = intervention ; admin sans cible source=>null et manque `chantier_source_absent`. Aucun champ technicien/personne/GPS/contact/photo/prix/coût/marge. Position réelle dans la liste source, ordre source conservé, pas de tri par quantité/libellé.

## Provenance et précision

- Rang de `source` = rang durable0-based de **le maillon sélectionné** dans `m06-material-control/besoins_prevus`, pas rang après filtre. Ce registre n’a pas de hash de chaîne natif : `empreinte_snapshot` est l’empreinte SHA256 de contenu copiée et canonique, explicitement un snapshot, jamais un historique inventé.
- `estimation_id`, `rang_m3`, `bareme_version` existent sur le provisoire M3 reçu et restent null quand la source ne les porte pas. Ne pas reprendre ces valeurs d’un provisoire écarté pour enrichir artificiellement un définitif.
- `reference_m3` n’est projetée qu’après rapprochement réel et non ambigu du maillon sélectionné avec l’événement/producteur/catalogue M3. Son ID est relu, jamais recomposé depuis une convention. Un définitif M6 manuel est légitime : provenanceM3absente annoncée. Une source M3 liée mais malformée/incohérente refuse ; ne pas la remplacer par une ancienne version.
- Le registre de prévu ne conserve pas d’horodatage. `source.horodatage` reste null/manque déclaré, sauf source M3 rapprochée portant réellement une date pertinente (`m3.devis_accepte.horodatage_acceptation`). `m3.besoins_materiaux` ne porte aucune date ; ni date de completion WCT, ni heure de lecture, ni date récente d’un autre événement ne sert de date du prévu.
- `m3.besoins_materiaux` conserve des quantités nettes en texte et, séparément, facteur-perte éventuel. `m6.besoins_materiaux_recus.lignes_prevues` et le récepteur du devis accepté les convertissent en float ; les détails M3 originaux sont conservés seulement pour le provisoire. Utiliser le texte original M3 seulement si les identités/unités/quantités de la source choisie concordent ; sinon restituer la représentation décimale finie du nombre M6 réellement persisté avec `origine_quantite=nombre_m6_persiste`. Ne pas annoncer alors une précision originale M3. Aucun facteur-perte appliqué, aucune conversion d’unité, prix ou calcul stock.
- Texte positif ASCII, fini ; texteM3 validé selon son vrai catalogue/validateur et conservé verbatim (ses zéros éventuels ne sont pas réécrits). La représentation M6 résulte du nombre persisté, sans exposant dans ce DTO. Pas de limiteJSsafe sur ces textes de lecture. Une conversion mobile vers l’actuel writer number ne peut pas perdre silencieusement de précision : estimation lisible mais non préremplissable à signaler si ce passage est impossible ; quantité réelle reste vide.
- Hash WCT = le vrai `hash_maillon` de M4, pas hash d’une projection ; contrôlé contre la complétion source. RangM3 hors domaine entier représentable, date incompatible, texte/ID hors projection fermée ou source/copie corrompue =>refus nominal, pas omission silencieuse.

## Borne, pureté et transport

Pages courantes sur les lignes du seul prévu sélectionné. Copier et valider les snapshots nécessaires puis plafond10000lignes ; cette limite n’est pas une garantie d’allocation initiale. Les compteurs globaux ou d’autres interventions ne sont pas exposés à employee. `total` compte seulement les lignes visibles de cette cible. Décalage au-delà du total légal=>page vide ; suivante exacte ; nouvelle version/source modifiée remplace la page courante, pas de snapshot figé.

DIRECT **entière**≤5400codepoints Python de l’enveloppe `{ok:true,resultat:DTO}`, point fixe pour `taille_caracteres`. Réduire la page en retirant ses dernières lignes si nécessaire ; un premier élément/métadonnées seuls trop grands refusent sans partiel. Ajouter ce nom exact à la garde Cap réelle des lectures M6 (limite800/6000) avant fallback ARTEFACTS. Jamais COUPLE/artifact, troncature silencieuse ou génération de fichier pour une lecture de contexte.

Chaque lecture réussie/refusée du producteur est sans mutation de tables business ; qualifier toutes les tables entières avant/après et protocole HTTP/metadata distinct. Restart backend=>même corps exact tant que sources inchangées. Aucun paiement/provider/commande/consolidation/canal client.

## UI, focus et brouillon hors ligne

Lecture en ligne à l’entrée autorisée, mêmes protections focus/session/rôle/réseau que Stock et lecteurs récents. Aucun nouveau cache de contexte. Hors ligne, un ancien contexte n’est pas considéré autorisé ou courant ; afficher indisponibilité et **conserver le brouillon local** de son propriétaire. Pas d’effacement des notes/lignes/photos après timeout, échec de préfill ou changement réseau.

« Charger le prévu » est une action explicite unique sur la cible/session confirmée. Appliquer la page à un nouveau jeu de lignes, quantité réelle vide, estimation affichée séparément. Ne jamais réécrire des lignes saisies pendant la requête, lors d’un retry, retour réseau, reprise outbox ou refocus. Capturer génération de requête+cible+propriétaire ; une réponse arrivée après navigation/changement de session ou modification du brouillon est ignorée pour l’application du préfill. Changement de propriétaire masque/quarantine ses brouillons, sans les envoyer sous une autre personne ni les supprimer.

La pagination remplace la vue du prévu ; l’utilisateur confirme explicitement les lignes à importer. Un changement de source entre pages est affiché par la provenance et impose une nouvelle lecture/confirmation, pas un mélange silencieux. La soumission existante revalide cible et WCT ; un conflit de cible ne rebascule pas le brouillon sur le nouvel ID.

## Surfaces à allouer après ACK et critères

Backend : nouveau module pur M6 contexte/préfill, adaptateur `m6_material_control/outils.py`, seam d’admission M4 ciblée si aucun helper réutilisable public ne suffit, tests producteurs/admission/liaison/borne/restart ; jeux/pins `test_portees_appareil.py`, `ROLES.md`, conformité et doc outil. Garder writers stock/prévu/M4, contrats de déclaration, CAS, Core et locks inchangés.

ROOT : nom exact dans Cap+tests anti-artefact ; services/UI/i18n de l’écran matériaux et hooks focus/session. Types : modèle et lecteur purs, fixtures provenant du producteur réel, assertions d’arguments/DTO/enveloppe fermés. Aucune fixture HTTP inventée. Outbox : uniquement usage de l’ACK déjà clos ; ce lot T0 n’ajoute aucune mutation ni vidange en arrière-plan.

Négatifs requis : identité inconnue/inactive/role retiré avant sources ; employee étranger/inconnu avec même refus et0bus/prévu/config ; admissionM4 séparément mesurée ; WCT/intervention divergents, technicien changé, WCTcorrompu/non publié/faux producteur ; M3devis≠WCT, prévuabsent/vide/provisoire/définitif, version périmée et définitifprioritaire ; horodatageabsent/corrompu ; quantités nonfinies, bool, unité absente/doublons, grands textes exacts et conversion impossible ; copie corrompue/exception sans raw ; argsfermés/forgés/null/bornes ; pages première/suivante/hors total/remplacement ; DIRECT5400/Cap800/10001 sans artefact ; tables/restart réels ; UI réponse tardive après saisie/navigation/logout, réseau perdu, owner changé et brouillon intact.

Ordre : ACKpublié+interopréelle → rouges admission/cible/préfill → producteur/DTO SQL réels → lecteur pur+UI explicitpréfill → Native DEVICE sur affaireM3/M4 dont chantier≠intervention → contrôles intégrés/CI exacte. Seulement ensuite preuves PERTE/BRIS et transport photos. Repli légitime sans prévu et absence de coût sont des comportements à livrer, pas des blocages à masquer.

## Réemploi et licences

Sources internes OPSYS-AI sous Apache2.0 (`LICENSE`) ; Core hérité MIT (`core/LICENSE`), aucune production Core à changer. SQLAlchemy, SQLite et pipelines CAS/outbox/photo déjà dépendances installées ; aucun nouvel ingrédient, SDK, provider, recherche d’outil externe ou installation nécessaire. Ce constat ne revendique pas une revue de licences nouvelle de toutes les dépendances ni une qualification téléphone/Hermes/ExpoSQLite. SHA des sources et licences lues dans le reçu distinct.
