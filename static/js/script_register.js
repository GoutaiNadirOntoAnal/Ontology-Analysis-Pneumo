
var roleSelect = document.getElementById('role');
var medecinFields = document.getElementById('medecin-fields');
var patientFields = document.getElementById('patient-fields');

roleSelect.addEventListener('change', function () {
  if (roleSelect.value === 'medecin') {
    medecinFields.style.display = 'block';
    patientFields.style.display = 'none';
  } else if (roleSelect.value === 'patient') {
    medecinFields.style.display = 'none';
    patientFields.style.display = 'block';
  }
});
