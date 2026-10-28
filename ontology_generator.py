"""
Générateur automatique d'application web Django basée sur une ontologie OWL
Utilise owlready2 pour parser l'ontologie et générer le code
"""

from owlready2 import get_ontology
import os
import re
from typing import Dict, List, Tuple

class OntologyToWebGenerator:
    def __init__(self, ontology_path: str, app_name: str = "hopital"):
        """
        Initialise le générateur
        :param ontology_path: chemin vers le fichier OWL
        :param app_name: nom de l'application Django
        """
        self.ontology_path = ontology_path
        self.app_name = app_name
        self.onto = None
        self.classes = {}
        self.data_properties = {}
        self.object_properties = {}
        
    def load_ontology(self):
        """Charge l'ontologie OWL"""
        print(f"Chargement de l'ontologie: {self.ontology_path}")
        self.onto = get_ontology(self.ontology_path).load()
        self.extract_classes()
        self.extract_properties()
        print(f"Ontologie chargée avec succès!")
        
    def extract_classes(self):
        """Extrait les classes de l'ontologie"""
        for cls in self.onto.classes():
            class_name = cls.name
            self.classes[class_name] = {
                'name': class_name,
                'parent_classes': list(cls.is_a),
                'instances': list(cls.instances()),
            }
        print(f"Trouvé {len(self.classes)} classes")
        
    def extract_properties(self):
        """Extrait les propriétés de données et d'objets"""
        # Propriétés de données
        for prop in self.onto.data_properties():
            prop_name = prop.name
            self.data_properties[prop_name] = {
                'name': prop_name,
                'domain': list(prop.domain),
                'range': list(prop.range),
            }
        
        # Propriétés d'objets
        for prop in self.onto.object_properties():
            prop_name = prop.name
            self.object_properties[prop_name] = {
                'name': prop_name,
                'domain': list(prop.domain),
                'range': list(prop.range),
            }
        
        print(f"Trouvé {len(self.data_properties)} propriétés de données")
        print(f"Trouvé {len(self.object_properties)} propriétés d'objets")
    
    def map_xsd_to_django(self, xsd_type: str) -> str:
        """Mappe les types XSD aux champs Django"""
        type_mapping = {
            'string': 'CharField',
            'integer': 'IntegerField',
            'int': 'IntegerField',
            'decimal': 'DecimalField',
            'float': 'FloatField',
            'date': 'DateField',
            'dateTime': 'DateTimeField',
            'boolean': 'BooleanField',
            'text': 'TextField',
        }
        
        for key, value in type_mapping.items():
            if key.lower() in str(xsd_type).lower():
                return value
        return 'CharField'  # Type par défaut
    
    def camel_to_snake(self, name: str) -> str:
        """Convertit CamelCase en snake_case"""
        s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
        return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
    
    def generate_models(self) -> str:
        """Génère le code des modèles Django"""
        models_code = '''"""
Modèles Django générés automatiquement à partir de l'ontologie
"""

from django.db import models
from django.contrib.auth.models import User


'''
        
        # Génère les modèles pour chaque classe
        for class_name, class_info in self.classes.items():
            # Ignore les classes sans propriétés
            if class_name in ['Thing']:
                continue
            
            snake_name = self.camel_to_snake(class_name)
            models_code += f"class {class_name}(models.Model):\n"
            models_code += f'    """{class_name} - Généré à partir de l\'ontologie"""\n'
            models_code += f"    id = models.AutoField(primary_key=True)\n"
            
            # Ajoute les propriétés de données pour cette classe
            properties_found = False
            for prop_name, prop_info in self.data_properties.items():
                for domain in prop_info['domain']:
                    if hasattr(domain, 'name') and domain.name == class_name:
                        xsd_type = str(prop_info['range'][0]) if prop_info['range'] else 'string'
                        django_field = self.map_xsd_to_django(xsd_type)
                        
                        # Configuration du champ
                        field_config = "blank=True, null=True"
                        if 'integer' in django_field.lower():
                            field_config = "blank=True, null=True"
                        elif 'decimal' in django_field.lower() or 'float' in django_field.lower():
                            field_config = "max_digits=10, decimal_places=2, blank=True, null=True"
                        
                        models_code += f"    {prop_name} = models.{django_field}({field_config})\n"
                        properties_found = True
            
            # Ajoute le timestamp de création
            models_code += f"    created_at = models.DateTimeField(auto_now_add=True)\n"
            models_code += f"    updated_at = models.DateTimeField(auto_now=True)\n"
            models_code += f"\n    def __str__(self):\n"
            models_code += f"        return f\"{class_name}-{{self.id}}\"\n\n"
        
        return models_code
    
    def generate_forms(self) -> str:
        """Génère les formulaires Django"""
        forms_code = '''"""
Formulaires générés automatiquement à partir de l'ontologie
"""

from django import forms
from .models import *


'''
        
        for class_name in self.classes.keys():
            if class_name in ['Thing']:
                continue
            
            forms_code += f"class {class_name}Form(forms.ModelForm):\n"
            forms_code += f"    class Meta:\n"
            forms_code += f"        model = {class_name}\n"
            forms_code += f"        fields = '__all__'\n"
            forms_code += f"        exclude = ['id', 'created_at', 'updated_at']\n"
            forms_code += f"        widgets = {{\n"
            
            # Ajoute les widgets pour les champs
            snake_name = self.camel_to_snake(class_name)
            for prop_name in self.data_properties.keys():
                forms_code += f"            '{prop_name}': forms.TextInput(attrs={{'class': 'form-control', 'placeholder': '{prop_name}'}}),\n"
            
            forms_code += f"        }}\n\n"
        
        return forms_code
    
    def generate_views(self) -> str:
        """Génère les vues Django"""
        views_code = '''"""
Vues CRUD générées automatiquement à partir de l'ontologie
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy
from .models import *
from .forms import *
from .decorators import user_is_medecin


'''
        
        for class_name in self.classes.keys():
            if class_name in ['Thing']:
                continue
            
            snake_name = self.camel_to_snake(class_name)
            form_name = f"{class_name}Form"
            
            # Vue ListView
            views_code += f"@login_required\n"
            views_code += f"def {snake_name}_list(request):\n"
            views_code += f"    \"\"\"{class_name}s list view\"\"\"\n"
            views_code += f"    {snake_name}s = {class_name}.objects.all()\n"
            views_code += f"    return render(request, '{self.app_name}/{snake_name}_list.html', {{\n"
            views_code += f"        '{snake_name}s': {snake_name}s,\n"
            views_code += f"    }})\n\n"
            
            # Vue DetailView
            views_code += f"@login_required\n"
            views_code += f"def {snake_name}_detail(request, pk):\n"
            views_code += f"    \"\"\"{class_name} detail view\"\"\"\n"
            views_code += f"    {snake_name} = get_object_or_404({class_name}, pk=pk)\n"
            views_code += f"    return render(request, '{self.app_name}/{snake_name}_detail.html', {{\n"
            views_code += f"        '{snake_name}': {snake_name},\n"
            views_code += f"    }})\n\n"
            
            # Vue CreateView
            views_code += f"@login_required\n"
            views_code += f"def {snake_name}_create(request):\n"
            views_code += f"    \"\"\"{class_name} create view\"\"\"\n"
            views_code += f"    if request.method == 'POST':\n"
            views_code += f"        form = {form_name}(request.POST)\n"
            views_code += f"        if form.is_valid():\n"
            views_code += f"            {snake_name} = form.save()\n"
            views_code += f"            return redirect('{snake_name}_detail', pk={snake_name}.pk)\n"
            views_code += f"    else:\n"
            views_code += f"        form = {form_name}()\n"
            views_code += f"    return render(request, '{self.app_name}/{snake_name}_form.html', {{\n"
            views_code += f"        'form': form,\n"
            views_code += f"        'action': 'Create',\n"
            views_code += f"    }})\n\n"
            
            # Vue UpdateView
            views_code += f"@login_required\n"
            views_code += f"def {snake_name}_update(request, pk):\n"
            views_code += f"    \"\"\"{class_name} update view\"\"\"\n"
            views_code += f"    {snake_name} = get_object_or_404({class_name}, pk=pk)\n"
            views_code += f"    if request.method == 'POST':\n"
            views_code += f"        form = {form_name}(request.POST, instance={snake_name})\n"
            views_code += f"        if form.is_valid():\n"
            views_code += f"            {snake_name} = form.save()\n"
            views_code += f"            return redirect('{snake_name}_detail', pk={snake_name}.pk)\n"
            views_code += f"    else:\n"
            views_code += f"        form = {form_name}(instance={snake_name})\n"
            views_code += f"    return render(request, '{self.app_name}/{snake_name}_form.html', {{\n"
            views_code += f"        'form': form,\n"
            views_code += f"        'action': 'Update',\n"
            views_code += f"        '{snake_name}': {snake_name},\n"
            views_code += f"    }})\n\n"
            
            # Vue DeleteView
            views_code += f"@login_required\n"
            views_code += f"def {snake_name}_delete(request, pk):\n"
            views_code += f"    \"\"\"{class_name} delete view\"\"\"\n"
            views_code += f"    {snake_name} = get_object_or_404({class_name}, pk=pk)\n"
            views_code += f"    if request.method == 'POST':\n"
            views_code += f"        {snake_name}.delete()\n"
            views_code += f"        return redirect('{snake_name}_list')\n"
            views_code += f"    return render(request, '{self.app_name}/{snake_name}_confirm_delete.html', {{\n"
            views_code += f"        '{snake_name}': {snake_name},\n"
            views_code += f"    }})\n\n"
        
        return views_code
    
    def generate_urls(self) -> str:
        """Génère les URLs Django"""
        urls_code = '''"""
URLs générées automatiquement à partir de l'ontologie
"""

from django.urls import path
from . import views

app_name = 'hopital'

urlpatterns = [
'''
        
        for class_name in self.classes.keys():
            if class_name in ['Thing']:
                continue
            
            snake_name = self.camel_to_snake(class_name)
            urls_code += f"    # {class_name} URLs\n"
            urls_code += f"    path('{snake_name}/', views.{snake_name}_list, name='{snake_name}_list'),\n"
            urls_code += f"    path('{snake_name}/<int:pk>/', views.{snake_name}_detail, name='{snake_name}_detail'),\n"
            urls_code += f"    path('{snake_name}/create/', views.{snake_name}_create, name='{snake_name}_create'),\n"
            urls_code += f"    path('{snake_name}/<int:pk>/update/', views.{snake_name}_update, name='{snake_name}_update'),\n"
            urls_code += f"    path('{snake_name}/<int:pk>/delete/', views.{snake_name}_delete, name='{snake_name}_delete'),\n"
            urls_code += f"\n"
        
        urls_code += "]\n"
        return urls_code
    
    def generate_template_list(self, class_name: str) -> str:
        """Génère un template liste"""
        snake_name = self.camel_to_snake(class_name)
        plural = f"{snake_name}s"
        
        return f'''{% extends "main.html" %}
{% load static %}

{{% block content %}}
<div class="container mt-5">
    <div class="row mb-4">
        <div class="col-md-8">
            <h2>{class_name}s</h2>
        </div>
        <div class="col-md-4 text-end">
            <a href="{{% url '{snake_name}_create' %}}" class="btn btn-primary">
                <i class="bi bi-plus-circle"></i> Nouveau {class_name}
            </a>
        </div>
    </div>

    {{% if {plural}|length > 0 %}}
        <div class="table-responsive">
            <table class="table table-striped table-hover">
                <thead class="table-dark">
                    <tr>
                        <th>ID</th>
                        <th>Date d'ajout</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {{% for item in {plural} %}}
                    <tr>
                        <td>{{{{ item.id }}}}</td>
                        <td>{{{{ item.created_at|date:"d/m/Y" }}}}</td>
                        <td>
                            <a href="{{% url '{snake_name}_detail' item.pk %}}" class="btn btn-sm btn-info">
                                <i class="bi bi-eye"></i> Voir
                            </a>
                            <a href="{{% url '{snake_name}_update' item.pk %}}" class="btn btn-sm btn-warning">
                                <i class="bi bi-pencil"></i> Modifier
                            </a>
                            <a href="{{% url '{snake_name}_delete' item.pk %}}" class="btn btn-sm btn-danger">
                                <i class="bi bi-trash"></i> Supprimer
                            </a>
                        </td>
                    </tr>
                    {{% endfor %}}
                </tbody>
            </table>
        </div>
    {{% else %}}
        <div class="alert alert-warning">
            Aucun {class_name} trouvé. <a href="{{% url '{snake_name}_create' %}}">Créer un nouveau</a>
        </div>
    {{% endif %}}
</div>
{{% endblock %}}
'''
    
    def generate_template_detail(self, class_name: str) -> str:
        """Génère un template détail"""
        snake_name = self.camel_to_snake(class_name)
        
        return f'''{% extends "main.html" %}
{% load static %}

{{% block content %}}
<div class="container mt-5">
    <div class="row mb-4">
        <div class="col-md-8">
            <h2>Détail {class_name}</h2>
        </div>
        <div class="col-md-4 text-end">
            <a href="{{% url '{snake_name}_update' {snake_name}.pk %}}" class="btn btn-warning">
                <i class="bi bi-pencil"></i> Modifier
            </a>
            <a href="{{% url '{snake_name}_list' %}}" class="btn btn-secondary">
                <i class="bi bi-arrow-left"></i> Retour
            </a>
        </div>
    </div>

    <div class="card">
        <div class="card-body">
            <dl class="row">
                <dt class="col-sm-3">ID:</dt>
                <dd class="col-sm-9">{{{{ {snake_name}.id }}}}</dd>

                <dt class="col-sm-3">Créé le:</dt>
                <dd class="col-sm-9">{{{{ {snake_name}.created_at|date:"d/m/Y H:i" }}}}</dd>

                <dt class="col-sm-3">Modifié le:</dt>
                <dd class="col-sm-9">{{{{ {snake_name}.updated_at|date:"d/m/Y H:i" }}}}</dd>
            </dl>
        </div>
    </div>

    <div class="mt-4">
        <a href="{{% url '{snake_name}_delete' {snake_name}.pk %}}" class="btn btn-danger">
            <i class="bi bi-trash"></i> Supprimer
        </a>
    </div>
</div>
{{% endblock %}}
'''
    
    def generate_template_form(self, class_name: str) -> str:
        """Génère un template formulaire"""
        snake_name = self.camel_to_snake(class_name)
        
        return f'''{% extends "main.html" %}
{% load static %}

{{% block content %}}
<div class="container mt-5">
    <div class="row mb-4">
        <div class="col-md-12">
            <h2>{{{{ action }}}} {class_name}</h2>
        </div>
    </div>

    <div class="row">
        <div class="col-md-6">
            <form method="post" class="needs-validation" novalidate>
                {{% csrf_token %}}
                
                {{% for field in form %}}
                    <div class="mb-3">
                        {{{{ field.label_tag }}}}
                        {{{{ field }}}}
                        {{% if field.errors %}}
                            <div class="invalid-feedback d-block">
                                {{{{ field.errors }}}}
                            </div>
                        {{% endif %}}
                    </div>
                {{% endfor %}}

                <div class="mt-4">
                    <button type="submit" class="btn btn-success">
                        <i class="bi bi-check-circle"></i> Enregistrer
                    </button>
                    <a href="{{% url '{snake_name}_list' %}}" class="btn btn-secondary">
                        <i class="bi bi-x-circle"></i> Annuler
                    </a>
                </div>
            </form>
        </div>
    </div>
</div>
{{% endblock %}}
'''
    
    def generate_all(self, output_dir: str = None):
        """Génère tous les fichiers"""
        if output_dir is None:
            output_dir = os.path.dirname(self.ontology_path)
        
        self.load_ontology()
        
        output = {
            'models_generated.py': self.generate_models(),
            'forms_generated.py': self.generate_forms(),
            'views_generated.py': self.generate_views(),
            'urls_generated.py': self.generate_urls(),
        }
        
        # Génère les templates
        templates_dir = os.path.join(output_dir, '..', 'hopital', 'templates', 'hopital', 'generated')
        os.makedirs(templates_dir, exist_ok=True)
        
        for class_name in self.classes.keys():
            if class_name in ['Thing']:
                continue
            
            snake_name = self.camel_to_snake(class_name)
            
            with open(os.path.join(templates_dir, f'{snake_name}_list.html'), 'w', encoding='utf-8') as f:
                f.write(self.generate_template_list(class_name))
            
            with open(os.path.join(templates_dir, f'{snake_name}_detail.html'), 'w', encoding='utf-8') as f:
                f.write(self.generate_template_detail(class_name))
            
            with open(os.path.join(templates_dir, f'{snake_name}_form.html'), 'w', encoding='utf-8') as f:
                f.write(self.generate_template_form(class_name))
        
        # Sauvegarde les fichiers Python
        for filename, content in output.items():
            filepath = os.path.join(output_dir, filename)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"✓ Généré: {filepath}")
        
        print(f"✓ Templates générés dans: {templates_dir}")
        print("\n" + "=" * 60)
        print("GÉNÉRATION TERMINÉE!")
        print("=" * 60)
        
        print("\nFichiers générés:")
        for filename in output.keys():
            print(f"  - {filename}")
        
        print(f"\n✓ {len(self.classes)} classes trouvées dans l'ontologie")
        print(f"✓ {len(self.data_properties)} propriétés de données")
        print(f"✓ {len(self.object_properties)} propriétés d'objets")


if __name__ == '__main__':
    # Exemple d'utilisation
    generator = OntologyToWebGenerator(
        'ontologies/onto.owl',
        app_name='hopital'
    )
    
    generator.generate_all('ontologies')
