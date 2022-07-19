const interstitial = JSON.parse(document.currentScript.getAttribute('data-interstitial'));
const completed = JSON.parse(document.currentScript.getAttribute('data-completed'));
const cancelled = JSON.parse(document.currentScript.getAttribute('data-cancelled'));
const windcaveUrl = document.currentScript.getAttribute('data-windcave-url');

$(document).ready(function() {
    if (!interstitial) {
        if (!completed && !cancelled) {
            if (windcaveUrl !== null && windcaveUrl !== '') {
                window.location.replace(windcaveUrl);
            }
        }
    }
});
