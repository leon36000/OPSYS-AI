import { formaterHorodatageLocal } from "../outbox/mutation";
import { appelerLecture } from "./appel";
import type { ConfigurationChargeurVendeur } from "./appel";
import type { SessionEnvoi } from "../protocole/configuration";
import { construireArgumentsReadiness, interpreterReadiness } from "../m2/readiness";
import type { ResultatReadiness } from "../m2/readiness";
import { OUTIL_EVALUER_READINESS } from "../m2/readiness";

/** Charge séparément la readiness: aucun cache, stockage, marqueur persistant ou transfert à M3. */
export async function chargerReadiness(
  config: ConfigurationChargeurVendeur,
  leadId: string,
): Promise<ResultatReadiness> {
  const horloge = config.horloge();
  const appel = await appelerLecture(config, OUTIL_EVALUER_READINESS, {
    ...construireArgumentsReadiness(leadId, formaterHorodatageLocal(horloge)),
  });
  if (appel.genre === "refuse") {
    return { genre: "refus", verdict: appel.verdict };
  }
  if (appel.genre === "injoignable") {
    return { genre: "non_verifie", verdict: appel.verdict };
  }
  return interpreterReadiness(appel.resultat, leadId);
}

/** Le résultat peut être rendu seulement si la session d'appareil n'a pas changé durant l'appel. */
export function memeSessionReadiness(
  configuration: Pick<ConfigurationChargeurVendeur, "urlBase" | "jeton" | "personne">,
  session: SessionEnvoi | null,
): boolean {
  return (
    session !== null &&
    session.urlBase === configuration.urlBase &&
    session.jeton === configuration.jeton &&
    session.personne === configuration.personne
  );
}

/** Rejette la valeur d'une lecture si l'URL, le jeton ou la personne ont changé depuis son départ. */
export function resultatSiMemeSession<T>(
  configuration: Pick<ConfigurationChargeurVendeur, "urlBase" | "jeton" | "personne">,
  session: SessionEnvoi | null,
  resultat: T,
): T | null {
  return memeSessionReadiness(configuration, session) ? resultat : null;
}
