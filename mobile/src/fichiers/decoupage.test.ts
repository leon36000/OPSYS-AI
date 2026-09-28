import {
  NOMBRE_BLOCS_MAX,
  TAILLE_BLOC_OCTETS,
  TAILLE_FICHIER_MAX_OCTETS,
  calculerNombreBlocs,
  decouperEnBlocs,
  validerTailleFichier,
} from "./decoupage";

describe("calculerNombreBlocs", () => {
  test("un octet -> un bloc", () => {
    expect(calculerNombreBlocs(1)).toBe(1);
  });

  test("exactement TAILLE_BLOC_OCTETS -> un bloc", () => {
    expect(calculerNombreBlocs(TAILLE_BLOC_OCTETS)).toBe(1);
  });

  test("TAILLE_BLOC_OCTETS + 1 -> deux blocs (le dernier partiel)", () => {
    expect(calculerNombreBlocs(TAILLE_BLOC_OCTETS + 1)).toBe(2);
  });

  test("taille maximale du contrat -> jamais plus que NOMBRE_BLOCS_MAX", () => {
    expect(calculerNombreBlocs(TAILLE_FICHIER_MAX_OCTETS)).toBeLessThanOrEqual(NOMBRE_BLOCS_MAX);
    expect(calculerNombreBlocs(TAILLE_FICHIER_MAX_OCTETS)).toBe(40);
  });
});

describe("decouperEnBlocs", () => {
  test("fichier vide -> aucun bloc", () => {
    expect(decouperEnBlocs(new Uint8Array(0))).toEqual([]);
  });

  test("plus petit qu'un bloc -> un seul bloc partiel, contenu exact", () => {
    const octets = Uint8Array.from([1, 2, 3]);
    const blocs = decouperEnBlocs(octets);
    expect(blocs).toHaveLength(1);
    expect(Array.from(blocs[0])).toEqual([1, 2, 3]);
  });

  test("exactement deux blocs pleins + un dernier bloc de 100 octets", () => {
    const taille = TAILLE_BLOC_OCTETS * 2 + 100;
    const octets = Uint8Array.from({ length: taille }, (_, i) => i % 256);
    const blocs = decouperEnBlocs(octets);
    expect(blocs).toHaveLength(3);
    expect(blocs[0]).toHaveLength(TAILLE_BLOC_OCTETS);
    expect(blocs[1]).toHaveLength(TAILLE_BLOC_OCTETS);
    expect(blocs[2]).toHaveLength(100);
    // Reconstruction bout à bout = octets d'origine, aucun octet perdu ni dupliqué.
    const reconstruit = new Uint8Array(taille);
    let curseur = 0;
    for (const bloc of blocs) {
      reconstruit.set(bloc, curseur);
      curseur += bloc.length;
    }
    expect(Array.from(reconstruit)).toEqual(Array.from(octets));
  });

  test("dernier bloc jamais > TAILLE_BLOC_OCTETS, jamais 0", () => {
    for (const taille of [1, TAILLE_BLOC_OCTETS, TAILLE_BLOC_OCTETS + 1, TAILLE_BLOC_OCTETS * 3]) {
      const blocs = decouperEnBlocs(new Uint8Array(taille));
      const dernier = blocs[blocs.length - 1];
      expect(dernier.length).toBeGreaterThan(0);
      expect(dernier.length).toBeLessThanOrEqual(TAILLE_BLOC_OCTETS);
    }
  });
});

describe("validerTailleFichier", () => {
  test("bornes valides (1 et TAILLE_FICHIER_MAX_OCTETS) -> aucun verdict", () => {
    expect(validerTailleFichier(1)).toBeNull();
    expect(validerTailleFichier(TAILLE_FICHIER_MAX_OCTETS)).toBeNull();
  });

  test("0 -> REJ-FICHIER-TROP-VOLUMINEUX (jamais un fichier vide envoyé)", () => {
    expect(validerTailleFichier(0)?.code).toBe("REJ-FICHIER-TROP-VOLUMINEUX");
  });

  test("au-delà de TAILLE_FICHIER_MAX_OCTETS -> REJ-FICHIER-TROP-VOLUMINEUX", () => {
    expect(validerTailleFichier(TAILLE_FICHIER_MAX_OCTETS + 1)?.code).toBe("REJ-FICHIER-TROP-VOLUMINEUX");
  });

  test("non entier -> refusé (jamais une taille approchée acceptée)", () => {
    expect(validerTailleFichier(10.5)).not.toBeNull();
  });
});
