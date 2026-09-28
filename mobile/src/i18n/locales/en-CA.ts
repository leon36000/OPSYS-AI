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
    appareilNonAppaire: "Device not paired: cannot punch right now.",
  },
  today: {
    titre: "Today's jobs",
    chargement: "Loading jobs…",
    aucunChantier: "No active job right now.",
    rafraichir: "Refresh",
    source: {
      cache: "Offline — last data received at {{heure}}",
      aucune: "No local data available offline.",
    },
    statut: {
      planifiee: "Scheduled",
      en_route: "On the way",
      sur_site: "On site",
      en_revue: "Under review",
      reportee: "Postponed",
      completed_pending_review: "Completed — under review",
      completed_verified: "Completed — verified",
      annulee: "Cancelled",
    },
  },
  job: {
    titre: "Job",
    champTechnicien: "Technician",
    champsRequis: "Enter the technician before continuing.",
    appareilNonAppaire: "Device not paired: cannot continue right now.",
    statutInconnu: "Unknown status",
    source: {
      cache: "Offline — last known status",
      aucune: "No status known locally.",
    },
    boutons: {
      enRoute: "On my way",
      arrive: "Arrived",
      pauseDebut: "Break",
      pauseFin: "End break",
    },
    liens: {
      checklist: "Checklist",
      photos: "Photos",
      signature: "Signature",
    },
    verdict: {
      echecPermanent: "Permanent failure",
      echecPermanentAvecVerdict: "Permanent failure ({{code}}): {{detail}}",
    },
  },
  checklist: {
    titre: "Checklist",
    champNouvelItem: "New item",
    ajouter: "Add",
    vide: "No items yet — add at least one step before finishing.",
    retirer: "Remove",
    etat: {
      terminee: "Checklist complete",
      nonTerminee: "Checklist not complete",
    },
  },
  photos: {
    titre: "Photos",
    natures: {
      avant: "Before",
      pendant: "During",
      apres: "After",
    },
    capturer: "Take a photo",
    aucunePhoto: "No photo for this category yet.",
    permissionRefusee: "Camera access denied. Allow it in the device settings.",
    enregistrement: "Saving the photo…",
  },
  signature: {
    titre: "Client signature",
    effacer: "Clear",
    confirmer: "Confirm",
    requise: "Signature required for this job.",
    enregistree: "Signature saved.",
    vide: "Draw a signature before confirming.",
  },
};

export default enCA;
