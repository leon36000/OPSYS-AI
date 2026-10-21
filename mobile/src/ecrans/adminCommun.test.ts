import {
  abreger,
  formaterDateOuInstant,
  libelleDeCatalogue,
  message,
  montantNullable,
  montantOuTexte,
  presenterSection,
  quantiteOuTexte,
} from "./adminCommun";
import { duCache, duServeur } from "./donneesDeVue";

const NBSP = " ";

describe("message", () => {
  test("une clé seule n'a pas de variables ; avec des variables, elles voyagent telles quelles", () => {
    expect(message("admin.commun.chargement")).toEqual({ cle: "admin.commun.chargement" });
    expect(message("admin.commun.cache", { date: "2026-09-29 14:03", code: "erreur_reseau" })).toEqual({
      cle: "admin.commun.cache",
      params: { date: "2026-09-29 14:03", code: "erreur_reseau" },
    });
  });
});

describe("libelleDeCatalogue : une valeur du serveur que l'app ne connaît pas est dite inconnue, jamais devinée", () => {
  test("connue : la clé `prefixe.valeur`, avec les variables données", () => {
    expect(libelleDeCatalogue("admin.chantiers.statuts", "planifiee", ["planifiee", "reportee"])).toEqual({
      cle: "admin.chantiers.statuts.planifiee",
    });
    expect(libelleDeCatalogue("admin.chantiers.typesDeRevue", "ecart_metier", ["ecart_metier"], { nombre: 3 })).toEqual({
      cle: "admin.chantiers.typesDeRevue.ecart_metier",
      params: { nombre: 3 },
    });
  });

  test("inconnue : la valeur telle quelle, dite inconnue de cette version de l'app", () => {
    expect(libelleDeCatalogue("admin.chantiers.statuts", "annulee_par_le_client", ["planifiee"])).toEqual({
      cle: "admin.commun.inconnu",
      params: { valeur: "annulee_par_le_client" },
    });
  });

  test("une valeur qui ressemble à un chemin ne traverse pas le catalogue (`__proto__`, `constructor`)", () => {
    for (const valeur of ["__proto__", "constructor", "toString", ""]) {
      expect(libelleDeCatalogue("admin.chantiers.statuts", valeur, ["planifiee"]).cle).toBe("admin.commun.inconnu");
    }
  });
});

describe("la mise en forme des montants : un texte décimal du serveur, jamais un nombre", () => {
  test("fr-CA : espaces insécables, virgule décimale, symbole après", () => {
    expect(montantOuTexte("1234.50", "fr-CA")).toBe(`1${NBSP}234,50${NBSP}$`);
    expect(montantOuTexte("20000.00", "fr-CA")).toBe(`20${NBSP}000,00${NBSP}$`);
    expect(montantOuTexte("-120.50", "fr-CA")).toBe(`-120,50${NBSP}$`);
  });

  test("en-CA : virgule des milliers, point décimal, symbole avant", () => {
    expect(montantOuTexte("1234.50", "en-CA")).toBe("$1,234.50");
    expect(montantOuTexte("-120.50", "en-CA")).toBe("-$120.50");
  });

  test("un texte qui n'est pas décimal n'est pas transformé en 0 : il est rendu tel quel", () => {
    expect(montantOuTexte("bientôt", "fr-CA")).toBe("bientôt");
    expect(quantiteOuTexte("1e3", "fr-CA")).toBe("1e3");
  });

  test("une précision au-delà d'un flottant n'est pas perdue (aucune conversion en nombre)", () => {
    expect(montantOuTexte("12345678901234567890.12", "fr-CA")).toBe(`12${NBSP}345${NBSP}678${NBSP}901${NBSP}234${NBSP}567${NBSP}890,12${NBSP}$`);
  });

  test("les quantités n'ont pas de symbole ; un montant absent reste absent (null), jamais « 0 »", () => {
    expect(quantiteOuTexte("4", "fr-CA")).toBe("4");
    expect(quantiteOuTexte("0.00", "fr-CA")).toBe("0,00");
    expect(montantNullable(null, "fr-CA")).toBeNull();
    expect(montantNullable("0.00", "fr-CA")).toBe(`0,00${NBSP}$`);
  });
});

describe("formaterDateOuInstant : un jour n'est pas un instant", () => {
  test("un jour (`AAAA-MM-JJ`) reste ce jour-là, même à un décalage négatif (minuit UTC serait la veille au soir)", () => {
    expect(formaterDateOuInstant("2026-09-14", -240)).toBe("2026-09-14");
    expect(formaterDateOuInstant("2026-09-14", 0)).toBe("2026-09-14");
    expect(formaterDateOuInstant("2026-01-01", -300)).toBe("2026-01-01");
  });

  test("un instant est ramené à l'heure locale de l'appareil", () => {
    expect(formaterDateOuInstant("2026-09-10T12:00:00-04:00", -240)).toBe("2026-09-10 12:00");
    expect(formaterDateOuInstant("2026-09-10T12:00:00-04:00", 0)).toBe("2026-09-10 16:00");
    expect(formaterDateOuInstant("2026-09-22T15:00:00+00:00", -240)).toBe("2026-09-22 11:00");
  });

  test("un texte illisible est rendu tel quel, jamais remplacé par une date inventée", () => {
    expect(formaterDateOuInstant("hier soir", -240)).toBe("hier soir");
  });
});

describe("abreger : l'affichage abrège, l'identifiant envoyé au serveur reste entier", () => {
  test("une empreinte de 64 caractères garde ses 8 premiers", () => {
    const empreinte = "bc40348bbff5df996888ea3e1fbb1de49a4858f3a8178120f937e0d7e2cd289d";
    expect(abreger(empreinte)).toBe("bc40348b…");
  });

  test("un identifiant court est laissé tel quel (12 caractères et moins)", () => {
    expect(abreger("DEVIS-ADM-1")).toBe("DEVIS-ADM-1");
    expect(abreger("abcdefghijkl")).toBe("abcdefghijkl");
    expect(abreger("abcdefghijklm")).toBe("abcdefgh…");
  });
});

describe("presenterSection : quatre issues, jamais confondues", () => {
  test("lue au serveur : le contenu, sa date à l'heure de l'appareil, aucun bandeau hors ligne", () => {
    const vue = presenterSection(duServeur({ n: 1 }), -240, (valeur) => ({ double: valeur.n * 2 }));
    expect(vue).toEqual({
      genre: "contenu",
      contenu: { double: 2 },
      lue: { cle: "admin.commun.lueLe", params: { date: "2026-09-29 14:03" } },
      horsLigne: null,
    });
  });

  test("lue dans le cache : le bandeau dit la date de la copie et la raison, et la lecture porte la date de la copie", () => {
    const vue = presenterSection(duCache({ n: 1 }, "http_503"), -240, (valeur) => valeur);
    expect(vue).toEqual({
      genre: "contenu",
      contenu: { n: 1 },
      lue: { cle: "admin.commun.lueLe", params: { date: "2026-09-28 09:30" } },
      horsLigne: { cle: "admin.commun.cache", params: { date: "2026-09-28 09:30", code: "http_503" } },
    });
  });

  test("refusée : le verdict du serveur, dit tel quel ; le présentateur n'est jamais appelé", () => {
    const presenter = jest.fn();
    const verdict = { code: "REJ-PREVISION-HORIZON-A-CONFIGURER", detail: "l'horizon est une décision du propriétaire" };
    const vue = presenterSection({ source: "refus", verdict }, -240, presenter);
    expect(vue).toEqual({ genre: "refus", avis: { cle: "admin.commun.refus", params: verdict }, verdict });
    expect(presenter).not.toHaveBeenCalled();
  });

  test("ni serveur ni cache : la raison, dite ; le présentateur n'est jamais appelé (rien n'est montré plutôt qu'inventé)", () => {
    const presenter = jest.fn();
    const raison = { code: "erreur_reseau", detail: "Network request failed" };
    const vue = presenterSection({ source: "aucune", raison }, -240, presenter);
    expect(vue).toEqual({ genre: "aucune", avis: { cle: "admin.commun.aucune", params: raison }, raison });
    expect(presenter).not.toHaveBeenCalled();
  });

  const DETAILS_QUI_CITENT_LE_SERVEUR = [
    ["un chemin du serveur", "profil invalide : voir /srv/opsys/entreprise.yaml"],
    ["une commande du serveur", "déclare les équipes avec opsys-metier equipes declarer --par toi"],
    ["un nom de fichier de configuration", "écris entreprise.yaml"],
  ] as const;

  test.each(DETAILS_QUI_CITENT_LE_SERVEUR)("refusée, détail avec %s : seul le code est dit, le détail est tu (et absent de la vue)", (_nom, detail) => {
    const vue = presenterSection({ source: "refus", verdict: { code: "REJ-PROFIL-INVALIDE", detail } }, -240, jest.fn());
    expect(vue).toEqual({
      genre: "refus",
      avis: { cle: "admin.commun.refusSansDetail", params: { code: "REJ-PROFIL-INVALIDE" } },
      verdict: { code: "REJ-PROFIL-INVALIDE", detail: "" },
    });
    expect(JSON.stringify(vue)).not.toContain(detail);
  });

  test.each(DETAILS_QUI_CITENT_LE_SERVEUR)("sans copie, détail avec %s : seul le code est dit, le détail est tu (et absent de la vue)", (_nom, detail) => {
    const vue = presenterSection({ source: "aucune", raison: { code: "http_500", detail } }, -240, jest.fn());
    expect(vue).toEqual({
      genre: "aucune",
      avis: { cle: "admin.commun.aucuneSansDetail", params: { code: "http_500" } },
      raison: { code: "http_500", detail: "" },
    });
    expect(JSON.stringify(vue)).not.toContain(detail);
  });

  test("un détail vide (le serveur n'en donne pas) se dit par le code seul, sans les deux-points d'une phrase vide", () => {
    expect(presenterSection({ source: "refus", verdict: { code: "REJ-X", detail: "" } }, -240, jest.fn())).toMatchObject({
      avis: { cle: "admin.commun.refusSansDetail", params: { code: "REJ-X" } },
    });
    expect(presenterSection({ source: "aucune", raison: { code: "http_500", detail: "" } }, -240, jest.fn())).toMatchObject({
      avis: { cle: "admin.commun.aucuneSansDetail", params: { code: "http_500" } },
    });
  });

  test("un détail sans chemin reste dit tel quel, avec son code", () => {
    const verdict = { code: "REJ-TRANSITION-ILLEGALE", detail: "préparation sans objet : l'intervention est completed_pending_review" };
    expect(presenterSection({ source: "refus", verdict }, -240, jest.fn())).toEqual({
      genre: "refus",
      avis: { cle: "admin.commun.refus", params: verdict },
      verdict,
    });
  });
});
