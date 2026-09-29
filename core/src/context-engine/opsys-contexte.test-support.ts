// Fixtures of the OPSYS context engine tests (OPSYS-AI PLAN T3.3-suite and T3.3-suite-b). Every
// identifier below is fictional (`fictif: true`, AGENTS.md).
//
// The packets are the REAL output of `m10_memoire.paquets.assembler_paquet_contexte` for fictional cases,
// asked for the agent `m03-estimation`, copied as is: the tests below therefore exercise the core against what M10
// actually produces, not against a shape the core imagined. `tests/test_openclaw_contexte.py` rebuilds each packet
// with M10 and compares it, key by key, with the literal below: change M10 and it turns red.
// The base case has one validated rule, one consolidated fact, one WCT and one critical variance:
//   - `PAQUET_M10`: the critical signal is OPEN (nobody took note of it); M10 never received the step that opened
//     the case, and says so (block `affaire`, verdict `AMONT-ORIGINE-NON-RECUE`);
//   - `PAQUET_M10_SIGNAL_CLOS`: the same case once a person took the signal into account and closed it,
//     with who and why;
//   - `PAQUET_M10_VIDE`: what M10 declares for a case it knows nothing about: four empty layers, and the verdict
//     `AMONT-AFFAIRE-INCONNUE` in the block `affaire` (PLAN T4.18-b) instead of a silence.
// Two more, for the blocks of PLAN T4.18-b:
//   - `PAQUET_M10_OPPORTUNITE`: the opportunity M2 opens when a client comes back (`<lead>~opp~<wct_id>`); its
//     opening step is M2's `m2.client_associe` (withheld from `m03-estimation`, counted in `nb_retenus`);
//   - `PAQUET_M10_HISTORIQUE_TRONQUE`: a lead from an SMS (a 64-character identifier) whose history overflows the
//     events layer: the opening step is omitted from the layer but still named by the block `affaire`, and the
//     block `consolidation` lists the two days that no durable fact sums up.
import type { OpsysContexteConfig, OpsysToolLevel } from "./opsys-contexte-config.js";

export const FICTIF = true;

export const PAQUET_M10 = {
  affaire_id: "LEAD-001",
  horodatage: "2026-09-28T10:15:00+00:00",
  budget_caracteres: 4000,
  caracteres_utilises: 1199,
  couches: [
    {
      nom: "regles_entreprise",
      vide: false,
      tronque: false,
      nb_total: 1,
      nb_inclus: 1,
      nb_omis: 0,
      caracteres: 261,
      faits: [
        {
          identifiant: "a5c1d8d956c2ebcd60a7c91b2cf441a8a3624734c9fead4caaee25474bb69579",
          horodatage: "2026-09-01T09:00:00-04:00",
          source: "m10:decision",
          resume: "Toujours confirmer la longueur des gouttières mesurée sur place.",
          confidentialite: "INTERNAL",
        },
      ],
    },
    {
      nom: "faits_affaire",
      vide: false,
      tronque: false,
      nb_total: 1,
      nb_inclus: 1,
      nb_omis: 0,
      caracteres: 277,
      faits: [
        {
          identifiant: "6a8d7b69943ede375c2eb5a099f855e2fb8abcf1c8579ebe4a2187ceacdaa121",
          horodatage: "2026-09-16T03:00:00-04:00",
          source: "m10:consolidation",
          resume: "2026-09-15 : 1 travaux terminés, 1 variance(s) matériaux dont 1 critique(s)",
          confidentialite: "INTERNAL",
        },
      ],
    },
    {
      nom: "evenements_recents",
      vide: false,
      tronque: false,
      nb_total: 2,
      nb_inclus: 2,
      nb_omis: 0,
      caracteres: 386,
      faits: [
        {
          identifiant: "EVT-001",
          horodatage: "2026-09-15T14:05:00-04:00",
          source: "m6.variance_chantier",
          resume: "Variance EVT-001 : evaluee, signal critique",
          confidentialite: "INTERNAL",
        },
        {
          identifiant: "WCT-001",
          horodatage: "2026-09-15T14:00:00-04:00",
          source: "m4.travaux_termines",
          resume: "WCT WCT-001 : durée réelle 95 min, écart signalé",
          confidentialite: "INTERNAL",
        },
      ],
    },
    {
      nom: "signaux_non_resolus",
      vide: false,
      tronque: false,
      nb_total: 1,
      nb_inclus: 1,
      nb_omis: 0,
      caracteres: 275,
      faits: [
        {
          identifiant: "EVT-001",
          horodatage: "2026-09-15T14:05:00-04:00",
          source: "m6.variance_chantier",
          resume: "Variance EVT-001 : critique, OUVERT, personne n'en a pris connaissance",
          confidentialite: "INTERNAL",
          etat: "ouvert",
          traite_par: null,
          traite_le: null,
        },
      ],
    },
  ],
  signaux: {
    nb_ouverts: 1,
    nb_pris_en_compte: 0,
    nb_clos: 0,
  },
  confidentialite: {
    agent: "m03-estimation",
    regle: "v1",
    nb_retenus: 0,
  },
  affaire: {
    connue: true,
    origine_recue: false,
    origine: null,
    verdict: "AMONT-ORIGINE-NON-RECUE",
  },
  consolidation: {
    a_consolider: [],
    nb_a_consolider: 0,
  },
};

export const PAQUET_M10_SIGNAL_CLOS = {
  affaire_id: "LEAD-001",
  horodatage: "2026-09-28T10:15:00+00:00",
  budget_caracteres: 4000,
  caracteres_utilises: 1278,
  couches: [
    {
      nom: "regles_entreprise",
      vide: false,
      tronque: false,
      nb_total: 1,
      nb_inclus: 1,
      nb_omis: 0,
      caracteres: 261,
      faits: [
        {
          identifiant: "a5c1d8d956c2ebcd60a7c91b2cf441a8a3624734c9fead4caaee25474bb69579",
          horodatage: "2026-09-01T09:00:00-04:00",
          source: "m10:decision",
          resume: "Toujours confirmer la longueur des gouttières mesurée sur place.",
          confidentialite: "INTERNAL",
        },
      ],
    },
    {
      nom: "faits_affaire",
      vide: false,
      tronque: false,
      nb_total: 1,
      nb_inclus: 1,
      nb_omis: 0,
      caracteres: 277,
      faits: [
        {
          identifiant: "6a8d7b69943ede375c2eb5a099f855e2fb8abcf1c8579ebe4a2187ceacdaa121",
          horodatage: "2026-09-16T03:00:00-04:00",
          source: "m10:consolidation",
          resume: "2026-09-15 : 1 travaux terminés, 1 variance(s) matériaux dont 1 critique(s)",
          confidentialite: "INTERNAL",
        },
      ],
    },
    {
      nom: "evenements_recents",
      vide: false,
      tronque: false,
      nb_total: 2,
      nb_inclus: 2,
      nb_omis: 0,
      caracteres: 386,
      faits: [
        {
          identifiant: "EVT-001",
          horodatage: "2026-09-15T14:05:00-04:00",
          source: "m6.variance_chantier",
          resume: "Variance EVT-001 : evaluee, signal critique",
          confidentialite: "INTERNAL",
        },
        {
          identifiant: "WCT-001",
          horodatage: "2026-09-15T14:00:00-04:00",
          source: "m4.travaux_termines",
          resume: "WCT WCT-001 : durée réelle 95 min, écart signalé",
          confidentialite: "INTERNAL",
        },
      ],
    },
    {
      nom: "signaux_non_resolus",
      vide: false,
      tronque: false,
      nb_total: 1,
      nb_inclus: 1,
      nb_omis: 0,
      caracteres: 354,
      faits: [
        {
          identifiant: "EVT-001",
          horodatage: "2026-09-15T14:05:00-04:00",
          source: "m6.variance_chantier",
          resume: "Variance EVT-001 : critique, CLOS par amina.admin le 2026-09-18 : Écart expliqué : gouttière refaite, facture corrigée.",
          confidentialite: "INTERNAL",
          etat: "clos",
          traite_par: "amina.admin",
          traite_le: "2026-09-18T16:00:00-04:00",
        },
      ],
    },
  ],
  signaux: {
    nb_ouverts: 0,
    nb_pris_en_compte: 0,
    nb_clos: 1,
  },
  confidentialite: {
    agent: "m03-estimation",
    regle: "v1",
    nb_retenus: 0,
  },
  affaire: {
    connue: true,
    origine_recue: false,
    origine: null,
    verdict: "AMONT-ORIGINE-NON-RECUE",
  },
  consolidation: {
    a_consolider: [],
    nb_a_consolider: 0,
  },
};

export const PAQUET_M10_VIDE = {
  affaire_id: "LEAD-777",
  horodatage: "2026-09-28T10:15:00+00:00",
  budget_caracteres: 4000,
  caracteres_utilises: 0,
  couches: [
    {
      nom: "regles_entreprise",
      vide: true,
      tronque: false,
      nb_total: 0,
      nb_inclus: 0,
      nb_omis: 0,
      caracteres: 0,
      faits: [],
    },
    {
      nom: "faits_affaire",
      vide: true,
      tronque: false,
      nb_total: 0,
      nb_inclus: 0,
      nb_omis: 0,
      caracteres: 0,
      faits: [],
    },
    {
      nom: "evenements_recents",
      vide: true,
      tronque: false,
      nb_total: 0,
      nb_inclus: 0,
      nb_omis: 0,
      caracteres: 0,
      faits: [],
    },
    {
      nom: "signaux_non_resolus",
      vide: true,
      tronque: false,
      nb_total: 0,
      nb_inclus: 0,
      nb_omis: 0,
      caracteres: 0,
      faits: [],
    },
  ],
  signaux: {
    nb_ouverts: 0,
    nb_pris_en_compte: 0,
    nb_clos: 0,
  },
  confidentialite: {
    agent: "m03-estimation",
    regle: "v1",
    nb_retenus: 0,
  },
  affaire: {
    connue: false,
    origine_recue: false,
    origine: null,
    verdict: "AMONT-AFFAIRE-INCONNUE",
  },
  consolidation: {
    a_consolider: [],
    nb_a_consolider: 0,
  },
};

/** The opportunity M2 opens for a client who comes back: the packet is asked for `AFFAIRE_M10_OPPORTUNITE`. */
export const AFFAIRE_M10_OPPORTUNITE = "LEAD-003~opp~WCT-009";
export const PAQUET_M10_OPPORTUNITE = {
  affaire_id: "LEAD-003~opp~WCT-009",
  horodatage: "2026-09-28T10:15:00+00:00",
  budget_caracteres: 4000,
  caracteres_utilises: 186,
  couches: [
    {
      nom: "regles_entreprise",
      vide: true,
      tronque: false,
      nb_total: 0,
      nb_inclus: 0,
      nb_omis: 0,
      caracteres: 0,
      faits: [],
    },
    {
      nom: "faits_affaire",
      vide: true,
      tronque: false,
      nb_total: 0,
      nb_inclus: 0,
      nb_omis: 0,
      caracteres: 0,
      faits: [],
    },
    {
      nom: "evenements_recents",
      vide: false,
      tronque: false,
      nb_total: 1,
      nb_inclus: 1,
      nb_omis: 0,
      caracteres: 186,
      faits: [
        {
          identifiant: "DEVIS-003",
          horodatage: "2026-09-22T16:00:00-04:00",
          source: "m3.devis_accepte",
          resume: "Devis DEVIS-003 accepté, chantier CH-003",
          confidentialite: "INTERNAL",
        },
      ],
    },
    {
      nom: "signaux_non_resolus",
      vide: true,
      tronque: false,
      nb_total: 0,
      nb_inclus: 0,
      nb_omis: 0,
      caracteres: 0,
      faits: [],
    },
  ],
  signaux: {
    nb_ouverts: 0,
    nb_pris_en_compte: 0,
    nb_clos: 0,
  },
  confidentialite: {
    agent: "m03-estimation",
    regle: "v1",
    nb_retenus: 2,
  },
  affaire: {
    connue: true,
    origine_recue: true,
    origine: "m2.client_associe",
    verdict: null,
  },
  consolidation: {
    a_consolider: [],
    nb_a_consolider: 0,
  },
};

/** A lead from an SMS (64-character identifier) whose history overflows the events layer. */
export const AFFAIRE_M10_HISTORIQUE_TRONQUE = "9f3a7c1e5b2d40868a1c3e5f7092b4d6e8f0a2c4e6081a3c5e7f9b1d3f5a7c9e";
export const PAQUET_M10_HISTORIQUE_TRONQUE = {
  affaire_id: "9f3a7c1e5b2d40868a1c3e5f7092b4d6e8f0a2c4e6081a3c5e7f9b1d3f5a7c9e",
  horodatage: "2026-09-28T10:15:00+00:00",
  budget_caracteres: 4000,
  caracteres_utilises: 906,
  couches: [
    {
      nom: "regles_entreprise",
      vide: true,
      tronque: false,
      nb_total: 0,
      nb_inclus: 0,
      nb_omis: 0,
      caracteres: 0,
      faits: [],
    },
    {
      nom: "faits_affaire",
      vide: true,
      tronque: false,
      nb_total: 0,
      nb_inclus: 0,
      nb_omis: 0,
      caracteres: 0,
      faits: [],
    },
    {
      nom: "evenements_recents",
      vide: false,
      tronque: true,
      nb_total: 6,
      nb_inclus: 4,
      nb_omis: 2,
      caracteres: 906,
      faits: [
        {
          identifiant: "DEVIS-2026-0044",
          horodatage: "2026-09-16T08:00:00-04:00",
          source: "m3.devis_sans_reponse",
          resume: "Devis DEVIS-2026-0044 (envoye) sans réponse depuis 2026-09-06T10:00:00-04:00, délai de relance 7 j",
          confidentialite: "INTERNAL",
        },
        {
          identifiant: "WCT-2026-0042",
          horodatage: "2026-09-15T14:00:00-04:00",
          source: "m4.travaux_termines",
          resume: "WCT WCT-2026-0042 : durée réelle 95 min",
          confidentialite: "INTERNAL",
        },
        {
          identifiant: "DEVIS-2026-0042",
          horodatage: "2026-09-14T16:00:00-04:00",
          source: "m3.devis_accepte",
          resume: "Devis DEVIS-2026-0042 accepté, chantier CH-2026-0042",
          confidentialite: "INTERNAL",
        },
        {
          identifiant: "DEVIS-2026-0043",
          horodatage: "2026-09-12T08:00:00-04:00",
          source: "m3.devis_sans_reponse",
          resume: "Devis DEVIS-2026-0043 (envoye) sans réponse depuis 2026-09-05T10:00:00-04:00, délai de relance 7 j",
          confidentialite: "INTERNAL",
        },
      ],
    },
    {
      nom: "signaux_non_resolus",
      vide: true,
      tronque: false,
      nb_total: 0,
      nb_inclus: 0,
      nb_omis: 0,
      caracteres: 0,
      faits: [],
    },
  ],
  signaux: {
    nb_ouverts: 0,
    nb_pris_en_compte: 0,
    nb_clos: 0,
  },
  confidentialite: {
    agent: "m03-estimation",
    regle: "v1",
    nb_retenus: 1,
  },
  affaire: {
    connue: true,
    origine_recue: true,
    origine: "m1.lead_qualifie",
    verdict: null,
  },
  consolidation: {
    a_consolider: [
      {
        affaire_id: "9f3a7c1e5b2d40868a1c3e5f7092b4d6e8f0a2c4e6081a3c5e7f9b1d3f5a7c9e",
        jour: "2026-09-10",
      },
      {
        affaire_id: "9f3a7c1e5b2d40868a1c3e5f7092b4d6e8f0a2c4e6081a3c5e7f9b1d3f5a7c9e",
        jour: "2026-09-11",
      },
    ],
    nb_a_consolider: 2,
  },
};

/** The answer of the OPSYS MCP server to a successful T0 call (`opsys.outils.executer`). */
export const ENVELOPE_PAQUET = { ok: true, resultat: PAQUET_M10, fictif: FICTIF };

/** A packet for `affaireId`, as M10 declares it for a case it knows nothing about. */
export function emptyPaquet(affaireId: string): Record<string, unknown> {
  return { ...PAQUET_M10_VIDE, affaire_id: affaireId };
}

/** Levels N of the OPSYS tools the tests call, as `openclaw.py` generates them from the manifests. */
export const LEVELS_TEST: ReadonlyMap<string, OpsysToolLevel> = new Map<string, OpsysToolLevel>([
  ["m3_estimer_projet", "N3"],
  ["m3_lire_devis", "N0"],
  ["m4_proposer_cedule", "N1"],
  ["m10_deposer_faits_candidats", "N2"],
  ["m4_notifier_client_completion", "N4"],
  ["m5_enregistrer_mouvement", "N5"],
]);

export const CONFIG_M3: OpsysContexteConfig = {
  server: "opsys_m10",
  packetTool: "m10_paquet_contexte_affaire",
  depositTool: "m10_deposer_faits_candidats",
  affaireTool: "m10_affaire_de_la_session",
  timeoutMs: 4_000,
  agents: new Map([["m03-estimation", ["m3_estimer_projet"]]]),
  affaireFromSession: new Set<string>(),
  levels: LEVELS_TEST,
};

/** M3 as above, and M1 on a client channel: its case comes from the session key, never from the text. */
export const CONFIG_M3_ET_M1_SESSION: OpsysContexteConfig = {
  ...CONFIG_M3,
  agents: new Map([
    ["m03-estimation", ["m3_estimer_projet"]],
    ["m01-front-office", []],
  ]),
  affaireFromSession: new Set(["m01-front-office"]),
};
