import type { LeadListe } from "../m2/listeLeads";
import { estObjet, texteOuNull } from "../protocole/enveloppeOutil";

/**
 * Compatibilité du parcours historique de découverte par leads. L'écran Soumissions utilise maintenant l'inventaire
 * courant `m3_lister_devis`; il ne fusionne pas cette liste avec les numéros gardés ici. Le parcours historique lit
 * `m3_lire_devis` par numéro, et reconnaît les citations M2 suivantes :
 *  - `won_pending_schedule` (lead converti) : `donnee.reference_devis_m3`, le devis accepté ;
 *  - `quote_stale` (lead qualifié) : `donnee.devis_id`, le devis envoyé resté sans réponse.
 * Un devis dont ni l'un ni l'autre ne parle (un brouillon, un devis envoyé pas encore périmé, un devis d'un lead
 * déjà cédulé ou facturé) ne figure pas dans ces segments. Ces fonctions restent utilisées par le chargeur
 * historique et les consommateurs existants; elles ne définissent pas la liste canonique de l'écran.
 */

export type OrigineDevis = "lead_converti" | "soumission_perimee" | "liste_vendeur" | "saisi";

export const ORIGINES_DEVIS: readonly OrigineDevis[] = [
  "lead_converti",
  "soumission_perimee",
  "liste_vendeur",
  "saisi",
];

/** Les segments dont la donnée cite un devis. */
export const SEGMENT_DEVIS_ACCEPTE = "won_pending_schedule";
export const SEGMENT_DEVIS_SANS_REPONSE = "quote_stale";

export interface DevisConnu {
  readonly devisId: string;
  /** Le lead qui cite ce devis ; `null` pour un numéro saisi (le devis lui-même dit son lead une fois lu). */
  readonly leadId: string | null;
  readonly origine: OrigineDevis;
}

/** Les devis que citent les segments de ces leads, chacun avec le lead qui le cite. Un numéro absent ou vide n'est pas
 * un devis : rien n'est deviné. */
export function devisCitesParLeads(leads: readonly LeadListe[]): readonly DevisConnu[] {
  const cites: DevisConnu[] = [];
  for (const lead of leads) {
    for (const segment of lead.segments) {
      if (segment.segment === SEGMENT_DEVIS_ACCEPTE) {
        const devisId = texteOuNull(segment.donnee.reference_devis_m3);
        if (devisId !== null) {
          cites.push({ devisId, leadId: lead.leadId, origine: "lead_converti" });
        }
      } else if (segment.segment === SEGMENT_DEVIS_SANS_REPONSE) {
        const devisId = texteOuNull(segment.donnee.devis_id);
        if (devisId !== null) {
          cites.push({ devisId, leadId: lead.leadId, origine: "soumission_perimee" });
        }
      }
    }
  }
  return cites;
}

/**
 * Réunit les devis connus, un par numéro, triés par numéro (ordre stable). Un devis cité par un lead remplace un
 * numéro seulement saisi (il dit d'où il vient) ; deux citations du même numéro gardent la première.
 */
export function fusionnerDevisConnus(
  existants: readonly DevisConnu[],
  nouveaux: readonly DevisConnu[],
): readonly DevisConnu[] {
  const parNumero = new Map<string, DevisConnu>();
  for (const devis of [...existants, ...nouveaux]) {
    const present = parNumero.get(devis.devisId);
    if (present === undefined || (present.origine === "saisi" && devis.origine !== "saisi")) {
      parNumero.set(devis.devisId, devis);
    }
  }
  return [...parNumero.values()].sort((a, b) => (a.devisId < b.devisId ? -1 : a.devisId > b.devisId ? 1 : 0));
}

export function estDevisConnuValide(valeur: unknown): valeur is DevisConnu {
  return (
    estObjet(valeur) &&
    typeof valeur.devisId === "string" &&
    valeur.devisId !== "" &&
    (valeur.leadId === null || (typeof valeur.leadId === "string" && valeur.leadId !== "")) &&
    (ORIGINES_DEVIS as readonly unknown[]).includes(valeur.origine)
  );
}

export function memesDevisConnus(a: readonly DevisConnu[], b: readonly DevisConnu[]): boolean {
  return a.length === b.length && a.every((d, i) => d.devisId === b[i].devisId && d.leadId === b[i].leadId && d.origine === b[i].origine);
}
