# LexBot Frontend

## API configuration

Create `.env` from `.env.example` when the backend is not served through the
Vite dev proxy:

```env
VITE_API_BASE_URL=http://127.0.0.1:8000
```

The main Graph v2 chat flow calls:

```http
POST ${VITE_API_BASE_URL}/chat/legal
```

The request keeps the `case_id` returned by the backend so follow-up messages
continue the same legal case. The older `/chat/query` flow remains available
for RAG v1 screens and history compatibility.

For production, configure the backend CORS allowlist to include the deployed
frontend origin.

Production deployment needs these env vars:

Frontend (Vercel):

```env
VITE_API_BASE_URL=https://<lexbot-api-production-host>
```

Backend (FastAPI Cloud):

```env
CHATBOT_GRAPH_V2_URL=https://<graph-rag-agentic-service>.up.railway.app
CORS_ORIGINS=https://lex-bot-datn.vercel.app
```

The frontend should call the LexBot backend, not the BLHS Graph service
directly. LexBot backend exposes `/chat/legal` and proxies to
`${CHATBOT_GRAPH_V2_URL}/chat/legal`. The legal chat flow keeps `case_id`,
`case_version`, and renders `clarification.questions` when the AI backend asks
for structured follow-up facts.
## Development

```bash
npm install
npm run dev
npm run build
npm run lint
```

This template provides a minimal setup to get React working in Vite with HMR and some ESLint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Babel](https://babeljs.io/) (or [oxc](https://oxc.rs) when used in [rolldown-vite](https://vite.dev/guide/rolldown)) for Fast Refresh
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/) for Fast Refresh

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the ESLint configuration

If you are developing a production application, we recommend using TypeScript with type-aware lint rules enabled. Check out the [TS template](https://github.com/vitejs/vite/tree/main/packages/create-vite/template-react-ts) for information on how to integrate TypeScript and [`typescript-eslint`](https://typescript-eslint.io) in your project.
