/** Forme des ressources i18n communes, partagée par toutes les langues (fr-CA.ts, en-CA.ts) —
 * un champ oublié dans une traduction est une erreur TypeScript, jamais un texte manquant
 * silencieux à l'exécution. */
export interface RessourcesCommunes {
  pairing: {
    titre: string;
    explication: string;
    etatNonApparie: string;
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
      "Cet appareil n'est pas encore apparié à la passerelle OPSYS. Le protocole d'appairage " +
      "(code QR ou code de configuration) sera activé à une prochaine étape.",
    etatNonApparie: "État : non apparié",
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
