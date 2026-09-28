import { calculerDelaiReculMs } from "../outbox/recul";
import { ErreurCodeAppairageExpire, decoderCodeAppairage, urlHttpDepuisUrlGateway } from "./codeAppairage";
import { construireChargeAppairageV3 } from "./chargeV3";
import { signerAvecCleSecrete } from "./identite";
import type {
  AuthHelloOk,
  EtatAppairage,
  MotifEchecAppairage,
  ParametresAppairage,
  ParametresConnexion,
  ResultatAppairage,
  SocketAppairageLike,
  TrameEvenement,
  TrameReponse,
  TrameRequete,
} from "./types";
import type { ChargeAppairage } from "./codeAppairage";

/**
 * Client d'appairage MINIMAL (PLAN T1.4-c3 item 1 — voie retenue, voir
 * `docs/architecture/MOBILE.md` § Appairage pour la justification complète). Implémente
 * uniquement la séquence lue dans le fork (R12 §1.3, confirmée fichier par fichier) :
 *
 *   ouverture WebSocket -> évènement `connect.challenge` (nonce serveur, non sollicité, envoyé
 *   dès l'ouverture — `core/src/gateway/server/connection.ts:333-343`) -> requête `connect`
 *   portant `device` (charge v3 signée) + `auth.bootstrapToken` (le code) -> réponse `hello-ok`
 *   (`ok:true`, `payload.auth.{deviceToken,role,scopes}`) OU refus `PAIRING_REQUIRED` (approbation
 *   du propriétaire en attente — `core/packages/gateway-protocol/src/connect-error-details.ts:46,54-59`),
 *   auquel cas on réessaie avec un NOUVEAU défi (chaque nonce est à usage unique par connexion),
 *   à recul exponentiel (`src/outbox/recul.ts`, déjà 1 s -> 30 s ×2 — réutilisé tel quel plutôt
 *   que réécrit, même principe que le client `gateway-client` d'OpenClaw cité par R12 §4/§1.2),
 *   jusqu'à expiration du budget (par défaut 10 min, la durée de vie du code — R12 §1.3).
 *
 * Une fois un jeton obtenu, la socket est FERMÉE : l'app ne garde pas de session WebSocket
 * ouverte, elle repasse par `POST /tools/invoke` (HTTP, déjà implémenté — `src/protocole
 * /client.ts`) pour tout le reste, exactement comme R12 §1.2 le décrit (« la porte déterministe
 * ... jamais par un tour de modèle/une session persistante »). C'est pourquoi ce module
 * n'essaie PAS de reproduire la machine à états générale de reconnexion de
 * `@openclaw/gateway-client` (`protocol-client.ts`, 635 lignes, pensée pour une session agent
 * persistante) : elle n'a aucun rôle une fois le jeton obtenu.
 */

/** `core/src/gateway/role-policy.types.ts:2` : `GatewayRole = "operator" | "node"` — un
 * appareil mobile opéré par une personne est un `"operator"`. C'est un rôle DE TRANSPORT
 * (distinct du profil métier OPSYS admin/employee/seller, voir `docs/architecture/MOBILE.md`
 * § Appairage) : tant que T1.4-c2 (rôles nommés) n'est pas livré côté core, c'est la SEULE
 * valeur que le fork accepte aujourd'hui pour un appareil apparié humain. */
const ROLE_CONNEXION = "operator";

/** Portées demandées par défaut — valeurs réellement acceptées par le fork, confirmées dans
 * `core/packages/gateway-client/src/browser-device-auth.test.ts:32,45` (`operator.read`,
 * `operator.write`, `operator.admin`). La politique fine par rôle OPSYS est un sujet T1.4-c2. */
const PORTEES_PAR_DEFAUT: readonly string[] = ["operator.read", "operator.write"];

/** `core/packages/gateway-protocol/src/version.ts:2-3` : version de protocole courante = 4,
 * plancher accepté = 4. `min = max` : on ne négocie pas de plage, on demande exactement ce que
 * le fork courant sait servir. */
const PROTOCOLE = 4;

const DELAI_DEFI_MS = 10_000;
const DELAI_REPONSE_MS = 10_000;
/** R12 §1.3 : le code QR/CLI est à usage unique et valide 10 minutes — même budget côté client,
 * en filet de sécurité (le serveur fait de toute façon foi sur l'expiration réelle). */
const BUDGET_PAR_DEFAUT_MS = 10 * 60_000;

function estTrameEvenement(valeur: unknown): valeur is TrameEvenement {
  return typeof valeur === "object" && valeur !== null && (valeur as { type?: unknown }).type === "event";
}

function estTrameReponse(valeur: unknown): valeur is TrameReponse {
  return typeof valeur === "object" && valeur !== null && (valeur as { type?: unknown }).type === "res";
}

function attendreDefi(socket: SocketAppairageLike): Promise<{ nonce: string; ts: number }> {
  return new Promise((resolve, reject) => {
    socket.onerror = (evenement) => reject(new Error("Connexion à la passerelle impossible.", { cause: evenement }));
    socket.onclose = () => reject(new Error("Connexion fermée avant le défi du serveur."));
    socket.onmessage = (evenement) => {
      let trame: unknown;
      try {
        trame = JSON.parse(evenement.data);
      } catch {
        return;
      }
      if (!estTrameEvenement(trame) || trame.event !== "connect.challenge") {
        return;
      }
      const charge = trame.payload as { nonce?: unknown; ts?: unknown } | undefined;
      if (charge && typeof charge.nonce === "string" && typeof charge.ts === "number") {
        resolve({ nonce: charge.nonce, ts: charge.ts });
      }
    };
  });
}

function attendreReponseConnexion(socket: SocketAppairageLike, id: string): Promise<TrameReponse> {
  return new Promise((resolve, reject) => {
    socket.onerror = (evenement) => reject(new Error("Connexion à la passerelle impossible.", { cause: evenement }));
    socket.onclose = () => reject(new Error("Connexion fermée avant la réponse du serveur."));
    socket.onmessage = (evenement) => {
      let trame: unknown;
      try {
        trame = JSON.parse(evenement.data);
      } catch {
        return;
      }
      if (estTrameReponse(trame) && trame.id === id) {
        resolve(trame);
      }
    };
  });
}

/** Fait échouer `promesse` si elle n'est pas réglée avant `ms` — implémenté avec le même
 * `attendre` injecté que le recul entre tentatives (mission item 5 : rien de non testable). */
function avecExpiration<T>(promesse: Promise<T>, ms: number, attendre: (ms: number) => Promise<void>): Promise<T> {
  return Promise.race([
    promesse,
    attendre(ms).then((): never => {
      throw new Error(`Délai dépassé après ${ms} ms.`);
    }),
  ]);
}

type ResultatTentative =
  | { readonly terminal: true; readonly resultat: ResultatAppairage }
  | { readonly terminal: false; readonly raison: "attente_approbation" | "reseau" };

async function tenterConnexion(params: {
  readonly connexion: ParametresAppairage;
  readonly charge: ChargeAppairage;
  readonly attendre: (ms: number) => Promise<void>;
  readonly maintenant: () => Date;
  readonly emettre: (etat: EtatAppairage) => void;
}): Promise<ResultatTentative> {
  const { connexion, charge, attendre, maintenant, emettre } = params;
  emettre({ phase: "connexion" });
  const socket = connexion.creerSocket(charge.url);
  try {
    emettre({ phase: "attente_defi" });
    const defi = await avecExpiration(attendreDefi(socket), DELAI_DEFI_MS, attendre);

    emettre({ phase: "signature" });
    const signedAtMs = maintenant().getTime();
    const chargeV3 = construireChargeAppairageV3({
      deviceId: connexion.identite.deviceId,
      clientId: connexion.clientInfo.id,
      clientMode: connexion.clientInfo.mode,
      role: ROLE_CONNEXION,
      scopes: PORTEES_PAR_DEFAUT,
      signedAtMs,
      token: charge.bootstrapToken,
      nonce: defi.nonce,
      platform: connexion.clientInfo.platform,
      deviceFamily: connexion.clientInfo.deviceFamily,
    });
    const signature = signerAvecCleSecrete(connexion.identite.cleSecreteBase64Url, chargeV3);

    const id = connexion.genererId ? connexion.genererId() : `${signedAtMs}-${Math.random().toString(36).slice(2)}`;
    const parametresConnexion: ParametresConnexion = {
      minProtocol: PROTOCOLE,
      maxProtocol: PROTOCOLE,
      client: {
        id: connexion.clientInfo.id,
        version: connexion.clientInfo.version,
        platform: connexion.clientInfo.platform,
        mode: connexion.clientInfo.mode,
        ...(connexion.clientInfo.deviceFamily ? { deviceFamily: connexion.clientInfo.deviceFamily } : {}),
      },
      role: ROLE_CONNEXION,
      scopes: [...PORTEES_PAR_DEFAUT],
      device: {
        id: connexion.identite.deviceId,
        publicKey: connexion.identite.publicKeyBase64Url,
        signature,
        signedAt: signedAtMs,
        nonce: defi.nonce,
      },
      auth: { bootstrapToken: charge.bootstrapToken },
    };
    const trame: TrameRequete = { type: "req", id, method: "connect", params: parametresConnexion };

    const reponsePromesse = attendreReponseConnexion(socket, id);
    socket.send(JSON.stringify(trame));
    const reponse = await avecExpiration(reponsePromesse, DELAI_REPONSE_MS, attendre);

    if (reponse.ok) {
      const auth = (reponse.payload as { auth?: AuthHelloOk } | undefined)?.auth;
      if (!auth?.deviceToken || !auth.role) {
        return {
          terminal: true,
          resultat: {
            ok: false,
            motif: "reponse_inattendue",
            message: "Réponse hello-ok inattendue : jeton ou rôle d'appareil absent.",
          },
        };
      }
      return {
        terminal: true,
        resultat: {
          ok: true,
          jeton: auth.deviceToken,
          role: auth.role,
          scopes: auth.scopes ?? [],
          urlBase: urlHttpDepuisUrlGateway(charge.url),
          appareilId: connexion.identite.deviceId,
        },
      };
    }

    const details = reponse.error?.details as { code?: string } | undefined;
    if (details?.code === "PAIRING_REQUIRED") {
      return { terminal: false, raison: "attente_approbation" };
    }
    return {
      terminal: true,
      resultat: {
        ok: false,
        motif: "refuse",
        message: reponse.error?.message ?? "Appairage refusé par la passerelle.",
      },
    };
  } catch {
    // Défi/réponse jamais reçus, ou socket en erreur/fermée : toujours réessayable (même
    // classification que src/protocole/classification.ts pour réseau/délai) — borné par le
    // budget total de la boucle appelante, jamais une attente indéfinie.
    return { terminal: false, raison: "reseau" };
  } finally {
    socket.close();
  }
}

/**
 * Point d'entrée de l'appairage (mission item 3). `identite` doit déjà exister (voir
 * `src/appairage/identite.ts` + `src/appairage/stockage.ts` pour la génération/persistance) ;
 * cette fonction ne fait QUE le protocole réseau, jamais la gestion de clé.
 */
export async function appairerAppareil(connexion: ParametresAppairage): Promise<ResultatAppairage> {
  const maintenant = connexion.maintenant ?? (() => new Date());
  const attendre = connexion.attendre ?? ((ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms)));
  const budgetMs = connexion.budgetMs ?? BUDGET_PAR_DEFAUT_MS;
  const emettre = (etat: EtatAppairage): void => connexion.onEtat?.(etat);
  const debutMs = maintenant().getTime();

  let charge: ChargeAppairage;
  try {
    charge = decoderCodeAppairage(connexion.code, maintenant);
  } catch (erreur) {
    const motif: MotifEchecAppairage = erreur instanceof ErreurCodeAppairageExpire ? "code_expire" : "code_invalide";
    const message = erreur instanceof Error ? erreur.message : String(erreur);
    emettre({ phase: "echec", motif });
    return { ok: false, motif, message };
  }

  for (let tentative = 0; ; tentative += 1) {
    if (maintenant().getTime() - debutMs > budgetMs) {
      emettre({ phase: "echec", motif: "delai_ecoule" });
      return {
        ok: false,
        motif: "delai_ecoule",
        message: "Délai d'appairage dépassé. Générez un nouveau code auprès du propriétaire.",
      };
    }
    const resultat = await tenterConnexion({ connexion, charge, attendre, maintenant, emettre });
    if (resultat.terminal) {
      emettre(
        resultat.resultat.ok
          ? { phase: "reussi" }
          : { phase: "echec", motif: resultat.resultat.motif },
      );
      return resultat.resultat;
    }
    emettre(
      resultat.raison === "attente_approbation"
        ? { phase: "attente_approbation", tentative: tentative + 1 }
        : { phase: "nouvelle_tentative_reseau", tentative: tentative + 1 },
    );
    await attendre(calculerDelaiReculMs(tentative));
  }
}
