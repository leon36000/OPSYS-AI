import { Directory, EncodingType, File, Paths } from "expo-file-system";
import * as Crypto from "expo-crypto";

import { decoderDataUrl, extensionDepuisMimeType } from "./dataUrl";
import { construireMutationSignatureCapture } from "./mutation";
import type { SignatureCapturee } from "./mutation";
import { empreinteSha256 } from "../fichiers/empreinte";
import type { FonctionDigestSha256 } from "../fichiers/empreinte";
import { genererMutationId } from "../outbox/id";
import { obtenirDepot } from "../outbox/service";
import type { MutationOutbox } from "../outbox/types";

/**
 * Câblage RÉEL de la capture signature (`signature.tsx`) — même principe que
 * `src/photos/service.ts` (R12 §4 : « même principe » pour la signature que pour les photos) :
 * jamais de binaire inline dans une mutation, un fichier local + un hachage SHA-256. La capture
 * elle-même (`react-native-signature-canvas`, rendu WebView) livre une DataURL via son callback
 * `onOK` — décodée par `src/signature/dataUrl.ts` (fonction pure, testée), puis écrite ici sur
 * le disque géré par l'app.
 *
 * Non testé unitairement : `expo-file-system`/`expo-crypto` natifs, même limite que
 * `src/photos/service.ts`. Le décodage de la DataURL et la construction de la mutation, eux,
 * sont testés ailleurs (`dataUrl.test.ts`, `mutation.test.ts`).
 */
const digestSha256Expo: FonctionDigestSha256 = (octets) => Crypto.digest(Crypto.CryptoDigestAlgorithm.SHA256, octets);

function repertoireSignatures(chantierId: string): Directory {
  const repertoire = new Directory(Paths.document, "opsys-signatures", chantierId);
  if (!repertoire.exists) {
    repertoire.create({ intermediates: true, idempotent: true });
  }
  return repertoire;
}

/**
 * Décode, écrit, hache et persiste une signature capturée. Lève si `dataUrl` n'est pas
 * reconnaissable (fail-closed : `signature.tsx` ne doit jamais construire de mutation depuis une
 * capture vide ou corrompue — voir `decoderDataUrl`).
 */
export async function enregistrerSignatureCapturee(dataUrl: string, chantierId: string): Promise<MutationOutbox> {
  const decodee = decoderDataUrl(dataUrl);
  if (!decodee) {
    throw new Error("signature : DataURL invalide ou vide, rien à enregistrer");
  }

  const repertoire = repertoireSignatures(chantierId);
  const extension = extensionDepuisMimeType(decodee.mimeType);
  const destination = new File(repertoire, `${genererMutationId()}.${extension}`);
  destination.create();
  destination.write(decodee.base64, { encoding: EncodingType.Base64 });

  const octets = await destination.bytes();
  const sha256 = await empreinteSha256(octets, digestSha256Expo);

  const signature: SignatureCapturee = { uri: destination.uri, sha256, tailleOctets: destination.size, chantierId };

  const horloge = { maintenant: new Date(), decalageMinutesUTC: -new Date().getTimezoneOffset() };
  const mutation = construireMutationSignatureCapture(signature, genererMutationId, horloge);
  const depot = await obtenirDepot();
  return depot.inserer(mutation);
}
