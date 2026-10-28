
# ──────────────────────────────────────────────────────────────
# ADMIN — RÈGLES DE L'ONTOLOGIE : LISTE + AJOUT + MODIF + SUPPRESSION
# À COLLER dans hopital/views.py en remplaçant ton ancien bloc ontology_rules
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

def _condition_label(prop_name):
    return dict(_ONTOLOGY_CONDITION_CHOICES).get(prop_name, prop_name)

def _safe_rule_name(name):
    return re.sub(r'[^A-Za-z0-9_]+', '_', str(name or '')).strip('_')

def _get_rule_by_name(rule_name):
    for rule in list(onto.rules()):
        if getattr(rule, 'name', '') == rule_name:
            return rule
    return None

def _parse_rule_text_for_admin(rule_text):
    """
    Extrait pathologie + conditions depuis le texte SWRL.
    Exemple : symptome(?d, "Dyspnée"), efr(?d, "TVO réversible") -> aPathologie(?p, Asthme)
    """
    text = str(rule_text or '')
    left = text.split('->')[0] if '->' in text else text
    right = text.split('->')[-1] if '->' in text else text

    conditions = []
    atom_pattern = re.compile(
        r'([A-Za-zÀ-ÖØ-öø-ÿ_][\wÀ-ÖØ-öø-ÿ]*)\s*\(\s*\?\w+\s*,\s*(?:"([^"]+)"|\'([^\']+)\'|([^,\)]+))\s*\)'
    )

    for m in atom_pattern.finditer(left):
        prop = m.group(1).strip()
        value = (m.group(2) or m.group(3) or m.group(4) or '').strip()
        if not prop or prop in {'aPathologie', 'aDossier'}:
            continue
        conditions.append({
            'prop': prop,
            'label': _condition_label(prop),
            'value': value,
        })

    pathologie = ''
    p1 = re.search(r'aPathologie\s*\(\s*\?\w+\s*,\s*([^)]+)\)', right)
    if p1:
        pathologie = p1.group(1).replace('"', '').replace("'", '').strip()

    return pathologie, conditions

def _rule_to_admin_dict(rule):
    name = getattr(rule, 'name', '')
    text = str(rule)
    pathologie, conditions = _parse_rule_text_for_admin(text)
    return {
        'name': name,
        'text': text,
        'pathologie': pathologie,
        'conditions': conditions,
    }

def _load_existing_ontology_rules():
    """Retourne toutes les règles SWRL présentes dans onto.owl avec nom + conditions."""
    try:
        rules = [_rule_to_admin_dict(r) for r in list(onto.rules())]
        rules.sort(key=lambda r: r.get('name', ''))
        return rules
    except Exception as e:
        print(f"[ONTOLOGY ADMIN] Lecture des règles impossible : {e}")
        return []

def _find_or_create_pathologie_individual(pathologie_name):
    safe_name = _safe_rule_name(pathologie_name) or 'PathologieAdmin'
    found = onto.search_one(iri=f"*#{safe_name}")
    if found is not None:
        return found

    with onto:
        # Si ta classe Pathologie existe, on l'utilise. Sinon Thing.
        if hasattr(onto, 'Pathologie'):
            obj = onto.Pathologie(safe_name)
        else:
            obj = Thing(safe_name)
        obj.label = [pathologie_name]
    return obj

def _build_swrl_rule_text(pathologie_id, conditions):
    body_atoms = []
    for prop_name, value in conditions:
        clean_value = str(value).replace('"', '\\"').strip()
        body_atoms.append(f'{prop_name}(?d, "{clean_value}")')
    return ', '.join(body_atoms) + f' -> aPathologie(?p, {pathologie_id})'

def _collect_rule_form_data(request):
    pathologie = request.POST.get('pathologie', '').strip()
    props = request.POST.getlist('condition_property')
    values = request.POST.getlist('condition_value')

    valid_props = {value for value, _ in _ONTOLOGY_CONDITION_CHOICES}
    conditions = []
    for prop_name, value in zip(props, values):
        prop_name = (prop_name or '').strip()
        value = (value or '').strip()
        if prop_name in valid_props and value:
            conditions.append((prop_name, value))

    return pathologie, conditions

@login_required
@superuser_required
def ontology_rules(request):
    """
    Page admin :
    - affiche toutes les règles de l’ontologie ;
    - ajoute une nouvelle règle ;
    - liens vers modifier/supprimer.
    """
    if request.method == 'POST':
        pathologie, conditions = _collect_rule_form_data(request)

        if not pathologie:
            messages.error(request, "Veuillez saisir la pathologie à suggérer.")
        elif not conditions:
            messages.error(request, "Veuillez ajouter au moins un critère clinique pour la règle.")
        else:
            try:
                timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
                base_name = slugify(pathologie, allow_unicode=False).replace('-', '_') or 'pathologie'
                rule_name = f"regle_admin_{base_name}_{timestamp}"

                with onto:
                    pathologie_obj = _find_or_create_pathologie_individual(pathologie)
                    rule_text = _build_swrl_rule_text(pathologie_obj.name, conditions)
                    new_rule = Imp(rule_name)
                    new_rule.set_as_rule(rule_text)
                    new_rule.label = [rule_name]
                    new_rule.comment = [f"{pathologie} : règle ajoutée depuis l’interface administrateur"]
                    onto.save(file="ontologies/onto.owl", format="rdfxml")

                reload_ontology_rules(force=True)
                messages.success(request, "La règle a été ajoutée dans l’ontologie avec succès.")
                return redirect('ontology_rules')
            except Exception as e:
                traceback.print_exc()
                messages.error(request, f"Impossible d’ajouter la règle : {e}")

    return render(request, 'hopital/ontology_rules.html', {
        'condition_choices': _ONTOLOGY_CONDITION_CHOICES,
        'existing_rules': _load_existing_ontology_rules(),
    })

@login_required
@superuser_required
def ontology_rule_edit(request, rule_name):
    rule = _get_rule_by_name(rule_name)
    if rule is None:
        messages.error(request, "Règle introuvable dans l’ontologie.")
        return redirect('ontology_rules')

    if request.method == 'POST':
        pathologie, conditions = _collect_rule_form_data(request)

        if not pathologie:
            messages.error(request, "Veuillez saisir la pathologie à suggérer.")
        elif not conditions:
            messages.error(request, "Veuillez ajouter au moins un critère clinique.")
        else:
            try:
                with onto:
                    old_rule = _get_rule_by_name(rule_name)
                    if old_rule is not None:
                        destroy_entity(old_rule)

                    pathologie_obj = _find_or_create_pathologie_individual(pathologie)
                    rule_text = _build_swrl_rule_text(pathologie_obj.name, conditions)

                    new_rule = Imp(rule_name)
                    new_rule.set_as_rule(rule_text)
                    new_rule.label = [rule_name]
                    new_rule.comment = [f"{pathologie} : règle modifiée depuis l’interface administrateur"]
                    onto.save(file="ontologies/onto.owl", format="rdfxml")

                reload_ontology_rules(force=True)
                messages.success(request, "La règle a été modifiée avec succès.")
                return redirect('ontology_rules')
            except Exception as e:
                traceback.print_exc()
                messages.error(request, f"Impossible de modifier la règle : {e}")

    return render(request, 'hopital/ontology_rule_edit.html', {
        'condition_choices': _ONTOLOGY_CONDITION_CHOICES,
        'rule': _rule_to_admin_dict(rule),
    })

@login_required
@superuser_required
@require_POST
def ontology_rule_delete(request, rule_name):
    rule = _get_rule_by_name(rule_name)
    if rule is None:
        messages.error(request, "Règle introuvable dans l’ontologie.")
        return redirect('ontology_rules')

    try:
        with onto:
            destroy_entity(rule)
            onto.save(file="ontologies/onto.owl", format="rdfxml")

        reload_ontology_rules(force=True)
        messages.success(request, "La règle a été supprimée de l’ontologie.")
    except Exception as e:
        traceback.print_exc()
        messages.error(request, f"Impossible de supprimer la règle : {e}")

    return redirect('ontology_rules')
