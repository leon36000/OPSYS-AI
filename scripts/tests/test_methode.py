# Suite de tests des scripts de methode (R-030) — la methode se teste elle-meme.
import json, os, shutil, subprocess, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def run(args, **kw):
    return subprocess.run([sys.executable] + args, capture_output=True, text=True, **kw)

def test_ledger_chain_and_tamper(tmp_path, monkeypatch):
    led = tmp_path / "registries" / "ledger"; led.mkdir(parents=True)
    script = os.path.join(HERE, "ledger_append.py")
    # copier le script dans tmp pour que LEDGER_DIR pointe local
    sdir = tmp_path / "scripts"; sdir.mkdir(); shutil.copy(script, sdir / "ledger_append.py")
    sp = str(sdir / "ledger_append.py")
    assert run([sp, "preuve", json.dumps({"tache":"t1","preuve":"cmd -> ok"})]).returncode == 0
    assert run([sp, "preuve", json.dumps({"tache":"t2","preuve":"cmd -> ok"})]).returncode == 0
    assert run([sp, "verify"]).returncode == 0
    # entree sans preuve = rejetee
    assert run([sp, "preuve", json.dumps({"tache":"t3"})]).returncode != 0
    # falsification -> chaine brisee detectee
    f = led / "preuves.jsonl"
    lines = f.read_text().splitlines()
    e = json.loads(lines[0]); e["payload"]["tache"] = "FALSIFIE"
    lines[0] = json.dumps(e, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    f.write_text("\n".join(lines) + "\n")
    assert run([sp, "verify"]).returncode == 2

def test_tally_approve_reject_and_civ(tmp_path):
    tal = os.path.join(HERE, "tally.py")
    d = tmp_path / "v"; d.mkdir()
    def dep(name, vendor, verdict, obj):
        (d / (name + ".json")).write_text(json.dumps(
            {"reviewer": name, "vendor": vendor, "verdict": verdict, "objections": obj}))
    dep("a", "v1", "APPROVE", []); dep("b", "v2", "APPROVE", []); dep("c", "v3", "APPROVE", [])
    assert run([tal, str(d), "codeur-vendor"]).returncode == 0
    dep("c", "v3", "REJECT", [{"severite": "critique", "fichier": "x", "description": "y", "preuve": "z"}])
    assert run([tal, str(d), "codeur-vendor"]).returncode == 3
    dep("c", "codeur-vendor", "APPROVE", [])
    assert run([tal, str(d), "codeur-vendor"]).returncode == 2  # CIV: meme vendor que le codeur

def test_structure_lint_green_here():
    assert run([os.path.join(HERE, "structure_lint.py")]).returncode == 0
