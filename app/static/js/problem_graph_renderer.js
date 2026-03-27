(function () {
    function renderGraphBlock(root) {
        if (!window.Plotly) {
            root.innerHTML = '<div class="problem-body-unsupported">Plotly failed to load.</div>';
            return;
        }

        const payloadNode = root.querySelector('.problem-graph-payload');
        const canvas = root.querySelector('.problem-graph-canvas');
        if (!payloadNode || !canvas) return;

        let payload = null;
        try {
            payload = JSON.parse(payloadNode.textContent);
        } catch (err) {
            canvas.innerHTML = '<div class="problem-body-unsupported">Invalid graph payload.</div>';
            return;
        }

        const layout = Object.assign(
            {
                autosize: true,
                height: 320,
            },
            payload.layout || {}
        );
        const config = Object.assign(
            {
                responsive: true,
                scrollZoom: true,
                displaylogo: false,
            },
            payload.config || {}
        );

        window.Plotly.newPlot(canvas, payload.data || [], layout, config);
    }

    window.renderProblemGraphs = function (scope) {
        const root = scope || document;
        root.querySelectorAll('[data-problem-graph-block]').forEach(renderGraphBlock);
    };

    document.addEventListener('DOMContentLoaded', function () {
        if (window.renderProblemGraphs) {
            window.renderProblemGraphs(document);
        }
    });
}());
