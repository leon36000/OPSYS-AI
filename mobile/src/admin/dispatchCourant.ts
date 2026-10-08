import type { HorlogeAppareil } from "../outbox/mutation";
import type { ParametresAppelOutil, ResultatAppelOutil } from "../protocole/client";
import type { SessionEnvoi } from "../protocole/configuration";
import { ERREURS_PASSAGERES, VERDICT_REPONSE_ILLISIBLE } from "../protocole/enveloppeOutil";
import type { DepotCleValeur } from "../stockage/depotCleValeur";
import { depotSousGardeLecture, commencerTransitionCaches } from "../stockage/lecturesEnVol";
import { copierJsonDispatch, JSON_DISPATCH_INVALIDE, lireDigest, lirePreparation, objetDispatch, clesDispatch, horodatageDispatch, hashDispatch, dateCivileDispatch, STATUTS_DU_DISPATCH } from "../m4/dispatch";
import type { DigestDuJour, Preparation } from "../m4/dispatch";
import { construireArgumentsPageDispatch, lirePageDispatch, OUTIL_LISTER_INTERVENTIONS } from "../m4/paginationDispatch";
import type { PageDispatch } from "../m4/paginationDispatch";
import { construireArgumentsMeteoIntervention, lireMeteoIntervention, OUTIL_LIRE_METEO_INTERVENTION } from "../m4/meteoIntervention";
import type { MeteoIntervention } from "../m4/meteoIntervention";
import { construireArgumentsRetardsIncidents, lireRetardsIncidents, OUTIL_LIRE_RETARDS_INCIDENTS } from "../m4/retardsIncidents";
import type { RetardsIncidents } from "../m4/retardsIncidents";
import { appelerLecture } from "./appel";
import { ecrireCacheSection } from "./cache";
import { interpreter } from "./enveloppe";
import type { FormeReponse, LectureSection } from "./enveloppe";
import { instantLocal, jourLocal } from "./horloge";
import { lireSection } from "./lecture";
import type { DefinitionSection, ResultatSection } from "./lecture";

export interface DependancesDispatch {
  /** Capture ADMIN, avant toute ouverture de dépôt ou de transport. */
  readonly capturerSession: () => { session: SessionEnvoi | null; courante: () => boolean };
  readonly obtenirDepot: () => Promise<DepotCleValeur>;
  readonly appelerOutil: (p: ParametresAppelOutil) => Promise<ResultatAppelOutil>;
  readonly fetchImpl: typeof fetch;
  readonly horloge: () => HorlogeAppareil;
  readonly enLigne: () => boolean;
}
const aucune = (code: string): ResultatSection<never> => ({ source: "aucune", raison: { code, detail: "" } });
function propre(v: unknown, cle: string): unknown {
  if (typeof v !== "object" || v === null) return undefined;
  try { const d = Object.getOwnPropertyDescriptor(v, cle); return d && "value" in d ? d.value : undefined; }
  catch { return undefined; }
}

/** Copier toute l'enveloppe AVANT de lire ses propriétés : ni getter ni prototype ne devient une donnée. */
export function interpreterDispatch<T>(brut: unknown, forme: FormeReponse, lire: (v: unknown) => T | null): LectureSection<T> {
  const copie = copierJsonDispatch(brut);
  if (copie === JSON_DISPATCH_INVALIDE) {
    const refusMetier = propre(propre(brut, "resultat"), "accepte") === false;
    const refus = propre(brut, "ok") === false;
    const code = propre(brut, "erreur");
    return { ok: false, genre: refusMetier || refus && !(typeof code === "string" && ERREURS_PASSAGERES.includes(code)) ? "refus" : "illisible",
      verdict: VERDICT_REPONSE_ILLISIBLE };
  }
  if (propre(propre(copie, "resultat"), "accepte") === false && propre(copie, "ok") === false)
    return { ok: false, genre: "refus", verdict: VERDICT_REPONSE_ILLISIBLE };
  return interpreter(copie, forme, lire);
}

function section<T>(outil: string, args: Readonly<Record<string, unknown>>, forme: FormeReponse, lire: (v: unknown) => T | null,
  lireCache?: (v: unknown, argumentsGardes: Record<string, unknown>) => T | null): DefinitionSection<T> {
  const slot = outil === OUTIL_LISTER_INTERVENTIONS ? `${outil}:${args.statut}` : outil;
  return {
    outil, args, cache: `dispatch_courant_borne:${slot}`,
    interpreter: v => interpreterDispatch(v, forme, lire),
    interpreterCache: brut => {
      const copie = copierJsonDispatch(brut);
      if (!objetDispatch(copie) || !clesDispatch(copie, ["arguments", "enveloppe"]) || !objetDispatch(copie.arguments))
        return { ok: false, genre: "illisible", verdict: VERDICT_REPONSE_ILLISIBLE };
      const argumentsGardes = copie.arguments;
      if (!lireCache && JSON.stringify(argumentsGardes) !== JSON.stringify(args))
        return { ok: false, genre: "illisible", verdict: VERDICT_REPONSE_ILLISIBLE };
      return interpreterDispatch(copie.enveloppe, forme, v => lireCache ? lireCache(v, argumentsGardes) : lire(v));
    },
    epurerPourLeCache: v => {
      const lu = interpreterDispatch(v, forme, lire);
      return lu.ok ? { arguments: args, enveloppe: copierJsonDispatch(v) } : null;
    },
  };
}

/** Pages courantes de huit éléments ; aucune accumulation ni promesse de snapshot. Retards : serveur seulement. */
export function creerChargeurDispatch(d: DependancesDispatch) {
  let autorite = "";
  const refusConnus = new Set<string>(), numeros = new Map<string, number>();
  async function charger<T>(definition: DefinitionSection<T>, garder = true): Promise<ResultatSection<T> | null> {
    const c = d.capturerSession(), session = c.session;
    if (!session) return null;
    if (!c.courante()) return aucune("lecture_remplacee");
    const identite = JSON.stringify([session.urlBase, session.appareilId, session.jeton, session.personne]);
    if (autorite !== identite) { autorite = identite; refusConnus.clear(); numeros.clear(); }
    const slot = definition.cache, numero = (numeros.get(slot) ?? 0) + 1;
    numeros.set(slot, numero);
    const courante = () => c.courante() && autorite === identite && numeros.get(slot) === numero;
    const sectionGardee: DefinitionSection<T> = { ...definition, interpreterCache: v => refusConnus.has(slot) ?
      { ok: false, genre: "refus", verdict: VERDICT_REPONSE_ILLISIBLE } : (definition.interpreterCache ?? definition.interpreter)(v) };
    const transport = { appelerOutil: d.appelerOutil, fetchImpl: d.fetchImpl, urlBase: session.urlBase, jeton: session.jeton };
    async function invaliderCopie(depot: DepotCleValeur): Promise<void> {
      try { await ecrireCacheSection(depotSousGardeLecture(depot, courante), session!.personne, slot, null, d.horloge().maintenant.toISOString()); }
      catch { const terminer = commencerTransitionCaches(depot); terminer(false); }
    }
    async function finaliser(lu: ResultatSection<T>, depot: DepotCleValeur | null): Promise<ResultatSection<T>> {
      if (!courante()) return aucune("lecture_remplacee");
      if (garder && lu.source === "refus") {
        refusConnus.add(slot);
        if (depot) await invaliderCopie(depot);
      } else if (lu.source === "serveur") refusConnus.delete(slot);
      return courante() ? lu : aucune("lecture_remplacee");
    }
    async function serveur(): Promise<ResultatSection<T>> {
      if (!d.enLigne()) return aucune("hors_ligne");
      const appel = await appelerLecture(transport, definition.outil, definition.args);
      if (!courante()) return aucune("lecture_remplacee");
      if (appel.genre !== "reponse") return appel.genre === "refuse" ? { source: "refus", verdict: appel.verdict } : { source: "aucune", raison: appel.verdict };
      const lu = definition.interpreter(appel.resultat);
      if (!courante()) return aucune("lecture_remplacee");
      return lu.ok ? { source: "serveur", valeur: lu.valeur, misAJourLe: d.horloge().maintenant.toISOString() } :
        lu.genre === "refus" ? { source: "refus", verdict: lu.verdict } : { source: "aucune", raison: lu.verdict };
    }
    try {
      if (!garder) return await finaliser(await serveur(), null);
      let depot: DepotCleValeur | null;
      try { depot = await d.obtenirDepot(); } catch { depot = null; }
      if (!courante()) return aucune("lecture_remplacee");
      if (!depot) return await finaliser(await serveur(), null);
      // Un refus reçu pendant la panne du dépôt doit devenir durable dès sa réouverture, avant toute copie.
      if (refusConnus.has(slot)) await invaliderCopie(depot);
      if (!courante()) return aucune("lecture_remplacee");
      const vueDepot = depotSousGardeLecture(depot, courante);
      const lu = await lireSection({ ...transport, depot: vueDepot, personne: session.personne,
        horloge: d.horloge, enLigne: d.enLigne }, sectionGardee);
      return await finaliser(lu, depot);
    } catch { return aucune(courante() ? "lecture_indisponible" : "lecture_remplacee"); }
  }
  return {
    chargerPage(statut: string, curseur: string | null = null): Promise<ResultatSection<PageDispatch> | null> {
      if (!STATUTS_DU_DISPATCH.includes(statut) || curseur !== null && !hashDispatch(curseur)) return Promise.resolve(aucune("arguments_invalides"));
      const args = construireArgumentsPageDispatch(statut, curseur, 8);
      return charger(section(OUTIL_LISTER_INTERVENTIONS, { ...args }, "directe", v => lirePageDispatch(v, args)));
    },
    chargerMeteo(id: string, date: string | null = null): Promise<ResultatSection<MeteoIntervention> | null> {
      if (!hashDispatch(id) || date !== null && !dateCivileDispatch(date)) return Promise.resolve(aucune("arguments_invalides"));
      const args = construireArgumentsMeteoIntervention(id, date);
      return charger(section(OUTIL_LIRE_METEO_INTERVENTION, { ...args }, "couple", v => lireMeteoIntervention(v, args)));
    },
    chargerRetards(): Promise<ResultatSection<RetardsIncidents> | null> {
      const reference = instantLocal(d.horloge()), args = construireArgumentsRetardsIncidents(reference);
      return charger(section(OUTIL_LIRE_RETARDS_INCIDENTS, args, "couple", v => lireRetardsIncidents(v, reference)), false);
    },
    chargerDigest(): Promise<ResultatSection<DigestDuJour> | null> {
      const horloge = d.horloge(), date = jourLocal(horloge), reference = instantLocal(horloge);
      return charger(section("m4_produire_digest", { date_cible: date, horodatage_reference: reference }, "couple", v => {
        const lu = lireDigest(v);
        return lu?.dateCible === date && lu.horodatageReference === reference ? lu : null;
      }, (v, gardes) => {
        if (!clesDispatch(gardes, ["date_cible", "horodatage_reference"]) || gardes.date_cible !== date || !horodatageDispatch(gardes.horodatage_reference)) return null;
        const lu = lireDigest(v);
        return lu?.dateCible === date && lu.horodatageReference === gardes.horodatage_reference ? lu : null;
      }));
    },
    chargerPreparation(id: string): Promise<ResultatSection<Preparation> | null> {
      if (!hashDispatch(id)) return Promise.resolve(aucune("arguments_invalides"));
      return charger(section("m4_verifier_preparation", { intervention_id: id }, "couple", v => {
        const lu = lirePreparation(v);
        return lu?.interventionId === id ? lu : null;
      }));
    },
  };
}
