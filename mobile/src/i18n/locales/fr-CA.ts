import adminFrCA from "./admin.fr-CA";
import type { RessourcesAdmin } from "./admin.fr-CA";

/** Forme des ressources i18n communes, partagée par toutes les langues (fr-CA.ts, en-CA.ts) —
 * un champ oublié dans une traduction est une erreur TypeScript, jamais un texte manquant
 * silencieux à l'exécution. */
export interface RessourcesCommunes {
  pairing: {
    titre: string;
    explication: string;
    champCode: {
      etiquette: string;
      indice: string;
    };
    bouton: string;
    boutonEnCours: string;
    phases: {
      connexion: string;
      attenteDefi: string;
      signature: string;
      attenteApprobation: string;
      nouvelleTentativeReseau: string;
      reussi: string;
    };
    erreurs: {
      code_invalide: string;
      code_expire: string;
      refuse: string;
      delai_ecoule: string;
      reponse_inattendue: string;
    };
  };
  identite: {
    chargement: string;
    absente: string;
    bandeau: {
      connecte: string;
      aReconfirmer: string;
      quarantaine: string;
    };
    roles: {
      admin: string;
      employee: string;
      seller: string;
    };
    erreur: {
      titre: string;
      appareil: string;
      reessayer: string;
      reessayerEnCours: string;
      reappairer: string;
      envoisConserves: string;
      motifs: {
        appareil_non_attribue: string;
        role_inconnu: string;
        jeton_refuse: string;
        refus_inattendu: string;
        reponse_invalide: string;
        hors_ligne_sans_memoire: string;
        stockage_illisible: string;
      };
    };
  };
  groupes: {
    employee: { accueil: string };
    seller: { accueil: string };
    admin: { accueil: string };
    client: { accueil: string };
  };
  pointage: {
    titre: string;
    champIntervention: string;
    champsRequis: string;
    aucunPointage: string;
    boutons: {
      entree: string;
      sortie: string;
      pauseDebut: string;
      pauseFin: string;
    };
    pointeA: string;
    etatSynchro: {
      enAttente: string;
      envoi: string;
      envoyee: string;
      echecPermanent: string;
      echecPermanentAvecVerdict: string;
    };
    appareilNonAppaire: string;
  };
  consentementGps: {
    titre: string;
    explication: string;
    retirer: string;
    appareilNonAppaire: string;
    etat: {
      enAttente: string;
      envoi: string;
      envoye: string;
      echecPermanentAvecVerdict: string;
      echecPermanent: string;
    };
    aucunChangement: string;
  };
  today: {
    titre: string;
    chargement: string;
    aucunChantier: string;
    rafraichir: string;
    source: {
      cache: string;
      aucune: string;
    };
    statut: {
      planifiee: string;
      en_route: string;
      sur_site: string;
      en_revue: string;
      reportee: string;
      completed_pending_review: string;
      completed_verified: string;
      annulee: string;
    };
  };
  job: {
    titre: string;
    appareilNonAppaire: string;
    statutInconnu: string;
    source: {
      cache: string;
      aucune: string;
    };
    boutons: {
      enRoute: string;
      arrive: string;
      pauseDebut: string;
      pauseFin: string;
    };
    liens: {
      checklist: string;
      photos: string;
      signature: string;
      complete: string;
    };
    verdict: {
      echecPermanent: string;
      echecPermanentAvecVerdict: string;
    };
  };
  checklist: {
    titre: string;
    champNouvelItem: string;
    ajouter: string;
    vide: string;
    retirer: string;
    etat: {
      terminee: string;
      nonTerminee: string;
    };
  };
  photos: {
    titre: string;
    natures: {
      avant: string;
      pendant: string;
      apres: string;
    };
    capturer: string;
    aucunePhoto: string;
    permissionRefusee: string;
    enregistrement: string;
  };
  signature: {
    titre: string;
    effacer: string;
    confirmer: string;
    requise: string;
    enregistree: string;
    vide: string;
  };
  complete: {
    titre: string;
    champNotes: string;
    signatureRequise: {
      question: string;
      oui: string;
      non: string;
    };
    consentements: {
      titre: string;
      consigne: string;
      noteLangue: string;
      demandeAvis: string;
      photos: string;
      version: string;
      satisfaction: {
        question: string;
        satisfait: string;
        insatisfait: string;
      };
    };
    bouton: string;
    boutonEnCours: string;
    appareilNonAppaire: string;
    blocages: {
      checklist_incomplete: string;
      aucune_photo_apres: string;
      signature_requise_non_choisie: string;
      signature_requise_mais_absente: string;
      fichiers_en_echec: string;
      fichiers_en_cours: string;
    };
    verdict: {
      echecPermanentAvecVerdict: string;
    };
    enAttenteEnvoi: string;
    succes: {
      titre: string;
      statut: string;
    };
    lienMateriaux: string;
  };
  materials: {
    titre: string;
    aucunWct: string;
    champMateriau: string;
    champQuantite: string;
    champUnite: string;
    champQuantiteEstimee: string;
    typeLigne: {
      prevu: string;
      non_prevu: string;
      retour: string;
      perte: string;
      bris: string;
      achat_terrain: string;
    };
    photoFournie: string;
    recuFourni: string;
    ajouterLigne: string;
    retirerLigne: string;
    aucuneLigne: string;
    erreurs: {
      materiau_id_manquant: string;
      unite_manquante: string;
      quantite_invalide: string;
      quantite_estimee_invalide: string;
      achat_terrain_preuve_manquante: string;
    };
    blocages: {
      aucune_ligne: string;
      lignes_invalides: string;
    };
    bouton: string;
    boutonEnCours: string;
    appareilNonAppaire: string;
    enAttenteEnvoi: string;
    succes: string;
    verdict: {
      echecPermanentAvecVerdict: string;
    };
  };
  approvals: {
    titre: string;
    lienDepuisAccueil: string;
    chargement: string;
    rafraichir: string;
    aucuneDemande: string;
    enAttente: string;
    reste: string;
    illisibles: string;
    lectureSeuleProprietaire: string;
    appareilNonAppaire: string;
    echecChargement: string;
    niveau: string;
    niveauInconnu: string;
    depuis: string;
    departement: string;
    motifDemande: string;
    argumentsTitre: string;
    argumentsNonAffiches: string;
    attentes: {
      titre: string;
      aucune: string;
      informatif: string;
      geste: string;
      reste: string;
      voirPlus: string;
      chargementSuite: string;
      echecSuite: string;
      listeChangee: string;
      pageIncoherente: string;
      illisibles: string;
      departementsIllisibles: string;
    };
    lectureSeule: {
      console: string;
      non_proprietaire: string;
      arguments_absents: string;
      incoherente: string;
      serveur: string;
    };
    champMotif: string;
    approuver: string;
    refuser: string;
    confirmerApprouver: string;
    confirmerRefuser: string;
    annuler: string;
    decisionEnFile: {
      approuver: string;
      refuser: string;
    };
    enFileHorsLigne: string;
    decisionsDeLaSession: string;
    resultat: {
      refusee: string;
      executee: string;
      executee_refusee_par_l_outil: string;
      echec_execution: string;
      tracee: string;
    };
    echecDefinitif: string;
  };
  vendeur: {
    accueil: { leads: string; quotes: string };
    commun: {
      rafraichir: string;
      chargement: string;
      sansSession: string;
      echecLecture: string;
      refus: string;
      cache: string;
      absent: string;
      date: string;
    };
    statuts: Record<string, string>;
    segments: Record<string, string>;
    leads: {
      titre: string;
      filtreStatut: string;
      filtreSegment: string;
      tous: string;
      segmentNonCalculable: string;
      badgeNonCalculable: string;
      segmentsNonCalculablesTitre: string;
      total: string;
      aucunLead: string;
      voirPlus: string;
      chargementSuite: string;
      echecSuite: string;
      listeChangee: string;
      pageIncoherente: string;
      listePartielleCache: string;
      illisibles: string;
      indetermines: string;
      urgent: string;
      derniereActivite: string;
      prochaineAction: string;
      aucuneProchaineAction: string;
      regleCitee: string;
      regleSansEnonce: string;
      donnee: string;
      voirRegles: string;
      masquerRegles: string;
      nonCalculableDuLead: string;
      ouvrir: string;
    };
    lead: {
      titre: string;
      identifiantInvalide: string;
      suggestion: {
        titre: string;
        regle: string;
        motif: string;
        refus: string;
      };
      client: {
        titre: string;
        contact: string;
        contactAbsent: string;
        ceLead: string;
        autres: string;
        opportuniteAbsente: string;
        statut: string;
        travaux: string;
        ville: string;
        canal: string;
        source: string;
        prochaineAction: string;
        illisibles: string;
        refus: string;
      };
      historique: {
        titre: string;
        aucune: string;
        systeme: string;
        autres: string;
        dernieres: string;
      };
      notes: {
        titre: string;
        champ: string;
        ajouter: string;
        enCours: string;
        vide: string;
        tropLongue: string;
        enFileTitre: string;
        statut: {
          en_attente: string;
          envoi: string;
          echec_permanent: string;
        };
        resultat: {
          enregistree: string;
          refusee: string;
          enFile: string;
        };
        appareilNonAppaire: string;
      };
    };
    quotes: {
      titre: string;
      limiteListe: string;
      prixSeulement: string;
      numero: {
        etiquette: string;
        indice: string;
        ouvrir: string;
        vide: string;
        ouvertsTitre: string;
      };
      aucune: string;
      prixTotal: string;
      prixAbsent: string;
      statut: string;
      statuts: Record<string, string>;
      statutInconnu: string;
      lead: string;
      origine: Record<string, string>;
      voirLignes: string;
      masquerLignes: string;
      ligne: string;
      ligneSansQuantite: string;
      prixUnitaire: string;
      prixLigne: string;
      avis: {
        non_calculable: string;
        echouee: string;
        partielle: string;
        depuis_cache: string;
      };
      refus: string;
      indisponible: string;
    };
  };
  /** Le profil admin (PLAN T4.20) : sa forme est celle de `admin.fr-CA.ts`. */
  admin: RessourcesAdmin;
}

/**
 * Chaînes du squelette seulement (PLAN T1.4-a) : aucun écran métier n'est encore traduit, il
 * n'y a donc rien d'autre ici que l'appairage et les quatre accueils de groupe.
 */
const frCA: RessourcesCommunes = {
  pairing: {
    titre: "Appairage de l'appareil",
    explication:
      "Entrez le code d'appairage affiché par le propriétaire (QR ou code de configuration). " +
      "Une fois le défi signé envoyé, l'approbation du propriétaire est requise avant de continuer.",
    champCode: {
      etiquette: "Code d'appairage",
      indice: "oc-pair://... ou le code fourni",
    },
    bouton: "Appairer cet appareil",
    boutonEnCours: "Appairage en cours…",
    phases: {
      connexion: "Connexion à la passerelle…",
      attenteDefi: "Attente du défi du serveur…",
      signature: "Signature de l'identité de l'appareil…",
      attenteApprobation: "En attente de l'approbation du propriétaire (tentative {{tentative}})…",
      nouvelleTentativeReseau: "Reconnexion en cours (tentative {{tentative}})…",
      reussi: "Appairage réussi.",
    },
    erreurs: {
      code_invalide: "Code d'appairage invalide. Vérifiez la saisie ou redemandez un code.",
      code_expire: "Ce code d'appairage a expiré. Demandez-en un nouveau au propriétaire.",
      refuse: "Appairage refusé par la passerelle.",
      delai_ecoule: "Délai d'appairage dépassé. Générez un nouveau code auprès du propriétaire.",
      reponse_inattendue: "Réponse inattendue de la passerelle. Réessayez plus tard.",
    },
  },
  identite: {
    chargement: "Vérification de votre identité…",
    absente: "Identité non confirmée : impossible de continuer pour l'instant.",
    bandeau: {
      connecte: "{{personne}} — {{role}}",
      aReconfirmer: "À reconfirmer : identité gardée de la dernière connexion, le serveur n'a pas pu être joint.",
      quarantaine:
        "{{nombre}} envoi(s) en attente appartiennent à une autre personne : conservés, ils ne partiront jamais " +
        "sous votre identité.",
    },
    roles: {
      admin: "Administrateur",
      employee: "Employé",
      seller: "Vendeur",
    },
    erreur: {
      titre: "Identité de l'appareil non confirmée",
      appareil: "Identifiant de l'appareil : {{appareilId}}",
      reessayer: "Réessayer",
      reessayerEnCours: "Vérification…",
      reappairer: "Appairer de nouveau",
      envoisConserves: "Les envois en attente sur cet appareil sont conservés : rien n'est supprimé.",
      motifs: {
        appareil_non_attribue:
          "Cet appareil est apparié, mais n'est pas encore attribué à une personne. Donnez l'identifiant " +
          "ci-dessous au propriétaire pour qu'il l'attribue à votre nom, puis réessayez.",
        role_inconnu:
          "Le rôle attribué à cet appareil n'est pas reconnu. Aucun profil n'est ouvert : demandez au " +
          "propriétaire de corriger l'attribution.",
        jeton_refuse:
          "Cet appareil n'est plus autorisé (accès révoqué ou expiré). Appairez-le de nouveau avec un nouveau code.",
        refus_inattendu:
          "La passerelle refuse de donner l'identité de cet appareil. Réessayez plus tard ou demandez de l'aide " +
          "au propriétaire.",
        reponse_invalide: "Réponse inattendue de la passerelle : l'identité n'a pas pu être confirmée. Réessayez plus tard.",
        hors_ligne_sans_memoire:
          "Impossible de joindre le serveur, et aucune identité n'a encore été confirmée sur cet appareil. " +
          "Connectez-vous au réseau, puis réessayez.",
        stockage_illisible:
          "Le stockage sécurisé de l'appareil est illisible pour l'instant. Réessayez ; si cela persiste, " +
          "redémarrez l'appareil.",
      },
    },
  },
  groupes: {
    employee: { accueil: "Accueil — employé" },
    seller: { accueil: "Accueil — vendeur" },
    admin: { accueil: "Accueil — admin" },
    client: { accueil: "Accueil — client" },
  },
  pointage: {
    titre: "Pointage",
    champIntervention: "Intervention",
    champsRequis: "Entrez l'intervention avant de pointer.",
    aucunPointage: "Aucun pointage pour l'instant.",
    boutons: {
      entree: "Entrée",
      sortie: "Sortie",
      pauseDebut: "Début de pause",
      pauseFin: "Fin de pause",
    },
    pointeA: "Pointé à {{heures}} h {{minutes}}",
    etatSynchro: {
      enAttente: "En attente d'envoi",
      envoi: "Envoi en cours…",
      envoyee: "Envoyé",
      echecPermanent: "Échec définitif",
      echecPermanentAvecVerdict: "Échec définitif ({{code}}) : {{detail}}",
    },
    appareilNonAppaire: "Appareil non apparié : impossible de pointer pour l'instant.",
  },
  consentementGps: {
    titre: "Consentement à la géolocalisation",
    explication:
      "Votre position n'est enregistrée qu'au moment de votre pointage, si vous y avez consenti. " +
      "Retirer votre consentement désactive tout de suite la position au pointage : vous pointez " +
      "alors à la main. Vous pouvez le donner de nouveau plus tard.",
    retirer: "Retirer mon consentement GPS",
    appareilNonAppaire: "Appareil non apparié : impossible d'envoyer le retrait pour l'instant.",
    etat: {
      enAttente: "Retrait en attente d'envoi (il partira dès que le réseau revient)",
      envoi: "Envoi du retrait en cours…",
      envoye: "Retrait enregistré : votre position n'est plus prise au pointage",
      echecPermanentAvecVerdict: "Retrait refusé ({{code}}) : {{detail}}",
      echecPermanent: "Retrait refusé",
    },
    aucunChangement: "Aucun changement envoyé pour l'instant.",
  },
  today: {
    titre: "Chantiers du jour",
    chargement: "Chargement des chantiers…",
    aucunChantier: "Aucun chantier actif pour l'instant.",
    rafraichir: "Rafraîchir",
    source: {
      cache: "Hors ligne — dernières données reçues à {{heure}}",
      aucune: "Aucune donnée locale disponible hors ligne.",
    },
    statut: {
      planifiee: "Planifié",
      en_route: "En route",
      sur_site: "Sur place",
      en_revue: "En revue",
      reportee: "Reportée",
      completed_pending_review: "Terminé — en revue",
      completed_verified: "Terminé — vérifié",
      annulee: "Annulée",
    },
  },
  job: {
    titre: "Chantier",
    appareilNonAppaire: "Appareil non apparié : impossible de continuer pour l'instant.",
    statutInconnu: "Statut inconnu",
    source: {
      cache: "Hors ligne — dernier statut connu",
      aucune: "Aucun statut connu localement.",
    },
    boutons: {
      enRoute: "En route",
      arrive: "Arrivé",
      pauseDebut: "Pause",
      pauseFin: "Fin de pause",
    },
    liens: {
      checklist: "Checklist",
      photos: "Photos",
      signature: "Signature",
      complete: "Terminer",
    },
    verdict: {
      echecPermanent: "Échec définitif",
      echecPermanentAvecVerdict: "Échec définitif ({{code}}) : {{detail}}",
    },
  },
  checklist: {
    titre: "Checklist",
    champNouvelItem: "Nouvel élément",
    ajouter: "Ajouter",
    vide: "Aucun élément — ajoutez au moins une étape avant de terminer.",
    retirer: "Retirer",
    etat: {
      terminee: "Checklist terminée",
      nonTerminee: "Checklist non terminée",
    },
  },
  photos: {
    titre: "Photos",
    natures: {
      avant: "Avant",
      pendant: "Pendant",
      apres: "Après",
    },
    capturer: "Prendre une photo",
    aucunePhoto: "Aucune photo pour cette catégorie.",
    permissionRefusee: "Accès à la caméra refusé. Autorisez-le dans les réglages de l'appareil.",
    enregistrement: "Enregistrement de la photo…",
  },
  signature: {
    titre: "Signature du client",
    effacer: "Effacer",
    confirmer: "Confirmer",
    requise: "Signature requise pour ce chantier.",
    enregistree: "Signature enregistrée.",
    vide: "Tracez une signature avant de confirmer.",
  },
  complete: {
    titre: "Terminer le chantier",
    champNotes: "Notes (imprévus, laissez vide si aucun)",
    signatureRequise: {
      question: "Une signature du client est-elle requise pour ce chantier ?",
      oui: "Oui, requise",
      non: "Non, pas requise",
    },
    consentements: {
      titre: "Consentements du client",
      consigne:
        "Lisez chaque énoncé au client, ou montrez-le-lui. Cochez seulement si le client accepte, devant vous : " +
        "ne cochez jamais à sa place. Sans coche, aucun consentement n'est enregistré, et rien n'est envoyé au client.",
      noteLangue: "Les énoncés sont présentés au client en français, quelle que soit la langue de l'application.",
      demandeAvis: "Demande d'avis",
      photos: "Photos du chantier",
      version: "Texte présenté : version {{version}}",
      satisfaction: {
        question: "Le client est-il satisfait du résultat ? (facultatif, selon sa réponse)",
        satisfait: "Satisfait",
        insatisfait: "Insatisfait",
      },
    },
    bouton: "Terminer",
    boutonEnCours: "Envoi en cours…",
    appareilNonAppaire: "Appareil non apparié : impossible de terminer pour l'instant.",
    blocages: {
      checklist_incomplete: "La checklist n'est pas terminée. Complétez-la avant de continuer.",
      aucune_photo_apres: "Aucune photo « après » capturée. Prenez au moins une photo avant de continuer.",
      signature_requise_non_choisie: "Précisez si une signature du client est requise pour ce chantier.",
      signature_requise_mais_absente: "Signature requise mais pas encore capturée. Allez à l'écran Signature.",
      fichiers_en_echec:
        "L'envoi d'une photo ou de la signature a été refusé de façon définitive. Reprenez la photo ou la signature concernée, puis réessayez.",
      fichiers_en_cours: "Envoi des photos et de la signature en cours. Réessayez une fois la connexion rétablie.",
    },
    verdict: {
      echecPermanentAvecVerdict: "Échec définitif ({{code}}) : {{detail}}",
    },
    enAttenteEnvoi: "En attente d'envoi (hors ligne). La complétion est en file ; appuyez sur Rafraîchir une fois en ligne.",
    succes: {
      titre: "Complétion envoyée.",
      statut: "Statut retourné par le serveur : {{statut}}",
    },
    lienMateriaux: "Continuer vers les matériaux utilisés",
  },
  materials: {
    titre: "Matériaux utilisés",
    aucunWct: "Aucune complétion trouvée pour ce chantier. Retournez à l'écran Terminer.",
    champMateriau: "Matériau",
    champQuantite: "Quantité réelle",
    champUnite: "Unité",
    champQuantiteEstimee: "Quantité prévue (optionnel)",
    typeLigne: {
      prevu: "Prévu",
      non_prevu: "Non prévu",
      retour: "Retour",
      perte: "Perte",
      bris: "Bris",
      achat_terrain: "Achat terrain",
    },
    photoFournie: "Photo fournie",
    recuFourni: "Reçu fourni",
    ajouterLigne: "Ajouter un matériau",
    retirerLigne: "Retirer",
    aucuneLigne: "Aucun matériau ajouté pour l'instant.",
    erreurs: {
      materiau_id_manquant: "Indiquez le matériau.",
      unite_manquante: "Indiquez l'unité.",
      quantite_invalide: "Quantité réelle invalide.",
      quantite_estimee_invalide: "Quantité prévue invalide.",
      achat_terrain_preuve_manquante: "Achat terrain : fournissez une photo ou un reçu.",
    },
    blocages: {
      aucune_ligne: "Ajoutez au moins un matériau avant de soumettre.",
      lignes_invalides: "Corrigez les lignes en erreur avant de soumettre.",
    },
    bouton: "Soumettre les matériaux",
    boutonEnCours: "Envoi en cours…",
    appareilNonAppaire: "Appareil non apparié : impossible de soumettre pour l'instant.",
    enAttenteEnvoi: "En attente d'envoi (hors ligne). La déclaration est en file ; appuyez sur Rafraîchir une fois en ligne.",
    succes: "Matériaux soumis.",
    verdict: {
      echecPermanentAvecVerdict: "Échec définitif ({{code}}) : {{detail}}",
    },
  },
  approvals: {
    titre: "Approbations",
    lienDepuisAccueil: "Approbations à décider",
    chargement: "Chargement des demandes…",
    rafraichir: "Rafraîchir",
    aucuneDemande: "Aucune demande en attente.",
    enAttente: "En attente : {{total}}",
    reste:
      "{{nombre}} autre(s) demande(s) non affichée(s) : décidez celles-ci, puis rafraîchissez, ou passez par la console.",
    illisibles: "{{nombre}} demande(s) illisible(s) pour cette version de l'app : à voir à la console.",
    lectureSeuleProprietaire: "Lecture seule : décider une demande est réservé au propriétaire.",
    appareilNonAppaire: "Appareil non apparié : impossible de charger les demandes.",
    echecChargement: "Impossible de charger les demandes ({{code}}) : {{detail}}",
    niveau: "Niveau {{niveau}}",
    niveauInconnu: "Niveau inconnu",
    depuis: "Depuis {{date}}",
    departement: "Département : {{nom}}",
    motifDemande: "Motif de la demande : {{motif}}",
    argumentsTitre: "Arguments exacts",
    argumentsNonAffiches: "Arguments non affichés.",
    attentes: {
      titre: "À voir (attentes des départements)",
      aucune: "Aucune attente signalée par les départements.",
      informatif: "Pour information : cela ne se décide pas ici.",
      geste: "Geste proposé : {{geste}}",
      reste: "{{nombre}} autre(s) attente(s) non affichée(s) : à voir à la console.",
      voirPlus: "Voir plus ({{nombre}} autre(s) attente(s))",
      chargementSuite: "Chargement de la suite…",
      echecSuite: "Impossible de charger la suite ({{code}}) : {{detail}}",
      listeChangee: "Des attentes ont changé pendant la lecture : la liste a été relue depuis le début.",
      pageIncoherente: "Réponse incohérente du serveur : la liste a été relue depuis le début.",
      illisibles: "{{nombre}} attente(s) illisible(s) pour cette version de l'app : à voir à la console.",
      departementsIllisibles:
        "Attentes illisibles pour : {{departements}}. L'absence d'alerte de ces départements n'est pas confirmée.",
    },
    lectureSeule: {
      console: "À décider à la console.",
      non_proprietaire: "Réservé au propriétaire.",
      arguments_absents: "Arguments non affichables : à décider à la console.",
      incoherente: "Cette demande ne se décide pas depuis l'app : à voir à la console.",
      serveur: "{{detail}} ({{code}})",
    },
    champMotif: "Note (facultative)",
    approuver: "Approuver",
    refuser: "Refuser",
    confirmerApprouver: "Confirmer l'approbation",
    confirmerRefuser: "Confirmer le refus",
    annuler: "Annuler",
    decisionEnFile: {
      approuver: "Approbation en file d'envoi : elle partira dès que l'appareil sera en ligne.",
      refuser: "Refus en file d'envoi : il partira dès que l'appareil sera en ligne.",
    },
    enFileHorsLigne: "Décision mise en file d'envoi (hors ligne) : le serveur la vérifiera à l'arrivée.",
    decisionsDeLaSession: "Décisions envoyées",
    resultat: {
      refusee: "Refusée. Rien n'a été exécuté.",
      executee: "Approuvée et exécutée.",
      executee_refusee_par_l_outil: "Approuvée, mais l'outil a refusé sur le fond ({{code}}) : {{detail}}",
      echec_execution: "Approuvée, mais l'exécution a échoué : {{detail}}",
      tracee: "Signée {{decidePar}} ({{role}}), {{date}}.",
    },
    echecDefinitif: "Décision non appliquée ({{code}}) : {{detail}}",
  },
  vendeur: {
    accueil: { leads: "Mes leads", quotes: "Mes soumissions" },
    commun: {
      rafraichir: "Rafraîchir",
      chargement: "Chargement…",
      sansSession: "Appareil non apparié ou identité non confirmée : impossible de lire pour l'instant.",
      echecLecture: "Impossible de lire ({{code}}) : {{detail}}",
      refus: "Le serveur refuse ({{code}}) : {{detail}}",
      cache: "Hors ligne : données du cache, lues le {{date}}. Raison : {{code}}.",
      absent: "non précisé",
      date: "{{date}}",
    },
    statuts: {
      nouveau: "Nouveau",
      qualifie: "Qualifié",
      converti: "Converti",
      perdu: "Perdu",
      cedule: "Cédulé",
      chantier: "Chantier",
      facture: "Facturé",
      paiement: "Paiement",
      avis: "Avis",
    },
    segments: {
      hot_lead: "Lead chaud",
      needs_photos: "Photos à demander",
      estimate_ready: "Prêt pour l'estimation",
      quote_sent: "Soumission envoyée",
      quote_stale: "Soumission sans réponse",
      won_pending_schedule: "Gagné, chantier à planifier",
      active_job: "Chantier en cours",
      invoice_pending: "Facture à encaisser",
      past_customer: "Client existant",
      high_value_customer: "Client de grande valeur",
      referral_candidate: "Candidat à la référence",
      complaint_risk: "Risque de plainte",
      dormant_lead: "Lead dormant",
      seasonal_opportunity: "Occasion saisonnière",
    },
    leads: {
      titre: "Mes leads",
      filtreStatut: "Statut",
      filtreSegment: "Segment",
      tous: "Tous",
      segmentNonCalculable: "Ce segment n'est pas calculable : {{detail}}",
      badgeNonCalculable: "non calculable",
      segmentsNonCalculablesTitre: "Segments non calculables ({{nombre}})",
      total: "{{total}} lead(s)",
      aucunLead: "Aucun lead pour ce filtre.",
      voirPlus: "Voir plus ({{nombre}} autre(s) lead(s))",
      chargementSuite: "Chargement de la suite…",
      echecSuite: "Impossible de charger la suite ({{code}}) : {{detail}}",
      listeChangee: "Des leads ont changé pendant la lecture : la liste a été relue depuis le début.",
      pageIncoherente: "Réponse incohérente du serveur : la liste a été relue depuis le début.",
      listePartielleCache: "Le cache ne garde que {{nombre}} lead(s) sur {{total}} : rafraîchissez en ligne pour voir la suite.",
      illisibles: "{{nombre}} lead(s) illisible(s) pour cette version de l'app : à voir à la console.",
      indetermines: "{{nombre}} lead(s) dont le segment n'a pas pu être calculé : ils ne sont pas dans cette liste.",
      urgent: "Urgence déclarée",
      derniereActivite: "Dernière activité : {{date}}",
      prochaineAction: "Prochaine action : {{description}} (échéance {{echeance}})",
      aucuneProchaineAction: "Prochaine action : aucune consignée",
      regleCitee: "Règle : {{enonce}}",
      regleSansEnonce: "Règle : {{regle}} (énoncé non fourni par le serveur)",
      donnee: "{{cle}} : {{valeur}}",
      voirRegles: "Voir les règles",
      masquerRegles: "Masquer les règles",
      nonCalculableDuLead: "Non calculable pour ce lead — {{segment}} : {{manque}}",
      ouvrir: "Ouvrir la fiche",
    },
    lead: {
      titre: "Lead {{id}}",
      identifiantInvalide: "Identifiant de lead illisible : rien n'est lu.",
      suggestion: {
        titre: "Prochaine action suggérée",
        regle: "Règle citée : {{regle}}",
        motif: "Motif : {{motif}}",
        refus: "Aucune suggestion ({{code}}) : {{detail}}",
      },
      client: {
        titre: "Client 360",
        contact: "Contact",
        contactAbsent: "Contact : non fourni par le serveur.",
        ceLead: "Ce lead",
        autres: "Autres opportunités du client",
        opportuniteAbsente: "Ce lead n'est pas dans le Client 360 rendu par le serveur.",
        statut: "Statut : {{statut}}",
        travaux: "Travaux : {{travaux}}",
        ville: "Ville : {{ville}}",
        canal: "Canal : {{canal}}",
        source: "Source : {{source}}",
        prochaineAction: "Prochaine action consignée : {{description}} (échéance {{echeance}})",
        illisibles: "{{nombre}} élément(s) illisible(s) pour cette version de l'app : à voir à la console.",
        refus: "Client 360 indisponible ({{code}}) : {{detail}}",
      },
      historique: {
        titre: "Historique",
        aucune: "Aucune interaction enregistrée pour ce lead.",
        systeme: "système",
        autres: "{{nombre}} interaction(s) des autres opportunités du client ne sont pas montrées ici.",
        dernieres: "Les dix dernières interactions du client sont lues.",
      },
      notes: {
        titre: "Ajouter une note",
        champ: "Note (au plus {{max}} caractères)",
        ajouter: "Ajouter la note",
        enCours: "Envoi en cours…",
        vide: "Écrivez la note avant de l'envoyer.",
        tropLongue: "La note dépasse {{max}} caractères.",
        enFileTitre: "Notes pas encore dans l'historique",
        statut: {
          en_attente: "En file d'envoi : elle partira dès que l'appareil sera en ligne.",
          envoi: "Envoi en cours…",
          echec_permanent: "Refusée par le serveur : elle ne sera pas renvoyée.",
        },
        resultat: {
          enregistree: "Note enregistrée.",
          refusee: "Note refusée ({{code}}) : {{detail}}",
          enFile: "Note mise en file d'envoi (hors ligne) : le serveur l'écrira une seule fois, à l'arrivée.",
        },
        appareilNonAppaire: "Appareil non apparié : impossible d'envoyer la note pour l'instant.",
      },
    },
    quotes: {
      titre: "Mes soumissions",
      limiteListe:
        "Aucun outil ne liste vos soumissions. Cette liste montre celles que vos leads citent (soumission acceptée à " +
        "planifier, soumission envoyée restée sans réponse). Pour une autre, entrez son numéro.",
      prixSeulement: "Statut et prix seulement : ni coût ni marge.",
      numero: {
        etiquette: "Numéro d'une soumission",
        indice: "Numéro de la soumission",
        ouvrir: "Ouvrir",
        vide: "Entrez le numéro de la soumission.",
        ouvertsTitre: "Ouvertes par leur numéro",
      },
      aucune: "Aucune soumission connue pour l'instant.",
      prixTotal: "Prix total : {{montant}}",
      prixAbsent: "Prix total : non fourni",
      statut: "Statut : {{statut}}",
      statuts: { brouillon: "Brouillon", envoye: "Envoyée au client", accepte: "Acceptée" },
      statutInconnu: "{{statut}} (statut inconnu de l'app)",
      lead: "Lead {{id}}",
      origine: {
        lead_converti: "Soumission acceptée : chantier à planifier",
        soumission_perimee: "Envoyée, restée sans réponse",
        saisi: "Ouverte par son numéro",
      },
      voirLignes: "Voir les lignes",
      masquerLignes: "Masquer les lignes",
      ligne: "{{description}} — {{quantite}} {{unite}}",
      ligneSansQuantite: "{{description}} — quantité non fournie",
      prixUnitaire: "Prix unitaire : {{montant}}",
      prixLigne: "Prix de la ligne : {{montant}}",
      avis: {
        non_calculable: "Segment « {{segment}} » non calculable : {{manque}}",
        echouee: "Segment « {{segment}} » non lu ({{code}}) : {{detail}}. La liste peut être incomplète.",
        partielle: "Segment « {{segment}} » : {{reste}} lead(s) non lu(s). La liste est incomplète.",
        depuis_cache: "Segment « {{segment}} » lu dans le cache ({{code}}) : la liste peut être périmée.",
      },
      refus: "Soumission {{id}} : le serveur refuse ({{code}}) : {{detail}}",
      indisponible: "Soumission {{id}} : impossible de la lire ({{code}}) et aucune copie n'est gardée.",
    },
  },
  admin: adminFrCA,
};

export default frCA;
