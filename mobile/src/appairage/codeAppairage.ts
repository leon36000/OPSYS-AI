import { decoderBase64Url } from "./base64url";

/**
 * Décodage du code d'appairage — port fidèle de `decodePairingSetupCode`/
 * `encodePairingSetupCode` (`core/src/pairing/setup-code.ts:414-494`, lu, jamais exécuté ni
 * importé — ADR-0008). Format confirmé dans le fork : préfixe `oc-pair://` (optionnel — un code
 * saisi à la main peut omettre le préfixe, `setup-code.ts:429-431`) suivi du base64url (sans
 * remplissage) d'un JSON `{url, urls?, bootstrapToken, expiresAtMs?, tlsFingerprint?}` où `url`
 * est l'URL WebSocket (`ws://`/`wss://`) de la passerelle et `bootstrapToken` le jeton
 * d'amorçage à usage unique (R12 §1.3 : « QR oc-pair://<code> à usage unique 10 min »).
 *
 * Écran d'appairage (PLAN T1.4-c3, mission item 3) : saisie du CODE seulement dans cette tranche
 * (pas de lecture QR — `expo-camera` alourdirait cette tranche pour un gain marginal tant que le
 * code peut être copié/collé ou tapé ; voir `docs/architecture/MOBILE.md`). Le code accepté ici
 * est donc exactement la même chaîne que celle encodée dans le QR, tapée ou collée par la
 * personne.
 */
export interface ChargeAppairage {
  readonly url: string;
  readonly urls?: readonly string[];
  readonly bootstrapToken: string;
  readonly expiresAtMs?: number;
  readonly tlsFingerprint?: string;
}

const PREFIXE_URL = "oc-pair://";
const RE_CODE = /^[A-Za-z0-9_-]+$/u;
const MAX_URLS = 8;

/** Distingue un code EXPIRÉ (l'appelant doit en redemander un) d'un code simplement mal formé —
 * `src/appairage/client.ts` s'en sert pour choisir le bon `MotifEchecAppairage`. */
export class ErreurCodeAppairageExpire extends Error {}

function estUrlGatewayValide(valeur: unknown): valeur is string {
  if (typeof valeur !== "string" || !valeur) {
    return false;
  }
  let analysee: URL;
  try {
    analysee = new URL(valeur);
  } catch {
    return false;
  }
  if (analysee.username || analysee.password) {
    return false;
  }
  return analysee.protocol === "ws:" || analysee.protocol === "wss:";
}

/**
 * Décode et valide un code d'appairage. Lève une `Error` fail-closed (jamais de valeur par
 * défaut inventée, AGENTS.md) sur : forme invalide, JSON non conforme, URL absente/non-WS,
 * `bootstrapToken` absent, ou code expiré (`expiresAtMs` dépassé — R12 §1.3, usage unique 10
 * min). `maintenant` est injecté (mission item 5, testabilité).
 */
export function decoderCodeAppairage(saisie: string, maintenant: () => Date = () => new Date()): ChargeAppairage {
  const coupee = saisie.trim();
  const code = coupee.toLowerCase().startsWith(PREFIXE_URL) ? coupee.slice(PREFIXE_URL.length) : coupee;
  if (!code || !RE_CODE.test(code)) {
    throw new Error("Code d'appairage invalide.");
  }

  let decode: unknown;
  try {
    decode = JSON.parse(new TextDecoder().decode(decoderBase64Url(code)));
  } catch {
    throw new Error("Code d'appairage invalide.");
  }
  if (typeof decode !== "object" || decode === null || Array.isArray(decode)) {
    throw new Error("Charge d'appairage invalide.");
  }
  const objet = decode as Record<string, unknown>;

  if (!estUrlGatewayValide(objet.url)) {
    throw new Error("Charge d'appairage invalide : URL de passerelle absente ou non-WebSocket.");
  }
  const url = objet.url as string;

  if (typeof objet.bootstrapToken !== "string" || !objet.bootstrapToken) {
    throw new Error("Charge d'appairage invalide : jeton d'amorçage absent.");
  }
  const bootstrapToken = objet.bootstrapToken;

  let urls: readonly string[] | undefined;
  if (objet.urls !== undefined) {
    if (!Array.isArray(objet.urls) || objet.urls.length === 0 || objet.urls.length > MAX_URLS) {
      throw new Error("Charge d'appairage invalide : liste d'URL de repli invalide.");
    }
    if (!objet.urls.every((candidate) => estUrlGatewayValide(candidate))) {
      throw new Error("Charge d'appairage invalide : liste d'URL de repli invalide.");
    }
    urls = objet.urls as string[];
  }

  let expiresAtMs: number | undefined;
  if (objet.expiresAtMs !== undefined) {
    const candidate = objet.expiresAtMs;
    if (typeof candidate !== "number" || !Number.isSafeInteger(candidate) || candidate < 0) {
      throw new Error("Charge d'appairage invalide : expiration invalide.");
    }
    expiresAtMs = candidate;
    if (candidate <= maintenant().getTime()) {
      throw new ErreurCodeAppairageExpire("Ce code d'appairage a expiré. Demandez-en un nouveau au propriétaire.");
    }
  }

  const tlsFingerprint = typeof objet.tlsFingerprint === "string" ? objet.tlsFingerprint : undefined;

  return {
    url,
    ...(urls ? { urls } : {}),
    bootstrapToken,
    ...(expiresAtMs !== undefined ? { expiresAtMs } : {}),
    ...(tlsFingerprint ? { tlsFingerprint } : {}),
  };
}

/** `wss://host:port/chemin` -> `https://host:port/chemin` (et `ws:` -> `http:`) : même hôte que
 * la passerelle WebSocket utilisée pour l'appairage, pour les appels `/tools/invoke` HTTP
 * ultérieurs (R12 §1.2 : « multiplexé avec une API HTTP sur le même port »). */
export function urlHttpDepuisUrlGateway(urlGateway: string): string {
  if (urlGateway.startsWith("wss://")) {
    return `https://${urlGateway.slice("wss://".length)}`;
  }
  if (urlGateway.startsWith("ws://")) {
    return `http://${urlGateway.slice("ws://".length)}`;
  }
  throw new Error("URL de passerelle invalide : ws:// ou wss:// attendu.");
}
