function getCssVar(name, fallback) {
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return value || fallback;
}

let robotsChartInstance = null;
let processChartInstance = null;

function createRobotsChart() {
    const canvas = document.getElementById('robotsChart');
    if (!canvas || typeof Chart === 'undefined') {
        return;
    }

    const text = getCssVar('--text', '#1b2331');
    const line = getCssVar('--line', 'rgba(27, 35, 49, 0.14)');

    if (robotsChartInstance) {
        robotsChartInstance.destroy();
    }

    robotsChartInstance = new Chart(canvas, {
        type: 'doughnut',
        data: {
            labels: ['Online', 'Offline', 'Bakim'],
            datasets: [
                {
                    data: [18, 4, 2],
                    backgroundColor: ['#2e8a57', '#b94a48', '#d18d2d'],
                    borderColor: line,
                    borderWidth: 1,
                    hoverOffset: 6,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            resizeDelay: 120,
            plugins: {
                legend: {
                    labels: {
                        color: text,
                    },
                },
            },
        },
    });
}

function createProcessChart() {
    const canvas = document.getElementById('processChart');
    if (!canvas || typeof Chart === 'undefined') {
        return;
    }

    const text = getCssVar('--text', '#1b2331');
    const line = getCssVar('--line', 'rgba(27, 35, 49, 0.14)');
    const accent = getCssVar('--accent', '#1f7a6b');

    if (processChartInstance) {
        processChartInstance.destroy();
    }

    processChartInstance = new Chart(canvas, {
        type: 'bar',
        data: {
            labels: ['Pzt', 'Sal', 'Car', 'Per', 'Cum', 'Cmt', 'Paz'],
            datasets: [
                {
                    label: 'Tamamlanan Surec',
                    data: [42, 50, 39, 62, 58, 36, 28],
                    borderRadius: 8,
                    backgroundColor: accent,
                },
                {
                    label: 'Bekleyen Surec',
                    data: [11, 9, 14, 8, 10, 12, 7],
                    borderRadius: 8,
                    backgroundColor: 'rgba(47, 140, 167, 0.72)',
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            resizeDelay: 120,
            scales: {
                x: {
                    ticks: { color: text },
                    grid: { color: line },
                },
                y: {
                    ticks: { color: text },
                    grid: { color: line },
                },
            },
            plugins: {
                legend: {
                    labels: { color: text },
                },
            },
        },
    });
}

document.addEventListener('DOMContentLoaded', () => {
    createRobotsChart();
    createProcessChart();
});

document.addEventListener('theme-changed', () => {
    createRobotsChart();
    createProcessChart();
});
