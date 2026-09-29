// Fixtures of the OPSYS context engine tests (OPSYS-AI PLAN T3.3-suite). Every identifier below is
// fictional (`fictif: true`, AGENTS.md).
//
// `PAQUET_M10` is the REAL output of `m10_memoire.paquets.assembler_paquet_contexte` for a fictional
// case (one validated rule, one consolidated fact, one WCT and one critical variance), copied as is:
// the tests below therefore exercise the core against what M10 actually produces, not against a
// shape the core imagined.
import type { OpsysContexteConfig } from "./opsys-contexte-config.js";

export const FICTIF = true;

export const PAQUET_M10 = {
  affaire_id: "LEAD-001",
  horodatage: "2026-09-28T10:15:00+00:00",
  budget_caracteres: 4000,
  caracteres_utilises: 960,
  couches: [
    {
      nom: "regles_entreprise",
      vide: false,
      tronque: false,
      nb_total: 1,
      nb_inclus: 1,
      nb_omis: 0,
      caracteres: 230,
      faits: [
        {
          identifiant: "f6fbc575e18f7ef77a2cb05ed0a8e9964eac43eb21f55c374b72c3ae02a0358f",
          horodatage: "2026-09-01T09:00:00-04:00",
          source: "m10:decision",
          resume: "Toujours confirmer la longueur des gouttières mesurée sur place.",
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
      caracteres: 246,
      faits: [
        {
          identifiant: "5ecb5f48972d15571323034ade16d6ec72df325a15d57a3fb401cd056046466f",
          horodatage: "2026-09-16T03:00:00-04:00",
          source: "m10:consolidation",
          resume: "2026-09-15 : 1 travaux terminés, 1 variance(s) matériaux dont 1 critique(s)",
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
      caracteres: 324,
      faits: [
        {
          identifiant: "EVT-001",
          horodatage: "2026-09-15T14:05:00-04:00",
          source: "m6.variance_chantier",
          resume: "Variance EVT-001 : evaluee, signal critique",
        },
        {
          identifiant: "WCT-001",
          horodatage: "2026-09-15T14:00:00-04:00",
          source: "m4.travaux_termines",
          resume: "WCT WCT-001 : durée réelle 95 min, écart signalé",
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
      caracteres: 160,
      faits: [
        {
          identifiant: "EVT-001",
          horodatage: "2026-09-15T14:05:00-04:00",
          source: "m6.variance_chantier",
          resume: "Variance EVT-001 : evaluee, signal critique",
        },
      ],
    },
  ],
};

/** The answer of the OPSYS MCP server to a successful T0 call (`opsys.outils.executer`). */
export const ENVELOPE_PAQUET = { ok: true, resultat: PAQUET_M10, fictif: FICTIF };

/** An empty packet as M10 declares it for a case it knows nothing about: four empty layers. */
export function emptyPaquet(affaireId: string): Record<string, unknown> {
  return {
    affaire_id: affaireId,
    horodatage: "2026-09-28T10:15:00+00:00",
    budget_caracteres: 4000,
    caracteres_utilises: 0,
    couches: PAQUET_M10.couches.map((couche) => ({
      nom: couche.nom,
      vide: true,
      tronque: false,
      nb_total: 0,
      nb_inclus: 0,
      nb_omis: 0,
      caracteres: 0,
      faits: [],
    })),
  };
}

export const CONFIG_M3: OpsysContexteConfig = {
  server: "opsys_m10",
  packetTool: "m10_paquet_contexte_affaire",
  depositTool: "m10_deposer_faits_candidats",
  timeoutMs: 4_000,
  agents: new Map([["m03-estimation", ["m3_estimer_projet"]]]),
};
