# UI components

This Vite app already uses React and TypeScript. Its current design system is MUI, with application styles in `src/executive.css`. Reusable components live here in `src/components/ui`; keeping this convention makes shadcn-style component imports and future integrations predictable. This folder is a convention, not a React requirement.

`git-hub-calendar.tsx` adapts the supplied calendar with scoped `git-hub-calendar.css`. It requires `date-fns` (installed), no provider, icons, or image assets. The production caller supplies real employee data; sample data is deliberately excluded. `count` represents replied messages, and `received` supplies the denominator for completion colors.

Optional full Tailwind/shadcn setup, if the application later adopts that design system:

1. From `frontend`, install `tailwindcss` and `@tailwindcss/vite` as development dependencies.
2. Add the Tailwind Vite plugin alongside the existing React plugin in `vite.config.ts`.
3. Add a stylesheet containing `@import "tailwindcss";` and import it from the application entry. Review Tailwind's global reset against existing MUI styling.
4. Configure `@/*` to resolve to `src/*` in both TypeScript and Vite.
5. Run `npx shadcn@latest init`, selecting the existing stylesheet and `@/components/ui` alias. Review generated theme/reset changes before applying them across the app.

The integrated calendar does not require this optional migration.
