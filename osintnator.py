#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, csv, json, time, queue, webbrowser, hashlib
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import List, Dict, Any, Tuple
from urllib.parse import quote_plus
import concurrent.futures
import threading

import datasets as DATASETS

import tkinter as tk
from tkinter import ttk, messagebox

import scrapers as PLUG

APP_NAME = "Osintnator"
REPORTS_DIR = "reports"
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
    "bg":        "#1e1e1e",
    "panel":     "#252526",
    "sunken":    "#2d2d2d",
    "fg":        "#e6e6e6",
    "muted":     "#9aa0a6",
    "accent":    "#00d1d1",
    "entrybg":   "#2b2b2b",
    "entryfg":   "#eaeaea",
    "entrybd":   "#3a3a3a",
    "focus":     "#007acc",
    "tab_bg":    "#252526",
    "tab_sel":   "#2f2f2f",
    "pb_trough": "#2a2a2a",
    "pb_bar":    "#00d1d1",
}
LIGHT = {
    "bg":        "#f5f6f7",
    "panel":     "#ffffff",
    "sunken":    "#f0f0f0",
    "fg":        "#202124",
    "muted":     "#5f6368",
    "accent":    "#0b84ff",
    "entrybg":   "#ffffff",
    "entryfg":   "#202124",
    "entrybd":   "#d0d7de",
    "focus":     "#0b84ff",
    "tab_bg":    "#f0f0f0",
    "tab_sel":   "#ffffff",
    "pb_trough": "#e9ecef",
    "pb_bar":    "#0b84ff",
}

ENGINES = {
    "DuckDuckGo": "https://duckduckgo.com/?q=",
    "Google":     "https://www.google.com/search?q=",
    "Brave":      "https://search.brave.com/search?q=",
    "Bing":       "https://www.bing.com/search?q=",
    "Yandex":     "https://yandex.com/search/?text=",
    "Baidu":      "https://www.baidu.com/s?wd=",
    "ZoomEye":    "https://www.zoomeye.ai/search?q=",
    "DogPile":    "https://www.dogpile.com/serp?q=",
}

# === Catalog ===
CATS = {
    "People Search": [
        "FastPeopleSearch","TruePeopleSearch","TruePeopleSearch.io","FastBackgroundCheck","That’sThem",
        "FamilyTreeNow","ZabaSearch","Radaris","NeighborReport","Nuwber",
    ],
    "Reverse Phone / Address": [
        "Whitepages (Free Search)","411.com","AnyWho","WhoCallsMe","SpyDialer",
        "CallerName","OKCaller","Sync.me","NumLookup","ReversePhoneLookup",
    ],
    "Property Records & Accessor": [
        "Zillow","Rehold","NeighborWho","HomeFacts","Melissa Address Lookup",
        "PropertyShark","Netronline Public Records","PublicRecords360","AddressSearch.com","HOMES.com",
    ],
    "Court/Criminal/Gov": [
        "PACER (federal index)","VINELink","BOP Inmate Locator","State/County Court Directory","InmateAid",
        "State Prison Inmate Locators","Offender Search","Arrests.org","Mugshots.com","BustedMugshots",
    ],
    "Specialized / Extra": [
        "PeekYou","Pipl (preview)","Social Searcher","Username Search","instant username search","IDcrawl","Username Pack (direct)","Hunter.io",
        "EmailHippo","HaveIBeenPwned","BlackBookOnline","DataAxle Reference","USPhoneBook",
    ],
    "Worldwide": [
        "SearchSystems", "GestolenObjectenRegister", "RDW-OVI", "PeopleSearch AU",
        "QKenteken", "KVK Zoeken", "Sportradar", "Weibo", "HKU DataHub", "OpenStreetMap",
    ],
}

# Primary domain roots (used for dork queries)
SITE_DOMAIN = {
    "FastPeopleSearch":"fastpeoplesearch.com","TruePeopleSearch":"truepeoplesearch.com","TruePeopleSearch.io":"truepeoplesearch.io",
    "FastBackgroundCheck":"fastbackgroundcheck.com","That’sThem":"thatsthem.com","FamilyTreeNow":"familytreenow.com","ZabaSearch":"zabasearch.com",
    "Radaris":"radaris.com","NeighborReport":None,"Nuwber":"nuwber.com",
    "Whitepages (Free Search)":"whitepages.com","411.com":"411.com","AnyWho":"anywho.com","WhoCallsMe":"whocallsme.com",
    "SpyDialer":"spydialer.com","CallerName":None,"OKCaller":"okcaller.com","Sync.me":"sync.me","NumLookup":"numlookup.com","ReversePhoneLookup":"reversephonelookup.com",
    "Zillow":"zillow.com","Rehold":"rehold.com","NeighborWho":"neighborwho.com","HomeFacts":"homefacts.com","Melissa Address Lookup":"melissa.com",
    "PropertyShark":"propertyshark.com","Netronline Public Records":"netronline.com","PublicRecords360":"publicrecords360.com","AddressSearch.com":"addresssearch.com","HOMES.com":"homes.com",
    "PACER (federal index)":"pacer.uscourts.gov","VINELink":"vinelink.vineapps.com","BOP Inmate Locator":"bop.gov","State/County Court Directory":None,
    "InmateAid":"inmateaid.com","State Prison Inmate Locators":None,"Offender Search":"nsopw.gov","Arrests.org":"arrests.org","Mugshots.com":"mugshots.com","BustedMugshots":"bustedmugshots.com",
    "PeekYou":"peekyou.com","Pipl (preview)":"pipl.com","Social Searcher":"social-searcher.com","Username Search":"usersearch.org","instant username search":"instantusername.com",
    "IDcrawl":"idcrawl.com/username-search","Username Pack (direct)": None,"Hunter.io":"hunter.io",
    "EmailHippo":"emailhippo.com","HaveIBeenPwned":"haveibeenpwned.com","BlackBookOnline":"blackbookonline.info","DataAxle Reference":"referenceusa.com","USPhoneBook":"usphonebook.com",
    "SearchSystems":"searchsystems.net","GestolenObjectenRegister":"gestolenobjectenregister.nl","RDW-OVI":"ovi.rdw.nl","PeopleSearch AU":"peoplesearch.com.au",
    "QKenteken":"qenteken.nl","KVK Zoeken":"kvk.nl","Sportradar":"sportradar.com","Weibo":"weibo.com","HKU DataHub":"datahub.hku.hk","OpenStreetMap":"openstreetmap.org",
}

SITE_URL = {
    "SearchSystems": "https://publicrecords.searchsystems.net/",
    "GestolenObjectenRegister": "https://gestolenobjectenregister.nl/",
    "RDW-OVI": "https://ovi.rdw.nl/",
    "PeopleSearch AU": "https://peoplesearch.com.au/",
    "QKenteken": "https://www.qenteken.nl/",
    "KVK Zoeken": "https://www.kvk.nl/zoeken/",
    "Sportradar": "https://sportradar.com/",
    "Weibo": "https://s.weibo.com/",
    "HKU DataHub": "https://datahub.hku.hk/",
    "OpenStreetMap": "https://www.openstreetmap.org/",
}

PRIORITY_SITES = ["Username Pack (direct)", "FamilyTreeNow", "WhoCallsMe", "HaveIBeenPwned"]

# ---------- Models ----------
@dataclass
class OSINTQuery:
    first: str = ""; last: str = ""; username: str = ""; email: str = ""; phone: str = ""
    address1: str = ""; city: str = ""; state: str = ""; zip: str = ""
    @property
    def full_name(self) -> str:
        parts = [self.first.strip(), self.last.strip()]
        return " ".join([p for p in parts if p])
    def to_ordered_dict(self) -> Dict[str,str]:
        return {
            "first": self.first or "","last": self.last or "",
            "username": self.username or "","email": self.email or "",
            "phone": self.phone or "","address1": self.address1 or "",
            "city": self.city or "","state": self.state or "","zip": self.zip or ""
        }

@dataclass
class OSINTHit:
    site: str; title: str; snippet: str; url: str; raw: Dict[str, Any]

# ---------- Helpers ----------
def digits_only(s: str) -> str: return "".join(c for c in s if c.isdigit())

def site_base_url(site: str) -> str | None:
    if site in SITE_URL: return SITE_URL[site]
    dom = SITE_DOMAIN.get(site); return f"https://{dom}" if dom else None

def dork_url(site_label: str, q: OSINTQuery, engine: str) -> str:
    """
    Build a site-specific dork. For property sites prefer address tokens;
    for reverse-phone sites prefer phone tokens; otherwise use name/username/email.
    """
    domain = SITE_DOMAIN.get(site_label)
    toks = []

    # helpers to check membership quickly
    prop_sites = set(CATS.get("Property Records & Accessor", []))
    rev_sites  = set(CATS.get("Reverse Phone / Address", []))

    # Property sites: prefer address -> name -> phone -> email -> username
    if site_label in prop_sites:
        if q.address1: toks.append(f"\"{q.address1}\"")
        if q.city:     toks.append(q.city)
        if q.state:    toks.append(q.state)
        if q.zip:      toks.append(q.zip)
        if q.full_name: toks.append(f"\"{q.full_name}\"")
        if q.phone:    toks.append(digits_only(q.phone))
        if q.email:    toks.append(q.email)
        if q.username: toks.append(q.username)

    # Reverse phone/address sites: prefer phone -> name -> address -> email
    elif site_label in rev_sites:
        if q.phone:    toks.append(digits_only(q.phone))
        if q.full_name: toks.append(f"\"{q.full_name}\"")
        if q.address1: toks.append(f"\"{q.address1}\"")
        if q.city:     toks.append(q.city)
        if q.state:    toks.append(q.state)
        if q.zip:      toks.append(q.zip)
        if q.email:    toks.append(q.email)
        if q.username: toks.append(q.username)

    # Default: name, username, email, phone, address
    else:
        if q.full_name: toks.append(f"\"{q.full_name}\"")
        if q.username:  toks.append(q.username)
        if q.email:     toks.append(q.email)
        if q.phone:     toks.append(digits_only(q.phone))
        if q.address1:  toks.append(f"\"{q.address1}\"")
        if q.city:      toks.append(q.city)
        if q.state:     toks.append(q.state)
        if q.zip:       toks.append(q.zip)

    parts = []
    if domain: parts.append(f"site:{domain}")
    parts.extend(toks)
    query_str = " ".join(parts) if parts else (domain or site_label)
    base = ENGINES.get(engine, ENGINES["DuckDuckGo"])
    return base + quote_plus(query_str)

def cache_key_for_query(q: OSINTQuery) -> str:
    payload = json.dumps(q.to_ordered_dict(), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

# NEW helper: canonical cache path
def cache_path_for_query(q: OSINTQuery) -> str:
    return os.path.join(CACHE_DIR, f"{cache_key_for_query(q)}.json")

def load_cache(q: OSINTQuery) -> List[OSINTHit]:
    path = cache_path_for_query(q)
    if not os.path.exists(path): return []
    try:
        with open(path, "r", encoding="utf-8") as f: data = json.load(f)
        return [OSINTHit(**h) for h in data]
    except Exception: return []

def save_cache(q: OSINTQuery, hits: List[OSINTHit]) -> str:
    path = cache_path_for_query(q)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump([asdict(h) for h in hits], f, ensure_ascii=False, indent=2)
        return path
    except Exception: return ""

# NEW helper: clear cache file for a specific query
def clear_cache_for_query(q: OSINTQuery) -> bool:
    p = cache_path_for_query(q)
    try:
        if os.path.exists(p):
            os.remove(p)
            return True
    except Exception:
        pass
    return False

def _report_paths(ts: str) -> Tuple[str, str, str]:
    return (
        os.path.join(REPORTS_DIR, f"osint_{ts}.csv"),
        os.path.join(REPORTS_DIR, f"osint_{ts}.json"),
        os.path.join(REPORTS_DIR, f"osint_{ts}.txt"),
    )

def save_reports(hits: List[OSINTHit]) -> Tuple[str, str, str]:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    csv_path, json_path, txt_path = _report_paths(ts)

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["site","title","snippet","url"])
        for h in hits: w.writerow([h.site, h.title, h.snippet, h.url])

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump([asdict(h) for h in hits], f, ensure_ascii=False, indent=2)

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"{APP_NAME} report — {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n")
        f.write("="*72 + "\n")
        if not hits: f.write("(no results)\n")
        for i, h in enumerate(hits, 1):
            f.write(f"[{i}] {h.site}\nTitle:   {h.title}\nURL:     {h.url}\n")
            snip = (h.snippet or "").replace("\n", " ").strip()
            f.write(f"Snippet: {snip}\n" + "-"*72 + "\n")
    return csv_path, json_path, txt_path

def _run_site_with_timeout(site: str, q: OSINTQuery, timeout: int) -> List[OSINTHit]:
    sess = PLUG.get_session()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as tmp_ex:
        fut = tmp_ex.submit(PLUG.run_scraper, sess, site, q)
        try:
            hits = fut.result(timeout=timeout); return hits or []
        except concurrent.futures.TimeoutError: raise
        except NotImplementedError: return []
        except Exception: return []

# ---------- GUI ----------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME); self.geometry("1200x900")
        self.engine_var = tk.StringVar(value="DuckDuckGo")
        self.threads_var = tk.IntVar(value=16)
        self.timeout_var = tk.IntVar(value=12)
        self.category_vars: Dict[str, Dict[str, tk.BooleanVar]] = {}
        self.results: List[OSINTHit] = []
        self.ui_queue = queue.Queue()
        self._font_size = 10  # results font size

        self._header()

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
        self._footer()

        self._apply_theme(True)
        self.after(200, self._process_ui_queue)

        # allow Ctrl/Cmd + / - to zoom results text
        self.bind_all("<Control-plus>", lambda e: self._bump_font(1))
        self.bind_all("<Control-KP_Add>", lambda e: self._bump_font(1))
        self.bind_all("<Control-minus>", lambda e: self._bump_font(-1))
        self.bind_all("<Control-KP_Subtract>", lambda e: self._bump_font(-1))

    # UI bits
    def _header(self):
        bar = ttk.Frame(self); bar.pack(fill="x", padx=10, pady=(10,6))
        ttk.Label(bar, text=APP_NAME, font=("Courier New", 18, "bold")).pack(side="left")
        right = ttk.Frame(bar); right.pack(side="right")
        self.dark_var = tk.BooleanVar(value=True)

        # NEW: bypass cache flag
        self.bypass_cache_var = tk.BooleanVar(value=False)

        ttk.Button(right, text="Max Results", command=self._maximize_results).pack(side="right", padx=(8,0))
        ttk.Button(right, text="Quick Username Pack", command=self._quick_username_pack).pack(side="right", padx=(8,0))
        ttk.Checkbutton(right, text="Dark", variable=self.dark_var, command=self._toggle_dark).pack(side="right", padx=(8,0))

        # NEW: Bypass cache toggle and clear cache button
        ttk.Checkbutton(right, text="Bypass cache", variable=self.bypass_cache_var).pack(side="right", padx=(8,0))
        ttk.Button(right, text="Clear Cache (this query)", command=self._clear_cache_current).pack(side="right", padx=(8,0))

        ttk.Label(right, text="Engine:").pack(side="left")
        ttk.Combobox(right, textvariable=self.engine_var, values=list(ENGINES.keys()), state="readonly", width=14).pack(side="left", padx=(6,0))
        ttk.Label(right, text="Threads:").pack(side="left", padx=(10,0))
        ttk.Spinbox(right, from_=2, to=40, textvariable=self.threads_var, width=4).pack(side="left")
        ttk.Label(right, text="Timeouts:").pack(side="left", padx=(10,0))
        ttk.Spinbox(right, from_=3, to=60, textvariable=self.timeout_var, width=4).pack(side="left")

    def _banner(self, parent):
        frame = ttk.Frame(parent); frame.pack(fill="x", pady=(0,6))
        self.banner_txt = tk.Text(frame, height=5, bd=0, highlightthickness=0)
        self.banner_txt.pack(fill="x")
        self.banner_txt.insert("1.0", BANNER)
        self.banner_txt.configure(state="disabled", font=("Courier New", 10, "bold"))

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

    def _field(self, parent, r, c, label, var, width=28):
        f = ttk.Frame(parent); f.grid(row=r, column=c, padx=6, pady=4, sticky="ew")
        ttk.Label(f, text=label).pack(anchor="w"); ttk.Entry(f, textvariable=var, width=width).pack(fill="x")

    def _tabs(self, parent):
        nb = ttk.Notebook(parent); nb.pack(fill="both", expand=True, pady=6)
        self.category_vars.clear()
        for cat, sites in CATS.items():
            tab = ttk.Frame(nb); nb.add(tab, text=cat)
            self._cat_tab(tab, cat, sites)

    def _cat_tab(self, parent, cat, sites):
        bar = ttk.Frame(parent); bar.pack(fill="x", pady=(8,4))
        ttk.Button(bar, text="Select all", command=lambda c=cat: self._select_all(c, True)).pack(side="left")
        ttk.Button(bar, text="Clear", command=lambda c=cat: self._select_all(c, False)).pack(side="left", padx=(6,0))
        ttk.Button(bar, text=f"Run selected ({cat})", command=lambda c=cat: self._run_category(c)).pack(side="right")

        self.category_vars[cat] = {}
        cols = ttk.Frame(parent); cols.pack(fill="both", expand=True)
        left = ttk.Frame(cols); left.pack(side="left", fill="both", expand=True, padx=(0,8))
        right= ttk.Frame(cols); right.pack(side="left", fill="both", expand=True)
        half = (len(sites)+1)//2
        for i, site in enumerate(sites):
            default_sel = (i < 6) or (site == "Username Pack (direct)")
            var = tk.BooleanVar(value=default_sel)
            ttk.Checkbutton(left if i<half else right, text=site, variable=var).pack(anchor="w", pady=2)
            self.category_vars[cat][site] = var

    def _result_area(self, parent):
        # results pane is larger by default and fully resizable
        box = ttk.Frame(parent); box.pack(fill="both", expand=True)
        # toolbar for the results area
        tbar = ttk.Frame(box); tbar.pack(fill="x", pady=(0,6))
        ttk.Label(tbar, text="Results").pack(side="left")
        ttk.Button(tbar, text="A–", command=lambda: self._bump_font(-1)).pack(side="right", padx=4)
        ttk.Button(tbar, text="A+", command=lambda: self._bump_font(1)).pack(side="right")

        # scrolled text
        sc = ttk.Frame(box); sc.pack(fill="both", expand=True)
        self.txt_scroll = ttk.Scrollbar(sc, orient="vertical")
        self.txt = tk.Text(sc, height=22, wrap="word", bd=0, highlightthickness=0, yscrollcommand=self.txt_scroll.set)
        self.txt_scroll.config(command=self.txt.yview)
        self.txt.pack(side="left", fill="both", expand=True)
        self.txt_scroll.pack(side="right", fill="y")
        self.txt.configure(font=("Courier New", self._font_size))

        self.status = tk.StringVar(value="ready")
        self.status_lbl = ttk.Label(parent, textvariable=self.status)
        self.status_lbl.pack(anchor="w", pady=(6,6))
        self.progress = ttk.Progressbar(parent, orient="horizontal", mode="determinate")
        self.progress.pack(fill="x")

    def _footer(self):
        bar = ttk.Frame(self); bar.pack(fill="x", padx=10, pady=(6,12))
        ttk.Button(bar, text="Run EVERYTHING selected", command=self._run_all).pack(side="left")
        ttk.Button(bar, text="Save CSV+JSON+TXT", command=self._save_now).pack(side="left", padx=(8,0))
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
        style.configure("Horizontal.TProgressbar", troughcolor=P["pb_trough"], background=P["pb_bar"])

        self.status_lbl.configure(foreground=P["muted"])
        self._style_text_widgets(dark)


    def _style_text_widgets(self, dark: bool):
        P = DARK if dark else LIGHT
        self.banner_txt.configure(bg=P["bg"], fg=P["accent"], insertbackground=P["fg"])
        self.txt.configure(bg=P["bg"], fg=P["fg"], insertbackground=P["fg"])
        self.txt.tag_configure("link", foreground=P["accent"], underline=True)
        self.txt.tag_bind("link", "<Enter>", lambda e: self.txt.config(cursor="hand2"))
        self.txt.tag_bind("link", "<Leave>", lambda e: self.txt.config(cursor="arrow"))

    # actions
    def _maximize_results(self):
        # toggle between mostly-results and balanced view
        try:
            sash = self.pw.sashpos(0)
            total = self.pw.winfo_height()
            if sash > total * 0.35:
                # collapse top pane
                self.pw.sashpos(0, 80)
            else:
                # restore to balanced
                self.pw.sashpos(0, int(total * 0.45))
        except Exception:
            pass

    def _bump_font(self, delta: int):
        self._font_size = max(8, min(20, self._font_size + delta))
        self.txt.configure(font=("Courier New", self._font_size))

    def _select_all(self, cat, val):
        for site, var in self.category_vars[cat].items(): var.set(val)

    def _collect_query(self) -> OSINTQuery:
        return OSINTQuery(
            first=self.var_first.get(), last=self.var_last.get(), username=self.var_user.get(),
            email=self.var_email.get(), phone=self.var_phone.get(), address1=self.var_addr1.get(),
            city=self.var_city.get(), state=self.var_state.get(), zip=self.var_zip.get()
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
        sites, any_sel = [], False
        for _, sites_map in self.category_vars.items():
            for site, var in sites_map.items():
                if var.get(): sites.append(site); any_sel = True
        if not any_sel:
            if not messagebox.askyesno("Confirm", "Open ALL sites for this query?"): return
            for _, s in CATS.items(): sites.extend(s)
        self._run_sites(sites, skip_cache=self.bypass_cache_var.get())

    def engine_guard(self, e: str) -> str:
        return e if e in ENGINES else "DuckDuckGo"

    def _run_sites(self, sites: List[str], skip_cache: bool = False):
        # fire-and-forget background runner
        t = threading.Thread(target=self._background_run, args=(sites, skip_cache), daemon=True); t.start()

    def _background_run(self, sites: List[str], skip_cache: bool):
        q = self._collect_query()

        # if skip cache is False, try load and return cached hits immediately
        if not skip_cache:
            cache_hits = load_cache(q)
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
        threads = max(2, min(40, int(self.threads_var.get())))
        timeout = max(3, int(self.timeout_var.get()))
        engine = self.engine_guard(self.engine_var.get())

        prioritized = [s for s in PRIORITY_SITES if s in sites]
        remaining = [s for s in sites if s not in prioritized]
        ordered_sites = prioritized + remaining

        results: List[OSINTHit] = []

        # --- NEW: run public dataset checks first, per-site with tailored payloads ---
        sites_to_scrape = list(ordered_sites)  # default: scrape everything
        self.ui_queue.put(("note", "Running public dataset lookups first..."))

        # build quick sets for categorization
        prop_sites = set(CATS.get("Property Records & Accessor", []))
        rev_sites = set(CATS.get("Reverse Phone / Address", []))

        satisfied_sites = set()
        results_from_datasets = []

        # Build token set from the GUI inputs (only tokens we care about)
        token_candidates = []
        if q.full_name:
            # include the full name and also first/last separately
            token_candidates.append(q.full_name.lower())
            if q.first: token_candidates.append(q.first.lower())
            if q.last: token_candidates.append(q.last.lower())
        if q.username: token_candidates.append(q.username.lower())
        if q.email: token_candidates.append(q.email.lower())
        if q.phone:
            p_digits = digits_only(q.phone)
            if p_digits: token_candidates.append(p_digits)
        if q.address1: token_candidates.append(q.address1.lower())
        if q.city: token_candidates.append(q.city.lower())
        if q.state: token_candidates.append(q.state.lower())
        if q.zip: token_candidates.append(q.zip.lower())

        # dedupe tokens
        tokens = [t for i, t in enumerate(token_candidates) if t and t not in token_candidates[:i]]
        # safety: if there are no tokens at all, don't call datasets (no user inputs)
        call_datasets = len(tokens) > 0

        # Query each site with a tailored payload (address-first for property sites, etc.)
        for s in ordered_sites:
            # Do not pass the site's domain to the datasets API — we want datasets to search only user input.
            site_entry = {"label": s}

            # build a per-site qdict tailored to the site's expected fields
            if s in prop_sites:
                site_qdict = {
                    "address1": q.address1 or "",
                    "city": q.city or "",
                    "state": q.state or "",
                    "zip": q.zip or "",
                    "first": q.first or "",
                    "last": q.last or ""
                }
            elif s in rev_sites:
                site_qdict = {
                    "phone": q.phone or "",
                    "first": q.first or "",
                    "last": q.last or "",
                    "address1": q.address1 or ""
                }
            else:
                site_qdict = q.to_ordered_dict()

            if not call_datasets:
                # no user input to search for — skip datasets for this run
                self.ui_queue.put(("note", f"Skipping datasets lookup for {s} (no user tokens present)"))
                continue

            # try a single-site API if available, otherwise fallback to batch API
            try:
                if hasattr(DATASETS, "search_site_for_query"):
                    ds_hits = DATASETS.search_site_for_query(site_entry, site_qdict) or []
                else:
                    # some implementations expect a batch call; pass the single-entry list and the qdict
                    ds_hits = DATASETS.search_sites_for_query([site_entry], site_qdict) or []
            except Exception as e:
                ds_hits = []
                self.ui_queue.put(("note", f"[!] datasets lookup failed for {s}: {str(e)[:200]}"))

            # Process returned dataset hits (if any). Only accept hits that include at least one user token.
            for dh in ds_hits:
                # dh expected: {'site': ..., 'title':..., 'snippet':..., 'url':..., 'raw': {...}}
                title = (dh.get("title", "") or "").lower()
                snippet = (dh.get("snippet", "") or "").lower()
                url = (dh.get("url", "") or "").lower()
                raw_text = json.dumps(dh.get("raw", {}) or {}).lower()

                combined = " ".join([title, snippet, url, raw_text])

                # check whether any token appears in the dataset hit
                matched = False
                for tok in tokens:
                    if tok and tok in combined:
                        matched = True
                        break

                if not matched:
                    # skip irrelevant dataset hits (e.g., crt.sh certs for the lookup site)
                    self.ui_queue.put(("note", f"[datasets skip] {s}: hit didn't match query tokens -> {dh.get('url','')[:200]}"))
                    continue

                site_label = dh.get("site", s).split(" (")[0]
                try:
                    hit = OSINTHit(site_label, dh.get("title",""), dh.get("snippet",""), dh.get("url",""), dh.get("raw", {}))
                    results_from_datasets.append(hit)
                    self.ui_queue.put(("hit", hit))
                    satisfied_sites.add(site_label)
                except Exception:
                    self.ui_queue.put(("note", f"[dataset] {dh.get('title')} -> {dh.get('url')}"))

        # If datasets returned anything, remove satisfied sites from the live-scrape list
        if satisfied_sites:
            sites_to_scrape = [s for s in ordered_sites if s not in satisfied_sites]
            self.ui_queue.put(("note", f"Datasets satisfied: {', '.join(sorted(list(satisfied_sites))) }"))
        else:
            self.ui_queue.put(("note", "No dataset hits found — will proceed to scrapers."))

        # merge dataset results into main results list
        for r in results_from_datasets:
            results.append(r)

        # If there are no sites left to scrape (datasets-only), skip the scraper pool
        if not sites_to_scrape:
            self.ui_queue.put(("note", "All sites satisfied by datasets — skipping live scrapers."))
            # Save cache and reports from 'results' so UI persists findings
            if results:
                save_cache(q, results)
                self.ui_queue.put(("note", f"Saved cache for this query ({len(results)} rows)"))
            csv_path, json_path, txt_path = save_reports(results)
            self.ui_queue.put(("note", f"Saved CSV: {csv_path}  JSON: {json_path}  TXT: {txt_path}"))
            self.ui_queue.put(("done", len(results))); return

        # --- continue with live scrapers, but only for remaining sites ---
        with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as ex:
            # Create futures, but allow a larger timeout for Username Pack (direct)
            future_map = {}
            for site in sites_to_scrape:
                site_timeout = timeout
                if site == "Username Pack (direct)":
                    site_timeout = max(timeout, 20)  # give username pack more breathing room
                future = ex.submit(_run_site_with_timeout, site, q, site_timeout)
                future_map[future] = (site, site_timeout)

            for fut in concurrent.futures.as_completed(list(future_map.keys())):
                site, used_timeout = future_map[fut]
                try:
                    hits = fut.result()
                    if hits:
                        self.ui_queue.put(("note", f"[+] {site}: {len(hits)} hit(s)"))
                        for h in hits:
                            results.append(h); self.ui_queue.put(("hit", h))
                    else:
                        home = site_base_url(site)
                        dork = dork_url(site, q, engine)
                        if home:
                            results.append(OSINTHit(site, f"{site} (open site)", "No scraper results — open site.", home, {"fallback": "home"}))
                            self.ui_queue.put(("hit", results[-1]))
                        results.append(OSINTHit(site, f"{site} (search dork)", "No scraper results — try search.", dork, {"fallback": "dork"}))
                        self.ui_queue.put(("hit", results[-1]))
                        self.ui_queue.put(("note", f"[~] {site}: provided links (site + dork)"))
                except concurrent.futures.TimeoutError:
                    home = site_base_url(site)
                    dork = dork_url(site, q, engine)
                    if home:
                        h = OSINTHit(site, f"{site} (timeout→open site)", f"Timed out after {used_timeout}s", home, {"timeout": True, "fallback": "home"})
                        results.append(h); self.ui_queue.put(("hit", h))
                    h = OSINTHit(site, f"{site} (timeout→dork)", f"Timed out after {used_timeout}s", dork, {"timeout": True, "fallback": "dork"})
                    results.append(h); self.ui_queue.put(("hit", h))
                    self.ui_queue.put(("note", f"[!] {site}: timeout, provided links"))
                except Exception as e:
                    home = site_base_url(site)
                    dork = dork_url(site, q, engine)
                    if home:
                        h = OSINTHit(site, f"{site} (error→open site)", str(e)[:300], home, {"error": str(e), "fallback": "home"})
                        results.append(h); self.ui_queue.put(("hit", h))
                    h = OSINTHit(site, f"{site} (error→dork)", str(e)[:300], dork, {"error": str(e), "fallback": "dork"})
                    results.append(h); self.ui_queue.put(("hit", h))
                    self.ui_queue.put(("note", f"[!] {site}: error, provided links"))
                self.ui_queue.put(("inc_progress", 1))

        if results:
            # Save cache (fresh results). This will create or overwrite the cache file.
            save_cache(q, results)
            self.ui_queue.put(("note", f"Saved cache for this query ({len(results)} rows)"))
        csv_path, json_path, txt_path = save_reports(results)
        self.ui_queue.put(("note", f"Saved CSV: {csv_path}  JSON: {json_path}  TXT: {txt_path}"))

        if not results:
            self.ui_queue.put(("note", "No scraper results returned for selected sites."))
            try: self.ui_queue.put(("note", f"Registered scrapers: {', '.join(sorted(list(PLUG.SCRAPERS.keys())))}"))
            except Exception: pass

        self.ui_queue.put(("done", len(results)))

    def _insert_link(self, widget: tk.Text, label: str, url: str):
        start = widget.index("end-1c"); widget.insert("end", label); end = widget.index("end-1c")
        tag = f"link_{start.replace('.', '_')}"; widget.tag_add(tag, start, end)
        P = DARK if self.dark_var.get() else LIGHT
        widget.tag_config(tag, foreground=P["accent"], underline=True)
        widget.tag_bind(tag, "<Button-1>", lambda e, u=url: webbrowser.open_new_tab(u))

    def _process_ui_queue(self):
        while not self.ui_queue.empty():
            t, payload = self.ui_queue.get()
            if t == "hit":
                h: OSINTHit = payload
                self.results.append(h)
                self.txt.insert("end", f"[{h.site}] {h.title}\n{h.snippet}\n")
                self._insert_link(self.txt, h.url, h.url)
                self.txt.insert("end", "\n\n"); self.txt.see("end")
            elif t == "note":
                self.status.set(payload); self.txt.insert("end", payload + "\n"); self.txt.see("end")
            elif t == "setup_progress":
                self.progress["maximum"] = payload; self.progress["value"] = 0
            elif t == "inc_progress":
                self.progress["value"] = min(self.progress["maximum"], self.progress["value"] + int(payload))
            elif t == "done":
                self.status.set(f"done. {payload} result rows ready."); self.progress["value"] = self.progress["maximum"]
        self.after(200, self._process_ui_queue)

    def _save_now(self):
        csv_path, json_path, txt_path = save_reports(self.results)
        messagebox.showinfo("Saved", f"CSV: {csv_path}\nJSON: {json_path}\nTXT: {txt_path}")

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
        # always skip cache for quick username lookup so user sees fresh results
        # clear previous results and show immediate feedback so user knows it's started
        self.results = []
        self.txt.delete("1.0", "end")
        self.status.set(f"running username pack for @{u} (bypassing cache)...")
        # call run_sites but force skip_cache True
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
