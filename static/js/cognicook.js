const historyReloadKey = `cognicook-history-reload:${window.location.pathname}${window.location.search}`;

window.addEventListener("pageshow", (event) => {
    const navigationEntry = performance.getEntriesByType("navigation")[0];
    const restoredFromHistory = event.persisted || navigationEntry?.type === "back_forward";

    if (!restoredFromHistory) {
        try {
            window.sessionStorage.removeItem(historyReloadKey);
        } catch (error) {
            // Session storage can be unavailable in strict/private browsing contexts.
        }
        return;
    }

    try {
        if (window.sessionStorage.getItem(historyReloadKey) === "1") {
            window.sessionStorage.removeItem(historyReloadKey);
            return;
        }
        window.sessionStorage.setItem(historyReloadKey, "1");
    } catch (error) {
        return;
    }

    window.location.reload();
});

document.addEventListener("DOMContentLoaded", () => {
    const buttons = document.querySelectorAll(".btn-neon-primary, .btn-neon-secondary, .btn-danger-soft");

    buttons.forEach((button) => {
        button.classList.add("ready");
    });

    initializeThemeToggle();
    initializeRegisterValidation();
});

function initializeThemeToggle() {
    const toggle = document.querySelector("#theme-toggle");
    if (!toggle) {
        return;
    }

    const storageKey = "cognicook-theme";
    const allowedThemes = new Set(["dark", "light"]);
    const root = document.documentElement;

    function currentTheme() {
        return allowedThemes.has(root.dataset.theme) ? root.dataset.theme : "dark";
    }

    function persistTheme(theme) {
        try {
            window.localStorage.setItem(storageKey, theme);
        } catch (error) {
            // Storage can be unavailable in strict/private browsing contexts.
        }
    }

    function updateToggleState(theme) {
        const isLight = theme === "light";
        toggle.setAttribute("aria-pressed", String(isLight));
        toggle.setAttribute("aria-label", isLight ? "Switch to dark mode" : "Switch to light mode");
        toggle.title = isLight ? "Switch to dark mode" : "Switch to light mode";
    }

    function applyTheme(theme, shouldPersist = true) {
        if (!allowedThemes.has(theme)) {
            return;
        }

        root.dataset.theme = theme;
        root.dataset.bsTheme = theme;
        updateToggleState(theme);

        if (shouldPersist) {
            persistTheme(theme);
        }
    }

    toggle.addEventListener("click", () => {
        applyTheme(currentTheme() === "light" ? "dark" : "light");
    });

    updateToggleState(currentTheme());

    const colorSchemeQuery = window.matchMedia("(prefers-color-scheme: light)");
    const handleColorSchemeChange = (event) => {
        let hasStoredTheme = false;
        try {
            hasStoredTheme = allowedThemes.has(window.localStorage.getItem(storageKey));
        } catch (error) {
            hasStoredTheme = false;
        }

        if (hasStoredTheme) {
            return;
        }

        applyTheme(event.matches ? "light" : "dark", false);
    };

    if (colorSchemeQuery.addEventListener) {
        colorSchemeQuery.addEventListener("change", handleColorSchemeChange);
    } else if (colorSchemeQuery.addListener) {
        colorSchemeQuery.addListener(handleColorSchemeChange);
    }
}

function initializeRegisterValidation() {
    const registerForm = document.querySelector("#register-form");
    const validationBox = document.querySelector("#register-validation");
    if (!registerForm || !validationBox) {
        return;
    }

    const usernameInput = registerForm.querySelector("#username");
    const emailInput = registerForm.querySelector("#email");
    const passwordInput = registerForm.querySelector("#password");
    const confirmPasswordInput = registerForm.querySelector("#confirm_password");
    const commonWeakPasswords = new Set([
        "12345678",
        "123456789",
        "1234567890",
        "password",
        "password1",
        "password123",
        "admin123",
        "qwerty123",
        "welcome123",
        "letmein123",
        "abc12345",
        "cognicook",
        "cognicook123",
    ]);
    const keyboardPatterns = [
        "qwer",
        "asdf",
        "zxcv",
    ];
    const sequentialSources = ["0123456789", "abcdefghijklmnopqrstuvwxyz"];

    function hasSequentialRun(value, runLength = 4) {
        const lowered = value.toLowerCase();
        if (keyboardPatterns.some((pattern) => lowered.includes(pattern))) {
            return true;
        }

        return sequentialSources.some((source) => {
            for (let index = 0; index <= source.length - runLength; index += 1) {
                const sequence = source.slice(index, index + runLength);
                const reversed = sequence.split("").reverse().join("");
                if (lowered.includes(sequence) || lowered.includes(reversed)) {
                    return true;
                }
            }
            return false;
        });
    }

    function isValidEmail(email) {
        const value = email.trim();
        const localPart = value.split("@", 1)[0];
        const emailPattern = /^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$/;
        return (
            value.length <= 254
            && !value.includes("..")
            && !localPart.startsWith(".")
            && !localPart.endsWith(".")
            && emailPattern.test(value)
        );
    }

    function validateRegisterForm() {
        const errors = [];
        const username = (usernameInput?.value || "").trim();
        const email = (emailInput?.value || "").trim();
        const password = passwordInput?.value || "";
        const confirmPassword = confirmPasswordInput?.value || "";
        const loweredPassword = password.toLowerCase();

        if (!/^[A-Za-z0-9_.-]{3,30}$/.test(username)) {
            errors.push("Username must be 3 to 30 characters and may contain letters, numbers, dots, hyphens, or underscores.");
        }
        if (!isValidEmail(email)) {
            errors.push("Please enter a valid email address.");
        }
        if (password.length < 8) {
            errors.push("Password must be at least 8 characters long.");
        }
        if (!/[A-Z]/.test(password)) {
            errors.push("Password must include at least one uppercase letter.");
        }
        if (!/[a-z]/.test(password)) {
            errors.push("Password must include at least one lowercase letter.");
        }
        if (!/\d/.test(password)) {
            errors.push("Password must include at least one number.");
        }
        if (/(.)\1{3,}/i.test(password)) {
            errors.push("Password cannot contain simple repeated sequences like 1111 or aaaa.");
        }
        if (hasSequentialRun(loweredPassword)) {
            errors.push("Password cannot contain obvious sequential patterns like 1234 or abcd.");
        }
        if (commonWeakPasswords.has(loweredPassword)) {
            errors.push("Password is too common. Please choose a stronger password.");
        }
        if (password !== confirmPassword) {
            errors.push("Password confirmation does not match.");
        }

        if (errors.length) {
            validationBox.replaceChildren();
            const list = document.createElement("ul");
            errors.forEach((error) => {
                const item = document.createElement("li");
                item.textContent = error;
                list.appendChild(item);
            });
            validationBox.appendChild(list);
            validationBox.classList.remove("d-none");
        } else {
            validationBox.replaceChildren();
            validationBox.classList.add("d-none");
        }

        return errors;
    }

    registerForm.addEventListener("submit", (event) => {
        if (validateRegisterForm().length) {
            event.preventDefault();
        }
    });

    [usernameInput, emailInput, passwordInput, confirmPasswordInput].forEach((input) => {
        input?.addEventListener("input", validateRegisterForm);
    });
}
