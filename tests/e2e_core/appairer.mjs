#!/usr/bin/env node
// Poignée de main d'appairage de l'app OPSYS, jouée contre un VRAI Gateway (PLAN T1.5-b).
//
// Ce script fait ce que fait l'app (`mobile/src/appairage/client.ts`), sans dépendance : Node >= 22
// (WebSocket global, `node:crypto`). Séquence lue dans le fork (docs/architecture/MOBILE.md, « Appairage ») :
//
//   ouverture WebSocket -> évènement `connect.challenge` {nonce, ts} (core/src/gateway/server/connection.ts)
//   -> requête `connect` : client `opsys-mobile`, rôle de transport `operator`, `device` signé (charge v3,
//      Ed25519 pur, `deviceId` = sha256 de la clé publique brute) et `auth.bootstrapToken` = le code
//   -> `hello-ok` {auth.deviceToken}, OU refus `PAIRING_REQUIRED` {details.requestId} tant que le
//      propriétaire n'a pas approuvé : nouvelle connexion, nouveau défi, même code.
//
// Ce qui diffère de l'app, volontairement : l'identité est neuve à chaque exécution (l'app garde la sienne dans
// `expo-secure-store`), l'attente entre deux tentatives est fixe (l'app recule de 1 s à 30 s) et peut être
// pilotée par l'appelant (`--attente stdin` : une ligne lue = « l'approbation est faite, reconnecte-toi »).
//
// Sortie : une ligne JSON par évènement sur la sortie standard (`identite`, `attente_approbation`, `reussi`,
// `echec`), le détail humain sur la sortie d'erreur. Le jeton d'appareil n'est écrit que dans l'évènement
// `reussi` : l'appelant le garde, il ne doit pas le recopier dans un journal.
//
// Usage :
//   node appairer.mjs --code <code d'appairage | oc-pair://...> [--attente delai|stdin] [--budget-s 180]
//   node appairer.mjs --autotest      # vecteurs de la charge v3 et de la signature, sans réseau
//
// Codes de sortie : 0 appairé, 1 échec (refus, délai, réponse inattendue), 2 usage, 3 auto-test en échec.

import crypto from "node:crypto";
import readline from "node:readline";
import { pathToFileURL } from "node:url";

// -- constantes de l'app (mobile/src/appairage/client.ts, clientInfo.ts) -----------------------------------
const ROLE_CONNEXION = "operator"; // rôle de transport ; le profil métier vient de `GET /opsys/identite`
const PORTEES = ["operator.read", "operator.write"];
const PROTOCOLE = 4; // core/packages/gateway-protocol/src/version.ts : minimum = maximum = 4
const CLIENT = { id: "opsys-mobile", version: "0.0.0-e2e-core", platform: "android", mode: "ui" };
const DELAI_DEFI_MS = 10_000;
const DELAI_REPONSE_MS = 10_000;
const PAUSE_ENTRE_TENTATIVES_MS = 1_000;
const BUDGET_PAR_DEFAUT_S = 180;
const PREFIXE_CODE = "oc-pair://";
// core/src/infra/ed25519-signature.ts:5 : enveloppe SPKI d'une clé publique Ed25519 brute de 32 octets.
const PREFIXE_SPKI_ED25519 = Buffer.from("302a300506032b6570032100", "hex");

// -- charge v3 (mobile/src/appairage/chargeV3.ts <- core/packages/gateway-client/src/device-auth.ts) ----------
export function normaliserMetadonnee(valeur) {
  if (typeof valeur !== "string") {
    return "";
  }
  const coupee = valeur.trim();
  if (!coupee) {
    return "";
  }
  // Seulement les lettres ASCII A-Z : « İOS » devient « İos », pas une casse Unicode complète.
  return coupee.replace(/[A-Z]/g, (c) => String.fromCharCode(c.charCodeAt(0) + 32));
}

export function construireChargeV3(p) {
  return [
    "v3",
    p.deviceId,
    p.clientId,
    p.clientMode,
    p.role,
    p.scopes.join(","),
    String(p.signedAtMs),
    p.token ?? "",
    p.nonce,
    normaliserMetadonnee(p.platform),
    normaliserMetadonnee(p.deviceFamily),
  ].join("|");
}

// -- identité et signature (mobile/src/appairage/identite.ts <- core/src/infra/device-identity.ts) ----------
export function creerIdentite() {
  const { publicKey, privateKey } = crypto.generateKeyPairSync("ed25519");
  const brute = Buffer.from(publicKey.export({ format: "jwk" }).x, "base64url");
  return {
    cle: privateKey,
    publicKeyBase64Url: brute.toString("base64url"),
    deviceId: crypto.createHash("sha256").update(brute).digest("hex"),
  };
}

export function signer(identite, charge) {
  // EdDSA pur, sans pré-hachage : `crypto.sign(null, ...)`, comme `signEd25519Payload` du core.
  return crypto.sign(null, Buffer.from(charge, "utf8"), identite.cle).toString("base64url");
}

/** Ce que le serveur recalcule pour vérifier une signature (`verifyEd25519Signature` du core). */
export function verifierSignature(publicKeyBase64Url, charge, signatureBase64Url) {
  const cle = crypto.createPublicKey({
    key: Buffer.concat([PREFIXE_SPKI_ED25519, Buffer.from(publicKeyBase64Url, "base64url")]),
    type: "spki",
    format: "der",
  });
  return crypto.verify(null, Buffer.from(charge, "utf8"), cle, Buffer.from(signatureBase64Url, "base64url"));
}

// -- code d'appairage (mobile/src/appairage/codeAppairage.ts <- core/src/pairing/setup-code.ts) --------------
export function decoderCode(entree, maintenantMs = Date.now()) {
  const coupe = entree.trim();
  const code = coupe.toLowerCase().startsWith(PREFIXE_CODE) ? coupe.slice(PREFIXE_CODE.length) : coupe;
  if (!/^[A-Za-z0-9_-]+$/u.test(code)) {
    throw new Error("code d'appairage invalide");
  }
  let charge;
  try {
    charge = JSON.parse(Buffer.from(code, "base64url").toString("utf8"));
  } catch {
    throw new Error("code d'appairage invalide");
  }
  if (typeof charge !== "object" || charge === null || typeof charge.url !== "string" || !charge.url ||
    typeof charge.bootstrapToken !== "string" || !charge.bootstrapToken) {
    throw new Error("charge d'appairage invalide (url ou bootstrapToken absent)");
  }
  if (typeof charge.expiresAtMs === "number" && charge.expiresAtMs <= maintenantMs) {
    throw new Error("le code d'appairage a expiré");
  }
  return { url: charge.url, bootstrapToken: charge.bootstrapToken };
}

export function urlHttpDepuisUrlGateway(urlWs) {
  const url = new URL(urlWs);
  url.protocol = url.protocol === "wss:" ? "https:" : "http:";
  return url.origin;
}

// -- protocole ---------------------------------------------------------------------------------------------
class ErreurReseau extends Error {}

function attendreTrame(ws, predicat, delaiMs, quoi) {
  return new Promise((resolve, reject) => {
    const terminer = (suite) => {
      clearTimeout(minuteur);
      ws.removeEventListener("message", surMessage);
      ws.removeEventListener("error", surErreur);
      ws.removeEventListener("close", surFermeture);
      suite();
    };
    const minuteur = setTimeout(() => terminer(() => reject(new ErreurReseau(`délai dépassé : ${quoi}`))), delaiMs);
    const surMessage = (evenement) => {
      let trame;
      try {
        trame = JSON.parse(typeof evenement.data === "string" ? evenement.data : Buffer.from(evenement.data).toString("utf8"));
      } catch {
        return;
      }
      if (predicat(trame)) {
        terminer(() => resolve(trame));
      }
    };
    const surErreur = () => terminer(() => reject(new ErreurReseau(`connexion impossible : ${quoi}`)));
    const surFermeture = (evenement) =>
      terminer(() => reject(new ErreurReseau(`connexion fermée avant : ${quoi} (code ${evenement.code})`)));
    ws.addEventListener("message", surMessage);
    ws.addEventListener("error", surErreur);
    ws.addEventListener("close", surFermeture);
  });
}

/** Une tentative de connexion : un WebSocket, un défi, une requête `connect`, une réponse. */
async function tenterConnexion({ url, bootstrapToken, identite }) {
  const ws = new WebSocket(url);
  try {
    const defi = await attendreTrame(
      ws, (t) => t.type === "event" && t.event === "connect.challenge" && typeof t.payload?.nonce === "string",
      DELAI_DEFI_MS, "le défi du serveur");
    const signedAtMs = Date.now();
    const charge = construireChargeV3({
      deviceId: identite.deviceId, clientId: CLIENT.id, clientMode: CLIENT.mode, role: ROLE_CONNEXION,
      scopes: PORTEES, signedAtMs, token: bootstrapToken, nonce: defi.payload.nonce, platform: CLIENT.platform,
    });
    const id = crypto.randomUUID();
    const requete = {
      type: "req", id, method: "connect",
      params: {
        minProtocol: PROTOCOLE, maxProtocol: PROTOCOLE,
        client: { id: CLIENT.id, version: CLIENT.version, platform: CLIENT.platform, mode: CLIENT.mode },
        role: ROLE_CONNEXION, scopes: [...PORTEES],
        device: {
          id: identite.deviceId, publicKey: identite.publicKeyBase64Url, signature: signer(identite, charge),
          signedAt: signedAtMs, nonce: defi.payload.nonce,
        },
        auth: { bootstrapToken },
      },
    };
    const reponse = attendreTrame(ws, (t) => t.type === "res" && t.id === id, DELAI_REPONSE_MS, "la réponse à connect");
    ws.send(JSON.stringify(requete));
    return interpreter(await reponse);
  } finally {
    ws.close();
  }
}

function interpreter(reponse) {
  if (reponse.ok) {
    const auth = reponse.payload?.auth;
    if (!auth?.deviceToken || !auth.role) {
      return { type: "inattendue", message: "hello-ok sans jeton d'appareil ni rôle", champs: Object.keys(auth ?? {}) };
    }
    return { type: "ok", deviceToken: auth.deviceToken, role: auth.role, scopes: auth.scopes ?? [] };
  }
  const details = reponse.error?.details ?? {};
  if (details.code === "PAIRING_REQUIRED") {
    return { type: "approbation", requestId: details.requestId ?? null, raison: details.reason ?? null };
  }
  const code = details.code ?? reponse.error?.code ?? null;
  const message = reponse.error?.message ?? "appairage refusé par la passerelle";
  if (reponse.error?.retryable === true) {
    // « gateway starting; retry shortly » : le serveur demande de réessayer, comme le fait le client du core.
    return { type: "reessayable", code, message };
  }
  return { type: "refus", code, message };
}

// -- entrée/sortie -----------------------------------------------------------------------------------------
function evenement(objet) {
  process.stdout.write(`${JSON.stringify(objet)}\n`);
}

function journal(texte) {
  process.stderr.write(`[appairer] ${texte}\n`);
}

const dormir = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function creerLecteurDeLignes() {
  const rl = readline.createInterface({ input: process.stdin });
  const enAttente = [];
  const recues = [];
  let ferme = false;
  rl.on("line", (ligne) => (enAttente.length > 0 ? enAttente.shift()(ligne) : recues.push(ligne)));
  rl.on("close", () => {
    ferme = true;
    for (const resoudre of enAttente.splice(0)) {
      resoudre(null);
    }
  });
  return {
    suivante: () =>
      new Promise((resolve) => {
        if (recues.length > 0) {
          resolve(recues.shift());
        } else if (ferme) {
          resolve(null);
        } else {
          enAttente.push(resolve);
        }
      }),
    arreter: () => rl.close(),
  };
}

async function appairer({ code, attente, budgetMs }) {
  const { url, bootstrapToken } = decoderCode(code);
  if (typeof WebSocket === "undefined") {
    throw new Error("WebSocket global absent : Node >= 22 requis");
  }
  const identite = creerIdentite();
  evenement({ evenement: "identite", deviceId: identite.deviceId });
  const lecteur = attente === "stdin" ? creerLecteurDeLignes() : null;
  const debut = Date.now();
  try {
    for (let tentative = 1; ; tentative += 1) {
      if (Date.now() - debut > budgetMs) {
        evenement({ evenement: "echec", motif: "delai_ecoule", message: `pas appairé après ${budgetMs / 1000} s` });
        return 1;
      }
      let issue;
      try {
        issue = await tenterConnexion({ url, bootstrapToken, identite });
      } catch (erreur) {
        if (!(erreur instanceof ErreurReseau)) {
          throw erreur;
        }
        journal(`tentative ${tentative} : ${erreur.message}`);
        await dormir(PAUSE_ENTRE_TENTATIVES_MS);
        continue;
      }
      if (issue.type === "ok") {
        evenement({
          evenement: "reussi", deviceId: identite.deviceId, deviceToken: issue.deviceToken, role: issue.role,
          scopes: issue.scopes, urlBase: urlHttpDepuisUrlGateway(url),
        });
        return 0;
      }
      if (issue.type === "reessayable") {
        journal(`tentative ${tentative} : le Gateway demande de réessayer (${issue.code} : ${issue.message})`);
        await dormir(PAUSE_ENTRE_TENTATIVES_MS);
        continue;
      }
      if (issue.type === "approbation") {
        journal(`tentative ${tentative} : approbation du propriétaire attendue (demande ${issue.requestId})`);
        evenement({ evenement: "attente_approbation", tentative, requestId: issue.requestId, raison: issue.raison });
        if (lecteur) {
          await lecteur.suivante(); // l'appelant écrit une ligne quand l'approbation est faite
        } else {
          await dormir(PAUSE_ENTRE_TENTATIVES_MS);
        }
        continue;
      }
      evenement({ evenement: "echec", motif: issue.type, code: issue.code ?? null, message: issue.message,
        ...(issue.champs ? { champs: issue.champs } : {}) });
      return 1;
    }
  } finally {
    lecteur?.arreter();
  }
}

// -- auto-test : vecteurs recopiés de mobile/src/appairage/*.test.ts (eux-mêmes tirés du core) ----------------
export function autotest() {
  let n = 0;
  const egal = (obtenu, attendu, quoi) => {
    n += 1;
    if (obtenu !== attendu) {
      throw new Error(`${quoi} : obtenu ${JSON.stringify(obtenu)}, attendu ${JSON.stringify(attendu)}`);
    }
  };
  egal(construireChargeV3({
    deviceId: "dev-1", clientId: "openclaw-macos", clientMode: "ui", role: "operator",
    scopes: ["operator.admin", "operator.read"], signedAtMs: 1_700_000_000_000, token: "tok-123",
    nonce: "nonce-abc", platform: "  IOS  ", deviceFamily: "  iPhone  ",
  }), "v3|dev-1|openclaw-macos|ui|operator|operator.admin,operator.read|1700000000000|tok-123|nonce-abc|ios|iphone",
  "charge v3 canonique");
  egal(construireChargeV3({
    deviceId: "dev-2", clientId: "openclaw-ios", clientMode: "ui", role: "operator", scopes: ["operator.read"],
    signedAtMs: 1_700_000_000_001, nonce: "nonce-def",
  }), "v3|dev-2|openclaw-ios|ui|operator|operator.read|1700000000001||nonce-def||", "champs optionnels vides");
  egal(construireChargeV3({
    deviceId: "device", clientId: "openclaw-browser-copilot", clientMode: "ui", role: "operator",
    scopes: ["operator.read", "operator.write"], signedAtMs: 123, token: "test-bootstrap-token", nonce: "nonce",
    platform: "Chrome", deviceFamily: "Extension",
  }), "v3|device|openclaw-browser-copilot|ui|operator|operator.read,operator.write|123|test-bootstrap-token|nonce|chrome|extension",
  "jeton d'amorçage");
  egal(normaliserMetadonnee("  İOS  "), "İos", "normalisation Unicode");
  egal(normaliserMetadonnee("  MAC  "), "mac", "normalisation ASCII");
  egal(normaliserMetadonnee(undefined), "", "normalisation absente");

  const identite = creerIdentite();
  egal(Buffer.from(identite.publicKeyBase64Url, "base64url").length, 32, "clé publique brute de 32 octets");
  egal(identite.deviceId, crypto.createHash("sha256").update(Buffer.from(identite.publicKeyBase64Url, "base64url"))
    .digest("hex"), "deviceId = sha256 de la clé publique brute");
  const charge = construireChargeV3({
    deviceId: identite.deviceId, clientId: CLIENT.id, clientMode: CLIENT.mode, role: ROLE_CONNEXION,
    scopes: PORTEES, signedAtMs: 1, token: "code", nonce: "n", platform: CLIENT.platform,
  });
  const signature = signer(identite, charge);
  egal(verifierSignature(identite.publicKeyBase64Url, charge, signature), true, "signature vérifiée comme le serveur");
  egal(verifierSignature(identite.publicKeyBase64Url, `${charge}x`, signature), false, "charge altérée refusée");

  const charge64 = Buffer.from(JSON.stringify({ url: "ws://127.0.0.1:1", bootstrapToken: "amorce", expiresAtMs: 2_000 }),
    "utf8").toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
  egal(JSON.stringify(decoderCode(`${PREFIXE_CODE}${charge64}`, 1_000)), JSON.stringify({ url: "ws://127.0.0.1:1",
    bootstrapToken: "amorce" }), "code d'appairage décodé");
  let expire = false;
  try {
    decoderCode(charge64, 3_000);
  } catch {
    expire = true;
  }
  egal(expire, true, "code expiré refusé");
  egal(urlHttpDepuisUrlGateway("ws://127.0.0.1:18789/x"), "http://127.0.0.1:18789", "URL HTTP du Gateway");
  return n;
}

function lireArguments(argv) {
  const options = { attente: "delai", budgetS: BUDGET_PAR_DEFAUT_S, code: null, autotest: false };
  for (let i = 0; i < argv.length; i += 1) {
    const drapeau = argv[i];
    if (drapeau === "--autotest") {
      options.autotest = true;
    } else if (drapeau === "--code" || drapeau === "--attente" || drapeau === "--budget-s") {
      const valeur = argv[i + 1];
      if (valeur === undefined) {
        return null;
      }
      i += 1;
      if (drapeau === "--code") {
        options.code = valeur;
      } else if (drapeau === "--attente") {
        options.attente = valeur;
      } else {
        options.budgetS = Number(valeur);
      }
    } else {
      return null;
    }
  }
  const valide = options.autotest ||
    (options.code && ["delai", "stdin"].includes(options.attente) && Number.isFinite(options.budgetS) && options.budgetS > 0);
  return valide ? options : null;
}

async function principal() {
  const options = lireArguments(process.argv.slice(2));
  if (options === null) {
    journal("usage : appairer.mjs --code <code> [--attente delai|stdin] [--budget-s 180] | --autotest");
    return 2;
  }
  if (options.autotest) {
    try {
      journal(`auto-test réussi (${autotest()} vérifications)`);
      return 0;
    } catch (erreur) {
      journal(`auto-test EN ÉCHEC : ${erreur.message}`);
      return 3;
    }
  }
  try {
    return await appairer({ code: options.code, attente: options.attente, budgetMs: options.budgetS * 1000 });
  } catch (erreur) {
    evenement({ evenement: "echec", motif: "erreur", message: erreur.message });
    return 1;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = await principal();
}
