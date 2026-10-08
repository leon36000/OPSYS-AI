import { capturerSessionAdminLecture } from "../protocole/configuration";
import { invoquerOutil } from "../protocole/client";
import { obtenirDepotLocal } from "../stockage/service";
import { obtenirDepot, declencherVidange } from "../outbox/service";
import { genererMutationId } from "../outbox/id";
import { creerChargeurLecturesMemoire } from "./lectures";
import { creerControleMemoire } from "./controle";

function horloge() {
  const maintenant = new Date();
  return { maintenant, decalageMinutesUTC: -maintenant.getTimezoneOffset() };
}
function enLigne(): boolean { return controleMemoire.etat().enLigne; }
const lectures = creerChargeurLecturesMemoire({
  capturerSession: capturerSessionAdminLecture,
  obtenirDepot: obtenirDepotLocal,
  appelerOutil: invoquerOutil,
  fetchImpl: fetch,
  horloge,
  enLigne,
});
/** Paquet courant informatif : aucun dépôt, cache, mutation ou consolidation. */
export const chargerPaquetAffaireMemoire = lectures.chargerPaquetAffaire;
/** NetInfo est transmis par actualiserConnectivite ; aucune décision issue du cache. */
export const controleMemoire = creerControleMemoire({
  ...lectures,
  capturerSession: capturerSessionAdminLecture,
  enLigne,
  horloge,
  genererId: genererMutationId,
  obtenirDepot,
  vidanger: courante => courante() ? declencherVidange(courante) : Promise.resolve(null),
});
