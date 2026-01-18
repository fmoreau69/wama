/**
 * WAMA System Stats Monitor
 * Fetches and displays server resource usage in the footer.
 */

(function() {
    'use strict';

    const STATS_URL = '/common/api/system-stats/';
    const UPDATE_INTERVAL = 5000; // 5 seconds

    // DOM elements (cached after first fetch)
    let elements = null;

    function getElements() {
        if (!elements) {
            elements = {
                cpuBar: document.getElementById('cpuBar'),
                cpuText: document.getElementById('cpuText'),
                ramBar: document.getElementById('ramBar'),
                ramText: document.getElementById('ramText'),
                gpuStats: document.getElementById('gpuStats'),
                gpuBar: document.getElementById('gpuBar'),
                gpuText: document.getElementById('gpuText'),
                diskText: document.getElementById('diskText')
            };
        }
        return elements;
    }

    function getBarColor(percent) {
        if (percent >= 90) return 'bg-danger';
        if (percent >= 70) return 'bg-warning';
        return null; // Use default color
    }

    function updateBar(bar, percent, defaultClass) {
        if (!bar) return;
        bar.style.width = percent + '%';

        // Update color based on usage level
        bar.className = 'progress-bar';
        const colorClass = getBarColor(percent);
        bar.classList.add(colorClass || defaultClass);
    }

    function updateStats(stats) {
        const el = getElements();

        // CPU
        if (stats.cpu && el.cpuBar && el.cpuText) {
            const cpuPercent = Math.round(stats.cpu.percent);
            updateBar(el.cpuBar, cpuPercent, 'bg-info');
            el.cpuText.textContent = cpuPercent + '%';
            el.cpuBar.parentElement.parentElement.title = `CPU: ${cpuPercent}% (${stats.cpu.count} cores)`;
        }

        // RAM
        if (stats.ram && el.ramBar && el.ramText) {
            const ramPercent = Math.round(stats.ram.percent);
            updateBar(el.ramBar, ramPercent, 'bg-success');
            el.ramText.textContent = ramPercent + '%';
            el.ramBar.parentElement.parentElement.title = `RAM: ${stats.ram.used_gb}/${stats.ram.total_gb} GB (${ramPercent}%)`;
        }

        // GPU
        if (stats.gpu && stats.gpu.length > 0 && el.gpuStats) {
            const gpu = stats.gpu[0]; // First GPU
            const gpuPercent = gpu.utilization;
            el.gpuStats.style.display = 'flex';

            if (el.gpuBar && el.gpuText) {
                updateBar(el.gpuBar, gpuPercent, 'bg-warning');
                el.gpuText.textContent = gpuPercent + '%';

                const memPercent = Math.round((gpu.memory_used / gpu.memory_total) * 100);
                el.gpuStats.title = `${gpu.name}\nUtilisation: ${gpuPercent}%\nVRAM: ${gpu.memory_used}/${gpu.memory_total} MB (${memPercent}%)\nTemp: ${gpu.temperature}°C`;
            }
        }

        // Disk
        if (stats.disk && el.diskText) {
            el.diskText.textContent = stats.disk.percent + '%';
            el.diskText.parentElement.title = `Disque: ${stats.disk.used_gb}/${stats.disk.total_gb} GB`;
        }
    }

    async function fetchStats() {
        try {
            const response = await fetch(STATS_URL);
            if (response.ok) {
                const stats = await response.json();
                updateStats(stats);
            }
        } catch (error) {
            // Silently fail - don't spam console with errors
        }
    }

    function init() {
        // Only run if the footer stats container exists
        if (!document.getElementById('systemStats')) {
            return;
        }

        // Initial fetch
        fetchStats();

        // Periodic updates
        setInterval(fetchStats, UPDATE_INTERVAL);
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
