import { useFocusEffect } from "expo-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Alert, Pressable, ScrollView, Text, TextInput, View } from "react-native";

import { ClientConsoleAgents, creerSessionConsole, type ProfilAgent, type SpecificationAgent } from "@/agents/console";
import { Carte, stylesAdmin as styles } from "@/admin/composants";
import { obtenirSessionEnvoi } from "@/protocole/configuration";
import { usePersonneAppairee } from "@/roles/contexte";

const URL_CONSOLE = process.env.EXPO_PUBLIC_OPSYS_CONSOLE_URL?.trim() ?? "";
const champ = { borderWidth: 1, borderColor: "#8b9298", borderRadius: 8, padding: 10, color: "#1d242a" } as const;
const bouton = { padding: 12, backgroundColor: "#e7edf2", borderRadius: 8 } as const;
type Etat = "repos" | "chargement" | "erreur";

export default function AgentsAdmin() {
  const personne = usePersonneAppairee();
  const [url, setUrl] = useState(URL_CONSOLE);
  const [identifiant, setIdentifiant] = useState(personne ?? "");
  const [motDePasse, setMotDePasse] = useState("");
  const [session, setSession] = useState<Awaited<ReturnType<typeof creerSessionConsole>> | null>(null);
  const [agents, setAgents] = useState<ProfilAgent[]>([]);
  const [selection, setSelection] = useState<ProfilAgent | null>(null);
  const [historique, setHistorique] = useState<ProfilAgent[]>([]);
  const [message, setMessage] = useState("");
  const [etat, setEtat] = useState<Etat>("repos");
  const [form, setForm] = useState<SpecificationAgent>(formulaireVide());
  const api = useMemo(() => session ? new ClientConsoleAgents(session, fetch, () => obtenirSessionEnvoi()?.personne ?? null) : null, [session]);

  useEffect(() => {
    if (session && personne !== session.utilisateur) {
      setSession(null); setAgents([]); setSelection(null); setHistorique([]);
      setMessage("Identité appareil modifiée : reconnectez la console.");
    }
  }, [personne, session]);

  const executer = useCallback(async (action: () => Promise<void>) => {
    setEtat("chargement"); setMessage("");
    try { await action(); setEtat("repos"); }
    catch (e) { setMessage(e instanceof Error ? e.message : "Erreur console"); setEtat("erreur"); }
  }, []);
  const rafraichir = useCallback(async () => {
    if (!api) return;
    const personneCourante = obtenirSessionEnvoi()?.personne ?? null;
    if (!personneCourante || personneCourante !== session?.utilisateur) {
      setSession(null); setAgents([]); setSelection(null); setHistorique([]);
      setMessage("Identité appareil modifiée : reconnectez la console."); return;
    }
    await executer(async () => { setAgents(await api.lister()); });
  }, [api, executer, session?.utilisateur]);

  useFocusEffect(useCallback(() => { if (api) void rafraichir(); }, [api, rafraichir]));

  async function connexion() {
    const personneCourante = obtenirSessionEnvoi()?.personne ?? null;
    if (!personneCourante) { setMessage("Identité appareil non confirmée."); setMotDePasse(""); return; }
    await executer(async () => {
      const nouvelle = await creerSessionConsole(url, identifiant, motDePasse, fetch, personneCourante);
      if (obtenirSessionEnvoi()?.personne !== personneCourante) throw new Error("Identité appareil modifiée pendant la connexion");
      const client = new ClientConsoleAgents(nouvelle, fetch, () => obtenirSessionEnvoi()?.personne ?? null);
      const liste = await client.lister();
      setSession(nouvelle); setAgents(liste);
    });
    setMotDePasse("");
  }

  async function choisir(agent: ProfilAgent) {
    setSelection(agent); setForm(specDe(agent));
    if (api) await executer(async () => { setHistorique(await api.historique(agent.id)); });
  }

  async function sauvegarder() {
    if (!api) return;
    await executer(async () => {
      const profil = selection
        ? await api.modifier(selection.id, form, mutationId(), selection.revision)
        : await api.creer(form, mutationId());
      setSelection(profil); setForm(specDe(profil)); setAgents(await api.lister()); setHistorique(await api.historique(profil.id));
    });
  }

  async function activer(actif: boolean) {
    if (!api || !selection) return;
    await executer(async () => {
      const profil = await api.activer(selection.id, actif, mutationId(), selection.revision);
      setSelection(profil); setAgents(await api.lister()); setHistorique(await api.historique(profil.id));
    });
  }

  async function supprimer() {
    if (!api || !selection) return;
    Alert.alert("Suppression logique", `Désactiver et supprimer ${selection.id} ?`, [
      { text: "Annuler", style: "cancel" },
      { text: "Supprimer", style: "destructive", onPress: () => void executer(async () => {
        const profil = await api.supprimer(selection.id, mutationId(), selection.revision);
        setSelection(profil); setAgents(await api.lister()); setHistorique(await api.historique(profil.id));
      }) },
    ]);
  }

  async function deconnecter() {
    if (api) await executer(async () => { await api.deconnecter(); });
    setSession(null); setAgents([]); setSelection(null); setHistorique([]);
  }

  const modifier = <K extends keyof SpecificationAgent>(key: K, value: SpecificationAgent[K]) => setForm((ancien) => ({ ...ancien, [key]: value }));
  return <ScrollView contentContainerStyle={[styles.conteneur, { gap: 12 }]}>
    <Text style={styles.titre}>Agents spécialistes</Text>
    <Text style={styles.trace}>L’activation enregistre le profil; le core doit ensuite synchroniser sa configuration. Les spécialistes configurés réservent leurs tokens avant génération. Un résultat incertain garde sa réservation. Ces limites ne couvrent pas les agents historiques, et cette page ne donne aucun statut d’exécution.</Text>
    {!URL_CONSOLE ? <Text style={styles.avis}>Console indisponible tant que EXPO_PUBLIC_OPSYS_CONSOLE_URL n’est pas configurée.</Text> : null}
    {!session ? <Carte>
      <Text style={styles.petitTitre}>Connexion administrateur de la console</Text>
      <Text style={styles.trace}>L’identité console doit correspondre à la personne confirmée sur l’appareil. Le mot de passe n’est gardé que pendant la requête de connexion.</Text>
      <Champ label="URL de la console" value={url} onChange={setUrl} />
      <Champ label="Identifiant console" value={identifiant} onChange={setIdentifiant} />
      <Champ label="Mot de passe console" value={motDePasse} onChange={setMotDePasse} secureTextEntry />
      <Action label="Se connecter et charger les profils" disabled={etat === "chargement" || !url.trim()} onPress={() => void connexion()} />
    </Carte> : <>
      <Text style={styles.meta}>Console : {session.base} · {session.utilisateur}</Text>
      <Action label="Déconnexion console" onPress={() => void deconnecter()} />
      <Action label="Créer un profil" onPress={() => { setSelection(null); setForm(formulaireVide()); setHistorique([]); }} />
      <Text style={styles.sousTitre}>Profils actifs et inactifs</Text>
      {agents.map((agent) => <Pressable key={agent.id} onPress={() => void choisir(agent)}><Carte>
        <Text style={styles.petitTitre}>{agent.id} · révision {agent.revision}</Text>
        <Text style={styles.meta}>{agent.departement} · {agent.actif ? "Actif" : "Inactif"}{agent.supprime ? " · Supprimé logiquement" : ""}</Text>
        <Text style={styles.trace}>{agent.responsabilite}</Text>
      </Carte></Pressable>)}
      <Carte>
        <Text style={styles.petitTitre}>{selection ? `Modifier ${selection.id} (révision ${selection.revision})` : "Nouveau profil"}</Text>
        <Champ label="ID stable" value={form.id} locked={!!selection} onChange={(v) => modifier("id", v)} />
        <Champ label="Département" value={form.departement} onChange={(v) => modifier("departement", v)} />
        <Champ label="Responsabilité" value={form.responsabilite} onChange={(v) => modifier("responsabilite", v)} />
        <Champ label="Palier modèle" value={form.palier_modele} onChange={(v) => modifier("palier_modele", v)} />
        <Champ label="Outils (noms séparés par virgule)" value={form.outils.join(", ")} onChange={(v) => modifier("outils", v.split(",").map((x) => x.trim()).filter(Boolean))} />
        {(["budget_jour", "budget_mois", "limite_tours", "limite_reessais", "limite_concurrence"] as const).map((key) => <Champ key={key} label={`${key} (configuration)`} value={String(form[key])} keyboardType="numeric" onChange={(v) => { const n = Number(v); if (Number.isInteger(n)) modifier(key, n); }} />)}
        <Text style={styles.trace}>Déclencheur : manuel (valeur initiale non vide).</Text>
        <Action label="Enregistrer" disabled={etat === "chargement"} onPress={() => void sauvegarder()} />
        {selection ? <>
          <Action label={selection.actif ? "Désactiver" : "Activer"} disabled={etat === "chargement" || selection.supprime} onPress={() => void activer(!selection.actif)} />
          {!selection.supprime ? <Action label="Supprimer logiquement" onPress={() => void supprimer()} /> : null}
          <Text style={styles.sousTitre}>Historique des révisions</Text>
          {historique.map((ligne) => <View key={ligne.revision} style={{ paddingVertical: 6, gap: 3 }}>
            <Text style={styles.petitTitre}>Révision {ligne.revision} · {ligne.modifie_le}</Text>
            <Text style={styles.trace}>{ligne.modifie_par} · {ligne.actif ? "actif" : "inactif"}{ligne.supprime ? " · supprimé logiquement" : ""}</Text>
            <Text style={styles.trace}>{ligne.departement} · {ligne.palier_modele} · budget jour {ligne.budget_jour} · mois {ligne.budget_mois}</Text>
            <Text style={styles.trace}>{ligne.responsabilite}</Text>
          </View>)}
        </> : null}
      </Carte>
    </>}
    {etat === "chargement" ? <Text style={styles.trace}>Chargement…</Text> : null}
    {message ? <Text accessibilityRole="alert" style={styles.erreur}>{message}</Text> : null}
  </ScrollView>;
}

function Champ({ label, value, onChange, locked = false, secureTextEntry = false, keyboardType = "default" }: {
  readonly label: string; readonly value: string; readonly onChange: (value: string) => void;
  readonly locked?: boolean; readonly secureTextEntry?: boolean; readonly keyboardType?: "default" | "numeric";
}) {
  return <View style={{ gap: 4 }}><Text style={styles.meta}>{label}</Text><TextInput accessibilityLabel={label} style={champ} value={value} editable={!locked} secureTextEntry={secureTextEntry} keyboardType={keyboardType} onChangeText={onChange} autoCapitalize="none" /></View>;
}

function Action({ label, onPress, disabled = false }: { readonly label: string; readonly onPress: () => void; readonly disabled?: boolean }) {
  return <Pressable accessibilityRole="button" disabled={disabled} style={[bouton, disabled ? { opacity: 0.5 } : null]} onPress={onPress}><Text>{label}</Text></Pressable>;
}

function formulaireVide(): SpecificationAgent {
  return { id: "", departement: "", responsabilite: "", palier_modele: "rapide", outils: [], budget_jour: 1000, budget_mois: 10000, limite_tours: 4, limite_reessais: 1, limite_concurrence: 1, declencheurs: [{ type: "manuel" }] };
}

function specDe(profil: ProfilAgent): SpecificationAgent {
  const { actif: _a, supprime: _s, revision: _r, cree_le: _c, modifie_le: _m, modifie_par: _p, ...spec } = profil;
  return spec;
}

function mutationId(): string { return `mobile:${Date.now()}:${Math.random().toString(36).slice(2, 14)}`; }
