import fs from "node:fs";
import path from "node:path";

import { OUTIL_OBTENIR_CLIENT_360, OUTIL_SUGGERER_PROCHAINE_ACTION, OUTIL_TROUVER_CLIENT_DE_LEAD } from "../m2/client360";
import { OUTIL_ENREGISTRER_INTERACTION } from "../m2/interaction";
import { OUTIL_LISTER_LEADS } from "../m2/listeLeads";
import { OUTIL_EVALUER_READINESS } from "../m2/readiness";
import { OUTIL_LIRE_DEVIS, OUTIL_LISTER_DEVIS } from "../m3/devis";
import { DESCRIPTEURS_MUTATION } from "../outbox/descripteurs";

/**
 * Les écrans ne sont pas testés en rendu (pas de `@testing-library/react-native` dans la pile installée, voir
 * MOBILE.md) : ces gardes lisent leur SOURCE et les noms d'outils que l'app envoie. Elles gardent trois promesses du
 * profil vendeur (PLAN T4.8) : tout passe par la porte d'appareil, sous le nom nu d'un outil de la portée `seller` ;
 * aucun coût ni marge n'atteint un écran ; aucun écran n'appelle le réseau lui-même.
 */
const RACINE = path.resolve(__dirname, "../..");
const SRC = path.join(RACINE, "src");
const APP_VENDEUR = path.join(RACINE, "app", "(seller)");

function lire(chemin: string): string {
  return fs.readFileSync(chemin, "utf8");
}

function fichiers(dossier: string, filtre: (nom: string) => boolean): string[] {
  return fs
    .readdirSync(dossier, { withFileTypes: true })
    .flatMap((entree) => {
      const complet = path.join(dossier, entree.name);
      return entree.isDirectory() ? fichiers(complet, filtre) : filtre(entree.name) ? [complet] : [];
    })
    .sort();
}

/** Les onze outils de la portée `seller` (`docs/architecture/ROLES.md`), épinglés par
 * `tests/test_portees_appareil.py` côté socle. */
const OUTILS_DU_VENDEUR: readonly string[] = [
  "m2_lister_leads",
  "m2_obtenir_client_360",
  "m2_trouver_client_de_lead",
  "m2_suggerer_prochaine_action",
  "m2_evaluer_readiness",
  "m2_transitionner_statut",
  "m2_enregistrer_interaction",
  "m3_lire_devis",
  "m3_lister_devis",
  "m3_generer_soumission_brouillon",
  "m3_qualifier_photos",
];

const OUTILS_DE_L_APP: readonly string[] = [
  OUTIL_LISTER_LEADS,
  OUTIL_OBTENIR_CLIENT_360,
  OUTIL_TROUVER_CLIENT_DE_LEAD,
  OUTIL_SUGGERER_PROCHAINE_ACTION,
  OUTIL_ENREGISTRER_INTERACTION,
  OUTIL_LIRE_DEVIS,
  OUTIL_LISTER_DEVIS,
  OUTIL_EVALUER_READINESS,
];

describe("tout passe par la porte d'appareil : nom nu, portée seller", () => {
  test.each(OUTILS_DE_L_APP)("%s : un nom nu (jamais préfixé par un serveur), dans la portée du vendeur", (outil) => {
    expect(outil).toMatch(/^m\d+_[a-z0-9_]+$/);
    expect(outil).not.toMatch(/[.:/]/);
    expect(OUTILS_DU_VENDEUR).toContain(outil);
  });

  test("la readiness reste une lecture MCP du rôle vendeur, sans mutation", () => {
    expect(OUTILS_DE_L_APP).toContain("m2_evaluer_readiness");
    expect([...DESCRIPTEURS_MUTATION.values()].some((descripteur) => descripteur.tool === OUTIL_EVALUER_READINESS)).toBe(false);
    const fiche = lire(path.join(APP_VENDEUR, "lead", "[id].tsx"));
    expect(fiche).toContain("chargerReadiness(leadId, personneLue)");
    expect(fiche).toContain("ficheLiveLisible");
    expect(fiche).toContain("ficheEnCache");
    expect(fiche).not.toContain("m2_transitionner_statut");
    expect(fiche).not.toMatch(/prix|estimation\.lancer/i);
  });

  test("la fiche affiche uniquement les champs d'attribution du Client 360 serveur", () => {
    const fiche = lire(path.join(APP_VENDEUR, "lead", "[id].tsx"));
    expect(fiche).toContain("opportunite.campagne");
    expect(fiche).toContain("opportunite.utm");
    expect(fiche).toContain("opportunite.source");
  });

  test("les huit outils sont huit outils distincts", () => {
    expect(new Set(OUTILS_DE_L_APP).size).toBe(8);
  });

  test("la note du vendeur part par la file sortante, sous le nom nu de l'outil, et aucun outil de l'admin n'est appelé", () => {
    expect(DESCRIPTEURS_MUTATION.get("lead_note")?.tool).toBe("m2_enregistrer_interaction");
    for (const outilAdmin of ["m2_produire_digest", "m2_signaler_doublon", "m2_arbitrer_doublon", "m9_decider_demande_approbation", "m5_etat_tresorerie"]) {
      expect(OUTILS_DE_L_APP).not.toContain(outilAdmin);
    }
  });

  test("aucun écran ni module du vendeur n'appelle le réseau lui-même : tout passe par le client `/tools/invoke`", () => {
    const sources = [
      ...fichiers(APP_VENDEUR, (nom) => nom.endsWith(".tsx")),
      ...fichiers(path.join(SRC, "vendeur"), (nom) => nom.endsWith(".ts") && !nom.endsWith(".test.ts") && nom !== "service.ts"),
      ...["m2/listeLeads.ts", "m2/client360.ts", "m2/interaction.ts", "m2/readiness.ts", "m3/devis.ts", "ecrans/leads.ts", "ecrans/lead.ts", "ecrans/quotes.ts"].map(
        (relatif) => path.join(SRC, relatif),
      ),
    ];
    expect(sources.length).toBeGreaterThan(10);
    for (const fichier of sources) {
      const texte = lire(fichier);
      expect({ fichier: path.relative(RACINE, fichier), fetch: /\bfetch\(/.test(texte) }).toEqual({
        fichier: path.relative(RACINE, fichier),
        fetch: false,
      });
      expect(texte).not.toMatch(/["']\/tools\/invoke/); // jamais l'URL de la porte en dur : `invoquerOutil` la connaît
    }
  });

  test("le devis vendeur passe par le registre paginé M3 et le parcours manuel reste disponible", () => {
    const ecran = lire(path.join(APP_VENDEUR, "quotes.tsx"));
    const service = lire(path.join(SRC, "vendeur", "service.ts"));
    expect(ecran).toContain("chargerSuiteDevis");
    expect(ecran).toContain("ouvrirDevisParNumero");
    expect(service).toContain("chargerInventaire");
    expect(service).toContain("obtenirSessionEnvoi()");
    expect(OUTILS_DE_L_APP).toContain(OUTIL_LISTER_DEVIS);
  });

  test("l'écran Soumissions lie ses cartes et les lectures différées à l'identité courante", () => {
    const ecran = lire(path.join(APP_VENDEUR, "quotes.tsx"));
    expect(ecran).toContain("useEtatIdentite()");
    expect(ecran).toContain("key={cleIdentite}");
    expect(ecran).toContain("inventaireVisiblePourPersonne(resultat, personne)");
    expect(ecran).toContain("peutAppliquerReponseInventaire(");
    expect(ecran).toContain("sequence.current += 1");
  });

  test("le câblage réel lit le jeton COURANT et la personne confirmée pour ce jeton, jamais une session gardée", () => {
    const service = lire(path.join(SRC, "vendeur", "service.ts"));
    expect(service).toContain("obtenirSessionEnvoi()");
    expect(service).toContain("invoquerOutil");
    expect(service).not.toMatch(/let \w+Cache/); // rien de gardé d'un appel à l'autre : la session est relue à chaque fois
  });
});

describe("aucun coût ni marge n'atteint un écran du vendeur", () => {
  /** Les noms de champs de coût et de marge de M3 (`devis_durable.py`), en identifiants. Seul `src/m3/devis.ts` les
   * nomme, pour dire qu'il les écarte. */
  const IDENTIFIANTS_INTERDITS = /cout_|taux_marge|\bcout[A-Z]|tauxMarge|\bmarge[A-Z_]|prix_recommande|prixRecommande/;

  const ecrans = fichiers(APP_VENDEUR, (nom) => nom.endsWith(".tsx"));
  const logique = [
    ...fichiers(path.join(SRC, "vendeur"), (nom) => nom.endsWith(".ts") && !nom.endsWith(".test.ts") && nom !== "donneesDeTest.ts"),
    path.join(SRC, "ecrans", "leads.ts"),
    path.join(SRC, "ecrans", "lead.ts"),
    path.join(SRC, "ecrans", "quotes.ts"),
  ];

  test("les trois écrans et l'accueil existent (le test ne passe pas à vide)", () => {
    const noms = ecrans.map((f) => path.relative(APP_VENDEUR, f).split(path.sep).join("/"));
    expect(noms).toEqual(expect.arrayContaining(["leads.tsx", "lead/[id].tsx", "quotes.tsx", "seller.tsx"]));
  });

  test.each([...ecrans, ...logique])("%s ne nomme aucun champ de coût ni de marge", (fichier) => {
    expect(lire(fichier)).not.toMatch(IDENTIFIANTS_INTERDITS);
  });

  test("les textes affichés au vendeur ne promettent aucun coût ni aucune marge", () => {
    const fr = lire(path.join(SRC, "i18n", "locales", "fr-CA.ts"));
    const bloc = fr.slice(fr.indexOf("  vendeur: {\n    accueil"));
    expect(bloc).not.toMatch(/Coût :|Marge :|Prix coûtant|coût total|marge estimée/i);
  });
});

describe("chaque écran garde ses raisons de lecture seule et de cache", () => {
  test("le groupe (seller) garde ses routes par la garde de rôle", () => {
    expect(lire(path.join(APP_VENDEUR, "_layout.tsx"))).toContain('evaluerGarde(session, "seller")');
  });

  test("les trois écrans lisent par les services du vendeur (cache marqué, session confirmée)", () => {
    expect(lire(path.join(APP_VENDEUR, "leads.tsx"))).toContain('from "@/vendeur/service"');
    expect(lire(path.join(APP_VENDEUR, "quotes.tsx"))).toContain('from "@/vendeur/service"');
    expect(lire(path.join(APP_VENDEUR, "lead", "[id].tsx"))).toContain('from "@/vendeur/service"');
  });

  test("la note ne part pas sans personne confirmée par le serveur (fail-closed), avec le texte d'identité absente", () => {
    const source = lire(path.join(APP_VENDEUR, "lead", "[id].tsx"));
    expect(source).toContain("usePersonneAppairee()");
    expect(source).toMatch(/if \(!personne\)/);
    expect(source).toContain('t("identite.absente")');
    expect(source).toContain("creerMutationNote(");
  });
});
