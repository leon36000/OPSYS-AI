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
  groupes: {
    employee: { accueil: string };
    seller: { accueil: string };
    admin: { accueil: string };
    client: { accueil: string };
  };
  pointage: {
    titre: string;
    champIntervention: string;
    champTechnicien: string;
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
    champTechnicien: string;
    champRequis: string;
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
    champTechnicien: string;
    champsRequis: string;
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
  groupes: {
    employee: { accueil: "Accueil — employé" },
    seller: { accueil: "Accueil — vendeur" },
    admin: { accueil: "Accueil — admin" },
    client: { accueil: "Accueil — client" },
  },
  pointage: {
    titre: "Pointage",
    champIntervention: "Intervention",
    champTechnicien: "Technicien",
    champsRequis: "Entrez l'intervention et le technicien avant de pointer.",
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
    champTechnicien: "Votre identifiant d'employé",
    champRequis: "Entrez votre identifiant d'employé avant de retirer votre consentement.",
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
    champTechnicien: "Technicien",
    champsRequis: "Entrez le technicien avant de continuer.",
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
};

export default frCA;
