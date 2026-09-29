import {
  OUTIL_LIRE_DEVIS,
  STATUTS_DEVIS,
  construireArgumentsLireDevis,
  estDevisVendeurValide,
  interpreterResultatLireDevis,
  lireDevisVendeur,
} from "./devis";
import { devisInterneBrut, enveloppeAcceptee, enveloppeRefusee } from "../vendeur/donneesDeTest";

/** Des valeurs de coût et de marge qu'aucun autre champ ne porte : si elles réapparaissent, c'est une fuite. */
const COUT_UNITAIRE = "111.11";
const COUT_LIGNE = "222.22";
const COUT_TOTAL = "333.33";
const TAUX_MARGE = "0.4444";

function devisAvecCout(surcharges: Record<string, unknown> = {}): Record<string, unknown> {
  const base = devisInterneBrut("devis-a-01");
  const ligne = (base.lignes as Record<string, unknown>[])[0];
  return {
    ...base,
    lignes: [{ ...ligne, cout_unitaire: COUT_UNITAIRE, cout_ligne: COUT_LIGNE }],
    cout_total: COUT_TOTAL,
    taux_marge: TAUX_MARGE,
    approbateur: "nathan.fictif",
    ...surcharges,
  };
}

describe("arguments de m3_lire_devis", () => {
  test("le seul devis_id : jamais role (employe retirerait le prix), jamais une personne", () => {
    expect(OUTIL_LIRE_DEVIS).toBe("m3_lire_devis");
    const args = construireArgumentsLireDevis("devis-a-01");
    expect(args).toEqual({ devis_id: "devis-a-01" });
    expect(Object.keys(args)).toEqual(["devis_id"]);
  });
});

describe("le devis du vendeur : statut et prix, ni coût ni marge", () => {
  test("statut, prix total et lignes décrites sont lus", () => {
    const lecture = interpreterResultatLireDevis(enveloppeAcceptee(devisInterneBrut("devis-a-01")));
    expect(lecture).toEqual({
      ok: true,
      devis: {
        devisId: "devis-a-01",
        leadId: "lead-a-01",
        chantierId: null,
        statut: "brouillon",
        horodatage: "2026-09-01T09:05:00-04:00",
        prixTotal: "360.00",
        lignes: [
          {
            referenceLigne: "devis-a-01-L0",
            description: "Gouttière alu 5 po (fictif)",
            quantite: "30",
            unite: "pi_lin",
            prixUnitaire: "12.00",
            prixLigne: "360.00",
          },
        ],
      },
    });
  });

  test("le serveur rend le coût et la marge au vendeur (vue interne) : l'app n'en garde AUCUN", () => {
    const brut = devisAvecCout();
    // Preuve que la réponse porte bien coût et marge : sans elle, ce test ne prouverait rien.
    const texteBrut = JSON.stringify(brut);
    for (const secret of [COUT_UNITAIRE, COUT_LIGNE, COUT_TOTAL, TAUX_MARGE, "cout_", "taux_marge"]) {
      expect(texteBrut).toContain(secret);
    }

    const lu = lireDevisVendeur(brut);
    expect(lu).not.toBeNull();
    const texteLu = JSON.stringify(lu);
    for (const secret of [COUT_UNITAIRE, COUT_LIGNE, COUT_TOTAL, TAUX_MARGE, "cout", "marge", "taux", "approbateur", "nathan"]) {
      expect(texteLu).not.toContain(secret);
    }
    expect(Object.keys(lu ?? {}).sort()).toEqual(
      ["chantierId", "devisId", "horodatage", "leadId", "lignes", "prixTotal", "statut"].sort(),
    );
    expect(Object.keys(lu?.lignes[0] ?? {}).sort()).toEqual(
      ["description", "prixLigne", "prixUnitaire", "quantite", "referenceLigne", "unite"].sort(),
    );
  });

  test("les statuts sont ceux de M3 ; un statut inconnu est gardé tel quel, jamais remplacé", () => {
    expect(STATUTS_DEVIS).toEqual(["brouillon", "envoye", "accepte"]);
    for (const statut of STATUTS_DEVIS) {
      expect(lireDevisVendeur(devisInterneBrut("d", { statut }))?.statut).toBe(statut);
    }
    expect(lireDevisVendeur(devisInterneBrut("d", { statut: "expire" }))?.statut).toBe("expire");
  });

  test("un montant absent ou illisible est null : l'app ne recalcule rien", () => {
    const ligne = (devisInterneBrut("d").lignes as Record<string, unknown>[])[0];
    const lu = lireDevisVendeur(
      devisInterneBrut("d", {
        prix_total: undefined,
        lignes: [{ ...ligne, prix_unitaire: "douze", prix_ligne: 360, quantite: undefined }],
      }),
    );
    expect(lu?.prixTotal).toBeNull();
    expect(lu?.lignes[0]).toMatchObject({ prixUnitaire: null, prixLigne: null, quantite: null });
  });

  test("un prix total qui n'est pas un texte décimal est null (jamais un nombre flottant accepté)", () => {
    expect(lireDevisVendeur(devisInterneBrut("d", { prix_total: 360 }))?.prixTotal).toBeNull();
    expect(lireDevisVendeur(devisInterneBrut("d", { prix_total: "3 60" }))?.prixTotal).toBeNull();
    expect(lireDevisVendeur(devisInterneBrut("d", { prix_total: "1234.5" }))?.prixTotal).toBe("1234.5");
  });

  test.each([
    ["sans devis_id", { devis_id: undefined }],
    ["sans lead_id", { lead_id: undefined }],
    ["sans statut", { statut: undefined }],
    ["sans horodatage", { horodatage: undefined }],
    ["lignes absentes", { lignes: undefined }],
    ["une ligne sans description", { lignes: [{ reference_ligne: "L0", quantite: "1" }] }],
    ["une ligne qui n'est pas un objet", { lignes: ["gouttière"] }],
  ])("devis illisible (%s) : jamais un devis montré à moitié", (_nom, surcharge) => {
    expect(interpreterResultatLireDevis(enveloppeAcceptee(devisInterneBrut("d", surcharge)))).toMatchObject({
      ok: false,
      genre: "illisible",
      verdict: { code: "reponse_illisible" },
    });
  });

  test("le devis d'un autre, un lead sans propriétaire ou un devis inconnu : le même refus, verdict tel quel", () => {
    const detail = "devis inconnu : 'devis-b-01'";
    expect(interpreterResultatLireDevis(enveloppeRefusee("REJ-DEVIS-INTROUVABLE", detail))).toEqual({
      ok: false,
      genre: "refus",
      verdict: { code: "REJ-DEVIS-INTROUVABLE", detail },
    });
  });

  test("une réponse tronquée par le socle n'est jamais lue comme un devis", () => {
    expect(interpreterResultatLireDevis({ ok: true, tronque: true, apercu: "{" })).toMatchObject({
      ok: false,
      genre: "technique",
      verdict: { code: "reponse_tronquee" },
    });
  });
});

describe("estDevisVendeurValide — ce que le cache relit", () => {
  const propre = lireDevisVendeur(devisInterneBrut("devis-a-01"))!;

  test("un devis que l'app a lu elle-même est valide, avec ou sans prix", () => {
    expect(estDevisVendeurValide(propre)).toBe(true);
    expect(estDevisVendeurValide({ ...propre, prixTotal: null, chantierId: "C1" })).toBe(true);
    expect(estDevisVendeurValide(JSON.parse(JSON.stringify(propre)))).toBe(true);
  });

  test.each([
    ["une clé de coût en plus sur le devis", { ...propre, cout_total: COUT_TOTAL }],
    ["une clé de marge en plus sur le devis", { ...propre, tauxMarge: "0.2" }],
    ["une clé de coût en plus sur une ligne", { ...propre, lignes: [{ ...propre.lignes[0], coutLigne: "1.00" }] }],
    ["une clé en moins", (({ statut: _statut, ...reste }) => reste)(propre)],
    ["un prix qui n'est pas un décimal", { ...propre, prixTotal: "beaucoup" }],
    ["des lignes qui ne sont pas une liste", { ...propre, lignes: null }],
    ["null", null],
    ["un texte", "devis"],
  ])("refusé : %s", (_nom, valeur) => {
    expect(estDevisVendeurValide(valeur)).toBe(false);
  });
});
