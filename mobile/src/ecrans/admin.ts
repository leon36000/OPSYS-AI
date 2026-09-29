import type { AttenteDepartement, DemandeApprobation, ListeApprobations } from "../approbations/contrat";
import type { ResultatSection } from "../admin/lecture";
import { cleAttente, formaterDepuis, vueAttentes } from "./approvals";
import { message, presenterSection } from "./adminCommun";
import type { Message, VueSection } from "./adminCommun";

/**
 * Logique PURE de l'accueil du propriétaire, `(admin)/admin.tsx` (PLAN T4.20, §9.5 « Approbations » et alertes) : ce que
 * l'accueil montre de `m9_lister_demandes_approbation` — les demandes en attente, et les attentes des départements
 * (complétion en revue avec écart de matériaux critique, facture prête, chantier à réviser, besoin de commande).
 *
 * **L'accueil résume, il ne décide pas.** Aucun bouton d'approbation ici : la décision se prend à l'écran des
 * approbations (`approvals.tsx`), que l'accueil ne remplace pas et vers lequel il renvoie. Il ne montre donc ni les
 * arguments d'une demande, ni son motif, ni la description de son outil (que le cache ne garde pas non plus : Loi 25).
 *
 * **Rien n'est reclassé.** Ni « urgent » ni « critique » n'est déduit : l'ordre est celui du serveur (la plus ancienne
 * d'abord) et chaque attente dit ce que son département a écrit. Des attentes que le serveur ne donne pas (moteur plus
 * ancien) ou qu'un département n'a pas su dire ne sont jamais présentées comme « rien à voir ».
 */

export interface LigneDemande {
  readonly id: string;
  /** Le nom du département quand le serveur en donne un, sinon son identifiant. */
  readonly departement: Message;
  /** Le nom nu de l'outil que la demande veut lancer, tel que le serveur le dit. */
  readonly outil: string;
  readonly niveau: Message;
  readonly depuis: Message;
}

export interface LigneAttente {
  readonly cle: string;
  readonly departement: Message;
  /** Ce que le département a écrit de l'attente, tel quel. */
  readonly resume: string;
  readonly niveau: Message;
  readonly depuis: Message;
  /** Le geste que le département propose, tel qu'il l'écrit ; `null` : il n'en propose pas. */
  readonly geste: Message | null;
}

export type VueAttentesAccueil =
  /** Le moteur n'en donne pas : l'accueil ne dit ni « aucune » ni rien d'autre, il ne sait pas. */
  | { readonly genre: "inconnues" }
  | { readonly genre: "aucune" }
  | {
      readonly genre: "presentes";
      readonly items: readonly LigneAttente[];
      /** Attentes que le serveur n'a pas montrées : à voir à l'écran des approbations (« Voir plus »). */
      readonly reste: Message | null;
      readonly illisibles: Message | null;
      /** Les départements dont les attentes n'ont pas pu être lues : leur silence n'est pas « rien à signaler ». */
      readonly departementsIllisibles: Message | null;
    };

export interface VueAVoir {
  readonly totalEnAttente: Message;
  readonly demandes: readonly LigneDemande[];
  /** Demandes en attente que le serveur n'a pas montrées (limite, taille de la réponse) ; `null` : aucune. */
  readonly resteDemandes: Message | null;
  readonly illisibles: Message | null;
  /** Seul le propriétaire décide, et seulement à l'écran des approbations. */
  readonly proprietaire: boolean;
  readonly attentes: VueAttentesAccueil;
  /**
   * `true` SEULEMENT quand le serveur dit qu'il n'y a rien : aucune demande (ni non montrée, ni illisible), et des
   * attentes dites « aucune » par tous les départements. Une attente inconnue n'est pas un « rien ».
   */
  readonly rienAVoir: boolean;
}

function niveauAffiche(niveau: string | null): Message {
  return niveau === null ? message("approvals.niveauInconnu") : message("approvals.niveau", { niveau });
}

function ligneDemande(demande: DemandeApprobation, decalageMinutesUTC: number): LigneDemande {
  return {
    id: demande.id,
    departement: message("approvals.departement", { nom: demande.departementNom ?? demande.departement }),
    outil: demande.outil,
    niveau: niveauAffiche(demande.niveau),
    depuis: message("approvals.depuis", { date: formaterDepuis(demande.depuis, decalageMinutesUTC) }),
  };
}

function ligneAttente(attente: AttenteDepartement, decalageMinutesUTC: number): LigneAttente {
  return {
    cle: cleAttente(attente),
    departement: message("approvals.departement", { nom: attente.departementNom ?? attente.departement }),
    resume: attente.resume,
    niveau: niveauAffiche(attente.niveau),
    depuis: message("approvals.depuis", { date: formaterDepuis(attente.depuis, decalageMinutesUTC) }),
    geste: attente.actionProposee === null ? null : message("approvals.attentes.geste", { geste: attente.actionProposee }),
  };
}

export function presenterAVoir(liste: ListeApprobations, decalageMinutesUTC: number): VueAVoir {
  const vue = vueAttentes(liste.attentes);
  const attentes: VueAttentesAccueil =
    vue.genre === "presentes"
      ? {
          genre: "presentes",
          items: vue.items.map((attente) => ligneAttente(attente, decalageMinutesUTC)),
          reste: vue.reste === 0 ? null : message("admin.aVoir.attentes.reste", { nombre: vue.reste }),
          illisibles: vue.illisibles === 0 ? null : message("approvals.attentes.illisibles", { nombre: vue.illisibles }),
          departementsIllisibles:
            vue.departementsIllisibles.length === 0
              ? null
              : message("approvals.attentes.departementsIllisibles", { departements: vue.departementsIllisibles.join(", ") }),
        }
      : { genre: vue.genre };
  return {
    totalEnAttente: message("admin.aVoir.demandes.total", { total: liste.totalEnAttente }),
    demandes: liste.demandes.map((demande) => ligneDemande(demande, decalageMinutesUTC)),
    resteDemandes: liste.reste === 0 ? null : message("admin.aVoir.demandes.reste", { nombre: liste.reste }),
    illisibles: liste.illisibles === 0 ? null : message("admin.aVoir.demandes.illisibles", { nombre: liste.illisibles }),
    proprietaire: liste.proprietaire,
    attentes,
    rienAVoir:
      liste.totalEnAttente === 0 &&
      liste.demandes.length === 0 &&
      liste.reste === 0 &&
      liste.illisibles === 0 &&
      attentes.genre === "aucune",
  };
}

export function vueAccueil(resultat: ResultatSection<ListeApprobations>, decalageMinutesUTC: number): VueSection<VueAVoir> {
  return presenterSection(resultat, decalageMinutesUTC, (liste) => presenterAVoir(liste, decalageMinutesUTC));
}
