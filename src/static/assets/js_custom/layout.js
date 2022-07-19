const loginUrl = document.currentScript.getAttribute('data-login-url');
const logoutUrl = document.currentScript.getAttribute('data-logout-url');

$(document).ready(function() {
    $('#btn-login').click(function() {
        window.location.href = loginUrl;
    });

    $('#btn-logout').click(function() {
        window.location.href = logoutUrl;
    });

    // enable tooltips
    $(function() {
        $('[data-toggle="tooltip"]').tooltip();
    });
});
