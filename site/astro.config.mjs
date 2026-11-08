// @ts-check
import { defineConfig } from 'astro/config';
import tailwind from '@astrojs/tailwind';

// https://astro.build/config
export default defineConfig({
  site: 'https://julienld.github.io',
  base: '/ha-mcp-simple-release-qa-20261108',
  integrations: [tailwind()],
  output: 'static',
});
