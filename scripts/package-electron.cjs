// SPDX-License-Identifier: AGPL-3.0-or-later
// Assemble the Electron folder only; native installers remain in packaging/.
const fs = require("node:fs/promises");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
function windowsVersions(version, build) {
  const match = /^(\d+)\.(\d+)\.(\d+)(?:-[A-Za-z0-9.-]+)?$/.exec(version);
  if (!match || !/^\d+$/.test(String(build))) throw new Error("An explicit release version and build number are required.");
  const numbers = [...match.slice(1).map(Number), Number(build)];
  if (numbers.some(value => !Number.isSafeInteger(value) || value < 0 || value > 65535)) throw new Error("Windows version components must fit 0–65535.");
  return { product: numbers.slice(0, 3).join("."), file: numbers.join("."), display: version };
}
async function main() {
  const [source, output, version, build, icon, cache] = process.argv.slice(2);
  const entry = require.resolve("@electron/packager", { paths: [path.resolve(__dirname, "../desktop")] });
  const module = await import(pathToFileURL(entry).href);
  const packager = module.packager || module.default;
  const electronVersion = require("../desktop/node_modules/electron/package.json").version;
  const windows = windowsVersions(version, build);
  const options = { dir: source, out: output, name: process.platform === "win32" ? "Saiph" : "saiph",
    platform: process.platform, arch: "x64", electronVersion, appVersion: process.platform === "win32" ? windows.product : version, buildVersion: windows.file,
    icon, asar: false, prune: false, overwrite: false, executableName: process.platform === "win32" ? "Saiph" : "saiph",
    download: { cacheRoot: cache }, win32metadata: { CompanyName: "Saiph", FileDescription: "Saiph", ProductName: "Saiph", InternalName: "OrionMini" } };
  let result;
  for (let attempt = 0; attempt < 3; attempt++) {
    try { result = await packager(options); break; }
    catch (error) {
      if (attempt === 2 || !["EPERM", "EACCES", "EBUSY"].includes(error.code)) throw error;
      // Windows scanners can briefly hold a newly stamped executable. Preserve
      // outputs and retry through Packager; never delete a directory to force it.
      await new Promise(resolve => setTimeout(resolve, 1000 * (attempt + 1)));
    }
  }
  if (process.platform === "win32") {
    const entry = require.resolve("resedit", { paths: [path.dirname(require.resolve("@electron/packager", { paths: [path.resolve(__dirname, "../desktop")] }))] });
    const { NtExecutable, NtExecutableResource, Resource } = await import(pathToFileURL(entry).href);
    for (const directory of result) {
      const file = path.join(directory, "Saiph.exe");
      const executable = NtExecutable.from(await fs.readFile(file));
      const resources = NtExecutableResource.from(executable);
      const info = Resource.VersionInfo.fromEntries(resources.entries);
      if (info.length !== 1 || info[0].getAllLanguagesForStringValues().length !== 1) throw new Error("Unexpected application version resource.");
      info[0].setStringValues(info[0].getAllLanguagesForStringValues()[0], { FileVersion: windows.display, ProductVersion: windows.display });
      info[0].outputToResourceEntries(resources.entries);
      resources.outputResource(executable);
      await fs.writeFile(file, Buffer.from(executable.generate()));
    }
  }
  await fs.writeFile(path.join(output, "packager-result.json"), JSON.stringify({ directories: result, electronVersion }));
}
module.exports = { windowsVersions };
if (require.main === module) main().catch(error => { console.error(error.message); process.exitCode = 1; });
