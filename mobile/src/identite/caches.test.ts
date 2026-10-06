import { creerChargeurAVoir } from "../admin/aVoir";
import { creerChargeurChantiers as creerChargeurChantiersAdmin } from "../admin/chantiers";
import { creerChargeurChiffres } from "../admin/chiffres";
import { config as configAdmin, fauxTransport as fauxTransportAdmin, reponse as reponseAdmin } from "../admin/donneesDeTest";
import { STATUTS_DU_DISPATCH } from "../m4/dispatch";
import { ecrireChecklist } from "../checklist/cache";
import { OUTIL_OBTENIR_CLIENT_360, OUTIL_SUGGERER_PROCHAINE_ACTION, OUTIL_TROUVER_CLIENT_DE_LEAD } from "../m2/client360";
import { OUTIL_LISTER_LEADS } from "../m2/listeLeads";
import { OUTIL_LIRE_DEVIS, OUTIL_LISTER_DEVIS } from "../m3/devis";
import { ecrireWctIdCompletion } from "../m4/wctIdCompletion";
import { creerChargeurChantiers } from "../today/orchestrateur";
import { invoquerOutil } from "../protocole/client";
import { CLES_HERITEES_SANS_PERSONNE, PREFIXES_DES_CACHES_PAR_PERSONNE } from "../stockage/cles";
import { DepotCleValeurMemoire } from "../stockage/depotCleValeur";
import type { DepotCleValeur } from "../stockage/depotCleValeur";
import { creerChargeurDevis } from "../vendeur/chargeurDevis";
import { creerChargeurFiche } from "../vendeur/chargeurFiche";
import { creerChargeurLeads } from "../vendeur/chargeurLeads";
import {
  CLIENT_DE_LEAD_BRUT,
  SUGGESTION_BRUTE,
  client360Brut,
  devisInterneBrut,
  enveloppeAcceptee,
  fauxTransport as fauxTransportVendeur,
  leadBrut,
  pageBrute,
} from "../vendeur/donneesDeTest";
import {
  CLE_PROPRIETAIRE_DES_CACHES,
  decisionCaches,
  ecrireProprietaireDesCaches,
  lireProprietaireDesCaches,
  purgerCachesDeLaPersonne,
  synchroniserCaches,
  synchroniserCachesSansEchouer,
} from "./caches";
import type { ProprietaireDesCaches } from "./caches";
import type { IdentiteOpsys, RoleNomme } from "./contrat";
import { MOTIFS_ERREUR_IDENTITE, estRefusDuServeur } from "./etat";
import type { EtatIdentite, MotifErreurIdentite } from "./etat";

const APPAREIL = "a".repeat(64);
function identite(personne: string, role: RoleNomme): IdentiteOpsys {
  return { appareilId: APPAREIL, personne, role };
}
function confirmee(personne: string, role: RoleNomme): EtatIdentite {
  return { genre: "confirmee", identite: identite(personne, role) };
}
const refusee = (motif: MotifErreurIdentite): EtatIdentite => ({ genre: "erreur", motif });
const ETAT_JETON_REFUSE = refusee("jeton_refuse");

const VENDEUR_A: ProprietaireDesCaches = { personne: "vendeur.a", role: "seller" };
const HORLOGE = { maintenant: new Date("2026-09-29T18:03:22.000Z"), decalageMinutesUTC: -240 };

/** Fait écrire un cache par CHAQUE chargeur réel des trois profils, avec les vraies réponses du moteur enregistrées. */
async function remplirParLesVraisChargeurs(depot: DepotCleValeurMemoire, personne: string): Promise<void> {
  // Le profil admin : « À voir », les trois sections de chiffres, un groupe par statut, le digest et une préparation.
  const transportAdmin = fauxTransportAdmin({
    m9_lister_demandes_approbation: () => reponseAdmin("a_voir"),
    m8_lire_vue_executive: () => reponseAdmin("vue_executive"),
    m5_etat_tresorerie: () => reponseAdmin("tresorerie"),
    m5_prevoir_tresorerie: () => reponseAdmin("prevision"),
    m5_lire_echeances_fiscales: () => reponseAdmin("echeances"),
    m4_lister_interventions: (args) => reponseAdmin(`interventions_${String(args.statut)}`),
    m4_produire_digest: () => reponseAdmin("digest"),
    m4_verifier_preparation: () => reponseAdmin("preparation_lead_v2"),
  });
  const admin = configAdmin(transportAdmin, { depot, personne, horloge: HORLOGE });
  await creerChargeurAVoir(admin).chargerAVoir();
  const chiffres = creerChargeurChiffres(admin);
  await chiffres.chargerVueExecutive();
  await chiffres.chargerTresorerie();
  await chiffres.chargerPrevision();
  await chiffres.chargerEcheances();
  const chantiers = creerChargeurChantiersAdmin(admin);
  await chantiers.chargerGroupes();
  await chantiers.chargerDigest();
  await chantiers.chargerPreparation("bc40348bbff5df996888ea3e1fbb1de49a4858f3a8178120f937e0d7e2cd289d");

  // Le profil vendeur : la liste (deux segments), la fiche, un devis et les numéros connus.
  const transportVendeur = fauxTransportVendeur({
    [OUTIL_LISTER_LEADS]: (args) =>
      enveloppeAcceptee(
        pageBrute({
          leads: [
            leadBrut("lead-a-01", {
              segments: [{ segment: "won_pending_schedule", regle: "r", donnee: { reference_devis_m3: "devis-a-01" } }],
            }),
          ],
          filtre: { statut: null, segment: (args.segment as string | undefined) ?? null },
        }),
      ),
    [OUTIL_SUGGERER_PROCHAINE_ACTION]: () => enveloppeAcceptee(SUGGESTION_BRUTE),
    [OUTIL_TROUVER_CLIENT_DE_LEAD]: () => enveloppeAcceptee(CLIENT_DE_LEAD_BRUT),
    [OUTIL_OBTENIR_CLIENT_360]: () => enveloppeAcceptee(client360Brut()),
    [OUTIL_LISTER_DEVIS]: () =>
      enveloppeAcceptee({ devis: [devisInterneBrut("devis-a-01")], curseur_suivant: null }),
    [OUTIL_LIRE_DEVIS]: () => enveloppeAcceptee(devisInterneBrut("devis-a-01")),
  });
  const vendeur = {
    depot,
    appelerOutil: transportVendeur,
    fetchImpl: jest.fn() as unknown as typeof fetch,
    urlBase: "https://grs.exemple.ca",
    jeton: "jeton-vendeur",
    personne,
    horloge: () => HORLOGE,
  };
  await creerChargeurLeads(vendeur).chargerLeads({ statut: null, segment: null });
  await creerChargeurFiche(vendeur).chargerFiche("lead-a-01");
  const devis = creerChargeurDevis(vendeur);
  await devis.chargerInventaire();
  await devis.ouvrirParNumero("devis-a-01");

  // Le profil employé : les chantiers.
  const fetchImpl = jest.fn(
    async () =>
      ({ ok: true, status: 200, json: async () => ({ ok: true, result: { ok: true, resultat: [] } }) }) as unknown as Response,
  );
  await creerChargeurChantiers({
    depot,
    appelerOutil: invoquerOutil,
    fetchImpl: fetchImpl as unknown as typeof fetch,
    urlBase: "https://grs.exemple.ca",
    jeton: "jeton-employe",
    personne,
    maintenant: () => HORLOGE.maintenant,
  }).chargerChantiersAujourdhui();
}

/** Ce qui n'est PAS un cache lu au serveur : les brouillons de l'employé, et une clé d'un autre module. */
async function ecrireBrouillons(depot: DepotCleValeur): Promise<void> {
  await ecrireChecklist(depot, "chantier-1", [{ id: "i1", texte: "Gouttières posées", fait: true }]);
  await ecrireWctIdCompletion(depot, "chantier-1", "wct-abc");
  await depot.ecrire("autre_module_v1", "reste");
}
const BROUILLONS = ["autre_module_v1", "checklist_chantier-1_v1", "wct_id_chantier-1_v1"];

describe("decisionCaches — ce que l'état de l'identité dit des caches", () => {
  test("identité confirmée SANS marqueur : on ne sait pas à qui sont les caches, on efface puis on marque", () => {
    expect(decisionCaches(null, confirmee("vendeur.a", "seller"))).toEqual({ genre: "purger_puis_marquer", proprietaire: VENDEUR_A });
  });

  test("la MÊME personne, le même rôle : les caches sont gardés (un nouvel appairage de la même personne)", () => {
    expect(decisionCaches(VENDEUR_A, confirmee("vendeur.a", "seller"))).toEqual({ genre: "conserver" });
  });

  test("une AUTRE personne : on efface, on marque la nouvelle", () => {
    expect(decisionCaches(VENDEUR_A, confirmee("vendeur.b", "seller"))).toEqual({
      genre: "purger_puis_marquer",
      proprietaire: { personne: "vendeur.b", role: "seller" },
    });
  });

  test("la même personne avec un AUTRE rôle : on efface (un rôle retiré ne garde pas les chiffres de l'entreprise)", () => {
    expect(decisionCaches({ personne: "nathan", role: "admin" }, confirmee("nathan", "seller"))).toEqual({
      genre: "purger_puis_marquer",
      proprietaire: { personne: "nathan", role: "seller" },
    });
  });

  test.each(MOTIFS_ERREUR_IDENTITE.filter((motif) => estRefusDuServeur(motif)))(
    "le serveur refuse l'appareil (%s) : l'appareil apprend qu'il est révoqué, on efface et on oublie le marqueur",
    (motif) => {
      expect(decisionCaches(VENDEUR_A, refusee(motif))).toEqual({ genre: "purger_puis_oublier" });
      expect(decisionCaches(null, refusee(motif))).toEqual({ genre: "purger_puis_oublier" });
    },
  );

  test.each(MOTIFS_ERREUR_IDENTITE.filter((motif) => !estRefusDuServeur(motif)))(
    "une panne que seule l'app voit (%s) ne dit rien de l'attribution : les caches restent",
    (motif) => {
      expect(decisionCaches(VENDEUR_A, refusee(motif))).toEqual({ genre: "conserver" });
    },
  );

  test("les cinq refus du serveur et les deux pannes locales sont exactement ceux du contrat d'identité", () => {
    expect(MOTIFS_ERREUR_IDENTITE.filter((motif) => estRefusDuServeur(motif)).sort()).toEqual([
      "appareil_non_attribue",
      "jeton_refuse",
      "refus_inattendu",
      "reponse_invalide",
      "role_inconnu",
    ]);
    expect(MOTIFS_ERREUR_IDENTITE.filter((motif) => !estRefusDuServeur(motif)).sort()).toEqual(["hors_ligne_sans_memoire", "stockage_illisible"]);
  });

  test.each([
    ["restauration", { genre: "restauration" }],
    ["non appairée", { genre: "non_appairee" }],
    ["lecture en cours", { genre: "en_lecture" }],
    ["à reconfirmer (le serveur n'a pas pu être joint : la dernière identité gardée sert)", { genre: "a_reconfirmer", identite: identite("vendeur.b", "seller"), confirmeLe: "2026-09-28T08:00:00.000Z" }],
  ] as const)("%s : rien ne bouge, même si l'identité gardée n'est pas celle des caches", (_nom, etat) => {
    expect(decisionCaches(VENDEUR_A, etat)).toEqual({ genre: "conserver" });
  });
});

describe("le marqueur du propriétaire des caches", () => {
  test("écrit puis relu", async () => {
    const depot = new DepotCleValeurMemoire();
    await ecrireProprietaireDesCaches(depot, VENDEUR_A);
    expect(await lireProprietaireDesCaches(depot)).toEqual(VENDEUR_A);
    expect(depot.cles()).toEqual([CLE_PROPRIETAIRE_DES_CACHES]);
  });

  test.each([
    ["absent", null],
    ["du JSON invalide", "{pas du json"],
    ["un texte", '"vendeur.a"'],
    ["sans personne", '{"role":"seller"}'],
    ["une personne vide", '{"personne":"  ","role":"seller"}'],
    ["sans rôle", '{"personne":"vendeur.a"}'],
    ["un rôle qui n'est pas nommé (le rôle de transport)", '{"personne":"vendeur.a","role":"operator"}'],
    ["un rôle mal écrit", '{"personne":"vendeur.a","role":"ADMIN"}'],
    ["nul", "null"],
  ])("%s : « pas de marqueur », jamais une identité devinée", async (_nom, brut) => {
    const depot = new DepotCleValeurMemoire();
    if (brut !== null) {
      await depot.ecrire(CLE_PROPRIETAIRE_DES_CACHES, brut);
    }
    expect(await lireProprietaireDesCaches(depot)).toBeNull();
  });

  test("il n'est ni un préfixe de cache ni une clé héritée : la purge ne l'efface pas", () => {
    expect(PREFIXES_DES_CACHES_PAR_PERSONNE.some((prefixe) => CLE_PROPRIETAIRE_DES_CACHES.startsWith(prefixe))).toBe(false);
    expect(CLES_HERITEES_SANS_PERSONNE).not.toContain(CLE_PROPRIETAIRE_DES_CACHES);
  });
});

describe("purgerCachesDeLaPersonne : rien de ce que les vrais chargeurs ont écrit n'y survit", () => {
  test.each([
    ["admin", "nathan"],
    ["vendeur", "vendeur.a"],
    ["employé", "etienne"],
  ])("les caches de la personne (%s) sont effacés, les brouillons et le reste restent", async (_profil, personne) => {
    const depot = new DepotCleValeurMemoire();
    await remplirParLesVraisChargeurs(depot, personne);
    await ecrireBrouillons(depot);
    expect(depot.cles().length).toBeGreaterThan(BROUILLONS.length + 12); // les trois profils ont bien écrit leurs caches

    await purgerCachesDeLaPersonne(depot);

    expect(depot.cles()).toEqual(BROUILLONS);
  });

  test("les caches de PLUSIEURS personnes des trois profils sont tous effacés (aucune n'est épargnée parce qu'elle n'est pas « la » personne)", async () => {
    const depot = new DepotCleValeurMemoire();
    for (const personne of ["nathan", "vendeur.a", "etienne", "a:b c"]) {
      await remplirParLesVraisChargeurs(depot, personne);
    }
    const prefixes = new Set(depot.cles().map((cle) => cle.split(":")[0]));
    expect([...prefixes].sort()).toEqual(["admin", "employe", "vendeur"]);

    await purgerCachesDeLaPersonne(depot);

    expect(depot.cles()).toEqual([]);
  });

  test("la clé d'avant T1.4-n, sans personne, est effacée elle aussi", async () => {
    const depot = new DepotCleValeurMemoire();
    await depot.ecrire("today_chantiers_v1", JSON.stringify({ interventions: [], misAJourLe: "2026-09-28T12:00:00.000Z" }));
    await ecrireBrouillons(depot);
    await purgerCachesDeLaPersonne(depot);
    expect(depot.cles()).toEqual(BROUILLONS);
  });

  test("le marqueur n'est pas effacé par la purge (c'est `synchroniserCaches` qui le remplace ou l'oublie)", async () => {
    const depot = new DepotCleValeurMemoire();
    await ecrireProprietaireDesCaches(depot, VENDEUR_A);
    await purgerCachesDeLaPersonne(depot);
    expect(await lireProprietaireDesCaches(depot)).toEqual(VENDEUR_A);
  });
});

describe("synchroniserCaches — les scénarios de l'appareil", () => {
  async function appareilDe(personne: string, role: RoleNomme): Promise<DepotCleValeurMemoire> {
    const depot = new DepotCleValeurMemoire();
    await remplirParLesVraisChargeurs(depot, personne);
    await ecrireBrouillons(depot);
    await ecrireProprietaireDesCaches(depot, { personne, role });
    return depot;
  }
  const cachesDe = (depot: DepotCleValeurMemoire, personne: string) =>
    depot.cles().filter((cle) => PREFIXES_DES_CACHES_PAR_PERSONNE.some((prefixe) => cle.startsWith(`${prefixe}${encodeURIComponent(personne)}:`)));

  test("le jeton est révoqué (401) : les caches de l'ancienne identité sont effacés, le marqueur oublié, les brouillons gardés", async () => {
    const depot = await appareilDe("vendeur.a", "seller");
    expect(cachesDe(depot, "vendeur.a").length).toBeGreaterThan(3);

    const decision = await synchroniserCaches(depot, ETAT_JETON_REFUSE);

    expect(decision).toEqual({ genre: "purger_puis_oublier" });
    expect(depot.cles()).toEqual(BROUILLONS);
  });

  test("l'appareil est appairé à une AUTRE personne : les caches de la première sont effacés, la seconde est marquée", async () => {
    const depot = await appareilDe("nathan", "admin");

    await synchroniserCaches(depot, confirmee("etienne", "employee"));

    expect(cachesDe(depot, "nathan")).toEqual([]);
    expect(await lireProprietaireDesCaches(depot)).toEqual({ personne: "etienne", role: "employee" });
    expect(depot.cles().filter((cle) => !BROUILLONS.includes(cle))).toEqual([CLE_PROPRIETAIRE_DES_CACHES]);
  });

  test("la même personne est appairée de nouveau : ses caches restent lisibles hors ligne", async () => {
    const depot = await appareilDe("nathan", "admin");
    const avant = depot.cles();

    expect(await synchroniserCaches(depot, confirmee("nathan", "admin"))).toEqual({ genre: "conserver" });

    expect(depot.cles()).toEqual(avant);
  });

  test("le rôle change (l'admin devient vendeur) : ses caches d'admin sont effacés", async () => {
    const depot = await appareilDe("nathan", "admin");
    await synchroniserCaches(depot, confirmee("nathan", "seller"));
    expect(cachesDe(depot, "nathan")).toEqual([]);
    expect(await lireProprietaireDesCaches(depot)).toEqual({ personne: "nathan", role: "seller" });
  });

  test("le serveur ne répond pas (à reconfirmer, hors ligne sans mémoire, coffre illisible) : rien n'est effacé", async () => {
    const depot = await appareilDe("vendeur.a", "seller");
    const avant = depot.cles();
    for (const etat of [
      refusee("hors_ligne_sans_memoire"),
      refusee("stockage_illisible"),
      { genre: "a_reconfirmer", identite: identite("vendeur.a", "seller"), confirmeLe: "2026-09-28T08:00:00.000Z" } as EtatIdentite,
      { genre: "en_lecture" } as EtatIdentite,
    ]) {
      await synchroniserCaches(depot, etat);
    }
    expect(depot.cles()).toEqual(avant);
  });

  test("après une révocation, la MÊME personne revient : ses caches ont disparu, elle repart d'un appareil propre et marqué", async () => {
    const depot = await appareilDe("vendeur.a", "seller");
    await synchroniserCaches(depot, ETAT_JETON_REFUSE);
    await synchroniserCaches(depot, confirmee("vendeur.a", "seller"));
    expect(cachesDe(depot, "vendeur.a")).toEqual([]);
    expect(await lireProprietaireDesCaches(depot)).toEqual(VENDEUR_A);
  });

  test("des caches d'avant ce changement (aucun marqueur, une clé sans personne) : effacés à la première confirmation", async () => {
    const depot = new DepotCleValeurMemoire();
    await depot.ecrire("today_chantiers_v1", "{}");
    await depot.ecrire("vendeur:vendeur.a:leads:*|*_v1", "{}");
    await ecrireBrouillons(depot);

    await synchroniserCaches(depot, confirmee("vendeur.a", "seller"));

    expect(depot.cles()).toEqual([...BROUILLONS, CLE_PROPRIETAIRE_DES_CACHES].sort());
  });

  test("un marqueur illisible est traité comme « aucun marqueur » : jamais une identité devinée, donc on efface", async () => {
    const depot = await appareilDe("vendeur.a", "seller");
    await depot.ecrire(CLE_PROPRIETAIRE_DES_CACHES, "{abîmé");
    await synchroniserCaches(depot, confirmee("vendeur.a", "seller"));
    expect(cachesDe(depot, "vendeur.a")).toEqual([]);
    expect(await lireProprietaireDesCaches(depot)).toEqual(VENDEUR_A);
  });

  test("la file sortante n'est pas dans ce dépôt : rien de ce module ne peut l'effacer (elle suit sa propre règle)", async () => {
    const depot = await appareilDe("vendeur.a", "seller");
    await synchroniserCaches(depot, ETAT_JETON_REFUSE);
    // Seuls les brouillons de l'employé et une clé étrangère restent dans le dépôt clé/valeur : ni mutation, ni photo.
    expect(depot.cles().every((cle) => !cle.includes("outbox") && !cle.includes("mutation"))).toBe(true);
  });
});

describe("une purge qui échoue est retentée (le marqueur n'est écrit qu'après elle)", () => {
  function depotQuiRefuseDEffacer(interne: DepotCleValeurMemoire, pannes: { restantes: number }): DepotCleValeur {
    return {
      lire: (cle) => interne.lire(cle),
      ecrire: (cle, valeur) => interne.ecrire(cle, valeur),
      supprimer: (cle) => interne.supprimer(cle),
      supprimerParPrefixe: async (prefixe) => {
        if (pannes.restantes > 0) {
          pannes.restantes -= 1;
          throw new Error("SQLite occupé");
        }
        await interne.supprimerParPrefixe(prefixe);
      },
    };
  }

  test("la première tentative échoue : le marqueur reste celui d'avant ; la suivante efface et marque", async () => {
    const interne = new DepotCleValeurMemoire();
    await remplirParLesVraisChargeurs(interne, "nathan");
    await ecrireProprietaireDesCaches(interne, { personne: "nathan", role: "admin" });
    const depot = depotQuiRefuseDEffacer(interne, { restantes: 1 });

    await expect(synchroniserCaches(depot, confirmee("etienne", "employee"))).rejects.toThrow("SQLite occupé");
    expect(await lireProprietaireDesCaches(interne)).toEqual({ personne: "nathan", role: "admin" });

    await synchroniserCaches(depot, confirmee("etienne", "employee"));
    expect(interne.cles()).toEqual([CLE_PROPRIETAIRE_DES_CACHES]);
    expect(await lireProprietaireDesCaches(interne)).toEqual({ personne: "etienne", role: "employee" });
  });

  test("synchroniserCachesSansEchouer ne lève jamais : un dépôt qui ne s'ouvre pas ou qui échoue est journalisé, sans personne ni jeton", async () => {
    const erreurs = jest.spyOn(console, "error").mockImplementation(() => undefined);
    const ouvertureImpossible = jest.fn(async () => {
      throw new Error("base illisible");
    });
    await expect(synchroniserCachesSansEchouer(ouvertureImpossible, confirmee("etienne", "employee"))).resolves.toBeNull();

    const interne = new DepotCleValeurMemoire();
    const depot = depotQuiRefuseDEffacer(interne, { restantes: 5 });
    await expect(synchroniserCachesSansEchouer(async () => depot, confirmee("etienne", "employee"))).resolves.toBeNull();

    expect(erreurs).toHaveBeenCalledTimes(2);
    const journal = JSON.stringify(erreurs.mock.calls.map((appel) => appel[0]));
    expect(journal).not.toContain("etienne");
    erreurs.mockRestore();
  });

  test("synchroniserCachesSansEchouer rend la décision quand tout va bien", async () => {
    const depot = new DepotCleValeurMemoire();
    expect(await synchroniserCachesSansEchouer(async () => depot, confirmee("etienne", "employee"))).toEqual({
      genre: "purger_puis_marquer",
      proprietaire: { personne: "etienne", role: "employee" },
    });
  });
});
