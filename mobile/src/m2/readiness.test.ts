import {
  construireArgumentsReadiness,
  interpreterReadiness,
  lireMarqueurReadiness,
} from "./readiness";
import { enveloppeAcceptee, enveloppeRefusee } from "../vendeur/donneesDeTest";

const LEAD = "lead-a-01";
const MARQUEUR = {
  readiness_ok: true,
  lead_id: LEAD,
  hash_tete_registre: "a".repeat(64),
  empreinte: "B".repeat(64),
  horodatage: "2026-10-05T14:03:22-04:00",
};

describe("contrat mobile de m2_evaluer_readiness", () => {
  test("construit seulement lead_id et horodatage", () => {
    expect(construireArgumentsReadiness(LEAD, MARQUEUR.horodatage)).toEqual({
      lead_id: LEAD,
      horodatage: MARQUEUR.horodatage,
    });
  });

  test("accepte un marqueur serveur complet et strict", () => {
    expect(interpreterReadiness(enveloppeAcceptee(MARQUEUR), LEAD)).toEqual({
      genre: "pret",
      marqueur: {
        leadId: LEAD,
        hashTeteRegistre: MARQUEUR.hash_tete_registre,
        empreinte: MARQUEUR.empreinte,
        horodatage: MARQUEUR.horodatage,
      },
    });
  });

  test.each([
    ["readiness false", { ...MARQUEUR, readiness_ok: false }],
    ["lead différent", { ...MARQUEUR, lead_id: "lead-b-01" }],
    ["hash trop court", { ...MARQUEUR, hash_tete_registre: "a".repeat(63) }],
    ["hash non hexadécimal", { ...MARQUEUR, hash_tete_registre: "g".repeat(64) }],
    ["empreinte manquante", { ...MARQUEUR, empreinte: undefined }],
    ["empreinte mal formée", { ...MARQUEUR, empreinte: "x".repeat(64) }],
    ["date sans fuseau", { ...MARQUEUR, horodatage: "2026-10-05T14:03:22" }],
    ["date invalide", { ...MARQUEUR, horodatage: "2026-99-99T14:03:22Z" }],
    ["jour inexistant normalisé par Date.parse", { ...MARQUEUR, horodatage: "2026-02-30T14:03:22Z" }],
    ["heure 24 normalisée par Date.parse", { ...MARQUEUR, horodatage: "2026-10-05T24:00:00Z" }],
    ["fuseau invalide", { ...MARQUEUR, horodatage: "2026-10-05T14:03:22+25:00" }],
    ["clé supplémentaire", { ...MARQUEUR, source: "cache" }],
  ])("refuse de déclarer prêt si %s", (_cas, marqueur) => {
    expect(interpreterReadiness(enveloppeAcceptee(marqueur), LEAD)).toMatchObject({ genre: "non_verifie" });
  });

  test("garde le verdict métier exact; une enveloppe ou une charge mal formée reste non vérifiée", () => {
    expect(interpreterReadiness(enveloppeRefusee("REJ-TRANSITION-ILLEGALE", "ville manquante"), LEAD)).toEqual({
      genre: "refus",
      verdict: { code: "REJ-TRANSITION-ILLEGALE", detail: "ville manquante" },
    });
    expect(interpreterReadiness({ ok: true, resultat: { accepte: true, resultat: MARQUEUR } }, "autre")).toMatchObject({ genre: "non_verifie" });
    expect(interpreterReadiness({ ok: true, resultat: { accepte: true, resultat: {} } }, LEAD)).toMatchObject({ genre: "non_verifie" });
  });

  test("le lecteur du marqueur seul échoue fermé", () => {
    expect(lireMarqueurReadiness(null, LEAD)).toBeNull();
    expect(lireMarqueurReadiness(MARQUEUR, "autre")).toBeNull();
  });
});
