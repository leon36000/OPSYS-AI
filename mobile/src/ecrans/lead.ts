import type { Client360, Opportunite } from "../m2/client360";
import type { AccuseNote } from "../m2/interaction";
import type { RapportVidange, VerdictServeur } from "../outbox/vidangeur";
import type { ResultatFiche } from "../vendeur/chargeurFiche";
import type { FicheLead } from "../vendeur/fiche";
import { lignesDeDonnee } from "./leads";
import type { LigneDonnee } from "./leads";

/**
 * Logique PURE de `(seller)/lead/[id].tsx` (PLAN T4.8) : ce que l'écran montre de la fiche d'un lead (Client 360,
 * prochaine action suggérée avec sa règle citée, historique) et ce qu'il dit d'une note écrite. Le fichier `.tsx` ne
 * fait que le câblage React ; tout ce qui décide est ici, testé (`lead.test.ts`).
 *
 * **Le serveur décide.** L'écran ne calcule aucune prochaine action, aucun statut : il montre la règle citée par M2
 * (`suggestions.py`) et les mots du serveur. Un refus (lead clos, lead d'un autre) est montré tel quel.
 */

export type VueFiche =
  | { readonly genre: "sans_appairage" }
  /** Le serveur refuse la requête (jeton révoqué, personne désactivée, rôle retiré) : son verdict, jamais une fiche gardée. */
  | { readonly genre: "refus"; readonly verdict: VerdictServeur }
  | { readonly genre: "aucune"; readonly raison: VerdictServeur }
  | {
      readonly genre: "fiche";
      readonly fiche: FicheLead;
      /** Non nul quand la fiche vient du cache : la date du cache et pourquoi le serveur n'a pas été lu. */
      readonly cache: { readonly misAJourLe: string; readonly raison: VerdictServeur } | null;
    };

export function vueFiche(resultat: ResultatFiche | null): VueFiche {
  if (resultat === null) {
    return { genre: "sans_appairage" };
  }
  switch (resultat.source) {
    case "serveur":
      return { genre: "fiche", fiche: resultat.fiche, cache: null };
    case "cache":
      return {
        genre: "fiche",
        fiche: resultat.fiche,
        cache: { misAJourLe: resultat.fiche.misAJourLe, raison: resultat.raisonHorsLigne },
      };
    case "refus":
      return { genre: "refus", verdict: resultat.verdict };
    case "aucune":
      return { genre: "aucune", raison: resultat.raison };
  }
}

/** Le contact tel que M2 l'a ingéré, une ligne par clé ; `null` : le serveur n'en donne pas (dit absent par
 * l'écran, jamais un nom ni un numéro inventés). */
export function lignesContact(client: Client360): readonly LigneDonnee[] | null {
  return client.contact === null || Object.keys(client.contact).length === 0 ? null : lignesDeDonnee(client.contact);
}

export interface OpportunitesDuClient {
  /** L'opportunité de CE lead, telle que le vendeur a le droit de la voir ; `null` : le Client 360 ne la porte pas. */
  readonly courante: Opportunite | null;
  /** Les autres opportunités du client visibles par ce vendeur (jamais celles d'un autre vendeur). */
  readonly autres: readonly Opportunite[];
}

export function opportunitesDuClient(client: Client360, leadId: string): OpportunitesDuClient {
  return {
    courante: client.opportunites.find((o) => o.leadId === leadId) ?? null,
    autres: client.opportunites.filter((o) => o.leadId !== leadId),
  };
}

/** La nature des travaux d'une opportunité : `service` (lead v2) ou `type_travaux` (lead v1), jamais l'un déduit de
 * l'autre ; `null` : absente. */
export function travauxDeOpportunite(opportunite: Opportunite): string | null {
  return opportunite.service ?? opportunite.typeTravaux;
}

/** L'accusé d'une note que le vidangeur a acceptée (`RapportVidange.resultatsAcceptes[].resume`, laissé `unknown`) :
 * `null` si la forme diffère (rien n'est affiché comme fait). Il vient de `interpreterResultatEnregistrerInteraction`,
 * le contrôle ici n'est qu'une ceinture. */
export function accuseNoteDepuisResume(resume: unknown): AccuseNote | null {
  if (typeof resume !== "object" || resume === null) {
    return null;
  }
  const { leadId, ligneId, horodatage } = resume as Partial<AccuseNote>;
  return typeof leadId === "string" && typeof ligneId === "string" && typeof horodatage === "string"
    ? { leadId, ligneId, horodatage }
    : null;
}

/** Ce qui est arrivé à une note que le vendeur vient d'écrire, d'après la tentative d'envoi immédiate. */
export type IssueNote =
  | { readonly genre: "enregistree"; readonly accuse: AccuseNote }
  /** Le serveur a refusé la note (lead d'un autre, lead clos...) : son verdict, tel quel ; elle ne sera pas renvoyée. */
  | { readonly genre: "refusee"; readonly verdict: VerdictServeur }
  /** Pas encore livrée (hors ligne, ou la file n'a pas pu partir) : elle reste en file avec sa clé d'idempotence. */
  | { readonly genre: "en_file" };

export function issueNote(rapport: RapportVidange | null, mutationId: string): IssueNote {
  const echec = rapport?.echecsPermanents.find((e) => e.id === mutationId);
  if (echec) {
    return { genre: "refusee", verdict: echec.verdict };
  }
  const acceptee = rapport?.resultatsAcceptes.find((r) => r.id === mutationId);
  const accuse = acceptee ? accuseNoteDepuisResume(acceptee.resume) : null;
  return accuse ? { genre: "enregistree", accuse } : { genre: "en_file" };
}
