/**
 * Textes du profil admin (PLAN T4.20) : l'accueil « À voir », l'écran « Chiffres » et l'écran « Chantiers du jour ».
 * fr-CA est la langue de référence : `RessourcesAdmin` en est la forme, et `admin.en-CA.ts` doit la reprendre clé pour
 * clé (un champ oublié est une erreur TypeScript, jamais un texte manquant à l'exécution). Un test
 * (`src/admin/traductions.test.ts`) épingle les catalogues (statuts, volets, unités...) à ceux du serveur et exige les
 * mêmes variables dans les deux langues.
 *
 * Règle d'écriture : un texte qui décrit une DONNÉE dit toujours son absence en toutes lettres (« non calculable »,
 * « à configurer », « non connu »), jamais un tiret ni un zéro. Ce que le serveur écrit lui-même n'est pas ici : l'app le
 * montre tel quel.
 */
const adminFrCA = {
  commun: {
    chargement: "Chargement…",
    sansSession: "Appareil non apparié ou identité non confirmée : impossible de lire pour l'instant.",
    rafraichir: "Rafraîchir",
    voirDetail: "Voir le détail",
    masquerDetail: "Masquer le détail",
    lueLe: "Lue le {{date}}",
    cache: "Hors ligne : données du cache, lues le {{date}}. Raison : {{code}}.",
    refus:
      "Le serveur ne donne pas cette section ({{code}}) : {{detail}} Aucune copie gardée n'est montrée à sa place.",
    aucune:
      "Impossible de lire cette section ({{code}}) : {{detail}} Aucune copie n'est gardée : rien n'est montré plutôt qu'une valeur inventée.",
    // Le détail du serveur cite un chemin ou une commande de son côté (ou n'existe pas) : il n'est pas montré, le code le dit.
    refusSansDetail:
      "Le serveur ne donne pas cette section ({{code}}). Aucune copie gardée n'est montrée à sa place.",
    aucuneSansDetail:
      "Impossible de lire cette section ({{code}}). Aucune copie n'est gardée : rien n'est montré plutôt qu'une valeur inventée.",
    inconnu: "{{valeur}} (inconnu de cette version de l'app)",
    manqueLigne: "{{code}} : {{detail}}",
  },
  aVoir: {
    titre: "À voir",
    aucuneDecision: "Cet accueil ne décide de rien : les décisions se prennent à l'écran des approbations.",
    rienAVoir: "Rien à voir : aucune demande en attente, et aucune attente signalée par les départements.",
    demandes: {
      titre: "Demandes en attente",
      total: "En attente : {{total}}",
      aucune: "Aucune demande en attente.",
      reste: "{{nombre}} autre(s) demande(s) non affichée(s) : à voir à l'écran des approbations.",
      illisibles: "{{nombre}} demande(s) illisible(s) pour cette version de l'app : à voir à la console.",
    },
    attentes: {
      titre: "Attentes des départements",
      aucune: "Aucune attente signalée par les départements.",
      inconnues:
        "Ce serveur ne donne pas les attentes des départements : on ne peut pas dire qu'il n'y en a aucune.",
      reste: "{{nombre}} autre(s) attente(s) non affichée(s) : « Voir plus » à l'écran des approbations.",
    },
    liens: {
      approbations: "Approbations : décider les demandes",
      chiffres: "Chiffres : trésorerie, prévision, échéances",
      chantiers: "Chantiers du jour",
    },
  },
  unites: {
    leads: "{{valeur}} lead(s)",
    devis: "{{valeur}} devis",
    pourcentage: "{{valeur}} %",
    jours: "{{valeur}} jour(s)",
    CAD: "{{valeur}}",
    autre: "{{valeur}} {{unite}}",
  },
  chiffres: {
    titre: "Chiffres",
    sections: {
      tresorerie: "Trésorerie et cash libre",
      prevision: "Prévision de trésorerie",
      echeances: "Échéances fiscales (TPS/TVQ)",
      vue: "Vue d'ensemble",
    },
    reserves: "Sous réserve : {{reserves}}",
    composantes: {
      solde: "Solde",
      taxes_a_remettre: "Taxes à remettre (TPS/TVQ)",
      paies: "Paies dues",
      das: "Déductions à la source (DAS)",
      comptes_a_payer: "Comptes à payer (fournisseurs)",
      dettes: "Dettes (versements exigibles)",
      reserves: "Réserves posées",
    },
    composante: {
      montant: "{{montant}}",
      nonCalculable: "Non calculable",
      plancher: "Au moins {{montant}} est certain.",
      source: "Source : {{source}}",
      dernierePiece: "Dernière pièce : {{date}}",
    },
    tresorerie: {
      solde: "Solde : {{montant}}",
      soldeInconnu: "Solde : non calculable. Aucun solde n'est connu ; rien n'est montré à sa place.",
      masque: "Montants non affichés pour votre rôle.",
      argentDisponible: "Argent disponible (solde moins les réserves posées) : {{montant}}",
    },
    cashLibre: {
      calcule: "Cash libre : {{montant}}",
      nonCalculable: "Cash libre : non calculable. Aucun chiffre n'est donné.",
      enDeficit: "En déficit : le cash libre est négatif.",
      auPlus: "Repère, pas de l'argent disponible : au plus {{montant}} (le solde moins ce qui est connu).",
      hypothesesOmises: "{{nombre}} hypothèse(s) retirée(s) de la réponse pour tenir dans la limite du serveur.",
      lectureTitre: "Lecture de M5",
      manqueTitre: "Ce qui manque",
      composantesTitre: "Détail : le solde et ce qui en est retranché",
      hypothesesTitre: "Hypothèses de M5",
      detailOmis: "M5 a retiré le détail des composantes pour tenir dans la limite de la réponse.",
    },
    alerte: {
      titre: "Alerte de seuil",
      statuts: {
        ALERTE: "Alerte : le solde prévu passe sous le seuil",
        SEUIL_A_CONFIGURER: "Seuil à configurer : aucune alerte n'est évaluée",
        NON_EVALUEE: "Alerte non évaluée : la prévision n'est pas calculable jusque-là",
        AUCUNE: "Aucune alerte : le solde prévu reste au-dessus du seuil",
      },
      seuil: "Seuil d'alerte : {{montant}}",
      sourceDuSeuil: "Seuil déclaré par {{source}} le {{date}}.",
      semaines: "Semaines sous le seuil : {{semaines}}",
      nonEvaluee: "Alerte non évaluée à partir de la semaine {{semaine}} (prévision non calculable).",
    },
    prevision: {
      horizon: "Horizon : {{semaines}} semaine(s), du {{du}} au {{au}}.",
      horizonMasque: "Horizon : {{semaines}} semaine(s). Montants non affichés pour votre rôle.",
      nonCalculable:
        "Prévision non calculable à partir de la semaine {{semaine}} : aucun chiffre n'est donné pour ces semaines.",
      manque:
        "{{code}} (à partir de la semaine {{semaine}}, {{nombre}} pièce(s)) : {{detail}} Exemples : {{exemples}}.",
      plusBas: "Le plus bas : {{montant}} (semaine {{semaine}}).",
      premiereSemaineEnDeficit: "Première semaine en déficit : {{semaine}}.",
      soldeInitial: "Solde de départ : {{montant}}",
      soldeInitialInconnu: "Solde de départ : non connu.",
      soldeInitialSource: "Source du solde : {{source}}",
      soldeInitialSourceDatee: "Source du solde : {{source}} (dernière pièce : {{date}})",
      cashLibreAujourdhui: "Cash libre d'aujourd'hui : {{montant}}",
      cashLibreAujourdhuiNonCalculable: "Cash libre d'aujourd'hui : non calculable.",
      auDelaEntrees: "Au-delà de l'horizon : {{nombre}} entrée(s), {{montant}} ; {{nonChiffres}} non chiffrée(s).",
      auDelaSorties: "Au-delà de l'horizon : {{nombre}} sortie(s), {{montant}} ; {{nonChiffres}} non chiffrée(s).",
      encaissementNonCompte:
        "{{code}} : {{nombre}} encaissement(s) non compté(s), {{montant}} connu(s). Exemples : {{exemples}}.",
      limitesOmises: "{{nombre}} limite(s) retirée(s) de la réponse pour tenir dans la limite du serveur.",
      limitesTitre: "Ce que la prévision ne sait pas",
      semainesTitre: "Semaine par semaine",
      semaine: "Semaine {{semaine}} — du {{du}}",
      semaineNonCalculable: "Non calculable : aucun chiffre pour cette semaine (voir ce qui manque plus haut).",
      entrees: "Entrées : {{montant}}",
      sorties: "Sorties : {{montant}}",
      soldeFin: "Solde de fin de semaine : {{montant}}",
      cashLibrePrevu: "Cash libre prévu : {{montant}}",
      cashLibrePrevuNonCalculable: "Cash libre prévu : non calculable.",
      sousSeuil: "Sous le seuil d'alerte",
      enDeficit: "En déficit",
      lignes: "{{nombre}} ligne(s) placée(s)",
      semainesIllisibles: "{{nombre}} semaine(s) illisible(s) pour cette version de l'app : non affichées.",
      progression: "Semaines lues : {{affichees}} sur {{total}}.",
      voirPlus: "Voir plus de semaines",
      chargementSuite: "Chargement de la suite…",
      suite: {
        prevision_changee: "La prévision a changé pendant la lecture : elle a été relue depuis le début.",
        incoherente: "Réponse incohérente du serveur : la prévision a été relue depuis le début.",
        refus: "Le serveur refuse la suite ({{code}}) : {{detail}}",
        echec: "Impossible de charger la suite ({{code}}) : {{detail}}",
      },
    },
    echeances: {
      frequenceEtiquette: "Fréquence de production",
      frequences: {
        mensuelle: "Mensuelle",
        trimestrielle: "Trimestrielle",
        annuelle: "Annuelle",
      },
      statuts: {
        A_VENIR: "À venir",
        EN_RETARD: "En retard",
      },
      moisFinExercice: "Fin de l'exercice : mois {{mois}}",
      particulierOui: "Particulier en affaires : oui",
      particulierNon: "Particulier en affaires : non",
      particulierNonDeclare: "Particulier en affaires : non déclaré",
      taxesRemises: "Taxes remises jusqu'au {{date}}",
      taxesRemisesNonDeclarees:
        "Dernière remise de taxes : non déclarée. Aucun retard n'est détectable tant qu'elle ne l'est pas.",
      periode: "Période du {{debut}} au {{fin}}",
      periodeTerminee: "Période terminée, du {{debut}} au {{fin}}",
      limitePaiement: "Paiement au plus tard le {{date}} (jours restants selon M5 : {{jours}})",
      limiteProduction: "Production de la déclaration au plus tard le {{date}} (jours restants selon M5 : {{jours}})",
      joursNegatifs: "Un nombre de jours négatif veut dire que la limite est passée.",
      aRemettre: "Taxes nettes à remettre : {{montant}}",
      tps: "TPS : collectée {{collectee}}, crédits d'intrants {{credits}}, nette {{nette}}, à remettre {{aRemettre}}.",
      tvq: "TVQ : collectée {{collectee}}, crédits d'intrants {{credits}}, nette {{nette}}, à remettre {{aRemettre}}.",
      factures: "Factures comptées : {{clients}} client(s), {{fournisseurs}} fournisseur(s).",
      taxesNonChiffrees: "Taxes non chiffrées par M5 : voir ce qui manque.",
      couverturePartielle: "Calcul sur les pièces reçues; couverture partielle.",
      couvertureInconnue: "Couverture non confirmée; le total peut être incomplet.",
      illisibles: "{{nombre}} échéance(s) illisible(s) pour cette version de l'app : non affichées.",
      nonAffichees: "{{nombre}} échéance(s) non affichée(s).",
      connuJusquAu: "Calendrier connu jusqu'au {{date}}",
      validationsTitre: "Validation du calendrier",
      validations: {
        A_VALIDER: "Année {{annee}} : calendrier {{version}}, à valider par le CPA.",
        VALIDE_PAR_LE_CPA: "Année {{annee}} : calendrier {{version}}, validé par le CPA.",
      },
      validationInconnue:
        "Année {{annee}} : calendrier {{version}}, validation « {{validation}} » (inconnue de cette version de l'app).",
      horsPerimetreTitre: "Hors du calendrier (à confirmer avec le CPA)",
      sourcesTitre: "Sources",
      source: "{{organisme}} — {{titre}} (consultée le {{date}})",
    },
    vue: {
      portee: "Ce que couvre cette vue",
      entonnoirTitre: "Entonnoir",
      mesureNonCalculable: "Non calculable — manque : {{manque}}",
      mesureNonCalculableSansPrecision: "Non calculable (le serveur ne dit pas ce qui manque).",
      mesuresIllisibles: "{{nombre}} mesure(s) illisible(s) pour cette version de l'app : non affichées.",
      sourcesTitre: "Faits reçus par source",
      sourceSansDate: "{{evenement}} : {{n}} fait(s), aucun horodatage.",
      sourceDatee: "{{evenement}} : {{n}} fait(s), le dernier le {{date}}.",
      sourcesIllisibles: "{{nombre}} source(s) illisible(s) pour cette version de l'app : non affichées.",
      sansReponse: "Devis sans réponse : {{n}} ({{devis}})",
      brouillonsEnRetard: "Brouillons de devis en retard : {{n}} ({{devis}})",
      devisReste: "{{reste}} autre(s) non cité(s) par le serveur.",
      seuilsTitre: "Seuils d'alerte",
      seuilsAConfigurer:
        "Seuils à configurer (aucune alerte n'est évaluée pour : {{mesures}}). À déclarer dans : {{configuration}}.",
      seuilsAConfigurerSansEndroit: "Seuils à configurer (aucune alerte n'est évaluée pour : {{mesures}}).",
      seuilsInvalides: "Seuils invalides, ignorés : {{mesures}}.",
      seuilsIgnores: "Seuils sans mesure connue, ignorés : {{mesures}}.",
      seuilsIllisibles: "{{nombre}} seuil(s) illisible(s) pour cette version de l'app : non affichés.",
      seuilStatuts: {
        franchi: "Seuil franchi",
        non_franchi: "Seuil non franchi",
      },
      sens: {
        au_dessus: "Alerte quand la mesure est au-dessus du seuil",
        au_dessous: "Alerte quand la mesure est au-dessous du seuil",
      },
      valeurEtiquette: "Valeur",
      seuilEtiquette: "Seuil",
      margeTitre: "Marge réelle des chantiers (M5)",
      margeResume: "Chantiers terminés : {{n}} ; marge connue : {{connue}} ; non calculable : {{nonCalculable}}.",
      chantier: "Chantier {{chantier}} (devis {{devis}})",
      chantierSansDevis: "Chantier {{chantier}} (sans devis relié)",
      chantierTermine: "Terminé le {{date}}",
      margeCalculee: "Marge réelle : {{montant}}",
      margeNonCalculable: "Marge réelle non calculable : {{raison}}",
      margeNonCalculableSansRaison: "Marge réelle non calculable (le serveur ne dit pas pourquoi).",
      chantiersIllisibles: "{{nombre}} chantier(s) illisible(s) pour cette version de l'app : non affichés.",
      chantiersReste: "{{nombre}} chantier(s) non montré(s) par le serveur.",
      stockTitre: "Stock à commander (M6)",
      stockResume: "Articles à commander : {{n}}",
      articleDepuis: "Depuis le {{date}}",
      articleGeste: "Geste proposé : {{geste}}",
      articlesIllisibles: "{{nombre}} article(s) illisible(s) pour cette version de l'app : non affichés.",
      articlesReste: "{{nombre}} article(s) non montré(s) par le serveur.",
      stockSeuilsAConfigurer:
        "Seuils de stock à configurer : l'absence d'article à commander ne veut pas dire que tout va bien.",
      stockManque: "Stock à commander non lu : il manque {{manque}}.",
      cashLibreAilleurs:
        "Cash libre : non repris dans cette vue (M8 ne le lit ni ne le calcule). Voir la section Trésorerie et cash libre.",
      cashLibreInconnu:
        "Cash libre : statut « {{statut}} » inconnu de cette version de l'app. Voir la section Trésorerie et cash libre.",
      manquesTitre: "Ce qui manque à cette vue",
      manque: "{{champ}} ({{source}}) : {{raison}}",
      manquesIllisibles: "{{nombre}} manque(s) illisible(s) pour cette version de l'app : non affichés.",
    },
  },
  chantiers: {
    titre: "Chantiers du jour",
    lectureSeule: "Lecture seule : aucune cédule n'est proposée ni appliquée depuis cet écran.",
    meteo:
      "Météo : non lue ici. La préparation dit seulement si les règles météo de l'entreprise sont déclarées ; la " +
      "prévision d'un créneau se juge quand une cédule est proposée, ce que cet écran ne fait pas.",
    dispatchTitre: "Interventions par statut",
    statuts: {
      en_route: "En route",
      sur_site: "Sur place",
      en_revue: "En revue",
      planifiee: "Planifiée",
      a_planifier: "À planifier",
      reportee: "Reportée",
      completed_pending_review: "Terminée, en attente de revue",
    },
    groupe: {
      aucune: "Aucune intervention.",
      nombre: "{{nombre}} intervention(s)",
      illisibles: "{{nombre}} intervention(s) illisible(s) pour cette version de l'app : non affichées.",
    },
    lead: "Lead {{id}}",
    devis: "Devis {{id}}",
    travauxService: "Service : {{valeur}}",
    travauxType: "Type de travaux : {{valeur}}",
    technicien: "Technicien : {{nom}}",
    technicienAucun: "Aucun technicien assigné",
    fenetre: "Fenêtre : {{fenetre}}",
    preparer: "Vérifier la préparation",
    preparerEnCours: "Vérification en cours…",
    digestTitre: "Digest du jour",
    digest: {
      titre: "Digest du {{date}} (référence : {{reference}})",
      rienASignaler: "Le digest du jour ne signale rien.",
      terminees: "Terminées",
      terminee: "Intervention {{intervention}} (chantier {{chantier}})",
      duree: "Durée réelle : {{minutes}} min",
      ecartSignale: "Écart signalé à la complétion",
      aucunEcart: "Aucun écart signalé",
      enRevueTitre: "En revue",
      enRevueLigne: "En revue : {{intervention}}",
      enAttenteDeRevue: "En attente de revue : {{nombre}}",
      parTypeTitre: "File de revue, par type",
      bloqueesTitre: "Bloquées en revue",
      bloquee: "Intervention {{intervention}}, demande {{demande}}",
      attente: "Bloquée depuis {{heures}} h (selon M4)",
      illisibles: "{{nombre}} élément(s) du digest illisible(s) pour cette version de l'app : non affichés.",
    },
    typesDeRevue: {
      ecart_metier: "Écarts de matériaux : {{nombre}}",
      anomalie_pointage: "Anomalies de pointage : {{nombre}}",
    },
    volets: {
      soumission: "Soumission",
      adresse: "Adresse",
      equipe: "Équipe",
      materiel: "Matériel",
      meteo: "Règles météo (pas la prévision d'un créneau)",
    },
    statutsDeVolet: {
      ok: "Prêt",
      manque: "Manque",
      non_verifiable: "Non vérifiable",
    },
    verdicts: {
      pret: "Prête à planifier",
      bloque: "Bloquée : des volets manquent",
      non_verifiable: "Non vérifiable",
    },
    preparation: {
      titre: "Préparation de l'intervention {{reference}}",
      statutEtiquette: "Statut de l'intervention",
      verdictEtiquette: "Verdict de M4",
      aFournirTitre: "À fournir",
    },
    // Ce qu'il faut faire, en mots simples, pour chaque manque que M4 sait dire (`src/ecrans/manquesM4.ts`). Jamais le texte de
    // M4 : il cite le fichier du serveur et les commandes `opsys-metier` destinées à un agent.
    manques: {
      code: "Code : {{code}}",
      inconnu: "À configurer côté serveur (code : {{code}}).",
      soumission: {
        absente: "Aucune soumission acceptée n'est rattachée à cette intervention.",
      },
      adresse: {
        aConfirmer: "L'adresse du chantier n'est pas confirmée. Une personne doit confirmer la position avant de planifier.",
        detruite: "La position confirmée n'est plus lisible. Il faut la confirmer de nouveau.",
      },
      equipe: {
        nonDeclarees: "Les équipes de l'entreprise ne sont pas déclarées. À configurer côté serveur.",
        profilInvalide: "Le profil des équipes est invalide. À corriger côté serveur.",
        reglagesIncomplets:
          "Il manque des réglages d'équipe : la liste des équipes, ou la durée et les compétences du service. À configurer côté serveur.",
        aucuneAdmissible:
          "Aucune équipe ne peut faire ce service : compétences ou quarts insuffisants. À ajuster côté serveur.",
        nonVerifiable: "Les équipes ne peuvent pas être vérifiées pour cette intervention.",
      },
      materiel: {
        partiel: "Le matériel est disponible en partie. Demandez à M6 de compléter la commande.",
        aCommander: "Le matériel doit être commandé. Demandez un bon de commande à M6.",
        nonVerifiable: "M6 n'a pas dit si le matériel est prêt : il ne peut pas être vérifié pour l'instant.",
      },
      meteo: {
        nonDeclarees: "Les règles météo de l'entreprise ne sont pas déclarées. À configurer côté serveur.",
        profilInvalide: "Le profil météo est invalide. À corriger côté serveur.",
        seuilsIncomplets: "Les seuils météo de ce service ne sont pas tous décidés. À configurer côté serveur.",
        nonVerifiable: "Les règles météo ne peuvent pas être vérifiées pour cette intervention.",
      },
    },
  },
};

export default adminFrCA;

/** La forme des textes du profil admin, partagée par toutes les langues. */
export type RessourcesAdmin = typeof adminFrCA;
