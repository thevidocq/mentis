# Frontend

React + Vite + TypeScript. Served in production by the `web` container (nginx), which also proxies `/api` to the API.

## Layout

```
src/
  api/          fetch client (sends X-Mentis-Request on every call), shared types
  auth/         auth context, theme handling, role-based home
  components/   Icon (single SVG icon family), Logo, Modal, PasswordFields
  layouts/      AdminShell (left menu with logo, page header) and menu definitions
  pages/        Setup, Login, AcceptInvite, Account, ChatHome, Users, platform/*, tenant/*
  styles/       themes.css (Light, Medium, Dark as CSS variables), base.css
```

## Development

```bash
cd frontend
npm install
npm run dev      # http://127.0.0.1:5173, proxies /api to 127.0.0.1:8000
npm run build    # type-check + production build into dist/
```

Rules: one icon family (add icons to `components/Icon.tsx`), colors only through theme variables, no emoji as icons.
