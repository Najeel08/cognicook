document.addEventListener("DOMContentLoaded", () => {
    const buttons = document.querySelectorAll(".btn-neon-primary, .btn-neon-secondary, .btn-danger-soft");

    buttons.forEach((button) => {
        button.classList.add("ready");
    });

    initializeThemeToggle();
    initializePasswordToggles();
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
    let themeSwitchTimeout = 0;

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

    function markThemeSwitching() {
        root.classList.add("theme-switching");
        window.clearTimeout(themeSwitchTimeout);
        themeSwitchTimeout = window.setTimeout(() => {
            root.classList.remove("theme-switching");
        }, 280);
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

        if (currentTheme() !== theme) {
            markThemeSwitching();
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

function initializePasswordToggles() {
    document.querySelectorAll("[data-password-toggle]").forEach((button) => {
        const inputId = button.getAttribute("aria-controls");
        const input = inputId ? document.getElementById(inputId) : null;
        if (!input) {
            return;
        }

        button.addEventListener("click", () => {
            const shouldShow = input.type === "password";
            input.type = shouldShow ? "text" : "password";
            button.setAttribute("aria-pressed", String(shouldShow));
            button.setAttribute("aria-label", shouldShow ? "Hide password" : "Show password");
        });
    });
}

function initializeRegisterValidation() {
    const registerForm = document.querySelector("#register-form");
    if (!registerForm) {
        return;
    }

    const fields = {
        username: registerForm.querySelector("#username"),
        email: registerForm.querySelector("#email"),
        password: registerForm.querySelector("#password"),
        confirm_password: registerForm.querySelector("#confirm_password"),
    };
    const feedback = {
        username: registerForm.querySelector('[data-validation-for="username"]'),
        email: registerForm.querySelector('[data-validation-for="email"]'),
        password: registerForm.querySelector('[data-validation-for="password"]'),
        confirm_password: registerForm.querySelector('[data-validation-for="confirm_password"]'),
    };
    const touched = new Set();
    let submitted = false;

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
    const keyboardPatterns = ["qwer", "asdf", "zxcv"];
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
        const domainParts = value.split("@");
        const domain = domainParts[domainParts.length - 1].toLowerCase();
        const knownDomainTypos = new Set(["gmail.co"]);
        const emailPattern = /^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$/;
        return (
            value.length <= 254
            && !value.includes("..")
            && !localPart.startsWith(".")
            && !localPart.endsWith(".")
            && !knownDomainTypos.has(domain)
            && emailPattern.test(value)
        );
    }

    function messagesFor(fieldName) {
        const username = (fields.username?.value || "").trim();
        const email = (fields.email?.value || "").trim();
        const password = fields.password?.value || "";
        const confirmPassword = fields.confirm_password?.value || "";
        const loweredPassword = password.toLowerCase();

        if (fieldName === "username") {
            if (!username) {
                return ["Username is required."];
            }
            if (!/^[A-Za-z0-9_.-]{3,30}$/.test(username)) {
                return ["Use 3 to 30 letters, numbers, dots, hyphens, or underscores."];
            }
            return [];
        }

        if (fieldName === "email") {
            if (!email) {
                return ["Email address is required."];
            }
            return isValidEmail(email) ? [] : ["Enter a valid email address."];
        }

        if (fieldName === "password") {
            const messages = [];
            if (password.length < 8) {
                messages.push("Minimum 8 characters.");
            }
            if (!/[A-Z]/.test(password)) {
                messages.push("Uppercase required.");
            }
            if (!/[a-z]/.test(password)) {
                messages.push("Lowercase required.");
            }
            if (!/\d/.test(password)) {
                messages.push("One number required.");
            }
            if (/(.)\1{3,}/i.test(password)) {
                messages.push("Avoid repeated sequences like 1111 or aaaa.");
            }
            if (hasSequentialRun(loweredPassword)) {
                messages.push("Avoid obvious sequences like 1234 or abcd.");
            }
            if (commonWeakPasswords.has(loweredPassword)) {
                messages.push("Choose a less common password.");
            }
            if (password.length > 256) {
                messages.push("Password is too long.");
            }
            return messages;
        }

        if (fieldName === "confirm_password") {
            if (!confirmPassword) {
                return ["Confirm your password."];
            }
            return password === confirmPassword ? [] : ["Passwords do not match."];
        }

        return [];
    }

    function renderFeedback(fieldName, messages) {
        const input = fields[fieldName];
        const box = feedback[fieldName];
        if (!input || !box) {
            return;
        }

        box.replaceChildren();
        input.setAttribute("aria-invalid", String(messages.length > 0));

        if (!messages.length || (!submitted && !touched.has(fieldName))) {
            box.classList.remove("is-visible");
            input.removeAttribute("aria-invalid");
            return;
        }

        const list = document.createElement("ul");
        messages.forEach((message) => {
            const item = document.createElement("li");
            item.textContent = message;
            list.appendChild(item);
        });
        box.appendChild(list);
        box.classList.add("is-visible");
    }

    function validateField(fieldName) {
        const messages = messagesFor(fieldName);
        renderFeedback(fieldName, messages);
        return messages;
    }

    function validateForm() {
        return Object.keys(fields).flatMap((fieldName) => validateField(fieldName));
    }

    Object.entries(fields).forEach(([fieldName, input]) => {
        input?.addEventListener("input", () => {
            touched.add(fieldName);
            validateField(fieldName);

            if (fieldName === "password" && (touched.has("confirm_password") || submitted)) {
                validateField("confirm_password");
            }
        });

        input?.addEventListener("blur", () => {
            touched.add(fieldName);
            validateField(fieldName);
        });
    });

    registerForm.addEventListener("submit", (event) => {
        submitted = true;
        Object.keys(fields).forEach((fieldName) => touched.add(fieldName));
        if (validateForm().length) {
            event.preventDefault();
        }
    });
}