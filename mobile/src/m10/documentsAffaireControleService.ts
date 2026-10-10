import { capturerSessionAdminLecture } from "../protocole/configuration";
import { obtenirDepot, declencherVidange } from "../outbox/service";
import { genererMutationId } from "../outbox/id";
import { creerControleDocumentsAffaireM10 } from "./documentsAffaireControle";
import { chargerIndexDocumentsAffaireM10, chargerVersionDocumentAffaireM10 } from "./documentsAffaireLectureService";

/** Une instance par panneau : le brouillon RAM ne survit pas à sa destruction. */
export function creerControleDocumentsAffaireService(enLigne: () => boolean) {
  return creerControleDocumentsAffaireM10({
    capturerSession: capturerSessionAdminLecture,
    enLigne,
    chargerIndex: (affaire, decalage, limite) => chargerIndexDocumentsAffaireM10(affaire, decalage, limite, enLigne),
    chargerVersion: (affaire, document, version) => chargerVersionDocumentAffaireM10(affaire, document, version, enLigne),
    obtenirDepot,
    vidanger: courante => courante() ? declencherVidange(courante) : Promise.resolve(null),
    genererId: genererMutationId,
    horloge: () => { const maintenant = new Date(); return { maintenant, decalageMinutesUTC: -maintenant.getTimezoneOffset() }; },
  });
}
