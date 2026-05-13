#!/usr/bin/env python3
"""
update_food.py
--------------
Scrape les spéciaux hebdomadaires des épiceries québécoises (Super C, Maxi, Metro, IGA)
depuis circulaires.club, tente de récupérer les prix réguliers depuis les sites officiels,
et génère food/index.html.

Conçu pour rouler chaque jeudi 8h AM (heure du Québec) via GitHub Actions.

Auteur : généré avec Claude pour jayballz.ca/food
"""

import re
import json
import sys
import time
import html
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# -----------------------------------------------------------------------------
# CONFIGURATION
# -----------------------------------------------------------------------------

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

CIRCULAIRES_CLUB_URL = "https://circulaires.club/les-meilleurs-aubaines-en-epicerie/"

# Sites officiels pour tenter de récupérer les prix réguliers
OFFICIAL_SITES = {
    "super-c": "https://www.superc.ca/",
    "maxi": "https://www.maxi.ca/",
    "metro": "https://www.metro.ca/",
    "iga": "https://www.iga.net/",
}

# Bannières à scraper (l'ordre détermine l'ordre d'affichage)
BANNERS = ["super-c", "maxi", "metro", "iga"]

BANNER_INFO = {
    "super-c": {
        "name": "Super C",
        "tagline": "Beau · Bon · Pas cher",
        "css_class": "super-c",
    },
    "maxi": {
        "name": "Maxi",
        "tagline": "Mêmes bas prix · Tous les jours",
        "css_class": "maxi",
    },
    "metro": {
        "name": "Metro",
        "tagline": "Mon Metro · Mon quartier",
        "css_class": "metro",
    },
    "iga": {
        "name": "IGA",
        "tagline": "Vivez mieux · Mangez mieux",
        "css_class": "iga",
    },
}

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "index.html"


# -----------------------------------------------------------------------------
# OUTILS HTTP
# -----------------------------------------------------------------------------

def fetch_url(url, timeout=30):
    """Récupère le contenu HTML d'une URL avec un User-Agent réaliste."""
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "fr-CA,fr;q=0.9,en;q=0.8"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError:
                return raw.decode("latin-1", errors="replace")
    except (URLError, HTTPError) as e:
        print(f"⚠️  Erreur en récupérant {url}: {e}", file=sys.stderr)
        return None


# -----------------------------------------------------------------------------
# SCRAPING DE CIRCULAIRES.CLUB
# -----------------------------------------------------------------------------

def parse_circulaires_club(html_content):
    """
    Extrait les spéciaux par bannière depuis circulaires.club/les-meilleurs-aubaines-en-epicerie/.

    Structure de la page : chaque bannière a un titre <h2>/<h3> ou un bloc image suivi
    d'une <ul> de spéciaux. On utilise une heuristique basée sur l'image de logo.
    """
    if not html_content:
        return {}

    results = {b: [] for b in BANNERS}

    # Mapping nom recherché dans la page → clé bannière
    name_to_key = {
        "Circulaire Maxi": "maxi",
        "Circulaire Super C": "super-c",
        "Circulaire IGA": "iga",
        "Circulaire Metro": "metro",
    }

    # Pattern : trouver chaque section bannière (commence par "Circulaire X")
    # puis capturer toutes les lignes <li>...</li> jusqu'à la prochaine section
    section_pattern = re.compile(
        r'alt="(Circulaire (?:Maxi|Super C|IGA|Metro))"'  # marqueur de section
        r'(.*?)'                                            # contenu
        r'(?=alt="Circulaire (?:Maxi|Super C|IGA|Metro|Provigo|Tigre|Walmart)"|$)',
        re.DOTALL,
    )

    for match in section_pattern.finditer(html_content):
        banner_name = match.group(1)
        section_html = match.group(2)
        key = name_to_key.get(banner_name)
        if not key:
            continue

        # Extraire chaque <li>...</li>
        items = re.findall(r"<li[^>]*>(.*?)</li>", section_html, re.DOTALL)
        for item_html in items:
            text = clean_html_text(item_html)
            if not text or len(text) < 5:
                continue
            parsed = parse_item_line(text)
            if parsed:
                results[key].append(parsed)

    return results


def clean_html_text(s):
    """Nettoie une chaîne HTML pour ne garder que le texte."""
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def parse_item_line(text):
    """
    Parse une ligne comme 'Cuisses de poulet frais 1,95$/lb ou 4,30$/kg'
    en un dict {name, sale_price, unit, scene_plus}.

    Retourne None si non parsable.
    """
    # Détecter prix membre Scène+ (marqué par * ou la mention)
    scene_plus = "*" in text or "membre" in text.lower()
    text_clean = text.rstrip("*").strip()

    # Chercher le prix : ex "1,95$/lb", "2,99$", "55¢", "3/4,98$"
    # On capture le dernier prix dans la ligne (le prix en spécial)
    price_patterns = [
        # Format "X pour Y,YY$" -> "3/4,98$"
        re.compile(r"(\d+)\s*/\s*(\d+[,.]?\d*)\s*\$(?:/(\w+))?", re.IGNORECASE),
        # Format "X,YY$/unité" ou "X,YY$"
        re.compile(r"(\d+[,.]?\d*)\s*\$(?:\s*/\s*(\w+))?", re.IGNORECASE),
        # Format "XX¢"
        re.compile(r"(\d+)\s*¢", re.IGNORECASE),
    ]

    # On cherche TOUS les prix et on prend le premier (le prix principal vient en premier
    # dans le texte de circulaires.club, ex: "1,95$/lb ou 4,30$/kg")
    sale_price = None
    unit = None
    name_end = len(text_clean)

    # Essayer le format "X/Y,YY$"
    m = price_patterns[0].search(text_clean)
    if m:
        try:
            qty = int(m.group(1))
            total = float(m.group(2).replace(",", "."))
            sale_price = total / qty
            unit = m.group(3) if m.group(3) else "un."
            name_end = m.start()
        except (ValueError, ZeroDivisionError):
            pass

    if sale_price is None:
        m = price_patterns[1].search(text_clean)
        if m:
            try:
                sale_price = float(m.group(1).replace(",", "."))
                unit = m.group(2) if m.group(2) else None
                name_end = m.start()
            except ValueError:
                pass

    if sale_price is None:
        m = price_patterns[2].search(text_clean)
        if m:
            try:
                sale_price = float(m.group(1)) / 100
                unit = "un."
                name_end = m.start()
            except ValueError:
                pass

    if sale_price is None:
        return None

    name = text_clean[:name_end].strip().rstrip(",.;:")
    if not name:
        return None

    return {
        "name": name,
        "sale_price": round(sale_price, 2),
        "unit": unit,
        "scene_plus": scene_plus,
        "raw": text,
    }


# -----------------------------------------------------------------------------
# RECHERCHE DES PRIX RÉGULIERS
# -----------------------------------------------------------------------------

def search_regular_price(item_name, banner_key, official_html_cache):
    """
    Tente de trouver le prix régulier d'un item sur le site officiel.

    Stratégie : on cherche le nom de l'item dans le HTML mis en cache.
    Si trouvé, on extrait le prix à proximité.

    Retourne (regular_price, source) ou (None, None) si introuvable.

    Note : c'est best-effort. Les sites officiels changent fréquemment et
    cette fonction retournera None pour la plupart des items.
    """
    html_content = official_html_cache.get(banner_key)
    if not html_content:
        return None, None

    # Extraire les mots-clés principaux du nom (3 premiers mots significatifs)
    keywords = [w for w in re.split(r"\s+", item_name) if len(w) > 3][:3]
    if not keywords:
        return None, None

    # Chercher un contexte qui contient ces mots-clés
    pattern = r"(?i)" + r".*?".join(re.escape(k) for k in keywords)
    m = re.search(pattern + r".{0,300}?(\d+[,.]?\d*)\s*\$", html_content[:500000], re.DOTALL)
    if m:
        try:
            return float(m.group(1).replace(",", ".")), "officiel"
        except ValueError:
            pass

    return None, None


def estimate_regular_price(sale_price, item_name):
    """
    Estime le prix régulier basé sur des heuristiques typiques au Québec :
    - Viandes/poissons : ~30-35% de rabais moyen
    - Fruits/légumes : ~40-50%
    - Garde-manger : ~30-40%
    - Items < 2$ : souvent 50-60% de rabais
    """
    name_lower = item_name.lower()

    # Catégorisation simple
    if any(k in name_lower for k in ["poulet", "porc", "bœuf", "boeuf", "viande", "veau", "agneau", "bacon", "saucisse"]):
        markup = 1.40  # +40% par rapport au prix de rabais
    elif any(k in name_lower for k in ["saumon", "truite", "homard", "crevette", "poisson", "thon"]):
        markup = 1.45
    elif any(k in name_lower for k in ["fromage", "yogourt", "lait", "beurre", "œuf", "oeuf", "crème"]):
        markup = 1.55
    elif any(k in name_lower for k in ["fraise", "framboise", "bleuet", "mûre", "raisin", "pomme",
                                        "ananas", "citron", "lime", "kiwi", "cerise", "clémentine"]):
        markup = 1.65
    elif any(k in name_lower for k in ["légume", "tomate", "concombre", "salade", "romaine", "champignon",
                                        "poivron", "chou", "carotte", "oignon"]):
        markup = 1.60
    elif any(k in name_lower for k in ["pâtes", "riz", "café", "biscuit", "croustille", "céréale", "thé"]):
        markup = 1.50
    elif any(k in name_lower for k in ["jus", "boisson", "pepsi", "coca"]):
        markup = 1.55
    elif any(k in name_lower for k in ["pizza", "surgelé"]):
        markup = 1.60
    else:
        markup = 1.45  # défaut

    if sale_price < 2:
        markup = max(markup, 1.80)  # items très peu chers = gros rabais

    return round(sale_price * markup, 2)


def category_for(item_name):
    """Catégorise un item pour l'étiquette dans le tableau."""
    name_lower = item_name.lower()
    if any(k in name_lower for k in ["poulet", "porc", "bœuf", "boeuf", "veau", "agneau",
                                       "bacon", "saucisse", "jambon", "viande"]):
        return "Viande"
    if any(k in name_lower for k in ["saumon", "truite", "homard", "crevette", "poisson",
                                       "thon", "pétoncle", "tartare", "céviché"]):
        return "Poisson"
    if any(k in name_lower for k in ["fraise", "framboise", "bleuet", "mûre", "raisin", "pomme",
                                       "ananas", "citron", "lime", "kiwi", "cerise", "clémentine",
                                       "orange", "melon", "cantaloup", "mangue"]):
        return "Fruits"
    if any(k in name_lower for k in ["légume", "tomate", "concombre", "salade", "romaine",
                                       "champignon", "poivron", "chou", "carotte", "oignon",
                                       "brocoli", "épinard", "ail", "courgette"]):
        return "Légumes"
    if any(k in name_lower for k in ["fromage", "yogourt", "lait", "beurre", "œuf", "oeuf",
                                       "crème glacée", "ricotta", "feta"]):
        return "Laitier"
    if any(k in name_lower for k in ["pizza", "surgelé"]):
        return "Surgelé"
    if any(k in name_lower for k in ["pâtes", "riz", "café", "biscuit", "croustille", "céréale",
                                       "thé", "sucre", "huile", "vinaigre", "sauce", "tomate en"]):
        return "Garde-manger"
    if any(k in name_lower for k in ["pain", "muffin", "baguette", "bagel", "boulangerie"]):
        return "Boulangerie"
    if any(k in name_lower for k in ["jus", "boisson", "pepsi", "coca", "eau", "soda"]):
        return "Boisson"
    if any(k in name_lower for k in ["détergent", "savon", "papier", "essuie-tout",
                                       "mouchoir", "nettoyant"]):
        return "Ménager"
    if any(k in name_lower for k in ["fleur", "rose", "bouquet", "orchidée", "annuelle", "plant"]):
        return "Floral"
    return "Épicerie"


# -----------------------------------------------------------------------------
# GÉNÉRATION HTML
# -----------------------------------------------------------------------------

CSS_STYLES = """
:root {
  --cream: #f4ead5;
  --paper: #faf3e0;
  --ink: #1a1a1a;
  --tomato: #c8312c;
  --tomato-dark: #962020;
  --moutarde: #d99a1c;
  --sapin: #2d5a3d;
  --sapin-dark: #1c3b28;
  --ardoise: #2b2926;
  --rouge-prix: #e63946;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: 'Inter', sans-serif;
  background-color: var(--paper);
  background-image:
    radial-gradient(circle at 20% 30%, rgba(217, 154, 28, 0.08) 0%, transparent 40%),
    radial-gradient(circle at 80% 70%, rgba(200, 49, 44, 0.06) 0%, transparent 40%);
  color: var(--ink);
  min-height: 100vh;
  padding: 40px 20px;
  line-height: 1.5;
}
body::before {
  content: '';
  position: fixed;
  inset: 0;
  background-image: repeating-linear-gradient(0deg, rgba(0,0,0,0.012) 0px, transparent 1px, transparent 2px, rgba(0,0,0,0.012) 3px);
  pointer-events: none;
  z-index: 1;
}
.container { max-width: 1100px; margin: 0 auto; position: relative; z-index: 2; }
header {
  border-top: 4px double var(--ink);
  border-bottom: 4px double var(--ink);
  padding: 32px 0;
  margin-bottom: 48px;
  text-align: center;
}
.kicker {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.3em;
  text-transform: uppercase;
  color: var(--tomato);
  margin-bottom: 16px;
  font-weight: 700;
}
h1 {
  font-family: 'Fraunces', serif;
  font-weight: 900;
  font-size: clamp(2.5rem, 6vw, 4.5rem);
  line-height: 1;
  letter-spacing: -0.03em;
  margin-bottom: 12px;
  font-style: italic;
}
h1 .amp { color: var(--tomato); font-style: italic; font-weight: 400; }
.dates {
  font-family: 'Fraunces', serif;
  font-size: 1.25rem;
  font-style: italic;
  color: var(--sapin-dark);
  margin-top: 8px;
}
.intro {
  max-width: 640px;
  margin: 24px auto 0;
  font-size: 0.95rem;
  color: #4a4a4a;
  line-height: 1.7;
}
.stats-bar {
  display: flex;
  justify-content: center;
  gap: 32px;
  margin-top: 24px;
  flex-wrap: wrap;
}
.stat {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.15em;
  color: var(--sapin-dark);
}
.stat strong {
  display: block;
  font-family: 'Fraunces', serif;
  font-size: 1.5rem;
  color: var(--tomato);
  font-style: italic;
  font-weight: 800;
  text-transform: none;
  letter-spacing: 0;
  margin-bottom: 2px;
}
.store-section {
  margin-bottom: 64px;
  background: var(--cream);
  border: 2px solid var(--ink);
  border-radius: 2px;
  box-shadow: 6px 6px 0 var(--ink);
  overflow: hidden;
}
.store-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  padding: 24px 32px;
  background: var(--ink);
  color: var(--paper);
  flex-wrap: wrap;
  gap: 12px;
}
.store-name {
  font-family: 'Fraunces', serif;
  font-weight: 800;
  font-size: 2.25rem;
  letter-spacing: -0.02em;
}
.store-tagline {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.2em;
  color: var(--moutarde);
}
.store-count {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.15em;
  color: rgba(250, 243, 224, 0.7);
  margin-top: 4px;
}
.super-c .store-header { background: var(--tomato); }
.super-c .store-header .store-tagline { color: #ffd966; }
.maxi .store-header { background: var(--moutarde); color: var(--ink); }
.maxi .store-header .store-tagline { color: var(--tomato-dark); }
.maxi .store-header .store-count { color: rgba(26, 26, 26, 0.6); }
.metro .store-header { background: var(--sapin); }
.metro .store-header .store-tagline { color: #f5d77a; }
.iga .store-header { background: var(--tomato-dark); }
.iga .store-header .store-tagline { color: var(--moutarde); }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; background: var(--cream); }
thead { background: var(--paper); border-bottom: 3px solid var(--ink); }
th {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.15em;
  text-align: left;
  padding: 16px 20px;
  color: var(--ardoise);
  font-weight: 700;
}
th.num, td.num { text-align: right; font-variant-numeric: tabular-nums; }
td {
  padding: 16px 20px;
  border-bottom: 1px dashed rgba(0,0,0,0.15);
  font-size: 0.92rem;
  vertical-align: middle;
}
tbody tr:last-child td { border-bottom: none; }
tbody tr:hover { background: rgba(255, 255, 255, 0.4); }
.item-name {
  font-family: 'Fraunces', serif;
  font-weight: 600;
  font-size: 1.02rem;
  line-height: 1.3;
}
.item-note {
  display: block;
  font-family: 'Inter', sans-serif;
  font-size: 0.76rem;
  color: #6b6b6b;
  margin-top: 2px;
  font-style: italic;
}
.category {
  display: inline-block;
  padding: 2px 8px;
  background: rgba(0,0,0,0.08);
  color: var(--ardoise);
  font-family: 'JetBrains Mono', monospace;
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  border-radius: 2px;
  margin-right: 8px;
  vertical-align: middle;
}
.price-reg {
  font-family: 'JetBrains Mono', monospace;
  color: #888;
  text-decoration: line-through;
  text-decoration-thickness: 1.5px;
  font-size: 0.88rem;
}
.price-reg.estim::after {
  content: '*';
  color: var(--tomato);
  text-decoration: none;
  display: inline-block;
  margin-left: 2px;
}
.price-sale {
  font-family: 'Fraunces', serif;
  font-weight: 800;
  font-size: 1.2rem;
  color: var(--rouge-prix);
  font-style: italic;
}
.savings {
  display: inline-block;
  padding: 4px 10px;
  background: var(--ink);
  color: var(--moutarde);
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.75rem;
  font-weight: 700;
  border-radius: 2px;
  min-width: 54px;
  text-align: center;
}
.savings.high { background: var(--tomato); color: #fff; }
.savings.medium { background: var(--sapin); color: var(--moutarde); }
.scene-mark {
  display: inline-block;
  font-family: 'JetBrains Mono', monospace;
  font-size: 9px;
  color: var(--tomato);
  margin-left: 6px;
  font-weight: 700;
}
.disclaimer {
  background: var(--cream);
  border-left: 4px solid var(--tomato);
  padding: 16px 20px;
  margin: 32px 0;
  font-size: 0.85rem;
  line-height: 1.6;
  color: #333;
}
.disclaimer strong { color: var(--tomato-dark); }
footer {
  margin-top: 56px;
  padding-top: 32px;
  border-top: 2px solid var(--ink);
  text-align: center;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.15em;
  color: #555;
}
footer a { color: var(--tomato); text-decoration: none; }
footer a:hover { text-decoration: underline; }
.update-badge {
  display: inline-block;
  margin-top: 12px;
  padding: 6px 14px;
  background: var(--sapin);
  color: var(--moutarde);
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  border-radius: 2px;
}
@media (max-width: 640px) {
  body { padding: 24px 12px; }
  .store-header { padding: 18px 20px; }
  .store-name { font-size: 1.75rem; }
  th, td { padding: 12px 10px; font-size: 0.82rem; }
  .item-name { font-size: 0.92rem; }
  .price-sale { font-size: 1.05rem; }
  .savings { font-size: 0.68rem; padding: 3px 6px; min-width: 46px; }
  .category { font-size: 8px; padding: 1px 5px; }
}
@media print {
  body { background: white; }
  .store-section { box-shadow: none; page-break-inside: avoid; }
}
"""


def format_price(price, unit=None):
    """Format un prix en string québécois : '1,95 $/lb' ou '2,99 $'"""
    s = f"{price:.2f}".replace(".", ",")
    if unit and unit not in ("un.", None):
        return f"{s} $/{unit}"
    return f"{s} $"


def format_savings_class(pct):
    if pct >= 45:
        return "high"
    if pct >= 30:
        return "medium"
    return ""


def extract_week_dates_from_html(html_content):
    """
    Extrait les dates de validité depuis le HTML de circulaires.club.
    Cherche un pattern comme "du 14 au 20 mai 2026" ou "14 au 20 mai".
    Retourne (date_debut, date_fin) ou None si non trouvé.
    """
    if not html_content:
        return None
    
    # Pattern pour "du X au Y mois année" ou "X au Y mois"
    # Ex: "du 14 au 20 mai 2026", "14 au 20 mai", etc.
    months_fr = {
        "janvier": 1, "février": 2, "mars": 3, "avril": 4,
        "mai": 5, "juin": 6, "juillet": 7, "août": 8,
        "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12
    }
    
    pattern = r'(?:du\s+)?(\d{1,2})\s+au\s+(\d{1,2})\s+(janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)(?:\s+(\d{4}))?'
    m = re.search(pattern, html_content, re.IGNORECASE)
    
    if m:
        day_start = int(m.group(1))
        day_end = int(m.group(2))
        month_name = m.group(3).lower()
        year = int(m.group(4)) if m.group(4) else datetime.now().year
        
        month = months_fr.get(month_name)
        if month:
            try:
                date_start = datetime(year, month, day_start)
                date_end = datetime(year, month, day_end)
                return date_start, date_end
            except ValueError:
                pass
    
    return None


def get_week_dates(html_content=None):
    """
    Retourne (date_jeudi, date_mercredi_suivant) pour la semaine des circulaires.
    
    Stratégie:
    1. Si html_content fourni, essaie d'extraire les dates depuis circulaires.club
    2. Sinon, calcule basé sur le jeudi le plus proche
    """
    # Essayer d'extraire depuis le HTML
    if html_content:
        dates = extract_week_dates_from_html(html_content)
        if dates:
            return dates
    
    # Fallback: calculer basé sur aujourd'hui
    today = datetime.now(timezone(timedelta(hours=-4)))  # heure du Québec
    
    # Si on est lundi/mardi/mercredi, prendre le jeudi qui vient (semaine suivante)
    # Si on est jeudi ou après, prendre le jeudi de cette semaine
    weekday = today.weekday()  # 0=lundi, 3=jeudi
    
    if weekday < 3:  # lundi, mardi, mercredi
        days_until_thursday = 3 - weekday
        thursday = today + timedelta(days=days_until_thursday)
    else:  # jeudi ou après
        days_since_thursday = weekday - 3
        thursday = today - timedelta(days=days_since_thursday)
    
    wednesday = thursday + timedelta(days=6)
    return thursday, wednesday


def format_date_fr(d):
    months = ["janvier", "février", "mars", "avril", "mai", "juin",
              "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
    return f"{d.day} {months[d.month - 1]} {d.year}"


def generate_html(data_by_banner, source_html=None):
    """Génère le HTML complet à partir des données scrapées."""
    thursday, wednesday = get_week_dates(source_html)
    date_range = f"du jeudi {thursday.day} au mercredi {format_date_fr(wednesday)}"
    update_time = datetime.now(timezone(timedelta(hours=-4))).strftime("%Y-%m-%d %H:%M")

    total_items = sum(len(items) for items in data_by_banner.values())

    sections_html = ""
    for banner_key in BANNERS:
        info = BANNER_INFO[banner_key]
        items = data_by_banner.get(banner_key, [])
        sections_html += render_section(banner_key, info, items)

    return f"""<!DOCTYPE html>
<html lang="fr-CA">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Spéciaux d'épicerie — {date_range}</title>
<meta name="description" content="Les meilleurs spéciaux hebdomadaires de Super C, Maxi, Metro et IGA au Québec, mis à jour chaque jeudi.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,600;0,9..144,800;0,9..144,900;1,9..144,400&family=JetBrains+Mono:wght@400;500;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>{CSS_STYLES}</style>
</head>
<body>
<div class="container">
  <header>
    <div class="kicker">★ Édition hebdomadaire ★ Québec ★</div>
    <h1>Les meilleurs spéciaux <span class="amp">&amp;</span> aubaines</h1>
    <div class="dates">{date_range}</div>
    <p class="intro">
      Une compilation hebdomadaire des meilleures occasions à saisir dans les quatre principales bannières québécoises. Mis à jour automatiquement chaque jeudi matin.
    </p>
    <div class="stats-bar">
      <div class="stat"><strong>4</strong>Épiceries</div>
      <div class="stat"><strong>{total_items}</strong>Spéciaux</div>
      <div class="stat"><strong>7 jours</strong>Validité</div>
    </div>
    <div class="update-badge">Dernière mise à jour : {update_time}</div>
  </header>

  {sections_html}

  <div class="disclaimer">
    <strong>* À propos des prix réguliers :</strong> les prix réguliers marqués d'un astérisque (*) sont des estimations basées sur les prix habituels au Québec — les économies réelles peuvent varier. Les prix peuvent différer d'une succursale à l'autre. Certains rabais nécessitent une carte de fidélité (programme Moi pour Metro/Super C, Scène+ pour IGA, PC Optimum pour Maxi). Les items marqués <span class="scene-mark">★ MEMBRE</span> exigent la carte de fidélité de la bannière.
  </div>

  <footer>
    Données scrapées de <a href="https://circulaires.club" target="_blank" rel="noopener">circulaires.club</a> ·
    Page générée le {update_time} ·
    <a href="https://github.com" target="_blank" rel="noopener">Code source</a>
  </footer>
</div>
</body>
</html>
"""


def render_section(banner_key, info, items):
    if not items:
        body = '<tr><td colspan="4" style="text-align:center; padding:24px; font-style:italic; color:#888;">Données non disponibles cette semaine. Réessayez bientôt.</td></tr>'
    else:
        # Trier par % de rabais décroissant
        for item in items:
            reg = item.get("regular_price")
            sale = item["sale_price"]
            if reg and reg > sale:
                item["_pct"] = round((1 - sale / reg) * 100)
            else:
                item["_pct"] = 0

        items_sorted = sorted(items, key=lambda x: x.get("_pct", 0), reverse=True)
        body = ""
        for item in items_sorted:
            body += render_row(item)

    return f"""
  <section class="store-section {info['css_class']}">
    <div class="store-header">
      <div>
        <div class="store-name">{info['name']}</div>
        <div class="store-count">{len(items)} spéciaux repérés</div>
      </div>
      <div class="store-tagline">{info['tagline']}</div>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Article</th>
            <th class="num">Prix régulier</th>
            <th class="num">Rabais</th>
            <th class="num">Économie</th>
          </tr>
        </thead>
        <tbody>
{body}        </tbody>
      </table>
    </div>
  </section>
"""


def render_row(item):
    name = html.escape(item["name"])
    cat = category_for(item["name"])
    sale = item["sale_price"]
    unit = item.get("unit")
    reg = item.get("regular_price")
    reg_is_estimated = item.get("regular_estimated", True)
    pct = item.get("_pct", 0)

    scene_mark = '<span class="scene-mark">★ MEMBRE</span>' if item.get("scene_plus") else ""

    sale_str = html.escape(format_price(sale, unit))
    reg_class = "estim" if reg_is_estimated else ""
    reg_str = html.escape(format_price(reg, unit)) if reg else "—"

    if pct >= 1:
        savings_class = format_savings_class(pct)
        savings_str = f'<span class="savings {savings_class}">−{pct} %</span>'
    else:
        savings_str = '<span class="savings" style="opacity:0.4">—</span>'

    return f"""          <tr>
            <td><span class="category">{cat}</span><span class="item-name">{name}{scene_mark}</span></td>
            <td class="num"><span class="price-reg {reg_class}">{reg_str}</span></td>
            <td class="num"><span class="price-sale">{sale_str}</span></td>
            <td class="num">{savings_str}</td>
          </tr>
"""


# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------

def main():
    print("🍅 Démarrage du scraping...")

    # 1. Scraper circulaires.club
    print(f"📥 Récupération de {CIRCULAIRES_CLUB_URL}")
    cc_html = fetch_url(CIRCULAIRES_CLUB_URL)
    if not cc_html:
        print("❌ Impossible de récupérer circulaires.club", file=sys.stderr)
        sys.exit(1)

    data = parse_circulaires_club(cc_html)
    for banner_key, items in data.items():
        print(f"   {BANNER_INFO[banner_key]['name']}: {len(items)} items")

    # 2. Tenter de récupérer les prix réguliers des sites officiels
    print("🔍 Récupération des sites officiels pour prix réguliers...")
    official_cache = {}
    for banner_key, url in OFFICIAL_SITES.items():
        print(f"   {url}")
        official_cache[banner_key] = fetch_url(url) or ""
        time.sleep(2)  # Politesse : 2 secondes entre les requêtes

    # 3. Enrichir chaque item avec prix régulier (officiel ou estimé)
    print("💰 Calcul des prix réguliers...")
    for banner_key, items in data.items():
        for item in items:
            reg, source = search_regular_price(item["name"], banner_key, official_cache)
            if reg and reg > item["sale_price"]:
                item["regular_price"] = reg
                item["regular_estimated"] = False
            else:
                item["regular_price"] = estimate_regular_price(item["sale_price"], item["name"])
                item["regular_estimated"] = True

    # 4. Générer le HTML
    print(f"✨ Génération de {OUTPUT_PATH}")
    html_out = generate_html(data, cc_html)
    OUTPUT_PATH.write_text(html_out, encoding="utf-8")

    total = sum(len(items) for items in data.values())
    print(f"✅ Terminé! {total} spéciaux générés dans {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
