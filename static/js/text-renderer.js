(function (window) {
    'use strict';

    const TOKEN_PATTERN = /\[([^\]\r\n]+)\]\(\s*([^)]+?)\s*\)|([^\r\n()[\]]+?)\(\$['’]\s*([^'’]+?)\s*['’]\$\)|(https?:\/\/[^\s<>"']+|www\.[^\s<>"']+)/gi;
    const TRAILING_PUNCTUATION = '.,;:!?，。；：！？、)]}';

    function normalizeUrl(url) {
        let value = String(url || '').trim();
        if (!value) return null;

        if (/^www\./i.test(value)) {
            value = `https://${value}`;
        }

        if (/^(\/(?!\/)|#)/.test(value)) {
            return value;
        }

        try {
            const parsed = new URL(value, window.location.origin);
            if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
                return parsed.href;
            }
        } catch (error) {
            return null;
        }

        return null;
    }

    function splitUrlPunctuation(url) {
        let cleanUrl = String(url || '').trim();
        let suffix = '';

        while (cleanUrl && TRAILING_PUNCTUATION.includes(cleanUrl.slice(-1))) {
            suffix = cleanUrl.slice(-1) + suffix;
            cleanUrl = cleanUrl.slice(0, -1);
        }

        return { cleanUrl, suffix };
    }

    function appendPlainText(target, text) {
        const lines = String(text || '').split(/\r?\n/);
        lines.forEach((line, index) => {
            if (index > 0) target.appendChild(document.createElement('br'));
            if (line) target.appendChild(document.createTextNode(line));
        });
    }

    function appendLink(target, label, rawUrl) {
        const href = normalizeUrl(rawUrl);
        const text = String(label || '').trim();

        if (!href || !text) {
            return false;
        }

        const link = document.createElement('a');
        link.href = href;
        link.className = 'cms-content-link';
        link.textContent = text;

        try {
            const parsed = new URL(href, window.location.origin);
            if (parsed.origin !== window.location.origin) {
                link.target = '_blank';
                link.rel = 'noopener noreferrer';
            }
        } catch (error) {
            link.target = '_blank';
            link.rel = 'noopener noreferrer';
        }

        target.appendChild(link);
        return true;
    }

    function appendLegacyLink(target, labelChunk, rawUrl) {
        const chunk = String(labelChunk || '');
        const leading = chunk.match(/^\s*/)[0];
        const trailing = chunk.match(/\s*$/)[0];
        let core = chunk.slice(leading.length, chunk.length - trailing.length);

        const split = core.match(/^(.*\s)(\S.*)$/);
        if (split) {
            appendPlainText(target, leading + split[1]);
            core = split[2];
        } else if (leading) {
            appendPlainText(target, leading);
        }

        appendLink(target, core, rawUrl);

        if (trailing) {
            appendPlainText(target, trailing);
        }
    }

    function append(target, text) {
        if (!target) return;

        const source = String(text || '');
        TOKEN_PATTERN.lastIndex = 0;

        let lastIndex = 0;
        let match;

        while ((match = TOKEN_PATTERN.exec(source)) !== null) {
            appendPlainText(target, source.slice(lastIndex, match.index));

            if (match[1] && match[2]) {
                if (!normalizeUrl(match[2])) {
                    appendPlainText(target, match[0]);
                } else {
                    appendLink(target, match[1], match[2]);
                }
            } else if (match[3] && match[4]) {
                if (!normalizeUrl(match[4])) {
                    appendPlainText(target, match[0]);
                } else {
                    appendLegacyLink(target, match[3], match[4]);
                }
            } else if (match[5]) {
                const { cleanUrl, suffix } = splitUrlPunctuation(match[5]);
                appendLink(target, cleanUrl, cleanUrl);
                appendPlainText(target, suffix);
            }

            lastIndex = TOKEN_PATTERN.lastIndex;
        }

        appendPlainText(target, source.slice(lastIndex));
    }

    function render(target, text) {
        if (!target) return;
        target.replaceChildren();
        append(target, text);
    }

    function toPlainText(text, maxLength) {
        let value = String(text || '')
            .replace(/\[([^\]\r\n]+)\]\(\s*([^)]+?)\s*\)/g, '$1')
            .replace(/([^\r\n()[\]]+?)\(\$['’]\s*([^'’]+?)\s*['’]\$\)/g, function (_, label) {
                return String(label || '').trim();
            })
            .replace(/\s+/g, ' ')
            .trim();

        const limit = Number(maxLength) || 0;
        if (limit > 3 && value.length > limit) {
            value = `${value.slice(0, limit - 3)}...`;
        }

        return value;
    }

    window.ContentTextRenderer = {
        append,
        render,
        toPlainText
    };
})(window);
