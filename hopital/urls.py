from django.urls import path
from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path('login/', views.loginPage, name="login"),
    path('logout/', views.logoutUser, name="logout"),

    path('medecin/create/', views.create_medecin, name='create_medecin'),
    path('medecin/medecin<int:id>/modifier/', views.modifier_medecin, name='modifier_medecin'),
    path('medecin/medecin<int:id>/supprimer/', views.supprimer_medecin, name='supprimer_medecin'),
    path('medecins/', views.medecin_list, name='medecin_list'),

    path('patient/create/', views.create_patient, name='create_patient'),
    path('patient/patient<int:id>/modifier/', views.modifier_patient, name='modifier_patient'),
    path('patient/patient<int:id>/supprimer/', views.supprimer_patient, name='supprimer_patient'),
    path('patients/', views.patient_list, name='patient_list'),
    path('patient/patient<int:id>/', views.patient_detail, name='patient_detail'),
    path('patient/patient<int:id>/ajout_dossier', views.ajout_dossier, name='ajout_dossier'),
    path('patient/patient<int:id>/modifier_dossier', views.modifier_dossier, name='modifier_dossier'),

    # Diagnostic connecté
    path('diagnostic/', views.diagnostic_view, name='diagnostic_view'),
    path('analyser/', views.analyser_api, name='analyser_api'),

    # Démo publique : sans connexion, sans patient, sans enregistrement
    path('demo-diagnostic/', views.demo_diagnostic_view, name='demo_diagnostic'),
    path('demo-diagnostic/analyser/', views.demo_analyser_api, name='demo_analyser_api'),

    # Règles d’ontologie
    path('regles/', views.ontology_rules, name='regle_list'),  # alias ancien menu
    path('admin-ontologie/regles/', views.ontology_rules, name='ontology_rules'),
    path('ontology/rules/', views.ontology_rules, name='ontology_rules_public_alias'),
    path('admin-ontologie/regles/<str:rule_name>/modifier/', views.ontology_rule_edit, name='ontology_rule_edit'),
    path('ontology/rules/<str:rule_name>/edit/', views.ontology_rule_edit, name='ontology_rule_edit_alias'),
    path('admin-ontologie/regles/<str:rule_name>/supprimer/', views.ontology_rule_delete, name='ontology_rule_delete'),
    path('ontology/rules/<str:rule_name>/delete/', views.ontology_rule_delete, name='ontology_rule_delete_alias'),
]
