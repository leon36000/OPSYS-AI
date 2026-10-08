import type { DepotOutbox } from "../outbox/depot";
import type { HorlogeAppareil } from "../outbox/mutation";
import type { MutationOutbox } from "../outbox/types";
import type { RapportVidange } from "../outbox/vidangeur";
import { creerMutationDecisionMarketing, construireArgumentsDecisionMarketing, decisionsMarketingEnFile, interpreterDecisionMarketing } from "./decisionOutbox";
import type { DecisionMarketingEnFile } from "./decisionOutbox";
import { lireListeM7, lireOwnerM9 } from "./contrat";
import type { LigneContenuM7, SessionM7 } from "./contrat";

export type CodeMessageMarketing =
  | "connexion"
  | "reponseInvalide"
  | "stockageLecture"
  | "lectureImpossible"
  | "motifInvalide"
  | "dejaEnFile"
  | "stockageDecision"
  | "relectureImpossible"
  | "decisionIncertaine"
  | "consentementRetire"
  | "refusServeur";

export interface EtatMarketing {
  readonly statut:
    | "inactif"
    | "chargement"
    | "pret"
    | "hors_ligne"
    | "erreur"
    | "decision_en_cours"
    | "decision_incertaine"
    | "relecture_impossible";
  readonly items: readonly LigneContenuM7[];
  readonly intentions: readonly DecisionMarketingEnFile[];
  readonly sourceDate: string | null;
  readonly owner: boolean;
  readonly message: string | null;
  /** Seulement les messages locaux connus ; une réponse serveur reste affichée brute. */
  readonly codeMessage?: CodeMessageMarketing | null;
  readonly suivant: number | null;
  readonly reste: number;
  readonly marqueCourante?: import("./contrat").PreuveMarqueM7 | null;
}

export interface DependancesMarketing {
  readonly obtenirSession: () => SessionM7 | null;
  readonly enLigne: () => boolean;
  readonly appeler: (
    tool: "m9_lister_demandes_approbation" | "m7_lister_contenus_chantier",
    args: Record<string, unknown>,
  ) => Promise<unknown>;
  readonly capturerSession: () => { session: SessionM7 | null; courante: () => boolean };
  readonly horloge: () => HorlogeAppareil;
  readonly obtenirDepot: () => Promise<DepotOutbox>;
  readonly vidanger: (courante: () => boolean) => Promise<RapportVidange | null>;
  readonly genererId: () => string;
}

function etatVide(
  statut: "inactif" | "hors_ligne" | "erreur",
  message: string | null = null,
  codeMessage: CodeMessageMarketing | null = null,
): EtatMarketing {
  return { statut, items: [], intentions: [], sourceDate: null, owner: false, message, codeMessage, suivant: null, reste: 0 };
}

export function creerControleMarketing(d: DependancesMarketing) {
  let state: EtatMarketing = etatVide("inactif");
  let generation = 0;
  let busy = false;
  let sessionCle: string | null = null;
  let online = false;
  let lectureCourante: (() => boolean) | null = null;
  let mutations: readonly MutationOutbox[] = [];
  let fileLisible = false;

  function accusePersistant(m: MutationOutbox) {
    return interpreterDecisionMarketing({ ok: true, resultat: { accepte: true, resultat: m.resumeAccepte } }, m);
  }
  function bloquee(id: string, personne: string): boolean {
    if (!fileLisible) return true;
    return mutations.filter(m => m.type === "marketing_decision").some(m => {
      const projection = decisionsMarketingEnFile([m])[0];
      if (projection.contenuId !== null && projection.contenuId !== id) return false;
      return m.proprietaire !== personne || construireArgumentsDecisionMarketing(m) === null ||
        (m.statut !== "envoyee" && m.statut !== "echec_permanent") ||
        (m.statut === "envoyee" && !accusePersistant(m).accepte);
    });
  }

  function cle(session: SessionM7 | null): string | null {
    return session
      ? `${session.urlBase}\0${session.jeton}\0${session.appareilId}\0${session.personne}`
      : null;
  }

  function etat(): EtatMarketing {
    if (!online) return state.statut === "inactif" ? state : etatVide("hors_ligne", "Connexion indisponible.", "connexion");
    if (sessionCle !== null && (cle(d.obtenirSession()) !== sessionCle || !lectureCourante?.())) return etatVide("inactif");
    return state;
  }

  function actualiserConnectivite(connectee: boolean): void {
    if (online === connectee) return;
    online = connectee;
    if (!connectee) {
      generation++;
      state = etatVide("hors_ligne", "Connexion indisponible.", "connexion");
    }
  }

  function invalider(): void {
    generation++;
    sessionCle = null;
    lectureCourante = null;
    mutations = [];
    fileLisible = false;
    state = etatVide("inactif");
    // `busy` reste verrouillé jusqu'à la fin de la mutation en vol.
  }

  function invaliderSiIdentiteChangee(captured: string, run: number, courante: () => boolean): boolean {
    if (run !== generation) return true;
    if (cle(d.obtenirSession()) !== captured || !courante()) {
      invalider();
      return true;
    }
    return false;
  }

  async function chargerInterne(offset: number, lectureDeMutation = false): Promise<void> {
    if (busy && !lectureDeMutation) return;

    const capture = d.capturerSession();
    const session = capture.session;
    const captured = cle(session);
    if (!session || !captured || !online || !d.enLigne()) {
      state = etatVide(session ? "hors_ligne" : "inactif", session ? "Connexion indisponible." : null, session ? "connexion" : null);
      return;
    }

    if (sessionCle !== null && sessionCle !== captured) {
      generation++;
      state = etatVide("inactif");
    }
    sessionCle = captured;
    lectureCourante = capture.courante;
    const run = ++generation;
    state = {
      ...state,
      statut: lectureDeMutation ? "decision_en_cours" : "chargement",
      items: offset === 0 ? [] : state.items,
      owner: false,
      message: null,
      codeMessage: null,
    };

    try {
      fileLisible = false;
      try {
        const depot = await d.obtenirDepot();
        if (invaliderSiIdentiteChangee(captured, run, capture.courante)) return;
        const rows = await depot.lister();
        if (invaliderSiIdentiteChangee(captured, run, capture.courante)) return;
        mutations = rows;
        fileLisible = true;
      } catch {
        mutations = [];
      }
      if (invaliderSiIdentiteChangee(captured, run, capture.courante)) return;
      let owner = lireOwnerM9({});
      try {
        owner = lireOwnerM9(await d.appeler("m9_lister_demandes_approbation", {}));
      } catch {
        // M7 reste lisible pour un admin, mais aucune décision n'est offerte sans preuve M9.
      }
      if (invaliderSiIdentiteChangee(captured, run, capture.courante)) return;

      const parsed = lireListeM7(
        await d.appeler("m7_lister_contenus_chantier", { limite: 8, decalage: offset }),
      );
      if (invaliderSiIdentiteChangee(captured, run, capture.courante)) return;
      if (!online || !d.enLigne()) {
        state = etatVide("hors_ligne", "Connexion indisponible.", "connexion");
        return;
      }
      if (!parsed.ok || parsed.value.decalage !== offset) {
        state = { ...etatVide("erreur", "La réponse du serveur est invalide. Rechargez la liste.", "reponseInvalide") };
        return;
      }

      // The server supplies current offset pages, with no snapshot token across reads.
      const items = [...parsed.value.items];
      state = {
        statut: "pret",
        items,
        intentions: decisionsMarketingEnFile(mutations),
        sourceDate: d.horloge().maintenant.toISOString(),
        owner: owner.ok && owner.value,
        message: fileLisible ? null : "Stockage local indisponible; aucune nouvelle décision possible.",
        codeMessage: fileLisible ? null : "stockageLecture",
        suivant: parsed.value.suivant,
        reste: parsed.value.reste,
        marqueCourante: parsed.value.marqueCourante,
      };
    } catch {
      if (run === generation) state = etatVide("erreur", "Lecture serveur impossible.", "lectureImpossible");
    }
  }

  async function charger(offset = 0): Promise<void> {
    return chargerInterne(offset);
  }

  function peutDecider(item: LigneContenuM7): boolean {
    const visible = etat();
    const current = visible.marqueCourante;
    const present = visible.items.some(
      (candidate) => candidate.contenu_id === item.contenu_id && candidate.revision === item.revision,
    );
    const proofMatches = item.marque_source !== null && current !== null && current !== undefined &&
      item.marque_source.source === current.source &&
      item.marque_source.revision === current.revision &&
      item.marque_source.sha256 === current.sha256;

    return !busy && online && d.enLigne() && cle(d.obtenirSession()) === sessionCle &&
      visible.statut === "pret" && visible.owner && present &&
      !bloquee(item.contenu_id, d.obtenirSession()?.personne ?? "") &&
      item.approval_status === "PROPOSE" && item.fraicheur_marque === "courante" && proofMatches;
  }

  async function decider(id: string, decision: "approuver" | "rejeter", motif = "") {
    const visible = etat();
    const original = visible.items.find((item) => item.contenu_id === id);
    const capture = d.capturerSession();
    const session = capture.session;
    const captured = cle(session);
    const motifNettoye = motif.trim();
    if (decision === "rejeter" && (motifNettoye.length < 5 || motifNettoye.length > 500)) {
      state = { ...visible, message: "Le motif doit contenir entre 5 et 500 caractères.", codeMessage: "motifInvalide" };
      return { ok: false as const, code: "motif_invalide" };
    }
    if (busy || !session || captured !== sessionCle || !online || !d.enLigne() ||
      !original || !peutDecider(original)) {
      return { ok: false as const, code: "action_indisponible" };
    }

    busy = true;
    const mutationGeneration = generation;
    state = { ...visible, statut: "decision_en_cours", message: null, codeMessage: null };
    let incertaine = false;
    let acceptee = false;
    let refusee = false;
    const courante = () => capture.courante() && generation === mutationGeneration &&
      cle(d.obtenirSession()) === captured && online && d.enLigne();

    try {
      const depot = await d.obtenirDepot();
      if (!courante()) return { ok: false as const, code: "identite_changee" };
      mutations = await depot.lister();
      if (!courante()) return { ok: false as const, code: "identite_changee" };
      fileLisible = true;
      if (bloquee(id, session.personne)) {
        state = { ...state, statut: "pret", intentions: decisionsMarketingEnFile(mutations), message: "Une intention existe déjà pour ce contenu. Consultez la file sortante.", codeMessage: "dejaEnFile" };
        return { ok: false as const, code: "decision_deja_en_file" };
      }
      const intention = creerMutationDecisionMarketing(original, decision, motifNettoye, d.genererId, d.horloge());
      if (!courante()) return { ok: false as const, code: "identite_changee" };
      const persistee = await depot.inserer(intention);
      if (!courante()) return { ok: false as const, code: "identite_changee" };
      mutations = [...mutations, persistee];
      state = { ...state, intentions: decisionsMarketingEnFile(mutations) };
      if (persistee.proprietaire !== session.personne || persistee.id !== intention.id) {
        incertaine = true;
      } else {
        try { await d.vidanger(courante); } catch { /* Le dépôt, pas le rapport, confirme la réception. */ }
        if (!courante()) return { ok: false as const, code: "identite_changee" };
        const relue = await depot.obtenir(persistee.id);
        if (!courante()) return { ok: false as const, code: "identite_changee" };
        if (relue?.statut === "envoyee") acceptee = accusePersistant(relue).accepte;
        refusee = relue?.statut === "echec_permanent";
        incertaine = !acceptee && !refusee;
      }
    } catch {
      if (!courante()) return { ok: false as const, code: "identite_changee" };
      fileLisible = false;
      state = { ...state, statut: "decision_incertaine", owner: false,
        message: "Stockage local indisponible; consultez la file avant toute nouvelle décision.", codeMessage: "stockageDecision" };
      return { ok: false as const, code: "stockage_impossible" };
    } finally {
      // La relecture conserve le verrou ; les sorties anticipées le libèrent.
      if (!courante() || state.statut !== "decision_en_cours") busy = false;
    }

    // Garder le verrou jusqu'au bout de la relecture empêche une action concurrente.
    await chargerInterne(0, true);
    busy = false;
    const relu = etat();
    if (!capture.courante() || cle(d.obtenirSession()) !== captured || relu.statut === "inactif") {
      return { ok: false as const, code: "identite_changee" };
    }
    if (relu.statut !== "pret") {
      if (relu.statut === "hors_ligne") return { ok: false as const, code: "relecture_impossible" };
      state = {
        ...relu,
        statut: "relecture_impossible",
        owner: false,
        message: "Décision persistée; relecture impossible. Consultez la file sans créer une nouvelle intention.",
        codeMessage: "relectureImpossible",
        items: [],
        suivant: null,
        reste: 0,
      };
      return { ok: false as const, code: "relecture_impossible" };
    }

    const observed = relu.items.find((item) => item.contenu_id === id);
    const statusAttendu = decision === "approuver" ? "APPROVED" : "REJECTED";
    if (incertaine || (acceptee && !observed) ||
      (acceptee && observed?.approval_status !== statusAttendu && observed?.approval_status !== "CONSENTEMENT_RETIRE")) {
      state = {
        ...relu,
        statut: "decision_incertaine",
        owner: false,
        message: "Réponse de décision incertaine; l’état a été relu. La même intention reste en file.",
        codeMessage: "decisionIncertaine",
        suivant: null,
      };
      return { ok: false as const, code: "decision_incertaine" };
    }
    if (acceptee && observed?.approval_status === "CONSENTEMENT_RETIRE") {
      state = { ...relu, message: "Consentement retiré; le contenu reste bloqué.", codeMessage: "consentementRetire" };
    } else if (refusee) {
      state = { ...relu, message: "Décision refusée par le serveur; la liste a été relue.", codeMessage: "refusServeur" };
    }
    return { ok: acceptee, code: acceptee ? "relue" : "refus_serveur_relue" };
  }

  function chargerSuite(): Promise<void> {
    const visible = etat();
    if (busy || visible.suivant === null) return Promise.resolve();
    return chargerInterne(visible.suivant);
  }

  return { etat, charger, chargerSuite, decider, peutDecider, invalider, actualiserConnectivite };
}
