#!/usr/bin/env node
// Builds the package the design-sync converter reads (cfg.buildCmd).
// frontend/ is a Next.js app with no dist/, so this compiles the synced surface
// from the app's own source into .design-sync/.cache/pkg/ (gitignored):
//   dist/index.js       .design-sync/entry.ts (risk vocabulary + hill card panel), esbuild ESM, react external
//   dist/types/*.d.ts   tsc declarations, "@/..." aliases rewritten to relative
//   dist/styles.css     .design-sync/tokens.css (the design addendum's tokens with the
//                       spec's hex values) compiled by Tailwind v4, plus a safelist so
//                       designs can use utilities the app hasn't yet
// Run from the repo root: node .design-sync/build-pkg.mjs
import { execFileSync } from 'node:child_process';
import { mkdirSync, readFileSync, readdirSync, rmSync, statSync, symlinkSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join, relative, resolve } from 'node:path';

const ROOT = resolve(dirname(new URL(import.meta.url).pathname), '..');
const FRONTEND = join(ROOT, 'frontend');
const OUT = join(ROOT, '.design-sync/.cache/pkg');
const ENTRY = join(ROOT, '.design-sync/entry.ts');
const require = createRequire(join(FRONTEND, 'package.json'));
const esbuild = createRequire(join(ROOT, '.ds-sync/package.json'))('esbuild');

rmSync(OUT, { recursive: true, force: true });
mkdirSync(join(OUT, 'dist/types'), { recursive: true });
writeFileSync(join(OUT, 'package.json'), JSON.stringify({
  name: 'terrasense-ui',
  version: JSON.parse(readFileSync(join(FRONTEND, 'package.json'), 'utf8')).version,
  module: 'dist/index.js',
  types: 'dist/types/index.d.ts',
}, null, 2) + '\n');
// The converter resolves @types/react from the package's own node_modules.
symlinkSync(join(FRONTEND, 'node_modules'), join(OUT, 'node_modules'));

// -- JS -------------------------------------------------------------------
await esbuild.build({
  entryPoints: [ENTRY],
  outfile: join(OUT, 'dist/index.js'),
  bundle: true,
  format: 'esm',
  jsx: 'automatic',
  external: ['react', 'react-dom', 'react/jsx-runtime'],
  alias: { '@': FRONTEND },
  logLevel: 'warning',
});

// -- .d.ts ------------------------------------------------------------------
const TYPES = join(OUT, 'dist/types');
writeFileSync(join(OUT, 'tsconfig.json'), JSON.stringify({
  compilerOptions: {
    declaration: true, emitDeclarationOnly: true, jsx: 'react-jsx', strict: true,
    moduleResolution: 'bundler', module: 'esnext', target: 'es2022', skipLibCheck: true,
    rootDir: ROOT, outDir: TYPES, baseUrl: FRONTEND, paths: { '@/*': ['./*'] },
    types: [], typeRoots: [join(FRONTEND, 'node_modules/@types')],
  },
  files: [ENTRY],
}));
execFileSync(join(FRONTEND, 'node_modules/.bin/tsc'), ['-p', join(OUT, 'tsconfig.json')], { stdio: 'inherit' });
rmSync(join(OUT, 'tsconfig.json'));
// tsc keeps "@/lib/x" specifiers; make them relative so ts-morph resolves them.
const walk = (d) => readdirSync(d).flatMap((f) => {
  const p = join(d, f);
  return statSync(p).isDirectory() ? walk(p) : [p];
});
for (const f of walk(TYPES).filter((p) => p.endsWith('.d.ts'))) {
  const src = readFileSync(f, 'utf8').replace(/(["'])@\/([^"']+)\1/g, (_, q, p) => {
    let rel = relative(dirname(f), join(TYPES, 'frontend', p));
    if (!rel.startsWith('.')) rel = './' + rel;
    return q + rel + q;
  });
  writeFileSync(f, src);
}
// The converter reads the types entry from the root of the types dir.
const entryDts = readFileSync(join(TYPES, '.design-sync/entry.d.ts'), 'utf8').replaceAll('"../frontend/', '"./frontend/');
writeFileSync(join(TYPES, 'index.d.ts'), entryDts);
rmSync(join(TYPES, '.design-sync'), { recursive: true });

// -- CSS --------------------------------------------------------------------
// Addendum token names (context/design-addendum.md, Tokens).
const COLORS = 'background,muted,card,popover,secondary,foreground,muted-foreground,primary,primary-foreground,ring,border,input,accent,destructive,risk-low,risk-moderate,risk-high,risk-extreme';
const RISK = 'risk-low,risk-moderate,risk-high,risk-extreme';
const SAFELIST = [
  `{bg,text,border,border-l,border-t,border-r,border-b,ring,outline,fill,stroke,divide,decoration}-{${COLORS}}`,
  // Addendum tints: the 8% High/Extreme treatment, 20% marker halo, 4% running row,
  // 40% status-line border, 70% unleveled trail text, 90% primary hover, 10% secondary hover.
  `bg-{${RISK}}/{8,20}`,
  'bg-foreground/4', 'border-foreground/40', 'text-foreground/70',
  '{hover:bg-primary/90,hover:bg-primary/10,hover:bg-accent,hover:text-foreground,hover:underline}',
  '{focus-visible:outline-2,focus-visible:outline-offset-2,focus-visible:outline-ring,focus-visible:outline-solid}',
  '{disabled:opacity-40,disabled:pointer-events-none,opacity-40,opacity-100}',
  // Layout and spacing.
  '{flex,inline-flex,grid,inline-grid,block,inline-block,inline,hidden,contents}',
  '{flex-row,flex-col,flex-wrap,flex-1,flex-none,grow,shrink-0,items-start,items-center,items-end,items-baseline,items-stretch,justify-start,justify-center,justify-end,justify-between,self-start,self-center,self-end}',
  '{gap,gap-x,gap-y,p,px,py,pt,pr,pb,pl,m,mx,my,mt,mr,mb,ml,space-y,space-x}-{0,0.5,1,1.5,2,2.5,3,4,5,6,7,8,10,12,16,20,24}',
  '{mx-auto,ml-auto,mr-auto,mt-auto}',
  '{grid-cols,col-span}-{1,2,3,4,6,12}',
  '{w,h,size,min-w,min-h,max-w}-{full,screen,fit,min,max,auto,px,0,1,2,3,4,5,6,7,8,10,12,16,20,24,32,40,48,64,80,96}',
  'max-w-{xs,sm,md,lg,xl,2xl,3xl,4xl,5xl,6xl,7xl,prose}',
  // Addendum sizes: search 360x40, hill card 55/45 columns, map 55dvh when stacked, marker 10/26 px, pin 28 px.
  '{w-[360px],md:w-[55%],md:w-[45%],h-[55dvh],h-dvh,md:h-dvh,size-[10px],size-[26px],size-[28px],size-[0.6em]}',
  // Addendum type roles (Type table). Standard steps plus the exact line heights and tracking.
  'text-{xs,sm,base,lg,xl,2xl,4xl}',
  '{text-base/5,text-base/6,text-sm/5,text-xl/7,text-2xl/7,text-4xl/10,text-lg/6,text-[21px]/[30px],text-[0.92em],tracking-[-0.01em],tracking-[-0.02em],tracking-tight,leading-snug,leading-relaxed}',
  'font-{sans,mono,normal,medium,semibold}',
  '{leading-none,tabular-nums,truncate,text-left,text-center,text-right,whitespace-nowrap,underline,underline-offset-2,underline-offset-4}',
  // Borders and shape. Radius: controls rounded-md (6 px), floating surfaces rounded-lg (8 px), side panel rounded-none.
  '{border,border-0,border-2,border-l,border-l-2,border-l-3,border-t,border-b,border-r,border-y,border-x,divide-y,divide-x}',
  '{rounded-none,rounded-md,rounded-lg,rounded-full}',
  '{relative,absolute,fixed,sticky,inset-0,top-0,right-0,bottom-0,left-0,z-0,z-10,z-20,z-50,overflow-hidden,overflow-auto,overflow-y-auto,pointer-events-none,cursor-pointer,select-none,sr-only}',
  // Addendum, Motion: the only animation class.
  '{animate-work,motion-reduce:animate-none}',
];
const tokens = readFileSync(join(ROOT, '.design-sync/tokens.css'), 'utf8');
const input = [
  // Addendum, Type: Space Grotesk 400/500/600 and JetBrains Mono 400/500.
  `@import url("https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap");`,
  tokens,
  // The exported components' own source. These use the addendum's role names, so they compile
  // to the right colors. The map and globe components stay out (not synced).
  ...['components/risk-badge.tsx', 'components/icons.tsx', 'components/panel/level.tsx', 'components/hill', 'components/pipeline']
    .map((p) => `@source "${join(FRONTEND, p)}";`),
  `@source "${join(ROOT, '.design-sync/previews')}";`,
  // Every class the conventions header names must compile.
  `@source "${join(ROOT, '.design-sync/conventions.md')}";`,
  ...SAFELIST.map((s) => `@source inline("${s}");`),
].join('\n');
const postcss = require('postcss');
const tailwind = require('@tailwindcss/postcss');
// `from` is only a resolution base so `@import "tailwindcss"` finds frontend/node_modules.
const out = await postcss([tailwind({ base: FRONTEND })]).process(input, { from: join(FRONTEND, 'app/ds-tokens.css') });
writeFileSync(join(OUT, 'dist/styles.css'), out.css);
console.error(`build-pkg: ${relative(ROOT, OUT)} (styles.css ${(out.css.length / 1024).toFixed(0)} KB)`);
