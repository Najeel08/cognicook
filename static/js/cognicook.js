window.addEventListener("pageshow", (event) => {
    const navigationEntry = performance.getEntriesByType("navigation")[0];
    const restoredFromHistory = event.persisted || navigationEntry?.type === "back_forward";

    if (restoredFromHistory) {
        window.location.reload();
    }
});

document.addEventListener("DOMContentLoaded", () => {
    const buttons = document.querySelectorAll(".btn-neon-primary, .btn-neon-secondary, .btn-danger-soft");

    buttons.forEach((button, index) => {
        button.style.animationDelay = `${index * 40}ms`;
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
        try {
            if (window.localStorage.getItem(storageKey)) {
                return;
            }
        } catch (error) {
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
    const sequentialPatterns = [
        "0123",
        "1234",
        "2345",
        "3456",
        "4567",
        "5678",
        "6789",
        "7890",
        "abcd",
        "bcde",
        "cdef",
        "defg",
        "qwer",
        "asdf",
        "zxcv",
    ];

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
        if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
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
        if (sequentialPatterns.some((pattern) => loweredPassword.includes(pattern))) {
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
