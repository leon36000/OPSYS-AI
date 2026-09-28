import type { RessourcesCommunes } from "./fr-CA";

/** Réserve (R12 §3) — même forme que fr-CA (`RessourcesCommunes`), valeurs différentes. */
const enCA: RessourcesCommunes = {
  pairing: {
    titre: "Device pairing",
    explication:
      "Enter the pairing code shown by the owner (QR or setup code). Once the signed " +
      "challenge is sent, the owner's approval is required before continuing.",
    champCode: {
      etiquette: "Pairing code",
      indice: "oc-pair://... or the provided code",
    },
    bouton: "Pair this device",
    boutonEnCours: "Pairing…",
    phases: {
      connexion: "Connecting to the gateway…",
      attenteDefi: "Waiting for the server challenge…",
      signature: "Signing the device identity…",
      attenteApprobation: "Waiting for the owner's approval (attempt {{tentative}})…",
      nouvelleTentativeReseau: "Reconnecting (attempt {{tentative}})…",
      reussi: "Pairing succeeded.",
    },
    erreurs: {
      code_invalide: "Invalid pairing code. Check the entry or request a new code.",
      code_expire: "This pairing code has expired. Ask the owner for a new one.",
      refuse: "Pairing refused by the gateway.",
      delai_ecoule: "Pairing timed out. Generate a new code from the owner.",
      reponse_inattendue: "Unexpected response from the gateway. Try again later.",
    },
  },
  groupes: {
    employee: { accueil: "Home — employee" },
    seller: { accueil: "Home — seller" },
    admin: { accueil: "Home — admin" },
    client: { accueil: "Home — client" },
  },
  pointage: {
    titre: "Time clock",
    champIntervention: "Job",
    champTechnicien: "Technician",
    champsRequis: "Enter the job and technician before punching.",
    aucunPointage: "No punch yet.",
    boutons: {
      entree: "Clock in",
      sortie: "Clock out",
      pauseDebut: "Start break",
      pauseFin: "End break",
    },
    pointeA: "Punched at {{heures}}:{{minutes}}",
    etatSynchro: {
      enAttente: "Waiting to send",
      envoi: "Sending…",
      envoyee: "Sent",
      echecPermanent: "Permanent failure",
      echecPermanentAvecVerdict: "Permanent failure ({{code}}): {{detail}}",
    },
  },
};

export default enCA;
