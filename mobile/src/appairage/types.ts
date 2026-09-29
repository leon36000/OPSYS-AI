import type { IdentiteAppareil } from "./identite";

/**
 * Sous-ensemble MINIMAL des trames du protocole gateway (Wire v4, R12 §1.2) réellement utilisé
 * par l'appairage — pas une copie des ~270 fichiers de schémas TypeBox de
 * `core/packages/gateway-protocol/src/schema/` (lus pour EN EXTRAIRE ces formes, jamais
 * importés — voir la décision d'intégration dans `docs/architecture/MOBILE.md`). Champs
 * confirmés dans `core/packages/gateway-protocol/src/schema/frames.ts` (`RequestFrameSchema`,
 * `ResponseFrameSchema`, `EventFrameSchema`, `ConnectParamsSchema`, `HelloOkSchema`).
 */
export interface TrameRequete {
  readonly type: "req";
  readonly id: string;
  readonly method: string;
  readonly params?: unknown;
}

export interface TrameReponse {
  readonly type: "res";
  readonly id: string;
  readonly ok: boolean;
  readonly payload?: unknown;
  readonly error?: {
    readonly code?: string;
    readonly message?: string;
    readonly details?: unknown;
  };
}

export interface TrameEvenement {
  readonly type: "event";
  readonly event: string;
  readonly payload?: unknown;
}

/** `frames.ts` : `device: closedObject({id, publicKey, signature, signedAt, nonce})`. */
export interface ParametresAppareilConnexion {
  readonly id: string;
  readonly publicKey: string;
  readonly signature: string;
  readonly signedAt: number;
  readonly nonce: string;
}

/** `frames.ts` : `auth: closedObject({token?, bootstrapToken?, deviceToken?, password?, ...})`. */
export interface ParametresAuthConnexion {
  readonly bootstrapToken?: string;
  readonly token?: string;
  readonly deviceToken?: string;
  readonly password?: string;
}

/** `ConnectParamsSchema` (`frames.ts`) — seuls les champs que l'appairage renseigne. */
export interface ParametresConnexion {
  readonly minProtocol: number;
  readonly maxProtocol: number;
  readonly client: {
    readonly id: string;
    readonly version: string;
    readonly platform: string;
    readonly mode: string;
    readonly deviceFamily?: string;
  };
  readonly role?: string;
  readonly scopes?: string[];
  readonly device?: ParametresAppareilConnexion;
  readonly auth?: ParametresAuthConnexion;
}

/** `HelloOkSchema.auth` (`frames.ts`) — seuls les champs lus par l'appairage. */
export interface AuthHelloOk {
  readonly method?: string;
  readonly deviceToken?: string;
  readonly role?: string;
  readonly scopes?: string[];
}

/**
 * Objet WebSocket minimal dont a besoin l'appairage — mêmes méthodes/évènements qu'un
 * `WebSocket` natif RN ou navigateur (assignation directe des gestionnaires, pas
 * `addEventListener`, pour rester le plus proche possible d'un vrai `WebSocket` sans wrapper).
 * Injecté (mission item 1/5) : en production `(url) => new WebSocket(url)` (le `WebSocket`
 * global RN — jamais le paquet npm `ws`, exactement l'esprit de `@openclaw/gateway-client
 * /browser`, R12 §1.2 : « l'hôte fournit son propre WebSocket »); dans les tests, un faux socket
 * en mémoire (`client.test.ts`).
 */
export interface SocketAppairageLike {
  onopen: (() => void) | null;
  onmessage: ((evenement: { readonly data: string }) => void) | null;
  onerror: ((evenement: unknown) => void) | null;
  onclose: ((evenement: { readonly code?: number; readonly reason?: string }) => void) | null;
  send(donnees: string): void;
  close(code?: number, reason?: string): void;
}

export interface InfoClientAppairage {
  /** Un des `GATEWAY_CLIENT_IDS` fermés du core : `opsys-mobile` depuis PLAN T1.4-c5 (avant, `openclaw-ios` /
   * `openclaw-android` empruntés) — voir `docs/architecture/MOBILE.md`, « Identifiant de client ». */
  readonly id: string;
  readonly version: string;
  /** `Platform.OS` ("ios" | "android"). */
  readonly platform: string;
  readonly mode: string;
  readonly deviceFamily?: string;
}

export type EtatAppairage =
  | { readonly phase: "connexion" }
  | { readonly phase: "attente_defi" }
  | { readonly phase: "signature" }
  | { readonly phase: "attente_approbation"; readonly tentative: number }
  | { readonly phase: "nouvelle_tentative_reseau"; readonly tentative: number }
  | { readonly phase: "reussi" }
  | { readonly phase: "echec"; readonly motif: MotifEchecAppairage };

export type MotifEchecAppairage =
  | "code_invalide"
  | "code_expire"
  | "refuse"
  | "delai_ecoule"
  | "reponse_inattendue";

export type ResultatAppairage =
  | {
      readonly ok: true;
      readonly jeton: string;
      readonly role: string;
      readonly scopes: readonly string[];
      readonly urlBase: string;
      readonly appareilId: string;
    }
  | { readonly ok: false; readonly motif: MotifEchecAppairage; readonly message: string };

export interface ParametresAppairage {
  /** Ce que la personne a saisi (le code, avec ou sans préfixe `oc-pair://`). */
  readonly code: string;
  readonly identite: IdentiteAppareil;
  readonly clientInfo: InfoClientAppairage;
  readonly creerSocket: (url: string) => SocketAppairageLike;
  /** Horloge injectée (mission item 5). */
  readonly maintenant?: () => Date;
  /** Sommeil injecté — entre les tentatives ET pour les délais d'expiration internes (mission
   * item 5 ; voir `client.ts`, `avecExpiration`). */
  readonly attendre?: (ms: number) => Promise<void>;
  /** Générateur d'id de requête injecté (par défaut : `expo-crypto` `randomUUID`, câblé par
   * l'appelant réel — voir `app/pairing/index.tsx`). */
  readonly genererId?: () => string;
  /** Budget total avant abandon (par défaut : 10 min, aligné sur la durée de vie du code —
   * R12 §1.3). */
  readonly budgetMs?: number;
  readonly onEtat?: (etat: EtatAppairage) => void;
}
