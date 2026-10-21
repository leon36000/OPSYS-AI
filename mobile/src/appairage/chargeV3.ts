/**
 * Port fidèle de `buildDeviceAuthPayloadV3`/`normalizeDeviceMetadataForAuth`
 * (`core/packages/gateway-client/src/device-auth.ts:1-64`, lus, jamais exécutés ni importés —
 * ADR-0008, « le bac à sable n'exécute pas le code de core/ »). Le serveur reconstruit CETTE
 * MÊME chaîne à partir des champs de `ConnectParams` pour vérifier la signature
 * (`core/src/gateway/server/ws-connection/handshake-auth-helpers.ts:288-325`,
 * `resolveDeviceSignaturePayloadVersion`) : un seul octet de différence fait échouer
 * l'appairage (`device-signature`, `connect-device-proof.ts:91-94`). D'où un test byte-à-byte
 * contre des vecteurs tirés tels quels des tests du core (`chargeV3.test.ts`).
 *
 * Pourquoi une copie plutôt qu'un import de `core/` : voir la décision d'intégration dans
 * `docs/architecture/MOBILE.md` (§ Appairage) — en résumé, `mobile/` ne doit JAMAIS faire
 * exécuter (ni, par transitivité, faire typechecker/bundler) du code sous `core/`, y compris via
 * un jour `npm test`/`npm run typecheck` local à `mobile/`.
 */

/**
 * Port de `normalizeDeviceMetadataForAuth` (`device-auth.ts:1-10`). Ne touche QUE les lettres
 * ASCII A-Z (pas de casse Unicode complète) — voir le vecteur « İOS » -> « İos » dans
 * `core/src/gateway/device-auth.test.ts:66-70`, reproduit dans `chargeV3.test.ts`.
 */
export function normaliserMetadonneeAppareil(valeur: string | null | undefined): string {
  if (typeof valeur !== "string") {
    return "";
  }
  const coupee = valeur.trim();
  if (!coupee) {
    return "";
  }
  return coupee.replace(/[A-Z]/g, (caractere) => String.fromCharCode(caractere.charCodeAt(0) + 32));
}

export interface ParametresChargeAppairageV3 {
  readonly deviceId: string;
  readonly clientId: string;
  readonly clientMode: string;
  readonly role: string;
  readonly scopes: readonly string[];
  readonly signedAtMs: number;
  readonly token?: string | null;
  readonly nonce: string;
  readonly platform?: string | null;
  readonly deviceFamily?: string | null;
}

/**
 * Port de `buildDeviceAuthPayloadV3` (`device-auth.ts:44-64`) : même ordre de concaténation,
 * même séparateur `|`, mêmes emplacements vides pour les champs optionnels absents.
 */
export function construireChargeAppairageV3(params: ParametresChargeAppairageV3): string {
  const scopes = params.scopes.join(",");
  const token = params.token ?? "";
  const platform = normaliserMetadonneeAppareil(params.platform);
  const deviceFamily = normaliserMetadonneeAppareil(params.deviceFamily);
  return [
    "v3",
    params.deviceId,
    params.clientId,
    params.clientMode,
    params.role,
    scopes,
    String(params.signedAtMs),
    token,
    params.nonce,
    platform,
    deviceFamily,
  ].join("|");
}
