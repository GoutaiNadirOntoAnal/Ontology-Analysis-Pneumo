from owlready2 import *
import os
print(os.getcwd())

# Chargez l'ontologie

onto = get_ontology("ontologies/onto.owl").load()
id="habib1"
iri = f"http://www.semanticweb.org/domo/ontologies/2023/4/OntoPneumo#{id}"
# with onto:
#     instance = onto.Medecin(iri=iri)
#     print(instance)
#     onto.save(file="C:/Users/Domo/Desktop/mypfe/ontologies/onto.owl", format="rdfxml")

print(onto)
# from rdflib import Graph
#
# g = Graph()
# print(g.parse("ontologies/onto.owl", format="xml"))
