// `Buffer` (Node) construit ici la fixture du code d'appairage — outillage de test seulement.
/// <reference types="node" />

import { appairerAppareil } from "./client";
import { construireChargeAppairageV3 } from "./chargeV3";
import { creerIdentiteDepuisGraine, signerAvecCleSecrete } from "./identite";
import type { EtatAppairage, SocketAppairageLike } from "./types";

/**
 * `appairerAppareil` — séquence confirmée en lisant le fork (lecture seule, ADR-0008) :
 * ouverture WS -> `connect.challenge` (`core/src/gateway/server/connection.ts:333-343`) ->
 * requête `connect` (device+auth) -> `hello-ok` OU refus `PAIRING_REQUIRED`
 * (`core/packages/gateway-protocol/src/connect-error-details.ts:46,54-59`). Le faux socket
 * ci-dessous script CHAQUE tentative (une par appel à `creerSocket`) plutôt que de rejouer une
 * connexion : le fork ouvre une connexion PAR tentative, avec un nonce neuf à chaque fois.
 */

const IDENTITE = creerIdentiteDepuisGraine(Uint8Array.from({ length: 32 }, (_, i) => i + 1));
const CLIENT_INFO = { id: "openclaw-ios", version: "0.1.0", platform: "ios", mode: "ui" };

type ComportementSocket =
  | { readonly genre: "defi_puis_reponse"; readonly nonce: string; readonly ts: number; readonly reponse: (trameEnvoyee: any) => unknown }
  | { readonly genre: "pas_de_defi" }
  | { readonly genre: "erreur_immediate" };

interface FauxSocket extends SocketAppairageLike {
  readonly url: string;
  readonly envoyes: unknown[];
  fermee: boolean;
}

function creerFauxServeur(comportements: readonly ComportementSocket[]) {
  let index = 0;
  const sockets: FauxSocket[] = [];
  const creerSocket = (url: string): SocketAppairageLike => {
    const comportement = comportements[Math.min(index, comportements.length - 1)];
    index += 1;
    const socket: FauxSocket = {
      url,
      envoyes: [],
      fermee: false,
      onopen: null,
      onmessage: null,
      onerror: null,
      onclose: null,
      send(donnees: string) {
        const trame = JSON.parse(donnees);
        socket.envoyes.push(trame);
        if (comportement.genre === "defi_puis_reponse" && trame.type === "req" && trame.method === "connect") {
          const reponse = comportement.reponse(trame);
          queueMicrotask(() => socket.onmessage?.({ data: JSON.stringify(reponse) }));
        }
      },
      close() {
        socket.fermee = true;
      },
    };
    sockets.push(socket);
    if (comportement.genre === "defi_puis_reponse") {
      const trameDefi = { type: "event", event: "connect.challenge", payload: { nonce: comportement.nonce, ts: comportement.ts } };
      queueMicrotask(() => socket.onmessage?.({ data: JSON.stringify(trameDefi) }));
    } else if (comportement.genre === "erreur_immediate") {
      queueMicrotask(() => socket.onerror?.(new Error("boom")));
    }
    // "pas_de_defi" : rien n'est jamais envoyé -> seul le délai d'expiration débloque l'appelant.
    return socket;
  };
  return { creerSocket, sockets };
}

/** Toujours résolu sur le prochain "macrotask" (`setTimeout`), JAMAIS avant : les réponses
 * scriptées ci-dessus sont programmées en microtâche (`queueMicrotask`), et la boucle
 * d'évènements draine TOUJOURS la file de microtâches avant le prochain macrotask (garantie du
 * langage) — donc une réponse scriptée gagne TOUJOURS la course interne de
 * `client.ts#avecExpiration` face à ce faux `attendre`, sans dépendre d'un ordre d'enfilement
 * fragile. Sert aussi de recul (rapide) entre tentatives : les tests restent silencieux, sans
 * vraie attente de plusieurs secondes/minutes. */
function attendreRapide(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

const REPONSE_HELLO_OK = (deviceToken: string, role: string, scopes: string[]) => (trameEnvoyee: any) => ({
  type: "res",
  id: trameEnvoyee.id,
  ok: true,
  payload: { type: "hello-ok", auth: { deviceToken, role, scopes } },
});

const REPONSE_PAIRING_REQUIRED = (requestId: string) => (trameEnvoyee: any) => ({
  type: "res",
  id: trameEnvoyee.id,
  ok: false,
  error: { code: "invalid_request", message: "device pairing required", details: { code: "PAIRING_REQUIRED", reason: "not-paired", requestId } },
});

const REPONSE_REFUS_SIGNATURE = (trameEnvoyee: any) => ({
  type: "res",
  id: trameEnvoyee.id,
  ok: false,
  error: { code: "invalid_request", message: "device signature invalid", details: { code: "DEVICE_AUTH_SIGNATURE_INVALID" } },
});

function coderChargeAppairage(charge: Record<string, unknown>): string {
  return `oc-pair://${Buffer.from(JSON.stringify(charge)).toString("base64url")}`;
}

const CODE_VALIDE = coderChargeAppairage({ url: "wss://grs.exemple.ca:8787", bootstrapToken: "amorce-abc" });

describe("appairerAppareil — chemin heureux", () => {
  test("un seul aller-retour -> jeton, rôle, portées, urlBase HTTP dérivée de wss://", async () => {
    const { creerSocket, sockets } = creerFauxServeur([
      { genre: "defi_puis_reponse", nonce: "nonce-1", ts: 1_000, reponse: REPONSE_HELLO_OK("jeton-abc", "operator", ["operator.read"]) },
    ]);
    const etats: EtatAppairage[] = [];

    const resultat = await appairerAppareil({
      code: CODE_VALIDE,
      identite: IDENTITE,
      clientInfo: CLIENT_INFO,
      creerSocket,
      attendre: attendreRapide,
      maintenant: () => new Date(1_000_000),
      genererId: () => "requete-1",
      onEtat: (etat) => etats.push(etat),
    });

    expect(resultat).toEqual({
      ok: true,
      jeton: "jeton-abc",
      role: "operator",
      scopes: ["operator.read"],
      urlBase: "https://grs.exemple.ca:8787",
      appareilId: IDENTITE.deviceId,
    });
    expect(sockets).toHaveLength(1);
    expect(sockets[0].fermee).toBe(true); // pas de session WS conservée après le jeton (client.ts, docstring)
    expect(etats.map((e) => e.phase)).toEqual(["connexion", "attente_defi", "signature", "reussi"]);
  });

  test("la requête connect envoyée est conforme au protocole lu (ConnectParamsSchema)", async () => {
    const { creerSocket, sockets } = creerFauxServeur([
      { genre: "defi_puis_reponse", nonce: "nonce-xyz", ts: 42, reponse: REPONSE_HELLO_OK("t", "operator", []) },
    ]);

    await appairerAppareil({
      code: CODE_VALIDE,
      identite: IDENTITE,
      clientInfo: CLIENT_INFO,
      creerSocket,
      attendre: attendreRapide,
      maintenant: () => new Date(5_000_000),
      genererId: () => "requete-2",
    });

    expect(sockets[0].url).toBe("wss://grs.exemple.ca:8787");
    const trame = sockets[0].envoyes[0] as any;
    expect(trame).toMatchObject({
      type: "req",
      id: "requete-2",
      method: "connect",
      params: {
        minProtocol: 4,
        maxProtocol: 4,
        client: { id: "openclaw-ios", version: "0.1.0", platform: "ios", mode: "ui" },
        role: "operator",
        scopes: ["operator.read", "operator.write"],
        auth: { bootstrapToken: "amorce-abc" },
        device: {
          id: IDENTITE.deviceId,
          publicKey: IDENTITE.publicKeyBase64Url,
          signedAt: 5_000_000,
          nonce: "nonce-xyz",
        },
      },
    });

    // La signature transmise DOIT être celle de construireChargeAppairageV3 + signerAvecCleSecrete
    // avec EXACTEMENT ces champs (le serveur reconstruit la même chaîne pour vérifier).
    const chargeAttendue = construireChargeAppairageV3({
      deviceId: IDENTITE.deviceId,
      clientId: "openclaw-ios",
      clientMode: "ui",
      role: "operator",
      scopes: ["operator.read", "operator.write"],
      signedAtMs: 5_000_000,
      token: "amorce-abc",
      nonce: "nonce-xyz",
      platform: "ios",
      deviceFamily: undefined,
    });
    expect(trame.params.device.signature).toBe(signerAvecCleSecrete(IDENTITE.cleSecreteBase64Url, chargeAttendue));
  });
});

describe("appairerAppareil — approbation du propriétaire en attente (PAIRING_REQUIRED)", () => {
  test("réessaie avec un NOUVEAU défi après un refus PAIRING_REQUIRED, puis réussit", async () => {
    const { creerSocket, sockets } = creerFauxServeur([
      { genre: "defi_puis_reponse", nonce: "nonce-1", ts: 1, reponse: REPONSE_PAIRING_REQUIRED("req-1") },
      { genre: "defi_puis_reponse", nonce: "nonce-2", ts: 2, reponse: REPONSE_PAIRING_REQUIRED("req-1") },
      { genre: "defi_puis_reponse", nonce: "nonce-3", ts: 3, reponse: REPONSE_HELLO_OK("jeton-final", "operator", []) },
    ]);
    const etats: EtatAppairage[] = [];

    const resultat = await appairerAppareil({
      code: CODE_VALIDE,
      identite: IDENTITE,
      clientInfo: CLIENT_INFO,
      creerSocket,
      attendre: attendreRapide,
      genererId: () => `id-${Math.random()}`,
      onEtat: (etat) => etats.push(etat),
    });

    expect(resultat.ok).toBe(true);
    expect(sockets).toHaveLength(3);
    // Chaque tentative signe un nonce DIFFÉRENT (jamais le même défi rejoué).
    const nonces = sockets.map((s) => (s.envoyes[0] as any).params.device.nonce);
    expect(nonces).toEqual(["nonce-1", "nonce-2", "nonce-3"]);
    expect(etats.filter((e) => e.phase === "attente_approbation")).toHaveLength(2);
  });
});

describe("appairerAppareil — refus permanent (pas PAIRING_REQUIRED)", () => {
  test("signature refusée par le serveur -> échec immédiat, UNE seule tentative", async () => {
    const { creerSocket, sockets } = creerFauxServeur([
      { genre: "defi_puis_reponse", nonce: "n", ts: 1, reponse: REPONSE_REFUS_SIGNATURE },
    ]);

    const resultat = await appairerAppareil({
      code: CODE_VALIDE,
      identite: IDENTITE,
      clientInfo: CLIENT_INFO,
      creerSocket,
      attendre: attendreRapide,
      genererId: () => "id",
    });

    expect(resultat).toEqual({ ok: false, motif: "refuse", message: "device signature invalid" });
    expect(sockets).toHaveLength(1);
  });
});

describe("appairerAppareil — code invalide/expiré : aucune tentative réseau", () => {
  test("code invalide -> motif code_invalide, aucun socket créé", async () => {
    const { creerSocket, sockets } = creerFauxServeur([]);
    const resultat = await appairerAppareil({
      code: "pas-un-code-valide!!",
      identite: IDENTITE,
      clientInfo: CLIENT_INFO,
      creerSocket,
      attendre: attendreRapide,
    });
    expect(resultat.ok).toBe(false);
    if (!resultat.ok) {
      expect(resultat.motif).toBe("code_invalide");
    }
    expect(sockets).toHaveLength(0);
  });

  test("code expiré -> motif code_expire, aucun socket créé", async () => {
    const codeExpire = coderChargeAppairage({ url: "wss://x", bootstrapToken: "y", expiresAtMs: 1_000 });
    const { creerSocket, sockets } = creerFauxServeur([]);
    const resultat = await appairerAppareil({
      code: codeExpire,
      identite: IDENTITE,
      clientInfo: CLIENT_INFO,
      creerSocket,
      attendre: attendreRapide,
      maintenant: () => new Date(2_000),
    });
    expect(resultat.ok).toBe(false);
    if (!resultat.ok) {
      expect(resultat.motif).toBe("code_expire");
    }
    expect(sockets).toHaveLength(0);
  });
});

describe("appairerAppareil — pannes réseau et budget", () => {
  test("le défi n'arrive jamais -> réessaie (réseau), jusqu'à épuisement du budget", async () => {
    const { creerSocket, sockets } = creerFauxServeur([{ genre: "pas_de_defi" }]);
    const etats: EtatAppairage[] = [];

    const resultat = await appairerAppareil({
      code: CODE_VALIDE,
      identite: IDENTITE,
      clientInfo: CLIENT_INFO,
      creerSocket,
      attendre: attendreRapide,
      genererId: () => "id",
      budgetMs: 1, // épuisé dès la première tentative retournée (réseau, pas approuvée)
      onEtat: (etat) => etats.push(etat),
    });

    expect(resultat.ok).toBe(false);
    if (!resultat.ok) {
      expect(resultat.motif).toBe("delai_ecoule");
    }
    expect(sockets.length).toBeGreaterThanOrEqual(1);
    expect(etats.some((e) => e.phase === "nouvelle_tentative_reseau")).toBe(true);
    expect(etats[etats.length - 1]).toEqual({ phase: "echec", motif: "delai_ecoule" });
  });

  test("budget déjà dépassé avant la première tentative -> échec immédiat, aucun socket créé", async () => {
    const { creerSocket, sockets } = creerFauxServeur([
      { genre: "defi_puis_reponse", nonce: "n", ts: 1, reponse: REPONSE_HELLO_OK("t", "operator", []) },
    ]);
    const resultat = await appairerAppareil({
      code: CODE_VALIDE,
      identite: IDENTITE,
      clientInfo: CLIENT_INFO,
      creerSocket,
      attendre: attendreRapide,
      budgetMs: -1,
    });
    expect(resultat.ok).toBe(false);
    if (!resultat.ok) {
      expect(resultat.motif).toBe("delai_ecoule");
    }
    expect(sockets).toHaveLength(0);
  });
});

describe("appairerAppareil — réponse hello-ok mal formée", () => {
  test("jeton ou rôle absent -> motif reponse_inattendue", async () => {
    const { creerSocket } = creerFauxServeur([
      { genre: "defi_puis_reponse", nonce: "n", ts: 1, reponse: (t: any) => ({ type: "res", id: t.id, ok: true, payload: { auth: {} } }) },
    ]);
    const resultat = await appairerAppareil({
      code: CODE_VALIDE,
      identite: IDENTITE,
      clientInfo: CLIENT_INFO,
      creerSocket,
      attendre: attendreRapide,
    });
    expect(resultat.ok).toBe(false);
    if (!resultat.ok) {
      expect(resultat.motif).toBe("reponse_inattendue");
    }
  });
});
