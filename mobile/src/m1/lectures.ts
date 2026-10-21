import { appelerLecture } from "../admin/appel";
import { lireSection, type ResultatSection } from "../admin/lecture";
import type { LectureSection } from "../admin/enveloppe";
import type { ParametresAppelOutil, ResultatAppelOutil } from "../protocole/client";
import type { SessionEnvoi } from "../protocole/configuration";
import { ERREURS_PASSAGERES } from "../protocole/enveloppeOutil";
import type { DepotCleValeur } from "../stockage/depotCleValeur";
import { depotSousGardeLecture } from "../stockage/lecturesEnVol";
import type { HorlogeAppareil } from "../outbox/mutation";
import type { Reponse } from "../m7/contrat";
import { dateDigestM1Valide, identifiantTransfertM1Valide, lireDigestM1, lireTransfertM1 } from "./contrat";
import type { DigestM1, TransfertM1 } from "./contrat";

export interface DependancesLecturesTransferts {
  readonly capturerSession: () => { session: SessionEnvoi | null; courante: () => boolean };
  readonly obtenirDepot: () => Promise<DepotCleValeur>;
  readonly appelerOutil: (p: ParametresAppelOutil) => Promise<ResultatAppelOutil>;
  readonly fetchImpl: typeof fetch;
  readonly horloge: () => HorlogeAppareil;
  readonly enLigne: () => boolean;
}
const aucune = (code: string): ResultatSection<never> => ({ source: "aucune", raison: { code, detail: "" } });
function valeurPropre(v: unknown, cle: string): unknown {
  if (typeof v !== "object" || v === null) return undefined;
  try { const d = Object.getOwnPropertyDescriptor(v, cle); return d && "value" in d ? d.value : undefined; } catch { return undefined; }
}
function adapter<T>(brut: unknown, lire: (v: unknown) => Reponse<T>): LectureSection<T> {
  const lu = lire(brut);
  if (lu.ok) return { ok: true, valeur: lu.value };
  const explicite = valeurPropre(brut, "ok") === false || valeurPropre(valeurPropre(brut, "resultat"), "accepte") === false;
  const genre = explicite && !ERREURS_PASSAGERES.includes(lu.code) ? "refus" :
    lu.code === "reponse_illisible" ? "illisible" :
    lu.code === "reponse_tronquee" || ERREURS_PASSAGERES.includes(lu.code) ? "technique" : "refus";
  return { ok: false, genre, verdict: { code: lu.code, detail: lu.detail } };
}

/** Les contacts/messages restent au serveur ; seul le digest agrégé peut être gardé par personne/date. */
export function creerChargeurLecturesTransferts(d: DependancesLecturesTransferts) {
  async function serveur<T>(session: SessionEnvoi, courante: () => boolean, outil: string, args: Record<string, unknown>, lire: (v: unknown) => Reponse<T>): Promise<ResultatSection<T>> {
    if (!d.enLigne()) return aucune("hors_ligne");
    try {
      const appel = await appelerLecture({ appelerOutil: d.appelerOutil, fetchImpl: d.fetchImpl, urlBase: session.urlBase, jeton: session.jeton }, outil, args);
      if (!courante()) return aucune("lecture_remplacee");
      if (appel.genre !== "reponse") return appel.genre === "refuse" ? { source: "refus", verdict: appel.verdict } : { source: "aucune", raison: appel.verdict };
      const lu = adapter(appel.resultat, lire);
      if (!courante()) return aucune("lecture_remplacee");
      return lu.ok ? { source: "serveur", valeur: lu.valeur, misAJourLe: d.horloge().maintenant.toISOString() } :
        lu.genre === "refus" ? { source: "refus", verdict: lu.verdict } : { source: "aucune", raison: lu.verdict };
    } catch { return aucune(courante() ? "lecture_indisponible" : "lecture_remplacee"); }
  }
  async function chargerTransfert(id: string): Promise<ResultatSection<TransfertM1> | null> {
    const c = d.capturerSession();
    if (!c.session) return null;
    if (!c.courante()) return aucune("lecture_remplacee");
    if (!identifiantTransfertM1Valide(id)) return aucune("REJ-TRANSFERT-INCONNU");
    return serveur(c.session, c.courante, "m1_lire_transfert", { transfert_id: id }, v => lireTransfertM1(v, id));
  }
  async function chargerDigest(date: string): Promise<ResultatSection<DigestM1> | null> {
    const c = d.capturerSession(), session = c.session;
    if (!session) return null;
    if (!c.courante()) return aucune("lecture_remplacee");
    if (!dateDigestM1Valide(date)) return aucune("REJ-DIGEST-DATE-INVALIDE");
    const lire = (v: unknown) => lireDigestM1(v, date);
    let depot: DepotCleValeur | null;
    try { depot = await d.obtenirDepot(); } catch { depot = null; }
    if (!c.courante()) return aucune("lecture_remplacee");
    if (!depot) return serveur(session, c.courante, "m1_produire_digest", { date_reference: date }, lire);
    try {
      const r = await lireSection({ depot: depotSousGardeLecture(depot, c.courante), appelerOutil: d.appelerOutil,
        fetchImpl: d.fetchImpl, urlBase: session.urlBase, jeton: session.jeton, personne: session.personne,
        horloge: d.horloge, enLigne: d.enLigne }, {
        outil: "m1_produire_digest", args: { date_reference: date }, cache: `reception_digest_${date}`,
        interpreter: v => adapter(v, lire), epurerPourLeCache: v => { const lu = lire(v); return lu.ok ? { ok: true, resultat: lu.value } : undefined; },
      });
      return c.courante() ? r : aucune("lecture_remplacee");
    } catch { return aucune(c.courante() ? "lecture_indisponible" : "lecture_remplacee"); }
  }
  return { chargerDigest, chargerTransfert };
}
