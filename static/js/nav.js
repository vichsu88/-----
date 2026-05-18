(function () {
    'use strict';

    document.addEventListener('DOMContentLoaded', function () {
        const menuBtn = document.querySelector('.nav-toggle');
        const closeBtn = document.getElementById('overlay-close-btn');
        const overlay = document.getElementById('mobile-nav-overlay');
        const navLinks = document.querySelectorAll('.overlay-nav-links a');

        if (!overlay) return;

        const toggleMenu = function (show) {
            overlay.classList.toggle('is-visible', show);
            overlay.classList.toggle('is-open', show);
            document.body.classList.toggle('menu-open', show);
            if (menuBtn) menuBtn.setAttribute('aria-expanded', show ? 'true' : 'false');
        };

        if (menuBtn) {
            menuBtn.addEventListener('click', function (event) {
                event.stopPropagation();
                toggleMenu(true);
            });
        }

        if (closeBtn) {
            closeBtn.addEventListener('click', function (event) {
                event.stopPropagation();
                toggleMenu(false);
            });
        }

        navLinks.forEach(function (link) {
            link.addEventListener('click', function () {
                toggleMenu(false);
            });
        });
    });
})();
