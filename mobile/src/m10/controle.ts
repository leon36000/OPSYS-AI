import type { ResultatSection } from "../admin/lecture";
import type { SessionEnvoi } from "../protocole/configuration";
import type { DepotOutbox } from "../outbox/depot";
import type { HorlogeAppareil } from "../outbox/mutation";
import type { MutationOutbox } from "../outbox/types";
import type { RapportVidange } from "../outbox/vidangeur";
import type { CatalogueM10, StatutDecisionM10, StatutRevisionM10, VueSignauxM10 } from "./contrat";
import { lireDossierRevisionM10 } from "./dossier";
import type { DossierRevisionM10 } from "./dossier";
import { arbitragesMemoireEnFile, construireArgumentsArbitrageMemoire, creerMutationArbitrageMemoire, interpreterArbitrageMemoire } from "./arbitrageOutbox";
import type { ArbitrageMemoireEnFile, ChoixArbitrageMemoire } from "./arbitrageOutbox";

export type CodeMessageMemoire = "connexion" | "lectureImpossible" | "dossierInvalide" | "actionIndisponible" |
  "stockageLecture" | "stockageDecision" | "dejaEnFile" | "decisionIncertaine" | "relectureImpossible" | "refusServeur" | "relue";
export interface EtatMemoire {
  readonly statut: "inactif" | "chargement" | "pret" | "hors_ligne" | "arbitrage_en_cours" | "decision_incertaine" | "relecture_impossible" | "erreur";
  readonly enLigne: boolean;
  readonly signaux: ResultatSection<VueSignauxM10> | null;
  readonly catalogue: ResultatSection<CatalogueM10> | null;
  readonly dossier: ResultatSection<DossierRevisionM10> | null;
  readonly statutDecision: ResultatSection<{ readonly statut: StatutDecisionM10 }> | null;
  readonly statutRevision: ResultatSection<{ readonly statut: StatutRevisionM10 }> | null;
  readonly decisionId: string | null; readonly revisionId: string | null;
  readonly intentions: readonly ArbitrageMemoireEnFile[];
  readonly messageCode: CodeMessageMemoire | null;
  /** Seulement un détail natif éventuel ; les messages locaux se traduisent par leur code. */
  readonly message: string | null;
  readonly sourceDate: string | null;
}
export interface DependancesMemoire {
  readonly capturerSession: () => { session: SessionEnvoi | null; courante: () => boolean };
  readonly enLigne: () => boolean;
  readonly chargerSignaux: () => Promise<ResultatSection<VueSignauxM10> | null>;
  readonly chargerReferences: (offset?: number) => Promise<ResultatSection<CatalogueM10> | null>;
  readonly chargerDossier: (id: string) => Promise<ResultatSection<DossierRevisionM10> | null>;
  readonly chargerStatutDecision: (id: string) => Promise<ResultatSection<{ readonly statut: StatutDecisionM10 }> | null>;
  readonly chargerStatutRevision: (id: string) => Promise<ResultatSection<{ readonly statut: StatutRevisionM10 }> | null>;
  readonly obtenirDepot: () => Promise<DepotOutbox>;
  readonly vidanger: (courante: () => boolean) => Promise<RapportVidange | null>;
  readonly genererId: () => string; readonly horloge: () => HorlogeAppareil;
}
const indisponible = <T>(): ResultatSection<T> => ({ source: "aucune", raison: { code: "lecture_indisponible", detail: "" } });
function serveurSeul<T>(r: ResultatSection<T> | null): ResultatSection<T> | null {
  return r?.source === "cache" ? indisponible() : r;
}
function dateSource<T>(r: ResultatSection<T> | null): string | null {
  return r?.source === "serveur" || r?.source === "cache" ? r.misAJourLe : null;
}

export function creerControleMemoire(d: DependancesMemoire) {
  let online = false, generation = 0, busy = false, lectureRevision = 0, lectureDecision = 0, lecturePage = 0;
  let captureActive: ReturnType<DependancesMemoire["capturerSession"]> | null = null;
  let rows: readonly MutationOutbox[] = [], fileLisible = false;
  const vide = (): EtatMemoire => ({ statut: "inactif", enLigne: online, signaux: null, catalogue: null, dossier: null,
    statutDecision: null, statutRevision: null, decisionId: null, revisionId: null, intentions: [], messageCode: null, message: null, sourceDate: null });
  let state = vide();
  function etat(): EtatMemoire {
    if (captureActive && !captureActive.courante()) return vide();
    return { ...state, enLigne: online };
  }
  function invalider(): void {
    generation++; lectureRevision++; lectureDecision++; lecturePage++;
    captureActive = null; rows = []; fileLisible = false; state = vide();
  }
  function actualiserConnectivite(connectee: boolean): void {
    if (connectee === online) return;
    online = connectee;
    if (!connectee) {
      generation++; lectureRevision++; lectureDecision++; lecturePage++;
      state = { ...etat(), statut: "hors_ligne", dossier: null, statutRevision: null, statutDecision: null,
        messageCode: "connexion", message: null, enLigne: false };
    }
  }
  function debut() {
    const capture = d.capturerSession();
    if (!capture.session || !capture.courante()) { invalider(); return null; }
    if (captureActive && !captureActive.courante()) invalider();
    captureActive = capture;
    const run = generation;
    return { capture, run, courante: () => run === generation && capture.courante() };
  }
  async function rafraichirFile(courante: () => boolean): Promise<boolean> {
    try {
      const depot = await d.obtenirDepot(); if (!courante()) return false;
      const nouvelles = await depot.lister(); if (!courante()) return false;
      rows = nouvelles; fileLisible = true;
      state = { ...state, intentions: arbitragesMemoireEnFile(rows) };
      return true;
    } catch {
      if (courante()) { fileLisible = false; state = { ...state, messageCode: "stockageLecture", message: null }; }
      return false;
    }
  }
  async function lecture<T>(f: () => Promise<ResultatSection<T> | null>): Promise<ResultatSection<T> | null> {
    try { return await f(); } catch { return indisponible(); }
  }
  async function charger(): Promise<void> {
    if (busy) return;
    const c = debut(); if (!c) return;
    const run = ++generation;
    const courante = () => c.capture.courante() && generation === run;
    lectureRevision++; lectureDecision++; lecturePage++;
    state = { ...state, statut: "chargement", dossier: null, statutRevision: null, statutDecision: null,
      decisionId: null, revisionId: null, messageCode: null, message: null };
    await Promise.all([
      rafraichirFile(courante),
      lecture(d.chargerSignaux).then(signaux => { if (courante()) state = { ...state, signaux, sourceDate: dateSource(signaux) ?? state.sourceDate }; }),
      lecture(() => d.chargerReferences(0)).then(catalogue => { if (courante()) state = { ...state, catalogue, sourceDate: dateSource(catalogue) ?? state.sourceDate }; }),
    ]);
    if (!courante()) return;
    state = { ...state, statut: online ? "pret" : "hors_ligne",
      messageCode: !fileLisible ? "stockageLecture" : online ? null : "connexion" };
  }
  async function chargerSuite(): Promise<void> {
    const v = etat(), catalogue = v.catalogue;
    if (busy || !catalogue || (catalogue.source !== "serveur" && catalogue.source !== "cache") || catalogue.valeur.suivant === null) return;
    const c = debut(); if (!c) return;
    const page = ++lecturePage;
    const nouvelle = await lecture(() => d.chargerReferences(catalogue.valeur.suivant ?? 0));
    if (!c.courante() || page !== lecturePage) return;
    state = { ...state, catalogue: nouvelle, sourceDate: dateSource(nouvelle) ?? state.sourceDate };
  }
  async function lireDecision(id: string): Promise<void> {
    if (busy) return;
    const c = debut(); if (!c) return;
    const version = ++lectureDecision;
    state = { ...state, decisionId: id, statutDecision: null, messageCode: null, message: null };
    const statutDecision = serveurSeul(await lecture(() => d.chargerStatutDecision(id)));
    if (!c.courante() || version !== lectureDecision) return;
    state = { ...state, statutDecision, sourceDate: dateSource(statutDecision) ?? state.sourceDate };
  }
  async function ouvrirInterne(id: string): Promise<boolean> {
    const c = debut(); if (!c) return false;
    const version = ++lectureRevision;
    state = { ...state, revisionId: id, dossier: null, statutRevision: null, messageCode: null, message: null };
    const [resultatDossier, resultatStatut] = await Promise.all([
      lecture(() => d.chargerDossier(id)), lecture(() => d.chargerStatutRevision(id)),
    ]);
    if (!c.courante() || version !== lectureRevision || !online || !d.enLigne()) return false;
    let dossier = serveurSeul(resultatDossier);
    const statutRevision = serveurSeul(resultatStatut);
    if (dossier?.source === "serveur") {
      const lu = lireDossierRevisionM10({ ok: true, resultat: { accepte: true, resultat: dossier.valeur } }, id);
      dossier = lu.ok ? { ...dossier, valeur: lu.value } : indisponible();
    }
    const coherent = dossier?.source === "serveur" && dossier.valeur.faits.every(f => Object.keys(f.champs).length > 0) && statutRevision?.source === "serveur" &&
      statutRevision.valeur.statut !== null && statutRevision.valeur.statut === dossier.valeur.revision.statut;
    const refus = dossier?.source === "refus" ? dossier.verdict : statutRevision?.source === "refus" ? statutRevision.verdict : null;
    state = { ...state, dossier, statutRevision,
      sourceDate: dateSource(dossier) ?? dateSource(statutRevision) ?? state.sourceDate,
      messageCode: coherent ? null : refus ? "refusServeur" : "dossierInvalide", message: refus?.detail ?? null };
    return coherent;
  }
  async function ouvrirRevision(id: string): Promise<void> {
    if (busy) return;
    if (await ouvrirInterne(id)) state = { ...state, statut: "pret" };
  }
  function bloquee(id: string, owner: string): boolean {
    if (!fileLisible) return true;
    return rows.filter(m => m.type === "memory_revision_arbitration").some(m => {
      const projection = arbitragesMemoireEnFile([m])[0];
      if (projection.revisionId !== null && projection.revisionId !== id) return false;
      return m.proprietaire !== owner || construireArgumentsArbitrageMemoire(m) === null ||
        (m.statut !== "envoyee" && m.statut !== "echec_permanent") ||
        (m.statut === "envoyee" && !interpreterArbitrageMemoire({ ok: true, resultat: { accepte: true, resultat: m.resumeAccepte } }, m).accepte);
    });
  }
  function peutArbitrer(): boolean {
    const v = etat(), session = d.capturerSession();
    return !busy && online && d.enLigne() && session.session !== null && session.courante() &&
      (v.statut === "pret" || v.statut === "chargement") &&
      v.revisionId !== null && v.dossier?.source === "serveur" && v.statutRevision?.source === "serveur" &&
      v.dossier.valeur.faits.every(f => Object.keys(f.champs).length > 0) &&
      v.dossier.valeur.revision.revision_ligne_id === v.revisionId &&
      v.statutRevision.valeur.statut !== null && v.statutRevision.valeur.statut === v.dossier.valeur.revision.statut &&
      !bloquee(v.revisionId, session.session.personne);
  }
  async function arbitrer(choix: ChoixArbitrageMemoire) {
    const v = etat();
    if (!peutArbitrer() || v.revisionId === null) return { ok: false as const, code: "action_indisponible" };
    // Une lecture générale commencée avant cette intention ne doit pas écraser son suivi.
    generation++; lecturePage++; lectureDecision++;
    const c = debut(); if (!c || !c.capture.session) return { ok: false as const, code: "identite_changee" };
    const id = v.revisionId;
    const courante = () => c.courante() && online && d.enLigne();
    busy = true;
    state = { ...state, statut: "arbitrage_en_cours", messageCode: null, message: null };
    let confirmee = false, refusee = false, detailRefus: string | null = null;
    try {
      const depot = await d.obtenirDepot(); if (!courante()) return { ok: false as const, code: "identite_changee" };
      rows = await depot.lister(); if (!courante()) return { ok: false as const, code: "identite_changee" };
      fileLisible = true;
      if (bloquee(id, c.capture.session.personne)) {
        state = { ...state, statut: "pret", intentions: arbitragesMemoireEnFile(rows), messageCode: "dejaEnFile" };
        return { ok: false as const, code: "decision_deja_en_file" };
      }
      const intention = creerMutationArbitrageMemoire(id, choix, d.genererId, d.horloge());
      if (!courante()) return { ok: false as const, code: "identite_changee" };
      const persistee = await depot.inserer(intention);
      if (!courante()) return { ok: false as const, code: "identite_changee" };
      rows = [...rows, persistee]; state = { ...state, intentions: arbitragesMemoireEnFile(rows) };
      if (persistee.id === intention.id && persistee.proprietaire === c.capture.session.personne) {
        let rapport: RapportVidange | null = null;
        try { rapport = await d.vidanger(courante); } catch { /* Seule la ligne durable confirme l'effet. */ }
        if (!courante()) return { ok: false as const, code: "identite_changee" };
        const relue = await depot.obtenir(persistee.id);
        if (!courante()) return { ok: false as const, code: "identite_changee" };
        confirmee = relue?.statut === "envoyee" && interpreterArbitrageMemoire({ ok: true,
          resultat: { accepte: true, resultat: relue.resumeAccepte } }, relue).accepte;
        refusee = relue?.statut === "echec_permanent";
        detailRefus = rapport?.echecsPermanents.find(e => e.id === persistee.id)?.verdict.detail ?? null;
      }
      await rafraichirFile(c.courante);
      if (!courante()) return { ok: false as const, code: "identite_changee" };
      const coherence = await ouvrirInterne(id);
      if (!courante()) return { ok: false as const, code: "identite_changee" };
      if (!coherence) {
        state = { ...state, statut: "relecture_impossible", messageCode: "relectureImpossible" };
        return { ok: false as const, code: "relecture_impossible" };
      }
      if (!confirmee && !refusee) {
        state = { ...state, statut: "decision_incertaine", messageCode: "decisionIncertaine" };
        return { ok: false as const, code: "decision_incertaine" };
      }
      const relu = state.statutRevision;
      if (confirmee && (relu?.source !== "serveur" || relu.valeur.statut !== choix)) {
        state = { ...state, statut: "decision_incertaine", messageCode: "decisionIncertaine" };
        return { ok: false as const, code: "decision_incertaine" };
      }
      state = { ...state, statut: "pret", messageCode: confirmee ? "relue" : "refusServeur", message: detailRefus };
      return { ok: confirmee, code: confirmee ? "relue" : "refus_serveur_relue" };
    } catch {
      if (!c.courante()) return { ok: false as const, code: "identite_changee" };
      fileLisible = false;
      state = { ...state, statut: "decision_incertaine", messageCode: "stockageDecision", message: null };
      return { ok: false as const, code: "stockage_impossible" };
    } finally {
      // Le reçu peut arriver après perte réseau : relire la file locale reste informatif.
      // Une autre identité/époque ou un écran invalidé ne récupère jamais l’ancienne UI.
      if (!online && state.statut === "hors_ligne" && captureActive?.courante() && c.capture.courante()) {
        const local = d.capturerSession(), run = generation;
        await rafraichirFile(() => local.courante() && run === generation && !online &&
          state.statut === "hors_ligne" && local.session?.personne === c.capture.session?.personne);
      }
      busy = false;
    }
  }
  return { etat, charger, chargerSuite, lireDecision, ouvrirRevision, arbitrer, peutArbitrer, invalider, actualiserConnectivite };
}
