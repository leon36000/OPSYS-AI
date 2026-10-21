import { lireDisponibilite, lireDigestSansSeuils, OUTIL_DISPONIBILITE, OUTIL_DIGEST } from "../m6/stock";
import type { DisponibiliteStock, DigestStock } from "../m6/stock";
import { capturerGardeLecture, VERDICT_LECTURE_REMPLACEE } from "../stockage/lecturesEnVol";
import type { ConfigurationChargeurAdmin } from "./appel";
import { interpreter } from "./enveloppe";
import type { FormeReponse } from "./enveloppe";
import { lireSection } from "./lecture";
import type { DefinitionSection, ResultatSection } from "./lecture";

function section<T>(outil: string, forme: FormeReponse, cache: string, lire: (v: unknown) => T | null): DefinitionSection<T> {
  return {
    outil, args: {}, cache, invaliderCacheSurRefus: true,
    interpreter: brut => interpreter(brut, forme, lire),
    epurerPourLeCache: brut => {
      const lu = interpreter(brut, forme, lire);
      return lu.ok ? { ok: true, resultat: forme === "couple" ? { accepte: true, resultat: lu.valeur } : lu.valeur } : brut;
    },
  };
}

export const SECTION_DISPONIBILITE_STOCK = section(OUTIL_DISPONIBILITE, "couple", "stock_disponibilite_m6", lireDisponibilite);
export const SECTION_DIGEST_STOCK = section(OUTIL_DIGEST, "directe", "stock_digest_m6", lireDigestSansSeuils);

/** Deux lectures indépendantes, args {} ; génération capturée à la création comme pour les comptes admin. */
export function creerChargeurStock(config: ConfigurationChargeurAdmin) {
  const garde = capturerGardeLecture(config.depot);
  const remplacee = <T>(): ResultatSection<T> => ({ source: "aucune", raison: VERDICT_LECTURE_REMPLACEE });
  function courante<T>(operation: () => Promise<ResultatSection<T>>): Promise<ResultatSection<T>> {
    if (!garde.courante()) return Promise.resolve(remplacee());
    // lireSection contrôle ses awaits et ferme elle-même la génération en cas de purge échouée.
    // Son refus connu reste un refus ; le chargeur retenu protège l'entrée de la lecture.
    return operation();
  }
  return {
    chargerDisponibilite(): Promise<ResultatSection<DisponibiliteStock>> {
      return courante(() => lireSection(config, SECTION_DISPONIBILITE_STOCK));
    },
    chargerDigest(): Promise<ResultatSection<DigestStock>> {
      return courante(() => lireSection(config, SECTION_DIGEST_STOCK));
    },
  };
}
