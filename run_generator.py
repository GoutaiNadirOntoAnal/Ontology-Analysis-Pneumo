#!/usr/bin/env python
"""
Script simple pour générer l'application web à partir de l'ontologie
"""

import os
import sys
from ontology_generator import OntologyToWebGenerator

def main():
    print("\n" + "=" * 70)
    print("GÉNÉRATEUR D'APPLICATION WEB À PARTIR D'ONTOLOGIE OWL")
    print("=" * 70)
    
    # Chemin vers l'ontologie
    ontology_path = os.path.join(os.path.dirname(__file__), 'ontologies', 'onto.owl')
    
    if not os.path.exists(ontology_path):
        print(f"❌ Erreur: Fichier ontologie non trouvé: {ontology_path}")
        sys.exit(1)
    
    print(f"\n📂 Ontologie trouvée: {ontology_path}")
    
    # Crée le générateur
    generator = OntologyToWebGenerator(ontology_path, app_name='hopital')
    
    # Génère les fichiers
    output_dir = os.path.join(os.path.dirname(__file__), 'ontologies')
    generator.generate_all(output_dir)
    
    print("\n" + "=" * 70)
    print("PROCHAINES ÉTAPES:")
    print("=" * 70)
    print("\n1. Vérifiez les fichiers générés dans le répertoire 'ontologies/':")
    print("   - models_generated.py")
    print("   - forms_generated.py")
    print("   - views_generated.py")
    print("   - urls_generated.py")
    
    print("\n2. Intégrez les modèles générés dans models.py:")
    print("   - Copiez le contenu de 'models_generated.py' si vous voulez remplacer")
    print("   - Ou utilisez les modèles générés comme référence")
    
    print("\n3. Intégrez les formulaires dans forms.py")
    
    print("\n4. Intégrez les vues dans views.py")
    
    print("\n5. Intégrez les URLs dans urls.py")
    
    print("\n6. Exécutez les migrations:")
    print("   python manage.py makemigrations hopital")
    print("   python manage.py migrate")
    
    print("\n7. Testez l'application:")
    print("   python manage.py runserver")
    
    print("\n" + "=" * 70)
    print("✅ GÉNÉRATION RÉUSSIE!")
    print("=" * 70 + "\n")

if __name__ == '__main__':
    main()
