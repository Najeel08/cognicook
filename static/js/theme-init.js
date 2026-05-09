(function () {
    const storageKey = "cognicook-theme";
    const allowedThemes = new Set(["dark", "light"]);

    function preferredTheme() {
        try {
            const storedTheme = window.localStorage.getItem(storageKey);
            if (allowedThemes.has(storedTheme)) {
                return storedTheme;
            }
        } catch (error) {
            // Storage can be unavailable in strict/private browsing contexts.
        }

        if (window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches) {
            return "light";
        }

        return "dark";
    }

    const theme = preferredTheme();
    document.documentElement.dataset.theme = theme;
    document.documentElement.dataset.bsTheme = theme;
})();
