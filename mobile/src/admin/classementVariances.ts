import { appelerLecture } from "./appel";
import type { ResultatSection } from "./lecture";
import { invoquerOutil } from "../protocole/client";
import type { ParametresAppelOutil, ResultatAppelOutil } from "../protocole/client";
import { capturerSessionAdminLecture } from "../protocole/configuration";
import type { SessionEnvoi } from "../protocole/configuration";
import type { Reponse } from "../m7/contrat";
import { obtenirDepot, declencherVidange } from "../outbox/service";
import type { DepotOutbox } from "../outbox/depot";
import type { MutationOutbox } from "../outbox/types";
import { genererMutationId } from "../outbox/id";
import {
  OUTIL_LISTE_VARIANCES, OUTIL_HISTORIQUE_CLASSEMENTS, construireArgumentsListeVariances,
  construireArgumentsHistoriqueClassements, lireVariancesClassables, lireHistoriqueClassements,
  creerMutationClassementVariance, validerRecuClassementVariance, figerArgumentsClassementVariance,
} from "../m6/classementVariance";
import type { ArgumentsClassementVarianceM6, SelectionVarianceM6 } from "../m6/classementVariance";
export interface DependancesClassementVariances {
  readonly capturerSession: () => { readonly session: SessionEnvoi | null; readonly courante: () => boolean };
  readonly capturerReseau: () => { readonly enLigne: boolean; readonly courante: () => boolean };
  readonly appelerOutil: (params: ParametresAppelOutil) => Promise<ResultatAppelOutil>;
  readonly fetchImpl: typeof fetch; readonly horloge: () => Date; readonly decalageMinutesUTC: () => number;
  readonly obtenirDepot: () => Promise<DepotOutbox>; readonly genererId: () => string;
  readonly declencher: (courante: () => boolean) => Promise<unknown>;
}
export type EtatIntentionClassement =
  | { readonly genre: "en_attente" | "confirmee" | "refusee"; readonly mutation: MutationOutbox }
  | { readonly genre: "aucune" | "indisponible" | "quarantaine" };
const aucune = (code: string) => ({ source: "aucune" as const, raison: { code, detail: "" } });
const estDuWct = (m: MutationOutbox, wct: string) => m.type === "variance_cause_classification" && m.chantierId === `variance:${wct}`;
const bloque = (m: MutationOutbox) => m.statut !== "echec_permanent" && (m.statut !== "envoyee" || !validerRecuClassementVariance(m));
function etat(m: MutationOutbox): EtatIntentionClassement {
  return { genre: bloque(m) ? "en_attente" : m.statut === "envoyee" ? "confirmee" : "refusee", mutation: m };
}
/** Pages courantes sans cache. Toute intention enregistrée reste liée à sa personne et son UUID. */
export function creerServiceClassementVariances(d: DependancesClassementVariances) {
  const verrous = new Map<string, Promise<void>>();
  async function lire<T>(outil: string, args: Readonly<Record<string, unknown>>, parser: (v: unknown) => Reponse<T>): Promise<ResultatSection<T> | null> {
    const capture = d.capturerSession(), reseau = d.capturerReseau(), session = capture.session;
    if (!session) return null;
    const courante = () => capture.courante() && reseau.courante();
    if (!reseau.enLigne || !courante()) return aucune("hors_ligne");
    try {
      const r = await appelerLecture({ appelerOutil: d.appelerOutil, fetchImpl: d.fetchImpl, urlBase: session.urlBase, jeton: session.jeton }, outil, args);
      if (!courante()) return aucune("lecture_remplacee");
      if (r.genre !== "reponse") return r.genre === "refuse" ? { source: "refus", verdict: r.verdict } : { source: "aucune", raison: r.verdict };
      const lu = parser(r.resultat);
      if (!courante()) return aucune("lecture_remplacee");
      if (!lu.ok) return lu.code === "reponse_illisible" || lu.code === "reponse_tronquee" ?
        { source: "aucune", raison: { code: lu.code, detail: lu.detail } } : { source: "refus", verdict: { code: lu.code, detail: lu.detail } };
      return courante() ? { source: "serveur", valeur: lu.value, misAJourLe: d.horloge().toISOString() } : aucune("lecture_remplacee");
    } catch { return aucune(courante() ? "lecture_indisponible" : "lecture_remplacee"); }
  }
  async function lireIntention(wct: string): Promise<EtatIntentionClassement> {
    const capture = d.capturerSession(); if (!capture.session || !capture.courante()) return { genre: "indisponible" };
    try {
      const depot = await d.obtenirDepot(); if (!capture.courante()) return { genre: "indisponible" };
      const toutes = (await depot.lister()).filter(m => estDuWct(m, wct));
      if (!capture.courante()) return { genre: "indisponible" };
      if (toutes.some(m => bloque(m) && m.proprietaire !== capture.session!.personne)) return { genre: "quarantaine" };
      const propres = toutes.filter(m => m.proprietaire === capture.session!.personne).sort((a, b) => (b.sequence ?? -1) - (a.sequence ?? -1));
      const attente = propres.find(bloque); return attente ? etat(attente) : propres[0] ? etat(propres[0]) : { genre: "aucune" };
    } catch { return { genre: "indisponible" }; }
  }
  async function soumettre(args: ArgumentsClassementVarianceM6, couranteExterne = () => true): Promise<EtatIntentionClassement> {
    const saisie = figerArgumentsClassementVariance(args); if (!saisie) return { genre: "indisponible" };
    const capture = d.capturerSession(), reseau = d.capturerReseau(), session = capture.session;
    const courante = () => capture.courante() && reseau.courante() && couranteExterne();
    if (!session || !reseau.enLigne || !courante()) return { genre: "indisponible" };
    const cle = JSON.stringify([session.personne, saisie.selection.wct_id]);
    const operation = (verrous.get(cle) ?? Promise.resolve()).then(async (): Promise<EtatIntentionClassement> => {
      try {
        if (!courante()) return { genre: "indisponible" };
        const depot = await d.obtenirDepot(); if (!courante()) return { genre: "indisponible" };
        const toutes = (await depot.lister()).filter(m => estDuWct(m, saisie.selection.wct_id));
        if (!courante()) return { genre: "indisponible" };
        const attente = toutes.find(bloque);
        if (attente) return attente.proprietaire === session.personne ? etat(attente) : { genre: "quarantaine" };
        const m = creerMutationClassementVariance(saisie, d.genererId, { maintenant: d.horloge(), decalageMinutesUTC: d.decalageMinutesUTC() }, session);
        // La personne est capturée avant les awaits ; un nouvel appairage ne réattribue pas l'intention.
        const inseree = await depot.inserer({ ...m, proprietaire: session.personne });
        if (!courante()) return { genre: "indisponible" };
        try { await d.declencher(courante); } catch { /* L'intention durable reste à relire. */ }
        if (!courante()) return { genre: "indisponible" };
        return etat(await depot.obtenir(inseree.id) ?? inseree);
      } catch { return { genre: "indisponible" }; }
    });
    const termine = operation.then(() => undefined); verrous.set(cle, termine);
    const r = await operation; if (verrous.get(cle) === termine) verrous.delete(cle); return r;
  }
  return {
    chargerVariances: (wct: string, decalage = 0) => {
      const args = construireArgumentsListeVariances(wct, decalage);
      return lire(OUTIL_LISTE_VARIANCES, { ...args }, v => lireVariancesClassables(v, args));
    },
    chargerHistorique: (selection: SelectionVarianceM6, decalage = 0) => {
      const args = construireArgumentsHistoriqueClassements(selection, decalage);
      return lire(OUTIL_HISTORIQUE_CLASSEMENTS, { ...args }, v => lireHistoriqueClassements(v, args));
    },
    soumettre, lireIntention,
  };
}
let connectee = false, generation = 0;
export function actualiserConnectiviteClassementM6(v: boolean): void { if (v !== connectee) generation++; connectee = v; }
const service = creerServiceClassementVariances({
  capturerSession: capturerSessionAdminLecture,
  capturerReseau: () => { const n = generation; return { enLigne: connectee, courante: () => connectee && n === generation }; },
  appelerOutil: invoquerOutil, fetchImpl: fetch, horloge: () => new Date(), decalageMinutesUTC: () => -new Date().getTimezoneOffset(),
  obtenirDepot, genererId: genererMutationId, declencher: declencherVidange,
});
export const chargerVariancesClassablesM6 = service.chargerVariances;
export const chargerHistoriqueClassementsM6 = service.chargerHistorique;
export const soumettreClassementVarianceM6 = service.soumettre;
export const lireIntentionClassementM6 = service.lireIntention;
