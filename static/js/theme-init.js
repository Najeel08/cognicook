(function () {
    const storageKey = "cognicook-theme";
    const allowedThemes = new Set(["dark", "light"]);

    function storedTheme() {
        try {
            const theme = window.localStorage.getItem(storageKey);
            if (allowedThemes.has(theme)) {
                return theme;
            }
        } catch (error) {
            // Storage can be unavailable in strict/private browsing contexts.
        }

        return "";
    }

    function colorSchemeQuery() {
        if (!window.matchMedia) {
            return null;
        }

        try {
            return window.matchMedia("(prefers-color-scheme: light)");
        } catch (error) {
            return null;
        }
    }

    function systemTheme() {
        const query = colorSchemeQuery();
        return query && query.matches ? "light" : "dark";
    }

    function preferredTheme() {
        return storedTheme() || systemTheme();
    }

    function applyTheme(theme) {
        if (!allowedThemes.has(theme)) {
            return;
        }

        document.documentElement.dataset.theme = theme;
        document.documentElement.dataset.bsTheme = theme;
    }

    applyTheme(preferredTheme());

    const query = colorSchemeQuery();
    const handleColorSchemeChange = function (event) {
        if (storedTheme()) {
            return;
        }

        applyTheme(event.matches ? "light" : "dark");
    };

    if (query && query.addEventListener) {
        query.addEventListener("change", handleColorSchemeChange);
    } else if (query && query.addListener) {
        query.addListener(handleColorSchemeChange);
    }
})();
