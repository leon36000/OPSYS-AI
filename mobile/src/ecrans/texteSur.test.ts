import { jetonSur, texteSansChemin } from "./texteSur";

describe("jetonSur : un code que l'app veut bien montrer", () => {
  test.each([
    "REJ-EQUIPES-NON-CONFIGUREES",
    "partiel",
    "a_commander",
    "erreur_reseau",
    "http_503",
    "v1.2",
    "x",
    "A".repeat(64),
  ])("« %s » est un jeton", (valeur) => {
    expect(jetonSur(valeur)).toBe(valeur);
  });

  test.each<[string, string | null]>([
    ["absent", null],
    ["vide", ""],
    ["deux mots", "deux mots"],
    ["un chemin du serveur", "/srv/opsys/entreprise.yaml"],
    ["un chemin relatif", "docs/architecture/TAXONOMIE.md"],
    ["un chemin Windows", "C:\\opsys\\entreprise.yaml"],
    ["un deux-points", "REJ-X:Y"],
    ["une fin de ligne", "REJ-X\n"],
    ["un espace en tête", " REJ-X"],
    ["une commande entre apostrophes inversées", "`ls`"],
    ["un caractère accentué", "détail"],
    ["65 caractères, un de trop", "A".repeat(65)],
    ["le nom d'un fichier de configuration", "entreprise.yaml"],
    ["le nom d'un fichier de base", "registre.sqlite"],
    ["le nom de la commande du serveur", "opsys-metier"],
    ["le nom de la commande, en majuscules", "OPSYS-METIER"],
  ])("%s n'est pas un jeton", (_nom, valeur) => {
    expect(jetonSur(valeur)).toBeNull();
  });
});

describe("texteSansChemin : un texte du serveur que l'app veut bien montrer", () => {
  test.each([
    "devis accepté DEVIS-ADM-B-fictif",
    "matériel prêt et réservé (M6, révision 1)",
    "préparation sans objet : l'intervention est completed_pending_review (attendu a_planifier, planifiee, reportee)",
    "segment quote_stale : non calculable, manque le seuil jours_soumission_perimee : seuil à configurer",
    "intervention inexistante",
  ])("« %s » est montré tel quel", (texte) => {
    expect(texteSansChemin(texte)).toBe(texte);
  });

  test("un texte vide reste vide : il n'y a rien à cacher ; absent reste absent", () => {
    expect(texteSansChemin("")).toBe("");
    expect(texteSansChemin(null)).toBeNull();
  });

  test.each<[string, string]>([
    ["un chemin absolu", "le profil est écrit dans /srv/opsys/entreprise.yaml"],
    ["un chemin de documentation", "voir docs/architecture/TAXONOMIE.md"],
    ["un chemin Windows", "C:\\Users\\proprio\\entreprise.txt"],
    ["le dossier de l'utilisateur", "écris dans ~/opsys"],
    ["une variable d'environnement", "lis $OPSYS_HOME avant"],
    ["une commande entre apostrophes inversées", "tape `ls -l` d'abord"],
    ["la commande du serveur", "opsys-metier equipes declarer --depuis un fichier"],
    ["la commande du serveur, en majuscules", "OPSYS-METIER equipes declarer"],
    ["un fichier YAML", "écris un fichier entreprise.yaml"],
    ["un fichier yml, en majuscules", "écris un fichier ENTREPRISE.YML"],
    ["un fichier JSON", "lis registre.json"],
    ["un fichier de base SQLite", "ouvre registre.sqlite"],
    ["un fichier Markdown", "lis LISEZMOI.md"],
    ["un fichier Python", "édite preparation.py"],
    ["un fichier TypeScript", "édite dispatch.ts"],
    ["un fichier de base .db", "supprime opsys-outbox.db"],
    ["un nom de fichier en fin de phrase", "le profil est dans entreprise.yaml."],
  ])("%s n'est pas montré", (_nom, texte) => {
    expect(texteSansChemin(texte)).toBeNull();
  });

  test("une barre oblique suffit à taire un texte, même « et/ou » : prudence assumée, le code dit le reste", () => {
    expect(texteSansChemin("un lead et/ou un client")).toBeNull();
  });

  test("une extension n'est reconnue qu'en fin de mot : « ymlx » et « pyramide » ne sont pas des fichiers", () => {
    expect(texteSansChemin("le format ymlx n'existe pas")).toBe("le format ymlx n'existe pas");
    expect(texteSansChemin("la pyramide des âges")).toBe("la pyramide des âges");
    expect(texteSansChemin("un fichier .doc")).toBe("un fichier .doc");
  });
});
