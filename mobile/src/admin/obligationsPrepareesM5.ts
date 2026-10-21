import { appelerLecture } from "./appel";
import type { ResultatSection } from "./lecture";
import { invoquerOutil } from "../protocole/client";
import type { ParametresAppelOutil, ResultatAppelOutil } from "../protocole/client";
import { capturerSessionAdminLecture } from "../protocole/configuration";
import type { SessionEnvoi } from "../protocole/configuration";
import { ERREURS_PASSAGERES } from "../protocole/enveloppeOutil";
import { copierJsonLecture, JSON_LECTURE_INVALIDE } from "../protocole/jsonLecture";
import { obtenirDepot, declencherVidange } from "../outbox/service";
import type { DepotOutbox } from "../outbox/depot";
import type { MutationOutbox } from "../outbox/types";
import { genererMutationId } from "../outbox/id";
import {
  OUTIL_OBLIGATIONS_PREPAREES, construireArgumentsObligations, lireObligationsPreparees, figerArgumentsDeclarationObligation,
  creerMutationObligationPreparee, validerRecuObligationPreparee, verifierDestinationObligationPreparee, CATEGORIES_OBLIGATIONS,
} from "../m5/obligationsPreparees";
import type { ArgumentsDeclarationObligation, PageObligationsPreparees } from "../m5/obligationsPreparees";
export interface DependancesObligationsM5 {
  readonly capturerSession: () => { readonly session: SessionEnvoi | null; readonly courante: () => boolean };
  readonly capturerReseau: () => { readonly enLigne: boolean; readonly courante: () => boolean };
  readonly appelerOutil: (params: ParametresAppelOutil) => Promise<ResultatAppelOutil>;
  readonly fetchImpl: typeof fetch; readonly horloge: () => Date; readonly decalageMinutesUTC: () => number;
  readonly obtenirDepot: () => Promise<DepotOutbox>; readonly genererId: () => string;
  readonly declencher: (courante: () => boolean) => Promise<unknown>;
}
export type EtatIntentionObligationM5 =
  | { readonly genre: "en_attente" | "confirmee" | "refusee"; readonly mutation: MutationOutbox }
  | { readonly genre: "aucune" | "indisponible" | "quarantaine" };
const categorieValide = (v: string) => (CATEGORIES_OBLIGATIONS as readonly string[]).includes(v);
const aucune = (code: string) => ({ source: "aucune" as const, raison: { code, detail: "" } });
const bloque = (m: MutationOutbox) => m.statut !== "echec_permanent" && (m.statut !== "envoyee" || !validerRecuObligationPreparee(m));
const deLaCategorie = (m: MutationOutbox, categorie: string) => m.type === "obligation_preparee" && m.chantierId === `obligation-m5:${categorie}`;
function sessionCopie(brut: unknown): SessionEnvoi | null {
  const c = copierJsonLecture(brut);
  return c !== JSON_LECTURE_INVALIDE && c !== null && typeof c === "object" && !Array.isArray(c) &&
    ["urlBase", "jeton", "appareilId", "personne"].every(k => typeof c[k] === "string" && c[k] !== "") ? c as unknown as SessionEnvoi : null;
}
async function lignes(depot: DepotOutbox, categorie: string): Promise<MutationOutbox[]> {
  const c = copierJsonLecture(await depot.lister()); if (!Array.isArray(c)) throw new Error("File locale illisible.");
  return (c as unknown as MutationOutbox[]).filter(m => deLaCategorie(m, categorie)).sort((a, b) => (a.sequence ?? -1) - (b.sequence ?? -1));
}
function etat(m: MutationOutbox): EtatIntentionObligationM5 { return { genre: bloque(m) ? "en_attente" : m.statut === "envoyee" ? "confirmee" : "refusee", mutation: m }; }
/** Lecture courante sans cache et déclaration interne ; aucune activation de cash, YAML ou paiement. */
export function creerChargeurObligationsM5(d: DependancesObligationsM5) {
  const verrous = new Map<string, Promise<void>>();
  async function serialiser(id: string, action: () => Promise<EtatIntentionObligationM5>): Promise<EtatIntentionObligationM5> {
    const p = (verrous.get(id) ?? Promise.resolve()).then(action), fini = p.then(() => undefined, () => undefined); verrous.set(id, fini);
    try { return await p; } finally { if (verrous.get(id) === fini) verrous.delete(id); }
  }
  async function charger(aujourdHui: string, decalage = 0, limite = 1): Promise<ResultatSection<PageObligationsPreparees> | null> {
    let args; try { args = construireArgumentsObligations(aujourdHui, decalage, limite); } catch { return aucune("lecture_indisponible"); }
    const capture = d.capturerSession(), session = sessionCopie(capture.session), reseau = d.capturerReseau();
    if (!session) return null;
    const courante = () => capture.courante() && reseau.courante();
    if (!reseau.enLigne) return aucune("hors_ligne"); if (!courante()) return aucune("lecture_remplacee");
    try {
      const r = await appelerLecture({ appelerOutil: d.appelerOutil, fetchImpl: d.fetchImpl, urlBase: session.urlBase, jeton: session.jeton }, OUTIL_OBLIGATIONS_PREPAREES, { ...args });
      if (!courante()) return aucune("lecture_remplacee");
      if (r.genre !== "reponse") return r.genre === "refuse" ? { source: "refus", verdict: r.verdict } : { source: "aucune", raison: r.verdict };
      const lu = lireObligationsPreparees(r.resultat, args); if (!courante()) return aucune("lecture_remplacee");
      if (!lu.ok) return ["reponse_illisible", "reponse_tronquee", ...ERREURS_PASSAGERES].includes(lu.code) ?
        { source: "aucune", raison: { code: lu.code, detail: lu.detail } } : { source: "refus", verdict: { code: lu.code, detail: lu.detail } };
      return courante() ? { source: "serveur", valeur: lu.value, misAJourLe: d.horloge().toISOString() } : aucune("lecture_remplacee");
    } catch { return aucune(courante() ? "lecture_indisponible" : "lecture_remplacee"); }
  }
  async function lireIntention(categorie: string): Promise<EtatIntentionObligationM5> {
    const capture = d.capturerSession(), session = sessionCopie(capture.session);
    if (!categorieValide(categorie) || !session || !capture.courante()) return { genre: "indisponible" };
    try {
      const depot = await d.obtenirDepot(); if (!capture.courante()) return { genre: "indisponible" };
      const toutes = await lignes(depot, categorie); if (!capture.courante()) return { genre: "indisponible" };
      const attente = toutes.find(bloque);
      if (attente) return verifierDestinationObligationPreparee(attente, session) ? etat(attente) : { genre: "quarantaine" };
      const propres = toutes.filter(m => m.proprietaire === session.personne); return propres.length ? etat(propres[propres.length - 1]) : { genre: "aucune" };
    } catch { return { genre: "indisponible" }; }
  }
  async function envoyer(depot: DepotOutbox, m: MutationOutbox, session: SessionEnvoi, courante: () => boolean): Promise<EtatIntentionObligationM5> {
    if (!verifierDestinationObligationPreparee(m, session)) return { genre: "quarantaine" };
    if (!courante()) return { genre: "indisponible" };
    try { await d.declencher(courante); } catch { /* La ligne durable reste la seule intention à relire. */ }
    if (!courante()) return { genre: "indisponible" };
    const actuelle = await depot.obtenir(m.id); return courante() ? etat(actuelle ?? m) : { genre: "indisponible" };
  }
  async function soumettre(args: ArgumentsDeclarationObligation, couranteExterne = () => true): Promise<EtatIntentionObligationM5> {
    const saisie = figerArgumentsDeclarationObligation(args), capture = d.capturerSession(), session = sessionCopie(capture.session), reseau = d.capturerReseau();
    const courante = () => capture.courante() && reseau.courante() && couranteExterne();
    if (!saisie || !session || !reseau.enLigne || !courante()) return { genre: "indisponible" };
    return serialiser(saisie.categorie, async () => {
      try {
        if (!courante()) return { genre: "indisponible" };
        const depot = await d.obtenirDepot(); if (!courante()) return { genre: "indisponible" };
        const toutes = await lignes(depot, saisie.categorie); if (!courante()) return { genre: "indisponible" };
        const attente = toutes.find(bloque); if (attente) return envoyer(depot, attente, session, courante);
        const m = creerMutationObligationPreparee(saisie, d.genererId, { maintenant: d.horloge(), decalageMinutesUTC: d.decalageMinutesUTC() }, session);
        // La personne et la destination copiées avant les awaits ne sont jamais réattribuées.
        const inseree = await depot.inserer({ ...m, proprietaire: session.personne });
        return envoyer(depot, inseree, session, courante);
      } catch { return { genre: "indisponible" }; }
    });
  }
  async function reprendre(categorie: string, couranteExterne = () => true): Promise<EtatIntentionObligationM5> {
    const capture = d.capturerSession(), session = sessionCopie(capture.session), reseau = d.capturerReseau();
    const courante = () => capture.courante() && reseau.courante() && couranteExterne();
    if (!categorieValide(categorie) || !session || !reseau.enLigne || !courante()) return { genre: "indisponible" };
    return serialiser(categorie, async () => {
      try {
        const depot = await d.obtenirDepot(); if (!courante()) return { genre: "indisponible" };
        const toutes = await lignes(depot, categorie); if (!courante()) return { genre: "indisponible" };
        const attente = toutes.find(bloque); return attente ? envoyer(depot, attente, session, courante) : { genre: "aucune" };
      } catch { return { genre: "indisponible" }; }
    });
  }
  return { charger, soumettre, lireIntention, reprendre };
}
let enLigne = false, generationReseau = 0;
export function actualiserConnectiviteObligationsM5(v: boolean): void { if (v !== enLigne) generationReseau++; enLigne = v; }
const service = creerChargeurObligationsM5({ capturerSession: capturerSessionAdminLecture,
  capturerReseau: () => { const n = generationReseau; return { enLigne, courante: () => enLigne && n === generationReseau }; },
  appelerOutil: invoquerOutil, fetchImpl: fetch, horloge: () => new Date(), decalageMinutesUTC: () => -new Date().getTimezoneOffset(),
  obtenirDepot, genererId: genererMutationId, declencher: declencherVidange });
export const chargerObligationsM5 = service.charger;
export const soumettreObligationM5 = service.soumettre;
export const lireIntentionObligationM5 = service.lireIntention;
export const reprendreObligationM5 = service.reprendre;
