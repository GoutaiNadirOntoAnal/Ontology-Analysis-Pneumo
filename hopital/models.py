from django.contrib.auth.models import User
from django.db import models


class Medecin(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    nom = models.CharField(max_length=100)
    prenom = models.CharField(max_length=100)
    specialite = models.CharField(max_length=100)
    adresse = models.CharField(max_length=200)
    numero_telephone = models.IntegerField()
    adresse_email = models.EmailField()

    def __str__(self):
        return f"{self.nom} {self.prenom}"


class Patient(models.Model):
    SEXE_CHOICES = [
        ('M', 'Homme'),
        ('F', 'Femme'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    medecin_traitant = models.ForeignKey(
        Medecin, on_delete=models.SET_NULL, null=True, blank=True)
    nom = models.CharField(max_length=100)
    prenom = models.CharField(max_length=100)
    adresse = models.CharField(max_length=200)
    date_naissance = models.DateField()
    numero_telephone = models.IntegerField()
    adresse_email = models.EmailField()
    sexe = models.CharField(max_length=1, choices=SEXE_CHOICES,  default='M')

    def __str__(self):
        return f"{self.nom} {self.prenom}"


class Dossier(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
    date_creation = models.DateField(auto_now_add=True)
    antFam = models.TextField(blank=True)
    antPers = models.TextField(blank=True)
    atopie = models.TextField(blank=True)
    efr = models.TextField(blank=True)
    examcli = models.TextField(blank=True)
    habitVie = models.TextField(blank=True)
    poids = models.IntegerField()
    radio = models.CharField(max_length=1000, blank=True)
    signe = models.CharField(max_length=1000, blank=True)
    symptome = models.CharField(max_length=1000, blank=True)
    taille = models.FloatField()
    tdm = models.CharField(max_length=1000, blank=True)


class Diagnostic(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
    medecin = models.ForeignKey(Medecin, on_delete=models.CASCADE)
    diagnostic_text = models.TextField()
    date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Diagnostic for {self.patient} on {self.date}"
