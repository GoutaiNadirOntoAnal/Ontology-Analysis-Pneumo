const ralesCheckbox = document.getElementById('id_rales');
const additionalRalesOptions = document.querySelector('.additional-rales-options');
const additionalRalesDropdown = document.getElementById('id_rales_additional');
const examcliField = document.querySelector('input[name="examcli"]');
const toggleRalesCheckbox = document.getElementById('toggle-additional-rales-options');

ralesCheckbox.addEventListener('change', toggleAdditionalRalesOptions);
toggleRalesCheckbox.addEventListener('change', toggleAdditionalRalesOptions);
additionalRalesDropdown.addEventListener('change', updateRalesCheckboxValue);

ralesCheckbox.dispatchEvent(new Event('change'));

function toggleAdditionalRalesOptions() {
  additionalRalesOptions.style.display = ralesCheckbox.checked ? 'block' : 'none';
  additionalRalesDropdown.style.display = ralesCheckbox.checked ? 'block' : 'none';
  additionalRalesDropdown.required = ralesCheckbox.checked;

  if (!ralesCheckbox.checked) {
    // Réinitialiser la valeur de examcli lorsque la case à cocher est décochée
    examcliField.value = '';
  }
}

function updateRalesCheckboxValue() {
  if (ralesCheckbox.checked) {
    ralesCheckbox.value = additionalRalesDropdown.value;
    examcliField.value = additionalRalesDropdown.value;
  }
}


const dyspneeCheckbox = document.getElementById('id_dyspnee');
const additionalDyspneeOptions = document.querySelector('.additional-dyspnee-options');
const additionalDyspneeDropdown = document.getElementById('id_dyspnee_additional');
const toggleDyspneeCheckbox = document.getElementById('toggle-additional-dyspnee-options');

dyspneeCheckbox.addEventListener('change', toggleAdditionalDyspneeOptions);
toggleDyspneeCheckbox.addEventListener('change', toggleAdditionalDyspneeOptions);
additionalDyspneeDropdown.addEventListener('change', updateDyspneeCheckboxValue);

dyspneeCheckbox.dispatchEvent(new Event('change'));

function toggleAdditionalDyspneeOptions() {
  additionalDyspneeOptions.style.display = dyspneeCheckbox.checked ? 'block' : 'none';
  additionalDyspneeDropdown.style.display = dyspneeCheckbox.checked ? 'block' : 'none';
  additionalDyspneeDropdown.required = dyspneeCheckbox.checked;
  additionalDyspneeDropdown.name = dyspneeCheckbox.checked ? 'symptome' : '';
}

function updateDyspneeCheckboxValue() {
  if (dyspneeCheckbox.checked) {
    dyspneeCheckbox.value = additionalDyspneeDropdown.value;
  }
}


const touxCheckbox = document.getElementById('id_toux');
const additionalTouxOptions = document.querySelector('.additional-toux-options');
const additionalTouxDropdown = document.getElementById('id_toux_additional');
const toggleTouxCheckbox = document.getElementById('toggle-additional-toux-options');

touxCheckbox.addEventListener('change', toggleAdditionalTouxOptions);
toggleTouxCheckbox.addEventListener('change', toggleAdditionalTouxOptions);
additionalTouxDropdown.addEventListener('change', updateTouxCheckboxValue);

touxCheckbox.dispatchEvent(new Event('change'));

function toggleAdditionalTouxOptions() {
  additionalTouxOptions.style.display = touxCheckbox.checked ? 'block' : 'none';
  additionalTouxDropdown.style.display = touxCheckbox.checked ? 'block' : 'none';
  additionalTouxDropdown.required = touxCheckbox.checked;
  additionalTouxDropdown.name = touxCheckbox.checked ? 'symptome' : '';
}

function updateTouxCheckboxValue() {
  if (touxCheckbox.checked) {
    touxCheckbox.value = additionalTouxDropdown.value;
  }
}


const tabacCheckbox = document.getElementById('id_tabac');
const additionalTabacOptions = document.querySelector('.additional-tabac-options');
const additionalTabacDropdown = document.getElementById('id_tabac_additional');
const toggleTabacCheckbox = document.getElementById('toggle-additional-tabac-options');

tabacCheckbox.addEventListener('change', toggleAdditionalTabacOptions);
toggleTabacCheckbox.addEventListener('change', toggleAdditionalTabacOptions);
additionalTabacDropdown.addEventListener('change', updateTabacCheckboxValue);

tabacCheckbox.dispatchEvent(new Event('change'));

function toggleAdditionalTabacOptions() {
  additionalTabacOptions.style.display = tabacCheckbox.checked ? 'block' : 'none';
  additionalTabacDropdown.style.display = tabacCheckbox.checked ? 'block' : 'none';
  additionalTabacDropdown.required = tabacCheckbox.checked;
  additionalTabacDropdown.name = tabacCheckbox.checked ? 'habitVie' : '';
}

function updateTabacCheckboxValue() {
  if (tabacCheckbox.checked) {
    tabacCheckbox.value = additionalTabacDropdown.value;
  }
}

