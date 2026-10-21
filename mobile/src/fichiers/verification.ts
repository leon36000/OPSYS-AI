import { empreinteSha256 } from "./empreinte";
import type { FonctionDigestSha256 } from "./empreinte";

/**
 * Garde fail-closed exigée par la mission T1.4-f : « lecture des octets du fichier local (vérifie
 * que le SHA-256 relu correspond à celui capturé ; sinon état d'erreur explicite, jamais
 * d'envoi) ». Un fichier local a pu être modifié/corrompu entre la capture (`src/photos/service.ts`
 * /`src/signature/service.ts`, qui hachent au moment même de l'écriture) et l'envoi, parfois bien
 * plus tard (R12 §4, brouillon local persistant) — cette fonction est le DERNIER contrôle avant
 * qu'un octet ne parte sur le réseau : `digest` est INJECTÉ (même fonction que
 * `src/fichiers/empreinte.ts::FonctionDigestSha256`), donc testable sans `expo-crypto`.
 */
export type ResultatVerificationEmpreinte =
  | { readonly ok: true }
  | { readonly ok: false; readonly sha256Capture: string; readonly sha256Relu: string };

export async function verifierEmpreinteFichier(
  octets: Uint8Array<ArrayBuffer>,
  sha256Capture: string,
  digest: FonctionDigestSha256,
): Promise<ResultatVerificationEmpreinte> {
  const sha256Relu = await empreinteSha256(octets, digest);
  if (sha256Relu !== sha256Capture) {
    return { ok: false, sha256Capture, sha256Relu };
  }
  return { ok: true };
}
