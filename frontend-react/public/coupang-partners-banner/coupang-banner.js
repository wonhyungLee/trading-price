(function () {
  const DEFAULT_ENDPOINT = '/api/coupang-banner';
  const DEFAULT_INTEREST_ENDPOINT = '/api/ad-interest';
  const DEFAULT_EMPTY_MESSAGE = '추천 상품을 불러오지 못했습니다.';

  const CTA_FALLBACK = '바로 보기';

  const getEl = (value) => {
    if (!value) return null;
    if (value instanceof HTMLElement) return value;
    if (typeof value === 'string') return document.querySelector(value);
    return null;
  };

  const updateSubtitle = (subtitleEl, meta, defaultText) => {
    const el = getEl(subtitleEl);
    if (!el) return;
    const tagline = meta?.tagline || (meta?.title ? `이번주 테마 · ${meta.title}` : '');
    el.textContent = tagline || defaultText || el.textContent || '';
  };

  const render = (containerEl, items, meta, options = {}) => {
    const container = getEl(containerEl);
    if (!container) return;

    container.innerHTML = '';
    updateSubtitle(options.subtitle, meta, options.defaultSubtitle);

    if (!items || !items.length) {
      container.innerHTML = `<div class="cpb-empty">${options.emptyMessage || DEFAULT_EMPTY_MESSAGE}</div>`;
      return;
    }

    items.forEach((item) => {
      const card = document.createElement('a');
      card.className = 'cpb-card';
      card.href = item.link;
      card.target = '_blank';
      card.rel = 'noopener noreferrer';

      const img = document.createElement('img');
      img.src = item.image;
      img.alt = item.title;
      card.appendChild(img);

      const info = document.createElement('div');
      info.className = 'cpb-info';

      const tags = document.createElement('div');
      tags.className = 'cpb-tags';
      const badgeLabel = item.badge || meta.title;
      if (badgeLabel) {
        const badge = document.createElement('span');
        badge.className = 'cpb-badge';
        badge.textContent = badgeLabel;
        tags.appendChild(badge);
      }
      if (item.discountRate) {
        const discount = document.createElement('span');
        discount.className = 'cpb-pill';
        discount.textContent = `${item.discountRate}%↓`;
        tags.appendChild(discount);
      }
      if (item.shippingTag) {
        const ship = document.createElement('span');
        ship.className = 'cpb-pill cpb-pill--soft';
        ship.textContent = item.shippingTag;
        tags.appendChild(ship);
      }
      if (tags.children.length) {
        info.appendChild(tags);
      }

      const title = document.createElement('div');
      title.className = 'cpb-title';
      title.textContent = item.title;
      info.appendChild(title);

      if (item.price) {
        const price = document.createElement('div');
        price.className = 'cpb-price';
        price.textContent = item.price;
        info.appendChild(price);
      }

      if (item.meta) {
        const metaEl = document.createElement('div');
        metaEl.className = 'cpb-meta';
        metaEl.textContent = item.meta;
        info.appendChild(metaEl);
      }

      const cta = document.createElement('div');
      cta.className = 'cpb-cta';
      cta.textContent = item.cta || meta.cta || CTA_FALLBACK;
      info.appendChild(cta);

      card.appendChild(info);
      container.appendChild(card);
    });
  };

  const load = async (options = {}) => {
    const container = getEl(options.container);
    if (!container) return;

    const endpoint = options.endpoint || DEFAULT_ENDPOINT;
    try {
      const response = await fetch(endpoint);
      if (!response.ok) throw new Error('invalid response');
      const payload = await response.json();
      render(container, payload.items || [], payload.theme || {}, options);
    } catch (error) {
      render(container, [], {}, options);
    }
  };

  const recordInterest = async (category, options = {}) => {
    const normalized = typeof category === 'string' ? category.trim() : '';
    if (!normalized) return;

    const storageKey = options.storageKey || 'cp_interest_sent';
    let sent = [];
    try {
      sent = JSON.parse(sessionStorage.getItem(storageKey) || '[]');
    } catch (error) {
      sent = [];
    }
    if (sent.includes(normalized)) return;

    try {
      await fetch(options.endpoint || DEFAULT_INTEREST_ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ category: normalized }),
      });
      sent.push(normalized);
      sessionStorage.setItem(storageKey, JSON.stringify(sent));
    } catch (error) {
      // Ignore.
    }
  };

  window.CoupangPartnersBanner = {
    load,
    render,
    recordInterest,
  };
})();
