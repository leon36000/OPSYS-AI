import type { RessourcesCommunes } from "./fr-CA";

/** Réserve (R12 §3) — même forme que fr-CA (`RessourcesCommunes`), valeurs différentes. */
const enCA: RessourcesCommunes = {
  pairing: {
    titre: "Device pairing",
    explication:
      "This device is not yet paired with the OPSYS gateway. The pairing protocol " +
      "(QR code or setup code) will be enabled in a future step.",
    etatNonApparie: "Status: not paired",
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
