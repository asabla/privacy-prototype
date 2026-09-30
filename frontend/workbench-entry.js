import { mountWorkbench } from "./workbench.js";

mountWorkbench({ document, window, fetch: window.fetch.bind(window) });
