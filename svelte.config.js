import adapter from '@sveltejs/adapter-vercel';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
  preprocess: vitePreprocess(),
  kit: {
    adapter: adapter({
      runtime: 'nodejs20.x',
      // The wiki is read at runtime via `fs`. Bundle the whole `wiki/` dir into
      // the serverless function so it is available on Vercel.
      includeFiles: ['wiki/**', 'system_prompt.md']
    })
  }
};

export default config;
