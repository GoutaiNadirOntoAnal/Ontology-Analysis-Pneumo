import os
import django

# Configure Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mypfe.settings')
django.setup()

from hopital.models import Patient

PATIENT_ID_TO_DELETE = 16

try:
    # Get the patient by ID
    patient = Patient.objects.get(id=PATIENT_ID_TO_DELETE)
    
    # Delete the patient
    patient.delete()
    
    print(f"Patient with ID {PATIENT_ID_TO_DELETE} has been successfully deleted from the database.")

except Patient.DoesNotExist:
    print(f"Patient with ID {PATIENT_ID_TO_DELETE} not found in the database.")
except Exception as e:
    print(f"An error occurred: {e}")
