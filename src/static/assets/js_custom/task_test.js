function runTask(csrfToken, action, workTime, yieldAfter, clear) {
    const name = Math.random().toString(36).slice(2, 7);
    const resDiv = $('#result');
    if (clear) {
        resDiv.html('');
    }
    resDiv.html(`${resDiv.html()}<br/>requesting task: ${name}...`);
    const start = Date.now();
    const params = {csrf_token: csrfToken, name, action, work_time: workTime, yield_after: yieldAfter};
    $.post('/task_test_action', params, function(data, textStatus) {
        const elapsed = Date.now() - start;
        console.log(data);
        console.log(textStatus);
        resDiv.html(`${resDiv.html()}<br/>request done: ${name} (elapsed ${elapsed}ms)`);
    });
}

function confirm(csrfToken, action, workTime, yieldAfter) {
    bootbox.confirm({
        message: `Are you sure you want to run the test with action of '${action}', work time of '${workTime}' and yield after '${yieldAfter}'?`,
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
                runTask(csrfToken, action, workTime, yieldAfter, true);
                runTask(csrfToken, action, workTime, yieldAfter, false);
            }
        }
    });
}

$(document).ready(function() {
    $('#form-submit').click(function() {
        const csrfToken = $('#csrfToken').val();
        const action = $('#action').val();
        const workTime = $('#workTime').val();
        const yieldAfter = $('#yieldAfter').val();
        confirm(csrfToken, action, workTime, yieldAfter);
        return false;
    });
});
