import { estObjet, lireEnveloppeMetier, texteOuNull, VERDICT_REPONSE_ILLISIBLE } from "../protocole/enveloppeOutil";
import { creerMutation, formaterHorodatageLocal, soumettreMutation } from "../outbox/mutation";
import type { HorlogeAppareil } from "../outbox/mutation";
import type { MutationOutbox } from "../outbox/types";
import type { VerdictServeur } from "../outbox/vidangeur";

/**
 * Contrat mobile de `m2_enregistrer_interaction` : le vendeur note un appel, une visite, une promesse sur SON
 * lead (`(seller)/lead/[id].tsx`, PLAN T4.8 ; DEFINITION-PRODUIT §9.4 « notes »).
 *
 * Lecture SEULE de `departments/m02-revenue-crm/src/m2_revenue_crm/outils.py` (`enregistrer_interaction` et
 * l'entrée `Outil(nom="m2_enregistrer_interaction", ...)`) et de `interactions.py` (`enregistrer`) — jamais
 * exécuté ici (ADR-0008). Les clés suivent LITTÉRALEMENT le JSON Schema serveur (`additionalProperties: false`).
 *
 * CE QUE LE SERVEUR FAIT DE CET APPEL (`acces.auteur_effectif`, `acces.controler_lead`) :
 *  - `auteur` n'est PAS envoyé : omis, il vaut la personne authentifiée par le jeton d'appareil ; un vendeur
 *    n'écrit jamais au nom d'un autre (`REJ-IDENTITE-FOURNIE-DIFFERENTE` sinon) ;
 *  - un vendeur n'écrit que sur SES leads (`REJ-LEAD-NON-ASSIGNE`, le même refus qu'un lead inconnu) ; un lead
 *    perdu est clos (`REJ-CONVERSATION-CLOSE`) : ces refus arrivent par la file, comme verdict de l'envoi ;
 *  - la note est écrite UNE fois par clé d'idempotence (`mutation.id`, R12 §4) : un renvoi après une réponse
 *    perdue rejoue l'accusé enregistré, sans second maillon.
 *
 * `horodatage` est l'heure de l'APPAREIL au moment où la note est écrite (la même que `createdAtLocal`), posée
 * UNE fois à la création : un renvoi porte le même payload, donc la même note. Le serveur en fait ce qu'il veut
 * (c'est l'instant que M2 consigne) ; aucun calcul ne dépend d'une horloge déréglée ici.
 */

export const OUTIL_ENREGISTRER_INTERACTION = "m2_enregistrer_interaction";

/**
 * Longueur maximale d'une note. Le serveur n'en fixe aucune, mais le Client 360 rend les DIX dernières
 * interactions dans UNE réponse que le socle tronque au-delà de 6 000 caractères (`Capacites._tronquer`) : une
 * note trop longue rendrait l'historique illisible pour tout le monde. 10 × 300 = 3 000 laisse la place du
 * contact et des opportunités.
 */
export const RESUME_LONGUEUR_MAX = 300;

/** Regroupement d'ordre de la file (`planification.ts` trie par `chantierId` puis `sequence`) : les notes d'un
 * lead partent dans l'ordre où le vendeur les a écrites. Une note n'appartient à aucun chantier. */
export function chantierIdNotes(leadId: string): string {
  return `lead:${leadId}`;
}

export interface ArgumentsEnregistrerInteraction {
  readonly lead_id: string;
  readonly resume: string;
  readonly horodatage: string;
}

/** Args EXACTS de `m2_enregistrer_interaction` : ni `auteur`, ni personne, ni rôle, ni appareil (le serveur les
 * tient du jeton d'appareil, `_meta`). */
export function construireArgumentsEnregistrerInteraction(
  leadId: string,
  resume: string,
  horodatage: string,
): ArgumentsEnregistrerInteraction {
  return { lead_id: leadId, resume: resume.trim(), horodatage };
}

export type ValidationNote =
  | { readonly ok: true; readonly resume: string }
  | { readonly ok: false; readonly raison: "vide" | "trop_longue" };

/** Ce que l'écran laisse partir : un résumé non vide une fois épuré, d'au plus `RESUME_LONGUEUR_MAX` caractères.
 * Le serveur refuse le reste (`REJ-CHAMP-VIDE`) : l'app ne met pas en file ce qu'elle sait refusé. */
export function validerNote(texte: string): ValidationNote {
  const resume = texte.trim();
  if (resume === "") {
    return { ok: false, raison: "vide" };
  }
  if (resume.length > RESUME_LONGUEUR_MAX) {
    return { ok: false, raison: "trop_longue" };
  }
  return { ok: true, resume };
}

/**
 * La mutation `lead_note` d'une note, prête à être insérée dans la file sortante : `en_attente` (soumise), son id
 * (généré sur l'appareil, avant tout réseau) est la clé d'idempotence. Le payload est EXACTEMENT les args de l'outil.
 * Lève pour un lead vide ou une note refusée par `validerNote` : une erreur de programmation, l'écran valide avant.
 */
export function creerMutationNote(
  leadId: string,
  texte: string,
  genererId: () => string,
  horloge: HorlogeAppareil,
): MutationOutbox {
  if (leadId.trim() === "") {
    throw new Error("identifiant de lead vide : aucune note n'est créée");
  }
  const validation = validerNote(texte);
  if (!validation.ok) {
    throw new Error(`note refusée par l'app (${validation.raison}) : aucune note n'est créée`);
  }
  const brouillon = creerMutation(
    {
      type: "lead_note",
      chantierId: chantierIdNotes(leadId),
      payload: { ...construireArgumentsEnregistrerInteraction(leadId, validation.resume, formaterHorodatageLocal(horloge)) },
    },
    genererId,
    horloge,
  );
  return soumettreMutation(brouillon);
}

/** L'accusé d'une note enregistrée (`interactions.enregistrer`) : le maillon écrit. */
export interface AccuseNote {
  readonly leadId: string;
  readonly ligneId: string;
  readonly horodatage: string;
}

export type InterpretationNote =
  | { readonly accepte: true; readonly resultat: AccuseNote }
  | { readonly accepte: false; readonly verdict: VerdictServeur };

/** Interprète la réponse de `m2_enregistrer_interaction`. Un accusé mal formé n'est JAMAIS un succès : c'est un
 * rejet (la file ne renverra pas la note : `echec_permanent`, verdict montré) qui dit de vérifier l'historique,
 * car le serveur a peut-être écrit la note. */
export function interpreterResultatEnregistrerInteraction(resultatBrut: unknown): InterpretationNote {
  const lecture = lireEnveloppeMetier(resultatBrut);
  if (!lecture.ok) {
    return { accepte: false, verdict: lecture.verdict };
  }
  const accuse = estObjet(lecture.valeur) ? lecture.valeur : null;
  const leadId = texteOuNull(accuse?.lead_id);
  const ligneId = texteOuNull(accuse?.ligne_id);
  const horodatage = texteOuNull(accuse?.horodatage);
  if (leadId === null || ligneId === null || horodatage === null) {
    return {
      accepte: false,
      verdict: {
        code: VERDICT_REPONSE_ILLISIBLE.code,
        detail:
          "La réponse du serveur est illisible : la note a peut-être été enregistrée. Ouvrez le lead pour le " +
          "vérifier ; l'app ne la renverra pas.",
      },
    };
  }
  return { accepte: true, resultat: { leadId, ligneId, horodatage } };
}

/** Une note qui n'est pas encore dans l'historique du serveur : en attente d'envoi, en cours, ou refusée. */
export interface NoteEnFile {
  readonly mutationId: string;
  readonly leadId: string;
  readonly resume: string;
  readonly ecriteLe: string;
  readonly statut: "en_attente" | "envoi" | "echec_permanent";
}

/** Les notes d'UN lead qui ne sont pas encore dans son historique serveur, dans l'ordre d'écriture. Une note
 * `envoyee` n'y est plus (elle est à l'historique) ; une note en échec permanent y reste, pour que le vendeur la
 * voie refusée plutôt que de croire qu'elle est partie. Une mutation d'un autre type ou d'un autre lead est ignorée.
 * L'ordre d'écriture est la `sequence` du dépôt, jamais `createdAtLocal` (texte à décalage variable). */
export function notesEnFile(mutations: readonly MutationOutbox[], leadId: string): readonly NoteEnFile[] {
  const retenues: { readonly rang: number; readonly note: NoteEnFile }[] = [];
  for (const mutation of mutations) {
    if (mutation.type !== "lead_note") {
      continue;
    }
    if (mutation.statut !== "en_attente" && mutation.statut !== "envoi" && mutation.statut !== "echec_permanent") {
      continue;
    }
    const { lead_id: idDuLead, resume } = mutation.payload;
    if (idDuLead !== leadId || typeof resume !== "string") {
      continue;
    }
    retenues.push({
      rang: mutation.sequence ?? Number.MAX_SAFE_INTEGER,
      note: { mutationId: mutation.id, leadId, resume, ecriteLe: mutation.createdAtLocal, statut: mutation.statut },
    });
  }
  return retenues.sort((a, b) => a.rang - b.rang).map((r) => r.note);
}
