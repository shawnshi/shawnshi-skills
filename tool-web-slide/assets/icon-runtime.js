/*
 * Small, dependency-free icon runtime for offline decks.
 * It implements the subset of Lucide's createIcons() API used by this skill.
 */
(function installLocalIconRuntime(global) {
  if (global.lucide?.createIcons) return;

  const N = {
    activity: [['path',{d:'M22 12h-4l-3 9L9 3l-3 9H2'}]],
    'arrow-left': [['path',{d:'m12 19-7-7 7-7'}],['path',{d:'M19 12H5'}]],
    'arrow-right': [['path',{d:'M5 12h14'}],['path',{d:'m12 5 7 7-7 7'}]],
    'bar-chart-3': [['path',{d:'M3 3v18h18'}],['path',{d:'M18 17V9'}],['path',{d:'M13 17V5'}],['path',{d:'M8 17v-3'}]],
    brain: [['path',{d:'M9.5 4A2.5 2.5 0 0 0 7 6.5v.4A3 3 0 0 0 5 12v.5A3.5 3.5 0 0 0 8.5 16H9v1.5a2.5 2.5 0 0 0 5 0V16h.5a3.5 3.5 0 0 0 3.5-3.5V12a3 3 0 0 0-2-5.1v-.4A2.5 2.5 0 0 0 13.5 4 2.5 2.5 0 0 0 12 4.5 2.5 2.5 0 0 0 9.5 4Z'}],['path',{d:'M12 4.5V19'}],['path',{d:'M8 9h2'}],['path',{d:'M14 13h2'}]],
    calendar: [['rect',{x:'3',y:'4',width:'18',height:'17',rx:'2'}],['path',{d:'M16 2v4M8 2v4M3 10h18'}]],
    check: [['path',{d:'m20 6-11 11-5-5'}]],
    'check-circle': [['circle',{cx:'12',cy:'12',r:'10'}],['path',{d:'m8 12 3 3 5-6'}]],
    'chevron-left': [['path',{d:'m15 18-6-6 6-6'}]],
    'chevron-right': [['path',{d:'m9 18 6-6-6-6'}]],
    circle: [['circle',{cx:'12',cy:'12',r:'10'}]],
    'circle-alert': [['circle',{cx:'12',cy:'12',r:'10'}],['path',{d:'M12 8v4'}],['path',{d:'M12 16h.01'}]],
    clock: [['circle',{cx:'12',cy:'12',r:'10'}],['path',{d:'M12 6v6l4 2'}]],
    database: [['ellipse',{cx:'12',cy:'5',rx:'8',ry:'3'}],['path',{d:'M4 5v7c0 1.7 3.6 3 8 3s8-1.3 8-3V5'}],['path',{d:'M4 12v7c0 1.7 3.6 3 8 3s8-1.3 8-3v-7'}]],
    'file-text': [['path',{d:'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z'}],['path',{d:'M14 2v6h6M8 13h8M8 17h8'}]],
    fullscreen: [['path',{d:'M8 3H5a2 2 0 0 0-2 2v3M16 3h3a2 2 0 0 1 2 2v3M8 21H5a2 2 0 0 1-2-2v-3M16 21h3a2 2 0 0 0 2-2v-3'}]],
    heart: [['path',{d:'M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8l1.1 1.1L12 21l7.8-7.5 1.1-1.1a5.5 5.5 0 0 0-.1-7.8Z'}]],
    'heart-pulse': [['path',{d:'M19 14c1.5-1.5 3-3.2 3-5.5A5.5 5.5 0 0 0 12 5.3 5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4 3 5.5l7 7Z'}],['path',{d:'M3.2 12H7l1.5-3 3 6 1.5-3h7.8'}]],
    hospital: [['path',{d:'M12 7v4M10 9h4'}],['path',{d:'M3 21h18M5 21V4a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v17M9 21v-4h6v4'}]],
    info: [['circle',{cx:'12',cy:'12',r:'10'}],['path',{d:'M12 16v-4M12 8h.01'}]],
    layers: [['path',{d:'m12 2 9 5-9 5-9-5 9-5Z'}],['path',{d:'m3 12 9 5 9-5M3 17l9 5 9-5'}]],
    lightbulb: [['path',{d:'M9 18h6M10 22h4'}],['path',{d:'M8.5 14.5A6 6 0 1 1 15.5 14.5c-.9.7-1.5 1.6-1.5 2.5h-4c0-.9-.6-1.8-1.5-2.5Z'}]],
    lock: [['rect',{x:'3',y:'11',width:'18',height:'11',rx:'2'}],['path',{d:'M7 11V7a5 5 0 0 1 10 0v4'}]],
    menu: [['path',{d:'M4 6h16M4 12h16M4 18h16'}]],
    monitor: [['rect',{x:'2',y:'3',width:'20',height:'14',rx:'2'}],['path',{d:'M8 21h8M12 17v4'}]],
    network: [['rect',{x:'16',y:'16',width:'6',height:'6',rx:'1'}],['rect',{x:'2',y:'16',width:'6',height:'6',rx:'1'}],['rect',{x:'9',y:'2',width:'6',height:'6',rx:'1'}],['path',{d:'M5 16v-3h14v3M12 8v5'}]],
    plus: [['path',{d:'M12 5v14M5 12h14'}]],
    search: [['circle',{cx:'11',cy:'11',r:'8'}],['path',{d:'m21 21-4.3-4.3'}]],
    server: [['rect',{x:'2',y:'2',width:'20',height:'8',rx:'2'}],['rect',{x:'2',y:'14',width:'20',height:'8',rx:'2'}],['path',{d:'M6 6h.01M6 18h.01'}]],
    'shield-check': [['path',{d:'M20 13c0 5-3.5 7.5-8 9-4.5-1.5-8-4-8-9V5l8-3 8 3Z'}],['path',{d:'m9 12 2 2 4-4'}]],
    sparkles: [['path',{d:'m12 3-1.5 4.5L6 9l4.5 1.5L12 15l1.5-4.5L18 9l-4.5-1.5L12 3Z'}],['path',{d:'m5 3-.6 1.4L3 5l1.4.6L5 7l.6-1.4L7 5l-1.4-.6L5 3ZM19 17l-.9 2.1L16 20l2.1.9L19 23l.9-2.1L22 20l-2.1-.9L19 17Z'}]],
    stethoscope: [['path',{d:'M6 2v6a4 4 0 0 0 8 0V2M4 2h4M12 2h4'}],['path',{d:'M10 14a5 5 0 0 0 10 0v-1'}],['circle',{cx:'20',cy:'10',r:'2'}]],
    target: [['circle',{cx:'12',cy:'12',r:'10'}],['circle',{cx:'12',cy:'12',r:'6'}],['circle',{cx:'12',cy:'12',r:'2'}]],
    'triangle-alert': [['path',{d:'m21.7 18-8-14a2 2 0 0 0-3.4 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.7-3Z'}],['path',{d:'M12 9v4M12 17h.01'}]],
    user: [['circle',{cx:'12',cy:'8',r:'4'}],['path',{d:'M4 22a8 8 0 0 1 16 0'}]],
    users: [['path',{d:'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2'}],['circle',{cx:'9',cy:'7',r:'4'}],['path',{d:'M22 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8'}]],
    workflow: [['rect',{x:'3',y:'3',width:'6',height:'6',rx:'1'}],['rect',{x:'15',y:'15',width:'6',height:'6',rx:'1'}],['path',{d:'M9 6h6a3 3 0 0 1 3 3v6M15 18H9a3 3 0 0 1-3-3V9'}]],
    x: [['path',{d:'M18 6 6 18M6 6l12 12'}]],
    zap: [['path',{d:'M13 2 3 14h9l-1 8 10-12h-9l1-8Z'}]]
  };

  const fallback = [['circle',{cx:'12',cy:'12',r:'9'}],['path',{d:'M8 12h8M12 8v8'}]];
  const ns = 'http://www.w3.org/2000/svg';

  function createIcons(options = {}) {
    const root = options.root || document;
    root.querySelectorAll('[data-lucide]').forEach(node => {
      if (node.dataset.lucideRendered === 'true') return;
      const name = (node.getAttribute('data-lucide') || '').trim().toLowerCase();
      const svg = document.createElementNS(ns, 'svg');
      for (const attr of node.attributes) {
        if (!['data-lucide','data-lucide-rendered'].includes(attr.name)) svg.setAttribute(attr.name, attr.value);
      }
      Object.entries(options.attrs || {}).forEach(([key,value]) => svg.setAttribute(key, value));
      svg.setAttribute('data-lucide', name);
      svg.dataset.lucideRendered = 'true';
      svg.setAttribute('viewBox', '0 0 24 24');
      svg.setAttribute('fill', 'none');
      svg.setAttribute('stroke', svg.getAttribute('stroke') || 'currentColor');
      svg.setAttribute('stroke-width', svg.getAttribute('stroke-width') || '2');
      svg.setAttribute('stroke-linecap', 'round');
      svg.setAttribute('stroke-linejoin', 'round');
      svg.classList.add('lucide', `lucide-${name || 'fallback'}`);
      if (!node.hasAttribute('aria-label')) svg.setAttribute('aria-hidden', 'true');
      (N[name] || fallback).forEach(([tag, attrs]) => {
        const child = document.createElementNS(ns, tag);
        Object.entries(attrs).forEach(([key,value]) => child.setAttribute(key, value));
        svg.appendChild(child);
      });
      node.replaceWith(svg);
    });
  }

  global.lucide = { createIcons, icons: Object.freeze({...N}) };
})(window);
