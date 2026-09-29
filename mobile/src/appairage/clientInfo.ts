import { Platform } from "react-native";

import type { InfoClientAppairage } from "./types";

/**
 * `core/packages/gateway-protocol/src/client-info.ts` : `GATEWAY_CLIENT_IDS` est un catalogue FERMÉ
 * (enum TypeBox sur `ConnectParams.client.id`, requis). PLAN T1.4-c3 empruntait `openclaw-ios` /
 * `openclaw-android`, faute d'identifiant OPSYS ; T1.4-c4 a enregistré `OPSYS_MOBILE` (`"opsys-mobile"`)
 * dans le core, et PLAN T1.4-c5 le câble ici : l'app se présente sous son propre nom, sur les deux
 * plateformes (la plateforme voyage dans `client.platform`, pas dans l'identifiant).
 *
 * Ce choix RETIRE à l'app la classe « app native OpenClaw » du core (`isNativeAppUiClient`), qui ouvre
 * des voies d'approbation silencieuse pensées pour les apps d'OpenClaw ; un téléphone OPSYS s'appaire par
 * l'approbation explicite du propriétaire, et cela est voulu (`docs/architecture/MOBILE.md`, « Identifiant
 * de client » ; épinglé côté core par `src/gateway/opsys-mobile-trust.test.ts`).
 */
const ID_CLIENT_OPSYS = "opsys-mobile";
const PLATEFORMES_PRISES_EN_CHARGE: readonly string[] = ["ios", "android"];

/** `GATEWAY_CLIENT_MODES.UI` (`client-info.ts:41-49`) : un téléphone opéré par une personne,
 * jamais un `node`/`worker` headless. */
const MODE_CLIENT = "ui";

export function resoudreInfoClientAppairage(version: string): InfoClientAppairage {
  if (!PLATEFORMES_PRISES_EN_CHARGE.includes(Platform.OS)) {
    throw new Error(`Plateforme non prise en charge par l'appairage OPSYS : ${Platform.OS}`);
  }
  return { id: ID_CLIENT_OPSYS, version, platform: Platform.OS, mode: MODE_CLIENT };
}
