import { appelerLecture } from "../admin/appel";
import type { ConfigurationChargeurAdmin } from "../admin/appel";
import { lireSection } from "../admin/lecture";
import type { ResultatSection } from "../admin/lecture";
import type { LectureSection } from "../admin/enveloppe";
import { ERREURS_PASSAGERES } from "../protocole/enveloppeOutil";
import type { ParametresAppelOutil, ResultatAppelOutil } from "../protocole/client";
import type { SessionEnvoi } from "../protocole/configuration";
import type { DepotCleValeur } from "../stockage/depotCleValeur";
import { depotSousGardeLecture } from "../stockage/lecturesEnVol";
import type { HorlogeAppareil } from "../outbox/mutation";
import type { Reponse } from "../m7/contrat";
import { lireReferencesM10, lireSignauxM10, lireStatutDecisionM10, lireStatutRevisionM10 } from "./contrat";
import { lireDossierRevisionM10 } from "./dossier";
import { construireArgumentsPaquetAffaire, lirePaquetAffaire } from "./paquetAffaire";

export interface DependancesLecturesMemoire {
  readonly capturerSession: () => { readonly session: SessionEnvoi | null; readonly courante: () => boolean };
  readonly obtenirDepot: () => Promise<DepotCleValeur>;
  readonly appelerOutil: (params: ParametresAppelOutil) => Promise<ResultatAppelOutil>;
  readonly fetchImpl: typeof fetch;
  readonly horloge: () => HorlogeAppareil;
  readonly enLigne: () => boolean;
}
const remplacee = () => ({ source: "aucune" as const, raison: { code: "lecture_remplacee", detail: "" } });
const indisponible = () => ({ source: "aucune" as const, raison: { code: "lecture_indisponible", detail: "" } });
const horsLigne = () => ({ source: "aucune" as const, raison: { code: "hors_ligne", detail: "" } });
function valeurPropre(v: unknown, cle: string): unknown {
  if (typeof v !== "object" || v === null) return undefined;
  try { const d = Object.getOwnPropertyDescriptor(v, cle); return d && "value" in d ? d.value : undefined; } catch { return undefined; }
}
function adaptation<T>(brut: unknown, lecteur: (v: unknown) => Reponse<T>): LectureSection<T> {
  const r = lecteur(brut);
  if (r.ok) return { ok: true, valeur: r.value };
  // Même un refus dont le verdict est illisible n'autorise pas à relire un cache ancien.
  const refusExplicite = valeurPropre(brut, "ok") === false || valeurPropre(valeurPropre(brut, "resultat"), "accepte") === false;
  const genre = refusExplicite && !ERREURS_PASSAGERES.includes(r.code) ? "refus" :
    r.code === "reponse_illisible" ? "illisible" :
    r.code === "reponse_tronquee" || ERREURS_PASSAGERES.includes(r.code) ? "technique" : "refus";
  return { ok: false, genre, verdict: { code: r.code, detail: r.detail } };
}

/** Les caches n'ont que les projections informatives ; les faits et statuts n'y entrent jamais. */
export function creerChargeurLecturesMemoire(d: DependancesLecturesMemoire) {
  async function lire<T>(outil: string, args: Record<string, unknown>, lecteur: (v: unknown) => Reponse<T>, cache?: string, couple = false): Promise<ResultatSection<T> | null> {
    const capture = d.capturerSession(), session = capture.session;
    if (!session) return null;
    if (!capture.courante()) return remplacee();
    const enveloppe = (valeur: T) => ({ ok: true, resultat: couple ? { accepte: true, resultat: valeur } : valeur });
    try {
      if (cache) {
        let depot: DepotCleValeur | null;
        try { depot = await d.obtenirDepot(); } catch { depot = null; }
        if (!capture.courante()) return remplacee();
        if (depot) {
          const config: ConfigurationChargeurAdmin = { depot: depotSousGardeLecture(depot, capture.courante),
            appelerOutil: d.appelerOutil, fetchImpl: d.fetchImpl, urlBase: session.urlBase, jeton: session.jeton,
            personne: session.personne, horloge: d.horloge, enLigne: d.enLigne };
          const result = await lireSection(config, { outil, args, cache, interpreter: v => adaptation(v, lecteur),
            epurerPourLeCache: v => { const lu = lecteur(v); return lu.ok ? enveloppe(lu.value) : undefined; } });
          return capture.courante() ? result : remplacee();
        }
      }
      if (!d.enLigne()) return horsLigne();
      // Pas besoin de démarrer SQLite pour une lecture sans cache.
      const config = { appelerOutil: d.appelerOutil, fetchImpl: d.fetchImpl, urlBase: session.urlBase, jeton: session.jeton };
      const appel = await appelerLecture(config, outil, args);
      if (!capture.courante()) return remplacee();
      if (appel.genre !== "reponse") return appel.genre === "refuse" ? { source: "refus", verdict: appel.verdict } : { source: "aucune", raison: appel.verdict };
      const lu = adaptation(appel.resultat, lecteur);
      if (!capture.courante()) return remplacee();
      return lu.ok ? { source: "serveur", valeur: lu.valeur, misAJourLe: d.horloge().maintenant.toISOString() } :
        lu.genre === "refus" ? { source: "refus", verdict: lu.verdict } : { source: "aucune", raison: lu.verdict };
    } catch { return capture.courante() ? indisponible() : remplacee(); }
  }
  return {
    chargerPaquetAffaire: async (affaireId: string, horodatage: string) => {
      let args: { affaire_id: string; horodatage: string };
      try { args = construireArgumentsPaquetAffaire(affaireId, horodatage); }
      catch { return indisponible(); }
      const resultat = await lire("m10_lire_paquet_affaire_appareil", args, v => lirePaquetAffaire(v, affaireId, horodatage));
      return resultat?.source === "serveur" && !d.enLigne() ? horsLigne() : resultat;
    },
    chargerSignaux: () => lire("m10_lister_signaux", {}, lireSignauxM10, "memoire_signaux"),
    chargerReferences: (decalage = 0) => lire("m10_lister_references", { limite: 8, decalage }, v => {
      const r = lireReferencesM10(v);
      return r.ok && r.value.decalage !== decalage ? { ok: false, code: "reponse_illisible", detail: "Page différente de celle demandée." } : r;
    }, `memoire_references_${decalage}`, true),
    chargerDossier: (revisionId: string) => lire("m10_lire_revision", { revision_ligne_id: revisionId }, v => lireDossierRevisionM10(v, revisionId)),
    chargerStatutDecision: (decisionId: string) => lire("m10_statut_decision", { decision_id: decisionId }, lireStatutDecisionM10),
    chargerStatutRevision: (revisionId: string) => lire("m10_statut_revision", { revision_ligne_id: revisionId }, lireStatutRevisionM10),
  };
}
