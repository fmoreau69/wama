/**
 * WAMA Imager - Console JavaScript
 * Handles console log display
 */

(function() {
    'use strict';

    const config = window.IMAGER_CONFIG;
    let consoleInterval = null;

    // Initialize on page load
    document.addEventListener('DOMContentLoaded', function() {
        initializeConsole();
        startConsolePolling();
    });

    /**
     * Initialize console
     */
    function initializeConsole() {
        const clearBtn = document.getElementById('clearConsoleBtn');
        if (clearBtn) {
            clearBtn.addEventListener('click', clearConsole);
        }
    }

    /**
     * Start polling for console updates
     */
    function startConsolePolling() {
        // Initial fetch
        updateConsole();

        // Poll every 2 seconds
        consoleInterval = setInterval(updateConsole, 2000);
    }

    /**
     * Update console output
     */
    function updateConsole() {
        fetch(config.urls.consoleContent)
            .then(response => response.json())
            .then(data => {
                const consoleOutput = document.getElementById('consoleOutput');
                if (consoleOutput && data.output) {
                    if (Array.isArray(data.output)) {
                        consoleOutput.textContent = data.output.join('\n');
                    } else {
                        consoleOutput.textContent = data.output;
                    }

                    // Auto-scroll to bottom
                    consoleOutput.parentElement.scrollTop = consoleOutput.parentElement.scrollHeight;
                }
            })
            .catch(error => {
                console.error('Error updating console:', error);
            });
    }

    /**
     * Clear console output
     */
    function clearConsole() {
        const consoleOutput = document.getElementById('consoleOutput');
        if (consoleOutput) {
            consoleOutput.textContent = 'Console cleared...\n';
        }
    }

})();
