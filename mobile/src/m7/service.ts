import { capturerSessionLecture, obtenirSessionEnvoi } from "../protocole/configuration";
import { invoquerOutil } from "../protocole/client";
import { genererMutationId } from "../outbox/id";
import { declencherVidange, obtenirDepot } from "../outbox/service";
import type { SessionM7 } from "./contrat";
import { creerControleMarketing } from "./controle";

function sessionCourante(): SessionM7 | null {
  const s = obtenirSessionEnvoi();
  return s ? { urlBase: s.urlBase, jeton: s.jeton, appareilId: s.appareilId, personne: s.personne } : null;
}
function capturerSession() {
  const capture = capturerSessionLecture();
  return { session: capture.session, courante: capture.courante };
}
const appeler = async (tool: string, args: Record<string, unknown> = {}) => {
  if (tool !== "m9_lister_demandes_approbation" && tool !== "m7_lister_contenus_chantier") {
    throw new Error("Ce port ne permet que les lectures marketing.");
  }
  const capture = capturerSession();
  const s = capture.session;
  if (!s || !capture.courante()) throw new Error("Identité appareil non confirmée.");
  const r = await invoquerOutil({ fetchImpl: fetch, urlBase: s.urlBase, jeton: s.jeton,
    requete: { tool, args } });
  if (!capture.courante()) throw new Error("Session de lecture modifiée.");
  if (!r.ok) throw new Error(r.echec.message);
  return r.result;
};
export const controleMarketing = creerControleMarketing({
  obtenirSession: sessionCourante,
  capturerSession,
  enLigne: () => true,
  appeler,
  horloge: () => {
    const maintenant = new Date();
    return { maintenant, decalageMinutesUTC: -maintenant.getTimezoneOffset() };
  },
  obtenirDepot,
  vidanger: courante => courante() ? declencherVidange(courante) : Promise.resolve(null),
  genererId: genererMutationId,
});
