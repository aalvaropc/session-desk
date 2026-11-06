const paths = {
  pages: '<path d="M8 4h11v15H8z"/><path d="M5 7H3v15h11v-1M11 8h5M11 12h5"/>',
  sessions: '<path d="M4 4h16v12H9l-5 4z"/><path d="M8 8h8M8 12h5"/>',
  memory: '<path d="M5 4h14v17l-7-4-7 4zM9 8h6M9 11h6"/>',
  trash: '<path d="M4 7h16M9 7V4h6v3M6 7l1 14h10l1-14M10 10v7M14 10v7"/>',
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1 1M18 18l1 1M5 19l1-1M18 6l1-1"/>',
  moon: '<path d="M20 15A9 9 0 0 1 9 4a9 9 0 1 0 11 11z"/>',
  arrow: '<path d="m9 5 7 7-7 7"/>',
  back: '<path d="m10 5-7 7 7 7M3 12h18"/>',
  close: '<path d="m6 6 12 12M6 18 18 6"/>',
  copy: '<path d="M8 8h12v13H8zM16 8V3H3v13h5"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/>',
  folder: '<path d="M3 6h7l2 3h9v11H3zM3 6V4h6l2 2h8v3"/>',
  branch:
    '<circle cx="6" cy="5" r="2"/><circle cx="6" cy="19" r="2"/><circle cx="18" cy="5" r="2"/><path d="M6 7v10M18 7c0 6-12 3-12 9"/>',
  refresh:
    '<path d="M20 7v5h-5M4 17v-5h5M6 7a7 7 0 0 1 12-2l2 3M4 16l2 3a7 7 0 0 0 12-2"/>',
  sort: '<path d="M8 4v16m-4-4 4 4 4-4M16 4v16m-4-12 4-4 4 4"/>',
  terminal: '<path d="m5 7 5 5-5 5M13 17h6"/>',
  link: '<path d="m10 14 4-4M8 16l-2 2a4 4 0 0 1-6-6l5-5a4 4 0 0 1 6 0M16 8l2-2a4 4 0 0 1 6 6l-5 5a4 4 0 0 1-6 0" transform="translate(1 0) scale(.9)"/>',
  shield: '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6zM8 12l3 3 5-6"/>',
};
export type Icon = keyof typeof paths;
export const icon = (name: Icon): string =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name]}</svg>`;
