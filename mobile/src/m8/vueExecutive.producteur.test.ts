import { reponse } from "../admin/donneesDeTest";
import { presenterVueExecutive } from "../ecrans/vueExecutive";
import producteur from "./fixtures/reponseProducteurM8SeuilsFictifs.json";
import { lireVueExecutive } from "./vueExecutive";

test("la réponse QA du vrai producteur M8 traverse le lecteur et la présentation mobile sans recalcul", () => {
  expect(producteur.provenance).toMatch(/vrais outils M8.*QA fictives seulement/);
  const evaluesProducteur = producteur.m8_lire_vue_executive.resultat.entonnoir.seuils.evalues;
  expect(producteur.m8_lire_vue_executive.ok).toBe(true);

  // Le producteur a fourni le bloc réel; la vue vide est uniquement l'enveloppe de test mobile sans autres chiffres.
  const brut = reponse("vue_executive_vide").resultat;
  brut.entonnoir.seuils.evalues = evaluesProducteur;
  const vue = lireVueExecutive(brut);
  expect(vue).not.toBeNull();
  if (vue === null) throw new Error("réponse M8 producteur illisible par le mobile");

  expect(vue.entonnoir.seuils.evalues).toEqual([
    {
      metricId: "m8_taux_acceptation_pct",
      statut: "non_franchi",
      valeur: "66.67",
      unite: "pourcentage",
      sens: "au_dessus",
      seuil: "66.67",
      baseTauxAcceptation: { nAcceptesParmiEnvoyes: 2, nEnvoyes: 3 },
      comparaisonNonArrondie: null,
    },
    {
      metricId: "m8_delai_lead_acceptation_jours",
      statut: "non_franchi",
      valeur: "1.24",
      unite: "jours",
      sens: "au_dessus",
      seuil: "1.24",
      baseTauxAcceptation: null,
      comparaisonNonArrondie: true,
    },
  ]);

  const presentee = presenterVueExecutive(vue, "fr-CA", -240).entonnoir.seuils.evalues;
  expect(presentee[0]).toMatchObject({
    valeur: { cle: "admin.unites.pourcentage", params: { valeur: "66,67" } },
    seuil: { cle: "admin.unites.pourcentage", params: { valeur: "66,67" } },
    statut: { cle: "admin.chiffres.vue.seuilStatuts.non_franchi" },
    indicationComparaison: {
      cle: "admin.chiffres.vue.comparaisonTauxArrondie",
      params: { acceptes: 2, envoyes: 3 },
    },
  });
  expect(presentee[1].indicationComparaison).toEqual({ cle: "admin.chiffres.vue.comparaisonNonArrondie" });
});
