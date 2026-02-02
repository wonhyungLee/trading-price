import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Dev only: proxy API calls to the FastAPI server.
// Production: the built UI is copied into /opt/wonyodd-reco/frontend and served by FastAPI.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8010',
        changeOrigin: true,
      },
    },
  },
});
