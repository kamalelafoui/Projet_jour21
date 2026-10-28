"""EduMind - version LangGraph (Jour 21 : observabilité).
Même instrumentation que main.py (logs JSONL, correlation_id, 3 alertes, PII masquée),
mais le workflow de l'agent est un graphe : route -> search -> [quiz] -> answer -> finish.
Réutilise les briques de main.py : scrub/log/tool/llm/alerts, outils et seuils.
Installation : pip install langgraph"""
import csv, json, random, re, time, uuid
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
import main as m                                   # briques d'observabilité communes


class State(TypedDict, total=False):
    cid: str; user: str; query: str; t0: float
    cost: float; status: str; error: str


# ----------------------------- Noeuds -----------------------------
def start(s: State) -> State:
    cid = f"REQ-{uuid.uuid4().hex[:6].upper()}"
    m.log(cid, "start", user=s["user"], query=s["query"])
    return {"cid": cid, "t0": time.time(), "cost": 0.0, "status": "Succès", "error": ""}

def route(s: State) -> State:                       # LLM routeur
    _, c = m.llm(s["cid"], "Intention: " + s["query"])
    return {"cost": s["cost"] + c}

def search(s: State) -> State:
    try: m.tool(s["cid"], "search_course", m.search_course, s["query"]); return {}
    except Exception as e: return {"status": "Échec", "error": str(e)}

def quiz(s: State) -> State:
    try: m.tool(s["cid"], "make_quiz", m.make_quiz, s["query"]); return {}
    except Exception as e: return {"status": "Échec", "error": str(e)}

def answer(s: State) -> State:                      # LLM final
    _, c = m.llm(s["cid"], s["query"])
    return {"cost": s["cost"] + c}

def finish(s: State) -> State:                      # toujours exécuté : écrit end + ligne d'exécution
    dur = round(time.time() - s["t0"], 3)
    m.log(s["cid"], "end", status=s["status"], duration_s=dur, cost_eur=round(s["cost"], 6), error=s["error"])
    m.ROWS.append({"correlation_id": s["cid"], "statut": s["status"], "date_heure": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "utilisateur": s["user"], "latence_s": dur, "cout_eur": round(s["cost"], 6), "erreur": s["error"]})
    return {}


# ----------------------------- Arêtes conditionnelles -----------------------------
def after_search(s: State) -> str:
    if s["status"] == "Échec": return "finish"
    return "quiz" if "quiz" in s["query"].lower() else "answer"

def after_quiz(s: State) -> str:
    return "finish" if s["status"] == "Échec" else "answer"


def build():
    g = StateGraph(State)
    for name, fn in [("start", start), ("route", route), ("search", search), ("quiz", quiz), ("answer", answer), ("finish", finish)]:
        g.add_node(name, fn)
    g.add_edge(START, "start"); g.add_edge("start", "route"); g.add_edge("route", "search")
    g.add_conditional_edges("search", after_search, {"quiz": "quiz", "answer": "answer", "finish": "finish"})
    g.add_conditional_edges("quiz", after_quiz, {"answer": "answer", "finish": "finish"})
    g.add_edge("answer", "finish"); g.add_edge("finish", END)
    return g.compile()


if __name__ == "__main__":
    m.LOG.unlink(missing_ok=True); random.seed(7)
    app = build()
    qs = ["Explique les fractions", "Quiz sur la photosynthèse", "Résume le chapitre 3 (mail: eleve@ecole.ma)",
          "Parcours d'apprentissage Python", "Quiz algèbre, password: abc123"]
    for i in range(40): app.invoke({"user": f"user{i % 3 + 1}", "query": random.choice(qs)})
    with open(m.BASE / "executions.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, m.ROWS[0].keys()); w.writeheader(); w.writerows(m.ROWS)
    al, avg, fail, cost = m.alerts(m.ROWS)
    logs = [json.loads(l) for l in m.LOG.read_text(encoding="utf-8").splitlines()]
    data = {"th": {"lat": m.LAT_MAX_S, "fail": m.FAIL_MAX, "budget": m.BUDGET_EUR}, "rows": m.ROWS, "logs": logs, "alerts": al}
    h = m.BASE / "dashboard.html"
    if h.exists():
        s = h.read_text(encoding="utf-8")
        h.write_text(re.sub(r"/\*DATA\*/.*?/\*END\*/", lambda x: "/*DATA*/" + json.dumps(data, ensure_ascii=False).replace("</", "<\\/") + "/*END*/", s, flags=re.S), encoding="utf-8")
    print(al or "Aucune alerte", "-> executions.csv, logs.jsonl, dashboard.html")
