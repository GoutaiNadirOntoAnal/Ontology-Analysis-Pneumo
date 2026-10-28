const ralesCheckbox = document.getElementById('id_rales');
const additionalRalesOptions = document.querySelector('.additional-rales-options');
const additionalRalesDropdown = document.getElementById('id_rales_additional');
const toggleRalesCheckbox = document.getElementById('toggle-additional-rales-options');

ralesCheckbox.addEventListener('change', function () {
    additionalRalesOptions.style.display = this.checked ? 'block' : 'none';
    toggleRalesCheckbox.checked = this.checked;

    if (this.checked) {
        additionalRalesDropdown.style.display = 'block';
        additionalRalesDropdown.required = true;
        additionalRalesDropdown.name = 'examcli';
    } else {
        additionalRalesDropdown.style.display = 'none';
        additionalRalesDropdown.required = false;
        additionalRalesDropdown.name = '';
    }
});

toggleRalesCheckbox.addEventListener('change', function () {
    additionalRalesOptions.style.display = this.checked ? 'block' : 'none';
    ralesCheckbox.checked = this.checked;

    if (this.checked) {
        additionalRalesDropdown.style.display = 'block';
        additionalRalesDropdown.required = true;
        additionalRalesDropdown.name = 'examcli';
    } else {
        additionalRalesDropdown.style.display = 'none';
        additionalRalesDropdown.required = false;
        additionalRalesDropdown.name = '';
    }
});

additionalRalesDropdown.addEventListener('change', function () {
    if (ralesCheckbox.checked) {
        ralesCheckbox.value = additionalRalesDropdown.value;
    }
});

const tabacCheckbox = document.getElementById('id_tabac');
const additionalTabacOptions = document.querySelector('.additional-tabac-options');
const additionalTabacDropdown = document.getElementById('id_tabac_additional');
const toggleTabacCheckbox = document.getElementById('toggle-additional-tabac-options');

tabacCheckbox.addEventListener('change', function () {
    additionalTabacOptions.style.display = this.checked ? 'block' : 'none';
    toggleTabacCheckbox.checked = this.checked;

    if (this.checked) {
        additionalTabacDropdown.style.display = 'block';
        additionalTabacDropdown.required = true;
        additionalTabacDropdown.name = 'habitVie';
    } else {
        additionalTabacDropdown.style.display = 'none';
        additionalTabacDropdown.required = false;
        additionalTabacDropdown.name = '';
    }
});

toggleTabacCheckbox.addEventListener('change', function () {
    additionalTabacOptions.style.display = this.checked ? 'block' : 'none';
    tabacCheckbox.checked = this.checked;

    if (this.checked) {
        additionalTabacDropdown.style.display = 'block';
        additionalTabacDropdown.required = true;
        additionalTabacDropdown.name = 'habitVie';
    } else {
        additionalTabacDropdown.style.display = 'none';
        additionalTabacDropdown.required = false;
        additionalTabacDropdown.name = '';
    }
});

additionalTabacDropdown.addEventListener('change', function () {
    if (tabacCheckbox.checked) {
        tabacCheckbox.value = additionalTabacDropdown.value;
    }
});


const dyspneeCheckbox = document.getElementById('id_dyspnee');
const additionalDyspneeOptions = document.querySelector('.additional-dyspnee-options');
const additionalDyspneeDropdown = document.getElementById('id_dyspnee_additional');
const toggleDyspneeCheckbox = document.getElementById('toggle-additional-dyspnee-options');

dyspneeCheckbox.addEventListener('change', function () {
    additionalDyspneeOptions.style.display = this.checked ? 'block' : 'none';
    toggleDyspneeCheckbox.checked = this.checked;

    if (this.checked) {
        additionalDyspneeDropdown.style.display = 'block';
        additionalDyspneeDropdown.required = true;
        additionalDyspneeDropdown.name = 'symptome';
    } else {
        additionalDyspneeDropdown.style.display = 'none';
        additionalDyspneeDropdown.required = false;
        additionalDyspneeDropdown.name = '';
    }
});

toggleDyspneeCheckbox.addEventListener('change', function () {
    additionalDyspneeOptions.style.display = this.checked ? 'block' : 'none';
    dyspneeCheckbox.checked = this.checked;

    if (this.checked) {
        additionalDyspneeDropdown.style.display = 'block';
        additionalDyspneeDropdown.required = true;
        additionalDyspneeDropdown.name = 'symptome';
    } else {
        additionalDyspneeDropdown.style.display = 'none';
        additionalDyspneeDropdown.required = false;
        additionalDyspneeDropdown.name = '';
    }
});

additionalDyspneeDropdown.addEventListener('change', function () {
    if (dyspneeCheckbox.checked) {
        dyspneeCheckbox.value = additionalDyspneeDropdown.value;
    }
});


const touxCheckbox = document.getElementById('id_toux');
const additionalTouxOptions = document.querySelector('.additional-toux-options');
const additionalTouxDropdown = document.getElementById('id_toux_additional');
const toggleTouxCheckbox = document.getElementById('toggle-additional-toux-options');

touxCheckbox.addEventListener('change', function () {
    additionalTouxOptions.style.display = this.checked ? 'block' : 'none';
    toggleTouxCheckbox.checked = this.checked;

    if (this.checked) {
        additionalTouxDropdown.style.display = 'block';
        additionalTouxDropdown.required = true;
        additionalTouxDropdown.name = 'symptome';
    } else {
        additionalTouxDropdown.style.display = 'none';
        additionalTouxDropdown.required = false;
        additionalTouxDropdown.name = '';
    }
});

toggleTouxCheckbox.addEventListener('change', function () {
    additionalTouxOptions.style.display = this.checked ? 'block' : 'none';
    touxCheckbox.checked = this.checked;

    if (this.checked) {
        additionalTouxDropdown.style.display = 'block';
        additionalTouxDropdown.required = true;
        additionalTouxDropdown.name = 'symptome';
    } else {
        additionalTouxDropdown.style.display = 'none';
        additionalTouxDropdown.required = false;
        additionalTouxDropdown.name = '';
    }
});

additionalTouxDropdown.addEventListener('change', function () {
    if (touxCheckbox.checked) {
        touxCheckbox.value = additionalTouxDropdown.value;
    }
});
