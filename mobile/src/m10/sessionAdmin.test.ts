import { capturerSessionAdminLecture, definirConfigurationAppel, definirPersonneConfirmee } from "../protocole/configuration";

const config = { urlBase: "https://core.fictif.test", jeton: "jeton-fictif", appareilId: "appareil-fictif" };
const personne = { jeton: config.jeton, appareilId: config.appareilId, personne: "gestionnaire.fictif" };
afterEach(() => { definirPersonneConfirmee(null); definirConfigurationAppel(null); });

test.each([undefined, "employee", "seller", "client"])("un rôle %s confirmé ne peut pas ouvrir une projection admin, même hors ligne", role => {
  definirConfigurationAppel(config); definirPersonneConfirmee({ ...personne, role });
  const capture = capturerSessionAdminLecture();
  expect(capture.session).toBeNull(); expect(capture.courante()).toBe(false);
});

test("le rôle admin ouvre la lecture puis son retrait au même jeton/personne invalide aussi le cache", () => {
  definirConfigurationAppel(config); definirPersonneConfirmee({ ...personne, role: "admin" });
  const ancienne = capturerSessionAdminLecture();
  expect(ancienne.session?.personne).toBe(personne.personne); expect(ancienne.courante()).toBe(true);
  definirPersonneConfirmee({ ...personne, role: "seller" });
  expect(ancienne.courante()).toBe(false); expect(capturerSessionAdminLecture().session).toBeNull();
});
