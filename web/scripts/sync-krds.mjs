// Copy the KRDS kit (krds-uiux) into public/krds and point its icon URLs at the local copy.
import { cpSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const kit = join(root, "node_modules", "krds-uiux", "resources");
const out = join(root, "public", "krds");
if (!existsSync(kit)) throw new Error("krds-uiux is not installed: run npm install");

mkdirSync(join(out, "css"), { recursive: true });
cpSync(join(kit, "fonts"), join(out, "fonts"), { recursive: true });
cpSync(join(kit, "img", "component", "icon"), join(out, "icon"), { recursive: true });
const css = readFileSync(join(kit, "cdn", "krds.min.css"), "utf8").replaceAll(
  "https://www.krds.go.kr/resources/img/component/icon/",
  "/krds/icon/",
);
writeFileSync(join(out, "css", "krds.min.css"), css);
console.log("KRDS assets synced to public/krds");
