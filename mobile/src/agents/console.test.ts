import { ClientConsoleAgents, creerSessionConsole } from "./console";

const profil = {
  id: "agent-test", departement: "m01-front-office", responsabilite: "Qualifier", palier_modele: "rapide",
  outils: [], budget_jour: 100, budget_mois: 1000, limite_tours: 4, limite_reessais: 1,
  limite_concurrence: 1, declencheurs: [{ type: "manuel" }], actif: false, supprime: false,
  revision: 1, cree_le: "2026-09-30T00:00:00Z", modifie_le: "2026-09-30T00:00:00Z", modifie_par: "alice",
};

describe("client agents de la console", () => {
  const fetcher = jest.fn();
  beforeEach(() => fetcher.mockReset());

  test("connexion par formulaire puis session cookie; refuse rôle ou identité différente", async () => {
    fetcher.mockResolvedValueOnce({ ok: true, status: 303 }).mockResolvedValueOnce({
      ok: true, status: 200, json: async () => ({ utilisateur: "alice", roles: ["admin"], csrf: "csrf-secret" }),
    });
    const session = await creerSessionConsole("https://console.example/opsys/", "alice", "secret", fetcher);
    expect(session).toEqual({ utilisateur: "alice", roles: ["admin"], csrf: "csrf-secret", base: "https://console.example/opsys" });
    expect(fetcher.mock.calls[0][0]).toBe("https://console.example/opsys/connexion");
    expect(fetcher.mock.calls[0][1]).toMatchObject({ method: "POST", credentials: "include", headers: { "Content-Type": "application/x-www-form-urlencoded" } });
    expect(fetcher.mock.calls[0][1].body).toBe("identifiant=alice&mot_de_passe=secret");
    expect(fetcher.mock.calls[1][1]).toMatchObject({ method: "GET", credentials: "include" });
    fetcher.mockReset().mockResolvedValueOnce({ ok: true, status: 303 }).mockResolvedValueOnce({
      ok: true, status: 200, json: async () => ({ utilisateur: "bob", roles: ["admin"], csrf: "csrf" }),
    });
    await expect(creerSessionConsole("https://console.example/opsys", "bob", "secret", fetcher, "alice")).rejects.toThrow("identité");
  });

  test("contrat enveloppé, cookies sur toutes requêtes et csrf sur mutations", async () => {
    const session = { base: "https://console.example/opsys", utilisateur: "alice", roles: ["admin"], csrf: "csrf-secret" };
    fetcher.mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ agents: [profil] }) })
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ agent: profil }) })
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ historique: [profil] }) })
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ agent: profil }) });
    const api = new ClientConsoleAgents(session, fetcher);
    await expect(api.lister()).resolves.toEqual([profil]);
    await api.obtenir("agent-test");
    await api.historique("agent-test");
    await api.creer(profil, "mutation-123456");
    expect(fetcher.mock.calls.map((x) => x[0])).toEqual([
      "https://console.example/opsys/api/agents", "https://console.example/opsys/api/agents/agent-test",
      "https://console.example/opsys/api/agents/agent-test/historique", "https://console.example/opsys/api/agents",
    ]);
    for (const [, init] of fetcher.mock.calls) expect(init.credentials).toBe("include");
    expect(fetcher.mock.calls[3][1].headers).toMatchObject({ "X-CSRF-Token": "csrf-secret" });
    expect(JSON.parse(fetcher.mock.calls[3][1].body)).toMatchObject({ spec: profil, mutation_id: "mutation-123456" });
  });

  test("URL absente, réponse invalide et erreurs HTTP ne sont pas simulées", async () => {
    await expect(creerSessionConsole("", "alice", "secret", fetcher)).rejects.toThrow("URL");
    fetcher.mockResolvedValueOnce({ ok: false, status: 401 });
    await expect(creerSessionConsole("https://console.example", "alice", "secret", fetcher)).rejects.toThrow("401");
  });

  test("invalide les opérations après un changement d’identité appareil", async () => {
    let personne: string | null = "alice";
    const api = new ClientConsoleAgents({ base: "https://console.example", utilisateur: "alice", roles: ["admin"], csrf: "csrf" }, fetcher, () => personne);
    personne = "bob";
    await expect(api.lister()).rejects.toThrow("Identité appareil modifiée");
    expect(fetcher).not.toHaveBeenCalled();
  });

  test("refuse le résultat de A quand la session devient B pendant la lecture du corps", async () => {
    let personne: string | null = "alice";
    const api = new ClientConsoleAgents({ base: "https://console.example", utilisateur: "alice", roles: ["admin"], csrf: "csrf" }, fetcher, () => personne);
    fetcher.mockResolvedValueOnce({ ok: true, status: 200, json: async () => {
      personne = "bob";
      return { agents: [profil] };
    } });
    await expect(api.lister()).rejects.toThrow("Identité appareil modifiée");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  test("déconnexion utilise le cookie et le CSRF, mais refuse après changement d’identité", async () => {
    const session = { base: "https://console.example/opsys", utilisateur: "alice", roles: ["admin"], csrf: "csrf-secret" };
    fetcher.mockResolvedValueOnce({ ok: true, status: 200 });
    await new ClientConsoleAgents(session, fetcher).deconnecter();
    expect(fetcher.mock.calls[0][0]).toBe("https://console.example/opsys/deconnexion");
    expect(fetcher.mock.calls[0][1]).toMatchObject({ method: "POST", credentials: "include", body: "csrf=csrf-secret" });
    let person = "bob";
    const api = new ClientConsoleAgents(session, fetcher, () => person);
    await expect(api.deconnecter()).rejects.toThrow("Identité appareil modifiée");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  test("envoie les préconditions de révision pour modification, activation et suppression logique", async () => {
    const api = new ClientConsoleAgents({ base: "https://console.example/opsys", utilisateur: "alice", roles: ["nathan_owner"], csrf: "csrf" }, fetcher);
    fetcher.mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ agent: profil }) })
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ agent: profil }) })
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ agent: profil }) });
    await api.modifier("agent-test", profil, "mutation-patch-1", 3);
    await api.activer("agent-test", true, "mutation-active-1", 4);
    await api.supprimer("agent-test", "mutation-delete-1", 5);
    expect(fetcher.mock.calls.map(([url, init]) => [url, init.method, JSON.parse(String(init.body))])).toEqual([
      ["https://console.example/opsys/api/agents/agent-test", "PATCH", { spec: profil, mutation_id: "mutation-patch-1", revision_attendue: 3 }],
      ["https://console.example/opsys/api/agents/agent-test/activation", "POST", { actif: true, mutation_id: "mutation-active-1", revision_attendue: 4 }],
      ["https://console.example/opsys/api/agents/agent-test", "DELETE", { mutation_id: "mutation-delete-1", revision_attendue: 5 }],
    ]);
    for (const [, init] of fetcher.mock.calls) {
      expect(init.credentials).toBe("include");
      expect(init.headers).toMatchObject({ "X-CSRF-Token": "csrf" });
    }
  });
});
