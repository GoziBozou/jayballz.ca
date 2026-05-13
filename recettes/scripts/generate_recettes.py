#!/usr/bin/env python3
"""
generate_recettes.py
--------------------
Génère la page jayballz.ca/recettes en matchant les recettes de la base de données
avec les rabais actuels de jayballz.ca/food.

Auteur : généré avec Claude pour jayballz.ca/recettes
"""

import json
import re
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

# -----------------------------------------------------------------------------
# CONFIGURATION
# -----------------------------------------------------------------------------

RECETTES_DB_PATH = Path(__file__).resolve().parent.parent / "recettes_database.json"
FOOD_HTML_PATH = Path(__file__).resolve().parent.parent.parent / "food" / "index.html"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "index.html"

# -----------------------------------------------------------------------------
# EXTRACTION DES RABAIS DEPUIS /food/index.html
# -----------------------------------------------------------------------------

def extract_specials_from_food_html(html_path):
    """
    Extrait les items en rabais depuis food/index.html.
    Retourne une liste de noms d'items normalisés.
    """
    if not html_path.exists():
        print(f"⚠️  {html_path} n'existe pas encore", file=sys.stderr)
        return []
    
    html_content = html_path.read_text(encoding='utf-8')
    
    # Extraire les noms d'items depuis les balises <span class="item-name">
    pattern = r'<span class="item-name">([^<]+)(?:<span|</span>)'
    matches = re.findall(pattern, html_content)
    
    # Normaliser les noms (minuscules, sans accents complexes)
    specials = []
    for name in matches:
        # Nettoyer les spans internes et badges
        name = re.sub(r'<[^>]+>', '', name)
        name = name.strip().lower()
        specials.append(name)
    
    return specials


def normalize_ingredient_name(name):
    """Normalise un nom d'ingrédient pour le matching."""
    name = name.lower()
    # Enlever les déterminants
    name = re.sub(r'^(le|la|les|du|de la|des|un|une) ', '', name)
    # Pluriel -> singulier basique
    name = re.sub(r's$', '', name)
    return name.strip()


def match_score(recipe, specials_normalized):
    """
    Calcule un score de matching pour une recette basé sur les ingrédients en rabais.
    
    Score:
    - +3 points par ingrédient principal en rabais (rabais_possible=true)
    - +1 point par ingrédient secondaire qui matche
    """
    score = 0
    matched_ingredients = []
    
    for ingredient in recipe.get('ingredients', []):
        ing_name = normalize_ingredient_name(ingredient['nom'])
        
        # Vérifier si cet ingrédient matche un rabais
        for special in specials_normalized:
            # Match direct ou partial (ex: "poulet" matche "cuisses de poulet")
            if ing_name in special or special in ing_name:
                if ingredient.get('rabais_possible', False):
                    score += 3
                    matched_ingredients.append(ingredient['nom'])
                else:
                    score += 1
                break
    
    return score, matched_ingredients


# -----------------------------------------------------------------------------
# SÉLECTION DES 10 MEILLEURES RECETTES
# -----------------------------------------------------------------------------

def select_top_recipes(recipes_db, specials):
    """
    Sélectionne les 10 meilleures recettes basées sur le matching avec les rabais.
    Retourne une liste de (recipe, score, matched_ingredients).
    """
    specials_normalized = [normalize_ingredient_name(s) for s in specials]
    
    scored_recipes = []
    for recipe in recipes_db['recipes']:
        score, matched = match_score(recipe, specials_normalized)
        if score > 0:  # Ne garder que les recettes avec au moins 1 match
            scored_recipes.append((recipe, score, matched))
    
    # Trier par score décroissant
    scored_recipes.sort(key=lambda x: x[1], reverse=True)
    
    # Prendre les 10 meilleures
    top_10 = scored_recipes[:10]
    
    # Si moins de 10, compléter avec des recettes aléatoires
    if len(top_10) < 10:
        remaining = [r for r in recipes_db['recipes'] if r not in [t[0] for t in top_10]]
        import random
        random.shuffle(remaining)
        for r in remaining[:10 - len(top_10)]:
            top_10.append((r, 0, []))
    
    return top_10


# -----------------------------------------------------------------------------
# GÉNÉRATION HTML
# -----------------------------------------------------------------------------

CSS_STYLES = """
:root {
  --cream: #f4ead5;
  --paper: #faf3e0;
  --ink: #1a1a1a;
  --tomato: #c8312c;
  --moutarde: #d99a1c;
  --sapin: #2d5a3d;
  --sapin-dark: #1c3b28;
  --rouge-prix: #e63946;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: 'Inter', -apple-system, system-ui, sans-serif;
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
  font-size: clamp(2.5rem, 6vw, 4rem);
  line-height: 1;
  letter-spacing: -0.03em;
  margin-bottom: 12px;
  font-style: italic;
}
.intro {
  max-width: 640px;
  margin: 24px auto 0;
  font-size: 0.95rem;
  color: #4a4a4a;
  line-height: 1.7;
}
.intro a {
  color: var(--tomato);
  text-decoration: none;
  border-bottom: 2px solid var(--moutarde);
}
.intro a:hover { border-bottom-color: var(--tomato); }
.recipes-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 32px;
  margin-top: 48px;
}
.recipe-card {
  background: var(--cream);
  border: 2px solid var(--ink);
  border-radius: 2px;
  overflow: hidden;
  cursor: pointer;
  transition: transform 0.2s, box-shadow 0.2s;
  box-shadow: 4px 4px 0 var(--ink);
}
.recipe-card:hover {
  transform: translateY(-4px);
  box-shadow: 6px 8px 0 var(--ink);
}
.recipe-image {
  height: 200px;
  background: linear-gradient(135deg, var(--sapin) 0%, var(--moutarde) 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 4rem;
  border-bottom: 2px solid var(--ink);
}
.recipe-card[data-category="poulet"] .recipe-image {
  background: linear-gradient(135deg, #d4a574 0%, #f4d03f 100%);
}
.recipe-card[data-category="poisson"] .recipe-image,
.recipe-card[data-category="fruits_de_mer"] .recipe-image {
  background: linear-gradient(135deg, #5dade2 0%, #21618c 100%);
}
.recipe-card[data-category="porc"] .recipe-image {
  background: linear-gradient(135deg, #ec7063 0%, #943126 100%);
}
.recipe-card[data-category="boeuf"] .recipe-image {
  background: linear-gradient(135deg, #a04000 0%, #641e16 100%);
}
.recipe-card[data-category="vegetarien"] .recipe-image {
  background: linear-gradient(135deg, #52b788 0%, #2d6a4f 100%);
}
.recipe-content {
  padding: 20px;
}
.recipe-title {
  font-family: 'Fraunces', serif;
  font-weight: 700;
  font-size: 1.25rem;
  line-height: 1.3;
  margin-bottom: 12px;
  color: var(--ink);
}
.recipe-badges {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.badge {
  display: inline-block;
  padding: 4px 10px;
  background: var(--ink);
  color: var(--moutarde);
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.05em;
  border-radius: 2px;
  text-transform: uppercase;
}
.badge.rabais {
  background: var(--tomato);
  color: #fff;
}
.recipe-meta {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: #666;
  margin-top: 12px;
  display: flex;
  gap: 16px;
}
.nutrition {
  display: flex;
  gap: 16px;
  margin-top: 8px;
  padding-top: 12px;
  border-top: 1px dashed rgba(0,0,0,0.2);
}
.nutrition-item {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
}
.nutrition-item strong {
  display: block;
  font-family: 'Fraunces', serif;
  font-size: 1.1rem;
  color: var(--sapin-dark);
  font-weight: 800;
}

/* MODAL */
.modal {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.85);
  z-index: 1000;
  align-items: center;
  justify-content: center;
  padding: 20px;
  overflow-y: auto;
}
.modal.active { display: flex; }
.modal-content {
  background: var(--paper);
  border: 3px solid var(--ink);
  border-radius: 2px;
  max-width: 700px;
  width: 100%;
  max-height: 90vh;
  overflow-y: auto;
  position: relative;
  box-shadow: 0 10px 40px rgba(0,0,0,0.3);
}
.modal-close {
  position: absolute;
  top: 16px;
  right: 16px;
  width: 40px;
  height: 40px;
  background: var(--ink);
  color: var(--paper);
  border: none;
  cursor: pointer;
  font-size: 24px;
  line-height: 1;
  border-radius: 2px;
  z-index: 10;
}
.modal-close:hover {
  background: var(--tomato);
}
.modal-image {
  height: 250px;
  background: linear-gradient(135deg, var(--sapin) 0%, var(--moutarde) 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 5rem;
  border-bottom: 3px solid var(--ink);
}
.modal-body {
  padding: 32px;
}
.modal-title {
  font-family: 'Fraunces', serif;
  font-weight: 900;
  font-size: 2rem;
  line-height: 1.2;
  margin-bottom: 16px;
  font-style: italic;
}
.modal-meta {
  display: flex;
  gap: 24px;
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 2px solid var(--cream);
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  color: #666;
}
.modal-meta strong {
  color: var(--ink);
}
.section-title {
  font-family: 'Fraunces', serif;
  font-weight: 700;
  font-size: 1.25rem;
  margin: 24px 0 12px;
  color: var(--sapin-dark);
}
.ingredients-list {
  list-style: none;
  padding: 0;
}
.ingredients-list li {
  padding: 8px 0;
  border-bottom: 1px dashed rgba(0,0,0,0.1);
  font-size: 0.95rem;
}
.ingredients-list li:last-child {
  border-bottom: none;
}
.ingredients-list .rabais-star {
  color: var(--tomato);
  margin-right: 6px;
  font-weight: 700;
}
.steps-list {
  list-style: none;
  counter-reset: step-counter;
  padding: 0;
}
.steps-list li {
  counter-increment: step-counter;
  padding: 16px 0 16px 48px;
  position: relative;
  border-bottom: 1px dashed rgba(0,0,0,0.1);
}
.steps-list li:last-child {
  border-bottom: none;
}
.steps-list li::before {
  content: counter(step-counter);
  position: absolute;
  left: 0;
  top: 12px;
  width: 32px;
  height: 32px;
  background: var(--ink);
  color: var(--moutarde);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: 'Fraunces', serif;
  font-weight: 800;
  font-size: 1.1rem;
}
.modal-nutrition {
  display: flex;
  gap: 32px;
  margin-top: 24px;
  padding: 20px;
  background: var(--cream);
  border-radius: 2px;
  border: 2px solid var(--ink);
}
.modal-nutrition-item {
  text-align: center;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: #666;
}
.modal-nutrition-item strong {
  display: block;
  font-family: 'Fraunces', serif;
  font-size: 2rem;
  color: var(--sapin-dark);
  font-weight: 800;
  margin-bottom: 4px;
  text-transform: none;
  letter-spacing: 0;
}

footer {
  margin-top: 64px;
  padding-top: 32px;
  border-top: 2px solid var(--ink);
  text-align: center;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.15em;
  color: #555;
}
footer a {
  color: var(--tomato);
  text-decoration: none;
}
footer a:hover {
  text-decoration: underline;
}

@media (max-width: 640px) {
  body { padding: 24px 12px; }
  .recipes-grid {
    grid-template-columns: 1fr;
    gap: 24px;
  }
  .modal-body { padding: 24px; }
  .modal-title { font-size: 1.5rem; }
  .modal-image { height: 180px; font-size: 3.5rem; }
}
"""

EMOJI_BY_CATEGORY = {
    "poulet": "🍗",
    "poisson": "🐟",
    "fruits_de_mer": "🦐",
    "porc": "🥓",
    "boeuf": "🥩",
    "vegetarien": "🥗",
}


def generate_html(top_recipes):
    """Génère le HTML complet de la page recettes."""
    
    update_time = datetime.now(timezone(timedelta(hours=-4))).strftime("%Y-%m-%d %H:%M")
    
    # Générer les cartes de recettes
    cards_html = ""
    for recipe, score, matched in top_recipes:
        emoji = EMOJI_BY_CATEGORY.get(recipe['categorie'], "🍽️")
        
        # Badges
        badges_html = ""
        if len(matched) > 0:
            badges_html = f'<span class="badge rabais">⭐ {len(matched)} en rabais</span>'
        badges_html += f'<span class="badge">{recipe["portions"]} portions</span>'
        
        # Temps total
        temps_total = recipe['temps_preparation'] + recipe['temps_cuisson']
        
        # Ingrédients en rabais pour data attribute
        matched_json = json.dumps(matched, ensure_ascii=False).replace('"', '&quot;')
        
        cards_html += f"""
    <div class="recipe-card" data-category="{recipe['categorie']}" data-recipe-id="{recipe['id']}" data-matched='{matched_json}'>
      <div class="recipe-image">{emoji}</div>
      <div class="recipe-content">
        <h3 class="recipe-title">{recipe['titre']}</h3>
        <div class="recipe-badges">
          {badges_html}
        </div>
        <div class="recipe-meta">
          <span>⏱️ {temps_total} min</span>
        </div>
        <div class="nutrition">
          <div class="nutrition-item">
            <strong>{recipe['calories_par_portion']}</strong>
            calories
          </div>
          <div class="nutrition-item">
            <strong>{recipe['proteines_par_portion']}g</strong>
            protéines
          </div>
        </div>
      </div>
    </div>"""
    
    # Générer les modals
    modals_html = ""
    for recipe, score, matched in top_recipes:
        emoji = EMOJI_BY_CATEGORY.get(recipe['categorie'], "🍽️")
        
        # Liste d'ingrédients avec étoiles pour ceux en rabais
        ingredients_html = ""
        matched_lower = [m.lower() for m in matched]
        for ing in recipe['ingredients']:
            star = ""
            if ing['nom'].lower() in matched_lower or any(m in ing['nom'].lower() for m in matched_lower):
                star = '<span class="rabais-star">⭐</span>'
            qte_str = f"{ing['quantite']} {ing['unite']}" if ing.get('quantite') else ""
            ingredients_html += f'<li>{star}{ing["nom"]} <em>({qte_str})</em></li>\n'
        
        # Étapes
        steps_html = ""
        for step in recipe['etapes']:
            steps_html += f'<li>{step}</li>\n'
        
        modals_html += f"""
  <div class="modal" id="modal-{recipe['id']}">
    <div class="modal-content">
      <button class="modal-close" onclick="closeModal({recipe['id']})">&times;</button>
      <div class="modal-image" style="background: linear-gradient(135deg, {'var(--sapin)' if recipe['categorie'] == 'vegetarien' else 'var(--moutarde)'} 0%, {'var(--sapin-dark)' if recipe['categorie'] == 'vegetarien' else 'var(--tomato)'} 100%);">
        {emoji}
      </div>
      <div class="modal-body">
        <h2 class="modal-title">{recipe['titre']}</h2>
        <div class="modal-meta">
          <span><strong>Préparation:</strong> {recipe['temps_preparation']} min</span>
          <span><strong>Cuisson:</strong> {recipe['temps_cuisson']} min</span>
          <span><strong>Portions:</strong> {recipe['portions']}</span>
        </div>
        
        <h3 class="section-title">Ingrédients</h3>
        <ul class="ingredients-list">
{ingredients_html}        </ul>
        
        <h3 class="section-title">Préparation</h3>
        <ol class="steps-list">
{steps_html}        </ol>
        
        <div class="modal-nutrition">
          <div class="modal-nutrition-item">
            <strong>{recipe['calories_par_portion']}</strong>
            Calories/portion
          </div>
          <div class="modal-nutrition-item">
            <strong>{recipe['proteines_par_portion']}g</strong>
            Protéines/portion
          </div>
        </div>
      </div>
    </div>
  </div>"""
    
    return f"""<!DOCTYPE html>
<html lang="fr-CA">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Recettes santé avec les rabais — jayballz.ca</title>
<meta name="description" content="10 recettes santé équilibrées basées sur les spéciaux d'épicerie de la semaine au Québec">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,600;0,9..144,800;0,9..144,900;1,9..144,400&family=JetBrains+Mono:wght@400;500;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>{CSS_STYLES}</style>
</head>
<body>
<div class="container">
  <header>
    <div class="kicker">★ Recettes santé ★ Basées sur les rabais ★</div>
    <h1>10 recettes avec les spéciaux de la semaine</h1>
    <p class="intro">
      Des recettes équilibrées (protéine + légumes + glucides) qui utilisent les ingrédients en rabais cette semaine. 
      Consultez les <a href="/food">spéciaux d'épicerie</a> pour voir tous les rabais.
    </p>
  </header>

  <div class="recipes-grid">
{cards_html}
  </div>

{modals_html}

  <footer>
    Mis à jour automatiquement chaque jeudi · 
    Dernière mise à jour : {update_time} · 
    <a href="/food">Voir les spéciaux</a>
  </footer>
</div>

<script>
function openModal(recipeId) {{
  const modal = document.getElementById('modal-' + recipeId);
  if (modal) {{
    modal.classList.add('active');
    document.body.style.overflow = 'hidden';
  }}
}}

function closeModal(recipeId) {{
  const modal = document.getElementById('modal-' + recipeId);
  if (modal) {{
    modal.classList.remove('active');
    document.body.style.overflow = '';
  }}
}}

// Click sur une carte pour ouvrir le modal
document.querySelectorAll('.recipe-card').forEach(card => {{
  card.addEventListener('click', function() {{
    const recipeId = this.dataset.recipeId;
    openModal(recipeId);
  }});
}});

// Click en dehors du modal pour fermer
document.querySelectorAll('.modal').forEach(modal => {{
  modal.addEventListener('click', function(e) {{
    if (e.target === this) {{
      const recipeId = this.id.replace('modal-', '');
      closeModal(recipeId);
    }}
  }});
}});

// ESC pour fermer
document.addEventListener('keydown', function(e) {{
  if (e.key === 'Escape') {{
    document.querySelectorAll('.modal.active').forEach(modal => {{
      const recipeId = modal.id.replace('modal-', '');
      closeModal(recipeId);
    }});
  }}
}});
</script>
</body>
</html>
"""


# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------

def main():
    print("🥗 Génération de la page recettes...")
    
    # 1. Charger la base de données de recettes
    if not RECETTES_DB_PATH.exists():
        print(f"❌ Base de données introuvable: {RECETTES_DB_PATH}", file=sys.stderr)
        sys.exit(1)
    
    with open(RECETTES_DB_PATH, 'r', encoding='utf-8') as f:
        recipes_db = json.load(f)
    
    print(f"📚 {len(recipes_db['recipes'])} recettes chargées")
    
    # 2. Extraire les rabais depuis food/index.html
    specials = extract_specials_from_food_html(FOOD_HTML_PATH)
    print(f"🛒 {len(specials)} spéciaux détectés dans /food")
    
    # 3. Sélectionner les 10 meilleures recettes
    top_10 = select_top_recipes(recipes_db, specials)
    print(f"✨ 10 recettes sélectionnées:")
    for recipe, score, matched in top_10:
        match_info = f"({len(matched)} ingrédients en rabais)" if matched else "(complément)"
        print(f"   - {recipe['titre']} [score: {score}] {match_info}")
    
    # 4. Générer le HTML
    html_output = generate_html(top_10)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(html_output, encoding='utf-8')
    
    print(f"✅ Page générée: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
