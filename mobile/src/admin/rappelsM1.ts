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
import { identifiantTransfertM1Valide } from "../m1/contrat";
import {
  OUTIL_LISTE_RAPPELS_M1, construireArgumentsRappelsM1, lireRappelsM1, figerArgumentsPriseRappelM1,
  creerMutationPriseRappelM1, validerRecuPriseRappelM1, verifierDestinationPriseRappelM1,
} from "../m1/rappelsAppareil";
import type { ArgumentsPriseRappelM1, PageRappelsM1 } from "../m1/rappelsAppareil";
export interface DependancesRappelsM1 {
  readonly capturerSession: () => { readonly session: SessionEnvoi | null; readonly courante: () => boolean };
  readonly capturerReseau: () => { readonly enLigne: boolean; readonly courante: () => boolean };
  readonly appelerOutil: (params: ParametresAppelOutil) => Promise<ResultatAppelOutil>;
  readonly fetchImpl: typeof fetch; readonly horloge: () => Date; readonly decalageMinutesUTC: () => number;
  readonly obtenirDepot: () => Promise<DepotOutbox>; readonly genererId: () => string;
  readonly declencher: (courante: () => boolean) => Promise<unknown>;
}
export type EtatIntentionRappelM1 =
  | { readonly genre: "en_attente" | "confirmee" | "refusee"; readonly mutation: MutationOutbox }
  | { readonly genre: "aucune" | "indisponible" | "quarantaine" };
const aucune = (code: string) => ({ source: "aucune" as const, raison: { code, detail: "" } });
const bloque = (m: MutationOutbox) => m.statut !== "echec_permanent" && (m.statut !== "envoyee" || !validerRecuPriseRappelM1(m));
const duRappel = (m: MutationOutbox, transfert: string) => m.type === "prise_en_charge_rappel" && m.chantierId === `rappel:${transfert}`;
function sessionCopie(brut: unknown): SessionEnvoi | null {
  const c = copierJsonLecture(brut);
  return c !== JSON_LECTURE_INVALIDE && c !== null && typeof c === "object" && !Array.isArray(c) &&
    ["urlBase", "jeton", "appareilId", "personne"].every(k => typeof c[k] === "string" && c[k] !== "") ? c as unknown as SessionEnvoi : null;
}
async function lignes(depot: DepotOutbox, transfert: string): Promise<MutationOutbox[]> {
  const c = copierJsonLecture(await depot.lister()); if (!Array.isArray(c)) throw new Error("File locale illisible.");
  return (c as unknown as MutationOutbox[]).filter(m => duRappel(m, transfert)).sort((a, b) => (a.sequence ?? -1) - (b.sequence ?? -1));
}
function etat(m: MutationOutbox): EtatIntentionRappelM1 { return { genre: bloque(m) ? "en_attente" : m.statut === "envoyee" ? "confirmee" : "refusee", mutation: m }; }
/** File de rappels sans cache ; seul l'UUID et son corps local sont persistés dans l'outbox existante. */
export function creerChargeurRappelsM1(d: DependancesRappelsM1) {
  const verrous = new Map<string, Promise<void>>();
  async function serialiser(id: string, action: () => Promise<EtatIntentionRappelM1>): Promise<EtatIntentionRappelM1> {
    const p = (verrous.get(id) ?? Promise.resolve()).then(action), fini = p.then(() => undefined, () => undefined); verrous.set(id, fini);
    try { return await p; } finally { if (verrous.get(id) === fini) verrous.delete(id); }
  }
  async function charger(apresTransfertId: string | null = null, taillePage = 8): Promise<ResultatSection<PageRappelsM1> | null> {
    let args; try { args = construireArgumentsRappelsM1(apresTransfertId, taillePage); } catch { return aucune("lecture_indisponible"); }
    const capture = d.capturerSession(), session = sessionCopie(capture.session), reseau = d.capturerReseau();
    if (!session) return null;
    const courante = () => capture.courante() && reseau.courante();
    if (!reseau.enLigne) return aucune("hors_ligne"); if (!courante()) return aucune("lecture_remplacee");
    try {
      const r = await appelerLecture({ appelerOutil: d.appelerOutil, fetchImpl: d.fetchImpl, urlBase: session.urlBase, jeton: session.jeton }, OUTIL_LISTE_RAPPELS_M1, { ...args });
      if (!courante()) return aucune("lecture_remplacee");
      if (r.genre !== "reponse") return r.genre === "refuse" ? { source: "refus", verdict: r.verdict } : { source: "aucune", raison: r.verdict };
      const lu = lireRappelsM1(r.resultat, args); if (!courante()) return aucune("lecture_remplacee");
      if (!lu.ok) return ["reponse_illisible", "reponse_tronquee", ...ERREURS_PASSAGERES].includes(lu.code) ?
        { source: "aucune", raison: { code: lu.code, detail: lu.detail } } : { source: "refus", verdict: { code: lu.code, detail: lu.detail } };
      return courante() ? { source: "serveur", valeur: lu.value, misAJourLe: d.horloge().toISOString() } : aucune("lecture_remplacee");
    } catch { return aucune(courante() ? "lecture_indisponible" : "lecture_remplacee"); }
  }
  async function lireIntention(transfertId: string): Promise<EtatIntentionRappelM1> {
    const capture = d.capturerSession(), session = sessionCopie(capture.session);
    if (!identifiantTransfertM1Valide(transfertId) || !session || !capture.courante()) return { genre: "indisponible" };
    try {
      const depot = await d.obtenirDepot(); if (!capture.courante()) return { genre: "indisponible" };
      const toutes = await lignes(depot, transfertId); if (!capture.courante()) return { genre: "indisponible" };
      const attente = toutes.find(bloque);
      if (attente) return verifierDestinationPriseRappelM1(attente, session) ? etat(attente) : { genre: "quarantaine" };
      const propres = toutes.filter(m => m.proprietaire === session.personne); return propres.length ? etat(propres[propres.length - 1]) : { genre: "aucune" };
    } catch { return { genre: "indisponible" }; }
  }
  async function envoyer(depot: DepotOutbox, m: MutationOutbox, session: SessionEnvoi, courante: () => boolean): Promise<EtatIntentionRappelM1> {
    if (!verifierDestinationPriseRappelM1(m, session)) return { genre: "quarantaine" };
    if (!courante()) return { genre: "indisponible" };
    try { await d.declencher(courante); } catch { /* La ligne durable reste la seule intention à relire. */ }
    if (!courante()) return { genre: "indisponible" };
    const actuelle = await depot.obtenir(m.id); return courante() ? etat(actuelle ?? m) : { genre: "indisponible" };
  }
  async function soumettre(args: ArgumentsPriseRappelM1, couranteExterne = () => true): Promise<EtatIntentionRappelM1> {
    const saisie = figerArgumentsPriseRappelM1(args), capture = d.capturerSession(), session = sessionCopie(capture.session), reseau = d.capturerReseau();
    const courante = () => capture.courante() && reseau.courante() && couranteExterne();
    if (!saisie || !session || !reseau.enLigne || !courante()) return { genre: "indisponible" };
    return serialiser(saisie.transfert_id, async () => {
      try {
        if (!courante()) return { genre: "indisponible" };
        const depot = await d.obtenirDepot(); if (!courante()) return { genre: "indisponible" };
        const toutes = await lignes(depot, saisie.transfert_id); if (!courante()) return { genre: "indisponible" };
        const attente = toutes.find(bloque); if (attente) return envoyer(depot, attente, session, courante);
        const m = creerMutationPriseRappelM1(saisie, d.genererId, { maintenant: d.horloge(), decalageMinutesUTC: d.decalageMinutesUTC() }, session);
        // La personne et la destination copiées avant les awaits ne sont jamais réattribuées.
        const inseree = await depot.inserer({ ...m, proprietaire: session.personne });
        return envoyer(depot, inseree, session, courante);
      } catch { return { genre: "indisponible" }; }
    });
  }
  async function reprendre(transfertId: string, couranteExterne = () => true): Promise<EtatIntentionRappelM1> {
    const capture = d.capturerSession(), session = sessionCopie(capture.session), reseau = d.capturerReseau();
    const courante = () => capture.courante() && reseau.courante() && couranteExterne();
    if (!identifiantTransfertM1Valide(transfertId) || !session || !reseau.enLigne || !courante()) return { genre: "indisponible" };
    return serialiser(transfertId, async () => {
      try {
        const depot = await d.obtenirDepot(); if (!courante()) return { genre: "indisponible" };
        const toutes = await lignes(depot, transfertId); if (!courante()) return { genre: "indisponible" };
        const attente = toutes.find(bloque); return attente ? envoyer(depot, attente, session, courante) : { genre: "aucune" };
      } catch { return { genre: "indisponible" }; }
    });
  }
  return { charger, soumettre, lireIntention, reprendre };
}
let enLigne = false, generationReseau = 0;
export function actualiserConnectiviteRappelsM1(v: boolean): void { if (v !== enLigne) generationReseau++; enLigne = v; }
const service = creerChargeurRappelsM1({ capturerSession: capturerSessionAdminLecture,
  capturerReseau: () => { const n = generationReseau; return { enLigne, courante: () => enLigne && n === generationReseau }; },
  appelerOutil: invoquerOutil, fetchImpl: fetch, horloge: () => new Date(), decalageMinutesUTC: () => -new Date().getTimezoneOffset(),
  obtenirDepot, genererId: genererMutationId, declencher: declencherVidange });
export const chargerRappelsM1 = service.charger;
export const soumettrePriseRappelM1 = service.soumettre;
export const lireIntentionRappelM1 = service.lireIntention;
export const reprendrePriseRappelM1 = service.reprendre;
