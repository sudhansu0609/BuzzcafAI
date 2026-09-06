/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Absolute API origin. Leave unset to use relative URLs via the dev proxy. */
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
