import type { GroupeInterventions } from "../admin/chantiers";
import type { ResultatSection } from "../admin/lecture";
import {
  STATUTS_DE_VOLET,
  STATUTS_DU_DISPATCH,
  STATUTS_PREPARABLES,
  TYPES_DE_DEMANDE_DE_REVUE,
  VERDICTS_DE_PREPARATION,
  VOLETS_DE_PREPARATION,
} from "../m4/dispatch";
import type {
  DigestDuJour,
  InterventionDuDispatch,
  InterventionsLues,
  Preparation,
  VoletDePreparation,
} from "../m4/dispatch";
import { abreger, formaterDateOuInstant, libelleDeCatalogue, message, presenterSection } from "./adminCommun";
import type { Message, VueSection } from "./adminCommun";
import { direLeManque } from "./manquesM4";
import { texteSansChemin } from "./texteSur";

/**
 * Logique PURE de l'écran « Chantiers du jour » du propriétaire, `(admin)/chantiers.tsx` (PLAN T4.20, §9.5 M4 « dispatch
 * du jour, retards, file de complétion ») : les interventions par statut, le digest du jour et la préparation d'une
 * intervention. Que des lectures : aucune cédule n'est proposée ni appliquée, aucun report n'est signalé.
 *
 * **Le dispatch est par statut, pas par jour** (voir `m4/dispatch.ts`) : l'écran ne dit jamais « du jour » d'une
 * intervention, n'invente ni date ni créneau, et la fenêtre planifiée, que le registre ne porte pas, n'est montrée que si
 * le serveur en donne une. Un groupe qui n'a pas pu être lu (trop gros, refusé, hors ligne sans copie) ne ressemble
 * jamais à un groupe vide : il dit pourquoi, et le cache d'un groupe est marqué avec sa date.
 *
 * **Un manque se dit en mots simples, jamais avec le texte de M4** (PLAN T1.4-n) : le `manque` d'un volet cite le fichier du
 * serveur et les commandes `opsys-metier` que M4 destine à un agent. L'écran dit quoi faire par une phrase de l'app, choisie
 * par le code du manque (`manquesM4.ts`), et ne montre jamais un chemin du serveur ; un manque inconnu se dit « à configurer
 * côté serveur », avec son code.
 *
 * **La météo n'est pas lue ici** : la préparation ne dit que si les RÈGLES météo de l'entreprise sont déclarées (son
 * volet « météo » : `preparation.py`), et la prévision d'un créneau se juge par `m4_verifier_meteo_creneau`, qui exige
 * une cédule PROPOSÉE (qui écrit au registre). L'écran le dit, au lieu de laisser croire qu'il a regardé le ciel.
 */

export interface LigneIntervention {
  /** L'identifiant entier : celui qu'on envoie au serveur pour lire la préparation. */
  readonly interventionId: string;
  /** L'identifiant abrégé pour l'affichage. */
  readonly reference: string;
  readonly lead: Message;
  readonly travaux: Message;
  readonly devis: Message | null;
  readonly technicien: Message;
  /** La fenêtre planifiée, seulement si le serveur en donne une ; `null` : aucune n'est dite (jamais inventée). */
  readonly fenetre: Message | null;
  /** Avant le départ, la question « prête à planifier ? » a un sens : le bouton « Vérifier la préparation » est offert. */
  readonly preparable: boolean;
}

export interface ContenuGroupe {
  readonly interventions: readonly LigneIntervention[];
  /** « Aucune intervention » ou « N intervention(s) » : un groupe lu et vide le dit, il ne reste pas muet. */
  readonly resume: Message;
  /** Éléments de la réponse que ce client n'a pas su lire : comptés, jamais devinés. */
  readonly illisibles: Message | null;
}

export interface VueGroupe {
  readonly statut: string;
  readonly titre: Message;
  readonly section: VueSection<ContenuGroupe>;
}

function ligneIntervention(intervention: InterventionDuDispatch): LigneIntervention {
  return {
    interventionId: intervention.interventionId,
    reference: abreger(intervention.interventionId),
    lead: message("admin.chantiers.lead", { id: intervention.leadId }),
    travaux:
      intervention.travaux.genre === "service"
        ? message("admin.chantiers.travauxService", { valeur: intervention.travaux.valeur })
        : message("admin.chantiers.travauxType", { valeur: intervention.travaux.valeur }),
    devis: intervention.devisId === null ? null : message("admin.chantiers.devis", { id: intervention.devisId }),
    technicien:
      intervention.technicienAssigne === null
        ? message("admin.chantiers.technicienAucun")
        : message("admin.chantiers.technicien", { nom: intervention.technicienAssigne }),
    fenetre:
      intervention.fenetrePlanifiee === null
        ? null
        : message("admin.chantiers.fenetre", { fenetre: intervention.fenetrePlanifiee }),
    preparable: STATUTS_PREPARABLES.includes(intervention.statut),
  };
}

function contenuDuGroupe(lues: InterventionsLues): ContenuGroupe {
  return {
    interventions: lues.interventions.map(ligneIntervention),
    resume:
      lues.interventions.length === 0
        ? message("admin.chantiers.groupe.aucune")
        : message("admin.chantiers.groupe.nombre", { nombre: lues.interventions.length }),
    illisibles: lues.illisibles === 0 ? null : message("admin.chantiers.groupe.illisibles", { nombre: lues.illisibles }),
  };
}

export function presenterGroupes(groupes: readonly GroupeInterventions[], decalageMinutesUTC: number): readonly VueGroupe[] {
  return groupes.map((groupe) => ({
    statut: groupe.statut,
    titre: libelleDeCatalogue("admin.chantiers.statuts", groupe.statut, STATUTS_DU_DISPATCH),
    section: presenterSection(groupe.resultat, decalageMinutesUTC, contenuDuGroupe),
  }));
}

// ---------------------------------------------------------------------------------------------------------------------
// Le digest du jour
// ---------------------------------------------------------------------------------------------------------------------
export interface VueDigest {
  /** Le jour que le serveur dit avoir couvert (celui de l'appareil) et l'instant de référence, à l'heure locale. */
  readonly titre: Message;
  readonly terminees: readonly {
    readonly titre: Message;
    /** La durée réelle, en minutes, telle que M4 la compte. */
    readonly duree: Message;
    readonly ecart: Message;
  }[];
  readonly enRevue: readonly Message[];
  readonly enAttenteDeRevue: Message;
  readonly parType: readonly Message[];
  readonly bloquees: readonly {
    readonly titre: Message;
    /** Les heures d'attente, telles que M4 les compte depuis l'instant de référence de l'appareil. */
    readonly attente: Message;
  }[];
  readonly illisibles: Message | null;
  /** `true` SEULEMENT si le serveur ne signale rien (et que rien n'était illisible) : jamais déduit d'une lecture partielle. */
  readonly rienASignaler: boolean;
}

export function presenterDigest(digest: DigestDuJour, decalageMinutesUTC: number): VueDigest {
  return {
    titre: message("admin.chantiers.digest.titre", {
      date: digest.dateCible,
      reference: formaterDateOuInstant(digest.horodatageReference, decalageMinutesUTC),
    }),
    terminees: digest.terminees.map((terminee) => ({
      titre: message("admin.chantiers.digest.terminee", {
        intervention: abreger(terminee.interventionId),
        chantier: abreger(terminee.wctId),
      }),
      duree: message("admin.chantiers.digest.duree", { minutes: terminee.dureeReelleMinutes }),
      ecart: message(terminee.ecartSignale ? "admin.chantiers.digest.ecartSignale" : "admin.chantiers.digest.aucunEcart"),
    })),
    enRevue: digest.enRevue.map((id) => message("admin.chantiers.digest.enRevueLigne", { intervention: abreger(id) })),
    enAttenteDeRevue: message("admin.chantiers.digest.enAttenteDeRevue", { nombre: digest.countPendingReview }),
    parType: digest.pendingParType.map((entree) =>
      libelleDeCatalogue("admin.chantiers.typesDeRevue", entree.type, TYPES_DE_DEMANDE_DE_REVUE, { nombre: entree.nombre }),
    ),
    bloquees: digest.bloquees.map((bloquee) => ({
      titre: message("admin.chantiers.digest.bloquee", { intervention: abreger(bloquee.interventionId), demande: bloquee.demandeId }),
      attente: message("admin.chantiers.digest.attente", { heures: bloquee.heuresEcoulees }),
    })),
    illisibles: digest.illisibles === 0 ? null : message("admin.chantiers.digest.illisibles", { nombre: digest.illisibles }),
    rienASignaler:
      digest.terminees.length === 0 &&
      digest.enRevue.length === 0 &&
      digest.countPendingReview === 0 &&
      digest.bloquees.length === 0 &&
      digest.illisibles === 0,
  };
}

export function vueDigest(resultat: ResultatSection<DigestDuJour>, decalageMinutesUTC: number): VueSection<VueDigest> {
  return presenterSection(resultat, decalageMinutesUTC, (digest) => presenterDigest(digest, decalageMinutesUTC));
}

// ---------------------------------------------------------------------------------------------------------------------
// La préparation d'une intervention, à la demande
// ---------------------------------------------------------------------------------------------------------------------
export interface VueVolet {
  readonly nom: Message;
  readonly statut: Message;
  readonly ok: boolean;
  /** Ce qu'il faut faire, en mots simples (une phrase de l'app, jamais le texte de M4) ; `null` : le volet est prêt. */
  readonly manque: Message | null;
  /** Le code du manque, seulement s'il est un jeton sûr : pour le support ; `null` : aucun. */
  readonly code: Message | null;
  /** Ce que M4 dit d'un volet PRÊT (un fait : « devis accepté X »), seulement s'il ne porte ni chemin ni commande ;
   * `null` : rien à dire, ou rien de montrable. Un volet qui n'est pas prêt n'a pas de détail : son manque le remplace. */
  readonly detail: string | null;
}

export interface VuePreparation {
  readonly interventionId: string;
  readonly titre: Message;
  readonly statutIntervention: Message;
  readonly verdict: Message;
  /** « Prête » : SEULEMENT si le serveur le dit et que chaque volet est `ok` (`lirePreparation` l'exige). */
  readonly pret: boolean;
  readonly volets: readonly VueVolet[];
  readonly aFournir: readonly { readonly volet: Message; readonly manque: Message }[];
}

function presenterVolet(volet: VoletDePreparation): VueVolet {
  const ok = volet.statut === "ok";
  const dit = ok ? null : direLeManque(volet);
  return {
    nom: libelleDeCatalogue("admin.chantiers.volets", volet.nom, VOLETS_DE_PREPARATION),
    statut: libelleDeCatalogue("admin.chantiers.statutsDeVolet", volet.statut, STATUTS_DE_VOLET),
    ok,
    manque: dit === null ? null : dit.texte,
    code: dit === null ? null : dit.code,
    detail: ok ? texteSansChemin(volet.detail) : null,
  };
}

export function presenterPreparation(preparation: Preparation): VuePreparation {
  return {
    interventionId: preparation.interventionId,
    titre: message("admin.chantiers.preparation.titre", { reference: abreger(preparation.interventionId) }),
    statutIntervention: libelleDeCatalogue("admin.chantiers.statuts", preparation.statutIntervention, STATUTS_DU_DISPATCH),
    verdict: libelleDeCatalogue("admin.chantiers.verdicts", preparation.verdict, VERDICTS_DE_PREPARATION),
    pret: preparation.pret,
    volets: preparation.volets.map(presenterVolet),
    // Un volet à fournir se dit par le code de SON volet (`a_fournir` ne porte que le texte de M4, que l'app ne montre pas).
    aFournir: preparation.aFournir.map((entree) => {
      const volet = preparation.volets.find((candidat) => candidat.nom === entree.volet);
      return {
        volet: libelleDeCatalogue("admin.chantiers.volets", entree.volet, VOLETS_DE_PREPARATION),
        // Sans volet du même nom, M4 se contredit : un détail « vide » (présent, pas un code) fait dire « à configurer côté
        // serveur ». Un volet SANS code (`detail` nul) est autre chose : « aucune équipe admissible » n'a pas de code.
        manque: direLeManque({ nom: entree.volet, statut: entree.statut, detail: volet === undefined ? "" : volet.detail }).texte,
      };
    }),
  };
}

export function vuePreparation(resultat: ResultatSection<Preparation>, decalageMinutesUTC: number): VueSection<VuePreparation> {
  return presenterSection(resultat, decalageMinutesUTC, presenterPreparation);
}
