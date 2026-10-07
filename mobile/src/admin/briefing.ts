import type { ConfigurationChargeurAdmin } from "./appel";
import { appelerLecture } from "./appel";
import { interpreter } from "./enveloppe";
import { lireSection } from "./lecture";
import type { ResultatSection } from "./lecture";
import {
  lireBriefing,
  lireSuiteBriefing,
  lireAlertesM9,
  lireEtatConsolide,
  OUTIL_BRIEFING,
  OUTIL_SUITE_BRIEFING,
  OUTIL_ALERTES_M9,
  OUTIL_ETAT_M9,
} from "../m9/briefing";
import type {
  BriefingM9,
  SuiteBriefingM9,
  AlertesM9,
  EtatConsolideM9,
  SectionBriefing,
} from "../m9/briefing";
import { capturerGardeLecture, VERDICT_LECTURE_REMPLACEE } from "../stockage/lecturesEnVol";
import { VERDICT_REPONSE_ILLISIBLE } from "../protocole/enveloppeOutil";

/** Projection lisible par le même contrat ; seules les références WCT de la preuve M8 sont affichées. */
function epurerAlerte<T extends { readonly preuve: Readonly<Record<string, unknown>> }>(
  alerte: T,
): T {
  const wct = alerte.preuve.wct_id;
  return { ...alerte, preuve: typeof wct === "string" ? { wct_id: wct } : {} };
}
function cacheNormalise<T>(
  reader: (raw: unknown) => T | null,
  projection: (lu: T) => unknown = (lu) => lu,
) {
  return (raw: unknown) => {
    const lue = interpreter(raw, "directe", reader);
    return lue.ok ? { ok: true, resultat: projection(lue.valeur) } : raw;
  };
}

/** T4.21 : premières lectures en cache personnel ; les suites courantes restent exclusivement en ligne. */
export function creerChargeurBriefing(config: ConfigurationChargeurAdmin) {
  const garde = capturerGardeLecture(config.depot);
  const remplacee = <T>(): ResultatSection<T> => ({
    source: "aucune",
    raison: VERDICT_LECTURE_REMPLACEE,
  });
  async function courante<T>(
    operation: () => Promise<ResultatSection<T>>,
  ): Promise<ResultatSection<T>> {
    if (!garde.courante()) return remplacee();
    const result = await operation();
    return garde.courante() ? result : remplacee();
  }
  async function pageEnLigne<T>(
    outil: string,
    args: Record<string, unknown>,
    reader: (raw: unknown) => T | null,
  ): Promise<ResultatSection<T>> {
    return courante(async () => {
      const appel = await appelerLecture(config, outil, args);
      if (!garde.courante()) return remplacee<T>();
      if (appel.genre === "refuse") return { source: "refus", verdict: appel.verdict };
      if (appel.genre === "injoignable") return { source: "aucune", raison: appel.verdict };
      const lue = interpreter(appel.resultat, "directe", reader);
      if (!lue.ok)
        return lue.genre === "refus"
          ? { source: "refus", verdict: lue.verdict }
          : { source: "aucune", raison: lue.verdict };
      return {
        source: "serveur",
        valeur: lue.valeur,
        misAJourLe: config.horloge().maintenant.toISOString(),
      };
    });
  }
  return {
    chargerBriefing(maintenant: string): Promise<ResultatSection<BriefingM9>> {
      return courante(() =>
        lireSection(config, {
          outil: OUTIL_BRIEFING,
          args: { maintenant },
          cache: `briefing_m9:${maintenant.slice(0, 10)}`,
          epurerPourLeCache: cacheNormalise(lireBriefing, (b) => ({
            ...b,
            sections: {
              ...b.sections,
              alertes_m8: {
                ...b.sections.alertes_m8,
                items: b.sections.alertes_m8.items.map(epurerAlerte),
              },
            },
          })),
          interpreter: (raw) =>
            interpreter(raw, "directe", (v) => {
              const lu = lireBriefing(v);
              return lu?.jour === maintenant.slice(0, 10) ? lu : null;
            }),
        }),
      );
    },
    chargerSuite(
      maintenant: string,
      section: SectionBriefing,
      depart: number,
    ): Promise<ResultatSection<SuiteBriefingM9>> {
      return pageEnLigne(OUTIL_SUITE_BRIEFING, { maintenant, section, depart }, (v) => {
        const lu = lireSuiteBriefing(v, section, depart);
        return lu?.jour === maintenant.slice(0, 10) ? lu : null;
      });
    },
    chargerAlertes(depart = 0): Promise<ResultatSection<AlertesM9>> {
      if (!Number.isSafeInteger(depart) || depart < 0)
        return Promise.resolve({ source: "aucune", raison: VERDICT_REPONSE_ILLISIBLE });
      return depart === 0
        ? courante(() =>
            lireSection(config, {
              outil: OUTIL_ALERTES_M9,
              args: { depart: 0 },
              cache: "alertes_m9",
              epurerPourLeCache: cacheNormalise(
                (v) => lireAlertesM9(v, 0),
                (a) => ({
                  type: a.type,
                  source: a.source,
                  ordre: a.ordre,
                  total: a.total,
                  depart: a.depart,
                  affichees: a.alertes.length,
                  reste: a.reste,
                  prochain_depart: a.prochain_depart,
                  message: a.message,
                  alertes: a.alertes.map(epurerAlerte),
                }),
              ),
              interpreter: (raw) => interpreter(raw, "directe", (v) => lireAlertesM9(v, 0)),
            }),
          )
        : pageEnLigne(OUTIL_ALERTES_M9, { depart }, (v) => lireAlertesM9(v, depart));
    },
    chargerEtat(): Promise<ResultatSection<EtatConsolideM9>> {
      return courante(() =>
        lireSection(config, {
          outil: OUTIL_ETAT_M9,
          args: {},
          cache: "etat_m9",
          epurerPourLeCache: cacheNormalise(lireEtatConsolide),
          interpreter: (raw) => interpreter(raw, "directe", lireEtatConsolide),
        }),
      );
    },
  };
}
