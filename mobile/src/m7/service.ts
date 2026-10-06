import { obtenirSessionEnvoi } from "../protocole/configuration";
import { invoquerOutil } from "../protocole/client";
import { genererMutationId } from "../outbox/id";
import type { SessionM7 } from "./contrat";
import { creerControleMarketing } from "./controle";

function sessionCourante(): SessionM7 | null {
  const s = obtenirSessionEnvoi();
  return s ? { urlBase: s.urlBase, jeton: s.jeton, appareilId: s.appareilId, personne: s.personne } : null;
}
const appeler = async (tool: string, args: Record<string, unknown> = {}, mutation?: { idempotencyKey: string; deviceId: string; deviceTimestamp: string }) => {
  const s = sessionCourante();
  if (!s) throw new Error("Identité appareil non confirmée.");
  const r = await invoquerOutil({ fetchImpl: fetch, urlBase: s.urlBase, jeton: s.jeton,
    requete: { tool, args, ...(mutation ?? {}) } });
  if (!r.ok) throw new Error(r.echec.message);
  return r.result;
};
export const controleMarketing = creerControleMarketing({
  obtenirSession: sessionCourante,
  enLigne: () => true,
  appeler,
  maintenant: () => new Date().toISOString(),
  genererId: genererMutationId,
});
