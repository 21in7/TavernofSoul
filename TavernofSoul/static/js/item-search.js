(function () {
    'use strict';
    // Preserve native GET navigation unless all required capabilities exist.
    if (!window.fetch || !window.AbortController || !window.URL ||
        !window.URLSearchParams || !window.FormData || !window.DOMParser ||
        !window.history.pushState || !window.history.replaceState ||
        !window.Promise || !Array.from || !Element.prototype.closest ||
        !Element.prototype.replaceWith) return;

    var form = document.getElementById('item-search-form');
    var results = document.getElementById('item-search-results');
    var status = document.getElementById('item-search-status');
    var error = document.getElementById('item-search-error');
    if (!form || !results || !status || !error) return;
    var path = new URL(form.action, location.href).pathname;
    var displayedURL = new URL(location.href);
    var displayedValues = new URLSearchParams(new FormData(form));
    var sequence = 0;
    var pending = null;
    var retry = null;
    var keys = ['q', 'grade', 'class', 'type', 'lvmin', 'lvmax', 'order'];

    function searchURL(value) {
        var url = new URL(value, location.href);
        if (url.origin !== location.origin || url.pathname !== path ||
            url.username || url.password || url.hash) throw new Error('Invalid search URL');
        return url;
    }

    function syncForm(url) {
        keys.forEach(function (key) {
            form.elements.namedItem(key).value = url.searchParams.get(key) ||
                (key === 'order' ? 'updated-dsc' : '');
        });
    }

    function parseResults(markup) {
        // DOMParser tolerates full documents, so reject them before parsing.
        if (/<\s*\/?\s*(?:html|head|body|script|base|iframe|object|embed|template)\b|<!doctype/i.test(markup)) {
            throw new Error('Unexpected document');
        }
        var doc = new DOMParser().parseFromString(markup, 'text/html');
        if (doc.head.children.length || doc.body.children.length !== 1) throw new Error('Unexpected fragment');
        var root = doc.body.firstElementChild;
        if (root.id !== 'item-search-results' ||
            root.getAttribute('data-item-search-fragment') !== 'results-v1' ||
            root.querySelectorAll('#item-search-summary').length !== 1 ||
            !root.hasAttribute('data-search-url')) throw new Error('Invalid fragment');
        var tags = ['SECTION', 'H2', 'P', 'A', 'DIV', 'TABLE', 'CAPTION', 'THEAD',
            'TR', 'TH', 'SPAN', 'TBODY', 'TD', 'IMG', 'NAV', 'UL', 'LI'];
        var attrs = ['id', 'class', 'role', 'tabindex', 'scope', 'rel', 'loading', 'alt',
            'aria-label', 'aria-labelledby', 'aria-describedby', 'aria-hidden',
            'aria-busy', 'aria-current', 'data-item-search-fragment', 'data-search-url',
            'data-search-pagination', 'data-search-reset', 'href', 'src'];
        [root].concat(Array.from(root.querySelectorAll('*'))).forEach(function (node) {
            if (node.namespaceURI !== 'http://www.w3.org/1999/xhtml' ||
                tags.indexOf(node.tagName) === -1) throw new Error('Unexpected element');
            Array.from(node.attributes).forEach(function (attr) {
                if (attrs.indexOf(attr.name) === -1) throw new Error('Unexpected attribute');
                if (attr.name === 'href' || attr.name === 'src') {
                    var url = new URL(attr.value, location.href);
                    var itemLink = url.pathname.indexOf(path) === 0 &&
                        /^[A-Za-z0-9_-]+$/.test(url.pathname.slice(path.length));
                    if (url.origin !== location.origin || url.username || url.password ||
                        (attr.name === 'href' && !(url.pathname === path || itemLink)) ||
                        (attr.name === 'src' && !(url.pathname.indexOf('/static/icons/') === 0 &&
                            /\.png$/.test(url.pathname)))) {
                        throw new Error('Unexpected resource URL');
                    }
                }
            });
        });
        searchURL(root.getAttribute('data-search-url'));
        return document.importNode(root, true);
    }

    async function navigate(url, mode) {
        var id = ++sequence;
        if (pending) pending.abort();
        var controller = new AbortController();
        pending = controller;
        var timedOut = false;
        var timer = window.setTimeout(function () {
            timedOut = true;
            controller.abort();
        }, 12000);
        var focused = document.activeElement;
        var focusResults = mode === 'page' || mode === 'pop' ||
            (focused && (results.contains(focused) || error.contains(focused)));
        results.setAttribute('aria-busy', 'true');
        status.textContent = 'Loading search results…';
        error.hidden = true;
        retry = null;
        try {
            var response = await fetch(url.href, {
                method: 'GET', credentials: 'same-origin', signal: controller.signal,
                headers: {'X-Item-Search': 'results-v1', 'Accept': 'text/html'}
            });
            if (!response.ok || response.redirected ||
                response.headers.get('X-Item-Search') !== 'results-v1' ||
                !/^text\/html(?:\s*;|$)/i.test(response.headers.get('Content-Type') || '')) {
                throw new Error('Invalid search response');
            }
            searchURL(response.url);
            var markup = await response.text();
            if (id !== sequence) return;
            if (timedOut || controller.signal.aborted) throw new Error('Search timed out');
            var replacement = parseResults(markup);
            var canonical = searchURL(replacement.getAttribute('data-search-url'));
            // Commit history before replacing the corresponding results.
            if (mode !== 'pop' && canonical.href !== displayedURL.href) {
                history.pushState(null, '', canonical.href);
            } else {
                history.replaceState(null, '', canonical.href);
            }
            results.replaceWith(replacement);
            results = replacement;
            displayedURL = canonical;
            syncForm(canonical);
            displayedValues = new URLSearchParams(new FormData(form));
            status.textContent = results.querySelector('#item-search-summary').textContent;
            // Hiding Retry or replacing results can return focus to the body.
            // Preserve focus if the user moved to another control while waiting.
            var active = document.activeElement;
            if (focusResults && (!active || active === document.body || active === focused)) {
                results.querySelector('#item-search-summary').focus();
            }
        } catch (failure) {
            if (id !== sequence) return;
            // Also covers a failed submit which superseded an in-flight popstate.
            if (location.href !== displayedURL.href) {
                history.replaceState(null, '', displayedURL.href);
            }
            if (mode === 'pop') {
                keys.forEach(function (key) {
                    form.elements.namedItem(key).value = displayedValues.get(key) || '';
                });
            }
            retry = {url: url, mode: mode === 'pop' ? 'page' : mode};
            document.getElementById('item-search-fallback').href = url.href;
            error.hidden = false;
            status.textContent = 'Search failed. Previous results are still shown. Retry or open the search page.';
            if (focusResults) document.getElementById('item-search-retry').focus();
        } finally {
            window.clearTimeout(timer);
            if (id === sequence) {
                pending = null;
                results.setAttribute('aria-busy', 'false');
            }
        }
    }

    form.addEventListener('submit', function (event) {
        if (event.defaultPrevented || form.method.toLowerCase() !== 'get' ||
            (form.target && form.target !== '_self')) return;
        var url;
        try {
            url = searchURL(form.action);
            url.search = new URLSearchParams(new FormData(form)).toString();
            url.searchParams.delete('page');
        } catch (failure) { return; }
        event.preventDefault();
        navigate(url, 'submit');
    });

    document.querySelector('.item-search').addEventListener('click', function (event) {
        if (event.defaultPrevented || event.button !== 0 ||
            event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        var link = event.target.closest('a');
        if (!link || link.hasAttribute('download') || (link.target && link.target !== '_self') ||
            !(link.hasAttribute('data-search-reset') || link.closest('[data-search-pagination]'))) return;
        var url;
        try { url = searchURL(link.href); } catch (failure) { return; }
        event.preventDefault();
        navigate(url, link.hasAttribute('data-search-reset') ? 'reset' : 'page');
    });

    document.getElementById('item-search-retry').addEventListener('click', function () {
        if (retry) navigate(retry.url, retry.mode);
    });
    window.addEventListener('popstate', function () {
        var url;
        try { url = searchURL(location.href); } catch (failure) {
            location.reload();
            return;
        }
        navigate(url, 'pop');
    });
})();
