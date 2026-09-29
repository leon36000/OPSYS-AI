import fs from "node:fs";
import path from "node:path";

import type { HorlogeAppareil } from "../outbox/mutation";
import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";
import type { DepotCleValeur } from "../stockage/depotCleValeur";
import type { ConfigurationChargeurAdmin } from "./appel";

/**
 * Données FICTIVES et outillage des tests du profil admin (AGENTS.md : « les fixtures portent fictif »). Aucun test
 * n'importe ce fichier hors de `src/` : ce n'est pas du code de production. Les réponses viennent de la VRAIE sortie du
 * moteur (`fixtures/reponses-moteur.json`), que `tests/e2e/test_admin_appareil.py` compare à la forme vivante du
 * serveur : un test qui part d'elles part de ce que le moteur dit vraiment.
 */

export const FICTIF = true;

interface AppelEnregistre {
  readonly outil: string;
  readonly args: Readonly<Record<string, unknown>>;
}

interface Fixture {
  readonly fictif: boolean;
  readonly appels: Readonly<Record<string, AppelEnregistre>>;
  readonly reponses: Readonly<Record<string, unknown>>;
}

export const FIXTURE: Fixture = JSON.parse(
  fs.readFileSync(path.join(__dirname, "fixtures", "reponses-moteur.json"), "utf8"),
) as Fixture;

/** Une copie profonde : un test qui abîme une réponse ne touche jamais la fixture partagée. */
export function reponse(nom: string): any {
  const trouve = FIXTURE.reponses[nom];
  if (trouve === undefined) {
    throw new Error(`la fixture n'a pas « ${nom} »`);
  }
  return JSON.parse(JSON.stringify(trouve));
}

export function appel(nom: string): AppelEnregistre {
  const trouve = FIXTURE.appels[nom];
  if (trouve === undefined) {
    throw new Error(`la fixture n'a pas d'appel « ${nom} »`);
  }
  return trouve;
}

/** L'enveloppe d'une lecture acceptée d'un outil `couple` (`depuis_couple`) : ce que `invoquerOutil` rend dans `result`. */
export function enveloppeCouple(valeur: unknown): Record<string, unknown> {
  return { ok: true, resultat: { accepte: true, resultat: valeur } };
}

/** L'enveloppe d'une lecture d'un outil de forme directe : la valeur elle-même sous `resultat`. */
export function enveloppeDirecte(valeur: unknown): Record<string, unknown> {
  return { ok: true, resultat: valeur };
}

export function enveloppeRefusee(code: string, detail = ""): Record<string, unknown> {
  return { ok: true, resultat: { accepte: false, verdict: { code, detail } } };
}

export function enveloppeEnErreur(erreur: string, details: unknown = ""): Record<string, unknown> {
  return { ok: false, erreur, details };
}

export const HORLOGE_DE_TEST: HorlogeAppareil = {
  maintenant: new Date("2026-09-29T18:03:22.000Z"),
  decalageMinutesUTC: -240,
};

/** Un faux transport de `/tools/invoke` : un gestionnaire par outil, qui rend l'enveloppe (`result`). Un outil sans
 * gestionnaire est refusé comme le fait la porte d'appareil (403, hors de la portée). */
export function fauxTransport(
  gestionnaires: Record<string, (args: Record<string, unknown>) => unknown>,
): jest.Mock {
  return jest.fn(async (params: { requete: { tool: string; args?: Record<string, unknown> } }) => {
    const gestionnaire = gestionnaires[params.requete.tool];
    if (gestionnaire === undefined) {
      return echecHttp(403, "tool_call_blocked", `OPSYS device is not authorized to call "${params.requete.tool}" (tool_out_of_scope).`);
    }
    return { ok: true, result: gestionnaire(params.requete.args ?? {}) };
  });
}

/** Le transport tombe : aucune réponse (hors ligne). */
export function transportHorsLigne(): jest.Mock {
  return jest.fn(async () => ({
    ok: false,
    echec: { origine: "reseau", reessayable: true, message: "Network request failed" },
  }));
}

/** Un échec HTTP tel que `invoquerOutil` le classe : le corps du core (`erreur`) quand il y en a un. */
export function echecHttp(status: number, type?: string, message = `réponse HTTP ${status} inattendue`) {
  const reessayable = status === 408 || status === 429 || (status >= 500 && status <= 599);
  return {
    ok: false,
    echec: {
      origine: "http",
      reessayable,
      message,
      status,
      ...(type === undefined ? {} : { erreur: { type, message } }),
    },
  };
}

export function transportEnEchec(status: number, type?: string, message?: string): jest.Mock {
  return jest.fn(async () => echecHttp(status, type, message));
}

export function config(
  appelerOutil: jest.Mock,
  options: { depot?: DepotCleValeur; personne?: string; horloge?: HorlogeAppareil } = {},
): ConfigurationChargeurAdmin {
  const horloge = options.horloge ?? HORLOGE_DE_TEST;
  return {
    depot: options.depot ?? new DepotCleValeurMemoire(),
    appelerOutil,
    fetchImpl: jest.fn() as unknown as typeof fetch,
    urlBase: "https://grs.exemple.ca",
    jeton: "jeton-admin",
    personne: options.personne ?? "nathan",
    horloge: () => horloge,
  };
}
