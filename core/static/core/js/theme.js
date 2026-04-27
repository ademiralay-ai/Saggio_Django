const STORAGE_KEY = 'saggio-theme';
const MOBILE_WIDTH = 900;

function getPreferredTheme() {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === 'light' || saved === 'dark') {
        return saved;
    }

    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);

    const icon = document.querySelector('#theme-toggle i, #theme-toggle-btn i');
    if (icon) {
        icon.classList.remove('fa-moon', 'fa-sun');
        icon.classList.add(theme === 'dark' ? 'fa-moon' : 'fa-sun');
    }

    document.dispatchEvent(new CustomEvent('theme-changed', { detail: { theme } }));
}

function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme') || 'light';
    const next = current === 'light' ? 'dark' : 'light';
    localStorage.setItem(STORAGE_KEY, next);
    applyTheme(next);
}

function setupSidebarToggle() {
    const button = document.getElementById('sidebar-toggle');
    const overlay = document.getElementById('sidebar-overlay');
    if (!button || !overlay) {
        return;
    }

    function isMobile() {
        return window.innerWidth <= MOBILE_WIDTH;
    }

    // Restore collapsed state on desktop
    if (!isMobile() && localStorage.getItem('saggio-sidebar') === 'collapsed') {
        document.body.classList.add('sidebar-collapsed');
    }

    function setButtonState() {
        const expanded = isMobile()
            ? document.body.classList.contains('sidebar-open')
            : !document.body.classList.contains('sidebar-collapsed');
        button.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    }

    function closeMobileMenu() {
        document.body.classList.remove('sidebar-open');
        setButtonState();
    }

    button.addEventListener('click', () => {
        if (isMobile()) {
            document.body.classList.toggle('sidebar-open');
        } else {
            const isNowCollapsed = document.body.classList.toggle('sidebar-collapsed');
            localStorage.setItem('saggio-sidebar', isNowCollapsed ? 'collapsed' : 'expanded');
        }
        setButtonState();
    });

    overlay.addEventListener('click', closeMobileMenu);

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && isMobile()) {
            closeMobileMenu();
        }
    });

    window.addEventListener('resize', () => {
        if (!isMobile()) {
            document.body.classList.remove('sidebar-open');
        }
        setButtonState();
    });

    setButtonState();
}

function _setupThemeAndSidebar() {
    applyTheme(getPreferredTheme());

    const button = document.getElementById('theme-toggle') || document.getElementById('theme-toggle-btn');
    if (button) {
        button.addEventListener('click', () => {
            toggleTheme();
            if (typeof window.showToast === 'function') {
                const active = document.documentElement.getAttribute('data-theme') || 'light';
                window.showToast(active === 'dark' ? 'Koyu tema aktif' : 'Acik tema aktif', 'info');
            }
        });
    }

    setupSidebarToggle();
}

// Sayfa altında yüklendiğinde DOM zaten hazır olabilir; readyState kontrolü ile
// hem erken hem geç yükleme senaryolarını kapsa.
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _setupThemeAndSidebar);
} else {
    _setupThemeAndSidebar();
}
