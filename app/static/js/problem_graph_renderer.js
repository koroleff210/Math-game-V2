(function () {
    const MAX_RENDER_ATTEMPTS = 8;

    function queueFrame(callback) {
        if (window.requestAnimationFrame) {
            window.requestAnimationFrame(callback);
            return;
        }
        setTimeout(callback, 16);
    }

    function graphCanvasHasSize(canvas) {
        if (!canvas) return false;
        const rect = canvas.getBoundingClientRect();
        return rect.width > 24 && rect.height > 24;
    }

    function scheduleGraphResize(canvas) {
        if (!window.Plotly || !canvas) return;
        const resize = function () {
            if (!graphCanvasHasSize(canvas)) return;
            Promise.resolve(window.Plotly.Plots.resize(canvas)).catch(function () {
                // Ignore resize race conditions while the mobile layout is still settling.
            });
        };
        queueFrame(function () {
            resize();
            queueFrame(resize);
        });
    }

    function renderGraphBlock(root, attempt) {
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

        const renderAttempt = Number(attempt) || 0;
        if (!graphCanvasHasSize(canvas)) {
            if (renderAttempt >= MAX_RENDER_ATTEMPTS) {
                return;
            }
            queueFrame(function () {
                renderGraphBlock(root, renderAttempt + 1);
            });
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

        const plotMethod = canvas.classList.contains('js-plotly-plot') ? 'react' : 'newPlot';
        Promise.resolve(window.Plotly[plotMethod](canvas, payload.data || [], layout, config)).then(function () {
            scheduleGraphResize(canvas);
        }).catch(function () {
            if (plotMethod !== 'newPlot') {
                Promise.resolve(window.Plotly.newPlot(canvas, payload.data || [], layout, config)).then(function () {
                    scheduleGraphResize(canvas);
                });
            }
        });
    }

    window.resizeProblemGraphs = function (scope) {
        if (!window.Plotly) return;
        const root = scope || document;
        root.querySelectorAll('.problem-graph-canvas').forEach(function (canvas) {
            scheduleGraphResize(canvas);
        });
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

    window.addEventListener('resize', function () {
        if (window.resizeProblemGraphs) {
            window.resizeProblemGraphs(document);
        }
    });

    if (window.visualViewport && window.visualViewport.addEventListener) {
        window.visualViewport.addEventListener('resize', function () {
            if (window.resizeProblemGraphs) {
                window.resizeProblemGraphs(document);
            }
        });
    }
}());
