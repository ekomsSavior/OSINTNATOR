#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, csv, json, time, queue, webbrowser, hashlib
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import List, Dict, Any, Tuple
from urllib.parse import quote_plus
import concurrent.futures
import threading


import tkinter as tk
from tkinter import ttk, messagebox

import scrapers as PLUG
from lookup_paths import guide_for, manual_path, input_hint
from bounded_runner import run_bounded
from graph_export import export_graphml
from report_html import export_html
from settings_store import save_settings, load_settings
import api_sources  # registers documented public API adapters
import free_sources
import public_web
import web_search
import identity_sources
import linkedin_sources
import property_sources
import property_directory
import obituary_sources
import contact_sources
from evidence_matching import annotate_hit
from query_inputs import ENGINES, normalize_domain, FIELD_LABELS, search_inputs
from research_plan import plan_lookups, coverage_plan, coverage, balanced_findings

APP_NAME = "Osintnator"
REPORTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
CACHE_DIR = os.path.join(REPORTS_DIR, "cache")
os.makedirs(REPORTS_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

BANNER = r"""
  ___  ___(_)_ __ | |_ _ __   __ _| |_ ___  _ __ 
 / _ \/ __| | '_ \| __| '_ \ / _` | __/ _ \| '__|
| (_) \__ \ | | | | |_| | | | (_| | || (_) | |   
 \___/|___/_|_| |_|\__|_| |_|\__,_|\__\___/|_|   
"""

# ===== Theme Palettes =====
DARK = {
    "bg":        "#080808",
    "panel":     "#141414",
    "sunken":    "#2d2d2d",
    "fg":        "#e6e6e6",
    "muted":     "#aaaaaa",
    "accent":    "#eeeeee",
    "entrybg":   "#2b2b2b",
    "entryfg":   "#eaeaea",
    "entrybd":   "#3a3a3a",
    "focus":     "#555555",
    "tab_bg":    "#141414",
    "tab_sel":   "#333333",
    "pb_trough": "#2a2a2a",
    "pb_bar":    "#eeeeee",
}
LIGHT = {
    "bg":        "#f5f5f5",
    "panel":     "#ffffff",
    "sunken":    "#f0f0f0",
    "fg":        "#202020",
    "muted":     "#606060",
    "accent":    "#333333",
    "entrybg":   "#ffffff",
    "entryfg":   "#202020",
    "entrybd":   "#cccccc",
    "focus":     "#333333",
    "tab_bg":    "#f0f0f0",
    "tab_sel":   "#ffffff",
    "pb_trough": "#eeeeee",
    "pb_bar":    "#333333",
}


from source_catalog import CATS, SITE_DOMAIN, SITE_URL, PRIORITY_SITES, ENGINE_SOURCES
from models import OSINTQuery, OSINTHit

# ---------- Helpers ----------
def digits_only(s: str) -> str: return "".join(c for c in s if c.isdigit())

def site_base_url(site: str) -> str | None:
    if site in SITE_URL: return SITE_URL[site]
    dom = SITE_DOMAIN.get(site); return f"https://{dom}" if dom else None

def dork_url(site_label: str, q: OSINTQuery, engine: str) -> str:
    """One relevant identifier per query, with location only for name/address searches."""
    if site_label=='LinkedIn Name Search':
        return ENGINES.get(engine,ENGINES['DuckDuckGo'])+quote_plus(linkedin_sources.search_expression(q)[0])
    if site_label=='Public Web Search' and getattr(q,'search_field',None):
        inputs=search_inputs(q)
        if inputs:return ENGINES.get(engine,ENGINES['DuckDuckGo'])+quote_plus(inputs[0]['query'])
    domain = SITE_DOMAIN.get(site_label)
    location = False
    if site_label in CATS.get("Property Records & Assessor", []):
        value = q.address1 or q.full_name
        location = True
    elif site_label in CATS.get("Reverse Phone / Address", []):
        value = digits_only(q.phone) or q.address1
        location = bool(q.address1 and not q.phone)
    elif site_label in ("Domain RDAP", "Domain DNS Records", "Website & Linked Profiles", "VirusTotal Domain (opt-in)"):
        try: value = normalize_domain(q.domain)
        except ValueError: value = q.domain
    elif site_label in ("Email Domain Records", "HaveIBeenPwned", "Hunter.io", "EmailHippo"):
        value = q.email
    elif site_label in CATS.get("People Search", []) or site_label in CATS.get("Court/Criminal/Gov", []):
        value = q.full_name or q.email or digits_only(q.phone)
        location = bool(q.full_name)
    else:
        value = q.username or q.full_name or q.email or q.domain
    parts = [f'site:{domain}'] if domain else []
    if value: parts.append('"'+value.replace('"',' ').strip()+'"')
    if location: parts.extend(v for v in (q.city,q.state,q.zip) if v)
    return ENGINES.get(engine,ENGINES["DuckDuckGo"]) + quote_plus(' '.join(parts) or site_label)


def cache_key_for_query(q: OSINTQuery) -> str:
    payload = json.dumps({k: v.strip() for k,v in q.to_ordered_dict().items()}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

# NEW helper: canonical cache path
def cache_path_for_query(q: OSINTQuery, sites=(), engine="DuckDuckGo") -> str:
    scope = json.dumps({"version": 8, "sites": sorted(set(sites)), "engine": engine, "search_fallback": getattr(q,"search_fallback",True)}, sort_keys=True)
    scope_key = hashlib.sha256(scope.encode()).hexdigest()
    return os.path.join(CACHE_DIR, f"{cache_key_for_query(q)}_{scope_key}.json")

def load_cache(q: OSINTQuery, sites=(), engine="DuckDuckGo") -> List[OSINTHit]:
    path = cache_path_for_query(q, sites, engine)
    if not os.path.exists(path): return []
    if time.time() - os.path.getmtime(path) > 86400: return []
    try:
        with open(path, "r", encoding="utf-8") as f: data = json.load(f)
        return [OSINTHit(**h) for h in data]
    except Exception: return []

def save_cache(q: OSINTQuery, hits: List[OSINTHit], sites=(), engine="DuckDuckGo") -> str:
    path = cache_path_for_query(q, sites, engine)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump([asdict(h) for h in hits], f, ensure_ascii=False, indent=2)
        return path
    except Exception: return ""

# NEW helper: clear cache file for a specific query
def clear_cache_for_query(q: OSINTQuery) -> bool:
    import glob
    prefix = os.path.join(CACHE_DIR, cache_key_for_query(q))
    removed = False
    for path in glob.glob(prefix + "_*.json") + [prefix + ".json"]:
        try:
            os.remove(path)
            removed = True
        except OSError:
            pass
    return removed


def _report_paths(ts: str) -> Tuple[str, str, str]:
    return (
        os.path.join(REPORTS_DIR, f"osint_{ts}.csv"),
        os.path.join(REPORTS_DIR, f"osint_{ts}.json"),
        os.path.join(REPORTS_DIR, f"osint_{ts}.txt"),
    )

def save_reports(hits: List[OSINTHit]) -> Tuple[str, str, str]:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S_%f")
    csv_path, json_path, txt_path = _report_paths(ts)

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["site","title","snippet","url","status","checked_at","source","source_url","relationship","entity_type","entity_value","content_sha256","evidence_file","input_fields","context_fields","engine","requested_engine","matched_inputs"])
        for h in hits:
            w.writerow([h.site, h.title, h.snippet, h.url, h.raw.get("kind", "candidate"), h.raw.get("checked_at", ""), h.raw.get("source", h.site)] +
                       [h.raw.get(key,"") for key in ("source_url","relationship","entity_type","entity_value","content_sha256","evidence_file")] +
                       [", ".join(h.raw.get("input_fields",[])), ", ".join(h.raw.get("context_fields",[])), h.raw.get("engine",""), h.raw.get("requested_engine",""), ", ".join(h.raw.get('matched_inputs',[]))])

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump([asdict(h) for h in hits], f, ensure_ascii=False, indent=2)

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"{APP_NAME} report — {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n")
        f.write("="*72 + "\n")
        if not hits: f.write("(no results)\n")
        for i, h in enumerate(hits, 1):
            f.write(f"[{i}] {h.site}\nStatus:  {h.raw.get('kind', 'candidate')}\nTitle:   {h.title}\nURL:     {h.url}\n")
            snip = (h.snippet or "").replace("\n", " ").strip()
            f.write(f"Snippet: {snip}\n" + "-"*72 + "\n")
    export_html(hits,os.path.splitext(json_path)[0]+'.html')
    return csv_path, json_path, txt_path

def _run_site_with_timeout(site, q, timeout, cancel=None):
    if cancel is not None and cancel.is_set():
        return [manual_path(site, q, SITE_DOMAIN, SITE_URL, CATS, "cancelled")]
    missing = input_hint(site, q, CATS)
    if missing:
        return [manual_path(site, q, SITE_DOMAIN, SITE_URL, CATS, "needs_input", missing)]
    guide = guide_for(site)
    if guide or site not in PLUG.SCRAPERS:
        return [manual_path(site, q, SITE_DOMAIN, SITE_URL, CATS)]
    outcome = run_bounded(site, q, timeout, cancel)
    hits = outcome.hits
    if site == "Username Pack (direct)":
        checked = {h.url for h in hits}
        hits.extend(h for h in PLUG.username_paths(q) if h.url not in checked)
    if not hits or outcome.status != "complete":
        hits.append(manual_path(site, q, SITE_DOMAIN, SITE_URL, CATS,
                                outcome.status if outcome.status != "complete" else "manual", outcome.error))
    for hit in hits:
        hit.raw.setdefault("checked_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
        hit.raw.setdefault("source", site)
    return hits

# ---------- GUI ----------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME); self.geometry("1200x900")
        self.engine_var = tk.StringVar(value="DuckDuckGo")
        self.threads_var = tk.IntVar(value=6)
        self.timeout_var = tk.IntVar(value=30)
        self.category_vars: Dict[str, Dict[str, tk.BooleanVar]] = {}
        self.results: List[OSINTHit] = []
        self.ui_queue = queue.Queue()
        self._running = False
        self.cancel_event = threading.Event()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.filter_var = tk.StringVar()
        self.kind_var = tk.StringVar(value="Findings")
        self.input_filter_var = tk.StringVar(value="All inputs")
        self.fallback_var = tk.BooleanVar(value=True)
        self.coverage_plan = {}
        self.coverage_var = tk.StringVar(value="Input coverage appears here when a search starts.")
        self.source_canvases=[]
        self._font_size = 10  # results font size

        self._header()
        self._footer()

        # ===== RESIZABLE LAYOUT (draggable sash) =====
        self.pw = ttk.Panedwindow(self, orient="vertical")
        self.pw.pack(fill="both", expand=True, padx=10, pady=(0,8))

        self.top_pane = ttk.Frame(self.pw)     # banner + inputs + tabs
        self.bottom_pane = ttk.Frame(self.pw)  # results/feed
        self.pw.add(self.top_pane, weight=3)   # give more room to results by default
        self.pw.add(self.bottom_pane, weight=5)

        # build panes
        self._banner(self.top_pane)
        self._inputs(self.top_pane)
        self._tabs(self.top_pane)
        self._result_area(self.bottom_pane)

        self._apply_theme(True)
        self.minsize(1100, 800)
        self._sash_after_id = self.after_idle(lambda: self.pw.sashpos(0, min(500,max(300,self.pw.winfo_height()-190))))
        self.pw.bind("<Configure>",self._keep_results_visible)
        self.pw.bind("<ButtonRelease-1>",lambda event:self.after_idle(self._reset_pane_bounds))
        self._queue_after_id = self.after(200, self._process_ui_queue)

        # allow Ctrl/Cmd + / - to zoom results text
        self.bind_all("<Control-plus>", lambda e: self._bump_font(1))
        self.bind_all("<Control-KP_Add>", lambda e: self._bump_font(1))
        self.bind_all("<Control-minus>", lambda e: self._bump_font(-1))
        self.bind_all("<Control-KP_Subtract>", lambda e: self._bump_font(-1))

    # UI bits
    def _header(self):
        title = ttk.Frame(self); title.pack(fill="x", padx=14, pady=(12,6))
        ttk.Label(title, text="OSINTNATOR", font=("TkDefaultFont", 18, "bold")).pack(side="left")
        ttk.Label(title, text="Public sources / direct lookups / research paths").pack(side="left", padx=16)
        ttk.Button(title, text="Load settings", command=self._load_settings).pack(side="right", padx=6)
        ttk.Button(title, text="Save settings", command=self._save_settings).pack(side="right")
        ttk.Button(title, text="Max results", command=self._maximize_results).pack(side="right")
        self.dark_var = tk.BooleanVar(value=True)
        self.bypass_cache_var = tk.BooleanVar(value=False)
        controls = ttk.Frame(self); controls.pack(fill="x", padx=14, pady=(0,10))
        ttk.Label(controls, text="Search engine").pack(side="left")
        ttk.Combobox(controls, textvariable=self.engine_var, values=list(ENGINES), state="readonly", width=12).pack(side="left", padx=6)
        ttk.Label(controls, text="Workers").pack(side="left", padx=(8,4))
        ttk.Spinbox(controls, from_=2, to=12, textvariable=self.threads_var, width=4).pack(side="left")
        ttk.Label(controls, text="Lookup budget (s)").pack(side="left", padx=(8,4))
        ttk.Spinbox(controls, from_=3, to=60, textvariable=self.timeout_var, width=4).pack(side="left")
        ttk.Checkbutton(controls, text="Dark", variable=self.dark_var, command=self._toggle_dark).pack(side="left", padx=8)
        ttk.Checkbutton(controls, text="Bypass cache", variable=self.bypass_cache_var).pack(side="left")
        ttk.Button(controls, text="Clear cache", command=self._clear_cache_current).pack(side="left", padx=8)
        ttk.Button(controls, text="Username pack", command=self._quick_username_pack).pack(side="right")

    def _banner(self, parent):
        frame = ttk.Frame(parent); frame.pack(fill="x", pady=(0,6))
        self.banner_txt = tk.Text(frame, height=1, bd=0, highlightthickness=0)
        self.banner_txt.pack(fill="x")
        self.banner_txt.insert("1.0", "RECORD = returned data    CANDIDATE = review needed    MANUAL = open source    NEEDS INPUT = add details")
        self.banner_txt.configure(state="disabled", font=("TkDefaultFont", 9))

    def _inputs(self, parent):
        g = ttk.Frame(parent); g.pack(fill="x", pady=4)
        self.var_first  = tk.StringVar(); self._field(g,0,0,"First",self.var_first)
        self.var_last   = tk.StringVar(); self._field(g,0,1,"Last",self.var_last)
        self.var_user   = tk.StringVar(); self._field(g,0,2,"Username",self.var_user)
        self.var_email  = tk.StringVar(); self._field(g,1,0,"Email",self.var_email,40)
        self.var_phone  = tk.StringVar(); self._field(g,1,1,"Phone",self.var_phone)
        self.var_addr1  = tk.StringVar(); self._field(g,1,2,"Address 1",self.var_addr1,40)
        self.var_city   = tk.StringVar(); self._field(g,2,0,"City",self.var_city)
        self.var_state  = tk.StringVar(); self._field(g,2,1,"State",self.var_state)
        self.var_zip    = tk.StringVar(); self._field(g,2,2,"ZIP",self.var_zip)

        self.var_domain = tk.StringVar(); self._field(g,3,0,"Domain / website URL",self.var_domain,40)

    def _field(self, parent, r, c, label, var, width=28):
        f = ttk.Frame(parent); f.grid(row=r, column=c, padx=6, pady=4, sticky="ew")
        ttk.Label(f, text=label).pack(anchor="w"); ttk.Entry(f, textvariable=var, width=width).pack(fill="x")

    def _tabs(self, parent):
        nb = ttk.Notebook(parent); nb.pack(fill="both", expand=True, pady=6)
        self.category_vars.clear()
        for cat, sites in CATS.items():
            tab = ttk.Frame(nb); nb.add(tab, text=cat)
            self._cat_tab(tab, cat, sites)
            if cat == "Free Research":
                nb.select(tab)

    def _cat_tab(self, parent, cat, sites):
        bar = ttk.Frame(parent); bar.pack(fill="x", pady=(6,2))
        ttk.Button(bar, text="Select all", command=lambda c=cat: self._select_all(c, True)).pack(side="left")
        ttk.Button(bar, text="Clear", command=lambda c=cat: self._select_all(c, False)).pack(side="left", padx=(6,0))
        if cat=="Free Research":
            ttk.Checkbutton(bar,text="Try other engines if unavailable",variable=self.fallback_var).pack(side="left",padx=12)
        ttk.Button(bar, text=f"Run selected ({cat})", command=lambda c=cat: self._run_category(c)).pack(side="right")

        self.category_vars[cat] = {}
        scrollbox=ttk.Frame(parent);scrollbox.pack(fill="both",expand=True)
        canvas=tk.Canvas(scrollbox,highlightthickness=0,height=150)
        scrollbar=ttk.Scrollbar(scrollbox,orient='vertical',command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
        self.source_canvases.append(canvas)
        cols=ttk.Frame(canvas);window=canvas.create_window((0,0),window=cols,anchor='nw')
        cols.bind('<Configure>',lambda event,c=canvas:c.configure(scrollregion=c.bbox('all')))
        canvas.bind('<Configure>',lambda event,c=canvas,w=window:c.itemconfigure(w,width=event.width))
        left = ttk.Frame(cols); left.pack(side="left", fill="both", expand=True, padx=(0,8))
        right= ttk.Frame(cols); right.pack(side="left", fill="both", expand=True)
        half = (len(sites)+1)//2
        for i, site in enumerate(sites):
            default_sel = (site in ("Public Web Search","LinkedIn Name Search","GitHub Public Discovery","Gravatar Email Profile","GitHub Email Commits","Official Property Records","US Address Geography","GitHub Profile API", "Bluesky Profile API", "Domain RDAP", "Username Pack (direct)"))
            var = tk.BooleanVar(value=default_sel)
            button=ttk.Checkbutton(left if i<half else right, text=site + (" (manual guide)" if guide_for(site) or site not in PLUG.SCRAPERS else ""), variable=var)
            button.pack(anchor="w",pady=1)
            button.bind('<Button-4>',lambda event,c=canvas:c.yview_scroll(-1,'units'))
            button.bind('<Button-5>',lambda event,c=canvas:c.yview_scroll(1,'units'))
            self.category_vars[cat][site] = var

    def _result_area(self, parent):
        # results pane is larger by default and fully resizable
        self.progress = ttk.Progressbar(parent, orient="horizontal", mode="determinate")
        self.progress.pack(side="bottom", fill="x")
        self.status = tk.StringVar(value="ready")
        self.status_lbl = ttk.Label(parent, textvariable=self.status)
        self.status_lbl.pack(side="bottom", anchor="w", pady=4)
        box = ttk.Frame(parent); box.pack(fill="both", expand=True)
        # toolbar for the results area
        tbar = ttk.Frame(box); tbar.pack(fill="x", pady=(0,6))
        ttk.Label(tbar, text="Filter results").pack(side="left")
        ttk.Entry(tbar, textvariable=self.filter_var, width=24).pack(side="left", padx=6)
        kinds=["Findings", "Shared evidence", "All", "record", "candidate", "context", "blocked", "unavailable", "manual", "not_found", "needs_input", "timeout", "error", "cancelled"]
        ttk.Combobox(tbar, textvariable=self.kind_var, values=kinds, state="readonly", width=12).pack(side="left")
        ttk.Combobox(tbar,textvariable=self.input_filter_var,values=["All inputs"]+list(FIELD_LABELS.values()),state="readonly",width=17).pack(side="left",padx=6)
        self.input_filter_var.trace_add("write",lambda *_:self._refresh_results())
        self.filter_var.trace_add("write", lambda *_: self._refresh_results())
        self.kind_var.trace_add("write", lambda *_: self._refresh_results())
        ttk.Button(tbar, text="A–", command=lambda: self._bump_font(-1)).pack(side="right", padx=4)
        ttk.Button(tbar, text="A+", command=lambda: self._bump_font(1)).pack(side="right")

        self.coverage_label=ttk.Label(box,textvariable=self.coverage_var,wraplength=1120,justify="left")
        self.coverage_label.pack(fill="x",pady=(0,6))
        self.coverage_label.bind("<Configure>",lambda event:self.coverage_label.configure(wraplength=max(300,event.width)))
        # scrolled text
        sc = ttk.Frame(box); sc.pack(fill="both", expand=True)
        self.txt_scroll = ttk.Scrollbar(sc, orient="vertical")
        self.txt = tk.Text(sc, height=8, wrap="word", bd=0, highlightthickness=0, yscrollcommand=self.txt_scroll.set)
        self.txt_scroll.config(command=self.txt.yview)
        self.txt.pack(side="left", fill="both", expand=True)
        self.txt_scroll.pack(side="right", fill="y")
        self.txt.configure(font=("TkDefaultFont", self._font_size))

    def _footer(self):
        bar = ttk.Frame(self); bar.pack(side="bottom", fill="x", padx=10, pady=(6,12))
        ttk.Button(bar, text="Run all selected", command=self._run_all).pack(side="left")
        ttk.Button(bar, text="Select all sources", command=lambda:[var.set(True) for group in self.category_vars.values() for var in group.values()]).pack(side="left",padx=(8,0))
        ttk.Button(bar, text="Save reports", command=self._save_now).pack(side="left", padx=(8,0))
        ttk.Button(bar, text="Export GraphML", command=self._export_graph).pack(side="left", padx=8)
        ttk.Button(bar, text="Stop search", command=self._cancel).pack(side="left", padx=8)
        ttk.Button(bar, text="About / Legal", command=self._about).pack(side="right")

    # theme controls
    def _toggle_dark(self): self._apply_theme(self.dark_var.get())

    def _apply_theme(self, dark: bool):
        P = DARK if dark else LIGHT
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # ---- base colors / option db ----
        self.configure(bg=P["bg"])
        self.option_clear()
        self.option_add("*background", P["panel"])
        self.option_add("*foreground", P["fg"])
        self.option_add("*selectBackground", P["focus"])
        self.option_add("*selectForeground", "#ffffff")
        # listbox used by Combobox dropdown
        self.option_add("*TCombobox*Listbox.background", P["panel"])
        self.option_add("*TCombobox*Listbox.foreground", P["fg"])
        # caret color in single-line entries
        self.option_add("*Entry.insertBackground", P["entryfg"])
        self.option_add("*Spinbox.insertBackground", P["entryfg"])

        # ---- core widgets ----
        style.configure(".", background=P["panel"], foreground=P["fg"])
        style.configure("TFrame", background=P["panel"])
        style.configure("TLabel", background=P["panel"], foreground=P["fg"])

        style.configure("TButton", background=P["sunken"], foreground=P["fg"])
        style.map("TButton",
                  background=[("active", P["focus"])],
                  foreground=[("active", "#ffffff")])

        # Entries / Spinboxes
        style.configure(
            "TEntry",
            fieldbackground=P["entrybg"],
            foreground=P["entryfg"],
            bordercolor=P["entrybd"],
            lightcolor=P["entrybd"],
            darkcolor=P["entrybd"],
        )
        style.map(
            "TEntry",
            fieldbackground=[("disabled", P["sunken"]), ("readonly", P["entrybg"])],
            foreground=[("disabled", P["muted"]), ("readonly", P["entryfg"])],
        )
        style.configure(
            "TSpinbox",
            fieldbackground=P["entrybg"],
            foreground=P["entryfg"],
            arrowsize=12,
        )
        style.map(
            "TSpinbox",
            fieldbackground=[("disabled", P["sunken"])],
            foreground=[("disabled", P["muted"])],
        )

        # Combobox (fix low-contrast readonly text)
        style.configure(
            "TCombobox",
            fieldbackground=P["entrybg"],
            foreground=P["entryfg"],
            bordercolor=P["entrybd"],
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", P["entrybg"]), ("disabled", P["sunken"])],
            foreground=[("readonly", P["entryfg"]), ("disabled", P["muted"])],
        )

        # Notebook / Tabs
        style.configure("TNotebook", background=P["tab_bg"], tabmargins=[2, 5, 2, 0])
        style.configure("TNotebook.Tab", background=P["tab_bg"], foreground=P["fg"])
        style.map(
            "TNotebook.Tab",
            background=[("selected", P["tab_sel"]), ("active", P["tab_sel"])],
            foreground=[("selected", P["fg"])],
        )

        # Checkboxes, Progress
        style.configure("TCheckbutton", background=P["panel"], foreground=P["fg"])
        style.map("TCheckbutton", background=[("active", P["sunken"])], indicatorbackground=[("selected", P["fg"]), ("!selected", P["entrybg"])])
        style.configure("Horizontal.TProgressbar", troughcolor=P["pb_trough"], background=P["pb_bar"])

        self.status_lbl.configure(foreground=P["muted"])
        self._style_text_widgets(dark)


    def _style_text_widgets(self, dark: bool):
        P = DARK if dark else LIGHT
        for canvas in self.source_canvases:canvas.configure(bg=P['panel'])
        self.banner_txt.configure(bg=P["bg"], fg=P["accent"], insertbackground=P["fg"])
        self.txt.configure(bg=P["bg"], fg=P["fg"], insertbackground=P["fg"])
        self.txt.configure(selectbackground=P["focus"], selectforeground=P["fg"])
        for tag in self.txt.tag_names():
            if tag.startswith("link_"): self.txt.tag_configure(tag, foreground=P["accent"])
        self.txt.tag_configure("link", foreground=P["accent"], underline=True)
        self.txt.tag_bind("link", "<Enter>", lambda e: self.txt.config(cursor="hand2"))
        self.txt.tag_bind("link", "<Leave>", lambda e: self.txt.config(cursor="arrow"))

    # actions
    def _maximize_results(self):
        # toggle between mostly-results and balanced view
        try:
            sash = self.pw.sashpos(0)
            total = self.pw.winfo_height()
            if sash > 455:
                self.pw.sashpos(0, 440)
            else:
                # restore to balanced
                self.pw.sashpos(0, min(510,total-190))
        except Exception:
            pass

    def _bump_font(self, delta: int):
        self._font_size = max(8, min(20, self._font_size + delta))
        self.txt.configure(font=("TkDefaultFont", self._font_size))

    def _select_all(self, cat, val):
        for site, var in self.category_vars[cat].items(): var.set(val)

    def _collect_query(self) -> OSINTQuery:
        return OSINTQuery(
            first=self.var_first.get(), last=self.var_last.get(), username=self.var_user.get(),
            email=self.var_email.get(), phone=self.var_phone.get(), address1=self.var_addr1.get(),
            city=self.var_city.get(), state=self.var_state.get(), zip=self.var_zip.get(), domain=self.var_domain.get()
        )

    def _task_list_for_cat(self, cat) -> List[str]:
        return [site for site, var in self.category_vars[cat].items() if var.get()]

    def _run_category(self, cat):
        sites = self._task_list_for_cat(cat)
        if not sites:
            messagebox.showinfo("Nothing selected", f"Pick at least one site in {cat}."); return
        # pass bypass flag from the header
        self._run_sites(sites, skip_cache=self.bypass_cache_var.get())

    def _run_all(self):
        sites = []
        for _, sites_map in self.category_vars.items():
            for site, var in sites_map.items():
                if var.get(): sites.append(site)
        if not sites:
            messagebox.showinfo("Nothing selected", "Select at least one source in the tabs above.")
            return
        self._run_sites(sites, skip_cache=self.bypass_cache_var.get())

    def engine_guard(self, e: str) -> str:
        return e if e in ENGINES else "DuckDuckGo"

    def _run_sites(self, sites: List[str], skip_cache: bool = False):
        if self._running:
            self.status.set("A search is already running. Wait for it to finish.")
            return
        q = self._collect_query()
        q = OSINTQuery(**{k: v.strip() for k, v in q.to_ordered_dict().items()})
        if not any(value.strip() for value in q.to_ordered_dict().values()):
            messagebox.showinfo("Search details needed", "Enter a name, username, email, phone, or address first.")
            return
        try:
            threads = max(2, min(12, int(self.threads_var.get())))
            timeout = max(3, min(60, int(self.timeout_var.get())))
        except (ValueError, tk.TclError):
            messagebox.showinfo("Invalid settings", "Threads and timeout must be whole numbers.")
            return
        engine = self.engine_guard(self.engine_var.get())
        q.search_fallback = self.fallback_var.get()
        self.cancel_event.clear()
        self._running = True
        self.results = []
        self.coverage_plan = {}
        self.coverage_var.set("Preparing separate lookups for the supplied inputs...")
        self.txt.delete("1.0", "end")
        self.status.set("Searching selected sources...")
        threading.Thread(target=self._background_run_guarded,
                         args=(list(dict.fromkeys(sites)), skip_cache, q, threads, timeout, engine, self.cancel_event),
                         daemon=True).start()

    def _background_run_guarded(self, *args):
        try:
            self._background_run(*args)
        except Exception as exc:
            self.ui_queue.put(("note", f"Search failed: {exc}"))
            self.ui_queue.put(("failed", str(exc)))

    def _background_run(self, sites, skip_cache, q, threads, timeout, engine, cancel=None):
        q.search_engine = engine
        prioritized = [s for s in PRIORITY_SITES if s in sites]
        ordered_sites = prioritized + [s for s in sites if s not in prioritized]
        tasks = plan_lookups(ordered_sites,q,CATS)
        self.ui_queue.put(("coverage_setup",coverage_plan(q,tasks)))
        # if skip cache is False, try load and return cached hits immediately
        if not skip_cache:
            cache_hits = load_cache(q, sites, engine)
            if cache_hits:
                self.ui_queue.put(("note", f"cache: {len(cache_hits)} hits loaded"))
                for h in cache_hits: self.ui_queue.put(("hit", h))
                self.ui_queue.put(("done", len(cache_hits))); return
        else:
            # If we're skipping cache, remove any existing cache so fresh results get saved cleanly
            try:
                cleared = clear_cache_for_query(q)
                if cleared:
                    self.ui_queue.put(("note", "Cache cleared for this query (skip cache requested)"))
            except Exception:
                pass

        total = len(sites)
        self.ui_queue.put(("setup_progress", total))

        results: List[OSINTHit] = []
        remaining={site:sum(task.site==site for task in tasks) for site in ordered_sites}
        has_web=any(task.site in ENGINE_SOURCES for task in tasks)
        web_workers=1
        normal_workers=max(1,threads-web_workers) if has_web else threads
        paused_engines=set()
        def run_lookup(task):
            if task.site in ENGINE_SOURCES:task.query.search_skip_engines=tuple(paused_engines)
            found=_run_site_with_timeout(task.site,task.query,timeout,cancel)
            if task.site in ENGINE_SOURCES:
                paused_engines.update(h.raw['engine'] for h in found if h.raw.get('engine') and h.raw.get('http_status') in (202,403,429))
            return found
        # Independent budgets per input prevent one stalled name/email search
        # from consuming the entire web-search budget for later fields.
        with concurrent.futures.ThreadPoolExecutor(max_workers=normal_workers) as normal, concurrent.futures.ThreadPoolExecutor(max_workers=web_workers) as web:
            future_map={}
            for task in tasks:
                executor=web if task.site in ENGINE_SOURCES else normal
                future_map[executor.submit(run_lookup,task)]=task
            for fut in concurrent.futures.as_completed(future_map):
                task=future_map[fut];site=task.site
                try: hits=fut.result()
                except Exception as exc:
                    hits=[manual_path(site,task.query,SITE_DOMAIN,SITE_URL,CATS,"error",str(exc))]
                if hits and not any(h.raw.get("kind") in ("record","candidate") for h in hits) and any(h.raw.get("kind") in ("manual","error","timeout","not_found","blocked","unavailable") for h in hits):
                    hits[0].raw["search_url"]=dork_url(site,task.query,engine)
                    hits[0].raw["search_engine"]=engine
                for hit in hits:
                    hit.raw.setdefault("source",site)
                    hit.raw.setdefault("checked_at",datetime.now(timezone.utc).isoformat(timespec="seconds"))
                    hit.raw.setdefault("input_fields",list(task.fields))
                    annotate_hit(hit,q)
                    hit.raw["task_id"]=task.task_id
                    hit.raw["coverage_plan"]=coverage_plan(q,tasks)
                    results.append(hit);self.ui_queue.put(("hit",hit))
                remaining[site]-=1
                if remaining[site]==0:self.ui_queue.put(("inc_progress",1))

        if results and any(h.raw.get("kind") in ("record", "candidate") for h in results) and not any(h.raw.get("kind") in ("manual", "error", "timeout", "cancelled", "blocked", "unavailable") for h in results) and not (cancel is not None and cancel.is_set()):
            # Save cache (fresh results). This will create or overwrite the cache file.
            save_cache(q, results, sites, engine)
            self.ui_queue.put(("note", f"Saved cache for this query ({len(results)} rows)"))
        csv_path, json_path, txt_path = save_reports(results)
        self.ui_queue.put(("note", f"Saved CSV: {csv_path}  JSON: {json_path}  TXT: {txt_path}"))

        if not results:
            self.ui_queue.put(("note", "No scraper results returned for selected sites."))
            try: self.ui_queue.put(("note", f"Registered scrapers: {', '.join(sorted(list(PLUG.SCRAPERS.keys())))}"))
            except Exception: pass

        self.ui_queue.put(("cancelled" if cancel is not None and cancel.is_set() else "done", len(results)))

    def _insert_link(self, widget: tk.Text, label: str, url: str):
        start = widget.index("end-1c"); widget.insert("end", label); end = widget.index("end-1c")
        tag = f"link_{start.replace('.', '_')}"; widget.tag_add(tag, start, end)
        P = DARK if self.dark_var.get() else LIGHT
        widget.tag_config(tag, foreground=P["accent"], underline=True)
        widget.tag_bind(tag, "<Button-1>", lambda e, u=url: webbrowser.open_new_tab(u))

    def _matches_filter(self, hit):
        keyword = self.filter_var.get().strip().casefold()
        kind = hit.raw.get("kind", "candidate")
        input_label=self.input_filter_var.get()
        if input_label!="All inputs" and not any(FIELD_LABELS.get(field,field)==input_label for field in set(hit.raw.get('input_fields',('other',)))|set(hit.raw.get('matched_inputs',()))):return False
        return ((self.kind_var.get() in ("All", kind) or (self.kind_var.get()=="Findings" and kind in ("record","candidate")) or (self.kind_var.get()=="Shared evidence" and len(hit.raw.get('matched_inputs',()))>=2)) and
                keyword in " ".join((hit.site, hit.title, hit.snippet, hit.url)).casefold())

    def _render_hit(self, hit):
        kind = hit.raw.get("kind", "candidate")
        labels=", ".join(FIELD_LABELS.get(f,f) for f in hit.raw.get('input_fields',()))
        engine=hit.raw.get('engine')
        if engine:labels+=(" / " if labels else "")+engine+(" fallback" if hit.raw.get('fallback_from') else "")
        detail=(" | "+labels) if labels else ""
        self.txt.insert("end", f"[{kind.upper()} | {hit.site}{detail}] {hit.title}\n{hit.snippet}\n")
        if len(hit.raw.get('matched_inputs',()))>=2:
            self.txt.insert('end','Supplied details found together: '+', '.join(FIELD_LABELS.get(f,f) for f in hit.raw['matched_inputs'])+'. Review the source relationship.\n')
        if hit.url.startswith(("https://", "http://")):
            self._insert_link(self.txt, hit.url, hit.url)
        search_url=hit.raw.get("search_url")
        if search_url:
            self.txt.insert("end", "\n")
            self._insert_link(self.txt, "Search "+hit.raw.get("search_engine","web"),search_url)
        evidence_url=hit.raw.get("source_url")
        if evidence_url and evidence_url!=hit.url:
            self.txt.insert("end", "\nSource: ")
            self._insert_link(self.txt,evidence_url,evidence_url)
        self.txt.insert("end", "\n\n")
        self.txt.see("end")

    def _refresh_results(self):
        if not hasattr(self, "txt"):
            return
        self.txt.delete("1.0", "end")
        for tag in self.txt.tag_names():
            if tag.startswith("link_"):
                self.txt.tag_delete(tag)
        for hit in balanced_findings(self.results):
            if self._matches_filter(hit):
                self._render_hit(hit)
        if self.results and not self.txt.get("1.0","end").strip():
            self.txt.insert("end","No findings match this view. Input coverage above shows whether lookups failed, returned no matches, or have no selected collector. Choose All statuses to inspect each attempt.\n")
        self.txt.yview_moveto(0)

    def _keep_results_visible(self,event):
        # Preserve the divider position unless resizing would hide a usable pane.
        if event.height>600:self._reset_pane_bounds()

    def _reset_pane_bounds(self):
        height=self.pw.winfo_height()
        if height>600:self.pw.sashpos(0,max(440,min(self.pw.sashpos(0),height-190)))

    def _update_coverage(self):
        stats=coverage(self.results,self.coverage_plan,finished=not self._running)
        self.coverage_var.set(" | ".join(row['label']+": "+row['status'] for row in stats.values()) or "No input coverage recorded.")

    def _save_settings(self):
        try:
            selected=[site for group in self.category_vars.values() for site,var in group.items() if var.get()]
            save_settings(os.path.join(os.path.dirname(__file__), "settings.json"), self.threads_var.get(),
                          self.timeout_var.get(), self.dark_var.get(), selected, self.engine_guard(self.engine_var.get()), self.fallback_var.get())
            self.status.set("Settings saved. Search details and API keys are not included.")
        except (OSError, ValueError, tk.TclError) as exc:
            messagebox.showerror("Settings", str(exc))

    def _load_settings(self):
        try:
            values=load_settings(os.path.join(os.path.dirname(__file__), "settings.json"),
                                 {s for group in CATS.values() for s in group})
            self.threads_var.set(values['workers']); self.timeout_var.set(values['timeout'])
            self.engine_var.set(self.engine_guard(values.get('engine', 'DuckDuckGo')))
            self.fallback_var.set(values.get('search_fallback',True))
            self.dark_var.set(values['dark']); self._apply_theme(values['dark'])
            for group in self.category_vars.values():
                for site,var in group.items(): var.set(site in values['selected'])
            self.status.set("Settings loaded.")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            messagebox.showerror("Settings", str(exc))

    def _export_graph(self):
        if not any(h.raw.get('kind','candidate') in ('record','candidate') for h in self.results):
            messagebox.showinfo('No findings to graph','No records or candidates were retrieved. Choose All in the results filter to inspect source failures and manual paths; Save reports preserves those details.')
            return
        path=os.path.join(REPORTS_DIR, "osint_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f") + ".graphml")
        try:
            export_graphml(self.results, path)
            messagebox.showinfo("Graph exported", "Findings and observed relationships exported; manual links and source failures are excluded:\n" + path)
        except OSError as exc:
            messagebox.showerror("Graph export", str(exc))

    def _process_ui_queue(self):
        while not self.ui_queue.empty():
            t, payload = self.ui_queue.get()
            if t == "hit":
                h: OSINTHit = payload
                self.results.append(h)
                self._update_coverage()
                if self._matches_filter(h):
                    self._render_hit(h)
            elif t == "coverage_setup":
                self.coverage_plan=payload
                self._update_coverage()
            elif t == "note":
                self.status.set(payload)
            elif t == "setup_progress":
                self.progress["maximum"] = payload; self.progress["value"] = 0
            elif t == "inc_progress":
                self.progress["value"] = min(self.progress["maximum"], self.progress["value"] + int(payload))
            elif t == "failed":
                self._running = False
                self.status.set(f"Search failed: {payload}")
                self._update_coverage()
            elif t in ("done", "cancelled"):
                self._running = False
                self._update_coverage()
                self._refresh_results()
                counts = {kind:sum(h.raw.get("kind","candidate")==kind for h in self.results) for kind in ("record","candidate","context")}
                issues = len(self.results)-sum(counts.values())
                self.status.set(f"{t}: {counts['record']} records, {counts['candidate']} candidates, {counts['context']} context; {issues} source issues/paths (All shows details).")
                self.progress["value"] = self.progress["maximum"]
        self._queue_after_id = self.after(200, self._process_ui_queue)

    def destroy(self):
        self.cancel_event.set()
        for attr in ("_queue_after_id", "_sash_after_id"):
            callback = getattr(self, attr, None)
            if callback:
                try:
                    self.after_cancel(callback)
                except tk.TclError:
                    pass
        super().destroy()

    def _close(self):
        self.destroy()

    def _cancel(self):
        if self._running:
            self.cancel_event.set()
            self.status.set("Stopping searches and preserving partial results...")

    def _save_now(self):
        csv_path, json_path, txt_path = save_reports(self.results)
        html_path=os.path.splitext(json_path)[0]+'.html'
        messagebox.showinfo("Saved", f"Readable report: {html_path}\nCSV: {csv_path}\nJSON: {json_path}\nTXT: {txt_path}")

    def _about(self):
        messagebox.showinfo("About / Legal",
            f"{APP_NAME}\n"
            "- Scrape-first with search fallback.\n"
            "- Timeouts and thread pool added for faster runs.\n"
            "- Toggleable dark mode.\n"
            "- Draggable splitter and font zoom for results pane.\n"
            "- Educational, lawful OSINT only. Respect site ToS & robots.\n"
            "- Configure API keys in environment (e.g., HIBP_API_KEY).")

    def _quick_username_pack(self):
        u = self.var_user.get().strip()
        if not u:
            messagebox.showinfo("No username", "Enter a username first.")
            return
        self._run_sites(["Username Pack (direct)"], skip_cache=True)

    def _clear_cache_current(self):
        q = self._collect_query()
        ok = clear_cache_for_query(q)
        if ok:
            self.status.set("cache cleared for this query")
            messagebox.showinfo("Cache", "Cleared cache for this query.")
        else:
            messagebox.showinfo("Cache", "No cache file found for this query.")

if __name__ == "__main__":
    App().mainloop()
