from django import forms
from django.contrib.auth.models import User, Group
from .models import *


class MedecinForm(forms.ModelForm):
    username = forms.CharField(label='Nom d\'utilisateur')
    password = forms.CharField(
        label='Mot de passe', widget=forms.PasswordInput)

    class Meta:
        model = Medecin
        fields = ['nom', 'prenom', 'specialite',
                  'adresse', 'numero_telephone', 'adresse_email']

    def save(self, commit=True):
        user = User.objects.create_user(
            username=self.cleaned_data['username'],
            password=self.cleaned_data['password']
        )
        medecin = super().save(commit=False)
        medecin.user = user
        if commit:
            medecin.save()
        group = Group.objects.get(name='Medecin')
        user.groups.add(group)
        return medecin


class PatientForm(forms.ModelForm):
    username = forms.CharField(label="Nom d'utilisateur")
    password = forms.CharField(
        label="Mot de passe", widget=forms.PasswordInput)

    class Meta:
        model = Patient
        fields = ['nom', 'prenom', 'adresse', 'date_naissance',
                  'numero_telephone', 'adresse_email', 'medecin_traitant', 'sexe']

    def save(self, commit=True):
        user = User.objects.create_user(
            username=self.cleaned_data['username'],
            password=self.cleaned_data['password']
        )
        patient = super().save(commit=False)
        patient.user = user
        if commit:
            patient.save()
        group = Group.objects.get(name='Patient')
        user.groups.add(group)
        return patient


class PatientUpdForm(forms.ModelForm):

    class Meta:
        model = Patient
        fields = ['nom', 'prenom', 'adresse', 'date_naissance',
                  'numero_telephone', 'adresse_email', 'medecin_traitant', 'sexe']


class MedecinUpdForm(forms.ModelForm):

    class Meta:
        model = Medecin
        fields = ['nom', 'prenom', 'specialite',
                  'adresse', 'numero_telephone', 'adresse_email']


class DossierForm(forms.ModelForm):

    class Meta:
        model = Dossier
        fields = ['patient', 'antFam', 'antPers', 'atopie', 'efr', 'examcli',
                  'habitVie', 'poids', 'radio', 'signe', 'symptome', 'taille', 'tdm']


class DiagnosticForm(forms.ModelForm):
    class Meta:
        model = Diagnostic
        fields = ['patient', 'diagnostic_text']

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super(DiagnosticForm, self).__init__(*args, **kwargs)
        if user and hasattr(user, 'medecin'):
            self.fields['patient'].queryset = Patient.objects.filter(medecin_traitant=user.medecin)

