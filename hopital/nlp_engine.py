"""
nlp_engine.py  — version V12 ONTOLOGY-ONLY LONGEST-MATCH : TargetRules, lexique et fallback depuis onto.owl
Corrections appliquées :
  1. Toutes les TargetRule sont extraites depuis onto.owl
  2. Les termes du lexique clinique #TermeClinique sont lus depuis l'ontologie
  3. Aucune TargetRule médicale codée en dur dans Python
  4. notationgenrique est integre comme lexique supplementaire de detection
  5. Correction hybride sécurisée conservée avec dictionnaire clinique extrait de onto.owl
  6. Rechargement automatique quand onto.owl change
  7. Fallback matcher OWL robuste : ajoute les entités manquées par medspaCy
  8. Correction clinique locale moins agressive : ne remplace pas les variantes valides déjà présentes dans onto.owl
  9. V11 : seuil fuzzy plus strict + termes OWL manquants ajoutés pour éviter les reformulations dangereuses
 10. V12 : extension automatique des entités vers le plus long terme OWL disponible (ex. Dyspnée + progressive → Dyspnée progressive)
"""

import os
import re
import unicodedata
import xml.etree.ElementTree as ET
from collections import defaultdict
from difflib import SequenceMatcher
import urllib.request
import json as _json

# Logs compatibles cPanel/Passenger ASCII : les accents sont gardes dans les termes medicaux,
# mais retires seulement des messages imprimes pour eviter UnicodeEncodeError.
import builtins as _builtins
_ORIGINAL_PRINT = _builtins.print

def _safe_ascii_log(value):
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
    args = tuple(_safe_ascii_log(a) for a in args)
    return _ORIGINAL_PRINT(*args, **kwargs)


import numpy as np
import medspacy
import spacy
from medspacy.ner import TargetRule
from spacy import displacy
from spacy.tokens import Span
from spacy.util import filter_spans
from sklearn.metrics.pairwise import cosine_similarity


# ──────────────────────────────────────────────────────────────
# Chemin vers l'ontologie
# CORRECTION 5 : fallback par variable d'environnement, plus
# de chemin Windows absolu hardcodé.
# ──────────────────────────────────────────────────────────────
_HERE     = os.path.dirname(os.path.abspath(__file__))
ONTO_PATH = os.path.normpath(os.path.join(_HERE, '..', 'ontologies', 'onto.owl'))

if not os.path.exists(ONTO_PATH):
    # Lire depuis la variable d'environnement si définie, sinon lever une erreur claire
    env_path = os.environ.get('ONTO_PATH', '')
    if env_path and os.path.exists(env_path):
        ONTO_PATH = env_path
    else:
        raise FileNotFoundError(
            f"[nlp_engine] Fichier OWL introuvable : {ONTO_PATH}\n"
            "Définissez la variable d'environnement ONTO_PATH avec le chemin absolu correct."
        )

print(f"[nlp_engine] Chemin OWL : {ONTO_PATH}")
print(f"[nlp_engine] OWL trouve : {os.path.exists(ONTO_PATH)}")

# V8 : source unique des termes/règles cliniques = onto.owl.
# onto.owl reste la source des regles; notationgenrique ajoute un lexique supplementaire de detection.


# ──────────────────────────────────────────────────────────────
# Chargement du modele
# ──────────────────────────────────────────────────────────────
def _load_nlp_with_vectors():
    candidates = ['fr_core_news_sm', 'fr_core_news_lg', 'en_core_web_sm', 'en_core_web_lg']
    for model_name in candidates:
        try:
            _tmp = spacy.load(model_name)
            shape = _tmp.vocab.vectors.shape
            del _tmp
            if shape[0] == 0:
                print(f"[nlp_engine] {model_name} : pas de vecteurs, ignore")
                continue
            exclude = ['parser', 'ner', 'senter', 'morphologizer']
            nlp = medspacy.load(model_name, exclude=exclude)
            print(f"[nlp_engine] Modele : {model_name}  vecteurs={shape}")
            return nlp, model_name
        except Exception as e:
            print(f"[nlp_engine] {model_name} ignore : {e}")
            continue
    print("[nlp_engine] Aucun modele avec vecteurs")
    return medspacy.load(), ''


nlp, _vec_model_name = _load_nlp_with_vectors()

try:
    if _vec_model_name:
        _vec_nlp = spacy.load(
            _vec_model_name,
            exclude=['parser', 'ner', 'senter', 'morphologizer', 'attribute_ruler', 'lemmatizer'],
        )
    else:
        _vec_nlp = nlp
except Exception:
    _vec_nlp = nlp


# ══════════════════════════════════════════════════════════════
# A. PARSING OWL
# ══════════════════════════════════════════════════════════════
_SWRL = 'http://www.w3.org/2003/11/swrl#'
_RDF  = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'
_OWL  = 'http://www.w3.org/2002/07/owl#'
_RDFS = 'http://www.w3.org/2000/01/rdf-schema#'


def _local(uri):
    return uri.split('#')[-1] if uri and '#' in uri else (uri or '')


def _walk_list(node):
    """
    Parcourt une liste SWRL sous forme <swrl:AtomList> ou <rdf:Description>.
    """
    atoms = []
    if node is None:
        return atoms

    node_tag = node.tag.split('}')[-1]
    if node_tag not in {'AtomList', 'Description'}:
        for child in list(node):
            ctag = child.tag.split('}')[-1]
            if ctag in {'AtomList', 'Description'}:
                atoms.extend(_walk_list(child))
        return atoms

    first = node.find(f'{{{_RDF}}}first')
    rest  = node.find(f'{{{_RDF}}}rest')

    if first is not None:
        for child in first:
            ctag = child.tag.split('}')[-1]

            if ctag == 'ClassAtom':
                cp = child.find(f'{{{_SWRL}}}classPredicate')
                a1 = child.find(f'{{{_SWRL}}}argument1')
                prop = _local(cp.get(f'{{{_RDF}}}resource', '')) if cp is not None else ''
                val = _local(a1.get(f'{{{_RDF}}}resource', '')) if a1 is not None else ''
                if prop:
                    atoms.append((prop, val))

            elif ctag == 'IndividualPropertyAtom':
                pp = child.find(f'{{{_SWRL}}}propertyPredicate')
                a2 = child.find(f'{{{_SWRL}}}argument2')
                prop = _local(pp.get(f'{{{_RDF}}}resource', '')) if pp is not None else ''
                val = _local(a2.get(f'{{{_RDF}}}resource', '')) if a2 is not None else ''
                if prop and prop != 'aDossier' and val:
                    atoms.append((prop, val))

            elif ctag == 'DatavaluedPropertyAtom':
                pp = child.find(f'{{{_SWRL}}}propertyPredicate')
                a2 = child.find(f'{{{_SWRL}}}argument2')
                prop = _local(pp.get(f'{{{_RDF}}}resource', '')) if pp is not None else ''
                val = (a2.text or '').strip() if a2 is not None else ''
                if prop and val:
                    atoms.append((prop, val))

    if rest is not None:
        rest_resource = rest.get(f'{{{_RDF}}}resource', '')
        if 'nil' not in rest_resource:
            for child in rest:
                atoms.extend(_walk_list(child))

    return atoms



def _parse_owl(owl_path):
    tree = ET.parse(owl_path)
    root = tree.getroot()
    values_by_prop = defaultdict(set)
    raw_rules      = []
    seen_keys      = set()

    for imp in root.iter(f'{{{_SWRL}}}Imp'):
        body_el = imp.find(f'{{{_SWRL}}}body')
        head_el = imp.find(f'{{{_SWRL}}}head')

        body_list = None
        head_list = None

        if body_el is not None:
            body_list = body_el.find(f'{{{_SWRL}}}AtomList')
            if body_list is None:
                body_list = body_el.find(f'{{{_RDF}}}Description')
            if body_list is None and len(list(body_el)):
                body_list = list(body_el)[0]

        if head_el is not None:
            head_list = head_el.find(f'{{{_SWRL}}}AtomList')
            if head_list is None:
                head_list = head_el.find(f'{{{_RDF}}}Description')
            if head_list is None and len(list(head_el)):
                head_list = list(head_el)[0]

        body_atoms = _walk_list(body_list)
        head_atoms = _walk_list(head_list)

        for prop, val in body_atoms:
            if prop not in {'Patient', 'aDossier'}:
                values_by_prop[prop].add(val)

        patho_id = None
        for prop, val in head_atoms:
            if prop == 'aPathologie':
                patho_id = val
                break
        if not patho_id:
            continue

        rule_text = ' '.join(val for prop, val in body_atoms if val and prop not in {'Patient', 'aDossier'})
        key = (patho_id, rule_text)
        if key in seen_keys:
            continue
        seen_keys.add(key)

        raw_rules.append({
            'patho_id':   patho_id,
            'body_atoms': [(p, v) for p, v in body_atoms if p not in {'Patient', 'aDossier'}],
            'rule_text':  rule_text,
        })

    # Lire aussi le lexique clinique intégré dans onto.owl.
    for ind in root.iter(f'{{{_OWL}}}NamedIndividual'):
        is_clinical_term = False
        for typ in ind.findall(f'{{{_RDF}}}type'):
            if _local(typ.get(f'{{{_RDF}}}resource', '')) == 'TermeClinique':
                is_clinical_term = True
                break
        if not is_clinical_term:
            continue

        prop = ''
        vals = []
        for child in ind:
            tag = child.tag.split('}')[-1]
            txt = (child.text or '').strip()
            if not txt:
                continue
            if tag == 'categorieClinique':
                prop = txt
            elif tag in {'termeCanonique', 'synonyme', 'label', 'prefLabel', 'altLabel'}:
                vals.append(txt)
        if prop:
            for val in vals:
                if val:
                    values_by_prop[prop].add(val)

    return values_by_prop, raw_rules


# ──────────────────────────────────────────────────────────────
# Mappings
# ──────────────────────────────────────────────────────────────
_PROP_TO_LABEL = {
    'symptome':          'SYMPTOME',
    'examcli':           'EXAMENCLI',
    'efr':               'EXPLFONCRESP',
    'radio':             'RADIOLOGIE',
    'tdm':               'TDM',
    'atopie':            'ATOPIE',
    'antFam':            'ANTECEDENT_FAMILIAL',
    'antPers':           'ANTECEDENT_PERSONNEL',
    'habitVie':          'HABITUDE_VIE',
    'facteurRisque':     'FACTEUR_RISQUE',
    'facteur_risque':    'FACTEUR_RISQUE',
    'facteursRisque':    'FACTEUR_RISQUE',
    'facteurs_risque':   'FACTEUR_RISQUE',
    'ageRisque':         'FACTEUR_RISQUE',
    'âgeRisque':         'FACTEUR_RISQUE',
    'signe':             'SIGNE_CLINIQUE',
    'biologie':          'BIOLOGIE',
    'testLab':           'BIOLOGIE',
    'testlab':           'BIOLOGIE',
    'gazometrie':        'BIOLOGIE',
    'gazométrie':        'BIOLOGIE',
    'angioscanner':      'ANGIOSCANNER',
    'polygraphie':       'POLYGRAPHIE',
    'exposition':        'EXPOSITION',
    'testGenetique':     'TEST_GENETIQUE',
    'testgenetique':     'TEST_GENETIQUE',
    'imagerie':          'IMAGERIE',
    'exacerbation':      'EXACERBATION',
    'immunosuppression': 'IMMUNOSUPPRESSION',
    'immunodepression':  'IMMUNOSUPPRESSION',
    'immunodépression':  'IMMUNOSUPPRESSION',
    'dureeSymptomes':    'DUREE_SYMPTOMES',
    'duréeSymptomes':    'DUREE_SYMPTOMES',
    'dureeSymptome':     'DUREE_SYMPTOMES',
    'duréeSymptome':     'DUREE_SYMPTOMES',
    'aPathologie':        'PATHOLOGIE',
    'pathologie':         'PATHOLOGIE',
    'age':                'FACTEUR_RISQUE',
    'absence':            'PROBLEM',
}


# Termes extraits de notationgenrique.txt pour detecter les exemples et paragraphes du fichier.
# Les regles de diagnostic restent chargees depuis onto.owl ; ce dictionnaire sert surtout
# a annoter davantage d'entites et a ameliorer la similarite.
_EXTRA_NOTATION_TERMS_BY_PROP = {'aPathologie': ['Œdème pulmonaire cardiogénique', 'Œdème pulmonaire non cardiogénique'],
 'absence': ['Cardiomégalie', 'Turgescence jugulaire'],
 'angioscanner': ['Embolie artère pulmonaire'],
 'antFam': ['Asthme'],
 'atopie': ['Conjonctivite', 'Eczéma', 'Rhinite'],
 'biologie': ['PCR virale positive'],
 'duréeSymptomes': ['≥3 mois'],
 'efr': ['TVO non réversible après bronchodilatateur',
         'TVO réversible partielle',
         'TVO réversible sous bronchodilatateur',
         'Trouble ventilatoire restrictif'],
 'exacerbation': ['≥2/an'],
 'examcli': ['Apnées observées',
             'Crépitants bilatéraux',
             'Crépitants fins',
             'Crépitants fins bibasaux',
             'Cyanose',
             'Diminution de murmure vésiculaire',
             'Expiration à lèvres pincée',
             'Hypocratisme digital',
             'Hypotension',
             'Hypoxémie',
             'Respiration sifflante',
             'Râles crépitants',
             'Râles crépitants diffus',
             'Râles ronflants',
             'Râles sibilants',
             'Signe de Hoover',
             'Tachycardie',
             'Tachypnée',
             'Turgescence jugulaire'],
 'exposition': ['Allergène inhalé'],
 'habitVie': ['Tabac actif'],
 'imagerie': ['Angio-TDM: Embole pulmonaire'],
 'immunodepression': ['Oui'],
 'immunosuppression': ['Oui'],
 'polygraphie': ['Index d’apnées-hypopnées > 15'],
 'radio': ['Cardiomégalie',
           'Collapsus pulmonaire',
           'Distension thoracique',
           'Infiltrat alvéolaire',
           'Infiltrat alvéolaire localisé',
           'Infiltrat pulmonaire',
           'Infiltrats bilatéraux',
           'Infiltrats diffus',
           'Infiltrats pulmonaires diffus',
           'Opacité alvéolaire localisée',
           'Opacité lobaire',
           'Opacités en verre dépoli',
           'Présence d’air pleural',
           'Raréfaction de la vascularisation',
           'Syndrome interstitiel'],
 'signe': ['Asthénie', 'Fièvre', 'Perte de poids'],
 'symptome': ['Crachat de sang',
              'Douleur thoracique',
              'Douleur thoracique aiguë',
              'Douleurs thoraciques',
              'Dyspnée',
              'Dyspnée aiguë',
              'Dyspnée de repos',
              'Dyspnée progressive',
              'Dyspnée soudaine',
              'Dyspnée sévère',
              'Expectoration matinale',
              'Fatigue',
              'Fièvre',
              'Fièvre élevée',
              'Hémoptysie',
              'Infections bronchiques',
              'Infections bronchiques répétées',
              'Oppression thoracique',
              'Orthopnée',
              'Retard croissance',
              'Ronflement',
              'Sifflement',
              'Sifflements',
              'Somnolence diurne',
              'Sueurs nocturnes',
              'Tachycardie',
              'Toux',
              'Toux chronique',
              'Toux mousseuse',
              'Toux nocturne',
              'Toux productive',
              'Toux sèche',
              'Œdème périphérique'],
 'tdm': ['Adénopathies médiastinales bilatérales',
         'Dilatation de bronches cylindriques',
         'Dilatation de bronches kystiques',
         'Dilatation de bronches variqueuses',
         'Opacités en verre dépoli bilatérales',
         'Opacités micronodulaires diffuse',
         'Opacités réticulaires diffuses',
         'Reticulations diffuses et épaississement septal'],
 'testGenetique': ['Mutation CFTR'],
 'testLab': ['PCR positive virus respiratoire']}


def _notation_file_candidates():
    project_root = os.path.normpath(os.path.join(_HERE, '..'))
    return [
        os.environ.get('NOTATION_GENERIC_PATH', ''),
        os.path.join(_HERE, 'notationgenrique.txt'),
        os.path.join(_HERE, 'notationgenrique(2).txt'),
        os.path.join(project_root, 'notationgenrique.txt'),
        os.path.join(project_root, 'notationgenrique(2).txt'),
    ]


def _read_external_notation_terms_by_prop():
    """Lit notationgenrique.txt si le fichier existe sur le serveur.

    Format accepte : lignes SWRL comme symptome(?d, "Dyspnee"), examcli(...), etc.
    C'est volontairement tolerant pour supporter les textes colles.
    """
    terms = defaultdict(set)
    pattern = re.compile(r'([A-Za-zÀ-ÖØ-öø-ÿ_][\wÀ-ÖØ-öø-ÿ]*)\s*\([^\)]*?,\s*\"([^\"]+)\"', re.UNICODE)
    for path in _notation_file_candidates():
        if not path or not os.path.exists(path):
            continue
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            for prop, value in pattern.findall(content):
                value = re.sub(r'\^\^.*$', '', str(value or '').strip())
                if value and not value.startswith('?'):
                    terms[prop].add(value)
            print(f"[nlp_engine] notationgenrique charge : {path}")
            break
        except Exception as e:
            print(f"[nlp_engine] notationgenrique ignore : {e}")
    return terms


def _load_notation_terms_by_prop():
    """Retourne les termes embarques + ceux du fichier notationgenrique.txt s'il existe."""
    terms = defaultdict(set)
    for prop, vals in _EXTRA_NOTATION_TERMS_BY_PROP.items():
        for v in vals:
            if v:
                terms[prop].add(v)
    for prop, vals in _read_external_notation_terms_by_prop().items():
        for v in vals:
            terms[prop].add(v)
    return terms


def _merge_notation_terms(values_by_prop):
    """Ajoute notationgenrique au dictionnaire prop -> termes."""
    for prop, vals in _load_notation_terms_by_prop().items():
        for v in vals:
            if v:
                values_by_prop[prop].add(v)
    return values_by_prop

_PATHO_META = {
    'Asthme':                                    ('Asthme',                                    '#e8f4fd', '#2a9df4'),
    'AsthmeSevereInd':                           ('Asthme severe',                             '#d6eaf8', '#1a6fa8'),
    'BPCO':                                      ('BPCO',                                      '#fff3cd', '#f0a500'),
    'DDB':                                       ('Dilatation des bronches (DDB)',              '#e8f8f5', '#1abc9c'),
    'PneumonieInd':                              ('Pneumonie',                                 '#faf0fb', '#a569bd'),
    'PneumonieBacterienneInd':                   ('Pneumonie bacterienne',                     '#fdf2f8', '#8e44ad'),
    'PneumonieViraleInd':                        ('Pneumonie virale',                          '#f5eef8', '#7d3c98'),
    'InfectionViralePulmonaireInd':              ('Infection virale pulmonaire',               '#e9f7ef', '#27ae60'),
    'InfectionOpportunisteInd':                  ('Infection opportuniste',                    '#fdedec', '#c0392b'),
    'FibrosePulmonaireIdiopathiqueInd':          ('Fibrose pulmonaire idiopathique',           '#f4f6f7', '#555555'),
    'fibpul':                                    ('Fibrose pulmonaire',                        '#f0f0f0', '#777777'),
    'FibroseKystiqueInd':                        ('Fibrose kystique / Mucoviscidose',          '#fdfefe', '#99a3a4'),
    'OedemePulmonaireCardiogeniqueInd':          ('Oedeme pulmonaire cardiogenique',           '#eaf4fb', '#1a5276'),
    'OedemePulmonaireNonCardiogeniqueInd':       ('Oedeme pulmonaire non cardiogenique',       '#e8f6f3', '#148f77'),
    'tuberculose':                               ('Tuberculose pulmonaire',                    '#fef9e7', '#d4ac0d'),
    'EmboliePulmonaireInd':                      ('Embolie pulmonaire',                        '#fdedec', '#e74c3c'),
    'COVID19SevereInd':                          ('COVID-19 severe',                           '#eafaf1', '#1e8449'),
    'PneumothoraxInd':                           ('Pneumothorax',                              '#fef5e4', '#e67e22'),
    'SyndromeApneeSommeilInd':                   ("Syndrome d'apnee du sommeil",               '#eaf0fb', '#2e86c1'),
    'BronchiteChroniqueInd':                     ('Bronchite chronique',                       '#fdfefe', '#aab7b8'),
    'PneumopathieHypersensibiliteInd':           ("Pneumopathie d'hypersensibilite",           '#fef9e7', '#b7950b'),
    'SarcoidosePulmonaireInd':                   ('Sarcoidose pulmonaire',                     '#f4ecf7', '#6c3483'),
    'PneumopathieInterstitielleNonSpecifiqueInd':('Pneumopathie interstitielle non specifique','#f0f3ff', '#5d6d7e'),
}

_DISPLACY_COLORS = {
    'ANTECEDENT_FAMILIAL':  '#EEEDFE',
    'ANTECEDENT_PERSONNEL': '#F3E5F5',
    'SYMPTOME':             '#FAECE7',
    'EXAMENCLI':            '#EAF3DE',
    'EXPLFONCRESP':         '#E6F1FB',
    'RADIOLOGIE':           '#FBEAF0',
    'PATHOLOGIE':           '#FAEEDA',
    'ATOPIE':               '#E1F5EE',
    'HABITUDE_VIE':         '#FCEBEB',
    'FACTEUR_RISQUE':       '#FFF8E1',
    'TDM':                  '#F1EFE8',
    'BIOLOGIE':             '#E6F1FB',
    'SIGNE_CLINIQUE':       '#FAEEDA',
    'EXPOSITION':           '#EEEDFE',
    'IMAGERIE':             '#FAECE7',
    'ANGIOSCANNER':         '#FAECE7',
    'EXACERBATION':         '#FCEBEB',
    'TEST_GENETIQUE':       '#EAF3DE',
    'POLYGRAPHIE':          '#E1F5EE',
    'IMMUNOSUPPRESSION':    '#FBEAF0',
    'DUREE_SYMPTOMES':      '#FFF8E1',
    'PROBLEM':              '#F1EFE8',
}


# ══════════════════════════════════════════════════════════════
# B. TargetRules
# ══════════════════════════════════════════════════════════════

_SYNONYMES = {
    "de":            ["de", "des", "du", "d"],
    "des":           ["de", "des", "du"],
    "du":            ["de", "des", "du"],
    "cylindriques":  ["cylindriques", "cylindrique"],
    "kystiques":     ["kystiques", "kystique"],
    "variqueuses":   ["variqueuses", "variqueuse"],
    "reversible":    ["reversible"],
    "obstructif":    ["obstructif", "obstructive"],
    "vascularisation": ["vascularisation", "vasculaire"],
    "sibilants":     ["sibilants", "sibilant"],
    "crepitants":    ["crepitants", "crepitant"],
    "bilateraux":    ["bilateraux", "bilateral", "bilaterales"],
    "bronchiques":   ["bronchiques", "bronchique"],
    "bronchique":    ["bronchique", "bronchiques"],
    "pulmonaire":    ["pulmonaire", "pulmonaires"],
    "thoracique":    ["thoracique", "thoraciques"],
    "alveolaire":    ["alveolaire", "alveolaires"],
    "vesiculaire":   ["vesiculaire"],
    "diminue":       ["diminue", "diminues"],
    "localise":      ["localise", "localisee"],
    "diffus":        ["diffus", "diffuse", "diffuses"],
    "pincees":       ["pincees", "pincee"],
    "reticulations": ["reticulations", "reticulation"],
    "rarefaction":   ["rarefaction"],
    "epaississement":["epaississement"],
    "depoli":        ["depoli"],
    "opacites":      ["opacites", "opacite"],
    "infiltrats":    ["infiltrats", "infiltrat"],
    "infiltrat":     ["infiltrat", "infiltrats"],
    "aigue":         ["aigue", "aigu"],
    "severe":        ["severe"],
    "progressive":   ["progressive", "progressif"],
    "nocturne":      ["nocturne", "nocturnes"],
    "chronique":     ["chronique", "chroniques"],
    "productive":    ["productive", "productif"],
    "septal":        ["septal", "septaux"],
    "bibasaux":      ["bibasaux", "bibasal"],
    "fins":          ["fins", "fin", "fines"],
    "sifflante":     ["sifflante", "sifflant", "sifflants"],
    "sifflement":    ["sifflement", "sifflements", "sifflement respiratoire", "sifflements respiratoires"],
    "sifflements":   ["sifflement", "sifflements", "sifflements respiratoires"],
    "ronflement":    ["ronflement", "ronflements"],
    "hemoptysie":    ["hémoptysie", "hemoptysie", "crachat de sang", "crachats de sang"],
    "soudaine":      ["soudaine", "soudain"],
    "partielle":     ["partielle", "partiel"],
    "kystique":      ["kystique", "kystiques"],
    "cylindrique":   ["cylindrique", "cylindriques"],
    "variqueuse":    ["variqueuse", "variqueuses"],
    "visible":       ["visible", "visibles"],
}

_DET_OPTIONNELS = {"de", "des", "du", "d", "la", "le", "les", "a", "en", "par"}


def _normalize(tok):
    low = tok.lower()
    variants = {low}
    for acc, plain in [
        ("\u00e9","e"),("\u00e8","e"),("\u00ea","e"),("\u00eb","e"),
        ("\u00e0","a"),("\u00e2","a"),("\u00f4","o"),("\u00ee","i"),
        ("\u00fb","u"),("\u00f9","u"),("\u00e7","c"),("\u0153","oe"),("\u00e6","ae"),
    ]:
        stripped = low.replace(acc, plain)
        if stripped != low:
            variants.add(stripped)
    if low in _SYNONYMES:
        for s in _SYNONYMES[low]:
            variants.add(s.lower())
    extra = set()
    for v in list(variants):
        for acc, plain in [
            ("\u00e9","e"),("\u00e8","e"),("\u00ea","e"),("\u00eb","e"),
            ("\u00e0","a"),("\u00e2","a"),("\u00f4","o"),("\u00ee","i"),
            ("\u00fb","u"),("\u00f9","u"),("\u00e7","c"),
        ]:
            stripped = v.replace(acc, plain)
            if stripped != v:
                extra.add(stripped)
    variants.update(extra)
    return sorted(variants)


def _make_pattern(value):
    tokens = re.split(r"\s+", value.strip())
    pattern = []
    for tok in tokens:
        low = tok.lower()
        variants = _normalize(low)
        if low in _DET_OPTIONNELS or any(v in _DET_OPTIONNELS for v in variants):
            pattern.append({"LOWER": {"IN": variants}, "OP": "?"})
        else:
            if len(variants) == 1:
                pattern.append({"LOWER": variants[0]})
            else:
                pattern.append({"LOWER": {"IN": variants}})
    return pattern


def _make_all_patterns(value):
    base_pattern = _make_pattern(value)
    patterns = [(value, base_pattern)]

    tokens = re.split(r"\s+", value.strip())
    lows   = [t.lower() for t in tokens]

    no_det = [t for t in tokens if t.lower() not in _DET_OPTIONNELS]
    if len(no_det) != len(tokens) and len(no_det) >= 2:
        alt = " ".join(no_det)
        altp = [{"LOWER": v[0] if len(v) == 1 else {"IN": v}}
                for v in [_normalize(t.lower()) for t in no_det]]
        patterns.append((alt, altp))

    if "bronches" in lows and len(tokens) >= 3:
        idx_b = lows.index("bronches")
        if idx_b + 1 < len(lows):
            adj    = tokens[idx_b + 1]
            prefix = [t for t in tokens[:idx_b] if t.lower() not in _DET_OPTIONNELS]
            alt_t  = prefix + [adj] + ["des", "bronches"]
            alt    = " ".join(alt_t)
            altp   = []
            for t in alt_t:
                v = _normalize(t.lower())
                altp.append({"LOWER": v[0]} if len(v) == 1 else {"LOWER": {"IN": v}})
            patterns.append((alt, altp))

    return patterns


# ══════════════════════════════════════════════════════════════
# Aucune TargetRule médicale codée en dur
# ══════════════════════════════════════════════════════════════
# Les anciennes listes manuelles (_PRIORITY_RULES, _EXTRA_EFR_RULES,
# _EXTRA_FLEX_RULES) ont été supprimées.
# Les entités détectables doivent venir de onto.owl :
#   - corps des règles SWRL : symptome(?d, "...") etc.
#   - individus #TermeClinique avec categorieClinique/termeCanonique/synonyme.
#
# Si un terme comme "toux sèche" n'est pas détecté, il faut l'ajouter
# dans onto.owl, pas dans Python.


def _clean_pathology_id(value):
    """Nettoie l'identifiant de pathologie extrait après aPathologie(?p, ...)."""
    value = (value or '').strip()
    value = value.replace('"', '').replace("'", '')
    value = re.sub(r"\^\^.*$", "", value).strip()
    value = value.split(',')[0].strip()
    value = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ0-9_\-]+", "_", value).strip('_')
    return value or 'PathologieInconnue'


def _is_boolean_like_value(value):
    return _strip_accents(value).lower().strip() in {
        'oui', 'non', 'true', 'false', 'present', 'absent', 'positive', 'negative'
    }


def _label_phrase_for_boolean_prop(prop):
    """
    Pour une règle comme immunosuppression(?d, "Oui"), on ne doit pas
    annoter le mot Oui. On annote plutôt le concept clinique lui-même.
    """
    p = _strip_accents(prop).lower()
    mapping = {
        'immunosuppression': 'immunosuppression',
        'immunodepression': 'immunodépression',
        'immunodepression': 'immunodépression',
    }
    return mapping.get(p, prop)


def _expand_value_variants(prop, value):
    """
    Génère des variantes utiles depuis une valeur clinique lue dans onto.owl.
    Exemple : "TVO réversible sous bronchodilatateur" donne aussi
    "trouble ventilatoire obstructif réversible" pour annoter le texte libre.
    """
    variants = []

    def add(v):
        v = re.sub(r"\s+", " ", str(v).strip())
        if v and v not in variants:
            variants.append(v)

    value = re.sub(r"\^\^rdf:[A-Za-z_]+", "", str(value)).strip()
    if not value:
        return variants

    if _is_boolean_like_value(value):
        add(_label_phrase_for_boolean_prop(prop))
        return variants

    add(value)

    # Singulier/pluriel fréquent pour les valeurs cliniques lues dans onto.owl.
    singular_plural = {
        'Sifflement': 'Sifflements',
        'Sifflements': 'Sifflement',
        'Douleur thoracique': 'Douleurs thoraciques',
        'Douleurs thoraciques': 'Douleur thoracique',
        'Infection bronchique': 'Infections bronchiques',
        'Infections bronchiques': 'Infection bronchique',
        'Râle crépitant': 'Râles crépitants',
        'Râles crépitants': 'Râle crépitant',
        'Crépitant fin': 'Crépitants fins',
        'Crépitants fins': 'Crépitant fin',
    }
    if value in singular_plural:
        add(singular_plural[value])

    # EFR : abréviations TVO/TVR <-> formulations complètes.
    low = _strip_accents(value).lower()
    low = low.replace('’', "'")

    if low.startswith('tvo'):
        rest = value[3:].strip(' :-')
        add(('Trouble ventilatoire obstructif ' + rest).strip())
        add(('trouble ventilatoire obstructif ' + rest).strip())
        # Variante sans "sous/après bronchodilatateur" pour annoter le texte plus court.
        rest_short = re.sub(r"\s+(sous|après|apres)\s+bronchodilatateur.*$", "", rest, flags=re.I).strip()
        if rest_short and rest_short != rest:
            add(('TVO ' + rest_short).strip())
            add(('Trouble ventilatoire obstructif ' + rest_short).strip())
            add(('trouble ventilatoire obstructif ' + rest_short).strip())

    if low.startswith('tvr'):
        rest = value[3:].strip(' :-')
        add(('Trouble ventilatoire restrictif ' + rest).strip())
        add(('trouble ventilatoire restrictif ' + rest).strip())

    if 'tvo non reversible' in _norm_key(value):
        add('TVO non réversible')
        add('trouble ventilatoire obstructif non réversible')
        add('Trouble ventilatoire obstructif non réversible')

    if 'tvo reversible' in _norm_key(value) and 'non reversible' not in _norm_key(value):
        add('TVO réversible')
        add('trouble ventilatoire obstructif réversible')
        add('Trouble ventilatoire obstructif réversible')

    # Termes fréquents décrits différemment dans les paragraphes du fichier.
    n = _norm_key(value)
    if n == 'opacites en verre depoli':
        add('Opacités en verre dépoli bilatérales')
    if n == 'infiltrats diffus':
        add('Infiltrats diffus bilatéraux')
    if n == 'opacite alveolaire localisee':
        add('Infiltrat alvéolaire localisé')
    if n == 'dilatation de bronches cylindriques':
        add('Dilatation bronchique cylindrique')
        add('Dilatation des bronches cylindriques')
        add('Dilatation des bronches de type cylindrique')
        add('Dilatation des bronches type cylindrique')
        add('Dilatation de bronches de type cylindrique')
        add('Dilatation de bronches type cylindrique')
    if n == 'dilatation de bronches kystiques':
        add('Dilatation bronchique kystique')
        add('Dilatation des bronches kystiques')
        add('Dilatation des bronches de type kystique')
        add('Dilatation des bronches type kystique')
        add('Dilatation de bronches de type kystique')
        add('Dilatation de bronches type kystique')
    if n == 'dilatation de bronches variqueuses':
        add('Dilatation bronchique variqueuse')
        add('Dilatation des bronches variqueuses')
        add('Dilatation des bronches de type variqueux')
        add('Dilatation des bronches type variqueux')
        add('Dilatation de bronches de type variqueux')
        add('Dilatation de bronches type variqueux')

    # V18 : variantes utiles pour les phrases longues de cours/description.
    # Exemple : "la TDM met en evidence une dilatation des bronches de type cylindrique".
    if n == 'dilatation des bronches cylindriques':
        add('Dilatation de bronches cylindriques')
        add('Dilatation bronchique cylindrique')
        add('Dilatation des bronches de type cylindrique')
        add('Dilatation des bronches type cylindrique')
        add('Dilatation de bronches de type cylindrique')
        add('Dilatation de bronches type cylindrique')
    if n == 'dilatation des bronches kystiques':
        add('Dilatation de bronches kystiques')
        add('Dilatation bronchique kystique')
        add('Dilatation des bronches de type kystique')
        add('Dilatation des bronches type kystique')
        add('Dilatation de bronches de type kystique')
        add('Dilatation de bronches type kystique')
    if n == 'dilatation des bronches variqueuses':
        add('Dilatation de bronches variqueuses')
        add('Dilatation bronchique variqueuse')
        add('Dilatation des bronches de type variqueux')
        add('Dilatation des bronches type variqueux')
        add('Dilatation de bronches de type variqueux')
        add('Dilatation de bronches type variqueux')
    if n == 'dilatation des bronches de type cylindrique':
        add('Dilatation de bronches cylindriques')
        add('Dilatation des bronches cylindriques')
        add('Dilatation bronchique cylindrique')
    if n == 'dilatation des bronches de type kystique':
        add('Dilatation de bronches kystiques')
        add('Dilatation des bronches kystiques')
        add('Dilatation bronchique kystique')
    if n == 'dilatation des bronches de type variqueux':
        add('Dilatation de bronches variqueuses')
        add('Dilatation des bronches variqueuses')
        add('Dilatation bronchique variqueuse')



    # V19 : variantes supplementaires issues de notationgenrique et des paragraphes explicatifs.
    # Elles permettent d'annoter les formulations longues, pas seulement les valeurs SWRL exactes.
    if n == 'rhinite':
        add('Rhinite allergique')
    if n == 'conjonctivite':
        add('Conjonctivite allergique')
    if n == 'eczema':
        add('Terrain atopique eczéma')
        add('Eczéma atopique')
    if n == 'asthme':
        add("Antécédents familiaux d'asthme")
        add('Antécédents familiaux d’asthme')
        add('Asthme familial')
    if n == 'tabac actif':
        add('Tabagisme actif')
        add('Tabac')
        add('Tabagisme')
    if n == 'toux productive':
        add('Toux productive chronique')
        add('Toux productive persistante')
    if n == 'toux seche':
        add('Toux sèche persistante')
        add('Toux seche persistante')
    if n == 'infections bronchiques':
        add('Infections bronchiques répétées')
        add('Infections bronchiques repetees')
        add('Infections bronchiques récidivantes')
        add('Infections bronchiques recidivantes')
    if n == 'sifflement':
        add('Sifflements')
        add('Sifflements respiratoires')
        add('Respiration sifflante')
    if n == 'sifflements':
        add('Sifflement')
        add('Sifflements respiratoires')
        add('Respiration sifflante')
    if n == 'rales sibilants':
        add('Râles sibilants diffus')
        add('Sibilants')
        add('Respiration sifflante')
    if n == 'rales ronflants':
        add('Ronflants')
        add('Râles ronflants bronchiques')
    if n == 'rales crepitants':
        add('Crépitants')
        add('Crépitants fins')
        add('Crépitants bilatéraux')
        add('Râles crépitants diffus')
    if n == 'crepitants fins':
        add('Crépitants fins bibasaux')
        add('Râles crépitants fins')
    if n == 'dyspnee':
        add('Dyspnée progressive')
        add('Dyspnée aiguë')
        add('Dyspnée sévère')
        add('Dyspnée de repos')
        add('Dyspnée soudaine')
    if n == 'douleur thoracique':
        add('Douleur thoracique aiguë')
        add('Douleurs thoraciques')
        add('Douleur thoracique pleurétique')
    if n == 'crachat de sang':
        add('Hémoptysie')
        add('Hemoptysie')
        add('Crachats de sang')
    if n == 'hemoptysie':
        add('Crachat de sang')
        add('Crachats de sang')
    if n == 'fievre':
        add('Fièvre élevée')
        add('Fièvre modérée')
    if n == 'fatigue':
        add('Asthénie')
    if n == 'asthenie':
        add('Fatigue')
    if n == 'opacites en verre depoli bilaterales':
        add('Opacités en verre dépoli')
    if n == 'infiltrats pulmonaires diffus':
        add('Infiltrats diffus')
        add('Infiltrats diffus bilatéraux')
    if n == 'infiltrat alveolaire':
        add('Infiltrat alvéolaire localisé')
        add('Opacité alvéolaire localisée')
        add('Opacité lobaire')
    if n == 'syndrome interstitiel':
        add('Atteinte interstitielle')
        add('Syndrome interstitiel radiologique')
    if n == 'rarefaction de la vascularisation':
        add('Raréfaction vasculaire')
        add('Raréfaction de la vascularisation pulmonaire')
    if n == 'diminution de murmure vesiculaire':
        add('Diminution du murmure vésiculaire')
        add('Murmure vésiculaire diminué')
    if n == 'expiration a levres pincee':
        add('Expiration à lèvres pincées')
    if n == 'index d apnees hypopnees 15':
        add('Index d’apnées-hypopnées supérieur à 15')
        add('IAH > 15')
    if n == 'pcr positive virus respiratoire':
        add('PCR virale positive')
        add('PCR positive')
    if n == 'pcr virale positive':
        add('PCR positive virus respiratoire')
    if n == 'angio tdm embole pulmonaire':
        add('Angio-TDM thoracique montrant un embole pulmonaire')
        add('Embolie artère pulmonaire')
    if n == 'embolie artere pulmonaire':
        add('Angio-TDM: Embole pulmonaire')
        add('Embole pulmonaire')
    return variants



def parse_target_rules_from_owl(owl_path):
    """
    Génère automatiquement les TargetRule depuis onto.owl uniquement :
      1) valeurs utilisées dans le corps des règles SWRL ;
      2) individus du lexique clinique #TermeClinique.

    Donc si tu ajoutes un terme ou une règle dans onto.owl, il devient
    détectable sans écrire de TargetRule à la main dans Python.
    """
    values_by_prop, _ = _parse_owl(owl_path)
    values_by_prop = _merge_notation_terms(values_by_prop)

    rules = []
    seen  = set()
    unknown_props = set()

    for prop, vals in sorted(values_by_prop.items()):
        label = _PROP_TO_LABEL.get(prop)
        if not label:
            label = re.sub(r"[^A-Za-z0-9_]+", "_", _strip_accents(prop)).upper()
            unknown_props.add(prop)

        for val in sorted(vals, key=lambda x: (-len(_norm_key(x).split()), _norm_key(x))):
            for display_text, pattern in _make_all_patterns(val):
                key = (_norm_key(display_text), label)
                if key in seen:
                    continue
                seen.add(key)
                rules.append(TargetRule(display_text, label, pattern=pattern))

    if unknown_props:
        print(f"[nlp_engine] Proprietes sans mapping explicite : {sorted(unknown_props)}")
        print("[nlp_engine] Elles sont quand meme chargees avec un label fallback en MAJUSCULES.")

    return rules

def parse_swrl_rules_from_owl(owl_path):
    _, raw_rules = _parse_owl(owl_path)

    result = []
    for r in raw_rules:
        pid = r['patho_id']
        label, bg, bord = _PATHO_META.get(pid, (pid.replace('_', ' '), '#f5f5f5', '#999999'))
        result.append({
            'pathologie_id': pid,
            'pathologie':    label,
            'couleur':       bg,
            'couleur_bord':  bord,
            'rule_text':     r['rule_text'],
            'body_atoms':    r['body_atoms'],
            'source':        r.get('source', 'onto.owl'),
        })
    return result


# ══════════════════════════════════════════════════════════════
# C. Chargement dynamique des règles depuis l'ontologie
# Objectif : aucune TargetRule médicale codée en dur dans le matcher.
# Les TargetRule sont générées depuis onto.owl uniquement, puis rechargées
# automatiquement si onto.owl change.
# ══════════════════════════════════════════════════════════════

target_matcher = None
_owl_target_rules = []
SWRL_RULES = []
_RULES_LOADED_MTIME = None  # mtime de onto.owl
_CLINICAL_TERMS = []
_MAX_CLINICAL_WORDS = 1
_CLINICAL_BY_WORD_COUNT = defaultdict(list)
_OWL_ENTITY_LEXICON = []  # fallback matcher : termes OWL -> labels NLP


def _build_owl_entity_lexicon():
    """Construit un lexique de fallback depuis onto.owl.

    Pourquoi ? Le medspacy_target_matcher peut parfois rater des petites entités
    ou perdre un match quand il y a beaucoup de règles proches. Ce fallback scanne
    le texte token par token après le pipeline medspaCy et ajoute les entités OWL
    manquantes sans toucher au texte.
    """
    values_by_prop, _ = _parse_owl(ONTO_PATH)
    values_by_prop = _merge_notation_terms(values_by_prop)
    lexicon = []
    seen = set()

    for prop, vals in values_by_prop.items():
        label = _PROP_TO_LABEL.get(prop)
        if not label:
            label = re.sub(r"[^A-Za-z0-9_]+", "_", _strip_accents(prop)).upper()

        for val in vals:
            expanded = [val]
            try:
                expanded = _expand_value_variants(prop, val)
            except Exception:
                expanded = [val]

            for v in expanded:
                n = _norm_key(v)
                if not n:
                    continue
                key = (n, label)
                if key in seen:
                    continue
                seen.add(key)
                lexicon.append({
                    "norm": n,
                    "words": n.split(),
                    "n_words": len(n.split()),
                    "label": label,
                    "text": v,
                })

    # Longs termes d'abord : ex. "oppression thoracique" avant "oppression".
    lexicon.sort(key=lambda x: (-x["n_words"], -len(x["norm"]), x["norm"]))
    return lexicon


def _add_missing_ontology_entities(doc):
    """Ajoute les entités OWL manquées par medspaCy.

    Le matching se fait sur la forme normalisée des tokens du texte analysé :
    accents/casse ignorés, ponctuation ignorée. Exemple :
    - "eczéma)" -> ATOPIE
    - "dyspnée," -> SYMPTOME
    - "râles sibilants" -> EXAMENCLI
    - "trouble ventilatoire obstructif réversible" -> EXPLFONCRESP
    """
    if not _OWL_ENTITY_LEXICON:
        return doc

    tokens = []
    for tok in doc:
        n = _norm_key(tok.text)
        if not n:
            continue
        # Certains tokens peuvent contenir plusieurs mots après normalisation.
        # Pour la majorité des cas cliniques ici, un token = un mot.
        if len(n.split()) == 1:
            tokens.append((tok.i, n))

    if not tokens:
        return doc

    # On garde les entités déjà trouvées par medspaCy, puis on ajoute aussi
    # les candidats OWL même s'ils chevauchent une entité existante.
    # filter_spans() gardera ensuite automatiquement la plus longue.
    # Exemple : si medspaCy trouve "toux" mais le fallback OWL trouve
    # "toux sèche", le résultat final sera "toux sèche".
    new_spans = list(doc.ents)
    added_keys = {(ent.start_char, ent.end_char, ent.label_) for ent in doc.ents}

    # Index par longueur pour éviter trop de boucles.
    by_len = defaultdict(list)
    for item in _OWL_ENTITY_LEXICON:
        if 1 <= item["n_words"] <= 12:
            by_len[item["n_words"]].append(item)

    max_len = min(12, max(by_len.keys() or [1]))
    for n_words in range(max_len, 0, -1):
        candidates = by_len.get(n_words, [])
        if not candidates:
            continue
        cand_by_norm = defaultdict(list)
        for c in candidates:
            cand_by_norm[c["norm"]].append(c)

        for i in range(0, len(tokens) - n_words + 1):
            tok_slice = tokens[i:i+n_words]
            # S'assurer que les tokens sont consécutifs dans le Doc spaCy.
            if tok_slice[-1][0] - tok_slice[0][0] != n_words - 1:
                continue
            norm_window = " ".join(t[1] for t in tok_slice)
            matches = cand_by_norm.get(norm_window)
            if not matches:
                continue

            start_tok = tok_slice[0][0]
            end_tok = tok_slice[-1][0] + 1
            # Prendre le premier label; les doublons exacts sont rares. Si un même terme
            # existe dans deux catégories, l'ontologie doit préciser une variante.
            label = matches[0]["label"]
            span = Span(doc, start_tok, end_tok, label=label)
            key = (span.start_char, span.end_char, span.label_)
            if key in added_keys:
                continue
            new_spans.append(span)
            added_keys.add(key)

    # Résolution finale des chevauchements : priorité aux expressions longues.
    # Corrige notamment : "toux" + "sèche" -> "toux sèche".
    doc.ents = filter_spans(new_spans)
    return doc


def _expand_entities_to_longest_owl_terms(doc):
    """Étend les entités existantes vers le plus long terme présent dans onto.owl.

    Exemple : si medspaCy détecte seulement "Dyspnée" mais que l'ontologie
    contient "Dyspnée progressive", cette fonction remplace l'entité courte
    par l'entité longue. Aucun terme médical n'est codé en dur ici : la décision
    vient uniquement du lexique extrait de onto.owl.
    """
    if not _OWL_ENTITY_LEXICON or not doc.ents:
        return doc

    # Index rapide : norme complète -> labels possibles
    owl_by_norm = defaultdict(set)
    max_words = 1
    for item in _OWL_ENTITY_LEXICON:
        norm = item.get("norm", "")
        label = item.get("label", "")
        if not norm or not label:
            continue
        owl_by_norm[norm].add(label)
        max_words = max(max_words, item.get("n_words", len(norm.split())))

    # Normalisation token par token, en gardant l'index spaCy.
    token_norms = []
    for tok in doc:
        n = _norm_key(tok.text)
        if n and len(n.split()) == 1:
            token_norms.append((tok.i, n))

    if not token_norms:
        return doc

    norm_by_i = {i: n for i, n in token_norms}
    new_spans = []

    for ent in doc.ents:
        best_start = ent.start
        best_end = ent.end
        best_len = ent.end - ent.start
        label = ent.label_

        # Essayer toutes les fenêtres qui commencent au début de l'entité.
        # Cela règle les cas : "dyspnée" + "progressive", "toux productive" + "chronique", etc.
        current_words = []
        last_i = None
        for tok_i in range(ent.start, min(len(doc), ent.start + max_words)):
            n = norm_by_i.get(tok_i)
            if not n:
                break
            if last_i is not None and tok_i != last_i + 1:
                break
            current_words.append(n)
            last_i = tok_i
            norm_window = " ".join(current_words)
            if label in owl_by_norm.get(norm_window, set()):
                cand_len = tok_i + 1 - ent.start
                if cand_len > best_len:
                    best_end = tok_i + 1
                    best_len = cand_len

        new_spans.append(Span(doc, best_start, best_end, label=label))

    # Ajouter aussi les entités initiales non modifiées puis résoudre les chevauchements.
    doc.ents = filter_spans(new_spans)
    return doc


def _rebuild_clinical_index():
    """Reconstruit l'index de correction locale avec les termes OWL actuels."""
    global _CLINICAL_TERMS, _MAX_CLINICAL_WORDS, _CLINICAL_BY_WORD_COUNT
    global _OWL_ENTITY_LEXICON, _PREFERRED_CLINICAL_DISPLAY
    global _CLINICAL_EXACT_NORMS, _CLINICAL_TOKEN_NORMS

    _PREFERRED_CLINICAL_DISPLAY = _build_preferred_display_from_owl()

    _CLINICAL_TERMS = _build_clinical_terms()
    _OWL_ENTITY_LEXICON = _build_owl_entity_lexicon()
    _MAX_CLINICAL_WORDS = max([_word_count(t) for t in _CLINICAL_TERMS] or [1])

    _CLINICAL_BY_WORD_COUNT = defaultdict(list)
    _CLINICAL_EXACT_NORMS = set()
    _CLINICAL_TOKEN_NORMS = set()

    for term in _CLINICAL_TERMS:
        key = _norm_key(term)
        if not key:
            continue

        wc = _word_count(term)
        _CLINICAL_BY_WORD_COUNT[wc].append((key, term))
        _CLINICAL_EXACT_NORMS.add(key)
        _CLINICAL_TOKEN_NORMS.update(_content_tokens_norm(term))

        # variantes via synonymes simples déjà définis.
        # Important : elles servent surtout à la DÉTECTION, pas à imposer une
        # forme canonique quand le texte original est déjà cliniquement valide.
        for raw, syns in _SYNONYMES.items():
            for syn in syns:
                term_words = _norm_key(term).split()
                raw_norm = _norm_key(raw)
                if raw_norm in term_words:
                    variant_words = [(_norm_key(syn) if w == raw_norm else w) for w in term_words]
                    variant_key = ' '.join(variant_words)
                    _CLINICAL_BY_WORD_COUNT[wc].append((variant_key, term))
                    _CLINICAL_EXACT_NORMS.add(variant_key)
                    _CLINICAL_TOKEN_NORMS.update([w for w in variant_words if w not in _DET_OPTIONNELS and len(w) > 2])

    print(f"[nlp_engine] {len(_CLINICAL_TERMS)} termes cliniques proteges depuis l'OWL")
    print(f"[nlp_engine] {len(_OWL_ENTITY_LEXICON)} termes fallback OWL/notation prets pour annotation")


def reload_ontology_rules(force=False):
    """
    Recharge les TargetRule et les règles SWRL depuis onto.owl.
    - force=True : rechargement obligatoire au démarrage.
    - force=False : rechargement seulement si onto.owl a été modifié.

    Important : medspaCy ne nettoie pas toujours facilement les anciennes règles.
    Pour éviter les doublons, on reconstruit le pipeline NLP quand l'ontologie change.
    """
    global nlp, target_matcher, _owl_target_rules, SWRL_RULES, _RULES_LOADED_MTIME

    mtime = os.path.getmtime(ONTO_PATH)
    if not force and _RULES_LOADED_MTIME == mtime:
        return False

    if _RULES_LOADED_MTIME is not None:
        print('[nlp_engine] Changement detecte dans onto.owl -> rechargement des regles NLP')
        nlp, _ = _load_nlp_with_vectors()

    target_matcher = nlp.get_pipe("medspacy_target_matcher")

    _owl_target_rules = parse_target_rules_from_owl(ONTO_PATH)
    target_matcher.add(_owl_target_rules)

    SWRL_RULES = parse_swrl_rules_from_owl(ONTO_PATH)
    _RULES_LOADED_MTIME = mtime

    _rebuild_clinical_index()

    print(f"[nlp_engine] {len(_owl_target_rules)} TargetRule chargees dynamiquement depuis onto.owl")
    print(f"[nlp_engine] {len(SWRL_RULES)} regles SWRL chargees")
    print(f"[nlp_engine] Pathologies : {sorted(set(r['pathologie_id'] for r in SWRL_RULES))}")
    return True


# Premier chargement au démarrage Django
# Source unique : onto.owl. Aucune TargetRule médicale manuelle n’est ajoutée au matcher.

# ══════════════════════════════════════════════════════════════
# D. Correction médicale locale sécurisée
#    But : corriger les termes cliniques mal écrits AVANT l'IA
#    et protéger ces termes pendant la correction grammaticale.
# ══════════════════════════════════════════════════════════════

_WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]+(?:[-’'][A-Za-zÀ-ÖØ-öø-ÿ0-9]+)?", re.UNICODE)


def _strip_accents(text):
    text = unicodedata.normalize('NFD', str(text))
    return ''.join(ch for ch in text if unicodedata.category(ch) != 'Mn')


def _norm_key(text):
    text = _strip_accents(str(text)).lower()
    text = text.replace("’", "'")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# ══════════════════════════════════════════════════════════════
# Fallback contexte : detecter les entites selon les rubriques du texte
# Exemple : "Antecedents familiaux d'asthme" doit donner
# "Asthme" avec le label ANTECEDENT_FAMILIAL, pas SYMPTOME/PATHOLOGIE.
# ══════════════════════════════════════════════════════════════
_SECTION_CONTEXT_LABELS = [
    ("ANTECEDENT_FAMILIAL", [
        "antecedent familial", "antecedents familiaux", "antecedents familial", "ant familial", "ant fam"
    ]),
    ("ANTECEDENT_PERSONNEL", [
        "antecedent personnel", "antecedents personnels", "ant personnel", "ant pers"
    ]),
    ("ATOPIE", [
        "terrain atopique", "atopie", "atopique"
    ]),
    ("SYMPTOME", [
        "symptome", "symptomes", "symptomes respiratoires", "plainte", "plaintes"
    ]),
    ("EXAMENCLI", [
        "examen clinique", "auscultation", "clinique"
    ]),
    ("EXPLFONCRESP", [
        "exploration fonctionnelle respiratoire", "efr", "spirometrie", "spirometrie"
    ]),
    ("RADIOLOGIE", [
        "radiographie", "radio", "rx thorax", "radiographie thoracique"
    ]),
    ("TDM", [
        "tdm", "scanner", "scanner thoracique"
    ]),
    ("BIOLOGIE", [
        "biologie", "bilan biologique", "test laboratoire", "test de laboratoire", "gazometrie"
    ]),
    ("HABITUDE_VIE", [
        "habitude de vie", "habitudes de vie", "tabac", "tabagisme"
    ]),
    ("FACTEUR_RISQUE", [
        "facteur de risque", "facteurs de risque", "age risque"
    ]),
    ("EXPOSITION", [
        "exposition", "expositions"
    ]),
    ("IMMUNOSUPPRESSION", [
        "immunosuppression", "immunodepression"
    ]),
]


def _context_label_for_segment(segment_text):
    """Retourne le label clinique attendu selon l'intitule de la ligne/rubrique."""
    n = _norm_key(segment_text)
    if not n:
        return None
    # Priorite au texte avant ':' si present : "Symptomes : ..."
    before_colon = segment_text.split(':', 1)[0] if ':' in segment_text else segment_text
    h = _norm_key(before_colon)
    for label, keys in _SECTION_CONTEXT_LABELS:
        for key in keys:
            k = _norm_key(key)
            if k and (k in h or h in k or k in n):
                return label
    return None


def _segment_offsets(text):
    """Decoupe le texte en segments avec offsets, sans perdre les positions originales."""
    if not text:
        return []
    segments = []
    # Lignes d'abord, puis on garde aussi les morceaux separes par ';'
    for line_m in re.finditer(r"[^\n\r]+", text):
        line = line_m.group(0)
        base = line_m.start()
        start = 0
        for part_m in re.finditer(r"[^;]+", line):
            part = part_m.group(0)
            s = base + part_m.start()
            e = base + part_m.end()
            if part.strip():
                segments.append((s, e, text[s:e]))
    return segments


def _add_contextual_section_entities(doc):
    """Ajoute les entites manquees en utilisant le contexte de rubrique.

    Le matcher OWL detecte les termes par valeur. Mais certains termes changent de
    categorie selon la phrase : "asthme" dans "antecedents familiaux d'asthme"
    doit etre ANTECEDENT_FAMILIAL. Cette fonction lit les titres de lignes
    (antecedents familiaux, symptomes, EFR, examen clinique, etc.) puis cherche les
    termes OWL de la categorie correspondante dans cette zone.
    """
    if not _OWL_ENTITY_LEXICON:
        return doc

    text = doc.text
    new_spans = list(doc.ents)
    added_keys = {(ent.start_char, ent.end_char, ent.label_) for ent in doc.ents}

    # Index candidates par label et longueur.
    by_label_len = defaultdict(lambda: defaultdict(list))
    for item in _OWL_ENTITY_LEXICON:
        label = item.get("label")
        n_words = int(item.get("n_words", 0) or 0)
        norm = item.get("norm", "")
        if not label or not norm or n_words <= 0 or n_words > 12:
            continue
        by_label_len[label][n_words].append(item)

    for seg_start, seg_end, segment in _segment_offsets(text):
        expected_label = _context_label_for_segment(segment)
        if not expected_label:
            continue

        # Chercher seulement apres ':' quand il existe, sinon dans toute la ligne.
        local_start = 0
        if ':' in segment:
            local_start = segment.index(':') + 1
        search_start = seg_start + local_start
        search_end = seg_end

        # Tokens du doc dans la zone.
        zone_tokens = []
        for tok in doc:
            if tok.idx < search_start or tok.idx + len(tok.text) > search_end:
                continue
            n = _norm_key(tok.text)
            if n and len(n.split()) == 1:
                zone_tokens.append((tok.i, n))

        if not zone_tokens:
            continue

        candidates_by_len = by_label_len.get(expected_label, {})
        if not candidates_by_len:
            continue

        max_len = min(12, max(candidates_by_len.keys() or [1]))
        for n_words in range(max_len, 0, -1):
            candidates = candidates_by_len.get(n_words, [])
            if not candidates:
                continue
            cand_by_norm = defaultdict(list)
            for c in candidates:
                cand_by_norm[c["norm"]].append(c)

            for i in range(0, len(zone_tokens) - n_words + 1):
                tok_slice = zone_tokens[i:i+n_words]
                if tok_slice[-1][0] - tok_slice[0][0] != n_words - 1:
                    continue
                norm_window = " ".join(t[1] for t in tok_slice)
                matches = cand_by_norm.get(norm_window)
                if not matches:
                    continue
                start_tok = tok_slice[0][0]
                end_tok = tok_slice[-1][0] + 1
                span = Span(doc, start_tok, end_tok, label=expected_label)
                key = (span.start_char, span.end_char, span.label_)
                if key in added_keys:
                    continue
                new_spans.append(span)
                added_keys.add(key)

        # Cas conceptuel utile : "terrain atopique" sans valeur OWL precise.
        # On ajoute la rubrique elle-meme comme ATOPIE si aucun terme ATOPIE n'a ete trouve dans la ligne.
        if expected_label == "ATOPIE":
            seg_norm = _norm_key(segment)
            has_atopie = any(ent.label_ == "ATOPIE" and ent.start_char >= seg_start and ent.end_char <= seg_end for ent in new_spans)
            if not has_atopie and ("terrain atopique" in seg_norm or "atopique" in seg_norm):
                for m in re.finditer(r"terrain\s+atopique|atopique", segment, flags=re.I):
                    span = doc.char_span(seg_start + m.start(), seg_start + m.end(), label="ATOPIE", alignment_mode="expand")
                    if span is None:
                        continue
                    key = (span.start_char, span.end_char, span.label_)
                    if key not in added_keys:
                        new_spans.append(span)
                        added_keys.add(key)
                    break

    doc.ents = filter_spans(new_spans)
    return doc


def _word_count(text):
    return len(_norm_key(text).split())


_CLINICAL_EXACT_NORMS = set()
_CLINICAL_TOKEN_NORMS = set()


def _content_tokens_norm(text):
    """Tokens normalisés utiles, hors déterminants courts."""
    return [
        t for t in _norm_key(text).split()
        if t and t not in _DET_OPTIONNELS and len(t) > 2
    ]


def _is_already_clinical_valid(text):
    """
    True si le texte correspond déjà à une forme/variante clinique connue.

    But V9 : ne pas transformer automatiquement un terme médical valide en une
    autre forme canonique de l'ontologie. Exemples bloqués :
      - ronflants -> Ronflement
      - Raréfaction vasculaire -> Raréfaction vascularisation
      - Expiration à lèvres pincées -> Expiration à lèvres pincée

    La correction locale reste autorisée pour les vraies fautes : dyspne, fievrr,
    thoracik, ventillatoire, etc.
    """
    norm = _norm_key(text)
    if not norm:
        return False

    if norm in _CLINICAL_EXACT_NORMS:
        return True

    toks = _content_tokens_norm(text)
    if not toks:
        return False

    # Un mot seul déjà présent dans les termes OWL ne doit pas être remplacé par
    # un autre mot médical juste parce qu'il lui ressemble.
    if len(toks) == 1 and toks[0] in _CLINICAL_TOKEN_NORMS:
        return True

    # Pour une expression, si tous les mots porteurs de sens existent déjà dans
    # le vocabulaire clinique, on considère que c'est une formulation valide.
    # Cela évite les reformulations dangereuses de style.
    known = sum(1 for t in toks if t in _CLINICAL_TOKEN_NORMS)
    if len(toks) >= 2 and known == len(toks):
        return True

    return False


# Affichage préféré dynamique : construit depuis onto.owl.
# But : éviter d'afficher une variante moins propre si l'ontologie contient
# aussi la forme accentuée/canonique. Exemple : dyspnee -> dyspnée.
_PREFERRED_CLINICAL_DISPLAY = {}


def _display_quality(text):
    """Score simple pour choisir la meilleure forme d'affichage depuis l'OWL."""
    t = str(text or '').strip()
    if not t:
        return -999
    score = 0
    if _has_accents(t):
        score += 10
    if not t.isupper():
        score += 2
    # Garder les abréviations médicales connues quand elles existent dans l'OWL.
    if t.upper() in {'TVO', 'TVR', 'EFR', 'VEMS', 'BPCO', 'DDB', 'TDM', 'PCR'}:
        score += 5
    # Les formes trop bizarres sont pénalisées.
    if re.search(r'[A-Za-zÀ-ÖØ-öø-ÿ]{2,}s{2,}$', t):
        score -= 5
    return score


def _build_preferred_display_from_owl():
    pref = {}
    try:
        values_by_prop, _ = _parse_owl(ONTO_PATH)
    except Exception as e:
        print('[clinical correction] Impossible de construire affichage OWL :', e)
        return pref

    for vals in values_by_prop.values():
        for val in vals:
            candidates = [val]
            try:
                candidates.extend(_expand_value_variants('', val))
            except Exception:
                pass
            for c in candidates:
                n = _norm_key(c)
                if not n:
                    continue
                current = pref.get(n)
                if current is None or _display_quality(c) > _display_quality(current):
                    pref[n] = str(c).strip()
    return pref



def _has_accents(text):
    return _strip_accents(text) != str(text)


def _preferred_display(term):
    return _PREFERRED_CLINICAL_DISPLAY.get(_norm_key(term), term)


_NEGATION_TOKENS = {'non', 'pas', 'sans', 'absence', 'aucun', 'aucune', 'ni'}

# Mots qui changent le sens clinique si on les ajoute/supprime par fuzzy matching.
# Exemple dangereux vu dans l'interface : "réversible" -> "non réversible".
_MODIFIER_EQUIV = {
    'reversible': 'reversible', 'reversibilite': 'reversible',
    'partielle': 'partielle', 'partiel': 'partielle',
    'irreversible': 'irreversible',
    # Important : ne jamais transformer obstructif <-> restrictif par fuzzy matching.
    # Ce sont deux profils EFR différents et le sens clinique change complètement.
    'obstructif': 'obstructif', 'obstructive': 'obstructif',
    'restrictif': 'restrictif', 'restrictive': 'restrictif',
    'severe': 'severe', 'severes': 'severe',
    'aigue': 'aigue', 'aigu': 'aigue',
    'chronique': 'chronique', 'chroniques': 'chronique',
    'productive': 'productive', 'productif': 'productive',
    'seche': 'seche', 'sec': 'seche',
    'bacterienne': 'bacterienne', 'bacterien': 'bacterienne',
    'virale': 'virale', 'viral': 'virale',
    'positive': 'positive', 'positif': 'positive',
    'negative': 'negative', 'negatif': 'negative',
    'bilaterale': 'bilateral', 'bilaterales': 'bilateral', 'bilateraux': 'bilateral', 'bilateral': 'bilateral',
    'localise': 'localise', 'localisee': 'localise',
    'diffus': 'diffus', 'diffuse': 'diffus', 'diffuses': 'diffus',
    'fins': 'fins', 'fin': 'fins', 'fines': 'fins',
    'bibasaux': 'bibasaux', 'bibasal': 'bibasaux',
    'progressive': 'progressif', 'progressif': 'progressif',
    'nocturne': 'nocturne', 'nocturnes': 'nocturne',
}


def _token_set_norm(text):
    return set(_norm_key(text).split())


def _modifier_signature(text):
    return {_MODIFIER_EQUIV[t] for t in _norm_key(text).split() if t in _MODIFIER_EQUIV}


def _clinical_match_safe(original, canonical):
    """Refuse les corrections fuzzy qui ajoutent/suppriment une negation ou un modificateur clinique."""
    orig_tokens = _token_set_norm(original)
    cand_tokens = _token_set_norm(canonical)

    # Ne jamais ajouter/supprimer une négation clinique.
    if (orig_tokens & _NEGATION_TOKENS) != (cand_tokens & _NEGATION_TOKENS):
        return False

    # Ne jamais ajouter/supprimer un modificateur clinique important.
    # On autorise seulement les variantes d'écriture dans le même groupe : productif/productive, positif/positive, etc.
    if _modifier_signature(original) != _modifier_signature(canonical):
        return False

    # Si le candidat ajoute des mots par rapport à l'original, il faut être très prudent.
    # On bloque surtout les ajouts de mots porteurs de sens.
    added = cand_tokens - orig_tokens
    if added & (_NEGATION_TOKENS | set(_MODIFIER_EQUIV.keys())):
        return False

    return True


def _rule_literal(rule):
    # medspacy TargetRule garde généralement le texte dans .literal
    return getattr(rule, 'literal', None) or getattr(rule, 'literal_', None) or ''


def _add_term(terms, term):
    term = re.sub(r"\s+", " ", str(term or '')).strip()
    if not term:
        return
    # éviter les variables OWL/SWRL et les déterminants isolés
    if _norm_key(term) in {'a', 'd', 'de', 'du', 'des', 'le', 'la', 'les'}:
        return
    if len(_norm_key(term)) < 3:
        return
    terms.add(term)


def _build_clinical_terms():
    """
    Construit le dictionnaire clinique protégé à partir de l'ontologie.
    Les termes viennent principalement des valeurs utilisées dans le corps
    des règles SWRL et des TargetRule OWL générées.
    """
    terms = set()

    # 1) termes présents dans le corps des règles OWL/SWRL
    try:
        values_by_prop, raw_rules = _parse_owl(ONTO_PATH)
        for vals in values_by_prop.values():
            for val in vals:
                _add_term(terms, val)
        for r in raw_rules:
            for _, val in r.get('body_atoms', []):
                _add_term(terms, val)

        # 1-bis) termes supplementaires venant de notationgenrique.txt / dictionnaire embarque
        for vals in _load_notation_terms_by_prop().values():
            for val in vals:
                _add_term(terms, val)
    except Exception as e:
        print('[clinical correction] Impossible de lire les termes OWL/notationgenrique :', e)

    # 2) termes des TargetRule générées automatiquement depuis l'OWL
    for rule in _owl_target_rules:
        _add_term(terms, _rule_literal(rule))

    # 3) noms affichés de pathologies déjà connus côté interface
    for label, _, _ in _PATHO_META.values():
        _add_term(terms, label)

    # 4) formes préférées construites depuis l’OWL pour l’affichage/correction locale
    for term in _PREFERRED_CLINICAL_DISPLAY.values():
        _add_term(terms, term)

    return sorted(terms, key=lambda t: (-_word_count(t), -len(t), _norm_key(t)))



# Chargement effectif après définition des fonctions utilisées par l'index clinique
reload_ontology_rules(force=True)


def _similarity(a, b):
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def _threshold_for(norm_text):
    # V11 : seuils plus stricts.
    # Objectif : corriger les vraies fautes proches (dyspne -> dyspnée,
    # ventillatoire -> ventilatoire), mais ne plus reformuler des termes
    # valides en termes voisins de l'ontologie (ronflants -> Ronflement,
    # vasculaire -> vascularisation, pincées -> pincée, etc.).
    ln = len(norm_text)
    wc = len(norm_text.split())
    if wc >= 4:
        return 0.92
    if wc == 3:
        return 0.91
    if wc == 2:
        return 0.90
    if ln >= 6:
        return 0.92
    return 0.94


def _best_clinical_match(window_text, n_words):
    norm = _norm_key(window_text)
    if len(norm) < 3:
        return None

    # V9 : si le segment est déjà une formulation clinique connue/acceptable
    # d'après l'ontologie, on ne le remplace pas par une forme canonique.
    # La détection/annotation se fera par TargetRules + fallback OWL.
    if _is_already_clinical_valid(window_text):
        return None

    best = None
    for cand_norm, canonical_raw in _CLINICAL_BY_WORD_COUNT.get(n_words, []):
        if not cand_norm:
            continue

        canonical = _preferred_display(canonical_raw)

        # Protection pour les mots courts : même première lettre obligatoire.
        if n_words == 1 and cand_norm[0] != norm[0]:
            continue

        # Évite les correspondances de longueur trop éloignée.
        if n_words == 1 and abs(len(cand_norm) - len(norm)) > max(2, int(len(cand_norm) * 0.35)):
            continue

        # Sécurité clinique : refuser toute correction qui ajoute/supprime une négation
        # ou un modificateur important (non, sévère, réversible, productive, etc.).
        if not _clinical_match_safe(window_text, canonical):
            continue

        score = _similarity(norm, cand_norm)
        if score >= _threshold_for(cand_norm):
            if best is None or score > best[0] or (score == best[0] and len(cand_norm) > len(best[1])):
                best = (score, cand_norm, canonical)

    if not best:
        return None

    score, _, canonical = best
    window_clean = window_text.strip()

    # Si la forme normalisée est identique, ne pas afficher une correction inutile
    # de casse seulement : "Toux" -> "toux", "Râles" -> "râles".
    if _norm_key(window_clean) == _norm_key(canonical):
        if window_clean.lower() == canonical.lower():
            return None
        # Ne jamais remplacer un terme déjà accentué par une variante sans accents.
        if _has_accents(window_clean) and not _has_accents(canonical):
            return None
        # Autoriser seulement l'amélioration utile : forme sans accents -> forme accentuée préférée.
        if not _has_accents(window_clean) and _has_accents(canonical):
            return canonical, score
        return None

    return canonical, score


def _corriger_termes_cliniques_locaux(texte):
    """
    Corrige uniquement les termes cliniques proches du dictionnaire OWL/TargetRules.
    Ne touche pas à la négation, ne complète pas le diagnostic.
    """
    if not texte:
        return texte, []

    words = list(_WORD_RE.finditer(texte))
    used = set()
    replacements = []

    max_n = min(_MAX_CLINICAL_WORDS, 7)
    for n in range(max_n, 0, -1):
        for i in range(0, len(words) - n + 1):
            idxs = set(range(i, i + n))
            if used & idxs:
                continue

            start = words[i].start()
            end = words[i + n - 1].end()
            window = texte[start:end]
            match = _best_clinical_match(window, n)
            if not match:
                continue

            canonical, score = match
            if window.strip() == canonical:
                continue

            replacements.append((start, end, window, canonical, score, idxs))
            used |= idxs

    if not replacements:
        return texte, []

    corrected = texte
    corrections = []
    for start, end, original, canonical, score, _ in sorted(replacements, key=lambda x: x[0], reverse=True):
        corrected = corrected[:start] + canonical + corrected[end:]
        corrections.append({
            'original': original,
            'corrige': canonical,
            'type': 'clinique',
            'explication': f'Terme rapproché du dictionnaire clinique OWL/règles NLP (similarité {round(score * 100)}%).'
        })

    corrections.reverse()
    return corrected, corrections


def _protect_clinical_terms(text):
    """Remplace les termes cliniques déjà corrigés par __CLIN_x__ avant correction IA."""
    spans = []
    occupied = []

    def overlaps(a, b):
        return not (a[1] <= b[0] or b[1] <= a[0])

    for term in _CLINICAL_TERMS:
        if len(term) < 3:
            continue
        pattern = re.compile(r'(?<!\w)' + re.escape(term) + r'(?!\w)', flags=re.IGNORECASE)
        for m in pattern.finditer(text):
            span = (m.start(), m.end())
            if any(overlaps(span, o) for o in occupied):
                continue
            occupied.append(span)
            spans.append((m.start(), m.end(), text[m.start():m.end()]))

    if not spans:
        return text, {}

    placeholders = {}
    protected = text
    for i, (start, end, value) in enumerate(sorted(spans, key=lambda x: x[0], reverse=True)):
        token = f'__CLIN_{i}__'
        placeholders[token] = value
        protected = protected[:start] + token + protected[end:]

    return protected, placeholders


def _restore_clinical_terms(text, placeholders):
    restored = str(text or '')
    for token, value in placeholders.items():
        restored = restored.replace(token, value)
    return restored


def _negation_signature(text):
    norm = ' ' + _norm_key(text) + ' '
    patterns = [' pas de ', ' absence de ', ' sans ', ' aucun ', ' aucune ', ' non ', ' ni ']
    return {p.strip(): norm.count(p) for p in patterns}


def _semantic_safety_ok(original, corrected):
    # Pour un essai PFE : règle simple mais importante.
    # Si le correcteur a ajouté/supprimé une négation ou un modificateur clinique,
    # on refuse la correction IA. Cela bloque notamment :
    #   obstructif -> restrictif
    #   réversible -> non réversible
    #   toux sèche -> toux productive
    if _negation_signature(original) != _negation_signature(corrected):
        return False
    if _modifier_signature(original) != _modifier_signature(corrected):
        return False
    return True


def _detect_clinical_warnings(text):
    """Détecte les formulations cliniquement incohérentes ou risquées.
    On ne les corrige pas automatiquement : on les affiche comme suggestions/alertes.
    """
    warnings = []
    norm = _norm_key(text)

    risky_patterns = [
        (
            r"\btrouble ventilatoire restrictif reversible\b",
            "trouble ventilatoire restrictif réversible",
            "Formulation EFR à vérifier : un trouble restrictif n'est généralement pas décrit comme réversible. Vérifier si le terme voulu était 'trouble ventilatoire obstructif réversible'."
        ),
        (
            r"\btvr reversible\b",
            "TVR réversible",
            "Formulation EFR à vérifier : TVR réversible est ambigu. Vérifier si le terme voulu était TVO réversible."
        ),
    ]

    for pattern, original, explication in risky_patterns:
        if re.search(pattern, norm):
            warnings.append({
                "original": original,
                "corrige": "à vérifier manuellement",
                "type": "alerte clinique",
                "explication": explication,
            })
    return warnings


# ══════════════════════════════════════════════════════════════
# E. Utilitaires vectoriels
# ══════════════════════════════════════════════════════════════

def _remove_determiners(text):
    dets = {'le','la','les','un','une','des','du','de','d','l'}
    words = re.split(r"\s+|[''`]", text.lower())
    return ' '.join(w for w in words if w and w not in dets)


def _vec(text):
    return _vec_nlp(text).vector


def _get_mean_vector(items):
    vectors = []
    if isinstance(items, str):
        v = _vec(_remove_determiners(items))
        if v.any():
            return v
        return None
    for item in items:
        raw = getattr(item, 'lemma_', None) or getattr(item, 'text', str(item))
        v = _vec(_remove_determiners(raw))
        if v.any():
            vectors.append(v)
    return np.mean(vectors, axis=0) if vectors else None


# ══════════════════════════════════════════════════════════════
# E. Correction orthographique / grammaticale / semantique
#    via API Claude
# CORRECTION 1 : en-tête x-api-key ajouté
# ══════════════════════════════════════════════════════════════

def corriger_texte(texte):
    """
    Pipeline hybride de correction médicale :
      1) correction locale prudente des termes cliniques mal écrits,
      2) protection des termes cliniques avec placeholders,
      3) correction grammaticale/orthographique générale par API si disponible,
      4) validation sémantique simple pour ne pas perdre les négations.
    """
    if not texte or not texte.strip():
        return {
            "texte_original": texte,
            "texte_corrige": texte,
            "texte_nlp": texte,
            "corrections": [],
            "suggestions_non_appliquees": [],
            "resume": "Texte vide.",
            "a_des_erreurs": False
        }

    texte_original = texte

    # 1) correction locale des termes cliniques issus de l'OWL et des TargetRules
    texte_clinique, corrections_cliniques = _corriger_termes_cliniques_locaux(texte_original)
    warnings_cliniques = _detect_clinical_warnings(texte_clinique)

    # 2) protéger les termes médicaux avant correction générale
    texte_protege, placeholders = _protect_clinical_terms(texte_clinique)

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    print("[corriger_texte] API KEY OK ?", bool(api_key))

    # Si pas d'API, on garde quand même la correction clinique locale.
    if not api_key:
        resume = "Correction clinique locale appliquée. API grammaticale non configurée."
        if not corrections_cliniques:
            resume = "⚠ API non configurée. Aucune correction clinique locale détectée."
        return {
            "texte_original": texte_original,
            "texte_corrige": texte_clinique,
            "texte_nlp": texte_clinique,
            "corrections": corrections_cliniques,
            "suggestions_non_appliquees": warnings_cliniques,
            "resume": resume,
            "a_des_erreurs": bool(corrections_cliniques or warnings_cliniques or texte_clinique.strip() != texte_original.strip())
        }

    prompt = f"""
Tu es un correcteur de texte clinique en français.

Objectif : corriger uniquement l'orthographe générale, la grammaire et les accords.
Règles strictes :
- Ne change jamais le sens clinique.
- N'ajoute aucun symptôme, examen, maladie ou diagnostic.
- Ne supprime aucun symptôme, examen, maladie ou diagnostic.
- Ne change jamais une négation : "pas de", "absence de", "sans", "aucun", "non", "ni".
- Ne modifie jamais les placeholders de type __CLIN_0__, __CLIN_1__, etc.
- Les placeholders représentent des termes cliniques déjà corrigés et protégés.
- Si une correction est sémantiquement incertaine, mets-la dans "suggestions_non_appliquees" et ne l'applique pas.

Texte à corriger :
<<<TEXTE_CLINIQUE>>>
{texte_protege}
<<<FIN_TEXTE_CLINIQUE>>>

Réponds UNIQUEMENT en JSON valide, sans markdown :
{{
  "texte_corrige": "...",
  "corrections": [
    {{"original":"...", "corrige":"...", "type":"orthographe|grammaire|accord|ponctuation", "explication":"..."}}
  ],
  "suggestions_non_appliquees": [
    {{"original":"...", "suggestion":"...", "type":"semantique", "raison":"..."}}
  ],
  "resume": "...",
  "a_des_erreurs": true
}}
"""

    try:
        payload = _json.dumps({
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 1800,
            "messages": [{"role": "user", "content": prompt}]
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
                "x-api-key": api_key,
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=30) as resp:
            data = _json.loads(resp.read().decode("utf-8"))

        raw = "".join(b["text"] for b in data.get("content", []) if b.get("type") == "text")
        print("[API RAW]:", raw)
        raw = raw.strip()

        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        result = _json.loads(raw)

        texte_api_protege = result.get("texte_corrige", texte_protege)
        texte_api = _restore_clinical_terms(texte_api_protege, placeholders)

        # restaurer aussi les corrections/suggestions de l'API si elles contiennent des placeholders
        corrections_api = []
        for c in result.get("corrections", []) or []:
            corrections_api.append({
                "original": _restore_clinical_terms(c.get("original", ""), placeholders),
                "corrige": _restore_clinical_terms(c.get("corrige", ""), placeholders),
                "type": c.get("type", "grammaire"),
                "explication": c.get("explication", "Correction générale contrôlée.")
            })

        suggestions = []
        for s in result.get("suggestions_non_appliquees", []) or []:
            suggestions.append({
                "original": _restore_clinical_terms(s.get("original", ""), placeholders),
                "suggestion": _restore_clinical_terms(s.get("suggestion", ""), placeholders),
                "type": s.get("type", "semantique"),
                "raison": s.get("raison", "Suggestion non appliquée par sécurité clinique.")
            })

        # Ajouter les alertes cliniques locales même si l'API répond correctement.
        for w in warnings_cliniques:
            suggestions.append({
                "original": w.get("original", ""),
                "suggestion": w.get("corrige", "à vérifier manuellement"),
                "type": w.get("type", "alerte clinique"),
                "raison": w.get("explication", "Formulation clinique à vérifier.")
            })

        # 4) sécurité : si la négation change, refuser la correction IA et garder la correction clinique locale
        if not _semantic_safety_ok(texte_clinique, texte_api):
            suggestions.append({
                "original": texte_api,
                "suggestion": texte_api,
                "type": "securite_semantique",
                "raison": "Correction IA refusée car elle modifie une négation ou un modificateur clinique important."
            })
            texte_final = texte_clinique
            corrections_finales = corrections_cliniques
            resume = "Correction clinique locale appliquée. Correction IA refusée par sécurité sémantique."
        else:
            texte_final = texte_api
            corrections_finales = corrections_cliniques + corrections_api
            resume = result.get("resume", "Correction hybride appliquée.")

        return {
            "texte_original": texte_original,
            "texte_corrige": texte_final,
            "texte_nlp": texte_final,
            "corrections": corrections_finales,
            "suggestions_non_appliquees": suggestions,
            "resume": resume,
            "a_des_erreurs": bool(
                result.get("a_des_erreurs")
                or corrections_finales
                or suggestions
                or texte_final.strip() != texte_original.strip()
            )
        }

    except Exception as e:
        print("[ERREUR API]:", e)
        # En cas d'erreur API, ne pas casser le diagnostic : garder la correction locale.
        return {
            "texte_original": texte_original,
            "texte_corrige": texte_clinique,
            "texte_nlp": texte_clinique,
            "corrections": corrections_cliniques,
            "suggestions_non_appliquees": warnings_cliniques,
            "resume": f"Correction clinique locale appliquée. Erreur API grammaticale : {e}",
            "a_des_erreurs": True
        }


# ══════════════════════════════════════════════════════════════
# F. Fonction principale d'analyse NLP
# CORRECTION 2 : corriger_texte() appelée avant l'analyse
# CORRECTION 3 : score_raw retiré du dict final
# CORRECTION 4 : negatif converti en bool Python natif
# ══════════════════════════════════════════════════════════════

def analyser_texte(texte):
    if not texte or not texte.strip():
        return {"html_annote": "", "entites": [],
                "scores_regles": [], "meilleur_diagnostic": None,
                "correction": None}

    # Recharger automatiquement les règles si onto.owl a changé
    reload_ontology_rules()

    # Correction hybride : utiliser texte_nlp si présent, sinon texte_corrige
    correction = corriger_texte(texte)
    texte_analyse = correction.get("texte_nlp") or correction.get("texte_corrige") or texte

    doc = nlp(texte_analyse)
    # V6 : ajout des entités OWL manquées par le matcher medspaCy
    doc = _add_missing_ontology_entities(doc)
    # V16 : fallback par contexte de rubrique (ex. Antecedents familiaux d'asthme -> ANTECEDENT_FAMILIAL).
    doc = _add_contextual_section_entities(doc)
    # V12 : si une entité courte peut être étendue vers un terme plus long présent dans onto.owl, on garde la plus longue.
    doc = _expand_entities_to_longest_owl_terms(doc)

    html_annote = displacy.render(
        doc, style="ent", page=False, jupyter=False, minify=True,
        options={"colors": _DISPLACY_COLORS}
    )

    entites = [
        {
            "texte": ent.text,
            "label": ent.label_,
            # CORRECTION 4 : conversion explicite en bool Python natif
            "negatif": bool(getattr(ent._, 'is_negated', False))
        }
        for ent in doc.ents
    ]

    # V14 : score par comparaison ENTITES DETECTEES <-> REGLES OWL.
    # Important : on ne cherche plus les valeurs directement dans le texte brut.
    # Une condition OWL est comptee seulement si une entite NLP detectee a :
    #   1) le meme type clinique attendu par la propriete OWL,
    #   2) un texte suffisamment similaire a la valeur de la regle.
    # Exemple : antFam(?d, "Asthme") exige une entite ANTECEDENT_FAMILIAL.
    # Si "Antecedents familiaux d'asthme" n'est pas detecte comme entite,
    # cette condition vaut 0 et le score ne peut pas etre 100%.

    def _label_for_rule_prop(prop):
        label = _PROP_TO_LABEL.get(prop)
        if label:
            return label
        return re.sub(r"[^A-Za-z0-9_]+", "_", _strip_accents(prop)).upper()

    def _criterion_variants(prop, val):
        variants = []
        try:
            variants = _expand_value_variants(prop, val)
        except Exception:
            variants = [val]
        variants.append(val)

        out = []
        seen = set()
        for v in variants:
            n = _norm_key(v)
            if n and n not in seen:
                out.append((str(v), n))
                seen.add(n)
        return out

    def _best_entity_similarity(expected_label, prop, val):
        variants = _criterion_variants(prop, val)
        if not variants:
            return 0.0, ""

        best_score = 0.0
        best_text = ""

        for ent in doc.ents:
            if bool(getattr(ent._, 'is_negated', False)):
                continue
            if ent.label_ != expected_label:
                continue

            ent_norm = _norm_key(ent.text)
            if not ent_norm:
                continue

            for _display, var_norm in variants:
                if not var_norm:
                    continue

                # Match exact ou inclusion d'expression complete.
                if ent_norm == var_norm:
                    score = 1.0
                elif f" {var_norm} " in f" {ent_norm} " or f" {ent_norm} " in f" {var_norm} ":
                    score = 1.0
                else:
                    score = _similarity(ent_norm, var_norm)

                if score > best_score:
                    best_score = score
                    best_text = ent.text

        return best_score, best_text

    raw_scores = []
    MATCH_THRESHOLD = 0.88

    for rule in SWRL_RULES:
        atoms = rule.get('body_atoms', []) or []
        total = 0
        matched = 0
        score_sum = 0.0
        matched_terms = []
        missing_terms = []
        criteria_details = []

        for prop, val in atoms:
            val_norm = _norm_key(val)
            if not val_norm:
                continue

            expected_label = _label_for_rule_prop(prop)
            total += 1

            sim, ent_text = _best_entity_similarity(expected_label, prop, val)
            score_sum += sim

            is_found = sim >= MATCH_THRESHOLD
            if is_found:
                matched += 1
                matched_terms.append(str(val))
            else:
                missing_terms.append(str(val))

            criteria_details.append({
                "propriete": prop,
                "label_attendu": expected_label,
                "valeur_attendue": str(val),
                "entite_trouvee": ent_text,
                "similarite": round(sim * 100, 2),
                "trouve": bool(is_found),
            })

        score = (score_sum / total) if total else 0.0

        raw_scores.append({
            "pathologie":   rule['pathologie'],
            "couleur":      rule['couleur'],
            "couleur_bord": rule['couleur_bord'],
            "score":        round(score * 100, 2),
            "criteres_trouves": matched,
            "criteres_total": total,
            "termes_trouves": matched_terms,
            "termes_manquants": missing_terms,
            "details_criteres": criteria_details,
            # score_raw conserve uniquement pour le tri interne,
            # retire du dict expose a JsonResponse plus bas.
            "_score_raw":   score,
        })

    # V17 : score strict par REGLE OWL, puis meilleure regle par pathologie.
    # On ne regroupe plus toutes les conditions de toutes les regles d'une pathologie,
    # sinon une phrase qui correspond parfaitement a une regle DDB peut etre penalisee
    # par d'autres regles DDB non concernees par le texte.
    # Chaque regle recoit : moyenne(similarite des entites detectees avec ses conditions).
    # Pour l'affichage par pathologie, on garde la regle la plus proche.
    best_by_patho = {}
    for s in raw_scores:
        p = s['pathologie']
        old = best_by_patho.get(p)
        if old is None:
            best_by_patho[p] = s
            continue

        # Priorite au meilleur score. En cas d'egalite, garder la regle la plus specifique
        # (plus de criteres), puis celle avec le plus de criteres trouves.
        if (
            s.get('_score_raw', 0) > old.get('_score_raw', 0)
            or (
                s.get('_score_raw', 0) == old.get('_score_raw', 0)
                and s.get('criteres_total', 0) > old.get('criteres_total', 0)
            )
            or (
                s.get('_score_raw', 0) == old.get('_score_raw', 0)
                and s.get('criteres_total', 0) == old.get('criteres_total', 0)
                and s.get('criteres_trouves', 0) > old.get('criteres_trouves', 0)
            )
        ):
            best_by_patho[p] = s

    scores_final = list(best_by_patho.values())

    scores_final = sorted(scores_final, key=lambda x: x['_score_raw'], reverse=True)

    # Retirer _score_raw avant de renvoyer (non serialisable en JSON Django)
    scores_serialisables = [
        {k: v for k, v in s.items() if k != '_score_raw'}
        for s in scores_final
    ]

    return {
        "html_annote":         html_annote,
        "entites":             entites,
        "scores_regles":       scores_serialisables,
        "meilleur_diagnostic": scores_serialisables[0] if scores_serialisables else None,
        "correction":          correction,   # infos de correction renvoyées au front
    }