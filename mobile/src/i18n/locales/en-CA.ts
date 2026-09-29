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
  identite: {
    chargement: "Checking your identity…",
    absente: "Identity not confirmed: cannot continue right now.",
    bandeau: {
      connecte: "{{personne}} — {{role}}",
      aReconfirmer: "To be reconfirmed: identity kept from the last connection, the server could not be reached.",
      quarantaine:
        "{{nombre}} pending send(s) belong to another person: kept, they will never be sent under your identity.",
    },
    roles: {
      admin: "Administrator",
      employee: "Employee",
      seller: "Seller",
    },
    erreur: {
      titre: "Device identity not confirmed",
      appareil: "Device ID: {{appareilId}}",
      reessayer: "Try again",
      reessayerEnCours: "Checking…",
      reappairer: "Pair again",
      envoisConserves: "Pending sends on this device are kept: nothing is deleted.",
      motifs: {
        appareil_non_attribue:
          "This device is paired, but not yet assigned to a person. Give the ID below to the owner so they " +
          "can assign it to your name, then try again.",
        role_inconnu:
          "The role assigned to this device is not recognized. No profile is opened: ask the owner to fix " +
          "the assignment.",
        jeton_refuse:
          "This device is no longer authorized (access revoked or expired). Pair it again with a new code.",
        refus_inattendu:
          "The gateway refuses to give this device's identity. Try again later or ask the owner for help.",
        reponse_invalide: "Unexpected gateway response: the identity could not be confirmed. Try again later.",
        hors_ligne_sans_memoire:
          "The server cannot be reached, and no identity has been confirmed on this device yet. Connect to " +
          "the network, then try again.",
        stockage_illisible:
          "The device's secure storage is unreadable for now. Try again; if it persists, restart the device.",
      },
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
    champsRequis: "Enter the job before punching.",
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
  approvals: {
    titre: "Approvals",
    lienDepuisAccueil: "Approvals to decide",
    chargement: "Loading requests…",
    rafraichir: "Refresh",
    aucuneDemande: "No pending requests.",
    enAttente: "Pending: {{total}}",
    reste: "{{nombre}} more request(s) not shown: decide these, then refresh, or use the console.",
    illisibles: "{{nombre}} request(s) unreadable in this app version: see the console.",
    lectureSeuleProprietaire: "Read-only: only the owner can decide a request.",
    appareilNonAppaire: "Device not paired: cannot load requests.",
    echecChargement: "Cannot load requests ({{code}}): {{detail}}",
    niveau: "Level {{niveau}}",
    niveauInconnu: "Unknown level",
    depuis: "Since {{date}}",
    departement: "Department: {{nom}}",
    motifDemande: "Reason for the request: {{motif}}",
    argumentsTitre: "Exact arguments",
    argumentsNonAffiches: "Arguments not shown.",
    attentes: {
      titre: "To review (department waits)",
      aucune: "No waits reported by the departments.",
      informatif: "For information: this is not decided here.",
      geste: "Suggested action: {{geste}}",
      reste: "{{nombre}} more wait(s) not shown: see the console.",
      voirPlus: "Show more ({{nombre}} more wait(s))",
      chargementSuite: "Loading more…",
      echecSuite: "Cannot load more ({{code}}): {{detail}}",
      listeChangee: "Some waits changed while reading: the list was reloaded from the start.",
      pageIncoherente: "Inconsistent server response: the list was reloaded from the start.",
      illisibles: "{{nombre}} wait(s) unreadable in this app version: see the console.",
      departementsIllisibles:
        "Waits unreadable for: {{departements}}. The absence of an alert from these departments is not confirmed.",
    },
    lectureSeule: {
      console: "To be decided at the console.",
      non_proprietaire: "Owner only.",
      arguments_absents: "Arguments cannot be shown: decide at the console.",
      incoherente: "This request cannot be decided from the app: see the console.",
      serveur: "{{detail}} ({{code}})",
    },
    champMotif: "Note (optional)",
    approuver: "Approve",
    refuser: "Reject",
    confirmerApprouver: "Confirm approval",
    confirmerRefuser: "Confirm rejection",
    annuler: "Cancel",
    decisionEnFile: {
      approuver: "Approval queued: it will be sent as soon as the device is online.",
      refuser: "Rejection queued: it will be sent as soon as the device is online.",
    },
    enFileHorsLigne: "Decision put in the send queue (offline): the server will check it on arrival.",
    decisionsDeLaSession: "Decisions sent",
    resultat: {
      refusee: "Rejected. Nothing was executed.",
      executee: "Approved and executed.",
      executee_refusee_par_l_outil: "Approved, but the tool refused on the merits ({{code}}): {{detail}}",
      echec_execution: "Approved, but the execution failed: {{detail}}",
      tracee: "Signed {{decidePar}} ({{role}}), {{date}}.",
    },
    echecDefinitif: "Decision not applied ({{code}}): {{detail}}",
  },
};

export default enCA;
