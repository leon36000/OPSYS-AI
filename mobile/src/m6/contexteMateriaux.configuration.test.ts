import { capturerSessionMateriauxLecture, definirConfigurationAppel, definirPersonneConfirmee } from "../protocole/configuration";

const FICTIF = true;
const config = { urlBase: "https://fictif.invalid", jeton: "JETON-FICTIF", appareilId: "APPAREIL-FICTIF" };
beforeEach(() => { definirConfigurationAppel(null); definirPersonneConfirmee(null); });
afterEach(() => { definirConfigurationAppel(null); definirPersonneConfirmee(null); });
test.each([undefined, "seller", "client", "operator", "ADMIN", ""])('rôle %s ne construit aucune lecture', role => {
  expect(FICTIF).toBe(true); definirConfigurationAppel(config);
  definirPersonneConfirmee({ ...config, personne: "PERSONNE-FICTIVE", role });
  const c = capturerSessionMateriauxLecture(); expect(c.session).toBeNull(); expect(c.courante()).toBe(false);
});
test.each(["employee", "admin"])('rôle %s capture une session liée au jeton', role => {
  definirConfigurationAppel(config); definirPersonneConfirmee({ ...config, personne: "PERSONNE-FICTIVE", role });
  const c = capturerSessionMateriauxLecture(); expect(c.session).toMatchObject({ personne: "PERSONNE-FICTIVE", jeton: config.jeton });
  expect(c.courante()).toBe(true);
  definirPersonneConfirmee({ ...config, personne: "AUTRE-PERSONNE-FICTIVE", role });
  definirPersonneConfirmee({ ...config, personne: "PERSONNE-FICTIVE", role });
  expect(c.courante()).toBe(false);
});
test.each(["role", "jeton", "appareil", "logout"])('%s ferme la capture et ses callbacks', changement => {
  definirConfigurationAppel(config); definirPersonneConfirmee({ ...config, personne: "PERSONNE-FICTIVE", role: "employee" });
  const c = capturerSessionMateriauxLecture();
  if (changement === "role") definirPersonneConfirmee({ ...config, personne: "PERSONNE-FICTIVE", role: "seller" });
  if (changement === "jeton") definirConfigurationAppel({ ...config, jeton: "JETON-REMPLACE-FICTIF" });
  if (changement === "appareil") definirConfigurationAppel({ ...config, appareilId: "AUTRE-APPAREIL-FICTIF" });
  if (changement === "logout") definirConfigurationAppel(null);
  expect(c.courante()).toBe(false);
});
