function confirmClose(form, peerId) {
    bootbox.confirm({
        title: 'Confirm Close Peer',
        message: `Do you want to close the peer ${peerId}?`,
        buttons: {
            confirm: {
                label: 'Yes',
                className: 'btn-success'
            },
            cancel: {
                label: 'No',
                className: 'btn-danger'
            }
        },
        callback: function(result) {
            if (result) {
                form.submit();
            }
        }
    });
}

function confirmPeerConnect(formclass, peerId) {
    bootbox.confirm({
        title: 'Connecting to peer',
        message: `Confirm the connection to ${peerId}`,
        buttons: {
            confirm: {
                label: 'Yes',
                className: 'btn-success'
            },
            cancel: {
                label: 'No',
                className: 'btn-danger'
            }
        },
        callback: function(result) {
            if (result) {
                $(formclass).submit();
            }
        }
    });
}

$(document).ready(function() {
    $('.close-peer-submit').click(function() {
        const peerId = $(this).prev().val();
        const form = $(this).parent();
        confirmClose(form, peerId);
        return false;
    });

    $('#peer-connect-submit').click(function() {
        const peerId = $('#peerId').val();
        confirmPeerConnect('#peer-connect-form', peerId);
        return false;
    });
});
