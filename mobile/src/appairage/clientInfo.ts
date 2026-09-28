import { Platform } from "react-native";

import type { InfoClientAppairage } from "./types";

/**
 * `core/packages/gateway-protocol/src/client-info.ts:10-29` : `GATEWAY_CLIENT_IDS` est un
 * catalogue FERMÉ (`closedObject`/enum TypeBox sur `ConnectParams.client.id`, requis) — il n'y a
 * PAS d'identifiant OPSYS dédié dans le fork non modifié. Limite documentée dans
 * `docs/architecture/MOBILE.md` (§ Appairage) : on emprunte l'id natif le plus proche selon la
 * plateforme (`openclaw-ios`/`openclaw-android`), faute de quoi la connexion échouerait dès la
 * validation de schéma. Enregistrer un id OPSYS dans ce catalogue est un changement CORE, hors
 * périmètre (lecture seule) de PLAN T1.4-c3.
 */
const ID_CLIENT_PAR_PLATEFORME: Readonly<Record<string, string>> = {
  ios: "openclaw-ios",
  android: "openclaw-android",
};

/** `GATEWAY_CLIENT_MODES.UI` (`client-info.ts:41-49`) : un téléphone opéré par une personne,
 * jamais un `node`/`worker` headless. */
const MODE_CLIENT = "ui";

export function resoudreInfoClientAppairage(version: string): InfoClientAppairage {
  const id = ID_CLIENT_PAR_PLATEFORME[Platform.OS];
  if (!id) {
    throw new Error(`Plateforme non prise en charge par l'appairage OPSYS : ${Platform.OS}`);
  }
  return { id, version, platform: Platform.OS, mode: MODE_CLIENT };
}
