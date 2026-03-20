const fs = require("fs");
const path = require("path");

const target = path.join(
  __dirname,
  "..",
  "node_modules",
  "@babel",
  "core",
  "lib",
  "transformation",
  "file",
  "babel-7-helpers.cts"
);

const source = path.join(path.dirname(target), "babel-7-helpers.cjs");

if (!fs.existsSync(source)) {
  process.exit(0);
}

if (!fs.existsSync(target)) {
  fs.writeFileSync(target, 'module.exports = require("./babel-7-helpers.cjs");\n', "utf-8");
  console.log("Created:", target);
}
