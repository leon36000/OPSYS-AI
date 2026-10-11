import type { ResultatLectureDocumentAffaireM10 } from "./documentsAffaireLectureService";
import type { DepotOutbox } from "../outbox/depot";
import type { HorlogeAppareil } from "../outbox/mutation";
import type { MutationOutbox } from "../outbox/types";
import type { RapportVidange } from "../outbox/vidangeur";
import type { SessionEnvoi } from "../protocole/configuration";
import { copierJsonLecture, JSON_LECTURE_INVALIDE } from "../protocole/jsonLecture";
import { estAffairePaquetM10Valide } from "./paquetAffaire";
import {
  argumentsRpcDocumentM10, creerMutationDocumentM10, validerRecuDocumentM10,
  verifierDestinationDocumentM10,
} from "./documentsAffaireOutbox";
import type { OperationDocumentM10, ReferenceDocumentM10 } from "./documentsAffaireOutbox";
import type { IndexDocumentsAffaireM10, LigneIndexDocumentM10, VersionDocumentAffaireM10 } from "./documentsAffaireLecture";

export interface DependancesControleDocumentsM10 {
  readonly capturerSession: () => { readonly session: SessionEnvoi | null; readonly courante: () => boolean };
  readonly enLigne: () => boolean;
  readonly chargerIndex: (affaireId: string, decalage: number, limite: number) => Promise<ResultatLectureDocumentAffaireM10<IndexDocumentsAffaireM10> | null>;
  readonly chargerVersion: (affaireId: string, documentRef: ReferenceDocumentM10, versionSource: ReferenceDocumentM10) => Promise<ResultatLectureDocumentAffaireM10<VersionDocumentAffaireM10> | null>;
  readonly obtenirDepot: () => Promise<DepotOutbox>;
  readonly vidanger: (courante: () => boolean) => Promise<RapportVidange | null>;
  readonly genererId: () => string;
  readonly horloge: () => HorlogeAppareil;
}
export interface EtatDocumentsAffaireM10 {
  readonly affaireId: string | null;
  readonly page: ResultatLectureDocumentAffaireM10<IndexDocumentsAffaireM10> | null;
  readonly detail: ResultatLectureDocumentAffaireM10<VersionDocumentAffaireM10> | null;
  readonly selection: LigneIndexDocumentM10 | null;
  readonly brouillon: { readonly titre: string; readonly corps: string };
  readonly cibleBrouillon: ReferenceDocumentM10 | null;
  readonly enCours: boolean;
  readonly intentionId: string | null;
  readonly message: "lecture_indisponible" | "intention_incertaine" | "confirmation_recue" | "action_indisponible" | null;
  readonly intentions: readonly { readonly id: string; readonly statut: string }[];
}
const indisponible = <T>(): ResultatLectureDocumentAffaireM10<T> => ({ source: "aucune", raison: { code: "lecture_indisponible", detail: "" } });
function lectureEnCache(v: unknown): boolean {
  if (v === null || typeof v !== "object") return false;
  const source = Object.getOwnPropertyDescriptor(v, "source");
  return source !== undefined && "value" in source && source.value === "cache";
}
const documentaire = (m: MutationOutbox) => m.type === "document_m10_depot" || m.type === "document_m10_activation" || m.type === "document_m10_retrait";
const identique = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
function memeSourceVersion(ligne: LigneIndexDocumentM10, version: VersionDocumentAffaireM10): boolean {
  // Même maillon source : ces valeurs sont immuables, contrairement au statut et à l'activation.
  return ligne.titre === version.titre && ligne.methode === version.methode &&
    ligne.source_sha256 === version.source_sha256 && ligne.taille_points === version.taille_points &&
    ligne.taille_octets === version.taille_octets && ligne.horodatage === version.horodatage &&
    ligne.auteur.personne === version.auteur.personne && ligne.auteur.role === version.auteur.role &&
    ligne.auteur.source === version.auteur.source;
}
function memeIntention(a: MutationOutbox, b: MutationOutbox): boolean {
  const copie = copierJsonLecture(b);
  return copie !== JSON_LECTURE_INVALIDE && a.id === b.id && a.type === b.type && a.chantierId === b.chantierId &&
    a.proprietaire === b.proprietaire && a.createdAtLocal === b.createdAtLocal && a.dependsOn === b.dependsOn && identique(a.payload, b.payload);
}

/** Les lectures courantes et le brouillon RAM sont séparés de l'intention durable. */
export function creerControleDocumentsAffaireM10(d: DependancesControleDocumentsM10) {
  let epoch = 0, demandeDetail = 0, online = false, busy = false, fileLisible = false;
  let capture: ReturnType<DependancesControleDocumentsM10["capturerSession"]> | null = null;
  let rows: MutationOutbox[] = [], pending: MutationOutbox | null = null;
  const ciblesContradictoires = new Set<string>();
  let state: EtatDocumentsAffaireM10 = { affaireId: null, page: null, detail: null, selection: null,
    brouillon: { titre: "", corps: "" }, cibleBrouillon: null, enCours: false, intentionId: null, message: null, intentions: [] };
  function fermerLectures() { ++epoch; ++demandeDetail; state = { ...state, page: null, detail: null, selection: null, enCours: false }; }
  function etat(): EtatDocumentsAffaireM10 {
    if (capture && !capture.courante()) {
      fermerLectures(); capture = null; rows = []; fileLisible = false; ciblesContradictoires.clear();
      state = { ...state, affaireId: null, brouillon: { titre: "", corps: "" }, cibleBrouillon: null, intentions: [], intentionId: null };
    }
    return { ...state, enCours: busy || state.enCours };
  }
  function debut() {
    etat(); const c = d.capturerSession();
    if (!c.session || !c.courante()) return null;
    capture = c; const e = epoch;
    return { ...c, courante: () => e === epoch && c.courante() };
  }
  function actualiserConnectivite(v: boolean) { if (online !== v) { online = v; fermerLectures(); } }
  function invaliderLectures() { fermerLectures(); }
  function modifierBrouillon(titre: string, corps: string) {
    etat(); if (!capture?.courante() || busy || pending) return;
    if (typeof titre === "string" && typeof corps === "string") state = { ...state, brouillon: { titre, corps } };
  }
  function serie(): MutationOutbox[] { return rows.filter(m => documentaire(m) && m.chantierId === `document-m10:${state.affaireId}`); }
  function bloquee(): boolean {
    if (!fileLisible) return true;
    return serie().some(m => m.statut !== "envoyee" || !validerRecuDocumentM10(m));
  }
  async function lireFile(courante: () => boolean): Promise<DepotOutbox | null> {
    try {
      const depot = await d.obtenirDepot(); if (!courante()) return null;
      const lus = await depot.lister(); if (!courante()) return null;
      const copie = copierJsonLecture(lus); if (copie === JSON_LECTURE_INVALIDE || !Array.isArray(copie)) throw new Error("file illisible");
      rows = copie as unknown as MutationOutbox[]; fileLisible = true;
      const session = capture?.session;
      const visibles = rows.filter(m => documentaire(m) && session !== null && session !== undefined &&
        verifierDestinationDocumentM10(m, session) && (state.affaireId === null || m.chantierId === `document-m10:${state.affaireId}`));
      state = { ...state, intentions: visibles.map(m => ({ id: m.id, statut: m.statut })) };
      return depot;
    } catch { if (courante()) { fileLisible = false; state = { ...state, intentions: [], message: "intention_incertaine" }; } return null; }
  }
  async function rafraichir(decalage = 0): Promise<void> {
    if (busy) return;
    fermerLectures(); const c = debut(), affaire = state.affaireId;
    if (!c) return;
    state = { ...state, enCours: true };
    await lireFile(c.courante); if (!c.courante()) return;
    if (!affaire || !online || !d.enLigne()) { state = { ...state, enCours: false }; return; }
    let lu: ResultatLectureDocumentAffaireM10<IndexDocumentsAffaireM10> | null;
    try { lu = await d.chargerIndex(affaire, decalage, 1); } catch { lu = indisponible(); }
    if (!c.courante() || !online || !d.enLigne()) return;
    if (lectureEnCache(lu) || (lu?.source === "serveur" && (lu.valeur.affaire_id !== affaire || lu.valeur.decalage !== decalage || lu.valeur.limite !== 1))) lu = indisponible();
    state = { ...state, page: lu, enCours: false, message: lu?.source === "serveur" ? null : "lecture_indisponible" };
  }
  async function ouvrirAffaire(id: string): Promise<void> {
    if (busy || !estAffairePaquetM10Valide(id)) return;
    etat();
    if (pending) {
      const nouvelle = d.capturerSession();
      const argumentsOriginaux = argumentsRpcDocumentM10(pending);
      if (!nouvelle.session || !nouvelle.courante() || !argumentsOriginaux) return;
      const memeDestination = verifierDestinationDocumentM10(pending, nouvelle.session);
      // Une autre identité peut lire une autre affaire, sans reprendre l'intention retenue.
      if (memeDestination ? argumentsOriginaux.affaire_id !== id : argumentsOriginaux.affaire_id === id) return;
      capture = nouvelle;
      if (memeDestination) state = { ...state, affaireId: id, intentionId: pending.id, message: "intention_incertaine" };
    }
    if (state.affaireId !== id) {
      fermerLectures(); state = { ...state, affaireId: id, brouillon: { titre: "", corps: "" }, cibleBrouillon: null, intentions: [], intentionId: null };
      rows = []; fileLisible = false;
    }
    await rafraichir();
  }
  async function suite(): Promise<void> {
    const s = etat(); if (s.page?.source === "serveur" && s.page.valeur.suivant_decalage !== null) await rafraichir(s.page.valeur.suivant_decalage);
  }
  async function selectionner(ligne: LigneIndexDocumentM10): Promise<void> {
    const s = etat(), c = debut();
    if (!c?.session || busy || (pending && verifierDestinationDocumentM10(pending, c.session)) || !online || !d.enLigne() || s.page?.source !== "serveur" ||
        !s.page.valeur.versions.some(v => identique(v, ligne))) return;
    const n = ++demandeDetail;
    const memeCible = identique(state.cibleBrouillon, ligne.document_ref);
    const cible = JSON.stringify([ligne.affaire_id, ligne.document_ref]);
    state = { ...state, selection: ciblesContradictoires.has(cible) ? null : ligne, detail: null, cibleBrouillon: ligne.document_ref,
      brouillon: memeCible ? state.brouillon : { titre: "", corps: "" } };
    if (ligne.statut === "RETIREE") return;
    let lu: ResultatLectureDocumentAffaireM10<VersionDocumentAffaireM10> | null;
    try { lu = await d.chargerVersion(ligne.affaire_id, ligne.document_ref, ligne.version_source); } catch { lu = indisponible(); }
    if (!c.courante() || n !== demandeDetail || !online || !d.enLigne()) return;
    if (lectureEnCache(lu)) lu = indisponible();
    if (lu?.source === "serveur" && (lu.valeur.affaire_id !== ligne.affaire_id ||
        !identique(lu.valeur.document_ref, ligne.document_ref) || !identique(lu.valeur.version_source, ligne.version_source) ||
        !memeSourceVersion(ligne, lu.valeur))) {
      ciblesContradictoires.add(cible);
      state = { ...state, selection: null, detail: indisponible() };
      return;
    }
    // Une panne ne réhabilite pas une cible contredite ; seule sa relecture cohérente le fait.
    if (lu?.source === "serveur") {
      ciblesContradictoires.delete(cible);
      state = { ...state, selection: ligne };
    }
    if (lu?.source === "serveur" && lu.valeur.statut === "RETIREE") state = { ...state, page: null, selection: null, detail: lu };
    else state = { ...state, detail: lu };
  }
  function nouveauDocument() { if (!busy && !pending) { ++demandeDetail; state = { ...etat(), selection: null, detail: null, cibleBrouillon: null }; } }
  function disponible(op: OperationDocumentM10): boolean {
    const s = etat(), c = d.capturerSession();
    return !busy && !pending && online && d.enLigne() && c.session !== null && c.courante() && capture?.courante() === true &&
      s.affaireId !== null && s.page?.source === "serveur" && !bloquee() &&
      (op === "deposer" ? s.selection?.statut !== "RETIREE" &&
        (s.cibleBrouillon === null || (s.selection !== null && identique(s.selection.document_ref, s.cibleBrouillon))) :
        s.selection !== null && s.selection.statut !== "RETIREE");
  }
  async function envoyerPending() {
    const c = debut(), intention = pending;
    if (!c?.session || !intention || !verifierDestinationDocumentM10(intention, c.session) || !online || !d.enLigne()) return { ok: false as const, code: "action_indisponible" };
    busy = true;
    const courante = () => c.courante() && online && d.enLigne();
    try {
      const depot = await d.obtenirDepot(); if (!courante()) return { ok: false as const, code: "identite_changee" };
      let persistee = await depot.obtenir(intention.id); if (!courante()) return { ok: false as const, code: "identite_changee" };
      const file = copierJsonLecture(await depot.lister());
      if (!courante()) return { ok: false as const, code: "identite_changee" };
      if (file === JSON_LECTURE_INVALIDE || !Array.isArray(file)) throw new Error("file illisible");
      rows = file as unknown as MutationOutbox[]; fileLisible = true;
      // La série vient de l'intention originale, même après fermeture de l'affaire affichée.
      const nonTerminees = rows.filter(m => documentaire(m) && m.chantierId === intention.chantierId &&
        (m.statut !== "envoyee" || !validerRecuDocumentM10(m)));
      if (!persistee && nonTerminees.length > 0) throw new Error("série déjà engagée");
      if (persistee && nonTerminees.length > 0) {
        if (nonTerminees.some(m => m.sequence === null || !Number.isSafeInteger(m.sequence) || m.sequence < 1) ||
            new Set(nonTerminees.map(m => m.sequence)).size !== nonTerminees.length ||
            nonTerminees.slice().sort((a,b) => a.sequence! - b.sequence!)[0].id !== intention.id) throw new Error("série bloquée");
      }
      if (!persistee) persistee = await depot.inserer(intention);
      if (!courante()) return { ok: false as const, code: "identite_changee" };
      if (!memeIntention(intention, persistee) || !argumentsRpcDocumentM10(persistee)) throw new Error("intention différente");
      state = { ...state, intentionId: intention.id, message: "intention_incertaine" };
      try { await d.vidanger(courante); } catch { /* Seul le reçu durable décide. */ }
      if (!courante()) return { ok: false as const, code: "identite_changee" };
      const relue = await depot.obtenir(intention.id); if (!courante()) return { ok: false as const, code: "identite_changee" };
      const confirmee = relue !== null && memeIntention(intention, relue) && relue.statut === "envoyee" && validerRecuDocumentM10(relue);
      await lireFile(courante); if (!courante()) return { ok: false as const, code: "identite_changee" };
      if (confirmee) { pending = null; state = { ...state, message: "confirmation_recue" }; }
      return { ok: confirmee, code: confirmee ? "confirmation_recue" : "intention_incertaine" };
    } catch { if (courante()) state = { ...state, intentionId: intention.id, message: "intention_incertaine" }; return { ok: false as const, code: "intention_incertaine" }; }
    finally { busy = false; }
  }
  async function soumettre(op: OperationDocumentM10) {
    if (!disponible(op)) return { ok: false as const, code: "action_indisponible" };
    const s = etat(), c = d.capturerSession(); if (!c.session) return { ok: false as const, code: "action_indisponible" };
    const ligne = s.selection;
    const args = op === "deposer" ? { affaire_id: s.affaireId, document_ref: ligne?.document_ref ?? null,
      version_precedente: ligne?.version_precedente_attendue ?? null, titre: s.brouillon.titre, corps: s.brouillon.corps, confidentialite: "INTERNAL" } :
      op === "activer" ? { affaire_id: s.affaireId, document_ref: ligne?.document_ref, version_source: ligne?.version_source, activation_attendue: ligne?.activation_attendue } :
        { affaire_id: s.affaireId, document_ref: ligne?.document_ref, activation_attendue: ligne?.activation_attendue, code_motif: "RETRAIT_ACCES" };
    try { pending = creerMutationDocumentM10(op, args, d.genererId, d.horloge(), c.session); }
    catch { return { ok: false as const, code: "action_indisponible" }; }
    // Avant tout await : l'objet original/UUID est retenu et les anciennes lectures sont invalidées.
    fermerLectures(); state = { ...state, intentionId: pending.id, message: "intention_incertaine" };
    return envoyerPending();
  }
  async function reprendre() {
    if (busy) return { ok: false as const, code: "action_indisponible" };
    if (pending) return envoyerPending();
    busy = true;
    try {
    const c = debut(); if (!c?.session || !online || !d.enLigne()) return { ok: false as const, code: "action_indisponible" };
    const depot = await lireFile(c.courante); if (!depot || !c.courante()) return { ok: false as const, code: "intention_incertaine" };
    const candidates = serie().filter(m => m.statut !== "envoyee" || !validerRecuDocumentM10(m));
    if (!candidates.length) return { ok: false as const, code: "action_indisponible" };
    if (candidates.some(m => m.sequence === null || !Number.isSafeInteger(m.sequence) || m.sequence < 1) || new Set(candidates.map(m => m.sequence)).size !== candidates.length) return { ok: false as const, code: "intention_incertaine" };
    const premier = candidates.slice().sort((a,b) => a.sequence! - b.sequence!)[0];
    if ((premier.statut !== "en_attente" && premier.statut !== "envoi") || !argumentsRpcDocumentM10(premier) || !verifierDestinationDocumentM10(premier, c.session)) return { ok: false as const, code: "intention_incertaine" };
    pending = premier; fermerLectures(); return await envoyerPending();
    } finally { busy = false; }
  }
  return { etat, actualiserConnectivite, invaliderLectures, modifierBrouillon, ouvrirAffaire, rafraichir, suite,
    selectionner, nouveauDocument, disponible, soumettre, reprendre };
}
