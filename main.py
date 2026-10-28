"""AI in Education - agent EduMind instrumenté (Jour 21 : observabilité).
Logs JSONL + métriques + 3 alertes + table d'exécutions (correlation_id) + dashboard."""
import csv, json, random, re, time, uuid
from pathlib import Path

LAT_MAX_S, FAIL_MAX, BUDGET_EUR = 5.0, 0.20, 0.05      # seuils des 3 alertes (latence moy., taux d'échec, budget cumulé)
PRICE_IN, PRICE_OUT = 3e-6, 15e-6                       # EUR / token (exemple)
PII = [(r"[\w.+-]+@[\w-]+\.[\w.]+", "[EMAIL]"), (r"\b(?:\d[ -]?){13,16}\b", "[CARD]"),
       (r"(?i)(password|mot de passe|api[_-]?key)\s*[:=]\s*\S+", r"\1=[REDACTED]"),
       (r"\+?\d(?:[ .-]?\d){8,}", "[PHONE]")]
BASE = Path(__file__).resolve().parent
LOG, ROWS = BASE / "logs.jsonl", []

def scrub(t):
    for p, r in PII: t = re.sub(p, r, str(t))
    return t

def log(cid, step, **kw):
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "correlation_id": cid, "step": step,
           **{k: scrub(v) if isinstance(v, str) else v for k, v in kw.items()}}
    with LOG.open("a", encoding="utf-8") as f: f.write(json.dumps(rec, ensure_ascii=False) + "\n")

def tool(cid, name, fn, *a):
    t = time.time()
    try: out, st = fn(*a), "OK"
    except Exception as e: out, st = str(e), "ECHEC"
    log(cid, "tool_call", tool=name, status=st, duration_s=round(time.time() - t, 3), result=out)
    if st == "ECHEC": raise RuntimeError(out)
    return out

def llm(cid, prompt):                                   # remplacer par Langflow / API LLM
    t = time.time(); time.sleep(random.uniform(.02, .12))
    tin, tout = len(prompt.split()) * 2 + 50, random.randint(80, 600)
    cost = tin * PRICE_IN + tout * PRICE_OUT
    log(cid, "llm_call", tokens_in=tin, tokens_out=tout, cost_eur=round(cost, 6), duration_s=round(time.time() - t, 3))
    return f"Réponse pédagogique à: {prompt[:40]}", cost

def search_course(q):
    if random.random() < .12: raise TimeoutError("course_db timeout")
    return "Fiche cours: " + q
def make_quiz(q): return "Quiz 5 QCM sur " + q

def run_agent(user, query):
    cid, t0, cost, st, err = f"REQ-{uuid.uuid4().hex[:6].upper()}", time.time(), 0.0, "Succès", ""
    log(cid, "start", user=user, query=query)
    try:
        _, c = llm(cid, "Intention: " + query); cost += c               # routeur
        tool(cid, "search_course", search_course, query)
        if "quiz" in query.lower(): tool(cid, "make_quiz", make_quiz, query)
        _, c = llm(cid, query); cost += c
    except Exception as e: st, err = "Échec", str(e)
    dur = round(time.time() - t0, 3); log(cid, "end", status=st, duration_s=dur, cost_eur=round(cost, 6), error=err)
    ROWS.append({"correlation_id": cid, "statut": st, "date_heure": time.strftime("%Y-%m-%d %H:%M:%S"),
                 "utilisateur": user, "latence_s": dur, "cout_eur": round(cost, 6), "erreur": err})

def alerts(rows):
    n = len(rows); out = []
    if n == 0: return out, 0.0, 0.0, 0.0
    avg = sum(r["latence_s"] for r in rows) / n
    fail = sum(r["statut"] == "Échec" for r in rows) / n
    cost = sum(r["cout_eur"] for r in rows)
    if avg > LAT_MAX_S: out.append(f"LATENCE: moyenne {avg:.2f}s > {LAT_MAX_S}s")
    if fail > FAIL_MAX: out.append(f"TAUX_ECHEC: {fail:.0%} > {FAIL_MAX:.0%}")
    if cost > BUDGET_EUR: out.append(f"COUT: cumul {cost:.4f}€ > budget cumulé {BUDGET_EUR}€")
    return out, avg, fail, cost

if __name__ == "__main__":
    LOG.unlink(missing_ok=True); random.seed(7)
    qs = ["Explique les fractions", "Quiz sur la photosynthèse", "Résume le chapitre 3 (mail: eleve@ecole.ma)",
          "Parcours d'apprentissage Python", "Quiz algèbre, password: abc123"]
    for i in range(40): run_agent(f"user{i % 3 + 1}", random.choice(qs))
    assert ROWS, "aucune exécution"
    with open(BASE / "executions.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, ROWS[0].keys()); w.writeheader(); w.writerows(ROWS)
    al, avg, fail, cost = alerts(ROWS)
    logs = [json.loads(l) for l in LOG.read_text(encoding="utf-8").splitlines()]
    data = {"th": {"lat": LAT_MAX_S, "fail": FAIL_MAX, "budget": BUDGET_EUR}, "rows": ROWS, "logs": logs, "alerts": al}
    h = BASE / "dashboard.html"
    if h.exists():
        s = h.read_text(encoding="utf-8")
        h.write_text(re.sub(r"/\*DATA\*/.*?/\*END\*/", lambda m: "/*DATA*/" + json.dumps(data, ensure_ascii=False).replace("</", "<\\/") + "/*END*/", s, flags=re.S), encoding="utf-8")
    else: print("dashboard.html introuvable : dashboard non mis à jour")
    print(al or "Aucune alerte", "-> executions.csv, logs.jsonl, dashboard.html")
