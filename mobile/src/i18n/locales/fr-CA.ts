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
  },
};

export default frCA;
