from owlready2 import *

# Charger l'ontologie
onto = get_ontology("file://c:/Users/Di Na/Documents/mypfe/ontologies/onto.owl").load()

# Liste des patients à supprimer
patients_to_delete = ["patient25", "patient26", "patient27"]

with onto:
    for patient_name in patients_to_delete:
        # Trouver l'individu (patient) par son nom
        patient_instance = onto.search_one(iri=f"*{patient_name}")
        
        if patient_instance:
            print(f"Suppression de l'instance : {patient_instance.name}")
            # Supprimer l'instance
            destroy_entity(patient_instance)
        else:
            print(f"Instance non trouvée : {patient_name}")

    # Sauvegarder les modifications dans l'ontologie
    onto.save(file="ontologies/onto.owl", format="rdfxml")

print("Les patients spécifiés ont été supprimés de l'ontologie.")
