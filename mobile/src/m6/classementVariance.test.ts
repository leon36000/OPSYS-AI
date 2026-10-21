import captureNull from "./fixturesClassementNullSQL.json";
import fixtures from "./fixturesClassementVariancesSQL.json";
import { DESCRIPTEURS_MUTATION } from "../outbox/descripteurs";
import type { MutationOutbox } from "../outbox/types";
const capture = (phase: string) => fixtures.captures.find(c => c.phase === phase)!;
const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v));
const api = () => require("./classementVariance") as typeof import("./classementVariance");
const horloge = { maintenant: new Date("2026-10-08T17:00:00Z"), decalageMinutesUTC: -240 };
const args = () => capture("classement_v1").request.arguments as unknown as import("./classementVariance").ArgumentsClassementVarianceM6;
function mutation(): MutationOutbox {
  return { ...api().creerMutationClassementVariance(args(), () => "9a276b43-3d42-4a55-a22f-03fe7a784a10", horloge, { appareilId: "APP-CLASSEMENT-FICTIF", urlBase: "https://fictif.invalid" }),
    proprietaire: "admin.contexte.fictif" };
}
test("le vrai descripteur classe la cause dans la file durable et ferme les refus HTTP incertains", () => {
  const d = DESCRIPTEURS_MUTATION.get("variance_cause_classification");
  expect(d).toBeDefined(); expect(d?.tool).toBe("m6_classer_cause_variance_appareil");
  expect(d?.serialiserParChantier).toBe(true); expect(d?.conserverRefusHttpIncertains).toBe(true);
});
test("les deux listes SQL réelles conservent source et dernier classement sans recalcul", () => {
  for (const phase of ["liste_initiale", "liste_classee"]) {
    const c = capture(phase);
    const lu = api().lireVariancesClassables(c.enveloppe, c.request.arguments);
    expect(lu.ok).toBe(true);
    if (lu.ok) expect(lu.value).toEqual((c.enveloppe.resultat as any).resultat);
  }
});
test("l'historique SQL garde les références v1/v2 et la page bornée courante", () => {
  for (const phase of ["historique_v1_v2", "historique_page1"]) {
    const c = capture(phase); const lu = api().lireHistoriqueClassements(c.enveloppe, c.request.arguments);
    expect(lu.ok).toBe(true);
    if (lu.ok) expect(lu.value).toEqual((c.enveloppe.resultat as any).resultat);
  }
});
test("ACK v1 et reprise v1 après v2 restent liés à leur propre intention", () => {
  const m = mutation();
  for (const rejoue of [false, true]) {
    const lu = api().interpreterClassementVariance({ ...capture("classement_v1").enveloppe, rejoue }, m);
    expect(lu.accepte).toBe(true);
    if (lu.accepte) expect(lu.resume.reference.index).toBe(0);
  }
  expect(api().interpreterClassementVariance(capture("classement_v2").enveloppe, m).accepte).toBe(false);
});
test.each(["selection", "cause", "motif", "reference_precedente", "auteur", "horodatage_appareil_declare", "references_pieces"])("ACK %s remplacé ne libère pas une intention", key => {
  const c = clone(capture("classement_v1").enveloppe) as any;
  const r = c.resultat.resultat;
  if (key === "selection") r.selection.position_ligne++;
  else if (key === "cause") r.cause = "breakage";
  else if (key === "motif") r.motif = "Autre motif fictif";
  else if (key === "reference_precedente") r.reference_precedente = r.reference;
  else if (key === "auteur") r.auteur.personne = "autre.admin.fictif";
  else if (key === "horodatage_appareil_declare") r.horodatage_appareil_declare = "2026-10-08T17:00:01+00:00";
  else r.references_pieces = [capture("liste_initiale").enveloppe.resultat.resultat!.lignes![0].pieces_disponibles_a_selectionner[0]];
  expect(api().interpreterClassementVariance(c, mutation())).toMatchObject({ accepte: false, verdict: { code: "accuse_invalide" } });
});
test("registre ACK faux et reçu local non lié restent inconnus", () => {
  const c = clone(capture("classement_v1").enveloppe) as any; c.resultat.registre.taille = 9;
  expect(api().interpreterClassementVariance(c, mutation()).accepte).toBe(false);
  const lu = api().interpreterClassementVariance(capture("classement_v1").enveloppe, mutation());
  expect(lu.accepte).toBe(true);
  if (lu.accepte) {
    const m = { ...mutation(), statut: "envoyee" as const, resumeAccepte: lu.resume };
    expect(api().validerRecuClassementVariance(m)).toBe(true);
    expect(api().validerRecuClassementVariance({ ...m, payload: { ...m.payload, cause: "breakage" } })).toBe(false);
  }
});
test.each(["IDENTITE-INVALIDE", "SOURCE-INCOHERENTE", "SORTIE-TROP-VOLUMINEUSE"])("refus préclaim %s garde l'issue inconnue", suffix => {
  expect(api().interpreterClassementVariance({ ok: false, erreur: `REJ-M6-CLASSEMENT-${suffix}`, details: "FICTIF" }, mutation()))
    .toMatchObject({ accepte: false, verdict: { code: "accuse_invalide" } });
});
test("le refus legacy même frais sans preuve indépendante conserve une issue inconnue", () => {
  expect(api().interpreterClassementVariance(capture("revision_perimee").enveloppe, mutation()))
    .toMatchObject({ accepte: false, verdict: { code: "accuse_invalide" } });
});
test.each(["autre_objet", "page_sans_progres", "position_page", "champ_prix"])("liste incohérente %s fermée en entier", kind => {
  const c = clone(capture("liste_initiale")) as any; const r = c.enveloppe.resultat.resultat;
  if (kind === "autre_objet") r.lignes[0].selection.wct_id = "AUTRE-WCT-FICTIF";
  else if (kind === "page_sans_progres") { r.lignes = []; r.pagination.affichees = 0; r.pagination.decalage_suivant = 0; }
  else if (kind === "position_page") r.lignes[0].selection.position_ligne = -1;
  else r.lignes[0].source_ligne.prix = "10.00";
  expect(api().lireVariancesClassables(c.enveloppe, c.request.arguments).ok).toBe(false);
});
test("getter jamais exécuté et cause/motif laissés intacts sans choix automatique", () => {
  const getter = jest.fn(); const v = Object.defineProperty({}, "ok", { get: getter, enumerable: true });
  expect(api().lireVariancesClassables(v, capture("liste_initiale").request.arguments).ok).toBe(false); expect(getter).not.toHaveBeenCalled();
  expect(() => api().creerMutationClassementVariance({ ...args(), cause: "" } as any, () => "UUID-FICTIF", horloge, { appareilId: "APP-CLASSEMENT-FICTIF", urlBase: "https://fictif.invalid" })).toThrow();
  const m = mutation(); expect(api().argumentsRpcClassementVariance(m)).toEqual(args());
  expect(m.payload.motif).toBe(args().motif); expect(m.statut).toBe("en_attente");
});
test("un ACK d'un autre appareil ne confirme pas l'intention créée pour cet appareil", () => {
  const c = clone(capture("classement_v1").enveloppe) as any;
  c.resultat.resultat.appareil_id = "AUTRE-APPAREIL-FICTIF";
  expect(api().interpreterClassementVariance(c, mutation())).toMatchObject({ accepte: false, verdict: { code: "accuse_invalide" } });
});

test("le vrai NON_PREVU lié à une PERTE garde son ratio inconnu, sans zéro inventé", () => {
  const lu = api().lireVariancesClassables(captureNull.response, captureNull.request.arguments);
  expect(lu.ok).toBe(true);
  if (lu.ok) {
    expect(lu.value.lignes[0].source_ligne.ecart_pourcentage).toBeNull();
    expect(lu.value.lignes[0].source_ligne.quantite_prevue).toBe("0.0");
    expect(lu.value.lignes[0].source_ligne.unite).toBeNull();
  }
});

// Encodeur Python réel RAM : args de capture historique, variantes de motif contrefactuelles.
// SHA6195153… ; ces vecteurs ne sont ni DTO SQL ni preuve Gateway.
const vecteursPython = [
  {
    "name": "base-original",
    "arguments": {
      "selection": {
        "wct_id": "491297daf122f43a179c6d028921cd228e748d7b2979b5aa6d902a714f862564",
        "reference_variance": {
          "type": "m6.variance_chantier",
          "evenement_id": "m6-variance-491297daf122f43a179c6d028921cd228e748d7b2979b5aa6d902a714f862564-evaluee",
          "empreinte_charge": "351822adaa27a28f711ab7bd3a1cfab02a66a9754e0e1268e0096e82c329bb84"
        },
        "position_ligne": 0,
        "materiau_id": "MAT-CONTEXTE-FICTIF"
      },
      "cause": "waste",
      "motif": "FICTIF : cause choisie par admin",
      "classement_attendu": null,
      "references_pieces": []
    },
    "sha256": "9a7a1f75423c72e39db22f4287f8697b2a41ce2dcf7c4cac5797331555aca6f4"
  },
  {
    "name": "base-permuted",
    "arguments": {
      "references_pieces": [],
      "classement_attendu": null,
      "motif": "FICTIF : cause choisie par admin",
      "cause": "waste",
      "selection": {
        "materiau_id": "MAT-CONTEXTE-FICTIF",
        "position_ligne": 0,
        "reference_variance": {
          "empreinte_charge": "351822adaa27a28f711ab7bd3a1cfab02a66a9754e0e1268e0096e82c329bb84",
          "evenement_id": "m6-variance-491297daf122f43a179c6d028921cd228e748d7b2979b5aa6d902a714f862564-evaluee",
          "type": "m6.variance_chantier"
        },
        "wct_id": "491297daf122f43a179c6d028921cd228e748d7b2979b5aa6d902a714f862564"
      }
    },
    "sha256": "9a7a1f75423c72e39db22f4287f8697b2a41ce2dcf7c4cac5797331555aca6f4"
  },
  {
    "name": "unicode-original",
    "arguments": {
      "selection": {
        "wct_id": "491297daf122f43a179c6d028921cd228e748d7b2979b5aa6d902a714f862564",
        "reference_variance": {
          "type": "m6.variance_chantier",
          "evenement_id": "m6-variance-491297daf122f43a179c6d028921cd228e748d7b2979b5aa6d902a714f862564-evaluee",
          "empreinte_charge": "351822adaa27a28f711ab7bd3a1cfab02a66a9754e0e1268e0096e82c329bb84"
        },
        "position_ligne": 0,
        "materiau_id": "MAT-CONTEXTE-FICTIF"
      },
      "cause": "waste",
      "motif": "FICTIF Québec 🧰 𝄞 α\tretour\r\nligne fin",
      "classement_attendu": null,
      "references_pieces": []
    },
    "sha256": "de83bea450c75afa62e1d685feb31770fc23a1effb1ee6e3090238055a31c583"
  },
  {
    "name": "unicode-permuted",
    "arguments": {
      "references_pieces": [],
      "classement_attendu": null,
      "motif": "FICTIF Québec 🧰 𝄞 α\tretour\r\nligne fin",
      "cause": "waste",
      "selection": {
        "materiau_id": "MAT-CONTEXTE-FICTIF",
        "position_ligne": 0,
        "reference_variance": {
          "empreinte_charge": "351822adaa27a28f711ab7bd3a1cfab02a66a9754e0e1268e0096e82c329bb84",
          "evenement_id": "m6-variance-491297daf122f43a179c6d028921cd228e748d7b2979b5aa6d902a714f862564-evaluee",
          "type": "m6.variance_chantier"
        },
        "wct_id": "491297daf122f43a179c6d028921cd228e748d7b2979b5aa6d902a714f862564"
      }
    },
    "sha256": "de83bea450c75afa62e1d685feb31770fc23a1effb1ee6e3090238055a31c583"
  },
  {
    "name": "non_bmp_500-original",
    "arguments": {
      "selection": {
        "wct_id": "491297daf122f43a179c6d028921cd228e748d7b2979b5aa6d902a714f862564",
        "reference_variance": {
          "type": "m6.variance_chantier",
          "evenement_id": "m6-variance-491297daf122f43a179c6d028921cd228e748d7b2979b5aa6d902a714f862564-evaluee",
          "empreinte_charge": "351822adaa27a28f711ab7bd3a1cfab02a66a9754e0e1268e0096e82c329bb84"
        },
        "position_ligne": 0,
        "materiau_id": "MAT-CONTEXTE-FICTIF"
      },
      "cause": "waste",
      "motif": "🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰",
      "classement_attendu": null,
      "references_pieces": []
    },
    "sha256": "17e6732cdffc048bf0256fb6457fbb00b7979517c3b41d33ebf8a5232bd30fe4"
  },
  {
    "name": "non_bmp_500-permuted",
    "arguments": {
      "references_pieces": [],
      "classement_attendu": null,
      "motif": "🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰🧰",
      "cause": "waste",
      "selection": {
        "materiau_id": "MAT-CONTEXTE-FICTIF",
        "position_ligne": 0,
        "reference_variance": {
          "empreinte_charge": "351822adaa27a28f711ab7bd3a1cfab02a66a9754e0e1268e0096e82c329bb84",
          "evenement_id": "m6-variance-491297daf122f43a179c6d028921cd228e748d7b2979b5aa6d902a714f862564-evaluee",
          "type": "m6.variance_chantier"
        },
        "wct_id": "491297daf122f43a179c6d028921cd228e748d7b2979b5aa6d902a714f862564"
      }
    },
    "sha256": "17e6732cdffc048bf0256fb6457fbb00b7979517c3b41d33ebf8a5232bd30fe4"
  }
] as const;

test.each(vecteursPython)("empreinte Python réelle $name, clés triées et Unicode verbatim", v => {
  const calculer = (api() as any).empreinteArgumentsClassementVariance;
  expect(calculer?.(v.arguments)).toBe(v.sha256);
});
// Cadres RAM de contrat r2; référence de forme, aucun maillon v2 réel n'est prétendu ici.
function cadreV2Spec() {
  const v = vecteursPython[0], a = v.arguments;
  const m = { ...api().creerMutationClassementVariance(a, () => "9a276b43-3d42-4a55-a22f-03fe7a784a10", horloge,
    { appareilId: "APP-CLASSEMENT-FICTIF", urlBase: "https://fictif.invalid" }), proprietaire: "admin.contexte.fictif" };
  const ancien = clone(capture("classement_v1").enveloppe) as any;
  const intention = { appareil_id: "APP-CLASSEMENT-FICTIF", intention_uuid: m.id, empreinte_arguments: v.sha256 };
  const resultat = { ...ancien.resultat.resultat, selection: a.selection, cause: a.cause, motif: a.motif,
    reference_precedente: a.classement_attendu, references_pieces: a.references_pieces, version_schema: 2, intention };
  return { m, positif: { ok: true, resultat: { accepte: true, version_schema: 2, resultat, registre: ancien.resultat.registre } },
    negatif: { ok: true, resultat: { accepte: false, version_schema: 2,
      verdict: { code: "REJ-M6-CLASSEMENT-REVISION-PERIMEE", detail: "le classement ne satisfait pas son contrat ; aucun détail partiel n’est transmis" },
      intention, preuve_refus: { registre: "refus_classement_variance", index: 0, hash_maillon: "e".repeat(64) },
      auteur: { personne: m.proprietaire, role: "admin", source: "appareil" }, horodatage_appareil_declare: m.createdAtLocal } } };
}
test("ACK succès r2 et reçu local versionné restent liés sans fabriquer une association legacy", () => {
  const { m, positif } = cadreV2Spec(), lu = api().interpreterClassementVariance(positif, m);
  expect(lu.accepte).toBe(true);
  if (lu.accepte) {
    expect((lu.resume as any).version_schema).toBe(2);
    expect(api().validerRecuClassementVariance({ ...m, statut: "envoyee", resumeAccepte: lu.resume })).toBe(true);
  }
  const legacy = api().interpreterClassementVariance(capture("classement_v1").enveloppe, mutation());
  expect(legacy.accepte).toBe(true);
  if (legacy.accepte) expect(Object.hasOwn(legacy.resume, "intention")).toBe(false);
});
test.each(["LIGNE-HORS-PERIMETRE", "ARGUMENTS-INVALIDES", "PIECES-INVALIDES", "LIAISON-INCOHERENTE", "REVISION-PERIMEE", "SORTIE-TROP-VOLUMINEUSE"])(
  "seul un reçu r2 propre de refus certain %s peut devenir terminal", suffix => {
    const { m, negatif } = cadreV2Spec(); negatif.resultat.verdict.code = `REJ-M6-CLASSEMENT-${suffix}`;
    expect(api().interpreterClassementVariance(negatif, m)).toMatchObject({ accepte: false, verdict: { code: `REJ-M6-CLASSEMENT-${suffix}` } });
  });
test.each(["uuid", "appareil", "empreinte", "personne", "heure", "reference", "index", "hash", "version", "detail", "code", "champ"])(
  "preuve r2 de refus %s incohérente garde la même intention", key => {
    const { m, negatif } = cadreV2Spec(), r = negatif.resultat as any;
    if (key === "uuid") r.intention.intention_uuid = "AUTRE-UUID-FICTIF";
    else if (key === "appareil") r.intention.appareil_id = "AUTRE-APP-FICTIF";
    else if (key === "empreinte") r.intention.empreinte_arguments = "a".repeat(64);
    else if (key === "personne") r.auteur.personne = "autre.admin.fictif";
    else if (key === "heure") r.horodatage_appareil_declare = "2026-10-08T17:00:00.000001Z";
    else if (key === "reference") r.preuve_refus.registre = "classements_variance";
    else if (key === "index") r.preuve_refus.index = true;
    else if (key === "hash") r.preuve_refus.hash_maillon = "E".repeat(64);
    else if (key === "version") r.version_schema = 1;
    else if (key === "detail") r.verdict.detail = "Détail libre FICTIF";
    else if (key === "code") r.verdict.code = "REJ-M6-CLASSEMENT-SOURCE-PERIMEE";
    else r.prix = "10.00";
    expect(api().interpreterClassementVariance(negatif, m)).toMatchObject({ accepte: false, verdict: { code: "accuse_invalide" } });
  });
test("l’instant se compare à la microseconde exacte, même avec un autre offset", () => {
  const { m, positif } = cadreV2Spec(); m.createdAtLocal = "2026-10-08T13:00:00.123456-04:00";
  positif.resultat.resultat.horodatage_appareil_declare = "2026-10-08T17:00:00.123456Z";
  expect(api().interpreterClassementVariance(positif, m).accepte).toBe(true);
  positif.resultat.resultat.horodatage_appareil_declare = "2026-10-08T17:00:00.123457Z";
  expect(api().interpreterClassementVariance(positif, m)).toMatchObject({ accepte: false, verdict: { code: "accuse_invalide" } });
});
test("reçu local avec accesseur refusé sans exécuter l’accesseur", () => {
  const getter = jest.fn(), m = Object.defineProperty(mutation(), "resumeAccepte", { enumerable: true, get: getter });
  expect(api().validerRecuClassementVariance(m)).toBe(false); expect(getter).not.toHaveBeenCalled();
});

// Deux vecteurs de correction provenant des args réels RootCap revision_v2, aucune pièce inventée.
const vecteursCorrectionPython = [
  {
    "name": "actual_correction-original",
    "arguments": {
      "selection": {
        "wct_id": "491297daf122f43a179c6d028921cd228e748d7b2979b5aa6d902a714f862564",
        "reference_variance": {
          "type": "m6.variance_chantier",
          "evenement_id": "m6-variance-491297daf122f43a179c6d028921cd228e748d7b2979b5aa6d902a714f862564-evaluee",
          "empreinte_charge": "351822adaa27a28f711ab7bd3a1cfab02a66a9754e0e1268e0096e82c329bb84"
        },
        "position_ligne": 0,
        "materiau_id": "MAT-CONTEXTE-FICTIF"
      },
      "cause": "breakage",
      "motif": "FICTIF : révision\tmatériau\nQuébec 😀",
      "classement_attendu": {
        "registre": "classements_variance",
        "index": 0,
        "hash_maillon": "1cc2d93d75a81ddc9c4299f83046268fa57783bf7039754d50786cac248c0bfc"
      },
      "references_pieces": []
    },
    "sha256": "dcc3ccd7c9eb0c1def3bd86d2edc1dd7881d08e5c8aecebfebcd7787f120ab2a"
  },
  {
    "name": "actual_correction-permuted",
    "arguments": {
      "references_pieces": [],
      "classement_attendu": {
        "hash_maillon": "1cc2d93d75a81ddc9c4299f83046268fa57783bf7039754d50786cac248c0bfc",
        "index": 0,
        "registre": "classements_variance"
      },
      "motif": "FICTIF : révision\tmatériau\nQuébec 😀",
      "cause": "breakage",
      "selection": {
        "materiau_id": "MAT-CONTEXTE-FICTIF",
        "position_ligne": 0,
        "reference_variance": {
          "empreinte_charge": "351822adaa27a28f711ab7bd3a1cfab02a66a9754e0e1268e0096e82c329bb84",
          "evenement_id": "m6-variance-491297daf122f43a179c6d028921cd228e748d7b2979b5aa6d902a714f862564-evaluee",
          "type": "m6.variance_chantier"
        },
        "wct_id": "491297daf122f43a179c6d028921cd228e748d7b2979b5aa6d902a714f862564"
      }
    },
    "sha256": "dcc3ccd7c9eb0c1def3bd86d2edc1dd7881d08e5c8aecebfebcd7787f120ab2a"
  }
] as const;
test.each(vecteursCorrectionPython)("correction réelle $name, référence précédente canonique", v => {
  expect(api().empreinteArgumentsClassementVariance(v.arguments)).toBe(v.sha256);
});
