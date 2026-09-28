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
  consentementGps: {
    titre: "Location consent",
    explication:
      "Your position is only recorded when you punch, if you have consented. Withdrawing your " +
      "consent turns off position capture at punch right away: you then punch by hand. You can " +
      "give it again later.",
    champTechnicien: "Your employee ID",
    champRequis: "Enter your employee ID before withdrawing your consent.",
    retirer: "Withdraw my GPS consent",
    appareilNonAppaire: "Device not paired: cannot send the withdrawal right now.",
    etat: {
      enAttente: "Withdrawal waiting to be sent (it will go out as soon as the network is back)",
      envoi: "Sending the withdrawal…",
      envoye: "Withdrawal recorded: your position is no longer taken at punch",
      echecPermanentAvecVerdict: "Withdrawal refused ({{code}}): {{detail}}",
      echecPermanent: "Withdrawal refused",
    },
    aucunChangement: "Nothing sent yet.",
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
      complete: "Finish",
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
  complete: {
    titre: "Finish the job",
    champNotes: "Notes (unexpected issues, leave blank if none)",
    signatureRequise: {
      question: "Is a client signature required for this job?",
      oui: "Yes, required",
      non: "No, not required",
    },
    bouton: "Finish",
    boutonEnCours: "Sending…",
    appareilNonAppaire: "Device not paired: cannot finish right now.",
    blocages: {
      checklist_incomplete: "The checklist is not complete. Finish it before continuing.",
      aucune_photo_apres: "No \"after\" photo captured yet. Take at least one photo before continuing.",
      signature_requise_non_choisie: "State whether a client signature is required for this job.",
      signature_requise_mais_absente: "Signature required but not captured yet. Go to the Signature screen.",
      fichiers_en_echec:
        "Sending a photo or the signature was permanently refused. Retake the photo or signature in question, then try again.",
      fichiers_en_cours: "Sending photos and the signature. Try again once back online.",
    },
    verdict: {
      echecPermanentAvecVerdict: "Permanent failure ({{code}}): {{detail}}",
    },
    enAttenteEnvoi: "Waiting to send (offline). Completion is queued; tap Refresh once back online.",
    succes: {
      titre: "Completion sent.",
      statut: "Status returned by the server: {{statut}}",
    },
    lienMateriaux: "Continue to materials used",
  },
  materials: {
    titre: "Materials used",
    aucunWct: "No completion found for this job. Go back to the Finish screen.",
    champMateriau: "Material",
    champQuantite: "Actual quantity",
    champUnite: "Unit",
    champQuantiteEstimee: "Estimated quantity (optional)",
    typeLigne: {
      prevu: "Planned",
      non_prevu: "Unplanned",
      retour: "Return",
      perte: "Loss",
      bris: "Breakage",
      achat_terrain: "Field purchase",
    },
    photoFournie: "Photo provided",
    recuFourni: "Receipt provided",
    ajouterLigne: "Add a material",
    retirerLigne: "Remove",
    aucuneLigne: "No material added yet.",
    erreurs: {
      materiau_id_manquant: "Enter the material.",
      unite_manquante: "Enter the unit.",
      quantite_invalide: "Invalid actual quantity.",
      quantite_estimee_invalide: "Invalid estimated quantity.",
      achat_terrain_preuve_manquante: "Field purchase: provide a photo or a receipt.",
    },
    blocages: {
      aucune_ligne: "Add at least one material before submitting.",
      lignes_invalides: "Fix the lines in error before submitting.",
    },
    bouton: "Submit materials",
    boutonEnCours: "Sending…",
    appareilNonAppaire: "Device not paired: cannot submit right now.",
    enAttenteEnvoi: "Waiting to send (offline). Submission is queued; tap Refresh once back online.",
    succes: "Materials submitted.",
    verdict: {
      echecPermanentAvecVerdict: "Permanent failure ({{code}}): {{detail}}",
    },
  },
};

export default enCA;
