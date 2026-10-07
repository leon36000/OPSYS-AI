import { lireDisponibilite, lireDigest, lireDigestSansSeuils, OUTIL_DISPONIBILITE, OUTIL_DIGEST } from "./stock";
import { CAPTURES_STOCK, disponibiliteFictive, digestFictif, FICTIF, provenanceStock } from "./fixturesStock";

const article = disponibiliteFictive.articles[0];
const variance = digestFictif.variances_significatives[0];
const digestAvecSeuils = CAPTURES_STOCK.digest_seuil_fourni_fictif.corps.result.resultat;

test("les fixtures portent la provenance HTTP MCP et les noms natifs des outils", () => {
  expect(FICTIF).toBe(true);
  expect(provenanceStock.capture_sha256).toBe("0e85744d54a2240532760708aa3079d5024ad95bd2a3b1a5d371d4a0a2d71122");
  expect(Object.keys(CAPTURES_STOCK)).toHaveLength(10);
  expect([OUTIL_DISPONIBILITE, OUTIL_DIGEST]).toEqual(["m6_lire_disponibilite", "m6_produire_digest"]);
});

test("lit les quantités natives, sans unité ajoutée ni recalcul du stock", () => {
  expect(lireDisponibilite(disponibiliteFictive)).toEqual(disponibiliteFictive);
  expect(lireDigest(digestFictif)).toEqual(digestFictif);
  expect(lireDigest(digestAvecSeuils)).toEqual(digestAvecSeuils);
  expect(lireDigestSansSeuils(digestFictif)).toEqual(digestFictif);
  expect(lireDigestSansSeuils(digestAvecSeuils)).toBeNull();
  const manque = CAPTURES_STOCK.reservation_manque_hors_selection_fictif.corps.result.resultat.resultat;
  expect(lireDisponibilite(manque)).toEqual(manque);
});

test.each(["articles_15_fictif", "articles_16_fictif", "reservations_10_fictif", "reservations_11_fictif"] as const)(
  "la capture %s conserve la limite métier, sans total ni curseur", nom => {
    const valeur = CAPTURES_STOCK[nom].corps.result.resultat.resultat;
    expect(lireDisponibilite(valeur)).toEqual(valeur);
  },
);

test.each(["-2.5", "0", "999999999999999999999999999999.125"])("stock signé exact %s gardé en texte", quantite => {
  const brut = { ...disponibiliteFictive, articles: [{ ...article, en_main: quantite,
    disponible: quantite, par_emplacement: { inconnu: quantite } }] };
  expect(lireDisponibilite(brut)?.articles[0].en_main).toBe(quantite);
});

test.each([NaN, Infinity, -Infinity, 1, null, undefined, "NaN", "Infinity", "1e3", " 1", "1,5", ""])(
  "quantité stock mal formée %p ferme la réponse", valeur => {
    expect(lireDisponibilite({ ...disponibiliteFictive, articles: [{ ...article, disponible: valeur }] })).toBeNull();
    expect(lireDisponibilite({ ...disponibiliteFictive, articles: [{ ...article, par_emplacement: { inconnu: valeur } }] })).toBeNull();
  },
);

test.each([null, undefined, [], "stock", 1])("racine invalide %p refuse sans défaut silencieux", valeur => {
  expect(lireDisponibilite(valeur)).toBeNull();
  expect(lireDigest(valeur)).toBeNull();
});

test("booléens obligatoires, limites fermées et ligne illisible ne disparaît pas", () => {
  for (const champ of ["tronque", "reservations_tronquees"] as const) {
    for (const valeur of [undefined, null, 1, "false"]) {
      expect(lireDisponibilite({ ...disponibiliteFictive, [champ]: valeur })).toBeNull();
    }
  }
  expect(lireDisponibilite({ ...disponibiliteFictive, tronque: true })).toBeNull();
  expect(lireDisponibilite({ ...disponibiliteFictive, reservations_tronquees: true })).toBeNull();
  expect(lireDisponibilite({ ...disponibiliteFictive, articles: Array(16).fill(article) })).toBeNull();
  expect(lireDisponibilite({ ...disponibiliteFictive,
    reservations_actives: Array(11).fill(disponibiliteFictive.reservations_actives[0]) })).toBeNull();
  expect(lireDisponibilite({ ...disponibiliteFictive, articles: [article, {}] })).toBeNull();
  expect(lireDisponibilite({ ...disponibiliteFictive, reservations_actives: [{
    ...disponibiliteFictive.reservations_actives[0], statut: "inventé",
  }] })).toBeNull();
});

test("unité manquante est illisible, unité nulle reste inconnue", () => {
  const reservation = disponibiliteFictive.reservations_actives[0];
  const ligne = reservation.lignes_manquantes[0];
  for (const unite of [undefined, 42, ""]) {
    expect(lireDisponibilite({ ...disponibiliteFictive, reservations_actives: [{ ...reservation,
      lignes_manquantes: [{ ...ligne, unite }] }] })).toBeNull();
  }
  expect(lireDisponibilite({ ...disponibiliteFictive, reservations_actives: [{ ...reservation,
    lignes_manquantes: [{ ...ligne, unite: null }] }] })?.reservations_actives[0].lignes_manquantes[0].unite).toBeNull();
});

test.each([NaN, Infinity, -Infinity, "-2", null, undefined, true])("écart digest non natif %p refusé", ecart => {
  expect(lireDigest({ ...digestFictif, variances_significatives: [{ ...variance, ecart }] })).toBeNull();
});

test("écart négatif, nul et positif finis conservés ; suggestions positives natives", () => {
  for (const [ecart, verdict_variance] of [[-2.25, "STOCK_INFERIEUR_AU_THEORIQUE"],
    [0, "AUCUN_ECART"], [3.5, "STOCK_SUPERIEUR_AU_THEORIQUE"]] as const) {
    expect(lireDigest({ ...digestFictif, variances_significatives: [{ ...variance, ecart, verdict_variance }] })
      ?.variances_significatives[0].ecart).toBe(ecart);
  }
  for (const quantite_suggeree of [NaN, Infinity, -Infinity, "20", 0, -1]) {
    expect(lireDigest({ ...digestAvecSeuils,
      reorders: [{ ...digestAvecSeuils.reorders[0], quantite_suggeree }] })).toBeNull();
  }
});

test.each([-1, 1.5, NaN, Infinity, "1", null, undefined, 2 ** 53, 0, 2])("compte de variance %p invalide ou incohérent", nb => {
  expect(lireDigest({ ...digestFictif, nb_variances_stock: nb })).toBeNull();
});

test.each([-1, 1.5, NaN, Infinity, "0", null, undefined, 2 ** 53, 1])("compte de reorder %p invalide ou incohérent", nb => {
  expect(lireDigest({ ...digestFictif, nb_reorders_suggeres: nb })).toBeNull();
});

test("digest fermé sur type, empreinte et listes brutes", () => {
  for (const hash_digest of [undefined, null, "a".repeat(63), "a".repeat(65), "g".repeat(64)]) {
    expect(lireDigest({ ...digestFictif, hash_digest })).toBeNull();
  }
  expect(lireDigest({ ...digestFictif, type: "STOCK" })).toBeNull();
  expect(lireDigest({ ...digestFictif, variances_significatives: [null] })).toBeNull();
  expect(lireDigest({ ...digestFictif, reorders: null })).toBeNull();
  expect(lireDigest({ ...digestFictif, variances_significatives: [{ ...variance, verdict_variance: "INDETERMINE" }] })).toBeNull();
});

test("objets propres sans héritage, accesseurs ni pollution ; normalisation idempotente", () => {
  const get = jest.fn(() => "100");
  const avecAccesseur = { ...article };
  Object.defineProperty(avecAccesseur, "en_main", { get, enumerable: true });
  expect(lireDisponibilite({ ...disponibiliteFictive, articles: [avecAccesseur] })).toBeNull();
  expect(get).not.toHaveBeenCalled();
  expect(lireDisponibilite(Object.create(disponibiliteFictive))).toBeNull();
  expect(lireDigest(Object.create(digestFictif))).toBeNull();
  expect(lireDisponibilite({ ...disponibiliteFictive, articles: [{ ...article,
    par_emplacement: Object.create({ inconnu: "100" }) }] })).toBeNull();
  const nul = Object.assign(Object.create(null), disponibiliteFictive);
  expect(lireDisponibilite(nul)).toEqual(disponibiliteFictive);
  const lu = lireDisponibilite(disponibiliteFictive);
  expect(lireDisponibilite(lu)).toEqual(lu);
  expect(lireDigest(lireDigest(digestFictif))).toEqual(digestFictif);
});

test("listes creuses ou à accesseur et proxy non lisible refusés sans exception", () => {
  const get = jest.fn(() => article);
  const liste = [article];
  Object.defineProperty(liste, "0", { get });
  expect(lireDisponibilite({ ...disponibiliteFictive, articles: liste })).toBeNull();
  expect(get).not.toHaveBeenCalled();
  expect(lireDisponibilite({ ...disponibiliteFictive, articles: Array(1) })).toBeNull();
  const proxy = new Proxy({}, { getPrototypeOf() { throw new Error("fictif"); } });
  expect(lireDisponibilite(proxy)).toBeNull();
});

test("une propriété du prototype global ne remplit jamais un champ JSON absent", () => {
  const { disponible: _absent, ...sansDisponible } = article;
  Object.defineProperty(Object.prototype, "disponible", { value: "999", configurable: true });
  try {
    expect(lireDisponibilite({ ...disponibiliteFictive, articles: [sansDisponible] })).toBeNull();
  } finally {
    Reflect.deleteProperty(Object.prototype, "disponible");
  }
});
