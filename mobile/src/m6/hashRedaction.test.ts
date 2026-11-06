import {
  construireFormulaireMateriauxUtilises,
  construireLigneDeclaree,
  interpreterResultatDeclarerMateriauxUtilises,
} from "./materiaux";
import {
  construireArgumentsMateriauxAvecPreuves,
  interpreterMateriauxAvecPreuves,
  validerRecuMateriauxAvecPreuves,
} from "./materiauxAvecPreuves";
import type { MutationOutbox } from "../outbox/types";

const ligne = construireLigneDeclaree({ typeLigne: "perte", materiauId: "MAT-FICTIF", quantite: 2, unite: "pi" });
const formulaire = construireFormulaireMateriauxUtilises("WCT-FICTIF", "INT-FICTIF", "CH-FICTIF", [ligne]);
const mutation = {
  id: "UUID-FICTIF", type: "materials_submit", proprietaire: "EMPLOYEE-FICTIF", chantierId: formulaire.intervention_id,
  payload: { wct_id: formulaire.wct_id, formulaire },
} as unknown as MutationOutbox;
const confirmation = {
  intervention_id: formulaire.intervention_id, chantier_id: formulaire.chantier_id, lignes_declarees: [ligne],
};

test.each([null, "a".repeat(64)])("ACK matériaux hash_tete=%s accepte l'ancienne forme ou l'expurgation explicite", hash => {
  const raw = { ok: true, resultat: { accepte: true, resultat: confirmation, registre: { taille: 1, hash_tete: hash } } };
  expect(interpreterResultatDeclarerMateriauxUtilises(raw, mutation)).toEqual({ accepte: true, resultat: confirmation });
});

test.each([undefined, "faux", 12])("ACK matériaux refuse une valeur hash non conforme (%s)", hash => {
  const raw = { ok: true, resultat: { accepte: true, resultat: confirmation, registre: { taille: 1, hash_tete: hash } } };
  expect(interpreterResultatDeclarerMateriauxUtilises(raw, mutation)).toMatchObject({
    accepte: false, verdict: { code: "accuse_invalide" },
  });
});

const photoHash = "b".repeat(64);
const formulairePreuve = { ...formulaire, lignes_materiaux: [{ ...ligne, type_ligne: "perte" as const }] };
const preuves = [{ position_ligne: 0, note: "Fait fictif observé.", photos: [`fichier:sha256:${photoHash}`] }];
const argsPreuve = construireArgumentsMateriauxAvecPreuves(formulairePreuve, preuves);
const mutationPreuve = {
  id: "UUID-PREUVE-FICTIF", type: "materials_submit_with_proofs", proprietaire: "EMPLOYEE-FICTIF",
  chantierId: formulaire.intervention_id,
  payload: { ...argsPreuve, _fichiers_locaux: [{ capture_id: "CAPTURE-FICTIVE", empreinte_sha256: photoHash,
    taille_octets: 12, type_mime: "image/jpeg" }] },
} as unknown as MutationOutbox;
const ackPreuve = (hachages: string | null) => ({ ok: true, resultat: { accepte: true,
  resultat: { wct_id: formulaire.wct_id, intervention_id: formulaire.intervention_id, chantier_id: formulaire.chantier_id,
    lignes_declarees: [ligne], preuves: [{ position_ligne: 0,
      reference_mouvement: { registre: "principal", index: 0, hash_maillon: hachages },
      reference_preuve: { registre: "preuves_pertes_bris", index: 0, hash_maillon: hachages }, nombre_photos: 1 }] },
  registre: { taille: 1, hash_tete: hachages } } });

test("ACK preuve expurgé conserve la ligne, la position, le compte photo et les registres sans preuve d'intégrité", () => {
  const lu = interpreterMateriauxAvecPreuves(ackPreuve(null), mutationPreuve);
  expect(lu.accepte).toBe(true);
  if (!lu.accepte) throw new Error("ACK expurgé fictif refusé");
  expect(lu.resultat.preuves).toEqual([{ position_ligne: 0,
    reference_mouvement: { registre: "principal", index: 0, hash_maillon: null },
    reference_preuve: { registre: "preuves_pertes_bris", index: 0, hash_maillon: null }, nombre_photos: 1 }]);
  expect(lu.resultat.registre_confirmation).toEqual({ taille: 1, hash_tete: null });
  expect(validerRecuMateriauxAvecPreuves({ ...mutationPreuve, statut: "envoyee", resumeAccepte: lu.resultat })).toBe(true);
});

test("ACK preuve historique complet reste accepté et liens/photo altérés restent refusés", () => {
  const historique = ackPreuve("c".repeat(64));
  expect(interpreterMateriauxAvecPreuves(historique, mutationPreuve).accepte).toBe(true);
  const photoCountAlt = structuredClone(ackPreuve(null));
  photoCountAlt.resultat.resultat.preuves[0].nombre_photos = 0;
  expect(interpreterMateriauxAvecPreuves(photoCountAlt, mutationPreuve)).toMatchObject({
    accepte: false, verdict: { code: "accuse_invalide" },
  });
  const indexAlt = structuredClone(ackPreuve(null));
  indexAlt.resultat.resultat.preuves[0].reference_mouvement.index = 1;
  expect(interpreterMateriauxAvecPreuves(indexAlt, mutationPreuve)).toMatchObject({
    accepte: false, verdict: { code: "accuse_invalide" },
  });
});
