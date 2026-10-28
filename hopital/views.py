import json
import os
import re
import traceback
import xml.etree.ElementTree as ET

import builtins as _builtins
import unicodedata

_ORIGINAL_PRINT = _builtins.print

def _safe_ascii_text(value):
    try:
        text = str(value)
        text = unicodedata.normalize("NFKD", text)
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        text = text.replace("’", "'").replace("‘", "'")
        text = text.replace("“", '"').replace("”", '"')
        text = text.replace("→", "->").replace("⚠", "ATTENTION")
        return text.encode("ascii", "ignore").decode("ascii")
    except Exception:
        return str(value).encode("ascii", "ignore").decode("ascii")

def print(*args, **kwargs):
    args = tuple(_safe_ascii_text(a) for a in args)
    return _ORIGINAL_PRINT(*args, **kwargs)

def _safe_print_exception():
    print(traceback.format_exc())


from django.shortcuts import render, redirect
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.models import User
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.db import models as dj_models
from django.db.models.fields import NOT_PROVIDED
from django.urls import reverse
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST   # CORRECTION : garde HTTP propre

from .decorators import *
from .models import *
from django.utils import timezone
from django.utils.text import slugify
from .forms import *
from owlready2 import *
from .nlp_engine import analyser_texte, parse_swrl_rules_from_owl, reload_ontology_rules, ONTO_PATH

onto = get_ontology("ontologies/onto.owl").load()


# ──────────────────────────────────────────────────────────────
# AUTH
# ──────────────────────────────────────────────────────────────

def index(request):
    return render(request, "hopital/home.html")


def loginPage(request):
    if request.user.is_authenticated:
        if request.user.groups.filter(name='Patient').exists():
            patient = Patient.objects.get(user=request.user)
            return redirect('patient_detail', id=patient.id)
        else:
            return redirect('index')

    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']
        if username and password:
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                messages.error(request, "Utilisateur n'existe pas.")
            else:
                user = authenticate(request, username=username, password=password)
                if user is not None:
                    login(request, user)
                    messages.success(request, "Connexion réussie. Bienvenue sur la plateforme médicale.")
                    if user.groups.filter(name='Patient').exists():
                        patient = Patient.objects.get(user=user)
                        return redirect('patient_detail', id=patient.id)
                    else:
                        return redirect('index')
                else:
                    messages.error(request, "Nom d’utilisateur ou mot de passe incorrect.")
        else:
            messages.error(request, "Veuillez remplir tous les champs.")

    return render(request, 'hopital/login.html')


def logoutUser(request):
    logout(request)
    messages.info(request, "Vous avez été déconnecté avec succès.")
    return redirect('login')









# ──────────────────────────────────────────────────────────────
# ADMIN — RÈGLES DE L'ONTOLOGIE : CRUD XML FIABLE, SANS DOUBLON
# ──────────────────────────────────────────────────────────────

_ONTOLOGY_CONDITION_CHOICES = [
    ('symptome', 'Symptôme'),
    ('signe', 'Signe clinique'),
    ('examcli', 'Examen clinique'),
    ('efr', 'EFR / exploration fonctionnelle respiratoire'),
    ('radio', 'Radiographie'),
    ('tdm', 'TDM / scanner thoracique'),
    ('angioscanner', 'Angioscanner'),
    ('biologie', 'Biologie'),
    ('testLab', 'Test de laboratoire'),
    ('testGenetique', 'Test génétique'),
    ('atopie', 'Atopie'),
    ('antFam', 'Antécédent familial'),
    ('antPers', 'Antécédent personnel'),
    ('habitVie', 'Habitudes de vie'),
    ('exposition', 'Exposition'),
    ('facteurRisque', 'Facteur de risque'),
    ('immunosuppression', 'Immunosuppression'),
    ('dureeSymptomes', 'Durée des symptômes'),
]

_PATHOLOGY_DISPLAY = {
    'Asthme': 'Asthme',
    'AsthmeSevereInd': 'Asthme sévère',
    'BPCO': 'BPCO',
    'BronchiteChroniqueInd': 'Bronchite chronique',
    'COVID19SevereInd': 'COVID-19 sévère',
    'DDB': 'Dilatation des bronches',
    'EmboliePulmonaireInd': 'Embolie pulmonaire',
    'FibroseKystiqueInd': 'Fibrose kystique',
    'FibrosePulmonaireIdiopathiqueInd': 'Fibrose pulmonaire idiopathique',
    'InfectionOpportunisteInd': 'Infection opportuniste',
    'InfectionViralePulmonaireInd': 'Infection virale pulmonaire',
    'OedemePulmonaireCardiogeniqueInd': 'Œdème pulmonaire cardiogénique',
    'OedemePulmonaireNonCardiogeniqueInd': 'Œdème pulmonaire non cardiogénique',
    'PneumonieBacterienneInd': 'Pneumonie bactérienne',
    'PneumonieInd': 'Pneumonie',
    'PneumonieViraleInd': 'Pneumonie virale',
    'PneumopathieHypersensibiliteInd': "Pneumopathie d’hypersensibilité",
    'PneumopathieInterstitielleNonSpecifiqueInd': 'Pneumopathie interstitielle non spécifique',
    'PneumothoraxInd': 'Pneumothorax',
    'SarcoidosePulmonaireInd': 'Sarcoïdose pulmonaire',
    'SyndromeApneeSommeilInd': "Syndrome d’apnée du sommeil",
    'fibpul': 'Fibrose pulmonaire',
    'tuberculose': 'Tuberculose pulmonaire',
}

_RDF = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'
_RDFS = 'http://www.w3.org/2000/01/rdf-schema#'
_OWL = 'http://www.w3.org/2002/07/owl#'
_SWRL = 'http://www.w3.org/2003/11/swrl#'
_SWRL2 = 'http://swrl.stanford.edu/ontologies/3.3/swrla.owl#'
_XSD = 'http://www.w3.org/2001/XMLSchema#'
_DONTO_BASE = 'http://www.semanticweb.org/domo/ontologies/2023/4/D-ONTO#'

_DISPLAY_NAMES_FILE = os.path.join(os.path.dirname(__file__), 'ontology_display_names.json')


def _register_owl_namespaces():
    ET.register_namespace('rdf', _RDF)
    ET.register_namespace('rdfs', _RDFS)
    ET.register_namespace('owl', _OWL)
    ET.register_namespace('swrl', _SWRL)
    ET.register_namespace('swrl2', _SWRL2)
    ET.register_namespace('xsd', _XSD)


def _local_tag(node_or_tag):
    tag = node_or_tag.tag if hasattr(node_or_tag, 'tag') else str(node_or_tag)
    return tag.split('}')[-1]


def _tag_namespace(node_or_tag):
    tag = node_or_tag.tag if hasattr(node_or_tag, 'tag') else str(node_or_tag)
    if tag.startswith('{') and '}' in tag:
        return tag[1:].split('}', 1)[0]
    return ''


def _condition_label(prop_name):
    return dict(_ONTOLOGY_CONDITION_CHOICES).get(prop_name, prop_name)


def _safe_rule_name(name):
    name = str(name or '').strip()
    name = name.replace('œ', 'oe').replace('Œ', 'Oe')
    return re.sub(r'[^A-Za-z0-9_]+', '_', name).strip('_')


def _local_iri(value):
    value = str(value or '').strip()
    value = value.replace('"', '').replace("'", '')
    value = re.sub(r'\^\^.*$', '', value).strip()
    value = re.sub(r'\s*\(instance\)\s*$', '', value, flags=re.I)
    if '#' in value:
        value = value.split('#')[-1]
    if '/' in value:
        value = value.rstrip('/').split('/')[-1]
    if value.startswith('onto.'):
        value = value.split('.', 1)[1]
    if value.startswith('urn:swrl#'):
        value = value.split('#')[-1]
    return value.strip()


def _clean_medical_display(value):
    value = str(value or '').strip()
    value = re.sub(r'\s*\(instance\)\s*$', '', value, flags=re.I)
    value = value.replace('_', ' ')
    value = re.sub(r'\s+', ' ', value).strip()
    return value


def _pretty_identifier(value):
    value = _local_iri(value)
    if not value:
        return ''
    if value in _PATHOLOGY_DISPLAY:
        return _PATHOLOGY_DISPLAY[value]
    value = re.sub(r'Ind$', '', value)
    value = re.sub(r'([a-zà-ÿ])([A-Z])', r'\1 \2', value)
    return _clean_medical_display(value)


def _load_interface_display_names():
    try:
        if os.path.exists(_DISPLAY_NAMES_FILE):
            with open(_DISPLAY_NAMES_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"[ONTOLOGY ADMIN] Lecture ontology_display_names.json impossible : {e}")
    return {}


def _save_interface_display_name(pathologie_id, display_name):
    pathologie_id = _local_iri(pathologie_id)
    display_name = _clean_medical_display(display_name)

    if not pathologie_id or not display_name:
        return

    data = _load_interface_display_names()
    data[pathologie_id] = display_name

    try:
        with open(_DISPLAY_NAMES_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[ONTOLOGY ADMIN] Écriture ontology_display_names.json impossible : {e}")


def _ontology_tree():
    _register_owl_namespaces()
    return ET.parse(ONTO_PATH)


def _save_ontology_tree(tree):
    _register_owl_namespaces()
    tree.write(ONTO_PATH, encoding='utf-8', xml_declaration=True)

    # Garde le moteur NLP synchronisé avec le fichier modifié.
    try:
        reload_ontology_rules(force=True)
    except Exception as e:
        print(f"[ONTOLOGY ADMIN] Reload NLP ignoré : {e}")

    # Évite que l'objet global Owlready2 écrase ensuite les règles modifiées.
    try:
        global onto
        onto.load(reload=True)
    except Exception as e:
        print(f"[ONTOLOGY ADMIN] Reload OWLReady ignoré : {e}")


def _child(node, local_name):
    if node is None:
        return None
    for child in list(node):
        if _local_tag(child) == local_name:
            return child
    return None


def _children(node, local_name):
    if node is None:
        return []
    return [c for c in list(node) if _local_tag(c) == local_name]


def _node_text(node):
    if node is not None and (node.text or '').strip():
        return node.text.strip()
    return ''


def _get_owl_label(local_name, root=None):
    try:
        if root is None:
            root = _ontology_tree().getroot()
        for el in root.iter():
            about = el.get(f'{{{_RDF}}}about', '') or el.get(f'{{{_RDF}}}ID', '')
            if _local_iri(about) != _local_iri(local_name):
                continue
            for child in el:
                if child.tag == f'{{{_RDFS}}}label' and (child.text or '').strip():
                    return child.text.strip()
    except Exception:
        pass
    return ''


def _pathology_display(pathologie_id, root=None):
    local = _local_iri(pathologie_id)
    if not local:
        return ''

    custom = _load_interface_display_names().get(local, '')
    if custom:
        return _clean_medical_display(custom)

    label = _get_owl_label(local, root=root)
    if label:
        return _clean_medical_display(label)

    return _clean_medical_display(_PATHOLOGY_DISPLAY.get(local, _pretty_identifier(local)))


def _pathology_label_from_id(pathologie_id):
    return _pathology_display(pathologie_id) or _pretty_identifier(pathologie_id) or _local_iri(pathologie_id)


def _is_rule_element(el):
    # Forme 1 : <swrl:Imp>...</swrl:Imp>
    if _tag_namespace(el) == _SWRL and _local_tag(el) == 'Imp':
        return True

    # Forme 2 : <owl:NamedIndividual rdf:about="#x"><rdf:type rdf:resource="...swrl#Imp"/>
    # Forme 3 : <rdf:Description rdf:about="#x"><rdf:type rdf:resource="...swrl#Imp"/>
    for child in list(el):
        if _local_tag(child) == 'type':
            res = child.get(f'{{{_RDF}}}resource', '')
            if res == f'{_SWRL}#Imp' or _local_iri(res) == 'Imp':
                return True
    return False


def _iter_rule_elements(root):
    return [el for el in list(root) if _is_rule_element(el)]


def _rule_raw_name(el):
    return _local_iri(
        el.get(f'{{{_RDF}}}about', '')
        or el.get(f'{{{_RDF}}}ID', '')
        or el.get(f'{{{_RDF}}}nodeID', '')
    )


def _rule_label_comment(el):
    label = ''
    comment = ''
    for child in list(el):
        if child.tag == f'{{{_RDFS}}}label' and (child.text or '').strip():
            label = child.text.strip()
        elif child.tag == f'{{{_RDFS}}}comment' and (child.text or '').strip():
            comment = child.text.strip()
    return label, comment


def _extract_rule_name(el, index):
    raw_name = _rule_raw_name(el)
    label, comment = _rule_label_comment(el)

    display = label or raw_name or f"Règle clinique #{index + 1}"

    if raw_name:
        key = f"name__{raw_name}"
    else:
        key = f"idx__{index}"

    return display, key, raw_name, comment


def _build_node_map(root):
    mapping = {}
    for el in root.iter():
        node_id = el.get(f'{{{_RDF}}}nodeID')
        if node_id:
            mapping[node_id] = el
        about = el.get(f'{{{_RDF}}}about')
        if about:
            mapping[_local_iri(about)] = el
        rdf_id = el.get(f'{{{_RDF}}}ID')
        if rdf_id:
            mapping[_local_iri(rdf_id)] = el
    return mapping


def _resolve_ref(container, node_map):
    if container is None:
        return None

    node_id = container.get(f'{{{_RDF}}}nodeID')
    if node_id and node_id in node_map:
        return node_map[node_id]

    resource = container.get(f'{{{_RDF}}}resource')
    if resource:
        return node_map.get(_local_iri(resource))

    children = list(container)
    if children:
        return children[0]

    return container


def _node_value(node, node_map=None):
    if node is None:
        return ''

    if (node.text or '').strip():
        return node.text.strip()

    resource = node.get(f'{{{_RDF}}}resource')
    if resource:
        return _local_iri(resource)

    node_id = node.get(f'{{{_RDF}}}nodeID')
    if node_id:
        return _local_iri(node_id)

    child = _resolve_ref(node, node_map or {})
    if child is not None and child is not node:
        return _node_value(child, node_map)

    about = node.get(f'{{{_RDF}}}about') or node.get(f'{{{_RDF}}}ID')
    if about:
        return _local_iri(about)

    return ''


def _parse_atom(atom, node_map):
    if atom is None:
        return None

    tag = _local_tag(atom)

    if tag == 'ClassAtom':
        pred = _node_value(_child(atom, 'classPredicate'), node_map)
        arg1 = _node_value(_child(atom, 'argument1'), node_map)
        return {'kind': 'class', 'prop': pred, 'value': arg1}

    if tag in {'IndividualPropertyAtom', 'DatavaluedPropertyAtom'}:
        pred = _node_value(_child(atom, 'propertyPredicate'), node_map)
        arg2 = _node_value(_child(atom, 'argument2'), node_map)
        return {'kind': 'property', 'prop': pred, 'value': arg2}

    if tag == 'BuiltinAtom':
        pred = _node_value(_child(atom, 'builtin'), node_map)
        return {'kind': 'builtin', 'prop': pred, 'value': ''}

    for child in list(atom):
        parsed = _parse_atom(child, node_map)
        if parsed:
            return parsed

    return None


def _parse_atom_list_from_container(container, node_map, depth=0):
    if container is None or depth > 1000:
        return []

    node = _resolve_ref(container, node_map)
    if node is None:
        return []

    if _local_tag(node) not in {'AtomList', 'Description'}:
        lists = [c for c in list(node) if _local_tag(c) in {'AtomList', 'Description'}]
        if lists:
            node = lists[0]
        else:
            if _child(node, 'first') is None:
                return []

    atoms = []

    first_container = _child(node, 'first')
    first_node = _resolve_ref(first_container, node_map)
    if first_node is not None:
        parsed = _parse_atom(first_node, node_map)
        if parsed:
            atoms.append(parsed)

    rest_container = _child(node, 'rest')
    if rest_container is None:
        return atoms

    rest_resource = rest_container.get(f'{{{_RDF}}}resource', '')
    if rest_resource and 'nil' in rest_resource:
        return atoms

    atoms.extend(_parse_atom_list_from_container(rest_container, node_map, depth + 1))
    return atoms


def _parse_rule_element(el, index, root, node_map):
    rule_name, key, raw_name, comment = _extract_rule_name(el, index)

    body_atoms = _parse_atom_list_from_container(_child(el, 'body'), node_map)
    head_atoms = _parse_atom_list_from_container(_child(el, 'head'), node_map)

    technical_props = {
        'Patient', 'Medecin', 'Dossier', 'aDossier', 'aPathologie',
        'type', 'rdf:type', 'greaterThanOrEqual', 'lessThanOrEqual',
        'differentFrom', 'sameAs'
    }
    variable_names = {'p', 'd', 'a', 'x', 'y', 'z', 's', 'v', 'valeur'}

    conditions = []
    seen = set()
    for atom in body_atoms:
        prop = _local_iri(atom.get('prop', ''))
        value = _local_iri(atom.get('value', ''))

        if not prop or prop in technical_props:
            continue
        if not value or value.startswith('?') or value in variable_names:
            continue

        pair = (prop, value)
        if pair in seen:
            continue
        seen.add(pair)

        conditions.append({
            'prop': prop,
            'label': _condition_label(prop),
            'value': value,
        })

    pathologie_id = ''
    for atom in head_atoms:
        prop = _local_iri(atom.get('prop', ''))
        value = _local_iri(atom.get('value', ''))
        if prop == 'aPathologie' and value:
            pathologie_id = value
            break

    return {
        'key': key,
        'name': rule_name,
        'real_name': raw_name,
        'comment': comment,
        'pathologie': pathologie_id,
        'pathologie_display': _pathology_display(pathologie_id, root=root),
        'conditions': conditions,
    }


def _load_existing_ontology_rules():
    """
    Lecture unique depuis onto.owl.
    Affiche TOUTES les règles, y compris :
    - <swrl:Imp>
    - <owl:NamedIndividual rdf:type="swrl:Imp">
    """
    try:
        tree = _ontology_tree()
        root = tree.getroot()
        node_map = _build_node_map(root)

        rules = []
        for i, el in enumerate(_iter_rule_elements(root)):
            rules.append(_parse_rule_element(el, i, root, node_map))
        return rules
    except Exception as e:
        _safe_print_exception()
        print(f"[ONTOLOGY ADMIN] Lecture des règles impossible : {e}")
        return []


def _find_rule_element(root, rule_key):
    rules = _iter_rule_elements(root)

    rule_key = str(rule_key or '').strip()
    if rule_key.startswith('name__'):
        target = rule_key.replace('name__', '', 1)
        for el in rules:
            if _rule_raw_name(el) == target:
                return el

    if rule_key.startswith('idx__'):
        try:
            idx = int(rule_key.replace('idx__', '', 1))
            if 0 <= idx < len(rules):
                return rules[idx]
        except Exception:
            pass

    return None


def _parent_of(root, target):
    for parent in root.iter():
        for child in list(parent):
            if child is target:
                return parent
    return None


def _get_rule_dict_by_key(rule_key):
    for rule in _load_existing_ontology_rules():
        if rule.get('key') == rule_key:
            return rule
    return None


def _rdf_resource(parent, tag, resource):
    el = ET.SubElement(parent, tag)
    el.set(f'{{{_RDF}}}resource', resource)
    return el


def _literal(parent, tag, text):
    el = ET.SubElement(parent, tag)
    el.set(f'{{{_RDF}}}datatype', f'{_XSD}string')
    el.text = str(text)
    return el


def _class_atom(class_name, variable):
    atom = ET.Element(f'{{{_SWRL}}}ClassAtom')
    _rdf_resource(atom, f'{{{_SWRL}}}classPredicate', f'#{_local_iri(class_name)}')
    _rdf_resource(atom, f'{{{_SWRL}}}argument1', f'#{_local_iri(variable)}')
    return atom


def _individual_property_atom(prop_name, arg1, arg2):
    atom = ET.Element(f'{{{_SWRL}}}IndividualPropertyAtom')
    _rdf_resource(atom, f'{{{_SWRL}}}propertyPredicate', f'#{_local_iri(prop_name)}')
    _rdf_resource(atom, f'{{{_SWRL}}}argument1', f'#{_local_iri(arg1)}')
    _rdf_resource(atom, f'{{{_SWRL}}}argument2', f'#{_local_iri(arg2)}')
    return atom


def _data_property_atom(prop_name, arg1, value):
    atom = ET.Element(f'{{{_SWRL}}}DatavaluedPropertyAtom')
    _rdf_resource(atom, f'{{{_SWRL}}}propertyPredicate', f'#{_local_iri(prop_name)}')
    _rdf_resource(atom, f'{{{_SWRL}}}argument1', f'#{_local_iri(arg1)}')
    _literal(atom, f'{{{_SWRL}}}argument2', value)
    return atom


def _atom_list(atoms):
    """
    Crée toujours les listes SWRL sous forme <swrl:AtomList>.

    Important :
    - Ajouter une règle utilise cette fonction.
    - Modifier une règle utilise aussi cette fonction.
    - Donc les nouvelles règles ne seront plus enregistrées sous <rdf:Description>.
    """
    if not atoms:
        empty = ET.Element(f'{{{_SWRL}}}AtomList')
        ET.SubElement(empty, f'{{{_RDF}}}rest').set(f'{{{_RDF}}}resource', f'{_RDF}nil')
        return empty

    node = ET.Element(f'{{{_SWRL}}}AtomList')
    first = ET.SubElement(node, f'{{{_RDF}}}first')
    first.append(atoms[0])

    rest = ET.SubElement(node, f'{{{_RDF}}}rest')
    if len(atoms) == 1:
        rest.set(f'{{{_RDF}}}resource', f'{_RDF}nil')
    else:
        rest.append(_atom_list(atoms[1:]))

    return node


def _build_rule_atoms(pathologie_id, conditions):
    body_atoms = [
        _class_atom('Patient', 'p'),
        _individual_property_atom('aDossier', 'p', 'd'),
    ]

    for prop_name, value in conditions:
        body_atoms.append(_data_property_atom(prop_name, 'd', value))

    head_atoms = [
        _individual_property_atom('aPathologie', 'p', pathologie_id)
    ]

    return body_atoms, head_atoms


def _ensure_swrl_variables(root):
    existing = {
        _local_iri(el.get(f'{{{_RDF}}}about', ''))
        for el in root.iter()
        if _tag_namespace(el) == _SWRL and _local_tag(el) == 'Variable'
    }
    for var in ['p', 'd']:
        if var not in existing:
            v = ET.SubElement(root, f'{{{_SWRL}}}Variable')
            v.set(f'{{{_RDF}}}about', f'#{var}')


def _clear_rule_element(el):
    for child in list(el):
        el.remove(child)


def _rebuild_rule_element(el, rule_name, pathologie_id, conditions, comment):
    """
    Reconstruit le contenu d'une règle existante sans changer l'élément lui-même.
    Donc modifier = remplacer la même ligne OWL, pas ajouter une nouvelle règle.
    """
    tag_ns = _tag_namespace(el)
    tag_local = _local_tag(el)

    # Garder le même type d'élément, mais nettoyer ses enfants.
    _clear_rule_element(el)

    # Si c'est un owl:NamedIndividual/rdf:Description, il doit garder rdf:type swrl:Imp.
    if not (tag_ns == _SWRL and tag_local == 'Imp'):
        type_el = ET.SubElement(el, f'{{{_RDF}}}type')
        type_el.set(f'{{{_RDF}}}resource', f'{_SWRL}#Imp')

    body_atoms, head_atoms = _build_rule_atoms(pathologie_id, conditions)

    body = ET.SubElement(el, f'{{{_SWRL}}}body')
    body.append(_atom_list(body_atoms))

    head = ET.SubElement(el, f'{{{_SWRL}}}head')
    head.append(_atom_list(head_atoms))

    enabled = ET.SubElement(el, f'{{{_SWRL2}}}isRuleEnabled')
    enabled.set(f'{{{_RDF}}}datatype', f'{_XSD}boolean')
    enabled.text = 'true'

    label = ET.SubElement(el, f'{{{_RDFS}}}label')
    label.set(f'{{{_RDF}}}datatype', f'{_XSD}string')
    label.text = rule_name

    comment_el = ET.SubElement(el, f'{{{_RDFS}}}comment')
    comment_el.set(f'{{{_RDF}}}datatype', f'{_XSD}string')
    comment_el.text = comment


def _new_rule_element(rule_name, pathologie_id, conditions, comment):
    # Nouvelle règle propre : <swrl:Imp rdf:about="#nom">...</swrl:Imp>
    el = ET.Element(f'{{{_SWRL}}}Imp')
    el.set(f'{{{_RDF}}}about', f'#{rule_name}')
    _rebuild_rule_element(el, rule_name, pathologie_id, conditions, comment)
    return el


def _conditions_to_comment(pathologie_id, conditions):
    maladie = _pathology_label_from_id(pathologie_id)
    criteria = " + ".join([v for _p, v in conditions])
    return f"{maladie} : {criteria}" if criteria else maladie


def _rule_name_from_existing_or_new(el, fallback_label):
    raw = _rule_raw_name(el)
    if raw:
        return _safe_rule_name(raw)

    label, _comment = _rule_label_comment(el)
    if label:
        return _safe_rule_name(label)

    return _safe_rule_name(fallback_label) or f"regle_admin_{timezone.now().strftime('%Y%m%d%H%M%S')}"


def _unique_rule_name(root, base_name):
    names = {_rule_raw_name(el) for el in _iter_rule_elements(root)}
    name = _safe_rule_name(base_name) or f"regle_admin_{timezone.now().strftime('%Y%m%d%H%M%S')}"
    if name not in names:
        return name

    i = 2
    while f"{name}_{i}" in names:
        i += 1
    return f"{name}_{i}"


def _create_or_replace_rule(rule_key, pathologie, conditions, replace=False, display_name=''):
    pathologie_id = _local_iri(pathologie)
    if not pathologie_id:
        raise ValueError("Pathologie vide.")

    if display_name:
        _save_interface_display_name(pathologie_id, display_name)

    tree = _ontology_tree()
    root = tree.getroot()
    _ensure_swrl_variables(root)

    comment = _conditions_to_comment(pathologie_id, conditions)

    if replace:
        el = _find_rule_element(root, rule_key)
        if el is None:
            raise ValueError("Règle introuvable dans le fichier OWL.")

        old_rule = _get_rule_dict_by_key(rule_key)
        fallback = old_rule.get('real_name') or old_rule.get('name') or f"regle_admin_{_pathology_label_from_id(pathologie_id)}"
        rule_name = _rule_name_from_existing_or_new(el, fallback)

        _rebuild_rule_element(el, rule_name, pathologie_id, conditions, comment)
    else:
        timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
        base = f"regle_admin_{slugify(_pathology_label_from_id(pathologie_id), allow_unicode=False).replace('-', '_')}_{timestamp}"
        rule_name = _unique_rule_name(root, base)
        root.append(_new_rule_element(rule_name, pathologie_id, conditions, comment))

    _save_ontology_tree(tree)


def _delete_rule_by_key(rule_key):
    tree = _ontology_tree()
    root = tree.getroot()
    el = _find_rule_element(root, rule_key)
    if el is None:
        raise ValueError("Règle introuvable dans le fichier OWL.")

    parent = _parent_of(root, el)
    if parent is None:
        raise ValueError("Impossible de supprimer cette règle : parent XML introuvable.")

    parent.remove(el)
    _save_ontology_tree(tree)


def _collect_rule_form_data(request):
    pathologie = request.POST.get('pathologie', '').strip()
    pathologie_display_name = request.POST.get('pathologie_display_name', '').strip()

    props = request.POST.getlist('condition_property')
    values = request.POST.getlist('condition_value')

    valid_props = {value for value, _ in _ONTOLOGY_CONDITION_CHOICES}
    conditions = []
    seen = set()
    for prop_name, value in zip(props, values):
        prop_name = _local_iri(prop_name)
        value = str(value or '').strip()
        if prop_name in valid_props and value:
            pair = (prop_name, value)
            if pair not in seen:
                seen.add(pair)
                conditions.append(pair)

    return pathologie, pathologie_display_name, conditions


def _same_rule_conditions(old_conditions, new_conditions):
    old_pairs = [
        (_local_iri(c.get('prop', '')), str(c.get('value', '')).strip())
        for c in (old_conditions or [])
    ]
    new_pairs = [
        (_local_iri(p), str(v).strip())
        for p, v in (new_conditions or [])
    ]
    return old_pairs == new_pairs


def _add_term_choice(terms_by_category, category, value):
    category = str(category or '').strip()
    value = str(value or '').strip()
    if not category or not value or value.startswith('?'):
        return
    terms_by_category.setdefault(category, set()).add(value)


def _load_clinical_terms_by_category():
    terms_by_category = {}

    # 1) Termes déjà utilisés dans les règles.
    try:
        for rule in _load_existing_ontology_rules():
            for c in rule.get('conditions', []):
                _add_term_choice(terms_by_category, c.get('prop'), c.get('value'))
    except Exception as e:
        print(f"[ONTOLOGY ADMIN] Suggestions depuis règles impossibles : {e}")

    # 2) Termes génériques s'ils existent comme individus OWL.
    try:
        tree = _ontology_tree()
        root = tree.getroot()

        for ind in root.iter():
            category = ''
            values = []

            for child in list(ind):
                local = _local_tag(child)
                value = (child.text or '').strip()
                if not value:
                    value = _local_iri(child.get(f'{{{_RDF}}}resource', ''))

                if local in {'categorieClinique', 'categorie', 'category'}:
                    category = value
                elif local in {'termeCanonique', 'canonicalTerm', 'nomClinique', 'label', 'synonyme', 'synonym', 'variante', 'fauteFrequente'}:
                    values.append(value)

            if category:
                for v in values:
                    _add_term_choice(terms_by_category, category, v)

    except Exception as e:
        print(f"[ONTOLOGY ADMIN] Suggestions depuis individus OWL impossibles : {e}")

    return {
        cat: sorted(values, key=lambda x: x.lower())
        for cat, values in terms_by_category.items()
    }


def _load_pathology_choices():
    choices = {}

    try:
        tree = _ontology_tree()
        root = tree.getroot()

        for rule in _load_existing_ontology_rules():
            pid = _local_iri(rule.get('pathologie'))
            if pid:
                choices[pid] = _pathology_display(pid, root=root)

        for el in root.iter():
            about = _local_iri(el.get(f'{{{_RDF}}}about', '') or el.get(f'{{{_RDF}}}ID', ''))
            if not about:
                continue

            is_pathology = False
            for child in list(el):
                if _local_tag(child) == 'type':
                    res = _local_iri(child.get(f'{{{_RDF}}}resource', ''))
                    if res == 'Pathologie':
                        is_pathology = True
                        break

            if is_pathology:
                choices[about] = _pathology_display(about, root=root)

    except Exception as e:
        print(f"[ONTOLOGY ADMIN] Lecture des maladies impossible : {e}")

    for pid, label in _PATHOLOGY_DISPLAY.items():
        choices.setdefault(pid, label)

    return [
        {'id': pid, 'label': _clean_medical_display(label)}
        for pid, label in sorted(choices.items(), key=lambda x: str(x[1]).lower())
        if pid and label
    ]


@login_required
@superuser_required
def ontology_rules(request):
    if request.method == 'POST':
        pathologie, pathologie_display_name, conditions = _collect_rule_form_data(request)

        if not pathologie:
            messages.error(request, "Veuillez sélectionner la maladie réelle dans l’ontologie.")
        elif not conditions:
            messages.error(request, "Veuillez ajouter au moins un critère clinique.")
        else:
            try:
                _create_or_replace_rule(
                    None,
                    pathologie,
                    conditions,
                    replace=False,
                    display_name=pathologie_display_name,
                )
                messages.success(request, "La nouvelle règle a été ajoutée dans l’ontologie et affichée dans le tableau.")
                return redirect('ontology_rules')
            except Exception as e:
                _safe_print_exception()
                messages.error(request, f"Impossible d’ajouter la règle : {e}")

    return render(request, 'hopital/ontology_rules.html', {
        'condition_choices': _ONTOLOGY_CONDITION_CHOICES,
        'existing_rules': _load_existing_ontology_rules(),
        'pathology_choices': _load_pathology_choices(),
        'clinical_terms_json': json.dumps(_load_clinical_terms_by_category(), ensure_ascii=False),
    })


@login_required
@superuser_required
def ontology_rule_edit(request, rule_name):
    rule_dict = _get_rule_dict_by_key(rule_name)
    if rule_dict is None:
        messages.error(request, "Règle introuvable dans l’ontologie.")
        return redirect('ontology_rules')

    if request.method == 'POST':
        pathologie, pathologie_display_name, conditions = _collect_rule_form_data(request)
        if not pathologie:
            pathologie = rule_dict.get('pathologie', '')

        if not pathologie:
            messages.error(request, "Maladie réelle introuvable pour cette règle.")
        elif not conditions:
            messages.error(request, "Veuillez garder au moins un critère clinique.")
        else:
            try:
                same_pathology = _local_iri(pathologie) == _local_iri(rule_dict.get('pathologie', ''))
                same_conditions = _same_rule_conditions(rule_dict.get('conditions', []), conditions)

                # Nom d'affichage seulement : ne touche pas onto.owl.
                if same_pathology and same_conditions:
                    if pathologie_display_name:
                        _save_interface_display_name(pathologie, pathologie_display_name)
                    messages.success(request, "Nom affiché mis à jour. L’ontologie n’a pas été modifiée.")
                    return redirect('ontology_rules')

                # Critères changés : remplace l'élément XML de la même règle.
                _create_or_replace_rule(
                    rule_name,
                    pathologie,
                    conditions,
                    replace=True,
                    display_name=pathologie_display_name,
                )
                messages.success(request, "La règle a été modifiée sans créer de doublon.")
                return redirect('ontology_rules')

            except Exception as e:
                _safe_print_exception()
                messages.error(request, f"Impossible de modifier la règle : {e}")

    return render(request, 'hopital/ontology_rule_edit.html', {
        'condition_choices': _ONTOLOGY_CONDITION_CHOICES,
        'rule': rule_dict,
        'pathology_choices': _load_pathology_choices(),
        'clinical_terms_json': json.dumps(_load_clinical_terms_by_category(), ensure_ascii=False),
    })


@login_required
@superuser_required
@require_POST
def ontology_rule_delete(request, rule_name):
    try:
        _delete_rule_by_key(rule_name)
        messages.success(request, "La règle a été supprimée de l’ontologie.")
    except Exception as e:
        _safe_print_exception()
        messages.error(request, f"Impossible de supprimer la règle : {e}")

    return redirect('ontology_rules')




def create_medecin(request):
    if request.method == 'POST':
        form = MedecinForm(request.POST)
        if form.is_valid():
            medecin = form.save()
            id = medecin.id
            iri = f"http://www.semanticweb.org/domo/ontologies/2023/4/D-ONTO#medecin{id}"
            with onto:
                instance_medecin = onto.Medecin(iri=iri)
                instance_medecin.nom = [form.cleaned_data['nom']]
                instance_medecin.prenom = [form.cleaned_data['prenom']]
                instance_medecin.specialite = [form.cleaned_data['specialite']]
                instance_medecin.adresse = [form.cleaned_data['adresse']]
                instance_medecin.numero_telephone = [form.cleaned_data['numero_telephone']]
                instance_medecin.adresse_email = [form.cleaned_data['adresse_email']]
                sync_reasoner_pellet(infer_property_values=True, infer_data_property_values=True)
                onto.save(file="ontologies/onto.owl", format="rdfxml")
            messages.success(request, "Le médecin a été créé avec succès.")
            return redirect('medecin_list')
    else:
        form = MedecinForm()
    return render(request, 'hopital/register.html', {'form': form})


@login_required
def modifier_medecin(request, id):
    medecin = Medecin.objects.get(id=id)
    iri = f"http://www.semanticweb.org/domo/ontologies/2023/4/D-ONTO#medecin{id}"
    med = onto.search_one(iri=iri, type=onto.Medecin)
    if request.method == 'POST':
        form = MedecinUpdForm(request.POST, instance=medecin)
        if form.is_valid():
            form.save()
            med.nom = [form.cleaned_data['nom']]
            med.prenom = [form.cleaned_data['prenom']]
            med.specialite = [form.cleaned_data['specialite']]
            med.adresse = [form.cleaned_data['adresse']]
            med.numero_telephone = [form.cleaned_data['numero_telephone']]
            med.adresse_email = [form.cleaned_data['adresse_email']]
            with onto:
                sync_reasoner_pellet(infer_property_values=True, infer_data_property_values=True)
                onto.save(file="ontologies/onto.owl", format="rdfxml")
            messages.success(request, "Le profil du médecin a été mis à jour avec succès.")
            return redirect('medecin_list')
    else:
        form = MedecinUpdForm(instance=medecin)
    return render(request, 'hopital/modifier_medecin.html', {'form': form, 'medecin': medecin})


@login_required
@superuser_required
def supprimer_medecin(request, id):
    if request.method != 'POST':
        messages.warning(request, "Veuillez confirmer la suppression depuis le bouton prévu.")
        return redirect('medecin_list')

    medecin = Medecin.objects.get(id=id)
    iri = f"http://www.semanticweb.org/domo/ontologies/2023/4/D-ONTO#medecin{id}"
    med = onto.search_one(iri=iri, type=onto.Medecin)
    if med is not None:
        destroy_entity(med)
    with onto:
        sync_reasoner_pellet(infer_property_values=True, infer_data_property_values=True)
        onto.save(file="ontologies/onto.owl", format="rdfxml")
    user = User.objects.filter(username=medecin.user.username).first()
    medecin.delete()
    if user:
        user.delete()
    messages.success(request, "Le médecin a été supprimé avec succès.")
    return redirect('medecin_list')


@login_required
@superuser_required
def medecin_list(request):
    query = request.GET.get('q')
    medecins = Medecin.objects.all()
    if query:
        medecins = medecins.filter(Q(nom__icontains=query) | Q(prenom__icontains=query))
    paginator = Paginator(medecins, 5)
    resultat_page = paginator.get_page(request.GET.get('page'))
    return render(request, 'hopital/medecin_list.html', {
        'resultat_page': resultat_page,
        'query': query,
    })


# ──────────────────────────────────────────────────────────────
# PATIENT
# ──────────────────────────────────────────────────────────────

@login_required
@medecin_required
def create_patient(request):
    if request.method == 'POST':
        form = PatientForm(request.POST)
        if form.is_valid():
            patient = form.save()
            patient_iri = f"http://www.semanticweb.org/domo/ontologies/2023/4/D-ONTO#patient{patient.id}"
            with onto:
                instance_patient = onto.Patient(iri=patient_iri)
                instance_patient.nom_p = [form.cleaned_data['nom']]
                instance_patient.prenom_p = [form.cleaned_data['prenom']]
                instance_patient.date_naissance = [form.cleaned_data['date_naissance']]
                instance_patient.adresse_p = [form.cleaned_data['adresse']]
                instance_patient.numero_telephone_p = [form.cleaned_data['numero_telephone']]
                instance_patient.adresse_email_p = [form.cleaned_data['adresse_email']]
                instance_patient.sexe = [form.cleaned_data['sexe']]
                medecin_traitant = form.cleaned_data.get('medecin_traitant')
                if medecin_traitant:
                    medecin_iri = f"http://www.semanticweb.org/domo/ontologies/2023/4/D-ONTO#medecin{medecin_traitant.id}"
                    medecin_onto = onto.search_one(iri=medecin_iri, type=onto.Medecin)
                    if medecin_onto:
                        instance_patient.aMedecin = [medecin_onto]
                sync_reasoner_pellet(infer_property_values=True, infer_data_property_values=True)
                onto.save(file="ontologies/onto.owl", format="rdfxml")
            messages.success(request, "Le patient a été créé avec succès.")
            return redirect(reverse('patient_detail', args=[patient.id]))
    else:
        form = PatientForm()
    return render(request, 'hopital/creer_patient.html', {
        'form': form,
        'medecins': Medecin.objects.all(),
    })


@login_required
@medecin_required
def modifier_patient(request, id):
    patient = Patient.objects.get(id=id)
    iri = f"http://www.semanticweb.org/domo/ontologies/2023/4/D-ONTO#patient{id}"
    pat = onto.search_one(iri=iri, type=onto.Patient)
    if request.method == 'POST':
        form = PatientUpdForm(request.POST, instance=patient)
        if form.is_valid():
            form.save()
            pat.nom_p = [form.cleaned_data['nom']]
            pat.prenom_p = [form.cleaned_data['prenom']]
            pat.date_naissance = [form.cleaned_data['date_naissance']]
            pat.adresse_p = [form.cleaned_data['adresse']]
            pat.numero_telephone_p = [form.cleaned_data['numero_telephone']]
            pat.adresse_email_p = [form.cleaned_data['adresse_email']]
            with onto:
                sync_reasoner_pellet(infer_property_values=True, infer_data_property_values=True)
                onto.save(file="ontologies/onto.owl", format="rdfxml")
            messages.success(request, "Les informations du patient ont été mises à jour avec succès.")
            return redirect('patient_detail', id=id)
    else:
        form = PatientUpdForm(instance=patient)
    return render(request, 'hopital/modifier_patient.html', {
        'form': form,
        'medecins': Medecin.objects.all(),
        'patient': patient,
    })


@login_required
@medecin_required
def supprimer_patient(request, id):
    if request.method != 'POST':
        messages.warning(request, "Veuillez confirmer la suppression depuis le bouton prévu.")
        return redirect('patient_list')

    patient = Patient.objects.get(id=id)
    iri = f"http://www.semanticweb.org/domo/ontologies/2023/4/D-ONTO#patient{id}"
    pat = onto.search_one(iri=iri, type=onto.Patient)
    if pat is not None:
        destroy_entity(pat)
    with onto:
        sync_reasoner_pellet(infer_property_values=True, infer_data_property_values=True)
        onto.save(file="ontologies/onto.owl", format="rdfxml")
    user = User.objects.filter(username=patient.user.username).first()
    patient.delete()
    if user:
        user.delete()
    messages.success(request, "Le patient a été supprimé avec succès.")
    return redirect('patient_list')


@login_required
@medecin_required
def patient_list(request):
    if request.user.is_superuser:
        patients = Patient.objects.all()
    else:
        patients = Patient.objects.filter(medecin_traitant=request.user.medecin)
    query = request.GET.get('q')
    if query:
        patients = patients.filter(Q(nom__icontains=query) | Q(prenom__icontains=query))
    paginator = Paginator(patients, 5)
    resultat_page = paginator.get_page(request.GET.get('page'))
    return render(request, 'hopital/patient_list.html', {
        'resultat_page': resultat_page,
        'query': query,
    })


def _owl_values(obj, prop_name):
    """Retourne une data property OWL sous forme de texte propre."""
    if obj is None or not hasattr(obj, prop_name):
        return ''
    try:
        values = getattr(obj, prop_name)
    except Exception:
        return ''
    if values is None:
        return ''
    if isinstance(values, (list, tuple, set)):
        return ', '.join(str(v) for v in values if str(v).strip())
    return str(values).strip()


def _owl_entity_label(obj):
    """Retourne un nom lisible pour une classe/instance OWL, surtout les pathologies."""
    if obj is None:
        return ''
    try:
        labels = getattr(obj, 'label', [])
        if labels:
            return str(labels[0]).strip()
    except Exception:
        pass
    try:
        name = getattr(obj, 'name', '')
        if name:
            return str(name).replace('_', ' ').strip()
    except Exception:
        pass
    return str(obj).split('#')[-1].replace('_', ' ').strip()


def _patient_pathologies_text(patient_owl):
    """Pathologies inférées/attachées au patient dans onto.owl : patient.aPathologie."""
    if patient_owl is None or not hasattr(patient_owl, 'aPathologie'):
        return ''
    values = []
    try:
        for patho in list(patient_owl.aPathologie):
            label = _owl_entity_label(patho)
            if label and label not in values:
                values.append(label)
    except Exception:
        return ''
    return ', '.join(values)


def _set_db_field_if_exists(obj, field_name, value):
    """Affecte un champ Django seulement s'il existe dans le modèle."""
    if obj is not None and hasattr(obj, field_name) and value not in (None, ''):
        try:
            setattr(obj, field_name, value)
            obj.save(update_fields=[field_name])
        except Exception:
            try:
                obj.save()
            except Exception:
                pass


def _get_owl_dossier_for_db(patient_id, dossier_db):
    """Trouve l'instance OWL qui correspond à un Dossier Django."""
    if dossier_db is None:
        return None
    iri_unique = f"http://www.semanticweb.org/domo/ontologies/2023/4/D-ONTO#dossier{patient_id}_{dossier_db.id}"
    obj = onto.search_one(iri=iri_unique, type=onto.Dossier)
    if obj is not None:
        return obj
    # fallback ancien système, seulement si c'est le premier/ancien dossier
    iri_legacy = f"http://www.semanticweb.org/domo/ontologies/2023/4/D-ONTO#dossier{patient_id}"
    return onto.search_one(iri=iri_legacy, type=onto.Dossier)


def _value_from_db_or_owl(dossier_db, owl_dossier, field_name):
    """Prend d'abord la valeur DB, sinon fallback OWL."""
    db_val = getattr(dossier_db, field_name, '') if dossier_db is not None and hasattr(dossier_db, field_name) else ''
    if db_val not in (None, ''):
        return db_val
    return _owl_values(owl_dossier, field_name)



def _first_available_value(dossier_db, owl_dossier, field_names):
    """Retourne la première valeur existante parmi plusieurs noms possibles de champ."""
    for field_name in field_names:
        val = _value_from_db_or_owl(dossier_db, owl_dossier, field_name)
        if val not in (None, ''):
            return val
    return ''


def _build_text_from_dossier_item(item):
    """
    Construit un petit texte clinique à partir des champs d'un dossier.
    Utilisé uniquement si le dossier formulaire n'a pas encore une pathologie enregistrée.
    La déduction reste basée sur analyser_texte(), donc sur l'ontologie/règles NLP.
    """
    if not item:
        return ''
    parts = ["Le patient présente :"]

    def add(label, keys):
        vals = []
        for k in keys:
            v = item.get(k, '')
            if v not in (None, ''):
                vals.append(str(v).strip())
        if vals:
            parts.append(f"{label} : {', '.join(vals)}.")

    add("Facteurs de risque et habitudes de vie", ['habitVie'])
    add("Antécédents familiaux", ['antFam'])
    add("Antécédents personnels", ['antPers'])
    add("Atopie", ['atopie'])
    add("Symptômes", ['symptome'])
    add("Signes", ['signe'])
    add("Examen clinique", ['examcli'])
    add("EFR", ['efr'])
    add("TDM", ['tdm'])
    add("Radiographie", ['radio'])

    text = " ".join(parts).strip()
    # éviter d'analyser un texte vide qui contient seulement l'introduction
    return text if len(parts) > 1 else ''


def _infer_pathologie_from_dossier_item(item):
    """
    Déduit une pathologie pour l'affichage si elle manque dans le dossier.
    Important : ne remplace pas les données du dossier ; c'est un fallback d'affichage.
    Pour les nouveaux dossiers formulaire, tu peux ensuite l'enregistrer aussi si tu ajoutes
    un champ pathologie dans le modèle Dossier.
    """
    text = _build_text_from_dossier_item(item)
    if not text:
        return '', ''
    try:
        resultat = analyser_texte(text)
        best = resultat.get('meilleur_diagnostic') or {}
        patho = (best.get('pathologie') or '').strip()
        score = best.get('score') or best.get('confiance') or best.get('confidence') or ''

        # Fallback si meilleur_diagnostic n'est pas rempli mais que le tableau des scores existe.
        if not patho:
            scores = resultat.get('scores_regles') or []
            if scores:
                top = scores[0]
                patho = (top.get('pathologie') or '').strip()
                score = top.get('score') or score
        return patho, score
    except Exception as e:
        print(f"[PATIENT DETAIL] Inférence pathologie ignorée : {e}")
        return '', ''

def _guess_dossier_source(dossier_db, owl_dossier, item):
    """
    Détermine l'origine du dossier pour l'affichage.
    - Si le dossier contient un texte diagnostique ou une pathologie suggérée : diagnostic automatique.
    - Sinon : formulaire manuel.
    Cette fonction ne nécessite aucune migration ; elle utilise seulement les champs existants si présents.
    """
    text_fields = ('texte_original', 'texte_corrige', 'diagnostic_text', 'diagnostic_corrige')
    for field in text_fields:
        if dossier_db is not None and hasattr(dossier_db, field):
            val = getattr(dossier_db, field, '')
            if val not in (None, ''):
                return 'Diagnostic texte'

    if item.get('pathologie'):
        return 'Diagnostic texte'

    # Fallback OWL si un champ texte existe dans l'ontologie
    for field in text_fields:
        if _owl_values(owl_dossier, field):
            return 'Diagnostic texte'

    return 'Formulaire'


def _build_dossiers_affichage(patient_id):
    """
    Construit l'historique complet des dossiers à afficher dans patient_detail.html.

    V19 : affiche les dossiers créés par les deux méthodes :
      1) formulaire classique Ajout dossier ;
      2) texte clinique du module Diagnostic.

    La source principale est la table Django Dossier.
    Un fallback OWL ajoute aussi les anciens dossiers OWL s'ils existent sans ligne Django.
    """
    qs = Dossier.objects.filter(patient_id=patient_id).order_by('-date_creation', '-id')
    result = []
    seen_owl_names = set()

    patient_iri = f"http://www.semanticweb.org/domo/ontologies/2023/4/D-ONTO#patient{patient_id}"
    patient_owl = onto.search_one(iri=patient_iri, type=onto.Patient)
    patient_pathologies = _patient_pathologies_text(patient_owl)

    for idx, ddb in enumerate(qs, start=1):
        owl_dossier = _get_owl_dossier_for_db(patient_id, ddb)
        if owl_dossier is not None:
            seen_owl_names.add(getattr(owl_dossier, 'name', str(owl_dossier)))

        item = {
            'index': idx,
            'db': ddb,
            'owl': owl_dossier,
            'date_creation': getattr(ddb, 'date_creation', None),
            # Informations générales du dossier
            'motif': _first_available_value(ddb, owl_dossier, [
                'motif_consultation', 'motif', 'motifConsultation', 'raison_consultation'
            ]),
            'poids': _value_from_db_or_owl(ddb, owl_dossier, 'poids'),
            'taille': _value_from_db_or_owl(ddb, owl_dossier, 'taille'),
            # Données cliniques principales
            'antFam': _value_from_db_or_owl(ddb, owl_dossier, 'antFam'),
            'antPers': _value_from_db_or_owl(ddb, owl_dossier, 'antPers'),
            'atopie': _value_from_db_or_owl(ddb, owl_dossier, 'atopie'),
            'symptome': _value_from_db_or_owl(ddb, owl_dossier, 'symptome'),
            'signe': _value_from_db_or_owl(ddb, owl_dossier, 'signe'),
            'examcli': _value_from_db_or_owl(ddb, owl_dossier, 'examcli'),
            'habitVie': _value_from_db_or_owl(ddb, owl_dossier, 'habitVie'),
            'efr': _value_from_db_or_owl(ddb, owl_dossier, 'efr'),
            'radio': _value_from_db_or_owl(ddb, owl_dossier, 'radio'),
            'tdm': _value_from_db_or_owl(ddb, owl_dossier, 'tdm'),
            # Résultat diagnostic / texte NLP si le modèle contient ces champs
            'pathologie': _value_from_db_or_owl(ddb, owl_dossier, 'pathologie') or patient_pathologies,
            'score': _first_available_value(ddb, owl_dossier, [
                'score', 'score_diagnostic', 'diagnostic_score', 'confidence', 'confiance'
            ]),
            'texte_original': _first_available_value(ddb, owl_dossier, [
                'texte_original', 'diagnostic_text', 'texteDiagnostic'
            ]),
            'texte_corrige': _first_available_value(ddb, owl_dossier, [
                'texte_corrige', 'diagnostic_corrige', 'texteCorrige'
            ]),
        }
        # V23 : si le dossier vient du formulaire et n'a pas encore de pathologie
        # sauvegardée, on la déduit pour l'affichage avec le même moteur NLP/ontologie.
        if not item.get('pathologie'):
            inferred_patho, inferred_score = _infer_pathologie_from_dossier_item(item)
            if inferred_patho:
                item['pathologie'] = inferred_patho
            if inferred_score and not item.get('score'):
                item['score'] = inferred_score

        item['source'] = _guess_dossier_source(ddb, owl_dossier, item)
        result.append(item)

    # Fallback : anciens dossiers enregistrés uniquement dans onto.owl
    if patient_owl is not None and hasattr(patient_owl, 'aDossier'):
        for od in list(patient_owl.aDossier):
            name = getattr(od, 'name', str(od))
            if name in seen_owl_names:
                continue
            # évite de remonter les dossiers d'un autre patient si l'ancienne ontologie mélange tout
            if not (name == f'dossier{patient_id}' or name.startswith(f'dossier{patient_id}_')):
                continue
            item = {
                'index': len(result) + 1,
                'db': None,
                'owl': od,
                'date_creation': None,
                'motif': _first_available_value(None, od, [
                    'motif_consultation', 'motif', 'motifConsultation', 'raison_consultation'
                ]),
                'poids': _owl_values(od, 'poids'),
                'taille': _owl_values(od, 'taille'),
                'antFam': _owl_values(od, 'antFam'),
                'antPers': _owl_values(od, 'antPers'),
                'atopie': _owl_values(od, 'atopie'),
                'symptome': _owl_values(od, 'symptome'),
                'signe': _owl_values(od, 'signe'),
                'examcli': _owl_values(od, 'examcli'),
                'habitVie': _owl_values(od, 'habitVie'),
                'efr': _owl_values(od, 'efr'),
                'radio': _owl_values(od, 'radio'),
                'tdm': _owl_values(od, 'tdm'),
                'pathologie': _owl_values(od, 'pathologie') or patient_pathologies,
                'score': _first_available_value(None, od, [
                    'score', 'score_diagnostic', 'diagnostic_score', 'confidence', 'confiance'
                ]),
                'texte_original': _first_available_value(None, od, [
                    'texte_original', 'diagnostic_text', 'texteDiagnostic'
                ]),
                'texte_corrige': _first_available_value(None, od, [
                    'texte_corrige', 'diagnostic_corrige', 'texteCorrige'
                ]),
            }
            # V23 : fallback d'affichage aussi pour les anciens dossiers OWL.
            if not item.get('pathologie'):
                inferred_patho, inferred_score = _infer_pathologie_from_dossier_item(item)
                if inferred_patho:
                    item['pathologie'] = inferred_patho
                if inferred_score and not item.get('score'):
                    item['score'] = inferred_score

            item['source'] = _guess_dossier_source(None, od, item)
            result.append(item)

    return result, qs


@login_required
def patient_detail(request, id):
    """
    Affiche le patient + l'historique complet de ses dossiers médicaux.

    V18 : le problème venait du template qui affichait seulement `dossier`.
    Ici on prépare `dossiers_affichage` pour afficher TOUS les diagnostics/dossiers.
    On garde aussi `dossier` pour compatibilité avec ton ancien template.
    """
    iri = f"http://www.semanticweb.org/domo/ontologies/2023/4/D-ONTO#patient{id}"
    patient = onto.search_one(iri=iri, type=onto.Patient)
    patient_db = Patient.objects.filter(id=id).first()

    medecin = None
    if patient and getattr(patient, 'aMedecin', None):
        try:
            medecin = patient.aMedecin[0]
        except Exception:
            medecin = None

    dossiers_affichage, dossiers_db_qs = _build_dossiers_affichage(id)
    dernier_dossier_db = dossiers_db_qs.first()
    dossier = dossiers_affichage[0]['owl'] if dossiers_affichage else None
    patient_pathologies = _patient_pathologies_text(patient)

    # Fallback ancien système si aucun dossier Django n'existe.
    if dossier is None:
        iri_legacy = f"http://www.semanticweb.org/domo/ontologies/2023/4/D-ONTO#dossier{id}"
        dossier = onto.search_one(iri=iri_legacy, type=onto.Dossier)

    return render(request, 'hopital/patient_detail.html', {
        'patient': patient,
        'patient_db': patient_db,
        'medecin': medecin,
        'dossier': dossier,  # compatibilité ancien affichage
        'dernier_dossier_db': dernier_dossier_db,
        'dossiers_db': dossiers_db_qs,
        'dossiers_affichage': dossiers_affichage,
        'nombre_dossiers': len(dossiers_affichage),
        'patient_pathologies': patient_pathologies,
        'id': id,
    })


# ──────────────────────────────────────────────────────────────
# DOSSIER
# ──────────────────────────────────────────────────────────────

@login_required
@medecin_required
def ajout_dossier(request, id):
    iri = f"http://www.semanticweb.org/domo/ontologies/2023/4/D-ONTO#patient{id}"
    pat = onto.search_one(iri=iri, type=onto.Patient)
    patient = Patient.objects.get(id=id)
    dos = list(pat.aDossier)
    if request.method == 'POST':
        form = DossierForm(request.POST)
        if form.is_valid():
            dossier = form.save(commit=False)
            dossier.patient = patient
            dossier.date_creation = timezone.now()
            atopie_values   = request.POST.getlist('atopie')
            examcli_values  = request.POST.getlist('examcli')
            habitVie_values = request.POST.getlist('habitVie')
            radio_values    = request.POST.getlist('radio')
            signe_values    = request.POST.getlist('signe')
            symptome_values = request.POST.getlist('symptome')
            tdm_values      = request.POST.getlist('tdm')
            dossier.atopie   = ', '.join(set(atopie_values))
            dossier.examcli  = ', '.join(set(examcli_values))
            dossier.habitVie = ', '.join(set(habitVie_values))
            dossier.radio    = ', '.join(set(radio_values))
            dossier.signe    = ', '.join(set(signe_values))
            dossier.symptome = ', '.join(set(symptome_values))
            dossier.tdm      = ', '.join(set(tdm_values))
            dossier.save()
            with onto:
                instance_patient = onto.search_one(iri=iri, type=onto.Patient)
                # IMPORTANT : plusieurs dossiers par patient.
                # On crée un nom unique avec l'id Django du dossier et on APPEND,
                # on ne fait jamais instance_patient.aDossier = [...] car cela écrase l'ancien.
                instance_dossier = onto.search_one(
                    iri=f"http://www.semanticweb.org/domo/ontologies/2023/4/D-ONTO#dossier{id}_{dossier.id}"
                )
                if instance_dossier is None:
                    instance_dossier = onto.Dossier(f"dossier{id}_{dossier.id}")

                if instance_patient is not None and hasattr(instance_patient, 'aDossier'):
                    if instance_dossier not in list(instance_patient.aDossier):
                        instance_patient.aDossier.append(instance_dossier)

                instance_dossier.antFam = [form.cleaned_data['antFam']] if form.cleaned_data.get('antFam') else []
                instance_dossier.antPers = [form.cleaned_data['antPers']] if form.cleaned_data.get('antPers') else []
                instance_dossier.atopie   = atopie_values
                instance_dossier.efr = [form.cleaned_data['efr']] if form.cleaned_data.get('efr') else []
                instance_dossier.examcli  = examcli_values
                instance_dossier.habitVie = habitVie_values
                instance_dossier.radio    = radio_values
                instance_dossier.signe    = signe_values
                instance_dossier.symptome = symptome_values
                instance_dossier.tdm      = tdm_values
                instance_dossier.poids    = [form.cleaned_data['poids']] if form.cleaned_data.get('poids') is not None else []
                instance_dossier.taille   = [form.cleaned_data['taille']] if form.cleaned_data.get('taille') is not None else []
                sync_reasoner_pellet(infer_property_values=True, infer_data_property_values=True)

                # V22 : sauvegarder aussi la pathologie inférée sur CE dossier,
                # pour qu'elle apparaisse dans l'historique du patient.
                pathologies_inferrees = _patient_pathologies_text(instance_patient)
                if pathologies_inferrees:
                    _set_onto_datavalues(instance_dossier, 'pathologie', pathologies_inferrees)
                    _set_db_field_if_exists(dossier, 'pathologie', pathologies_inferrees)

                onto.save(file="ontologies/onto.owl", format="rdfxml")
            messages.success(request, "Nouveau dossier médical ajouté par formulaire.")
            return redirect('patient_detail', id=id)
    else:
        form = DossierForm()
    return render(request, 'hopital/ajout_dossier.html', {
        'patient': patient, 'id': id, 'dos': dos, 'form': form,
    })


# CORRECTION : décorateurs de sécurité ajoutés
@login_required
@medecin_required
def modifier_dossier(request, id):
    """
    Compatible avec plusieurs dossiers médicaux par patient.

    Ancienne erreur : Dossier.objects.get(patient=patient) plante dès qu'un patient
    possède 2 dossiers ou plus.

    Nouveau comportement :
    - si ?dossier_id=XX est fourni, on modifie ce dossier précis ;
    - sinon, on modifie le dossier le plus récent ;
    - aucun ancien dossier n'est écrasé par la création d'un nouveau dossier.
    """
    patient = Patient.objects.get(id=id)

    dossier_id = request.GET.get('dossier_id') or request.POST.get('dossier_id')
    qs = Dossier.objects.filter(patient=patient).order_by('-date_creation', '-id')

    if dossier_id:
        dossier = qs.filter(id=dossier_id).first()
    else:
        dossier = qs.first()

    if dossier is None:
        messages.error(request, "Aucun dossier médical à modifier pour ce patient.")
        return redirect('patient_detail', id=id)

    existing_values = {
        'antFam': dossier.antFam, 'antPers': dossier.antPers,
        'atopie': dossier.atopie, 'efr': dossier.efr,
        'examcli': dossier.examcli, 'habitVie': dossier.habitVie,
        'poids': dossier.poids, 'radio': dossier.radio,
        'signe': dossier.signe, 'symptome': dossier.symptome,
        'taille': dossier.taille, 'tdm': dossier.tdm,
    }

    if request.method == 'POST':
        form = DossierForm(request.POST, instance=dossier)
        if form.is_valid():
            dossier = form.save(commit=False)
            dossier.patient = patient
            dossier.date_creation = timezone.now()

            atopie_values   = request.POST.getlist('atopie')
            examcli_values  = request.POST.getlist('examcli')
            habitVie_values = request.POST.getlist('habitVie')
            radio_values    = request.POST.getlist('radio')
            signe_values    = request.POST.getlist('signe')
            symptome_values = request.POST.getlist('symptome')
            tdm_values      = request.POST.getlist('tdm')

            dossier.atopie   = ', '.join(dict.fromkeys(atopie_values))
            dossier.examcli  = ', '.join(dict.fromkeys(examcli_values))
            dossier.habitVie = ', '.join(dict.fromkeys(habitVie_values))
            dossier.radio    = ', '.join(dict.fromkeys(radio_values))
            dossier.signe    = ', '.join(dict.fromkeys(signe_values))
            dossier.symptome = ', '.join(dict.fromkeys(symptome_values))
            dossier.tdm      = ', '.join(dict.fromkeys(tdm_values))
            dossier.save()

            # Mettre à jour seulement l'instance OWL correspondant à CE dossier.
            # Priorité : nouveau nom unique dossier<patient_id>_<dossier_id>.
            # Fallback : ancien nom dossier<patient_id> pour ne pas casser les anciens dossiers.
            patient_iri = f"http://www.semanticweb.org/domo/ontologies/2023/4/D-ONTO#patient{id}"
            instance_patient = onto.search_one(iri=patient_iri, type=onto.Patient)
            dossier_iri_unique = f"http://www.semanticweb.org/domo/ontologies/2023/4/D-ONTO#dossier{id}_{dossier.id}"
            dossier_iri_legacy = f"http://www.semanticweb.org/domo/ontologies/2023/4/D-ONTO#dossier{id}"

            with onto:
                instance_dossier = onto.search_one(iri=dossier_iri_unique, type=onto.Dossier)

                # Si le dossier est ancien et n'a pas encore sa version unique, on la crée.
                if instance_dossier is None:
                    instance_dossier = onto.search_one(iri=dossier_iri_legacy, type=onto.Dossier)

                if instance_dossier is None:
                    instance_dossier = onto.Dossier(f"dossier{id}_{dossier.id}")

                if instance_patient is not None and hasattr(instance_patient, 'aDossier'):
                    if instance_dossier not in list(instance_patient.aDossier):
                        instance_patient.aDossier.append(instance_dossier)

                if hasattr(instance_dossier, 'antFam'):
                    instance_dossier.antFam = [form.cleaned_data['antFam']] if form.cleaned_data.get('antFam') else []
                if hasattr(instance_dossier, 'antPers'):
                    instance_dossier.antPers = [form.cleaned_data['antPers']] if form.cleaned_data.get('antPers') else []
                if hasattr(instance_dossier, 'atopie'):
                    instance_dossier.atopie = atopie_values
                if hasattr(instance_dossier, 'efr'):
                    instance_dossier.efr = [form.cleaned_data['efr']] if form.cleaned_data.get('efr') else []
                if hasattr(instance_dossier, 'examcli'):
                    instance_dossier.examcli = examcli_values
                if hasattr(instance_dossier, 'habitVie'):
                    instance_dossier.habitVie = habitVie_values
                if hasattr(instance_dossier, 'radio'):
                    instance_dossier.radio = radio_values
                if hasattr(instance_dossier, 'signe'):
                    instance_dossier.signe = signe_values
                if hasattr(instance_dossier, 'symptome'):
                    instance_dossier.symptome = symptome_values
                if hasattr(instance_dossier, 'tdm'):
                    instance_dossier.tdm = tdm_values
                if hasattr(instance_dossier, 'poids'):
                    instance_dossier.poids = [form.cleaned_data['poids']] if form.cleaned_data.get('poids') is not None else []
                if hasattr(instance_dossier, 'taille'):
                    instance_dossier.taille = [form.cleaned_data['taille']] if form.cleaned_data.get('taille') is not None else []

                try:
                    sync_reasoner_pellet(infer_property_values=True, infer_data_property_values=True)
                except Exception as e:
                    print(f"[MODIFIER DOSSIER OWL] Reasoner ignoré : {e}")

                onto.save(file="ontologies/onto.owl", format="rdfxml")

            messages.success(request, "Dossier médical modifié sans écraser les autres dossiers.")
            return redirect('patient_detail', id=id)
    else:
        form = DossierForm(instance=dossier)

    return render(request, 'hopital/modifier_dossier.html', {
        'patient': patient,
        'dossier': dossier,
        'dossiers': qs,
        'id': id,
        'form': form,
        'existing_values': existing_values,
    })


# ──────────────────────────────────────────────────────────────
# CRÉATION AUTOMATIQUE D'UN DOSSIER DEPUIS L'ANALYSE NLP
# ──────────────────────────────────────────────────────────────

_LABEL_TO_DOSSIER_FIELD = {
    'ANTECEDENT_FAMILIAL':  'antFam',
    'ANTECEDENT_PERSONNEL': 'antPers',
    'ATOPIE':               'atopie',
    'SYMPTOME':             'symptome',
    'SIGNE_CLINIQUE':       'signe',
    'EXAMENCLI':            'examcli',
    'HABITUDE_VIE':         'habitVie',
    'FACTEUR_RISQUE':       'habitVie',  # âge >= 40 ans, tabac actif... affiché dans facteurs/habitudes
    'EXPLFONCRESP':         'efr',
    'RADIOLOGIE':           'radio',
    'TDM':                  'tdm',
}


def _unique_join(values):
    """Retourne une chaîne propre sans doublons, en gardant l'ordre."""
    seen = set()
    out = []
    for v in values or []:
        v = str(v).strip()
        if not v:
            continue
        key = v.lower()
        if key not in seen:
            seen.add(key)
            out.append(v)
    return ', '.join(out)


def _get_selected_patient(request, form=None):
    """
    Récupère le patient choisi dans DiagnosticForm.
    Supporte plusieurs noms possibles de champ : patient, patient_id, id_patient.
    """
    patient = None

    if form is not None and hasattr(form, 'cleaned_data'):
        for field_name in ('patient', 'patient_id', 'id_patient'):
            obj = form.cleaned_data.get(field_name)
            if obj:
                if hasattr(obj, 'id'):
                    patient = obj
                else:
                    patient = Patient.objects.filter(id=obj).first()
                break

    if patient is None:
        patient_id = (
            request.POST.get('patient')
            or request.POST.get('patient_id')
            or request.POST.get('id_patient')
        )
        if patient_id:
            patient = Patient.objects.filter(id=patient_id).first()

    return patient


def _check_patient_permission(request, patient):
    """Empêche un médecin d'enregistrer un dossier sur un patient qui ne lui appartient pas."""
    if not patient:
        return False
    if request.user.is_superuser:
        return True
    medecin = getattr(request.user, 'medecin', None)
    return medecin is not None and getattr(patient, 'medecin_traitant_id', None) == medecin.id


def _fields_from_nlp_result(resultat):
    """Transforme les entités NLP en champs Dossier."""
    fields = {
        'antFam': '', 'antPers': '', 'atopie': '', 'symptome': '', 'signe': '',
        'examcli': '', 'habitVie': '', 'efr': '', 'radio': '', 'tdm': '',
        'pathologie': '',
    }

    grouped = {v: [] for v in _LABEL_TO_DOSSIER_FIELD.values()}
    for ent in resultat.get('entites', []) or []:
        # Ne pas enregistrer les entités niées dans le dossier positif.
        if ent.get('negatif'):
            continue
        label = ent.get('label')
        target_field = _LABEL_TO_DOSSIER_FIELD.get(label)
        if target_field:
            grouped[target_field].append(ent.get('texte', ''))

    for field, values in grouped.items():
        fields[field] = _unique_join(values)

    best = resultat.get('meilleur_diagnostic') or {}
    if best:
        fields['pathologie'] = best.get('pathologie', '') or ''
        # champ optionnel : sera sauvegardé seulement si le modèle Dossier possède un champ compatible
        score = best.get('score') or best.get('confiance') or best.get('confidence') or ''
        if score != '':
            fields['score_diagnostic'] = score

    return fields


def _default_for_required_model_field(field):
    """Valeur neutre pour éviter une erreur NOT NULL si le modèle Dossier impose un champ."""
    if isinstance(field, (dj_models.CharField, dj_models.TextField)):
        return ''
    if isinstance(field, (dj_models.IntegerField, dj_models.PositiveIntegerField)):
        return 0
    if isinstance(field, (dj_models.FloatField, dj_models.DecimalField)):
        return 0
    if isinstance(field, dj_models.BooleanField):
        return False
    if isinstance(field, dj_models.DateTimeField):
        return timezone.now()
    if isinstance(field, dj_models.DateField):
        return timezone.now().date()
    return None


def _save_django_dossier_from_analysis(patient, fields, texte_original='', texte_corrige=''):
    """Crée une nouvelle ligne Dossier dans la base Django."""
    dossier = Dossier()
    dossier.patient = patient

    if hasattr(dossier, 'date_creation'):
        dossier.date_creation = timezone.now()

    # Champs extraits de l'analyse NLP.
    for name, value in fields.items():
        if hasattr(dossier, name):
            setattr(dossier, name, value)

    # Champs optionnels si ton modèle les contient.
    optional_payload = {
        'texte_original': texte_original,
        'texte_corrige': texte_corrige,
        'diagnostic_text': texte_original,
        'diagnostic_corrige': texte_corrige,
    }
    for name, value in optional_payload.items():
        if hasattr(dossier, name):
            setattr(dossier, name, value or '')

    # Sécurité pour champs obligatoires non remplis.
    for field in Dossier._meta.fields:
        if field.name in ('id', 'patient'):
            continue
        if getattr(field, 'auto_now', False) or getattr(field, 'auto_now_add', False):
            continue
        current = getattr(dossier, field.name, None)
        if current in (None, '') and not field.null and not field.blank and field.default is NOT_PROVIDED:
            default_value = _default_for_required_model_field(field)
            if default_value is not None:
                setattr(dossier, field.name, default_value)

    dossier.save()
    return dossier


def _set_onto_datavalues(obj, prop_name, value):
    """Affecte proprement une data property OwlReady2 si elle existe."""
    if not value or not hasattr(obj, prop_name):
        return
    values = [v.strip() for v in str(value).split(',') if v.strip()]
    try:
        setattr(obj, prop_name, values)
    except Exception:
        try:
            current = getattr(obj, prop_name)
            for v in values:
                current.append(v)
        except Exception as e:
            print(f"[AUTO DOSSIER OWL] Impossible d'écrire {prop_name}: {e}")


def _save_onto_dossier_from_analysis(patient, django_dossier, fields):
    """
    Crée une nouvelle instance OWL Dossier liée au patient.
    Important : on append dans aDossier, on ne remplace pas les anciens dossiers.
    """
    patient_iri = f"http://www.semanticweb.org/domo/ontologies/2023/4/D-ONTO#patient{patient.id}"
    instance_patient = onto.search_one(iri=patient_iri, type=onto.Patient)
    if not instance_patient:
        print(f"[AUTO DOSSIER OWL] Patient OWL introuvable : patient{patient.id}")
        return None

    with onto:
        # Création / récupération de l'instance OWL correspondant exactement
        # au dossier Django créé. Cela permet à patient_detail d'afficher le bon dossier.
        dossier_name = f"dossier{patient.id}_{django_dossier.id}"
        dossier_iri = f"http://www.semanticweb.org/domo/ontologies/2023/4/D-ONTO#{dossier_name}"
        instance_dossier = onto.search_one(iri=dossier_iri, type=onto.Dossier)
        if instance_dossier is None:
            instance_dossier = onto.Dossier(dossier_name)

        if hasattr(instance_patient, 'aDossier'):
            if instance_dossier not in list(instance_patient.aDossier):
                instance_patient.aDossier.append(instance_dossier)

        for prop in ('antFam', 'antPers', 'atopie', 'symptome', 'signe',
                     'examcli', 'habitVie', 'efr', 'radio', 'tdm'):
            _set_onto_datavalues(instance_dossier, prop, fields.get(prop, ''))

        # Pathologie suggérée : on la garde aussi dans le dossier pour l'affichage,
        # et on l'ajoute au patient pour rester compatible avec les règles OWL.
        pathologie = (fields.get('pathologie') or '').strip()
        if pathologie:
            _set_onto_datavalues(instance_dossier, 'pathologie', pathologie)

        score_diag = fields.get('score_diagnostic') or fields.get('score') or ''
        if score_diag:
            for score_prop in ('score_diagnostic', 'score', 'confidence', 'confiance'):
                _set_onto_datavalues(instance_dossier, score_prop, score_diag)

        if pathologie and hasattr(instance_patient, 'aPathologie'):
            patho_obj = (
                onto.search_one(iri=f"*{pathologie}")
                or onto.search_one(label=pathologie)
            )
            if patho_obj is not None and patho_obj not in list(instance_patient.aPathologie):
                instance_patient.aPathologie.append(patho_obj)

        # On évite de casser l'enregistrement si Pellet/Java n'est pas disponible.
        try:
            sync_reasoner_pellet(infer_property_values=True, infer_data_property_values=True)
        except Exception as e:
            print(f"[AUTO DOSSIER OWL] Reasoner ignoré : {e}")

        onto.save(file="ontologies/onto.owl", format="rdfxml")

    return instance_dossier


def _creer_dossier_depuis_analyse(request, patient, texte, resultat):
    """Crée le dossier Django + OWL à partir du résultat NLP."""
    if not _check_patient_permission(request, patient):
        raise PermissionError("Vous n'avez pas le droit d'enregistrer un dossier pour ce patient.")

    fields = _fields_from_nlp_result(resultat)
    correction = resultat.get('correction') or {}
    texte_corrige = correction.get('texte_corrige') or correction.get('texte_nlp') or texte

    django_dossier = _save_django_dossier_from_analysis(
        patient=patient,
        fields=fields,
        texte_original=texte,
        texte_corrige=texte_corrige,
    )

    # Important sur cPanel : ne pas annuler le dossier Django si la mise a jour OWL
    # echoue a cause du reasoner Java/Pellet ou d'un probleme d'encodage des logs.
    try:
        _save_onto_dossier_from_analysis(patient, django_dossier, fields)
    except Exception as e:
        print(f"[AUTO DOSSIER OWL] Enregistrement OWL ignore : {e}")

    return django_dossier

# ──────────────────────────────────────────────────────────────
# DIAGNOSTIC
# ──────────────────────────────────────────────────────────────

@login_required
@medecin_required
def diagnostic_view(request):
    """
    Deux actions séparées :
    - action=analyser     : analyse le texte et affiche le résultat, sans créer de dossier.
    - action=enregistrer  : analyse puis crée un nouveau dossier médical pour le patient sélectionné.
    """
    form                = DiagnosticForm(user=request.user)
    analyse_nlp         = None
    diagnostic_surligne = ""
    scores_regles       = []
    meilleur_diagnostic = None
    correction          = None

    if request.method == "POST":
        form   = DiagnosticForm(request.POST, user=request.user)
        action = request.POST.get("action", "analyser")
        texte  = request.POST.get("diagnostic_text", "").strip()

        if not texte:
            messages.error(request, "Le texte du diagnostic est vide.")
        else:
            # 1) Toujours analyser d'abord.
            resultat = analyser_texte(texte)

            diagnostic_surligne = resultat.get("html_annote", "")
            scores_regles       = resultat.get("scores_regles", [])
            meilleur_diagnostic = resultat.get("meilleur_diagnostic")
            analyse_nlp         = {"entites": resultat.get("entites", [])}
            correction          = resultat.get("correction")

            # 2) Si l'utilisateur a cliqué seulement sur "Analyser", on ne sauvegarde rien.
            if action != "enregistrer":
                messages.info(request, "Analyse effectuée. Aucun dossier médical n'a été créé. Cliquez sur Enregistrer pour créer le dossier.")

            # 3) Si l'utilisateur a cliqué sur "Enregistrer", on crée le dossier.
            else:
                form_is_valid = form.is_valid()
                patient = _get_selected_patient(request, form if form_is_valid else None)

                if patient is None:
                    messages.error(request, "Veuillez sélectionner un patient avant d'enregistrer le dossier médical.")
                elif not _check_patient_permission(request, patient):
                    messages.error(request, "Vous n'avez pas le droit d'enregistrer un dossier pour ce patient.")
                else:
                    try:
                        nouveau_dossier = _creer_dossier_depuis_analyse(request, patient, texte, resultat)
                        messages.success(
                            request,
                            f"Nouveau dossier médical créé pour {patient.nom} {patient.prenom}."
                        )
                        return redirect('patient_detail', id=patient.id)
                    except Exception as e:
                        _safe_print_exception()
                        messages.error(request, f"Analyse effectuée, mais enregistrement du dossier impossible : {e}")

    return render(request, "hopital/diagnostic.html", {
        "form":                 form,
        "analyse_nlp":          analyse_nlp,
        "diagnostic_surligne":  diagnostic_surligne,
        "scores_regles":        scores_regles,
        "meilleur_diagnostic":  meilleur_diagnostic,
        "correction":           correction,
    })


# ──────────────────────────────────────────────────────────────
# ENDPOINT AJAX
# CORRECTION : doublon supprimé, une seule définition avec
#   @require_POST + traceback complet
# Ajouter dans urls.py : path('analyser/', views.analyser_api, name='analyser_api')
# ──────────────────────────────────────────────────────────────

@login_required
@require_POST   # CORRECTION : remplace la vérification manuelle de la méthode
def analyser_api(request):
    """
    POST /analyser/
    Body JSON : {"texte": "..."}
    Réponse   : {html_annote, entites, scores_regles, meilleur_diagnostic, correction}
    Tout vient de onto.owl via nlp_engine — aucune règle codée en dur.
    """
    try:
        data  = json.loads(request.body)
        texte = data.get("texte", "").strip()
        if not texte:
            return JsonResponse({"error": "Texte vide"}, status=400)
        resultat = analyser_texte(texte)
        return JsonResponse(resultat)
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON invalide"}, status=400)
    except Exception as e:
        _safe_print_exception()
        return JsonResponse({"error": str(e)}, status=500)

# ──────────────────────────────────────────────────────────────
# DEMO DIAGNOSTIC PUBLIC — sans connexion, sans patient, sans sauvegarde
# ──────────────────────────────────────────────────────────────

DEMO_DIAGNOSTIC_EXAMPLES = [
    {
        "id": "asthme",
        "titre": "Exemple 1 — Asthme",
        "maladie_attendue": "Asthme",
        "texte": """Le patient présente :

Antécédents familiaux d’asthme
Terrain atopique (eczéma)
Symptômes respiratoires : Dyspnée, Sifflements, Oppression thoracique, Toux sèche
Examen clinique : Râles sibilants
Exploration fonctionnelle respiratoire (EFR) : Trouble ventilatoire obstructif réversible""",
    },
    {
        "id": "bpco",
        "titre": "Exemple 2 — BPCO avec fautes",
        "maladie_attendue": "BPCO",
        "texte": """Le patient présente :

✔️ Facteurs de risque : Âge ≥ 40 ans, Tabagisme actif
✔️ Symptômes : Dspnée progressive, Tou productive chronique
✔️ Examen clinique : Râles ronflants (encombrement bronchique), Cyanose (hypoxémie), Signe de Hoover (distension pulmonaire), Diminution du murmure vésiculaire, Expiration à lèvres pincées
✔️ Explorations :
 - EFR : TVO non réversible
 - Radiographie : Distension thoracique, Raréfaction vasculaire""",
    },
    {
        "id": "ddb",
        "titre": "Exemple 3 — DDB",
        "maladie_attendue": "Dilatation des bronches",
        "texte": """Le patient présente :

✔️ Symptômes : Toux productive chronique, Infections bronchiques répétées, Dyspnée
✔️ Examen clinique : Râles ronflants (encombrement bronchique)
✔️ Imagerie (TDM) : Dilatation des bronches variqueuses (aspect irrégulier et sinueux des bronches)""",
    },
    {
        "id": "asthmeallsais",
        "titre": "Exemple 4 — Asthme Allergique Saisonnier",
        "maladie_attendue": "AsthmeAllergiqueSaisonnier",
        "texte": """Le patient présente :

✔️ Atopie : rhinite atopique
✔️ Symptômes : Dspnée, sifflement, toux sèche
✔️ Examen clinique : exacerbations saisonnières au printemps
✔️ Explorations :
 - EFR : TVO réversible sous bronchodilatateur""",
    }
]


def demo_diagnostic_view(request):
    """
    Page publique de démonstration.
    Pas de login_required.
    Pas de patient.
    Pas d'enregistrement.
    """
    return render(request, "hopital/demo_diagnostic.html", {
        "examples": DEMO_DIAGNOSTIC_EXAMPLES,
    })


@require_POST
def demo_analyser_api(request):
    """
    Analyse un exemple statique sélectionné.
    Le testeur ne peut pas envoyer un texte libre.
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
        example_id = payload.get("example_id", "")

        selected = None
        for ex in DEMO_DIAGNOSTIC_EXAMPLES:
            if ex["id"] == example_id:
                selected = ex
                break

        if selected is None:
            return JsonResponse({"error": "Exemple invalide."}, status=400)

        # Analyse NLP sans sauvegarde
        result = analyser_texte(selected["texte"])

        return JsonResponse({
            "ok": True,
            "example": selected,
            "texte_original": selected["texte"],
            "correction": result.get("correction", {}),
            "diagnostic_surligne": result.get("diagnostic_surligne") or result.get("html_annote") or "",
            "analyse_nlp": result.get("analyse_nlp") or {"entites": result.get("entites", [])},
            "meilleur_diagnostic": result.get("meilleur_diagnostic", None),
            "scores_regles": result.get("scores_regles", []),
        })

    except Exception as e:
        _safe_print_exception()
        return JsonResponse({"error": str(e)}, status=500)
