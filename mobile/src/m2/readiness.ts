import { estObjet, lireEnveloppeMetier, VERDICT_REPONSE_ILLISIBLE } from "../protocole/enveloppeOutil";
import type { VerdictServeur } from "../outbox/vidangeur";

/** Lecture M2 de la gate avant estimation. Le marqueur reste en mémoire d'écran et n'est pas une preuve M3. */
export const OUTIL_EVALUER_READINESS = "m2_evaluer_readiness";

export interface MarqueurReadiness {
  readonly leadId: string;
  readonly hashTeteRegistre: string;
  readonly horodatage: string;
  readonly empreinte: string;
}

export type ResultatReadiness =
  | { readonly genre: "pret"; readonly marqueur: MarqueurReadiness }
  | { readonly genre: "refus"; readonly verdict: VerdictServeur }
  | { readonly genre: "non_verifie"; readonly verdict: VerdictServeur };

export function construireArgumentsReadiness(leadId: string, horodatage: string): {
  lead_id: string;
  horodatage: string;
} {
  return { lead_id: leadId, horodatage };
}

function hex64(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{64}$/i.test(value);
}

function dateAvecFuseau(value: unknown): value is string {
  if (typeof value !== "string") {
    return false;
  }
  const parties = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(Z|([+-])(\d{2}):(\d{2}))$/.exec(value);
  if (parties === null) {
    return false;
  }
  const annee = Number(parties[1]);
  const mois = Number(parties[2]);
  const jour = Number(parties[3]);
  const heure = Number(parties[4]);
  const minute = Number(parties[5]);
  const seconde = Number(parties[6]);
  const joursParMois = [31, (annee % 4 === 0 && (annee % 100 !== 0 || annee % 400 === 0)) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (annee < 1 || mois < 1 || mois > 12 || jour < 1 || jour > joursParMois[mois - 1] || heure > 23 || minute > 59 || seconde > 59) {
    return false;
  }
  if (!Number.isFinite(Date.parse(value))) {
    return false;
  }
  if (parties[7] === "Z") {
    return true;
  }
  return Number(parties[9]) <= 23 && Number(parties[10]) <= 59;
}

export function lireMarqueurReadiness(value: unknown, leadIdAttendu: string): MarqueurReadiness | null {
  const clesAttendues = ["readiness_ok", "lead_id", "hash_tete_registre", "horodatage", "empreinte"];
  if (
    !estObjet(value) ||
    Object.keys(value).length !== clesAttendues.length ||
    !clesAttendues.every((cle) => Object.prototype.hasOwnProperty.call(value, cle)) ||
    value.readiness_ok !== true ||
    value.lead_id !== leadIdAttendu
  ) {
    return null;
  }
  if (!hex64(value.hash_tete_registre) || !hex64(value.empreinte) || !dateAvecFuseau(value.horodatage)) {
    return null;
  }
  return {
    leadId: leadIdAttendu,
    hashTeteRegistre: value.hash_tete_registre,
    empreinte: value.empreinte,
    horodatage: value.horodatage,
  };
}

/** Une forme inconnue ou un marqueur incohérent ne devient jamais « prêt ». Les refus métier gardent leur verdict. */
export function interpreterReadiness(value: unknown, leadIdAttendu: string): ResultatReadiness {
  const enveloppe = lireEnveloppeMetier(value);
  if (!enveloppe.ok) {
    if (enveloppe.genre === "refus") {
      return { genre: "refus", verdict: enveloppe.verdict };
    }
    return { genre: "non_verifie", verdict: enveloppe.verdict };
  }
  const marqueur = lireMarqueurReadiness(enveloppe.valeur, leadIdAttendu);
  return marqueur === null
    ? { genre: "non_verifie", verdict: VERDICT_REPONSE_ILLISIBLE }
    : { genre: "pret", marqueur };
}
